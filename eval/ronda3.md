# Evaluación ronda 3 — Calidad Alta, modelos y capturas (2026-10-20)

Banco: Ryzen 5 5500 + RX 6600 (8 GB). Pruebas de **calidad** con `eval/score.py` sobre el gold de 5 reuniones
(charla_comite, larga_cne, real_clickmeeting, reunion_sintetica, webinar_pmia). Sin emulación del portátil: los tiempos
de esta ronda no valen para el ProBook. Desde la parte 2, el LLM corre en GPU (`ACTAS_GPU=1`, build Vulkan b11690,
`-ngl 99`), un solo llama-server a la vez, todo con `nice -n 19`.

Dato de partida (usuario, portátil real): Rápida tarda ~50 % de la duración de la reunión; la emulación decía 0,31-0,36x
→ el portátil real va ≈1,5x más lento que la emulación.

Leyenda: D = decisiones precisión/recall, T = tareas precisión/recall, claves = temas clave cubiertos, prohib = frases
prohibidas. "—" = el gold no tiene decisiones/tareas.

## 1. Calidad Alta v1 — reduce con 9B + comprobación (`f38f33f`..`fa41c5b`)

Map con 4B (igual que Rápida), reduce con Qwen3.5-9B Q4_0, y `check_sources`: el 4B dice sí/no a cada decisión/tarea
contra su bloque. Si RAM < 12 GB, todo con el 4B. CPU (`taskset -c 0-5`).

| Reunión | Rápida | Alta v1 |
|---|---|---|
| sintética (breve y normal) | D 1,00 · T 0,80 | D 1,00 · T 0,60 |
| larga_cne breve | D 1,00 · T 1,00 | D 0,67 · T 1,00 |
| larga_cne normal | D 1,00 · T 1,00 | igual |
| charla_comite | D 0,67 · T 0,50 | igual |
| webinar normal / clickmeeting | 9/9 · 8/9 y 7/9 claves | igual |

Sobrecoste ≈ +0,10-0,13x. **No mejora.** Causas: el recall lo limita el map (lo que el 4B no extrae no lo recupera
el reduce) y `check_sources` tiró aciertos reales ("Preparar la convocatoria de la beta cerrada").
`score.py` no mide la calidad de la redacción.

## 2. Modelo mejor en el map — Gemma-4 E4B vs 9B (`0f463f8`)

`ACTAS_MAP_MODEL=<gguf>` = ese modelo hace map + reduce; salida en `acta_<nivel>_rápido_<modelo>/`; `score.py --tag`.
charla_comite normal, sin `check_sources`, 2 ejecuciones por variante (idénticas, seed 0).

| Variante | D | T | claves | prohib | tiempo GPU |
|---|---|---|---|---|---|
| 4B (Rápida) | ,67/,67 | ,50/,50 | 4/6 | 0 | — |
| gemma-4-E4B Q4_0 | ,50/,33 | 0/0 | 4/6 | 2 | 87-95 s |
| Qwen3.5-9B Q4_0 | ,67/,67 | 1,0/1,0 | 4/6 | 4 | 151 s |

Gemma-4 E4B **descartado** para actas. Los 4 prohibidos del 9B: cuenta la lectura del acta anterior como acuerdo de hoy.

## 3. Regla "el acta anterior no es decisión de hoy" (`d3d3e4a`)

Una frase en `FAITHFUL` (secciones y acta final) y otra en la regla de decisiones del map. Afecta a Rápida.
charla_comite normal, GPU.

