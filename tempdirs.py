"""One private temporary folder per run, in the system's temporary location.

Files being downloaded or converted live here. Two copies of the program running at once each get
their own folder, so one finishing never deletes the other's files, and nothing is left in the project."""
import contextlib
import os
import shutil
import tempfile
import threading
import time

ROOT = os.path.join(tempfile.gettempdir(), "Burdamix")
STALE_AFTER_SECONDS = 12 * 60 * 60   # a run folder untouched this long belongs to a run that was killed

_run_dir = None
_lock = threading.Lock()


def run_dir():
    """The temporary folder of this run (created on first use)."""
    global _run_dir
    with _lock:
        if _run_dir is None or not os.path.isdir(_run_dir):
            os.makedirs(ROOT, exist_ok=True)
            _run_dir = tempfile.mkdtemp(prefix="run-", dir=ROOT)
        return _run_dir


def remove_run_dir():
    """Delete this run's folder (and the parent if nobody else is using it)."""
    global _run_dir
    with _lock:
        if _run_dir is not None:
            shutil.rmtree(_run_dir, ignore_errors=True)
            _run_dir = None
        with contextlib.suppress(OSError):
            os.rmdir(ROOT)   # only succeeds when it is empty


def clean_stale(now=None, max_age=STALE_AFTER_SECONDS):
    """Remove run folders that nobody touched for hours, left behind by a run that was closed by force."""
    now = now or time.time()
    try:
        names = os.listdir(ROOT)
    except OSError:
        return
    for name in names:
        path = os.path.join(ROOT, name)
        with contextlib.suppress(OSError):
            if name.startswith("run-") and now - os.path.getmtime(path) > max_age:
                shutil.rmtree(path, ignore_errors=True)
