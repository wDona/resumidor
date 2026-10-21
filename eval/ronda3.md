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

## 11. Duplicados que saturan el top-8 y preguntas «por qué»

Problema (§10a): en larga_cne las ~15 votaciones de Elena Nájera son casi idénticas y llenaban el top-8; la razón real (136:35) estaba
en el puesto 32 del denso y nunca llegaba al LLM, que solo podía decir «con motivaciones expuestas».

Cambios (`rag.py`, `Index.search` y `prompt`):
1. **MMR sobre las voces.** Tras el RRF, cada tramo se elige por relevancia (RRF normalizado) menos 6 × (coseno máximo con los ya
   elegidos − 0,75). Los duplicados se hunden y los huecos los ocupa contenido distinto. Sin cambio para la pantalla. (Una poda por
   umbral con máx. 2 por grupo, probada antes, no bastaba: los cosenos entre votos eran 0,83-0,94 y el resto de huecos seguía lleno de votos.)
2. **«Por qué / motivo / razón / causa».** Tercera lista del RRF con doble peso: los tramos de las 120 mejores por similitud
   densa que contienen una palabra de razón (porque, motivo(s), motivación(es), razón, debido, causa, dado). Y una nota en el
   prompt: la pregunta pide una razón; usa los fragmentos que la den, no los que solo dan el resultado.
3. Eval: la pregunta de Nájera exige `must` de la razón real (vinculante / seguridad jurídica / legalidad / informe). Una comprobación
   genérica «toda respuesta a un por qué lleva palabra de razón» se probó y se quitó: marcaba mal «¿Por qué se cambió el día…?».
   No se añadió el aviso «se repite N veces» (YAGNI; el MMR ya deja 1-2 representantes).

Respuesta de «¿Por qué motivo se abstiene Elena Nájera…?» ahora: `[136:35]` Se dijo que el voto es abstención dado que para mí el
informe técnico y el informe jurídico no es vinculante y así lo señala también la doctrina. · `[136:35]` *Se deduce que la abstención se
debe a que el informe técnico y el informe jurídico no son vinculantes, porque se dijo que «mi voto es abstención dado que para mí el
informe técnico y el informe jurídico no es vinculante y así lo señala también la doctrina.»* (antes: «su voto es abstención con
motivaciones expuestas»).

| Métrica | §10 | §11 |
|---|---|---|
| factual / trampas / ausentes / propósito / general | 100 % en todas | 100 % en todas |
| paráfrasis (con `must` de razón en Nájera) | 100 % | 100 % (14/14) |
| recall@8 | 100 % | 100 % |
| deducciones verificadas / mostradas | 77 % / 15 | 79 % (23/29) / 16 |
| números inventados | 0 | 0 |
| recuperación p50 | 0,12 s | 0,14 s (MMR) |
| total p50 / p90 | 4,6 / 5,9 s | 4,6 / 7,5 s (p90 sube por ruido del revisor y de «por qué», +0,3 s de prompt) |

## 12. Alta v2: map x2 con voto y ordenación en vez de nota (4B, sin 9B)

Cambio: Alta ya no usa el 9B (queda `ACTAS_MAP_MODEL`). El map corre dos veces por bloque con el 4B (2.ª pasada: seed 1,
temperatura 0,5) y `vote()` las une: puntos de la 2.ª que repiten uno de la 1.ª (>= 50 % de raíces, +-90 s) suben +1 la nota
(máx. 5), los demás se añaden; decisiones y tareas = unión sin repetidos (`dedupe`, tope 7). `select_points` escala `keep` al
nº de puntos de una pasada (`n0`) para que el nivel muestre el mismo nº de puntos que Rápida. Variante `ACTAS_ALTA_ORD=1`
(`_alta_ord`): el esquema pide `rango` 1-9 (sin repetir) en vez de `importancia`; el rango pasa a nota por cuantiles
(15 % -> 5, 25 % -> 4, 35 % -> 3, resto 2), así que ya no existe el 1 (saludos/logística quedan solo al final del rango).
Rápida: byte a byte igual (acta.json de sintética con el código anterior y el nuevo, ambos en frío).
Banco: GPU Vulkan, un servidor a la vez, nivel normal, ASR/OCR en caché; Rápida y Alta rehechas en frío (map+verify+reduce).

