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

Referencia (4 núcleos de un Ryzen 5500 con `taskset` emulando un HP ProBook 440 G8, `--asr rápido`, nivel breve):

| reunión | ASR | capturas+OCR | map | reduce b / n / d | total breve | × duración |
|---|---|---|---|---|---|---|
| comité 50 min | 242 s | 54 s | 487 s | 29 / 65 / 103 s | 813 s | 0,27 |
| webinar 70 min | 283 s | 75 s | 760 s | 27 s / – / – | 1148 s | 0,27 |
| sesión 2 h 22 | 834 s | 87 s | 1643 s | 83 / 213 / 343 s | 2650 s | 0,31 |

En el ProBook con RAM de un solo canal la generación puede ir bastante más lenta: medirlo allí. Pico de RAM: python
≈ 1,0-1,8 GB (ASR por ventanas: no crece con la duración) y llama-server 3,1 GB (no a la vez), cabe en 8 GB.

## Arquitectura

1. `video_id`: hash rápido del vídeo → carpeta `work/<hash>/` con todas las cachés.
2. ASR: faster-whisper int8 en CPU con VAD, por ventanas de 15 min (`ASR_WIN`): ffmpeg decodifica solo esa ventana
   (`-ss/-t`) y las marcas se desplazan; cada ventana lleva 30 s de más y la siguiente empieza en el primer segmento que
   cruzó el borde, así no se corta ninguna frase. La RAM no crece con la duración (faster-whisper hace la STFT de todo lo
   que recibe de golpe: con la reunión entera eran 6,9 GB en 2 h 20). Idioma detectado en la primera ventana.
   → `transcript_<asr>.json` (cambiar el nivel no repite el ASR).
3. Vídeo: ffmpeg saca 1 miniatura gris cada 3 s; se compara por bloques de 8×8 sin el 5 % de arriba/abajo (barra de menús,
   reloj, dock) e ignorando bloques que cambian casi siempre en ±15 s (webcam superpuesta). Se corta cuando cambia >5 % de
   los bloques respecto al inicio del tramo.
4. De cada tramo estable (≥ 6 s) se guarda el último frame a resolución completa, descartando pantallas ya vistas.
5. RapidOCR (reconocedor latino PP-OCRv5, 7,5 MB, se baja solo a `models/`; sin red usa el chino/inglés de serie) sobre
   esos frames sin las franjas de arriba/abajo; se quita basura CJK → `frames.json` (crudo). `screens` lo clasifica en
   cada ejecución: quita la interfaz de la videollamada (líneas cuyas dos primeras palabras salen en ≥ 30 % de los frames:
   barra de marcadores, "X está presentando", nombres de la columna de caras, paneles) y solo cuenta líneas de ≥ 2
   palabras con alguna en minúscula (los nombres bajo las caras y los botones no). Con ≥ 30 letras así es "pantalla
   compartida"; una cuadrícula de caras no. Pantallas cuyo texto contiene ≥ 75 % del de otra se fusionan: queda la más
   completa, con la marca de la primera aparición solo si el texto es ≥ 90 % igual. Pie de captura = primera línea de
   texto de la pantalla.
6. La transcripción se trocea en bloques de ~3k tokens (un resto < 40 % se une al anterior: si no, el bloque de cola solo
   trae la despedida) con el texto OCR de su intervalo. Los segmentos se funden en tramos de 15 s antes de poner `[mm:ss]`
   (menos tokens de entrada; leer el prompt va a ~45 tok/s en el ProBook).
7. Map: Qwen3.5-4B Q4_0 (llama-server, sin mmap ni caché de prompts) con gramática GBNF compacta generada del esquema
   (`gbnf`: JSON sin sangría y con máximos duros) → tema + hasta 10 puntos de ≤ 20 palabras con importancia 1-5 (rúbrica
   con distribución forzada; saludos, despedidas, agradecimientos y logística siempre 1) + decisiones y tareas. El prompt
   lleva reglas con contraejemplos: no son decisiones lo leído de un acta anterior, los pasos de una demo, opiniones ni
   propuestas sin aprobar; las opiniones se atribuyen; votos y cifras solo si se dicen. Cada decisión/tarea trae una
   `cita` literal: si sus pares de palabras no están (≥ 50 %) en la transcripción del bloque se descarta (inventada); si
   están (≥ 25 %) en el texto de la pantalla de ese intervalo, también (es un documento leído en voz alta, p. ej. el acta
   anterior); si no, su marca pasa a ser la del segmento de la cita. Cadenas con tope duro de longitud en la gramática. Lo caro en CPU es generar, así que la salida es corta a propósito.
   Caché `map_<asr>_<hash>.json`: el hash cubre prompt, esquema, modelo y entrada (transcripción + OCR). Se imprime el
   histograma de notas y los tokens de cada llamada.
8. Selección por presupuesto: ranking global de puntos (nota, orden en el bloque), sin las notas 1; breve 20 %, normal
   50 %, detallado 100 % (`LEVELS`).
9. Decisiones y tareas se deduplican entre bloques (≥ 78 % de palabras en orden; las tareas también si comparten la mitad
   de las raíces: la misma acción rutinaria redactada distinto). Después una llamada con los temas de toda la reunión se
   queda con las que de verdad lo son (el map solo ve un bloque y confunde consejos de una charla o cortesías con
   encargos); se cachea, así los tres niveles muestran las mismas.
10. Reduce jerárquico (nunca se pasa de contexto ni recorta): en normal/detallado una sección por bloque del map, con su
   `tema` de título y sus puntos elegidos de viñetas; el LLM solo redacta el resumen de la sección a partir de esas viñetas.
   El resumen global sale de los resúmenes de sección (breve: de los puntos elegidos) y, si hay más decisiones/tareas que
   el tope del nivel, el LLM elige las clave por número (breve 5/5, normal 12/10, detallado todas).
11. Render: breve = resumen + 8 puntos clave con marca + decisiones/tareas clave + 3 capturas; normal = secciones con sus
    viñetas y las capturas más relevantes (máx. 10); detallado = todos los puntos y todas las capturas. Solo se copian a
    `img/` las capturas mostradas. El vídeo se enlaza (o se copia una sola vez por vídeo en `work/<hash>/`).
12. `app.py` es solo la GUI: llama a `pipeline.run` y muestra el `index.html` en un iframe + zip de descarga.
