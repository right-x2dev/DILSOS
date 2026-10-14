# Implementation Status

Statuses: `TODO` · `IN_PROGRESS` · `IMPLEMENTED` (code exists, not fully verified) · `TESTED` (automated tests pass, evidence linked) · `BLOCKED`.

_Last updated: 2026-10-14 — end of Phase 1._

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

## Phase 1 — Warehouse vertical slice

| Item | Status | Evidence |
|---|---|---|
| Typed contracts (`ScenarioSnapshot`, `SolveConfig`, `ScheduleResult`, `ValidationReport`, …) | TESTED | `app/optimization/common/contracts.py`; used by every test |
| Full MySQL schema (27 spec tables + `scenario_orders`) + migration 0002 | TESTED | migrated per test session; CI re-runs on MySQL 8.4 |
| Immutable published outputs (ORM guard) | TESTED | `test_published_outputs_are_immutable` |
| Deterministic synthetic generator + 4 demo scenarios | TESTED | `tests/unit/test_generator.py` (reproducibility, refs, durations, feasible/infeasible) |
| Definition ⇄ DB ⇄ snapshot lossless round trip; snapshot versioning/dedup | TESTED | `test_definition_round_trip_is_lossless`, `test_snapshot_versioning_on_master_change` |
| Inventory allocation / explicit backorders | TESTED | `test_inventory_shortage_creates_backorders`, `test_inventory_negative_detected` |
| Warehouse FIFO / EDD / SPT (serial SGS, multi-resource) | TESTED | `tests/optimization/test_warehouse_solvers.py` |
| Warehouse CP-SAT (optional intervals, shifts/downtime, EDD warm start, gap, cancel) | TESTED | `test_cpsat_certifies_optimality_on_tiny…`, `test_cpsat_cancellation_stops_early` |
| Independent validator (U1, W1–W10 + D/R rules) | TESTED (W rules) | `tests/unit/test_validator_warehouse.py`, `tests/property/test_validator_properties.py` (hypothesis) |
| Shared evaluator (cost decomposition, KPIs) | TESTED | `test_objective_terms_are_recomputable` |
| Run queue: eager / DB-poller / Celery; atomic claim; cancel; failure; publish-only-if-valid | TESTED (eager, db) / IMPLEMENTED (celery, CI compose) | `tests/integration/test_queue_and_persistence.py` |
| API: scenarios (build/patch/clone/validate/geo), orders, resources, runs, schedule, validation, metrics, compare, algorithms, dashboard, audit | TESTED | `tests/integration/test_phase1_api.py` |
| UI: dashboard, scenarios/builder, orders & resources, optimization console, warehouse Gantt, runs/audit | TESTED | `frontend/src/tests/phase1.test.tsx`; manual: CP-SAT run via DB worker → Gantt in browser |
| CSV import / export buttons | TODO (Phase 7) | rendered disabled with “준비 중” label |

## Phase 2 — Packing & dock scheduling

| Item | Status | Evidence |
|---|---|---|
| Route timing propagation (travel/service/wait/late, load trajectory, return) | TESTED | `test_route_time_propagation_by_hand` |
| Hard-constraint repair (drop stops breaking shift end / hard windows) | TESTED | `test_hard_window_repair_drops_violating_stop` |
| Shipment readiness: LOAD starts after all orders packed; departure ≥ load end | TESTED | `test_dock_tiny_feasible_and_ready_before_load`, API `test_dock_run_publishes…` |
| Dock FIFO / EDD dispatch, compatible docks, dock hours & downtime, no overlap | TESTED | `test_single_dock_no_overlap`, `test_dock_downtime_respected` |
| Dock CP-SAT with exact downstream delivery timing (fixed sequences) | TESTED | `test_cpsat_dock_not_worse_than_heuristics_on_bottleneck` (bottleneck: 1628 vs FIFO 1666 / EDD 1785 late-min, seed 1, 10 s) |
| Baseline time-aware grouping (dock-only problem) | IMPLEMENTED | used by all dock algorithms; replaced by VRPTW in Phase 3/4 |
| Validator D1–D5 + R1–R8 | TESTED | `test_dock_validator_catches_violations` |
| Dock timeline UI (dock lanes, vehicle lanes, waiting/load/road bars, overlap/capacity/early-load warnings) | TESTED | `frontend/src/tests/phase2.test.tsx`; manual browser check (run #4, 0 warnings) |

## Phase 3 — Vehicle routing (VRPTW)

| Item | Status | Evidence |
|---|---|---|
| Routing units (same-customer aggregation, capacity split) + fast simulator identical to shared timing | TESTED | `test_same_customer_orders_share_one_stop`, `test_simulator_matches_shared_timing` |
| Time-oriented nearest neighbour | TESTED | `tests/optimization/test_routing.py` (all cases) |
| Cheapest insertion (cached per route) | TESTED | same |
| OR-Tools Routing VRPTW (weight+volume capacity, time windows soft/hard, drop penalties, readiness per vehicle, GLS, warm start) | TESTED | `test_ortools_not_worse_than_insertion_warm_start`; normal_day: cost 362k vs insertion 413k vs NN 526k (seed 1, 8–10 s) |
| Capacity / hard windows / zero vehicles / identical windows / single order / unreachable customer | TESTED | `test_capacity_is_respected`, `test_hard_windows_never_violated`, `test_zero_vehicles_all_unserved`, `test_identical_time_windows_and_single_order`, `test_far_customer_beyond_shift_is_unserved…` |
| Honest provenance: synthetic coordinates, euclidean travel, schematic straight lines, no optimality claims | TESTED | API `test_routing_run_publishes_routes_and_stops` (gap = null); UI `phase3.test.tsx` |
| Routes UI: schematic SVG (default), optional OSM map (lazy, tile-error fallback), route/stop table | TESTED | `phase3.test.tsx`; manual browser check (OSM tiles loaded, 34 overlays) |
| Routing-only readiness assumption = order release (warehouse not modelled) | IMPLEMENTED | documented in pipeline docstring, metadata and validator R8 |
