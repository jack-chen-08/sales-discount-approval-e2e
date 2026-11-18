"""pytest 公共夹具：每个用例一套独立内存库，互不污染。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


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
