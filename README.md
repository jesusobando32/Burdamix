<div align="center">
  <img src="assets/logo.png" alt="logo" width="200" height="auto" />
  <h1>Burdamix</h1>
  <p>Baja tus canciones, álbumes y playlists de Spotify como archivos MP3.</p>
</div>

Spotify no permite descargar su audio, así que el programa **lee la lista en Spotify y busca cada canción en YouTube**,
descarga el audio que mejor coincide (compara la duración, el título y el artista con los de Spotify), lo convierte a MP3
y le pone título, artista, álbum, año y portada.

> Proyecto basado en [couldbejake/spotify2mp3](https://github.com/couldbejake/spotify2mp3). Úsalo solo con música
> que tengas derecho a guardar; bajar audio de YouTube va contra sus términos de servicio.

---

## Inicio rápido (Windows)

1. Instala **Python 3.10 o más nuevo** desde <https://www.python.org/downloads/>.
   Durante la instalación **marca la casilla “Add python.exe to PATH”**.
2. Descarga este proyecto (botón verde *Code* > *Download ZIP*) y descomprímelo.
3. Haz **doble clic en `iniciar.bat`**.
   La primera vez instala todo lo necesario (unos 2 minutos). Después abre el programa guiado.
4. Sigue las instrucciones de la pantalla. La primera vez te explica, paso a paso, cómo conectarlo con Spotify (ver abajo).

Los MP3 quedan en la carpeta **`downloads/`**.

En Mac o Linux:

```bash
pip install -r requirements.txt
python spotify2mp3.py
```

## Conectar con Spotify (solo la primera vez)

Spotify obliga a que cada persona cree su propia “app” gratuita; así el programa puede leer tus playlists.
El programa te lo pide y te guía, pero estos son los pasos:

1. Entra a <https://developer.spotify.com/dashboard> e inicia sesión con tu cuenta de Spotify.
2. **Create app**. Nombre y descripción: lo que quieras.
3. En **Redirect URI** pega exactamente `http://127.0.0.1:5000/callback` y pulsa **Add**.
4. Marca **Web API**, acepta los términos y pulsa **Save**.
5. Abre tu app > **Settings**. Copia el **Client ID** y el **Client secret** (*View client secret*) y pégalos cuando el programa los pida.

Tu usuario y contraseña de Spotify **nunca** se piden. Los datos se guardan en `tekore_cfg.ini` (en tu computador, no se sube a Git).

La primera vez que uses una **playlist** se abrirá el navegador para que pulses **Aceptar**. Tienes 3 minutos.

Si algo sale mal o cambias de app: `python spotify2mp3.py --setup`.

## Cómo usarlo

**Modo guiado** (lo más fácil): abre `iniciar.bat` (o `python spotify2mp3.py`), pega el enlace y elige la calidad.

Para sacar el enlace: clic derecho en la canción, playlist o álbum > *Compartir* > *Copiar enlace*.
En el móvil: tres puntos > *Compartir* > *Copiar enlace*. Los enlaces cortos `spotify.link` no funcionan; ábrelos en el navegador y copia el enlace largo.

**Línea de comandos:**

```bash
python spotify2mp3.py -s "https://open.spotify.com/track/..."        # una canción
python spotify2mp3.py -a "https://open.spotify.com/album/..."        # un álbum
python spotify2mp3.py -p "https://open.spotify.com/playlist/..."     # una playlist TUYA
python spotify2mp3.py -l                                              # tus canciones con “Me gusta”
```

| Opción | Para qué |
|---|---|
| `-q high` | `low` (≤50 kbps), `medium` (≤80 kbps), `high` o un número en kbps. **`high` = la mejor calidad que ofrece YouTube** (unos 130 kbps, que queda como MP3 de 128 kbps); es el valor por defecto. Pedir más, por ejemplo `320`, no mejora nada: YouTube no tiene más, así que se usa lo máximo disponible. |
| `--workers 5` | Canciones que se bajan a la vez (1–8). Por defecto 5. |
| `--max-length 30` | Descarta videos más largos que esto (minutos). |
| `--min-views N` | Descarta videos con menos reproducciones (apagado por defecto). |
| `--keep-interludes` | Descarga también los interludios (por defecto se saltan). |
| `--short-max 50` | Se salta cualquier tema de esta duración o menos, se llame como se llame (segundos). |
| `--interlude-max 70` | Se salta un tema llamado *interlude*, *interludio*, *skit* o *prelude* si dura esto o menos. |
| `--intro-outro-max 95` | Se salta un tema llamado *intro* u *outro* si dura esto o menos; si dura más, es una canción y se baja. |
| `--cookies-from-browser firefox` | Para videos con restricción de edad (ver abajo). |
| `--setup` | Repetir la conexión con Spotify. |

## Cosas que conviene saber

- **Solo playlists tuyas.** Spotify ya no deja que ninguna app lea las playlists de otras personas (da error 403).
  Truco: abre la playlist en Spotify, selecciona todo (`Ctrl+A`), *Añadir a playlist* > *Nueva playlist*, y usa el enlace de tu copia.
  Los **álbumes y canciones sueltas** funcionan con cualquier enlace.
- **Velocidad.** Medido con un álbum de 14 canciones: 2 a la vez = 70 s, 4 = 41 s, 8 = 32 s. Por eso el valor por defecto es 5: subir más rinde poco y aumenta el riesgo de que YouTube te limite.
- **Se puede cortar y reanudar.** Si ya existe `Artista - Título.mp3`, se salta. Vuelve a ejecutar el mismo enlace y sigue donde quedó.
- **Videos con restricción de edad.** El programa prueba automáticamente otra coincidencia (casi siempre hay una versión sin restricción).
  Si no la hay, puedes dejar que use tu sesión de YouTube con `--cookies-from-browser firefox` (o `chrome`, `edge`…): tienes que haber iniciado
  sesión en YouTube en ese navegador. Úsalo solo si lo necesitas: usar tu cuenta para bajadas masivas puede llevar a que YouTube la limite. Es opcional y no está probado en todos los navegadores.
- **Canciones saltadas.** Al final se lista cuáles no se pudieron bajar y por qué. Archivos locales y podcasts de una playlist se ignoran.
- **Nombre de archivo:** `Artista - Título.mp3`, dentro de `downloads/playlists/<nombre>/`, `downloads/albums/<nombre>/` o `downloads/tracks/`.

## Problemas frecuentes

| Síntoma | Qué hacer |
|---|---|
| `python` no se reconoce | Reinstala Python marcando “Add python.exe to PATH”. |
| “Spotify no aceptó esos datos” | Copia de nuevo el Client ID y el Client secret, completos y sin espacios. |
| “El puerto 5000 está ocupado” | Cierra el programa que lo usa y reintenta. |
| “Spotify only lets this app read playlists that are YOURS” | Copia la playlist a una tuya (ver arriba). |
| Muchas canciones saltadas con “No YouTube video matches…” | Normal en temas muy nuevos o raros; el programa prefiere saltar antes que bajar una versión equivocada. |
| Dejó de funcionar de golpe | YouTube cambia seguido. Actualiza el descargador: `.venv\Scripts\pip install -U yt-dlp` (o `pip install -U yt-dlp` si no usas `iniciar.bat`). |

## Para desarrolladores

```bash
pip install -r requirements.txt pytest
python -m pytest tests
```
