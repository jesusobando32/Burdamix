"""Completes the tags and the cover of audio files.

For each file: find out which song it is (from its tags or its file name), look it up (MusicBrainz first, then Deezer
and iTunes), rank the candidates so that the original studio album comes before compilations and live versions, and,
once a candidate is chosen, write its tags and cover into the file."""
import copy
import os
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import tagwriter
from apis.deezer import Deezer
from apis.itunes import ITunes
from apis.metadata_http import MetadataClient
from apis.musicbrainz import MusicBrainz
from apis.song_info import SongInfo
from apis.youtube import STRICT_TOLERANCE, UNWANTED_WORDS, clean_song_title, normalize
from exceptions import MetadataError, MetadataNotFound
from tagwriter import is_complete

MAX_CANDIDATES = 5
SURE_TITLE = 0.92             # how alike the titles must be to apply a match without asking
SURE_ARTIST = 0.80
KIND_BONUS = {"album": 6, "ep": 3, "single": 1, "other": 0, "compilation": -8, "live": -15}
SURE_KINDS = ("album", "ep", "single")   # a compilation or a live version is never applied on its own

FIELD_LABELS = (("title", "Título"), ("artist", "Artista"), ("album", "Álbum"), ("album_artist", "Artista del álbum"),
                ("year", "Año"), ("genre", "Género"))


@dataclass
class Query:
    title: str
    artist: str = None


@dataclass
class Identification:
    path: str
    tags: tagwriter.TagInfo = None
    candidates: list = field(default_factory=list)   # SongInfo, best first
    sure: bool = False                               # the best one is safe to apply without asking
    complete: bool = False                           # the file already has all its tags
    error: str = None                                # why nothing could be done, in plain Spanish


# ---------- what the file says ----------

def parse_filename(path):
    """'Artist - Title.mp3' or 'Title - Artist.mp3' (we cannot tell which: both are returned), or just 'Title.mp3'."""
    stem = os.path.splitext(os.path.basename(path))[0].replace("_", " ").strip()
    without_number = re.sub(r"^\s*\d{1,3}\s*[-.)]\s+", "", stem)   # '01 - ' or '07. ' in front
    stem = without_number or stem
    parts = [p.strip() for p in stem.split(" - ", 1)]
    if len(parts) == 2 and all(parts):
        return [Query(title=parts[1], artist=parts[0]), Query(title=parts[0], artist=parts[1])]
    return [Query(title=stem)] if stem else []


def queries_for(tags, path, title=None, artist=None):
    """What to look for. The user's own words win, then the file's tags, then its name."""
    title, artist = (title or "").strip(), (artist or "").strip()
    if title or artist:
        base_title = title or tags.title
        return [Query(base_title, artist or None)] if base_title else []
    if tags.title and tags.artist:
        return [Query(tags.title, tags.artist)]
    if tags.title:
        return [Query(tags.title)]
    return parse_filename(path)


# ---------- ranking ----------

def similarity(a, b):
    """0..1. Words of the shorter text all appearing in the longer one counts as 0.88: close, but never 'the same'."""
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = SequenceMatcher(None, a, b).ratio()
    if set(a.split()) <= set(b.split()) or set(b.split()) <= set(a.split()):
        ratio = max(ratio, 0.88)
    return ratio


def _title_similarity(wanted, found):
    return similarity(clean_song_title(wanted), clean_song_title(found))


def _duration_score(file_seconds, found_seconds):
    if not file_seconds or not found_seconds:
        return 0.5                    # unknown: neither helps nor hurts
    difference = abs(file_seconds - found_seconds)
    if difference <= 3:
        return 1.0
    if difference <= STRICT_TOLERANCE:
        return 0.8
    return 0.3 if difference <= 20 else 0.0


def match_quality(info, query, file_seconds):
    """(title similarity, artist similarity or None, duration agrees or None)"""
    t = _title_similarity(query.title, info.title)
    a = similarity(query.artist, info.artist) if query.artist else None
    d = None
    if file_seconds and info.duration:
        d = abs(file_seconds - info.duration) <= STRICT_TOLERANCE
    return t, a, d


def score(info, query, file_seconds):
    t, a, _ = match_quality(info, query, file_seconds)
    value = 100 * (0.55 * t + 0.30 * (0.5 if a is None else a) + 0.15 * _duration_score(file_seconds, info.duration))
    value += KIND_BONUS.get(info.kind, 0) + (2 if info.source == "musicbrainz" else 0)
    wanted, found = normalize(query.title), normalize(info.title)
    for word in UNWANTED_WORDS:   # a remix or a live version nobody asked for
        pattern = rf"\b{word}\b"
        if re.search(pattern, found) and not re.search(pattern, wanted):
            value -= 12
    return round(value, 1)


def is_sure(info, query, file_seconds):
    """Safe to write without asking: same title, same artist, a real release, and a duration that agrees."""
    if not query.artist or info.kind not in SURE_KINDS:
        return False
    t, a, d = match_quality(info, query, file_seconds)
    return t >= SURE_TITLE and a is not None and a >= SURE_ARTIST and d is not False


def rank(pairs, file_seconds, limit=MAX_CANDIDATES):
    """[(SongInfo, Query)] -> the best distinct candidates, best first. Among equals, the earliest year (the original)."""
    best = {}
    for info, query in pairs:
        info.score = score(info, query, file_seconds)
        key = (normalize(info.title), normalize(info.artist), normalize(info.album))
        if key not in best or info.score > best[key][0].score:
            best[key] = (info, query)
    ordered = sorted(best.values(), key=lambda pair: (-pair[0].score, pair[0].year or "9999"))
    return ordered[:limit]


