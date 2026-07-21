# Windows Desktop Build

This project can be built into a Windows desktop-style package through GitHub Actions. The app still runs Streamlit locally, but users only need to unzip the package and double-click a launcher.

## User Workflow

1. Download `StockResearchDashboard-windows.zip` from the GitHub Actions build.
2. Unzip it.
3. Double-click `Open Stock Research Dashboard.bat`.
4. The app opens in the browser at a local address.
5. Use `Scan local folder` in the sidebar to point at the large stock-folder library. The app remembers that folder for next time.
6. Type a ticker, such as `AAPL`, and click `+ Add stock`.
7. Repeat step 6 for each company you want open.
8. Paste the Claude key once in `Advanced` and click `Save Claude key on this computer`.
9. Double-click `Stop Stock Research Dashboard.bat` when finished.

## Folder Scanner

The scanner is intended for a folder shaped like:

```text
Stock Library/
  AAPL/
    ZP Quarterly matrix (AAPL).xlsx
    notes.pdf
  AMZN/
    ZP Quarterly Matrix (AMZN).xlsx
    other files.docx
  GS/
    workbook.xlsx
```

It recursively finds `.xlsx` and `.xlsm` files, ignores temporary Excel files and common build/cache folders, and chooses the best-looking workbook in each ticker folder. Non-Excel files are ignored.

For large libraries, the app starts with no scan-folder workbooks open. Add only the ticker or tickers you want to analyze.

Folder rules:

- Top-level folders beginning with `1 -` are ignored.
- Top-level folders beginning with `ZZZ` are ignored.
- Other top-level folders should begin with a ticker, such as `AAPL`.
- Old numbered files such as `1 - ZP Quarterly Matrix...` are ignored.
- The preferred workbook is the file beginning with `ZP Quarterly Matrix...`.

## Building With GitHub CLI

Install the GitHub CLI and sign in:

```bash
brew install gh
gh auth login
```

Then from the project folder:

```bash
cd "/Users/liamczelusta/Documents/Liam Codex"
git init
git branch -M main
git remote add origin https://github.com/liamczelusta/Updated-Stock-Research.git
git add app.py desktop_launcher.py requirements.txt runtime.txt README.md pyproject.toml .gitignore .streamlit/config.toml .streamlit/secrets.example.toml src scripts docs tests ".github/workflows/build-windows.yml" "Open Stock Research Dashboard.bat" "Stop Stock Research Dashboard.bat"
git commit -m "Add Windows desktop build and folder scanner"
git push -u origin main
```

If the remote already exists, replace the remote command with:

```bash
git remote set-url origin https://github.com/liamczelusta/Updated-Stock-Research.git
```

## Downloading The Windows Build

1. Open the GitHub repo.
2. Go to `Actions`.
3. Open the latest `Build Windows Desktop App` run.
4. Download the `StockResearchDashboard-windows` artifact.

## API Keys

Do not put real keys in GitHub. For desktop use, place real keys in a local `.streamlit/secrets.toml` next to the app source before building, or enter keys through the app override when needed.
