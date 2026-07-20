"""Local preferences for the single-workbook desktop workflow."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys


MAX_RECENT_FILES = 6
APP_SUPPORT_DIR = (
    Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming")) / "StockResearchDashboard"
    if sys.platform.startswith("win")
    else Path.home() / "Library" / "Application Support" / "StockResearchDashboard"
)
PREFERENCES_PATH = APP_SUPPORT_DIR / "preferences.json"


@dataclass(frozen=True)
class AppPreferences:
    """Small local state used to remove repeated file-picking friction."""

    recent_files: tuple[str, ...] = ()
    last_folder: str | None = None
    last_scan_folder: str | None = None


def load_preferences() -> AppPreferences:
    """Read local preferences, returning defaults if the file is absent or malformed."""

    try:
        payload = json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return AppPreferences()

    recent_files = tuple(
        path
        for path in payload.get("recent_files", [])
        if isinstance(path, str) and Path(path).exists()
    )
    last_folder = payload.get("last_folder")
    if not isinstance(last_folder, str) or not Path(last_folder).exists():
        last_folder = str(Path(recent_files[0]).parent) if recent_files else None
    last_scan_folder = payload.get("last_scan_folder")
    if not isinstance(last_scan_folder, str) or not Path(last_scan_folder).exists():
        last_scan_folder = None
    return AppPreferences(
        recent_files=recent_files[:MAX_RECENT_FILES],
        last_folder=last_folder,
        last_scan_folder=last_scan_folder,
    )


def remember_workbook(path: str | Path) -> AppPreferences:
    """Persist a successfully opened workbook path and return updated preferences."""

    workbook_path = Path(path).expanduser()
    preferences = load_preferences()
    existing = [item for item in preferences.recent_files if Path(item) != workbook_path]
    recent_files = (str(workbook_path), *existing)[:MAX_RECENT_FILES]
    updated = AppPreferences(
        recent_files=tuple(recent_files),
        last_folder=str(workbook_path.parent),
        last_scan_folder=preferences.last_scan_folder,
    )
    _save_preferences(updated)
    return updated


def remember_scan_folder(path: str | Path) -> AppPreferences:
    """Persist the root folder used for recursive workbook scans."""

    scan_path = Path(path).expanduser()
    preferences = load_preferences()
    updated = AppPreferences(
        recent_files=preferences.recent_files,
        last_folder=preferences.last_folder,
        last_scan_folder=str(scan_path) if scan_path.exists() else preferences.last_scan_folder,
    )
    _save_preferences(updated)
    return updated


def _save_preferences(preferences: AppPreferences) -> None:
    PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "recent_files": list(preferences.recent_files),
        "last_folder": preferences.last_folder,
        "last_scan_folder": preferences.last_scan_folder,
    }
    PREFERENCES_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
