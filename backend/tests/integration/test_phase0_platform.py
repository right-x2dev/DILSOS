from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect

from app.db.base import UTCDateTime
from app.db.session import get_engine


def test_live(client):
    r = client.get("/api/v1/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert r.headers.get("X-Request-ID")


def test_ready_reports_database(client):
    r = client.get("/api/v1/health/ready")
    body = r.json()
    assert r.status_code == 200, body
    assert body["status"] == "ready"
    assert {c["name"] for c in body["checks"]} == {"database"}  # eager backend => no redis check


def test_migrations_created_tables():
    tables = set(inspect(get_engine()).get_table_names())
    assert {"users", "audit_logs", "alembic_version"} <= tables


def test_login_success_and_me(client, auth_headers):
    r = client.get("/api/v1/auth/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["is_demo"] is True


def test_login_wrong_password_typed_error(client):
    r = client.post("/api/v1/auth/login", json={"email": "demo@dilsos.local", "password": "nope"})
    assert r.status_code == 401
    err = r.json()["error"]
    assert err["code"] == "invalid_credentials"
    assert err["request_id"]


def test_me_requires_token(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_invalid_payload_is_422_with_details(client):
    r = client.post("/api/v1/auth/login", json={"email": "x"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert r.json()["error"]["details"]


def test_password_is_hashed(db):
    from sqlalchemy import select

    from app.db.models import User

    u = db.scalar(select(User).where(User.email == "demo@dilsos.local"))
    assert u is not None and u.password_hash.startswith("$argon2")


def test_utc_type_rejects_naive_and_normalises():
    t = UTCDateTime()
    with pytest.raises(ValueError):
        t.process_bind_param(datetime(2026, 1, 1, 9, 0), None)
    kst = timezone(timedelta(hours=9))
    stored = t.process_bind_param(datetime(2026, 1, 1, 9, 0, tzinfo=kst), None)
    assert stored == datetime(2026, 1, 1, 0, 0)
    assert t.process_result_value(stored, None).tzinfo is not None


def test_log_redaction():
    from app.core.logging import redact

    assert "abc.def" not in redact("Authorization: Bearer abc.def")
    assert "hunter2" not in redact('password="hunter2"')
