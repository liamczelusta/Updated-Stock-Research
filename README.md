# Stock Research Desktop App

A focused Streamlit desktop-style application for analyzing internally standardized Excel workbooks.

This is intentionally not a general investing platform. It is a small-firm productivity tool for quickly turning a fixed-format quarterly workbook into an executive summary, deterministic metrics, charts, market context, AI follow-up questions, and PDF exports.

## Primary Workflow

1. Launch the app.
2. Drag and drop one Excel workbook.
3. The workbook parses automatically.
4. Deterministic analysis and Yahoo Finance market data load.
5. An executive summary and AI analyst memo appear at the top.
6. Ask follow-up questions in the chat panel.
7. Copy or export the summary/report.

## Architecture

```text
app.py
src/stock_research/
  analysis_engine.py      deterministic calculations, trends, scores
  dataclasses.py          typed workbook and analysis objects
  excel_parser.py         explicit fixed-layout workbook parser
  market_data.py          Yahoo Finance provider and future provider interface
  preferences.py          local recent-file and last-folder memory
  reporting.py            executive summary and PDF export helpers
  ai/
    context.py            compact AI evidence packets
    providers.py          Claude client
  dashboard/
    views.py              Streamlit UI, charts, copy/download actions
```

## Design Principles

- Optimize for one workbook at a time.
- Prefer explicit cell and sheet assumptions over layout detection.
- Keep parsing, analysis, market data, reporting, AI, and UI separate.
- Use deterministic calculations first; AI explains the evidence, not invents it.
- Fail with friendly messages when workbooks or market data are unavailable.
- Keep all user data local.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Run:

```bash
streamlit run app.py
```

## Free Web Deployment

The easiest free hosted option is Streamlit Community Cloud because this project is already a Streamlit app. See `docs/streamlit_cloud_deploy.md` for the exact deployment steps.

For private financial workbooks, the desktop/local version remains the safest option because files stay on the user's machine.

## Windows Desktop Build

The Windows package can be built through GitHub Actions. See `docs/windows_desktop_build.md`.

For large local research folders, use the sidebar's `Scan local folder` option. It remembers the last folder used and starts with no workbooks open. Add only the tickers you want, one at a time, such as `AAPL` or `GS`. The scanner ignores top-level folders beginning with `1 -` or `ZZZ`, skips old numbered matrix files such as `1 - ZP Quarterly Matrix...`, and prefers the workbook named `ZP Quarterly Matrix...` inside each ticker folder.

## AI Configuration

The app uses Claude for the AI assistant. In the desktop app, paste the key once in `Advanced` and choose `Save Claude key on this computer`. For Streamlit Cloud, store the key in app secrets. The sidebar lets you choose Haiku, Sonnet, Opus, or Fable depending on whether you want lower cost or stronger analysis.

```toml
ANTHROPIC_API_KEY = "..."
```

The AI receives a compact evidence packet containing recent workbook data, deterministic scores, trends, risks, current market data, and recent company news. The app keeps the default response short to control API cost.

Recommended model use:

- Haiku: routine workbook Q&A and fast summaries.
- Sonnet: best everyday choice for stronger investment judgment.
- Opus: deeper review when cost matters less.
- Fable: most demanding analysis if your Anthropic account has access.

## Market Data

Yahoo Finance is loaded through `yfinance` and cached by Streamlit. Finnhub is used for company news when `FINNHUB_API_KEY` is available, with Yahoo Finance headlines as the fallback. The app retrieves:

- Current price
- Daily price history
- Market cap
- 52-week high/low
- Beta
- Average volume
- Dividend yield when available
- Analyst targets when available
- Recent company news headlines when available

The provider interface is intentionally narrow so a future FactSet implementation can be added without changing the UI.

## Exports

The app can export:

- Executive Summary PDF
- Complete Report PDF

PDF generation is dependency-free and local.

## Local State

Recent files and the last opened folder are stored under `.cache/`. Secrets are kept out of version control.
