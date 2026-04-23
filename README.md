# memecoin-terminal

A local-first, advisory desktop app for Solana meme-coin analysis. Read-only
wallet watching, opportunity scanning, wallet intelligence, narrative tracking,
and AI-assisted thesis/exit recommendations — all running on your laptop.

See [the full plan](.claude/plans/bro-i-got-us-quirky-brook.md) for the complete
spec (25 sections, 10 subsystems, 9 build phases).

## Status

Phase 0 — Foundations. Backend skeleton + health endpoint + docker compose
come up. Nothing else is wired yet.

## Quick start (dev, Phase 0)

```bash
# 1. Fill in .env
cp .env.example .env

# 2. Bring up infra (Postgres, Redis, ChromaDB)
docker compose -f infra/docker-compose.yml up -d

# 3. Install backend
cd backend && pip install -e '.[dev]' && cd ..

# 4. Run the API
uvicorn memeterm.api.http:app --reload --host 127.0.0.1 --port 8787

# 5. Check health
curl http://127.0.0.1:8787/api/health
```

## Layout

```
backend/     Python 3.11 + FastAPI + asyncio (WSL2 recommended)
frontend/    Next.js 14 + TS (Windows native)  — not yet in repo
infra/       docker-compose + PM2
scripts/     dev.ps1 / dev.sh / replay_stream.py
shared/      JSON schemas shared by FE/BE
```

## Safety posture

This app **never signs transactions**. It watches a Phantom pubkey (public
data only) and produces advisory signals. No private keys, no trading, no
deep-links into Phantom. Every recommendation is advisory.
