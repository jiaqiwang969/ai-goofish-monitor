import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


def _log(msg: str) -> None:
    sys.stderr.write(f"[goofish-mcp] {msg}\n")
    sys.stderr.flush()


def _as_bool(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default


def auto_setup_enabled() -> bool:
    # Default: enabled. Set `GOOFISH_AUTO_SETUP=0` to disable.
    return _as_bool(os.getenv("GOOFISH_AUTO_SETUP"), default=True)


def _setup_lock_path() -> Path:
    return Path.home() / ".codex" / "goofish" / "setup.lock"


def _with_process_lock(fn) -> None:
    lock_path = _setup_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a", encoding="utf-8") as f:
        try:
            import fcntl  # type: ignore

            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        except Exception:
            # Best-effort: on non-unix platforms, just continue without a lock.
            pass
        fn()


def _run(cmd: List[str]) -> int:
    env = os.environ.copy()
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    env.setdefault("PIP_NO_INPUT", "1")
    # Important: never let subprocess write to stdout (reserved for MCP JSON).
    proc = subprocess.run(cmd, stdout=sys.stderr, stderr=sys.stderr, env=env)
    return int(proc.returncode)


def _can_import_playwright() -> bool:
    try:
        import playwright  # type: ignore  # noqa: F401
    except Exception:
        return False
    return True


def _ensure_pip_available() -> bool:
    # `python -m pip` is usually available; if not, try ensurepip.
    rc = subprocess.run(
        [sys.executable, "-m", "pip", "--version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode
    if rc == 0:
        return True
    rc2 = _run([sys.executable, "-m", "ensurepip", "--upgrade"])
    return rc2 == 0


def _ensure_playwright_python_installed() -> bool:
    if _can_import_playwright():
        return True
    _log("Playwright (python) missing; installing...")
    if not _ensure_pip_available():
        _log("pip is unavailable; auto-setup cannot proceed.")
        return False
    rc = _run([sys.executable, "-m", "pip", "install", "--user", "-U", "playwright>=1.40.0"])
    if rc != 0:
        _log(f"pip install playwright failed (rc={rc}).")
        return False
    # Re-check importability (invalidate caches for safety).
    try:
        import importlib

        importlib.invalidate_caches()
    except Exception:
        pass
    return _can_import_playwright()


_INSTALL_LOCATION_RE = re.compile(r"Install location:\s*(?P<path>.+)$")


def _playwright_install_locations_for_chromium() -> Tuple[bool, List[str]]:
    # Returns (ok, locations). ok=false means we couldn't determine.
    if not _can_import_playwright():
        return (False, [])

    proc = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=os.environ.copy(),
    )
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")

    locations: List[str] = []
    for line in out.splitlines():
        m = _INSTALL_LOCATION_RE.search(line)
        if not m:
            continue
        path = m.group("path").strip()
        if path:
            locations.append(path)
    if not locations:
        return (False, [])
    return (True, locations)


def _chromium_installed() -> Optional[bool]:
    ok, locations = _playwright_install_locations_for_chromium()
    if not ok:
        return None
    return all(os.path.exists(p) for p in locations)


def _ensure_playwright_chromium_installed() -> bool:
    installed = _chromium_installed()
    if installed is True:
        return True
    if installed is None:
        _log("Unable to determine Playwright Chromium install status; attempting install anyway...")
    else:
        _log("Playwright Chromium missing; installing browsers...")

    rc = _run([sys.executable, "-m", "playwright", "install", "chromium"])
    if rc != 0:
        _log(f"playwright install chromium failed (rc={rc}).")
        return False
    installed2 = _chromium_installed()
    return installed2 is not False


@dataclass
class SetupStatus:
    state: str  # idle|running|ready|error
    last_error: Optional[str] = None
    last_updated_ts: float = 0.0


_status = SetupStatus(state="idle", last_updated_ts=time.time())
_status_lock = threading.Lock()
_setup_thread: Optional[threading.Thread] = None


def get_setup_status() -> SetupStatus:
    with _status_lock:
        return SetupStatus(
            state=_status.state,
            last_error=_status.last_error,
            last_updated_ts=_status.last_updated_ts,
        )


def _set_status(state: str, last_error: Optional[str] = None) -> None:
    with _status_lock:
        _status.state = state
        _status.last_error = last_error
        _status.last_updated_ts = time.time()


def ensure_runtime_ready() -> bool:
    if not auto_setup_enabled():
        return _can_import_playwright()

    def _do() -> None:
        try:
            _set_status("running", None)
            if not _ensure_playwright_python_installed():
                _set_status("error", "failed to install python playwright")
                return
            if not _ensure_playwright_chromium_installed():
                _set_status("error", "failed to install playwright chromium")
                return
            _set_status("ready", None)
        except Exception as e:
            _set_status("error", f"{type(e).__name__}: {e}")

    _with_process_lock(_do)
    return get_setup_status().state == "ready"


def start_background_setup() -> None:
    global _setup_thread
    if not auto_setup_enabled():
        return
    with _status_lock:
        if _setup_thread is not None and _setup_thread.is_alive():
            return
        if _status.state == "ready":
            return

    def runner() -> None:
        # Quick fast-path: skip if already installed.
        try:
            if _can_import_playwright() and _chromium_installed() is True:
                _set_status("ready", None)
                return
        except Exception:
            pass
        _log("Auto-setup: ensuring Playwright runtime is available (this runs only if needed)...")
        ok = ensure_runtime_ready()
        if ok:
            _log("Auto-setup: Playwright runtime ready.")
        else:
            st = get_setup_status()
            _log(f"Auto-setup: failed ({st.last_error}).")

    t = threading.Thread(target=runner, name="goofish-auto-setup", daemon=True)
    _setup_thread = t
    t.start()


def probe_runtime() -> dict:
    playwright_installed = _can_import_playwright()
    chromium_installed = _chromium_installed() if playwright_installed else None
    ok, locations = _playwright_install_locations_for_chromium() if playwright_installed else (False, [])
    return {
        "auto_setup_enabled": auto_setup_enabled(),
        "playwright_installed": playwright_installed,
        "chromium_installed": chromium_installed,
        "chromium_install_locations": locations if ok else [],
        "setup_status": {
            "state": get_setup_status().state,
            "last_error": get_setup_status().last_error,
            "last_updated_ts": get_setup_status().last_updated_ts,
        },
    }
