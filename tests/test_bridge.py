import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui import bridge


class Probe:
    value = 3                      # not a method: never exposed

    def hello(self, name, punct="!"):
        return {"saludo": f"Hola {name}{punct}"}

    def nothing(self):
        return None

    def boom(self):
        raise ValueError("se rompió")

    def odd(self):
        return {1, 2}              # a set is not JSON

    def _private(self):
        return "no"

    def attach_window(self, window):
        return "no"


def test_methods_are_the_public_callables_without_the_hidden_ones():
    assert bridge.methods(Probe(), hidden=("attach_window",)) == ["boom", "hello", "nothing", "odd"]


def test_a_call_returns_its_value_in_an_envelope():
    answer = json.loads(bridge.call(Probe(), "hello", json.dumps(["Ana"])))
    assert answer == {"ok": True, "value": {"saludo": "Hola Ana!"}}


def test_none_travels_as_null():
    assert json.loads(bridge.call(Probe(), "nothing", "[]")) == {"ok": True, "value": None}


def test_an_exception_becomes_an_error_envelope():
    answer = json.loads(bridge.call(Probe(), "boom", "[]"))
    assert answer == {"ok": False, "error": {"name": "ValueError", "message": "se rompió"}}


def test_unknown_private_and_non_callable_names_are_refused():
    for name in ("nope", "_private", "__class__", "value"):
        answer = json.loads(bridge.call(Probe(), name, "[]"))
        assert answer["ok"] is False and answer["error"]["name"] == "AttributeError", name


def test_hidden_names_are_refused_too():
    answer = json.loads(bridge.call(Probe(), "attach_window", "[1]", hidden=("attach_window",)))
    assert answer["ok"] is False


def test_a_value_that_is_not_json_is_an_error_not_a_crash():
    answer = json.loads(bridge.call(Probe(), "odd", "[]"))
    assert answer["ok"] is False and answer["error"]["name"] == "TypeError"


def test_bad_arguments_are_an_error_envelope():
    for raw in ("no es json", '{"a": 1}', json.dumps([1, 2, 3])):
        answer = json.loads(bridge.call(Probe(), "hello", raw))
        assert answer["ok"] is False, raw
