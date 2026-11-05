"""Edges of likes and playlists: files that disappear without the program knowing, and files renamed twice."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import collections_store  # noqa: E402
import const  # noqa: E402
import library  # noqa: E402
from gui import backend  # noqa: E402
from tagwriter import TagInfo  # noqa: E402


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(const, "data_dir", lambda: str(tmp_path / "datos"))
    songs = tmp_path / "descargas"
    for name in ("a.mp3", "b.mp3"):
        (songs / "tracks").mkdir(parents=True, exist_ok=True)
        (songs / "tracks" / name).write_bytes(b"x" * 100)
    monkeypatch.setattr(library.tagwriter, "read_tags", lambda p: TagInfo(path=p, title=os.path.basename(p), artist="Mora", duration=10))
    instance = backend.Api()
    monkeypatch.setattr(instance, "_downloads_dir", lambda: str(songs))
    yield instance, songs
    instance._media.stop()


def test_a_file_deleted_outside_the_program_is_left_out_without_a_crash_and_comes_back_if_the_file_does(api):
    instance, songs = api
    ids = {t["title"]: t["id"] for t in instance.library_list()["tracks"]}
    made = instance.playlist_create("P", [ids["a.mp3"], ids["b.mp3"]])
    instance.like_toggle(ids["a.mp3"])
    gone = songs / "tracks" / "a.mp3"
    saved = gone.read_bytes()
    os.remove(gone)
    instance.library_list()                                              # the next scan no longer sees it
    state = instance.collections_get()
    assert state["playlists"][0]["ids"] == [ids["b.mp3"]] and ids["a.mp3"] not in state["liked"]
    gone.write_bytes(saved)                                              # restored from the Recycle Bin: it is back in both places
    instance.library_list()
    state = instance.collections_get()
    assert state["playlists"][0]["ids"] == [ids["a.mp3"], ids["b.mp3"]] and ids["a.mp3"] in state["liked"] and made["ok"]


def test_a_file_renamed_twice_keeps_its_place(tmp_path):
    store = collections_store.Collections(str(tmp_path / "c.json"))
    one, two, three = (str(tmp_path / n) for n in ("one.mp3", "two.mp3", "three.mp3"))
    store.like(one)
    store.playlist_create("P", [one])
    store.renamed(one, two)
    store.renamed(two, three)
    assert store.liked == {collections_store.key(three)} and store.playlists[0]["paths"] == [collections_store.key(three)]


def test_a_dangling_playlist_entry_does_not_break_the_playlist_api(api):
    instance, _ = api
    ids = {t["title"]: t["id"] for t in instance.library_list()["tracks"]}
    made = instance.playlist_create("P", [ids["a.mp3"]])
    instance._collections.playlist_add(made["id"], ["Z:\\no\\existe.mp3"])        # a path no scan will ever list
    assert instance.collections_get()["playlists"][0]["ids"] == [ids["a.mp3"]]
    assert instance.playlist_remove(made["id"], ids["a.mp3"])["ok"] is True
