"""Streamlit entry point for the stock research application."""

from pathlib import Path
import hashlib
import sys
import tempfile
from typing import Any

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from stock_research.analysis_engine import analyze_workbook
from stock_research.config import APP_TITLE
from stock_research.dashboard.views import render_dashboard, render_empty_state
from stock_research.excel_parser import WorkbookValidationError, parse_workbook
from stock_research.preferences import load_preferences, remember_scan_folder, remember_workbook
from stock_research.similar_companies import (
    CompanyProfile,
    build_company_profile_index,
    find_similar_companies,
    find_similar_companies_from_profiles,
    load_company_profile_index,
    yahoo_company_profile,
)
from stock_research.workbook_discovery import WorkbookCandidate, discover_workbooks, find_workbook_for_ticker


def _save_upload_to_temp(uploaded_file: Any) -> Path:
    data = uploaded_file.getvalue()
    digest = hashlib.sha256(data).hexdigest()[:16]
    suffix = Path(uploaded_file.name).suffix or ".xlsx"
    safe_stem = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in Path(uploaded_file.name).stem)
    upload_dir = Path(tempfile.gettempdir()) / "stock_research_dashboard_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / f"{digest}_{safe_stem}{suffix}"
    if not path.exists():
        path.write_bytes(data)
    return path


@st.cache_data(show_spinner=False)
def _load_workbook_from_path(path: str):
    parsed = parse_workbook(path)
    analysis = analyze_workbook(parsed)
    return parsed, analysis


@st.cache_data(show_spinner=False)
def _discover_workbooks(folder: str) -> tuple[WorkbookCandidate, ...]:
    return discover_workbooks(folder)


@st.cache_data(show_spinner=False)
def _find_workbook_for_ticker(folder: str, ticker: str) -> WorkbookCandidate | None:
    return find_workbook_for_ticker(folder, ticker)


@st.cache_data(show_spinner=False, ttl=60 * 60 * 24 * 7)
def _company_profile(ticker: str) -> CompanyProfile | None:
    return yahoo_company_profile(ticker)


@st.cache_data(show_spinner=False)
def _load_company_profile_index(folder: str):
    return load_company_profile_index(folder)


def _build_company_profile_index(folder: str):
    index = build_company_profile_index(folder, _company_profile)
    _load_company_profile_index.clear()
    return index


def _parse_ticker_filter(value: str) -> set[str]:
    parts = value.replace(",", " ").replace(";", " ").split()
    return {part.strip().upper() for part in parts if part.strip()}


def _candidate_matches_ticker(candidate: WorkbookCandidate, ticker: str) -> bool:
    ticker = ticker.strip().upper()
    if not ticker:
        return False
    ticker_hint = candidate.ticker_hint.upper()
    name = candidate.path.stem.upper()
    folder = candidate.path.parent.name.upper()
    return (
        ticker == ticker_hint
        or folder.startswith(ticker)
        or name.startswith(ticker)
        or f"({ticker})" in name
        or f" {ticker} " in f" {name} "
    )


def _find_candidate_for_ticker(candidates: tuple[WorkbookCandidate, ...], ticker: str) -> WorkbookCandidate | None:
    matches = [candidate for candidate in candidates if _candidate_matches_ticker(candidate, ticker)]
    if not matches:
        return None
    return sorted(matches, key=lambda candidate: (candidate.ticker_hint.upper() == ticker.upper(), candidate.path.name), reverse=True)[0]


def _opened_scan_paths() -> list[tuple[str, Path]]:
    opened = st.session_state.setdefault("opened_scan_workbooks", [])
    cleaned = []
    for item in opened:
        if not isinstance(item, dict):
            continue
        display_name = item.get("display_name")
        path = item.get("path")
        if isinstance(display_name, str) and isinstance(path, str) and Path(path).exists():
            cleaned.append((display_name, Path(path)))
    return cleaned


def _add_opened_scan_candidate(candidate: WorkbookCandidate) -> None:
    opened = st.session_state.setdefault("opened_scan_workbooks", [])
    if any(item.get("path") == str(candidate.path) for item in opened if isinstance(item, dict)):
        return
    opened.append(
        {
            "display_name": candidate.display_name,
            "path": str(candidate.path),
            "ticker": candidate.ticker_hint,
        }
    )


