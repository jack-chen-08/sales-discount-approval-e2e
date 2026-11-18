"""分支③：绕过审批的四种尝试必须全部被拦，且状态码 + 错误码可区分。

覆盖客户验收条款：
  - 拿别的报价/商机的审批号来用 -> 409
  - 审批通过后把折扣改低再生成 -> 409，原审批失效需重新审批
  - 伪造（不存在的）approval_id -> 409
  - 审批号重放（同一审批生成第二张报价单）-> 409
"""
from __future__ import annotations

import uuid

from helpers import approve, make_quote, submit_approval, user


def test_01_discount_lowered_after_approval_is_rejected(client, seed):
    approval = submit_approval(client, seed, 0.9).json()
    assert approve(client, approval["id"], user(seed, "ops")).status_code == 200

    r = make_quote(client, seed, 0.85, approval_id=approval["id"])
    assert r.status_code == 409, r.text
    err = r.json()
    assert err["code"] == "QUOTE_APPROVAL_REQUIRED"
    assert err["context"]["reason"] == "discount_changed_after_approval"
    assert err["context"]["approved_discount_bp"] == 9000
    assert err["context"]["request_discount_bp"] == 8500


def test_02_new_discount_supersedes_old_approval(client, seed):
    """客户把 0.85 改成 0.8：旧审批立即作废，必须拿 0.8 重新审批。"""
    old = submit_approval(client, seed, 0.85).json()
    assert approve(client, old["id"], user(seed, "club")).status_code == 200

    new = submit_approval(client, seed, 0.8).json()
    assert new["status"] == "pending"

    r = make_quote(client, seed, 0.85, approval_id=old["id"])
    assert r.status_code == 409
    assert r.json()["code"] == "QUOTE_APPROVAL_REQUIRED"
    assert r.json()["context"]["reason"] == "approval_superseded"

    # 旧审批在工作台状态为 superseded，不可再被当作有效依据
    listing = client.get("/api/sales/approvals", params={"opportunity_id": seed["opportunities"]["primary"]}).json()
    by_id = {a["id"]: a for a in listing["items"]}
    assert by_id[old["id"]]["status"] == "superseded"
    assert by_id[old["id"]]["invalidated_reason"] == "discount_changed"


def test_03_approval_from_another_opportunity_is_rejected(client, seed):
    other = submit_approval(client, seed, 0.85, key="secondary").json()
    assert approve(client, other["id"], user(seed, "club")).status_code == 200

    r = make_quote(client, seed, 0.85, approval_id=other["id"], key="primary")
    assert r.status_code == 409, r.text
    err = r.json()
    assert err["code"] == "APPROVAL_SCOPE_MISMATCH"
    assert err["context"]["approval_opportunity_id"] == seed["opportunities"]["secondary"]
    assert err["context"]["request_opportunity_id"] == seed["opportunities"]["primary"]


def test_04_forged_approval_id_is_rejected(client, seed):
    r = make_quote(client, seed, 0.85, approval_id=str(uuid.uuid4()))
    assert r.status_code == 409, r.text
    err = r.json()
    assert err["code"] == "APPROVAL_NOT_FOUND"
    assert err["context"]["approval_id"]


def test_05_approval_cannot_be_replayed(client, seed):
    approval = submit_approval(client, seed, 0.9).json()
    assert approve(client, approval["id"], user(seed, "ops")).status_code == 200
    assert make_quote(client, seed, 0.9, approval_id=approval["id"]).status_code == 201

    replay = make_quote(client, seed, 0.9, approval_id=approval["id"])
    assert replay.status_code == 409, replay.text
    assert replay.json()["code"] == "APPROVAL_ALREADY_CONSUMED"


def test_06_bypass_probe_on_v1_alias_also_blocked(client, seed):
    """绕过探针在 /api/v1 别名上同样必须被拦，避免只堵一个前缀。"""
    approval = submit_approval(client, seed, 0.9).json()
    approve(client, approval["id"], user(seed, "ops"))
    r = client.post(
        "/api/v1/sales/quotes",
        json={
            "opportunity_id": seed["opportunities"]["primary"],
            "discount": 0.8,
            "created_by": user(seed, "consultant"),
            "amount_cents": 19_800_00,
            "approval_id": approval["id"],
        },
    )
    assert r.status_code == 409
    assert r.json()["code"] == "QUOTE_APPROVAL_REQUIRED"
    assert r.json()["context"]["reason"] == "discount_changed_after_approval"
