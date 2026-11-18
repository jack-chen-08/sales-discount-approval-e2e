"""折扣审批路由策略与错误码。

本模块把「谁能审批」的口径收敛到一处，接口层与页面层共用同一个判据，
避免出现「页面上看不到按钮、接口却能过」的分叉（越权审批的典型成因）。
"""
from __future__ import annotations

OPS_SUPERVISOR = "ops_supervisor"   # 运营主管
CLUB_MANAGER = "club_manager"       # 会所负责人
CONSULTANT = "consultant"           # 招商顾问

#: 折扣以「万分位整数」存储：9000 = 9 折，8500 = 8.5 折。
FULL_PRICE_BP = 10_000
MIN_DISCOUNT_BP = 5_000        # 低于 5 折不收单，避免脏数据
APPROVAL_THRESHOLD_BP = 9_000  # 9 折为分界点


def required_role(discount_bp: int) -> str | None:
    """返回该折扣所需的审批角色；None 表示无需审批（原价）。

    口径（客户验收条款第 3 条）：
      - 9 折及以上（>= 9000）：运营主管
      - 低于 9 折（< 9000）：会所负责人，运营主管无权审批
    """
    if discount_bp >= FULL_PRICE_BP:
        return None
    if discount_bp >= APPROVAL_THRESHOLD_BP:
        return OPS_SUPERVISOR
    return CLUB_MANAGER


class ErrorCode:
    """对外错误码。测试断言直接对齐这些常量，不依赖中文提示文案。"""

    DISCOUNT_OUT_OF_RANGE = "DISCOUNT_OUT_OF_RANGE"
    QUOTE_APPROVAL_REQUIRED = "QUOTE_APPROVAL_REQUIRED"
    APPROVAL_NOT_FOUND = "APPROVAL_NOT_FOUND"
    APPROVAL_SCOPE_MISMATCH = "APPROVAL_SCOPE_MISMATCH"
    APPROVAL_ALREADY_CONSUMED = "APPROVAL_ALREADY_CONSUMED"
    APPROVAL_ALREADY_DECIDED = "APPROVAL_ALREADY_DECIDED"
    APPROVAL_FORBIDDEN_ROLE = "APPROVAL_FORBIDDEN_ROLE"
    QUOTE_APPROVAL_REJECTED = "QUOTE_APPROVAL_REJECTED"
    ORG_ISOLATION_VIOLATION = "ORG_ISOLATION_VIOLATION"
    WECOM_SIGNATURE_INVALID = "WECOM_SIGNATURE_INVALID"


class ApiError(Exception):
    """业务错误：HTTP 状态码与错误码成对返回。"""

    def __init__(self, status_code: int, code: str, message: str, **context):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.context = context

    def to_payload(self) -> dict:
        payload = {"code": self.code, "message": self.message}
        if self.context:
            payload["context"] = self.context
        return payload
