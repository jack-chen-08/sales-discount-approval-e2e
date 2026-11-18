"""用例辅助函数：把常用动作收敛，用例正文只留断言。"""
from __future__ import annotations

from app.service import wecom_signature


def opp(seed: dict, key: str = "primary") -> str:
    return seed["opportunities"][key]


def user(seed: dict, key: str = "consultant") -> str:
    return seed["users"][key]


def submit_approval(client, seed: dict, discount: float, key: str = "primary",
                   requester: str = "consultant"):
    return client.post(
        "/api/sales/approvals",
        json={
            "opportunity_id": opp(seed, key),
            "discount": discount,
            "requested_by": user(seed, requester),
            "note": "用例数据，虚构商机",
        },
    )


def approve(client, approval_id: str, operator: str, comment: str = "", path: str = "approve"):
    return client.post(
        f"/api/sales/approvals/{approval_id}/{path}",
        json={"operator_id": operator, "comment": comment},
    )


def make_quote(client, seed: dict, discount: float, approval_id: str | None,
               key: str = "primary"):
    body = {
        "opportunity_id": opp(seed, key),
        "discount": discount,
        "created_by": user(seed, "consultant"),
        "amount_cents": 19_800_00,
    }
    if approval_id is not None:
        body["approval_id"] = approval_id
    return client.post("/api/sales/quotes", json=body)


def attachments(client, seed: dict, key: str = "primary"):
    r = client.get(
        f"/api/sales/opportunities/{opp(seed, key)}/contract-attachments",
        params={"org_id": seed["org_id"]},
    )
    assert r.status_code == 200, r.text
    return r.json()["items"]


def wecom_approve(client, approval_id: str, operator: str, action: str = "approve",
                  comment: str = ""):
    return client.post(
        "/api/integrations/wecom/approval-callback",
        json={
            "approval_id": approval_id,
            "action": action,
            "operator_id": operator,
            "comment": comment,
            "signature": wecom_signature(approval_id, action, operator),
        },
    )