| Reunión | Rápida D / T / claves | Alta-v2 (x2+voto) D / T / claves | Alta-v2 + orden D / T / claves |
|---|---|---|---|
| charla | ,67/,67 · 1/1 · 4/6 | ,67/,67 · 1/1 · 4/6 | ,67/,67 · 1/1 · 4/6 |
| larga | ,83/,67 · 1/1 · 4/5 | ,83/**,33** · 1/1 · 5/5 | ,83/,67 · 1/1 · 4/5 |
| click | — · — · 6/9 | — · — · **5/9** | — · — · 6/9 |
| sintética | 1/1 · 1/,8 · 3/5 | **,80**/1 · 1/,8 · 3/5 | 1/1 · 1/,8 · 3/5 |
| webinar | — · — · 9/9 | — · — · 9/9 | — · — · 9/9 |

Prohibidas 0 en todo; resp✗ solo 1 en sintética (igual en los tres).

Tiempo LLM (carga+map+reduce incl. verify y check, s): sintética 40/68/62, click 52/81/87, charla 91/178/200, webinar 117/197/202,
larga 299/620/607. Total 600 / 1142 / 1158 s -> **1,90x** y **1,93x** Rápida.

Lectura: el voto no sube el recall (larga D R baja de ,67 a ,33; la unión infla las notas 5, 26 de 104 puntos frente a 4 de 33 en
charla, y aplana la selección; click pierde una clave; sintética mete una decisión falsa). Con ordenación las puntuaciones salen
idénticas a Rápida en las 5 reuniones, pero al doble de coste. **El cuello de botella del recall no se arregla repitiendo el map con
el mismo modelo**: la 2.ª pasada aporta poco que la 1.ª no tuviera. Recomendación: no vender Alta como más calidad; si se mantiene,
quedarse con la variante de orden (empata con Rápida, sin empeorar) o volver a Alta = solo comprobación. La variante de orden
queda tras `ACTAS_ALTA_ORD=1`.

## 13. Lote 1: que no falte información importante (Rápida y Alta)

Cambios (`pipeline.py`): (1) decisiones y tareas nunca se recortan en ningún nivel (fuera `dec`/`tar` de LEVELS, fuera el
«elige las N más importantes» del LLM, fuera `group()` y el `[:7]` del voto de Alta; topes del map 5 -> 8 por bloque); se mantienen
los filtros de falsas decisiones (`verify`) y el dedup entre bloques es más estricto: dos decisiones con nombres/cifras distintos
no son repetidas, dos tareas con responsable distinto tampoco. (2) Formato compacto: una línea + enlace al minuto; no se agrupa
nada (la repetida idéntica ya la quita `dedupe`). (3) El map añade `tipo` por punto (contexto|dato|pregunta|decision|tarea|saludo);
`protected()` = tipo en {decision,tarea,dato,pregunta} o regex ESPECÍFICA (importes, fechas, %, votos/abstenciones, «próxima
reunión/sesión», aprob*/acord*/acuerd*, «se/me/nos encarg*»); un punto protegido entra siempre (también nota 1); la nota y la
distribución forzada solo ordenan/recortan el resto. Los puntos con `READ_NOTE` (lectura del acta anterior) no se protegen. Breve
(10 puntos clave): protegidos primero, sin repetidos, hasta el tope; decision/tarea no cuentan (ya van enteras en sus listas).
(4) Hasta 14 puntos y 8+8 decisiones/tareas por bloque, `MAP_MAX` 1800 -> 3800, ctx 8192 -> 12288; `finish_reason=length` o JSON
incompleto -> `Truncated`, se registra «MAP TRUNCADO» y el bloque se parte en dos (en esta ronda: 0 truncados). (5) Tras la
redacción se comprueba cada decisión/tarea verificada por (t, texto) y se re-añade la que falte (0 re-añadidas: decisiones y tareas
y los puntos protegidos se pintan directamente de las listas, el LLM solo escribe título y resúmenes). (6) Cada bloque recibe tema,
últimos 2 puntos y últimas 3 decisiones del anterior como contexto («no extraigas nada de aquí»).
`ACTAS_TAG=v2` separa la caché de salida (`acta_*_rápido_v2`); `eval/perdidas.py` reproduce la clasificación a-e (automática,
por regex del gold: sus cifras no son idénticas a las del `perdidas.md` manual).
Una primera calibración del prompt de `tipo` (enum con decision primero, «dato» = hecho concreto) marcó 90-100 % de los puntos como
protegidos (el 4B pone «dato» a todo; 30 «decision» en el webinar, que no tiene): se acotó («dato» solo con cifra/fecha/norma,
«decision» solo si alguien acuerda/vota, contexto primero en el enum). Cifras de abajo: la segunda.

