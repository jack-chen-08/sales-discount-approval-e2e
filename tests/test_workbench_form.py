"""工作台表单提交路径：页面点按钮与直接调接口必须经过同一套判据。

验收条款「直接调审批接口 -> 403」在这里被反向覆盖：从页面按钮提交，
越权同样只能在 403 上被拦，并且工作台要把错误回显出来（不是静默失败）。
"""
from __future__ import annotations

from helpers import submit_approval, user


def _post_form(client, approval_id, operator_id, action="approve", comment=""):
    return client.post(
        "/workbench/decision",
        data={
            "approval_id": approval_id,
            "action": action,
            "operator_id": operator_id,
            "comment": comment,
            "opportunity_id": "",
        },
        follow_redirects=False,
    )


def test_club_manager_button_approves(client, seed):
    approval = submit_approval(client, seed, 0.85).json()
    r = _post_form(client, approval["id"], user(seed, "club"), comment="同意 8.5 折")
    assert r.status_code == 303
    assert "error=" not in r.headers["location"]

    page = client.get("/workbench", params={"opportunity_id": seed["opportunities"]["primary"],
                                            "as_user": user(seed, "club")})
    assert 'data-status="approved"' in page.text


def test_ops_supervisor_button_attempt_is_blocked_with_visible_error(client, seed):
    approval = submit_approval(client, seed, 0.85).json()
    r = _post_form(client, approval["id"], user(seed, "ops"))
    assert r.status_code == 303
    assert "403+APPROVAL_FORBIDDEN_ROLE" in r.headers["location"]

    page = client.get("/workbench", params={"opportunity_id": seed["opportunities"]["primary"],
                                            "as_user": user(seed, "ops"),
                                            "error": "403 APPROVAL_FORBIDDEN_ROLE"})
    assert "APPROVAL_FORBIDDEN_ROLE" in page.text
    assert 'data-status="pending"' in page.text


def test_reject_without_comment_is_blocked_in_ui(client, seed):
    approval = submit_approval(client, seed, 0.85).json()
    r = _post_form(client, approval["id"], user(seed, "club"), action="reject", comment="")
    assert "400+REJECT_COMMENT_REQUIRED" in r.headers["location"]
