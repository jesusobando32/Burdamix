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

## Aplicación con ventana (Windows)

Burdamix tiene una ventana con un menú a la izquierda, al estilo de un asistente de IA:

| Menú | Qué hace |
|---|---|
| **Pegar enlace** | Pegas el enlace de una canción, álbum o playlist; ves la lista con portadas, marcas las que quieres y descargas. El progreso y los errores salen en la misma pantalla. |
| **Mis favoritos** | Tus «Me gusta» más recientes (50, 100, 200, 500, todas o el número que escribas). |
| **Completar etiquetas** | Elige canciones que ya tengas (o suéltalas en la ventana) y Burdamix escribe en ellas título, artista, álbum, año, género, número de pista y portada. Ver la sección de abajo. |
| **Tutorial · Iniciar sesión** | Los pasos para conectar el programa con Spotify, con los campos para pegar el Client ID y el Client secret. |
| **Preguntas frecuentes** | Las dudas más comunes. |
| **Configuración** | Carpeta de descargas, canciones a la vez, saltar intros, sesión del navegador y actualizar yt-dlp. |

Para abrirla desde el código: `python gui_app.py`. Las versiones compiladas (instalador y portable) están en la sección
*Releases* del repositorio y abren esta ventana; `Burdamix-consola.exe` es el modo de texto de siempre.

## Completar etiquetas y portadas

Sirve para canciones que ya tienes (de Burdamix o de cualquier otro sitio) y que no muestran bien su nombre, artista o portada
en el reproductor. Se usa desde la ventana, en **Completar etiquetas**:

1. **Elige archivos o una carpeta** (o suéltalos sobre la ventana). Formatos: **mp3** (ID3v2.3, el que leen hasta los equipos más viejos), **flac**, **m4a**, **ogg** y **opus**.
2. Pulsa **Buscar etiquetas**. Burdamix averigua qué canción es a partir de sus etiquetas o de su nombre (`Artista - Título.mp3` o `Título - Artista.mp3`: prueba los dos órdenes y se queda con el que mejor coincide). Si el archivo no dice nada, puedes escribir el título y el artista tú.
3. Si hay una **coincidencia clara** (mismo título, mismo artista y duración parecida), queda lista. Si hay dudas, te muestra de **3 a 5 opciones** (título, artista, álbum, año y tipo: álbum de estudio, sencillo, recopilatorio o en vivo) y tú eliges. El álbum de estudio original va primero.
4. **Revisa los cambios** (qué había y qué quedará) y confirma. **Los cambios se escriben en el archivo y no se pueden deshacer**; por eso siempre se muestran antes.
5. Opcional: **renombrar el archivo** con el título (`Título.mp3`; el artista queda en las etiquetas). Está apagado por defecto.

**Con una carpeta entera** (modo por lotes): los archivos que ya tienen título, artista, álbum, año, número de pista y portada se **saltan**. Las coincidencias claras se aplican con **un solo botón** (después de una confirmación) y las dudosas quedan en la lista para que las revises una por una.

**De dónde salen los datos** (todos gratis y sin iniciar sesión):

