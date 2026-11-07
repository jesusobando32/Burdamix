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
