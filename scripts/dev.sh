#!/usr/bin/env bash
# One-command NexusOps dev environment
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Starting Postgres (5433) and Redis..."
docker compose up -d postgres redis

echo "==> Waiting for Postgres..."
until docker compose exec -T postgres pg_isready -U nexusops >/dev/null 2>&1; do sleep 1; done

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "==> Created .env from .env.example"
fi

echo "==> Running migrations..."
alembic upgrade head

echo "==> Running tests..."
python -m pytest tests/ -q --tb=no

# Free port 8000 if occupied by a previous uvicorn
if ss -tlnp 2>/dev/null | grep -q ':8000 '; then
  echo "==> Port 8000 in use — stopping old uvicorn..."
  pkill -f "uvicorn nexusops.main:app" 2>/dev/null || true
  sleep 1
fi

echo ""
echo "Ready. Start the API:"
echo "  uvicorn nexusops.main:app --reload --host 127.0.0.1 --port 8000"
echo ""
echo "Or full stack via Docker:"
echo "  docker compose up -d"
