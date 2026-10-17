# Evaluación ronda 2 — actas (2026-10-17)

Banco: el de la ronda 1 (Ryzen 5 5500, `taskset -c 0-3,6-9 … --threads 4`, `--asr rápido`, Qwen3.5-4B Q4_0).
Código: `5ce213b`. Se sacaron todas las cachés de `work/`, así que las 12 actas se generaron desde cero, en serie
(breve → normal → detallado). RSS de python y de llama-server muestreado cada 1 s.

**Ruido:** desde las 00:54 otro proceso del usuario (uvicorn + ffmpeg, sin fijar a núcleos) gastó ~1 núcleo. Afecta al
final de charla y a todo el webinar; en esos dos vídeos los tiempos son una cota superior.

## 1. Tiempos

| vídeo | dur | ASR | capt+OCR | map (bloques) | s/bloque | reduce b / n / d | total breve | RTF breve | RTF b+n+d |
|---|---|---|---|---|---|---|---|---|---|
| real_clickmeeting | 29:49 | 130 | 92 | 406 (3) | 135 | 21 / 55 / 85 | 652 s | 0,36 (r1 0,34) | 0,45 |
| charla_comite* | 50:13 | 282 | 72 | 608 (3) | 202 | 35 / 81 / 122 | 1002 s | 0,33 (r1 0,30) | 0,40 |
| webinar_pmia* | 70:01 | 338 | 79 | 854 (6) | 142 | 32 / 107 / 155 | 1306 s | 0,31 (r1 0,29) | 0,38 |
| larga_cne | 141:50 | 708 | 86 | 1627 (14) | 116 | 85 / 216 / 323 | 2510 s | **0,30** (r1 0,38) | 0,36 |

Segundos; total = tiempo de pared del proceso. *Con carga ajena.

- La larga mejora un 23 %: 116 s por bloque (antes 163), porque los segmentos fundidos dejan el prompt en ~2,5 k tokens.
  El ASR por ventanas también va más rápido (708 s frente a 822).
- En charla y webinar el ASR va un 21-26 % más lento, pero coincide con la carga ajena. Click, medido sin carga, sale
  igual que en la ronda 1 (130 frente a 124).
- El último bloque de charla absorbe la cola: 4,3 k tokens de prompt y 266 s.

**Proyección ProBook (×1,0–1,3):**
- breve: click 11–14 min · charla 17–22 · webinar 22–28 · larga **42–54 min**;
- los tres niveles seguidos: 13–17 / 20–26 / 26–34 / 51–66 min.

Falta medirlo en el equipo real, con RAM de un solo canal.

**Pico de RAM:**

| | click | charla | webinar | larga |
|---|---|---|---|---|
| python | 0,97 GB | 1,71 | 1,11 | **1,63** (r1 6,86) |
| llama-server | 3,13 | 3,09 | 3,19 | 3,19 |

Python ya no crece con la duración y nunca coincide con llama-server: cabe en 8 GB. El README acierta.

## 2. Puntuaciones (1-10), ronda 1 → ronda 2

