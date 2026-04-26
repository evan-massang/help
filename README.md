# memeterm

Local-first, advisory-only Solana meme-coin analyst. Read-only Phantom
wallet watching, opportunity scanning, wallet intelligence, narrative
tracking, and AI-assisted thesis/exit recommendations — all on your laptop.

See [the full plan](.claude/plans/bro-i-got-us-quirky-brook.md) for the
25-section spec.

## Status — Phase 8 (final)

All ten subsystems wired:

| # | Subsystem | Where it lives |
|---|-----------|----------------|
| 1 | Opportunity scanner | `backend/src/memeterm/scanner/` |
| 2 | Position monitor | `backend/src/memeterm/positions/` |
| 3 | Wallet intelligence | `backend/src/memeterm/wallets/` |
| 4 | Narrative engine | `backend/src/memeterm/narratives/` |
| 5 | Fake-hype filter | `backend/src/memeterm/hype/` |
| 6 | Next.js dashboard | `frontend/` |
| 7 | AI orchestration | `backend/src/memeterm/ai/` |
| 8 | Learning system | `backend/src/memeterm/learning/` |
| 9 | Safety rails | `backend/src/memeterm/safety/`, `rails/` |
| 10 | Alerting | `backend/src/memeterm/alerts/`, `infra/notifier/` |

## Operating modes

The whole pipeline runs without a wallet. Three sane configurations:

* **Observe mode (no wallet, no buying)**. Leave `PHANTOM_PUBKEY` blank.
  Scanner, safety, scorer, AI thesis, narratives, wallet-intel, alerts
  all run. The position monitor parks idle. Use this for the first
  week to watch what the system surfaces before you trade against it.
* **Watch mode (read-only wallet)**. Paste your Phantom pubkey on
  `/settings`. Position monitor activates: tracks PnL, fires
  exit-signal alerts when you're in a coin. You still buy/sell
  manually in Phantom — the app never signs.
* **Sized-watch mode (default once configured)**. Same as Watch mode
  plus the opportunity drawer shows a recommended buy size scaled to
  your wallet (`risk_per_trade_pct` × score multiplier). Tweak the
  base risk on `/settings`. The recommendation is advisory; you still
  type the number into Phantom yourself.

## Cold-start (first time)

Target: from a fresh WSL2 + Docker Desktop install to a running dashboard
in **under 3 minutes**.

```bash
git clone <repo>
cd memeterm

# 1. Fill in API keys (Helius is the only required one for the scanner)
cp .env.example .env
$EDITOR .env

# 2. Bring up infra: Postgres 16, Redis 7, ChromaDB
docker compose -f infra/docker-compose.yml up -d

# 3. Backend deps + initial migration
cd backend
pip install -e '.[dev]'           # add the [twikit] extra for free Twitter scraping
scripts/init_db.sh                # autogenerates + applies the alembic baseline
cd ..

# 4. Frontend deps
cd frontend && pnpm install && cd ..

# 5. (Optional, Windows only) build the toast sidecar
cd infra/notifier && cargo build --release && cd ../..

# 6. One-command boot
scripts/dev.sh         # WSL / Linux
# or
scripts/dev.ps1        # Windows (PowerShell)
```

## API key tiers (what each unlocks)

You don't need every key on day 1. The system degrades gracefully:

| Tier | Keys | Cost | What you get |
|------|------|------|--------------|
| **Bare minimum** | `HELIUS_API_KEY` | ~$49/mo Developer | Scanner + safety pipeline + 4-stage filter. Position monitor when wallet is set. |
| **Recommended** | + `BIRDEYE_API_KEY` + one of `ANTHROPIC_API_KEY` / `GROQ_API_KEY` | ~$60/mo + LLM | Above + momentum/liquidity scoring + AI thesis (Anthropic) or free Llama (Groq). |
| **Full free path** | Bare minimum + `GROQ_API_KEY` + `GOOGLE_AI_API_KEY` + twikit accounts | ~$49/mo | All AI on free tiers, Twitter scraped via twikit, Birdeye replaced by DexScreener + GeckoTerminal price fallback chain. Some features (deep holder data, security flags) won't be available. |
| **Everything** | + `RUGCHECK_JWT` + `CIELO_API_KEY` + `GMGN_SESSION_COOKIE` + `TWITTER_BEARER_TOKEN` + `NEWSAPI_KEY` | varies | All ten subsystems at full fidelity. |

### Free-tier Twitter via twikit

The X API Basic tier is $200/mo. To skip it:

```bash
pip install -e '.[twikit]'        # install the extra
# create 1–3 throwaway X accounts (separate emails + phone numbers)
# log into each interactively once with twikit's helpers — this writes
# data/twikit/<username>.json
# in .env:
TWITTER_SCRAPE_ACCOUNTS=user1,user2,user3
# leave TWITTER_BEARER_TOKEN blank
```

The Twitter adapter falls through automatically: v2 when the bearer
token is set, twikit when it isn't. Burner accounts get suspended
periodically — expect to refresh them every few weeks.

### Free-tier prices via DexScreener + GeckoTerminal

If you don't want a Birdeye key, leave `BIRDEYE_API_KEY` blank. The
price fallback chain skips Birdeye and uses DexScreener (no key) →
GeckoTerminal (no key). You lose deep holder distribution + security
flags from Stage 3, but momentum + liquidity subscores keep working.

