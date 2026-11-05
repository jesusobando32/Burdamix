"""The songs you like and your own playlists. They only point at files (nothing is copied or moved), they are written to a small
file of their own, and they survive a file being renamed (Completar etiquetas can rename it) or deleted."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import collections_store  # noqa: E402
import const  # noqa: E402
import library  # noqa: E402
from gui import backend  # noqa: E402
from tagwriter import TagInfo  # noqa: E402


# --- the store ------------------------------------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    return collections_store.Collections(str(tmp_path / "collections.json"))


def test_a_new_store_is_empty(store):
    assert store.liked == set() and store.unliked == set() and store.playlists == []


def test_likes_survive_a_restart_and_no_half_written_file_is_left(store, tmp_path):
    store.like(str(tmp_path / "a.mp3"))
    again = collections_store.Collections(str(tmp_path / "collections.json"))
    assert again.liked == {collections_store.key(str(tmp_path / "a.mp3"))}
    assert [n for n in os.listdir(tmp_path) if n.endswith(".part")] == []


def test_a_damaged_file_is_ignored(tmp_path):
    (tmp_path / "collections.json").write_text("{no es json", encoding="utf-8")
    assert collections_store.Collections(str(tmp_path / "collections.json")).liked == set()


def test_liking_a_song_removes_the_unlike_of_it_and_unliking_remembers_it_for_the_liked_folder(store, tmp_path):
    path = str(tmp_path / "liked" / "a.mp3")
    store.unlike(path, remember=True)
    assert collections_store.key(path) in store.unliked
    store.like(path)
    assert collections_store.key(path) in store.liked and collections_store.key(path) not in store.unliked


def test_playlists_can_be_made_renamed_filled_emptied_and_deleted(store, tmp_path):
    a, b = str(tmp_path / "a.mp3"), str(tmp_path / "b.mp3")
    pid = store.playlist_create("  Para   correr ", [a])
    assert store.playlists[0]["name"] == "Para correr"
    store.playlist_add(pid, [a, b, b])                         # no song twice
    assert store.playlists[0]["paths"] == [collections_store.key(a), collections_store.key(b)]
    store.playlist_remove(pid, a)
    assert store.playlists[0]["paths"] == [collections_store.key(b)]
    store.playlist_rename(pid, "Noche")
    assert store.playlists[0]["name"] == "Noche"
    store.playlist_delete(pid)
    assert store.playlists == []


def test_a_playlist_needs_a_sensible_name(store):
    for bad in ("", "   ", "x" * 61, 5, None):
        with pytest.raises(collections_store.CollectionsError):
            store.playlist_create(bad)


def test_unknown_playlists_are_refused(store, tmp_path):
    with pytest.raises(collections_store.CollectionsError):
        store.playlist_add("no-existe", [str(tmp_path / "a.mp3")])


def test_a_renamed_file_keeps_its_likes_and_its_places_in_playlists(store, tmp_path):
    old, new, other = str(tmp_path / "old.mp3"), str(tmp_path / "new.mp3"), str(tmp_path / "other.mp3")
    store.like(old)
    store.unlike(str(tmp_path / "liked" / "x.mp3"), remember=True)
    pid = store.playlist_create("P", [other, old])
    store.renamed(old, new)
    assert collections_store.key(new) in store.liked and collections_store.key(old) not in store.liked
    assert store.playlists[0]["paths"] == [collections_store.key(other), collections_store.key(new)]
    assert pid == store.playlists[0]["id"]


def test_forgetting_files_removes_them_everywhere(store, tmp_path):
    a, b = str(tmp_path / "a.mp3"), str(tmp_path / "b.mp3")
    store.like(a)
    store.playlist_create("P", [a, b])
    store.forget([a])
    assert store.liked == set() and store.playlists[0]["paths"] == [collections_store.key(b)]


# --- through the window's Api ---------------------------------------------------------------------------------------

@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(const, "data_dir", lambda: str(tmp_path / "datos"))
    songs = tmp_path / "descargas"
    for relative in ("albums/Disco/Mora - Uno.mp3", "albums/Disco/Mora - Dos.mp3", "liked/Spotify/Mora - Uno.mp3", "liked/Spotify/Feid - Tres.mp3", "tracks/Suelta.mp3"):
        path = songs.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 100)

    def read(path):
        stem = os.path.splitext(os.path.basename(path))[0]
        artist, _, title = stem.partition(" - ")
        return TagInfo(path=path, title=title or stem, artist=artist if title else "", duration=10)
    monkeypatch.setattr(library.tagwriter, "read_tags", read)
    instance = backend.Api()
    monkeypatch.setattr(instance, "_downloads_dir", lambda: str(songs))
    instance._removed = []
    instance._trash = lambda path: (instance._removed.append(path), os.remove(path))
    instance.listing = lambda: {os.path.relpath(t["path"], str(songs)).replace(os.sep, "/"): t["id"] for t in instance._library.listing()}
    instance.library_list()
    yield instance
    instance._media.stop()


def test_the_songs_downloaded_as_liked_start_liked_and_the_others_do_not(api):
    ids = api.listing()
    liked = set(api.collections_get()["liked"])
    assert ids["liked/Spotify/Feid - Tres.mp3"] in liked
    assert ids["tracks/Suelta.mp3"] not in liked and ids["albums/Disco/Mora - Dos.mp3"] not in liked


def test_a_song_kept_as_two_files_is_liked_in_both(api):
    ids = api.listing()
    liked = set(api.collections_get()["liked"])
    assert ids["liked/Spotify/Mora - Uno.mp3"] in liked and ids["albums/Disco/Mora - Uno.mp3"] in liked      # same artist and title


def test_liking_and_unliking_a_regular_song(api):
    ids = api.listing()
    song = ids["tracks/Suelta.mp3"]
    assert api.like_toggle(song) == {"ok": True, "liked": True}
    assert song in api.collections_get()["liked"]
    assert api.like_toggle(song) == {"ok": True, "liked": False}
    assert song not in api.collections_get()["liked"]


def test_unliking_a_song_unlikes_all_its_copies_even_the_one_in_the_liked_folder(api):
    ids = api.listing()
    assert api.like_toggle(ids["albums/Disco/Mora - Uno.mp3"]) == {"ok": True, "liked": False}
    liked = set(api.collections_get()["liked"])
    assert ids["liked/Spotify/Mora - Uno.mp3"] not in liked and ids["albums/Disco/Mora - Uno.mp3"] not in liked
    assert api.like_toggle(ids["albums/Disco/Mora - Uno.mp3"]) == {"ok": True, "liked": True}            # and it can be liked again


def test_unknown_ids_are_refused(api):
    assert api.like_toggle("no-existe")["ok"] is False
    assert api.like_toggle(5)["ok"] is False


def test_playlists_through_the_api_hold_the_songs_in_order(api):
    ids = api.listing()
    made = api.playlist_create("Mi lista", [ids["tracks/Suelta.mp3"], ids["albums/Disco/Mora - Dos.mp3"]])
    assert made["ok"] is True
    got = api.collections_get()["playlists"]
    assert got == [{"id": made["id"], "name": "Mi lista", "ids": [ids["tracks/Suelta.mp3"], ids["albums/Disco/Mora - Dos.mp3"]]}]
    assert api.playlist_add(made["id"], [ids["liked/Spotify/Feid - Tres.mp3"]])["ok"] is True
    assert len(api.collections_get()["playlists"][0]["ids"]) == 3
    assert api.playlist_remove(made["id"], ids["tracks/Suelta.mp3"])["ok"] is True
    assert api.playlist_rename(made["id"], "Otra")["ok"] is True
    assert api.collections_get()["playlists"][0]["name"] == "Otra"
    assert api.playlist_delete(made["id"])["ok"] is True
    assert api.collections_get()["playlists"] == []


def test_a_bad_name_comes_back_as_a_message_not_a_crash(api):
    result = api.playlist_create("   ")
    assert result["ok"] is False and result["error"]


def test_deleting_a_song_takes_it_out_of_likes_and_playlists(api):
    ids = api.listing()
    song = ids["tracks/Suelta.mp3"]
    api.like_toggle(song)
    made = api.playlist_create("P", [song])
    api.library_delete([song])
    state = api.collections_get()
    assert song not in state["liked"] and state["playlists"][0]["ids"] == []
    assert made["ok"]


def test_renaming_a_file_with_completar_etiquetas_moves_its_like_and_its_playlist_place(api, tmp_path):
    ids = api.listing()
    song = ids["tracks/Suelta.mp3"]
    api.like_toggle(song)
    api.playlist_create("P", [song])
    old = api._library.path_of(song)
    new = os.path.join(os.path.dirname(old), "Mora - Nueva.mp3")
    os.rename(old, new)
    api._tags._on_renamed(old, new)                                    # what the tag writer calls when it renames a file
    api.library_list()
    new_id = {t["path"]: t["id"] for t in api._library.listing()}[new]
    state = api.collections_get()
    assert new_id in state["liked"] and state["playlists"][0]["ids"] == [new_id]