| acta | Fidel. | Cobert. | Dec/Tar | Estruct. | Marcas | Capturas | Nivel* | 2 h+* |
|---|---|---|---|---|---|---|---|---|
| click breve | 5→5 | 6→5 | 3→**10** | 7→7 | 8→9 | 6→6 | 7→7 | – |
| click normal | 5→5 | 7→6 | 3→**10** | 5→8 | 8→9 | 7→7 | | |
| click detallado | 6→5 | 8→8 | 3→**10** | 5→7 | 8→9 | 5→6 | | |
| charla breve | 3→4 | 5→5 | 2→2 | 6→7 | 6→9 | 3→3 | 5→6 | – |
| charla normal | 4→4 | 7→6 | 2→2 | 5→6 | 6→9 | 4→4 | | |
| charla detallado | 4→3 | 8→7 | 2→2 | 5→5 | 6→9 | 4→4 | | |
| webinar breve | 6→6 | 4→6 | 10→**2** | 6→7 | 8→9 | 6→8 | 6→7 | – |
| webinar normal | 6→6 | 6→6 | 10→**2** | 4→5 | 8→9 | 6→8 | | |
| webinar detallado | 6→6 | 8→8 | 10→**2** | 6→7 | 8→9 | 8→8 | | |
| larga breve | 5→4 | 5→**3** | 3→3 | 3→5 | 7→6 | 7→7 | 4→5 | 6→**3** |
| larga normal | 5→4 | 7→7 | 3→3 | 3→6 | 7→6 | 8→7 | | 7→6 |
| larga detallado | 5→4 | 7→8 | 3→3 | 3→5 | 6→6 | 8→7 | | 6→6 |
| **media** | **5,0→4,7** | **6,5→6,3** | **4,5→4,3** | **4,8→6,3** | **7,2→8,3** | **6,0→6,3** | **5,5→6,3** | **6,3→5,0** |

Media global: 5,7 → 5,9. UX del HTML: 6/10 (sin nota numérica en la ronda 1).

**Marcas** (5 por vídeo, contra la transcripción nueva):
- click 5/5 y webinar 5/5.
- charla 5/5 de posición, aunque `[32:12]` es lectura del acta anterior.
- larga 3/5: `[32:22] … Marques Sánchez` cae en el informe de Beltrán Ayala y `[44:12] García Samaniego` en el de
  Espinoza Cordero.

**GUI** (`app.py` + gradio_client, `reunion_sintetica.mp4`, nivel normal):
- Acta en 189 s. El iframe responde 200, el vídeo 206 (con Range) y el zip se descarga.
- Sin vídeo: «Sube primero un vídeo». Los textos de progreso están en español y son claros.
- Problemas:
  - En el map la barra se para ~2 min por bloque y no da tiempo estimado (en la larga, 14 saltos en ~30 min).
  - En Linux, `work/<hash>/video.mp4` es un symlink a `/tmp/gradio/…`; tras reiniciar, el acta pierde el vídeo.
  - Los errores de ffmpeg o llama-server llegan tal cual (`str(e)`, en inglés).

## 3. Problemas de la ronda 1

| # | estado | evidencia |
|---|---|---|
| 1 RAM del ASR | **Arreglado** | 1,63 GB en la larga. Fronteras de ventana (900 … 8100 s) sin huecos ni solapes |
| 2 Decisiones/tareas falsas | **Parcial; regresión** | click limpio. charla pierde su única decisión. webinar pasa de 0 a **5 tareas falsas**. larga baja de 35 a 24 decisiones, pero sin agrupar (N1, N4, N5) |
| 3 Sección ≠ viñetas | **Arreglado** | una sección por bloque, con el resumen sacado de sus viñetas |
| 4 Cola y despedidas | **Arreglado** | el webinar tiene 6 bloques y la sección final recoge las preguntas. Efecto secundario: N6 |
| 5 Opiniones como hechos | **No arreglado** | N3 |
| 6 Pantallas | **Arreglado** | fuera la cuadrícula de Meet y la webcam del webinar; desaparece el desajuste de 22:24. Nuevo: N7 |
| 7 Niveles | **Parcial** | breve: 8 puntos con marca y tope 5/5. En la larga solo cubre la primera mitad (N4) |
| 8 Cifras | **Arreglado** (quitado) | |
| 9 Reduce de 16 k | **Arreglado** en la entrada | la salida se corta (N2) |
| 10 Nombres | **No arreglado** | «Belés de Erdogo Catalina Lisabet» (Vélez Verdugo), «Discaíno Cardenas» |
| 11 Map lento | **Arreglado** | 116 s por bloque |
| 12 UX HTML | **Parcial** | ✓ «—», pie = título OCR, solo se copian las capturas mostradas (zip de webinar breve: 294 KB, antes 3 MB), una sola copia del vídeo. ✗ Título = nombre del fichero; «miniaturas» = `max-width:560px` sobre el JPG entero; «idioma es» |

