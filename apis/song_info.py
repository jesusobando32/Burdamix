"""What a metadata service knows about one song: the same shape whichever service it came from."""
from dataclasses import asdict, dataclass, fields

KINDS = ("album", "ep", "single", "other", "compilation", "live")   # best to worst when choosing which release to use
KIND_LABELS = {"album": "Álbum de estudio", "ep": "EP", "single": "Sencillo", "other": "Otro",
               "compilation": "Recopilatorio", "live": "En vivo"}


@dataclass
class SongInfo:
    source: str = ""          # "musicbrainz", "deezer" or "itunes"
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    year: str = ""
    genre: str = ""
    track_number: int = 0
    track_total: int = 0
    disc_number: int = 0
    kind: str = "other"       # one of KINDS
    duration: float = 0.0     # seconds
    cover_urls: tuple = ()    # best first; the first that downloads is used
    thumb_url: str = ""       # small picture for the window
    release_id: str = ""      # MusicBrainz release id, when there is one
    score: float = 0.0        # filled in when the results are ranked

    @property
    def kind_label(self):
        return KIND_LABELS.get(self.kind, "Otro")

    def to_dict(self):
        data = asdict(self)
        data["cover_urls"] = list(self.cover_urls)
        data["kind_label"] = self.kind_label
        return data

    @classmethod
    def from_dict(cls, data):
        """Rebuild from what the window sent back, ignoring anything we do not know about."""
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in (data or {}).items() if k in known}
        clean["cover_urls"] = tuple(str(u) for u in clean.get("cover_urls") or () if isinstance(u, str) and u.startswith("https://"))
        for key in ("track_number", "track_total", "disc_number"):
            try:
                clean[key] = max(0, int(clean.get(key) or 0))
            except (TypeError, ValueError):
                clean[key] = 0
        try:
            clean["duration"] = float(clean.get("duration") or 0)
            clean["score"] = float(clean.get("score") or 0)
        except (TypeError, ValueError):
            clean["duration"] = clean["score"] = 0.0
        for key in ("source", "title", "artist", "album", "album_artist", "year", "genre", "thumb_url", "release_id"):
            clean[key] = str(clean.get(key) or "")
        clean["kind"] = clean.get("kind") if clean.get("kind") in KINDS else "other"
        return cls(**clean)