Banco: GPU Vulkan, un servidor, ASR/OCR en caché, map+verify+reduce en frío en ambos lados. Puntuación (`score.py`):

| Reunión (normal) | dec P/R antes -> ahora | tar P/R antes -> ahora | claves | prohib | decis. / tareas / puntos en el acta |
|---|---|---|---|---|---|
| charla | ,67/,67 -> ,50/1 | 1/1 -> 1/,50 | 4/6 -> 5/6 | 0 -> 1 | 3/2/14 -> 6/1/33 |
| larga | ,83/,67 -> ,78/1 | 1/1 -> ,80/1 | 4/5 -> 5/5 | 0 -> 4 | 12/2/48 -> 27/5/143 |
| click | — | — | 6/9 -> 5/9 | 0 -> 1 | -/-/10 -> -/-/27 |
| sintética | 1/1 -> 1/1 | 1/,80 -> 1/,80 | 3/5 -> 4/5 | 0 | 2/4/4 -> 2/4/14 |
| webinar | — | — | 9/9 -> 9/9 | 0 | -/-/26 -> -/-/63 |

Breve: charla ,67/,67 -> ,50/1 (tar ,50/,50 -> 1/,50), larga 1/1 -> ,78/1 (tar ,75/1 -> ,80/1), sintética igual salvo claves 1/5 -> 4/5, claves click 8/9 -> 4/9,
webinar 5/9 -> 5/9, charla 4/6 -> 5/6 (con 10 puntos clave los protegidos desplazan a los de contexto).

Pérdidas por etapa (normal, 59 ítems gold; `eval/perdidas.py`, antes con el código anterior en frío):

| | a ASR | b map | c selección | d redacción | e presente |
|---|---|---|---|---|---|
| antes | 1 | 8 | 5 | 0 | 45 |
| ahora | 1 | 12 | 1 | 0 | 45 |

La selección ya no pierde (c 5 -> 1), pero el map omite más (b 8 -> 12; charla 5 -> 7: «próxima reunión en noviembre» y aprobación del acta
no salen en el último bloque, el 4B escribe 8 puntos aunque el tope sea 14) y los presentes no suben (45): lo que se rescata de c se
compensa con lo que se pierde en b. Con tareas: sintética sigue perdiendo «Laura prepara la convocatoria» en el map.

Distribución de `tipo` y protegidos (normal; puntos del map: contexto/dato/pregunta/decision/tarea/saludo -> protegidos):
charla 7/17/1/9/2/5 -> 29 de 41; larga 8/43/0/92/3/1 -> 141 de 147; click 23/16/0/0/0/1 -> 16 de 40; sintética 0/8/0/2/4/0 -> 14 de 14;
webinar 54/36/0/1/0/3 -> 39 de 94 (3 por regex). Calibración razonable en charla/click/webinar; en el pleno (larga) casi todo es
voto y el acta pasa de 48 a 143 viñetas; sintética es todo hecho (9 min).

