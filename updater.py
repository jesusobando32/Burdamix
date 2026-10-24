"""Keeps yt-dlp current. YouTube changes every few weeks and an old yt-dlp simply stops working."""
import importlib.metadata
import os
import subprocess
import sys
import time

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
