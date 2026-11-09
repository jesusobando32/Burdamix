# Traspaso: seguir la versión móvil de Burdamix en otro PC

Este archivo es para quien (persona o Claude) continúe el trabajo en un PC con **Android Studio**. Lo escrito aquí es todo el contexto
que hace falta; no se necesita la conversación original.

## Qué es Burdamix

Programa de escritorio (Windows) que baja las canciones de un enlace de Spotify como MP3, buscando el audio en YouTube con yt-dlp. Python +
interfaz web (`gui/web`, HTML/CSS/JS sin librerías) dentro de una ventana pywebview. Tiene biblioteca, reproductor propio (ecualizador,
crossfade, letras, temporizador, vinilo), playlists, estadísticas y etiquetas. El usuario habla español: textos de la app, commits y
respuestas, en español.

Repositorio: https://github.com/jesusobando32/Burdamix · **Trabajar en el branch `movil`** (no tocar `main` sin pedirlo).

## Qué se quiere

Llevar la app a **Android**, solo Android 8+ (`minSdk 26`), 64 bits. Decisiones ya acordadas con el usuario (no volver a preguntarlas):

- **Se descarga en el propio teléfono, sin PC.** yt-dlp y ffmpeg van dentro de la app.
- **Para el usuario y gente cercana, con todas las funciones.** Nada de Play Store por ahora (temas legales de YouTube, más adelante).
- **Funciona sin internet como reproductor**: biblioteca, reproductor, letras guardadas, estadísticas, etiquetas y playlists no dependen de la red.
  Solo buscar, descargar, iniciar sesión en Spotify y actualizar yt-dlp la necesitan. Ya está hecho en `gui/web/net.js` (con pruebas).