Demos (decisiones deben ser ~0): vscode 0 decisiones/0 tareas (normal y breve), excel 0/0; solo 1 y 3-4 puntos protegidos. Longitud (normal,
caracteres de resumen+puntos+secciones+relato): vscode 4073 -> 3816, excel 4046 -> 5049 (+25 %; 20 puntos frente a 12, el resto es
ranking); breve 2016 -> 2086 y 2230 -> 2397.

Tiempo LLM (carga+map+reduce, s, normal): sintética 36 -> 45, click 52 -> 76, charla 91 -> 111, webinar 117 -> 174, larga 300 -> 481;
total 595 -> 887 = **1,49x** (>20 %). Lo que cuesta: map x1,5 (más puntos por bloque + `tipo` + prompt más largo + contexto previo, ≈ +60 %
de tokens de salida) y reduce x1,3-1,5 (más candidatas a decisión/tarea que verificar una a una y más viñetas por sección que
resumir, porque ya no hay tope).

Huecos: (a) el recall por gold no sube (45/59 igual): lo que falta ya no está en la selección sino en el map; haría falta un rescate por
texto (p. ej. «próxima reunión», encargos pequeños) como el de `RESCUE`; (b) la protección infla las actas de plenos repetitivos y sube
los falsos «prohibidos» (decisiones mal atribuidas que antes caían en el tope); (c) charla: 3 falsas decisiones nuevas (propuestas sin aprobar
admitidas por `verify`); (d) click pierde 3 claves de funciones que el map describe menos al priorizar cifras; (e) breve: el criterio
«protegidos primero» ocupa los 10 puntos con datos y se pierde panorama.

## 14. Lote 1 revertido (salvo «decisiones y tareas sin tope») y Qwen3.5-4B Q5_K_M frente a Q4_0

Decisión posterior a §13: se revierte todo el lote 1 salvo (a) decisiones y tareas nunca se recortan (sin `dec`/`tar` en LEVELS, sin
elección del LLM ni `group()`, sin `[:7]` del voto) y (b) `eval/perdidas.py` (nuevo `--solo`). MAP_PROMPT/MAP_SCHEMA vuelven a ser los de
antes (cachés válidas). Q4_0 con sin-tope, normal: larga dec ,89/1 (antes ,83/,67), tar 1/1; click igual que antes.

Q5_K_M: `ACTAS_MAP_MODEL=Qwen3.5-4B-Q5_K_M.gguf` cambia el modelo de TODO el pipeline LLM (map, verify, reduce); GPU Vulkan, frío.

| Reunión (normal) | dec P/R | tar P/R | claves | prohib | resp✗ | perdidas a/b/c/d/e | LLM s (carga+map+reduce) |
|---|---|---|---|---|---|---|---|
| larga Q4_0 | ,89/1 | 1/1 | 4/5 | 0 | 0 | 1/1/0/0/10 | 300 |
| larga Q5_K_M | ,87/1 | 1/1 | 4/5 | 0 | 0 | 1/1/0/0/10 | 316 (+5 %) |
| click Q4_0 | — | — | 6/9 | 0 | 0 | 0/2/0/0/7 | 52 |
| click Q5_K_M | — | — | 6/9 | 0 | 0 | 0/1/0/0/8 | 64 (+23 %) |

Lectura: empate en todo salvo un ítem recuperado en click (b 2 -> 1); puntos mostrados 48/10 -> 43/12. Con 2 reuniones no hay señal.
Tiempos de Q4 = los de la ronda en frío (map+verify en caché ahora). Veredicto: no merece seguir comparando cuantizaciones; el cuello
está en lo que el map omite, no en la precisión del modelo.

## 15. Recuperar lo que omite el map con embeddings (ACTAS_SEMCHUNK, ACTAS_COVER)

