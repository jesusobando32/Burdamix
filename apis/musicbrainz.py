"""MusicBrainz (the song data) and the Cover Art Archive (its covers). Both are free and need no account.
MusicBrainz asks for at most one request per second and a User-Agent that says who is asking."""
import re

from apis.metadata_http import MetadataClient
from apis.song_info import KINDS, SongInfo

BASE = "https://musicbrainz.org/ws/2"
COVERS = "https://coverartarchive.org/release"
SEARCH_LIMIT = 10
MIN_INTERVAL_SECONDS = 1.1   # the service allows 1 per second; the extra 0.1 is a margin


def _lucene(text):
    """Inside a quoted Lucene phrase only the quote and the backslash are special."""
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def _credit(parts):
    """[{'name': 'A', 'joinphrase': ' feat. '}, {'name': 'B'}] -> 'A feat. B'"""
    return "".join((p.get("name") or (p.get("artist") or {}).get("name") or "") + (p.get("joinphrase") or "") for p in parts or []).strip()


def _year(date):
    found = re.match(r"\d{4}", date or "")
    return found.group(0) if found else ""


def _number(text):
    """Track numbers on vinyl are 'A1', 'B3'... those have no plain number."""
    return int(text) if re.fullmatch(r"\d+", str(text or "")) else 0


def release_kind(release):
    """'album' only for a plain studio album; compilations and live albums are worse choices."""
    group = release.get("release-group") or {}
    primary = (group.get("primary-type") or "").lower()
    secondary = [s.lower() for s in group.get("secondary-types") or []]
    if "live" in secondary:
        return "live"
    if "compilation" in secondary:
        return "compilation"
    if secondary:                     # soundtrack, remix, demo, mixtape...
        return "other"
    return {"album": "album", "ep": "ep", "single": "single"}.get(primary, "other")


def _release_rank(release):
    """Best release first: an official studio album, then EP, single...; among equals, the earliest."""
    official = 0 if release.get("status") == "Official" else 1
    return official, KINDS.index(release_kind(release)), release.get("date") or "9999"


class MusicBrainz:
    def __init__(self, client=None):
        self.client = client or MetadataClient("MusicBrainz", MIN_INTERVAL_SECONDS)

    def search(self, title, artist=None, limit=SEARCH_LIMIT):
        """Candidates for a song, one or two per recording (its best studio release, and its single)."""
        query = f'recording:"{_lucene(title)}"'
        if artist:
            query += f' AND artist:"{_lucene(artist)}"'
        data = self.client.get_json(f"{BASE}/recording", {"query": query, "fmt": "json", "limit": limit})
        found = []
        for recording in data.get("recordings") or []:
            found.extend(self._infos(recording))
        return found

    def find_cover(self, album, artist, releases=2):
        """Cover Art Archive urls (biggest first) of the first releases that match this album and artist, or ().
        For songs another service identified, so the cover can still come from here."""
        query = f'release:"{_lucene(album)}" AND artist:"{_lucene(artist)}"'
        data = self.client.get_json(f"{BASE}/release", {"query": query, "fmt": "json", "limit": releases})
        urls = []
        for release in (data.get("releases") or [])[:releases]:
            if release.get("id"):
                urls += [f"{COVERS}/{release['id']}/{name}" for name in ("front-1200", "front-500", "front")]
        return tuple(urls)

    def _infos(self, recording):
        releases = sorted(recording.get("releases") or [], key=_release_rank)
        if not releases:
            return []
        chosen = [releases[0]]
        if release_kind(releases[0]) == "album":
            single = next((r for r in releases[1:] if release_kind(r) == "single"), None)
            if single:
                chosen.append(single)
        return [self._info(recording, release) for release in chosen]

    @staticmethod
    def _info(recording, release):
        artist = _credit(recording.get("artist-credit"))
        media = (release.get("media") or [{}])[0]
        track = (media.get("track") or [{}])[0]
        release_id = release.get("id") or ""
        covers = tuple(f"{COVERS}/{release_id}/{name}" for name in ("front-1200", "front-500", "front")) if release_id else ()
        return SongInfo(
            source="musicbrainz",
            title=recording.get("title") or "",
            artist=artist,
            album=release.get("title") or "",
            album_artist=_credit(release.get("artist-credit")) or artist,
            year=_year(release.get("date")) or _year(recording.get("first-release-date")),
            track_number=_number(track.get("number")),
            track_total=int(media.get("track-count") or 0),
            disc_number=int(media.get("position") or 0),
            kind=release_kind(release),
            duration=(recording.get("length") or 0) / 1000,
            cover_urls=covers,
            thumb_url=f"{COVERS}/{release_id}/front-250" if release_id else "",
            release_id=release_id,
        )
