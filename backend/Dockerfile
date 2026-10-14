FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py && pip install ".[dev]" && rm -rf app

COPY . .
RUN pip install --no-deps -e . && useradd --create-home --uid 10001 dilsos && chown -R dilsos /app
USER dilsos

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
  CMD curl -fsS http://localhost:8000/api/v1/health/live || exit 1

CMD ["sh", "scripts/entrypoint.sh"]
