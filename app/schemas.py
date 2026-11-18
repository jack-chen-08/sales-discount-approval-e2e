"""接口出入参模型（Pydantic v2）。

折扣对外仍以小数形式（0.9 / 0.85）暴露，落库前统一换算成万分位整数，
换算集中在本文件，避免各路由各写一遍四舍五入。
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, Field, field_validator

from .policy import FULL_PRICE_BP


def to_bp(value: float | int | str | Decimal) -> int:
    """0.85 -> 8500。用 Decimal 承接，避免 0.1+0.2 类的浮点误差写进库。"""
    d = Decimal(str(value))
    return int((d * FULL_PRICE_BP).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class DiscountMixin(BaseModel):
    discount: float = Field(..., description="折扣，0.85 表示 8.5 折")

    @field_validator("discount")
    @classmethod
    def _check(cls, v: float) -> float:
        if not (0 < v <= 1.0):
            raise ValueError("discount 必须落在 (0, 1] 区间，0.85 表示 8.5 折")
        return v

    @property
    def discount_bp(self) -> int:
        return to_bp(self.discount)


class ApprovalCreate(DiscountMixin):
    opportunity_id: str
    requested_by: str
    note: str = ""


class DecisionRequest(BaseModel):
    operator_id: str
    comment: str = ""


class QuoteCreate(DiscountMixin):
    opportunity_id: str
    created_by: str
    amount_cents: int = Field(..., ge=0, description="报价总额，单位：分")
    approval_id: str | None = None


class WecomCallback(BaseModel):
    approval_id: str
    action: str = Field(..., pattern="^(approve|reject)$")
    operator_id: str
    comment: str = ""
    signature: str
