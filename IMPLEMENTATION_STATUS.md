# Implementation Status

Statuses: `TODO` · `IN_PROGRESS` · `IMPLEMENTED` (code exists, not fully verified) · `TESTED` (automated tests pass, evidence linked) · `BLOCKED`.

_Last updated: 2026-10-14 — end of Phase 0._

## Phase 0 — Bootstrap

| Item | Status | Evidence |
|---|---|---|
| Repo layout, env template, gitignore | TESTED | tree in README; `.env.example` |
| FastAPI app, request IDs, JSON logs, redaction | TESTED | `backend/tests/integration/test_phase0_platform.py` (`test_live`, `test_log_redaction`) |
| Health live/ready | TESTED | same file; manual `GET /health/ready` → `{"status":"ready","database_dialect":"sqlite"}` |
| JWT login + Argon2 hashing + demo user seed | TESTED | `test_login_success_and_me`, `test_password_is_hashed` |
| Alembic migration 0001 | TESTED | `test_migrations_created_tables` (fresh DB per session) |
| UTC datetime type | TESTED | `test_utc_type_rejects_naive_and_normalises` |
| Frontend shell, login, health badge | TESTED | `frontend/src/tests/shell.test.tsx` (3 tests); manual browser login on Vite dev server |
| Dockerfiles + compose (dev/prod) | IMPLEMENTED | Not run locally (no Docker on dev machine); verified by CI job `compose-smoke` once pushed |
| CI workflow | IMPLEMENTED | `.github/workflows/ci.yml` — result pending first push |
| Local MySQL | BLOCKED (owner action) | Run `scripts/mysql_init.sql` as root; until then local runtime uses SQLite. CI tests on MySQL 8.4 |
