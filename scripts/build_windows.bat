@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0\.."

if not exist ".venv\Scripts\activate.bat" (
  py -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

set PYINSTALLER_CONFIG_DIR=%CD%\.pyinstaller-cache

python -m PyInstaller ^
  --name StockResearchDashboard ^
  --windowed ^
  --onedir ^
  --noconfirm ^
  --add-data "app.py;." ^
  --add-data "src;src" ^
  --add-data ".streamlit;.streamlit" ^
  --collect-all streamlit ^
  --collect-all yfinance ^
  --collect-all curl_cffi ^
  desktop_launcher.py

copy "Open Stock Research Dashboard.bat" "dist\Open Stock Research Dashboard.bat" >nul
copy "Stop Stock Research Dashboard.bat" "dist\Stop Stock Research Dashboard.bat" >nul

powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\StockResearchDashboard','dist\Open Stock Research Dashboard.bat','dist\Stop Stock Research Dashboard.bat' -DestinationPath 'dist\StockResearchDashboard-windows.zip' -Force"

echo Built dist\StockResearchDashboard
echo Built dist\StockResearchDashboard-windows.zip
