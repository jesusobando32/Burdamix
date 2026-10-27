"""What the window can ask the program to do. Every public method of `Api` is callable from JavaScript
(window.pywebview.api.<name>); everything private (leading underscore) is not exposed.

The window never blocks: long jobs (login, download) run in threads and the window asks for news with
get_events() / get_login_state()."""
import json
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser

import const
import downloader
import login
import tempdirs
import updater
from apis.spotify import Spotify, SpotifyNetworkError, SpotifyRateLimited
from apis.text_search import search_songs
from apis.text_track import TextTrack
from apis.youtube import YouTube, SUPPORTED_BROWSERS
from const import SpotifyAuthType
from gui.tags_jobs import TagJobs
from downloader import ADVICE, SpotifyDownloader, friendly_reason, plan_filenames, reason_category, suggests_outdated_ytdlp
from exceptions import (InvalidSpotifyURL, SpotifyAlbumNotFound, SpotifyPlaylistNotFound, SpotifyRetrievalError,
                        SpotifyTrackNotFound)
from pathutils import sanitize_filename

DEFAULT_SETTINGS = {"downloads_dir": "", "workers": 5, "skip_interludes": True, "browser": "", "name_style": const.DEFAULT_NAME_STYLE}
MAX_WORKERS = 8
TEXT_RESULTS = 5               # songs offered when the user types a name instead of pasting a link
LINK = re.compile(r"https?://|spotify[:.]|/(?:track|album|playlist)/", re.I)   # anything else is a song name to search
BEST_QUALITY_BPS = 320000      # "the best YouTube has": the real bitrate is whatever the best stream is (~130 kbps)

# Pages the window may open in the user's browser; nothing else is ever opened from a link in the page.
ALLOWED_LINKS = ("https://developer.spotify.com/", "https://github.com/jesusobando32/Burdamix", "https://open.spotify.com/")


def _validate_spotify_url(url):
    from spotify2mp3 import validate_spotify_url   # same rules as the console version
    return validate_spotify_url(url)


