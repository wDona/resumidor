# Plan: Actas → herramienta para PM y analistas funcionales (v0.7.0 base)

## Principios

- **IA primero:** las vistas se pueblan automáticamente con IA (entran como `propuesto`, con cita verificada `[mm:ss]`); el humano revisa/edita y/o exporta.
- **Exportar NO exige aprobar:** sale todo; lo no revisado va marcado «BORRADOR / sin revisar»; conmutador «solo aprobados».
- **Nada sin cita de origen:** lo derivado (historias/Gherkin) se marca «Propuesta, no dicha en la reunión».
- **Local/offline por defecto;** sin dependencias pesadas.
- **Pruebas con modelo vía passthrough de suscripción** (CLI `claude`/`codex`), NO con modelo local.

## Hallazgos del código

| Área | Hallazgo |
|---|---|
| `plantillas.py` | `SERIE`/`base()`/`sec(id,nombre,descripcion,campos,nunca)`; `pipeline._prompts()` convierte secciones en esquema de extracción con cita; `pipeline.gen_check()` verifica cita y cifras. `cache_keys()` no usa el dict de plantilla → se pueden añadir claves (`seguir`) sin invalidar cachés. `plantillas.validar()` debe conservar `seguir`. |
| `carpetas` | `ACCION` es un set fijo de ids; `items_doc()` solo recoge tareas. `SUGERIDOS["proyecto"]` ya existe. |
| Preguntar | `/api/preguntar` con `sel="c:<carpeta>"` ya usa `rag.Multi`; `carpetas.pregunta_pendientes()` responde sin LLM. |
| Base de decisiones e informe | `carpetas.vigentes()`, `comparar()`, `estado_actual()`, `_redactar()`. |
| `exportar.py` | `_csv`, `csv_jira`, `docx_bytes` (`base_docx`, `estilo_para`), `pdf_bytes`, `FORMATOS`. `python-docx` y `lxml` en `uv.lock`; `openpyxl` no; `python-pptx` no. |
| UI / tests | JS sin framework (`el()`, `api()`, `post()`, `fLink()`); `carpeta.js` con `FTABS`. Tests pytest + TestClient (`test_carpetas.py`). |

## Fases

| Fase | Contenido | Esfuerzo | Dependencias |
|---|---|---|---|
| F1 | Rápidas (1a, 1c, 1b+1d en paralelo) | 2-3 d | — |
| F2 | Almacén SQLite + migración | 4-5 d | Bloquea el resto (salvo F1) |
| F3 | Bandeja y API genérica | 3-4 d | F2 |
| F3b | Job `poblar` y extractores por vista | — | F3 |
| F4 | Vistas (en paralelo, un JS por vista) | — | F3 / F3b |
| F5 | Derivación requisitos → historias | 3 d | F2, F3b |
| F6 | Informe de estado/comité | 4-5 d | F3 / F3b |
| F7 | Preguntar al proyecto | 2 d | Solo F2 |

### F1 Rápidas (2-3 d; 1a, 1c, 1b+1d en paralelo) ✅ hecho en código (sin verificar en navegador)

**1a. `plantillas.py`**: nuevas plantillas (máx. 5-6 secciones cada una).

| Plantilla | Secciones |
|---|---|
| `raid` | riesgos [probabilidad, impacto, responsable; `seguir=riesgo`], supuestos, incidencias [gravedad, responsable], dependencias [de_quien, plazo], decisiones, tareas |
| `requisitos` | requisitos [tipo_req, prioridad, solicitante], interesados [rol, organizacion, actitud], preguntas [dirigida_a], restricciones, decisiones |
| `comite` | decisiones, hitos [fecha, estado], riesgos, escalados, tareas |
| `daily` | — |
| `retro` | — |

Descripciones «solo si se dice»; probabilidad/impacto/poder/interés no se infieren.

**1b. `sec(..., seguir=None)`** con valores: tarea, riesgo, incidencia, supuesto, dependencia, pregunta, requisito, decision, interesado, hito.
- `validar()` lo conserva.
- `carpetas.items_doc()` usa `seguir` de `d["tpl"]` con fallback a `ACCION`; el ítem lleva `tipo_ent`.
- Selector en `static/plantillas.js`.
- Marcar `seguir` en las plantillas de serie existentes.

