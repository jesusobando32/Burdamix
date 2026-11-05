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


def test_a_file_that_cannot_be_read_is_set_aside_not_overwritten(tmp_path):
    path = tmp_path / "collections.json"
    path.write_text("{playlists: lo que había", encoding="utf-8")
    store = collections_store.Collections(str(path))
    assert store.playlists == []
    store.like(str(tmp_path / "a.mp3"))                                    # the next save must not destroy the old text
    assert (tmp_path / "collections.json.bad").read_text(encoding="utf-8") == "{playlists: lo que había"
    assert collections_store.Collections(str(path)).liked == store.liked


def test_a_file_that_is_not_there_yet_leaves_no_bad_copy(tmp_path):
    collections_store.Collections(str(tmp_path / "collections.json"))
    assert not (tmp_path / "collections.json.bad").exists()


def test_renaming_onto_a_name_already_in_the_playlist_does_not_repeat_it(tmp_path):
    store = collections_store.Collections(str(tmp_path / "c.json"))
    one, two = str(tmp_path / "one.mp3"), str(tmp_path / "two.mp3")
    store.playlist_create("P", [one, two])
    store.renamed(one, two)
    assert store.playlists[0]["paths"] == [collections_store.key(two)]


def test_the_snapshot_is_a_copy(tmp_path):
    store = collections_store.Collections(str(tmp_path / "c.json"))
    store.playlist_create("P", [str(tmp_path / "a.mp3")])
    liked, unliked, playlists = store.snapshot()
    playlists[0]["paths"].clear()
    assert len(store.playlists[0]["paths"]) == 1


def test_inside_means_under_the_folder_even_for_a_drive_root(tmp_path):
    songs = tmp_path / "descargas"
    songs.mkdir()
    assert backend._is_inside(str(songs), str(songs / "tracks" / "a.mp3"))
    assert not backend._is_inside(str(songs), str(tmp_path / "otra" / "a.mp3"))
    assert not backend._is_inside(str(songs), str(songs))                       # the folder itself is not a song
    assert not backend._is_inside(str(songs), str(tmp_path / "descargas-2" / "a.mp3"))   # a name that merely starts the same
    root = os.path.splitdrive(str(tmp_path))[0] + os.sep
    assert backend._is_inside(root, str(tmp_path / "a.mp3"))                    # a root such as D:\ works too


def test_a_song_deleted_while_a_scan_is_running_does_not_come_back_from_that_scan(tmp_path, monkeypatch):
    path = tmp_path / "tracks" / "a.mp3"
    path.parent.mkdir()
    path.write_bytes(b"x" * 100)
    lib = library.Library()

    def read(p):
        lib.forget(p)                                                      # deleted at the very moment the scan reads it
        return TagInfo(path=p, title="A", artist="B", duration=10)
    monkeypatch.setattr(library.tagwriter, "read_tags", read)
    assert lib.scan(str(tmp_path)) == [] and lib.path_of(library.Library._id(str(path))) is None and lib.listing() == []
    monkeypatch.setattr(library.tagwriter, "read_tags", lambda p: TagInfo(path=p, title="A", artist="B", duration=10))
    assert len(lib.scan(str(tmp_path))) == 1                               # a later scan lists it again (restored from the bin)


def test_a_file_locked_for_a_moment_is_never_overwritten_by_the_session(tmp_path, monkeypatch):
    """An antivirus holding collections.json at start-up must not make the program begin empty and then write over the good file."""
    path = tmp_path / "collections.json"
    good = '{"liked": [], "unliked": [], "playlists": [{"id": "x", "name": "Mis cosas", "paths": []}]}'
    path.write_text(good, encoding="utf-8")
    real_open = open

    def locked(file, *args, **kwargs):
        if str(file) == str(path) and "w" not in (args[0] if args else kwargs.get("mode", "r")):
            raise PermissionError("en uso por otro proceso")
        return real_open(file, *args, **kwargs)
    monkeypatch.setattr("builtins.open", locked)
    store = collections_store.Collections(str(path))
    monkeypatch.undo()
    store.like(str(tmp_path / "a.mp3"))
    store.playlist_create("Otra")
    assert path.read_text(encoding="utf-8") == good and not (tmp_path / "collections.json.bad").exists()
