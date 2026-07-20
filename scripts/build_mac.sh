#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

source .venv/bin/activate
export PYINSTALLER_CONFIG_DIR="$PWD/.pyinstaller-cache"

python -m PyInstaller \
  --name StockResearchDashboard \
  --windowed \
  --onedir \
  --noconfirm \
  --add-data "app.py:." \
  --add-data "src:src" \
  --add-data ".streamlit:.streamlit" \
  --collect-all streamlit \
  --collect-all yfinance \
  --collect-all curl_cffi \
  desktop_launcher.py

ditto -c -k --sequesterRsrc --keepParent \
  "dist/StockResearchDashboard.app" \
  "dist/StockResearchDashboard-mac.zip"

echo "Built dist/StockResearchDashboard.app"
echo "Built dist/StockResearchDashboard-mac.zip"
