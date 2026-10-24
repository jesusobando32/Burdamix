from enum import Enum
import sys
import os

def supports_24bit_color():
    """Determine if the terminal supports 24-bit color."""
    if sys.platform != "win32":
        return os.getenv("COLORTERM") == "truecolor"
    return False

class SpotifyAuthType(str, Enum):
    USER = 'user'
    ANONYMOUS = 'anonymous'

class colours:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    CVIOLETBG2 = '\33[105m'
    SPOTIFYGREEN = '\033[38;2;30;215;96m' if supports_24bit_color() else '\033[92m'


LIKED_KEYWORD = "liked"

IS_FROZEN = getattr(sys, "frozen", False)  # True inside the compiled program (PyInstaller)
PORTABLE_MARKER = "portable.txt"           # an empty file with this name next to the .exe keeps everything in its folder


def app_dir():
    """Folder of the project, or of the .exe when compiled."""
    if IS_FROZEN:
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def is_portable():
    return IS_FROZEN and os.path.exists(os.path.join(app_dir(), PORTABLE_MARKER))


def _downloads_dir():
    """Songs go inside the project when run as a script, next to the .exe when portable,
    and in the user's Music folder when installed (Program Files cannot be written to)."""
    if IS_FROZEN and not is_portable():
        return os.path.join(os.path.expanduser("~"), "Music", "Burdamix")
    return os.path.join(app_dir(), "downloads")


DOWNLOADS_DIR = _downloads_dir()

DEFAULT_MIN_VIEWS_FOR_DOWNLOAD = 0  # the duration match already rules out wrong videos
DEFAULT_MAX_LENGTH_FOR_DOWNLOAD = 60*30

UNKNOWN_ALBUM_COVER_URL = "https://github.com/jesusobando32/Burdamix/blob/main/assets/unknown-song.png?raw=true"
HELP_URL = "https://github.com/jesusobando32/Burdamix/issues"