**1c. `exportar.py`**
- `csv_azure`: Work Item Type, Title, Description, Assigned To, Tags, Priority.
- `csv_planner`: Task Name, Bucket, Assigned To, Start Date, Due Date, Priority, Notes.
- Añadir a `FORMATOS`, `exportar()` y `static/exportar.js`.

**1d. `carpetas.py`**
- `TIPO_PERFIL` gana raid/requisitos/comite/daily/retro → «Proyecto».
- `SUGERIDOS["proyecto"]`: Código, Cliente, Sponsor, Jefe de proyecto, Fase, Fecha de inicio, Fecha fin prevista, Presupuesto.

**Tests:** `plantillas._selftest`, `pipeline._selftest`, caso `seguir=riesgo` en `test_carpetas.py`, cabecera+fila de cada CSV en `test_exportar.py`.

### F2 Almacén SQLite + migración (4-5 d, bloquea el resto) ✅ hecho en código (sin verificar en navegador)

`registro.py` (sqlite3 stdlib, `work/registro.db`, WAL, `foreign_keys`, `user_version`).

| Tabla | Campos / valores |
|---|---|
| `proyecto` | carpeta, tipo, datos, ajustes, glosario, extra |
| `entidad` | id (uuid corto), proyecto_id, tipo [decision\|tarea\|riesgo\|incidencia\|supuesto\|dependencia\|requisito\|historia\|pregunta\|interesado\|hito], codigo, titulo, detalle, estado, revision [propuesto\|aprobado\|descartado\|fusionado], origen [reunion\|manual\|derivado\|migrado], dueno, prioridad, fecha_limite/alta/cierre, campos JSON, mid, ver, ruta, h, editado, sugerencia, fusionado_en, orden, creado, modificado, `UNIQUE(proyecto_id,mid,h)` |
| `cita` | — |
| `relacion` | a, b, tipo [deriva_de\|sustituye\|bloquea\|mitiga\|afecta\|responde\|solicita\|fusion], propuesta |
| `historial` | accion, antes, despues, lote |
| `informe` | — |

**Funciones:** `conectar`, `proyecto`, `crear`, `editar`, `borrar` (lógico), `fusionar`, `deshacer` (por lote), `historial`, `listar`, `sincronizar` (idempotente, por `(mid,ruta)` luego `(mid,h)`; lo que desaparece → `campos.huerfano`), `migrar_json`.

- `carpetas.py` usa `registro.py` sin cambiar su API pública.
- Migración de `expedientes.json` en una transacción; renombrar a `expedientes.json.migrado`; rollback = borrar `registro.db` y restaurar el nombre.
- Ítems antiguos entran `aprobado`, origen `migrado`.
- **Aceptación:** mismos pendientes/estados/notas antes y después; `test_carpetas.py` pasa sin cambios.

### F3 Bandeja y API genérica (3-4 d) ✅ hecho en código (sin verificar en navegador)

**API `/api/reg`:**

| Método | Función |
|---|---|
| GET | lista con filtros |
| POST | crear |
| PATCH | edición inline |
| DELETE | descartar |
| POST | revisar `{ids,accion}`, fusionar, deshacer, relacion |
| GET | historial, bandeja |

**UI `static/registro.js`:** tabla genérica editable (inputs nativos, guardado al salir), selección múltiple, filtros, columna Origen con `fLink()`, insignias IA·Propuesto/Derivado/Manual, panel de historial, atajos A/D/E/J/K/F, «Aprobar todo».

**`carpeta.js` FTABS:** Revisión(n), Requisitos, Historias, Interesados, Decisiones, Informe.

**Tests** con TestClient.

### F3b Job `poblar` y extractores por vista (nuevo) ✅ hecho en código (sin verificar en navegador)

