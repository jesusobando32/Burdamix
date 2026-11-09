# Burdamix para Android

Rama `movil`. La app móvil descarga **en el propio teléfono**, sin PC, y funciona como reproductor **sin internet**.

## Estado

**Ya es la app** (versión de prueba 0.4.0). Un WebView en Kotlin muestra la misma interfaz que el escritorio (`gui/web`) y el Python del programa corre
dentro con Chaquopy; yt-dlp y ffmpeg van empaquetados. Se instala y se probó en un teléfono real arm64 (Infinix, Android 16): biblioteca,
reproductor con notificación, descargas, Spotify, compartir e importar playlists (con escáner de QR por cámara), canciones en `Música/Burdamix`,
paleta de color de la interfaz. Lo que falta y lo que no se pudo probar está en [`HANDOFF.md`](HANDOFF.md) (sobre todo: en el Infinix las descargas
se detienen al salir de la app).

Las secciones de abajo («Resultado de la prueba», «Etapas») son la historia de cómo se llegó aquí: la prueba del 6 de noviembre de 2026 con el emulador.

## Resultado de la prueba (6 nov 2026)

Compilado con Gradle 8.10.2 (wrapper incluido), JDK 21 y Python 3.13 en el PC; probado en el emulador `Medium_Phone_API_37.0`
(x86_64). **No se probó en un teléfono físico arm64**: no había ninguno conectado. El APK de `arm64-v8a` compila, pero su ejecución
real queda por verificar.

| Etapa | Motor Python (Chaquopy) | Motor Kotlin (youtubedl-android 0.16.0) |
|---|---|---|
| Arranca | ✔ Python 3.13 | ✔ (con arreglo, ver abajo) |
| yt-dlp | ✔ 2026.10.26 (de pip, actual) | ✘ el yt-dlp que trae la librería está viejo: YouTube responde «Precondition check failed» |
| Descarga el audio | ✔ `.webm`, 246 KB | no llegó a esta etapa |
| Ejecutar ffmpeg y pasar a MP3 | ✔ `prueba.mp3`, 175 KB (libmp3lame incluido) | no llegó a esta etapa |

Lo que se aprendió:
- **El ffmpeg empaquetado sí se puede ejecutar** desde `nativeLibraryDir` (viene como `libffmpeg.so`). Necesita dos cosas: que la app
  incluya `libc++_shared.so` (la librería no la trae; ahora se copia del NDK al compilar) y `LD_LIBRARY_PATH` con
  `nativeLibraryDir` y `noBackupFilesDir/youtubedl-android/packages/ffmpeg/usr/lib`.
- **Los dos motores en un mismo proceso chocan**: Chaquopy deja `PYTHONPATH` en el entorno del proceso y el Python 3.8 de la librería lo
  hereda y no arranca. Se resolvió con `Os.unsetenv("PYTHONPATH")`, pero es frágil.
- Compilar desde una ruta con caracteres no ASCII (como `programación`) falla en AGP; se compiló desde una unidad `subst` ASCII.
- Para emuladores x86_64: `./gradlew assembleDebug -Pburdamix.abis=arm64-v8a,x86_64`.

**Motor recomendado: Python con Chaquopy**, más el ffmpeg empaquetado ejecutado como subproceso. Conserva un solo código con el
escritorio, usa el yt-dlp más nuevo (se actualiza con pip y con la actualización automática ya acordada) y no mezcla un segundo Python.
El motor Kotlin se descarta como descargador principal. De `youtubedl-android` solo hace falta el ffmpeg; queda por evaluar si el módulo `ffmpeg`
puede usarse sin el módulo `library`, o si conviene empaquetar ffmpeg por otro medio.

## Decisiones (acordadas)

