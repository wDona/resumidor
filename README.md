# Actas

Genera el acta de una videollamada grabada (1-3 h): resumen con nivel de detalle ajustable, decisiones, tareas,
capturas de la pantalla compartida y marcas `[mm:ss]` que saltan al momento del vídeo. Todo offline, solo CPU.

## Instalación

Requisitos: `ffmpeg`/`ffprobe` en el PATH y [uv](https://docs.astral.sh/uv/).

```sh
uv sync                                   # Python 3.12 + dependencias
# llama-server (binario CPU de https://github.com/ggml-org/llama.cpp/releases) en ./bin/
curl -L https://github.com/ggml-org/llama.cpp/releases/download/b11690/llama-b11690-bin-ubuntu-x64.tar.gz | tar xz -C bin
# modelo de lenguaje en ./models/ (si falta Qwen3.5-4B-Q4_0 se usa el primer .gguf que haya)
curl -L -o models/Qwen3.5-4B-Q4_0.gguf https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_0.gguf
```

En Windows, el zip `llama-bXXXXX-bin-win-cpu-x64.zip` de la misma página, descomprimido en `bin\`.

Los modelos de whisper se descargan solos la primera vez (small ≈ 480 MB, large-v3-turbo ≈ 1,6 GB).

## Uso

```sh
uv run app.py                                         # interfaz web (Gradio)
uv run pipeline.py video.mp4 --nivel breve --asr rápido --threads 4   # línea de comandos
uv run make_sample.py                                 # vídeo de prueba sintético en samples/
uv run pipeline.py --selftest
```

El acta queda en `work/<hash>/acta_<nivel>_<asr>/index.html` (abrible sin servidor; el vídeo va enlazado al lado)
y en un `.zip` sin el vídeo (el informe ofrece abrirlo si no lo encuentra). Hilos por defecto: núcleos lógicos / 2
(= físicos con hyperthreading; con más hilos que núcleos llama.cpp genera a menos de la mitad); `--threads` o
`ACTAS_THREADS` (GUI) lo cambian.

Referencia (reunión real de 30 min, 4 núcleos de un Ryzen 5500 con `taskset` emulando un HP ProBook 440 G8): ASR 124 s,
capturas+OCR 88 s, map 379 s, reduce 13 s (breve) / 52 s (normal) / 95 s (detallado): ≈ 0,34× la duración. En el ProBook
con RAM de un solo canal la generación va a la mitad: ≈ 0,45-0,5×. Pico de RAM: python 2,2 GB (ASR/OCR) y llama-server
3,0 GB (no a la vez), cabe en 8 GB.

## Arquitectura

1. `video_id`: hash rápido del vídeo → carpeta `work/<hash>/` con todas las cachés.
2. ASR: faster-whisper int8 en CPU con VAD → `transcript_<asr>.json` (cambiar el nivel no repite el ASR).
3. Vídeo: ffmpeg saca 1 miniatura gris cada 3 s; se compara por bloques de 8×8 sin el 5 % de arriba/abajo (barra de menús,
   reloj, dock) e ignorando bloques que cambian casi siempre en ±15 s (webcam superpuesta). Se corta cuando cambia >5 % de
   los bloques respecto al inicio del tramo.
4. De cada tramo estable (≥ 6 s) se guarda el último frame a resolución completa, descartando pantallas ya vistas.
5. RapidOCR (reconocedor latino PP-OCRv5, 7,5 MB, se baja solo a `models/`; sin red usa el chino/inglés de serie) sobre
   esos frames sin las franjas de arriba/abajo; se quita basura CJK. Si hay ≥ 80 letras es "pantalla compartida"; si no,
   son caras y se descarta. Pantallas cuyo texto contiene ≥ 75 % del de otra se fusionan: queda la más completa con la
   marca de su primera aparición.
6. La transcripción se trocea en bloques de ~3k tokens con el texto OCR de su intervalo.
7. Map: Qwen3.5-4B Q4_0 (llama-server, sin mmap ni caché de prompts) con gramática GBNF compacta generada del esquema
   (`gbnf`: JSON sin sangría y con máximos duros) → hasta 10 puntos de ≤ 20 palabras con importancia 1-5 (rúbrica con
   distribución forzada, ordenados por nota), ≤ 4 cifras/citas, decisiones y tareas solo explícitas. Lo caro en CPU es
   generar, así que la salida es corta a propósito. Marcas fuera del bloque se llevan al inicio del bloque.
   Caché `map_<asr>_<hash>.json`: el hash cubre prompt, esquema, modelo y entrada (transcripción + OCR). Se imprime el
   histograma de notas.
8. Selección por presupuesto: ranking global de puntos (nota, orden en el bloque); breve 20 %, normal 50 %, detallado 100 % (`LEVELS`). Decisiones y tareas entran siempre.
9. Reduce: breve = resumen; normal/detallado añaden secciones por tema. Decisiones y tareas pasan tal cual del map (sin
   reescribirlas con el LLM).
10. Render: breve = 3 capturas; normal = puntos por sección + capturas cercanas a los puntos elegidos (máx. 10); detallado = todos los puntos, cifras y citas, todas las capturas.
11. `app.py` es solo la GUI: llama a `pipeline.run` y muestra el `index.html` en un iframe + zip de descarga.
