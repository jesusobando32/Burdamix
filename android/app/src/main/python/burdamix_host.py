"""What the Android WebView talks to. MainActivity calls `methods()` once and `call(name, args_json)` for every call of the page;
both go through bridge.py (copied from gui/bridge.py at build time), the same rules as the desktop window.

For now the Api is a small probe, only to prove the transport (a value, an error, a slow call next to a fast one). The real
`gui.backend.Api` replaces it in the next stage.
"""
import time

import bridge

HIDDEN = ("attach_window",)


class ProbeApi:
    def ping(self, text="ping"):
        return {"eco": text}

    def fail(self):
        raise RuntimeError("fallo a propósito")

    def slow(self, seconds=3):
        time.sleep(seconds)
        return "lenta"


_api = ProbeApi()


def methods():
    """The names the page may call, as JSON text."""
    import json
    return json.dumps(bridge.methods(_api, HIDDEN))


def call(name, args_json):
    return bridge.call(_api, name, args_json, HIDDEN)