- Al terminar cada reunión de un proyecto (ajuste «Poblar proyecto automáticamente», por defecto activado; también a demanda) la cola ejecuta una pasada transversal (independiente de la plantilla) que extrae requisitos, decisiones, interesados (rol), riesgos y preguntas abiertas con cita verificada → `propuesto`.
- Luego deriva historias+Gherkin (F5) y regenera el borrador del informe del periodo.
- Un prompt+esquema por vista, LLM en exclusiva.
- Botón «Regenerar con IA» por vista: respeta `editado=1`, aprobado y descartado; solo añade lo nuevo y propone fusiones.
- Medir coste/tiempo con `eval/score.py`.

### F4 Vistas (en paralelo, un JS por vista) ✅ hecho en código (sin verificar en navegador)

| Vista | Fichero | Contenido |
|---|---|---|
| Requisitos | `static/requisitos.js` | REQ-n, titulo, detalle, tipo_req, MoSCoW, solicitante (relación `solicita`), criterios, estado (borrador/validado/aprobado/rechazado/implementado), versión; tabla editable agrupable, filtros, columna de trazabilidad; duplicar, fusionar, descartar, deshacer, historial. |
| Historias | `historias.js` | HU-n, como/quiero/para, criterios Gherkin, puntos, épica, estado (backlog/preparada/en curso/hecha), `deriva_de`; kanban drag&drop nativo + tabla; editor Gherkin con vista previa. |
| Interesados | `interesados.js` | nombre, rol, organización, poder 1-5, interés 1-5, actitud, estrategia por cuadrante, canal, notas; matriz poder/interés 2×2 con chips arrastrables (soltar fija poder/interés), color por actitud, menciones con `[mm:ss]`; fusión de duplicados. |
| Decisiones | `decisiones.js` | D-n, titulo, contexto, alternativas, consecuencias, decisor, fecha, estado (vigente/sustituida/revocada), `sustituye`; línea de tiempo vertical estilo ADR, sustituidas tachadas con flecha a la vigente. |

**F4d. `export_registro.py`:** `exportar(c,vista,fmt,borrador)` → `(bytes,nombre,mime)`.
- Formatos: DOCX corporativo, PDF, XLSX, CSV, MD, JSON, `.feature`, CSV Jira (Story+Gherkin) y Azure (User Story + Acceptance Criteria).
- Extraer en `exportar.py` `doc_base(est)` y `pdf_html(html)`.
- Endpoint `GET /api/reg/exportar`.

### F5 Derivación requisitos → historias (3 d) ✅ hecho en código (sin verificar en navegador)

- `derivar.py` como trabajo de cola (op `derivar`).
- 1-3 historias por requisito, 1-4 escenarios Gherkin, preguntas abiertas.
- Usar solo lo recibido; si falta dato → pregunta; filtro de cifras con `rag.bad_nums`.
- Salida: `origen=derivado`, `revision=propuesto`, `criterios[].propuesta=true`, relación `deriva_de`, cita heredada.
- `test_derivar.py` con chat falso.

### F6 Informe de estado/comité (4-5 d) ✅ hecho en código (sin verificar en navegador)

- `informe.py`:
  - `kpis(c,desde,hasta)` determinista: tareas abiertas/vencidas/cerradas, riesgos por severidad y top 5, decisiones del periodo, requisitos/HU por estado, preguntas abiertas, hitos, serie de tareas abiertas.
  - `semaforos_sugeridos`: Global, Alcance, Plazo, Coste, Riesgos; con justificación editable.
  - `redactar()` reutiliza `carpetas._redactar` con refs `[n]`.
- Persistencia en tabla `informe` (borrador→final, versiones).
- API `/api/reg/informes` (+ `redactar`, `exportar` docx|pdf|pptx|md|json|xlsx).
- UI `informe.js`: semáforos, KPIs, SVG (barras por estado, mapa de calor riesgos 5×5, línea de tareas abiertas), narrativa editable.
- Export: PDF (HTML+SVG), DOCX (celdas sombreadas), PPTX (`python-pptx`).

### F7 Preguntar al proyecto (2 d) ⏳ pendiente