# ---------- the tagger ----------

class AutoTagger:
    def __init__(self, musicbrainz=None, deezer=None, itunes=None, images=None, reader=None, writer=None, renamer=None):
        self.musicbrainz = musicbrainz or MusicBrainz()
        self.deezer = deezer or Deezer()
        self.itunes = itunes or ITunes()
        self.images = images or MetadataClient("las portadas", 0.2)
        self.read = reader or tagwriter.read_tags
        self.write = writer or tagwriter.write_tags
        self.rename = renamer or tagwriter.rename_to_title

    def identify(self, path, title=None, artist=None):
        """Look the song up. Never raises for 'nothing found' (that is an answer); raises MetadataError for network trouble."""
        try:
            tags = self.read(path)
        except MetadataError as error:
            return Identification(path=path, error=str(error))
        result = Identification(path=path, tags=tags, complete=is_complete(tags))
        queries = queries_for(tags, path, title, artist)
        if not queries:
            result.error = "No sé qué canción es: el archivo no tiene título ni artista y su nombre no ayuda. Escríbelos tú."
            return result

        pairs = []
        for query in queries:
            pairs += [(info, query) for info in self.musicbrainz.search(query.title, query.artist)]
        ranked = rank(pairs, tags.duration)

        if not (ranked and is_sure(ranked[0][0], ranked[0][1], tags.duration)):
            query = ranked[0][1] if ranked else queries[0]
            for source in (self.deezer, self.itunes):
                try:
                    pairs += [(info, query) for info in source.search(query.title, query.artist)]
                except MetadataError:
                    if not pairs:
                        raise                       # nothing found anywhere and the back-up failed: say why
                    continue
                ranked = rank(pairs, tags.duration)
                if ranked and is_sure(ranked[0][0], ranked[0][1], tags.duration):
                    break

        result.candidates = [info for info, _query in ranked]
        result.sure = bool(ranked) and is_sure(ranked[0][0], ranked[0][1], tags.duration)
        if not result.candidates:
            result.error = "No encontré esta canción en MusicBrainz, Deezer ni iTunes. Prueba escribiendo el título y el artista."
        return result

    # --- what will change, shown before anything is written ---

    @staticmethod
    def changes(tags, info):
        """[{field, label, old, new}] for what writing `info` would change. Empty new values leave the file as it is."""
        rows = []
        for key, label in FIELD_LABELS:
            new, old = getattr(info, key), getattr(tags, key)
            if new and new != old:
                rows.append({"field": key, "label": label, "old": old, "new": new})
        if info.track_number and (info.track_number, info.track_total) != (tags.track, tags.track_total):
            total = f"/{info.track_total}" if info.track_total else ""
            old = f"{tags.track}/{tags.track_total}" if tags.track_total else (str(tags.track) if tags.track else "")
            rows.append({"field": "track", "label": "Pista", "old": old, "new": f"{info.track_number}{total}"})
        if info.cover_urls or info.thumb_url:
            rows.append({"field": "cover", "label": "Portada", "old": "sí" if tags.has_cover else "no", "new": "nueva"})
        return rows

    # --- writing ---

    def enrich(self, info):
        """A copy of `info` with the genre filled in from Deezer or iTunes when it has none (MusicBrainz rarely has it)."""
        info = copy.copy(info)
        if not info.genre:
            for source in (self.deezer, self.itunes):
                try:
                    for other in source.search(info.title, info.artist, limit=3):
                        if other.genre and _title_similarity(info.title, other.title) >= SURE_TITLE \
                                and similarity(info.artist, other.artist) >= SURE_ARTIST:
                            info.genre = other.genre
                            break
                except MetadataError:
                    continue
                if info.genre:
                    break
        return info

    def fetch_cover(self, info):
        """The cover as bytes: the candidate's own urls first, then Deezer's and iTunes' picture of the same album."""
        urls = list(info.cover_urls)
        for url in urls:
            try:
                return self.images.get_image(url)
            except MetadataError:
                continue                          # 404 for a size that does not exist, a dropped connection...
        if info.album and info.artist:
            for source in (self.deezer, self.itunes):
                try:
                    for url in source.find_cover(info.album, info.artist):
                        try:
                            return self.images.get_image(url)
                        except MetadataError:
                            continue
                except MetadataError:
                    continue
        return None

    def apply(self, path, info, rename=False):
        """Write `info` and its cover into the file. Returns {path, cover, genre}; raises TagWriteError on failure."""
        info = self.enrich(info)
        cover = self.fetch_cover(info)
        self.write(path, info, cover)
        new_path = self.rename(path, info.title) if rename else path
        return {"path": new_path, "cover": cover is not None, "genre": info.genre}


def collect_audio_files(paths):
    """The supported audio files among `paths`; folders are searched inside, sorted, without repeats."""
    found, seen = [], set()
    for path in paths or []:
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                dirs.sort()
                for name in sorted(files):
                    full = os.path.join(root, name)
                    if tagwriter.is_supported(full) and full not in seen:
                        seen.add(full)
                        found.append(full)
        elif os.path.isfile(path) and tagwriter.is_supported(path) and path not in seen:
            seen.add(path)
            found.append(path)
    return found