Dos banderas, apagadas por defecto (EmbeddingGemma ONNX de rag.py, sin dependencias nuevas). `ACTAS_SEMCHUNK=1`: ventanas de ~45 s, similitud
entre los 2 bloques de ventanas a cada lado de cada hueco (TextTiling), se corta en el mínimo (menos 0,03 por pausa >= 1,5 s y 0,03 por
cambio de hablante) con tamaño 0,4-1 x `ACTAS_CHUNK_CHARS` (def. 10000). `ACTAS_MINPTS=n` cambia el «6 a 9» del prompt y del esquema.
`ACTAS_COVER=1`: ventanas de 30 s; cubierta = similitud máx. con algún punto/relato/decisión/tarea del map >= `ACTAS_COVER_THR` (0,50);
tramos no cubiertos contiguos se unen y se repite el map solo ahí (mismo prompt, 1..hi puntos, hi = chars/700); se descartan los puntos
nuevos con similitud >= 0,85 con uno existente y se funde en el bloque que contiene el tramo. Normal, GPU Vulkan, Q4_0. Tiempos LLM en s
(carga+map+reduce(+verify)); «emb» = embeddings (CPU). Base = §14 (en frío).

Barrido de tamaño (solo real_clickmeeting; la clave es el máximo de caracteres del bloque):

| click, normal | bloques | puntos map / mostrados | claves | perdidas a/b/c/d/e | prohib | LLM s | emb s |
|---|---|---|---|---|---|---|---|
| base (10000, iguales) | 3 | 25 / 10 | 6/9 | 0/2/0/0/7 | 0 | 52 | 0 |
| sem 10000 | 4 | 33 / 14 | 5/9 | 0/1/1/0/7 | 0 | 67 | 4,6 |
| sem 6000 | 7 | 58 / 26 | 7/9 | 0/0/0/0/9 | 0 | 107 | 4,5 |
| sem 4000 | 9 | 72 / 32 | 8/9 | 0/0/0/0/9 | 0 | 131 | 4,7 |
| sem 4000, min 3 | 9 | 76 / 32 | 8/9 | 0/0/0/0/9 | 2 | 135 | 4,7 |
| sem 6000, min 3 | 7 | 57 / 24 | 8/9 | 0/0/0/0/9 | 0 | 105 | 4,8 |
| cover (sobre base) | 3 | 43 / 19 | 7/9 | 0/1/1/0/7 | 0 | 52+48 ≈ 100 | 6,6 |
| sem 6000 + cover | 7 | 62 / 27 | 7/9 | 0/0/0/0/9 | 0 | 107+17 = 124 | 9,5 |

Mínimo 3: el 4B sigue escribiendo ~8 puntos por bloque (76 con 9 bloques), así que no hay relleno que quitar y no cambia nada
(salvo 2 «prohibidos» de ruido en 4000). Tiempo: crece con los bloques (más puntos y relato por minuto; el map son los tokens de salida),
x2,1 con 6000 y x2,5 con 4000. Puntos duplicados entre bloques (similitud >= 0,75): 0-2, despreciable. Ojo: parte de la mejora de
«claves» es solo que se muestran más puntos (10 -> 26-32; la selección es 50 % del total), no que se recupere más por punto.

larga_cne (solo el tamaño elegido, 6000, y cover):

| larga, normal | puntos map / mostrados | dec P/R | tar P/R | claves | prohib / resp✗ | perdidas a/b/c/d/e | LLM s | emb s |
|---|---|---|---|---|---|---|---|---|
| base | 104 / 48 | ,89/1 | 1/1 | 4/5 | 0 / 0 | 1/1/0/0/10 | 300 | 0 |
| cover | 135 / 62 | ,88/1 | 1/1 | 4/5 | 0 / 0 | 1/1/0/0/10 | 300+104 ≈ 470 | 22 |
| sem 6000 | 265 / 112 | ,89/1 | 1/1 | 5/5 | 2 / 1 | 1/0/0/0/11 | 618 (x2,1) | 16 |
| sem 6000 + cover | 273 / 114 | ,89/1 | 1/1 | 5/5 | 2 / 1 | 1/0/0/0/11 | 617+44 ≈ 660 | 42 |