| Tema | Decisión |
|---|---|
| Plataforma | Solo Android 8 o más (`minSdk 26`), 64 bits (`arm64-v8a`). |
| Dónde se descarga | En el teléfono. Sin PC. |
| Para quién | Para ti y tu gente cercana, con todas las funciones. Publicar en tiendas queda para después (temas legales de YouTube). |
| Cómo se construye | App nativa pequeña (Kotlin) que muestra la interfaz web de `gui/web` en un WebView; el Python del programa corre dentro con [Chaquopy](https://chaquo.com/chaquopy/); yt-dlp y ffmpeg van empaquetados. Compila GitHub Actions, no hace falta Android Studio. |
| Sin conexión | Reproducir, biblioteca, letras guardadas, estadísticas, etiquetas y playlists **nunca** dependen de internet. Solo buscar, descargar, iniciar sesión en Spotify y actualizar yt-dlp lo necesitan (`gui/web/net.js`). |
| Un solo código | La interfaz y el Python son los mismos del escritorio, con capas por plataforma. No se copia ni se divide el programa. |
| Canciones | En `Música/Burdamix` del teléfono (no se pierden al desinstalar). |
| Segundo plano | Reproducción con notificación y controles en la pantalla de bloqueo; descargas como servicio en primer plano, 3 a la vez por defecto. |
| yt-dlp | Se actualiza solo si tiene más de 7 días, y con botón manual. |
| Reemplazos de lo exclusivo de Windows | Explorador → app Archivos; Papelera de Reciclaje → papelera propia de 30 días; arrastrar archivos → selector del sistema; compartir → hoja de compartir de Android. |

## Gesto atrás, notificación del reproductor y compartir (7 nov 2026)

Escrito **sin poder compilar** (este PC no tiene Android SDK): hay que compilar y probar en el teléfono antes de fiarse.

- **Gesto atrás.** `WebActivity.onBackPressed` le pregunta a la página (`window.burdamixBack()`, en `gui/web/mobile.js`) y esta cierra lo
  que esté encima: menú, diálogo, letra, cola, reproductor grande, álbum o playlist abierto... Después vuelve al **Inicio**; desde
  Estadísticas, Configuración, etc. vuelve a «Más» o al Inicio según de dónde se abrieron. Solo en el Inicio sin nada abierto sale de
  la app: con música sonando la manda **al segundo plano** (sigue sonando, con su notificación) y si no suena la cierra.
- **Notificación del reproductor** (`PlaybackService.kt`): servicio en primer plano de tipo `mediaPlayback` con `MediaSession` y
  `Notification.MediaStyle` (solo APIs del sistema, sin librerías nuevas). Muestra portada grande, título, artista y álbum; botones
  anterior, pausa/reproducir, siguiente y aleatorio; es pública, así que se ve en la pantalla de bloqueo. La página manda el estado con
  `BurdamixAndroid.media(json)` (`gui/web/androidmedia.js`) y los botones vuelven como palabras a `window.__burdamixMedia`. También
  pausa al llegar una llamada u otro reproductor (foco de audio), al desenchufar los auriculares, y mantiene la CPU despierta con la
  pantalla apagada. Android 13+ pide permiso de notificaciones al abrir la app.
- **Compartir y elegir archivos:** la hoja de compartir de Android (`Platform.shareText/shareFile`, con `FileProvider` y la carpeta
  `cache/share`) en lugar de «Guardar como»; el selector del sistema (`onShowFileChooser`) para importar la tarjeta de una playlist y
  para elegir una portada en Completar etiquetas.
- `tests/test_android_static.py` comprueba por lectura que la página, Kotlin, el manifiesto y los recursos coinciden en nombres.

**Segunda vuelta (8 nov 2026), a raíz de probar en un teléfono:**
- **Notificación que no salía.** Hipótesis más probable: el WebView de Android no define `navigator.mediaSession` y el aviso a Kotlin
  estaba detrás de esa comprobación (ahora no lo está). Además, si Android 13+ tiene las notificaciones desactivadas, la app lo dice
  una vez con un botón «Activar» que abre los ajustes. Kotlin escribe en el log (`BurdamixMedia`) cada estado que recibe.
- **Descargas que se paraban al salir de la app:** `KeepAliveService` (primer plano, tipo `dataSync`, con CPU y Wi-Fi despiertos). La página
  solo avisa de que hay trabajo; el servicio mira a Python (`burdamix_host.busy()`) y se apaga solo cuando termina.
- **Animación y tirones en el móvil:** sin aguja del tocadiscos; sin `backdrop-filter` en ningún sitio (se recalculaba con cada fotograma de
  los halos); los halos empiezan apagados (se encienden con el interruptor del ecualizador); el bucle del espectro no corre si no hay nada que
  dibujar; el `AudioContext` pide buffers grandes (`latencyHint: "playback"`).

**Sin verificar:** compilar; el servicio y la notificación en un teléfono; que Android no pause el WebView con la pantalla apagada
(si pasa, hay que llamar a `WebView.onResume`/mantener los temporizadores); la pantalla de bloqueo en cada fabricante.

## Etapas

1. **Prueba del teléfono** (esta). Si falla algo, se sabe en qué etapa.
2. Puente: el WebView habla con el Python de la app (mismo contrato que `pywebview` en el escritorio).
3. Adaptar el backend: carpetas de Android, sin dependencias de Windows, descargas y reproducción en segundo plano.
4. Interfaz: ya existe el diseño móvil (`gui/web/mobile.*`); se ajusta con el teléfono real.
5. Firma, release y actualización.

## Cómo compilar y probar (sin instalar nada)

1. Sube el branch `movil` a GitHub (hace falta tu permiso: es una publicación).
2. La compilación arranca sola al subir cambios de `android/` al branch `movil` (pestaña **Actions** del repositorio, flujo **Android**). Cuando el flujo esté también en `main`, se podrá lanzar a mano con **Run workflow**.
3. Al terminar, descarga el artefacto `burdamix-apk`, pásalo al teléfono e instálalo (hay que permitir «instalar apps desconocidas» para el navegador o el gestor de archivos).
4. Abre **Burdamix**, espera a que se activen los botones y pulsa **Probar: Python** y **Probar: motor Kotlin**. Cuéntame lo que dice la pantalla (se puede seleccionar y copiar el texto).

El flujo corre al subir cambios de `android/` a `movil`, a mano, o al subir una etiqueta `movil-v*`, que además publica un release marcado como prueba.

## Pruebas del lado Python

```bash
python -m pytest tests/test_android_spike.py -q
```

El módulo `app/src/main/python/burdamix_spike.py` se prueba en el PC con la red y ffmpeg simulados.

## Firma (más adelante)

El APK de prueba va firmado con la clave de depuración. Para las versiones reales se genera **una** clave de firma, se guarda en un
lugar seguro y en los secretos del repositorio; **nunca** se sube al repositorio (`*.keystore` y `*.jks` están ignorados). Si se pierde,
las versiones nuevas no se podrán instalar encima de las anteriores.
