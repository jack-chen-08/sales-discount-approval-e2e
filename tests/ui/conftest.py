"""UI 用例夹具：拉起真实进程 + 真浏览器（默认连本机已开的 Edge/Chromium，避免额外下载）。

环境变量：
  UI_TEST_PORT  服务端口，默认 8199
  PW_CDP        Playwright CDP 地址，例如 http://127.0.0.1:19222（连本机已登录浏览器）
  不设 PW_CDP 时自动 playwright.chromium.launch()，装过浏览器即可跑
"""
from __future__ import annotations

import os
import pathlib
import socket
import subprocess
import sys
import time

import httpx
import pytest

from ui_config import (  # noqa: E402
    OPP_PRIMARY,
    OPP_SECONDARY,
    OPP_TERTIARY,
    REJECT_COMMENT,
    ROOT,
    SCREENSHOT_DIR,
    U_CLUB,
    U_CONSULTANT,
    U_OPS,
)

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# 固定端口会让「上一轮残留进程」冒充本轮服务，端口被占时用例会打到旧库上；
# 默认每次取一个空闲端口，需要固定端口时再用 UI_TEST_PORT 覆盖。
PORT = int(os.getenv("UI_TEST_PORT") or _free_port())


def _browser_host() -> str:
    """浏览器要访问的地址。

    浏览器可能跑在 Windows 侧（PW_CDP 连本机 Edge），而服务跑在 WSL 里，
    此时 127.0.0.1 在两边不是同一个栈，必须用 WSL 的对外 IP，并且服务监听 0.0.0.0。
    """
    if host := os.getenv("PW_BASE_HOST"):
        return host
    if os.getenv("PW_CDP"):
        try:
            ips = subprocess.check_output(["hostname", "-I"]).decode().split()
            return ips[0] if ips else "127.0.0.1"
        except Exception:
            return "127.0.0.1"
    return "127.0.0.1"


BROWSER_HOST = _browser_host()
BASE = f"http://{BROWSER_HOST}:{PORT}"
API_BASE = f"http://127.0.0.1:{PORT}"


@pytest.fixture(scope="session")
def live_server(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("uidb") / "ui.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite+pysqlite:///{db_path}"}
    log_file = open(db_path.with_suffix(".log"), "wb")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0",
         "--port", str(PORT), "--log-level", "warning"],
        cwd=str(ROOT), env=env, stdout=log_file, stderr=subprocess.STDOUT,
    )
    try:
        for _ in range(120):
            try:
                if httpx.get(f"{API_BASE}/healthz", timeout=0.5).status_code == 200:
                    break
            except Exception:
                time.sleep(0.25)
        else:
            raise RuntimeError("UI 测试服务未在 30s 内起来")
        yield BASE
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="session")
def ui_scenario(live_server):
    """把三个商机各自备一场：0.85 待审批 / 0.9 已批已出单 / 0.8 已驳回。"""
    c = httpx.Client(base_url=live_server.replace(BROWSER_HOST, "127.0.0.1"), timeout=10)

    def submit(opp_id, discount):
        r = c.post("/api/sales/approvals", json={
            "opportunity_id": opp_id, "discount": discount,
            "requested_by": U_CONSULTANT, "note": "UI 截图用虚构数据",
        })
        assert r.status_code == 201, r.text
        return r.json()["id"]

    pending_id = submit(OPP_PRIMARY, 0.85)

    approved_id = submit(OPP_SECONDARY, 0.9)
    assert c.post(f"/api/sales/approvals/{approved_id}/approve",
                  json={"operator_id": U_OPS, "comment": "同意"}).status_code == 200
    assert c.post("/api/sales/quotes", json={
        "opportunity_id": OPP_SECONDARY, "discount": 0.9, "approval_id": approved_id,
        "created_by": U_CONSULTANT, "amount_cents": 10_800_00,
    }).status_code == 201

    rejected_id = submit(OPP_TERTIARY, 0.8)
    assert c.post(f"/api/sales/approvals/{rejected_id}/reject",
                  json={"operator_id": U_CLUB, "comment": REJECT_COMMENT}).status_code == 200

    yield {"pending": pending_id, "approved": approved_id, "rejected": rejected_id}
    c.close()


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        cdp = os.getenv("PW_CDP")
        if cdp:
            b = pw.chromium.connect_over_cdp(cdp)
        else:
            try:
                b = pw.chromium.launch()
            except Exception as exc:  # pragma: no cover
                pytest.skip(f"无可用浏览器：{exc}；请 playwright install chromium 或设置 PW_CDP")
        yield b


@pytest.fixture()
def page(browser):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    yield pg
    ctx.close()


@pytest.fixture(scope="session", autouse=True)
def _shots_dir():
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return SCREENSHOT_DIR
