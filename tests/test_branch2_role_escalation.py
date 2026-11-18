"""分支②：低于 9 折只有会所负责人能批，运营主管越权必须 403。

覆盖客户验收条款：
  - 0.85 折提交后，运营主管审批 -> 403
  - 会所负责人审批 -> 通过，报价单可生成
  - 会所负责人的审批记录进入合同附件
"""
from __future__ import annotations

import pytest

from helpers import approve, attachments, make_quote, submit_approval, user


@pytest.mark.parametrize("discount,bp,role", [
    (0.90, 9000, "ops_supervisor"),
    (0.89, 8900, "club_manager"),
    (0.85, 8500, "club_manager"),
    (0.80, 8000, "club_manager"),
])
def test_01_discount_routing_matrix(client, seed, discount, bp, role):
    r = submit_approval(client, seed, discount)
    assert r.status_code == 201, r.text
    assert r.json()["discount_bp"] == bp
    assert r.json()["required_role"] == role


def test_02_ops_supervisor_cannot_approve_85(client, seed):
    approval = submit_approval(client, seed, 0.85).json()
    assert approval["required_role"] == "club_manager"

    r = approve(client, approval["id"], user(seed, "ops"))
    assert r.status_code == 403, r.text
    err = r.json()
    assert err["code"] == "APPROVAL_FORBIDDEN_ROLE"
    assert err["context"]["required_role"] == "club_manager"
    assert err["context"]["actual_role"] == "ops_supervisor"

    # 驳回同样越权，不能靠「驳回」绕过
    assert approve(client, approval["id"], user(seed, "ops"), path="reject").status_code == 403


def test_03_quote_still_blocked_after_ops_attempt(client, seed):
    """越权尝试失败后，审批单仍是 pending，报价单仍不可生成。"""
    approval = submit_approval(client, seed, 0.85).json()
    approve(client, approval["id"], user(seed, "ops"))

    r = make_quote(client, seed, 0.85, approval_id=approval["id"])
    assert r.status_code == 409
    assert r.json()["code"] == "QUOTE_APPROVAL_REQUIRED"
    assert r.json()["context"]["reason"] == "approval_pending"


def test_04_club_manager_approves_and_quote_issued(client, seed):
    approval = submit_approval(client, seed, 0.85).json()
    ok = approve(client, approval["id"], user(seed, "club"), comment="客户体量大，同意 8.5 折")
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "approved"
    assert ok.json()["decided_by"] == user(seed, "club")

    r = make_quote(client, seed, 0.85, approval_id=approval["id"])
    assert r.status_code == 201, r.text
    assert r.json()["discount_bp"] == 8500


def test_05_club_manager_record_in_contract_attachments(client, seed):
    approval = submit_approval(client, seed, 0.85).json()
    approve(client, approval["id"], user(seed, "club"), comment="同意")
    make_quote(client, seed, 0.85, approval_id=approval["id"])

    items = attachments(client, seed)
    assert len(items) == 1
    assert items[0]["approval_id"] == approval["id"]
    assert "8.50 折" in items[0]["title"]
    assert "会所负责人·余青" in items[0]["title"]
