# Actas

Genera el acta de una videollamada grabada (1-3 h): resumen con nivel de detalle ajustable, decisiones, tareas,
capturas de la pantalla compartida y marcas `[mm:ss]` que saltan al momento del vídeo. Todo offline, solo CPU.

## Instalación

Requisitos: `ffmpeg`/`ffprobe` en el PATH y [uv](https://docs.astral.sh/uv/).

```sh
uv sync                                   # Python 3.12 + dependencias
# llama-server (binario CPU de https://github.com/ggml-org/llama.cpp/releases) en ./bin/
curl -L https://github.com/ggml-org/llama.cpp/releases/download/b11690/llama-b11690-bin-ubuntu-x64.tar.gz | tar xz -C bin
# modelo de lenguaje en ./models/ (cualquier .gguf; se usa el primero)
curl -L -o models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf \
  https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen3-4B-Instruct-2507-Q4_K_M.gguf
```

Los modelos de whisper se descargan solos la primera vez (small ≈ 480 MB, large-v3-turbo ≈ 1,6 GB).

## Uso

```sh
uv run app.py                                         # interfaz web (Gradio)
uv run pipeline.py video.mp4 --nivel breve --asr rápido --threads 4   # línea de comandos
uv run make_sample.py                                 # vídeo de prueba sintético en samples/
uv run pipeline.py --selftest
```

El acta queda en `work/<hash>/acta_<nivel>_<asr>/index.html` (abrible sin servidor; el vídeo va enlazado al lado)
y en un `.zip` sin el vídeo (el informe ofrece abrirlo si no lo encuentra). `ACTAS_THREADS` limita los hilos en la GUI.

## Arquitectura

1. `video_id`: hash rápido del vídeo → carpeta `work/<hash>/` con todas las cachés.
2. ASR: faster-whisper int8 en CPU con VAD → `transcript_<asr>.json` (cambiar el nivel no repite el ASR).
3. Vídeo: ffmpeg saca 1 miniatura gris cada 3 s; se corta cuando cambia >3 % de los píxeles respecto al inicio del tramo.
4. De cada tramo estable (≥ 6 s) se guarda el último frame a resolución completa, descartando pantallas ya vistas.
5. RapidOCR sobre esos frames: si hay ≥ 80 letras es "pantalla compartida"; si no, son caras y se descarta.
6. La transcripción se trocea en bloques de ~3k tokens con el texto OCR de su intervalo.
7. Map: Qwen3-4B (llama-server, JSON schema) → puntos con importancia 1-5 (rúbrica con distribución forzada, ordenados por nota), cifras/citas, decisiones, tareas (`map_<asr>_<hash>.json`; el hash del prompt invalida la caché). Se imprime el histograma de notas.
8. Selección por presupuesto: ranking global de puntos (nota, orden en el bloque); breve 20 %, normal 50 %, detallado 100 % (`LEVELS`). Decisiones y tareas entran siempre.
9. Reduce: breve = resumen + decisiones + tareas; normal/detallado añaden secciones por tema.
10. Render: breve = 3 capturas; normal = puntos por sección + capturas cercanas a los puntos elegidos (máx. 10); detallado = todos los puntos, cifras y citas, todas las capturas.
11. `app.py` es solo la GUI: llama a `pipeline.run` y muestra el `index.html` en un iframe + zip de descarga.
