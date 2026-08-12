@echo off
title OrbitalMind Platform
color 0A

echo.
echo  ============================================================
echo   OrbitalMind — Multi-Disaster Intelligence Platform v2.0
echo  ============================================================
echo.

:: ── Check Python availability ────────────────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] Python not found. Please install Python 3.10+
    pause & exit /b 1
)

:: ── Check if dist/ exists (production build) ─────────────────────────────────
if not exist "%~dp0frontend\dist\index.html" (
    echo  [INFO] Production build not found. Building frontend...
    echo.
    cd /d "%~dp0frontend"
    call npm run build
    if %errorlevel% neq 0 (
        echo  [ERROR] Frontend build failed. Run: cd frontend ^&^& npm run build
        pause & exit /b 1
    )
    cd /d "%~dp0"
    echo.
)

:: ── Activate virtual environment if present ──────────────────────────────────
if exist "%~dp0.venv\Scripts\activate.bat" (
    echo  [INFO] Activating virtual environment...
    call "%~dp0.venv\Scripts\activate.bat"
) else if exist "%~dp0venv\Scripts\activate.bat" (
    call "%~dp0venv\Scripts\activate.bat"
)

:: ── Start the server ──────────────────────────────────────────────────────────
echo  Starting OrbitalMind server...
echo  URL  : http://localhost:8000
echo  API  : http://localhost:8000/docs
echo  Press Ctrl+C to stop.
echo.

:: Open browser after 2 second delay (server needs a moment to start)
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000"

:: Start uvicorn from repo root so relative imports resolve correctly
cd /d "%~dp0"
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

pause
