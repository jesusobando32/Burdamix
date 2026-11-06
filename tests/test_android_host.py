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
