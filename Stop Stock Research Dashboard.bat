@echo off
setlocal EnableDelayedExpansion

set "APP_DIR=%~dp0"
set "LOG_DIR=%LOCALAPPDATA%\StockResearchDashboard\Logs"
set "LOG_FILE=%LOG_DIR%\simple-launcher.log"
set "STATE_DIR=%APP_DIR%\.cache"
set "PID_FILE=%STATE_DIR%\stock_research_dashboard.pid"
if not exist "%PID_FILE%" (
  if exist "%APP_DIR%StockResearchDashboard\.cache\stock_research_dashboard.pid" (
    set "PID_FILE=%APP_DIR%StockResearchDashboard\.cache\stock_research_dashboard.pid"
  )
)

mkdir "%LOG_DIR%" >nul 2>nul
mkdir "%STATE_DIR%" >nul 2>nul

echo ========================================>> "%LOG_FILE%"
echo %DATE% %TIME% Stopping Stock Research Dashboard>> "%LOG_FILE%"

if not exist "%PID_FILE%" (
  echo No PID file found. Nothing was stopped.>> "%LOG_FILE%"
  echo.
  echo No running dashboard was found from this launcher.
  echo If the browser is still open, just close the dashboard tab.
  echo.
  pause
  exit /b 0
)

for /f "usebackq delims=" %%p in ("%PID_FILE%") do set "PID_FROM_FILE=%%p"

if "%PID_FROM_FILE%"=="" (
  del "%PID_FILE%" >nul 2>nul
  echo Dashboard was already stopped.
  pause
  exit /b 0
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$root = '%APP_DIR%';" ^
  "$pidValue = [int]'%PID_FROM_FILE%';" ^
  "$proc = Get-CimInstance Win32_Process -Filter \"ProcessId=$pidValue\" -ErrorAction SilentlyContinue;" ^
  "if ($null -eq $proc) { exit 0 }" ^
  "$cmd = [string]$proc.CommandLine;" ^
  "if ($cmd -notlike \"*$root*\" -and $cmd -notlike \"*streamlit*\") { exit 0 }" ^
  "function Stop-Tree($id) { Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $id } | ForEach-Object { Stop-Tree $_.ProcessId }; Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }" ^
  "Stop-Tree $pidValue" >> "%LOG_FILE%" 2>&1

del "%PID_FILE%" >nul 2>nul

echo Stock Research Dashboard stop command finished.>> "%LOG_FILE%"
echo.
echo Stock Research Dashboard is stopped.
echo Your browser tabs were not touched.
echo.
pause
