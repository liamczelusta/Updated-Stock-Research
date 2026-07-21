"""Find standardized stock workbooks inside local ticker folders."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


EXCEL_SUFFIXES = {".xlsx", ".xlsm"}
IGNORED_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    ".pytest_cache",
    ".streamlit",
}
IGNORED_TOP_LEVEL_PREFIXES = ("1 -", "ZZZ")
PREFERRED_WORKBOOK_PREFIXES = (
    "zp quarterly matrix",
    "zp quarterly matric",
)


@dataclass(frozen=True)
class WorkbookCandidate:
    """One likely workbook found in a local folder scan."""

    path: Path
    ticker_hint: str
    display_name: str


def discover_workbooks(root: str | Path, max_files: int = 500) -> tuple[WorkbookCandidate, ...]:
    """Return likely Excel workbooks from ticker folders, one best file per folder."""

    root_path = Path(root).expanduser()
    if not root_path.exists() or not root_path.is_dir():
        return ()

    by_folder: dict[Path, list[Path]] = {}
    for path in _iter_excel_files(root_path):
        ticker_folder = _ticker_folder(path, root_path)
        if ticker_folder is None:
            continue
        by_folder.setdefault(path.parent, []).append(path)
        if sum(len(paths) for paths in by_folder.values()) >= max_files:
            break

    candidates = []
    for folder, paths in sorted(by_folder.items(), key=lambda item: str(item[0]).lower()):
        ticker = _ticker_hint(folder, root_path)
        best = sorted(paths, key=lambda path: _candidate_score(path, folder, ticker), reverse=True)[0]
        candidates.append(
            WorkbookCandidate(
                path=best,
                ticker_hint=ticker,
                display_name=f"{ticker} - {best.name}" if ticker else best.name,
            )
        )
    return tuple(candidates)


def find_workbook_for_ticker(root: str | Path, ticker: str) -> WorkbookCandidate | None:
    """Find the best standardized workbook for one ticker without scanning the full library."""

    root_path = Path(root).expanduser()
    clean_ticker = _clean_ticker(ticker)
    if not root_path.exists() or not root_path.is_dir() or not clean_ticker:
        return None

    folder = _find_ticker_folder(root_path, clean_ticker)
    if folder is None:
        return None

    paths = [path for path in _iter_excel_files(folder) if path.is_file()]
    if not paths:
        return None

    best = sorted(paths, key=lambda path: _candidate_score(path, folder, clean_ticker), reverse=True)[0]
    return WorkbookCandidate(
        path=best,
        ticker_hint=clean_ticker,
        display_name=f"{clean_ticker} - {best.name}",
    )


def _iter_excel_files(root: Path):
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        relative_parts = path.relative_to(root).parts
        if not relative_parts:
            continue
        top_level = relative_parts[0].upper()
        if top_level.startswith(IGNORED_TOP_LEVEL_PREFIXES):
            continue
        if any(part in IGNORED_DIR_NAMES for part in path.parts):
            continue
        if path.name.startswith(("~$", ".")):
            continue
        if path.suffix.lower() not in EXCEL_SUFFIXES:
            continue
        if _is_numbered_old_matrix(path.name):
            continue
        yield path


def _candidate_score(path: Path, folder: Path, ticker_hint: str = "") -> tuple[int, float, str]:
    name = path.name.lower()
    ticker = (ticker_hint or folder.name).lower()
    score = 0
    if ticker and ticker in name:
        score += 4
    if name.startswith(PREFERRED_WORKBOOK_PREFIXES):
        score += 20
    if "quarter" in name or "qtr" in name:
        score += 3
    if "matrix" in name or "matric" in name:
        score += 2
    if "copy" in name:
        score -= 1
    try:
        modified = path.stat().st_mtime
    except OSError:
        modified = 0.0
    return score, modified, path.name.lower()


def _ticker_hint(folder: Path, root: Path) -> str:
    if folder == root:
        return ""
    try:
        name = folder.relative_to(root).parts[0].strip()
    except ValueError:
        name = folder.name.strip()
    name = name.split()[0].split("-")[0].strip()
    return name.upper() if 1 <= len(name) <= 8 else name


def _ticker_folder(path: Path, root: Path) -> Path | None:
    try:
        relative_parts = path.relative_to(root).parts
    except ValueError:
        return None
    if len(relative_parts) < 2:
        return None
    folder = root / relative_parts[0]
    folder_name = relative_parts[0].strip()
    if folder_name.upper().startswith(IGNORED_TOP_LEVEL_PREFIXES):
        return None
    return folder


def _find_ticker_folder(root: Path, ticker: str) -> Path | None:
    exact_matches = []
    prefix_matches = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        name = child.name.strip()
        upper_name = name.upper()
        if upper_name.startswith(IGNORED_TOP_LEVEL_PREFIXES):
            continue
        folder_ticker = _clean_ticker(name)
        if folder_ticker == ticker:
            exact_matches.append(child)
        elif upper_name.startswith(ticker):
            prefix_matches.append(child)
    matches = exact_matches or prefix_matches
    if not matches:
        return None
    return sorted(matches, key=lambda path: (len(path.name), path.name.lower()))[0]


def _clean_ticker(value: str) -> str:
    cleaned = value.strip().upper()
    if not cleaned:
        return ""
    cleaned = cleaned.split()[0].split("-")[0].strip()
    return "".join(char for char in cleaned if char.isalnum() or char in {".", "_"})


def _is_numbered_old_matrix(name: str) -> bool:
    lowered = name.strip().lower()
    if "zp quarterly matrix" not in lowered and "zp quarterly matric" not in lowered:
        return False
    prefix = lowered.split("zp quarterly", 1)[0].strip()
    if not prefix:
        return False
    return prefix.rstrip("- ").isdigit()
