import argparse
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apis.youtube import Candidate, clean_song_title, normalize, rank_candidates  # noqa: E402
from pathutils import sanitize_filename  # noqa: E402
from exceptions import YoutubeItemNotFound  # noqa: E402


def cand(title, duration, channel="Some Channel", views=1000, url="u"):
    return Candidate(url=url, title=title, channel=channel, duration=duration, views=views)


# --- Matching YouTube videos against Spotify's data ----------------------------

def test_normalize_drops_accents_and_punctuation():
    assert normalize("Tití Me Preguntó!") == "titi me pregunto"


def test_clean_song_title():
    assert clean_song_title("Song (feat. X) - Remastered 2011") == "Song"
    assert clean_song_title("Blinding Lights") == "Blinding Lights"


def test_blinding_lights_regression_picks_audio_not_the_long_video():
    """The music video (263s) used to win because it was the first result; Spotify says 200s."""
    video = cand("The Weeknd - Blinding Lights (Official Video)", 263, "The Weeknd", 1_075_000_000, "video")
    audio = cand("The Weeknd - Blinding Lights (Official Audio)", 204, "The Weeknd", 883_000_000, "audio")
    ranked = rank_candidates([video, audio], "Blinding Lights", ["The Weeknd"], 200)
    assert [c.url for c in ranked] == ["audio"]


def test_topic_channel_beats_a_live_version_of_the_same_length():
    live = cand("Song (Live at Wembley)", 200, "Artist", 90_000_000, "live")
    topic = cand("Song", 200, "Artist - Topic", 1_000_000, "topic")
    assert rank_candidates([live, topic], "Song", ["Artist"], 200)[0].url == "topic"


def test_unwanted_word_is_fine_when_spotify_title_has_it():
    live = cand("Live Forever", 200, "Oasis", 1000, "x")
    assert rank_candidates([live], "Live Forever", ["Oasis"], 200)[0].url == "x"


def test_no_video_close_to_the_duration_means_no_match():
    assert rank_candidates([cand("Song", 400)], "Song", ["A"], 200) == []


def test_relaxed_tolerance_needs_the_title_in_the_video_name():
    assert rank_candidates([cand("Song by A", 212)], "Song", ["A"], 200)       # 12s off but same title
    assert not rank_candidates([cand("Something else", 212)], "Song", ["A"], 200)


def test_videos_without_duration_are_ignored():
    assert rank_candidates([cand("Song", None)], "Song", ["A"], 200) == []


def test_quality_helpers():
    import spotify2mp3 as app
    assert app.get_bitrate_from_quality("high") == 320000
    assert app.get_bitrate_from_quality("192") == 192000
    assert app.get_bitrate_from_quality("192000") == 192000
    assert app.validate_quality("320") == "320"
    for bad in ("5", "abc", "999999"):
        with pytest.raises(argparse.ArgumentTypeError):
            app.validate_quality(bad)


# --- Spotify parsing -------------------------------------------------------------

def _api_track(**overrides):
    track = {
        "id": "abc123", "type": "track", "name": "Canción", "track_number": 3, "disc_number": 1,
        "duration_ms": 200000, "external_urls": {"spotify": "https://open.spotify.com/track/abc123"},
        "artists": [{"name": "Artista", "external_urls": {}}],
        "album": {"name": "Álbum", "release_date": "2020-05-01", "album_type": "album",
                  "images": [{"url": "http://img/1.jpg"}], "external_urls": {}},
    }
    track.update(overrides)
    return track


def test_track_from_data_builds_metadata_and_filename():
    from apis.spotify import track_from_data
    track = track_from_data(None, _api_track())
    assert track.get_filename() == "Artista - Canción"
    assert track.get_metadata()["image_url"] == "http://img/1.jpg"
    assert track.get_searchable_title() == "Canción - Artista"


