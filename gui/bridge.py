"""The transport between a web page and the program's `Api`, for hosts that are not pywebview (the Android WebView).

It keeps pywebview's rules, so `gui/web` runs unchanged: only the public methods of the Api are reachable (a leading underscore hides
one), a call returns a JSON value (`None` becomes null) and an exception reaches the page as a rejected promise with a name and a
message. No Android code here: the host hands in the Api, the method name and the arguments as JSON text, and gets JSON text back.
"""
import inspect
import json


def methods(api, hidden=()):
    """The names the page may call, sorted."""
    return sorted(name for name, member in inspect.getmembers(api, callable)
                  if not name.startswith("_") and name not in hidden)


def _error(error):
    return json.dumps({"ok": False, "error": {"name": type(error).__name__, "message": str(error)}})


def call(api, name, args_json, hidden=()):
    """Runs `api.<name>(*args)` and returns the envelope as JSON text: {"ok": true, "value": ...} or {"ok": false, "error": {...}}.
    Never raises: whatever goes wrong is an answer for the page."""
    try:
        if name not in methods(api, hidden):
            raise AttributeError(f"El programa no tiene la función «{name}».")
        args = json.loads(args_json)
        if not isinstance(args, list):
            raise TypeError("Los argumentos deben ser una lista.")
        return json.dumps({"ok": True, "value": getattr(api, name)(*args)})
    except Exception as error:   # every failure goes back to the page as a rejected promise
        return _error(error)