- `registro.pregunta(c,q)`: regex por tipo (riesgos, decisiones sobre X, requisitos de Y, preguntas abiertas, interesados) sin LLM sobre entidades, ordenadas por `carpetas.sim()`.
- `/api/preguntar` la prueba antes de la RAG.
- Selector «Todo el proyecto» por defecto.

## Esfuerzo y paralelización

- **Total:** ~33-38 días-persona (12-15 días naturales con 3-4 agentes).
- **Paralelo:** F1 (1a, 1c, 1b+1d); tras F3/F3b: F4a/b/c/d y F6; F7 solo necesita F2.
- **Choques:** `app.py`, `carpeta.js`, `index.html` → F3 deja preparadas pestañas y scripts.

## Dependencias (D1)

`python-pptx` (puro Python; trae XlsxWriter para XLSX). Si se rechaza: XLSX con `zipfile`+XML y PDF apaisado en lugar de PPTX.

## Riesgos

| Riesgo | Mitigación / nota |
|---|---|
| Rendimiento del map con modelo pequeño | Máx. 5-6 secciones; coste extra de `poblar` |
| Migración | Huérfanos por `(mid,h)` |
| Edición en dos sitios | Manda la entidad editada |
| Planner sin import CSV nativo | Ofrecer XLSX |
| Columnas Azure según proceso | Configurables / documentar |
| Gherkin derivado vs principio de cita | Herencia de cita + marca «propuesta» |
| Concurrencia SQLite | Conexión por llamada, LOCK, WAL |

## Decisiones tomadas (propuestas aceptadas)

| ID | Decisión |
|---|---|
| D1 | `python-pptx` sí |
| D2 | Exportar todo con marca BORRADOR para lo no revisado (conmutador «solo aprobados») |
| D3 | Migrados entran aprobados |
| D4 | Manuales sin cita permitidos con marca «Manual» |
| D5 | Interesados solo rol y organización (sin contacto) |
| D6 | Códigos por proyecto |
| D7 | Umbrales de semáforo fijos, editables por informe |
| D8 | `poblar` automático al terminar reunión, con opción de apagarlo |

## Pruebas

Todas las pruebas que usen LLM se ejecutan con passthrough de suscripción (CLI `claude` con la cuenta del usuario y/o `codex`) configurado como proveedor en la app; nunca con modelos locales.

## Fuera de alcance

- Importar JSON/XLSX de vuelta
- Multiusuario
- Sync por API con Jira/Azure
- Gráficos dentro del DOCX

## Estado y pendientes (guardado 2026-10-26)

### Hecho (en el árbol de trabajo, SIN commit; todo con tests offline: suite 85 passed + 1 skipped al guardar)

