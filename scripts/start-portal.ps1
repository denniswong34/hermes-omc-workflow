#Requires -Version 5.1
<#
.SYNOPSIS
  Start the OMC Agentic OS portal (API + Next.js UI).

.DESCRIPTION
  Launches:
    - FastAPI control plane  → http://127.0.0.1:8787  (OMC_API_HOST / OMC_API_PORT)
    - Next.js agent portal   → http://127.0.0.1:3000

  PIDs and logs live under .run/
  Loads repo-root .env into the process environment when present.

.EXAMPLE
  .\scripts\start-portal.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$RunDir = Join-Path $RepoRoot ".run"
$UiDir = Join-Path $RepoRoot "apps\agentic-os"
$ApiPidFile = Join-Path $RunDir "api.pid"
$UiPidFile = Join-Path $RunDir "ui.pid"
$ApiLog = Join-Path $RunDir "api.log"
$ApiErrLog = Join-Path $RunDir "api.err.log"
$UiLog = Join-Path $RunDir "ui.log"
$UiErrLog = Join-Path $RunDir "ui.err.log"

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or $line -notmatch "=") { return }
        $key, $value = $line.Split("=", 2)
        $key = $key.Trim()
        $value = $value.Trim().Trim('"').Trim("'")
        if ($key -and -not [string]::IsNullOrWhiteSpace($value) -and -not (Test-Path "Env:$key")) {
            Set-Item -Path "Env:$key" -Value $value
        }
    }
}

function Test-PidAlive {
    param([int]$ProcessId)
    try {
        $p = Get-Process -Id $ProcessId -ErrorAction Stop
        return -not $p.HasExited
    } catch {
        return $false
    }
}

function Get-ListeningPid {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($conn) { return [int]$conn.OwningProcess }
    return $null
}

function Assert-NotRunning {
    param(
        [string]$Name,
        [string]$PidFile,
        [int]$Port
    )
    if (Test-Path $PidFile) {
        $existing = [int](Get-Content $PidFile -Raw).Trim()
        if (Test-PidAlive $existing) {
            Write-Host "$Name already running (pid $existing). Use .\scripts\stop-portal.ps1 first."
            exit 1
        }
        Remove-Item $PidFile -Force
    }
    $portPid = Get-ListeningPid -Port $Port
    if ($portPid) {
        Write-Host "$Name port $Port already in use by pid $portPid. Stop that process or change the port."
        exit 1
    }
}

New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
Import-DotEnv (Join-Path $RepoRoot ".env")

if (-not $env:OMC_API_HOST) { $env:OMC_API_HOST = "127.0.0.1" }
if (-not $env:OMC_API_PORT) { $env:OMC_API_PORT = "8787" }
if (-not $env:OMC_UI_PORT) { $env:OMC_UI_PORT = "3000" }

$ApiHost = $env:OMC_API_HOST
$ApiPort = [int]$env:OMC_API_PORT
$UiPort = [int]$env:OMC_UI_PORT
$ApiBase = "http://${ApiHost}:${ApiPort}"
$env:NEXT_PUBLIC_API_BASE = $ApiBase

# Keep Next.js .env.local aligned with the API we actually start.
# A stale NEXT_PUBLIC_API_BASE (e.g. :8790) causes browser "Failed to fetch".
$UiEnvLocal = Join-Path $UiDir ".env.local"
$desiredEnv = "NEXT_PUBLIC_API_BASE=$ApiBase"
$currentEnv = if (Test-Path $UiEnvLocal) { (Get-Content $UiEnvLocal -Raw).Trim() } else { "" }
if ($currentEnv -ne $desiredEnv) {
    Set-Content -Path $UiEnvLocal -Value "$desiredEnv`n" -NoNewline
    Write-Host "Updated apps/agentic-os/.env.local → $ApiBase"
}

Assert-NotRunning -Name "API" -PidFile $ApiPidFile -Port $ApiPort
Assert-NotRunning -Name "UI" -PidFile $UiPidFile -Port $UiPort

$Python = if ($env:OMC_PYTHON) {
    $env:OMC_PYTHON
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    (Get-Command python).Source
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    (Get-Command py).Source
} else {
    throw "Python not found. Install Python or set OMC_PYTHON."
}

if (-not $SkipInstall) {
    if (-not (Test-Path (Join-Path $UiDir "node_modules"))) {
        Write-Host "Installing UI dependencies..."
        Push-Location $UiDir
        try {
            npm install
            if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
        } finally {
            Pop-Location
        }
    }
}

Write-Host "Starting API on $ApiBase ..."
$api = Start-Process -FilePath $Python `
    -ArgumentList @("-m", "apps.api.main") `
    -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput $ApiLog `
    -RedirectStandardError $ApiErrLog `
    -PassThru `
    -WindowStyle Hidden
Set-Content -Path $ApiPidFile -Value $api.Id -NoNewline

Write-Host "Starting UI on http://127.0.0.1:${UiPort} ..."
# npm.cmd cannot use RedirectStandard* reliably; shell-redirect via cmd.exe instead.
$uiCmd = "npm run dev -- -p $UiPort > `"$UiLog`" 2> `"$UiErrLog`""
$ui = Start-Process -FilePath "cmd.exe" `
    -ArgumentList @("/c", $uiCmd) `
    -WorkingDirectory $UiDir `
    -PassThru `
    -WindowStyle Hidden
Set-Content -Path $UiPidFile -Value $ui.Id -NoNewline

# Brief readiness check
$deadline = (Get-Date).AddSeconds(20)
$apiUp = $false
while ((Get-Date) -lt $deadline) {
    if (-not (Test-PidAlive $api.Id)) {
        Write-Host "API exited early. See $ApiLog"
        exit 1
    }
    try {
        $resp = Invoke-WebRequest -Uri "$ApiBase/api/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
            $apiUp = $true
            break
        }
    } catch {
        Start-Sleep -Milliseconds 500
    }
}

Write-Host ""
Write-Host "OMC Agent Portal started"
Write-Host "  API  $ApiBase   (pid $($api.Id), log $ApiLog)"
Write-Host "  UI   http://127.0.0.1:${UiPort}  (pid $($ui.Id), log $UiLog)"
if (-not $apiUp) {
    Write-Host "  Note: API health check not confirmed yet — check $ApiLog if the UI cannot reach the API."
}
Write-Host ""
Write-Host "Stop with: .\scripts\stop-portal.ps1"