| Qué | Servicio |
|---|---|
| Canción, álbum, año, número de pista | [MusicBrainz](https://musicbrainz.org). Se respeta su límite de 1 petición por segundo. |
| Portada | Es un paso aparte, después de las etiquetas, y no depende de qué servicio las dio: se busca con el título, el artista y el álbum en este orden (el más probable primero): **Deezer**, **YouTube Music** (su búsqueda pública, sin cuenta; no es una API oficial y puede cambiar), [Cover Art Archive](https://coverartarchive.org) e **iTunes**. Se verifica que la portada sea del álbum correcto, siempre se pide la de mayor resolución, y un servidor que te rechaza (por ejemplo, por una VPN) se deja en pausa 10 minutos. |
| Respaldo si MusicBrainz no la conoce, y género | Deezer e iTunes. |

Si ningún servicio da la portada, la tarjeta de esa canción tiene el botón **Elegir una imagen…** para ponerla tú (JPG, PNG, WEBP o BMP). Si el motivo es un rechazo (el servidor de imágenes de Deezer, por ejemplo, bloquea algunas **VPN** con un error 403), la tarjeta lo dice.

Las portadas se guardan como JPG de **1000 × 1000 píxeles como máximo**. Si un archivo está abierto en otro programa (por ejemplo, en el reproductor), Burdamix avisa y no lo toca: las etiquetas se escriben en una copia que reemplaza al original solo cuando está completa.

> **Todavía no incluido:** identificar una canción por su **huella acústica** (AcoustID), para archivos sin ningún dato. Necesitará
> el programa `fpcalc` (Chromaprint) y una clave gratuita de AcoustID; se añadirá con sus instrucciones de instalación.

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

Tu usuario y contraseña de Spotify **nunca** se piden. El Client ID, el Client secret y tu sesión se guardan en una carpeta privada de tu usuario (`%LOCALAPPDATA%\Burdamix\` en Windows), **fuera del proyecto**: así no se sincronizan con OneDrive ni viajan dentro de la carpeta si se la pasas a alguien.

La primera vez que uses una **playlist** se abrirá el navegador para que pulses **Aceptar**. Tienes 3 minutos.

Si algo sale mal o cambias de app: `python spotify2mp3.py --setup`.

## Cómo usarlo

**Modo guiado** (lo más fácil): abre `iniciar.bat` (o `python spotify2mp3.py`), pega el enlace y elige la calidad.

Para tus canciones con **“Me gusta”**, en vez de un enlace escribe:

| Escribes | Qué pasa |
|---|---|
| `like it` | Te muestra tus **últimas 200** (las más recientes primero) |
| `like it 50` | Te muestra las **últimas 50** (o el número que pongas) |
| `like it all` | Te muestra **todas** |

Primero ves la lista (con la fecha en que guardaste cada una y cuántas ya tienes) y el programa pregunta **“¿Quieres descargarlas? (yes/no)”**. Con `yes` baja exactamente esas; con `no` no hace nada.

Para sacar el enlace: clic derecho en la canción, playlist o álbum > *Compartir* > *Copiar enlace*.
En el móvil: tres puntos > *Compartir* > *Copiar enlace*. Los enlaces cortos `spotify.link` no funcionan; ábrelos en el navegador y copia el enlace largo.

**Línea de comandos:**

```bash
python spotify2mp3.py -s "https://open.spotify.com/track/..."        # una canción
python spotify2mp3.py -a "https://open.spotify.com/album/..."        # un álbum
python spotify2mp3.py -p "https://open.spotify.com/playlist/..."     # una playlist TUYA
python spotify2mp3.py -l                                              # tus canciones con “Me gusta”
python spotify2mp3.py -l --last 50 --dry-run                         # ver tus 50 más recientes, sin descargar
python spotify2mp3.py -l --last 50                                   # bajar solo esas 50
```

| Opción | Para qué |
|---|---|
| `-q high` | `low` (≤50 kbps), `medium` (≤80 kbps), `high` o un número en kbps. **`high` = la mejor calidad que ofrece YouTube** (unos 130 kbps, que queda como MP3 de 128 kbps); es el valor por defecto. Pedir más, por ejemplo `320`, no mejora nada: YouTube no tiene más, así que se usa lo máximo disponible. |
| `--workers 5` | Canciones que se bajan a la vez (1–8). Por defecto 5. |
| `--max-length 30` | Descarta videos más largos que esto (minutos). |
| `--min-views N` | Descarta videos con menos reproducciones (apagado por defecto). |
| `--keep-interludes` | Descarga también los interludios (por defecto se saltan). |
| `--last 50` | Con `-l`: solo tus **50 canciones más recientes** de “Me gusta” (Spotify las ordena de la más nueva a la más vieja). Si tienes miles, no hace falta bajarlas todas. |
| `--ask` | Muestra la lista primero y pregunta **yes/no** antes de descargar (es lo que hace `like it` en el modo guiado). |
| `--dry-run` | Solo **muestra la lista** (con la fecha en que la guardaste y cuántas ya tienes) y no descarga nada. Sirve para ver cuántas detecta antes de bajar. |
| `--short-max 50` | Se salta cualquier tema de esta duración o menos, se llame como se llame (segundos). |
| `--interlude-max 70` | Se salta un tema llamado *interlude*, *interludio*, *skit* o *prelude* si dura esto o menos. |
| `--intro-outro-max 95` | Se salta un tema llamado *intro* u *outro* si dura esto o menos; si dura más, es una canción y se baja. |
| `--cookies-from-browser firefox` | Para videos con restricción de edad (ver abajo). |
| `--setup` | Repetir la conexión con Spotify (también cierra la sesión anterior). |
| `--no-update` | No buscar una versión nueva de yt-dlp. |

## Cosas que conviene saber

- **Solo playlists tuyas.** Spotify ya no deja que ninguna app lea las playlists de otras personas (da error 403).
  Truco: abre la playlist en Spotify, selecciona todo (`Ctrl+A`), *Añadir a playlist* > *Nueva playlist*, y usa el enlace de tu copia.
  Los **álbumes y canciones sueltas** funcionan con cualquier enlace.
- **Velocidad.** Medido con un álbum de 14 canciones: 2 a la vez = 70 s, 4 = 41 s, 8 = 32 s. Por eso el valor por defecto es 5: subir más rinde poco y aumenta el riesgo de que YouTube te limite.
- **Cancelar.** Mientras se descarga (una playlist, un álbum o una canción), pulsa **Ctrl+C tres veces**: una o dos solo avisan y la descarga sigue (probado con pulsaciones reales de consola). Al cancelar se conserva lo ya descargado. En las preguntas del modo guiado, un Ctrl+C te despide al instante.
- **Dónde quedan los MP3.** Siempre en la carpeta `downloads` **dentro del proyecto**, sin importar desde dónde lo ejecutes. Al terminar, el programa muestra la ruta completa.
- **“Me gusta” con muchas canciones.** Usa `-l --last 50` para bajar solo las más recientes: pide a Spotify únicamente esas (una petición en lugar de veinte). Más adelante puedes repetirlo con otro número y las que ya tienes se saltan, así que sirve para ir actualizando.
- **Se puede cortar y reanudar.** Si ya existe `Artista - Título.mp3`, se salta. Vuelve a ejecutar el mismo enlace y sigue donde quedó.
- **Videos para mayores de edad.** Si la única versión de una canción en YouTube está marcada para mayores de edad, YouTube exige iniciar sesión y el programa no puede bajarla sin tu cuenta. En el **modo guiado**, al terminar te pregunta si quieres usar la sesión de YouTube que ya tienes en tu navegador: escribe `firefox` (el que mejor funciona), `chrome`, `edge`... o Enter para dejarlas. En la línea de comandos: `--cookies-from-browser firefox`. Solo se lee el navegador que elijas, y solo cuando lo eliges. Si usas Chrome o Edge, ciérralo por completo antes.
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
| Dejó de funcionar de golpe | YouTube cambia seguido. El programa busca solo una versión nueva de `yt-dlp` **una vez al día**. Si acaba de fallar, borra el archivo `.ytdlp_last_check` y vuelve a abrirlo para forzar la búsqueda. |
| Dos canciones con el mismo nombre | Si la misma canción está repetida en la lista, se baja una sola vez. Si son versiones distintas con el mismo nombre (por ejemplo la original y la *Remastered*), la segunda se guarda como `Artista - Título (2).mp3` y el programa te avisa. |
| “YouTube pidió comprobar que no eres un robot” | Pasa a veces con un video concreto: el programa prueba solo otra versión de la canción, y al final reintenta una vez las que YouTube rechazó. Si siguen saltadas, espera unos minutos y ejecuta **el mismo enlace**: solo baja las que faltan. |
| “YouTube marca este video para mayores de edad” | Mira la sección *Videos para mayores de edad* de arriba. |
| “YouTube te está bloqueando” | Tras 5 canciones seguidas rechazadas el programa se detiene para no empeorarlo. Espera un rato (a veces hasta una hora) o cambia de red y ejecuta **el mismo enlace**: lo ya descargado se salta. |

## Para desarrolladores

```bash
pip install -r requirements.lock yt-dlp pytest mutagen
python -m pytest tests
```

**Etiquetas.** `autotag.py` coordina la búsqueda y el ranking; `tagwriter.py` lee y escribe etiquetas con `mutagen`; cada servicio está en `apis/` (`musicbrainz.py`, `deezer.py`, `itunes.py`) con un cliente HTTP común (`apis/metadata_http.py`) que limita las peticiones y envía el User-Agent. Las pruebas están en `tests/test_autotag.py` y no usan internet.

**Versiones fijas.** `requirements.lock` tiene las versiones exactas (con hashes) con las que se probó todo, y es lo que instala `iniciar.bat`.
`yt-dlp` queda fuera a propósito: se actualiza solo. Para subir versiones, edita `requirements.in` y regenera:

```bash
pip install pip-tools
pip-compile --generate-hashes --allow-unsafe --strip-extras -o requirements.lock requirements.in
```
