"""Test fixtures.

Each test session gets a fresh SQLite file migrated with Alembic (so migrations are exercised).
Set TEST_MYSQL_URL to run the same suite against MySQL 8 instead.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

_tmpdir = tempfile.mkdtemp(prefix="dilsos_test_")
_DB_URL = os.environ.get("TEST_MYSQL_URL") or f"sqlite:///{Path(_tmpdir) / 'test.db'}"
os.environ["DATABASE_URL"] = _DB_URL
os.environ["APP_ENV"] = "test"
os.environ["TASK_BACKEND"] = "eager"
os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef0123456789")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.session import get_engine, get_sessionmaker  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _alembic_cfg() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "app" / "db" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", _DB_URL)
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _migrated_db() -> Iterator[None]:
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    cfg = _alembic_cfg()
    if os.environ.get("TEST_MYSQL_URL"):
        command.downgrade(cfg, "base")  # start clean on a shared MySQL test schema
    command.upgrade(cfg, "head")
    from app.seed.cli import ensure_demo_user

    with get_sessionmaker()() as db:
        ensure_demo_user(db)
        db.commit()
    yield
    get_engine().dispose()


@pytest.fixture
def db() -> Iterator[Session]:
    with get_sessionmaker()() as s:
        yield s


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(scope="session")
def auth_headers(client: TestClient) -> dict[str, str]:
    s = get_settings()
    r = client.post("/api/v1/auth/login", json={"email": s.demo_user_email, "password": s.demo_user_password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
