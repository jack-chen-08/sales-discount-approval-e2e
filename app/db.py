"""数据库会话与建表。

DATABASE_URL 只从环境变量读取（客户约定：配置与密钥不进代码）。
默认落一个本地 SQLite 文件，便于在本机一键复跑；生产切 PostgreSQL 16 只需改环境变量。
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base

DEFAULT_URL = "sqlite+pysqlite:///./sales_demo.db"


def make_engine(url: str | None = None, *, in_memory: bool = False):
    url = url or os.getenv("DATABASE_URL", DEFAULT_URL)
    kwargs: dict = {"future": True}
    if in_memory or url == "sqlite+pysqlite:///:memory:":
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
    return create_engine(url, **kwargs)


def init_db(engine) -> None:
    Base.metadata.create_all(engine)


def make_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
