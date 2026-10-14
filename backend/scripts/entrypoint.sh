#!/bin/sh
# API container entrypoint: wait for DB, migrate, seed demo data (dev only), serve.
set -e

python -m app.seed.wait_for_db
alembic upgrade head
if [ "${APP_ENV}" != "production" ]; then
  python -m app.seed.cli demo-user
  python -m app.seed.cli demo-scenarios || echo "demo scenarios not available yet"
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
