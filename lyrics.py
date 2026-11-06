"""Song lyrics. They come from LRCLIB (free, no key; only the artist, the title, the album and the length are sent) as LRC text: lines with
the second at which each is sung. What was found, and what was not, is kept in a small file so the service is not asked twice; lyrics the
user pastes themselves win over everything."""
import json
import math
import os
import re
import tempfile
import time

from apis.metadata_http import MetadataClient
from apis.youtube import normalize
from exceptions import MetadataError, MetadataNotFound

API = "https://lrclib.net"
LENGTH_TOLERANCE = 5            # seconds: a search result of another length is another recording
RETRY_MISSING_AFTER = 7 * 86400  # what was not found is looked for again after a week; the service may have it by then

MAX_OFFSET = 30                  # seconds either way: more than that is not a sync problem, it is another song
_JOINERS = re.compile(r"\s*(?:,|;|&|\s(?:feat\.?|ft\.?|featuring|with|x|y|con|and)\s)\s*", re.IGNORECASE)
_CREDIT_BRACKET = re.compile(r"\s*[\(\[][^\)\]]*\b(?:feat|ft|featuring|with|prod|remaster\w*|version|deluxe|mono|stereo|bonus|explicit|single)\b[^\)\]]*[\)\]]", re.IGNORECASE)
_LABEL_TAIL = re.compile(r"\s+-\s+[^-]*\b(?:remaster\w*|version|single|mono|stereo|deluxe)\b.*$", re.IGNORECASE)

_STAMP = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_OFFSET = re.compile(r"^\[offset:\s*([+-]?\d+)\s*\]", re.IGNORECASE)


def first_artist(artist):
    """"SAIKO, ULI" -> "SAIKO"; "Mora feat. Feid" -> "Mora". Services list a song under one name, tags list all of them."""
    return _JOINERS.split(artist.strip(), maxsplit=1)[0].strip() or artist.strip()


def clean_title(title):
    """Without credits and remaster labels ("Tema (feat. X) - Remastered 2011" -> "Tema"). A remix or a live version keeps its label."""
    return _LABEL_TAIL.sub("", _CREDIT_BRACKET.sub("", title.strip())).strip() or title.strip()


def parse_lrc(text):
    """[[second, line], ...] sorted by second. Lines with several stamps are repeated; tags and untimed lines are ignored;
    `[offset:ms]` moves everything; blank lines are kept (they are the pauses) except at the start."""
    offset, lines = 0.0, []
    for raw in (text or "").splitlines():
        raw = raw.strip()
        tag = _OFFSET.match(raw)
        if tag:
            offset = int(tag.group(1)) / 1000
            continue
        stamps, rest = [], raw
        while True:
            m = _STAMP.match(rest)
            if not m:
                break
            minutes, seconds, fraction = int(m.group(1)), int(m.group(2)), m.group(3)
            stamps.append(minutes * 60 + seconds + (float("0." + fraction) if fraction else 0))
            rest = rest[m.end():]
        for second in stamps:
            lines.append([round(max(second - offset, 0), 3), rest.strip()])
    lines.sort(key=lambda line: line[0])
    while lines and not lines[0][1]:
        lines.pop(0)
    return lines


