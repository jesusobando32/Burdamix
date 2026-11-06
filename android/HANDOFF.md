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

## Estado actual del branch `movil`

Hecho y probado (613 pruebas de Python pasan: `python -m pytest -q`):
- Diseño móvil responsive y modo sin conexión (`net.js`).

Hecho **pero nunca compilado** (se escribió sin SDK de Android, solo con la documentación):
- `android/`: proyecto Gradle (Kotlin DSL; AGP 8.7.3, Kotlin 2.0.21, Chaquopy 17.2, Python 3.13, minSdk 26, arm64-v8a).
- `MainActivity.kt`: pantalla de **prueba**, no la app. Dos botones que ejecutan, en el teléfono, descargar un audio y convertirlo a MP3:
  yt-dlp en Python (Chaquopy, `app/src/main/python/burdamix_spike.py`) y la librería `youtubedl-android` 0.16.0 (módulos `library` y `ffmpeg`,
  Maven Central). Cada etapa se informa por separado.

GitHub Actions no está disponible ahora: la cuenta del usuario tiene un bloqueo de facturación. Por eso se compila en este PC.

## Primeros pasos en el PC con Android Studio

```bash
git clone https://github.com/jesusobando32/Burdamix.git
cd Burdamix
git checkout movil
```

1. Abre la carpeta **`android/`** (no la raíz) en Android Studio y deja que sincronice Gradle.
   - Chaquopy necesita un **Python 3.13** en el PC (el mismo major.minor que `version = "3.13"` de `app/build.gradle.kts`); si el PC tiene otro,
     instala 3.13 o indica su ruta con `buildPython("...")` dentro del bloque `chaquopy`.
   - Si el wrapper de Gradle no existe (no se generó), Android Studio ofrece crearlo; o usa **Gradle 8.10.2** (AGP 8.7.3 pide 8.9 o más).
2. **Corrige lo que no compile.** Lo más probable: los imports de `youtubedl-android` en `MainActivity.kt` (el README de la librería no los
   muestra; deberían ser `com.yausername.youtubedl_android.YoutubeDL`, `YoutubeDLRequest` y `com.yausername.ffmpeg.FFmpeg`) y la firma de
   `YoutubeDL.getInstance().execute(...)`.
3. Instala en un **teléfono real** (modo desarrollador y depuración USB) o un emulador arm64/x86_64 con internet. Abre Burdamix, espera a que
   se activen los botones y pulsa los dos. La pantalla enseña cada etapa con ✔ o ✘.
4. Lo que hay que averiguar y anotar en `android/README.md`:
   - ¿Importa yt-dlp en Python y llega a YouTube? ¿Descarga el audio?
   - **¿Se puede ejecutar el ffmpeg empaquetado?** Android 10+ limita ejecutar binarios desde la carpeta de datos de la app; la librería dice dónde
     lo deja? La prueba busca `ffmpeg`/`libffmpeg.so` en `noBackupFilesDir`, `filesDir` y `nativeLibraryDir` y lo informa.
   - ¿Cuál de los dos motores conviene para la app real? (Decisión: si el de Python funciona con ffmpeg ejecutable, mantiene un solo código con el
     escritorio; si no, el motor Kotlin hace de «descargador» y Python se queda con la lógica.)
5. Con eso decidido, seguir las etapas de `android/README.md` (puente WebView↔Python con el mismo contrato que `pywebview` en
   `gui/backend.py`; adaptar el backend a Android; servicio de reproducción y de descargas; firma y release).

## Cómo trabajar

- Cambios pequeños y verificados; corre `python -m pytest -q` (debe seguir en verde) y, en la interfaz, prueba en el navegador con
  `python -m http.server` dentro de `gui/web` y abre `http://localhost:8000/?demo` (la ventana a ≤ 760 px de ancho es el diseño móvil).
- Pruebas primero cuando el proyecto ya tiene pruebas. Buenas prácticas profesionales, sin parches adivinados: reproducir, aislar, arreglar, verificar.
- Commits en español, uno por función, con esta línea al final: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- **No subir claves de firma** (`*.keystore`, `*.jks` están ignorados) ni datos del usuario. Preguntar antes de publicar, hacer push a `main`,
  borrar o crear releases.
- El usuario no quiere gimmicks invasivos (cursor que sigue al mouse, transiciones de cortina entre pantallas): se quitaron.
