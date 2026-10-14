# Operations: deployment, configuration, backup, security, observability

## Docker Compose (development / demo)

```bash
cp .env.example .env
docker compose up --build            # mysql, redis, api, worker, frontend
open http://localhost:8080           # demo login: demo@dilsos.local / demo1234
```
The API container entrypoint waits for MySQL, runs `alembic upgrade head`, seeds the demo user and the four demo
scenarios (non-production only) and starts uvicorn. The worker is Celery (`TASK_BACKEND=celery`). Health checks:
`/api/v1/health/live` (process) and `/api/v1/health/ready` (MySQL + Redis); nginx exposes `/healthz`.

> Verification status: compose files are exercised by the CI job `compose-smoke` (build, start, readiness, API smoke,
> Playwright E2E). They were **not** executed on the development machine (no Docker installed there).

## Production overrides

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
* `APP_ENV=production` disables demo login and refuses the default `JWT_SECRET`.
* MySQL, Redis and the API are **not** published on host ports; only nginx (`:80`). Put TLS in front (load
  balancer or an nginx `listen 443 ssl` block with your certificates).
* Set strong `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD`, `JWT_SECRET`; restrict `CORS_ORIGINS` to your domain.
* nginx returns 404 for `/api/v1/ops/*`; scrape metrics from the internal network (`http://api:8000/api/v1/ops/metrics`).

## Local development without Docker (Windows-tested)

```bash
cd backend && python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"
cp ../.env.example .env   # set DATABASE_URL (SQLite for a quick start, or MySQL after scripts/mysql_init.sql)
alembic upgrade head && python -m app.seed.cli demo-user && python -m app.seed.cli demo-scenarios
uvicorn app.main:app --reload --port 8000        # API
python -m app.tasks.db_worker                    # worker (TASK_BACKEND=db, no Redis needed)
cd ../frontend && npm install && npm run dev      # http://localhost:5173 (proxies /api → :8000)
```
On Windows paths containing `&` break npm `.cmd` shims; run tools as `node node_modules/vite/bin/vite.js` etc.

### MySQL 8 (least privilege)
`scripts/mysql_init.sql` (run once as root) creates `dilsos` and `dilsos_test` schemas and a `dilsos` user with
DML + DDL rights on those schemas only. Run the integration tests against MySQL with
`TEST_MYSQL_URL=mysql+pymysql://dilsos:…@localhost:3306/dilsos_test pytest tests/integration`.

## Configuration (`.env`)
| Variable | Purpose |
|---|---|
| `APP_ENV` | development / test / production |
| `DATABASE_URL` | SQLAlchemy URL (MySQL: `mysql+pymysql://…?charset=utf8mb4`) |
| `TASK_BACKEND` | `celery` · `db` · `eager` |
| `REDIS_URL` | Celery broker/result backend |
| `JWT_SECRET`, `JWT_EXPIRE_MINUTES` | token signing |
| `CORS_ORIGINS` | comma-separated allowed origins |
| `MAX_UPLOAD_BYTES` | CSV import limit (default 1 MiB) |
| `MAX_SOLVER_TIME_LIMIT_S`, `RUN_TIMEOUT_S` | solver budget cap; worker hard limit; stale RUNNING runs are failed after 2× |
| `RATE_LIMIT_PER_MINUTE` | per-user submissions (runs, experiments, reschedules, imports) |

## Backup & restore (MySQL)
```bash
docker compose exec mysql sh -c 'mysqldump -u root -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines dilsos' > dilsos_$(date +%F).sql
docker compose exec -T mysql sh -c 'mysql -u root -p"$MYSQL_ROOT_PASSWORD" dilsos' < dilsos_YYYY-MM-DD.sql
```
Snapshots and published outputs are immutable, so a logical dump is a complete, reproducible record of every run.
Redis holds only transient Celery messages (QUEUED runs live in MySQL and can be re-dispatched).

## Security checklist
* Argon2id password hashes; JWT secret from environment; demo account disabled in production.
* Mutations require `planner`/`admin` role; all queries via SQLAlchemy (parameterised).
* CSV import: size limit, media-type check, UTF-8 only, header/row validation, all-or-nothing transaction, row cap.
* Logs are JSON with request IDs; bearer tokens and `password=`/`token=`/`secret=` values are redacted.
* Rate limit for expensive submissions (in-process; use a shared limiter when running several API replicas).

## Observability
* Structured JSON logs (`request_id`, `method`, `path`, `status_code`, `duration_ms`, `run_id`, `algorithm`).
* `GET /api/v1/ops/metrics` (Prometheus text): runs by status/algorithm, runtime sum/count/max, rejected-infeasible
  runs, queue depth, HTTP requests by status class.
* Every run stores solver metadata (status, wall time, solutions, time-to-first-feasible, bounds/gap where meaningful).
