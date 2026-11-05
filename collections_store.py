"""The songs you like and your own playlists, kept in a small file of their own (collections.json in the program's data folder).

They only point at files: nothing is copied or moved, so a song can be in an album, in «Me gusta» and in three playlists at once.
Files are identified by their normalized path. When a file is renamed (Completar etiquetas can do it) or deleted, the program
tells this store so that likes and playlist places follow the file or go away."""
import json
import os
import secrets
import threading

MAX_NAME = 60


class CollectionsError(Exception):
    """Something the window can show the user in plain Spanish."""


def key(path):
    return os.path.normcase(os.path.abspath(path))


class Collections:
    def __init__(self, path):
        self._path = path
        self._lock = threading.RLock()
        self.liked = set()          # files the user liked
        self.unliked = set()        # files of the liked/ folder the user took the like off: they are liked unless listed here
        self.playlists = []         # [{"id", "name", "paths": [key, ...]}]
        self._unreadable = False
        self._load()

    # --- the file ---

    def _keep_bad_copy(self):
        """A file that cannot be read is set aside (collections.json.bad), not overwritten by the next save: it may still be worth rescuing."""
        try:
            os.replace(self._path, self._path + ".bad")
        except OSError:
            pass

    def _load(self):
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return                              # the first time: nothing saved yet
        except ValueError:                      # not JSON: set aside
            self._keep_bad_copy()
            return
        except OSError:                         # locked or unreadable for now: this session writes nothing, so the good file is never overwritten
            self._unreadable = True
            return
        if not isinstance(data, dict):
            self._keep_bad_copy()
            return
        strings = lambda values: [v for v in values if isinstance(v, str)] if isinstance(values, list) else []
        self.liked = set(strings(data.get("liked")))
        self.unliked = set(strings(data.get("unliked")))
        for item in data.get("playlists") if isinstance(data.get("playlists"), list) else []:
            if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("name"), str):
                self.playlists.append({"id": item["id"], "name": item["name"], "paths": strings(item.get("paths"))})

    def _save(self):
        if self._unreadable:
            return
        data = {"liked": sorted(self.liked), "unliked": sorted(self.unliked), "playlists": self.playlists}
        part = self._path + ".part"
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(part, "w", encoding="utf-8") as f:           # written beside and swapped in: no half-written file
                json.dump(data, f, ensure_ascii=False)
            os.replace(part, self._path)
        except OSError:
            pass                                                   # the choices stay for this session; the next save tries again

    # --- likes ---

    def like(self, path):
        with self._lock:
            self.liked.add(key(path))
            self.unliked.discard(key(path))
            self._save()

    def unlike(self, path, remember=False):
        """Takes the like off. `remember` is for a file of the liked/ folder, which would otherwise count as liked again."""
        with self._lock:
            self.liked.discard(key(path))
            if remember:
                self.unliked.add(key(path))
            self._save()

    # --- playlists ---

    @staticmethod
    def _clean_name(name):
        if not isinstance(name, str):
            raise CollectionsError("Ponle un nombre a la playlist.")
        name = " ".join(name.split())
        if not name:
            raise CollectionsError("Ponle un nombre a la playlist.")
        if len(name) > MAX_NAME:
            raise CollectionsError(f"El nombre es demasiado largo (máximo {MAX_NAME} letras).")
        return name

    def _playlist(self, playlist_id):
        found = next((p for p in self.playlists if p["id"] == playlist_id), None)
        if found is None:
            raise CollectionsError("Esa playlist ya no existe.")
        return found

    def playlist_create(self, name, paths=()):
        with self._lock:
            name = self._clean_name(name)
            playlist = {"id": secrets.token_hex(6), "name": name, "paths": []}
            for path in paths:
                if key(path) not in playlist["paths"]:
                    playlist["paths"].append(key(path))
            self.playlists.append(playlist)
            self._save()
            return playlist["id"]

    def playlist_rename(self, playlist_id, name):
        with self._lock:
            playlist = self._playlist(playlist_id)
            playlist["name"] = self._clean_name(name)
            self._save()

    def playlist_delete(self, playlist_id):
        with self._lock:
            playlist = self._playlist(playlist_id)
            self.playlists.remove(playlist)
            self._save()

    def playlist_add(self, playlist_id, paths):
        with self._lock:
            playlist = self._playlist(playlist_id)
            for path in paths:
                if key(path) not in playlist["paths"]:
                    playlist["paths"].append(key(path))
            self._save()

    def playlist_remove(self, playlist_id, path):
        with self._lock:
            playlist = self._playlist(playlist_id)
            playlist["paths"] = [p for p in playlist["paths"] if p != key(path)]
            self._save()

    # --- when files change ---

    def forget(self, paths):
        """Files that were deleted: they are no longer liked nor in any playlist."""
        gone = {key(p) for p in paths}
        with self._lock:
            self.liked -= gone
            self.unliked -= gone
            for playlist in self.playlists:
                playlist["paths"] = [p for p in playlist["paths"] if p not in gone]
            self._save()

    def renamed(self, old, new):
        """A file now has another name: its likes and its places in playlists go with it."""
        old, new = key(old), key(new)
        with self._lock:
            for group in (self.liked, self.unliked):
                if old in group:
                    group.discard(old)
                    group.add(new)
            for playlist in self.playlists:
                renamed = [new if p == old else p for p in playlist["paths"]]
                playlist["paths"] = [p for i, p in enumerate(renamed) if p not in renamed[:i]]       # the new name may already have been there
            self._save()

    def snapshot(self):
        """A consistent copy of everything, for readers on other threads: (liked, unliked, playlists)."""
        with self._lock:
            return set(self.liked), set(self.unliked), [{**p, "paths": list(p["paths"])} for p in self.playlists]
