# Boot-resilience for the paper-trading pipeline. Runs at Windows logon (via a
# shim in the user's Startup folder) and brings the whole stack back up:
#   1. API server (scripts/run_api.py) if it isn't already answering /health
#   2. HD recorder (15+60 min windows)   — via the API, 409 = already running, fine
#   3. Paper trader (60-min rule, $10/clock-window) — same idempotent start
#
# Why this exists: on July 5 a reboot silently killed the recorder, so the July
# 6-7 losing days have no tick data and could never be forensically replayed.
# Daemons must never depend on a human remembering to restart them.
#
# Install (one-time, no admin needed): copy scripts\autostart.cmd to
#   shell:startup  (C:\Users\<you>\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup)
# Manual run to test:  powershell -ExecutionPolicy Bypass -File scripts\autostart.ps1

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot   # project root (this file lives in scripts/)
$py   = Join-Path $root ".venv\Scripts\python.exe"
$api  = "http://localhost:8040"
$log  = Join-Path $root "logs\autostart.log"

New-Item -ItemType Directory -Force (Join-Path $root "logs") | Out-Null
function Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg"
    Add-Content -Path $log -Value $line
}

function Healthy {
    try { (Invoke-RestMethod "$api/health" -TimeoutSec 3).status -eq "ok" } catch { $false }
}

Log "autostart fired"

# --- 1. API server ---
if (-not (Healthy)) {
    Log "API down - launching run_api.py"
    Start-Process -FilePath $py -ArgumentList "scripts\run_api.py" -WorkingDirectory $root -WindowStyle Hidden
    # Wait for it (network stack can be slow right after boot - retry ~3 min)
    $up = $false
    for ($i = 0; $i -lt 36; $i++) {
        Start-Sleep -Seconds 5
        if (Healthy) { $up = $true; break }
    }
    if (-not $up) { Log "GAVE UP waiting for API - daemons not started"; exit 1 }
    Log "API is up"
} else {
    Log "API already healthy"
}

# --- 2. Recorder + 3. Paper trader (409 Conflict = already running - fine) ---
foreach ($job in @(
    # recorder REMOVED from autostart (July 14, user request - disk pressure).
    # To record again: mm start (one-off) or restore the line below.
    # @{ name = "recorder";   url = "$api/hd/recorder/start"; body = '{"assets":["Bitcoin","Ethereum","Solana","XRP"],"windows":[15,60]}' },
    @{ name = "paper trader"; url = "$api/paper/start";       body = '{"windows":[60],"stake":10}' }
)) {
    try {
        Invoke-RestMethod -Method Post -Uri $job.url -ContentType "application/json" -Body $job.body -TimeoutSec 10 | Out-Null
        Log "$($job.name) started"
    } catch {
        $code = $null
        try { $code = [int]$_.Exception.Response.StatusCode } catch {}
        if ($code -eq 409) { Log "$($job.name) already running" }
        else { Log "$($job.name) FAILED to start: $($_.Exception.Message)" }
    }
}
Log "autostart done"
