"""Completes the tags and the cover of audio files.

For each file: find out which song it is (from its tags or its file name), look it up (MusicBrainz first, then Deezer
and iTunes), rank the candidates so that the original studio album comes before compilations and live versions, and,
once a candidate is chosen, write its tags and cover into the file."""
import copy
import os
import re
import threading
from dataclasses import dataclass, field

import const
import tagwriter
from apis.deezer import Deezer
from apis.itunes import ITunes
from apis.matching import similarity
from apis.metadata_http import MetadataClient
from apis.musicbrainz import MusicBrainz
from apis.ytmusic import YouTubeMusic
from covers import CoverFinder
from pathutils import song_filename
from apis.song_info import SongInfo
from apis.youtube import STRICT_TOLERANCE, UNWANTED_WORDS, clean_song_title, normalize
from exceptions import MetadataError, MetadataNotFound
from tagwriter import is_complete

MAX_CANDIDATES = 5
# The order the cover is looked for. Measured on 19 real songs (Latin urban music), each cover compared with Spotify's:
#   deezer   15 right, 0.6 s per song, never wrong when it downloads (a VPN refuses some: it is paused when that happens)
#   ytmusic  17 right, 1.0 s, finds them all, but gives a single's cover when the album's differs (2 of 19)
#   caa       9 right, 3.0 s, never wrong, but only has about half
#   itunes    4 right, 3.4 s, hardly has this music and is the slowest
PICTURES_KEPT = 32    # artist photos remembered (a few KB each)
COVER_ORDER = ("deezer", "ytmusic", "caa", "itunes")
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
    def __init__(self, musicbrainz=None, deezer=None, itunes=None, images=None, reader=None, writer=None, renamer=None, ytmusic=None, covers=None):
        self.musicbrainz = musicbrainz or MusicBrainz()
        self.deezer = deezer or Deezer()
        self.itunes = itunes or ITunes()
        self.ytmusic = ytmusic or YouTubeMusic()
        self.images = images or MetadataClient("El servidor de portadas", 0.2)
        self.read = reader or tagwriter.read_tags
        self.write = writer or tagwriter.write_tags
        self.rename = renamer or tagwriter.rename_to_title
        services = {"deezer": self.deezer, "itunes": self.itunes, "ytmusic": self.ytmusic, "caa": self.musicbrainz}
        self.covers = covers or CoverFinder([(name, services[name]) for name in COVER_ORDER], self.images)
        self._pictures = {}
        self._pictures_lock = threading.Lock()

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

        pairs, failures, answered = [], [], []

        def ask(source, query):
            """Add what `source` knows. A service that is down is remembered, not fatal: the others may have the song."""
            try:
                pairs.extend((info, query) for info in source.search(query.title, query.artist))
                answered.append(source)
                return True
            except MetadataError as error:
                failures.append(error)
                return False

        for query in queries:
            if not ask(self.musicbrainz, query):
                break                               # it is failing: asking again with the other word order would fail the same way
        ranked = rank(pairs, tags.duration)

        if not (ranked and is_sure(ranked[0][0], ranked[0][1], tags.duration)):
            # With a best guess, ask the back-ups about that one. With none (MusicBrainz knows nothing or is down), try
            # every way of reading the file name: the right word order may be the one MusicBrainz never got to try.
            for source in (self.deezer, self.itunes):
                for query in ([ranked[0][1]] if ranked else queries):
                    ask(source, query)
                ranked = rank(pairs, tags.duration)
                if ranked and is_sure(ranked[0][0], ranked[0][1], tags.duration):
                    break

        if not answered and failures:
            raise failures[0]                       # no service could answer at all: say why, not "not found"

        result.candidates = [info for info, _query in ranked]
        result.sure = bool(ranked) and is_sure(ranked[0][0], ranked[0][1], tags.duration)
        if not result.candidates:
            result.error = "No encontré esta canción en MusicBrainz, Deezer ni iTunes. Prueba escribiendo el título y el artista."
            if failures:                              # some service could not answer: the song may be there
                result.error += f" Ojo: {failures[0]}"
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
        """The cover as bytes, or None. See fetch_cover_checked for why there is none."""
        return self.fetch_cover_checked(info)[0]

    def fetch_cover_checked(self, info):
        """(cover bytes or None, problem or None). The cover is a step of its own: it is searched with the song's tags,
        whichever service gave them (see covers.py). `problem` is set when a server refused us (403, no internet), which
        is different from "nobody has a cover for this song", and the user needs to know which one it was."""
        found = self.covers.find(info)
        return found.data, found.problem

    def apply(self, path, info, rename=False, style=const.DEFAULT_NAME_STYLE):
        """Write `info` and its cover into the file; with `rename`, also rename the file in the chosen style (const.NAME_STYLES).
        Returns {path, cover, genre, cover_problem, cover_source}; raises TagWriteError on failure."""
        info = self.enrich(info)
        found = self.covers.find(info)
        self.write(path, info, found.data)
        new_path = self.rename(path, song_filename(info.title, info.artist, style)) if rename else path
        return {"path": new_path, "cover": found.data is not None, "genre": info.genre, "cover_problem": found.problem,
                "cover_source": found.source, "cover_thumb": tagwriter.cover_thumbnail(found.data) if found.data else None}

    def preview_cover(self, info):
        """(a small picture as a data: URL or None, problem or None): the cover that WOULD be written, so the window can show it."""
        found = self.covers.find(info)
        return (tagwriter.cover_thumbnail(found.data) if found.data else None), found.problem

    def preview_picture(self, url):
        """A small picture (an artist's photo) from its address as a data: URL, or None. Remembered: going back to a list does not download it again."""
        with self._pictures_lock:
            if url in self._pictures:
                return self._pictures[url]
        try:
            picture = tagwriter.cover_thumbnail(self.images.get_image(url))
        except MetadataError:
            return None                        # not remembered: a refusal or a lost connection may pass
        with self._pictures_lock:
            self._pictures[url] = picture
            while len(self._pictures) > PICTURES_KEPT:
                self._pictures.pop(next(iter(self._pictures)))
        return picture


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
