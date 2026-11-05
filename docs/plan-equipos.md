# Plan: Actas para equipos y para equipos de innovación

Estado: propuesta, sin desarrollar. Base: v0.11.0 (rama `rediseno`).

## Punto de partida

- Hoy Actas es **monousuario y local**: servidor en 127.0.0.1, datos en `work/` (meta.json por reunión, `registro.db` SQLite, `buscar.db`).
- PLAN.md dejó **«Multiusuario» fuera de alcance**. Este plan lo reabre, pero por fases y sin montar un servidor central de entrada.
- Lo que ya sirve a un equipo: proyectos (carpetas con tipo y campos), un registro con revisión (tareas, decisiones, requisitos, riesgos, preguntas, interesados, historias), envío a Teams, Slack, Jira, Planner y webhooks, informes de estado, recetas «al terminar» y Preguntar sobre el proyecto.
- Lo que falta para un equipo:
  - identidad (quién hizo qué);
  - un sitio común donde viva el proyecto;
  - asignar a personas, no a texto libre;
  - avisos;
  - una vista de equipo (lo mío y lo de todos).

## Principios

1. **Local primero, compartir sin servidor propio.** El primer paso usa lo que el equipo ya tiene: una carpeta de OneDrive/SharePoint, o Teams y Planner como destino. Un servidor llega solo si se demuestra que hace falta.
2. **Nada de la reunión sale sin querer.** Lo compartido es lo generado y revisado (acta, registro). El audio y el vídeo solo se comparten si se pide. Se mantienen los tipos sensibles (paciente, candidato).
3. **El equipo no instala nada para leer.** Quien no usa Actas recibe HTML, Teams o Planner. Solo quien graba y revisa necesita la app.
4. **Sin IA en la colaboración.** Sincronizar, asignar y avisar no gastan modelo.

---

## Parte A: equipos que usan la aplicación

### A1. Identidad mínima (pequeño)
- Ajustes → «Tu nombre y correo», guardado en `ajustes.json`.
- Cada cambio del registro guarda `autor` en `historial`; la tabla ya existe, falta el campo.
- «Responsable» deja de ser texto libre: sale de una lista de **miembros del proyecto**. Esa lista nace de los interesados y los hablantes y se puede editar.
- *Hecho cuando:* el historial dice quién aprobó o editó cada elemento, y en el responsable se puede elegir a un miembro.

### A2. Proyecto compartido por carpeta sincronizada (medio, el núcleo)
- Opción del proyecto: «Compartir en carpeta…». Se elige una ruta de OneDrive o SharePoint sincronizada.
- Se exporta allí un **paquete del proyecto**:
  - `proyecto.json` (campos, glosario, miembros);
  - un fichero por entidad o un `registro.jsonl` con un evento por línea, porque añadir líneas casi no genera conflictos en OneDrive;
  - las actas en HTML y md.
- Otro miembro con Actas pulsa «Unirse a proyecto compartido» y elige esa carpeta. Su app importa los eventos y vuelve a escribir los suyos.
- Resolución de conflictos: **por campo, gana el último** y queda en el historial. Ya existen `editado`, `revision` y `modificado` en `entidad`, que sirven para detectar conflictos.
- Las grabaciones y transcripciones se quedan en la máquina de quien grabó. Solo se comparte la transcripción si el proyecto lo permite.
- *Riesgos:* bloqueos de SQLite en carpetas sincronizadas. Por eso **nunca se comparte `registro.db`**, solo el registro de eventos.
- *Hecho cuando:* dos instalaciones ven las mismas tareas y decisiones en menos de un minuto tras sincronizar, y una edición simultánea no pierde datos.

### A3. «Mis cosas» y vista de equipo (pequeño)
- En Pendientes, un filtro «Asignado a mí», que usa A1.
- En el proyecto, una pestaña «Equipo»: carga por persona (tareas abiertas y vencidas), decisiones recientes y preguntas dirigidas a cada uno.
- *Hecho cuando:* cada miembro ve solo lo suyo con un clic.

### A4. Avisos sin servidor (pequeño, reutiliza destinos)
- Recetas nuevas, sin IA:
  - «Cuando se me asigne una tarea → Teams o correo a esa persona»;
  - «Resumen semanal del proyecto → canal».
- El envío programado y los destinos Teams, Slack y Outlook ya existen; falta el disparador por evento (asignación, vencimiento).
- *Hecho cuando:* asignar una tarea manda un aviso al responsable.

### A5. Planner, To Do y Jira de ida y vuelta (medio)
- Hoy solo se envía. Añadir la lectura del estado: si una tarea se cierra en Planner o Jira, se marca «hecho» en Actas.
- *Hecho cuando:* cerrar una tarea fuera se ve en Actas en la siguiente sincronización.

