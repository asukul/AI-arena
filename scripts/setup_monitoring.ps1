#requires -Version 7
<#
.SYNOPSIS
    Create log-based metrics + a Cloud Monitoring dashboard for AI Arena.

.DESCRIPTION
    The structured logger in api/logging_config.py emits JSON to stdout, which
    Cloud Logging auto-parses. This script captures the events worth tracking
    as log-based metrics so they show up as graphable time-series in Cloud
    Monitoring, then assembles them into a single dashboard.

    Idempotent — re-running will recreate the metrics and dashboard with the
    latest definitions.

    Required permissions on the project:
      roles/logging.configWriter
      roles/monitoring.dashboardEditor

.PARAMETER ProjectId
    GCP project. Defaults to ai-arena-platform.

.EXAMPLE
    pwsh ./scripts/setup_monitoring.ps1
#>

[CmdletBinding()]
param(
    [string]$ProjectId = 'ai-arena-platform'
)

$ErrorActionPreference = 'Stop'

Write-Host "==> Project: $ProjectId"

# ---------- Log-based metrics ----------
#
# Each metric counts a specific structured-log event. Recreating an existing
# metric requires `gcloud logging metrics update`, but `create` after a
# `delete` is simpler and doesn't lose anything (metrics are stateless
# definitions; the data lives in the underlying log entries).

function New-LogMetric {
    param(
        [string]$Name,
        [string]$Description,
        [string]$Filter,
        [string]$LabelName = "",
        [string]$LabelExtractor = ""
    )

    Write-Host "==> Metric: $Name"

    # Idempotent: delete-if-exists, then create.
    & gcloud logging metrics delete $Name --project=$ProjectId --quiet 2>$null

    $args = @(
        "logging", "metrics", "create", $Name,
        "--project=$ProjectId",
        "--description=$Description",
        "--log-filter=$Filter",
        "--quiet"
    )

    & gcloud @args
    if ($LASTEXITCODE -ne 0) { throw "gcloud logging metrics create $Name failed" }
}

# All four metrics are scoped to the d4-arena-api Cloud Run service so logs
# from other services in the project don't pollute the counts.
$ServiceFilter = 'resource.type="cloud_run_revision" AND resource.labels.service_name="d4-arena-api"'

New-LogMetric `
    -Name "arena_submissions_received" `
    -Description "POST /submit requests reaching the d4-arena-api service." `
    -Filter "$ServiceFilter AND httpRequest.requestMethod=`"POST`" AND httpRequest.requestUrl:`"/submit`""

New-LogMetric `
    -Name "arena_judge_calls" `
    -Description "Successful Anthropic judge calls (one per scored item on Tracks 2/3)." `
    -Filter "$ServiceFilter AND jsonPayload.event=`"judge_call`""

New-LogMetric `
    -Name "arena_judge_retries" `
    -Description "Judge calls that were retried after a transient failure." `
    -Filter "$ServiceFilter AND jsonPayload.event=`"judge_retry`""

New-LogMetric `
    -Name "arena_token_budget_exceeded" `
    -Description "Per-student daily token budget hits — students bouncing off the cap." `
    -Filter "$ServiceFilter AND jsonPayload.event=`"token_budget_exceeded`""

