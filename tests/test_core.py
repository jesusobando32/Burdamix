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


# --- Spotify setup ---------------------------------------------------------------

def test_setup_with_a_new_app_forgets_the_old_login(tmp_path, monkeypatch):
    """Regression: --setup used to keep the refresh token of the previous Spotify app, which then failed forever."""
    import login
    import tekore as tk

    cfg = tmp_path / "tekore_cfg.ini"
    monkeypatch.setattr(login, "cfg_filename", str(cfg))
    monkeypatch.setattr(login, "legacy_cfg_filename", str(tmp_path / "no_legacy.ini"))   # never touch the real file
    tk.config_to_file(str(cfg), ("OLD_ID", "OLD_SECRET", login.login_redirect_url, "OLD_REFRESH"))
    assert login.is_user_logged_in()

    monkeypatch.setattr("builtins.input", lambda *_: "NEW_ID")
    monkeypatch.setattr(login.getpass, "getpass", lambda *_: "NEW_SECRET")
    monkeypatch.setattr(login.webbrowser, "open", lambda *_: True)
    monkeypatch.setattr(login, "_request_client_token", lambda *_: "token")

    login.do_client_login()

    assert tk.config_from_file(str(cfg), return_refresh=True)[:2] == ("NEW_ID", "NEW_SECRET")
    assert not login.is_user_logged_in()   # the old refresh token is gone, so a fresh login will be requested
    assert login.is_client_configured()


# --- Spotify rate limit ------------------------------------------------------------

def _api(url):
    """An API client allowed to talk to the local test server at `url`."""
    from urllib.parse import urlparse
    import apis.spotify as sp
    parsed = urlparse(url)
    return sp.SpotifyAPI("t", allowed_origins={f"{parsed.scheme}://{parsed.netloc}"})


def _server(handler_body):
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        hits = 0

        def do_GET(self):
            type(self).hits += 1
            handler_body(self, type(self).hits)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}/x"


def test_long_rate_limit_stops_with_a_clear_message_instead_of_sleeping_for_hours(monkeypatch):
    import apis.spotify as sp

    def handler(h, n):
        h.send_response(429); h.send_header("Retry-After", "86400"); h.end_headers()

    srv, url = _server(handler)
    slept = []
    monkeypatch.setattr(sp.time, "sleep", slept.append)
    with pytest.raises(sp.SpotifyRateLimited) as e:
        _api(url).get(url)
    srv.shutdown()
    assert slept == []                       # it did not wait a day
    assert "minuto" in str(e.value)


def test_short_rate_limit_is_waited_out_and_the_request_then_succeeds(monkeypatch):
    import apis.spotify as sp

    def handler(h, n):
        if n == 1:
            h.send_response(429); h.send_header("Retry-After", "2"); h.end_headers()
        else:
            h.send_response(200); h.send_header("Content-Type", "application/json"); h.end_headers(); h.wfile.write(b'{"ok": true}')

    srv, url = _server(handler)
    slept = []
    monkeypatch.setattr(sp.time, "sleep", slept.append)
    assert _api(url).get(url) == {"ok": True}
    srv.shutdown()
    assert slept == [3]


def test_total_wait_is_capped_at_five_minutes(monkeypatch):
    import apis.spotify as sp

    def handler(h, n):
        h.send_response(429); h.send_header("Retry-After", "200"); h.end_headers()

    srv, url = _server(handler)
    slept = []
    monkeypatch.setattr(sp.time, "sleep", slept.append)
    with pytest.raises(sp.SpotifyRateLimited):
        _api(url).get(url)
    srv.shutdown()
    assert sum(slept) <= sp.MAX_RATE_LIMIT_WAIT_SECONDS


# --- Network errors ------------------------------------------------------------------

def test_no_internet_becomes_a_clear_error_not_a_raw_requests_exception():
    import apis.spotify as sp
    with pytest.raises(sp.SpotifyNetworkError) as e:
        _api("http://127.0.0.1:9/never").get("http://127.0.0.1:9/never")      # nothing listens on port 9
    assert "internet" in str(e.value)


def test_a_non_json_200_is_reported_as_a_network_problem():
    import apis.spotify as sp

    def handler(h, n):
        h.send_response(200); h.end_headers(); h.wfile.write(b"<html>Wi-Fi login</html>")

    srv, url = _server(handler)
    with pytest.raises(sp.SpotifyNetworkError):
        _api(url).get(url)
    srv.shutdown()


def test_collection_download_exits_cleanly_when_spotify_is_unreachable(capsys):
    """Regression: a ConnectionError used to escape as a traceback while reading a playlist."""
    import apis.spotify as sp
    from downloader import SpotifyDownloader

    class Playlist:
        def get_title(self): return "x"
        def get_tracks(self): raise sp.SpotifyNetworkError("ConnectionError")

    with pytest.raises(SystemExit):
        SpotifyDownloader(None, None)._download_collection("playlist", "playlists", lambda: Playlist(), "nf")
    out = capsys.readouterr().out
    assert "No pude conectarme a Spotify" in out and "Could not read" not in out


# --- Long paths --------------------------------------------------------------------

