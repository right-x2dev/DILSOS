# Changelog

All notable changes per phase. Dates are UTC.

## [0.1.0] — 2026-10-14 — Phase 0: bootstrap
### Added
- Repository layout (backend / frontend / datasets / docs / scripts), `.env.example`, `.gitignore`.
- FastAPI app factory with request-ID middleware, JSON structured logging with token/password redaction, typed error envelope.
- `/api/v1/health/live`, `/api/v1/health/ready` (DB + Redis when Celery backend), `/api/v1/auth/login`, `/api/v1/auth/me` (Argon2id + JWT).
- SQLAlchemy 2 base, `UTCDateTime` type, `users` / `audit_logs` models, Alembic migration `0001`.
- Seed CLI (`python -m app.seed.cli demo-user`), DB wait script, container entrypoint.
- React + TS + Vite shell: login, sidebar navigation (Korean labels), demo banner, API health badge, explicitly-labelled “준비 중” placeholders.
- Dockerfiles (api/worker, nginx frontend reverse proxy), `docker-compose.yml`, `docker-compose.prod.yml`, GitHub Actions CI (ruff, mypy, pytest on SQLite + MySQL, vitest, build, compose smoke).
- `scripts/mysql_init.sql`, `scripts/smoke_test.py`.
