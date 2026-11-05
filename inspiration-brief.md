# Brief de inspiración — Burdamix (rediseño)

**Tipo:** app de escritorio (ventana web local), no landing. **Idioma:** español.
**Público:** quien baja canciones de Spotify en MP3 (pegar enlace, favoritas, etiquetas, ficha de artista, tutorial, FAQ, ajustes).
**Estilo:** pendiente, el usuario elige entre A, B y C viendo `design-preview/index.html`.
**Animación:** máxima. **Restricciones:** ligero (sin CDN ni librerías; CSS + JS propio), libertad total de identidad.
**Stack:** el actual, HTML/CSS/JS vanilla en `gui/web/`.

## Referencias

Solo se leyeron resultados de búsqueda; **no se abrió ningún sitio en el navegador** (falta tu permiso para la lista de abajo).

| # | Referencia | Qué se toma |
|---|---|---|
| 1 | Patrón "color desde la portada" en apps de música (Spotify, Apple Music; guías de design systems) | Fondo oscuro que deja el color a la portada; transición corta al cambiar de canción |
| 2 | [Awwwards: elementos de reproductor](https://www.awwwards.com/inspiration/music-player-percale-mobile-visualizers) · [mini player](https://www.awwwards.com/inspiration/music-player-mini-player-soso-radio) · [Spotify Discover](https://www.awwwards.com/inspiration/spotify-discover) | Visualizadores, progreso como onda |
| 3 | [Join Radio (SOTD 2015)](https://www.awwwards.com/sites/join-radio) | Interfaz que cambia de carácter según el contexto |
| 4 | [B/D JAMS (SOTM 2022)](https://basicagency.com/blog/b-d-jams-earns-awwwards-site-of-the-month) | Sitio musical premiado con reproductor tipo playlist |
| 5 | [Codrops: visualizador 3D con Three.js + GSAP](https://tympanus.net/codrops/author/filip) · [etiqueta audio](https://tympanus.net/codrops/tag/audio) | Partículas y elementos que reaccionan al sonido/cursor |
| 6 | [Awwwards: Developer Award, GSAP/WebGL](https://www.awwwards.com/inspiration_search/developer/) · [fromanother.love](https://www.hontran.dev/blog/fromanother-award-winning-creative-agency-website) | Motion de scroll y revelados fuera del nicho |
| 7 | [React Bits](https://reactbits.dev) | Split text, hovers, fondos. Solo como referencia visual: la app no usa React, se recrea con CSS |

## Patrones del nicho
- **Lo esperado:** fondo oscuro, portadas grandes, un color de acento, filas de canción con hover.
- **Lo que diferencia:** el color y el movimiento nacen del contenido (portada, sonido), el progreso se *ve* como audio y no como una barra gris.

## Tres direcciones (visibles en `design-preview/index.html`)
- **A · Vinilo nocturno:** oscuro, aurora de color a la deriva, vinilo girando, lima como acento, foco que sigue al cursor.
- **B · Revista bold:** papel crema, tipografía gigante condensada, sombras duras, filas que se rellenan de lima, marquesina y sello giratorio.
- **C · Neón estudio:** negro violeta, borde en conic-gradient animado, partículas que huyen del cursor, brillo por fila.

Comunes a las tres: título palabra por palabra, entrada en cascada, indicador de menú deslizante, botones magnéticos, progreso en forma de onda con ecualizador, check que rota al terminar, `prefers-reduced-motion`.

## Plan de movimiento (se aplicará a todas las vistas)
| Zona | Efecto | Técnica |
|---|---|---|
| Cambio de vista | Entrada en cascada de bloques | CSS `animation-delay` por `--i` |
| Menú | Indicador que se desliza | `transform` con curva ease-out |
| Compositor | Escala al enfocar, flecha que gira | transform |
| Filas | Desplazamiento, brillo en portada, onda de progreso | transform + opacity |
| Fondo | Aurora / marquesina / partículas según dirección | CSS o canvas pausado fuera de la vista activa |

## Pendiente
1. Elegir dirección (o mezcla).
2. Permiso para abrir las referencias y revisarlas con navegador.
3. Aplicar a `gui/web/` con `impeccable` y `animate`, y probar con `playwright-cli` en 1440 y 390 px.
