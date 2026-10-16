# Evaluación ronda 1 — actas (2026-10-16)

Banco: Ryzen 5 5500 con `taskset -c 0-3,6-9 … --threads 4` (4C/8T ≈ i5-1135G7), `--asr rápido`, Qwen3.5-4B Q4_0.
Código evaluado: `485a5b8`. Pico RSS muestreado cada 1 s (python vs llama-server).
charla y clickmeeting tenían ASR/OCR/map en caché de hoy (mismo hash de map): sus tiempos de etapa salen de los
`timings_rápido_breve.json` de esa ejecución; normal/detallado de charla sí se han medido ahora.

## 1. Tiempos

| vídeo | dur | ASR | capt+OCR | map (bloques) | reduce b / n / d | total breve | RTF breve | RTF b+n+d |
|---|---|---|---|---|---|---|---|---|
| real_clickmeeting | 29:49 | 124 | 88 | 379 (3) | 13 / 52 / 95 | 608 s | 0,34 | 0,43 |
| charla_comite | 50:13 | 223 | 53 | 586 (4) | 28 / 100 / 79 | 893 s | 0,30 | 0,36 |
| webinar_pmia | 70:01 | 278 | 75 | 862 (7) | 18 / 71 / 117 | 1236 s | 0,29 | 0,34 |
| larga_cne | 141:50 | 822 | 86 | 2277 (14) | 60 / 178 / 273 | 3247 s | 0,38 | 0,43 |

(segundos; total breve incluye carga LLM ≈ 2,5 s; b+n+d = las tres actas seguidas).
- El map es el 61-70 % del tiempo. Generación medida: 12,2 tok/s. Larga: 163 s/bloque frente a 123 s en el webinar.
- Reduce crece con la entrada: larga detallado 273 s (entrada recortada, ver issue 9).

**Proyección ProBook (×1,0–1,3):** click 10–13 min, charla 15–19 min, webinar 21–27 min, larga **54–70 min**
(breve); pedir los tres niveles suma +3/+3/+4/+16 min. Ojo: el README estima que con RAM de un canal la
generación va a la mitad; si es así, el map (dominante) dispara la larga a ~1,5 h. Hay que medirlo en el equipo real.

**Pico de RAM:**
| | webinar 70 min | larga 142 min |
|---|---|---|
| python (pico transitorio) | **4,27 GB** | **6,86 GB** |
| python estable durante ASR | 1,8–2,6 GB | 1,8–2,6 GB |
| llama-server | 3,04 GB | 3,06 GB |

El pico de python aparece justo después de «Cargando modelo de voz», antes del primer segmento, y crece con la
duración (≈ +36 MB/min). Con 8 GB una reunión de 2 h+ en el ProBook va a swap o la mata el OOM (issue 1).
El README dice «python 2,2 GB»; eso es falso para reuniones largas.

## 2. Puntuaciones (1-10)

| acta | Fidel. | Cobert. | Dec/Tar | Estruct. | Marcas | Capturas | Nivel* | 2 h+* |
|---|---|---|---|---|---|---|---|---|
| click breve | 5 | 6 | 3 | 7 | 8 | 6 | 7 | – |
| click normal | 5 | 7 | 3 | 5 | 8 | 7 | | |
| click detallado | 6 | 8 | 3 | 5 | 8 | 5 | | |
| charla breve | 3 | 5 | 2 | 6 | 6 | 3 | 5 | – |
| charla normal | 4 | 7 | 2 | 5 | 6 | 4 | | |
| charla detallado | 4 | 8 | 2 | 5 | 6 | 4 | | |
| webinar breve | 6 | 4 | 10 | 6 | 8 | 6 | 6 | – |
| webinar normal | 6 | 6 | 10 | 4 | 8 | 6 | | |
| webinar detallado | 6 | 8 | 10 | 6 | 8 | 8 | | |
| larga breve | 5 | 5 | 3 | 3 | 7 | 7 | 4 | 6 |
| larga normal | 5 | 7 | 3 | 3 | 7 | 8 | | 7 |
| larga detallado | 5 | 7 | 3 | 3 | 6 | 8 | | 6 |
| **media** | **5,0** | **6,5** | **4,5** | **4,8** | **7,2** | **6,0** | **5,5** | **6,3** |

