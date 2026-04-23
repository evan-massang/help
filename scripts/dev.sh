#!/usr/bin/env bash
# One-command dev boot (Linux / WSL2).
# Brings up infra, waits for healthchecks, then starts backend + frontend via PM2.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

mkdir -p data/logs data/postgres data/redis data/chroma

echo "[dev] bringing up infra…"
docker compose -f infra/docker-compose.yml up -d

echo "[dev] waiting for postgres…"
until docker exec memeterm-postgres pg_isready -U memeterm -d memeterm >/dev/null 2>&1; do
  sleep 1
done

echo "[dev] waiting for redis…"
until docker exec memeterm-redis redis-cli ping >/dev/null 2>&1; do
  sleep 1
done

echo "[dev] waiting for chroma…"
until curl -fsS http://127.0.0.1:8001/api/v1/heartbeat >/dev/null 2>&1; do
  sleep 1
done

echo "[dev] starting backend + frontend via PM2…"
pm2 start infra/pm2.config.cjs
pm2 logs --lines 0
