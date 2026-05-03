# Deploy AI Arena FastAPI to Cloud Run.
#
# Two-phase deploy:
#   1. First pass: deploy with EVALUATOR_TARGET_URL=""  (queue runs in local
#      mode inside the container — fine for the very first deploy where the
#      service URL is not yet known).
#   2. After the deploy reports the service URL, redeploy with
#      EVALUATOR_TARGET_URL=<service-url>/internal/evaluate so Cloud Tasks
#      can dispatch real HTTP tasks to the worker route.
#
# The script does both passes in one run; the second redeploy is fast.

$ErrorActionPreference = "Stop"

# Run from repo root regardless of where the user invoked us from. Critical
# for `--source .` which uploads the cwd to Cloud Build.
$RepoRoot = (Resolve-Path "$PSScriptRoot/..").Path
Set-Location $RepoRoot
Write-Host "==> Working from: $RepoRoot"

$ProjectId   = "ai-arena-platform"
$Region      = "us-central1"
$ServiceName = "d4-arena-api"
$RuntimeSA   = "d4-arena-runtime@$ProjectId.iam.gserviceaccount.com"
$InvokerSA   = "d4-arena-tasks-invoker@$ProjectId.iam.gserviceaccount.com"
$QueueId     = "d4-arena-submissions"

Write-Host "==> Pass 1: deploy from source"
gcloud run deploy $ServiceName `
  --source . `
  --region $Region `
  --project $ProjectId `
  --service-account $RuntimeSA `
  --allow-unauthenticated `
  --set-env-vars "GCP_PROJECT_ID=$ProjectId,GCP_REGION=$Region,TASKS_QUEUE_ID=$QueueId,TASKS_INVOKER_SA=$InvokerSA,ARENA_LOCAL_DEV=0" `
  --set-secrets "CANVAS_API_TOKEN=canvas-api-token:latest,CANVAS_WEBHOOK_SECRET=canvas-webhook-secret:latest,ANTHROPIC_API_KEY=anthropic-api-key:latest" `
  --quiet

$ServiceUrl = gcloud run services describe $ServiceName --region $Region --project $ProjectId --format="value(status.url)"
Write-Host "    Service URL: $ServiceUrl"

$EvaluatorUrl = "$ServiceUrl/internal/evaluate"
Write-Host "==> Pass 2: redeploy with EVALUATOR_TARGET_URL=$EvaluatorUrl"
gcloud run services update $ServiceName `
  --region $Region `
  --project $ProjectId `
  --update-env-vars "EVALUATOR_TARGET_URL=$EvaluatorUrl" `
  --quiet

Write-Host "==> Granting Cloud Tasks invoker SA permission to call the worker route"
gcloud run services add-iam-policy-binding $ServiceName `
  --region $Region --project $ProjectId `
  --member "serviceAccount:$InvokerSA" `
  --role "roles/run.invoker" --quiet | Out-Null

Write-Host ""
Write-Host "==> Deploy complete."
Write-Host ""
Write-Host "Smoke-test:"
Write-Host "  curl $ServiceUrl/health"
Write-Host "  curl -X POST $ServiceUrl/submit -H 'Content-Type: application/json' --data-binary `@tests/fixtures/sample_hallucination.json"
Write-Host "  curl $ServiceUrl/leaderboard/hallucination_hunter"
