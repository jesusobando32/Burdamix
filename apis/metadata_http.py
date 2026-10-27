"""One small HTTP client for the free metadata services (MusicBrainz, Cover Art Archive, Deezer, iTunes).

Every service gets its own rate limiter (they all ask for it) and its failures become messages the user can read."""
import threading
import time

import requests

import const
from exceptions import MetadataNetworkError, MetadataNotFound, MetadataRateLimited, MetadataRefused

USER_AGENT = f"Burdamix/{const.APP_VERSION} (https://github.com/jesusobando32/Burdamix)"   # MusicBrainz asks for "App/version (contact)"
MAX_IMAGE_BYTES = 15 * 1024 * 1024   # a cover bigger than this is not a cover
MAX_RETRY_WAIT_SECONDS = 10


class RateLimiter:
    """At most one call every `min_interval` seconds, across threads."""

    def __init__(self, min_interval, clock=time.monotonic, sleep=time.sleep):
        self.min_interval = min_interval
        self._clock, self._sleep = clock, sleep
        self._lock = threading.Lock()
        self._last = None

    def wait(self):
        with self._lock:
            if self._last is not None:
                remaining = self._last + self.min_interval - self._clock()
                if remaining > 0:
                    self._sleep(remaining)
            self._last = self._clock()


class MetadataClient:
    def __init__(self, name, min_interval, session=None, clock=time.monotonic, sleep=time.sleep):
        self.name = name            # "MusicBrainz": how the service is called in messages
        self.limiter = RateLimiter(min_interval, clock, sleep)
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._sleep = sleep

    def _get(self, url, params=None, stream=False, body=None, headers=None):
        for attempt in (1, 2):
            self.limiter.wait()
            try:
                if body is None:
                    response = self.session.get(url, params=params or None, timeout=20, stream=stream)
                else:
                    response = self.session.post(url, json=body, headers=headers or None, timeout=20)
            except requests.RequestException:
                raise MetadataNetworkError(f"No pude conectar con {self.name}. Revisa tu conexión a internet.") from None
            if response.status_code in (429, 503) and attempt == 1:
                try:
                    wait = min(int(response.headers.get("Retry-After", 2)), MAX_RETRY_WAIT_SECONDS)
                except ValueError:
                    wait = 2
                self._sleep(wait)
                continue
            break
        if response.status_code in (429, 503):
            raise MetadataRateLimited(f"{self.name} pide ir más despacio. Espera un minuto e inténtalo de nuevo.")
        if response.status_code == 404:
            raise MetadataNotFound(f"{self.name} no tiene lo que se buscó.")
        if response.status_code == 403:   # some services refuse VPN and data-centre addresses
            raise MetadataRefused(f"{self.name} negó el acceso (403). Si usas una VPN, prueba sin ella.")
        if response.status_code != 200:
            raise MetadataNetworkError(f"{self.name} respondió con un error ({response.status_code}).")
        return response

    def get_json(self, url, params=None):
        return self._json(self._get(url, params))

    def post_json(self, url, body, headers=None):
        return self._json(self._get(url, body=body, headers=headers))

    def _json(self, response):
        try:
            data = response.json()
        except ValueError:   # a 200 that is not JSON, e.g. a Wi-Fi login page
            raise MetadataNetworkError(f"{self.name} respondió algo inesperado.") from None
        return data

    def get_image(self, url):
        """The bytes of an image, refusing anything huge."""
        response = self._get(url, stream=True)
        chunks, total = [], 0
        try:
            for chunk in response.iter_content(65536):
                total += len(chunk)
                if total > MAX_IMAGE_BYTES:
                    raise MetadataNotFound("La portada es demasiado grande.")
                chunks.append(chunk)
        except requests.RequestException:
            raise MetadataNetworkError(f"No pude descargar la portada desde {self.name}.") from None
        return b"".join(chunks)
