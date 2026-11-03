# Crítica ronda 4

Resueltos desde R3: Extraído (1440) limpio, Pendientes en grid, Inicio con soltar compacto, Enviar en 3 tarjetas, Búsqueda con contadores, Ajustes plegado. Persisten los arrastres declarados.

P1
1. Móvil /p/* — «+» superior y FAB a la vez; el FAB tapa texto («plan de migración de dat…») → ocultar «+» ≤700px en proyecto, padding-bottom 80px (shell.js, vistas-shell.css).
2. Añadir — sigue la pila: soltar + presets + «Guardar como preset» huérfano + «Personalizar» + píldora de ajustes; en móvil «Procesar» tapa la píldora → 3 presets + «Más» en una línea, «Guardar preset» dentro de «Más», ajustes como texto bajo el botón, «Procesar» fijo con sombra (enviar.js, vistas-enviar.css).
3. Añadir — «×» con anillo azul permanente, «Más ▾» con doble borde, ✦ y ⋯ en todos los chips → foco inicial en «Elegir archivos», ✦/⋯ solo en activo/hover (enviar.js).
4. Documento imagen — «Abrir el original / Describir con IA» lejos de la imagen; hueco bajo ella y columna IA larguísima → iconos en la esquina de la imagen, imagen sticky, IA plegada a 5 líneas + «Ver más» (app.js).
5. Biblioteca — tres filas de filtros, 400 px vacíos, sin barra al seleccionar; raíl dice 2, vista «3 de 3» → una fila (buscar | tipo | Estado | Fecha | vista), «Esta semana/Solo buscable/En cola» en menú «Rápidos», barra flotante (Descargar, Enviar, Mover), contador 3 (shell.js).
6. Descargar — anillo doble en «Acta en PDF», formatos tachados sin motivo visible, hueco antes de «Opciones» → preseleccionar «Acta en PDF» y activar «Descargar», opacidad .45 + tooltip, subir «Opciones» (descargar.js, vistas-enviar.css).

P2
7. Paleta — «+» ×5, sin «Recientes», filas cortadas por scroll, doble borde en el campo → iconos propios, «Recientes» primero, 4 por grupo + «Ver más», atajos visibles (shell.js).
8. Inicio — «Por revisar» es tarjeta ancha para una línea y repite Pendientes (5); «Continúa» con 140 px vacíos → banda de 56 px arriba «5 por revisar → Revisar», tarjetas de igual altura (shell.js).
9. Inicio móvil — «Suelta archivos» no aplica en táctil; compite con «+» → título «Añadir», un botón (shell.js).
10. Pendientes móvil — responsable y plazo flotan a la derecha en dos líneas sueltas → una fila meta «Proyecto · Responsable · Plazo» a la izquierda (vistas-shell.css).
11. Extraído — dos filas de chips + dos selects, «Decisiones» duplicado (tipo y estado); «Tarea» + «Descartar» subrayado en cada fila; formulario manual de 3 campos → renombrar estado, selects a «Filtros», «Descartar» solo en hover/⋯, ocultar «Tarea» si filtro=Tareas, alta manual en una línea (carpeta.js, app.css).
12. Búsqueda — «Respuesta» es select + botón sin respuesta; título pegado a los chips → «Preguntar a Migración CRM →» en una línea, 16px de aire (shell.js).
13. Enviar — 80 % vacío, tarjetas sin icono ni estado → icono por destino, «Sin conectar», 2 recetas de ejemplo debajo (enviar.js, vistas-enviar.css).

P3
14. Tipografía/botones — overline en 3 estilos; alturas 44/36/32 mezcladas; «Nuevo» global duplica «Añadir» en proyecto → un token overline, alturas 28/36/44 (app.css).
15. Paridad claro/oscuro — oscuro correcto, pero bordes de tarjeta casi invisibles y casillas grises pesadas; claro: gris secundario ~4,3:1 → bordes +1 paso, secundario #4b5563 (app.css).
16. Resumen de proyecto — «Añadir datos del proyecto +» suelto fuera de la tarjeta; «Desde el documento anterior» en 3 tarjetas de 3 líneas → mover a «Más», chips «+1 · +3 · +4» (carpeta.js).
17. Raíl — engranaje superior y «Ajustes» abajo duplicados → quitar uno (shell.js).
18. Delight — nada se anima; entrada 120 ms y tachado animado, respetando «Animaciones» (app.css).

## Top 5
1. Móvil: ocultar «+» superior en /p/* y que el FAB no tape contenido.
2. Añadir: hoja simple, foco inicial correcto, Procesar fijo.
3. Biblioteca: una fila de filtros + barra al seleccionar.
4. Imagen: acciones como iconos sobre la imagen, IA plegada.
5. Paleta: iconos distintos, «Recientes», grupos cortos.
