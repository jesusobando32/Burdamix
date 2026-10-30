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
        def get_filename(self, style=None): return f"t{self.n}"

    def fake_download_track(self, url, track, i, n, out, sub, filename=None):
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


# --- YouTube block brake ---------------------------------------------------------------

@pytest.mark.parametrize("message,kind", [
    ("ERROR: [youtube] abc: Sign in to confirm you’re not a bot. Use --cookies-from-browser", "YoutubeBlocked"),
    ("ERROR: HTTP Error 429: Too Many Requests", "YoutubeBlocked"),
    ("ERROR: The current session has been rate-limited by YouTube for up to an hour", "YoutubeBlocked"),
    ("ERROR: [youtube] abc: Sign in to confirm your age. This video may be inappropriate", "YoutubeVideoUnavailable"),
    ("ERROR: [youtube] abc: Video unavailable", "YoutubeVideoUnavailable"),
    ("ERROR: unable to download video data: HTTP Error 403: Forbidden", "YoutubeTransientError"),
    ("ERROR: <urlopen error [WinError 10060] timed out>", "YoutubeNetworkError"),
])
def test_youtube_errors_are_classified(message, kind):
    from apis.youtube import translate_youtube_error
    assert type(translate_youtube_error(Exception(message))).__name__ == kind


def test_unknown_errors_pass_through_unchanged():
    from apis.youtube import translate_youtube_error
    original = Exception("ERROR: something else entirely")
    assert translate_youtube_error(original) is original


class _Song:
    def __init__(self, n): self.n = n
    def get_filename(self, style=None): return f"s{self.n}"


def _run(outcomes, workers, capsys):
    """outcomes[n] is None (success) or an exception that song n raises."""
    import threading
    from downloader import SpotifyDownloader

    attempts = []
    lock = threading.Lock()

    def fake(self, url, track, i, n, out, sub, filename=None):
        with lock:
            attempts.append(track.n)
        if outcomes[track.n] is not None:
            raise outcomes[track.n]
        return True

    import downloader
    d = SpotifyDownloader(None, None, workers=workers)
    orig, orig_delay = SpotifyDownloader.download_track, downloader.RETRY_PASS_DELAY_SECONDS
    SpotifyDownloader.download_track = fake
    downloader.RETRY_PASS_DELAY_SECONDS = 0       # the end-of-run retry would otherwise wait 15 s
    try:
        skipped = d.download_tracks("out/", [_Song(n) for n in range(len(outcomes))])
    finally:
        SpotifyDownloader.download_track = orig
        downloader.RETRY_PASS_DELAY_SECONDS = orig_delay
    return d, attempts, skipped, capsys.readouterr().out


def test_five_blocked_songs_in_a_row_stop_the_run(capsys):
    from exceptions import YoutubeBlocked
    d, attempts, skipped, out = _run([YoutubeBlocked("bot")] * 40, workers=1, capsys=capsys)
    assert d.blocked
    assert len(attempts) == 5            # it stopped asking YouTube after the fifth refusal
    assert "te está bloqueando" in out and "mismo enlace" in out


def test_with_parallel_workers_the_brake_still_limits_the_damage(capsys):
    from exceptions import YoutubeBlocked
    d, attempts, skipped, out = _run([YoutubeBlocked("bot")] * 200, workers=5, capsys=capsys)
    assert d.blocked
    assert len(attempts) < 20            # not all 200


def test_a_success_in_between_resets_the_streak(capsys):
    from exceptions import YoutubeBlocked
    b = YoutubeBlocked("bot")
    outcomes = [b, b, b, b, None, b, b, b, b, None, b, b, b, b]     # never 5 in a row
    d, attempts, skipped, out = _run(outcomes, workers=1, capsys=capsys)
    assert not d.blocked
    assert set(attempts) == set(range(len(outcomes)))                 # every song was tried (the failed ones once more at the end)


def test_other_failures_do_not_trigger_the_brake(capsys):
    from exceptions import YoutubeItemNotFound
    d, attempts, skipped, out = _run([YoutubeItemNotFound("x")] * 12, workers=1, capsys=capsys)
    assert not d.blocked and len(attempts) == 12                       # not retryable, so each song is tried exactly once


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


# --- File name collisions ------------------------------------------------------------------

class _Named:
    def __init__(self, spotify_id, filename): self.resource_id, self._f = spotify_id, filename
    def get_filename(self, style=None): return self._f


def test_same_song_twice_is_planned_once():
    from downloader import plan_filenames
    a1, a2 = _Named("id1", "Artista - Song"), _Named("id1", "Artista - Song")
    plan, repeated, renamed = plan_filenames([a1, a2])
    assert [name for _, _, name in plan] == ["Artista - Song"] and repeated == [a2] and renamed == []


def test_different_songs_with_the_same_name_get_a_number():
    from downloader import plan_filenames
    original, remaster = _Named("aaa", "Queen - Song"), _Named("bbb", "Queen - Song")
    plan, repeated, renamed = plan_filenames([original, remaster])
    assert sorted(name for _, _, name in plan) == ["Queen - Song", "Queen - Song (2)"]
    assert len(renamed) == 1 and repeated == []


def test_names_that_differ_only_in_case_collide_on_windows_and_are_separated():
    from downloader import plan_filenames
    plan, _, renamed = plan_filenames([_Named("x1", "Artista - Intro"), _Named("x2", "ARTISTA - INTRO")])
    assert len({name.casefold() for _, _, name in plan}) == 2       # two different files, even ignoring case


def test_names_do_not_depend_on_playlist_order():
    """A second run, with the playlist in another order, must give each version the same file name."""
    from downloader import plan_filenames
    a, b = _Named("aaa", "Q - Song"), _Named("bbb", "Q - Song")
    first = {t.resource_id: n for _, t, n in plan_filenames([a, b])[0]}
    second = {t.resource_id: n for _, t, n in plan_filenames([b, a])[0]}
    assert first == second


def test_download_tracks_downloads_a_repeated_song_once_and_reports_it(capsys):
    from downloader import SpotifyDownloader
    calls = []

    def fake(self, url, track, i, n, out, sub, filename=None):
        calls.append(filename)
        return True

    orig = SpotifyDownloader.download_track
    SpotifyDownloader.download_track = fake
    try:
        d = SpotifyDownloader(None, None, workers=1)
        d.download_tracks("out/", [_Named("a", "X - One"), _Named("a", "X - One"), _Named("b", "X - Two"), _Named("c", "X - Two")])
    finally:
        SpotifyDownloader.download_track = orig
    assert sorted(calls) == ["X - One", "X - Two", "X - Two (2)"]
    out = capsys.readouterr().out
    assert "repeated song" in out and "X - Two (2)" in out and d.planned == 3


# --- yt-dlp updates -----------------------------------------------------------------------

def test_update_check_is_due_only_after_a_day(tmp_path):
    import time
    import updater
    marker = tmp_path / "m"
    assert updater.is_due(str(marker))                          # never checked
    marker.write_text("x")
    assert not updater.is_due(str(marker))                      # just checked
    assert updater.is_due(str(marker), now=time.time() + 25 * 3600)


def test_update_runs_pip_once_and_then_waits_a_day(tmp_path):
    import subprocess
    import updater
    marker = str(tmp_path / "m")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    updater.update_ytdlp_if_due(marker, run=fake_run)
    updater.update_ytdlp_if_due(marker, run=fake_run)           # same day: nothing to do
    assert len(calls) == 1 and "yt-dlp" in calls[0] and "--upgrade" in calls[0]