Open <http://localhost:3000> — Command Deck shows live opportunities,
the alert feed, and system health dots within 2 seconds of startup.

## Daily operation

| Action | Command |
|--------|---------|
| Boot everything | `scripts/dev.sh` (or `dev.ps1` on Windows) |
| Stop everything | `pm2 stop all && docker compose -f infra/docker-compose.yml stop` |
| Tail backend logs | `pm2 logs memeterm-backend` |
| Re-run a thesis manually | `curl -X POST http://localhost:8787/api/thesis/<MINT>` |
| Force a calibration snapshot | `python -c "import asyncio; from memeterm.learning.calibration import run_once; asyncio.run(run_once())"` |
| Backup Postgres now | `python -c "import asyncio; from memeterm.learning.backups import pg_dump_now; asyncio.run(pg_dump_now())"` |
| Set the watched Phantom pubkey | POST `/api/settings/phantom` with JSON body `{"pubkey": "..."}` (or use Settings page) |

## Verification (per the plan §23)

```bash
# Backend
cd backend
ruff check .
mypy src/memeterm
pytest -q                                   # unit + integration (cassettes)
RECORD=1 pytest tests/integration            # re-record VCR cassettes

# Frontend
cd ../frontend
pnpm lint
pnpm typecheck
pnpm build
pnpm e2e:install                              # one-time
pnpm e2e                                      # Playwright critical-path

# Load test (Phase 8 §20 target: 500 launches/min, P99 < 2s)
cd ..
python scripts/loadtest.py --rate 8 --total 500 --report data/loadtest.json

# Replay a fixture through the scanner parser
python scripts/replay_stream.py backend/tests/fixtures/enhanced_tx_pumpfun_launch.json
```

## Routes

| Route | What it shows |
|-------|---------------|
| `/` | Command Deck (top opportunities + alert feed + system health) |
| `/opportunities` | Full opportunity table with click-to-thesis drawer |
| `/positions` | Live position cards + PnL + exit-signal alerts |
| `/wallets` | Tracked-wallet leaderboard + rubric drawer |
| `/narratives` | Narrative momentum + per-narrative drawer |
| `/settings` | Pubkey + budget + (forthcoming) mute manager |
| `/review` | Latest weekly review + scorer calibration |

REST surface is mounted under `/api/*`; WebSocket at `ws://127.0.0.1:8787/ws`
with channels `opportunities`, `positions`, `wallets`, `narratives`,
`alerts`. See per-route source under `backend/src/memeterm/api/`.

## Keyboard shortcuts

* `g d` deck · `g o` opportunities · `g p` positions · `g w` wallets · `g n` narratives · `g s` settings
* `/` focus search
* `m` toggle mute
* `?` show help · `esc` close

## Backups + crash reports

* `data/backups/pg/memeterm_*.dump` — nightly `pg_dump`, 30-day retention
* `data/backups/chroma/chroma_*` — weekly Chroma volume snapshot, 8-snapshot retention
* `data/crashes/*.json` — supervisor-captured exception with full traceback + log tail
* `data/snapshots/learning_*.json` — nightly calibration metrics
* `data/snapshots/review_*.json` — weekly review (rendered by `/review`)

## Safety posture

* **Read-only**. The app never signs transactions and has no code path
  that imports a signer library.
* **Pubkey-only** — public on-chain data only.
* **Advisory** — every recommendation surfaces the underlying numbers
  (safety stages, score components, exit signals) so the human stays in
  the loop.
* **Local-first** — no telemetry, no remote logging, no cloud backups.
  All persistent state lives under `data/` inside the WSL2 filesystem.

## Layout

```
backend/                  Python 3.11 + FastAPI + asyncio
  src/memeterm/
    main.py               supervisor TaskGroup (9 subsystems + API)
    config.py             pydantic-settings .env loader
    db/                   SQLModel tables + alembic
    adapters/             helius, birdeye, dexscreener, rugcheck,
                          twitter, jupiter, gmgn, cielo, newsapi,
                          gdelt, gtrends, phantom_watch
    safety/               4-stage pipeline (authority/lp/holders/honeypot)
    scanner/              ingest + parser + scorer
    positions/            reconstruct + classify + watcher + signals
    wallets/              rubric + ingest + watcher + refresh
    narratives/           ingest + cluster + tagging + extract
    hype/                 author shill + burst detection
    ai/                   router + budget + chroma RAG + providers
    alerts/               types + limiter + router + notifier
    learning/             outcomes + calibration + drift + backups + weekly_review
    rails/                rug cooldown + loss streak + overtrading
    api/                  REST + WebSocket
frontend/                 Next.js 14 + TypeScript
  app/                    deck + opportunities + positions + wallets +
                          narratives + settings + review
  components/             ThesisDrawer, WalletDrawer, NarrativeDrawer,
                          AlertToast, KeyboardNav, HealthDot
  lib/                    typed clients per route + ws + store
  e2e/                    Playwright critical-path
infra/
  docker-compose.yml      Postgres + Redis + Chroma
  pm2.config.cjs          backend + frontend + notifier
  notifier/               Rust toast sidecar (Windows)
scripts/                  dev.{sh,ps1} + replay_stream + loadtest
```
