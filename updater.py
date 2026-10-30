"""Keeps yt-dlp current. YouTube changes every few weeks and an old yt-dlp simply stops working."""
import hashlib
import importlib.metadata
import io
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

import const
from const import colours

MARKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".ytdlp_last_check")
CHECK_EVERY_SECONDS = 24 * 60 * 60
PIP_TIMEOUT_SECONDS = 90


def _installed_version():
    try:
        return importlib.metadata.version("yt-dlp")
    except importlib.metadata.PackageNotFoundError:
        return None


def is_due(marker=MARKER, now=None, every=CHECK_EVERY_SECONDS):
    """True when the last successful check is older than `every` seconds (or there never was one)."""
    try:
        return (now or time.time()) - os.path.getmtime(marker) >= every
    except OSError:
        return True


def update_ytdlp_if_due(marker=MARKER, run=subprocess.run):
    """At most once a day, ask pip for a newer yt-dlp. Never raises: no internet just means no update.

    Must run before yt_dlp is imported, so that the new version is the one that gets used."""
    if getattr(sys, "frozen", False):
        return  # the compiled program has no pip; it ships the yt-dlp it was built with
    if not is_due(marker):
        return

    before = _installed_version()
    print(f"{colours.OKBLUE}[i] Buscando una versión nueva de yt-dlp (1 vez al día)...{colours.ENDC}")
    try:
        result = run([sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", "--disable-pip-version-check",
                      "--retries", "1", "--timeout", "10", "yt-dlp"],
                     capture_output=True, text=True, timeout=PIP_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        print(f"{colours.WARNING}[!] No pude buscar actualizaciones; sigo con la versión que tienes.{colours.ENDC}")
        return

    if result.returncode != 0:
        print(f"{colours.WARNING}[!] No pude actualizar yt-dlp (¿sin internet?); sigo con la versión que tienes.{colours.ENDC}")
        return

    try:
        with open(marker, "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
    except OSError:
        pass

    after = _installed_version()
    if before and after and before != after:
        print(f"{colours.OKGREEN}[i] yt-dlp actualizado: {before} -> {after}{colours.ENDC}")


# --- The compiled program (.exe) has no pip: it downloads yt-dlp itself, only when the user agrees --------------------

PYPI_URL = "https://pypi.org/pypi/yt-dlp/json"
WHEEL_HOST = "https://files.pythonhosted.org/"   # the only place a download is accepted from


class UpdateError(Exception):
    """The yt-dlp update could not be done; the message is for the user."""


def ytdlp_lib_dir():
    return os.path.join(const.data_dir(), "yt-dlp")


def _version_key(version):
    return tuple(int(n) for n in re.findall(r"\d+", version or ""))


def _version_in(lib):
    """Version of the yt-dlp inside `lib` (without importing it), or None."""
    try:
        with open(os.path.join(lib, "yt_dlp", "version.py"), encoding="utf-8") as f:
            found = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", f.read())
        return found.group(1) if found else None
    except OSError:
        return None


def bundled_ytdlp_version():
    return _installed_version()


def use_downloaded_ytdlp(lib=None):
    """Compiled program only, before yt_dlp is imported: if an update was downloaded earlier and it is newer
    than the yt-dlp the program was built with, use it. (A newer program release must win over an old download.)"""
    if not const.IS_FROZEN:
        return False
    lib = lib or ytdlp_lib_dir()
    downloaded = _version_in(lib)
    if not downloaded or _version_key(downloaded) <= _version_key(bundled_ytdlp_version()):
        return False
    sys.path.insert(0, lib)
    return True


def current_ytdlp_version():
    import yt_dlp.version
    return yt_dlp.version.__version__


def _safe_members(archive):
    """Only the yt_dlp package, and only inside the target folder (a malicious zip could try '../', or 'D:' in the middle
    of the name, which os.path.join takes as 'jump to that drive')."""
    for name in archive.namelist():
        parts = name.replace("\\", "/").split("/")
        if (parts[0] == "yt_dlp" and ".." not in parts and not os.path.isabs(name) and not name.endswith("/")
                and not any(":" in part for part in parts)):
            yield name


def download_latest_ytdlp(lib=None, get=None, current=None):
    """Download the newest yt-dlp from PyPI into `lib`. Returns (old_version, new_version), or None when the
    one in use is already the newest. The file is checked against the hash PyPI publishes before it is used.
    It takes effect the next time the program starts."""
    if get is None:
        import requests
        get = requests.get
    lib = lib or ytdlp_lib_dir()
    current = current or current_ytdlp_version()
    try:
        data = get(PYPI_URL, timeout=20).json()
        latest = data["info"]["version"]
        if _version_key(latest) <= _version_key(current):
            return None
        wheel = next(u for u in data["urls"] if u["filename"].endswith("-py3-none-any.whl"))
        if not wheel["url"].startswith(WHEEL_HOST):
            raise UpdateError("La dirección de descarga no es la oficial; no la uso.")
        content = get(wheel["url"], timeout=120).content
    except UpdateError:
        raise
    except Exception as error:   # no internet, PyPI changed its format, ...
        raise UpdateError(f"No pude descargar la actualización ({type(error).__name__}).") from None

    if hashlib.sha256(content).hexdigest() != wheel["digests"]["sha256"]:
        raise UpdateError("El archivo descargado no coincide con su firma de PyPI; no lo uso.")

    staging = lib + ".new"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for name in _safe_members(archive):
                target = os.path.join(staging, *name.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as f:
                    f.write(archive.read(name))
        if _version_in(staging) != latest:
            raise UpdateError("La actualización descargada está incompleta.")
        shutil.rmtree(lib, ignore_errors=True)
        os.replace(staging, lib)
    except UpdateError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except (OSError, zipfile.BadZipFile) as error:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(f"No pude guardar la actualización ({type(error).__name__}).") from None
    return current, latest