### A6. Plantillas y perfiles de equipo (pequeño)
- Exportar e importar plantillas, recetas, destinos (sin secretos) y el glosario como un `.actas-equipo.json`, para que todo el equipo use los mismos formatos.
- *Hecho cuando:* un miembro nuevo se configura importando un fichero.

### A7. Modo servidor (aprobado el 2026-11-05, para desplegar en Coolify)
Decisiones:
- **Despliegue:** imagen Docker para Coolify; los datos van en un volumen (`/data`). `ACTAS_SERVIDOR=1` activa el modo.
- **Login:** usuario y contraseña propios (sin Entra ID). El primer administrador se crea con variables de entorno; él da de alta al resto. El autor del historial es el usuario que ha entrado.
- **IA:** ninguna local en el servidor; solo la de la nube (proveedores con API, nunca CLIs). Las reuniones se procesan en el escritorio y llegan ya hechas.
- **Permisos:** todos ven todo (un equipo, un espacio). Permisos por proyecto, más adelante si hace falta.
- **Escritorio:** sigue existiendo. Envía fácil al servidor: URL y token en Ajustes, y «Enviar al servidor» en cada proyecto (registro de ida y vuelta, y reuniones como zip de acta).

Seguridad (lo que el modo servidor cierra):
- Todas las rutas piden sesión (cookie HttpOnly, SameSite=Lax) o token (escritorio), salvo el login.
- Se bloquean las rutas que leen o escriben rutas del disco del servidor, abren diálogos, graban, vigilan carpetas, descargan o usan modelos locales, y las CLIs de IA.
- Se bloquean los destinos que ejecutan comandos o escriben en carpetas del servidor (carpeta, sftp con comando).
- Los secretos van a un fichero del volumen con permisos 600 (no hay llavero del sistema en el contenedor).
- Un test enumera todas las rutas: una ruta nueva debe declararse permitida o bloqueada en el servidor.
- Riesgo aceptado: los webhooks y destinos HTTP los configura cualquier usuario con sesión (SSRF hacia la red interna); son miembros del equipo.

Fases: S1 servidor con login y bloqueos + Dockerfile; S2 envío desde el escritorio; S3 IA en la nube en el servidor.

---

## Parte B: equipos de innovación

Lo que necesitan es distinto. Les importa menos el acta y más capturar **ideas, hipótesis, experimentos y aprendizajes** a lo largo de muchas sesiones (ideación, entrevistas con usuarios, demos y retros), y decidir qué seguir y qué matar.

### B1. Tipo de proyecto «innovación» con su registro (pequeño-medio)
- Nuevo tipo de carpeta en `SUGERIDOS` con estos campos: Reto, Sponsor, Horizonte (H1/H2/H3), Fase (descubrir / validar / escalar) y Presupuesto.
- Tipos de entidad nuevos en el registro, con columnas propias (como los existentes):
  - **Idea:** problema, propuesta, autor, votos y estado (nueva / en evaluación / descartada / en experimento);
  - **Hipótesis:** «creemos que… medido por… éxito si…»;
  - **Experimento:** hipótesis, métrica, umbral, fechas, resultado y decisión (pivotar / perseverar / matar);
  - **Aprendizaje / insight:** con cita de la sesión (entrevista o demo).
- Extractores para `poblar.py` de ideas, hipótesis e insights. Son opcionales, como `EXTRA`, y se activan desde el nuevo «Qué sacar», que ya permite elegir.
- *Hecho cuando:* tras una sesión de ideación, «Qué sacar → Ideas» llena la bandeja con ideas citadas.

### B2. Plantillas de sesión de innovación (pequeño)
- Perfiles nuevos en `plantillas.py`:
  - Ideación o brainstorming: ideas agrupadas por tema, más votadas, siguientes pasos;
  - Entrevista con usuario: necesidades, dolores, citas literales, insights;
  - Demo o sprint review: feedback, decisiones, cambios de prioridad;
  - Retro: qué fue bien, qué mejorar y acciones.
- *Hecho cuando:* cada perfil genera su documento con secciones y citas verificadas.

### B3. Embudo y priorización (medio)
- Vista «Embudo» del proyecto: tablero de ideas a experimentos a escaladas o descartadas, arrastrando de una columna a otra.
- Puntuación sencilla y configurable (ICE o RICE: impacto, confianza, facilidad) sobre las ideas, con orden automático.
- Votación del equipo, que necesita A1 (un voto por miembro) y A2 si es entre varias máquinas.
- *Hecho cuando:* el equipo prioriza en la propia app y exporta la lista a Excel o PowerPoint.