- [x] Passthrough CLI claude endurecido (UTF-8, argv ligero `--tools "" --strict-mcp-config --disable-slash-commands --no-session-persistence --setting-sources ""`, ~5× más barato, `ACTAS_CLI_MODEL` opcional); codex con flags NO verificados y no instalado.
- [x] Infra de pruebas: `tests_data/reunion.vtt` + `conftest.py`, `ACTAS_NO_EMBED=1` (degradación léxica), modelo de embeddings local reparado (faltaba `model_quantized.onnx_data`), `rag.no_embed` exige el sidecar, selftest cp1252, `tools/e2e_cli.py` (`--poblar`, `--derivar`) para pruebas reales con `cli:claude`.
- [x] F1: plantillas raid/requisitos/comite/daily/retro + clave `seguir` + CSV Azure/Planner + tipo Proyecto.
- [x] F2: `registro.py` SQLite + migración de `expedientes.json` (→ `.migrado`).
- [x] F3: API `/api/reg/*` + bandeja + `registro.js`; sugerencias aceptar/rechazar; restaurar.
- [x] F3b: poblar (job, auto tras reunión con ajuste `poblar_auto`, botón Regenerar con IA, extractores por vista; local = una llamada por vista).
- [x] F4: vistas Requisitos, Historias (kanban+Gherkin), Interesados (matriz poder/interés), Decisiones (timeline ADR) + `export_registro.py` (docx/pdf/xlsx stdlib/csv/md/json/.feature/csv_jira/csv_azure).
- [x] F5: derivar historias+Gherkin+preguntas (propuesta, cita heredada).
- [x] F6: informe de estado (KPIs, semáforos, narrativa con [n], exportes docx/pdf/md/json/xlsx/pptx_min).
- [x] Decisiones del usuario aplicadas: NO_DECISION también al sincronizar decisiones del acta; local una llamada por vista; interesados solo con rol; «Como» = rol del interesado si existe, si no nombre, si no «usuario»; máx 4 preguntas por requisito; Regenerar con IA manual también encadena derivar; riesgos en 5 puntos (bajo 2, medio 3, alto 4; rojo ≥12).
- [x] Último lote en curso (prompt específico del informe y DELETE de versión de informe): verificado aplicado.
- [x] F7 Preguntar sobre todo el proyecto (`preguntar_reg.py`).
- [x] Code review aplicado: renombrar/migración/deshacer/códigos/cerrojos del registro, validación de la API, privacidad (auto-poblar solo en tipo Proyecto), gemini/copilot desactivados salvo `ACTAS_CLI_EXTRA=1`, CSV injection, clave de caché léxica, carrera en la limpieza del PDF; frontend: PATCH solo con claves cambiadas y atajos acotados; `migrado_t` global.
- [x] Cierre de integración: renombrar carpeta sobre otra con registro -> 400 (no 500); `POST /api/reg/deshacer-pasada {c, lote}` + botón «Deshacer última pasada IA» en la bandeja; `derivar.guardar` precalcula embeddings antes del cerrojo de escritura; suite final 122 passed + 1 skipped.

### Pendiente — verificación