def test_failed_update_does_not_start_the_day_and_never_crashes(tmp_path, capsys):
    import subprocess
    import updater
    marker = tmp_path / "m"
    updater.update_ytdlp_if_due(str(marker), run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "no internet"))
    assert not marker.exists()                                  # tries again next time
    assert "sigo con la versión que tienes" in capsys.readouterr().out

    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)
    updater.update_ytdlp_if_due(str(marker), run=boom)          # a hung pip is also survived
    assert not marker.exists()


# --- Retrying with another video -------------------------------------------------------------

class _Audio:
    """A fake YouTube whose download() follows a script: one outcome per call (an exception or a result)."""
    def __init__(self, script): self.script, self.calls = list(script), []
    def download(self, link, quality):
        self.calls.append(link)
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _downloader(script, monkeypatch):
    import downloader
    monkeypatch.setattr(downloader, "RETRY_DELAY_SECONDS", 0)
    yt = _Audio(script)
    d = downloader.SpotifyDownloader(None, yt, 128000)
    track = type("T", (), {"get_title": lambda self, sanitize=False: "Song"})()
    return d, yt, track


def test_a_temporary_error_moves_on_to_the_next_video(monkeypatch):
    from exceptions import YoutubeTransientError
    d, yt, track = _downloader([YoutubeTransientError("403"), ("file.m4a", 130)], monkeypatch)
    assert d._download_audio("[1/1]", track, ["A", "B", "C"]) == ("file.m4a", 130)
    assert yt.calls == ["A", "B"]


def test_when_every_video_fails_temporarily_everything_is_tried_once_more(monkeypatch):
    from exceptions import YoutubeTransientError
    script = [YoutubeTransientError("403")] * 2 + [("ok.m4a", 130)]
    d, yt, track = _downloader(script, monkeypatch)
    assert d._download_audio("[1/1]", track, ["A", "B"]) == ("ok.m4a", 130)
    assert yt.calls == ["A", "B", "A"]                    # second round started over


def test_it_gives_up_after_the_second_round(monkeypatch):
    from exceptions import YoutubeTransientError
    d, yt, track = _downloader([YoutubeTransientError("403")] * 10, monkeypatch)
    with pytest.raises(YoutubeTransientError):
        d._download_audio("[1/1]", track, ["A", "B"])
    assert len(yt.calls) == 4                              # 2 videos x 2 rounds, not an endless loop


def test_restricted_videos_do_not_trigger_a_second_round(monkeypatch):
    from exceptions import YoutubeVideoUnavailable
    d, yt, track = _downloader([YoutubeVideoUnavailable("age")] * 10, monkeypatch)
    with pytest.raises(YoutubeVideoUnavailable):
        d._download_audio("[1/1]", track, ["A", "B"])
    assert len(yt.calls) == 2                              # a restricted video will not get better in 3 seconds


def test_unknown_errors_are_not_retried(monkeypatch):
    d, yt, track = _downloader([RuntimeError("disk full")], monkeypatch)
    with pytest.raises(RuntimeError):
        d._download_audio("[1/1]", track, ["A", "B"])
    assert yt.calls == ["A"]


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


# --- Tags ----------------------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def private_temp_root(tmp_path, monkeypatch):
    """Every test gets its own temporary root, so tests never touch (or depend on) the real one."""
    import tempdirs
    monkeypatch.setattr(tempdirs, "ROOT", str(tmp_path / "Burdamix-temp"))
    monkeypatch.setattr(tempdirs, "_run_dir", None)


def _tone_file(path, seconds=3):
    import subprocess
    import imageio_ffmpeg
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency=440:duration={seconds}", "-c:a", "aac", "-b:a", "96k", str(path)], check=True)


def _cover_bytes(fmt):
    import subprocess
    import imageio_ffmpeg
    codec = "mjpeg" if fmt == "jpeg" else "png"
    return subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64",
                           "-frames:v", "1", "-f", "image2pipe", "-c:v", codec, "-"], capture_output=True).stdout


@pytest.mark.parametrize("fmt,mime", [("jpeg", "image/jpeg"), ("png", "image/png")])
def test_mp3_is_written_as_id3v23_with_accents_year_cover_and_no_leftovers(tmp_path, monkeypatch, fmt, mime):
    from mutagen.id3 import ID3
    import utils

    src, out = tmp_path / "in.m4a", tmp_path / "out" / "Artista - Canción.mp3"
    (tmp_path / "out").mkdir()
    _tone_file(src)
    monkeypatch.chdir(tmp_path)                                  # the converter uses ./temp
    monkeypatch.setattr(utils, "_fetch_cover", lambda url: _cover_bytes(fmt))

    md = {"title": "Canción Ñandú", "artist": ["Bad Bunny", "Rosalía"], "album": "Mañana", "release_date": "2023-10-13",
          "track_num": 3, "image_url": "x"}
    utils.resave_audio_clip_with_metadata(str(src), md, str(out), 96)

    tags = ID3(str(out), translate=False)   # frames exactly as stored in the file
    assert tags.version == (2, 3, 0)
    assert str(tags["TIT2"]) == "Canción Ñandú" and str(tags["TPE1"]) == "Bad Bunny, Rosalía" and str(tags["TALB"]) == "Mañana"
    assert str(tags["TYER"]) == "2023"                           # the year survives in v2.3
    cover = next(frame for key, frame in tags.items() if key.startswith("APIC"))
    assert cover.mime == mime and len(cover.data) > 50
    import tempdirs
    assert not src.exists() and not os.path.exists(str(out) + ".part") and os.listdir(tempdirs.run_dir()) == []


def test_a_track_without_release_date_still_gets_tagged(tmp_path, monkeypatch):
    from mutagen.id3 import ID3
    import utils
    src, out = tmp_path / "in.m4a", tmp_path / "o.mp3"
    _tone_file(src)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(utils, "_fetch_cover", lambda url: _cover_bytes("jpeg"))
    utils.resave_audio_clip_with_metadata(str(src), {"title": "T", "artist": ["A"], "album": "Al", "release_date": "", "track_num": 1, "image_url": "x"}, str(out), 96)
    assert "TYER" not in ID3(str(out)) and str(ID3(str(out))["TIT2"]) == "T"


# --- Ctrl+C ----------------------------------------------------------------------------------------

def _download_with_ctrl_c(presses, monkeypatch, capsys):
    """Run download_tracks on slow fake songs and press Ctrl+C `presses` times while it works."""
    import signal
    import threading
    import time
    from downloader import SpotifyDownloader

    finished = []

    def slow(self, url, track, i, n, out, sub, filename=None):
        time.sleep(0.5)
        finished.append(track.n)
        return True

    monkeypatch.setattr(SpotifyDownloader, "download_track", slow)

    def presser():
        time.sleep(0.15)
        for _ in range(presses):
            signal.raise_signal(signal.SIGINT)
            time.sleep(0.2)

    threading.Thread(target=presser, daemon=True).start()
    d = SpotifyDownloader(None, None, workers=1)
    try:
        d.download_tracks("out/", [_Song(n) for n in range(3)])
        return finished, False
    except KeyboardInterrupt:
        return finished, True
    finally:
        capsys.readouterr()


def test_one_or_two_ctrl_c_do_not_cancel_a_download(monkeypatch, capsys):
    for presses in (1, 2):
        finished, cancelled = _download_with_ctrl_c(presses, monkeypatch, capsys)
        assert not cancelled and finished == [0, 1, 2]


