# Packaging The Desktop App

The application is a Streamlit app with a small desktop launcher. For development, run it directly:

```bash
source .venv/bin/activate
streamlit run app.py
```

## Preferred Local Launchers

The simplest local workflow is to use the command launchers instead of the `.app` bundle:

```text
Open Stock Research Dashboard.command
Stop Stock Research Dashboard.command
```

Run this installer once:

```text
Install Easy Stock Research Launcher.command
```

It places open/stop commands in:

```text
~/Applications/StockResearchDashboard/
```

The open launcher starts the dashboard at `http://127.0.0.1:8765` and writes a PID file. The stop launcher uses that PID file, kills child processes, and falls back to stopping anything listening on port `8765`.

## Mac App Bundle

For a standalone Mac app bundle, use the build script:

```bash
bash scripts/build_mac.sh
```

The app bundle is created at:

```text
dist/StockResearchDashboard.app
```

Create a zip that is easy to move or share:

```bash
ditto -c -k --sequesterRsrc --keepParent \
  "dist/StockResearchDashboard.app" \
  "dist/StockResearchDashboard-mac.zip"
```

The desktop app still runs Streamlit locally inside the app bundle and opens the dashboard in the default browser automatically. The user does not need to run terminal commands.

If the Mac build fails with `lipo` or `install_name_tool` errors, install Apple Command Line Tools and rebuild:

```bash
xcode-select --install
bash scripts/build_mac.sh
```

## Windows Build

Windows applications must be built on Windows. From a Windows machine:

```bat
scripts\build_windows.bat
```

The Windows bundle is created at:

```text
dist\StockResearchDashboard
```

The shareable zip is created at:

```text
dist\StockResearchDashboard-windows.zip
```

The Windows app entrypoint is:

```text
dist\StockResearchDashboard\StockResearchDashboard.exe
```

The Windows zip also includes:

```text
Open Stock Research Dashboard.bat
Stop Stock Research Dashboard.bat
```

Those batch files mirror the Mac launchers and use the same local URL: `http://127.0.0.1:8765`.

## Startup Logs

If a packaged app does not open, check:

```text
~/Library/Logs/StockResearchDashboard/launcher.log
```

On Windows, check:

```text
%LOCALAPPDATA%\StockResearchDashboard\Logs\launcher.log
```

## API Keys

The app reads API keys from the sidebar or these environment variables:

- `ANTHROPIC_API_KEY`
- `FINNHUB_API_KEY`

For this internal two-user tool, local Streamlit secrets can be bundled if desired. For broader distribution, do not bundle production API keys; use environment variables or runtime entry instead.

## Market Data

Yahoo Finance data is fetched through `yfinance` and cached in the running Streamlit session for 15 minutes. The yfinance project notes that Yahoo Finance data is intended for research and educational use; review Yahoo's terms before distributing the app broadly.

## Future FactSet Support

Market data is accessed through a provider interface in `stock_research.market_data`. Add a concrete FactSet provider behind that interface when credentials are available, then expose it as another sidebar option.
