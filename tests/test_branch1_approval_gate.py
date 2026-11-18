"""分支①：9 折报价必须先审批；审批前生成报价单必须 409。

覆盖客户验收条款：
  - 审批前调生成报价单 -> 409 + QUOTE_APPROVAL_REQUIRED
  - 运营主管在工作台审批通过 -> 可生成报价单
  - 另走一次企业微信卡片审批回调 -> 同样可生成报价单
  - 审批记录进入合同附件
"""
from __future__ import annotations

from helpers import (
    approve,
    attachments,
    make_quote,
    submit_approval,
    user,
    wecom_approve,
)


def test_01_submit_9_discount_approval_routes_to_ops_supervisor(client, seed):
    r = submit_approval(client, seed, 0.9)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["required_role"] == "ops_supervisor"
    assert body["discount_bp"] == 9000


def test_02_quote_blocked_before_approval(client, seed):
    approval = submit_approval(client, seed, 0.9).json()

    r = make_quote(client, seed, 0.9, approval_id=approval["id"])
    assert r.status_code == 409, r.text
    err = r.json()
    assert err["code"] == "QUOTE_APPROVAL_REQUIRED"
    assert err["context"]["reason"] == "approval_pending"
    assert err["context"]["required_role"] == "ops_supervisor"


def test_03_quote_blocked_without_any_approval_id(client, seed):
    r = make_quote(client, seed, 0.9, approval_id=None)
    assert r.status_code == 409
    assert r.json()["code"] == "QUOTE_APPROVAL_REQUIRED"
    assert r.json()["context"]["reason"] == "no_approval_id"


def test_04_ops_supervisor_approves_then_quote_issued(client, seed):
    approval = submit_approval(client, seed, 0.9).json()
    ok = approve(client, approval["id"], user(seed, "ops"))
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "approved"

    r = make_quote(client, seed, 0.9, approval_id=approval["id"])
    assert r.status_code == 201, r.text
    assert r.json()["discount_bp"] == 9000
    assert r.json()["approval_id"] == approval["id"]


def test_05_approval_record_enters_contract_attachments(client, seed):
    approval = submit_approval(client, seed, 0.9).json()
    approve(client, approval["id"], user(seed, "ops"))
    make_quote(client, seed, 0.9, approval_id=approval["id"])

    items = attachments(client, seed)
    assert len(items) == 1
    assert items[0]["approval_id"] == approval["id"]
    assert items[0]["kind"] == "discount_approval"
    assert items[0]["file_ref"] == f"approvals/{approval['id']}.pdf"


def test_06_wecom_card_callback_is_an_equivalent_approval_path(client, seed):
    """另走一次企业微信卡片审批回调：签名校验通过即等同工作台审批。"""
    approval = submit_approval(client, seed, 0.9, key="secondary").json()

    bad = client.post(
        "/api/integrations/wecom/approval-callback",
        json={
            "approval_id": approval["id"],
            "action": "approve",
            "operator_id": user(seed, "ops"),
            "comment": "",
            "signature": "forged",
        },
    )
    assert bad.status_code == 401
    assert bad.json()["code"] == "WECOM_SIGNATURE_INVALID"

    ok = wecom_approve(client, approval["id"], user(seed, "ops"))
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "approved"
    assert ok.json()["channel"] == "wecom_card"

    r = make_quote(client, seed, 0.9, approval_id=approval["id"], key="secondary")
    assert r.status_code == 201, r.text


def test_07_api_v1_alias_behaves_identically(client, seed):
    """集成方统一走 /api/v1，判据必须与 /api 完全一致。"""
    approval = submit_approval(client, seed, 0.9).json()
    r = client.post(
        "/api/v1/sales/quotes",
        json={
            "opportunity_id": seed["opportunities"]["primary"],
            "discount": 0.9,
            "created_by": user(seed, "consultant"),
            "amount_cents": 19_800_00,
            "approval_id": approval["id"],
        },
    )
    assert r.status_code == 409
    assert r.json()["code"] == "QUOTE_APPROVAL_REQUIRED"
