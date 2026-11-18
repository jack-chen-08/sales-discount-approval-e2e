"""分支④：驳回链路——报价单不可生成，驳回意见回填工作台，可重新发起。

覆盖客户验收条款：
  - 驳回后生成报价单 -> 409 + QUOTE_APPROVAL_REJECTED
  - 驳回意见写回工作台可见
  - 同一审批单不可二次决策
  - 驳回后可按新折扣重新发起审批（不锁死业务）
"""
from __future__ import annotations

from helpers import approve, make_quote, submit_approval, user

REJECT_COMMENT = "8.5 折低于本季度底价，请先谈押付方式再报"


def test_01_reject_requires_comment(client, seed):
    approval = submit_approval(client, seed, 0.85).json()
    r = approve(client, approval["id"], user(seed, "club"), comment="   ", path="reject")
    assert r.status_code == 400
    assert r.json()["code"] == "REJECT_COMMENT_REQUIRED"


def test_02_rejected_approval_blocks_quote(client, seed):
    approval = submit_approval(client, seed, 0.85).json()
    rj = approve(client, approval["id"], user(seed, "club"), comment=REJECT_COMMENT, path="reject")
    assert rj.status_code == 200, rj.text
    assert rj.json()["status"] == "rejected"

    r = make_quote(client, seed, 0.85, approval_id=approval["id"])
    assert r.status_code == 409, r.text
    err = r.json()
    assert err["code"] == "QUOTE_APPROVAL_REJECTED"
    assert err["context"]["decision_comment"] == REJECT_COMMENT


def test_03_reject_comment_visible_in_workbench(client, seed):
    approval = submit_approval(client, seed, 0.85).json()
    approve(client, approval["id"], user(seed, "club"), comment=REJECT_COMMENT, path="reject")

    page = client.get(
        "/workbench",
        params={"opportunity_id": seed["opportunities"]["primary"], "as_user": user(seed, "club")},
    )
    assert page.status_code == 200
    html = page.text
    assert REJECT_COMMENT in html
    assert 'data-testid="approval-row"' in html
    assert "rejected" in html

    api = client.get(
        "/api/sales/approvals", params={"opportunity_id": seed["opportunities"]["primary"]}
    ).json()
    assert api["items"][0]["decision_comment"] == REJECT_COMMENT


def test_04_decision_is_final(client, seed):
    approval = submit_approval(client, seed, 0.85).json()
    approve(client, approval["id"], user(seed, "club"), comment=REJECT_COMMENT, path="reject")
    again = approve(client, approval["id"], user(seed, "club"))
    assert again.status_code == 409
    assert again.json()["code"] == "APPROVAL_ALREADY_DECIDED"
    assert again.json()["context"]["status"] == "rejected"


def test_05_can_resubmit_after_rejection(client, seed):
    """驳回不是死锁：按 9 折重新发起，走运营主管审批后仍能出单。"""
    rejected = submit_approval(client, seed, 0.85).json()
    approve(client, rejected["id"], user(seed, "club"), comment=REJECT_COMMENT, path="reject")

    again = submit_approval(client, seed, 0.9).json()
    assert again["status"] == "pending"
    assert again["required_role"] == "ops_supervisor"
    assert approve(client, again["id"], user(seed, "ops")).status_code == 200

    r = make_quote(client, seed, 0.9, approval_id=again["id"])
    assert r.status_code == 201, r.text
