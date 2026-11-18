"""UI 用例：工作台按角色渲染审批入口 + 驳回意见回填 + 合同附件可见。

只读断言为主（不点按钮改状态），保证用例可乱序执行、可重复执行。
按钮的提交路径由 tests/test_workbench_form.py 覆盖。
"""
from __future__ import annotations

from ui_config import (
    OPP_PRIMARY,
    OPP_SECONDARY,
    OPP_TERTIARY,
    REJECT_COMMENT,
    SCREENSHOT_DIR,
    U_CLUB,
    U_OPS,
)


def _open(page, base, opp_id, as_user):
    page.goto(f"{base}/workbench?opportunity_id={opp_id}&as_user={as_user}")
    page.wait_for_selector('[data-testid="opportunity"]')


def test_01_ops_supervisor_has_no_button_on_85(page, live_server, ui_scenario):
    """8.5 折单在运营主管视角下没有审批入口（越权入口在页面层就不该出现）。"""
    _open(page, live_server, OPP_PRIMARY, U_OPS)
    row = page.locator(f'[data-testid="approval-row"]').first
    assert row.get_attribute("data-discount") == "8.50 折"
    assert row.get_attribute("data-status") == "pending"
    assert page.locator('[data-testid^="no-approve-"]').first.is_visible()
    assert page.locator('[data-testid^="approve-btn-"]').count() == 0
    page.screenshot(path=str(SCREENSHOT_DIR / "01_ops_supervisor_085_no_approve_button.png"), full_page=True)


def test_02_club_manager_sees_approve_button_on_85(page, live_server, ui_scenario):
    _open(page, live_server, OPP_PRIMARY, U_CLUB)
    assert page.locator('[data-testid^="approve-btn-"]').first.is_visible()
    assert page.locator('[data-testid^="reject-btn-"]').first.is_visible()
    assert page.locator('[data-testid^="no-approve-"]').count() == 0
    page.screenshot(path=str(SCREENSHOT_DIR / "02_club_manager_085_approve_button.png"), full_page=True)


def test_03_rejection_comment_is_shown_in_workbench(page, live_server, ui_scenario):
    _open(page, live_server, OPP_TERTIARY, U_CLUB)
    row = page.locator('[data-testid="approval-row"]').first
    assert row.get_attribute("data-status") == "rejected"
    comment = page.locator('[data-testid^="rejection-comment-"]').first
    assert comment.is_visible()
    assert REJECT_COMMENT in comment.inner_text()
    assert page.locator('[data-testid^="approve-btn-"]').count() == 0
    page.screenshot(path=str(SCREENSHOT_DIR / "03_rejection_comment_in_workbench.png"), full_page=True)


def test_04_contract_attachment_listed_for_approved_quote(page, live_server, ui_scenario):
    _open(page, live_server, OPP_SECONDARY, U_OPS)
    item = page.locator('[data-testid="attachment-item"]').first
    assert item.is_visible()
    text = item.inner_text()
    assert "9.00 折" in text
    assert "运营主管·周敏" in text
    assert page.locator('[data-testid="quote-item"]').count() == 1
    page.screenshot(path=str(SCREENSHOT_DIR / "04_contract_attachment_and_quote.png"), full_page=True)
