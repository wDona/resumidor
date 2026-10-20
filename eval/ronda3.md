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

## Pendiente

- Calidad Alta sin una mejora demostrada: falta una idea que funcione (p. ej. extraer dos veces con el 4B y votar,
  o que el modelo ordene los puntos en vez de puntuarlos).
- Casilla "Usar GPU" en la UI (Vulkan win/linux, pre-marcada según GPU, offload parcial con poca VRAM).
- RAG interpretativo (síntesis citada + deducciones marcadas); comparar gemma-4-E4B y 9B para el chat.
- Medir en el portátil: coste de las 2 pasadas de OCR y de la etapa de capturas.
- Capturas: cara a 0:53 en charla; validar `collapse_typing` con más vídeos.
- Nada de esta ronda está subido (sin push ni release).
