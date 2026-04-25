#!/usr/bin/env bash
# Bootstrap the memeterm database: wait for Postgres, autogenerate the
# initial migration if none exists yet, then upgrade to head.
#
# Idempotent — safe to run on every cold start. Subsequent runs simply
# `alembic upgrade head`; new migrations the user generates by hand land
# in the same versions/ dir.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT/backend"

echo "[init_db] waiting for postgres…"
until docker exec memeterm-postgres pg_isready -U memeterm -d memeterm >/dev/null 2>&1; do
  sleep 1
done

VERSIONS_DIR="src/memeterm/db/migrations/versions"
HAS_MIGRATIONS=$(find "$VERSIONS_DIR" -maxdepth 1 -name "*.py" -not -name "__init__.py" | head -n1)

if [ -z "$HAS_MIGRATIONS" ]; then
  echo "[init_db] no migrations found — autogenerating initial revision…"
  alembic -c alembic.ini revision --autogenerate -m "initial"
fi

echo "[init_db] alembic upgrade head"
alembic -c alembic.ini upgrade head

echo "[init_db] done."