New-LogMetric `
    -Name "arena_errors_5xx" `
    -Description "5xx responses from d4-arena-api (real failures, not 4xx user errors)." `
    -Filter "$ServiceFilter AND httpRequest.status>=500"

# ---------- Cloud Monitoring dashboard ----------
#
# The dashboard JSON is assembled inline so the source of truth is this
# script — no separate file to drift out of sync.

$DashboardJson = @'
{
  "displayName": "AI Arena — Operations",
  "mosaicLayout": {
    "columns": 12,
    "tiles": [
      {
        "width": 6, "height": 4, "xPos": 0, "yPos": 0,
        "widget": {
          "title": "Submissions / min",
          "xyChart": {
            "dataSets": [{
              "timeSeriesQuery": {
                "timeSeriesFilter": {
                  "filter": "metric.type=\"logging.googleapis.com/user/arena_submissions_received\" AND resource.type=\"cloud_run_revision\"",
                  "aggregation": {
                    "alignmentPeriod": "60s",
                    "perSeriesAligner": "ALIGN_RATE"
                  }
                }
              },
              "plotType": "LINE"
            }]
          }
        }
      },
      {
        "width": 6, "height": 4, "xPos": 6, "yPos": 0,
        "widget": {
          "title": "Judge calls / min",
          "xyChart": {
            "dataSets": [{
              "timeSeriesQuery": {
                "timeSeriesFilter": {
                  "filter": "metric.type=\"logging.googleapis.com/user/arena_judge_calls\" AND resource.type=\"cloud_run_revision\"",
                  "aggregation": {
                    "alignmentPeriod": "60s",
                    "perSeriesAligner": "ALIGN_RATE"
                  }
                }
              },
              "plotType": "LINE"
            }]
          }
        }
      },
      {
        "width": 6, "height": 4, "xPos": 0, "yPos": 4,
        "widget": {
          "title": "5xx errors / hour",
          "xyChart": {
            "dataSets": [{
              "timeSeriesQuery": {
                "timeSeriesFilter": {
                  "filter": "metric.type=\"logging.googleapis.com/user/arena_errors_5xx\" AND resource.type=\"cloud_run_revision\"",
                  "aggregation": {
                    "alignmentPeriod": "3600s",
                    "perSeriesAligner": "ALIGN_DELTA"
                  }
                }
              },
              "plotType": "LINE"
            }]
          }
        }
      },
      {
        "width": 6, "height": 4, "xPos": 6, "yPos": 4,
        "widget": {
          "title": "Token-budget bounces / hour",
          "xyChart": {
            "dataSets": [{
              "timeSeriesQuery": {
                "timeSeriesFilter": {
                  "filter": "metric.type=\"logging.googleapis.com/user/arena_token_budget_exceeded\" AND resource.type=\"cloud_run_revision\"",
                  "aggregation": {
                    "alignmentPeriod": "3600s",
                    "perSeriesAligner": "ALIGN_DELTA"
                  }
                }
              },
              "plotType": "LINE"
            }]
          }
        }
      },
      {
        "width": 12, "height": 4, "xPos": 0, "yPos": 8,
        "widget": {
          "title": "Cloud Run request latency (p50 / p95 / p99)",
          "xyChart": {
            "dataSets": [
              {
                "timeSeriesQuery": {
                  "timeSeriesFilter": {
                    "filter": "metric.type=\"run.googleapis.com/request_latencies\" AND resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"d4-arena-api\"",
                    "aggregation": {
                      "alignmentPeriod": "60s",
                      "perSeriesAligner": "ALIGN_PERCENTILE_50"
                    }
                  }
                },
                "plotType": "LINE",
                "legendTemplate": "p50"
              },
              {
                "timeSeriesQuery": {
                  "timeSeriesFilter": {
                    "filter": "metric.type=\"run.googleapis.com/request_latencies\" AND resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"d4-arena-api\"",
                    "aggregation": {
                      "alignmentPeriod": "60s",
                      "perSeriesAligner": "ALIGN_PERCENTILE_95"
                    }
                  }
                },
                "plotType": "LINE",
                "legendTemplate": "p95"
              },
              {
                "timeSeriesQuery": {
                  "timeSeriesFilter": {
                    "filter": "metric.type=\"run.googleapis.com/request_latencies\" AND resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"d4-arena-api\"",
                    "aggregation": {
                      "alignmentPeriod": "60s",
                      "perSeriesAligner": "ALIGN_PERCENTILE_99"
                    }
                  }
                },
                "plotType": "LINE",
                "legendTemplate": "p99"
              }
            ]
          }
        }
      }
    ]
  }
}
'@

Write-Host "==> Creating / updating Cloud Monitoring dashboard..."

$tmp = [System.IO.Path]::GetTempFileName()
try {
    [System.IO.File]::WriteAllText($tmp, $DashboardJson, (New-Object System.Text.UTF8Encoding $false))

    # If a dashboard with this displayName already exists, update it; otherwise create.
    $existing = & gcloud monitoring dashboards list `
        --project=$ProjectId `
        --filter="displayName=`"AI Arena — Operations`"" `
        --format="value(name)" 2>$null

    if ($existing) {
        Write-Host "    Existing dashboard: $existing — updating..."
        & gcloud monitoring dashboards update $existing `
            --config-from-file=$tmp `
            --project=$ProjectId `
            --quiet
    } else {
        & gcloud monitoring dashboards create `
            --config-from-file=$tmp `
            --project=$ProjectId `
            --quiet
    }
    if ($LASTEXITCODE -ne 0) { throw "monitoring dashboards create/update failed" }
} finally {
    Remove-Item -Force -LiteralPath $tmp
}

Write-Host ""
Write-Host "==> Done."
Write-Host ""
Write-Host "    View the dashboard:"
Write-Host "      https://console.cloud.google.com/monitoring/dashboards?project=$ProjectId"
Write-Host ""
Write-Host "    Saved Logs Explorer queries are documented in docs/operations.md."
