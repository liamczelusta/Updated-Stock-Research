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
    ai_model_label: str | None = None
    claude_web_search: bool = False
    claude_web_search_max_uses: int = 3
    yahoo_finance: bool = True
    market_period: str = "1y"
    display_theme: str = "Dark"
    quarters_shown: int | None = None
    show_forecast_extension: bool = True


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
        ai_model_label=_text_or_none(payload.get("ai_model_label")),
        claude_web_search=bool(payload.get("claude_web_search", False)),
        claude_web_search_max_uses=_bounded_int(payload.get("claude_web_search_max_uses"), 3, 1, 5),
        yahoo_finance=bool(payload.get("yahoo_finance", True)),
        market_period=_choice(payload.get("market_period"), {"6mo", "1y", "2y", "5y"}, "1y"),
        display_theme=_choice(payload.get("display_theme"), {"Dark", "Light"}, "Dark"),
        quarters_shown=_optional_bounded_int(payload.get("quarters_shown"), 4, 80),
        show_forecast_extension=bool(payload.get("show_forecast_extension", True)),
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
        ai_model_label=preferences.ai_model_label,
        claude_web_search=preferences.claude_web_search,
        claude_web_search_max_uses=preferences.claude_web_search_max_uses,
        yahoo_finance=preferences.yahoo_finance,
        market_period=preferences.market_period,
        display_theme=preferences.display_theme,
        quarters_shown=preferences.quarters_shown,
        show_forecast_extension=preferences.show_forecast_extension,
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
        ai_model_label=preferences.ai_model_label,
        claude_web_search=preferences.claude_web_search,
        claude_web_search_max_uses=preferences.claude_web_search_max_uses,
        yahoo_finance=preferences.yahoo_finance,
        market_period=preferences.market_period,
        display_theme=preferences.display_theme,
        quarters_shown=preferences.quarters_shown,
        show_forecast_extension=preferences.show_forecast_extension,
    )
    _save_preferences(updated)
    return updated


def remember_dashboard_preferences(
    *,
    ai_model_label: str,
    claude_web_search: bool,
    claude_web_search_max_uses: int,
    yahoo_finance: bool,
    market_period: str,
    display_theme: str,
    quarters_shown: int,
    show_forecast_extension: bool,
) -> AppPreferences:
    """Persist dashboard controls that should survive workbook changes and restarts."""

    preferences = load_preferences()
    updated = AppPreferences(
        recent_files=preferences.recent_files,
        last_folder=preferences.last_folder,
        last_scan_folder=preferences.last_scan_folder,
        ai_model_label=ai_model_label,
        claude_web_search=claude_web_search,
        claude_web_search_max_uses=_bounded_int(claude_web_search_max_uses, 3, 1, 5),
        yahoo_finance=yahoo_finance,
        market_period=_choice(market_period, {"6mo", "1y", "2y", "5y"}, "1y"),
        display_theme=_choice(display_theme, {"Dark", "Light"}, "Dark"),
        quarters_shown=_bounded_int(quarters_shown, 16, 4, 80),
        show_forecast_extension=show_forecast_extension,
    )
    _save_preferences(updated)
    return updated


def _save_preferences(preferences: AppPreferences) -> None:
    PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "recent_files": list(preferences.recent_files),
        "last_folder": preferences.last_folder,
        "last_scan_folder": preferences.last_scan_folder,
        "ai_model_label": preferences.ai_model_label,
        "claude_web_search": preferences.claude_web_search,
        "claude_web_search_max_uses": preferences.claude_web_search_max_uses,
        "yahoo_finance": preferences.yahoo_finance,
        "market_period": preferences.market_period,
        "display_theme": preferences.display_theme,
        "quarters_shown": preferences.quarters_shown,
        "show_forecast_extension": preferences.show_forecast_extension,
    }
    PREFERENCES_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _text_or_none(value) -> str | None:
    return str(value).strip() if isinstance(value, str) and value.strip() else None


def _choice(value, choices: set[str], default: str) -> str:
    return value if isinstance(value, str) and value in choices else default


def _bounded_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _optional_bounded_int(value, minimum: int, maximum: int) -> int | None:
    if value is None:
        return None
    return _bounded_int(value, minimum, minimum, maximum)
