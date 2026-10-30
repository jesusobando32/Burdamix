"""A song found by typing its name, shaped like a Spotify track so the downloader, the file names and the window treat both the same."""
import hashlib

import const
from apis.song_info import SongInfo
from apis.youtube import normalize
from pathutils import sanitize_filename, song_filename


class TextTrack:
    def __init__(self, info: SongInfo, asked=""):
        self.song_info = info          # what the metadata service said: the tags are written from it
        self.asked = asked             # what the user typed ("en vivo" in it is not held against a video)
        self.added_at = None
        # Letters and digits only: the window and the file-name planner use this id as a key. Two songs of one album may share a title
        # ("Intro" on both discs): the service's id, or the disc and track number, keep them apart (or the second would count as a repeat).
        key = "|".join([*(normalize(part) for part in (info.artist, info.title, info.album)), info.track_id,
                        str(info.disc_number), str(info.track_number)])
        self.resource_id = "t" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
        self.refresh()

    def refresh(self):
        """Rebuild what the downloader reads from `song_info`: call it after the song's data was completed."""
        info = self.song_info
        self.track_metadata = {
            "title": info.title,
            # The main artist first (file name, window), then the guests credited on the song: the video search must know
            # them, or a video that names a real guest ('ft. Daddy Yankee') would be taken for a remix.
            "artist": [info.artist, *(n for n in info.contributors if n != info.artist)],
            "album": info.album,
            "release_date": info.year,
            "track_num": info.track_number,
            "disc_num": info.disc_number or 1,
            "duration_ms": round(info.duration * 1000),
            "image_url": info.cover_urls[0] if info.cover_urls else (info.thumb_url or const.UNKNOWN_ALBUM_COVER_URL),
        }

    def get_title(self, sanitize=False):
        title = self.track_metadata["title"] or "Unknown Title"
        return sanitize_filename(title) if sanitize else title

    def get_artist(self, sanitize=False):
        artist = self.track_metadata["artist"][0] or "Unknown artist"
        return sanitize_filename(artist) if sanitize else artist

    def get_filename(self, style=const.DEFAULT_NAME_STYLE):
        return song_filename(self.track_metadata["title"], self.track_metadata["artist"][0], style)

    def get_metadata(self):
        return self.track_metadata
