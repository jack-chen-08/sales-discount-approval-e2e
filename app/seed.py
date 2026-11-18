"""确定性测试数据（全部为虚构数据，不含任何真实企业或个人）。

客户要求「只用虚构的测试数据」：这里的公司名、人名、金额都是编的，
且固定 UUID 便于用例断言与截图复现。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import Opportunity, User
from .policy import CLUB_MANAGER, CONSULTANT, OPS_SUPERVISOR

ORG_ID = "11111111-1111-4111-8111-111111111111"
SITE_ID = "22222222-2222-4222-8222-222222222222"

USERS = {
    "consultant": ("33333333-3333-4333-8333-333333333331", "顾问·林舟", CONSULTANT),
    "ops": ("33333333-3333-4333-8333-333333333332", "运营主管·周敏", OPS_SUPERVISOR),
    "club": ("33333333-3333-4333-8333-333333333333", "会所负责人·余青", CLUB_MANAGER),
}

OPPORTUNITIES = {
    "primary": ("44444444-4444-4444-8444-444444444441", "示例企业甲 · A 栋 3 层 860㎡ 招商", "negotiating", 23_500_00),
    "secondary": ("44444444-4444-4444-8444-444444444442", "示例企业乙 · B 栋 1 层 420㎡ 招商", "negotiating", 12_000_00),
    "tertiary": ("44444444-4444-4444-8444-444444444443", "示例企业丙 · C 栋 2 层 310㎡ 招商", "negotiating", 9_800_00),
}


def seed(session: Session) -> dict:
    """写入固定测试数据，返回这些主键，供用例与 UI 直接引用。"""
    for _, (uid, name, role) in USERS.items():
        session.merge(
            User(id=uid, org_id=ORG_ID, site_id=SITE_ID, created_by=uid, name=name, role=role)
        )
    for _, (oid, name, stage, rent) in OPPORTUNITIES.items():
        session.merge(
            Opportunity(
                id=oid,
                org_id=ORG_ID,
                site_id=SITE_ID,
                created_by=USERS["consultant"][0],
                name=name,
                stage=stage,
                owner_id=USERS["consultant"][0],
                expected_monthly_rent_cents=rent,
            )
        )
    session.commit()
    return {
        "org_id": ORG_ID,
        "site_id": SITE_ID,
        "users": {k: v[0] for k, v in USERS.items()},
        "user_roles": {v[0]: v[2] for v in USERS.values()},
        "opportunities": {k: v[0] for k, v in OPPORTUNITIES.items()},
    }
