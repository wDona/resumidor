# Rediseño: de «actas» a «añadir → procesar → revisar → enviar»

Objetivo (usuario, 2026-11-03): UI mucho más simple, pocos clics, menos opciones a la vista, mejor uso del espacio, flujo evidente.
**No se quita ninguna función: solo se esconden** (menú ⋯, «Más», Opciones avanzadas, modo avanzado, paleta Ctrl+K).
Reorientación: meter información de cualquier archivo (vídeo, audio, PDF grande, md/txt/docx, capturas con descripción, enlaces) → hacerla buscable → «mascarla» (resúmenes, acta, informe…) → sacar información (tareas, decisiones, requisitos, historias…) → exportar/enviar en un clic (archivo local, carpeta/Obsidian, API, webhook, servidor propio), también automático.
Cada función accesible desde un sitio central y, de forma redundante, desde su menú contextual y la paleta Ctrl+K.

## Flujo visible en toda la app

`1 Añadir → 2 Procesar → 3 Revisar → 4 Enviar` (tira con contadores clicables en Inicio: «En cola 2 · Por revisar 14 · Listo para enviar 6 · Enviado hoy 3»).

## Arquitectura de pantallas

- **Marco**: barra superior = logo · omnibox Buscar/Preguntar (tecla `/`, alcance: todo/proyecto/documento) · indicador de cola (anillo de progreso) · botón primario «+ Añadir» · ⚙. Raíl izquierdo plegable (iconos+texto → solo iconos): Inicio, Biblioteca, Pendientes, Enviar, — Proyectos (lista + «Nuevo») —, abajo Ajustes. Paleta **Ctrl+K**: navegación + todas las acciones (incluidas las escondidas) + búsqueda. Ancho completo, densidad media, tokens actuales de `static/app.css`, claro/oscuro.
- **Inicio (centro)**: zona de soltar grande («Suelta archivos, pega una captura (Ctrl+V) o un enlace») con iconos de tipos + «Receta al terminar» resumida en una línea (Resumir ✓ · Extraer tareas y decisiones ✓ · Enviar a: Obsidian ▾) · tira del flujo · «Continúa» (recientes) · Pendientes (5) · Por revisar. Estado vacío con 1 frase y 3 acciones.
- **Añadir (hoja/modal, no página)** — lo principal es el **OBJETIVO**, no la configuración (petición expresa del usuario):
  1. Archivos/enlace/zip/captura (zona de soltar; lista con tipo detectado). Un **.zip con muchos archivos** se desempaqueta y cada archivo compatible entra en la cola, uno tras otro, en el proyecto elegido (el .zip exportado por la app sigue importándose como antes).
  2. **¿Qué quieres sacar y dónde?** lista de casillas, protagonista (SIN lenguaje natural): una fila por cosa — ☑ Tareas → [Jira · PROJ ▾] · ☑ Decisiones → [Documento en el proyecto ▾] nombre [Comité 28-oct · Decisiones] · ☑ Riesgos → [Documento en el proyecto ▾] nombre […] · ☐ Requisitos · ☐ Historias · ☐ Resumen · ☐ Documento completo; cada fila con selector de destino (documento en el proyecto, archivo local, destinos configurados, «+ configurar…») y nombre opcional; «Guardar como receta». Arriba, tarjetas de objetivo como atajos que marcan casillas: (icono + 1 línea), elegidas según perfil de uso: «Acta de reunión» (tareas+decisiones) · «Requisitos e historias» · «Resumen y puntos clave» · «Seguimiento de proyecto / informe» · «Entrevista» · «Apuntes de clase» · **«Solo hacerlo buscable»** (indexar sin resumir: barato, ideal para PDFs grandes) · «Otro…» (todas las plantillas). Objetivo = plantilla + qué extraer + receta de envío por defecto.
  3. Proyecto (por defecto el actual) y, en una línea, «Al terminar: enviar a [destino ▾]».
  4. Botón «Procesar N archivos». Todo lo técnico (Rápido|Calidad, nivel/modelo, idioma, hablantes, nube, cookies, solo audio, transcripción propia, longitud breve/normal/detallado) va en «Ajustes de procesado ▸» plegado, con un resumen de una línea («Calidad · español · local»). También: Grabar, Pegar captura (con campo descripción).
