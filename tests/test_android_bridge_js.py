"""gui/web/android.js builds window.pywebview.api inside the Android WebView. It is run with node over a fake window and a fake host."""
import json
import os
import shutil
import subprocess

import pytest

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui", "web")

HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const code = fs.readFileSync(process.argv[1], "utf8");
const events = [], sent = [];
const window = { dispatchEvent: e => events.push(e.type) };
if (process.argv[2] === "host") window.BurdamixAndroid = {
  methods: () => JSON.stringify(["hello", "boom"]),
  call: (id, name, args) => sent.push([id, name, args]),
};
class Event { constructor(type) { this.type = type; } }
vm.runInNewContext(code, { window, Event, JSON, Map, Promise, Error, String });
(async () => {
  %s
})().catch(e => { console.log("FALLO " + e.stack); process.exit(1); });
"""


def run(scenario, host=True):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = HARNESS % scenario
    done = subprocess.run([node, "-e", script, os.path.join(WEB, "android.js"), "host" if host else "none"],
                          capture_output=True, text=True, timeout=30, encoding="utf-8")
    assert done.returncode == 0, done.stdout + done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_without_the_android_host_nothing_is_installed():
    out = run("console.log(JSON.stringify({pw: typeof window.pywebview, events}));", host=False)
    assert out == {"pw": "undefined", "events": []}


def test_with_the_host_the_api_and_the_ready_event_appear():
    out = run("console.log(JSON.stringify({names: Object.keys(window.pywebview.api), events}));")
    assert out == {"names": ["hello", "boom"], "events": ["pywebviewready"]}


def test_a_call_resolves_with_the_value():
    out = run("""
      const p = window.pywebview.api.hello("Ana", 2);
      const [id, name, args] = sent[0];
      window.__burdamixReply(id, JSON.stringify({ok: true, value: {x: null}}));
      console.log(JSON.stringify({name, args: JSON.parse(args), value: await p}));""")
    assert out == {"name": "hello", "args": ["Ana", 2], "value": {"x": None}}


def test_an_error_rejects_with_name_and_message():
    out = run("""
      const p = window.pywebview.api.boom();
      window.__burdamixReply(sent[0][0], JSON.stringify({ok: false, error: {name: "ValueError", message: "mal"}}));
      try { await p; console.log(JSON.stringify("no rechazó")); }
      catch (e) { console.log(JSON.stringify({name: e.name, message: e.message})); }""")
    assert out == {"name": "ValueError", "message": "mal"}


def test_concurrent_calls_are_told_apart_and_can_finish_out_of_order():
    out = run("""
      const slow = window.pywebview.api.hello("lenta"), fast = window.pywebview.api.hello("rapida");
      const done = [];
      slow.then(v => done.push(v)); fast.then(v => done.push(v));
      window.__burdamixReply(sent[1][0], JSON.stringify({ok: true, value: "rapida"}));
      window.__burdamixReply(sent[0][0], JSON.stringify({ok: true, value: "lenta"}));
      await Promise.all([slow, fast]);
      console.log(JSON.stringify(done));""")
    assert out == ["rapida", "lenta"]


def test_a_reply_nobody_waits_for_is_ignored():
    out = run("""window.__burdamixReply("999", JSON.stringify({ok: true, value: 1})); console.log("true");""")
    assert out is True