*Nivel: una nota por vídeo. 2 h+: solo para la larga.

Marcas (5 comprobadas por vídeo con la transcripción): click 5/5 · webinar 4/5 (`[59:24]` «cualquier cultura» está
en 61:12-62:33) · charla 3/5 (`[28:28] Se aprobó el acta`: ahí empieza la lectura y se aprueba en 34:15-36:27) ·
larga 3/5 (`[24:21] Aprobar … Vélez`: 24:21 es el resultado del informe anterior; `[135:15] CNST 2021-109` lleva un número equivocado).
La larga NO pierde la segunda mitad: el ranking de puntos es global y salen las negativas (97-138 min) y la suspensión (138:56).

## 3. Problemas por prioridad

**1. Pico de RAM del ASR proporcional a la duración (6,9 GB en 2 h 22).**
Evidencia: muestreo de RSS (tabla de arriba).
Causa probable: `transcribe()` pasa a faster-whisper un único array con toda la reunión. Con VAD,
`collect_chunks` concatena todo y `FeatureExtractor` hace la STFT/mel del audio entero de una vez
(complex64 201×N frames ≈ GB). Se suma el `capture_output` de ffmpeg (bytes + join).
Arreglo: transcribir en ventanas de 10-20 min de PCM (leer el stdout de ffmpeg por trozos o `-ss/-t`),
sumar el desfase a `s.start/s.end`, y no tener nunca el audio completo en memoria.
Criterio: pico < 2,5 GB en la larga.

**2. Se dan como decisiones y tareas cosas que no lo son.**
- charla: las tareas `[32:09]` MIMO, `[32:34]` Castro y `[32:53]` NAFIL, y la decisión `[31:43]` «Conformación de la
  comisión…», salen de la **lectura del acta anterior** (31:30 «Acuerdos.» leído en voz alta).
- charla: `[10:34]` «Se acordó que la implementación … corresponde a la GDS» es una observación, no un acuerdo.
- click: la única decisión, «Crear un webinar permanente sobre Instagram…», es una acción de demo. Además es falsa:
  en 11:23 eligió «con hora programada».
- larga breve: 35 decisiones; «Notificar la resolución…» aparece 2 veces como decisión y 4 como tarea.

Causa: `MAP_PROMPT` solo dice «explícitas». No excluye la lectura de actas anteriores, las demos ni los supuestos.
`reduce_maps` (l.357) y `render` pasan todo tal cual, sin deduplicar.
Arreglo:
(a) reglas en el prompt: «no son acuerdos: lo que se lee de actas previas, demostraciones, ejemplos ni hipótesis;
la acción rutinaria repetida (notificar) es una sola tarea»;
(b) deduplicar decisiones/tareas con `words()` + SequenceMatcher (reutilizar `DUP`);
(c) en breve/normal agrupar las decisiones repetitivas con el LLM («22 informes de recalificación aceptados
parcialmente, 4 a favor y 1 abstención; ~16 negados») y poner tope en el render.

**3. En normal/detallado el resumen de cada sección no corresponde a los puntos que lleva debajo.**
- webinar normal: la sección `[06:31] Diseño y Contenido Visual` habla de la «regla de los tercios» (37:15), y
  `[22:12] Gráficos y Tipografía` dura 40 min (22-62) e incluye storytelling y pósters.
- click normal: `[00:00] Planificación del evento` resume lo de 11:23-14:51, y sus viñetas son los precios (02:37-04:33).
- larga detallado: `[66:03] Negativa de recalificaciones…` no contiene ninguna negativa (eso va de 97 a 138 min).