- **Biblioteca**: una sola lista de todo (sustituye «Documentos»): chips de tipo (vídeo, audio, PDF, texto, imagen), proyecto, estado, fecha; selección múltiple → Enviar/Mover/Exportar; panel derecho de vista previa (resumen + acciones) sin salir de la lista.
- **Documento**: cabecera (título, tipo, proyecto, estado) + barra de acciones: [Preguntar] [Enviar ▾ (último destino, 1 clic)] [Exportar ▾] [⋯ Renombrar, Mover, Anonimizar, Correo, Vídeo condensado, Buscar a fondo, Descargar zip/con vídeo, Versiones, Dudas]. Pestañas: **Resumen | Extraído (n) | Fuente | Preguntar**. Fuente = vídeo+transcripción, o páginas PDF con texto, o imagen + OCR + descripción. Citas `[mm:ss]` o `p. 12` / `§ Título` saltan a la fuente.
- **Proyecto (carpeta)**: de 15 pestañas a 5: **Resumen** (estado actual, KPIs, pendientes, actividad) · **Documentos** · **Extraído** (segmentado con contadores, solo los no vacíos: Tareas · Decisiones · Requisitos · Historias · Interesados · Riesgos · Preguntas · Hitos; aviso «14 por revisar · Aprobar todo · Revisar») · **Informe** · **Preguntar**. «⋯ Más»: Línea de tiempo, Comparar, Glosario, Regenerar con IA, Derivar historias, Deshacer pasada IA, Ajustes del proyecto.
- **Buscar** (resultado del omnibox): Respuesta con citas (si es pregunta) · Fragmentos (snippet + `[mm:ss]`/`p. N`/imagen) · Elementos (tareas, decisiones, historias…) · filtros tipo/proyecto/fecha.
- **Enviar (centro de salida)**: Destinos (tarjetas con estado + Probar) · Recetas automáticas («Cuando termine un documento en [proyecto/tipo] → [qué] → [destino]», interruptor, vista previa) · Historial (enlace externo, reintentar) · catálogo «+ Destino» por grupos: Local (Carpeta, Obsidian/Logseq), Tareas (Jira, Linear, GitHub, GitLab, Azure DevOps, Todoist, Trello…), Notas/wiki (Notion, Outline, BookStack, Joplin, Confluence), Mensajería (Slack, Teams, Discord), Mensajería (Slack, Teams vía Workflows), Servidor propio / VPS (SFTP/SSH con el cliente OpenSSH del sistema, S3 compatible: MinIO/Garage/B2/R2, WebDAV/Nextcloud, Webhook → n8n/Zapier/Make, Gitea/Forgejo, GitLab/Jira autoalojados, Paperless-ngx, Outline, BookStack; URL base configurable y TLS autofirmado opcional), Correo SMTP.
- **Ajustes**: General | Modelos | Plantillas | Enviar | Avanzado (niveles, nube, perfiles de uso, modo simple/avanzado). Modo simple = esta UI limpia; avanzado = muestra lo escondido en línea.

## Envío programado (petición del usuario)

Recetas con disparador «Al terminar un documento» **o** «Programado: cada día / semana [lunes] / mes a las [09:00]». Qué enviar: lo mismo que el checklist (tareas, decisiones, riesgos, informe de estado regenerado, documento resumen del proyecto…) con «solo lo nuevo desde el último envío» (por defecto) o todo. Si la app estaba cerrada a esa hora, se envía al abrirla (marcado «atrasado»). Próximo envío visible en la receta + «Enviar ahora». En Añadir/Proyecto: «Repetir cada semana» en una línea.

## Imágenes con IA (petición del usuario, adelantado de M3)

Imágenes/capturas: OCR + **descripción por IA** (modelo local con visión: el mismo modelo si es multimodal + mmproj, o LM Studio/Ollama; nube solo con «Permitir enviar imágenes a la nube», apagado) + descripción del usuario editable; todo buscable. Opcional «Describir capturas con IA» para las capturas de vídeo incluidas en el documento. Sin modelo con visión → aviso para instalar uno recomendado.

## Enlaces inteligentes (decidido, siguiente lote)

Pegar enlace → detecta: vídeo/audio (yt-dlp, como hoy) · archivo directo PDF/docx/md/zip/imagen (descarga y procesa como soltado) · página web (extrae el texto del artículo) · OneDrive/SharePoint (propone la carpeta sincronizada).

## Documentos ya procesados → proyecto (decidido, siguiente lote)

