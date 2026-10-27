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


APP_VERSION = "0.2.0-pre"
# How a downloaded song's file is named. The artist is always written inside the tags too, so a name with only the title loses nothing.
NAME_STYLES = {"artist_title": "Artista - Título", "title_artist": "Título - Artista", "title": "Solo el título"}
DEFAULT_NAME_STYLE = "artist_title"
LIKED_KEYWORD = "liked"

IS_FROZEN = getattr(sys, "frozen", False)  # True inside the compiled program (PyInstaller)
PORTABLE_MARKER = "portable.txt"           # an empty file with this name next to the .exe keeps everything in its folder


def app_dir():
    """Folder of the project, or of the .exe when compiled."""
    if IS_FROZEN:
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resource_dir():
    """Where the program's own files (like the window's web page) are: next to the code, or inside the .exe's bundle."""
    if IS_FROZEN:
        return getattr(sys, "_MEIPASS", app_dir())
    return os.path.dirname(os.path.abspath(__file__))


def is_portable():
    return IS_FROZEN and os.path.exists(os.path.join(app_dir(), PORTABLE_MARKER))


def data_dir():
    """Private folder of the user for settings and the yt-dlp updates. It is outside the project: it is not
    inside Documents (so OneDrive does not sync it) and it is not included when the project folder is zipped
    to share it. The portable version keeps it in a "datos" folder next to the .exe."""
    if is_portable():
        return os.path.join(app_dir(), "datos")
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "Burdamix")


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