def test_files_can_be_written_past_260_characters(tmp_path):
    """Windows rejects such paths unless long-path support is on; long_path() makes them work anyway."""
    from pathutils import long_path
    from downloader import SpotifyDownloader
    from pathlib import Path

    deep = str(tmp_path / ("P" * 120) / ("Artista - " + "T" * 140)) + ".mp3"
    assert len(deep) > 260 if os.name == "nt" else True

    d = SpotifyDownloader(None, None)
    d.prep_folder(os.path.dirname(deep) + os.sep)
    with open(long_path(deep), "wb") as f:
        f.write(b"data")
    assert d.file_exists(deep)
    assert Path(long_path(deep)).read_bytes() == b"data"


def test_hard_to_open_warning_only_for_very_long_paths():
    from pathutils import is_hard_to_open
    assert not is_hard_to_open("downloads/albums/Album/Artista - Titulo.mp3")
    if os.name == "nt":
        assert is_hard_to_open("C:/" + "a" * 300 + ".mp3")


def test_invisible_direction_characters_are_removed_from_names():
    assert sanitize_filename("x‮exe.mp3") == "xexe.mp3"


# --- Token only goes to Spotify ----------------------------------------------------------

def test_token_is_never_sent_to_another_host():
    """Regression: a 'next' link pointing elsewhere used to receive 'Authorization: Bearer <token>'."""
    import apis.spotify as sp
    seen = []

    def handler(h, n):
        seen.append(h.headers.get("Authorization"))
        h.send_response(200); h.send_header("Content-Type", "application/json"); h.end_headers(); h.wfile.write(b'{"items": []}')

    srv, url = _server(handler)
    api = sp.SpotifyAPI("SECRET_TOKEN")            # default: only api.spotify.com is allowed
    with pytest.raises(sp.SpotifyRetrievalError, match="unexpected address"):
        api.get(url)
    with pytest.raises(sp.SpotifyRetrievalError):
        list(api.paginate({"items": [], "next": url}))   # the same link arriving as a 'next' page
    srv.shutdown()
    assert seen == []                                # the foreign server never saw a request, let alone the token


@pytest.mark.parametrize("bad", ["http://api.spotify.com/v1/me", "https://api.spotify.com.evil.com/v1/me",
                                 "https://evil.com/https://api.spotify.com/", "//api.spotify.com/v1/me"])
def test_lookalike_addresses_are_rejected(bad):
    import apis.spotify as sp
    with pytest.raises(sp.SpotifyRetrievalError):
        sp.SpotifyAPI("t").get(bad)


def test_redirects_are_not_followed():
    import apis.spotify as sp

    def handler(h, n):
        h.send_response(302); h.send_header("Location", "http://127.0.0.1:1/steal"); h.end_headers()

    srv, url = _server(handler)
    with pytest.raises(sp.SpotifyRetrievalError):
        _api(url).get(url)
    srv.shutdown()


# --- Config location ------------------------------------------------------------------------

def test_config_lives_outside_the_project_folder():
    import login
    project = os.path.dirname(os.path.abspath(login.__file__))
    assert not os.path.abspath(login.cfg_filename).startswith(project)
    assert os.path.dirname(login.cfg_filename).endswith("Burdamix")


def test_old_config_is_moved_to_the_private_folder_without_losing_it(tmp_path, monkeypatch):
    import login
    import tekore as tk
    old, new = tmp_path / "project" / "tekore_cfg.ini", tmp_path / "private" / "Burdamix" / "tekore_cfg.ini"
    old.parent.mkdir()
    tk.config_to_file(str(old), ("ID", "SECRET", login.login_redirect_url, "REFRESH"))
    original = old.read_bytes()
    monkeypatch.setattr(login, "cfg_filename", str(new))
    monkeypatch.setattr(login, "legacy_cfg_filename", str(old))

    assert login.is_user_logged_in()                      # first use triggers the move
    assert new.read_bytes() == original and not old.exists()
    assert tk.config_from_file(str(new), return_refresh=True)[3] == "REFRESH"


def test_nothing_is_deleted_if_the_copy_cannot_be_verified(tmp_path, monkeypatch):
    import login
    old, new = tmp_path / "old.ini", tmp_path / "private" / "new.ini"
    old.write_text("[DEFAULT]\nx = 1\n")
    monkeypatch.setattr(login, "cfg_filename", str(new))
    monkeypatch.setattr(login, "legacy_cfg_filename", str(old))
    def bad_copy(src, dst):
        with open(dst, "wb") as f:
            f.write(b"corrupted")
    monkeypatch.setattr(login.shutil, "copy2", bad_copy)
    login.migrate_legacy_config()
    assert old.exists() and not new.exists()              # the original survived and no bad copy was left behind
    assert not (tmp_path / "private" / "new.ini.tmp").exists()


def test_an_existing_new_config_is_never_overwritten_by_the_old_one(tmp_path, monkeypatch):
    import login
    old, new = tmp_path / "old.ini", tmp_path / "new.ini"
    old.write_text("OLD"); new.write_text("NEW")
    monkeypatch.setattr(login, "cfg_filename", str(new))
    monkeypatch.setattr(login, "legacy_cfg_filename", str(old))
    login.migrate_legacy_config()
    assert new.read_text() == "NEW" and old.exists()


