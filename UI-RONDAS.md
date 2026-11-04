# Rondas de diseño de la UI (5+)

Dirección del usuario (2026-11-03): minimalista sin perder funciones (esconder, abstraer zonas, juntar opciones), muy navegable, cómoda y bonita, con animaciones, muy dinámica y con presets (de serie + propios). Inspiración: cómo Google ha simplificado sus apps con el tiempo pese a añadir funciones (el enfoque, no su aspecto). Base: REDISENO.md.

## Principios (investigación ronda 1)

1. Búsqueda primero: omnibox con chips de filtro (tipo, proyecto, fecha, estado) en vez de más pestañas.
2. Una sola acción primaria: «+ Añadir» (FAB extendido que se contrae con el scroll; atajo N).
3. Revelado progresivo: barra corta + split-buttons («Enviar ▾», «Descargar ▾» = acción por defecto + flecha) + ⋯.
4. Valores por defecto inteligentes: vídeo → acta + tareas; PDF → resumen; recordar la última elección.
5. Barra contextual al seleccionar (n seleccionados + Enviar, Proyecto, Descargar, Borrar).
6. Chips en vez de pestañas cuando son filtros de una misma lista (tipos extraídos).
7. Layout adaptativo lista-detalle; Preguntar como panel lateral en pantallas anchas.
8. Ajustes con buscador y menos grupos; «Restablecer» por sección.
9. Tarjetas de sugerencia en Inicio («3 tareas sin enviar», «Acta lista para revisar»).
10. Deshacer en lugar de confirmar (snackbar 5-8 s, pausa con hover).
11. Estados vacíos que enseñan, con la zona de soltar viva.
12. Jerarquía por tamaño/peso/forma, menos chrome.

## Movimiento (tokens)

```css
--ease-standard: cubic-bezier(.2,0,0,1); --ease-emph-decel: cubic-bezier(.05,.7,.1,1); --ease-emph-accel: cubic-bezier(.3,0,.8,.15);
--dur-s2:100ms; --dur-s4:200ms; --dur-m2:300ms; --dur-m4:400ms; --dur-l1:450ms;
--spring-fast: linear(0,.55 12%,1.08 28%,.98 45%,1.01 62%,1);  /* solo posición/tamaño; color/opacidad sin rebote */
```
Patrones: fade-through entre rutas (90 ms salida / 210 ms entrada, scale .92→1), shared axis X entre pestañas, container transform (tarjeta → documento) con View Transitions (`document.startViewTransition` con fallback), lista escalonada (30 ms × i, máx. 8), skeletons sin saltos, micro-interacciones (`:active scale(.97)`, check SVG), snackbar desde abajo. Solo transform/opacity. `prefers-reduced-motion` + ajuste «Animaciones: completas / reducidas / no».

## Presets

De serie (solo lectura, «Duplicar para editar», «Restablecer») + propios («Guardar lo actual como preset»), fijables, con resumen de una línea e insignia de serie/propio. Dónde: objetivos de Añadir (chips arriba; el checklist = «Personalizar»), Descargar (selección + formatos), Enviar (recetas/presets fijados en el split-button), vistas guardadas de Biblioteca, apariencia (tema claro/oscuro/auto, densidad cómoda/compacta, animaciones), calidad (Rápido/Equilibrado/Preciso).

## Rondas

- R1: base de movimiento + View Transitions + skeletons/escalonado + snackbar con Deshacer + presets (Añadir, Descargar, Enviar fijados, apariencia).
- R2…R5: captura de todas las pantallas (claro/oscuro/móvil) → crítica → mejoras → QA automática (sin errores JS en ninguna ruta).

## Estado (2026-11-03, sesión interrumpida por el usuario)

- Hechas: R1 (movimiento, tema/densidad/animaciones, deshacer, presets), R2 (tokens, Documento con «Enviar ▾» + ⋯, Inicio «Siguiente paso», Enviar/Descargar/Ajustes), R3 (tipografía y chip únicos, Extraído y Pendientes sin cortes, móvil, «Enviar proyecto» dividido, cola solo con trabajos, «+ Añadir»), R4 A+C (3 presets + «Más», Descargar por defecto, legibilidad) y R4-B parcial (marco).
- R4-B hecha (2026-11-04): Añadir simple con preset activo y «Procesar» fijo; Biblioteca con una fila de filtros y barra contextual; paleta con «Recientes», iconos y atajos; imagen abierta en Fuente con iconos sobre la imagen; un solo «+ Añadir» en proyectos. Queda la fila cortada al final de la paleta.
- R5 hecha y verificada (2026-11-04, `docs/ui/critica-ronda5.md` § Verificación): de 33 puntos, 29 resueltos. Entran los dudosos legibles en oscuro, los contadores por tipo, una sola barra en Extraído («Filtros», «Descartar» visible en táctil), Ajustes › Enviar por enlace y los estados vacíos que enseñan.
- Pendiente R6: P1 Fuente a 390 (la imagen tapa «Tu descripción», app.css:789); Descargar a 390 (Formato bajo el pie); doble scroll residual del documento; Inicio sin «N por revisar» (shell.js:451 frente a carpeta.js:27); «Preguntar a … →» en Búsqueda; 7 P3 menores. Además, recapturar el primer arranque.
- Huecos de backend: el chip «Descartadas» no lleva número (falta el contador por tipo en `/api/reg`); mojibake en Windows sin `PYTHONUTF8` (`encoding="utf-8"` en meta()/acta.json de app.py); el seed no trae propuestas IA reales.
- Herramientas de QA: `docs/ui/qa-app.sh` (app con latido en el puerto 57377 y `ACTAS_WORK` aparte) y `docs/ui/cdp.mjs` (Brave sin interfaz con `--remote-debugging-port=9333`: errores JS/HTTP + capturas por ruta).
- Probado con modelos reales en GPU (RX 6600, Vulkan): Qwen3.5-4B (acta de un .md, extracción al proyecto, resumen por partes de un documento de 429k caracteres) y Gemma 4 E4B + mmproj (descripción de una captura de pantalla, buscable).
