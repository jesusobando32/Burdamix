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

# Songs always go here, inside the project, whatever folder the program is started from.
DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")

DEFAULT_MIN_VIEWS_FOR_DOWNLOAD = 0  # the duration match already rules out wrong videos
DEFAULT_MAX_LENGTH_FOR_DOWNLOAD = 60*30

UNKNOWN_ALBUM_COVER_URL = "https://github.com/jesusobando32/Burdamix/blob/main/assets/unknown-song.png?raw=true"
HELP_URL = "https://github.com/jesusobando32/Burdamix/issues"