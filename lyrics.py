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

MIN_SCALE, MAX_SCALE = 0.5, 2     # the speed of the lyrics against the song
MAX_VERSIONS = 5                # versions of the lyrics kept per song
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


def _label(result):
    seconds = int(round(result.get("duration") or 0))
    who = (result.get("artistName") or "").strip()
    return f"{who} · {seconds // 60}:{seconds % 60:02d}" if who and seconds else who or (f"{seconds // 60}:{seconds % 60:02d}" if seconds else "")


def ends_wrong(synced, duration):
    """True when the lyrics are timed for another length: the last line of an LRC is often an empty one stamped at the very end of the
    song, and if that stamp is far from the length of the file, the whole timeline is stretched or squeezed."""
    if not duration or not synced or synced[-1][1]:
        return False
    return synced[-1][0] < duration * 0.9 or synced[-1][0] > duration + 3


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

    @staticmethod
    def _number(data, table, key, default, low, high):
        values = data.get(table)
        value = values.get(key) if isinstance(values, dict) else None
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high else default

    @staticmethod
    def _versions(entry):
        """The versions of the lyrics found for a song (an entry written before versions existed has just one)."""
        versions = entry.get("versions")
        if isinstance(versions, list) and versions:
            return versions
        return [{"synced": entry.get("synced") or [], "plain": entry.get("plain") or "", "label": ""}]

    # --- what the panel gets ---------------------------------------------------------------------------------------

    def _shape(self, entry, data, key):
        versions = self._versions(entry)
        pick = int(self._number(data, "_picks", key, 0, 0, len(versions) - 1))
        chosen = versions[pick]
        return {"ok": True, "synced": chosen.get("synced") or [], "plain": chosen.get("plain") or "", "manual": bool(entry.get("manual")),
                "offset": self._number(data, "_offsets", key, 0, -MAX_OFFSET, MAX_OFFSET), "scale": self._number(data, "_scales", key, 1, MIN_SCALE, MAX_SCALE),
                "version": pick, "versions": len(versions), "label": chosen.get("label") or ""}

    def _missing(self, data, key):
        return {"ok": False, "none": True, "error": "No encontré la letra de esta canción.", "offset": self._number(data, "_offsets", key, 0, -MAX_OFFSET, MAX_OFFSET),
                "scale": self._number(data, "_scales", key, 1, MIN_SCALE, MAX_SCALE)}

    def get(self, artist, title, album="", duration=0):
        key = self._key(artist, title)
        if key is None:
            return {"ok": False, "error": "A esta canción le faltan el artista o el título, y sin ellos no puedo buscar la letra."}
        data = self._load()
        entry = data.get(key)
        # lyrics kept before versions existed are asked for again once (they may be the squeezed version); the old ones stay as a fallback
        old = entry if entry and not entry.get("manual") and not entry.get("none") and "versions" not in entry else None
        if entry and not old and (entry.get("manual") or not entry.get("none") or self.clock() - entry.get("at", 0) < RETRY_MISSING_AFTER):
            return self._shape(entry, data, key) if not entry.get("none") else self._missing(data, key)
        try:
            found = self._ask(artist, title, album, duration)
        except MetadataError as error:
            return self._shape(old, data, key) if old else {"ok": False, "error": str(error)}   # no connection is not "no lyrics": nothing is remembered
        if found is None and old:
            return self._shape(old, data, key)
        if found is None:
            data[key] = {"none": True, "at": self.clock()}
            self._save(data)
            return self._missing(data, key)
        data[key] = found
        if isinstance(data.get("_picks"), dict):
            data["_picks"].pop(key, None)            # new lyrics: the old choice of version means nothing
        self._save(data)
        return self._shape(found, data, key)

    def _set_number(self, artist, title, table, value, default, low, high, step):
        key = self._key(artist, title)
        if key is None or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return None
        value = round(round(max(low, min(high, value)) / step) * step, 4)
        data = self._load()
        values = data.get(table) if isinstance(data.get(table), dict) else {}
        if value == default:
            values.pop(key, None)
        else:
            values[key] = value
        data[table] = values
        self._save(data)
        return value

    def set_offset(self, artist, title, seconds):
        """How many seconds later (+) or earlier (-) the lyrics of this song must run to match the file you have. Answers the value
        kept (rounded to a quarter of a second, within ±30), or None when it is not a number or the song has no name."""
        return self._set_number(artist, title, "_offsets", seconds, 0, -MAX_OFFSET, MAX_OFFSET, .25)

    def set_scale(self, artist, title, factor):
        """The speed of the lyrics against the song: every time of the lyrics is multiplied by this factor, so above 1 they spread out
        (for lyrics that run too fast) and below 1 they bunch up. Between 0.5 and 2; 1 is no change."""
        return self._set_number(artist, title, "_scales", factor, 1, MIN_SCALE, MAX_SCALE, .0001)

    def set_version(self, artist, title, index):
        """Chooses another of the versions found for the song. Answers the index kept, or None if there is nothing to choose."""
        key = self._key(artist, title)
        data = self._load()
        entry = data.get(key) if key else None
        if not entry or entry.get("none") or isinstance(index, bool) or not isinstance(index, int):
            return None
        index = max(0, min(index, len(self._versions(entry)) - 1))
        picks = data.get("_picks") if isinstance(data.get("_picks"), dict) else {}
        if index:
            picks[key] = index
        else:
            picks.pop(key, None)
        data["_picks"] = picks
        self._save(data)
        return index

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
        if isinstance(data.get("_picks"), dict):
            data["_picks"].pop(key, None)
        self._save(data)
        return True

    # --- the service -----------------------------------------------------------------------------------------------

    def _ask(self, artist, title, album, duration):
        """The exact lookup, then searches by the full name, by the name without credits, and by the first artist: a handful of requests.
        Every version found is kept, the most believable first (see `_entry`), so the panel can offer the others."""
        params = {"artist_name": artist, "track_name": title}
        if album:
            params["album_name"] = album
        if duration:
            params["duration"] = int(duration)
        first, plain = first_artist(artist), clean_title(title)
        candidates = []
        try:
            candidates.append(self.client.get_json(f"{API}/api/get", params))
        except MetadataNotFound:
            pass   # not under that exact name and length: search
        found_exact = bool(candidates)
        asked = []
        for a, t in ((artist, title), (artist, plain), (first, title), (first, plain)):
            if (a, t) in asked:
                continue
            if found_exact and asked:
                break                          # the exact lookup worked: one search, for the other versions, is enough
            asked.append((a, t))
            candidates += self._near(self._search_raw({"track_name": t, "artist_name": a}, optional=found_exact), duration)
            if found_exact:
                # the exact lookup may have found a collaboration while the same song is also listed under the first artist
                if first != artist:
                    candidates += self._near(self._search_raw({"track_name": t, "artist_name": first}, optional=True), duration)
                break
            if candidates:
                break
        if not candidates:
            candidates = self._near(self._search_raw({"q": f"{plain} {first}"}), duration)
        return self._entry(candidates, duration)

    def _search_raw(self, params, optional=False):
        try:
            results = self.client.get_json(f"{API}/api/search", params)
        except MetadataError:
            if optional:
                return []                      # the others are a bonus: not finding them must not lose the one already found
            raise
        return [r for r in results if isinstance(r, dict)] if isinstance(results, list) else []

    @staticmethod
    def _near(results, duration):
        return [r for r in results if not duration or abs((r.get("duration") or 0) - duration) <= LENGTH_TOLERANCE]

    def _entry(self, candidates, duration):
        versions, seen = [], set()
        for result in candidates:
            synced = parse_lrc(result.get("syncedLyrics") or "")
            plain = (result.get("plainLyrics") or "").strip() or "\n".join(line for _, line in synced)
            if not synced and not plain:
                continue
            fingerprint = json.dumps(synced) if synced else plain
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            versions.append({"synced": synced, "plain": plain, "label": _label(result), "_length": result.get("duration") or 0})
        if not versions:
            return None
        # timed lyrics first; among them, those whose end marker agrees with the length of the file; then the closest length
        versions.sort(key=lambda v: (not v["synced"], ends_wrong(v["synced"], duration), abs(v["_length"] - duration) if duration else 0))
        for v in versions:
            v.pop("_length")
        return {"versions": versions[:MAX_VERSIONS], "manual": False, "at": self.clock()}
