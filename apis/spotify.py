from exceptions import InvalidSpotifyURL, SpotifyAlbumNotFound, SpotifyTrackNotFound, SpotifyPlaylistNotFound, SpotifyRetrievalError
import re
import time
from urllib.parse import urlparse

import requests

import login
import const
from pathutils import sanitize_filename

API_BASE = "https://api.spotify.com/v1/"
SPOTIFY_ORIGIN = "https://api.spotify.com"
MAX_RATE_LIMIT_WAIT_SECONDS = 5 * 60   # longer than this in total: stop and tell the user instead of hanging

PLAYLIST_NOT_READABLE = (
    "Spotify only lets this app read playlists that are YOURS (or collaborative ones you are part of). "
    "To download someone else's playlist, open it in Spotify, select all songs (Ctrl+A), "
    "'Add to playlist' > 'New playlist', and use the link of your new copy."
)


class SpotifyHTTPError(SpotifyRetrievalError):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


class SpotifyNetworkError(SpotifyRetrievalError):
    def __init__(self, detail=""):
        super().__init__("No pude conectarme a Spotify. Revisa tu conexión a internet e inténtalo de nuevo."
                         + (f" ({detail})" if detail else ""))


class SpotifyRateLimited(SpotifyHTTPError):
    def __init__(self, status_code, wait_seconds):
        super().__init__(status_code, f"Spotify te limitó por hacer demasiadas peticiones. Intenta de nuevo en unos {max(1, round(wait_seconds / 60))} minuto(s).")


class SpotifyAPI:
    """Minimal Spotify Web API client. Talks to the REST API directly instead of through
    tekore's models, which reject the responses Spotify returns today."""

    def __init__(self, access_token, allowed_origins=None):
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {access_token}"
        # The token is only ever sent to these origins. Links inside responses ('next' pages) are
        # checked against them, so a strange link can never make us hand the token to another server.
        self.allowed_origins = set(allowed_origins or {SPOTIFY_ORIGIN})

    def get(self, path, **params):
        url = path if path.startswith("http") else API_BASE + path
        parsed = urlparse(url)
        if f"{parsed.scheme}://{parsed.netloc}" not in self.allowed_origins:
            raise SpotifyRetrievalError(f"Refusing to send the Spotify token to an unexpected address: {parsed.netloc or url[:40]}")
        waited = 0

        for _ in range(5):
            try:
                response = self.session.get(url, params=params or None, timeout=20, allow_redirects=False)
            except requests.RequestException as e:   # no internet, DNS failure, timeout...
                raise SpotifyNetworkError(type(e).__name__) from None
            if response.status_code != 429:
                break

            try:
                wait = int(response.headers.get("Retry-After", 2)) + 1
            except ValueError:
                wait = 3
            if waited + wait > MAX_RATE_LIMIT_WAIT_SECONDS:
                raise SpotifyRateLimited(response.status_code, wait)

            print(f"[!] Spotify te limitó por pedir demasiado; espero {wait} s...")
            time.sleep(wait)
            waited += wait

        if response.status_code == 429:
            raise SpotifyRateLimited(429, wait)
        if response.status_code != 200:
            raise SpotifyHTTPError(response.status_code, f"Spotify answered {response.status_code} for {url.replace(API_BASE, '')}")

        try:
            return response.json()
        except ValueError:   # a 200 that is not JSON, e.g. a Wi-Fi login page
            raise SpotifyNetworkError("respuesta inesperada") from None

    def paginate(self, first_page):
        """Yield every item of a paging object, following 'next' links."""
        page = first_page
        while page:
            yield from page.get("items") or []
            page = self.get(page["next"]) if page.get("next") else None


def _extract_id(kind, url):
    match = re.search(rf"/{kind}/([a-zA-Z0-9]+)", url)
    if match is None:
        raise InvalidSpotifyURL(f"Could not find a {kind} ID in: {url}")
    return match.group(1)


