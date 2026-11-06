"""Where multiprocessing does not exist (Android) the Spotify login server runs in a thread; the flow reads the same things
from it as from a child process: is it alive, how did it end."""
import os
import socket
import sys
import threading
import time
import urllib.request

import pytest
from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import login  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def tiny_app(monkeypatch):
    app = Flask("tiny")

    @app.route("/")
    def home():
        return "hola"

    @app.route("/ok")
    def ok():
        threading.Timer(0.2, login.stop_flask).start()
        return "bien"

    @app.route("/no")
    def no():
        threading.Timer(0.2, login.stop_flask, args=(2,)).start()
        return "mal"
    port = free_port()
    monkeypatch.setattr(login, "app_port", port)
    monkeypatch.setattr(login, "app_url", f"http://127.0.0.1:{port}")
    monkeypatch.setattr(login, "app_factory", lambda: app)
    monkeypatch.setattr(login, "USE_THREAD_SERVER", True)
    return port


def wait_until(condition, seconds=5):
    end = time.time() + seconds
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.05)
    return False


def test_the_thread_server_answers_and_can_be_stopped(tiny_app):
    server = login._new_server()
    server.start()
    assert wait_until(lambda: login._port_in_use())
    assert urllib.request.urlopen(f"http://127.0.0.1:{tiny_app}/").read() == b"hola"
    assert server.is_alive()
    server.terminate()
    assert wait_until(lambda: not server.is_alive())


def test_stop_flask_ends_the_thread_server_with_its_code(tiny_app):
    server = login._new_server()
    server.start()
    assert wait_until(lambda: login._port_in_use())
    urllib.request.urlopen(f"http://127.0.0.1:{tiny_app}/no").read()
    assert wait_until(lambda: not server.is_alive())
    assert server.exitcode == 2


def test_the_login_flow_succeeds_when_the_server_ends_with_zero(tiny_app, monkeypatch):
    monkeypatch.setattr(login, "is_client_configured", lambda: True)
    monkeypatch.setattr(login, "get_user_token", lambda: type("T", (), {"access_token": "t"})())

    class Me:
        def raise_for_status(self): pass
        def json(self): return {"display_name": "Ana"}
    monkeypatch.setattr(login.requests, "get", lambda *a, **k: Me())
    opened = []

    def open_browser(url):
        opened.append(url)
        urllib.request.urlopen(f"http://127.0.0.1:{tiny_app}/ok").read()
    assert login.run_user_login_flow(open_browser=open_browser) == (True, "Ana")
    assert opened == [f"http://127.0.0.1:{tiny_app}"]


def test_the_login_flow_reports_a_denied_permission(tiny_app, monkeypatch):
    monkeypatch.setattr(login, "is_client_configured", lambda: True)
    ok, message = login.run_user_login_flow(open_browser=lambda url: urllib.request.urlopen(f"http://127.0.0.1:{tiny_app}/no").read())
    assert ok is False and "permiso" in message
