# Streamlit Community Cloud Deployment

This is the simplest free web deployment path for the Stock Research Dashboard.

## What Users Will Do

Users open one private app link in their browser, upload one or more standardized Excel workbooks, review the analysis, generate the optional AI memo, ask follow-up questions, and export/copy the report.

## Privacy Note

The desktop version keeps workbooks on the user's computer. A hosted Streamlit version uploads workbooks to the running cloud app while the session is active. Use the cloud version only if that is acceptable for the firm's data policy.

## Files Streamlit Cloud Needs

- `app.py`
- `requirements.txt`
- `runtime.txt`
- `.streamlit/config.toml`
- `src/stock_research/...`

Do not upload local build artifacts, desktop bundles, virtual environments, cache folders, or real secrets.

## Secrets To Add In Streamlit Cloud

Open the app settings in Streamlit Community Cloud and add:

```toml
ANTHROPIC_API_KEY = "your-real-anthropic-key"
FINNHUB_API_KEY = "your-real-finnhub-key"
```

These values should be stored in Streamlit Cloud's Secrets panel, not in GitHub.

## Deploy Steps

1. Create a private GitHub repository.
2. Upload or push this source project to the repository. If using the GitHub website, unzip `release/StockResearchDashboard-streamlit-cloud-source.zip` and upload the unzipped contents.
3. Go to Streamlit Community Cloud.
4. Choose the GitHub repository.
5. Set the main file path to `app.py`.
6. Paste the secrets above into the app's Secrets panel.
7. Deploy.
8. Send the deployed app link to the two users.

## Recommended Settings

- Keep the Claude model on Haiku for quick routine analysis.
- Use Sonnet for stronger judgment calls.
- Use Opus or Fable only for deeper reviews where the extra cost is justified.
- Keep response length around `1500`.
- Generate AI memos only when needed to control API cost.

## What To Avoid

- Do not commit `.streamlit/secrets.toml`.
- Do not upload `dist/`, `build/`, `.venv/`, `.cache/`, or downloaded Excel workbooks.
- Do not use Vercel for this Streamlit app unless the app is rewritten for a different web architecture.
