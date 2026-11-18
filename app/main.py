"""FastAPI 应用装配：接口 + 工作台页面。

同一路由同时挂在 /api 与 /api/v1 下：客户工单原文用 POST /api/sales/quotes，
集成方又统一走 /api/v1，两种写法都在用例覆盖范围内。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from . import service
from .db import init_db, make_engine, make_session_factory
from .models import DiscountApproval, Opportunity, User
from .policy import ApiError, required_role
from .schemas import ApprovalCreate, DecisionRequest, QuoteCreate, WecomCallback
from .seed import seed as seed_data

BASE_DIR = Path(__file__).resolve().parent


def _bp_to_display(bp: int) -> str:
    # 万分位 -> 折：8500 -> 8.50 折
    return f"{bp / 1000:.2f} 折"


def _approval_row(a: DiscountApproval) -> dict:
    return {
        "id": a.id,
        "short_id": a.id[:8],
        "discount": _bp_to_display(a.discount_bp),
        "discount_bp": a.discount_bp,
        "status": a.status,
        "required_role": a.required_role,
        "note": a.note,
        "decision_comment": a.decision_comment,
        "decided_by": a.decided_by,
        "invalidated_reason": a.invalidated_reason,
        "channel": a.channel,
    }


def create_app(*, database_url: str | None = None, with_seed: bool = True) -> FastAPI:
    engine = make_engine(database_url, in_memory=(database_url or "").endswith(":memory:"))
    init_db(engine)
    SessionLocal = make_session_factory(engine)

    app = FastAPI(title="会员空间平台 · 折扣审批与报价闭环（S4-E2E-035 参考实现）")
    app.state.engine = engine
    app.state.SessionLocal = SessionLocal

    with SessionLocal() as session:
        app.state.seed = seed_data(session) if with_seed else {}

    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

    @app.exception_handler(ApiError)
    async def _api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    # ------------------------------------------------------------------ 接口路由
    api = APIRouter()

    @api.get("/users")
    def list_users() -> dict:
        with SessionLocal() as s:
            rows = s.scalars(select(User).order_by(User.name)).all()
            return {"items": [{"id": u.id, "name": u.name, "role": u.role} for u in rows]}

    @api.get("/sales/opportunities/{opportunity_id}")
    def get_opportunity(opportunity_id: str) -> dict:
        with SessionLocal() as s:
            opp = s.get(Opportunity, opportunity_id)
            if opp is None:
                raise ApiError(404, "OPPORTUNITY_NOT_FOUND", "商机不存在")
            return {
                "id": opp.id,
                "name": opp.name,
                "stage": opp.stage,
                "expected_monthly_rent_cents": opp.expected_monthly_rent_cents,
            }

    @api.post("/sales/approvals", status_code=201)
    def submit_approval(payload: ApprovalCreate) -> dict:
        with SessionLocal() as s:
            a = service.create_approval(s, payload)
            return _approval_row(a)

    @api.get("/sales/approvals")
    def get_approvals(opportunity_id: str) -> dict:
        with SessionLocal() as s:
            return {"items": [_approval_row(a) for a in service.list_approvals(s, opportunity_id)]}

    @api.post("/sales/approvals/{approval_id}/approve")
    def approve(approval_id: str, payload: DecisionRequest) -> dict:
        with SessionLocal() as s:
            a = service.decide_approval(s, approval_id, payload.operator_id, "approve", payload.comment)
            return _approval_row(a)

    @api.post("/sales/approvals/{approval_id}/reject")
    def reject(approval_id: str, payload: DecisionRequest) -> dict:
        with SessionLocal() as s:
            a = service.decide_approval(s, approval_id, payload.operator_id, "reject", payload.comment)
            return _approval_row(a)

    @api.post("/sales/quotes", status_code=201)
    def create_quote(payload: QuoteCreate) -> dict:
        with SessionLocal() as s:
            q = service.create_quote(s, payload)
            return {
                "id": q.id,
                "opportunity_id": q.opportunity_id,
                "approval_id": q.approval_id,
                "discount": _bp_to_display(q.discount_bp),
                "discount_bp": q.discount_bp,
                "amount_cents": q.amount_cents,
                "status": q.status,
            }

    @api.get("/sales/quotes")
    def get_quotes(opportunity_id: str) -> dict:
        with SessionLocal() as s:
            return {
                "items": [
                    {
                        "id": q.id,
                        "discount_bp": q.discount_bp,
                        "amount_cents": q.amount_cents,
                        "approval_id": q.approval_id,
                    }
                    for q in service.list_quotes(s, opportunity_id)
                ]
            }

    @api.get("/sales/opportunities/{opportunity_id}/contract-attachments")
    def contract_attachments(opportunity_id: str, org_id: str) -> dict:
        with SessionLocal() as s:
            rows = service.list_attachments(s, opportunity_id, org_id)
            return {
                "items": [
                    {"id": r.id, "approval_id": r.approval_id, "kind": r.kind,
                     "title": r.title, "file_ref": r.file_ref}
                    for r in rows
                ]
            }

    @api.post("/integrations/wecom/approval-callback")
    def wecom_callback(payload: WecomCallback) -> dict:
        with SessionLocal() as s:
            a = service.handle_wecom_callback(
                s, payload.approval_id, payload.action, payload.operator_id,
                payload.comment, payload.signature,
            )
            return _approval_row(a)

    app.include_router(api, prefix="/api")
    app.include_router(api, prefix="/api/v1")

    # ------------------------------------------------------------------ 工作台页面
    @app.get("/workbench", response_class=HTMLResponse)
    def workbench(request: Request, opportunity_id: str | None = None, as_user: str | None = None):
        with SessionLocal() as s:
            users = s.scalars(select(User).order_by(User.name)).all()
            opp_id = opportunity_id or app.state.seed["opportunities"]["primary"]
            opp = s.get(Opportunity, opp_id)
            current = s.get(User, as_user) if as_user else users[0]
            approvals = service.list_approvals(s, opp_id) if opp else []
            attachments = service.list_attachments(s, opp_id, opp.org_id) if opp else []
            quotes = service.list_quotes(s, opp_id) if opp else []

            rows = []
            for a in approvals:
                row = _approval_row(a)
                row["can_approve"] = (a.status == "pending" and current and current.role == a.required_role)
                rows.append(row)

            ctx = {
                "request": request,
                "users": users,
                "current": current,
                "opportunity": opp,
                "approvals": rows,
                "attachments": attachments,
                "quotes": quotes,
                "required_role_for_90": required_role(9000),
                "required_role_for_85": required_role(8500),
            }
        return templates.TemplateResponse(request, "workbench.html", ctx)

    @app.post("/workbench/decision")
    def workbench_decision(
        approval_id: str = Form(...),
        action: str = Form(...),
        operator_id: str = Form(...),
        comment: str = Form(""),
        opportunity_id: str = Form(""),
    ):
        """页面按钮走这里：失败也整页回显错误码，方便手工复现时截图留证。"""
        with SessionLocal() as s:
            try:
                service.decide_approval(s, approval_id, operator_id, action, comment)
                err = ""
            except ApiError as exc:
                err = f"{exc.status_code} {exc.code}"
        target = f"/workbench?opportunity_id={opportunity_id}&as_user={operator_id}"
        if err:
            target += f"&error={err.replace(' ', '+')}"
        return RedirectResponse(target, status_code=303)

    return app


app = create_app()