- **Un solo código** para escritorio y móvil: la misma interfaz (`gui/web`) y el mismo Python, con pequeñas capas por plataforma.
- **Arquitectura**: app nativa pequeña (Kotlin) con un WebView que muestra `gui/web`; el Python del programa corre dentro con
  [Chaquopy](https://chaquo.com/chaquopy/); yt-dlp y ffmpeg empaquetados. No React Native (obligaría a reescribir la interfaz).
- **Canciones** en `Música/Burdamix` del teléfono. **Reproducción en segundo plano** con notificación y controles en la pantalla de bloqueo;
  **descargas como servicio en primer plano**, 3 a la vez por defecto. **yt-dlp** se actualiza solo si tiene más de 7 días y con botón manual.
- **Reemplazos de lo exclusivo de Windows**: Explorador → app Archivos; Papelera de Reciclaje → papelera propia de 30 días; arrastrar archivos
  para etiquetar → selector del sistema; compartir playlist → hoja de compartir de Android; teclas multimedia → notificación de música.
- **Inicio de sesión de Spotify**: el mismo flujo de hoy (el usuario crea su app en el panel de Spotify; la redirección vuelve a
  `http://127.0.0.1:5000/callback`, donde escucha el Flask del programa).
- **Diseño móvil**: ya hecho en `gui/web/mobile.css` y `gui/web/mobile.js` (barra inferior con el botón de descarga al centro, inicio con lo
  último escuchado, reproductor pequeño que se abre completo con el vinilo). Se ve con `?demo` en el navegador. Solo se activa en ≤ 760 px.

## Estado actual del branch `movil` (9 de noviembre de 2026)

La app **compila, se instala y se probó en un teléfono real** (Infinix X6855, Android 16, arm64). `python -m pytest tests -q` pasa completo y
`tests/test_android_static.py` comprueba los contratos web ↔ Kotlin ↔ manifiesto sin necesitar el SDK.

Funciona y está verificado en el teléfono:
- Biblioteca, reproductor con notificación (portada, progreso, anterior, pausa, siguiente, aleatorio con su estado), pantalla de bloqueo, teclas de
  medios, música con la pantalla apagada, gesto atrás por pasos, cerrar desde recientes (se quita la notificación y no queda proceso).
- Búsqueda y descarga por texto o enlace, sesión de Spotify, pegar con el portapapeles del teléfono, importar y compartir playlists (código,
  tarjeta con QR y hoja del sistema), **escanear el QR con la cámara** (jsQR dentro de la app, `gui/web/scan.js`).
- Las canciones van a **`Música/Burdamix`** del teléfono (`Storage.kt`; pide «Acceso a todos los archivos» una vez; si se niega quedan en la carpeta
  privada de la app y Configuración ofrece «Mover a Música»). Lo que ya hubiera en la carpeta privada se mueve solo
  (`burdamix_host.migrate_music`, que también corrige «Me gusta» y playlists, que apuntan a rutas). Configuración → «Abrir» la muestra en Archivos.
- Configuración → **Color de la interfaz**: 16 tonos (`gui/web/theme.js`, OKLCH) además del lima; se guarda en el teléfono.
- El pulso de la portada (halos que laten con la música) viene encendido como en escritorio; 0 frames lentos medidos con `dumpsys gfxinfo`.
- Llamadas: el servicio pausa la música mientras el teléfono suena o está en llamada y la reanuda después. Si otra app (un video, Reels) hace que
  Android pause la canción, el servicio la reanuda cuando nada más suena durante 2 s (hasta 15 min); lo que pausa el usuario no se reanuda.
  **Estas dos reanudaciones están programadas pero no se pudieron probar con una llamada ni con Reels reales.**

Limitaciones conocidas:
- **Las descargas se detienen al salir de la app en el Infinix** (ROM de Transsion): el proceso se congela (`cgroup.events frozen 1`) aunque
  `KeepAliveService` esté en primer plano y tenga su bloqueo de CPU; siguen al volver. En otros teléfonos no se ha comprobado. No se encontró
  ajuste de Phone Master que lo evite; cualquier arreglo es una decisión de diseño (avisar en la app, etc.).
- YouTube pide «confirma que no eres un robot» tras muchas descargas seguidas, sobre todo con VPN; es temporal.
- Sin probar con manos: auriculares desenchufados, selector de portada de las etiquetas, audio de otra app y llamada reales.

## Compilar y probar en un teléfono

Entorno de esta máquina (no se reinstala): JDK 17 y SDK en `C:\Users\Yisu\devtools`, `android/local.properties` (ignorado) apunta al SDK.

```powershell
cd android
$env:JAVA_HOME="C:\Users\Yisu\devtools\jdk\jdk-17.0.21+9"; $env:ANDROID_HOME="C:\Users\Yisu\devtools\sdk"; $env:Path="$env:JAVA_HOME\bin;$env:Path"
.\gradlew.bat assembleDebug --console=plain
adb install -r app\build\outputs\apk\debug\app-debug.apk      # -r conserva los datos
```

- En Git Bash usa `export MSYS_NO_PATHCONV=1` para rutas del teléfono; las capturas (`adb exec-out screencap -p > x.png`) solo salen bien desde Bash.
- Etiquetas de log útiles: `BurdamixMedia`, `BurdamixKeepAlive`, `BurdamixWeb`, `Burdamix`. **Esta ROM filtra `Log.d`: usa `Log.i` o `Log.w`.**
- Las coordenadas de `input tap` son del tamaño real (1080x2436); una captura vista a 887x2000 se multiplica por 1,22.

## Release

GitHub Actions falla en segundos en este repositorio (el flujo existe pero no llega a compilar), así que los releases se hacen a mano: compilar,
nombrar el APK `Burdamix-prueba-arm64.apk` y `gh release create movil-vX.Y.Z-prueba <apk> --target movil --prerelease`. Va firmado con la clave de
depuración (ver «Firma» en `README.md`). Sube el `versionName` de `app/build.gradle.kts` con cada release.

## Cómo trabajar

- Cambios pequeños y verificados; corre `python -m pytest -q` (debe seguir en verde) y, en la interfaz, prueba en el navegador con
  `python -m http.server` dentro de `gui/web` y abre `http://localhost:8000/?demo` (la ventana a ≤ 760 px de ancho es el diseño móvil).
- Pruebas primero cuando el proyecto ya tiene pruebas. Buenas prácticas profesionales, sin parches adivinados: reproducir, aislar, arreglar, verificar.
- Commits en español y pequeños, **sin** línea `Co-Authored-By` (regla del usuario).
- **No subir claves de firma** (`*.keystore`, `*.jks` están ignorados) ni datos del usuario. Preguntar antes de hacer push a `main`, borrar
  o desinstalar la app del teléfono (borra sus datos y su música). Nunca borrar `downloads/`.
- El usuario no quiere gimmicks invasivos (cursor que sigue al mouse, transiciones de cortina entre pantallas): se quitaron.