### B4. Memoria de innovación entre proyectos (medio, mucho valor)
- Preguntar ya cruza documentos de un proyecto. Ampliarlo a **todos los proyectos de tipo innovación**: «¿ya probamos algo parecido?», «¿qué aprendimos de pagos?».
- Detección de duplicados: al entrar una idea nueva, avisar de ideas o experimentos parecidos anteriores, por similitud de embeddings, que ya existen en `rag.py`, sin LLM.
- *Hecho cuando:* una idea repetida muestra «parecida a X (proyecto Y, descartada en marzo porque…)».

### B5. Informe de portafolio (pequeño, reutiliza `informe.py`)
- Informe para comité de innovación: experimentos en curso, resultados, decisiones de matar o escalar, aprendizajes clave e inversión por horizonte.
- *Hecho cuando:* se genera un PPTX o PDF del portafolio con un clic.

### B6. Conexión con herramientas de innovación (opcional)
- Destinos nuevos solo si se piden: Miro o Mural (ideas como post-its), Notion o Confluence (ya hay Notion) y Excel de portafolio.

---

## Orden propuesto

| Fase | Contenido | Tamaño | Depende de |
|---|---|---|---|
| 1 | A1 identidad, A6 perfiles de equipo, B2 plantillas | pequeño | — |
| 2 | B1 tipo innovación y entidades, A3 vista de equipo | pequeño-medio | A1 |
| 3 | A2 proyecto compartido por carpeta, A5 Planner de ida y vuelta | medio | A1 |
| 4 | A4 avisos, B3 embudo y votación (ICE) | medio | A1, A2 (votación multi-máquina) |
| 5 | B4 memoria entre proyectos, B5 portafolio, ida y vuelta con Jira y Azure | medio | B1, A5 |
| 6 | A7 modo servidor (Coolify): S1 login y bloqueos, S2 envío desde escritorio, S3 IA en la nube | grande | A2 |

## Decisiones tomadas (2026-11-05)

1. **Compartir por OneDrive/SharePoint** (A2): sí, es la vía.
2. **Transcripciones:** por defecto **no** se comparten. Hay un interruptor por proyecto («Compartir también las transcripciones») y otro por documento para casos sueltos. Al activarlo se avisa de qué sale.
3. **Priorización:** se usa **ICE** por defecto, con **RICE** como opción en los ajustes del proyecto. Todas las puntuaciones son de 1 a 10 y se pueden editar a mano.
   - *ICE* = Impacto × Confianza × Facilidad. Es rápido, bueno para muchas ideas tempranas.
   - *RICE* = (Alcance × Impacto × Confianza) / Esfuerzo. Es más preciso cuando se sabe a cuánta gente afecta y cuánto cuesta.
4. **Horizontes:** H1/H2/H3 son opcionales y vienen desactivados. Por defecto se usan solo las fases del embudo (idea → en evaluación → en experimento → escalada / descartada). Las fases se pueden renombrar por proyecto.
   - *H1* = mejorar lo que ya existe (corto plazo).
   - *H2* = extender a mercados o productos cercanos (medio plazo).
   - *H3* = apuestas nuevas y disruptivas (largo plazo).
5. **Integraciones:** **Planner** es la integración principal y la primera que se hace de ida y vuelta (A5). Además **todo debe poder conectarse**: cada tipo de entidad (tareas, ideas, experimentos, decisiones…) se puede enviar a cualquier destino existente (Jira, Azure DevOps, To Do, Teams, Slack, Notion, webhook, Power Automate…). La ida y vuelta se añade por destino con la misma interfaz que Planner. Miro/Mural (B6) entran como destinos nuevos con esa misma interfaz.

### Cambios que esto introduce en las fases
- **A2:** el paquete compartido nunca incluye transcripciones salvo con el interruptor activado; las capturas siguen la misma regla.
- **A5:** pasa a la **fase 3**, junto a A2: Planner de ida y vuelta, con estado, responsable y fecha sincronizados. Se diseña una interfaz `sincronizar(destino, entidades)` que luego reutilizan Jira y Azure.
- **B3:** usa ICE por defecto. El tablero muestra la puntuación y permite ordenar por ella.
- **B1:** el campo «Horizonte» solo aparece si el proyecto lo activa.

## Riesgos

- **Conflictos de sincronización** (A2): por eso eventos que solo se añaden, y nunca SQLite compartido.
- **Privacidad:** compartir actas expone lo dicho. Se mantienen la anonimización y los tipos sensibles, y se avisa al compartir.
- **Alcance:** el modo servidor (A7) se aprobó el 2026-11-05 para desplegar en Coolify (ver A7).
- **Rendimiento en portátiles:** los extractores nuevos (B1) solo con IA en la nube o bajo demanda, nunca automáticos en local.
