"""Local-only secret storage for desktop convenience.

This is intentionally separate from Streamlit Cloud secrets. Values saved here
stay on the user's computer and are not included in GitHub or release zips.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


APP_SUPPORT_DIR = (
    Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming")) / "StockResearchDashboard"
    if sys.platform.startswith("win")
    else Path.home() / "Library" / "Application Support" / "StockResearchDashboard"
)
LOCAL_SECRETS_PATH = APP_SUPPORT_DIR / "local_secrets.json"


def load_local_secret(name: str) -> str:
    """Return a locally saved secret value, or an empty string."""

    try:
        payload = json.loads(LOCAL_SECRETS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return ""
    value = payload.get(name, "")
    return value.strip() if isinstance(value, str) else ""


def save_local_secret(name: str, value: str) -> None:
    """Save one local secret for this computer."""

    try:
        payload = json.loads(LOCAL_SECRETS_PATH.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    payload[name] = value.strip()
    _write_payload(payload)


def delete_local_secret(name: str) -> None:
    """Remove one local secret if it exists."""

    try:
        payload = json.loads(LOCAL_SECRETS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    payload.pop(name, None)
    _write_payload(payload)


def _write_payload(payload: dict[str, str]) -> None:
    APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_SECRETS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        LOCAL_SECRETS_PATH.chmod(0o600)
    except OSError:
        pass
