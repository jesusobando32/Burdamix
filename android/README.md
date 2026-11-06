# Burdamix para Android

Rama `movil`. La app móvil descarga **en el propio teléfono**, sin PC, y funciona como reproductor **sin internet**.

## Estado

**Paso 1 de 5: la prueba del teléfono.** Esta carpeta todavía no es la app: es un APK de prueba que dice, etapa por etapa, si el
teléfono puede hacer todo el trabajo (Python dentro de la app, yt-dlp, descargar un audio, convertirlo a MP3 con ffmpeg).
Se escribió sin poder compilarlo en el PC de desarrollo: la primera compilación en GitHub puede pedir arreglos de sintaxis
(los imports de `youtubedl-android` no estaban en su README).

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

## Etapas

1. **Prueba del teléfono** (esta). Si falla algo, se sabe en qué etapa.
2. Puente: el WebView habla con el Python de la app (mismo contrato que `pywebview` en el escritorio).
3. Adaptar el backend: carpetas de Android, sin dependencias de Windows, descargas y reproducción en segundo plano.
4. Interfaz: ya existe el diseño móvil (`gui/web/mobile.*`); se ajusta con el teléfono real.
5. Firma, release y actualización.

## Cómo compilar y probar (sin instalar nada)

1. Sube el branch `movil` a GitHub (hace falta tu permiso: es una publicación).
2. En la pestaña **Actions** del repositorio, elige **Android → Run workflow** sobre `movil`.
3. Al terminar, descarga el artefacto `burdamix-apk`, pásalo al teléfono e instálalo (hay que permitir «instalar apps desconocidas» para el navegador o el gestor de archivos).
4. Abre **Burdamix**, espera a que se activen los botones y pulsa **Probar: Python** y **Probar: motor Kotlin**. Cuéntame lo que dice la pantalla (se puede seleccionar y copiar el texto).

El flujo solo corre cuando se pide (manual o al subir una etiqueta `movil-v*`, que además publica un release marcado como prueba).

## Pruebas del lado Python

```bash
python -m pytest tests/test_android_spike.py -q
```

El módulo `app/src/main/python/burdamix_spike.py` se prueba en el PC con la red y ffmpeg simulados.

## Firma (más adelante)

El APK de prueba va firmado con la clave de depuración. Para las versiones reales se genera **una** clave de firma, se guarda en un
lugar seguro y en los secretos del repositorio; **nunca** se sube al repositorio (`*.keystore` y `*.jks` están ignorados). Si se pierde,
las versiones nuevas no se podrán instalar encima de las anteriores.
