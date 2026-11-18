@echo off
setlocal

set "ROOT=%~dp0"
set "BACKEND_DIR=%ROOT%backend"
set "FRONTEND_DIR=%ROOT%frontend"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5173"
set "BACKEND_URL=http://127.0.0.1:%BACKEND_PORT%"
set "FRONTEND_URL=http://127.0.0.1:%FRONTEND_PORT%"

cd /d "%ROOT%"

echo.
echo ========================================
echo   Personal Toolbox - Dev Server Launcher
echo ========================================
echo.

REM ---------- Preflight ----------
set "HAS_ERROR="

if not exist "%BACKEND_DIR%\.venv\Scripts\python.exe" (
    set "HAS_ERROR=1"
    echo [ERROR] Backend virtual environment not found.
    echo         Create it with:
    echo           python -m venv backend\.venv
    echo           backend\.venv\Scripts\pip install -r backend\requirements.txt
    echo.
)

where node >nul 2>&1
if errorlevel 1 (
    set "HAS_ERROR=1"
    echo [ERROR] Node.js not found in PATH.
    echo         Install from https://nodejs.org
    echo.
)

where npm >nul 2>&1
if errorlevel 1 (
    set "HAS_ERROR=1"
    echo [ERROR] npm not found in PATH.
    echo.
)

if not exist "%FRONTEND_DIR%\node_modules" (
    set "HAS_ERROR=1"
    echo [ERROR] Frontend dependencies not installed.
    echo         Run: cd frontend ^&^& npm install
    echo.
)

if defined HAS_ERROR (
    echo Preflight failed. Fix the issues above and run start.bat again.
    echo.
    pause
    exit /b 1
)

echo [OK] Environment checks passed.
echo.

REM ---------- Launch backend ----------
REM Use pushd so the new cmd window inherits the correct working directory,
REM avoiding nested-quote hell in the cmd /k command.
echo [START] Backend (port %BACKEND_PORT%) ...
pushd "%BACKEND_DIR%"
start "Personal Toolbox - Backend" cmd /k ".\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port %BACKEND_PORT%"
popd

REM ---------- Launch frontend ----------
echo [START] Frontend (port %FRONTEND_PORT%) ...
pushd "%FRONTEND_DIR%"
start "Personal Toolbox - Frontend" cmd /k "npm.cmd run dev"
popd

echo.

REM ---------- Wait for BOTH services, verify identity, then open browser ----------
echo Waiting for services to become ready ...

powershell -NoProfile -Command ^
  "$max=40; $interval=3; $b=$false; $f=$false;" ^
  "for($i=0;$i -lt $max -and (-not $b -or -not $f);$i++){" ^
  "  if(-not $b){" ^
  "    try{" ^
  "      $r=Invoke-WebRequest -Uri '%BACKEND_URL%/openapi.json' -UseBasicParsing -TimeoutSec 2;" ^
  "      if($r.StatusCode -eq 200 -and $r.Content -match '/api/pdf-to-word/convert'){$b=$true;Write-Host '[OK] Backend ready (Personal Toolbox)' -ForegroundColor Green}" ^
  "    }catch{};" ^
  "  };" ^
  "  if(-not $f){" ^
  "    try{" ^
  "      $r=Invoke-WebRequest -Uri '%FRONTEND_URL%' -UseBasicParsing -TimeoutSec 2;" ^
  "      if($r.StatusCode -eq 200 -and $r.Content -match 'Personal Toolbox'){$f=$true;Write-Host '[OK] Frontend ready (Personal Toolbox)' -ForegroundColor Green}" ^
  "    }catch{};" ^
  "  };" ^
  "  if(-not $b -or -not $f){Start-Sleep -Seconds $interval}" ^
  "};" ^
  "$ok=$true;" ^
  "if(-not $b){Write-Host '[FAIL] Backend did not become ready in time.' -ForegroundColor Red; $ok=$false};" ^
  "if(-not $f){Write-Host '[FAIL] Frontend did not become ready in time.' -ForegroundColor Red; $ok=$false};" ^
  "if(-not $ok){exit 1}else{" ^
  "  Start-Process '%FRONTEND_URL%';" ^
  "  Write-Host ''; Write-Host 'Both servers are up. Browser opened.'}"

if errorlevel 1 (
    echo.
    echo One or both services failed to start.
    echo Check the Backend/Frontend cmd windows for error messages.
    echo.
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Both services running.
echo   Browser opened at %FRONTEND_URL%
echo   Close the Backend/Frontend windows
echo   to stop the servers.
echo ========================================
echo.
exit /b 0