- **De la app:** «Añadir a proyecto» desde Documento (⋯ y botón), Biblioteca (selección múltiple) y arrastrando al proyecto del raíl. Sin reprocesar: el proyecto incorpora sus tareas/decisiones/riesgos/requisitos a su registro (poblar), aplica sus recetas «al terminar» si el usuario marca «enviar también» y queda buscable en el proyecto.
- **De fuera:** importar .zip exportado por Actas (otro PC/compañero) directamente en un proyecto elegido (hoy solo global); actas/informes ya hechos por personas (Word/PDF/md) con la opción «Ya está hecho, no resumir»: se guarda tal cual, se indexa y se extraen sus elementos al proyecto con cita.

## Ideas aprobadas por el usuario (siguiente lote)

1. **«Enviar a → Actas» y menú contextual en Windows** (instalador: acceso en `shell:sendto` + entrada «Procesar con Actas» en HKCU para archivos y carpetas): si la app está abierta, encola por la API local; si no, la abre y encola. Van al proyecto por defecto (o «Bandeja») con aviso «3 archivos en cola · cambiar proyecto». macOS (Acción rápida) después.
2. **Arrastrar desde Outlook**: toda la ventana acepta soltar; adjuntos y correos arrastrados desde Outlook. Correos como entrada: **.eml** (stdlib `email`) y **.msg** (lectura mínima OLE, sin dependencias GPL): cuerpo = documento, adjuntos = documentos hijos encolados en el mismo proyecto.
3. **Enlaces inteligentes** (ver arriba): páginas web y artículos → texto del artículo.
4. **Importar de vuelta desde Excel/CSV**: tareas, requisitos, riesgos, historias editados fuera vuelven al proyecto emparejando por código/ID (los exportes ya lo llevan); vista previa de cambios (nuevos, modificados, sin cambios, filas desconocidas) antes de aplicar; nunca borra; deshacer con el mecanismo del registro. Lectura xlsx con stdlib (zip+xml).

Reparto: **B3 Windows/Microsoft** (Graph, Outlook COM, Enviar a/menú contextual, .eml/.msg, arrastre Outlook) · **B4 Entrada/registro** (enlaces inteligentes, documentos procesados → proyecto, importar de vuelta Excel/CSV).

## Microsoft 365 (petición del usuario: «todo lo que se pueda»)

- **Sin permisos de TI (B2):** OneDrive/SharePoint = carpeta sincronizada autodetectada (Word/Excel/PDF); Teams = webhook de Workflows; **Power Automate** = el mismo disparador con JSON documentado → el flujo del usuario crea tareas de Planner/To Do, elementos de Lists, páginas de OneNote, archivos de SharePoint o correos de Outlook con sus propios permisos; Azure DevOps con PAT; exportes Office nativos (docx, xlsx, pptx).
- **B3 (después de B2):** «Iniciar sesión con Microsoft» (Graph, flujo device code, client ID/tenant configurables porque requiere registrar una app en Entra, posible consentimiento de administrador): subir a OneDrive/SharePoint, Planner, To Do, OneNote, mensaje a canal/chat de Teams, enviar correo con Outlook. Outlook clásico en Windows por COM vía PowerShell (sin dependencias): crear borrador con adjunto y mostrarlo. «Abrir en Word/Excel» tras descargar.
- **Entrada:** transcripciones de Teams (.vtt/.docx, ya soportado); grabaciones de Teams desde la carpeta de OneDrive sincronizada (carpeta vigilada, M3); enlaces privados de Stream/SharePoint suelen fallar → descarga manual.

## Exportación automática por carpeta/proyecto (petición del usuario)

Proyecto › Ajustes › **Automático**: recetas de esa carpeta (al terminar cada documento + programadas), editables ahí mismo, con el mismo checklist «qué → dónde» y formatos. Son el plan por defecto: Añadir dentro del proyecto llega con las casillas ya marcadas según la carpeta (desmarcar = no se envía ese documento). Visible en la cabecera del proyecto en una línea («Auto: tareas → Jira · decisiones → OneDrive · cada lunes informe → Teams»), clic → editar. También en Enviar › Recetas agrupadas por proyecto.

## Descargar fácil (petición del usuario)