class Lyrics:
    def __init__(self, path, client=None, clock=time.time):
        self.path = path
        self.client = client or MetadataClient("LRCLIB", 0.2)
        self.clock = clock

    # --- the file ------------------------------------------------------------------------------------------------

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}   # no file yet, or a damaged one: the lyrics are only a cache, they are asked for again

    def _save(self, data):
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path) or ".", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            pass   # a lyric not kept is only asked for again

    @staticmethod
    def _key(artist, title):
        a, t = normalize(artist), normalize(title)
        return f"{a}|{t}" if a and t else None

    # --- what the panel gets ---------------------------------------------------------------------------------------

    @staticmethod
    def _shape(entry, offset=0):
        return {"ok": True, "synced": entry.get("synced") or [], "plain": entry.get("plain") or "", "manual": bool(entry.get("manual")), "offset": offset}

    def get(self, artist, title, album="", duration=0):
        key = self._key(artist, title)
        if key is None:
            return {"ok": False, "error": "A esta canción le faltan el artista o el título, y sin ellos no puedo buscar la letra."}
        data = self._load()
        entry, offset = data.get(key), self._offset(data, key)
        if entry and (entry.get("manual") or not entry.get("none") or self.clock() - entry.get("at", 0) < RETRY_MISSING_AFTER):
            return self._shape(entry, offset) if not entry.get("none") else self._missing(offset)
        try:
            found = self._ask(artist, title, album, duration)
        except MetadataError as error:
            return {"ok": False, "error": str(error)}   # no connection is not "no lyrics": nothing is remembered
        if found is None:
            data[key] = {"none": True, "at": self.clock()}
            self._save(data)
            return self._missing(offset)
        data[key] = found
        self._save(data)
        return self._shape(found, offset)

    @staticmethod
    def _missing(offset=0):
        return {"ok": False, "none": True, "error": "No encontré la letra de esta canción.", "offset": offset}

    @staticmethod
    def _offset(data, key):
        offsets = data.get("_offsets")
        value = offsets.get(key) if isinstance(offsets, dict) else None
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value) <= MAX_OFFSET else 0

    def set_offset(self, artist, title, seconds):
        """How many seconds later (+) or earlier (-) the lyrics of this song must run to match the file you have. Answers the value
        kept (rounded to a quarter of a second, within ±30), or None when it is not a number or the song has no name."""
        key = self._key(artist, title)
        if key is None or isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds):
            return None
        value = round(max(-MAX_OFFSET, min(MAX_OFFSET, seconds)) * 4) / 4
        data = self._load()
        offsets = data.get("_offsets") if isinstance(data.get("_offsets"), dict) else {}
        if value:
            offsets[key] = value
        else:
            offsets.pop(key, None)
        data["_offsets"] = offsets
        self._save(data)
        return value

    def set_manual(self, artist, title, text):
        """The user's own lyrics (with or without LRC times). An empty text takes them away."""
        key = self._key(artist, title)
        if key is None:
            return False
        data = self._load()
        text = (text or "").strip()
        if not text:
            data.pop(key, None)
        else:
            synced = parse_lrc(text)
            data[key] = {"synced": synced, "plain": "\n".join(line for _, line in synced) if synced else text, "manual": True, "at": self.clock()}
        self._save(data)
        return True

    # --- the service -----------------------------------------------------------------------------------------------

    def _ask(self, artist, title, album, duration):
        """The exact lookup, then searches by the full name, by the name without credits, and by the first artist: a handful of requests."""
        params = {"artist_name": artist, "track_name": title}
        if album:
            params["album_name"] = album
        if duration:
            params["duration"] = int(duration)
        try:
            return self._entry(self.client.get_json(f"{API}/api/get", params))
        except MetadataNotFound:
            pass   # not under that exact name and length: search
        first, plain = first_artist(artist), clean_title(title)
        tried = []
        for a, t in ((artist, title), (artist, plain), (first, title), (first, plain)):
            if (a, t) not in tried:
                tried.append((a, t))
                found = self._search({"track_name": t, "artist_name": a}, duration)
                if found:
                    return found
        return self._search({"q": f"{plain} {first}"}, duration)

    def _search(self, params, duration):
        results = self.client.get_json(f"{API}/api/search", params)
        near = [r for r in results if isinstance(r, dict) and (not duration or abs((r.get("duration") or 0) - duration) <= LENGTH_TOLERANCE)]
        near.sort(key=lambda r: (not r.get("syncedLyrics"), abs((r.get("duration") or 0) - duration)))
        for result in near:
            entry = self._entry(result)
            if entry:
                return entry
        return None

    def _entry(self, result):
        synced = parse_lrc(result.get("syncedLyrics") or "")
        plain = (result.get("plainLyrics") or "").strip()
        if not synced and not plain:
            return None
        return {"synced": synced, "plain": plain or "\n".join(line for _, line in synced), "manual": False, "at": self.clock()}
