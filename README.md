# AI Arena (`d4-arena`)

Kaggle-style competition platform for the **D4 Summer 2026 Bootcamp** (LLM, GenAI, and RAG modules) at Iowa State University.

> The full design and rationale lives in [`PLAN.md`](PLAN.md) (the project anchor — read at the start of every session).
> This README is the *operator's manual* for the codebase.

## What's here

| Path | Purpose |
|---|---|
| `api/` | FastAPI app — Canvas webhook, submission dispatcher, grade passback, Kaggle-style competition UI |
| `api/landing.py` | Card-grid landing page (`GET /`) — one card per competition |
| `api/competition.py` | Per-track Kaggle-style shell (`GET /competitions/{track_id}`) — Overview / Data / Code / Leaderboard / Rules tabs + persistent in-browser submit modal |
| `api/competition_data.py` | Single source of truth for per-track metadata (name, metric, sample, files, rules) |
| `evaluator/` | Track scorers + Claude-as-judge wrapper. One file per track under `tracks/`. |
| `leaderboard/` | Firestore writer (server) + static HTML leaderboard (Firebase Hosting) |
| `prompts/` | Version-controlled judge prompts as plain `.txt` files |
| `tests/` | `pytest` — every scoring function has unit tests (happy, empty, malformed, edge) |
| `corpora/` | RAG corpora (Track 3) — starter is the ISU course catalog |

## Public routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Card grid of all four competitions (live counts) |
| `GET` | `/competitions/{track_id}` | Per-track Kaggle-style page — tabs + submit modal |
| `GET` | `/get-started` | Long-form tutorial / curl recipes (kept for reference) |
| `GET` | `/samples/{track_id}` | Canonical sample submission JSON (scores 1.0) |
| `GET` | `/leaderboard/{track_id}` | Leaderboard JSON (used by the live-refresh JS) |
| `POST` | `/submit` | Submit a graded entry |
| `GET` | `/health` | Liveness probe (note: not `/healthz` — see troubleshooting) |
| `GET` | `/docs`, `/redoc` | OpenAPI references |

## What students see

The platform is modeled on Kaggle's competition layout — anyone who has used
Kaggle should recognize the shape immediately.

**Landing (`/`):** card grid of all four competitions. Each card shows live
submission/student counts and the current top student.

```
┌─ AI Arena ────────────────────────────────────────────────────────────────┐
│  Competitions  Docs  GitHub                                               │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  AI Arena                                                                 │
│  Kaggle-style competition platform · D4 Summer 2026 Bootcamp · ISU        │
│  [v0.1.0 live] [4 active competitions]                                    │
│                                                                           │
│  ACTIVE COMPETITIONS                                                      │
│  ┌─────────────────────────────────────┐ ┌─────────────────────────────┐  │
│  │ TRACK 1                          →  │ │ TRACK 2                  →  │  │
│  │ Hallucination Hunter                │ │ Prompt Golf                 │  │
│  │ Classify each claim as supported,…  │ │ Find the shortest prompt…   │  │
│  │ EVAL  macro-F1                      │ │ EVAL  judge accuracy × …    │  │
│  │ ─────────────────────────────────── │ │ ─────────────────────────── │  │
│  │ 3        3        qa_tester_2026…   │ │ 0    0    —                 │  │
│  │ subs   students   top student       │ │ subs students top student   │  │
│  └─────────────────────────────────────┘ └─────────────────────────────┘  │
│  ┌─ TRACK 3 ────────────┐  ┌─ TRACK 4 ─────────────────────────────────┐  │
│  │ RAG Treasure Hunt …  │  │ Build Your Own AI Judge …                 │  │
│  └──────────────────────┘  └───────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
```

**Per-track page (`/competitions/{track_id}`):** Kaggle-style horizontal tabs,
persistent blue **Submit Entry** button, evaluation metric pinned in the header.

```
┌───────────────────────────────────────────────────────────────────────────┐
│ TRACK 3                                                  ┌─────────────┐ │
│ RAG Treasure Hunt                                        │ ↑ Submit    │ │
│ Build a retrieval pipeline over the ISU course catalog   │   Entry     │ │
│ [Active] [Eval: weighted rubric (30/25/15/15/10/5)]      └─────────────┘ │
│ [N submissions] [N students]                                              │
├───────────────────────────────────────────────────────────────────────────┤
│ Overview │ Data │ Code │ Leaderboard │ Rules                              │
└───────────────────────────────────────────────────────────────────────────┘
```

**Submit modal:** opens from the persistent button. Three input modes — *Paste
JSON*, *Upload .json*, *Use sample as starting point*. Submits via `fetch`
to `/submit` and shows the response inline. Students never leave the page.

The single source of truth for per-track metadata (name, metric, sample
payload, public files, rules) lives in
[`api/competition_data.py`](api/competition_data.py); both the landing and the
per-track shell read from it.

## Quick start (local dev — no GCP needed)