def test_the_third_ctrl_c_cancels_the_download(monkeypatch, capsys):
    finished, cancelled = _download_with_ctrl_c(3, monkeypatch, capsys)
    assert cancelled and len(finished) < 3                  # songs that had not started never did


def test_the_original_ctrl_c_behaviour_is_restored_afterwards():
    import signal
    from downloader import ctrl_c_needs_three_presses
    before = signal.getsignal(signal.SIGINT)
    with ctrl_c_needs_three_presses():
        assert signal.getsignal(signal.SIGINT) is not before
    assert signal.getsignal(signal.SIGINT) is before


# --- Temporary folders ----------------------------------------------------------------------------

def test_each_run_has_its_own_temporary_folder_and_removes_it():
    import tempdirs
    folder = tempdirs.run_dir()
    assert os.path.isdir(folder) and folder.startswith(tempdirs.ROOT)
    assert tempdirs.run_dir() == folder                      # same folder for the whole run
    open(os.path.join(folder, "x.webm"), "w").close()
    tempdirs.remove_run_dir()
    assert not os.path.exists(folder) and not os.path.exists(tempdirs.ROOT)


def test_two_runs_do_not_delete_each_others_files(monkeypatch):
    """Regression: with one shared 'temp' folder, a run that finished wiped the other run's files."""
    import tempdirs
    first = tempdirs.run_dir()
    open(os.path.join(first, "in_progress.webm"), "w").close()

    monkeypatch.setattr(tempdirs, "_run_dir", None)          # a second copy of the program starts
    second = tempdirs.run_dir()
    assert second != first
    tempdirs.remove_run_dir()                                # the second one finishes first

    assert os.path.exists(os.path.join(first, "in_progress.webm"))   # the first one's files are intact


def test_only_old_abandoned_folders_are_cleaned_at_start():
    import time
    import tempdirs
    live = tempdirs.run_dir()
    old = os.path.join(tempdirs.ROOT, "run-abandoned")
    os.makedirs(old)
    long_ago = time.time() - 48 * 3600
    os.utime(old, (long_ago, long_ago))

    tempdirs.clean_stale()
    assert not os.path.exists(old) and os.path.isdir(live)


def test_songs_that_keep_failing_with_403_also_stop_the_run(capsys):
    """Regression: persistent 403s used to reset the brake, so a 300-song list was attempted to the end."""
    from exceptions import YoutubeTransientError
    d, attempts, skipped, out = _run([YoutubeTransientError("HTTP Error 403")] * 40, workers=1, capsys=capsys)
    assert d.blocked and len(attempts) == 5
    assert "te está bloqueando" in out


def test_an_occasional_403_does_not_stop_the_run(capsys):
    from exceptions import YoutubeTransientError
    t = YoutubeTransientError("HTTP Error 403")
    d, attempts, skipped, out = _run([t, None, t, None, t, t, None, t, None, t, None, t], workers=1, capsys=capsys)
    assert not d.blocked and set(attempts) == set(range(12))           # every song was tried (the failed ones once more at the end)


# --- Search wordings ------------------------------------------------------------------------------

def _searching(results_by_query):
    """A YouTube client whose search answers from a table: {query: [Candidate, ...]}. Records the queries asked."""
    from apis.youtube import YouTube
    yt = YouTube()
    asked = []

    def fake(query, count=8):
        asked.append(query)
        return iter(results_by_query.get(query, []))

    yt._search = fake
    return yt, asked


def test_a_simpler_wording_rescues_a_song_the_first_one_misses():
    """Regression: 'mariposas en el estómago' returned only a 949 s concert for the long query and was skipped."""
    from apis.youtube import search_queries
    long_q, simple_q, *_ = search_queries("mariposas en el estómago", ["RaiNao", "El Laberinto del Coco"])
    yt, asked = _searching({
        long_q: [cand("RaiNao: Tiny Desk Concert", 949, "NPR Music", 650_000, "concert")],
        simple_q: [cand("RaiNao & El Laberinto del Coco - mariposas en el estómago (BICHOALIZER)", 221, "RaiNao", 55_000, "song")],
    })
    assert yt.search("mariposas en el estómago", ["RaiNao", "El Laberinto del Coco"], 220, 1800, 0) == ["song"]
    assert asked == [long_q, simple_q]


def test_a_title_made_of_symbols_is_found_when_the_first_query_returns_nothing():
    from apis.youtube import search_queries
    title = "へ( •́ ‸ •̀) ʋ"
    long_q, simple_q, *_ = search_queries(title, ["RaiNao"])
    yt, asked = _searching({long_q: [], simple_q: [cand("RaiNao - へ[ •́ ‸ •̀ ]ʋ (BICHOALIZER)", 61, "RaiNao", 640_000, "kaomoji")]})
    assert yt.search(title, ["RaiNao"], 60, 1800, 0) == ["kaomoji"]


def test_no_extra_searches_when_the_first_wording_already_works():
    from apis.youtube import search_queries
    long_q = search_queries("Blinding Lights", ["The Weeknd"])[0]
    yt, asked = _searching({long_q: [cand("The Weeknd - Blinding Lights (Official Audio)", 204, "The Weeknd", 883_000_000, "audio")]})
    assert yt.search("Blinding Lights", ["The Weeknd"], 200, 1800, 0) == ["audio"]
    assert asked == [long_q]


def test_it_gives_up_only_after_every_wording_and_says_what_it_saw():
    yt, asked = _searching({})
    with pytest.raises(YoutubeItemNotFound, match="Could not load"):
        yt.search("Nada", ["Nadie"], 200, 1800, 0)
    assert len(asked) == 3

    from apis.youtube import search_queries
    yt, _ = _searching({q: [cand("Otra cosa", 949, "X", 10, "u")] for q in search_queries("Nada", ["Nadie"])})
    with pytest.raises(YoutubeItemNotFound, match="closest video lasts 949s"):
        yt.search("Nada", ["Nadie"], 200, 1800, 0)


def test_search_wordings_have_no_repeats():
    from apis.youtube import search_queries
    assert len(search_queries("Song", ["A"])) == len(set(search_queries("Song", ["A"])))


# --- Words YouTube refuses to search ----------------------------------------------------------------

def test_reduced_queries_drop_one_word_at_a_time_longest_first():
    from apis.youtube import reduced_queries
    assert reduced_queries("Graxxx & QSJM", ["JHAYCO"]) == ["JHAYCO QSJM", "JHAYCO Graxxx"]
    assert reduced_queries("Una sola", ["A"]) == ["A Una", "A sola"]      # drops the longer word first
    assert reduced_queries("Graxxx", ["JHAYCO"]) == []            # one word: nothing left to search with


def test_a_song_whose_title_has_a_word_youtube_will_not_search_is_found_without_it():
    """Regression: any query containing 'Graxxx' returns zero results, so the song was always skipped."""
    from apis.youtube import search_queries, reduced_queries
    title, artists = "Graxxx & QSJM", ["JHAYCO"]
    yt, asked = _searching({reduced_queries(title, artists)[0]: [cand("JHAYCO - Graxxx & QSJM (Visualizer)", 215, "JHAYCO", 1_000_000, "song")]})
    assert yt.search(title, artists, 214, 1800, 0) == ["song"]
    assert asked == search_queries(title, artists) + [reduced_queries(title, artists)[0]]


def test_last_resort_results_must_contain_the_title_so_another_song_is_never_chosen():
    from apis.youtube import search_queries, reduced_queries
    title, artists = "Graxxx & QSJM", ["JHAYCO"]
    other = cand("JHAYCO - Quimik (Visualizer)", 214, "JHAYCO", 9_000_000, "other-song")   # same length, different song
    yt, _ = _searching({q: [other] for q in reduced_queries(title, artists)})
    with pytest.raises(YoutubeItemNotFound):
        yt.search(title, artists, 214, 1800, 0)


