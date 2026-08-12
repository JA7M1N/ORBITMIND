# OrbitalMind — Demo Backend Startup Script
# ============================================
# Run from the OrbitalMind\ repo root:
#   powershell -ExecutionPolicy Bypass -File scripts\start_demo_backend.ps1

param(
    [string]$Port      = "8000",
    [string]$LogLevel  = "info",
    [switch]$NoBrowser
)

$ErrorActionPreference = "SilentlyContinue"

# ── Colours ────────────────────────────────────────────────────────────────────
function Write-OK    { param($msg) Write-Host "  [  OK  ]  $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "  [ WARN ]  $msg" -ForegroundColor Yellow }
function Write-Fail  { param($msg) Write-Host "  [ FAIL ]  $msg" -ForegroundColor Red }
function Write-Info  { param($msg) Write-Host "  [ INFO ]  $msg" -ForegroundColor Cyan }
function Write-Bar   {
    Write-Host ("=" * 60) -ForegroundColor DarkCyan
}

# ── Banner ─────────────────────────────────────────────────────────────────────
Write-Bar
Write-Host "  OrbitalMind Platform — Demo Backend Startup" -ForegroundColor Cyan
Write-Host "  AI-powered multi-disaster satellite intelligence" -ForegroundColor DarkCyan
Write-Bar
Write-Host ""

# ── STEP 1: Python environment ─────────────────────────────────────────────────
Write-Host "STEP 1 — Python environment" -ForegroundColor White
$pythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonPath) {
    Write-Fail "Python not found. Install Python 3.10+ from python.org"
    exit 1
}
$pythonVersion = python --version 2>&1
Write-OK "Python found: $pythonVersion  ($pythonPath)"

# Check key packages
$packages = @("fastapi", "uvicorn", "asyncpg", "pydantic_settings")
foreach ($pkg in $packages) {
    $check = python -c "import $pkg" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-OK "Package '$pkg' available"
    } else {
        Write-Warn "Package '$pkg' missing — run: pip install -r backend/requirements.txt"
    }
}
Write-Host ""

# ── STEP 2: PostgreSQL ─────────────────────────────────────────────────────────
Write-Host "STEP 2 — PostgreSQL service" -ForegroundColor White
$pgService = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue |
             Where-Object Status -eq "Running" |
             Select-Object -First 1

if ($pgService) {
    Write-OK "PostgreSQL running: $($pgService.Name)"
} else {
    $allPg = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue
    if ($allPg) {
        Write-Warn "PostgreSQL installed but NOT running: $($allPg.Name)"
        Write-Info "Start it: Start-Service $($allPg.Name)"
        Write-Info "Or: net start postgresql-x64-16"
    } else {
        Write-Warn "PostgreSQL service not found"
        Write-Info "Install: https://www.postgresql.org/download/windows/"
    }
    Write-Info "DEMO_MODE=True — API will work without DB using pre-computed data"
}

# Check DB connectivity
$dbCheck = python -c @"
import asyncio, asyncpg
async def check():
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect('postgresql://postgres:postgres@localhost:5432/orbitalmind',
                            statement_cache_size=0), timeout=2)
        ver = await conn.fetchval('SELECT version()')
        await conn.close()
        print('OK:' + ver[:40])
    except Exception as e:
        print('FAIL:' + str(e)[:60])
asyncio.run(check())
"@ 2>&1

if ($dbCheck -like "OK:*") {
    Write-OK "Database 'orbitalmind' reachable: $($dbCheck -replace 'OK:','')"
} else {
    Write-Warn "Database not reachable: $($dbCheck -replace 'FAIL:','')"
    Write-Info "Demo data will be served from disk (DEMO_MODE=True)"
}
Write-Host ""

# ── STEP 3: Ollama LLM ─────────────────────────────────────────────────────────
Write-Host "STEP 3 — Ollama LLM server" -ForegroundColor White
try {
    $ollamaResp = Invoke-WebRequest "http://localhost:11434/api/tags" `
                    -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
    $ollamaData = $ollamaResp.Content | ConvertFrom-Json
    $modelCount = ($ollamaData.models | Measure-Object).Count
    Write-OK "Ollama running — $modelCount model(s) available"

    $hasModel = $ollamaData.models | Where-Object { $_.name -like "llama3.2*" }
    if ($hasModel) {
        Write-OK "llama3.2:3b available — live narration ENABLED"
    } else {
        Write-Warn "llama3.2:3b not found — run: ollama pull llama3.2:3b"
        Write-Info "Fallback narrations will be used (pre-written, still accurate)"
    }
} catch {
    Write-Warn "Ollama not running at http://localhost:11434"
    Write-Info "Start: ollama serve  (install from https://ollama.com/download)"
    Write-Info "Fallback narrations active — narration endpoint still works"
}
Write-Host ""

# ── STEP 4: Demo data check ────────────────────────────────────────────────────
Write-Host "STEP 4 — Demo data files" -ForegroundColor White
$manifestPath = "backend\demo_data\events_manifest.json"
if (Test-Path $manifestPath) {
    $manifest = Get-Content $manifestPath | ConvertFrom-Json
    $eventCount = ($manifest.events | Measure-Object).Count
    Write-OK "events_manifest.json — $eventCount events"
} else {
    Write-Fail "events_manifest.json missing!"
    Write-Info "Run: python scripts/generate_mock_data.py"
}

$demoDirs = @("flood/kerala_2018","wildfire/uttarakhand_2024",
              "landslide/himachal_2023","cyclone/odisha_2023","earthquake/gujarat_2024")
foreach ($dir in $demoDirs) {
    $fullDir = "backend\demo_data\$dir"
    if (Test-Path $fullDir) {
        $files = (Get-ChildItem $fullDir -File).Count
        Write-OK "$dir — $files file(s)"
    } else {
        Write-Warn "$dir — directory missing (run generate_mock_data.py)"
    }
}
Write-Host ""

# ── STEP 5: Port check ─────────────────────────────────────────────────────────
Write-Host "STEP 5 — Port $Port availability" -ForegroundColor White
$portInUse = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($portInUse) {
    Write-Warn "Port $Port already in use (PID: $($portInUse.OwningProcess))"
    Write-Info "Kill it: Stop-Process -Id $($portInUse.OwningProcess) -Force"
    Write-Info "Or use a different port: .\scripts\start_demo_backend.ps1 -Port 8001"
} else {
    Write-OK "Port $Port is free"
}
Write-Host ""

# ── STEP 6: Start server ───────────────────────────────────────────────────────
Write-Bar
Write-Host "  Starting OrbitalMind API on http://localhost:$Port" -ForegroundColor Cyan
Write-Host "  Swagger UI : http://localhost:$Port/docs" -ForegroundColor DarkCyan
Write-Host "  Health     : http://localhost:$Port/health" -ForegroundColor DarkCyan
Write-Host "  Modules    : http://localhost:$Port/api/modules" -ForegroundColor DarkCyan
Write-Bar
Write-Host ""
Write-Host "  Press Ctrl+C to stop the server" -ForegroundColor DarkGray
Write-Host ""

# Small delay so the startup messages appear before uvicorn takes over
Start-Sleep -Milliseconds 500

# Launch uvicorn (blocking — stays in foreground for the demo)
uvicorn backend.main:app --port $Port --log-level $LogLevel --reload