```powershell
# 1. Create venv and install
uv venv
uv pip install -r requirements-dev.txt

# 2. Copy env template
Copy-Item .env.example .env   # edit values; ARENA_LOCAL_DEV=1 skips GCP

# 3. Run tests
pytest -xvs

# 4. Run API in local mode (in-memory queue + leaderboard)
$env:ARENA_LOCAL_DEV="1"; uvicorn api.main:app --reload --port 8080

# 5. Smoke-test
curl http://localhost:8080/health
curl -X POST http://localhost:8080/submit `
  -H "Content-Type: application/json" `
  --data-binary "@tests/fixtures/sample_hallucination.json"
curl http://localhost:8080/leaderboard/hallucination_hunter
```

## Deploy to Cloud Run (project: `ai-arena-platform`)

```powershell
# One-time: enable APIs, create Firestore, queue, service accounts, secrets
gcloud auth login
pwsh ./scripts/bootstrap_gcp.ps1

# Then deploy (two-phase: first pass gets the URL, second pass wires it back in)
pwsh ./scripts/deploy.ps1
```

### Live service

```
https://d4-arena-api-77646749251.us-central1.run.app
```

Quick verification (PowerShell):

```powershell
$url = "https://d4-arena-api-77646749251.us-central1.run.app"
Invoke-RestMethod "$url/health"
Invoke-RestMethod "$url/submit" -Method POST -ContentType "application/json" `
    -Body (Get-Content "tests/fixtures/sample_hallucination.json" -Raw)
Invoke-RestMethod "$url/leaderboard/hallucination_hunter"
```

### Populating / rotating real secrets

After bootstrap, the three secrets (`canvas-api-token`, `canvas-webhook-secret`,
`anthropic-api-key`) hold placeholder strings. The full policy (which key is
used where, spend caps, audit queries, off-switch) is in
[`docs/api_key_policy.md`](docs/api_key_policy.md). To set or rotate any of them:

```powershell
# Pipe the real value via stdin — never paste it into a file.
"sk-ant-…NEW…" | pwsh ./scripts/rotate_secret.ps1 -Name anthropic-api-key

# Same flow for the Canvas secrets:
"…canvas-token…"  | pwsh ./scripts/rotate_secret.ps1 -Name canvas-api-token
"…webhook-secret…" | pwsh ./scripts/rotate_secret.ps1 -Name canvas-webhook-secret
```

The script creates a new Secret Manager version and bumps a no-op env var on
Cloud Run so the next request reloads the secret. Old versions stay enabled
for rollback; disable them in the Secret Manager console once the new one is
confirmed serving.

Emergency off-switch (stops all judge calls without redeploying):

```powershell
"" | pwsh ./scripts/rotate_secret.ps1 -Name anthropic-api-key
```

## Troubleshooting (lessons from Day 1)

| Symptom | Cause | Fix |
|---|---|---|
| `gcloud services enable` returns `PERMISSION_DENIED` on a fresh project | Bulk batch enable can fail intermittently even for Owners | Loop one API at a time (see `scripts/bootstrap_gcp.ps1`) |
| `/submit` returns 500 with `iam.serviceAccounts.actAs` permission denied | Runtime SA can't impersonate the invoker SA when creating Cloud Tasks tasks | `roles/iam.serviceAccountUser` on invoker SA → runtime SA (now in bootstrap) |
| Submission queues but score never lands on leaderboard | `corpora/` not in container, `gold.json` missing at runtime | Dockerfile copies `corpora/` (now fixed) |
| `--set-secrets` deploy fails | Secret exists but has no versions | Add a placeholder version: `"PLACEHOLDER" \| gcloud secrets versions add …` |
| `/healthz` returns Google's 404 page on `*.run.app` | GCP edge reserves the exact path `/healthz` and intercepts it before Cloud Run | Use `/health` (or any path that isn't literally `/healthz`) — see `memory/reference_cloud_run_healthz_gotcha.md` |
| Firebase Hosting not deployed | `firebase` CLI not installed locally | `npm install -g firebase-tools` then `firebase login` (Day 5) |


## Tracks

| # | Track | Submission | Metric |
|---|---|---|---|
| 1 | Hallucination Hunter | CSV: `(claim_id, label)` | F1 vs hidden ground truth |
| 2 | Prompt Golf | Prompt template + sample outputs | judge accuracy ÷ token cost |
| 3 | RAG Treasure Hunt | JSON answers + citations + contexts | Weighted rubric (30/25/15/15/10/5) |
| 4 | Build Your Own AI Judge | Student evaluator + rubric | Cohen's κ vs instructor gold |

## Conventions

- Python 3.12+, type hints everywhere, `pydantic` for all I/O schemas
- All LLM calls go through `evaluator/judge.py` (enforces `temperature=0`, retries, token logging)
- Judge prompts live in `prompts/*.txt`, version-controlled
- Tests written *before* scoring code; secrets never committed
- Conventional commits: `feat:`, `fix:`, `test:`, `docs:`

See [`PLAN.md`](PLAN.md) for the day-by-day TODO and architectural decisions.
