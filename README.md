# DILSOS — Dynamic Integrated Logistics Scheduling & Optimization System

물류센터의 **피킹 → 패킹 → 도크 적재 → 차량 출발 → 고객 배송**을 하나의 연결된 스케줄로 최적화하고,
교란(결근·차량 고장·긴급 주문·교통 지연 등)이 생기면 **KEEP / PARTIAL / FULL** 정책으로 안정적으로 재계획하는
풀스택 운영 SCM 플랫폼입니다. 기존 생산 스케줄러와는 별개의 독립 프로젝트입니다.

> 모든 데이터는 **합성(synthetic)** 데이터이며 이동시간은 합성 유클리드 행렬(×1.3, 30 km/h)입니다. 실제 도로 경로·텔레메트리·
> 비즈니스 성과를 주장하지 않습니다. 화면과 API 응답에 출처 라벨이 항상 표시됩니다.

![dashboard](docs/screenshots/01_dashboard.png)

## What makes it different

* **Coupled scheduling** — packing completion constrains dock loading, which constrains departure and customer arrival.
  The integrated coordinator feeds downstream departure cutoffs back into warehouse priorities
  (bottleneck demo: total cost 2.37 M → 2.12 M KRW, lateness 995 → 845 min, seed 1 — measured, see `docs/experiments`).
* **One contract, one evaluator, one validator** — 19 registered algorithms share `ScheduleResult`, the same cost function and an
  independent feasibility validator (§3.2 rules). A run is published as `SUCCEEDED` **only** if the validator finds no error.
* **Honest optimisation** — CP-SAT gaps are reported only where meaningful; heuristics/metaheuristics/decompositions are
  never labelled optimal; unserved demand is always explicit with a reason and penalty.
* **Rescheduling with history protection** — executed work and routes are frozen and copied verbatim; stability metrics
  and a transparent, rule-based policy recommendation compare KEEP / PARTIAL / FULL on the same event.

## Features (all API-backed)

| Area | Implemented |
|---|---|
| Warehouse | FIFO / EDD / SPT (multi-resource serial SGS), CP-SAT, SA / Tabu / GA |
| Docks | FIFO / EDD dispatch, CP-SAT with exact downstream delivery timing |
| Routing (VRPTW) | nearest neighbour, cheapest insertion, OR-Tools Routing (GLS), ALNS |
| Integrated | sequential decomposition, iterative coordination |
| Rescheduling | 7 disruption types, KEEP / PARTIAL / FULL, rolling horizon, idempotent events, versioned schedules |
| Platform | FastAPI + JWT, MySQL 8 + Alembic, Celery/Redis or DB-poller queue, immutable snapshots, audit log, CSV import/export, rate limit, Prometheus metrics |
| UI (Korean) | dashboard, scenario builder, orders & resources, optimisation console, warehouse Gantt, dock/vehicle timeline, routes map (schematic SVG + optional OSM), order-journey timeline, disruption simulator, algorithm comparison, run history & audit |

Screens: [Gantt](docs/screenshots/04_warehouse_gantt.png) · [Docks](docs/screenshots/05_docks.png) ·
[Routes](docs/screenshots/06_routes.png) · [Journey](docs/screenshots/07_journey.png) ·
[Compare](docs/screenshots/08_compare.png) · [Disruptions](docs/screenshots/09_disruptions.png)

## Quick start

### Docker (all services)
```bash
cp .env.example .env
docker compose up --build
# UI http://localhost:8080 · API docs http://localhost:8080/api/docs · login demo@dilsos.local / demo1234
```

### Local without Docker
```bash
# backend (Python 3.12+)
cd backend
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"      # (Linux/macOS: .venv/bin/…)
copy ..\.env.example .env                                            # set DATABASE_URL (SQLite or MySQL)
alembic upgrade head
python -m app.seed.cli demo-user
python -m app.seed.cli demo-scenarios
uvicorn app.main:app --reload --port 8000
python -m app.tasks.db_worker                                        # second terminal (TASK_BACKEND=db)

# frontend (Node 20+)
cd ../frontend && npm install && npm run dev                         # http://localhost:5173
```
MySQL: run `scripts/mysql_init.sql` once as root, then
`DATABASE_URL=mysql+pymysql://dilsos:dilsos_dev_pw@localhost:3306/dilsos?charset=utf8mb4`.

### Demo data & story
```bash
python scripts/demo_populate.py --base http://localhost:8000/api/v1   # integrated runs, experiments, disruption + 3 policies
```

## Tests
```bash
cd backend && pytest -m "not slow"           # unit · solver · property-based · API · queue (SQLite)
TEST_MYSQL_URL=mysql+pymysql://… pytest tests/integration   # same API suite on MySQL 8
pytest -m slow                                # longer solver tests
ruff check app tests && mypy
cd frontend && npm run typecheck && npm test  # Vitest + Testing Library
npx playwright test                           # E2E smoke against a running stack (E2E_BASE_URL)
python -m app.experiments.benchmark --suite quick --out ../docs/experiments   # reproducible benchmark
```
CI (`.github/workflows/ci.yml`): lint, types, tests on SQLite **and** MySQL 8.4, frontend build/tests,
`docker compose up --build` smoke + Playwright E2E.

## Architecture
```
frontend (React/TS/Vite) ──/api──▶ nginx ──▶ FastAPI ──▶ MySQL (snapshots · runs · outputs · events · audit)
                                              │  enqueue (202)
                                              ▼
                                    Celery/Redis or DB-poller worker ──▶ optimization engine
                                    (solve → shared evaluator → independent validator → publish in one TX)
```
Details: [architecture](docs/architecture/overview.md) · [ERD](docs/architecture/erd.md) ·
[mathematical models](docs/mathematical_models/formulations.md) · [algorithms](docs/algorithms/README.md) ·
[API](docs/api/README.md) · [operations](docs/operations/deployment.md) ·
[experiments](docs/experiments/README.md) · [case study](docs/PORTFOLIO_CASE_STUDY.md) · [demo script](docs/demo_script.md)

## Project status
See [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) (evidence per item), [DECISIONS.md](DECISIONS.md) (ADRs) and
[CHANGELOG.md](CHANGELOG.md). Optional Phase 8 extensions (MILP network/inventory planning, forecasting, real road routing,
RL dispatch) are **not** implemented.

## Repository layout
```
backend/   app/{api,core,db,schemas,services,optimization,tasks,seed,experiments}  tests/{unit,integration,optimization,property}
frontend/  src/{app,api,components,features,store,types,utils,tests}  e2e/
datasets/  synthetic/ (demo scenario definitions)  examples/ (CSV import example)
docs/      architecture · api · mathematical_models · algorithms · experiments · operations · screenshots
scripts/   mysql_init.sql · smoke_test.py · run_via_api.py · demo_populate.py
```