def test_require_title_only_filters_when_asked():
    from apis.youtube import rank_candidates
    other = cand("Artist - Something else", 200, "Artist", 10, "x")
    assert not rank_candidates([other], "Wanted", ["Artist"], 200)                  # the same length is not enough: it is another song
    assert not rank_candidates([other], "Wanted", ["Artist"], 200, require_title=True)


# --- Liked songs: last N, preview ---------------------------------------------------------------------

class _LikedApi:
    """Stands in for SpotifyAPI: serves 'me/tracks' in pages of up to 50, newest first, and counts requests."""
    def __init__(self, total):
        import apis.spotify as sp
        self.total, self.requests, self.first_limit = total, [], None
        self._real = sp.SpotifyAPI("t")
        self._real.get = self.get              # so SpotifyAPI.paginate follows our 'next' links

    def get(self, path, **params):
        self.requests.append(path)
        if len(self.requests) == 1:
            self.first_limit = params.get("limit")   # page size asked for in the first request
        offset = int(path.split("offset=")[1].split("&")[0]) if "offset=" in path else 0
        size = int(path.split("limit=")[1]) if "limit=" in path else params.get("limit", 50)
        items = [{"added_at": f"2026-10-{(i % 28) + 1:02d}T10:00:00Z", "track": _api_track(id=f"id{i}", name=f"Song {i}")}
                 for i in range(offset, min(offset + size, self.total))]
        more = offset + size < self.total
        return {"items": items, "total": self.total,
                "next": f"https://api.spotify.com/v1/me/tracks?offset={offset + size}&limit={size}" if more else None}

    def paginate(self, first):
        return self._real.paginate(first)


def _liked(total, limit):
    from apis.spotify import SpotifyLikedSongs
    base = type("Base", (), {})()
    base.api = _LikedApi(total)
    liked = SpotifyLikedSongs(base, limit)
    return liked, base.api


def test_the_last_50_liked_songs_cost_a_single_request():
    liked, api = _liked(total=1036, limit=50)
    tracks = liked.get_tracks()
    assert len(tracks) == 50 and len(api.requests) == 1 and api.first_limit == 50
    assert tracks[0].get_title() == "Song 0" and tracks[-1].get_title() == "Song 49"     # newest first
    assert liked.total == 1036                                                           # still reports how many there are


def test_a_limit_in_the_middle_of_a_page_stops_there():
    liked, api = _liked(total=1036, limit=70)
    assert len(liked.get_tracks()) == 70 and len(api.requests) == 2


def test_a_small_limit_asks_for_a_small_page():
    liked, api = _liked(total=1036, limit=10)
    assert len(liked.get_tracks()) == 10
    assert api.first_limit == 10 and len(api.requests) == 1       # no need to ask for 50 to keep 10


def test_without_a_limit_every_liked_song_is_fetched_in_pages_of_50():
    liked, api = _liked(total=120, limit=None)
    assert len(liked.get_tracks()) == 120 and len(api.requests) == 3


def test_liked_songs_remember_when_they_were_saved():
    liked, _ = _liked(total=5, limit=None)
    assert liked.get_tracks()[0].added_at.startswith("2026-10-")


def test_asking_for_more_than_you_have_just_returns_everything():
    liked, _ = _liked(total=30, limit=500)
    assert len(liked.get_tracks()) == 30


def test_last_must_be_a_positive_number():
    import spotify2mp3 as app
    assert app.positive_int("50") == 50
    for bad in ("0", "-3", "abc", "1.5"):
        with pytest.raises(argparse.ArgumentTypeError):
            app.positive_int(bad)


def test_last_without_liked_songs_is_refused_before_touching_spotify(capsys):
    import spotify2mp3 as app
    with pytest.raises(SystemExit):
        app.main(playlist="https://open.spotify.com/playlist/abc", last=5)
    assert "--last only works with your liked songs" in capsys.readouterr().out


def test_dry_run_with_a_single_song_is_refused(capsys):
    import spotify2mp3 as app
    with pytest.raises(SystemExit):
        app.main(song="https://open.spotify.com/track/abc", dry_run=True)
    assert "preview a list" in capsys.readouterr().out


def test_dry_run_lists_the_songs_and_downloads_nothing(tmp_path, capsys, monkeypatch):
    import downloader
    from downloader import SpotifyDownloader
    monkeypatch.setattr(downloader, "DOWNLOADS_DIR", str(tmp_path))     # never look at the real downloads folder
    liked, _ = _liked(total=3, limit=None)
    liked.limit = 2                                              # "the 2 most recent of 3"
    d = SpotifyDownloader(type("S", (), {"likedSongs": lambda self, last=None: liked})(), None, dry_run=True)
    monkeypatch.setattr(SpotifyDownloader, "download_tracks", lambda *a, **k: pytest.fail("a dry run must not download"))
    assert d.download_liked_songs(2) is True
    out = capsys.readouterr().out
    assert "Vista previa" in out and "   1. " in out and "(guardada 2026-10-" in out
    assert "por descargar: 2" in out and "ya descargadas: 0" in out
    assert not (tmp_path / "liked").exists()                      # not even the folder was created


def test_dry_run_counts_what_is_already_on_disk(tmp_path, capsys):
    from downloader import SpotifyDownloader
    liked, _ = _liked(total=3, limit=None)
    tracks = liked.get_tracks()
    d = SpotifyDownloader(None, None, dry_run=True)
    (tmp_path / f"{tracks[0].get_filename()}.mp3").write_bytes(b"x")
    d._show_plan(tracks, str(tmp_path) + os.sep, total=3)
    assert "ya descargadas: 1 | por descargar: 2" in capsys.readouterr().out


# --- "like it" in the guided mode --------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("like it", (True, 200)),                 # no number: the latest 200
    ("Like It", (True, 200)),
    ("like it 50", (True, 50)),
    ("LIKE IT 7", (True, 7)),
    ("likeit 30", (True, 30)),
    ("like it all", (True, None)),            # None = every liked song
    ("like it todas", (True, None)),
    ("liked", (True, 200)),                   # the old keyword keeps working
    ("me gusta 15", (True, 15)),
    ("  like it   25  ", (True, 25)),
    ("https://open.spotify.com/track/abc", (False, None)),
    ("like", (False, None)),
    ("", (False, None)),
])
def test_the_like_it_command(text, expected):
    import spotify2mp3 as app
    assert app.parse_liked_command(text) == expected


@pytest.mark.parametrize("bad", ["like it 0", "like it abc", "like it -5", "like it 2.5"])
def test_like_it_with_a_wrong_number_explains_what_to_write(bad):
    import spotify2mp3 as app
    with pytest.raises(ValueError, match="like it 50"):
        app.parse_liked_command(bad)


def test_like_it_asks_nothing_else_and_leads_to_the_list(monkeypatch):
    import spotify2mp3 as app
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt="": asked.append(prompt) or "like it 50")
    assert app.get_user_input() == ("liked", "like it 50", "high", {"last": 50, "confirm": True})
    assert len(asked) == 1                                    # not even the quality: the list comes first


