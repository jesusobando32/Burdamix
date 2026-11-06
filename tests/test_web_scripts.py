import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui", "web")
SCRIPTS = ("fx.js", "tags.js", "player.js", "crate.js", "lyrics.js", "sleep.js", "stats.js", "smart.js", "app.js")      # loaded by index.html into one global scope
TOP_LEVEL = re.compile(r"^(?:async function|function|const|let|var) ([A-Za-z_$][\w$]*)", re.M)


def top_level_names(text):
    return TOP_LEVEL.findall(text)


def repeated_names(sources):
    """Names that two or more scripts declare at the top level: the later script silently replaces the earlier one."""
    seen, repeated = {}, {}
    for script, text in sources.items():
        for name in top_level_names(text):
            if name in seen and seen[name] != script:
                repeated.setdefault(name, {seen[name]}).add(script)
            seen.setdefault(name, script)
    return repeated


def test_the_scripts_of_the_window_share_no_top_level_name():
    sources = {}
    for script in SCRIPTS:
        with open(os.path.join(WEB, script), encoding="utf-8") as f:
            sources[script] = f.read()
    assert repeated_names(sources) == {}


def test_a_repeated_name_is_detected():
    """The bug this guards against: tags.js and app.js both declared cardHTML, so the tag cards were drawn as album cards."""
    found = repeated_names({"tags.js": "function cardHTML(f) {}\n", "app.js": "function cardHTML(card) {}\n"})
    assert found == {"cardHTML": {"tags.js", "app.js"}}


def test_the_window_and_the_program_side_agree_on_what_is_the_same_song():
    """Both sides must write a name the same way (accents, capitals, symbols), or a liked song would be liked on one side only:
    crate.js `norm` and apis.youtube `normalize` are run over the same names."""
    import json
    import shutil
    import subprocess

    import pytest

    from apis.youtube import normalize
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    with open(os.path.join(WEB, "crate.js"), encoding="utf-8") as f:
        line = next(l for l in f.read().splitlines() if l.startswith("const norm = "))
    names = ["Tití Me Preguntó", "Chino & Nacho", "  Mucho   espacio  ", "ÁÉÍÓÚ ñandú", "AC/DC - Back In Black", "¿Qué pasó?", "100% Cumbia", "Beyoncé", "", "ǅ ﬁn ² ①", "日本語 mix", "Sin título.mp3"]
    script = line + "\nconsole.log(JSON.stringify(%s.map(norm)));" % json.dumps(names, ensure_ascii=True)
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == [normalize(n) for n in names]
