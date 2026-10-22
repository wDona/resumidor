# Modo "Máxima": LLM mayor para el map/reduce del acta

Prueba local mínima: UNA reunión corta (real_clickmeeting, 30 min), ASR rápido en caché, `--calidad alta`, `ACTAS_MAP_MODEL=<gguf>`,
RX 6600 8 GB + 31 GB RAM, `nice -n 19`. Salidas en `~/actas_comparar/real_clickmeeting/normal__{9B,35B}_alta/`. Puntuación con `eval/score.py --tag alta_<modelo>` (claves; el gold de esta reunión no tiene decisiones/tareas, así que no hay P/R de ellas).
Línea base de RAM 5 GB y VRAM 1,75 GB ya ocupadas por el escritorio; los picos son totales.

| modelo | tiempo (map+reduce) | RAM pico | VRAM pico | claves (gold 9) | "21 abril 18:00" | notas |
|---|---|---|---|---|---|---|
| 4B Q4_0 alta (ref.) | map en caché; reduce 27 s | - | - | 6/9 | perdido | pierde también pizarra y calificación |
| 9B Q4_0 (5,1 GB) | 220 s total (map 147, reduce 50) | 7,3 GB | 6,8 GB | 9/9 | recuperado | cabe entera en VRAM, ~6 s/llamada |
| 35B-A3B Q4_K_M (21 GB) | 840 s total (map 604, reduce 149, carga 66) | 26,8 GB | 1,8 GB (no usó GPU) | 8/9 (falta precios) | recuperado | el arranque en GPU falló y el pipeline cayó a CPU (~90 s por bloque); ~4x el 9B |

Funciona y devuelve un acta decente en ambos. El 9B es mejor que el 4B en esta reunión sin coste notable. El 35B no mejora al 9B aquí y cuesta ~4x en esta máquina.
No se repitieron larga_cne (prohibidos / responsable erróneo del 4B): sin comprobar.
Para usar GPU parcial con MoE haría falta pasar `--n-cpu-moe N` (o `-ot exps=CPU`) a `launch(... extra ...)`; hoy `llama()` fija `extra` y no hay hook por entorno. Cambio mínimo: leer `ACTAS_LLAMA_ARGS` y añadirlo a `extra` en `llama()`. Además el arranque en GPU falló con 35B (causa no investigada: log sobrescrito por el reintento en CPU).

## Calidad según benchmarks públicos (fichas oficiales de Qwen, medidas por Qwen)

| benchmark | gpt-oss-20B | Qwen3.5-9B | Qwen3.5-35B-A3B | gpt-oss-120B |
|---|---|---|---|---|
| IFEval (seguir instrucciones) | 88,2 | 91,5 | 91,9 | 88,9 |
| AA-LCR (contexto largo) | 30,7 | 63,0 | 58,5 | 50,7 |
| LongBench v2 | 45,6 | 55,2 | 59,0 | 48,2 |
| MMMLU (multilingüe) | 69,7 | 81,2 | 85,2 | 78,2 |

Fuentes: https://huggingface.co/Qwen/Qwen3.5-9B , https://huggingface.co/Qwen/Qwen3.5-35B-A3B (no se consultaron Gemma/Mistral; sin benchmark de resumen en español propio).
gpt-oss-20b queda por debajo del 9B en todo, así que se descartó (no probado localmente). El 35B-A3B gana en multilingüe y contexto largo (LongBench) pero la diferencia con el 9B es pequeña.

## Recomendación

- Máxima = Qwen3.5-9B Q4 en cualquier equipo con >= 8 GB de VRAM (o >= 12 GB RAM en CPU, más lento): mejora medida (9/9 vs 6/9) y 220 s en 30 min de reunión.
- Mínimo para el 9B: GPU 8 GB (6,8 GB usados con contexto) o CPU con 16 GB RAM.
- 35B-A3B Q4_K_M (sin probar en GPU; datos públicos): ~21 GB de pesos; práctico con >= 32 GB RAM + GPU >= 8 GB con `--n-cpu-moe` (solo ~3B activos por token), o 24 GB de VRAM para entero. Solo vale la pena como "Máxima+" tras confirmar mejora real; aquí no se vio.
