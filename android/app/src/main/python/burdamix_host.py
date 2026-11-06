"""What the Android WebView talks to. WebActivity calls `start(...)` once, then `methods()` once and `call(name, args_json)` for
every call of the page; both go through bridge.py (copied from gui/bridge.py at build time), the same rules as the desktop window.

The Api is the program's own `gui.backend.Api`. Only what Windows did differently is replaced here: where the data and the songs
live, which ffmpeg converts, and what deleting a song means (there is no Recycle Bin). Things that need Android's own screens
(choosing a folder, opening a link, picking files) still raise and reach the page as an error; they come next.
"""
import json
import os
import shutil
import time

import bridge

HIDDEN = ("attach_window",)

_api = None


def _open_url(url, *ignored):
    """webbrowser.open for Android: the system opens the link (Kotlin side: Platform.openUrl)."""
    from java import jclass
    return bool(jclass("app.burdamix.Platform").openUrl(url))


def start(files_dir, music_dir, ffmpeg, lib_dirs):
    """Prepares the environment and creates the Api. Must be called before the page loads."""
    global _api
    os.environ["XDG_CONFIG_HOME"] = files_dir                 # const.data_dir() -> <files>/Burdamix
    os.environ["BURDAMIX_FFMPEG"] = ffmpeg                    # utils.ffmpeg_command()
    os.environ["LD_LIBRARY_PATH"] = lib_dirs + (":" + os.environ["LD_LIBRARY_PATH"] if os.environ.get("LD_LIBRARY_PATH") else "")
    os.makedirs(music_dir, exist_ok=True)

    import webbrowser
    webbrowser.open = _open_url        # before login.py is imported: it keeps webbrowser.open as a default argument

    import const
    const.DOWNLOADS_DIR = music_dir
    import trash
    import login
    login.USE_THREAD_SERVER = True     # no multiprocessing on Android: the Spotify login server runs in a thread
    from gui.backend import Api

    trash_dir = os.path.join(files_dir, "Burdamix", "papelera")

    def move_to_trash(path):
        """The app's own bin: the song waits in a folder (purged after 30 days, a later step) instead of being deleted for good."""
        if not isinstance(path, str) or not os.path.isfile(path):
            raise trash.TrashError("El archivo ya no está en su sitio.")
        os.makedirs(trash_dir, exist_ok=True)
        shutil.move(path, os.path.join(trash_dir, f"{int(time.time())}-{os.path.basename(path)}"))

    _api = Api()
    _api._trash = move_to_trash


def methods():
    """The names the page may call, as JSON text."""
    return json.dumps(bridge.methods(_api, HIDDEN))


def call(name, args_json):
    return bridge.call(_api, name, args_json, HIDDEN)