@pytest.mark.parametrize("bad", [
    None, _api_track(is_local=True), _api_track(id=None), _api_track(type="episode"), _api_track(artists=[]),
])
def test_track_from_data_skips_undownloadable_items(bad):
    from apis.spotify import track_from_data
    assert track_from_data(None, bad) is None


def test_album_tracks_use_the_album_passed_in():
    from apis.spotify import track_from_data
    simplified = _api_track()
    album = simplified.pop("album")
    assert track_from_data(None, simplified, album).get_metadata()["album"] == "Álbum"


# --- Parallel download -----------------------------------------------------------

def test_download_tracks_runs_in_parallel_and_collects_failures(monkeypatch):
    import threading
    import time
    from downloader import SpotifyDownloader

    d = SpotifyDownloader(None, None, workers=4)
    running, peak, lock = [0], [0], threading.Lock()

    class FakeTrack:
        def __init__(self, n): self.n = n
        def get_filename(self): return f"t{self.n}"

    def fake_download_track(self, url, track, i, n, out, sub):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.05)
        with lock:
            running[0] -= 1
        if track.n == 3:
            raise YoutubeItemNotFound("nope")
        return True

    monkeypatch.setattr(SpotifyDownloader, "download_track", fake_download_track)
    skipped = d.download_tracks("out/", [FakeTrack(n) for n in range(8)])

    assert [t.n for t, _ in skipped] == [3]
    assert 1 < peak[0] <= 4


# --- Interludes ------------------------------------------------------------------

@pytest.mark.parametrize("title,seconds,expected", [
    ("EUROPA :)", 12, True),                      # regression: 12s track with a normal name
    ("Blinding Lights", 50, True),                # <= 50s is never a song, whatever the name
    ("Blinding Lights", 51, False),               # just over the limit: kept
    ("Blinding Lights", 65, False),
    ("Repeat After Me (Interlude)", 196, False),  # named interlude but a real 3-minute piece
    ("Skit: la llamada", 50, True),
    ("Interludio", 61, True),                     # a 60s interlude measured as 61 is still caught
    ("Interlude", 70, True),                      # interludes: 70s limit
    ("Interlude", 71, False),
    ("Intro", 35, True),
    ("Outro", 85, True),
    ("Intro", 95, True),                          # intro/outro: 95s limit
    ("Intro", 96, False),                         # over that it is a song, keep it
    ("Canción con Intro", 200, False),
    ("Introspection", 60, False),                 # 'intro' only as part of another word
])
def test_is_interlude(title, seconds, expected):
    from downloader import is_interlude
    assert is_interlude(title, seconds) is expected


def test_limits_are_configurable():
    from downloader import is_interlude
    assert is_interlude("Interlude", 90, max_seconds=120)
    assert not is_interlude("Intro", 90, intro_outro_max_seconds=30)
    assert is_interlude("Song", 55, short_max_seconds=60)
    assert not is_interlude("Song", 12, short_max_seconds=5)


# --- Quality ---------------------------------------------------------------------

@pytest.mark.parametrize("source,requested,expected", [
    (132, 320, 128),   # "high": YouTube's best (Opus 132) becomes a 128 kbps MP3, not 320
    (130, 320, 128),
    (67, 320, 64),
    (132, 80, 80),     # "medium" caps the download
    (132, 50, 48),
    (160, 320, 160),   # a 160 kbps source is kept at 160
    (132, 192, 128),   # asking for more than the source never raises the bitrate
])
def test_mp3_bitrate_never_exceeds_source(source, requested, expected):
    from downloader import mp3_bitrate_for
    assert mp3_bitrate_for(source, requested) == expected


def test_high_means_best_available_and_is_described_honestly():
    import spotify2mp3 as app
    assert app.get_bitrate_from_quality("high") == app.MAX_BITRATE_BPS
    assert "best YouTube offers" in app.describe_quality("high")
    assert "YouTube offers about" in app.describe_quality("320")   # asking for 320 explains what you really get
    assert "up to 80" in app.describe_quality("medium")


