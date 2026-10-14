# Architecture Decision Records (ADR)

Short ADRs; newest at the bottom. Status: Accepted unless stated.

## ADR-001 — Integer minutes relative to a scenario anchor
All optimization inputs/outputs use **integer minutes** offset from `Scenario.horizon_start` (a timezone-aware UTC instant). Distances are **integer meters**. Conversion to wall-clock happens only at the API/UI boundary (`horizon_start + minutes`). This keeps CP-SAT / OR-Tools models integral and makes the validator exact (no float tolerance).

## ADR-002 — Pluggable run queue: `celery` | `db` | `eager`
Spec requires Redis + Celery and forbids in-memory globals as queues. The dev machine has no Docker/Redis, so `TASK_BACKEND` selects:
- `celery` (Docker Compose default): Celery + Redis transport run IDs; state lives in MySQL.
- `db`: a persistent DB-polling worker (`python -m app.tasks.db_worker`) claims `QUEUED` rows with an atomic conditional `UPDATE … WHERE status='QUEUED'` (works on MySQL and SQLite).
- `eager`: synchronous execution for tests.
All three call the same `execute_run(run_id)`; the HTTP handler never runs a solver.

## ADR-003 — SQLite for local tests, MySQL 8 for runtime/CI
The suite migrates a fresh SQLite DB through Alembic per session; CI re-runs integration tests on a MySQL 8.4 service container (`TEST_MYSQL_URL`). A `UTCDateTime` type stores naive UTC (MySQL `DATETIME`) and **rejects naive datetimes** on write.

## ADR-004 — Python 3.12 in containers, 3.14 locally
Spec says 3.12+. Docker/CI pin 3.12 (broadest wheel availability); local dev used CPython 3.14 (OR-Tools 9.15 wheels available).

## ADR-005 — Frontend: React 18 + Tailwind 3 + in-repo primitives
React 18.3 for compatibility with react-leaflet 4 / Recharts 2. Instead of the shadcn CLI, a small set of accessible primitives lives in `src/components/ui.tsx` (same Tailwind approach, no extra generator step). Gantt/timeline/journey charts are custom SVG so every pixel derives from API data.

## ADR-006 — Windows path containing `&`
The project folder name contains `&`, which breaks npm `.cmd` shims (`npx`, `npm run` on Windows). Locally, tools are invoked as `node node_modules/<pkg>/bin/...`. Linux CI/Docker use normal `npm run` scripts.

## ADR-007 — MySQL provisioning by the owner
The agent does not handle the MySQL root password. `scripts/mysql_init.sql` creates `dilsos` + `dilsos_test` schemas and a least-privilege `dilsos` user; the owner runs it once, then points `backend/.env` at MySQL. Until then local runtime uses SQLite (clearly shown in the UI header badge: `API 정상 · sqlite`).

## ADR-008 — Publication
New **public** GitHub repository, separate from the existing production-scheduler project. GitHub CLI installed via winget; authentication is performed by the owner.

## ADR-009 — One synthetic facility per demo scenario
Each generated "world" (customers, SKUs, orders with codes like `O0001`) gets its own facility code (`DC-NORMAL`, `DC-PEAK`, …) so order/customer codes stay unique per facility without renaming. Real deployments would use one facility with many scenarios (scenarios select orders via `scenario_orders`).

## ADR-010 — Snapshot document stored as JSON
`scenario_snapshots.content` stores the full `ScenarioSnapshot` (incl. travel matrix) as JSON with a SHA-256 content hash; identical consecutive snapshots are deduplicated. This deliberately exceeds "bounded metadata" because the snapshot *is* the reproducibility record; queryable projections are also written to `tasks`, `task_dependencies`, `travel_matrices`, `travel_matrix_entries`.

## ADR-011 — CP-SAT usage
OR-Tools ≥ 9.10 snake_case API. Default 8 search workers (better incumbents) ⇒ results under a time limit are not bit-reproducible; `params.num_workers=1` gives deterministic runs (recorded in `solver_metadata.deterministic`). The CP-SAT objective adds a 1 KRW/min completion tie-break; comparisons always use the shared evaluator, and the reported gap refers to the solver's own objective.

## ADR-012 — Dispatch rules use one shared serial SGS
FIFO/EDD/SPT only change task priority; placement is a gap-filling serial schedule-generation scheme over multi-resource requirements (picker [+ zone skill] [+ forklift], packer + station). The same decoder is reused by SA/Tabu/GA so their encodings are feasible by construction.

## ADR-013 — Routing-only readiness = order release
Without a warehouse plan the routing-only problem assumes goods are available at order release (warehouse treated as
instantaneous). The first draft used the ship cutoff, which forced mixed-window routes to wait for the latest cutoff and
produced artificial lateness. Realistic readiness is modelled in the `integrated` problem.

## ADR-014 — Rescheduling semantics
Executed = started before the event (tasks) / loading started (routes); frozen and copied verbatim, never re-timed.
KEEP freezes all unaffected work; PARTIAL opens the disrupted resources' tasks and all unstarted routes (vehicles/docks are
shared); FULL freezes only executed work + a committed window. PARTIAL/FULL always evaluate the KEEP plan as a candidate.
All three are registered algorithms that read their freeze sets from the stored snapshot → queued runs are reproducible.

## ADR-015 — Policy recommendation is rule-based and normalised
Weighted sum of min-max-normalised cost (incl. unserved/change penalties), lateness, changes and runtime among feasible
policies, with a human-readable reason. It is explicitly labelled "rule-based selector, not ML".

## ADR-016 — In-process rate limiting
A per-process sliding window protects expensive submissions without adding infrastructure. It is not a queue and keeps no
business state; multi-replica deployments should swap in a Redis-backed limiter.
