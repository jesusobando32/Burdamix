"""The library groups songs by where they are in the downloads folder: albums/<album>/, playlists/<playlist>/, liked/, tracks/.
A group is only a way of looking at the files: nothing is moved or copied."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import library  # noqa: E402
from tagwriter import TagInfo  # noqa: E402


def make(folder, relative):
    path = os.path.join(folder, *relative.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * 100)
    return path


def kinds(tmp_path):
    return {t["path"][len(str(tmp_path)) + 1:].replace(os.sep, "/"): (t["kind"], t["group"]) for t in library.Library().scan(str(tmp_path))}


def test_each_folder_of_the_downloads_tells_what_a_song_is(tmp_path, monkeypatch):
    monkeypatch.setattr(library.tagwriter, "read_tags", lambda p: TagInfo(path=p, title="T", artist="A"))
    for name in ("albums/Disco Uno/1.mp3", "albums/Disco Dos/2.mp3", "playlists/Rock/3.mp3", "liked/Spotify/4.mp3", "tracks/5.mp3", "otra/6.mp3", "7.mp3"):
        make(str(tmp_path), name)
    assert kinds(tmp_path) == {
        "albums/Disco Uno/1.mp3": ("album", "Disco Uno"), "albums/Disco Dos/2.mp3": ("album", "Disco Dos"),
        "playlists/Rock/3.mp3": ("playlist", "Rock"), "liked/Spotify/4.mp3": ("liked", ""),
        "tracks/5.mp3": ("track", ""), "otra/6.mp3": ("other", "otra"), "7.mp3": ("other", ""),
    }


def test_the_names_of_the_folders_do_not_depend_on_capitals(tmp_path, monkeypatch):
    monkeypatch.setattr(library.tagwriter, "read_tags", lambda p: TagInfo(path=p, title="T", artist="A"))
    make(str(tmp_path), "Albums/Disco/1.mp3")
    assert kinds(tmp_path) == {"Albums/Disco/1.mp3": ("album", "Disco")}


def test_a_file_directly_in_albums_is_not_an_album(tmp_path, monkeypatch):
    monkeypatch.setattr(library.tagwriter, "read_tags", lambda p: TagInfo(path=p, title="T", artist="A"))
    make(str(tmp_path), "albums/suelta.mp3")
    assert kinds(tmp_path) == {"albums/suelta.mp3": ("other", "")}


def test_the_track_number_comes_with_each_song_to_order_an_album(tmp_path, monkeypatch):
    make(str(tmp_path), "albums/D/a.mp3")
    monkeypatch.setattr(library.tagwriter, "read_tags", lambda p: TagInfo(path=p, title="T", artist="A", track=7, disc=2))
    [track] = library.Library().scan(str(tmp_path))
    assert (track["number"], track["disc"]) == (7, 2)


def test_the_group_follows_the_folder_even_when_the_scan_comes_from_the_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(library.tagwriter, "read_tags", lambda p: TagInfo(path=p, title="T", artist="A"))
    make(str(tmp_path), "albums/Disco/1.mp3")
    lib = library.Library()
    first = lib.scan(str(tmp_path))
    second = lib.scan(str(tmp_path))
    assert first[0]["kind"] == second[0]["kind"] == "album" and first[0]["group"] == second[0]["group"] == "Disco"
