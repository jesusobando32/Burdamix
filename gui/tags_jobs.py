"""The window's "Completar etiquetas" jobs: looking songs up and writing their tags without freezing the window.

Same pattern as the downloads: the work runs in a thread and the window asks for news with get_events(). Tagging has
its own event list and its own busy flag, so it never mixes with a download that is running at the same time."""
import os
import threading
import time

import autotag
import tagwriter
from apis.song_info import SongInfo
from exceptions import MetadataError, MetadataNetworkError, MetadataRateLimited
from pathutils import long_path

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
MAX_IMAGE_BYTES = 15 * 1024 * 1024


class TagJobs:
    def __init__(self, tagger=None):
        self._tagger = tagger
        self._lock = threading.Lock()
        self._events = []
        self._busy = False
        self._cancel = threading.Event()

    # --- plumbing ---

    @property
    def tagger(self):
        if self._tagger is None:      # built on first use: creating the services costs nothing, but there is no reason to do it earlier
            self._tagger = autotag.AutoTagger()
        return self._tagger

    def push(self, kind, **data):
        with self._lock:
            self._events.append({"kind": kind, "t": time.time(), **data})

    def get_events(self):
        with self._lock:
            events, self._events = self._events, []
        return events

    @property
    def busy(self):
        return self._busy

    def cancel(self):
        self._cancel.set()
        return self._busy

    def _start(self, target, *args):
        if self._busy:
            return {"ok": False, "error": "Ya hay un proceso de etiquetas en marcha. Espera a que termine o cancélalo."}
        self._busy = True
        self._cancel.clear()
        threading.Thread(target=target, args=args, daemon=True).start()
        return {"ok": True}

    # --- looking at the files ---

    @staticmethod
    def scan(paths):
        """The audio files behind what the user picked (folders are searched), with the tags each has now."""
        files = []
        for path in autotag.collect_audio_files(paths):
            entry = {"path": path, "name": os.path.basename(path)}
            try:
                entry["tags"] = tagwriter.read_tags(path).to_dict()
            except MetadataError as error:
                entry["error"] = str(error)
            files.append(entry)
        return files

    # --- identifying ---

    def identify(self, paths, title=None, artist=None, skip_complete=True):
        return self._start(self._run_identify, list(paths or []), title, artist, bool(skip_complete))

    def _run_identify(self, paths, title, artist, skip_complete):
        counts = {"sure": 0, "review": 0, "notfound": 0, "complete": 0, "error": 0}
        stopped = None
        try:
            for path in paths:
                if self._cancel.is_set():
                    break
                self.push("identifying", path=path)
                event = self._identify_one(path, title, artist, skip_complete)
                counts[event["status"]] += 1
                self.push("identified", **event)
                if event.get("fatal"):          # no internet / blocked: the next files would fail the same way
                    stopped = event["error"]
                    break
        except Exception as error:               # whatever happens, the window must hear the job ended
            stopped = f"Se detuvo la búsqueda ({type(error).__name__})."
        finally:
            self._busy = False
            self.push("finished", job="identify", total=len(paths), counts=counts, cancelled=self._cancel.is_set(), error=stopped)

    def _identify_one(self, path, title, artist, skip_complete):
        try:
            current = tagwriter.read_tags(path)
        except MetadataError as error:
            return {"path": path, "status": "error", "error": str(error)}
        if skip_complete and tagwriter.is_complete(current) and not (title or artist):
            return {"path": path, "status": "complete", "tags": current.to_dict()}
        try:
            found = self.tagger.identify(path, title, artist)
        except (MetadataNetworkError, MetadataRateLimited) as error:
            return {"path": path, "status": "error", "error": str(error), "fatal": True}
        except MetadataError as error:
            return {"path": path, "status": "error", "error": str(error)}
        base = {"path": path, "tags": found.tags.to_dict() if found.tags else None}
        if found.error:
            return {**base, "status": "notfound" if not found.candidates else "error", "error": found.error}
        candidates = [c.to_dict() for c in found.candidates]
        return {**base, "status": "sure" if found.sure else "review", "candidates": candidates,
                "changes": self.tagger.changes(found.tags, found.candidates[0]) if found.sure else []}

    # --- what exactly will change (asked for before writing) ---

    def prepare(self, path, candidate):
        """The chosen candidate with its genre filled in, and the list of changes it would make to this file."""
        try:
            tags = tagwriter.read_tags(path)
            info = self.tagger.enrich(SongInfo.from_dict(candidate))
            return {"ok": True, "candidate": info.to_dict(), "changes": self.tagger.changes(tags, info)}
        except MetadataError as error:
            return {"ok": False, "error": str(error)}

    # --- a cover the user picked themselves ---

    def set_cover(self, path, image_path):
        """Put an image file the user chose as the cover of `path`, leaving every other tag as it is. Quick and local: no internet."""
        if self._busy:
            return {"ok": False, "error": "Espera a que termine el proceso de etiquetas."}
        if not isinstance(path, str) or not tagwriter.is_supported(path):
            return {"ok": False, "error": "Ese archivo de audio no es compatible."}
        if not isinstance(image_path, str) or os.path.splitext(image_path)[1].lower() not in IMAGE_EXTENSIONS:
            return {"ok": False, "error": "Elige una imagen JPG, PNG, WEBP o BMP."}
        try:
            if os.path.getsize(long_path(image_path)) > MAX_IMAGE_BYTES:
                return {"ok": False, "error": "La imagen es demasiado grande (más de 15 MB)."}
            with open(long_path(image_path), "rb") as f:
                data = f.read()
        except OSError:
            return {"ok": False, "error": "No pude abrir esa imagen."}
        try:
            tagwriter.write_tags(path, SongInfo(), data)
        except MetadataError as error:
            return {"ok": False, "error": str(error)}
        return {"ok": True, "tags": self._safe_tags(path)}

    # --- writing ---

    def apply(self, items, rename=False):
        clean = []
        for item in items or []:
            path = (item or {}).get("path")
            if isinstance(path, str) and tagwriter.is_supported(path):
                clean.append((path, SongInfo.from_dict(item.get("candidate"))))
        if not clean:
            return {"ok": False, "error": "No hay nada que escribir."}
        return self._start(self._run_apply, clean, bool(rename)) | {"count": len(clean)}

    def _run_apply(self, items, rename):
        done = failed = 0
        stopped = None
        try:
            for path, info in items:
                if self._cancel.is_set():
                    break
                self.push("applying", path=path)
                try:
                    result = self.tagger.apply(path, info, rename=rename)
                except (MetadataNetworkError, MetadataRateLimited) as error:
                    failed += 1
                    stopped = str(error)
                    self.push("failed", path=path, error=str(error))
                    break
                except MetadataError as error:
                    failed += 1
                    self.push("failed", path=path, error=str(error))
                    continue
                done += 1
                self.push("applied", path=path, new_path=result["path"], cover=result["cover"], cover_problem=result.get("cover_problem"), genre=result["genre"],
                          tags=self._safe_tags(result["path"]))
        except Exception as error:
            stopped = f"Se detuvo la escritura ({type(error).__name__})."
        finally:
            self._busy = False
            self.push("finished", job="apply", total=len(items), done=done, failed=failed, cancelled=self._cancel.is_set(), error=stopped)

    @staticmethod
    def _safe_tags(path):
        try:
            return tagwriter.read_tags(path).to_dict()
        except MetadataError:
            return None
