import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import const  # noqa: E402
from gui import backend  # noqa: E402


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(const, "data_dir", lambda: str(tmp_path / "datos"))
    return backend.Api()


def test_nothing_remembered_the_first_time(api):
    assert api.get_player() == {}


def test_what_the_player_saves_comes_back(api):
    data = {"volume": 0.4, "track": "abc", "eq": {"on": True, "bands": [0] * 10}, "custom": [{"id": "c1", "name": "Mi bajo"}]}
    assert api.save_player(data) == {"ok": True}
    assert api.get_player() == data


def test_a_damaged_file_is_ignored(api, tmp_path):
    os.makedirs(tmp_path / "datos")
    (tmp_path / "datos" / "player.json").write_text("{no es json", encoding="utf-8")
    assert api.get_player() == {}


def test_a_huge_or_wrong_value_is_not_saved(api):
    assert api.save_player({"queue": ["x" * 20] * 20000}) == {"ok": False}
    assert api.get_player() == {}
    assert api.save_player("no soy un diccionario") == {"ok": True}
    assert api.get_player() == {}


def test_library_list_gives_urls_and_hides_paths(api, tmp_path, monkeypatch):
    songs = tmp_path / "canciones"
    songs.mkdir()
    (songs / "Mora - Volando.mp3").write_bytes(b"x" * 100)
    monkeypatch.setattr(api, "_downloads_dir", lambda: str(songs))
    try:
        [track] = api.library_list()["tracks"]
    finally:
        api._media.stop()
    assert (track["title"], track["artist"]) == ("Volando", "Mora")
    assert track["url"].startswith("http://127.0.0.1:") and "path" not in track
    assert track["cover_url"] == ""
