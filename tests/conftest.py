"""pytest 公共夹具：每个用例一套独立内存库，互不污染。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(autouse=True)
def _wecom_test_secret(monkeypatch):
    """企业微信签名密钥只从环境变量读取（生产无缺省值）；用例里注入一个公开的测试值。"""
    monkeypatch.setenv("WECOM_STUB_SECRET", "local-test-only-not-a-real-secret")


@pytest.fixture()
def app():
    return create_app(database_url="sqlite+pysqlite:///:memory:", with_seed=True)


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def seed(app) -> dict:
    return app.state.seed
