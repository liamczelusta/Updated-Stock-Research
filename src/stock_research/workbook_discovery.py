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


@dataclass(frozen=True)
class WorkbookCandidate:
    """One likely workbook found in a local folder scan."""

    path: Path
    ticker_hint: str
    display_name: str


def discover_workbooks(root: str | Path, max_files: int = 500) -> tuple[WorkbookCandidate, ...]:
    """Return likely Excel workbooks from a root folder, one best file per folder."""

    root_path = Path(root).expanduser()
    if not root_path.exists() or not root_path.is_dir():
        return ()

    by_folder: dict[Path, list[Path]] = {}
    for path in _iter_excel_files(root_path):
        by_folder.setdefault(path.parent, []).append(path)
        if sum(len(paths) for paths in by_folder.values()) >= max_files:
            break

    candidates = []
    for folder, paths in sorted(by_folder.items(), key=lambda item: str(item[0]).lower()):
        if folder == root_path:
            for path in sorted(paths, key=lambda item: item.name.lower()):
                candidates.append(
                    WorkbookCandidate(
                        path=path,
                        ticker_hint="",
                        display_name=path.name,
                    )
                )
            continue
        best = sorted(paths, key=lambda path: _candidate_score(path, folder), reverse=True)[0]
        ticker = _ticker_hint(folder, root_path)
        candidates.append(
            WorkbookCandidate(
                path=best,
                ticker_hint=ticker,
                display_name=f"{ticker} - {best.name}" if ticker else best.name,
            )
        )
    return tuple(candidates)


def _iter_excel_files(root: Path):
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(part in IGNORED_DIR_NAMES for part in path.parts):
            continue
        if path.name.startswith(("~$", ".")):
            continue
        if path.suffix.lower() not in EXCEL_SUFFIXES:
            continue
        yield path


def _candidate_score(path: Path, folder: Path) -> tuple[int, float, str]:
    name = path.name.lower()
    ticker = folder.name.lower()
    score = 0
    if ticker and ticker in name:
        score += 4
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
    name = folder.name.strip()
    return name.upper() if 1 <= len(name) <= 8 else name