class Api:
    def __init__(self):
        self._lock = threading.Lock()
        self._events = []
        self._login = {"state": "idle", "message": ""}
        self._pending = None        # the list the user is looking at (songs, folder, Spotify session)
        self._downloader = None     # the running download, if any
        self._busy = False
        self._window = None
        self._tags = TagJobs()      # "Completar etiquetas": its own jobs and events, apart from the downloads
        self._settings = self._load_settings()
        self._apply_settings()

    def attach_window(self, window):
        self._window = window
        window.events.loaded += self._on_page_loaded

    def _on_page_loaded(self):
        """Files dropped onto the window arrive here with their full path (the page itself cannot see paths)."""
        from webview.dom import DOMEventHandler
        self._window.dom.document.events.drop += DOMEventHandler(self._on_drop, prevent_default=True, stop_propagation=True)

    def _on_drop(self, event):
        files = ((event or {}).get("dataTransfer") or {}).get("files") or []
        paths = [f["pywebviewFullPath"] for f in files if isinstance(f, dict) and f.get("pywebviewFullPath")]
        if paths:
            self._tags.push("dropped", paths=paths)

    # --- settings ---------------------------------------------------------------------------------------------

    def _settings_path(self):
        return os.path.join(const.data_dir(), "settings.json")

    def _load_settings(self):
        settings = dict(DEFAULT_SETTINGS)
        try:
            with open(self._settings_path(), encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                settings.update({k: v for k, v in saved.items() if k in DEFAULT_SETTINGS})
        except (OSError, ValueError):
            pass
        return self._clean_settings(settings)

    @staticmethod
    def _clean_settings(settings):
        try:
            workers = int(settings.get("workers", 5))
        except (TypeError, ValueError):
            workers = 5
        browser = settings.get("browser") or ""
        return {
            "downloads_dir": str(settings.get("downloads_dir") or ""),
            "workers": max(1, min(MAX_WORKERS, workers)),
            "skip_interludes": bool(settings.get("skip_interludes", True)),
            "browser": browser if browser in SUPPORTED_BROWSERS else "",
            "name_style": settings.get("name_style") if settings.get("name_style") in const.NAME_STYLES else const.DEFAULT_NAME_STYLE,
        }

    def _downloads_dir(self):
        return self._settings["downloads_dir"] or const.DOWNLOADS_DIR

    def _apply_settings(self):
        downloader.DOWNLOADS_DIR = self._downloads_dir()

    def get_settings(self):
        return {**self._settings, "effective_downloads_dir": self._downloads_dir(), "browsers": list(SUPPORTED_BROWSERS),
                "name_styles": [{"id": key, "label": label} for key, label in const.NAME_STYLES.items()]}

    def save_settings(self, new_settings):
        merged = {**self._settings, **(new_settings or {})}
        self._settings = self._clean_settings(merged)
        self._apply_settings()
        try:
            os.makedirs(const.data_dir(), exist_ok=True)
            with open(self._settings_path(), "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2)
        except OSError:
            return {"ok": False, "error": "No pude guardar los ajustes."}
        return {"ok": True, **self.get_settings()}

    # --- state ------------------------------------------------------------------------------------------------

    def get_state(self):
        try:
            ytdlp = updater.current_ytdlp_version()
        except Exception:
            ytdlp = ""
        return {
            "version": const.APP_VERSION,
            "ytdlp": ytdlp,
            "frozen": const.IS_FROZEN,
            "configured": login.is_client_configured(),
            "logged_in": login.is_user_logged_in(),
            "redirect_uri": login.login_redirect_url,
            "dashboard_url": login.dashboard_url,
            "busy": self._busy,
            "downloads_dir": self._downloads_dir(),
        }

    # --- connecting to Spotify -------------------------------------------------------------------------------

    def save_spotify_app(self, client_id, client_secret):
        error = login.save_client_credentials(client_id, client_secret)
        return {"ok": error is None, "error": error}

    def login_spotify(self):
        if self._login["state"] == "waiting":
            return {"ok": True}
        self._login = {"state": "waiting", "message": ""}

        def work():
            try:
                ok, message = login.run_user_login_flow()
            except Exception as error:   # never leave the window waiting forever
                ok, message = False, f"No pude iniciar sesión ({type(error).__name__})."
            self._login = {"state": "ok" if ok else "failed", "message": message}

        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    def get_login_state(self):
        return dict(self._login)

    def open_external(self, url):
        if isinstance(url, str) and url.startswith(ALLOWED_LINKS):
            webbrowser.open(url)
            return True
        return False

    # --- looking at a link before downloading ----------------------------------------------------------------

    def preview(self, url, last=None):
        """The songs behind a Spotify link, with covers and what is already on disk. Nothing is downloaded.
        Text that is not a link ("badtrip mora") is searched as a song name instead; that needs no Spotify at all."""
        if (url or "").strip() and not LINK.search(url):
            return self._preview_text(url.strip())
        try:
            kind = _validate_spotify_url(url or "")
        except ValueError as error:
            return {"error": str(error)}
        return self._preview(kind, (url or "").strip(), last)

    def preview_liked(self, last=None):
        try:
            last = int(last) if last else None
        except (TypeError, ValueError):
            return {"error": "Escribe un número de canciones."}
        if last is not None and last < 1:
            return {"error": "Escribe un número mayor que 0."}
        return self._preview("liked", None, last)

    def _preview_text(self, text):
        """The songs a name may mean, best first and only the first one marked, with their official data. Needs no account."""
        if self._busy:
            return {"error": "Hay una descarga en curso. Espera a que termine o cancélala."}
        self._apply_settings()
        try:
            songs, problems = search_songs(text, TEXT_RESULTS)
        except Exception as error:
            return {"error": f"Algo salió mal al buscar ({type(error).__name__})."}
        if not songs:
            if problems:
                return {"error": f"No pude buscar esa canción: {problems[0]}"}
            return {"error": "No encontré esa canción. Prueba con el título y el artista, por ejemplo «badtrip mora»."}

        helper = self._make_downloader(spotify=None, youtube=None)
        output_path = os.path.join(self._downloads_dir(), "tracks") + os.sep
        plan, _repeated, _renamed = plan_filenames([TextTrack(song, asked=text) for song in songs], self._settings["name_style"])
        items = []
        for _index, track, name in plan:
            meta = track.get_metadata()
            items.append({
                "key": track.resource_id, "title": track.get_title(), "artists": track.get_artist(),
                "album": meta["album"], "seconds": round(meta["duration_ms"] / 1000), "cover": meta["image_url"],
                "saved": "", "already": helper.already_downloaded(track, name, output_path),
            })

        self._pending = {"spotify": None, "tracks": {t.resource_id: t for _i, t, _n in plan}, "output_path": output_path,
                         "kind": "search"}
        first = items[0]
        return {"kind": "search", "title": text, "cover": first["cover"], "items": items, "total": len(items), "folder": output_path,
                "interludes": [], "repeated": 0, "limited": False, "preselect": [] if first["already"] else [first["key"]]}

    def _preview(self, kind, url, last):
        if self._busy:
            return {"error": "Hay una descarga en curso. Espera a que termine o cancélala."}
        if not login.is_client_configured():
            return {"error": "setup_required", "message": "Primero conecta el programa con Spotify (Tutorial)."}
        needs_login = kind in ("playlist", "liked")
        if needs_login and not login.is_user_logged_in():
            return {"error": "login_required", "message": "Para leer tus playlists y tus favoritos hay que iniciar sesión en Spotify."}

        self._apply_settings()
        try:
            spotify = Spotify(SpotifyAuthType.USER if needs_login else SpotifyAuthType.ANONYMOUS)
        except Exception:
            return {"error": "No pude conectarme a Spotify. Si cambiaste o borraste tu app de Spotify, vuelve a conectarla en Tutorial."}

        helper = self._make_downloader(spotify=None, youtube=None)
        try:
            if kind == "song":
                track = spotify.track(url)
                track.get_title()   # loads it
                tracks, title, image, folder, total = [track], track.get_title(), track.get_metadata()["image_url"], "tracks", 1
                output_path = os.path.join(self._downloads_dir(), "tracks") + os.sep
            else:
                if kind == "album":
                    collection, folder = spotify.album(url), "albums"
                elif kind == "playlist":
                    collection, folder = spotify.playlist(url), "playlists"
                else:
                    collection, folder = spotify.likedSongs(last), "liked"
                title = collection.get_title()
                tracks = collection.get_tracks()
                image = collection.metadata.get("image_url") if kind != "liked" else None
                total = getattr(collection, "total", None) or len(tracks)
                output_path = os.path.join(self._downloads_dir(), folder, sanitize_filename(title)) + os.sep
        except (SpotifyAlbumNotFound, SpotifyPlaylistNotFound, SpotifyTrackNotFound):
            return {"error": "Spotify no encontró ese enlace. Revisa que esté completo."}
        except (SpotifyNetworkError, SpotifyRateLimited) as error:
            return {"error": f"No pude hablar con Spotify: {error}"}
        except (SpotifyRetrievalError, InvalidSpotifyURL):
            return {"error": "No pude leer eso de Spotify. Las playlists solo se pueden leer si son TUYAS."}
        except Exception as error:
            return {"error": f"Algo salió mal al leer el enlace ({type(error).__name__})."}

        tracks, interludes = helper.split_interludes(tracks)
        plan, repeated, _renamed = plan_filenames(tracks, self._settings["name_style"])
        items = []
        for _index, track, name in plan:
            meta = track.get_metadata()
            items.append({
                "key": track.resource_id,
                "title": track.get_title(),
                "artists": ", ".join(meta["artist"]),
                "album": meta["album"],
                "seconds": round(meta["duration_ms"] / 1000),
                "cover": meta["image_url"],
                "saved": (getattr(track, "added_at", None) or "")[:10],
                "already": helper.already_downloaded(track, name, output_path),
            })

        self._pending = {"spotify": spotify, "tracks": {t.resource_id: t for _i, t, _n in plan}, "output_path": output_path,
                         "kind": kind}
        return {"kind": kind, "title": title, "cover": image, "items": items, "total": total, "folder": output_path,
                "interludes": [t.get_title() for t in interludes], "repeated": len(repeated),
                "limited": bool(last) and total > len(items)}

    # --- downloading -----------------------------------------------------------------------------------------

    def _make_downloader(self, spotify, youtube):
        return SpotifyDownloader(spotify, youtube, BEST_QUALITY_BPS, const.DEFAULT_MAX_LENGTH_FOR_DOWNLOAD,
                                 const.DEFAULT_MIN_VIEWS_FOR_DOWNLOAD, self._settings["workers"],
                                 skip_interludes=self._settings["skip_interludes"], on_event=self._push,
                                 name_style=self._settings["name_style"])

    def _push(self, kind, **data):
        with self._lock:
            self._events.append({"kind": kind, "t": time.time(), **data})

    def get_events(self):
        with self._lock:
            events, self._events = self._events, []
        return events

    def start_download(self, keys):
        if self._busy:
            return {"ok": False, "error": "Ya hay una descarga en curso."}
        pending = self._pending
        if not pending:
            return {"ok": False, "error": "Primero pega un enlace."}
        chosen = [pending["tracks"][k] for k in (keys or []) if k in pending["tracks"]]
        if not chosen:
            return {"ok": False, "error": "No hay canciones marcadas."}

        self._busy = True
        with self._lock:
            self._events = []
        threading.Thread(target=self._run_download, args=(pending, chosen), daemon=True).start()
        return {"ok": True, "count": len(chosen)}

    def _run_download(self, pending, chosen):
        summary = {"folder": pending["output_path"], "failed": [], "blocked": False, "cancelled": False,
                   "advice": [], "outdated_ytdlp": False, "error": None}
        d = None
        try:
            tempdirs.clean_stale()
            d = self._make_downloader(pending["spotify"], YouTube(self._settings["browser"] or None))
            self._downloader = d
            d.prep_folder(pending["output_path"])
            skipped = d.download_tracks(pending["output_path"], chosen)

            summary["blocked"] = d.blocked
            summary["cancelled"] = d.cancelled.is_set()
            summary["outdated_ytdlp"] = any(suggests_outdated_ytdlp(e) for _, e in skipped)
            for track, error in skipped:
                summary["failed"].append({"key": track.resource_id, "title": track.get_title(),
                                          "artists": track.get_artist(), "reason": friendly_reason(error),
                                          "category": reason_category(error)})
            summary["advice"] = [ADVICE[c] for c in ADVICE if any(f["category"] == c for f in summary["failed"])]
        except Exception as error:   # whatever happens, the window must hear the download ended
            summary["error"] = f"La descarga se detuvo ({type(error).__name__})."
        finally:
            if d is not None:
                d.rm_tmp_folder()
            self._downloader = None
            self._busy = False
            self._push("finished", **summary)

    def cancel_download(self):
        d = self._downloader
        if d is not None:
            d.cancelled.set()
        return d is not None

    # --- completing tags and covers of audio files ---------------------------------------------------------------

    def tags_pick_files(self):
        if self._window is None:
            return []
        import webview
        kind = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
        chosen = self._window.create_file_dialog(kind, allow_multiple=True,
                                                 file_types=("Audio (*.mp3;*.flac;*.m4a;*.ogg;*.oga;*.opus)", "Todos los archivos (*.*)"))
        return list(chosen or [])

    def tags_pick_folder(self):
        chosen = self.choose_folder()
        return [chosen] if chosen else []

    def tags_pick_image(self):
        if self._window is None:
            return None
        import webview
        kind = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
        chosen = self._window.create_file_dialog(kind, file_types=("Imágenes (*.jpg;*.jpeg;*.png;*.webp;*.bmp)", "Todos los archivos (*.*)"))
        return chosen[0] if chosen else None

    def tags_set_cover(self, path, image_path):
        return self._tags.set_cover(path, image_path)

    def tags_scan(self, paths):
        return self._tags.scan(paths if isinstance(paths, list) else [])

    def tags_identify(self, paths, title=None, artist=None, skip_complete=True):
        return self._tags.identify(paths, title, artist, skip_complete)

    def tags_prepare(self, path, candidate):
        return self._tags.prepare(path, candidate, self._settings["name_style"])

    def tags_cover_preview(self, candidate):
        return self._tags.cover_preview(candidate)

    def tags_apply(self, items, rename=False):
        return self._tags.apply(items, rename, self._settings["name_style"])

    def tags_cancel(self):
        return self._tags.cancel()

    def get_tag_events(self):
        return self._tags.get_events()

    # --- folders and updates ---------------------------------------------------------------------------------

    def open_folder(self, path=None):
        target = path or self._downloads_dir()
        while target and not os.path.isdir(target):   # the folder appears with the first download: open what exists
            parent = os.path.dirname(target.rstrip("\\/"))
            if parent == target:
                return False
            target = parent
        if not target:
            return False
        if sys.platform == "win32":
            os.startfile(target)
        else:
            subprocess.Popen(["xdg-open", target])
        return True

    def choose_folder(self):
        if self._window is None:
            return None
        import webview
        kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        chosen = self._window.create_file_dialog(kind, directory=self._downloads_dir())
        return chosen[0] if chosen else None

    def update_ytdlp(self):
        """Look for a newer yt-dlp. In the compiled program it is downloaded; as a script, pip does it."""
        try:
            if const.IS_FROZEN:
                result = updater.download_latest_ytdlp()
                if result is None:
                    return {"ok": True, "message": "Ya tienes la versión más nueva de yt-dlp."}
                return {"ok": True, "restart": True,
                        "message": f"yt-dlp actualizado: {result[0]} -> {result[1]}. Cierra Burdamix y ábrelo otra vez."}
            done = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", "yt-dlp"],
                                  capture_output=True, text=True, timeout=120)
            if done.returncode != 0:
                return {"ok": False, "message": "No pude actualizar yt-dlp (¿sin internet?)."}
            return {"ok": True, "restart": True, "message": "yt-dlp actualizado. Cierra Burdamix y ábrelo otra vez."}
        except updater.UpdateError as error:
            return {"ok": False, "message": str(error)}
        except (OSError, subprocess.SubprocessError):
            return {"ok": False, "message": "No pude actualizar yt-dlp (¿sin internet?)."}
