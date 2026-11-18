"""业务服务层：折扣审批、报价单生成的唯一执行路径。

页面与接口共用这里，越权与绕过的判定只有一份实现（避免 UI 与 API 判据分叉）。
所有拒绝都返回「HTTP 状态码 + 业务错误码」成对结果，供用例断言。
"""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditEvent, ContractAttachment, DiscountApproval, Opportunity, Quote, User
from .policy import (
    MIN_DISCOUNT_BP,
    FULL_PRICE_BP,
    ApiError,
    ErrorCode,
    required_role,
)
from .schemas import ApprovalCreate, QuoteCreate


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _audit(session: Session, *, org_id: str, site_id: str, entity: str, entity_id: str,
           action: str, actor_id: str, detail: str = "") -> None:
    session.add(
        AuditEvent(
            org_id=org_id, site_id=site_id, created_by=actor_id, entity=entity,
            entity_id=entity_id, action=action, actor_id=actor_id, detail=detail, at=_now(),
        )
    )


def _get_opportunity(session: Session, opportunity_id: str, org_id: str) -> Opportunity:
    opp = session.get(Opportunity, opportunity_id)
    if opp is None or opp.deleted_at is not None:
        raise ApiError(404, "OPPORTUNITY_NOT_FOUND", "商机不存在或不属于当前组织")
    if opp.org_id != org_id:
        raise ApiError(403, ErrorCode.ORG_ISOLATION_VIOLATION, "跨组织访问被拒绝")
    return opp


def _check_discount(bp: int) -> None:
    if not (MIN_DISCOUNT_BP <= bp <= FULL_PRICE_BP):
        raise ApiError(
            400,
            ErrorCode.DISCOUNT_OUT_OF_RANGE,
            "折扣超出允许区间（5 折 ~ 原价）",
            min_discount_bp=MIN_DISCOUNT_BP,
            max_discount_bp=FULL_PRICE_BP,
            got_bp=bp,
        )


def _get_user(session: Session, user_id: str) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise ApiError(404, "USER_NOT_FOUND", "操作人不存在")
    return user


def create_approval(session: Session, payload: ApprovalCreate) -> DiscountApproval:
    """提交折扣审批。同一商机上折扣一变，之前的审批立即失效（回到待审批）。"""
    requester = _get_user(session, payload.requested_by)
    opp = _get_opportunity(session, payload.opportunity_id, requester.org_id)
    bp = payload.discount_bp
    _check_discount(bp)

    role = required_role(bp)
    if role is None:
        raise ApiError(400, "NO_APPROVAL_NEEDED", "原价报价无需审批，可直接生成报价单")

    # 折扣变更 -> 同商机上旧审批（未驳回的）全部作废，必须重新审批
    stale = session.scalars(
        select(DiscountApproval).where(
            DiscountApproval.opportunity_id == opp.id,
            DiscountApproval.discount_bp != bp,
            DiscountApproval.status.in_(("pending", "approved")),
        )
    ).all()
    for old in stale:
        old.status = "superseded"
        old.invalidated_reason = "discount_changed"
        old.updated_at = _now()

    approval = DiscountApproval(
        org_id=opp.org_id,
        site_id=opp.site_id,
        created_by=requester.id,
        opportunity_id=opp.id,
        discount_bp=bp,
        status="pending",
        required_role=role,
        requested_by=requester.id,
        note=payload.note,
    )
    session.add(approval)
    session.flush()
    _audit(session, org_id=opp.org_id, site_id=opp.site_id, entity="approval",
           entity_id=approval.id, action="submitted", actor_id=requester.id,
           detail=f"discount_bp={bp} required_role={role} superseded={len(stale)}")
    session.commit()
    return approval


