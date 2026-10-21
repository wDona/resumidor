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
uv run app.py                                         # interfaz web local (se abre sola en el navegador)
uv run pipeline.py video.mp4 --nivel breve --asr rápido --threads 4   # línea de comandos
uv run make_sample.py                                 # vídeo de prueba sintético en samples/
uv run pipeline.py --selftest
uv run eval/score.py -v                               # actas de work/ contra eval/gold/*.json
```

La interfaz (`app.py`: FastAPI + `static/` en JS puro, sin CDN ni build) escucha solo en 127.0.0.1 en un puerto libre y abre el
navegador. «Elegir vídeo» abre el diálogo nativo del sistema (no copia el vídeo; también se puede soltar un fichero, que se guarda
en `uploads/`). El trabajo largo avanza en segundo plano con progreso y tiempo restante, y sobrevive a recargar la página
(`work/job.json`). Una segunda ejecución de `uv run app.py` solo abre la ventana ya existente (`.actas.lock`); el servidor se
cierra solo ~60 s después de cerrar la pestaña y apaga el modelo de lenguaje.

El acta queda en `work/<hash>/acta_<nivel>_<asr>/index.html` (abrible sin servidor; el vídeo va enlazado al lado)
y en un `.zip` sin el vídeo (el informe ofrece abrirlo si no lo encuentra). Hilos por defecto: núcleos lógicos / 2
(= físicos con hyperthreading; con más hilos que núcleos llama.cpp genera a menos de la mitad); `--threads` o
`ACTAS_THREADS` (GUI) lo cambian.

**Calidad Alta** (`--calidad alta`, campo `calidad` de la API, selector en la GUI): todo con el 4B. El map corre dos veces por bloque
(la 2.ª con semilla 1 y temperatura 0,5) y se unen por voto: unión de puntos, decisiones y tareas; un punto en las dos pasadas sube +1
la nota. Además `check_sources` (sí/no de cada decisión/tarea contra su bloque). `ACTAS_ALTA_ORD=1`: el modelo ordena los puntos
(rango) en vez de puntuarlos. Sin 9B (`ACTAS_MAP_MODEL` sigue sirviendo para un experimento). Salida en `acta_<nivel>_<asr>_alta/`
(`_alta_ord`); `eval/score.py --alta`. Medido en eval/ronda3.md §12: ≈1,9x el tiempo de LLM de Rápida, sin mejora de calidad.

Referencia (4 núcleos de un Ryzen 5500 con `taskset` emulando un HP ProBook 440 G8, `--asr rápido`, nivel breve):

| reunión | ASR | capturas+OCR | map | reduce b / n / d | total breve | × duración |
|---|---|---|---|---|---|---|
| comité 50 min | 242 s | 54 s | 487 s | 29 / 65 / 103 s | 813 s | 0,27 |
| webinar 70 min | 283 s | 75 s | 760 s | 27 s / – / – | 1148 s | 0,27 |
| sesión 2 h 22 | 834 s | 87 s | 1643 s | 83 / 213 / 343 s | 2650 s | 0,31 |

En el ProBook con RAM de un solo canal la generación puede ir bastante más lenta: medirlo allí. Pico de RAM: python
≈ 1,0-1,8 GB (ASR por ventanas: no crece con la duración) y llama-server 3,1 GB (no a la vez), cabe en 8 GB.

## Transcripción importada (Teams, Zoom, Meet, Otter…)

Una transcripción exportada **sustituye al ASR** (`transcripts.py`, solo biblioteca estándar; `--transcripcion FICHERO` en la línea
de órdenes o «Transcripción (opcional)» en la GUI, con diálogo o arrastrando el fichero). Formatos: WebVTT (Teams `<v Nombre>`, Zoom
`Nombre: texto`, ids tipo GUID, marcas `0:0:0.0`), SRT, TXT con cabeceras (`[hh:mm:ss] Nombre:`, `Nombre  0:05`, `Nombre (00:01:02)`:
Otter, Meet, Fireflies, tl;dv) y DOCX (Teams/Meet, se lee `word/document.xml`). Se limpian etiquetas y entidades, se funden los cues
seguidos del mismo hablante (≤ 20 s) y «Unknown»/«Desconocido»/teléfonos no cuentan como hablante.

- **Con vídeo**: no se ejecuta whisper sobre toda la reunión; se transcribe una muestra de 150 s (desde el minuto 1) y se busca el
  desfase (±10 min) que más palabras comunes alinea. Si hay certeza se aplica; si no, se usa 0 y queda un aviso en el acta y en la GUI.
  Capturas, OCR y vídeo condensado como siempre.
- **Sin vídeo**: acta sin capturas ni reproductor (marcas visibles, no enlaces); Preguntar también funciona.
- **Hablantes**: si el fichero trae nombres se usan en lugar de la diarización (la casilla se desactiva), aparecen como «Participantes»,
  llegan al map/tareas y a las citas de Preguntar. No se inventa ninguno.
- Caché: `transcript_imp<hash del fichero>.json` (no choca con `rápido`/`calidad`).
- Prueba: VTT estilo Teams generado desde el ASR de `reunion_sintetica` y desplazado +7 s: desfase recuperado -7,0 s; acta breve/normal
  con `eval/gold/reunion_sintetica.json`: decisiones 1,00/1,00, tareas 1,00/1,00 (ASR: 1,00/1,00 y 1,00/0,80), prohibidos 0.

Límites: un desfase que no sea constante (cortes, pausas) no se corrige; sin voz en la muestra no hay alineación.

## Hablantes y vídeo condensado

- **Hablantes** (opcional y experimental, desactivado por defecto: casilla en la GUI o `--hablantes`; ~0,7 % del tiempo total): sobre los segmentos del ASR (ya sin silencios), trozos de ≤ 5 s;
  huella de voz con 3D-Speaker CAM++ (sherpa-onnx, 27 MB, se baja solo a `models/`) y agrupación por distancia coseno
  (`DIAR_THR`); los grupos con < 4 % del total se funden con el más parecido. El acta y el prompt del map llevan
  «Hablante N»; en la GUI, «Hablante 1=Ana, Hablante 2=Luis» los renombra al pintar (sin repetir nada). Con un solo
  hablante no se etiqueta. Se probó la segmentación pyannote de sherpa-onnx: 220 s para 30 min en el ProBook emulado, descartada
  (ahora 12 s: reunión de 30 min; 20 s: comité de 49 min). Sin el modelo (sin red) se sigue sin hablantes.
- **Vídeo condensado** (`--condensar PCT`, 0 = el recomendado; en la GUI, deslizador + botón): quita los silencios > 1,5 s
  y después los segmentos de menos nota hasta PCT % (recomendado entre 20 y 70); una pasada de ffmpeg, h264_qsv si
  funciona o libx264. Reunión de 30 min, 67 % recomendado: 9:49 de vídeo, 42 s de codificación (libx264, 4 hilos).
  Se guarda en `work/<hash>/condensado_<pct>.mp4`.

## Arquitectura

1. `video_id`: hash rápido del vídeo → carpeta `work/<hash>/` con todas las cachés.
2. ASR: faster-whisper int8 en CPU con VAD, por ventanas de 15 min (`ASR_WIN`): ffmpeg decodifica solo esa ventana
   (`-ss/-t`) y las marcas se desplazan; cada ventana lleva 30 s de más y la siguiente empieza en el primer segmento que
   cruzó el borde, así no se corta ninguna frase. La RAM no crece con la duración (faster-whisper hace la STFT de todo lo
   que recibe de golpe: con la reunión entera eran 6,9 GB en 2 h 20). Idioma detectado en la primera ventana.
   → `transcript_<asr>.json` (cambiar el nivel no repite el ASR).
3. Vídeo: ffmpeg saca 1 miniatura gris por segundo (un cambio < 1 s se pierde); se compara por bloques de 8×8 sin el 5 %
   de arriba/abajo (barra de menús, reloj, dock) e ignorando bloques que cambian casi siempre en ±15 s (webcam superpuesta).
   Se corta cuando cambia >5 % de los bloques respecto al inicio del tramo **o** un grupo compacto (≥ 2×2, ≥ 3 bloques) de
   bloques (menú, submenú, diálogo). Un scroll (misma página desplazada en vertical) solo corta al entrar ≥ 50 % de
   contenido nuevo.
4. De cada tramo estable (≥ 2 s) se guarda el último frame a resolución completa, descartando los iguales a CUALQUIER
   captura anterior (A → B → A no repite A); ya no se deduplica por palabras de OCR.
5. RapidOCR (reconocedor latino PP-OCRv5, 7,5 MB, se baja solo a `models/`; sin red usa el chino/inglés de serie) sobre
   esos frames sin las franjas de arriba/abajo; se quita basura CJK → `frames.json` (crudo). `screens` lo clasifica en
   cada ejecución: quita la interfaz de la videollamada (líneas cuyas dos primeras palabras salen en ≥ 30 % de los frames:
   barra de marcadores, "X está presentando", nombres de la columna de caras, paneles) y solo cuenta líneas de ≥ 2
   palabras con alguna en minúscula (los nombres bajo las caras y los botones no). Con ≥ 30 letras así es "pantalla
   compartida"; también una captura sin texto con bordes (`edge` ≥ 0,05), poca piel (`skin` < 4 %) y < 3 nombres bajo caras
   (gráfico, imagen). Una cuadrícula de caras no, y las no-pantalla casi iguales (huella 32×18) se descartan. El OCR relee solo
   las zonas que cambian si son < 35 % de la pantalla (ahorro pequeño: casi todo el coste es leer capturas nuevas enteras).
   Al LLM (map) solo van las líneas de pantalla que no habían salido antes. El OCR solo alimenta al LLM con el texto de pantalla. Pie de captura = primera línea de texto, solo si
   ≥ 70 % de sus palabras salen en la transcripción (en vídeos de 480p el OCR da basura: entonces «Pantalla compartida»).
6. La transcripción se trocea en n = ⌈total / 10 000 caracteres⌉ bloques del mismo tamaño (~3k tokens; ni cola diminuta
   con solo la despedida ni un último bloque gigante con solo 10 puntos para 20 min) con el texto OCR de su intervalo. Los segmentos se funden en tramos de 15 s antes de poner `[mm:ss]`
   (menos tokens de entrada; leer el prompt va a ~45 tok/s en el ProBook).
7. Map: Qwen3.5-4B Q4_0 (llama-server sin mmap; `-ctxcp 2`: el prompt de sistema, igual en todas las llamadas de una fase,
   se lee una vez, −11 s por llamada, +100 MB; `seed` fija: misma entrada, misma acta) con gramática GBNF compacta generada
   del esquema (`gbnf`: JSON sin sangría, máximos duros y solo caracteres latinos: ni CJK ni `\uXXXX`) → tema + de 6 a 9 puntos (mínimo en la gramática: el último bloque ya no se queda en 5) de ≤ 20 palabras con importancia 1-5 (rúbrica
   con distribución forzada; saludos, despedidas, agradecimientos y logística siempre 1) + decisiones y tareas. El prompt
   lleva reglas con contraejemplos: no son decisiones lo leído de un acta anterior, los pasos de una demo, opiniones ni
   propuestas sin aprobar; las opiniones se atribuyen solo si está claro quién habla (un cargo no es un postulante, un
   jurista citado no participa); en demos «se muestra», nunca «se propone». Cada decisión/tarea trae una `cita` literal: si
   sus pares de palabras no están (≥ 50 %) en la transcripción del bloque se descarta (inventada); si no, su marca pasa a
   ser la del segmento de la cita (la aparición más cercana a la marca propuesta). Cadenas con tope duro de longitud en la gramática. Lo caro en CPU es generar, así que la salida es corta a propósito.
   Caché `map_<asr>_<hash>.json`: el hash cubre prompt, esquema, modelo y entrada (transcripción + OCR). Se imprime el
   histograma de notas y los tokens de cada llamada.
8. Selección por presupuesto (breve 20 %, normal 50 %, detallado 100 %, `LEVELS`; sin las notas 1) con cuotas por tiempo:
   los bloques se agrupan en g = min(k, bloques) tramos y cada uno aporta k // g puntos (los mejores suyos); el resto por
   ranking global. Así breve no se queda con la primera mitad cuando hay muchas notas 5. En breve se salta el punto con
   el mismo esqueleto (palabras en minúscula, ≥ 75 %) que uno ya elegido: 26 «se aprueba la recalificación de X» no llenan
   los puntos clave.
9. Decisiones y tareas se deduplican entre bloques (≥ 78 % de palabras en orden; las tareas también si comparten la mitad
   de las raíces). Después `verify`, una vez por candidata (se cachea: los tres niveles muestran las mismas):
   - fuera sin LLM: cita condicional («deberíamos», «se podría»…), tarea = responsable, y lectura de la pantalla (los pares
     de palabras de la transcripción a ±45 s están ≥ 25 % en el texto de la pantalla visible entonces: leer el acta
     anterior da 0,3-0,6, hablar sobre una diapositiva ≤ 0,15);
   - el resto, una llamada corta (cita + transcripción a ±45 s, gramática con un solo enum) que la clasifica con una
     rúbrica: acuerdo, encargo, hecho, lectura, demostración, consejo, propuesta, cortesía o trámite. Solo quedan acuerdo y
     encargo (un modelo pequeño dice «sí» a todo; eligiendo categoría acierta mucho más). La rúbrica dice expresamente que
     aprobar hoy el acta anterior, aplazar un punto o suspender la sesión son acuerdos y que lo que manda hacer una
     resolución votada hoy («disponer que la Secretaría notifique…») es encargo, no hecho; en el extracto van marcadas las
     líneas «(lectura en voz alta)». Una decisión leída de la pantalla se reancla a la última aprobación con sus palabras
     en los 5 min siguientes (la primera suele ser el anuncio «se les preguntará si aprueban…»);
   - responsable y plazo solo si los dice la transcripción de alrededor; si no, «—».
10. Reduce jerárquico (nunca se pasa de contexto ni recorta): en normal/detallado una sección por bloque del map, con su
   `tema` de título y sus puntos elegidos de viñetas; el LLM solo redacta el resumen de la sección a partir de esas viñetas.
   El título y el resumen global salen de los resúmenes de sección (breve: de los temas de cada bloque + los puntos
   elegidos, para que recorra toda la reunión); sin decisiones ni
   tareas, el prompt prohíbe «se acordó / queda pendiente». En breve/normal las decisiones repetitivas (esqueleto ≥ 75 %) se agrupan («… y 14
   más parecidas») y, si aún hay más que el tope, el LLM elige las clave por número (breve 5/5, normal 12/10). Largo pedido
   en caracteres, tope duro un 50 % mayor y recorte en la última frase completa: nunca a mitad de palabra.
11. Render: breve = resumen + 10 puntos clave con marca + decisiones/tareas clave + 3 capturas; normal = secciones con sus
    viñetas y las capturas más relevantes (máx. 10); detallado = todos los puntos y todas las capturas. Dos niveles: las capturas
    clave van en línea (en breve/normal no se repiten casi iguales, ≥ 50 % de palabras a menos de 3 min) y TODAS las demás en
    una tira de miniaturas por tramo (`img/t_*.jpg`, carga diferida; clic = ampliar). El
    vídeo se enlaza (o se copia una sola vez por vídeo en `work/<hash>/`; una subida en un temporal nunca con enlace
    simbólico, que moría al reiniciar). Junto a `index.html` va `acta.json` (lo mismo, para `eval/score.py`).
    Orden de la página: resumen, **Desarrollo de la reunión** (relato digerido: el map genera en la misma llamada 2 párrafos
    por bloque, en lenguaje llano y con `[mm:ss]`; se recortan a 1/2/2 frases por nivel, y cada párrafo lleva la captura más
    relevante de su tramo, máx. 6/12/20), decisiones, tareas y el detalle literal. Decisiones y Tareas sin elementos no salen.
    En vídeos de pantalla (≥ 20 pantallas distintas) la parte literal muestra todas, sin tope (lazy-load).
12. `app.py` es solo la GUI: llama a `pipeline.run` y muestra el `index.html` en un iframe + zip de descarga.

## Windows (ProBook)

- Enchufado y con el plan de energía «Alto rendimiento»: en batería el i5-1135G7 baja a 15 W y la generación cae.
- Que ni python ni llama-server estén en «modo eficiencia» (Administrador de tareas): lanzar la GUI desde una ventana en
  primer plano.
- Exclusión de Defender para `bin\`, `models\` y `work\` (si no, escanea el modelo de 2,4 GB en cada arranque).

## Preguntas sobre una reunión (pestaña «Preguntar», `rag.py`)

```sh
uv run rag.py work/<hash> "¿Cuánto cuesta el plan?"   # o el vídeo; ACTAS_LLM_URL reutiliza un llama-server ya arrancado
uv run rag.py --selftest                              # verificación: rosa/femenino, 1843/antigua, cifras, negación
uv run eval/rag_score.py                              # eval/rag_preguntas.json (62 preguntas, 6 reuniones)
```

Responde solo con lo dicho, en estilo indirecto («Se dijo que…»), cada frase con su `[mm:ss]` (salta al vídeo) y la cita
literal desplegable con los tramos vecinos; si no se dijo: «No se menciona en la reunión». Cada pregunta es una llamada
independiente: sin historial, sin caché de respuestas y con `cache_prompt: false` (lo anterior en pantalla es solo visual).

1. Índice (en la primera pregunta, ~4 s; caché `work/<hash>/rag_<asr>_<h>.npy`): tramos de voz de 15 s (`merge_segs`) y el
   texto de las pantallas compartidas (sin URLs, trozos de 60 palabras). BM25 propio (raíces pobres sin tildes, sin
   stopwords) + `google/embeddinggemma-300m` int8 en ONNX (295 MB, se baja solo a `models/gemma-emb/`; usa su `sentence_embedding`
   y los prompts oficiales de consulta/documento; onnxruntime y tokenizers ya venían con faster-whisper/RapidOCR: cero
   dependencias nuevas), fusionados por RRF (k = 60) → 8 tramos, como mucho 2 de pantalla. Las valoraciones amplían la
   búsqueda con el dato del que saldrían (`EXPAND`: «¿es caro?» → precio). Frente a multilingual-e5-small: paráfrasis 77 → 85 %,
   mismo recall@8 (94 %) pero indexa ~8× más lento (36 s frente a 4 s en la reunión de 2 h 22) y 1,6 GB de RAM pico frente
   a 0,6. Qwen3-Embedding-0.6B (int8, 613 MB) quedó peor: recall@8 88 %, índice 96 s, 1,9 GB.
2. Umbral de coseno (`MIN_COS` = 0,35): por debajo, «No se menciona» sin LLM. Con Gemma las preguntas sin respuesta
   (0,27-0,54) se separan bastante mejor de las respondibles (≥ 0,36), pero se solapan: el umbral solo corta las más ajenas
   y el «No se menciona» real lo decide el LLM (NINGUNO).
3. LLM: el mismo Qwen3.5-4B en un llama-server propio (ctx 4096, sin thinking) que arranca con la primera pregunta y se
   para al generar un acta (dos modelos de 3 GB no caben en 8 GB). Prompt: instrucciones fijas → tramos numerados en orden
   cronológico → pregunta. Gramática GBNF por pregunta: `NINGUNO` o hasta 2 líneas `[id] Se dijo que …` con `id` ∈ tramos
   recuperados.
4. Verificación en código (`verify`): cada palabra de contenido de la frase (raíz sin tildes; fuera stopwords y palabras de
   ≤ 2 letras) tiene que estar en el tramo citado o en sus vecinos ±1; las cifras exactas (también dichas en letra:
   «cinco» = 5), y una cifra que en el original va negada («ya no vale 25 sino 30») no puede salir sin negar. Si falla y la
   frase sale entera de otro tramo recuperado, se le atribuye a ese (el LLM a veces se equivoca de número); si no, se
   descarta y se muestra la cita literal del tramo. Sobre texto de pantalla: «En pantalla se mostró que…».

**Chat interpretativo (gemma-4-E4B, por defecto si está `models/gemma-4-E4B-it-Q4_0.gguf`; `ACTAS_CHAT=qwen` = estilo literal con el 4B):**
síntesis citada con `[mm:ss]` (puede juntar varios tramos), «Se deduce que X, porque se dijo que Y» en cursiva (la base Y se verifica
como cualquier «Se dijo» y solo cita tramos de las líneas «Se dijo» de la misma respuesta; si no, se descarta), preguntas generales
(«¿de qué va la reunión?») resueltas con el acta breve y de propósito («¿para qué sirve X?») con deducción marcada. Medido en
`eval/ronda3.md` §7 (GPU): ausentes y trampas 100 %, general 17 → 67 %, propósito 40 → 100 %, latencia ×1,5-2,5.

Limitaciones: la verificación es por palabras, no por sentido: una frase que reordena palabras del mismo tramo (o quita
una negación que no va pegada a una cifra) pasa; por eso la cita literal va siempre al lado. Se cita el ASR tal cual
(con sus errores). Preguntas de síntesis («¿cuántas votaciones hubo?») no encajan: responde con tramos sueltos.

Medido (47 preguntas, 4 reuniones, emulando ProBook: `taskset -c 0-3,6-9`, llama `-t 4`): recall@8 94 %, ausentes 100 %,
trampas 91 %, paráfrasis 77 %, factuales 88 %; latencia por pregunta p50 21,8 s / p90 25,8 s (prefill ~18 s de ~790 tokens + gen ~3,5 s).

LLM más fuerte para RAG (probado, no adoptado; 38 preguntas con gold, todos los hilos): 4B Q4_0 (actual) factual 95 / paráfrasis 93 /
trampas 91 / ausentes 100 %, descartes 18 %, p50 19,6 s; 4B Q8_0 (4,5 GB) 95 / 86 / 91 / 100 %, descartes 14 %, p50 22,5 s;
9B Q4_0 (5,1 GB) 89 / 93 / 100 / 86 %, descartes 6 %, p50 29,2 s (≈ 2× en el ProBook). Mismo nº de aciertos con más latencia y RAM: se queda el 4B Q4_0.

## Instalador de Windows

Descarga `Actas-setup.exe` de la sección Releases y ejecútalo (no pide administrador; se instala en `%LOCALAPPDATA%\Programs\Actas`). Necesita internet durante la instalación (Python y librerías) y en el primer arranque (unos 3,3 GB de modelos, con pantalla de progreso; si se corta, se reanuda al volver a abrir).

El instalador no está firmado: Windows SmartScreen mostrará «Windows protegió su PC». Pulsa **Más información → Ejecutar de todos modos**. La primera vez, Windows Defender analiza los ficheros nuevos y el arranque y el primer acta pueden tardar más; es normal. No se añaden exclusiones a Defender.

Para construirlo: `python tools/fetch_bins.py --uv` y `iscc installer\actas.iss` (Inno Setup 6). `tools/fetch_bins.py` también deja `bin/` listo (ffmpeg + llama.cpp) en Linux/macOS. Licencia de ffmpeg (GPL, build de gyan.dev): se incluye `LICENSE` en `bin\ffmpeg`; fuentes en https://ffmpeg.org y https://www.gyan.dev/ffmpeg/builds/.

## macOS (Apple Silicon e Intel)

Descarga `Actas-arm64.dmg` (Apple Silicon: M1 o posterior) o `Actas-x64.dmg` (Intel) de Releases, ábrelo y arrastra **Actas** a Aplicaciones. Necesita macOS 14 o posterior.

La app no está firmada ni notarizada (solo firma ad hoc), así que la primera vez macOS la bloqueará: **clic derecho en Actas → Abrir → Abrir**, o bien Ajustes del Sistema → Privacidad y seguridad → **Abrir igualmente**. Si aun así no abre: `xattr -dr com.apple.quarantine /Applications/Actas.app`.

El primer arranque prepara el entorno en `~/Library/Application Support/Actas` (necesita internet; unos minutos, avisa con una notificación y, si falla, con un diálogo; detalles en `instalacion.log`) y luego baja los modelos (~3,3 GB) con la pantalla de progreso de siempre. Reuniones y modelos quedan también ahí; para desinstalar, borra la app y esa carpeta.

Aceleración: el LLM usa Metal en Apple Silicon (`ACTAS_CPU=1` lo desactiva); el vídeo condensado se codifica con VideoToolbox. El ASR (faster-whisper) y todo en Intel van por CPU. En Intel, `onnxruntime` queda fijado a 1.23.2 (última con ruedas para macOS Intel; ver `pyproject.toml`).

Construir (en un Mac): `python3 tools/fetch_bins.py --uv && installer/macos/build.sh arm64|x64 <versión>`. ffmpeg/ffprobe: builds estáticos GPL de https://ffmpeg.martin-riedl.de (fuentes enlazadas allí).
