# Crítica ronda 5

Capturas: qa-r5, 42 rutas × (1440 claro, 1440 oscuro, 390 claro) + primer arranque. Sin errores JS/HTTP ni desbordes. Cito los ficheros por nombre (shots/<modo>/).

## Estado de R4
1. Resuelto: en /p/* solo queda el FAB, sin «+» arriba (p_Reservas_20App_resumen-390.png).
2. Parcial: 3 presets + «Más», «Guardar preset» dentro de «Más», ajustes en texto y «Procesar» fijo. Pero ningún chip sale activo y quedan 90 px en blanco bajo el pie a 390 (p_Reservas_20App_resumen_formNuevo-390.png).
3. Parcial: el foco cae en «Elegir archivos», el «×» está limpio y ✦/⋯ se ocultan. Al pasar el ratón, el chip crece ~46 px y empuja a los vecinos (se ve en el código, vistas-enviar.css:95-96,184).
4. Sin evidencia: la captura de la imagen abre en Resumen y los iconos/«Ver más» están en Fuente (app.js:588). En R6, capturar la pestaña Fuente de cccc3333.
5. Resuelto: una sola fila de filtros y el contador 5 coincide con el raíl. El hueco bajo la tabla es solo el final de la lista: no tocar. La barra al seleccionar queda sin evidencia (biblioteca-1440.png).
6. Resuelto: «Acta en PDF» preseleccionado, «Descargar» activo, Excel/CSV atenuados y «Opciones» más arriba (d_aaaa1111_acta_normal_impaaaa_Descargar_ab-1440.png).
7. Parcial: Recientes, iconos, «Ver 4 más» y atajos bien. La primera fila de «Vista» queda cortada bajo la barra de atajos (paleta-1440.png, y≈658).
8. Parcial: las tarjetas ya tienen el mismo alto, pero no aparece ninguna banda «N por revisar» aunque hay 20 propuestas de la IA, y Pendientes deja 150 px vacíos (inicio-1440.png).
9. Resuelto: «Añadir» con un solo botón (inicio-390.png).
10. Resuelto: la fila meta «Proyecto · Responsable · Plazo» va a la izquierda (pendientes-390.png).
11. Parcial: Tareas ya está limpio. «Vigentes» sigue siendo un tipo metido entre estados (ver P2-10), y Decisiones/Requisitos/Riesgos mantienen selects sueltos y «Descartar» a la vista (p_Reservas_20App_decisiones-1440.png).
12. Parcial: ya no están el select ni el botón, pero tampoco se ve «Preguntar a … →» (buscar_ascensor-1440.png). Si se oculta por no haber modelo, mostrarlo deshabilitado.
13. Resuelto: icono, «Sin conectar» y 2 recetas (enviar-1440.png). Lo que queda va en P3-33.
14. Parcial: overline unificado. Sigue habiendo «+ Añadir» global de 44 px + uno de 36 px en el proyecto + un tercero en Requisitos/Riesgos (p_Reservas_20App_requisitos-1440.png).
15. Parcial: los bordes en oscuro están bien, pero las casillas siguen grises y rellenas (biblioteca-1440-dark.png), y hay un fallo nuevo (P1-1).
16. Resuelto: «+ Datos…» en la cabecera y chips «+0 ~0 −1» (p_Reservas_20App_resumen-1440-dark.png).
17. Resuelto: solo queda «Ajustes» abajo.
18. Sin evidencia: las capturas son estáticas.

## P1
1. Documento en oscuro: los fragmentos dudosos no se leen, texto claro sobre #fde68a (d_cccc3333_acta_normal_impcccc-1440-dark.png) → en el CSS inyectado poner `.dd{color:#1f2933}`, o en oscuro `background:rgba(253,230,138,.22)` (exportar.js:124).
2. Extraído: los contadores de revisión son del proyecto entero, «Todas 17 · Propuestas 12» en Riesgos/Preguntas/Hitos con 1 ítem (p_Reservas_20App_riesgos-1440.png, p_Comunidad_20Los_20Pinos_preguntas-390.png) → contar los ítems del tipo, no `contadores.por_revision` (registro.js:200-201, requisitos.js:164,174, o filtrar por tipo en /api/reg).
3. Ajustes › Enviar: al entrar por enlace dice «El módulo de envío no está disponible», aunque #/enviar funciona (ajustes_enviar-1440.png). ajustes.js pinta antes de que cargue enviar.js (index.html:410 frente a 422) → resolver `window.Enviar` al mostrar la pestaña (ajustes.js:137).
4. Extraído: cada tipo tiene una barra distinta. Decisiones: 4 filas, 380 px de controles a 390 antes del primer ítem. Requisitos: «3 sin prioridad». Interesados: 8 chips + select + «Deshacer». «Importar Excel/CSV» suelto en la fila de tipos (p_Reservas_20App_decisiones-390.png, p_Reservas_20App_interesados-390.png) → un solo patrón: [Buscar] [chips de revisión] [Filtros ▾: selects, «Solo vigentes», agrupar] ··· [Vista] [+ Añadir] [⋯ Importar/Exportar/Derivar]; «Deshacer» solo en la snackbar. Reusar masFiltros (registro.js:91). Ficheros: decisiones.js, requisitos.js, historias.js, interesados.js, registro.js, carpeta.js.
5. Documento: hay doble scroll. El iframe mide `calc(100vh - 150px)`, pero la cabecera, las pestañas y el aviso ocupan ≈355 px, así que salen dos barras de scroll y «+ Añadir» salta 15 px de una ruta a otra (d_aaaa1111_acta_normal_impaaaa-1440.png) → alto medido (≈`100dvh - 360px`) o alto automático según el contenido, y `html{scrollbar-gutter:stable}` (app.css:201).

## P2
6. Añadir: ningún preset sale marcado aunque el resumen dice «Acta de reunión» → `pre.sel` por defecto = el último usado o el del perfil del proyecto (enviar.js:398-404).
7. Añadir a 390: 90 px en blanco bajo «Cancelar/Procesar», y «N salidas: …» ocupa 3 líneas → diálogo en flex columna, cuerpo con `overflow:auto` y pie con `margin-top:auto`; `#an-res{flex-basis:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}` + `title` (vistas-shell.css:72,182; shell.js:339).
8. Añadir: el chip inactivo crece al pasar el ratón (⋯ pasa de 0 a 30 px y aparece ✦) → poner ⋯ con `position:absolute` dentro de un padding reservado, o mostrarlo solo en el chip activo (vistas-enviar.css:95-96,184).
9. Inicio: las 20 propuestas de la IA no aparecen ni en la tira ni en Continúa (todo sale «Listo») → revisar iniDatos/pinta (shell.js:430-445). Antes, comprobar que la captura espera a la red: la de proyecto salió en esqueleto.
10. Extraído › Tareas: quitar «Vigentes» (es un filtro de Decisiones, no lleva número y ya existe «Solo vigentes») y quitar el chip «Por revisar 12», que repite el aviso «12 por revisar · Revisar» (carpeta.js:76,225).
11. Requisitos/Historias: «Exportar ▾ ▼» con dos flechas → quitar «▾» del texto del summary (requisitos.js:20-30, historias.js:25).
12. Decisiones: «Miércoles, 4 De Noviembre De 2026» → quitar `text-transform:capitalize` y usar `::first-letter` (vistas-decisiones.css:6).
13. Proyecto vacío: muestra «Ninguna/Ninguno/Ver todos» con «Generar resumen» y «Enviar proyecto» activos sobre 0 documentos (p_Proyecto_20vac_C3_ADo_resumen-1440.png) → zona de soltar «Suelta aquí el primer documento» y ocultar las dos acciones (carpeta.js:188).
14. Resumen de proyecto: pone «+ Datos del comunidad» (p_Comunidad_20Los_20Pinos_resumen-1440.png). A 390, «Generar resumen» se sale 15 px de la tarjeta y «Estado actual» se parte en 2 líneas → «+ Añadir datos» y cabecera en 2 filas por debajo de 700 px (carpeta.js:188, app.css).
15. Pestaña Documentos: la columna PROYECTO repite el proyecto, la cabecera ESTADO contiene «Mover» y el h2 repite el nombre de la pestaña. A 390, «Mover» cae en una x distinta en cada fila (p_Reservas_20App_documentos-390.png) → sin columna dentro de un proyecto, estado como badge y «Mover» en hover/⋯ (app.js:365-377).
16. Imagen: en Resumen no se ve la imagen (d_cccc3333_acta_normal_impcccc-1440.png) → miniatura de 160 px junto al título, o abrir las imágenes en Fuente (app.js).
17. Raíl a 390: la sombra del cajón cerrado asoma por el borde izquierdo (p_Reservas_20App_preguntar-390.png, cola-390.png) → `box-shadow` y `visibility` solo con el raíl abierto (app.css:567).
18. Diálogos: Añadir tiene título de 26 px, «×» y [Cancelar][Procesar]; Descargar tiene título de 17 px, sin «×», y [Descargar][Cerrar] → la misma cabecera y el mismo orden secundario·primario (descargar.js, vistas-enviar.css).
19. Comparar a 390: el select «Después» se sale por la derecha (p_Reservas_20App_comparar-390.png) → etiqueta encima y `width:100%` (carpeta.js:297, app.css).
20. Búsqueda: 8 chips con 0 resultados se pueden pulsar y a 390 ocupan 4 filas (buscar_ascensor-390.png) → ocultar los vacíos o plegarlos en «Más» (shell.js).
21. Primer arranque: el raíl, el buscador y «+ Añadir» siguen activos detrás del asistente, y sale «Proyecto vacÃo» (primer-arranque-1440-light.png) → #/uso sin cromo (shell.js, app.css); el mojibake se arregla en el backend con `encoding="utf-8"` en meta()/acta.json (app.py).
22. Plantillas: la plantilla de serie parece editable y «Duplicar» no se ve (ajustes_plantillas-1440.png) → campos de solo lectura atenuados y «Duplicar para editar» junto al título (plantillas.js).

## P3
23. Las 5 filas de Continúa y Biblioteca dicen «Listo» → mostrar el estado solo si no es «Listo» (shell.js:430 y la tabla de Biblioteca en shell.js).
24. En el proyecto hay dos «+ Añadir» y «··· Más ▾» repite la pista → ocultar el global en /p/* y dejar solo «⋯» (shell.js).
25. Textos: «propone «+ Nuevo»» (carpeta.js:345); «carpeta» frente a «proyecto»; en Pendientes, la cabecera «HECHO PENDIENTE» y un select «Cualquiera» sin etiqueta (shell.js:587-610).
26. Aviso de dudosos: la muestra amarilla de 14 px parece una casilla, y a 390 ocupa 3 filas (135 px) → icono ⚠ y una sola fila con «‹ ›» (app.css:306-307).
27. Pestañas a 390: se cortan sin ninguna pista («Inf…», «Preguntar») → máscara de degradado de 24 px en el borde (vistas-shell.css).
28. Riesgos/Preguntas/Hitos: el código es un input y «Origen» lo repite («R-001 … R-001 [01:00]») → código como texto y en origen solo la cita (registro.js).
29. Historias: select vacío sin etiqueta al pie de HU-001, y «En Curso» con mayúscula → placeholder «Épica…» u ocultarlo, y minúscula (historias.js).
30. Línea de tiempo con el chip «Documento» en cada fila; Informe sin ningún rango preseleccionado; Preguntar sin preguntas de ejemplo (carpeta.js, informe.js).
31. Táctil: a 390 se ven atajos de teclado (paleta, «J/K navegar»), y las filas de casillas de Descargar miden 25 px → `(pointer:coarse)` para ocultarlos y filas de 44 px (vistas-shell.css, vistas-enviar.css).
32. Oscuro y Ajustes: casillas grises rellenas → fondo transparente + `accent-color` (app.css). «Nombres» está en Proceso › Avanzado → moverlo a Apariencia (ajustes.js).
33. Enviar: iconos emoji de 16 px casi invisibles (Correo, Slack) y la píldora «Ejemplo» parece un botón → SVG de 24 px y etiqueta plana (enviar.js, vistas-enviar.css).

## Top 5
1. P1-1: que los dudosos se lean en oscuro (una línea en exportar.js).
2. P1-2: contadores por tipo en Extraído.
3. P1-4: una sola barra en Extraído, junto con P2-10 y P2-11.
4. P1-5 + P1-3: documento sin doble scroll y Ajustes › Enviar al entrar por enlace.
5. P2-6/7/8: Añadir con preset activo, pie sin hueco y chips que no saltan.

## Verificación R5 (2026-11-04)
Capturas en shots-r5b (46 rutas, con espera a que la red quede inactiva). Balance R5: 29 resueltos, 2 parciales, 1 abierto, 1 sin evidencia. R4 revisados: 7 resueltos, 2 parciales, 1 abierto, 1 sin evidencia.
- R4-2 resuelto: chip activo y pie sin hueco (p_Reservas_20App_resumen_formNuevo-390.png). R4-3 resuelto: el ⋯ ya va en posición absoluta (vistas-enviar.css:97-98). R4-4 resuelto a 1440: iconos en la esquina de la imagen (d_cccc3333_fuente-1440.png); a 390 hay regresión, ver N1. R4-5 resuelto: barra «2 seleccionados» (biblioteca_sel2-1440.png).
- R4-7 parcial: la fila «Cambiar a modo avanzado» sigue cortada bajo los atajos (paleta-1440.png, y≈658). R4-8 abierto: ver P2-9. R4-11 resuelto: una sola barra y sin «Vigentes». R4-12 parcial: sigue sin aparecer «Preguntar a … →» (buscar_ascensor-1440.png). R4-14 resuelto: un solo «+ Añadir» en /p/*. R4-15 resuelto: casillas transparentes en oscuro (biblioteca-1440-dark.png). R4-18 sin evidencia.
- P1-1 resuelto: los dudosos se leen en oscuro (d_aaaa1111_acta_normal_impaaaa-1440-dark.png).
- P1-2 resuelto: «Todas 1» en Riesgos y «Todos 3» en Requisitos (p_Reservas_20App_riesgos-1440.png, p_Reservas_20App_requisitos-1440.png).
- P1-3 resuelto (ajustes_enviar-1440.png).
- P1-4 resuelto: una fila de barra en Decisiones, Requisitos, Historias, Interesados y Riesgos (p_Reservas_20App_decisiones-1440.png).
- P1-5 parcial: el iframe ya se mide y hay `scrollbar-gutter`, pero la página aún desborda ≈45 px y conviven dos barras de scroll (d_aaaa1111_acta_normal_impaaaa-1440.png).
- P2-6, 7 y 8 resueltos (p_Reservas_20App_resumen_formNuevo-1440.png y -390.png).
- P2-9 abierto: Inicio no muestra ni «N por revisar» ni «N listos para enviar», mientras el proyecto dice «12 por revisar» (inicio-1440.png). El proyecto cuenta con `contadores.por_revision.propuesto` (carpeta.js:27) e Inicio filtra `items.revision==="propuesto"` (shell.js:451); hay que usar los contadores y comprobar que el `.then` de shell.js:449-470 llega a pintar.
- P2-10, 11 y 12 resueltos (p_Reservas_20App_pendientes-1440.png, p_Reservas_20App_requisitos-1440.png, p_Reservas_20App_decisiones-1440.png).
- P2-13 resuelto: zona de soltar y sin acciones (p_Proyecto_20vac_C3_ADo_resumen-1440.png).
- P2-14 resuelto (p_Comunidad_20Los_20Pinos_resumen-1440.png, p_Reservas_20App_resumen-390.png).
- P2-15 parcial: la columna Proyecto ya no está, pero ESTADO queda vacía y a 390 el título sigue 20 px más adentro que la fecha (p_Reservas_20App_documentos-1440.png y -390.png).
- P2-16 resuelto: las imágenes abren en Fuente. P2-17 resuelto (app.css:566 + p_Reservas_20App_preguntar-390.png). P2-18 resuelto (d_aaaa1111_acta_normal_impaaaa_Descargar_ab-1440.png). P2-19 resuelto (p_Reservas_20App_comparar-390.png). P2-20 resuelto: sin chips vacíos. P2-21 sin evidencia: no se recapturó el primer arranque. P2-22 resuelto (ajustes_plantillas-1440.png).
- P3-23 a P3-33 resueltos (inicio-1440.png, pendientes-1440.png, p_Reservas_20App_ajustes-1440.png, d_aaaa1111_acta_normal_impaaaa-390.png, p_Reservas_20App_riesgos-1440.png, p_Reservas_20App_historias-1440.png, p_Reservas_20App_informe-1440.png, p_Reservas_20App_preguntar-390.png, paleta-390.png, p_Reservas_20App_revision-390.png, ajustes_general-1440.png, enviar-390.png).

### Nuevos/regresiones
- N1 P1 · Fuente a 390: la imagen baja ≈75 px y tapa «Tu descripción» (d_cccc3333_fuente-390.png, d_cccc3333_acta_normal_impcccc-390.png). `.fu-img .fu-fig{top:calc(61px + …)}` también se aplica cuando no es sticky → llevar ese `top` dentro de `@media(min-width:861px)` (app.css:789, vistas-shell.css:196).
- N2 P2 · Descargar a 390: con filas de 48 px, «Formato» queda bajo el pie y Excel/CSV asoman por debajo del diálogo (d_aaaa1111_acta_normal_impaaaa_Descargar_ab-390.png) → cuerpo con `min-height:0;overflow:auto` y Formato antes de «Qué descargar» por debajo de 700 px (descargar.js, vistas-enviar.css).
- N3 P3 · Biblioteca y Documentos: la columna ESTADO sale vacía en todas las filas desde que se quitó «Listo» (biblioteca-1440-dark.png, p_Reservas_20App_documentos-1440.png) → ocultarla si ninguna fila tiene estado (shell.js, app.js:369-377).
- N4 P3 · Chips inactivos: el hueco reservado para ✦/⋯ descentra el texto unos 20 px («Pack comité», «Resumen y puntos clave») (d_aaaa1111_acta_normal_impaaaa_Descargar_ab-1440.png) → reservar solo a la derecha y con padding simétrico (vistas-enviar.css:91-98).
- N5 P3 · Línea de tiempo: la fecha queda pegada al borde izquierdo de la tarjeta (x=257) (p_Reservas_20App_linea-1440.png) → padding-left de 16 px en la fila (carpeta.js, app.css).
- N6 P3 · Añadir: «Tareas, Decisiones → documento del proyecto», bajo los chips, repite «2 salidas: tareas, decisiones» del pie → dejar uno de los dos (enviar.js, shell.js:339).
- N7 P3 · Búsqueda a 390: «Todo 2» y «Decisiones 2» salen en filas distintas aunque caben juntas, porque el separador fuerza el salto (buscar_ascensor-390.png) → ocultar el separador por debajo de 700 px (shell.js, vistas-shell.css).
- N8 P3 · Riesgos a 1440: queda un hueco de 50 px entre «Aprobar» e «Historial» donde está «Descartar» oculto (p_Reservas_20App_riesgos-1440.png) → `display:none` fuera del hover (registro.js, app.css).
- N9 P3 · Fuente: «Texto · 1 partes» → singular (app.js).