Causa: el reduce inventa secciones con `t` y resumen libres. `render` (l.399-412) reparte los puntos por
rangos de `t`, así que contenido y viñetas se descuadran.
Arreglo: las secciones deben salir de los puntos. Dar ids a los puntos y pedir `secciones[{titulo, ids, resumen}]`
con ids contiguos, o agrupar por bloque del map (usar `tema`, que hoy se genera y se tira) y que el LLM solo
redacte el resumen de cada grupo.

**4. Un bloque de cola diminuto y el reparto forzado de notas meten despedidas en el acta.**
- webinar: el bloque 7 dura 68:46-70:01 (679 caracteres).
- Sus notas 5 y 4 («Se da por finalizado el webinar…», «Se anima a contactar con David») acaban en el resumen breve
  («El evento concluyó con la invitación a … contactar al ponente»).
- En normal, 4 de las 5 viñetas de la última sección son cierre de cortesía. Mientras, falta el contenido del
  turno de preguntas (cultura 60:20-63:40, IA 64-66).
- charla: el bloque 4 es de 5 min; `[48:55] Se concluyó la reunión`.

Causa: `chunk()` deja el resto como bloque propio. La rúbrica obliga a poner un 5 en cada bloque y
`select_points` compara notas entre bloques como si fueran absolutas.
Arreglo: unir el último bloque al anterior si mide < 40 % de `CHUNK_CHARS`. En el prompt: «saludos, despedidas y
agradecimientos = 1 siempre». Opcional: ponderar la nota por la longitud del bloque.

**5. Infidelidades: opiniones como hechos y mezclas de datos.**
- larga: «se determinó que existía inseguridad jurídica en la elección de delegados» es la opinión de la consejera
  Nájera, que razona su abstención. El acta no recoge que el patrón fue 4 a favor y 1 abstención en todos los informes.
- larga: «La doctora Elena Najera y el ingeniero Enrique Pita votaron por abstención» (88:53): falso, Pita votó a favor.
- larga: «Calderón Tobar obtuvo 72.5 sobre 50».
- charla: «se acordó presentar un informe sobre la paridad de género» (fue un memorando ya enviado, 08:01) y
  «Resolución 452-2022-SM» (es SUNAFIL).
- webinar: «la regla de los tres encabezados» (es el truco HTML H1-H3, 18:37) y «usar gráficos escalables como SVG
  para datos financieros y científicos».

Causa: el map pide frases de ≤ 20 palabras sin atribución, y el reduce reescribe y mezcla.
Arreglo: en el prompt «distingue opinión, propuesta y acuerdo; atribuye a quien lo dice si se le nombra;
no combines cifras de puntos distintos». En el reduce: «no añadas hechos que no estén en un punto».

**6. La deduplicación de pantallas y la clasificación "pantalla compartida" fallan con UI común.**
- click detallado: `[22:24]` muestra `k001497.jpg` (resumen de encuesta, 24:57), pero en 22:24 se ve la pizarra.
  Se fusionaron porque comparten el texto del panel lateral de ClickMeeting.
- charla breve: la captura `[00:00]` es la cuadrícula de caras de Meet. Pasa como "pantalla" porque el OCR lee
  la barra de marcadores y los nombres (478 caracteres), y las otras 2 capturas son casi idénticas (documento Word).
- webinar `[62:18]` es la webcam del ponente.

Causa: `dedupe_screens` y `MIN_CHARS` cuentan las líneas de interfaz que se repiten en casi todos los frames.
Además `keep["t"] = min(...)` pone la marca de la primera aparición a la imagen más completa, aunque sea otra pantalla.
Arreglo: antes de contar letras y comparar, quitar las líneas OCR presentes en más del 50 % de los frames. Mover la
marca solo si el texto que queda es ≥ 90 % igual.

