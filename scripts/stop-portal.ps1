#Requires -Version 5.1
<#
.SYNOPSIS
  Stop the OMC Agentic OS portal (API + Next.js UI).

.DESCRIPTION
  Stops processes tracked in .run/*.pid and falls back to freeing
  OMC_API_PORT / OMC_UI_PORT listeners when PID files are stale.

.EXAMPLE
  .\scripts\stop-portal.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$RunDir = Join-Path $RepoRoot ".run"
$ApiPidFile = Join-Path $RunDir "api.pid"
$UiPidFile = Join-Path $RunDir "ui.pid"

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

function Stop-TrackedProcess {
    param(
        [string]$Name,
        [string]$PidFile
    )
    if (-not (Test-Path $PidFile)) {
        Write-Host "${Name}: no pid file"
        return
    }
    $raw = (Get-Content $PidFile -Raw).Trim()
    if (-not $raw) {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        Write-Host "${Name}: empty pid file removed"
        return
    }
    $processId = [int]$raw
    try {
        $proc = Get-Process -Id $processId -ErrorAction Stop
        Write-Host "${Name}: stopping pid $processId ($($proc.ProcessName))..."
        & taskkill.exe /PID $processId /T /F 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                Where-Object { $_.ParentProcessId -eq $processId } |
                ForEach-Object {
                    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                }
        }
        Start-Sleep -Milliseconds 400
        Write-Host "${Name}: stopped"
    } catch {
        Write-Host "${Name}: pid $processId not running"
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

function Stop-PortListener {
    param(
        [string]$Name,
        [int]$Port
    )
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) {
        Write-Host "${Name}: port $Port free"
        return
    }
    $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($processId in $pids) {
        try {
            $proc = Get-Process -Id $processId -ErrorAction Stop
            Write-Host "${Name}: freeing port $Port (pid $processId, $($proc.ProcessName))..."
            & taskkill.exe /PID $processId /T /F 2>$null | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            }
        } catch {
            Write-Host "${Name}: could not stop pid $processId on port $Port"
        }
    }
}

Import-DotEnv (Join-Path $RepoRoot ".env")
if (-not $env:OMC_API_PORT) { $env:OMC_API_PORT = "8787" }
if (-not $env:OMC_UI_PORT) { $env:OMC_UI_PORT = "3000" }

$ApiPort = [int]$env:OMC_API_PORT
$UiPort = [int]$env:OMC_UI_PORT

Write-Host "Stopping OMC Agent Portal..."
Stop-TrackedProcess -Name "UI" -PidFile $UiPidFile
Stop-TrackedProcess -Name "API" -PidFile $ApiPidFile
Stop-PortListener -Name "UI" -Port $UiPort
Stop-PortListener -Name "API" -Port $ApiPort
Write-Host "Done."