def _best_image(images):
    return images[0]["url"] if images else const.UNKNOWN_ALBUM_COVER_URL


class Spotify:

    def __init__(self, authType: const.SpotifyAuthType):
        if authType == const.SpotifyAuthType.USER:
            access_token = login.get_user_token().access_token
        else:
            access_token = login.get_client_token()

        self.api = SpotifyAPI(access_token)

    def likedSongs(self, limit=None):
        return SpotifyLikedSongs(self, limit)

    def playlist(self, playlist_url):
        if 'playlist/' not in playlist_url:
            raise InvalidSpotifyURL(f"Invalid Spotify Playlist URL: {playlist_url}")
        return SpotifyPlaylist(self, playlist_url)

    def track(self, track_url):
        if 'track/' not in track_url:
            raise InvalidSpotifyURL(f"Invalid Spotify Track URL: {track_url}")
        return SpotifyTrack(self, track_url)

    def album(self, album_url):
        if 'album/' not in album_url:
            raise InvalidSpotifyURL(f"Invalid Spotify Album URL: {album_url}")
        return SpotifyAlbum(self, album_url)


def track_from_data(base, data, album=None, added_at=None):
    """Build a loaded SpotifyTrack from API JSON, or None if it can't be downloaded
    (removed track, local file, podcast episode)."""
    if not data or data.get("is_local") or not data.get("id") or data.get("type", "track") != "track":
        return None

    album = data.get("album") or album
    if not album or not data.get("artists"):
        return None

    track = SpotifyTrack(base, f"https://open.spotify.com/track/{data['id']}")
    track.load(data, album)
    track.added_at = added_at   # when the user saved it (liked songs only)
    return track


class _Collection:
    """Common behaviour of albums, playlists and liked songs."""
    default_title = "Unknown"

    def __init__(self, base):
        self.base = base
        self.metadata = {}

    def load(self):
        raise NotImplementedError

    def _ensure_loaded(self):
        if not self.metadata:
            self.load()

    def get_title(self, sanitize=False):
        self._ensure_loaded()
        title = self.metadata.get("title", self.default_title)
        return sanitize_filename(title) if sanitize else title

    def get_tracks(self):
        self._ensure_loaded()
        return self.metadata.get("tracks", [])

    def get_metadata(self):
        self._ensure_loaded()
        return self.metadata


class SpotifyPlaylist(_Collection):
    default_title = "Unknown Playlist Name"

    def __init__(self, base: Spotify, resource_url):
        super().__init__(base)
        self.resource_url = resource_url
        self.resource_id = _extract_id("playlist", resource_url)

    def load(self):
        api = self.base.api
        try:
            info = api.get(f"playlists/{self.resource_id}", fields="name,images")
            first_page = api.get(f"playlists/{self.resource_id}/items", limit=100)

            tracks = []
            for entry in api.paginate(first_page):
                # Spotify renamed 'track' to 'item' in this endpoint; accept both.
                track = track_from_data(self.base, entry.get("item") or entry.get("track"))
                if track is not None:
                    tracks.append(track)
        except SpotifyHTTPError as e:
            if e.status_code == 404:
                raise SpotifyPlaylistNotFound("Playlist not found.") from None
            if e.status_code in (401, 403):
                raise SpotifyPlaylistNotFound(PLAYLIST_NOT_READABLE) from None
            raise

        self.metadata = {"title": info.get("name", self.default_title), "image_url": _best_image(info.get("images")), "tracks": tracks}


class SpotifyAlbum(_Collection):
    default_title = "Unknown Album Name"

    def __init__(self, base: Spotify, resource_url):
        super().__init__(base)
        self.resource_url = resource_url
        self.resource_id = _extract_id("album", resource_url)

    def load(self):
        api = self.base.api
        try:
            album = api.get(f"albums/{self.resource_id}")
            tracks = []
            # Album tracks come without album info, so the album object is passed along
            # instead of fetching every track again.
            for item in api.paginate(album["tracks"]):
                track = track_from_data(self.base, item, album)
                if track is not None:
                    tracks.append(track)
        except SpotifyHTTPError as e:
            if e.status_code == 404:
                raise SpotifyAlbumNotFound("Album not found.") from None
            raise

        self.metadata = {"title": album.get("name", self.default_title), "image_url": _best_image(album.get("images")), "tracks": tracks}


