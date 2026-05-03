# Idempotent GCP bootstrap for AI Arena.
#
# Run once per GCP project. Re-running is safe — every step skips if the
# resource already exists. After this finishes, run scripts/deploy.ps1 to
# build and deploy the FastAPI service to Cloud Run.
#
# Prereqs:
#   - gcloud SDK installed and authenticated:  gcloud auth login
#   - Billing enabled on the project (Firestore + Cloud Run require it)
#
# Usage:
#   pwsh ./scripts/bootstrap_gcp.ps1

$ErrorActionPreference = "Stop"

# Run from repo root regardless of where the user invoked us from.
$RepoRoot = (Resolve-Path "$PSScriptRoot/..").Path
Set-Location $RepoRoot
Write-Host "==> Working from: $RepoRoot"

# ---- Settings (mirror these in api/config.py / .env) ----
$ProjectId   = "ai-arena-platform"
$Region      = "us-central1"
$QueueId     = "d4-arena-submissions"
$RuntimeSA   = "d4-arena-runtime"
$InvokerSA   = "d4-arena-tasks-invoker"
$ServiceName = "d4-arena-api"

Write-Host "==> Setting active project: $ProjectId"
gcloud config set project $ProjectId | Out-Null

Write-Host "==> Enabling APIs (idempotent — may take a minute)"
# Bulk enable (`gcloud services enable api1 api2 ...`) intermittently fails
# on new projects with PERMISSION_DENIED on the entire batch even when the
# caller is Owner. Looping one at a time avoids the quirk.
$apis = @(
  "cloudresourcemanager.googleapis.com",
  "run.googleapis.com",
  "cloudtasks.googleapis.com",
  "firestore.googleapis.com",
  "cloudbuild.googleapis.com",
  "artifactregistry.googleapis.com",
  "secretmanager.googleapis.com",
  "cloudscheduler.googleapis.com",
  "logging.googleapis.com"
)
foreach ($api in $apis) {
    Write-Host "    enabling $api"
    gcloud services enable $api --project=$ProjectId --quiet
}

# ---- Firestore (native mode, default DB) ----
Write-Host "==> Ensuring Firestore native database in $Region"
$dbExists = gcloud firestore databases list --project=$ProjectId --format="value(name)" 2>$null
if (-not $dbExists) {
    gcloud firestore databases create --location=$Region --type=firestore-native --project=$ProjectId | Out-Null
} else {
    Write-Host "    Firestore database already exists — skipping"
}

# ---- Service accounts ----
function Ensure-SA($name, $description) {
    $email = "$name@$ProjectId.iam.gserviceaccount.com"
    $exists = gcloud iam service-accounts list --project=$ProjectId --filter="email:$email" --format="value(email)" 2>$null
    if (-not $exists) {
        Write-Host "==> Creating service account: $name"
        gcloud iam service-accounts create $name --display-name=$description --project=$ProjectId | Out-Null
    } else {
        Write-Host "==> Service account exists: $name"
    }
    return $email
}

$RuntimeEmail = Ensure-SA $RuntimeSA "AI Arena Cloud Run runtime"
$InvokerEmail = Ensure-SA $InvokerSA "AI Arena Cloud Tasks invoker (OIDC)"

# ---- IAM roles for runtime SA ----
Write-Host "==> Granting IAM roles to runtime SA"
$runtimeRoles = @(
  "roles/datastore.user",            # Firestore read/write
  "roles/cloudtasks.enqueuer",       # enqueue submissions
  "roles/secretmanager.secretAccessor",
  "roles/logging.logWriter"
)
foreach ($role in $runtimeRoles) {
    gcloud projects add-iam-policy-binding $ProjectId `
      --member="serviceAccount:$RuntimeEmail" --role=$role --condition=None | Out-Null
}

# Runtime SA needs to "actAs" invoker SA so Cloud Tasks tasks can be created
# with the invoker SA's OIDC token. Without this, /submit returns 500 with
# "iam.serviceAccounts.actAs" permission denied.
Write-Host "==> Granting runtime SA permission to actAs the invoker SA"
gcloud iam service-accounts add-iam-policy-binding $InvokerEmail `
  --member="serviceAccount:$RuntimeEmail" `
  --role="roles/iam.serviceAccountUser" `
  --project=$ProjectId | Out-Null

# ---- Cloud Tasks queue ----
Write-Host "==> Ensuring Cloud Tasks queue: $QueueId"
$queueExists = gcloud tasks queues describe $QueueId --location=$Region --project=$ProjectId 2>$null
if (-not $queueExists) {
    gcloud tasks queues create $QueueId --location=$Region --project=$ProjectId | Out-Null
} else {
    Write-Host "    Queue already exists — skipping"
}

# ---- Secret Manager placeholders (populate by hand) ----
function Ensure-Secret($name) {
    $exists = gcloud secrets describe $name --project=$ProjectId 2>$null
    if (-not $exists) {
        Write-Host "==> Creating empty secret: $name (populate with: gcloud secrets versions add $name --data-file=...)"
        gcloud secrets create $name --replication-policy=automatic --project=$ProjectId | Out-Null
    } else {
        Write-Host "==> Secret exists: $name"
    }
}
Ensure-Secret "canvas-api-token"
Ensure-Secret "canvas-webhook-secret"

Write-Host ""
Write-Host "==> Bootstrap complete."
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Populate secrets:"
Write-Host "     gcloud secrets versions add canvas-api-token --data-file=path-to-token.txt"
Write-Host "     gcloud secrets versions add canvas-webhook-secret --data-file=path-to-secret.txt"
Write-Host "  2. Deploy:  pwsh ./scripts/deploy.ps1"
Write-Host ""
Write-Host "Runtime SA: $RuntimeEmail"
Write-Host "Invoker SA: $InvokerEmail"
