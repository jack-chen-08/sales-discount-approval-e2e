"""基础约束：原价免审批、折扣区间、组织隔离、v1 别名一致性。"""
from __future__ import annotations

from helpers import make_quote, submit_approval, user


def test_full_price_quote_needs_no_approval(client, seed):
    r = make_quote(client, seed, 1.0, approval_id=None)
    assert r.status_code == 201, r.text
    assert r.json()["approval_id"] is None
    assert r.json()["discount_bp"] == 10000


def test_discount_out_of_range_rejected(client, seed):
    r = submit_approval(client, seed, 0.3)
    assert r.status_code == 400
    assert r.json()["code"] == "DISCOUNT_OUT_OF_RANGE"


def test_approval_request_at_full_price_is_meaningless(client, seed):
    r = submit_approval(client, seed, 1.0)
    assert r.status_code == 400
    assert r.json()["code"] == "NO_APPROVAL_NEEDED"


def test_cross_org_access_blocked(client, seed):
    approval = submit_approval(client, seed, 0.9).json()
    r = client.post(
        f"/api/sales/approvals/{approval['id']}/approve",
        json={"operator_id": "ffffffff-ffff-4fff-8fff-ffffffffffff", "comment": ""},
    )
    assert r.status_code == 404
    assert r.json()["code"] == "USER_NOT_FOUND"


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_roles_are_seeded_for_ui(client, seed):
    users = client.get("/api/users").json()["items"]
    roles = {u["role"] for u in users}
    assert roles == {"consultant", "ops_supervisor", "club_manager"}
    assert user(seed, "club") in {u["id"] for u in users}
