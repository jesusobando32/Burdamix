import contextlib
import getpass
import multiprocessing
import os
import shutil
import socket
import sys
import threading
import time
import webbrowser

import requests
import tekore as tk
from flask import Flask, request, redirect

from const import colours

auths = {}  # Auth attempts. Stores data across spotify login

def _config_dir():
    """Private folder of the user, outside the project: it is not inside Documents (so OneDrive does not
    sync it) and it is not included when the project folder is zipped to share it."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "Burdamix")


cfg_filename = os.path.join(_config_dir(), 'tekore_cfg.ini')
# Where older versions kept it: next to the code.
legacy_cfg_filename = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tekore_cfg.ini')
app_host = "127.0.0.1"
app_port = 5000
app_url = f'http://{app_host}:{app_port}'
login_redirect_url = f'{app_url}/callback'
dashboard_url = "https://developer.spotify.com/dashboard"

LOGIN_TIMEOUT_SECONDS = 180

# The least Spotify needs to let us read your playlists and liked songs.
login_scope = tk.Scope('playlist-read-private', 'playlist-read-collaborative', 'user-library-read')

client_prompt = f"""
{colours.HEADER}=== Configuración de Spotify (solo se hace una vez) ==={colours.ENDC}
{colours.FAIL}IMPORTANTE:{colours.ENDC} aquí NUNCA se te pide tu usuario ni tu contraseña de Spotify.

Spotify exige que cada persona cree su propia "app" gratuita; es lo que permite que este
programa lea tus playlists. Sigue estos pasos:

{colours.OKBLUE}1.{colours.ENDC} Entra a {colours.OKCYAN}{dashboard_url}{colours.ENDC} e inicia sesión con tu cuenta de Spotify.
{colours.OKBLUE}2.{colours.ENDC} Pulsa {colours.BOLD}Create app{colours.ENDC}.
{colours.OKBLUE}3.{colours.ENDC} Nombre y descripción: lo que quieras (por ejemplo "Burdamix").
{colours.OKBLUE}4.{colours.ENDC} En {colours.BOLD}Redirect URI{colours.ENDC} copia EXACTAMENTE esto y pulsa "Add":
       {colours.OKCYAN}{login_redirect_url}{colours.ENDC}
{colours.OKBLUE}5.{colours.ENDC} En "Which API/SDKs are you planning to use?" marca {colours.BOLD}Web API{colours.ENDC}.
{colours.OKBLUE}6.{colours.ENDC} Acepta los términos y pulsa {colours.BOLD}Save{colours.ENDC}.
{colours.OKBLUE}7.{colours.ENDC} Abre tu app nueva > {colours.BOLD}Settings{colours.ENDC}. Ahí verás el {colours.BOLD}Client ID{colours.ENDC} y, con "View client secret",
   el {colours.BOLD}Client secret{colours.ENDC}. Los vas a pegar a continuación.

