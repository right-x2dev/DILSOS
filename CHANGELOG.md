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

## [0.2.0] — 2026-10-14 — Phase 1: warehouse vertical slice
### Added
- Optimization core: typed contracts, deterministic preprocessing (inventory allocation, explicit unserved reasons), resource timelines, serial SGS, FIFO/EDD/SPT dispatch, CP-SAT warehouse model, shared evaluator, independent validator, algorithm registry & runner.
- Full domain schema (migration 0002), immutable outputs guard, scenario snapshots (versioned, hashed), definition ⇄ DB round trip.
- Synthetic generator + demo scenarios `normal_day`, `peak_demand`, `vehicle_breakdown`, `warehouse_bottleneck`; seed CLI.
- Run lifecycle (202 enqueue, atomic claim, cancel, timeout cap, publish-only-if-valid), DB-polling worker, Celery task.
- REST API for scenarios, orders, resources, runs, schedule/validation/metrics/compare, algorithms, dashboard, audit logs.
- UI: dashboard KPIs & cost decomposition, scenario builder/editor/clone/validate, orders & resources, optimization console with live polling & cancel, SVG warehouse Gantt, run details & audit.
- Tests: unit, solver, property-based (hypothesis), API integration, queue/persistence; Vitest UI tests.

## [0.3.0] — 2026-10-14 — Phase 2: packing & dock scheduling
### Added
- `common/routes.py`: route plans, deterministic time propagation, hard-violation detection & stop-dropping repair, LOAD tasks.
- Dock dispatch (FIFO readiness / EDD slack) and CP-SAT dock model with exact downstream timing; `dock` problem pipeline (warehouse rule → readiness → baseline grouping → dock appointment → timed routes).
- Dock & vehicle timeline UI with integrity warnings; `scripts/run_via_api.py`.

## [0.4.0] — 2026-10-14 — Phase 3: vehicle routing
### Added
- Routing units & simulator; time-oriented nearest neighbour; cheapest insertion; OR-Tools VRPTW (capacity, time, soft/hard windows, disjunctions, readiness, GLS, warm start).
- `routing` problem pipeline with hard-repair finalisation; validator R8 readiness for routing-only scope.
- Routes UI: schematic SVG map, optional OpenStreetMap view with synthetic-data labelling and tile-error fallback, per-vehicle stop tables.
### Changed
- Synthetic display anchor moved inland (Seoul area) so derived lat/lon points do not fall into the sea.

## [0.5.0] — 2026-10-14 — Phase 4: integrated coordination
### Added
- `integrated_sequential` (one-pass) and `integrated_iterative` (cutoff feedback coordination) with shared sub-solvers and full validation of every candidate.
- Integrated journey timeline UI (release → pick → pack → dock wait → load → transit → service, lateness and heuristic main-cause attribution).
### Changed
- Inventory allocation order is now (priority, release, id) so tightening due dates never changes backorders.

## [0.6.0] — 2026-10-14 — Phase 5: metaheuristics & experiments
### Added
- Warehouse simulated annealing, tabu search and genetic algorithm over order permutations (feasible by construction, validator-checked incumbents).
- Routing ALNS with adaptive operator weights; available standalone and inside integrated coordination.
- Benchmark harness `app.experiments.benchmark` + generated quick-suite results in `docs/experiments/`.
- `POST /scenarios/{id}/experiments` (algorithms × seeds on one snapshot) and the comparison dashboard (stats, charts, CSV).

## [0.7.0] — 2026-10-14 — Phase 6: dynamic events & rescheduling
### Added
- Disruption event engine (7 event types), freeze/neighbourhood logic, KEEP/PARTIAL/FULL rescheduling algorithms, rolling-horizon driver, rule-based policy recommendation.
- Snapshot fields for task model, events applied, KEEP freeze sets → rescheduled runs are reproducible from the stored snapshot alone.
- Validator: frozen-route identity (F1), no re-planned loading/departure in the past, cancelled-on-loaded-route as warning.
- API: `POST/GET /scenarios/{id}/events` (Idempotency-Key), `POST /runs/{id}/reschedule`, `GET /runs/{id}/reschedules`.
- Disruption simulator UI with before/after comparison.
### Fixed
- Policy recommendation was dominated by runtime ratios (3 ms vs 300 ms); now min-max normalised per criterion.
- Run pickers showed the first option while nothing was selected.

## [1.0.0] — 2026-10-14 — Phase 7: polish, evaluation, deployment
### Added
- CSV order import (validated, all-or-nothing) and CSV/JSON run export, with UI.
- Rate limiting, Prometheus-style ops metrics, nginx block for internal metrics.
- Playwright E2E smoke and screenshot capture against the real stack; CI runs E2E inside the compose job.
- Documentation set: architecture & sequence diagrams, ERD, formulations, algorithm catalogue, operations, API examples,
  OpenAPI export, case study, demo script; synthetic dataset exports and CSV example; demo population script.
### Removed
- Unused placeholder screen and empty `app/simulation` package.
