"""The Android app packages the program's Python by the rules of android/app/build.gradle.kts. A module that is left out but that a packaged
one imports (even lazily, inside a function) only fails on the phone, when that line runs: "No module named 'spotify2mp3'"."""
import ast
import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def excluded_files():
    with open(os.path.join(ROOT, "android", "app", "build.gradle.kts"), encoding="utf-8") as f:
        text = f.read()
    block = re.search(r"exclude\(([^)]*)\)", text).group(1)
    return set(re.findall(r'"([^"]+)"', block))


def packaged_files():
    names = glob.glob(os.path.join(ROOT, "*.py")) + glob.glob(os.path.join(ROOT, "apis", "*.py")) + glob.glob(os.path.join(ROOT, "gui", "*.py"))
    skip = excluded_files()
    return [p for p in names if os.path.relpath(p, ROOT).replace("\\", "/") not in skip]


def imported_modules(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


def test_no_packaged_module_imports_one_that_is_left_out():
    skip = excluded_files()
    left_out = {os.path.splitext(name)[0].replace("/", ".") for name in skip if name.endswith(".py")}
    problems = []
    for path in packaged_files():
        for module in imported_modules(path):
            if module in left_out:
                problems.append(f"{os.path.relpath(path, ROOT)} imports {module}")
    assert problems == []