**7. Los niveles apenas se distinguen en Decisiones y Tareas, y breve no es breve en reuniones formales.**
- Las decisiones y tareas son idénticas en los 3 niveles.
- larga breve = resumen + 35 decisiones + 4 tareas + 3 capturas.
- breve no muestra ninguna viñeta con marca: el resumen no tiene enlaces y el usuario no puede saltar al vídeo
  salvo por las decisiones.

Arreglo: issue 2(c), y en breve añadir 5-8 «puntos clave» con marca (ya existen en `sel`).

**8. «Cifras y citas» (detallado) es ruido.**
Ejemplos: «Juan», «Instagram», «Lima», «150», «7,134 / 6,301 / 900 / 4230» (números de un gráfico, sin contexto).
Además salen sin ordenar por tiempo (`render` l.417 recorre los bloques en orden, no por `t`).
Arreglo: pedir «dato + a qué se refiere» y ordenar por `t`. O quitar `datos` del esquema: ahorra unos 60-100
tokens generados por bloque (~10-15 % del map).

**9. Reduce único con tope de 16 000 caracteres: no escalará a 3 h.**
- larga detallado: puntos 14 262 + decisiones 3 533 + tareas 626 = 18,4 k caracteres, así que `keep` baja a 0,8.
- Ese reduce tarda 273 s; el prompt ronda ~5 k tokens y `ctx=8192` con `max_tokens=2000` deja poco margen.
- Una sesión de 3 h superará el tope también en normal.

El recorte respeta el ranking global (no pierde la segunda mitad), pero las decisiones van siempre completas y se
comen el presupuesto.
Arreglo: reduce jerárquico (secciones por grupos de bloques y después el resumen global) o pasar al reduce solo
las decisiones agrupadas (issue 2c).

**10. Nombres destrozados por el ASR rápido.**
larga: «Kappa», «Carden Las Gloria Susana» (Vizcaíno Cárdenas), «Elvira Mirano Vacas» (Altamirano Vaca Eloísa).
charla: «la fil» (SUNAFIL). En la larga los nombres son el contenido principal.
Arreglo (barato): `initial_prompt` de whisper con nombres y siglas sacados del OCR de las primeras pantallas, o
recomendar `--asr calidad` para sesiones formales. Medir el coste de calidad en el ProBook.

**11. Rendimiento del map en reuniones largas: 163 s por bloque.**
Hay más tokens de marca por segmento corto (la larga tiene 3 464 segmentos y muchos de 2-3 palabras).
Arreglo: en `map_input`, fundir segmentos consecutivos hasta ~15-20 s antes de poner `[mm:ss]` (menos tokens de
prompt). Probar `max_tokens` 700.

**12. UX del HTML** (render revisado con Brave headless a 1400 px y 390 px; el layout está bien y el vídeo
enlazado carga por `file://`):
- La tabla de Tareas vacía muestra solo la cabecera; debería poner «—» como Decisiones.
- El pie de captura es siempre «Pantalla compartida»; usar la primera línea del OCR (título de la diapositiva).
- `img/` copia todas las pantallas aunque breve muestre 3 (zip de 3 MB en webinar breve).
- El título es el nombre del fichero; `tema` del primer bloque o del reduce serviría.
- En Windows `os.link` entre unidades falla y `os.symlink` necesita privilegios, así que copia el vídeo entero por
  nivel (3 × 262 MB en la larga). Mejor `video_src` relativo al original, o una sola copia por `wd`.
- Las capturas a todo el ancho alargan mucho detallado (43 en click, 36 en webinar). Usar miniaturas a 50 % con
  clic para ampliar.

## 4. Lo que funciona

- La larga no pierde la segunda mitad y el resumen detallado recoge la suspensión y que el presupuesto queda para el día siguiente.
- Las marcas del map son precisas en contenido didáctico (webinar, click).
- Las capturas de diapositivas del webinar son limpias y útiles (36 en detallado, todas distintas).
- No se inventan decisiones en el webinar (lista vacía correcta).
- Español correcto y legible en todas las actas.
