"""Listening statistics: every listen is one line appended to a file, the summary is worked out from those lines. All on this computer."""
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stats_store  # noqa: E402

NOW = datetime(2026, 11, 6, 15, 0).timestamp()
DAY = 86400


@pytest.fixture
def stats(tmp_path):
    return stats_store.Stats(str(tmp_path / "plays.jsonl"), clock=lambda: NOW)


def listen(stats, artist, title, album="", seconds=200, days_ago=0, at=None):
    stats.record(artist, title, album, seconds, ts=(NOW - days_ago * DAY) if at is None else at)


def test_a_new_store_has_nothing_to_summarise(stats):
    s = stats.summary("all")
    assert s["plays"] == 0 and s["seconds"] == 0 and s["songs"] == [] and s["artists"] == [] and s["albums"] == [] and s["streak"] == 0


def test_listens_survive_a_restart(stats, tmp_path):
    listen(stats, "Feid", "Normal")
    again = stats_store.Stats(str(tmp_path / "plays.jsonl"), clock=lambda: NOW)
    assert again.summary("all")["plays"] == 1


def test_the_same_song_in_other_capitals_or_accents_counts_as_one(stats):
    listen(stats, "Feid", "Normal")
    listen(stats, "FEID", "normal")
    listen(stats, "Féid", "Normal")
    songs = stats.summary("all")["songs"]
    assert len(songs) == 1 and songs[0]["plays"] == 3


def test_tops_are_ordered_by_plays_then_by_time_and_limited(stats):
    for i in range(15):
        listen(stats, f"Artista {i}", f"Canción {i}")
    for _ in range(3):
        listen(stats, "Mora", "Memorias", "Cabernet", seconds=100)
    listen(stats, "Mora", "Otra", "Cabernet", seconds=300)
    s = stats.summary("all")
    assert s["songs"][0]["title"] == "Memorias" and s["songs"][0]["plays"] == 3
    assert s["artists"][0] == {"artist": "Mora", "plays": 4, "seconds": 600}
    assert s["albums"][0]["album"] == "Cabernet" and s["albums"][0]["plays"] == 4
    assert len(s["songs"]) == stats_store.TOP and len(s["artists"]) == stats_store.TOP


def test_a_song_without_album_does_not_make_an_empty_album(stats):
    listen(stats, "Mora", "Suelta")
    assert stats.summary("all")["albums"] == []


def test_periods_are_rolling_windows(stats):
    listen(stats, "A", "hoy", days_ago=0)
    listen(stats, "A", "hace 5", days_ago=5)
    listen(stats, "A", "hace 20", days_ago=20)
    listen(stats, "A", "hace 200", days_ago=200)
    listen(stats, "A", "hace 800", days_ago=800)
    assert [stats.summary(p)["plays"] for p in ("week", "month", "year", "all")] == [2, 3, 4, 5]


def test_an_unknown_period_is_taken_as_everything(stats):
    listen(stats, "A", "x", days_ago=900)
    assert stats.summary("nope")["plays"] == 1


def test_hours_are_the_sum_of_seconds_listened(stats):
    listen(stats, "A", "x", seconds=1800)
    listen(stats, "A", "y", seconds=1800)
    assert stats.summary("all")["seconds"] == 3600


def test_the_streak_counts_consecutive_days_ending_today_or_yesterday(stats):
    for d in (0, 1, 2, 4):
        listen(stats, "A", f"d{d}", days_ago=d)
    assert stats.summary("all")["streak"] == 3
    other = stats_store.Stats(stats.path, clock=lambda: NOW + DAY)    # tomorrow: today's gap does not break it yet
    assert other.summary("all")["streak"] == 3
    later = stats_store.Stats(stats.path, clock=lambda: NOW + 2 * DAY)
    assert later.summary("all")["streak"] == 0


def test_the_week_chart_has_seven_daily_bars_oldest_first_with_minutes(stats):
    listen(stats, "A", "x", seconds=600, days_ago=0)
    listen(stats, "A", "y", seconds=300, days_ago=2)
    bars = stats.summary("week")["series"]
    assert len(bars) == 7 and bars[-1]["minutes"] == 10 and bars[-3]["minutes"] == 5 and bars[0]["minutes"] == 0
    assert bars[-1]["label"] and bars[-1]["date"] == "2026-11-06"


def test_the_year_chart_has_twelve_monthly_bars(stats):
    listen(stats, "A", "x", seconds=600, days_ago=0)
    bars = stats.summary("year")["series"]
    assert len(bars) == 12 and bars[-1]["minutes"] == 10


def test_play_counts_by_song_serve_the_smart_playlists(stats):
    listen(stats, "Feid", "Normal", days_ago=3)
    listen(stats, "feid", "NORMAL", days_ago=1)
    counts = stats.counts()
    (plays, last), = counts.values()
    assert plays == 2 and last == NOW - DAY
    assert ("feid", "normal") in counts


def test_garbage_lines_in_the_file_are_skipped(stats):
    listen(stats, "A", "x")
    with open(stats.path, "a", encoding="utf-8") as f:
        f.write("esto no es json\n[1,2]\n{}\n")
    listen(stats, "A", "y")
    assert stats.summary("all")["plays"] == 2


def test_a_record_without_artist_or_title_still_counts_for_time_but_has_no_song_entry(stats):
    stats.record("", "", "", 100, ts=NOW)
    s = stats.summary("all")
    assert s["plays"] == 1 and s["seconds"] == 100 and s["songs"] == []


def test_silly_values_are_refused(stats):
    assert stats.record("A", "x", "", -5, ts=NOW) is False
    assert stats.record("A", "x", "", float("nan"), ts=NOW) is False
    assert stats.record("A", "x", "", 99999, ts=NOW) is False
    assert stats.summary("all")["plays"] == 0


# --- through the window's API ---------------------------------------------------------------------------------------

def test_the_api_records_listens_of_library_songs_only_and_links_the_top_songs_to_their_ids(tmp_path, monkeypatch):
    import const
    import library
    from gui import backend
    from tagwriter import TagInfo
    monkeypatch.setattr(const, "data_dir", lambda: str(tmp_path / "datos"))
    songs = tmp_path / "songs"
    songs.mkdir()
    (songs / "a.mp3").write_bytes(b"x")
    monkeypatch.setattr(library.tagwriter, "read_tags", lambda path: TagInfo(title="Normal", artist="Feid", album="FERXXO", duration=200))
    api = backend.Api()
    monkeypatch.setattr(api, "_downloads_dir", lambda: str(songs))
    track = api.library_list()["tracks"][0]
    assert api.stats_play(track["id"], 45) == {"ok": True}
    assert api.stats_play("no-existe", 45) == {"ok": False}
    assert api.stats_play(track["id"], "45") == {"ok": False}
    assert api.stats_play(track["id"], True) == {"ok": False}
    summary = api.stats_summary("week")
    assert summary["plays"] == 1 and summary["songs"][0]["id"] == track["id"]
    assert api.stats_summary(5)["plays"] == 1      # a nonsense period is taken as everything