class SpotifyLikedSongs(_Collection):
    default_title = "Liked Songs"

    def __init__(self, base, limit=None):
        super().__init__(base)
        self.limit = limit   # only the N most recently liked songs (None = all of them)
        self.total = None    # how many liked songs the account has, as reported by Spotify

    def load(self):
        api = self.base.api
        wanted = self.limit
        first = api.get("me/tracks", limit=min(50, wanted) if wanted else 50)
        self.total = first.get("total")

        tracks = []
        # Spotify returns them newest first, and pages are only requested as they are consumed, so
        # stopping as soon as there are enough means a "last 50" costs one request, not twenty.
        for entry in api.paginate(first):
            track = track_from_data(self.base, entry.get("track"), added_at=entry.get("added_at"))
            if track is not None:
                tracks.append(track)
                if wanted and len(tracks) >= wanted:
                    break

        self.metadata = {"title": "Liked Songs", "image_url": const.UNKNOWN_ALBUM_COVER_URL, "tracks": tracks}


class SpotifyTrack:
    def __init__(self, base: Spotify, resource_url):
        self.base = base
        self.resource_url = resource_url
        self.resource_id = _extract_id("track", resource_url)
        self.track_metadata = {}
        self.added_at = None

    def load(self, track_data=None, album_data=None):
        if track_data is None:
            try:
                track_data = self.base.api.get(f"tracks/{self.resource_id}")
            except SpotifyHTTPError as e:
                if e.status_code == 404:
                    raise SpotifyTrackNotFound("Track not found.") from None
                raise

        album_data = track_data.get("album") or album_data
        artists = track_data.get("artists") or []
        if not album_data or not artists:
            raise SpotifyTrackNotFound("Failed to fetch track data from Spotify API.")

        self.track_metadata = {
            "title": track_data["name"],
            "artist": [artist["name"] for artist in artists],
            "album": album_data["name"],
            "release_date": album_data.get("release_date", ""),
            "track_num": track_data.get("track_number", 0),
            "disc_num": track_data.get("disc_number", 1),
            "duration_ms": track_data.get("duration_ms", 0),
            "isrc": (track_data.get("external_ids") or {}).get("isrc", False),
            "comments": {
                "Spotify Track URL": (track_data.get("external_urls") or {}).get("spotify", ""),
                "Spotify Album URL": (album_data.get("external_urls") or {}).get("spotify", ""),
                "Spotify Artist URL": (artists[0].get("external_urls") or {}).get("spotify", ""),
                "Duration (ms)": str(track_data.get("duration_ms", 0)),
                "Album Type": album_data.get("album_type", ""),
            },
            "image_url": _best_image(album_data.get("images")),
        }

    def _ensure_loaded(self):
        if not self.track_metadata:
            self.load()

    def get_title(self, sanitize=False):
        self._ensure_loaded()
        title = self.track_metadata.get("title", "Unknown Title")
        return sanitize_filename(title) if sanitize else title

    def get_filename(self):
        """'Artist - Title': unique enough that two songs titled alike don't overwrite each other."""
        self._ensure_loaded()
        return sanitize_filename(f"{', '.join(self.track_metadata['artist'])} - {self.track_metadata['title']}")

    def get_artist(self, sanitize=False):
        self._ensure_loaded()
        artist_name = " ".join(self.track_metadata.get("artist", ["Unknown artist"]))
        return sanitize_filename(artist_name) if sanitize else artist_name

    def get_metadata(self):
        self._ensure_loaded()
        return self.track_metadata
