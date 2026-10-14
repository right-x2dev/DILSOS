# API

* Interactive docs: `http://localhost:8000/api/docs` (Swagger UI) — generated from the real response models.
* Static schema: [`openapi.json`](openapi.json) (regenerate: `python -c "import json; from app.main import create_app; print(json.dumps(create_app().openapi()))"`).
* Example requests: [`examples.http`](examples.http) (VS Code REST Client / JetBrains HTTP client).

Conventions: prefix `/api/v1`; JWT bearer auth (`POST /auth/login`); errors are
`{"error": {"code", "message", "details", "request_id"}}`; list endpoints return `{items, total, limit, offset}`;
long work returns **202** + run id, poll `GET /runs/{id}`; times are integer minutes from the scenario
`horizon_start` (UTC) unless the field is an ISO-8601 timestamp.

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/login` | demo login (disabled in production) |
| GET | `/auth/me` | |
| GET/POST | `/orders` | filters: scenario_id, status, priority, q; pagination |
| GET/POST | `/resources/workers` · `/resources/vehicles` · `/resources/docks` | facility_id |
| GET | `/facilities` | |
| GET/POST | `/scenarios` | POST = synthetic scenario builder |
| GET/PATCH | `/scenarios/{id}` | PATCH requires `version` (optimistic concurrency, 409 on conflict) |
| POST | `/scenarios/{id}/clone` | |
| POST | `/scenarios/{id}/validate` | input checks + snapshot version/hash |
| GET | `/scenarios/{id}/geo` | coordinates + provenance labels |
| POST | `/scenarios/{id}/runs` | 202 |
| POST | `/scenarios/{id}/experiments` | algorithms × seeds on one snapshot |
| GET | `/runs`, `/runs/{id}` | |
| POST | `/runs/{id}/cancel` | QUEUED → CANCELLED; RUNNING → cooperative cancel |
| GET | `/runs/{id}/schedule` · `/validation` · `/metrics` · `/compare` | |
| GET | `/algorithms` | availability detection |
| POST/GET | `/scenarios/{id}/events` | `Idempotency-Key` header: 201 new · 200 replay · 409 conflicting payload |
| POST | `/runs/{id}/reschedule` | KEEP/PARTIAL/FULL → new versioned runs |
| GET | `/runs/{id}/reschedules` | per-policy KPIs + rule-based recommendation |
| POST | `/imports/orders` | multipart CSV, all-or-nothing |
| GET | `/exports/runs/{id}?format=csv|json` | validated schedules only |
| GET | `/dashboard/summary` · `/audit-logs` | |
| GET | `/health/live` · `/health/ready` · `/ops/metrics` | |