def decide_approval(session: Session, approval_id: str, operator_id: str, action: str,
                    comment: str = "", channel: str = "workbench") -> DiscountApproval:
    """审批通过 / 驳回。角色不匹配直接 403，与页面是否显示按钮无关。"""
    operator = _get_user(session, operator_id)
    approval = session.get(DiscountApproval, approval_id)
    if approval is None:
        raise ApiError(404, ErrorCode.APPROVAL_NOT_FOUND, "审批单不存在")
    if approval.org_id != operator.org_id:
        raise ApiError(403, ErrorCode.ORG_ISOLATION_VIOLATION, "跨组织审批被拒绝")
    if approval.status != "pending":
        raise ApiError(
            409,
            ErrorCode.APPROVAL_ALREADY_DECIDED,
            "该审批单已结束，不能重复处理",
            status=approval.status,
        )
    if operator.role != approval.required_role:
        # 关键拦截：0.85 折时运营主管即便猜到接口也过不去
        raise ApiError(
            403,
            ErrorCode.APPROVAL_FORBIDDEN_ROLE,
            "当前角色无权审批该折扣",
            required_role=approval.required_role,
            actual_role=operator.role,
            discount_bp=approval.discount_bp,
        )

    approval.decided_by = operator.id
    approval.decided_at = _now()
    approval.decision_comment = comment
    approval.channel = channel
    approval.updated_at = _now()

    if action == "approve":
        approval.status = "approved"
        session.add(
            ContractAttachment(
                org_id=approval.org_id,
                site_id=approval.site_id,
                created_by=operator.id,
                opportunity_id=approval.opportunity_id,
                approval_id=approval.id,
                kind="discount_approval",
                title=f"折扣审批单 · {approval.discount_bp / 1000:.2f} 折 · {operator.name}",
                file_ref=f"approvals/{approval.id}.pdf",
            )
        )
        _audit(session, org_id=approval.org_id, site_id=approval.site_id, entity="approval",
               entity_id=approval.id, action="approved", actor_id=operator.id,
               detail=f"channel={channel} discount_bp={approval.discount_bp}")
    elif action == "reject":
        if not comment.strip():
            # 驳回必须带意见，否则工作台上谁也看不懂为什么被驳回
            raise ApiError(400, "REJECT_COMMENT_REQUIRED", "驳回必须填写审批意见")
        approval.status = "rejected"
        _audit(session, org_id=approval.org_id, site_id=approval.site_id, entity="approval",
               entity_id=approval.id, action="rejected", actor_id=operator.id,
               detail=f"comment={comment} discount_bp={approval.discount_bp}")
    else:
        raise ApiError(400, "DECISION_INVALID", "action 只能是 approve 或 reject")

    session.commit()
    return approval


def create_quote(session: Session, payload: QuoteCreate) -> Quote:
    """生成报价单。这里是所有绕过路径的收口处。

    判定顺序（先粗后细，错误码对应用例断言）：
      1. 商机归属
      2. 折扣区间
      3. 原价免审批
      4. 无审批号 -> QUOTE_APPROVAL_REQUIRED
      5. 审批号不存在（伪造）-> APPROVAL_NOT_FOUND
      6. 审批号属于别的商机 -> APPROVAL_SCOPE_MISMATCH
      7. 审批号已被用掉 -> APPROVAL_ALREADY_CONSUMED
      8. 审批被驳回 -> QUOTE_APPROVAL_REJECTED
      9. 审批被折扣变更作废 -> QUOTE_APPROVAL_REQUIRED(reason=approval_superseded)
     10. 审批仍待批 -> QUOTE_APPROVAL_REQUIRED(reason=approval_pending)
     11. 审批折扣与本次折扣不一致 -> QUOTE_APPROVAL_REQUIRED(reason=discount_changed_after_approval)
    """
    creator = _get_user(session, payload.created_by)
    opp = _get_opportunity(session, payload.opportunity_id, creator.org_id)
    bp = payload.discount_bp
    _check_discount(bp)

    needed_role = required_role(bp)
    approval: DiscountApproval | None = None

    if needed_role is not None:
        if not payload.approval_id:
            raise ApiError(
                409,
                ErrorCode.QUOTE_APPROVAL_REQUIRED,
                "该折扣必须先完成审批才能生成报价单",
                required_role=needed_role,
                discount_bp=bp,
                reason="no_approval_id",
            )

        approval = session.get(DiscountApproval, payload.approval_id)
        if approval is None or approval.org_id != opp.org_id:
            raise ApiError(
                409,
                ErrorCode.APPROVAL_NOT_FOUND,
                "审批单不存在，无法核销（伪造的 approval_id）",
                approval_id=payload.approval_id,
            )
        if approval.opportunity_id != opp.id:
            raise ApiError(
                409,
                ErrorCode.APPROVAL_SCOPE_MISMATCH,
                "该审批单属于另一个商机，不能挪用到本单",
                approval_opportunity_id=approval.opportunity_id,
                request_opportunity_id=opp.id,
            )
        if approval.consumed_by_quote_id:
            raise ApiError(
                409,
                ErrorCode.APPROVAL_ALREADY_CONSUMED,
                "该审批单已经生成过报价单，不可重复使用",
                consumed_by_quote_id=approval.consumed_by_quote_id,
            )
        if approval.status == "rejected":
            raise ApiError(
                409,
                ErrorCode.QUOTE_APPROVAL_REJECTED,
                "审批已被驳回，报价单不可生成",
                decision_comment=approval.decision_comment,
            )
        if approval.status == "superseded":
            raise ApiError(
                409,
                ErrorCode.QUOTE_APPROVAL_REQUIRED,
                "折扣已变更，原审批失效，需重新审批",
                reason="approval_superseded",
                required_role=needed_role,
                invalidated_reason=approval.invalidated_reason,
            )
        if approval.status != "approved":
            raise ApiError(
                409,
                ErrorCode.QUOTE_APPROVAL_REQUIRED,
                "审批尚未通过，报价单不可生成",
                reason="approval_pending",
                required_role=needed_role,
                status=approval.status,
            )
        if approval.discount_bp != bp:
            raise ApiError(
                409,
                ErrorCode.QUOTE_APPROVAL_REQUIRED,
                "本次折扣与审批折扣不一致，原审批对本折扣无效，需重新审批",
                reason="discount_changed_after_approval",
                required_role=needed_role,
                approved_discount_bp=approval.discount_bp,
                request_discount_bp=bp,
            )

    quote = Quote(
        org_id=opp.org_id,
        site_id=opp.site_id,
        created_by=creator.id,
        opportunity_id=opp.id,
        approval_id=approval.id if approval else None,
        discount_bp=bp,
        amount_cents=payload.amount_cents,
        status="issued",
    )
    session.add(quote)
    session.flush()
    if approval is not None:
        approval.consumed_by_quote_id = quote.id
    _audit(session, org_id=opp.org_id, site_id=opp.site_id, entity="quote",
           entity_id=quote.id, action="issued", actor_id=creator.id,
           detail=f"discount_bp={bp} approval_id={approval.id if approval else None}")
    session.commit()
    return quote


