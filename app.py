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
from stock_research.preferences import load_preferences, remember_workbook


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

    selected_path: Path | None = None
    remember_selected_path = False
    uploaded_paths: list[tuple[str, Path]] = []
    if uploaded_files:
        uploaded_paths = [(uploaded_file.name, _save_upload_to_temp(uploaded_file)) for uploaded_file in uploaded_files]
        if len(uploaded_paths) == 1:
            selected_path = uploaded_paths[0][1]
        else:
            with st.sidebar:
                selected_name = st.selectbox("Active workbook", [name for name, _path in uploaded_paths])
            selected_path = dict(uploaded_paths)[selected_name]
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
    try:
        with st.spinner("Reading workbook"):
            if uploaded_paths:
                loaded_by_path = {}
                for display_name, path in uploaded_paths:
                    item_parsed, item_analysis = _load_workbook_from_path(str(path))
                    loaded_by_path[str(path)] = (item_parsed, item_analysis)
                    comparison_workbooks.append((display_name, item_parsed, item_analysis))
                parsed, analysis = loaded_by_path.get(str(selected_path)) or _load_workbook_from_path(str(selected_path))
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

    render_dashboard(parsed, analysis, comparison_workbooks=comparison_workbooks)


if __name__ == "__main__":
    main()
