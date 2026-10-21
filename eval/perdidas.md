# Dónde se pierde información (nivel normal, ASR rápido)

Diagnóstico, sin arreglos. Cada ítem del gold (decisiones, tareas, puntos clave) se clasifica por la PRIMERA etapa donde desaparece:
a = ASR (no está en la transcripción), b = map (está en la transcripción, ningún ítem del map lo cubre o lo falsea),
c = selección (está en el map pero no pasa el ranking/tope: `select_points` keep 0,5, tope de decisiones/tareas),
d = redacción (seleccionado pero perdido o deformado en el texto final), e = presente (aunque sea en forma gruesa).
Método: coincidencia de palabras clave (raíz de 5 letras) sobre transcripción, map (`map_rápido_*.json`), `valid_*.json` y `acta.json`
en la ventana del gold ±90 s, más revisión manual. Se usó la caché del map que reproduce los puntos del acta existente (sin re-ejecutar el LLM).

## Por reunión

| reunión | ítems | a | b | c | d | e |
|---|---|---|---|---|---|---|
| charla_comite | 17 | 0 | 2 | 4 | 0 | 11 |
| larga_cne | 12 | 0 | 1 | 0 | 0 | 11 |
| real_clickmeeting | 9 | 0 | 1 | 1 | 0 | 7 |
| reunion_sintetica | 12 | 0 | 3 | 1 | 0 | 8 |
| webinar_pmia | 10 | 0 | 0 | 2 | 0 | 8 |
| **total** | **60** | **0** | **7** | **8** | **0** | **45** |

## Ítems perdidos

| reunión | ítem gold | etapa | causa |
|---|---|---|---|
| charla_comite | corregir apellido Guevara Gordillo (t=1401) | b | el map no genera tarea de las correcciones al acta |
| charla_comite | seguimiento: solo asisten acreditados (t=1282) | b | sin punto ni tarea; el map solo recoge la sugerencia de invitar a Capitanía Naval |
| charla_comite | próxima reunión en noviembre / convocar (dec, tar, clave) | c | punto con nota 1 (despedida): `select_points` descarta siempre la nota 1 |
| charla_comite | Res. 452-2022-SUNAFIL (clave) | c | punto nota 3 («competencia territorial SUNAFIL») fuera del 50 % |
| larga_cne | aprobar orden del día (t=908) | b | ningún ítem del map |
| real_clickmeeting | precios de los planes (25 y 30 USD, t~144-300) | b | el map dice «planes pagos permiten grabaciones…» sin cifras |
| real_clickmeeting | calificación del webinar por asistentes (t=1729) | c | punto nota 2 @28:49 sin cupo |
| reunion_sintetica | Laura prepara la convocatoria de la beta cerrada | b | tarea omitida (el ASR dice «beta hermana», pero «yo preparo la convocatoria» sí está) |
| reunion_sintetica | Carlos redacta las FAQ a final de mes | b | tarea creada pero con responsable «Marta» y sin plazo (deformada ya en el map) |
| reunion_sintetica | presupuesto 200.000 € | b | las cifras (200 k, reparto) no entran en el map |
| reunion_sintetica | próxima reunión el martes | c | nota 1 |
| webinar_pmia | >75 palabras por diapositiva (t=385) | c | punto nota 3 sin cupo (se elige otro más genérico, nota 4) |
| webinar_pmia | pósters científicos (t=3422) | c | punto nota 3 sin cupo |

## Deformaciones que no cuentan como pérdida del gold (detectadas de paso)

- Detalle perdido en ítems «presentes»: siglas desarrolladas del acta (charla), «solo la ley fija los consejeros», fecha 21 abril 18:00 (clickmeeting), «atajos» de PowerPoint.
- Cadena «ASR/map → texto final» sin corrección: «MIMNO» (3 veces en la charla), «Consejo Nacional de Educación» en lugar de Electoral (cne, 1 vez), «storytelling en 3D» (webinar, 2 veces).
- Las decisiones y tareas importantes de la charla (`gds`, `gds_t`) salen como punto/relato, no en las listas decisiones/tareas.
- cne: 28 decisiones validadas, 12 en el acta (tope `dec`=12 de normal tras agrupar): 16 recortadas (repetitivas por postulante, pero se pierde el detalle por postulante).

## Cobertura

Minutos de transcripción con voz sin ningún ítem de map (punto, decisión, tarea o relato), y puntos del map que no se muestran.

| reunión | min con voz | sin ítem en su minuto | sin ítem a ±1 min | puntos map | no mostrados en normal | no mostrados en detallado (nota 1 y cupos) |
|---|---|---|---|---|---|---|
| charla_comite | 49 | 22 (45 %) | 2 (4 %) | 33 | 19 (58 %) | 6 (18 %) |
| larga_cne | 132 | 42 (32 %) | 7 (5 %) | 104 | 56 (54 %) | 8 (8 %) |
| real_clickmeeting | 30 | 6 (20 %) | 0 (0 %) | 36 | 25 (69 %) | 14 (39 %) |
| reunion_sintetica | 9 | 2 (22 %) | 0 (0 %) | 9 | 5 (56 %) | 1 (11 %) |
| webinar_pmia | 71 | 25 (35 %) | 0 (0 %) | 56 | 30 (54 %) | 4 (7 %) |
| **total** | **291** | **97 (33 %)** | **9 (3 %)** | **238** | **135 (57 %)** | **33 (14 %)** |


Lectura: el map cubre casi todo el tiempo (con ±1 min solo el 3 % queda sin ítem), pero a nivel normal se oculta el 57 % de los puntos del map; los puntos ocultos incluyen notas 3-4 reales. Los relatos (párrafos de 1-2 frases por bloque) se muestran todos, y son lo que cubre de forma gruesa muchos ítems «presentes».

## Causas principales

1. **Cupo de selección (c, 8/15 pérdidas):** keep=0,5 oculta puntos nota 3-4 válidos; la nota 1 se descarta siempre aunque contenga la «próxima reunión» o un cierre con compromiso.
2. **Map incompleto o impreciso (b, 7/15):** omite tareas pequeñas (corregir apellido, convocatoria de Laura), cifras (precios, 200 k) y atribuye mal el responsable («Me lo quedo yo» a Marta).
3. **Ruido ASR propagado a la redacción (d en sentido amplio, sin ítems gold perdidos):** «MIMNO», «Educación», «3D» pasan tal cual al acta; ninguna pérdida pura de ASR (a = 0).