def _opened_scan_tickers() -> list[str]:
    opened = st.session_state.setdefault("opened_scan_workbooks", [])
    tickers = []
    for item in opened:
        if isinstance(item, dict) and isinstance(item.get("ticker"), str):
            tickers.append(item["ticker"].upper())
    return tickers


def _add_tickers_from_folder(root_folder: str, tickers: set[str]) -> list[str]:
    missing = []
    fallback_candidates: tuple[WorkbookCandidate, ...] | None = None
    for ticker in sorted(tickers):
        candidate = _find_workbook_for_ticker(root_folder, ticker)
        if candidate is None:
            if fallback_candidates is None:
                fallback_candidates = _discover_workbooks(root_folder)
            candidate = _find_candidate_for_ticker(fallback_candidates, ticker)
        if candidate:
            _add_opened_scan_candidate(candidate)
        else:
            missing.append(ticker)
    return missing


def main() -> None:
    """Render the Streamlit stock research dashboard."""
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    preferences = load_preferences()

    with st.sidebar:
        st.title("Stock Research")
        st.caption("Open only the workbooks you want to analyze.")
        uploaded_files = []
        recent_choice = ""
        workbook_path = ""

        with st.expander("Library", expanded=True):
            scan_default = preferences.last_scan_folder or preferences.last_folder or ""
            scan_folder = st.text_input("Root folder", value=scan_default)
            with st.form("add_ticker_form", clear_on_submit=True):
                ticker_to_add = st.text_input("Ticker", value="", placeholder="AAPL")
                add_ticker = st.form_submit_button("+ Add stock")
            st.caption("The app starts empty. Add one ticker at a time.")

            if scan_folder.strip() and Path(scan_folder.strip()).expanduser().is_dir():
                remember_scan_folder(scan_folder.strip())
                if add_ticker:
                    ticker_parts = sorted(_parse_ticker_filter(ticker_to_add))
                    if not ticker_parts:
                        st.warning("Enter a ticker first.")
                    else:
                        root_folder = str(Path(scan_folder.strip()).expanduser())
                        missing = _add_tickers_from_folder(root_folder, ticker_parts)
                        if missing:
                            st.warning(f"Could not find: {', '.join(missing)}")
                        else:
                            st.success("Added.")
            elif add_ticker:
                st.warning("Enter a valid root folder first.")

            opened_scan_paths = _opened_scan_paths()
            if opened_scan_paths:
                st.caption("Open workbooks")
                for display_name, _path in opened_scan_paths:
                    st.caption(f"- {display_name}")
                if st.button("Clear opened stocks"):
                    st.session_state["opened_scan_workbooks"] = []
                    st.rerun()

            st.divider()
            profile_index = None
            root_folder_for_index = str(Path(scan_folder.strip()).expanduser()) if scan_folder.strip() else ""
            if root_folder_for_index and Path(root_folder_for_index).is_dir():
                profile_index = _load_company_profile_index(root_folder_for_index)
            if profile_index:
                st.caption(f"Profile index: {len(profile_index.profiles)} companies")
            else:
                st.caption("Profile index: not built")
            if st.button("Build / refresh profile index", disabled=not bool(root_folder_for_index)):
                if not Path(root_folder_for_index).is_dir():
                    st.warning("Enter a valid root folder first.")
                else:
                    with st.spinner("Building company profile index from Yahoo"):
                        profile_index = _build_company_profile_index(root_folder_for_index)
                    st.success(f"Indexed {len(profile_index.profiles)} companies.")

            similar_theme = st.text_input("Find similar", value="", placeholder="steel, banks, semiconductors")
            if st.button("Suggest similar companies", disabled=not bool(scan_folder.strip()) or not bool(similar_theme.strip())):
                root_folder = str(Path(scan_folder.strip()).expanduser())
                if not Path(root_folder).is_dir():
                    st.warning("Enter a valid root folder first.")
                else:
                    profile_index = _load_company_profile_index(root_folder)
                    if profile_index:
                        st.session_state["similar_company_results"] = find_similar_companies_from_profiles(
                            profile_index.profiles,
                            _opened_scan_tickers(),
                            similar_theme,
                        )
                    else:
                        with st.spinner("Checking Yahoo profiles"):
                            st.session_state["similar_company_results"] = find_similar_companies(
                                root_folder,
                                _opened_scan_tickers(),
                                similar_theme,
                                _company_profile,
                            )
            similar_results = st.session_state.get("similar_company_results", ())
            if similar_results:
                st.caption("Suggestions")
                for item in similar_results:
                    cols = st.columns([0.38, 0.62])
                    with cols[0]:
                        if st.button(f"+ {item.ticker}", key=f"add_similar_{item.ticker}"):
                            root_folder = str(Path(scan_folder.strip()).expanduser())
                            _add_tickers_from_folder(root_folder, {item.ticker})
                            st.rerun()
                    with cols[1]:
                        st.caption(f"{item.name or item.ticker} - {item.industry or item.sector or 'profile match'}")
                        st.caption(item.reason)

        with st.expander("Manual open"):
            uploaded_files = st.file_uploader("Excel workbook", type=("xlsx", "xlsm"), accept_multiple_files=True)
            if preferences.recent_files:
                recent_choice = st.selectbox(
                    "Recent files",
                    [""] + list(preferences.recent_files),
                    format_func=lambda value: "Choose recent workbook" if not value else Path(value).name,
                )
            default_folder = preferences.last_folder or ""
            workbook_path = st.text_input("Workbook path", value=default_folder)

    selected_path: Path | None = None
    remember_selected_path = False
    uploaded_paths: list[tuple[str, Path]] = []
    folder_paths: list[tuple[str, Path]] = []
    if uploaded_files:
        uploaded_paths = [(uploaded_file.name, _save_upload_to_temp(uploaded_file)) for uploaded_file in uploaded_files]
        if len(uploaded_paths) == 1:
            selected_path = uploaded_paths[0][1]
        else:
            with st.sidebar:
                selected_name = st.selectbox("Active workbook", [name for name, _path in uploaded_paths])
            selected_path = dict(uploaded_paths)[selected_name]
    elif _opened_scan_paths():
        folder_paths = _opened_scan_paths()
        if folder_paths:
            with st.sidebar:
                selected_name = st.selectbox("Active workbook", [name for name, _path in folder_paths])
            selected_path = dict(folder_paths)[selected_name]
    elif recent_choice:
        selected_path = Path(recent_choice).expanduser()
        remember_selected_path = True
    elif workbook_path.strip() and Path(workbook_path.strip()).expanduser().is_file():
        selected_path = Path(workbook_path.strip()).expanduser()
        remember_selected_path = True

    if selected_path is None:
        render_empty_state(preferences)
        return

    comparison_workbooks = []
    load_warnings = []
    try:
        with st.spinner("Reading workbook"):
            comparison_paths = uploaded_paths or folder_paths
            if comparison_paths:
                loaded_by_path = {}
                for display_name, path in comparison_paths:
                    try:
                        item_parsed, item_analysis = _load_workbook_from_path(str(path))
                    except Exception as exc:
                        load_warnings.append(f"{display_name}: {exc}")
                        continue
                    loaded_by_path[str(path)] = (item_parsed, item_analysis)
                    comparison_workbooks.append((display_name, item_parsed, item_analysis))
                if str(selected_path) in loaded_by_path:
                    parsed, analysis = loaded_by_path[str(selected_path)]
                elif comparison_workbooks:
                    _display_name, parsed, analysis = comparison_workbooks[0]
                else:
                    raise WorkbookValidationError("No valid standardized workbooks were found in that folder.")
            else:
                parsed, analysis = _load_workbook_from_path(str(selected_path))
        if remember_selected_path:
            remember_workbook(selected_path)
    except WorkbookValidationError as exc:
        render_empty_state(preferences, error=str(exc))
        return
    except Exception as exc:
        render_empty_state(
            preferences,
            error=f"Could not load that workbook. Please confirm it uses the standardized template. Details: {exc}",
        )
        return

    if load_warnings:
        with st.sidebar.expander("Ignored files"):
            for warning in load_warnings[:20]:
                st.caption(warning)
            if len(load_warnings) > 20:
                st.caption(f"{len(load_warnings) - 20} more file(s) were ignored.")

    render_dashboard(parsed, analysis, comparison_workbooks=comparison_workbooks)


if __name__ == "__main__":
    main()