def list_attachments(session: Session, opportunity_id: str, org_id: str) -> list[ContractAttachment]:
    _get_opportunity(session, opportunity_id, org_id)
    return list(
        session.scalars(
            select(ContractAttachment)
            .where(ContractAttachment.opportunity_id == opportunity_id,
                   ContractAttachment.deleted_at.is_(None))
            .order_by(ContractAttachment.created_at)
        ).all()
    )


def list_approvals(session: Session, opportunity_id: str) -> list[DiscountApproval]:
    return list(
        session.scalars(
            select(DiscountApproval)
            .where(DiscountApproval.opportunity_id == opportunity_id)
            .order_by(DiscountApproval.created_at)
        ).all()
    )


def list_quotes(session: Session, opportunity_id: str) -> list[Quote]:
    return list(
        session.scalars(
            select(Quote)
            .where(Quote.opportunity_id == opportunity_id, Quote.deleted_at.is_(None))
            .order_by(Quote.created_at)
        ).all()
    )


# ---------------------------------------------------------------- 企业微信卡片审批回调
# 签名密钥只允许从环境变量读取，**不设任何缺省值**（fail-closed）：
# 未配置 WECOM_STUB_SECRET 时，签名校验直接失败，回调一律拒绝，避免用公开已知的桩串伪造审批。
def wecom_secret() -> str:
    secret = os.getenv("WECOM_STUB_SECRET")
    if not secret:
        raise ApiError(
            500,
            ErrorCode.WECOM_SIGNATURE_INVALID,
            "企业微信签名密钥未配置：只允许从环境变量 WECOM_STUB_SECRET 读取（本地用例由 tests/conftest.py 注入测试值）",
        )
    return secret


def wecom_signature(approval_id: str, action: str, operator_id: str) -> str:
    msg = f"{approval_id}:{action}:{operator_id}".encode()
    return hmac.new(wecom_secret().encode(), msg, hashlib.sha256).hexdigest()


def handle_wecom_callback(session: Session, approval_id: str, action: str, operator_id: str,
                          comment: str, signature: str) -> DiscountApproval:
    """企业微信审批卡片回调（接口桩）。

    真实接入点：企微「审批」应用回调 URL + 卡片按钮 action。
    这里校验 HMAC 签名后走与工作台完全相同的 decide_approval，
    保证「卡片点通过」与「工作台点通过」不能有两条判据。
    """
    expected = wecom_signature(approval_id, action, operator_id)
    if not hmac.compare_digest(expected, signature or ""):
        raise ApiError(401, ErrorCode.WECOM_SIGNATURE_INVALID, "回调签名校验失败")
    return decide_approval(session, approval_id, operator_id, action, comment, channel="wecom_card")
