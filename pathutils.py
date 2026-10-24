import re

_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_filename(name, fallback="Unknown"):
    """Make `name` safe as a Windows/macOS/Linux file or folder name.

    Keeps accents and non-Latin scripts; only strips what the filesystems reject.
    """
    cleaned = _ILLEGAL_CHARS.sub("", name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(". ")

    if not cleaned:
        return fallback

    if cleaned.split(".")[0].upper() in _RESERVED_NAMES:
        cleaned = "_" + cleaned

    return cleaned[:150].rstrip(". ")