Panel «Descargar» (desde Documento › Exportar ▾, Biblioteca con selección múltiple, Proyecto, Ctrl+K): casillas de **qué** (Documento completo, Resumen, Tareas, Decisiones, Riesgos, Requisitos, Historias, Interesados, Informe, Transcripción) × chips de **formato** de selección múltiple (PDF, Word, Markdown, Excel, CSV; «Más formatos»: Obsidian, Notion, ics, Jira/Azure/Planner CSV, srt/vtt, json) + «solo aprobados» → botón «Descargar» (1 archivo directo; varios → .zip). Recuerda la última selección. La fila «archivo local» del checklist de Añadir usa los mismos formatos.

## Esconder (sigue accesible por ⋯ / Más / Ctrl+K / avanzado)

Comparar, Glosario, Vídeo condensado, Buscar a fondo, Derivar, fusionar/separar/matriz, niveles de calidad, nube, Importar .zip, formatos CSV/srt/vtt/notion.zip («Más formatos»), detalle de modelos, cookies de navegador, transcripción propia.

## Fases

- **M1 (paralelo)**: (D) lienzo de diseño con estas pantallas · (B1) ingesta PDF/md/txt/docx/imagen + zip de lote + modo «solo buscable» + búsqueda global · (B2) destinos + envío en 1 clic + recetas automáticas + historial.
- **M2**: implementar la UI según el lienzo (marco+Inicio+Añadir+paleta → Biblioteca+Documento+Buscar → Proyecto+Enviar+Ajustes) + QA en navegador.
- **M3**: descripción automática de capturas con VLM local (Florence-2/Qwen-VL vía Ollama/LM Studio), carpeta vigilada, servidor MCP / API de búsqueda para otras herramientas, más destinos (S3, SFTP).

## Reglas del repo

- Nunca escribir la palabra RELEASE en commits (dispara CI de publicación).
- Un `.py` nuevo se añade también a `installer/actas.iss` y `installer/macos/build.sh`.
- Tests: `ACTAS_NO_EMBED=1 uv run pytest -q` (offline). Sin dependencias pesadas; stdlib primero.

## Decisiones tomadas sin preguntar (usuario ausente, 2026-11-03)

1. Trabajo en la rama local **`rediseno`** con commits de control; `master` intacto; sin push ni release.
2. «Solo buscable» no dispara envíos ni recetas (no hay nada extraído que enviar).
3. Imágenes a la nube apagado por defecto; visión local opcional = Gemma 4 E4B + mmproj (~1 GB, no se instala sola).
4. PDFs muy largos: el resumen final usa como máximo 14k caracteres de las partes (cabe en el 4B); resumen jerárquico = mejora pendiente.
5. Microsoft Graph: client ID/tenant configurables, sin valor por defecto (hace falta registrar una app en Entra).
6. Enlaces: solo http/https; red local/privada bloqueada salvo ajuste `enlaces_red_local`.
7. Notion «actualizar» = archiva la página anterior y crea otra.
8. El plan de un trabajo (checklist de Añadir) sustituye a las recetas «al terminar» de su carpeta para ese documento: nunca se envía dos veces.
9. Con «Anonimizar por defecto», si falta la copia anonimizada no se envía nada (error en historial); nunca sale vídeo/audio.
10. Tests: `test_hardening::test_pdf_limpieza_no_es_500` y `test_nube::test_claude_argv_y_utf8` fallan en esta máquina también sin cambios (entorno); se excluyen al validar.
11. Servidor MCP apagado por defecto, solo desde este equipo y con token; con «Anonimizar por defecto» activo no entrega contenido a herramientas externas (pueden usar la nube). `encolar` solo con permiso explícito.
12. Carpetas vigiladas: un archivo entra cuando su tamaño/fecha no cambian en dos pasadas (10 s); «Mover a Procesados/» apagado por defecto.
13. Correos .eml/.msg: el cuerpo es el documento y los adjuntos compatibles entran en la cola en el mismo proyecto (un adjunto que falla no impide el correo). Un .eml descargado por enlace se lee, pero sus adjuntos no se encolan.
14. «Ya está hecho, no resumir» solo para documentos de texto; extrae tareas/decisiones/riesgos/requisitos al proyecto vía poblar.
15. «Añadir a proyecto» no reenvía nada salvo que se marque «Enviar también».
16. Importar de vuelta desde Excel/CSV: nunca borra; las filas nuevas entran como manuales aprobadas (sin cita) y todo el lote se puede deshacer.
