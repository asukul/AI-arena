# Operations runbook — AI Arena

The platform's day-to-day observability lives in Cloud Logging + Cloud
Monitoring on the `ai-arena-platform` project. This doc collects the queries,
dashboards, and "something is wrong" recipes you'll reach for during the
bootcamp.

## Setup (one-time)

```powershell
# Creates 5 log-based metrics + the "AI Arena — Operations" Monitoring dashboard.
pwsh ./scripts/setup_monitoring.ps1
```

After running, the dashboard is live at:

```
https://console.cloud.google.com/monitoring/dashboards?project=ai-arena-platform
```

Pick **AI Arena — Operations** from the list.

## At-a-glance dashboard

The dashboard shows five charts — pick the one that matches the question:

| Chart | What you learn |
|---|---|
| Submissions / min | Are students actively submitting? Spikes correspond to assignment due dates. |
| Judge calls / min | Tracks 2 & 3 fan out into ~1 judge call per item; check this when latency feels slow. |
| 5xx errors / hour | Should be ~0. Anything else means the platform is dropping submissions. |
| Token-budget bounces / hour | A few is fine; a flat line of bounces means a student is stuck — DM them. |
| Cloud Run latency (p50/p95/p99) | Cold-start spikes p95–p99 to ~2s; warm requests should be sub-200ms. |

## Saved Logs Explorer queries

Open **Logs Explorer** in the Cloud Console and paste any of these into the
query bar.

### Every submission today

```
resource.type="cloud_run_revision"
resource.labels.service_name="d4-arena-api"
httpRequest.requestMethod="POST"
httpRequest.requestUrl=~"/submit"
timestamp >= "2026-05-04T00:00:00Z"
```

### Errors in the last hour

```
resource.type="cloud_run_revision"
resource.labels.service_name="d4-arena-api"
severity >= "ERROR"
timestamp >= timestamp_sub(timestamp_now(), interval 1 hour)
```

### Judge tokens used per student today

Run this in Cloud Shell — the in-browser Logs Explorer can't aggregate.

```bash
TODAY=$(date -u +%Y-%m-%dT00:00:00Z)
gcloud logging read --project=ai-arena-platform \
  "jsonPayload.event=\"judge_call\" AND timestamp>=\"$TODAY\"" \
  --format='value(jsonPayload.tokens_in,jsonPayload.tokens_out)' \
  --limit=10000 \
| awk '{ sum += $1 + $2 } END { print sum " tokens total today" }'
```

For per-student breakdown, the platform's structured logger doesn't include
`student_id` on `judge_call` events (the call doesn't have it directly). Use
the Firestore `submissions/` collection or the `daily_token_budgets/` rate-limit
counter instead — those are the authoritative per-student records.

### Students bouncing off the daily token cap

```
resource.type="cloud_run_revision"
jsonPayload.event="token_budget_exceeded"
```

Each entry includes `student_id`, `used`, `limit`, and `submission_id`.

### Cloud Run revision rollouts

```
resource.type="cloud_run_revision"
jsonPayload.event="app_starting"
```

One row per cold start. Useful for confirming a deploy actually picked up
new code (the timestamp clusters tell you when).

## "Something is wrong" recipes

### A student says their submission was "accepted but never scored"

1. Pull the `submission_id` they got back from `/submit`.
2. Query Firestore: `submissions/{submission_id}` — does the document exist?
   - Yes, with a `final_score`: scoring worked, the student is reading the
     wrong place. Direct them to `/competitions/{track_id}` Leaderboard tab.
   - Yes, with `error: "..."`: the scorer ran but failed. The error string
     is human-readable.
   - No: the request never made it to the worker. Check Cloud Tasks queue:

      ```bash
      gcloud tasks queues describe d4-arena-submissions \
        --location=us-central1 --project=ai-arena-platform
      ```

3. If Cloud Tasks shows queued tasks piling up, the worker has stopped
   accepting traffic. Check the latest revision health:

   ```bash
   curl https://d4-arena-api-77646749251.us-central1.run.app/health
   ```

### "All my judge calls just started failing"

```
resource.type="cloud_run_revision"
jsonPayload.event="judge_retry"
timestamp >= timestamp_sub(timestamp_now(), interval 30 minute)
```

If retries are spiking, Anthropic is throttling or down. Confirm at
[status.anthropic.com](https://status.anthropic.com). The judge wrapper
already retries with exponential backoff — students see HTTP 200 on
`/submit` regardless, but their `final_score` may show `null` with a
populated `error` field if all retries fail.

### "I need to stop everything right now"

```powershell
# Empties the Anthropic API key — judge wrapper raises a clean error,
# /submit returns 503, students see a meaningful message.
"" | pwsh ./scripts/rotate_secret.ps1 -Name anthropic-api-key
```

Tracks 1 and 4 keep working (they don't call the judge). To restore:

```powershell
"sk-ant-..." | pwsh ./scripts/rotate_secret.ps1 -Name anthropic-api-key
```

### "The leaderboard shows wrong scores"

Server-side leaderboard rendering reads from
`leaderboard/{track_id}/entries/{student_id}` in Firestore (latest-best-wins
per student). If a student's entry looks wrong:

```bash
gcloud firestore documents export gs://ai-arena-platform-firestore-backup \
  --project=ai-arena-platform \
  --collection-ids=submissions,leaderboard
```

Then download and grep for the `student_id`. The full submission history
shows whether the platform actually scored their best submission as best.

## Routine maintenance

| Cadence | Task |
|---|---|
| Pre-bootcamp Day −1 | Rotate `anthropic-api-key`, `canvas-api-token`, `canvas-webhook-secret` (`scripts/rotate_secret.ps1`). Verify Anthropic workspace monthly cap is set ($500 recommended; manual in console). |
| Daily during bootcamp | Glance at the dashboard. Token-budget bounces > 0 means at least one student needs attention. |
| Weekly during bootcamp | Cloud Logging retention is 30 days by default — fine for the bootcamp. Export to BigQuery if you want longer history. |
| Post-bootcamp Day +1 | Rotate `anthropic-api-key` again (revoke the bootcamp key). Optionally delete `submissions/*` after exporting aggregate stats. |