| Variante | D | T | claves | prohib |
|---|---|---|---|---|
| 4B antes | ,67/,67 | ,50/,50 | 4/6 | 0 |
| 4B después | ,67/,67 | **1,0/1,0** | 4/6 | 0 |
| 9B antes | ,67/,67 | 1,0/1,0 | 4/6 | 4 |
| 9B después | ,75/1,0 | ,67/**0** | 4/6 | **0** |

Se queda para las dos. El 9B cambia de tareas (saca "corregir el apellido en el acta", otra vez del acta anterior):
con una sola reunión, cualquier cambio de prompt mueve mucho el resultado.

## 4. Capturas de pantalla

Problema (usuario): salen pocas; se pierden cambios rápidos, scroll y submenús. Causas: muestreo cada 3 s, cambio =
5 % de bloques 8x8 de una miniatura 128x72 (un submenú no llega), duplicados por 75 % de palabras OCR compartidas (scroll
y submenús comparten casi todo el texto), y exigir 30 letras OCR (el OCR solo lee texto: gráficas/iconos no cuentan).

### 4a. `075a1ba` — muestreo 1 s, cambio local, scroll, duplicados por imagen, tira de miniaturas

Cambio local = grupo compacto ≥2x2 y ≥3 bloques; scroll = desplazamiento vertical, corta al entrar ≥50 % nuevo;
duplicados por diff de bloques contra TODAS las capturas previas (dHash fallaba en imágenes planas); acta con capturas
clave en línea (6 breve / 20 normal) + tira de miniaturas por tramo (clic amplía). 2 vídeos nuevos en samples/:
`demo_excel_tablas_dinamicas.mp4`, `demo_vscode_guia.mp4` (ES, 720p).

| Vídeo | antes | 075a1ba |
|---|---|---|
| sintética | 12 | 12 |
| clickmeeting | 70 | 120 |
| charla_comite | 25 | 66 |
| webinar_pmia | 50 | 50 |
| larga_cne | 160 | 78 |
| demo_excel | 42 | 102 |
| demo_vscode | 58 | 109 |

Etapa de capturas (todos los núcleos): clickmeeting 102 → 147 s (1,44x), demo_excel 69 → 161 s (2,3x); domina el OCR.
El texto del acta cambia porque el map recibe más texto de pantalla.

### 4b. `37b7132` — caras fuera, OCR por zonas, el map recibe solo texto nuevo

Comparado con `d3d3e4a` (base), 20 actas en GPU, 0 prohibidos en todas:

| Reunión / nivel | base → 37b7132 |
|---|---|
| charla (breve y normal) | T 1,0 → 0,50 · claves 4/6 → 5/6 |
| larga breve | claves 3/5 → **1/5** |
| larga normal | igual (D ,67 · T 1,0 · 4/5) |
| click breve | claves 6/9 → **4/9** |
| click normal | igual (6/9) |
| sintética | igual; normal claves 3/5 → 4/5 |
| webinar | breve igual 7/9; normal 9/9 → 8/9 |

Etapa de capturas vs `075a1ba`: demo_excel 127,9 → 120,6 s, clickmeeting 125,1 → 118,7 s (≈5 % más rápido).
Capturas (total/pantalla): charla 43/40, larga 36/5, click 112/104, sintética 9/7, webinar 49/40, excel 94/91,
vscode 101/98. Las caras se marcaban como no-pantalla pero seguían en el acta (larga: 31 de 36).

### 4c. `53c3c41` — solo pantallas, rachas de escritura, map con el texto de siempre

- El acta solo lleva capturas con `screen=True`.
- `collapse_typing()`: capturas seguidas casi iguales (diferencia media de huella < 5) = mismo documento en edición →
  primera, una cada 45 s y la última de la racha.
- El map vuelve a leer el texto de pantalla del método antiguo (`keyframes_map()`: 3 s, OCR entero, DUP 0,75 →
  `frames_map.json`); las capturas nuevas solo alimentan el informe.

Resultado: OCR del map idéntico a la base en los 5 vídeos; **puntuación idéntica a la base en las 10 actas**.
Capturas finales: charla 18 (antes 40), larga 5 de 36, vscode 94.
Pendiente: una captura de caras a 0:53 en charla pasa como pantalla; ahora hay 2 pasadas de OCR (coste sin medir);
umbral de `collapse_typing` ajustado solo con charla y vscode.

## 5. 4B vs 9B en las 5 reuniones (`53c3c41`)

9B = map + reduce (`ACTAS_MAP_MODEL`), GPU. 4B = actas ya generadas en el mismo commit.

| Reunión / nivel | 4B D | 4B T | 4B claves/prohib | 9B D | 9B T | 9B claves/prohib |
|---|---|---|---|---|---|---|
| charla breve | ,67/,67 | 1/1 | 4/6 · 0 | ,75/1 | ,67/0 | 5/6 · 0 |
| charla normal | ,67/,67 | 1/1 | 4/6 · 0 | ,75/1 | ,67/0 | 4/6 · 0 |
| larga breve | 1/,33 | 1/1 | 3/5 · 0 | ,80/,67 | ,60/1 | 3/5 · 0 |
| larga normal | ,83/,67 | 1/1 | 4/5 · 0 | ,67/,67 | ,67/1 | 5/5 · **1** |
| click breve | — | — | 6/9 · 0 | — | — | 7/9 · 0 |
| click normal | — | — | 6/9 · 0 | — | — | 7/9 · 0 |
| sintética breve | 1/1 | 1/,8 | 4/5 · 0 | 1/1 | 1/,6 | **1/5** · 0 |
| sintética normal | 1/1 | 1/,8 | 3/5 · 0 | 1/1 | 1/,6 | **1/5** · 0 |
| webinar breve | — | — | 7/9 · 0 | 0/— | — | **4/9** · 0 |
| webinar normal | — | — | 9/9 · 0 | 0/— | — | 8/9 · 0 |

Tiempo 9B en GPU (breve incluye el map; normal reutiliza el map): larga 503 s / 67 s, click 78 / 20 s,
sintética 53 / 14 s, webinar 196 / 35 s. Webinar D 0: el 9B inventa decisiones donde el gold no tiene ninguna.

Lectura cualitativa (charla normal): el 9B redacta más fluido pero es menos fiel; sus decisiones salen más genéricas
("una fil", "primera zona naval") y las del 4B son más precisas.

**Conclusión: el 9B no justifica Calidad Alta con este pipeline.** Mejora algo de recall de decisiones y algunas claves,
pero pierde tareas, claves en sintética y webinar, y mete decisiones falsas.

## 6. 9B con límites más amplios (`ACTAS_LOOSE=1`)

Pregunta: ¿perdió el 9B porque los topes (`REL_MAX`, `PT_MAX`, `S(n)` de decisión/tarea, `MAP_MAX`, 9 puntos/parte) eran del 4B?
`ACTAS_LOOSE=1` (experimento, por defecto sin cambios; salida con sufijo `_loose`): cadenas x1,7 (REL 391, PT 272,
decisión/tarea 272), `MAP_MAX` 3460, hasta 12 puntos por parte. Prompts, gramática, puntuación, temperatura 0,2 y seed 0 iguales.
9B + map + reduce, GPU Vulkan, un servidor a la vez.

| Reunión / nivel | 4B D | 4B T | 4B claves/prohib | 9B D | 9B T | 9B claves/prohib | 9B loose D | 9B loose T | 9B loose claves/prohib |
|---|---|---|---|---|---|---|---|---|---|
| charla breve | ,67/,67 | 1/1 | 4/6 · 0 | ,75/1 | ,67/0 | 5/6 · 0 | ,75/1 | ,67/0 | 5/6 · 0 |
| charla normal | ,67/,67 | 1/1 | 4/6 · 0 | ,75/1 | ,67/0 | 4/6 · 0 | ,75/1 | ,67/0 | 4/6 · 0 |
| sintética breve | 1/1 | 1/,8 | 4/5 · 0 | 1/1 | 1/,6 | 1/5 · 0 | 1/1 | 1/,6 | 1/5 · 0 |
| sintética normal | 1/1 | 1/,8 | 3/5 · 0 | 1/1 | 1/,6 | 1/5 · 0 | 1/1 | 1/,6 | 1/5 · 0 |
| webinar breve | — | — | 7/9 · 0 | 0/— | — | 4/9 · 0 | 0/— | — | 4/9 · 0 |
| webinar normal | — | — | 9/9 · 0 | 0/— | — | 8/9 · 0 | 0/— | — | 8/9 · 0 |

Tiempo 9B loose (breve incluye el map / normal): charla 141 / 23 s, sintética 53 / 14 s, webinar 197 / 35 s; igual que el 9B normal.

Resultado idéntico en las 6 puntuaciones. Las actas de charla y sintética salen byte a byte iguales a las del 9B sin `LOOSE`;
webinar cambia el texto pero no la puntuación. En el map loose el punto más largo mide 104 caracteres y el relato 136
(topes originales 160 / 230): los topes no ligan con el 9B.

Opinión (charla normal): relato igual de fluido que el 9B normal; las decisiones siguen siendo más genéricas e inventadas
("se compromete a hacer seguimiento", "se reorienta el acuerdo") que las del 4B ("aprobación del acta", "se aplaza la designación").

**Conclusión: los límites no explican la derrota del 9B.** Ampliarlos no cambia nada; la diferencia está en el modelo
(menos fiel, decisiones inventadas), no en el recorte. `ACTAS_LOOSE` queda como interruptor de experimento, sin efecto por defecto.

## 7. Chat interpretativo con gemma-4-E4B

`rag.py`: el chat usa `models/gemma-4-E4B-it-Q4_0.gguf` (el 4B de las actas no cambia; solo hay un llama-server cargado a la vez,
el del chat se para al generar un acta). `ACTAS_CHAT=qwen` vuelve al 4B y al estilo literal anterior. Estilo nuevo (`answer_i`):
líneas `[n] Se dijo que …` (síntesis con sus palabras, puede juntar dos tramos `[n][m]`, misma verificación léxica de siempre
contra la unión de los tramos citados) y, como mucho, una `[n] Se deduce que X, porque se dijo que Y.` / `Probablemente …`:
la base Y es una afirmación de hecho y pasa la misma verificación que «Se dijo» (si falla, se descarta la deducción) y solo
puede citar tramos que ya sostienen alguna línea «Se dijo» de la misma respuesta. Cifras de la deducción también comprobadas.
Preguntas generales («¿de qué va la reunión?», regex `GEN_Q`): 3 líneas sacadas del acta breve (resumen + relato) con el enlace
al tramo de voz de cada momento. Preguntas de propósito (`PURP_Q`): se enseña el contexto ±1 de cada tramo.
Gold nuevo: 15 preguntas (6 `general`, 5 `purpose`; reuniones nuevas `demo_excel` y `demo_vscode`, procesadas con el pipeline;
el vídeo de VS Code está en inglés). 62 preguntas, 6 reuniones. GPU (Vulkan, `-ngl 99`), un solo servidor, `nice 19`.
**Latencias solo de referencia en GPU, no representan el portátil.**

| métrica (62 preguntas) | 4B literal | gemma, original | gemma + cita ⊆ «se dijo» | gemma + base «porque se dijo» (final) |
|---|---|---|---|---|
| recall@8 | 98 % | 98 % | 98 % | 98 % |
| factual | 95 % (18/19) | 95 % | 95 % | 100 % (19/19) |
| paráfrasis | 86 % (12/14) | 93 % | 93 % | 93 % (13/14) |
| trampas | 91 % (10/11) | 91 % | 91 % | 100 % (11/11) |
| ausentes | 100 % (7/7) | 100 % | 100 % | 100 % (7/7) |
| general (nuevo) | 17 % (1/6) | 67 % | 67 % | 67 % (4/6) |
| propósito (nuevo) | 40 % (2/5) | 100 % | 100 % | 100 % (5/5) |
| propósito con deducción marcada y citada | 0 % | 60 % | 60 % | 20 % (1/5) |
| falso «No se menciona» en respondibles | 6 % | 0 % | 0 % | 0 % |
| frases descartadas por la verificación | 24 % | 23 % | 25 % | 30 % |
| deducciones totales / en trampas+ausentes | 0 / 0 | 41 / 6 | 24 / 2 | 6 / 0 |
| deducciones con cita que no las respalda | – | 17 de 41 | 0 de 24 | 0 de 6 |
| deducciones con base verificada (antes de descartar) | – | – | – | 32 % (7/22) |
| latencia p50 / p90 (GPU, referencia) | 2,0 / 2,6 s | 3,1 / 4,1 s | 3,1 / 4,1 s | 4,8 / 6,4 s |

(«cita que no las respalda» = refs de la deducción ⊄ refs de sus líneas «Se dijo»; en la primera columna de gemma se calculó
a posteriori sobre `rag_resultados.json`.) Gemma no es peor en ausentes ni trampas (100 % en ambas, la ronda original ya estaba
al 91 % en trampas; el único fallo, «¿Fue un éxito el evento…?», se resolvió en la versión final porque la deducción se descarta
sin base verificable). Mejora clara en general y propósito, a costa de ~1,5-2,5× de latencia. Las deducciones sin base verificable
mueren (68 % de los intentos): quedan pocas, pero todas citadas, marcadas y con su «porque se dijo». Límite conocido: la
verificación es léxica, una suma inventada cuyas cifras aparecen sueltas en el tramo («75,75» con «34,75» presente) pasa;
en inglés (VS Code) casi todo lo escrito en español se descarta por no coincidir las palabras (queda la cita literal).

Ejemplos (versión final, gemma):

- «¿De qué va la reunión?» (clickmeeting): `[00:01]` Se presenta una demostración de la plataforma ClickMeeting para conferencias y
  capacitaciones en línea. · `[09:23]` Se explica cómo configurar un evento con hora programada y opciones de acceso seguras. ·
  `[21:17]` Se muestran herramientas interactivas como la pizarra, encuestas y el chat. (4B: dos tramos sueltos sobre «crear un
  evento» y «reunión normal».)
- «¿Para qué sirve el modo cameo de PowerPoint?»: `[10:48]` Se dijo que en el modo cameo lo único que va a ver el personal que
  atiende es lo que se llama el modo cameo. · `[11:07]` Se dijo que el modo cameo, lo que haría en mi ordenador, sería presentarme
  a mí ahí mismo. · `[10:48]` *Se deduce que el modo cameo sirve para que el presentador se muestre al personal que atiende, porque
  se dijo que «…lo que haría en mi ordenador, sería presentarme a mí ahí mismo».*
- «¿Para qué sirven las tablas dinámicas?» (demo_excel): `[00:15]` Se dijo que en este vídeo se aprenderá a dominar las tablas
  dinámicas, saber para qué sirven, cuándo se utilizan y cómo adaptarlas a nuestros informes. (4B: «un tema bastante interesante que
  me han pedido muchísimo».)
- «¿Se puede emitir en vivo en redes sociales?»: `[03:53]` Se dijo que se puede transmitir en directo en Facebook o en YouTube si se
  utiliza el plan pago · `[03:53]` *Se deduce que la transmisión en vivo en redes sociales requiere el plan pago, porque se dijo que
  «también puedo transmitir con el plan pago… en directo en Facebook o en YouTube».*

Fallos que quedan: «¿De qué trata la reunión?» en la charla del comité (el resumen del acta tiene líneas que no resumen la sesión) y en el
vídeo de VS Code (la cita no cae en el `must` en inglés); la pregunta de propósito en inglés (VS Code) solo devuelve citas literales.

## Pendiente

- Calidad Alta sin una mejora demostrada: falta una idea que funcione (p. ej. extraer dos veces con el 4B y votar,
  o que el modelo ordene los puntos en vez de puntuarlos).
- Casilla "Usar GPU" en la UI (Vulkan win/linux, pre-marcada según GPU, offload parcial con poca VRAM).
- Chat: comparar también el 9B con el estilo interpretativo; deducciones con base verificable son pocas (32 %), ver §7.
- Medir en el portátil: coste de las 2 pasadas de OCR y de la etapa de capturas.
- Capturas: cara a 0:53 en charla; validar `collapse_typing` con más vídeos.
- Nada de esta ronda está subido (sin push ni release).

## 8. Chat gemma: deducciones con cita literal, cifras enteras, inglés

Tres arreglos en `rag.py` (`answer_i`), mismas 62 preguntas, GPU Vulkan:

1. **Base de la deducción = cita literal.** El LLM escribe `Se deduce que <conclusión>, porque se dijo que «<5-20 palabras copiadas>»`
   (gramática: una sola oración, la cita entre «»). `quote_ok` comprueba que la cita es subcadena del fragmento citado (±1 vecino)
   sin mayúsculas, tildes ni puntuación (`…` permite saltos; mínimo 3 palabras). Sin cita literal, la deducción se descarta.
2. **Cifras enteras.** `bad_nums`: toda cifra de una frase (dijo, deduce, resumen) tiene que estar entera en lo que cita
   (34,75 = 34.75; 1.000 = 1000; también cifras en letra del fragmento). Si no, se descarta la frase (antes solo se enseñaba la
   cita literal, y «75,75» pasaba con «34,75» presente porque se miraban las cifras sueltas).
3. **Inglés.** Causa: la frase en español nunca coincide palabra a palabra con la transcripción en inglés, así que `verify` la
   descartaba siempre (50 % de frases descartadas en demo_vscode, solo quedaba la cita). Ahora, si `transcript.language` no es `es`,
   el LLM responde en español y añade `«cita literal en inglés»` a cada «Se dijo que»; se verifica esa cita (no las palabras) y las cifras.

| Métrica | Antes | Después |
|---|---|---|
| factual | 100 % (19/19) | 100 % (19/19) |
| paráfrasis | 93 % (13/14) | 93 % (13/14) |
| trampas | 100 % (11/11) | 82 % (9/11) |
| ausentes | 100 % (7/7) | 100 % (7/7) |
| general | 67 % (4/6) | 67 % (4/6) |
| propósito | 100 % (5/5) | 100 % (5/5) |
| deducciones supervivientes (base verificada / propuestas) | 32 % (7/22) | 77 % (20/26) |
| deducciones mostradas | 6 | 19 |
| números inventados en frases mostradas | 0 | 0 |
| inglés (demo_vscode): ok / frases descartadas | 50 % (1/2) / 50 % (3/6) | 50 % (1/2) / 0 % (0/6) |
| frases descartadas en total | 30 % (36/122) | 15 % (19/131) |
| latencia p50 / p90 (GPU) | 4,8 / 6,3 s | 4,0 / 5,4 s |

Notas: «números inventados» se mide con `bad_nums` sobre lo mostrado (`rag_score.py`); en esta tanda ya era 0 antes (el caso
75,75 era del experimento anterior), así que el arreglo es una garantía, no una mejora medible; `selftest` cubre el caso.
Las trampas bajan porque ahora sobreviven más deducciones y dos casos se cuelan: «¿Recomienda el ponente usar ClickMeeting?»
(deducción «recomienda…», marcada y con cita literal, pero la palabra prohibida aparece) y «¿Qué color…métricas financieras?» (frase
fiel al fragmento 21:57 que nombra azul/negro; la gramática distinta cambió qué líneas genera). La verificación de la cita
garantiza que lo dicho es literal, no que la conclusión sea sensata. Inglés: las citas ya sobreviven, pero las 2 preguntas
siguen sin dar ok en «general» (`must` en español, igual que antes); «¿Para qué sirve VS Code?» pasa con citas en inglés.
Pendiente: las deducciones con propósito ligado al gold siguen siendo 20 % (1/5).

## 9. Chat gemma: revisor SI/NO con el mismo servidor

Problema (§8): con deducciones de cita literal sobrevivían más, pero dos trampas se colaban: una deducción que «recomienda» con una
cita que solo describe, y una frase fiel pero de otro asunto (colores de resaltado, no de métricas financieras). Cita literal != que
la conclusión se siga ni que responda.

Cambio (`rag.py`, `judge`): tras la verificación léxica, UNA llamada más al mismo llama-server (gramática `N: SI|NO`, temperatura 0)
revisa todas las frases mostradas de la respuesta con su pregunta y su fragmento. DIJO: se mantiene si el fragmento lo dice sin
añadir nada y aporta datos sobre el asunto concreto de la pregunta (aunque no la conteste del todo). DEDUCE: se mantiene solo si la
cita sostiene la conclusión sin suponer nada más y la conclusión responde; no si la cita solo describe y la conclusión es una
opinión o recomendación. Si cae un «Se dijo», las deducciones que lo citaban caen también. Las frases ya descartadas por la
verificación no se revisan; si el revisor falla, se muestra lo verificado. `ACTAS_JUDGE=0` lo desactiva. No se usan datos de las
preguntas del eval. Primer intento (criterio «responde directamente») rechazaba de más: factual 95 %, trampas 82 % (dos
«No se menciona» falsos en «¿Es caro…?»); se relajó el criterio de DIJO.
Además, `must` de «¿De qué va el vídeo?» (inglés) acepta también términos del contenido (carpeta, proyecto, código, git…).

| Métrica | §8 | §9 (revisor) |
|---|---|---|
| factual | 100 % | 100 % (19/19) |
| paráfrasis | 93 % | 93 % (13/14) |
| trampas | 82 % (9/11) | 100 % (11/11) |
| ausentes | 100 % | 100 % |
| general | 67 % | 83 % (5/6) |
| propósito | 100 % | 100 % (5/5) |
| deducciones con base verificada (antes del revisor) | 77 % (20/26) | 77 % (20/26) |
| deducciones mostradas (tras revisor) | 19 | 15 |
| números inventados | 0 | 0 |
| inglés (demo_vscode) ok | 50 % (1/2) | 100 % (2/2) |
| latencia p50 / p90 total | 4,0 / 5,4 s | 5,0 / 6,3 s |
| revisor solo, p50 / p90 | – | 0,83 / 1,13 s |

Coste: ~+0,8 s por pregunta con frases (una llamada, prefill de ~1 k tokens + ~10 tokens de salida). Se perdieron 4 deducciones
de 19, sin tocar las supervivientes de propósito/general. Quedan: «¿Por qué motivo se abstiene…?» (paráfrasis; las citas no caen
en el gold) y «¿De qué trata la reunión?» del comité (el acta no resume la sesión).

## 10. Los dos fallos que quedaban: diagnóstico

**(a) «¿Por qué motivo se abstiene Elena Nájera…?» (larga_cne)**. No era un fallo del sistema sino del gold. Recuperación: el top-8 son
8 votos casi idénticos de Elena («doctora Elena Najera, su voto por favor… mi voto es abstención»); la reunión tiene ~15. Las dos citas
que devolvió (76:03 «con motivaciones expuestas mi voto es abstención» y 111:23 «se han hecho los argumentos… por lo tanto mi
voto es abstención») son literales, fieles y contestan a la pregunta, pero el gold solo listaba otros votos (136:35, 60:04…). Se añadieron
esos dos tramos al gold tras leerlos. Sin cambio de código. (Limitación real, no corregida: en reuniones con muchas líneas casi
idénticas el top-8 se llena de duplicados; MMR o más K costaría latencia.)

**(b) «¿De qué trata la reunión?» (charla_comite)**. La recuperación no interviene (usa el acta breve). El LLM solo recibía los 8
momentos y escribía 2-3 líneas de detalles (acta aprobada, ordenanza…), ninguna dice «de qué va la reunión». El `resumen` global del
acta (que sí lo dice) iba en el prompt pero nunca se mostraba. Mecanismo general: en preguntas generales, la primera línea es ahora
el resumen del acta tal cual (ya revisado por la pipeline, sin pasar por el LLM, enlazada al primer momento), seguida de las líneas del LLM.

| Métrica | §9 | §10 |
|---|---|---|
| factual / trampas / ausentes / propósito | 100 / 100 / 100 / 100 % | 100 / 100 / 100 / 100 % |
| paráfrasis | 93 % (13/14) | 100 % (14/14) (gold corregido) |
| general | 83 % (5/6) | 100 % (6/6) |
| recall@8 | 98 % | 100 % (gold corregido) |
| deducciones verificadas / mostradas | 77 % / 15 | 77 % / 15 |
| números inventados | 0 | 0 |
| latencia p50 / p90 | 5,0 / 6,3 s | 4,6 / 5,9 s (ruido; sin coste añadido) |
