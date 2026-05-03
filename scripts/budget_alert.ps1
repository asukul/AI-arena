# Create a GCP billing budget alert for AI Arena.
#
# Two thresholds, matching PLAN.md §"Costs and guardrails":
#   $200 — soft alert (email Adisak; bootcamp ops should be looked at)
#   $400 — hard alert (consider pulling the plug on student spend)
#
# Usage:
#   pwsh ./scripts/budget_alert.ps1
#
# Prereqs:
#   - billing API enabled (bootstrap covers it)
#   - billing-account-level role roles/billing.user on the billing account
#   - gcloud auth login (already done if you ran bootstrap)

$ErrorActionPreference = 'Stop'

$ProjectId       = "ai-arena-platform"
$ProjectNumber   = "77646749251"
$BillingAccount  = "015AEC-F205C8-2B91FA"
$BudgetName      = "ai-arena-summer-2026"
$DisplayName     = "AI Arena bootcamp budget"

Write-Host "==> Enabling billing-budgets API"
gcloud services enable billingbudgets.googleapis.com --project=$ProjectId --quiet

Write-Host "==> Listing existing budgets (skip if a matching one already exists)"
$existing = gcloud billing budgets list --billing-account=$BillingAccount --format="value(displayName)" 2>$null
if ($existing -match $DisplayName) {
    Write-Host "    A budget named '$DisplayName' already exists — not duplicating."
    exit 0
}

Write-Host "==> Creating budget: $DisplayName ($1,030 / month with 50% / 90% / 110% alerts)"
gcloud billing budgets create `
  --billing-account=$BillingAccount `
  --display-name=$DisplayName `
  --budget-amount=1030 `
  --filter-projects="projects/$ProjectNumber" `
  --threshold-rule=percent=0.5 `
  --threshold-rule=percent=0.9 `
  --threshold-rule=percent=1.0 `
  --threshold-rule=percent=1.1

Write-Host ""
Write-Host "==> Done. Notifications go to billing-account admin emails by default."
Write-Host ""
Write-Host "To route alerts to a Pub/Sub topic for hard automation (e.g. auto-disable"
Write-Host "billing at \$400), see:"
Write-Host "  https://cloud.google.com/billing/docs/how-to/notify"