(Spotify puede exigir que la cuenta sea Premium para apps nuevas en modo desarrollo.)
"""

permission_prompt = f"""
{colours.HEADER}=== Iniciar sesión en Spotify ==={colours.ENDC}
Spotify solo entrega el contenido de las playlists a quien inició sesión, y solo las que son TUYAS.
Se abrirá el navegador: elige tu cuenta y pulsa {colours.BOLD}Aceptar / Agree{colours.ENDC}.
Tienes {LOGIN_TIMEOUT_SECONDS // 60} minutos para hacerlo.

Pulsa {colours.OKGREEN}Enter{colours.ENDC} para continuar"""


# Token in the context of a user, can access user resources such as liked songs
def get_user_token():
    migrate_legacy_config()
    (spotifyClientId, spotifyClientSecret, spotifyReturnUri,
        refreshToken) = tk.config_from_file(cfg_filename, return_refresh=True)
    cred = tk.Credentials(
        spotifyClientId, spotifyClientSecret, spotifyReturnUri)

    if refreshToken is None or refreshToken == '':
        raise ValueError('RefreshToken not available in tekore config file')

    return cred.refresh_user_token(refreshToken)


def _request_client_token(client_id, client_secret):
    return tk.request_client_token(client_id, client_secret).access_token


# Token for the app itself (no user). Enough for single tracks and albums.
def get_client_token():
    migrate_legacy_config()
    if not is_client_configured():
        do_client_login()

    (spotifyClientId, spotifyClientSecret, _) = tk.config_from_file(cfg_filename, return_refresh=False)
    return _request_client_token(spotifyClientId, spotifyClientSecret)


def is_user_logged_in():
    if not does_config_exist():
        return False

    (spotifyClientId, spotifyClientSecret, spotifyReturnUri, refreshToken) = tk.config_from_file(cfg_filename, return_refresh=True)
    return spotifyClientId is not None and spotifyClientSecret is not None and spotifyReturnUri is not None and bool(refreshToken)


def is_client_configured():
    if not does_config_exist():
        return False

    (spotifyClientId, spotifyClientSecret, spotifyReturnUri) = tk.config_from_file(cfg_filename, return_refresh=False)
    return spotifyClientId is not None and spotifyClientSecret is not None and spotifyReturnUri is not None


def migrate_legacy_config():
    """Move the config an older version left next to the code into the private folder.

    Copies, checks the copy, and only then deletes the original, so a failure can never lose it."""
    if os.path.exists(cfg_filename) or not os.path.exists(legacy_cfg_filename):
        return
    partial = cfg_filename + ".tmp"
    try:
        os.makedirs(os.path.dirname(cfg_filename), exist_ok=True)
        shutil.copy2(legacy_cfg_filename, partial)
        with open(legacy_cfg_filename, "rb") as old, open(partial, "rb") as copy:
            identical = old.read() == copy.read()
        if not identical:
            os.remove(partial)
            return
        os.replace(partial, cfg_filename)       # the new file only ever appears complete and verified
        os.remove(legacy_cfg_filename)
        _restrict_permissions()
        print(f"{colours.OKBLUE}[i] Tu configuración de Spotify ahora se guarda en una carpeta privada: {os.path.dirname(cfg_filename)}{colours.ENDC}")
    except OSError:
        pass   # keep using whatever is there; the original is only deleted after everything above worked


def _restrict_permissions():
    with contextlib.suppress(OSError):
        os.chmod(cfg_filename, 0o600)   # owner only (no effect on Windows, whose folder already is per-user)


def _write_config(values):
    os.makedirs(os.path.dirname(cfg_filename), exist_ok=True)
    tk.config_to_file(cfg_filename, values)
    _restrict_permissions()


def does_config_exist():
    migrate_legacy_config()
    return os.path.exists(cfg_filename)


def _port_in_use():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((app_host, app_port)) == 0


def do_user_login():
    """Open the browser so the user can allow the app to read their playlists. Exits the program on failure."""
    if not is_client_configured():
        do_client_login()

    if _port_in_use():
        print(f"\n{colours.FAIL}El puerto {app_port} está ocupado por otro programa.{colours.ENDC} Ciérralo e inténtalo de nuevo.")
        sys.exit(1)

    input(permission_prompt)

    threading.Timer(1.25, lambda: webbrowser.open(app_url)).start()

    flask_process = multiprocessing.Process(target=start_flask)
    flask_process.start()

    deadline = time.time() + LOGIN_TIMEOUT_SECONDS
    while flask_process.is_alive() and time.time() < deadline:
        time.sleep(1)

    if flask_process.is_alive():
        flask_process.terminate()
        print(f"\n{colours.FAIL}Se acabó el tiempo sin completar el inicio de sesión.{colours.ENDC} Vuelve a ejecutar el programa.")
        sys.exit(1)

    if flask_process.exitcode != 0:
        print(f"\n{colours.FAIL}No se dio el permiso en Spotify.{colours.ENDC} Vuelve a ejecutar el programa y pulsa Aceptar.")
        sys.exit(1)

    try:
        access_token = get_user_token().access_token
        me = requests.get('https://api.spotify.com/v1/me', headers={'Authorization': f'Bearer {access_token}'}, timeout=20)
        me.raise_for_status()
        print(f"\n{colours.OKGREEN}Listo.{colours.ENDC} Sesión iniciada como {me.json().get('display_name') or me.json().get('id')}.\n")
    except Exception as e:
        print(f"\n{colours.FAIL}El inicio de sesión no quedó bien.{colours.ENDC} Vuelve a intentarlo. ({type(e).__name__}: {e})")
        sys.exit(1)


def do_client_login():
    """Guide the user through creating a Spotify app and store its Client ID / Secret (checked before saving)."""
    print(client_prompt)

    input(f"Pulsa {colours.OKGREEN}Enter{colours.ENDC} y se abrirá esa página en tu navegador (o ábrela tú): ")
    webbrowser.open(dashboard_url)

    while True:
        client_id = input(f"\n{colours.OKGREEN}Pega el Client ID{colours.ENDC}: ").strip()
        client_secret = getpass.getpass(f"{colours.OKGREEN}Pega el Client secret{colours.ENDC} (no se ve al pegar, es normal): ").strip()

        if not client_id or not client_secret:
            print(f"{colours.WARNING}Los dos datos son obligatorios.{colours.ENDC}")
            continue

        try:
            _request_client_token(client_id, client_secret)
            break
        except Exception:
            print(f"{colours.FAIL}Spotify no aceptó esos datos.{colours.ENDC} Revisa que copiaste el Client ID y el Client secret completos, sin espacios.")

    # tekore keeps the old refresh token when it is given None, and that token belongs to the previous
    # Spotify app: it would fail with the new credentials forever. Start from an empty file instead,
    # so the next playlist asks you to log in again.
    if os.path.exists(cfg_filename):
        os.remove(cfg_filename)
    _write_config((client_id, client_secret, login_redirect_url, None))
    print(f'{colours.OKGREEN}Guardado.{colours.ENDC} No tendrás que repetir esto. (Se guarda en una carpeta privada: {os.path.dirname(cfg_filename)})')


def start_flask():
    flask_app = app_factory()
    flask_app.run(app_host, app_port)


def stop_flask(exit_code=0):
    os._exit(exit_code)  # the parent reads this code to know whether the login worked


def app_factory() -> Flask:
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.urandom(24).hex()

    @app.route('/', methods=['GET'])
    def main():
        (spotifyClientId, spotifyClientSecret, spotifyReturnUri) = tk.config_from_file(cfg_filename, return_refresh=False)
        cred = tk.Credentials(spotifyClientId, spotifyClientSecret, spotifyReturnUri)

        auth = tk.UserAuth(cred, login_scope)
        auths[auth.state] = auth
        return redirect(auth.url, 307)

    @app.route('/callback', methods=['GET'])
    def login_callback():
        code = request.args.get('code', None)
        state = request.args.get('state', None)
        auth = auths.pop(state, None)

        if request.args.get('error') or not code:
            threading.Timer(2, stop_flask, args=(2,)).start()
            return '<h1>Permission denied</h1><p>You can close this window and run the program again.</p>', 400

        if auth is None:
            return 'Invalid login state!', 400

        userToken = auth.request_token(code, state)

        # Store refresh token
        new_conf = (None, None, None, userToken.refresh_token)
        _write_config(new_conf)

        return redirect('/complete')

    @app.route('/complete', methods=['GET'])
    def login_complete():
        threading.Timer(3, stop_flask).start()  # wait long enough to return the html

        return """
        <h1>Login complete!</h1>
        <br>
        <h4>Close this window to return to the application</h4>
        <script>window.close()</script>
        """

    return app