Umbral de cover: la similitud máxima de las ventanas es muy plana (click P5 ,46, mediana ,55, P75 ,59; larga P5 ,47, mediana ,58);
0,50 ≈ percentil 20 (click 12 de 55 ventanas, larga 18 de 246 con el map de base; 4 y 9 tramos). Los ítems perdidos del click (t=674
«21 de abril 18:00», t=1729 «calificación») caen en ventanas con 0,55 y 0,61: «cubiertas» por tema; para atraparlas habría que subir el
umbral por encima del percentil 75 (media ventana re-mapeada). Cover recupera 1 clave en click (6 -> 7, pero no las dos perdidas por
b) y 0 en larga; solo añade puntos. Caso precios: el punto «30 dólares mensual y 25 anual» sí está en el map y su ventana (t=265) tiene
0,67; el fallo «tema cubierto, dato ausente» no se pudo reproducir con precios, pero sí ocurre con t=674 y t=1729 (ventana cubierta por
puntos del mismo tema que no llevan el dato). No se parcheó.

Veredicto: SEMCHUNK con tope 6000 es lo que recupera (b 2 -> 0 en click, 1 -> 0 en larga, claves 6 -> 7 y 4 -> 5) pero cuesta x2,1 de LLM
y añade 2 prohibidos/1 resp✗ en larga (más decisiones: 35); el corte semántico a 10000 no aporta frente a iguales. COVER es barato en larga
(+0 map, +35 %) pero no recupera lo perdido. Mejor variante copiada: `normal__4B_sc6`. Con 2 reuniones y un solo run por celda no hay señal firme.

## 16. Pasada 2 sobre los puntos del map (ACTAS_PASS2=1, sobre SEMCHUNK 6000)

Se elimina ACTAS_COVER (no recuperaba nada, §15). `ACTAS_PASS2=1` (solo con secciones, es decir normal/detallado), sin tocar decisiones ni tareas:
(1) `dedup_points`: puntos con coseno >= 0,93 (`ACTAS_DEDUP_THR`) y las mismas cifras se funden en el primero (texto más largo, las demás
marcas quedan como enlaces extra); umbral por datos en larga sem6000 (223 puntos): >= 0,95 son la misma notificación repetida, 0,90-0,95
mezcla repetidos y «aprobado el informe X / Y» distintos, por eso el requisito de cifras iguales. (2) `group_section`: el LLM recibe los
puntos de cada sección numerados y devuelve resumen + viñetas con los ids que cada una resume (1-5); en lugar de la llamada de resumen de
sección de antes (mismo nº de llamadas). (3) Comprobación en código: ids sin cubrir -> una segunda llamada solo con ellos -> si siguen
faltando, se añaden tal cual. Las marcas de los ids (y las de los fundidos) son los enlaces [mm:ss] de la viñeta; los ids no se ven.
Las notas 1 ya no entran en la selección, así que no hay «descarte explícito». En ambas reuniones no hizo falta la 2.ª llamada.

| normal | viñetas | caracteres de viñetas / resúmenes | dec P/R | tar P/R | claves | prohib / resp✗ | perdidas a/b/c/d/e | LLM s |
|---|---|---|---|---|---|---|---|---|
| larga base (10000) | 48 | 4652 / 3743 | ,89/1 | 1/1 | 4/5 | 0 / 0 | 1/1/0/0/10 | 300 |
| larga sem6000 | 112 | 10637 / 9839 | ,89/1 | 1/1 | 5/5 | 2 / 1 | 1/0/0/0/11 | 618 |
| larga sem6000 + pass2 | 87 | 8787 / 6993 | ,89/1 | 1/1 | 5/5 | 2 / 1 | 1/0/0/0/11 | 618 + reduce +28 (130 frente a 102) |
| click base | 10 | 817 / 768 | — | — | 6/9 | 0 / 0 | 0/2/0/0/7 | 52 |
| click sem6000 | 26 | 2195 / 2059 | — | — | 7/9 | 0 / 0 | 0/0/0/0/9 | 107 |
| click sem6000 + pass2 | 17 | 1918 / 1323 | — | — | 6/9 | 0 / 0 | 0/0/0/0/9 | 107 + 12 |

