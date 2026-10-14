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

## Phase 4 — Integrated coordination

| Item | Status | Evidence |
|---|---|---|
| One-pass sequential decomposition (warehouse → readiness → VRPTW w/ load estimate → docks → repair) | TESTED | `tests/optimization/test_integrated.py`, `test_phase4_api.py` |
| Iterative coordination (departure cutoffs → tightened warehouse due dates → re-plan; accept only feasible improvements; controlled diversification; budget/iteration/stall stop) | TESTED | `test_demo_integrated_consistent_and_iterative_never_worse_than_its_start`, `test_iterative_improves_on_bottleneck` (bottleneck: 2.37M → 2.12M KRW, late 995 → 845 min, seed 1) |
| Pick→pack→load→depart→deliver consistency (independent re-check) | TESTED | `assert_chain_consistent`, API timestamp test |
| No departure before readiness; downstream constraints validated | TESTED | validator D1/R8 + chain checks |
| Sub-solver options (warehouse fifo/edd/spt/cpsat, routing nn/insertion/ortools, dock edd/fifo/cpsat) | TESTED (default + exact combo, slow test) | `test_integrated_with_exact_subsolvers` (`-m slow`) |
| Objective decomposition persisted | TESTED | `schedule_runs.metrics.cost`; API metrics test |
| Integrated journey UI with delay attribution (heuristic, labelled as such) | TESTED | `frontend/src/tests/phase4.test.tsx`; manual browser check (run #9) |
| Integrated ALNS across all layers (optional research) | TODO | spec marks optional; routing ALNS is Phase 5 |

## Phase 5 — Metaheuristics & experiments

| Item | Status | Evidence |
|---|---|---|
| Warehouse SA / Tabu / GA (order-permutation encoding, SGS decoder, validator-checked incumbents, eval budgets, seeds) | TESTED | `tests/optimization/test_metaheuristics.py` (never worse than EDD start, reproducible, measured improvement on tight instance) |
| Routing ALNS (4 destroy, 2 repair, adaptive weights, SA acceptance, iteration budget) | TESTED | `test_alns_reproducible_and_not_worse_than_insertion`; usable inside integrated (`params.routing="alns"`) |
| Benchmark harness (instances × algorithms × seeds, best/mean/std, infeasible rate, TTFF, gap, hardware metadata) | TESTED (quick suite executed) | `docs/experiments/benchmark_quick_*` (generated 2026-10-14, 8 CPUs, OR-Tools 9.15) |
| Experiments API (algorithms × seeds on one shared snapshot) | TESTED | `tests/integration/test_phase5_api.py` |
| Comparison dashboard (same-snapshot check, per-algorithm stats, stacked cost breakdown, runtime-vs-cost scatter, CSV download) | TESTED | `frontend/src/tests/phase5.test.tsx` |
| Full benchmark suite (medium/large, 10 seeds) | IMPLEMENTED | `--suite full` available; not executed in this session (time) |

Selected measured results (quick suite, 5 s budget): CP-SAT best on every warehouse instance (gap 0 on small-s1);
ALNS (≤150 iterations, 0.05–0.8 s) within 0–0.4 % of OR-Tools' 5 s solution on best-of-5 (equal on small-s1/s2); integrated iterative
improves the bottleneck scenario by 10.4 % total cost vs sequential and equals it on the small instances.

## Phase 6 — Dynamic events & rescheduling

| Item | Status | Evidence |
|---|---|---|
| Event engine: urgent order, worker absence, pack-station outage, dock outage, vehicle breakdown, travel-time increase, order cancellation | TESTED | `tests/optimization/test_rescheduling.py` (7 events × 3 policies) |
| No preemption (absence/outage after in-progress work), breakdown-after-departure & late cancellation reported as explicit exceptions | TESTED | `test_absence_respects_no_preemption`, `test_breakdown_after_departure_is_reported_not_rewritten` |
| Freeze logic: executed history, committed window, affected closure; PARTIAL neighbourhood | TESTED | history/past/validation assertions in every event×policy test |
| KEEP / PARTIAL / FULL algorithms (KEEP candidate evaluated inside PARTIAL/FULL; never claims optimality) | TESTED | `test_keep_changes_least_and_full_is_cheapest_or_equal_for_breakdown` |
| History-tamper detection (W10 tasks, F1 routes), no re-planning into the past (W3) | TESTED | `test_tampering_with_history_is_detected` |
| Rolling horizon over an event stream (only feasible versions adopted) | TESTED | `test_rolling_horizon_accumulates_history` |
| Stability metrics (changed tasks/routes, stability score, change penalty) | TESTED | evaluator; API summary |
| Rule-based policy selector with min-max normalised weights + human-readable reason | TESTED | `test_recommendation_is_transparent`, `test_recommendation_not_dominated_by_runtime_scale` (regression found in browser check) |
| API: idempotent events (201/200/409), versioned reschedule runs (parent + schedule_version+1, per-policy idempotency, optimistic version guard), summary + recommendation | TESTED | `tests/integration/test_phase6_api.py`; live API + DB worker run (base #10 → #11–#13) |
| Disruption simulator UI (event form, event list, policy runs, comparison, recommendation weights, before/after Gantt + route diff) | TESTED | `frontend/src/tests/phase6.test.tsx`; manual browser check |

## Phase 7 — Polish, evaluation, deployment

| Item | Status | Evidence |
|---|---|---|
| CSV order import (size/type/encoding/header/row validation, all-or-nothing, row cap) + UI with row-level errors and template | TESTED | `test_phase7_api.py` (success, rollback, header/size/type), `test_example_dataset_csv_imports_into_normal_day`; `phase7.test.tsx` |
| Run export CSV / JSON (validated runs only, UTC timestamps, provenance) + UI buttons | TESTED | `test_export_csv_and_json`; `phase7.test.tsx` |
| Per-user rate limit for runs / experiments / reschedules / imports | TESTED | `test_rate_limit` |
| Prometheus metrics endpoint (runs, runtimes, rejected-infeasible, queue depth, HTTP) — hidden from public nginx | TESTED | `test_ops_metrics` |
| OpenAPI covers every spec endpoint; static `docs/api/openapi.json` + `examples.http` | TESTED | `test_openapi_lists_spec_endpoints` |
| Playwright E2E smoke (login → warehouse run → Gantt → routing → map → disruption → compare) against the real stack | TESTED (local: Edge + dev stack) / IMPLEMENTED (CI compose job) | `frontend/e2e/smoke.spec.ts` — passed locally in 8.7 s |
| Screenshots from real runs | DONE | `docs/screenshots/*.png` via `e2e/screenshots.spec.ts` |
| Docs: README, architecture + sequence diagrams, ERD, formulations, algorithms, operations (deploy, backup/restore, security, observability), case study, demo script | DONE | `README.md`, `docs/**` |
| Demo story automation | TESTED | `scripts/demo_populate.py` (ran on a fresh DB; numbers identical to in-memory runs) |
| Full benchmark suite (medium/large, 10 seeds) | IMPLEMENTED, not executed | `python -m app.experiments.benchmark --suite full` |

## Acceptance checklist (spec §10.3)

| Criterion | Status | Notes |
|---|---|---|
| `docker compose up --build` starts all services with `.env.example` defaults | IMPLEMENTED — pending CI | No Docker on the dev machine; CI job `compose-smoke` builds, starts, waits for readiness, runs API smoke + Playwright |
| Migration & seed commands work; demo login succeeds | TESTED | SQLite locally (fresh DB in this session), MySQL 8.4 in CI integration job; local MySQL needs `scripts/mysql_init.sql` (owner) |
| Create/load a scenario, run a real warehouse solver and a real VRPTW solver, inspect verified schedules/metrics, API-backed Gantt, dock and map views | TESTED | E2E smoke + API tests + screenshots |
| Integrated baseline produces consistent pick→pack→load→depart→deliver timestamps | TESTED | `assert_chain_consistent`, `test_integrated_run_has_consistent_timestamps` |
| Injected disruption yields versioned KEEP/PARTIAL/FULL outputs or explicit infeasibility, differences shown in UI | TESTED | Phase 6 tests, disruption simulator diff view |
| ≥1 baseline and ≥1 advanced algorithm benchmarked on identical datasets with reproducible seeds | TESTED | `docs/experiments/benchmark_quick_*` |
| No invalid schedule published as feasible | TESTED | `test_invalid_schedule_is_never_published`, property tests |
| All mandatory tests pass; CI builds | TESTED locally / pending first CI run | see final report |
| README includes setup and architecture | DONE | `README.md` |

## Not implemented (explicitly)
* Phase 8 optional extensions: MILP network/inventory planning, demand forecasting, real road routing (OSRM), RL dispatch,
  live integrations, stochastic simulation (SimPy).
* Integrated ALNS spanning warehouse + routing moves (spec "optional research").
* SSE push updates (polling is used, as the spec allows initially).

## Publication
| Item | Status | Evidence |
|---|---|---|
| Local git history (one commit per phase) | DONE | `git log` |
| New public GitHub repository + push | BLOCKED (owner action) | GitHub CLI install via winget is waiting for Windows admin (UAC) approval and `gh auth login` must be done by the owner; then run `powershell -ExecutionPolicy Bypass -File scripts\publish_github.ps1` |
