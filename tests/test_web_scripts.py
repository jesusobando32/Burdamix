import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui", "web")
SCRIPTS = ("fx.js", "tags.js", "player.js", "app.js")      # loaded by index.html into one global scope
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
