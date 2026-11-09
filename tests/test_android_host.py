"""android/app/src/main/python/burdamix_host.py is what the Android WebView calls. In the app `bridge` is gui/bridge.py copied at build time.
`start` needs the phone; here a small Api stands in for gui.backend.Api."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "gui"), os.path.join(ROOT, "android", "app", "src", "main", "python")]

import burdamix_host as host   # noqa: E402


class FakeApi:
    def ping(self, text="ping"):
        return {"eco": text}

    def fail(self):
        raise RuntimeError("fallo")

    def attach_window(self, window):
        return "no"


def test_the_page_sees_the_public_methods_only(monkeypatch):
    monkeypatch.setattr(host, "_api", FakeApi())
    assert json.loads(host.methods()) == ["fail", "ping"]


def test_a_call_goes_through_the_bridge(monkeypatch):
    monkeypatch.setattr(host, "_api", FakeApi())
    assert json.loads(host.call("ping", json.dumps(["x"]))) == {"ok": True, "value": {"eco": "x"}}
    assert json.loads(host.call("fail", "[]"))["error"]["name"] == "RuntimeError"
    assert json.loads(host.call("attach_window", "[1]"))["ok"] is False


def test_the_service_that_keeps_the_app_alive_asks_whether_anything_is_still_running(monkeypatch):
    class Tags:
        _busy = False

    class Api(FakeApi):
        _busy = False

        def __init__(self):
            self._tags = Tags()

    api = Api()
    monkeypatch.setattr(host, "_api", api)
    assert host.busy() is False
    api._busy = True                       # a download
    assert host.busy() is True
    api._busy, api._tags._busy = False, True    # tag jobs
    assert host.busy() is True
    monkeypatch.setattr(host, "_api", None)     # before start(): nothing runs
    assert host.busy() is False


def test_the_service_may_not_know_the_tag_jobs(monkeypatch):
    monkeypatch.setattr(host, "_api", FakeApi())     # an Api without _busy at all
    assert host.busy() is False


def _song(folder, *parts, text="a"):
    path = os.path.join(folder, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    return path


def test_the_songs_move_to_the_public_music_folder_and_their_likes_and_playlists_follow(tmp_path):
    old, new = str(tmp_path / "private"), str(tmp_path / "Music" / "Burdamix")
    a = _song(old, "tracks", "A - uno.mp3")
    b = _song(old, "albums", "X - Y", "01 dos.mp3")
    moved = []
    count = host.migrate_music(old, new, lambda was, now: moved.append((was, now)))
    assert count == 2
    assert os.path.isfile(os.path.join(new, "tracks", "A - uno.mp3")) and os.path.isfile(os.path.join(new, "albums", "X - Y", "01 dos.mp3"))
    assert not os.path.exists(a) and not os.path.exists(b)
    assert sorted(moved) == sorted([(a, os.path.join(new, "tracks", "A - uno.mp3")), (b, os.path.join(new, "albums", "X - Y", "01 dos.mp3"))])
    assert not os.path.exists(os.path.join(old, "albums"))         # the empty folders left behind go away


def test_a_song_that_is_already_in_the_new_folder_is_never_overwritten(tmp_path):
    old, new = str(tmp_path / "private"), str(tmp_path / "Music" / "Burdamix")
    _song(old, "tracks", "A.mp3", text="viejo")
    keep = _song(new, "tracks", "A.mp3", text="nuevo")
    assert host.migrate_music(old, new, None) == 0
    assert open(keep).read() == "nuevo"
    assert os.path.isfile(os.path.join(old, "tracks", "A.mp3"))     # nothing is lost


def test_moving_to_the_same_folder_or_from_a_missing_one_does_nothing(tmp_path):
    folder = str(tmp_path / "Burdamix")
    _song(folder, "tracks", "A.mp3")
    assert host.migrate_music(folder, folder, None) == 0
    assert host.migrate_music(str(tmp_path / "nada"), folder, None) == 0
    assert os.path.isfile(os.path.join(folder, "tracks", "A.mp3"))
