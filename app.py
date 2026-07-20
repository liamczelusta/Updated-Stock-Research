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
from stock_research.workbook_discovery import WorkbookCandidate, discover_workbooks


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


def main() -> None:
    """Render the Streamlit stock research dashboard."""
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    preferences = load_preferences()

    with st.sidebar:
        st.title("Stock Research")
        st.caption("Drop one or more standardized workbooks to begin.")
        uploaded_files = st.file_uploader("Excel workbook", type=("xlsx", "xlsm"), accept_multiple_files=True)
        recent_choice = ""
        if preferences.recent_files:
            recent_choice = st.selectbox(
                "Recent files",
                [""] + list(preferences.recent_files),
                format_func=lambda value: "Choose recent workbook" if not value else Path(value).name,
            )
        with st.expander("Open by path"):
            default_folder = preferences.last_folder or ""
            workbook_path = st.text_input("Workbook path", value=default_folder)
        with st.expander("Scan local folder"):
            scan_default = preferences.last_scan_folder or preferences.last_folder or ""
            scan_folder = st.text_input("Root folder", value=scan_default)
            st.caption("Desktop use: scan ticker subfolders and ignore non-Excel files.")

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
    elif scan_folder.strip() and Path(scan_folder.strip()).expanduser().is_dir():
        candidates = _discover_workbooks(str(Path(scan_folder.strip()).expanduser()))
        folder_paths = [(candidate.display_name, candidate.path) for candidate in candidates]
        if folder_paths:
            with st.sidebar:
                st.caption(f"Found {len(folder_paths)} workbook(s).")
                selected_name = st.selectbox("Active workbook", [name for name, _path in folder_paths])
            selected_path = dict(folder_paths)[selected_name]
            remember_scan_folder(scan_folder.strip())
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
