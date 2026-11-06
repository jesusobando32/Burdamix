"""android/app/src/main/python/burdamix_host.py is what the Android WebView calls. In the app `bridge` is gui/bridge.py copied at build time."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "gui"), os.path.join(ROOT, "android", "app", "src", "main", "python")]

import burdamix_host as host   # noqa: E402


def test_the_page_sees_the_public_methods_only():
    assert json.loads(host.methods()) == ["fail", "ping", "slow"]


def test_a_call_goes_through_the_bridge():
    assert json.loads(host.call("ping", json.dumps(["x"]))) == {"ok": True, "value": {"eco": "x"}}
    assert json.loads(host.call("fail", "[]"))["error"]["name"] == "RuntimeError"
