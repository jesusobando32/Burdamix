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


def migrate_music(old_dir, new_dir, renamed=None):
    """Moves the songs of the app's private folder to the public Music/Burdamix (the user can see it in any file manager).
    `renamed(old_path, new_path)` is told of every song moved: likes and playlists point at paths. A song that already exists in the
    new folder is never overwritten (it stays where it was). Returns how many songs moved."""
    if not old_dir or not os.path.isdir(old_dir) or os.path.abspath(old_dir) == os.path.abspath(new_dir):
        return 0
    moved = 0
    for root, _, names in os.walk(old_dir):
        for name in names:
            source = os.path.join(root, name)
            target = os.path.join(new_dir, os.path.relpath(source, old_dir))
            if os.path.exists(target):
                continue
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.move(source, target)
            except OSError:
                continue                                # the song stays in the old folder: the next launch tries again
            moved += 1
            if renamed:
                renamed(source, target)
    for root, folders, names in os.walk(old_dir, topdown=False):       # the empty folders left behind
        if root != old_dir and not os.listdir(root):
            try:
                os.rmdir(root)
            except OSError:
                pass
    return moved


def start(files_dir, music_dir, ffmpeg, lib_dirs, share_dir=None, old_music_dir=None):
    """Prepares the environment and creates the Api. Must be called before the page loads.
    `share_dir`: the folder of the app's cache that Android's file provider may hand to other apps (the cards of shared playlists).
    `old_music_dir`: the private folder the songs used to live in; whatever is still there moves to `music_dir`."""
    global _api
    if share_dir:
        os.environ["BURDAMIX_SHARE_DIR"] = share_dir          # gui.backend.Api.share_card_file writes there
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
    if old_music_dir:
        migrate_music(old_music_dir, music_dir, _api._collections.renamed)

    def open_folder(path=None):
        """The system's file manager at the songs' folder (Platform.openFolder); False when no app can show it."""
        from java import jclass
        return bool(jclass("app.burdamix.Platform").openFolder(path or _api._downloads_dir()))

    _api.open_folder = open_folder


def busy():
    """Whether a download or a tag job is running. The service that keeps the app alive in the background asks this every few
    seconds and stops itself when the answer is no, so it never outlives the work (even if the page is gone)."""
    api = _api
    if api is None:
        return False
    return bool(getattr(api, "_busy", False) or getattr(getattr(api, "_tags", None), "_busy", False))


def methods():
    """The names the page may call, as JSON text."""
    return json.dumps(bridge.methods(_api, HIDDEN))


def call(name, args_json):
    return bridge.call(_api, name, args_json, HIDDEN)