def test_a_wrong_like_it_is_asked_again(monkeypatch, capsys):
    import spotify2mp3 as app
    answers = iter(["like it 0", "like it 3"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert app.get_user_input()[3] == {"last": 3, "confirm": True}
    assert "like it 50" in capsys.readouterr().out


def test_the_quality_question_shows_what_youtube_really_offers_not_320(monkeypatch):
    """Regression: the question kept saying '(48-320)' although YouTube never gives more than ~130 kbps."""
    import spotify2mp3 as app
    prompts, answers = [], iter(["https://open.spotify.com/track/abc", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or next(answers))
    assert app.get_user_input() == ("song", "https://open.spotify.com/track/abc", "high", {})
    quality_question = prompts[1]
    assert "320" not in quality_question and "48" not in quality_question
    assert f"~{app.YOUTUBE_MAX_KBPS} kbps" in quality_question


def test_the_instructions_mention_like_it(monkeypatch, capsys):
    import spotify2mp3 as app
    monkeypatch.setattr("builtins.input", lambda prompt="": "like it")
    app.get_user_input()
    assert "like it 50" in capsys.readouterr().out


@pytest.mark.parametrize("text,expected", [("yes", True), ("Y", True), ("s", True), ("sí", True), ("SI", True), ("no", False), ("N", False)])
def test_yes_no_answers(monkeypatch, text, expected):
    from downloader import ask_yes_no
    monkeypatch.setattr("builtins.input", lambda prompt="": text)
    assert ask_yes_no("?") is expected


def test_yes_no_asks_again_until_it_understands(monkeypatch, capsys):
    from downloader import ask_yes_no
    answers = iter(["quizás", "", "no"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert ask_yes_no("?") is False
    assert capsys.readouterr().out.count("Responde yes o no") == 2


def _asking_downloader(monkeypatch, tmp_path, answer, total=3, last=None):
    import downloader
    from downloader import SpotifyDownloader
    monkeypatch.setattr(downloader, "DOWNLOADS_DIR", str(tmp_path))
    liked, _ = _liked(total=total, limit=last)
    d = SpotifyDownloader(type("S", (), {"likedSongs": lambda self, n=None: liked})(), None, ask_before_download=True)
    downloaded = []

    def fake_download_tracks(self, out, tracks):
        downloaded.append(len(tracks))
        self.planned = len(tracks)        # what the real method records
        return []

    monkeypatch.setattr(SpotifyDownloader, "download_tracks", fake_download_tracks)
    monkeypatch.setattr("builtins.input", lambda prompt="": answer)
    return d, downloaded


def test_after_the_list_yes_downloads_exactly_what_was_shown(monkeypatch, tmp_path, capsys):
    d, downloaded = _asking_downloader(monkeypatch, tmp_path, "yes", total=5, last=3)
    assert d.download_liked_songs(3) is True
    out = capsys.readouterr().out
    assert "Vista previa" in out and "   3. " in out                 # the list came first
    assert downloaded == [3] and not d.declined                        # same 3 songs, no second fetch


def test_after_the_list_no_downloads_nothing(monkeypatch, tmp_path, capsys):
    d, downloaded = _asking_downloader(monkeypatch, tmp_path, "no", total=5, last=3)
    assert d.download_liked_songs(3) is True
    assert downloaded == [] and d.declined
    assert not (tmp_path / "liked").exists()


def test_the_preview_lists_up_to_300_songs():
    import downloader
    assert downloader.PREVIEW_LINES == 300                             # "like it" (200) shows every song


def test_ask_is_refused_for_a_single_song(capsys):
    import spotify2mp3 as app
    with pytest.raises(SystemExit):
        app.main(song="https://open.spotify.com/track/abc", confirm=True)
    assert "--ask" in capsys.readouterr().out


# --- Plain-language failures, retries and the YouTube login ------------------------------------------------

RAW_AGE = "ERROR: [youtube] n35nuFy_gkc: Sign in to confirm your age. This video may be inappropriate for some users. Use --cookies-from-browser or --cookies for the authentication."
RAW_BOT = "ERROR: [youtube] Heez0bXE4p0: Sign in to confirm you’re not a bot. This helps protect our community. Use --cookies-from-browser or --cookies for the authentication."


def test_the_two_errors_from_the_screenshot_are_explained_in_plain_words():
    from downloader import friendly_reason, reason_category
    from exceptions import YoutubeBlocked, YoutubeVideoUnavailable
    age, bot = YoutubeVideoUnavailable(RAW_AGE), YoutubeBlocked(RAW_BOT)
    assert reason_category(age) == "edad" and reason_category(bot) == "robot"
    assert friendly_reason(age) == "YouTube marca este video para mayores de edad y pide iniciar sesión."
    assert "no eres un robot" in friendly_reason(bot)
    for error in (age, bot):
        text = friendly_reason(error)
        assert "ERROR" not in text and "[youtube]" not in text and "--cookies" not in text and "http" not in text


@pytest.mark.parametrize("error,category", [
    ("YoutubeVideoUnavailable:Private video", "no_disponible"),
    ("YoutubeTransientError:HTTP Error 403", "temporal"),
    ("YoutubeItemNotFound:No YouTube video matches Spotify's duration of 220s (closest video lasts 949s)", "no_encontrada"),
    ("YoutubeItemNotFound:Could not load results from YouTube", "no_encontrada"),
    ("ConfigVideoLowViewCount:View count 3", "pocas_vistas"),
    ("SpotifyTrackNotFound:gone", "no_en_spotify"),
    ("RuntimeError:Failed to decrypt cookies", "cookies"),
    ("RuntimeError:disk full", "otro"),
])
def test_every_kind_of_failure_has_a_spanish_explanation_and_advice(error, category):
    import downloader
    import exceptions
    name, message = error.split(":", 1)
    cls = getattr(exceptions, name, None) or RuntimeError
    err = cls(message)
    assert downloader.reason_category(err) == category
    reason = downloader.friendly_reason(err)
    assert reason and reason[0].isupper() and "Traceback" not in reason
    assert category in downloader.ADVICE


def test_the_duration_explanation_says_why_it_prefers_to_skip():
    from downloader import friendly_reason
    from exceptions import YoutubeItemNotFound
    text = friendly_reason(YoutubeItemNotFound("No YouTube video matches Spotify's duration of 220s"))
    assert "misma duración" in text and "equivocada" in text


def _scripted(script, monkeypatch, **kwargs):
    """A downloader whose download_track follows script = {song number: [outcome per attempt]} and counts calls."""
    import downloader
    from downloader import SpotifyDownloader
    calls = []

    def fake(self, url, track, i, n, out, sub, filename=None):
        calls.append(track.n)
        outcome = script[track.n].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return True

    monkeypatch.setattr(SpotifyDownloader, "download_track", fake)
    monkeypatch.setattr(downloader, "RETRY_PASS_DELAY_SECONDS", 0)
    return SpotifyDownloader(None, None, workers=1, **kwargs), calls


def test_the_summary_names_each_song_with_its_reason_and_what_to_do(monkeypatch, capsys):
    from exceptions import YoutubeBlocked, YoutubeVideoUnavailable
    d, _ = _scripted({0: [YoutubeVideoUnavailable(RAW_AGE)], 1: [YoutubeBlocked(RAW_BOT)] * 2, 2: [True]}, monkeypatch)
    skipped = d.download_tracks("out/", [_Song(0), _Song(1), _Song(2)])
    out = capsys.readouterr().out
    assert len(skipped) == 2
    assert "2 canción(es) no se pudieron descargar" in out and "    s0" in out and "    s1" in out
    assert "mayores de edad" in out and "no eres un robot" in out and "Qué hacer" in out
    assert "--cookies-from-browser firefox" in out and "Espera unos minutos" in out
    assert "ERROR:" not in out and "[youtube]" not in out and "Skipped" not in out


def test_a_robot_check_on_one_video_moves_on_to_the_next_version(monkeypatch):
    """Regression: 'LOKENECESITAS' was skipped because its first video gave the robot check, although 11 others work."""
    import downloader
    from exceptions import YoutubeBlocked
    monkeypatch.setattr(downloader, "RETRY_DELAY_SECONDS", 0)
    yt = type("YT", (), {})()
    outcomes = iter([YoutubeBlocked("bot"), ("file.m4a", 130)])
    tried = []

    def download(link, quality):
        tried.append(link)
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    yt.download = download
    d = downloader.SpotifyDownloader(None, yt, 128000)
    track = type("T", (), {"get_title": lambda self, sanitize=False: "Song"})()
    assert d._download_audio("[1/1]", track, ["A", "B", "C"]) == ("file.m4a", 130)
    assert tried == ["A", "B"]


def test_if_every_version_gives_the_robot_check_it_gives_up_without_a_second_round(monkeypatch):
    import downloader
    from exceptions import YoutubeBlocked
    monkeypatch.setattr(downloader, "RETRY_DELAY_SECONDS", 0)
    tried = []

    def download(link, quality):
        tried.append(link)
        raise YoutubeBlocked("bot")

    yt = type("YT", (), {"download": staticmethod(download)})()
    d = downloader.SpotifyDownloader(None, yt, 128000)
    track = type("T", (), {"get_title": lambda self, sanitize=False: "Song"})()
    with pytest.raises(YoutubeBlocked):
        d._download_audio("[1/1]", track, ["A", "B", "C"])
    assert tried == ["A", "B", "C"]                       # each version once; waiting does not fix a block


def test_songs_rejected_by_youtube_get_one_calm_retry_at_the_end(monkeypatch, capsys):
    from exceptions import YoutubeBlocked
    d, calls = _scripted({0: [YoutubeBlocked("bot"), True], 1: [True]}, monkeypatch)
    assert d.download_tracks("out/", [_Song(0), _Song(1)]) == []
    assert calls == [0, 1, 0]                             # song 0 failed, song 1 worked, song 0 was retried and worked
    assert "Reintentando 1 canción(es)" in capsys.readouterr().out


def test_a_song_that_fails_again_in_the_retry_stays_in_the_summary(monkeypatch):
    from exceptions import YoutubeBlocked
    d, calls = _scripted({0: [YoutubeBlocked("bot")] * 2}, monkeypatch)
    skipped = d.download_tracks("out/", [_Song(0)])
    assert calls == [0, 0] and len(skipped) == 1


def test_adult_only_songs_are_not_retried_blindly(monkeypatch):
    from exceptions import YoutubeVideoUnavailable
    d, calls = _scripted({0: [YoutubeVideoUnavailable(RAW_AGE)]}, monkeypatch)
    assert len(d.download_tracks("out/", [_Song(0)])) == 1
    assert calls == [0]                                   # retrying cannot fix a missing login


def test_the_guided_mode_offers_the_youtube_login_for_adult_only_songs(monkeypatch, capsys):
    import downloader
    from exceptions import YoutubeVideoUnavailable

    class FakeYouTube:
        def __init__(self, cookies_from_browser=None):
            self.cookies_from_browser = cookies_from_browser

    monkeypatch.setattr(downloader, "YouTube", FakeYouTube)
    monkeypatch.setattr("builtins.input", lambda prompt="": "firefox")
    d, calls = _scripted({0: [YoutubeVideoUnavailable(RAW_AGE), True]}, monkeypatch, offer_browser_login=True)
    assert d.download_tracks("out/", [_Song(0)]) == []
    assert calls == [0, 0] and d.youtube_client.cookies_from_browser == "firefox"
    assert "sesión de firefox" in capsys.readouterr().out


def test_without_a_browser_answer_the_adult_only_songs_are_just_listed(monkeypatch):
    from exceptions import YoutubeVideoUnavailable
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    d, calls = _scripted({0: [YoutubeVideoUnavailable(RAW_AGE)]}, monkeypatch, offer_browser_login=True)
    assert len(d.download_tracks("out/", [_Song(0)])) == 1 and calls == [0]


def test_the_login_is_never_offered_outside_the_guided_mode(monkeypatch):
    from exceptions import YoutubeVideoUnavailable
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("must not ask"))
    d, _ = _scripted({0: [YoutubeVideoUnavailable(RAW_AGE)]}, monkeypatch)
    assert len(d.download_tracks("out/", [_Song(0)])) == 1


def test_ask_browser_only_accepts_a_known_browser(monkeypatch, capsys):
    from downloader import ask_browser
    answers = iter(["internet explorer", "Chrome"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert ask_browser() == "chrome"
    assert "Escribe uno de estos" in capsys.readouterr().out


def test_the_command_line_accepts_the_same_browsers():
    import spotify2mp3 as app
    from apis.youtube import SUPPORTED_BROWSERS
    for browser in SUPPORTED_BROWSERS:
        assert app.build_parser().parse_args(["-l", "--cookies-from-browser", browser]).cookies_from_browser == browser


def test_a_lone_song_that_fails_gets_the_same_plain_explanation_and_advice(capsys):
    from downloader import SpotifyDownloader
    from exceptions import YoutubeBlocked
    d = SpotifyDownloader(None, None)
    assert d._explain_single_failure(YoutubeBlocked(RAW_BOT)) is False
    out = capsys.readouterr().out
    assert "no eres un robot" in out and "Qué hacer" in out and "Espera unos minutos" in out
    assert "ERROR:" not in out and "[youtube]" not in out


def test_a_lone_adult_only_song_can_be_retried_with_the_browser_login(monkeypatch):
    import downloader
    from exceptions import YoutubeVideoUnavailable

    class FakeYouTube:
        def __init__(self, cookies_from_browser=None):
            self.cookies_from_browser = cookies_from_browser

    monkeypatch.setattr(downloader, "YouTube", FakeYouTube)
    monkeypatch.setattr("builtins.input", lambda prompt="": "firefox")
    d = downloader.SpotifyDownloader(None, None, offer_browser_login=True)
    assert d._explain_single_failure(YoutubeVideoUnavailable(RAW_AGE)) is True
    assert d.youtube_client.cookies_from_browser == "firefox"
    assert d._explain_single_failure(YoutubeVideoUnavailable(RAW_AGE)) is False      # only one retry, never a loop


def test_a_lone_adult_only_song_without_a_browser_answer_is_just_explained(monkeypatch):
    import downloader
    from exceptions import YoutubeVideoUnavailable
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    d = downloader.SpotifyDownloader(None, None, offer_browser_login=True)
    assert d._explain_single_failure(YoutubeVideoUnavailable(RAW_AGE)) is False


# --- yt-dlp updates inside the compiled program ------------------------------------------------------------------

def _fake_pypi(version="2099.01.01", extra_files=None, tamper=False, host="https://files.pythonhosted.org/x/yt_dlp.whl"):
    """A `get` that behaves like PyPI: a JSON answer and a wheel (a zip) with a yt_dlp package."""
    import hashlib
    import io
    import zipfile
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("yt_dlp/__init__.py", "")
        z.writestr("yt_dlp/version.py", f"__version__ = '{version}'\n")
        for name, content in (extra_files or {}).items():
            z.writestr(name, content)
    wheel = buffer.getvalue()
    digest = hashlib.sha256(wheel).hexdigest()
    if tamper:
        digest = "0" * 64
    data = {"info": {"version": version},
            "urls": [{"filename": "yt_dlp-x-py3-none-any.whl", "url": host, "digests": {"sha256": digest}}]}

    class Response:
        def __init__(self, payload=None, content=b""):
            self._payload, self.content = payload, content

        def json(self):
            return self._payload

    return lambda url, timeout=None: Response(data) if "pypi.org" in url else Response(content=wheel)


def test_the_newest_ytdlp_is_downloaded_checked_and_saved(tmp_path):
    import updater
    lib = tmp_path / "yt-dlp"
    assert updater.download_latest_ytdlp(str(lib), _fake_pypi(), current="2025.01.01") == ("2025.01.01", "2099.01.01")
    assert updater._version_in(str(lib)) == "2099.01.01"
    assert not (tmp_path / "yt-dlp.new").exists()


def test_nothing_is_downloaded_when_ytdlp_is_already_the_newest(tmp_path):
    import updater
    assert updater.download_latest_ytdlp(str(tmp_path / "lib"), _fake_pypi("2025.01.01"), current="2025.01.01") is None
    assert not (tmp_path / "lib").exists()


def test_a_download_that_does_not_match_its_pypi_hash_is_rejected(tmp_path):
    import updater
    with pytest.raises(updater.UpdateError, match="firma"):
        updater.download_latest_ytdlp(str(tmp_path / "lib"), _fake_pypi(tamper=True), current="2025.01.01")
    assert not (tmp_path / "lib").exists()


def test_a_download_from_an_unofficial_host_is_rejected(tmp_path):
    import updater
    with pytest.raises(updater.UpdateError, match="oficial"):
        updater.download_latest_ytdlp(str(tmp_path / "lib"), _fake_pypi(host="https://evil.example/yt.whl"), current="2025.01.01")


def test_files_outside_the_yt_dlp_package_are_never_written(tmp_path):
    import updater
    lib = tmp_path / "sub" / "yt-dlp"
    get = _fake_pypi(extra_files={"yt_dlp/../../escape.txt": "x", "other/file.py": "x", "/abs.txt": "x"})
    updater.download_latest_ytdlp(str(lib), get, current="2025.01.01")
    assert not (tmp_path / "escape.txt").exists() and not (tmp_path / "sub" / "escape.txt").exists()
    assert not (lib / "other").exists() and not (lib / "abs.txt").exists()


def test_no_internet_gives_a_clear_error_and_keeps_the_old_update(tmp_path):
    import updater
    lib = tmp_path / "lib"
    (lib / "yt_dlp").mkdir(parents=True)
    (lib / "yt_dlp" / "version.py").write_text("__version__ = '2030.01.01'\n")

    def offline(url, timeout=None):
        raise ConnectionError("offline")

    with pytest.raises(updater.UpdateError, match="No pude descargar"):
        updater.download_latest_ytdlp(str(lib), offline, current="2025.01.01")
    assert updater._version_in(str(lib)) == "2030.01.01"


def test_a_downloaded_ytdlp_is_used_only_when_newer_than_the_bundled_one(tmp_path, monkeypatch):
    import sys
    import updater
    lib = tmp_path / "lib"
    (lib / "yt_dlp").mkdir(parents=True)
    version_file = lib / "yt_dlp" / "version.py"
    monkeypatch.setattr(updater, "bundled_ytdlp_version", lambda: "2026.10.21")
    monkeypatch.setattr(sys, "path", list(sys.path))
    version_file.write_text("__version__ = '2026.10.30'\n")
    assert updater.use_downloaded_ytdlp(str(lib)) is False          # not compiled: scripts use pip instead
    monkeypatch.setattr(updater.const, "IS_FROZEN", True)
    assert updater.use_downloaded_ytdlp(str(lib)) is True and sys.path[0] == str(lib)
    sys.path.pop(0)
    version_file.write_text("__version__ = '2026.09.01'\n")         # the program was updated later: its own is newer
    assert updater.use_downloaded_ytdlp(str(lib)) is False
    assert updater.use_downloaded_ytdlp(str(tmp_path / "missing")) is False


def test_only_unexplained_extraction_errors_suggest_an_outdated_ytdlp():
    from downloader import suggests_outdated_ytdlp
    from exceptions import YoutubeBlocked, YoutubeVideoUnavailable
    assert suggests_outdated_ytdlp(RuntimeError("ERROR: [youtube] abc: Unable to extract player response"))
    assert suggests_outdated_ytdlp(RuntimeError("Requested format is not available"))
    assert not suggests_outdated_ytdlp(RuntimeError("disk full"))
    assert not suggests_outdated_ytdlp(YoutubeBlocked("Unable to extract"))          # a block is not fixed by updating
    assert not suggests_outdated_ytdlp(YoutubeVideoUnavailable("Private video"))


def _update_offer(monkeypatch, answer, frozen=True, guided=True, error=None):
    import downloader
    monkeypatch.setattr(downloader.const, "IS_FROZEN", frozen)
    monkeypatch.setattr("builtins.input", lambda prompt="": answer)
    calls = []

    def fake_download():
        calls.append(1)
        return ("2026.10.21", "2026.11.02")

    monkeypatch.setattr(downloader.updater, "download_latest_ytdlp", fake_download)
    d = downloader.SpotifyDownloader(None, None, offer_browser_login=guided)
    d._offer_ytdlp_update([(object(), error or RuntimeError("Unable to extract player response"))])
    return calls


def test_the_update_is_offered_and_done_when_the_user_says_yes(monkeypatch, capsys):
    assert _update_offer(monkeypatch, "yes") == [1]
    assert "2026.10.21 -> 2026.11.02" in capsys.readouterr().out


def test_the_update_is_not_done_when_the_user_says_no(monkeypatch):
    assert _update_offer(monkeypatch, "no") == []


def test_the_update_is_never_offered_outside_the_compiled_guided_mode(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("must not ask"))
    assert _update_offer(monkeypatch, "yes", frozen=False) == []
    assert _update_offer(monkeypatch, "yes", guided=False) == []
    assert _update_offer(monkeypatch, "yes", error=RuntimeError("disk full")) == []


# --- The window (gui/backend.py) and the progress events it listens to ------------------------------------------------

def _window_api(tmp_path, monkeypatch):
    import const
    import downloader
    monkeypatch.setattr(const, "data_dir", lambda: str(tmp_path))                  # never touch the real settings
    monkeypatch.setattr(downloader, "DOWNLOADS_DIR", downloader.DOWNLOADS_DIR)    # restored after the test
    from gui.backend import Api
    return Api()


def test_the_window_starts_with_sensible_settings_when_nothing_was_saved(tmp_path, monkeypatch):
    s = _window_api(tmp_path, monkeypatch).get_settings()
    assert s["workers"] == 5 and s["skip_interludes"] is True and s["browser"] == ""
    assert s["effective_downloads_dir"]


def test_settings_are_saved_cleaned_and_remembered(tmp_path, monkeypatch):
    import downloader
    api = _window_api(tmp_path, monkeypatch)
    folder = str(tmp_path / "mis canciones")
    result = api.save_settings({"workers": 99, "browser": "internet explorer", "downloads_dir": folder, "skip_interludes": False})
    assert result["ok"] and result["workers"] == 8 and result["browser"] == ""    # clamped; an unknown browser is dropped
    assert downloader.DOWNLOADS_DIR == folder                                       # the downloader uses the new folder at once
    again = _window_api(tmp_path, monkeypatch)                                             # a new run remembers them
    assert again.get_settings()["downloads_dir"] == folder and again.get_settings()["skip_interludes"] is False


def test_garbage_in_the_settings_file_falls_back_to_the_defaults(tmp_path, monkeypatch):
    (tmp_path / "settings.json").write_text("{not json")
    assert _window_api(tmp_path, monkeypatch).get_settings()["workers"] == 5
    (tmp_path / "settings.json").write_text('{"workers": "many", "browser": 7, "unknown": 1}')
    s = _window_api(tmp_path, monkeypatch).get_settings()
    assert s["workers"] == 5 and s["browser"] == "" and "unknown" not in s


def test_the_window_only_opens_known_pages(tmp_path, monkeypatch):
    import gui.backend as backend
    opened = []
    monkeypatch.setattr(backend.webbrowser, "open", opened.append)
    api = _window_api(tmp_path, monkeypatch)
    assert api.open_external("https://developer.spotify.com/dashboard") is True
    assert api.open_external("https://evil.example/https://developer.spotify.com/") is False
    assert api.open_external("file:///C:/Windows/System32/cmd.exe") is False
    assert api.open_external(None) is False
    assert opened == ["https://developer.spotify.com/dashboard"]


def test_events_are_delivered_once_and_in_order(tmp_path, monkeypatch):
    api = _window_api(tmp_path, monkeypatch)
    api._push("stage", key="a", stage="searching")
    api._push("done", key="a", existed=False)
    first = api.get_events()
    assert [e["kind"] for e in first] == ["stage", "done"] and first[0]["key"] == "a"
    assert api.get_events() == []


def test_a_bad_link_is_explained_before_anything_is_contacted(tmp_path, monkeypatch):
    api = _window_api(tmp_path, monkeypatch)
    assert "no parece un enlace de Spotify" in api.preview("https://example.com/hola")["error"]
    assert "spotify.link" in api.preview("https://spotify.link/abc")["error"]
    assert "número" in api.preview_liked("abc")["error"] and "mayor que 0" in api.preview_liked(-5)["error"]


def test_the_window_asks_for_setup_or_login_instead_of_failing(tmp_path, monkeypatch):
    import gui.backend as backend
    api = _window_api(tmp_path, monkeypatch)
    monkeypatch.setattr(backend.login, "is_client_configured", lambda: False)
    assert api.preview("https://open.spotify.com/album/abc")["error"] == "setup_required"
    monkeypatch.setattr(backend.login, "is_client_configured", lambda: True)
    monkeypatch.setattr(backend.login, "is_user_logged_in", lambda: False)
    assert api.preview("https://open.spotify.com/playlist/abc")["error"] == "login_required"
    assert api.preview_liked(50)["error"] == "login_required"


def test_downloading_needs_a_list_and_checked_songs(tmp_path, monkeypatch):
    api = _window_api(tmp_path, monkeypatch)
    assert api.start_download(["x"])["ok"] is False                      # no link was pasted yet
    api._pending = {"tracks": {"a": object()}, "output_path": "out/", "spotify": None}
    assert api.start_download([])["ok"] is False                         # nothing checked
    assert api.start_download(["not-in-the-list"])["ok"] is False


def test_the_spotify_app_is_checked_before_it_is_saved(tmp_path, monkeypatch):
    import login
    monkeypatch.setattr(login, "cfg_filename", str(tmp_path / "cfg.ini"))
    assert "obligatorios" in login.save_client_credentials("", "x")

    def refuse(client_id, client_secret):
        raise RuntimeError("bad")

    monkeypatch.setattr(login, "_request_client_token", refuse)
    assert "no aceptó" in login.save_client_credentials("id", "secret")
    assert not (tmp_path / "cfg.ini").exists()
    monkeypatch.setattr(login, "_request_client_token", lambda i, s: "token")
    assert login.save_client_credentials("  id  ", " secret ") is None
    import tekore as tk
    assert tk.config_from_file(str(tmp_path / "cfg.ini"), return_refresh=True)[:2] == ("id", "secret")


def test_progress_events_report_each_stage_and_a_broken_listener_cannot_stop_a_download():
    import downloader
    events = []
    d = downloader.SpotifyDownloader(None, None, on_event=lambda kind, **data: events.append((kind, data)))
    song = type("S", (), {"resource_id": "abc"})()
    d._emit("stage", song, stage="searching")
    d._emit("done", song, existed=True)
    assert events == [("stage", {"key": "abc", "stage": "searching"}), ("done", {"key": "abc", "existed": True})]

    def broken(kind, **data):
        raise RuntimeError("the window crashed")

    downloader.SpotifyDownloader(None, None, on_event=broken)._emit("done", song)   # must not raise


def test_a_failed_song_is_reported_to_the_window_with_its_reason(monkeypatch):
    from exceptions import YoutubeVideoUnavailable
    events = []
    d, _ = _scripted({0: [YoutubeVideoUnavailable(RAW_AGE)]}, monkeypatch)
    d.on_event = lambda kind, **data: events.append((kind, data))
    d.download_tracks("out/", [_Song(0)])
    failed = [data for kind, data in events if kind == "failed"]
    assert len(failed) == 1 and failed[0]["category"] == "edad" and "mayores de edad" in failed[0]["reason"]


def test_cancelling_stops_new_songs_and_skips_the_retry_pass(monkeypatch):
    from exceptions import YoutubeBlocked
    d, calls = _scripted({0: [YoutubeBlocked("bot")], 1: [True]}, monkeypatch)
    d.cancelled.set()
    d.download_tracks("out/", [_Song(0), _Song(1)])
    assert calls == []                                       # nothing started, and nothing was retried


def test_short_tracks_are_split_off_the_same_way_for_the_console_and_the_window():
    import downloader
    short = type("T", (), {"get_title": lambda self: "Intro", "get_metadata": lambda self: {"duration_ms": 30000}})()
    song = type("T", (), {"get_title": lambda self: "Real song", "get_metadata": lambda self: {"duration_ms": 200000}})()
    d = downloader.SpotifyDownloader(None, None, skip_interludes=True)
    assert d.split_interludes([short, song]) == ([song], [short])
    keep = downloader.SpotifyDownloader(None, None, skip_interludes=False)
    assert keep.split_interludes([short, song]) == ([short, song], [])


def test_the_window_files_exist_and_the_page_works_offline():
    import const
    web = os.path.join(const.resource_dir(), "gui", "web")
    for name in ("index.html", "style.css", "app.js", "logo.png"):
        assert os.path.exists(os.path.join(web, name)), name
    html = open(os.path.join(web, "index.html"), encoding="utf-8").read()
    assert 'href="style.css"' in html and 'src="app.js"' in html and "https://" not in html


def test_a_zip_member_with_a_drive_letter_is_never_extracted(tmp_path, monkeypatch):
    """'yt_dlp/D:evil/x.py' made os.path.join jump to the drive-relative path 'D:evil/x.py', outside the staging folder."""
    import updater
    drive = os.path.splitdrive(str(tmp_path))[0] or "D:"
    sneaky = f"yt_dlp/{drive}evil/x.py"

    class Archive:
        def namelist(self):
            return ["yt_dlp/ok.py", sneaky]
    assert list(updater._safe_members(Archive())) == ["yt_dlp/ok.py"]

    monkeypatch.chdir(tmp_path)   # a drive-relative path on this drive would land here, not in the user's real folders
    lib = tmp_path / "sub" / "yt-dlp"
    updater.download_latest_ytdlp(str(lib), _fake_pypi(extra_files={sneaky: "x"}), current="2025.01.01")
    assert not (tmp_path / "evil").exists()
    assert updater._version_in(str(lib)) == "2099.01.01"

