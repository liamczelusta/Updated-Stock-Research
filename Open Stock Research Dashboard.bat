@echo off
setlocal EnableDelayedExpansion

set "APP_DIR=%~dp0"
set "PORT=8765"
set "URL=http://127.0.0.1:%PORT%"
set "LOG_DIR=%LOCALAPPDATA%\StockResearchDashboard\Logs"
set "LOG_FILE=%LOG_DIR%\simple-launcher.log"
set "ERR_FILE=%LOG_DIR%\simple-launcher.err.log"
set "STATE_DIR=%APP_DIR%\.cache"
set "PID_FILE=%STATE_DIR%\stock_research_dashboard.pid"

mkdir "%LOG_DIR%" >nul 2>nul
mkdir "%STATE_DIR%" >nul 2>nul

echo ========================================>> "%LOG_FILE%"
echo %DATE% %TIME% Starting Stock Research Dashboard>> "%LOG_FILE%"
echo Project: %APP_DIR%>> "%LOG_FILE%"

if exist "%APP_DIR%StockResearchDashboard\StockResearchDashboard.exe" (
  start "" "%APP_DIR%StockResearchDashboard\StockResearchDashboard.exe"
  exit /b 0
)

if exist "%APP_DIR%StockResearchDashboard.exe" (
  start "" "%APP_DIR%StockResearchDashboard.exe"
  exit /b 0
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 '%URL%/_stcore/health').StatusCode | Out-Null; exit 0 } catch { exit 1 }"
if %ERRORLEVEL% EQU 0 (
  start "" "%URL%"
  exit /b 0
)

if not exist "%APP_DIR%\.venv\Scripts\python.exe" (
  echo Creating Python environment...
  py -m venv "%APP_DIR%\.venv" >> "%LOG_FILE%" 2>&1
)

if not exist "%APP_DIR%\.venv\Scripts\streamlit.exe" (
  echo Installing app dependencies...
  "%APP_DIR%\.venv\Scripts\python.exe" -m pip install --upgrade pip >> "%LOG_FILE%" 2>&1
  "%APP_DIR%\.venv\Scripts\python.exe" -m pip install -r "%APP_DIR%\requirements.txt" >> "%LOG_FILE%" 2>&1
)

set "PYTHONPATH=%APP_DIR%\src"
set "STREAMLIT_GLOBAL_DEVELOPMENT_MODE=false"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath '%APP_DIR%\.venv\Scripts\streamlit.exe' -ArgumentList @('run','%APP_DIR%\app.py','--global.developmentMode=false','--server.headless=true','--server.address=127.0.0.1','--server.port=%PORT%','--browser.gatherUsageStats=false') -WorkingDirectory '%APP_DIR%' -RedirectStandardOutput '%LOG_FILE%' -RedirectStandardError '%ERR_FILE%' -PassThru; $p.Id | Set-Content '%PID_FILE%'"

for /L %%i in (1,1,30) do (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 '%URL%/_stcore/health').StatusCode | Out-Null; exit 0 } catch { exit 1 }"
  if !ERRORLEVEL! EQU 0 (
    start "" "%URL%"
    exit /b 0
  )
  timeout /t 1 >nul
)

notepad "%LOG_FILE%"
exit /b 1
