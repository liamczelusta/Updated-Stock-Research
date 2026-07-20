"""Desktop launcher for packaged Streamlit builds."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser

from streamlit.web import cli as streamlit_cli


def main() -> None:
    """Launch the Streamlit app from source or a PyInstaller bundle."""

    log_path = _log_path()
    try:
        _write_log(log_path, "Starting StockResearchDashboard")
        os.environ.setdefault("STREAMLIT_GLOBAL_DEVELOPMENT_MODE", "false")
        app_path = _find_app_path()
        _write_log(log_path, f"Using app.py at {app_path}")
        _write_pid(_pid_path(app_path), os.getpid())
        os.chdir(app_path.parent)
    except Exception:
        _write_log(log_path, traceback.format_exc())
        raise

    port = _available_port(preferred=8765)
    _write_log(log_path, f"Starting Streamlit on http://127.0.0.1:{port}")
    threading.Thread(target=_open_browser, args=(port, log_path), daemon=True).start()
    sys.argv = [
        "streamlit",
        "run",
        str(app_path),
        "--global.developmentMode=false",
        "--server.headless=true",
        "--server.address=127.0.0.1",
        f"--server.port={port}",
        "--browser.gatherUsageStats=false",
    ]
    try:
        streamlit_cli.main()
    except Exception:
        _write_log(log_path, traceback.format_exc())
        raise


def _find_app_path() -> Path:
    candidates = []
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        root = Path(frozen_root)
        candidates.extend([root / "app.py", root.parent / "Resources" / "app.py"])

    executable = Path(sys.executable).resolve()
    candidates.extend(
        [
            Path(__file__).resolve().parent / "app.py",
            executable.parent / "app.py",
            executable.parent.parent / "Resources" / "app.py",
            executable.parent.parent / "Frameworks" / "app.py",
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return candidate
    searched = "\n".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(f"Could not find bundled app.py. Searched:\n{searched}")


def _available_port(preferred: int | None = None) -> int:
    if preferred is not None and _can_bind(preferred):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _can_bind(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def _open_browser(port: int, log_path: Path) -> None:
    time.sleep(2.5)
    url = f"http://127.0.0.1:{port}"
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", url], check=False)
        else:
            webbrowser.open(url)
        _write_log(log_path, f"Opened browser at {url}")
    except Exception:
        _write_log(log_path, f"Could not open browser automatically:\n{traceback.format_exc()}")


def _log_path() -> Path:
    if sys.platform.startswith("win"):
        root = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        log_dir = root / "StockResearchDashboard" / "Logs"
    else:
        log_dir = Path.home() / "Library" / "Logs" / "StockResearchDashboard"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "launcher.log"


def _pid_path(app_path: Path) -> Path:
    if getattr(sys, "frozen", False):
        state_dir = Path(sys.executable).resolve().parent / ".cache"
    else:
        state_dir = app_path.parent / ".cache"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "stock_research_dashboard.pid"


def _write_pid(path: Path, pid: int) -> None:
    path.write_text(str(pid), encoding="utf-8")


def _write_log(path: Path, message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"[{timestamp}] {message}\n")


if __name__ == "__main__":
    main()
