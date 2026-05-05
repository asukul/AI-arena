#requires -Version 7
<#
.SYNOPSIS
    Rotate a Secret Manager secret used by AI Arena and force Cloud Run to pick up the new value.

.DESCRIPTION
    Creates a new version of the named secret in GCP Secret Manager, then bumps
    a no-op env var on the d4-arena-api Cloud Run service so the next request
    triggers a cold start and re-reads the secret.

    The new value is read from STDIN (so it never lands in shell history or on
    disk). Pipe the value in:

      "sk-ant-..." | pwsh ./scripts/rotate_secret.ps1 -Name anthropic-api-key

    Or read from a file (less safe — the file lingers):

      Get-Content C:\path\to\new_key.txt -Raw | pwsh ./scripts/rotate_secret.ps1 -Name anthropic-api-key

    To kill judge calls in an emergency, pass an empty value (the wrapper
    raises a clean error and /submit returns HTTP 503 instead of burning tokens):

      "" | pwsh ./scripts/rotate_secret.ps1 -Name anthropic-api-key

.PARAMETER Name
    Secret Manager secret name. Must be one of the AI Arena managed secrets.

.PARAMETER ProjectId
    GCP project. Defaults to ai-arena-platform.

.PARAMETER ServiceName
    Cloud Run service to bump. Defaults to d4-arena-api.

.PARAMETER Region
    Cloud Run region. Defaults to us-central1.

.EXAMPLE
    "sk-ant-newkey..." | pwsh ./scripts/rotate_secret.ps1 -Name anthropic-api-key

.NOTES
    Documented in docs/api_key_policy.md. Old versions stay enabled by default
    so you can roll back; disable them in the Secret Manager console once the
    new version is confirmed serving.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('anthropic-api-key', 'canvas-api-token', 'canvas-webhook-secret')]
    [string]$Name,

    [string]$ProjectId   = 'ai-arena-platform',
    [string]$ServiceName = 'd4-arena-api',
    [string]$Region      = 'us-central1'
)

$ErrorActionPreference = 'Stop'

# 1. Read the new value from stdin. PowerShell's $input is the pipeline; -Raw
#    keeps any embedded newlines intact (some tokens have trailing newlines —
#    we strip just one trailing newline at the end, which is what `echo $value`
#    would feed in via heredoc).
$value = ($input | Out-String)
if ($value.EndsWith("`r`n")) { $value = $value.Substring(0, $value.Length - 2) }
elseif ($value.EndsWith("`n")) { $value = $value.Substring(0, $value.Length - 1) }

if ($value.Length -eq 0) {
    Write-Warning "Empty value piped in. This will disable the secret — '/submit' will start returning errors."
    Write-Warning "If this is intentional (emergency off-switch), continuing in 5 seconds. Ctrl-C to abort."
    Start-Sleep -Seconds 5
}

Write-Host "==> Adding new version to secret '$Name' in project '$ProjectId'..."

# Pipe the value to gcloud via stdin (--data-file=-). Use a temp file as the
# bridge because gcloud's stdin handling on Windows PowerShell is unreliable
# for binary pipes; .NET's StreamWriter is consistent.
$tmp = [System.IO.Path]::GetTempFileName()
try {
    [System.IO.File]::WriteAllText($tmp, $value, (New-Object System.Text.UTF8Encoding $false))
    & gcloud secrets versions add $Name `
        --project=$ProjectId `
        --data-file=$tmp
    if ($LASTEXITCODE -ne 0) { throw "gcloud secrets versions add failed (exit $LASTEXITCODE)" }
} finally {
    Remove-Item -Force -LiteralPath $tmp
}

Write-Host "==> Bumping env var on Cloud Run service '$ServiceName' to force a re-read..."
# A timestamp env var on the runtime forces a new revision so secrets re-mount.
$ts = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
& gcloud run services update $ServiceName `
    --region=$Region `
    --project=$ProjectId `
    --update-env-vars "_SECRETS_REFRESHED=$ts" `
    --quiet
if ($LASTEXITCODE -ne 0) { throw "gcloud run services update failed (exit $LASTEXITCODE)" }

Write-Host ""
Write-Host "==> Done. Verify the new key works:"
Write-Host "      Invoke-RestMethod ""https://$ServiceName-77646749251.$Region.run.app/health"""
Write-Host ""
Write-Host "    Old version stays enabled — disable it in the Secret Manager console"
Write-Host "    once the new key is confirmed serving:"
Write-Host "      https://console.cloud.google.com/security/secret-manager/secret/$Name/versions?project=$ProjectId"