- [ ] QA en navegador SIGUE sin hacerse (los subagentes no alcanzan herramientas de navegador). `seed.py`/`smoke2.py` del scratchpad (`C:\Users\fernando.decisneros\AppData\Local\Temp\claude\C--Users-fernando-decisneros\42ba5325-0d93-4905-8f82-57df65dfaf44\scratchpad\`) vuelven a sembrar un workspace.
- [ ] Decisiones por confirmar: el acta solo filtra decisiones POSTPONED («próxima reunión»/lenguaje condicional llegan como propuesto); la exportación del informe descarta frases cuyas refs se borraron; gemini/copilot apagados; renombrar sobre una carpeta con datos se rechaza; una carpeta borrada conserva su registro como «old [eliminada …]».
- [ ] Los informes guardados conservan los umbrales antiguos hasta «Recalcular»; «muy alto/crítico» = 4.
- [ ] Hallazgos de la revisión sin arreglar: ninguno conocido (reg_revisar hecho).
- [ ] Probar TODAS las UIs en navegador real (registro/Revisión, Requisitos, Historias, Interesados, Decisiones, Informe): arrastrar y soltar, atajos, modo claro/oscuro, responsive, descargas. Nada se ha visto en navegador.
- [ ] Abrir el PPTX generado (`pptx_min.py`) en PowerPoint; si lo rechaza, instalar python-pptx (D1).
- [ ] Revisar visualmente un PDF generado (informe e interesados).
- [ ] Probar la migración de `expedientes.json` → `registro.db` con datos REALES (hacer copia de `work/` antes; rollback = borrar `registro.db`/`-wal`/`-shm` y devolver el nombre a `expedientes.json`).
- [ ] Repaso final: suite completa + code review de todo lo añadido (git diff; ficheros nuevos `registro.py`, `poblar.py`, `derivar.py`, `informe.py`, `export_registro.py`, `pptx_min.py`, `static/*.js` de las vistas).
- [ ] Verificar codex como proveedor CLI (instalar codex y confirmar flags `--skip-git-repo-check --sandbox read-only --ephemeral`) y `--model` vía `ACTAS_CLI_MODEL` con llamada real.
- [ ] Probar poblar/derivar con el modelo LOCAL de 4B (solo se ha probado con `cli:claude`); medir tiempo y calidad con `eval/score.py`; añadir gold sintético RAID/requisitos en `eval/gold`.
- [ ] Test del camino real de embeddings (sin `ACTAS_NO_EMBED`, con onnxruntime+tokenizers; skip si faltan). Recalibrar `MIN_COS` de la RAG para vectores léxicos si se usa ese modo.

### Pendiente — funcionalidad

- [x] (hecho, `preguntar_reg.py`) F7 Preguntar sobre todo el proyecto: `registro.pregunta(c,q)` con regex por tipo (riesgos, decisiones sobre X, requisitos de Y, preguntas abiertas, interesados) sobre entidades; probarla antes de la RAG en `/api/preguntar`; selector «Todo el proyecto» por defecto.
- [ ] «Escalados» del informe es siempre 0 (nada escribe `estado=="escalado"` / `campos.escalado`): decidir dónde se marca.
- [ ] Decisiones: la columna Fecha de la tabla es de solo lectura; marcar «sustituida» a mano no crea relación/flecha; aplicar sobre relación existente + deshacer la borra en vez de dejarla propuesta.
- [ ] Huérfanos: `pipeline.py:2000` guarda `secciones_plantilla` sin `seguir`; si la plantilla pierde `seguir` la entidad queda huérfana (hoy F3 los muestra con insignia).
- [ ] Reforzar `models.ok()`: comprobar tamaño/hash, no solo no-vacío y sin `.part`.
- [ ] Interesados: el arrastre HTML5 no funciona en táctil (quedan flechas/tabla/ficha).
- [ ] Umbrales de similitud de poblar (0,85; 0,6 en 30 s) afinados con un solo fixture; `carpetas.sim` ya se precalienta fuera del lock (poblar y derivar); posible duplicado si se regenera un acta y cambia el texto de una decisión.
- [ ] Asistentes sin rol no se crean como interesados (decisión tomada); incidencias/supuestos/dependencias no se extraen en poblar (añadir sería otra entrada en `VISTAS`).
- [ ] Coste: `/api/reg/poblar/estado` solo muestra coste con el CLI de Claude.
- [ ] Informe: los gráficos los genera Python (`informe.graficos`) y los inyecta la UI; PPTX sin gráficos.
- [ ] Fuera de alcance por ahora: importar JSON/XLSX de vuelta, multiusuario, sync por API con Jira/Azure/Planner (conectores), matriz de trazabilidad/análisis de impacto, gráficos dentro del DOCX.

### Pendiente — repo y housekeeping

- [ ] NADA está commiteado: decidir rama y commits (hay ficheros sin seguimiento: `.claude/`, `.mcp.json`, `.ignore`, `PLAN.md`, `tests_data/`, `conftest.py`, `registro.py`, `poblar.py`, `derivar.py`, `informe.py`, `export_registro.py`, `pptx_min.py`, `test_*.py` nuevos, `static/*.js` nuevos, `tools/e2e_cli.py`). Revisar qué de `.claude/` y `.mcp.json` (graft) debe entrar o ignorarse.
- [ ] `graft init` se hizo solo para Claude Code: reiniciar Claude Code para cargar el MCP de graft (cursor/gemini/copilot sin configurar).
- [ ] Actualizar README (nuevas plantillas, vistas de proyecto, poblar/derivar, informe, exportes, `ACTAS_NO_EMBED`, `ACTAS_CLI_MODEL`, ajuste `poblar_auto`) y subir versión (v0.7.0 base).
- [ ] `test_grabar::test_recuperacion_tras_corte` se salta sin ffmpeg (instalar ffmpeg para ejecutarlo).
- [ ] Las pruebas con LLM real usan la suscripción de Claude: `tools/e2e_cli.py` con `-X utf8`, tope de llamadas y coste; no hay CI para ello.

### Decisiones tomadas (referencia)

D1 python-pptx sí (no disponible offline → `pptx_min`) · D2 exportar todo con marca BORRADOR (conmutador «solo aprobados») · D3 migrados entran aprobados · D4 manuales sin cita permitidos · D5 interesados sin contacto · D6 códigos por proyecto · D7 umbrales de semáforo fijos y editables por informe · D8 poblar automático con opción de apagarlo.
