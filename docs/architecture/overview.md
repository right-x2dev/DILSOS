# Architecture

## Components

```mermaid
flowchart LR
  subgraph Browser
    UI[React + TS SPA<br/>TanStack Query · Zustand UI state<br/>SVG Gantt/Dock/Journey · Recharts · Leaflet]
  end
  subgraph Edge
    NG[nginx<br/>static SPA + /api reverse proxy]
  end
  subgraph Backend
    API[FastAPI /api/v1<br/>JWT · typed errors · request IDs]
    W[Worker<br/>Celery (Redis) or DB-poller]
    OPT[Optimization engine<br/>contracts · validator · evaluator<br/>warehouse · dock · routing · integrated · rescheduling]
  end
  DB[(MySQL 8<br/>master data · snapshots · runs · outputs · events · audit)]
  R[(Redis<br/>Celery broker)]

  UI -->|HTTPS JSON| NG --> API
  API -->|enqueue run id| R --> W
  API -->|QUEUED rows| DB
  W -->|claim (atomic UPDATE)| DB
  W --> OPT
  OPT -->|validated result| W -->|publish in one transaction| DB
  API --> DB
```

* The HTTP layer never runs a solver: `POST /scenarios/{id}/runs` stores a QUEUED run and returns **202**.
* `TASK_BACKEND=celery` (compose) transports run IDs via Redis; `db` uses a persistent DB-polling worker
  (`python -m app.tasks.db_worker`); `eager` runs inline for tests. All three call `execute_run(run_id)`.
* The optimization engine is ORM-free: it consumes a `ScenarioSnapshot` and returns a `ScheduleResult`
  (spec §5.1). The shared evaluator computes every KPI/cost term; the independent validator decides publication.

## Run lifecycle

```mermaid
sequenceDiagram
  autonumber
  participant U as UI
  participant A as API
  participant D as MySQL
  participant Q as Queue (Redis / DB)
  participant W as Worker
  U->>A: POST /scenarios/{id}/runs {problem, algorithm, seed, time limit}
  A->>D: build snapshot from current master data (dedup by SHA-256) · INSERT run (QUEUED)
  A->>Q: dispatch run id
  A-->>U: 202 {id, status: QUEUED}
  loop poll every 1 s
    U->>A: GET /runs/{id}
  end
  W->>D: UPDATE … SET status=RUNNING WHERE id=? AND status='QUEUED' (atomic claim)
  W->>W: solve(snapshot) → evaluate → validate_schedule
  alt feasible & publishable
    W->>D: one transaction: assignments, routes, stops, shipments, metrics, SUCCEEDED
  else invalid / solver error / cancel
    W->>D: FAILED or CANCELLED (+ validation report, no outputs)
  end
  U->>A: GET /runs/{id}/schedule · /validation · /metrics
```

## Disruption handling

```mermaid
sequenceDiagram
  autonumber
  participant U as UI (Disruption simulator)
  participant A as API
  participant E as Rescheduling engine
  participant W as Worker
  U->>A: POST /scenarios/{id}/events (Idempotency-Key)
  A-->>U: 201 (or 200 replay / 409 conflicting payload)
  U->>A: POST /runs/{base}/reschedule {event, policies, freeze window}
  A->>E: base snapshot + published base schedule + event
  E->>E: apply event (no preemption) · executed = started before t · affected closure
  E-->>A: policy snapshots (frozen history, KEEP freeze set, baseline, current time)
  A->>A: store snapshots, enqueue runs (parent = base, schedule_version + 1)
  W->>W: reschedule_{keep|partial|full}: KEEP repair vs re-optimiser (keep candidate if not better)
  W->>W: validator: W10 frozen tasks unchanged · F1 frozen routes identical · nothing re-planned before t
  U->>A: GET /runs/{base}/reschedules → per-policy KPIs + rule-based recommendation
```

## Code map

| Path | Responsibility |
|---|---|
| `backend/app/optimization/common/` | contracts, preprocessing (inventory, explicit unserved), timelines, route timing & repair, evaluator, validator, registry, runner |
| `backend/app/optimization/warehouse/` | serial SGS, FIFO/EDD/SPT, CP-SAT, SA/Tabu/GA |
| `backend/app/optimization/dock/` | dock dispatch + CP-SAT, baseline grouping, dock pipeline |
| `backend/app/optimization/routing/` | units & simulator, NN, cheapest insertion, OR-Tools VRPTW, ALNS |
| `backend/app/optimization/integrated/` | sequential decomposition, iterative coordination |
| `backend/app/optimization/rescheduling/` | events, freeze policies, reschedule algorithms, rolling horizon, recommendation |
| `backend/app/services/` | snapshot builder, scenario store, run lifecycle, rescheduling orchestration, input validation, audit |
| `backend/app/api/v1/` | REST endpoints |
| `frontend/src/features/` | one folder per screen |