## 4. Problemas nuevos o pendientes, por prioridad

**N1. Tareas falsas en charlas; la validación no quita ninguna (webinar Dec/Tar 10 → 2).**
- El webinar no tiene encargos, pero salen 5 tareas en los tres niveles, por ejemplo `[02:15] David López | David López`
  (cita: «No veo el chat… si me tenés que interrumpir»), `[35:01] Revisar las diapositivas… | Audiencia` y
  `[69:12] Contactar al ponente…`, una cortesía que el prompt excluye expresamente.
- `valid_*.json` conserva las 5, y el resumen breve las convierte en «Queda pendiente … contactar al ponente».
- Causa: `validate()` pasa los temas y el texto de cada entrada, sin la cita, y pide «las que de verdad lo son»; el
  modelo de 4B devuelve todas.
- Arreglo:
  - pedir los números a *descartar*, con la cita delante;
  - filtros baratos: tarea = responsable, sin verbo, o responsable «Audiencia» / «el orador»;
  - campo `tipo` (reunión / charla) en el primer map; si es charla, nada salvo cita con «acordamos / se aprueba».

**N2. Los resúmenes se cortan a mitad de palabra y a veces acaban en un carácter chino.**
- webinar normal: 1000 caracteres justos, termina en «…con bloques幅»; la sección [34:38] termina en «(contex».
- larga normal: termina en «…Valencia Torres, Mera,».
- larga detallado: 1600 caracteres, termina en «…las resoluciones por病».
- Causa: el `maxLength` de `S(n)` corta en seco, y `ch` admite CJK.
- Arreglo:
  - excluir el rango CJK en la regla `ch`;
  - tope un 50 % por encima de lo pedido y, si se alcanza, recortar en Python hasta el último punto.

**N3. Infidelidades graves (ronda 1 #5).**
- larga normal:
  - `[54:13] … recalificación de la postulante Elena Najira` y `[56:47] … Roberto Dromi Peñalva`: son la consejera y un
    jurista que ella cita;
  - `[26:59] José Cabrera solicita replazar su voto de abstención`: votó a favor;
  - `[60:04] Se rechaza la calificación original…` es el argumento de Nájera;
  - `[139:17] Se solicita traslado de la sesión al día siguiente por conflictos de agenda`: Nájera pidió la tarde por el
    grado de su hijo, se le negó y asistirá.
- larga detallado: inventa una «consejera Elena Magira».
- click normal: «webinar mensual … para grupos grandes, con micrófono abierto». Es al revés (10:32) y «mensual» no se
  dice. click breve: «Se acordó crear un webinar mensual».
- Causa: los puntos no dicen quién habla y no hay lista de personas.
- Arreglo:
  - `participantes` (nombre y rol, del pase de lista) en el map, pasados a los prompts de sección y final;
  - prohibir «se acordó / se determinó / queda pendiente» en los resúmenes si no hay decisión o tarea validada.

**N4. Breve de la larga: puntos clave solo de la primera mitad y «decisiones clave» = las cinco primeras.**
- Los 8 puntos van de 12:30 a 78:55: sin negativas (97-138) ni suspensión (138:31).
- Decisiones: `[15:08] Se conoce el primer punto del orden del día`, `[17:57] Se toma votación…`, más tres aprobaciones.
- El resumen no dice nada del patrón 4 a 1 ni de la suspensión.
- Causa:
  - `select_points` ordena por `(-nota, n)` con `n` = posición en el bloque. Con `cap=8` y 34 notas 5, el desempate
    estable elige los bloques 0-7;
  - el LLM elige por número y devuelve 1-5.
- Arreglo:
  - desempate round-robin entre bloques;
  - agrupar las decisiones repetitivas antes de elegir (ronda 1 #2c);
  - quitar las de trámite («se conoce», «se toma votación»).

**N5. El filtro «leída de la pantalla» tira la decisión real y deja pasar lo leído (charla Dec/Tar 2).**
- `descartada (leída de la pantalla): Aprobación del acta de sesión anterior con correcciones formales`: es la única
  decisión de hoy (34:19-36:28) y Decisiones queda en «—».
- Pasa `[33:02] Comunicar a las instituciones … titular y alterno`, que es lectura del acta anterior (33:08), con un
  responsable inventado.
- En los puntos, la lectura sigue saliendo como acuerdo de hoy: `[32:12] Se acuerda que la comisión normativa
  designará…`, `[31:53] Se acuerda que las inspecciones … sean competencia de inspectores regionales`. En detallado son 7
  de las 10 viñetas de la última sección.
- Causa: se compara la cita con **cualquier** pantalla del bloque y basta un 25 % de pares de palabras («el acta»,
  «en su»…).
- Arreglo:
  - comparar ±45 s de transcripción con la pantalla visible en ese momento (leer en voz alta da más del 50 % sostenido);
  - quitar las palabras vacías de los pares;
  - marcar en el map el tramo «vamos a dar lectura…» / «se acaba de terminar de dar lectura» con `lectura: true`.

**N6. La cola unida hace crecer el último bloque, pero sigue con un máximo de 10 puntos.**
- charla: el bloque 2 va de 29:57 a 50:13; 7 de sus 10 puntos son lectura de 30 a 33 min.
- De 36 a 50 min no queda nada en ningún nivel: aplazamiento de la designación (40:33), resolución 452-2022-SUNAFIL
  (43:55), próxima sesión en noviembre (48:16).
- Arreglo: `maxItems` proporcional al tamaño del bloque, o repartir el resto entre los dos últimos bloques.

**N7. Pies de captura basura y casi duplicados.**
- charla (vídeo de 480p): «aal fngora oe egunad y bao en er rEaoato duz», «delo por Sh».
- click normal: tres tablas de precios casi iguales (02:06, 02:21, 03:45).
- Arreglo:
  - título solo si ≥ 70 % de sus palabras salen en la transcripción o en un diccionario; si no, «Pantalla compartida»;
  - en normal, no repetir capturas con DUP ≥ 0,5 en menos de 3 min.

**N8. Responsables inventados**: «Secretaría Técnica», «Audiencia», «El orador». Aceptar el responsable solo si sale en
la cita o en `participantes`.

**N9. Duplicados y marcas repetidas en la larga.**
- Maridueña aparece en 130:17 y en 138:15 (la segunda es Jácome); hay 3 decisiones en `[47:21]`.
- Causa: con citas iguales, `find_quote` coge la última del bloque.
- Arreglo: buscar la cita a ±120 s de la `t` propuesta y deduplicar por nombre propio.

**N10. Pendiente:** nombres del ASR, título = nombre del fichero, progreso dentro de cada bloque, vídeo de la GUI
enlazado al temporal.

## 5. Lo que funciona

- RAM resuelta: la larga cabe con holgura en 8 GB a RTF 0,30, unos 50 min en el ProBook.
- Secciones coherentes con sus viñetas.
- Marcas exactas: 15 de 15 fuera de la larga.
- La larga normal recoge las dos mitades, el 4 a 1 por informe, la abstención de Nájera y la suspensión.
- Click ya no inventa decisiones.
- Capturas del webinar limpias y con su título.
- GUI completa en español.

**Veredicto: no está listo para un usuario no técnico.**
- En reuniones formales, Decisiones y Tareas no son fiables en ninguno de los dos sentidos: charla omite la única decisión
  y webinar inventa 5 tareas.
- Los resúmenes atribuyen hechos a quien no los dijo y a veces se cortan con un carácter chino.
- Breve pierde la segunda mitad de una sesión de 2 h.
- Mínimo antes de entregarlo: N1, N2, N4 y N5.
