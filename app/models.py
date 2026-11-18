"""ORM 模型（SQLAlchemy 2.0 声明式）。

遵循客户《统一技术约定》：
  - 业务表统一含 id(UUID) / org_id / site_id / created_at / created_by / updated_at / deleted_at
  - 金额一律以「分」存整数；折扣以「万分位整数」存（9000 = 9 折），不出现浮点
  - 生产库为 PostgreSQL 16，本参考实现用 SQLite 落地同一套 DDL（便于用例离线复跑）
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class BusinessColumns:
    """业务表统一列（软删除、审计字段）。"""

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    site_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class User(BusinessColumns, Base):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    #: consultant / ops_supervisor / club_manager
    role: Mapped[str] = mapped_column(String(32), nullable=False)


class Opportunity(BusinessColumns, Base):
    """招商商机（前置数据由 S2-CRM 提供，本单用接口桩造数）。"""

    __tablename__ = "opportunities"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), default="negotiating", nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    expected_monthly_rent_cents: Mapped[int] = mapped_column(Integer, nullable=False)


class DiscountApproval(BusinessColumns, Base):
    """折扣审批单。一条审批只对一个商机 + 一个折扣生效，用过即消费。"""

    __tablename__ = "discount_approvals"

    opportunity_id: Mapped[str] = mapped_column(String(36), ForeignKey("opportunities.id"), index=True)
    discount_bp: Mapped[int] = mapped_column(Integer, nullable=False)
    #: pending / approved / rejected / superseded
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    required_role: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(36), nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: 折扣变更导致失效时写入原因，供页面与用例展示
    invalidated_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 已生成报价单则回填，防止同一审批被复用
    consumed_by_quote_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    #: 审批来源：workbench / wecom_card
    channel: Mapped[str] = mapped_column(String(16), default="workbench", nullable=False)


class Quote(BusinessColumns, Base):
    __tablename__ = "quotes"

    opportunity_id: Mapped[str] = mapped_column(String(36), ForeignKey("opportunities.id"), index=True)
    approval_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    discount_bp: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="issued", nullable=False)


class ContractAttachment(BusinessColumns, Base):
    """合同附件清单。审批通过后落一条附件记录，指向审批单。"""

    __tablename__ = "contract_attachments"

    opportunity_id: Mapped[str] = mapped_column(String(36), ForeignKey("opportunities.id"), index=True)
    approval_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="discount_approval", nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    file_ref: Mapped[str] = mapped_column(String(128), nullable=False)


class AuditEvent(BusinessColumns, Base):
    """审批与报价的关键动作留痕（谁、何时、什么动作、结果）。"""

    __tablename__ = "audit_events"

    entity: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
