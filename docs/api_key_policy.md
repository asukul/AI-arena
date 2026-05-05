# API Key Policy — AI Arena (D4 Summer 2026)

**Status:** Locked 2026-05-04. Supersedes the "API key model" entry in `PLAN.md` § Open decisions.
**Owner:** Adisak Sukul.

---

## Decision

AI Arena uses a **shared-key model**: the platform holds the API keys, students never see them, and the per-student daily token budget enforced in [`evaluator/token_budget.py`](../evaluator/token_budget.py) keeps any single student from blowing the cohort budget.

We rejected the BYO-key model: it would have advantaged students with credit cards and made auth, key storage, and rotation a year-round support burden. The hybrid model (shared for basic, BYO for advanced) is a Phase-2 candidate if the cohort outgrows the shared budget.

## Provider matrix

| Provider | Used for | Why this provider | Cost ceiling |
|---|---|---|---|
| **Anthropic Claude Haiku 4.5** | Primary judge for Tracks 2, 3, 4 | Deterministic at `temperature=0`, fast, cheap, scoreable | Anthropic workspace **monthly spend cap** (see "Spend caps" below) |
| **Anthropic Claude Opus 4.7** | Cross-family re-grade pass on top 10% (`evaluator/regrade.py`) | Different model family from primary judge → exposes scoring artifacts | Re-grade pass runs nightly, capped by `regrade.RegradeRunner.max_per_run` |
| **Google Gemini Flash** | Optional second cross-family check; recommended for student inference | Generous free tier covers most student work without instructor cost | Free tier first, then per-key cap |

Students are encouraged to use Gemini Flash for their own inference on Tracks 2 / 3 because it has a per-developer free tier that the Anthropic key does not.

## Where keys live

| Secret name | Used by | Stored in | Read at | Rotation cadence |
|---|---|---|---|---|
| `anthropic-api-key` | `evaluator/judge.py` (judge calls), `evaluator/regrade.py` (cross-family) | GCP Secret Manager (`projects/ai-arena-platform/secrets/anthropic-api-key`) | Cloud Run startup, mounted as `ANTHROPIC_API_KEY` env var | Pre-bootcamp (Day −1) and post-bootcamp (Day +1) |
| `canvas-api-token` | `api/canvas.py` (grade passback) | GCP Secret Manager | Cloud Run startup | Pre-bootcamp (Day −1) and post-bootcamp (Day +1) |
| `canvas-webhook-secret` | `api/auth.py` (HMAC verification) | GCP Secret Manager | Cloud Run startup | Pre-bootcamp (Day −1) only — Canvas reissues if rotated mid-flight |

**No keys are committed to git.** `.env.example` is committed; `.env` is gitignored.

## Spend caps (defense in depth)

Three independent caps sit between a runaway prompt and a $5,000 surprise:

1. **Per-student daily token cap** — `DAILY_TOKEN_BUDGET=50000` in Cloud Run env, enforced in `evaluator/token_budget.py`. Hits return HTTP 429 from `/submit` before reaching the judge.
2. **GCP project budget alert** — `scripts/budget_alert.ps1` configures email alerts at 50%, 90%, 100%, 110% of the $1,030 cohort budget. The 110% alert is the "pull the plug" trigger.
3. **Anthropic workspace monthly spend cap** — set manually in the Anthropic console (this is **not** API-configurable as of 2026-05). Recommended setting: **$500/month**. Steps:
   1. https://console.anthropic.com → Settings → Billing → Workspace limits
   2. Create a hard limit on the workspace that owns the `anthropic-api-key`
   3. Verify by hitting it with a tiny test workload — Anthropic returns HTTP 429 cleanly.

## Rotation procedure

When you need to rotate `anthropic-api-key` (or any of the secrets above):

```powershell
# Mint a new key in the Anthropic console first.
# Then pipe it via stdin to the rotation script — never paste it into a file.
"sk-ant-…NEW…" | pwsh ./scripts/rotate_secret.ps1 -Name anthropic-api-key
```

The script creates a new secret version, then forces Cloud Run to pick it up by bumping a no-op env var on the service. Old versions stay around in case you need to roll back; revoke them in the Anthropic console once the new key is confirmed serving.

## Auditing & reporting

The judge wrapper logs every Claude call's `model`, `input_tokens`, `output_tokens`, and `student_id` to Cloud Logging via the structured logger in `api/logging_config.py`. Two queries land you the answers you'll want for the bootcamp retrospective:

```bash
# How many tokens has each student used today?
gcloud logging read --project=ai-arena-platform \
  "jsonPayload.event=judge_call AND timestamp>=\"$(date -u +%Y-%m-%dT00:00:00Z)\"" \
  --format='value(jsonPayload.student_id,jsonPayload.input_tokens,jsonPayload.output_tokens)' \
  | sort | awk '{a[$1]+=$2+$3} END{for(s in a) print s, a[s]}'

# Which submissions cost the most?
gcloud logging read --project=ai-arena-platform \
  "jsonPayload.event=submission_scored" --limit 200 \
  --format='value(jsonPayload.submission_id,jsonPayload.judge_metadata.total_tokens)'
```

## Off-switch

If you need to stop all judge calls immediately (e.g. someone found a way to drain the cap):

```powershell
# Replace the active Anthropic key with a zero-length placeholder. The judge
# wrapper raises a clean error and the platform returns HTTP 503 from /submit
# instead of burning tokens. Real keys can be restored with the rotate script.
"" | pwsh ./scripts/rotate_secret.ps1 -Name anthropic-api-key
```

The platform still scores Tracks 1 and 4 (no judge needed), so the leaderboard for those tracks keeps moving.
