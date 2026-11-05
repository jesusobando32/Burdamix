"""Deleting songs from the library sends them to the Recycle Bin. The real Windows call is never made here: the Api takes the
function that does it, so the tests give it a stand-in that only records (or removes a file in a temporary folder)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import const  # noqa: E402
import trash  # noqa: E402
from gui import backend  # noqa: E402


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(const, "data_dir", lambda: str(tmp_path / "datos"))
    songs = tmp_path / "descargas"
    (songs / "albums" / "Disco").mkdir(parents=True)
    for name in ("Mora - Uno.mp3", "Mora - Dos.mp3"):
        (songs / "albums" / "Disco" / name).write_bytes(b"x" * 100)
    instance = backend.Api()
    monkeypatch.setattr(instance, "_downloads_dir", lambda: str(songs))
    instance._removed = []

    def fake_trash(path):
        instance._removed.append(path)
        os.remove(path)
    instance._trash = fake_trash
    yield instance
    instance._media.stop()


def ids_by_title(api):
    return {t["title"]: t["id"] for t in api.library_list()["tracks"]}


def test_a_song_goes_to_the_bin_and_leaves_the_library(api):
    ids = ids_by_title(api)
    result = api.library_delete([ids["Uno"]])
    assert result == {"ok": True, "deleted": 1, "failed": []}
    assert [os.path.basename(p) for p in api._removed] == ["Mora - Uno.mp3"]
    assert sorted(ids_by_title(api)) == ["Dos"]


def test_several_songs_at_once_and_ids_that_are_not_in_the_library_are_ignored(api):
    ids = ids_by_title(api)
    result = api.library_delete([ids["Uno"], ids["Dos"], "no-existe", 7])
    assert result["deleted"] == 2 and result["failed"] == []
    assert api.library_list()["tracks"] == []


def test_a_file_outside_the_downloads_folder_is_never_touched(api, tmp_path, monkeypatch):
    ids = ids_by_title(api)
    monkeypatch.setattr(api, "_downloads_dir", lambda: str(tmp_path / "otra-carpeta"))      # the folder changed after the scan
    result = api.library_delete([ids["Uno"]])
    assert result["deleted"] == 0 and len(result["failed"]) == 1 and api._removed == []


def test_a_song_the_bin_refuses_is_reported_and_the_others_still_go(api):
    ids = ids_by_title(api)
    real = api._trash

    def picky(path):
        if "Uno" in path:
            raise trash.TrashError("El archivo está en uso.")
        real(path)
    api._trash = picky
    result = api.library_delete([ids["Uno"], ids["Dos"]])
    assert result["deleted"] == 1
    assert result["failed"] == [{"id": ids["Uno"], "error": "El archivo está en uso."}]
    assert sorted(ids_by_title(api)) == ["Uno"]


def test_nothing_is_asked_when_the_list_is_not_a_list(api):
    assert api.library_delete("no es una lista") == {"ok": True, "deleted": 0, "failed": []}


def test_outside_windows_the_real_function_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(trash.sys, "platform", "linux")
    with pytest.raises(trash.TrashError):
        trash.move_to_recycle_bin(str(tmp_path / "a.mp3"))


def test_a_relative_or_missing_path_is_refused_before_asking_windows(tmp_path):
    with pytest.raises(trash.TrashError):
        trash.move_to_recycle_bin("a.mp3")
    with pytest.raises(trash.TrashError):
        trash.move_to_recycle_bin(str(tmp_path / "no-existe.mp3"))