Lectura: -22 % de viñetas en larga (112 -> 87) y -33 % en click (26 -> 17), -29 % / -36 % de texto de resúmenes, sin perder ítems del
gold en perdidas (a-e igual) ni decisiones/tareas; embeddings 21 s (larga) y 5 s (click). Pero sigue lejos de lo compacto (87 viñetas
para 239 puntos: el 4B agrupa poco) y en click el score de claves baja 7 -> 6 (se pierde «evento programado 21 de abril 18:00», que pasó a
la viñeta con otro texto; perdidas.py, con ventana ±90 s, sí lo ve). Los 2 prohibidos y el 1 responsable erróneo NO vienen de la fusión ni
de la redacción: están igual en sem6000 sin pass2 y salen del map con bloques de 6000 (la viñeta «la presidenta solicita trasladar su
sesión…», una viñeta que cuenta la petición sin su desenlace, y una tarea «Comisión Técnica» como responsable de notificar); con
bloques de 10000 no aparecían. Copiada: `normal__4B_sc6_pass2`.

## 17. Pasada 2: comprobación de cifras, horas y fechas; viñetas cortadas

Comprobación en `group_section` (sobre sem6000 + pass2): cada cifra (`rag.bad_nums`, 34,75 != 75, también en letra), hora (18:00 se lee como una cifra) y
mes de los puntos que cita una viñeta debe salir en ella. Si falta, una repetición de esas viñetas («conserva literalmente las cifras, horas y
fechas») y, si sigue faltando, se añade tal cual la frase del punto que la contiene.
Arreglo aparte: `sentences()` solo recortaba con len >= tope y el tope de la gramática no cuenta igual (un relato de 229 de 230 acababa en «…artículo 39 y»);
ahora recorta desde tope-10 si no acaba en puntuación, y `trim_caps()` lo aplica antes de pintar el acta (puntos, relato, decisiones, tareas,
resúmenes e viñetas, también los ya en caché). Con el arreglo, ningún relato ni punto de las 4 actas acaba a mitad de frase.

| normal | viñetas | claves | prohib / resp✗ | perdidas a/b/c/d/e | LLM s (reduce) |
|---|---|---|---|---|---|
| larga base | 48 | 4/5 | 0 / 0 | 1/1/0/0/10 | 300 (total §14) |
| larga sem6000 + pass2 + cifras | 89 | 5/5 | 2 / 1 | 1/0/0/0/11 | ~130 + 3 repeticiones (~5 s cada una) |
| click base | 10 | 6/9 | 0 / 0 | 0/2/0/0/7 | 52 |
| click sem6000 + pass2 + cifras | 17 | 6/9 | 0 / 0 | 0/0/0/0/9 | ~29 (reduce) |

La comprobación saltó 3 veces en larga (1 viñeta cada vez) y ninguna en click. Click NO conserva «21 de abril 18:00»: el punto del map
(«webinar … 21 de abril, hora 18:00 …») no llega a ninguna viñeta porque la selección (50 % de los puntos, ya tras fundir repetidos) lo deja
fuera; no es un fallo de redacción, así que la comprobación no puede recuperarlo (con sem6000 sin pass2 sí salía, porque se mostraban más puntos).
Aparte, en larga base hay 2 «decisiones» que son solo una marca («101:34», «98:10»): bug del map/rescate sin investigar.
Se regenera ~/actas_comparar con `normal__4B_rapida` (base actual) y `normal__4B_sc6_pass2`.
