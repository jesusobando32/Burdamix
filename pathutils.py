import os
import re
import unicodedata

_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

WINDOWS_CLASSIC_LIMIT = 259  # longest path most Windows programs can open without long-path support


def sanitize_filename(name, fallback="Unknown"):
    """Make `name` safe as a Windows/macOS/Linux file or folder name.

    Keeps accents and non-Latin scripts; only strips what the filesystems reject, plus invisible
    formatting characters (such as the right-to-left override that can disguise a file name).
    """
    cleaned = _ILLEGAL_CHARS.sub("", name or "")
    cleaned = "".join(c for c in cleaned if unicodedata.category(c) != "Cf")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(". ")

    if not cleaned:
        return fallback

    if cleaned.split(".")[0].upper() in _RESERVED_NAMES:
        cleaned = "_" + cleaned

    return cleaned[:150].rstrip(". ")


def long_path(path):
    """Path to use for creating, writing and checking files.

    On Windows, adds the extended-length prefix so paths above 260 characters work without the user
    having to change any system setting. Elsewhere the path is returned unchanged."""
    path = str(path)
    if os.name != "nt":
        return path

    prefix = "\\" * 2 + "?" + "\\"
    full = os.path.abspath(path)
    if full.startswith(prefix):
        return full
    if full.startswith("\\" * 2):                       # network share: \\server\share
        return prefix + "UNC" + full[1:]
    return prefix + full


def is_hard_to_open(path):
    """True when the file will be written fine, but some Windows programs (older Explorer, players)
    may fail to open it because the path is longer than the classic limit."""
    return os.name == "nt" and len(os.path.abspath(str(path))) > WINDOWS_CLASSIC_LIMIT
