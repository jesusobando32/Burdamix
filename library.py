"""The songs the window can play: what is in the downloads folder, and a tiny local server that hands them to the page.

The window is a file:// page, so the browser treats every audio it loads as coming from another origin and silences it
as soon as the equalizer touches it. The server therefore answers with `Access-Control-Allow-Origin: *`. A random token
in every address and a list of only the scanned files keep the rest of the disk (and other local pages) out."""
import hashlib
import io
import mimetypes
import os
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, UnidentifiedImageError

import tagwriter
from exceptions import MetadataError, UnsupportedAudioFormat
from pathutils import long_path

CHUNK = 64 * 1024
COVER_SIZE = 320
COVERS_KEPT = 200
MIME = {".mp3": "audio/mpeg", ".flac": "audio/flac", ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg"}
RANGE = re.compile(r"bytes=(\d*)-(\d*)$")


def _from_file_name(path):
    stem = os.path.splitext(os.path.basename(path))[0].replace("_", " ").strip()
    artist, separator, title = stem.partition(" - ")
    return (title.strip(), artist.strip()) if separator and title.strip() and artist.strip() else (stem, "")


class Library:
    def __init__(self):
        self._paths = {}
        self._known = {}     # path -> ((mtime, size), track): files that did not change are not read again (swapped whole by each scan)
        self._lock = threading.Lock()

    @staticmethod
    def _id(path):
        return hashlib.sha1(os.path.normcase(os.path.abspath(path)).encode("utf-8", "surrogatepass")).hexdigest()[:16]

    def scan(self, folder):
        """Every playable file under `folder` as a dict for the window; remembers which paths may be served."""
        found = []
        with self._lock:
            known = self._known
        fresh = {}
        for root, _, names in os.walk(folder):
            for name in names:
                path = os.path.join(root, name)
                if not tagwriter.is_supported(path):
                    continue
                try:
                    stat = os.stat(long_path(path))
                except OSError:
                    continue
                stamp = (stat.st_mtime, stat.st_size)
                kept = known.get(path)
                if kept and kept[0] == stamp:
                    fresh[path] = kept
                    found.append(kept[1])
                    continue
                title, artist, album, duration, cover, complete = *_from_file_name(path), "", 0, False, False
                try:
                    tags = tagwriter.read_tags(path)
                    title, artist, album = tags.title or title, tags.artist or artist, tags.album
                    duration, cover, complete = int(round(tags.duration)), tags.has_cover, tagwriter.is_complete(tags)
                except (MetadataError, UnsupportedAudioFormat):
                    pass
                track = {"id": self._id(path), "path": path, "title": title, "artist": artist, "album": album,
                         "duration": duration, "cover": cover, "complete": complete, "added": stat.st_mtime}
                fresh[path] = (stamp, track)
                found.append(track)
        found.sort(key=lambda t: (t["artist"].casefold(), t["title"].casefold()))
        with self._lock:
            self._paths = {t["id"]: t["path"] for t in found}
            self._known = fresh
        return found

    def forget(self, path):
        """A file that was deleted: it is no longer served nor remembered."""
        with self._lock:
            self._paths = {k: v for k, v in self._paths.items() if v != path}
            self._known.pop(path, None)

    def path_of(self, track_id):
        with self._lock:
            return self._paths.get(track_id)


class MediaServer:
    """Serves /audio/<token>/<id> (with byte ranges, so the progress bar can jump) and /cover/<token>/<id>."""

    def __init__(self, library):
        self._library = library
        self.token = secrets.token_urlsafe(16)
        self._covers = {}
        self._covers_lock = threading.Lock()
        self._server = None
        self._start_lock = threading.Lock()
        self.port = 0

    def start(self):
        with self._start_lock:
            if self._server:
                return   # two requests at once (page start and opening the library) must not start two servers
            self._start()

    def _start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *args):
                pass
            def do_HEAD(self):
                owner._handle(self, head=True)
            def do_GET(self):
                owner._handle(self, head=False)
            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Range")
                self.send_header("Content-Length", "0")
                self.end_headers()

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def audio_url(self, track_id):
        return f"http://127.0.0.1:{self.port}/audio/{self.token}/{track_id}"

    def cover_url(self, track_id):
        return f"http://127.0.0.1:{self.port}/cover/{self.token}/{track_id}"

    # --- one request ---

    def _handle(self, request, head):
        parts = request.path.split("?")[0].strip("/").split("/")
        path = self._library.path_of(parts[2]) if len(parts) == 3 and parts[1] == self.token else None
        if path is None or parts[0] not in ("audio", "cover"):
            return self._empty(request, 404)
        try:
            if parts[0] == "audio":
                self._audio(request, path, head)
            else:
                self._cover(request, path, head)
        except (OSError, ConnectionError):
            pass   # the page cancelled the request (skipping a song): nothing to report

    @staticmethod
    def _empty(request, status, extra=None):
        request.send_response(status)
        request.send_header("Access-Control-Allow-Origin", "*")
        request.send_header("Content-Length", "0")
        for key, value in (extra or {}).items():
            request.send_header(key, value)
        request.end_headers()

    def _audio(self, request, path, head):
        try:
            size = os.path.getsize(long_path(path))
        except OSError:
            return self._empty(request, 404)
        start, end, status = 0, size - 1, 200
        wanted = RANGE.match((request.headers.get("Range") or "").strip())
        if wanted:
            first, last = wanted.groups()
            if first == "" and last == "":
                return self._empty(request, 416, {"Content-Range": f"bytes */{size}"})
            if first == "":
                start, end = max(0, size - int(last)), size - 1
            else:
                start, end = int(first), min(int(last), size - 1) if last else size - 1
            if start >= size or start > end:
                return self._empty(request, 416, {"Content-Range": f"bytes */{size}"})
            status = 206
        extension = os.path.splitext(path)[1].lower()
        request.send_response(status)
        request.send_header("Content-Type", MIME.get(extension) or mimetypes.guess_type(path)[0] or "application/octet-stream")
        request.send_header("Accept-Ranges", "bytes")
        request.send_header("Access-Control-Allow-Origin", "*")
        request.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            request.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        request.end_headers()
        if head:
            return
        with open(long_path(path), "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                data = f.read(min(CHUNK, left))
                if not data:
                    break
                request.wfile.write(data)
                left -= len(data)

    def _cover(self, request, path, head):
        jpeg = self._small_cover(path)
        if jpeg is None:
            return self._empty(request, 404)
        request.send_response(200)
        request.send_header("Content-Type", "image/jpeg")
        request.send_header("Access-Control-Allow-Origin", "*")
        request.send_header("Cache-Control", "max-age=3600")
        request.send_header("Content-Length", str(len(jpeg)))
        request.end_headers()
        if not head:
            request.wfile.write(jpeg)

    def _small_cover(self, path):
        try:
            key = (path, os.path.getmtime(long_path(path)))   # a new cover (Completar etiquetas) is a new version of the file
        except OSError:
            return None
        with self._covers_lock:
            if key in self._covers:
                return self._covers[key]
        jpeg = None
        data = tagwriter.read_cover(path)
        if data:
            try:
                image = Image.open(io.BytesIO(data))
                image.load()
                image = image.convert("RGB")
                image.thumbnail((COVER_SIZE, COVER_SIZE), Image.LANCZOS)
                out = io.BytesIO()
                image.save(out, "JPEG", quality=82)
                jpeg = out.getvalue()
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
                jpeg = None
        with self._covers_lock:
            if len(self._covers) >= COVERS_KEPT:
                self._covers.pop(next(iter(self._covers)))
            self._covers[key] = jpeg
        return jpeg
