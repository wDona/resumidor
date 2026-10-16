"""Vídeo de reunión -> acta HTML (resumen + capturas + marcas de tiempo). Todo local, CPU."""
import contextlib, hashlib, html, json, os, re, shutil, socket, subprocess, sys, time, unicodedata, urllib.request, zipfile
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "work"
STEP = 3                      # s entre muestras de vídeo
THUMB_W, THUMB_H = 128, 72    # miniatura en gris para detectar cambios
CROP = 0.05                   # franjas de arriba/abajo ignoradas (barra de menús con reloj/batería, dock)
BLOCK = 8                     # lado del bloque (px de miniatura) para comparar por zonas
CUT = 0.05                    # fracción de bloques cambiados que cuenta como "cambio de pantalla"
NOISY = 0.4                   # bloque que cambia en >= 40 % de las muestras vecinas (webcam superpuesta): se ignora
DUP = 0.75                    # palabras OCR compartidas / palabras de la pantalla más corta para darla por repetida
OCR_REC = ("latin_PP-OCRv5_rec_mobile.onnx",  # reconocedor latino (tildes, ñ, espacios); 7,5 MB, se baja solo
           "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv5/rec/latin_PP-OCRv5_rec_mobile.onnx",
           "b20bd37c168a570f583afbc8cd7925603890efbcdc000a59e22c269d160b5f5a")
MIN_CHARS = 30                # letras OCR (sin interfaz ni nombres, ver screens) para considerar un frame "pantalla compartida"
CHUNK_CHARS = 10000           # ~3k tokens de transcripción por bloque del map
ASR_WIN = 900                 # s de audio por ventana del ASR: la RAM no crece con la duración de la reunión
ASR_MODELS = {"rápido": "small", "calidad": "large-v3-turbo"}
LLM = ("Qwen3.5-4B-Q4_0.gguf", "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_0.gguf")
# ponytail: núcleos físicos = lógicos / 2 (SMT de 2 hilos, p. ej. i5-1135G7 4C/8T); con más hilos que núcleos llama.cpp
# genera a menos de la mitad de velocidad. Sin SMT se queda con la mitad: --threads / ACTAS_THREADS lo corrigen
PHYS = max(1, (os.cpu_count() or 2) // 2)
# keep = fracción de puntos (ranking global por importancia) que entra en el acta; pts = máx. de puntos a la vista (breve:
# "puntos clave"); shots = máx. de capturas; dec/tar = máx. de decisiones/tareas (las elige el LLM); None = todas.
# secs = una sección por bloque del map con su resumen.
# tldr/sec = largo pedido del resumen global/de sección, con su tope duro en caracteres (un modelo pequeño a veces entra en
# bucle y agotaría max_tokens con el JSON a medias)
LEVELS = {
    "breve": dict(keep=0.2, pts=8, shots=3, dec=5, tar=5, secs=False, tldr=("2-3 frases", 600), sec=None),
    "normal": dict(keep=0.5, pts=None, shots=10, dec=12, tar=10, secs=True, tldr=("4-6 frases", 1000),
                   sec=("2-3 frases", 500)),
    "detallado": dict(keep=1.0, pts=None, shots=None, dec=None, tar=None, secs=True,
                      tldr=("un párrafo de 6-10 frases", 1600), sec=("3-5 frases", 800)),
}
SHOT_WIN = (-10, 90)          # s alrededor de una captura donde los puntos elegidos la hacen "relevante"
LANG = {"es": "español", "en": "inglés (English)"}


def fmt(t):
    t = int(t)
    return f"{t // 60:02d}:{t % 60:02d}"


def parse_ts(s):
    m = re.match(r"\s*(\d+):(\d\d)(?::(\d\d))?", s or "")
    if not m:
        return 0
    a, b, c = m.groups()
    return int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b)


def video_id(path):
    # ponytail: hash de tamaño + primeros/últimos 4 MB, no del fichero entero (GBs); hash completo si hay colisiones
    n = os.path.getsize(path)
    h = hashlib.sha1(str(n).encode())
    with open(path, "rb") as f:
        h.update(f.read(4 << 20))
        f.seek(max(0, n - (4 << 20)))
        h.update(f.read())
    return h.hexdigest()[:16]


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


# ---------- ASR ----------
def windowed(transcribe_win, dur, win, pad=30):
    """Transcribe por ventanas para que la RAM no crezca con la duración. transcribe_win(inicio, largo) da segmentos
    (s, e, texto) relativos a la ventana. Cada ventana lleva `pad` s de más: el segmento que empieza después de `win`
    se descarta y la ventana siguiente arranca en él, así ninguna frase queda cortada por el borde."""
    out, start = [], 0.0
    while True:
        final = start + win + pad >= dur
        nxt = start + win
        for s, e, txt in transcribe_win(start, win + pad):
            if not final and s >= win:
                nxt = start + s
                break
            out.append((start + s, start + e, txt))
            nxt = max(nxt, start + e)
        if final:
            return out
        start = nxt


def transcribe(video, quality, threads, dur, cb):
    from faster_whisper import WhisperModel
    name = ASR_MODELS[quality]
    cb(0, f"Cargando modelo de voz ({name})…")
    model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=threads)
    lang = [None]  # se detecta en la primera ventana y se fija para las demás

    def win(start, length):
        # audio vía ffmpeg (PyAV 19 rompe el decode_audio de faster-whisper 1.2.1) y solo esta ventana en RAM:
        # faster-whisper hace la STFT de todo lo que recibe de una vez; con la reunión entera eran 7 GB en 2 h 20
        pcm = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{start:.2f}", "-t", str(length), "-i", str(video), "-vn",
                              "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True, check=True).stdout
        segs, info = model.transcribe(np.frombuffer(pcm, np.float32), language=lang[0], vad_filter=True,
                                      beam_size=1 if name == "small" else 5, condition_on_previous_text=False)
        lang[0] = lang[0] or info.language
        for s in segs:
            cb(min((start + s.end) / dur, 1), f"Transcribiendo… {fmt(start + s.end)} / {fmt(dur)}")
            yield s.start, s.end, s.text.strip()
    segs = windowed(win, dur, ASR_WIN)
    return {"language": lang[0], "segments": [{"s": round(s, 1), "e": round(e, 1), "text": t} for s, e, t in segs if t]}


# ---------- Vídeo: cambios de pantalla ----------
def sample_thumbs(video, threads, dur, cb):
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-threads", str(threads), "-i", str(video), "-an", "-vf",
                          f"fps=1/{STEP},scale={THUMB_W}:{THUMB_H}:flags=area,format=gray", "-f", "rawvideo", "-"],
                         stdout=subprocess.PIPE)
    frames, size = [], THUMB_W * THUMB_H
    while buf := p.stdout.read(size):
        if len(buf) < size:
            break
        frames.append(np.frombuffer(buf, np.uint8))
        cb(min(len(frames) * STEP / dur, 1), f"Analizando vídeo… {fmt(len(frames) * STEP)}")
    if p.wait():
        raise RuntimeError("ffmpeg falló al leer el vídeo")
    return np.array(frames, np.int16)


def stable_segments(thumbs, cut=CUT, min_len=2, win=5):
    """[(inicio, fin)] en índices de muestra: tramos estables (>= min_len muestras) sin repetir pantallas ya vistas.
    Se compara con el inicio del tramo (no con el frame anterior) para que un cambio gradual también corte.
    Por bloques y sin las franjas CROP; los bloques que cambian casi siempre en ±win muestras (webcam superpuesta
    o vídeo incrustado) no cuentan, así que solo corta un cambio que cubra > cut del área útil."""
    # dHash probado y descartado: en imágenes planas (diapositiva blanca vs. mosaico oscuro) apenas cambia.
    c = round(THUMB_H * CROP)
    t = thumbs.reshape(len(thumbs), THUMB_H, THUMB_W)[:, c:c + (THUMB_H - 2 * c) // BLOCK * BLOCK].astype(np.int16)
    n, h, w = t.shape
    blk = lambda i, j: (np.abs(t[i] - t[j]) > 32).reshape(h // BLOCK, BLOCK, w // BLOCK, BLOCK).mean((1, 3)) > 0.125
    cs = np.cumsum([np.zeros((h // BLOCK, w // BLOCK))] + [blk(i, i + 1) for i in range(n - 1)], 0)
    lo, hi = np.maximum(np.arange(n) - win, 0), np.minimum(np.arange(n) + win, n - 1)
    noisy = (cs[hi] - cs[lo]) / np.maximum(hi - lo, 1)[:, None, None] >= NOISY
    noisy &= noisy.mean((1, 2), keepdims=True) < 0.25  # solo zonas pequeñas; si cambia media pantalla es contenido
    diff = lambda i, j: (blk(i, j) & ~(noisy[i] | noisy[j])).mean()
    segs, start = [], 0
    for i in range(1, n + 1):
        if i == n or diff(i, start) > cut:
            if i - start >= min_len and all(diff(i - 1, e) > cut for _, e in segs):
                segs.append((start, i - 1))
            start = i
    return segs


def ocr_rec_model():
    """Ruta del reconocedor latino; lo baja la primera vez. None (modelo chino/inglés de serie) si no hay red."""
    name, url, sha = OCR_REC
    p = ROOT / "models" / name
    if not p.exists():
        try:
            data = urllib.request.urlopen(url, timeout=60).read()
            if hashlib.sha256(data).hexdigest() != sha:
                return None
            p.parent.mkdir(exist_ok=True)
            p.with_suffix(".part").write_bytes(data)
            p.with_suffix(".part").rename(p)
        except OSError:
            return None
    return p


def clean_ocr(t):
    """Quita CJK/ancho completo (basura del modelo chino) y deja la línea solo si le quedan >= 2 letras/cifras."""
    t = re.sub(r"[\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]", "", t).strip()
    return t if sum(c.isalnum() for c in t) >= 2 else ""


def words(t):
    t = unicodedata.normalize("NFKD", t.lower())
    return re.findall(r"[a-z0-9]+", "".join(c for c in t if not unicodedata.combining(c)))


def screens(kfs):
    """Marca qué frames son pantalla compartida (k["screen"]), deja en k["text"] solo su contenido y deduplica.
    Antes de contar letras y comparar se quita la interfaz de la videollamada: líneas cuyas dos primeras palabras salen
    en >= 30 % de los frames (barra de marcadores, "X está presentando", nombres de la columna de caras aunque el OCR los
    corte distinto, paneles de la aplicación). Solo cuentan las líneas con >= 2 palabras y alguna en minúscula de >= 3
    letras: los nombres bajo las caras de Meet/Zoom/Teams y los botones no, así que una cuadrícula de caras no es pantalla.
    Repetidas (mismo texto, o una contiene a la otra: viñetas que van apareciendo, volver a una pantalla ya vista):
    queda la más completa; hereda la marca de la primera aparición solo si su texto es casi igual (>= 90 %)."""
    key = lambda line: " ".join(words(line)[:2])
    lines = [[x for x in k["text"].split(" | ") if key(x)] for k in kfs]
    freq = Counter(n for ls in lines for n in {key(x) for x in ls})
    ui = {n for n, c in freq.items() if c >= max(5, 0.3 * len(kfs))}
    kept = []  # [(palabras, keyframe)]
    for k, ls in zip(kfs, lines):
        body = [x for x in ls if key(x) not in ui]
        prose = [x for x in body if " " in x.strip() and re.search(r"(?<!\w)[a-záéíóúüñ]{3,}", x)]
        k.update(text=" | ".join(body), title=next((x for x in prose if len(x.split()) >= 3), "")[:90],
                 screen=sum(c.isalnum() for x in prose for c in x) >= MIN_CHARS)
        if not k["screen"]:
            continue
        w = words(k["text"])
        for n, (ow, o) in enumerate(kept):
            sm = SequenceMatcher(None, ow, w, autojunk=False)
            m = sum(b.size for b in sm.get_matching_blocks())
            if m >= DUP * min(len(ow), len(w)):
                keep, drop = (k, o) if len(w) > len(ow) else (o, k)
                if m >= 0.9 * max(len(ow), len(w)):
                    keep["t"] = min(k["t"], o["t"])
                drop["screen"] = False
                kept[n] = (max(w, ow, key=len), keep)
                break
        else:
            kept.append((w, k))
    return kfs


def keyframes(video, wd, threads, dur, cb):
    import cv2
    from rapidocr_onnxruntime import RapidOCR
    segs = stable_segments(sample_thumbs(video, threads, dur, lambda f, m: cb(f * 0.5, m)))
    (wd / "frames").mkdir(exist_ok=True)
    rec = ocr_rec_model()
    ocr = RapidOCR(intra_op_num_threads=threads, inter_op_num_threads=1, **({"rec_model_path": str(rec)} if rec else {}))
    out = []
    for n, (a, b) in enumerate(segs):
        cb(0.5 + 0.5 * n / len(segs), f"Leyendo texto de capturas… {n + 1}/{len(segs)}")
        img = wd / "frames" / f"k{b * STEP:06d}.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(b * STEP), "-i", str(video), "-frames:v", "1",
                        "-vf", "scale='min(1280,iw)':-2", "-q:v", "3", str(img)], check=True)
        im = cv2.imread(str(img))
        c = round(len(im) * CROP)  # sin barra de menús/dock: el reloj no ensucia el texto ni la deduplicación
        res, _ = ocr(im[c:len(im) - c])
        lines = [x for _, t, sc in (res or []) if float(sc) > 0.6 and (x := clean_ocr(t))]
        out.append({"t": a * STEP, "img": img.name, "text": " | ".join(lines)})
    return out  # crudo; screens() clasifica y deduplica al cargar (barato, y así se puede ajustar sin repetir el OCR)


# ---------- LLM (llama-server) ----------
def llm_model():
    p = ROOT / "models" / LLM[0]
    return p if p.exists() else next(iter(sorted(ROOT.glob("models/*.gguf"))), None)


@contextlib.contextmanager
def llama(threads, ctx=8192):
    exe = next((p for p in ROOT.glob("bin/**/llama-server*") if p.is_file()), None)
    model = llm_model()
    if not exe or not model:
        raise RuntimeError("Falta bin/**/llama-server o models/*.gguf (ver README)")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    log = open(WORK / "llama-server.log", "w")
    proc = subprocess.Popen([str(exe), "-m", str(model), "-c", str(ctx), "-t", str(threads), "-np", "1",
                             # sin caché de prompts en RAM (8 GB por defecto) ni checkpoints (32 copias del estado en modelos híbridos:
                             # +3 GB y aquí nunca se reutiliza el prompt), sin "thinking" y sin mmap: con mmap los pesos
                             # reempaquetados para AVX quedan duplicados (≈4,9 GB de RSS en vez de 3,2 GB con Qwen3.5-4B)
                             "-cram", "0", "-ctxcp", "0", "-rea", "off", "-lm", "none",
                             "--host", "127.0.0.1", "--port", str(port)], stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(600):
            if proc.poll() is not None:
                raise RuntimeError(f"llama-server terminó (ver {log.name})")
            try:
                if urllib.request.urlopen(url + "/health", timeout=2).status == 200:
                    break
            except OSError:
                time.sleep(0.5)

        def chat(system, user, schema, max_tokens, repeat_penalty=1.0):
            body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "temperature": 0.2, "max_tokens": max_tokens, "grammar": gbnf(schema),
                    "repeat_penalty": repeat_penalty}
            req = urllib.request.Request(url + "/v1/chat/completions", json.dumps(body).encode(),
                                         {"Content-Type": "application/json"})
            r = json.load(urllib.request.urlopen(req, timeout=7200))
            u, tm = r.get("usage", {}), r.get("timings", {})
            print(f"  llm {u.get('prompt_tokens')}→{u.get('completion_tokens')} tok, "
                  f"{(tm.get('prompt_ms', 0) + tm.get('predicted_ms', 0)) / 1000:.0f} s", flush=True)
            return json.loads(r["choices"][0]["message"]["content"])
        yield chat
    finally:
        proc.terminate()
        proc.wait(10)
        log.close()


def obj(**props):
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


STR = {"type": "string"}
S = lambda n: {"type": "string", "maxLength": n}  # tope duro: una cadena desbocada no agota max_tokens ni corta el JSON
TS = {"type": "string", "pattern": "^[0-9]{1,3}:[0-5][0-9]$"}
arr = lambda item, n: {"type": "array", "items": item, "maxItems": n}
# la cita va antes que el texto: el modelo primero copia la frase que lo prueba y luego redacta a partir de ella
TASK = obj(cita=S(100), tarea=S(160), responsable=S(60), plazo=S(60), t=TS)
MAP_SCHEMA = obj(tema=S(100), puntos=arr(obj(texto=S(160), importancia={"enum": [1, 2, 3, 4, 5]}, t=TS), 10),
                 decisiones=arr(obj(cita=S(100), texto=S(160), t=TS), 5), tareas=arr(TASK, 5))
MAP_MAX = 1600  # peor caso con todos los topes llenos (≈ 1500 tokens); lo normal son 500-900


def gbnf(schema):
    """Esquema (solo obj/arr/STR/S/TS/enum de aquí) -> gramática GBNF compacta: sin saltos de línea ni sangría (menos
    tokens; con json_schema Gemma se quedaba generando espacios hasta max_tokens) y con maxItems/maxLength como límite duro."""
    rules = {"sp": '" "?', "ts": r'"\"" [0-9] [0-9]? [0-9]? ":" [0-5] [0-9] "\""',
             "ch": r'[^"\\\x7F\x00-\x1F] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F]{4})', "str": r'"\"" ch* "\""'}
    lit = lambda v: json.dumps(json.dumps(v) if not isinstance(v, str) else v)

    def g(s):
        if "enum" in s:
            return "(" + " | ".join(lit(v) for v in s["enum"]) + ")"
        if s.get("type") == "array":
            if not s["maxItems"]:
                return '"[" sp "]"'
            it = g(s["items"])
            return f'"[" sp ({it} ("," sp {it}){{0,{s["maxItems"] - 1}}})? sp "]"'
        if s.get("type") == "object":
            body = ' "," sp '.join(f'{lit(json.dumps(k) + ":")} sp {g(v)}' for k, v in s["properties"].items())
            name = f"o{len(rules)}"
            rules[name] = f'"{{" sp {body} sp "}}"'
            return name
        if "maxLength" in s:
            rules[f"s{s['maxLength']}"] = f'"\\"" ch{{0,{s["maxLength"]}}} "\\""'
            return f"s{s['maxLength']}"
        return "ts" if "pattern" in s else "str"
    rules["root"] = g(schema)
    return "\n".join(f"{k} ::= {v}" for k, v in rules.items())

# Salida corta a propósito: generar es lo caro en CPU (~12 tok/s); 10 puntos de <= 20 palabras ≈ 400 tokens por bloque.
# Leer tampoco es gratis (~45 tok/s): el prompt de sistema se procesa en cada bloque, así que va escueto.
MAP_PROMPT = """Redactas actas de reuniones. Recibes un fragmento de transcripción automática (con errores) con marcas [mm:ss] \
y, a veces, texto de la pantalla compartida.
tema: título breve del fragmento.
puntos: hasta 10 ideas, de mayor a menor importancia; cada una, una frase autocontenida de máx. 20 palabras, sin repetir \
ideas; t = marca donde empieza.
importancia: 5 = decisión, compromiso o cifra clave; 4 = información nueva relevante (también preguntas del público y \
sus respuestas); 3 = contexto útil; 2 = detalle o ejemplo; 1 = saludos, presentaciones, agradecimientos, despedidas y \
logística, siempre. Como mucho un 5 y dos 4 por cada cinco puntos; la mayoría 2-3.
Fidelidad: atribuye opiniones y propuestas a quien las dice («X opina que…», «Y propone…»), no las des como hechos; \
no mezcles cifras ni nombres de partes distintas; votos, abstenciones y números solo si se dicen; lo leído de un acta \
anterior se cuenta como lectura («el acta anterior recoge…»), no como acuerdo de hoy.
decisiones: solo acuerdos tomados en esta reunión («se aprueba…», «acordamos…», votación con resultado). NO son \
decisiones: lo que se lee en voz alta de un acta anterior (aunque diga «Acuerdos»), los pasos de una demostración o \
ejemplo («ahora creo un webinar…»), opiniones, observaciones ni propuestas sin aprobar.
tareas: solo encargos o compromisos explícitos de alguien para después de la reunión (quién hará qué); no lo son \
consejos o recomendaciones generales, pasos de una demostración ni ofrecimientos de cortesía («podéis contactarme»). Sin repetir: una acción que se repite (p. ej. notificar cada resolución) \
es una sola tarea. responsable y plazo "—" si no se dicen.
cita: copia literal de la transcripción (máx. 12 palabras) que prueba la decisión o tarea; si no la hay, no la incluyas.
Listas vacías si no hay. Solo lo que dice el texto; no inventes. Escribe en {lang}."""

FAITHFUL = "Usa solo lo recibido: no añadas hechos, cifras, votos ni abstenciones. Atribuye las opiniones a quien las dice."
SEC_PROMPT = """Redactas una sección del acta de una reunión. Recibes sus puntos clave con marcas [mm:ss].
resumen: {n} que los sinteticen. {faithful} Escribe en {lang}."""
VALID_PROMPT = """Revisas el borrador de un acta. Recibes los temas de la reunión en orden y las decisiones y tareas \
numeradas que propuso un primer borrador, que solo veía un fragmento cada vez.
decisiones: números de las que de verdad se acordaron en esta reunión. tareas: números de los encargos reales a alguien \
para después de la reunión. No lo son: consejos o contenido de una charla o curso, pasos de una demostración, lo leído de \
un acta anterior, opiniones ni ofrecimientos de cortesía. Si ninguna lo es, lista vacía."""
FINAL_PROMPT = """Redactas el acta de una reunión. Recibes, en orden cronológico, {src} con marcas [mm:ss], y las \
decisiones y tareas numeradas.
{pick}resumen: resumen general de {tldr}: de qué trata, qué se decidió y qué queda pendiente. Las decisiones parecidas, juntas \
en una frase y sin inventar cuántas. Nada de saludos, agradecimientos ni despedidas.
{faithful} Escribe en {lang}."""


def chunk(segments):
    """Bloques de ~CHUNK_CHARS; un resto pequeño (< 40 %) se une al anterior: un bloque de cola diminuto solo trae la
    despedida, y la rúbrica le obligaría a dar notas altas."""
    size = lambda c: sum(len(x["text"]) + 9 for x in c)
    out, cur = [], []
    for s in segments:
        cur.append(s)
        if size(cur) > CHUNK_CHARS:
            out.append(cur)
            cur = []
    if cur and out and size(cur) < 0.4 * CHUNK_CHARS:
        out[-1] += cur
    elif cur:
        out.append(cur)
    return out


def merge_segs(segs, span=15):
    """Funde segmentos seguidos hasta `span` s: menos marcas [mm:ss] = menos tokens de entrada (hay reuniones con miles de
    segmentos de 2-3 palabras)."""
    out = []
    for s in segs:
        if out and s["s"] - out[-1]["s"] < span:
            out[-1] = {**out[-1], "e": s["e"], "text": out[-1]["text"] + " " + s["text"]}
        else:
            out.append(s)
    return out


def map_input(segs, kfs):
    t0, t1 = segs[0]["s"], segs[-1]["e"]
    text = "\n".join(f"[{fmt(s['s'])}] {s['text']}" for s in merge_segs(segs))
    screens = [f"[{fmt(k['t'])}] {k['text'][:600]}" for k in kfs if k["screen"] and t0 <= k["t"] <= t1]
    if screens:
        text += "\n\nTexto en pantalla compartida:\n" + "\n".join(screens)[:2500]
    return text


def find_quote(quote, segs, sw=None):
    """(fracción de pares de palabras de la cita que están en la transcripción, inicio del segmento donde empieza).
    Comprobación barata de que la decisión/tarea sale del fragmento; de paso da su marca exacta."""
    q = words(quote)
    qb = set(zip(q, q[1:]))
    sw = sw or [words(s["text"]) for s in segs]
    best = (0, segs[0]["s"])
    for i in range(len(segs) if qb else 0):
        w = sw[i] + [x for s in sw[i + 1:i + 8] for x in s][:len(q)]  # la cita puede cruzar segmentos cortos
        f = len(qb & set(zip(w, w[1:]))) / len(qb)
        if f and f >= best[0]:  # >=: la última ventana que la contiene entera empieza en su segmento
            best = (f, segs[i]["s"])
    return best


def map_chunk(chat, segs, text, lang, kfs=()):
    """Map de un bloque. Decisiones/tareas sin su cita en la transcripción se descartan (inventadas), y también las que
    se leen de un documento en pantalla (acta anterior compartida y leída en voz alta: no son acuerdos de hoy)."""
    m = chat(MAP_PROMPT.format(lang=lang), text, MAP_SCHEMA, MAP_MAX)
    t0, t1 = segs[0]["s"], segs[-1]["e"]
    shown = [{"s": k["t"], "text": k["text"]} for k in kfs if t0 - 60 <= k["t"] <= t1 and k["text"]]
    for p in m["puntos"]:
        if not t0 - 5 <= parse_ts(p["t"]) <= t1 + 5:  # marca inventada fuera del bloque: al inicio del bloque
            p["t"] = fmt(t0)
    seen = set()  # el modelo a veces repite el mismo punto tal cual
    m["puntos"] = [p for p in m["puntos"] if not (k := " ".join(words(p["texto"]))) in seen and not seen.add(k)]
    sw = [words(s["text"]) for s in segs]
    for k in ("decisiones", "tareas"):
        keep = []
        for it in m[k]:
            f, t = find_quote(it["cita"], segs, sw)
            why = ("cita no está en el bloque" if f < 0.5 else
                   "leída de la pantalla" if shown and find_quote(it["cita"], shown)[0] >= 0.25 else "")
            if why:
                print(f"  descartada ({why}): {it.get('texto') or it['tarea']}", flush=True)
            else:  # marca = la de la cita, salvo que otra del bloque ya la use (citas iguales: "se aprueba el informe")
                own = parse_ts(it["t"])
                used = any(parse_ts(x["t"]) == t for x in keep)
                keep.append({**it, "t": fmt(own if used and t0 - 5 <= own <= t1 + 5 else t)})
        m[k] = keep
    return m


def select_points(maps, keep, cap=None):
    """Puntos [(t, texto, nota, bloque)] que entran en el acta: ranking global (nota, orden en el bloque), se queda `keep`
    (y como mucho `cap`). Por presupuesto y no por umbral: aunque el modelo puntúe todo 4-5, cada nivel muestra un
    contenido distinto. Las notas 1 (saludos, despedidas, logística) no entran nunca."""
    allp = sorted(((-p["importancia"], n, parse_ts(p["t"]), p["texto"], b) for b, m in enumerate(maps)
                   for n, p in enumerate(m["puntos"]) if p["importancia"] > 1), key=lambda x: x[:2])
    k = min(max(1, round(keep * len(allp))), cap or len(allp)) if allp else 0
    return sorted((t, txt, -neg, b) for neg, _, t, txt, b in allp[:k])


def score_hist(maps):
    c = [sum(p["importancia"] == k for m in maps for p in m["puntos"]) for k in range(1, 6)]
    return "puntos por nota " + " ".join(f"{k}:{n}" for k, n in zip(range(1, 6), c)) + f" (total {sum(c)})"


def dedupe(items, key, loose=False):
    """Quita decisiones/tareas repetidas entre bloques: texto casi igual (>= 78 % de las palabras en orden). Con `loose`
    (tareas: la misma acción rutinaria redactada distinto en cada bloque, "notificar la resolución…") también si comparten
    >= la mitad de las raíces (5 letras) de las palabras largas. Las decisiones no: "se aprueba la recalificación de X"
    y "… de Y" solo se distinguen por el nombre. Se queda la primera."""
    stems = lambda x: {w[:5] for w in words(x) if len(w) >= 4}
    dup = lambda a, b: (SequenceMatcher(None, words(a), words(b), autojunk=False).ratio() >= 0.78 or
                        loose and len(stems(a) & stems(b)) >= 0.5 * max(1, min(len(stems(a)), len(stems(b)))))
    out = []
    for it in items:
        if not any(dup(it[key], o[key]) for o in out):
            out.append(it)
    return out


def validate(chat, maps, starts):
    """Decisiones y tareas deduplicadas que el LLM, ya con la reunión entera a la vista (temas en orden), da por buenas:
    el map, que ve un bloque, confunde consejos de una charla, pasos de una demo o cortesías con encargos. Una sola vez por
    map (caché), así todos los niveles muestran las mismas."""
    dec = dedupe([{**d, "b": b} for b, m in enumerate(maps) for d in m["decisiones"]], "texto")
    tar = dedupe([{**t, "b": b} for b, m in enumerate(maps) for t in m["tareas"]], "tarea", loose=True)
    if not dec and not tar:
        return {"decisiones": [], "tareas": []}
    text = "Temas:\n" + "\n".join(f"[{fmt(t)}] {m['tema']}" for t, m in zip(starts, maps))
    fields = {}
    for name, items, key in (("decisiones", dec, "texto"), ("tareas", tar, "tarea")):
        text += f"\n\n{name.capitalize()}:\n" + ("\n".join(f"{i}. [{x['t']}] {x[key]}" for i, x in enumerate(items, 1)) or "—")
        fields[name] = arr({"enum": list(range(1, len(items) + 1))}, len(items)) if items else arr(STR, 0)
    ok = chat(VALID_PROMPT, text, obj(**fields), 400)
    return {name: [items[i - 1] for i in sorted(set(ok[name]))] for name, items in (("decisiones", dec), ("tareas", tar))}


def reduce_maps(chat, maps, valid, starts, level, lang):
    """Reduce jerárquico, nunca se pasa de contexto ni recorta: (1) una sección por bloque del map (título = su tema,
    viñetas = sus puntos elegidos) y el LLM solo redacta su resumen a partir de esas viñetas; (2) el resumen global sale de
    los resúmenes de sección (breve: de los puntos elegidos) y, si hay más decisiones/tareas (ya validadas) que el tope
    del nivel, el LLM elige las más importantes."""
    cfg = LEVELS[level]
    dec, tar = valid["decisiones"], valid["tareas"]
    sel = select_points(maps, cfg["keep"])
    bullets = lambda pts: "\n".join(f"- [{fmt(t)}] {x}" for t, x, _, _ in pts)
    secs = []
    for b, m in enumerate(maps if cfg["secs"] else []):
        pts = [p for p in sel if p[3] == b]
        if pts:
            res = chat(SEC_PROMPT.format(n=cfg["sec"][0], faithful=FAITHFUL, lang=lang), bullets(pts),
                       obj(resumen=S(cfg["sec"][1])), 500, 1.1)["resumen"] if len(pts) > 1 else pts[0][1]
            secs.append({"titulo": m["tema"], "t": starts[b], "b": b, "resumen": res})
    if secs:
        src, text = "los resúmenes de cada parte", "\n\n".join(f"[{fmt(s['t'])}] {s['titulo']}: {s['resumen']}" for s in secs)
    else:
        src, text = "los puntos clave", bullets(sel)
    fields, pick = {}, ""
    for name, items, n, what, key in (("decisiones", dec, cfg["dec"], "decisiones", "texto"),
                                      ("tareas", tar, cfg["tar"], "tareas", "tarea")):
        if items:
            text += f"\n\n{what.capitalize()}:\n" + "\n".join(f"{i}. [{x['t']}] {x[key]}" for i, x in enumerate(items, 1))
        if n and len(items) > n:
            fields[name] = arr({"enum": list(range(1, len(items) + 1))}, n)
            pick += f"{name}: números de las {n} {what} más importantes.\n"
    fields["resumen"] = S(cfg["tldr"][1])
    red = chat(FINAL_PROMPT.format(src=src, tldr=cfg["tldr"][0], pick=pick, faithful=FAITHFUL, lang=lang), text,
               obj(**fields), 1000, 1.1)
    top = lambda items, name: [items[i - 1] for i in sorted(set(red[name]))] if name in red else items
    return {"resumen": red["resumen"], "secciones": secs, "decisiones": top(dec, "decisiones"), "tareas": top(tar, "tareas"),
            "mas": bool(cfg["dec"] and len(dec) > cfg["dec"] or cfg["tar"] and len(tar) > cfg["tar"])}


def pick_shots(kfs, sel, n):
    """Capturas relevantes: peso = suma de notas de los puntos elegidos cerca de la captura; las n de más peso (o todas)."""
    scr = [k for k in kfs if k["screen"]]
    if n is None:
        return scr
    w = lambda k: sum(p[2] for p in sel if k["t"] + SHOT_WIN[0] <= p[0] <= k["t"] + SHOT_WIN[1])
    return sorted(sorted(scr, key=w, reverse=True)[:n], key=lambda k: k["t"])


# ---------- Informe HTML ----------
CSS = """body{font:16px/1.5 system-ui,sans-serif;margin:0;color:#222;background:#fafafa}
main{display:grid;grid-template-columns:minmax(320px,44%) 1fr;gap:24px;padding:16px;max-width:1500px;margin:auto}
#side{position:sticky;top:16px;align-self:start}video{width:100%;background:#000;border-radius:6px}
@media(max-width:900px){main{grid-template-columns:1fr}#side{position:sticky;top:0;z-index:1;background:#fafafa}}
h1{font-size:1.4em;margin:.2em 0}h2{border-bottom:2px solid #ddd;padding-bottom:4px;margin-top:1.6em}
a.ts{font:13px monospace;color:#06c;text-decoration:none;margin-right:6px;cursor:pointer}a.ts:hover{text-decoration:underline}
.meta{color:#666;font-size:14px}.tldr{background:#fff;border-left:4px solid #c2185b;padding:10px 14px}
figure{margin:10px 0 14px}figure img{max-width:min(100%,560px);border:1px solid #ccc;border-radius:4px}
figcaption{font-size:13px;color:#666}table{border-collapse:collapse;width:100%}
td,th{border:1px solid #ddd;padding:4px 8px;text-align:left;vertical-align:top}
details p{margin:2px 0;font-size:14px}"""

JS = """const v=document.getElementById('v');
document.addEventListener('click',e=>{const a=e.target.closest('[data-t]');if(!a)return;e.preventDefault();
v.currentTime=+a.dataset.t;v.play();});
v.addEventListener('error',()=>{document.getElementById('pick').hidden=false});
document.querySelector('#pick input').onchange=e=>{v.src=URL.createObjectURL(e.target.files[0]);
document.getElementById('pick').hidden=true};"""


def ts_link(t):
    return f'<a class="ts" href="#" data-t="{int(t)}">[{fmt(t)}]</a>'


def render(out, title, dur, lang, red, maps, kfs, starts, segments, level):
    """Escribe index.html y devuelve las capturas que muestra (solo esas se copian a img/)."""
    cfg = LEVELS[level]
    sel = select_points(maps, cfg["keep"], cfg["pts"])
    shots = pick_shots(kfs, sel, cfg["shots"])
    esc = html.escape
    li = lambda t, x: f"<li>{ts_link(t)}{esc(x)}</li>"
    fig = lambda k: (f'<figure><a href="img/{k["img"]}" target="_blank"><img src="img/{k["img"]}" loading="lazy"></a>'
                     f'<figcaption>{ts_link(k["t"])}{esc(k["title"] or "Pantalla compartida")}</figcaption></figure>')
    more = "<p class=meta>Hay más decisiones y tareas en el nivel detallado.</p>" if red["mas"] else ""
    body = []
    secs = red["secciones"]
    for i, s in enumerate(secs):  # secciones = bloques del map: viñetas por bloque, capturas por rango de tiempo
        t0 = 0 if i == 0 else s["t"]
        t1 = secs[i + 1]["t"] if i + 1 < len(secs) else 1e9
        inner = sorted([(t, li(t, x)) for t, x, _, b in sel if b == s["b"]] +
                       [(k["t"], f"</ul>{fig(k)}<ul>") for k in shots if t0 <= k["t"] < t1])
        body.append(f"<h3>{ts_link(s['t'])}{esc(s['titulo'])}</h3><p>{esc(s['resumen'])}</p>"
                    f"<ul>{''.join(h for _, h in inner)}</ul>")
    dec = "".join(li(parse_ts(d["t"]), d["texto"]) for d in sorted(red["decisiones"], key=lambda d: parse_ts(d["t"])))
    tasks = "".join(f"<tr><td>{ts_link(parse_ts(t['t']))}{esc(t['tarea'])}</td><td>{esc(t['responsable'])}</td>"
                    f"<td>{esc(t['plazo'])}</td></tr>" for t in sorted(red["tareas"], key=lambda t: parse_ts(t["t"])))
    if cfg["secs"]:
        desarrollo = f"<h2>Desarrollo</h2>{''.join(body)}"
    else:  # breve: unos pocos puntos clave con marca y las capturas más relevantes
        desarrollo = (f"<h2>Puntos clave</h2><ul>{''.join(li(t, x) for t, x, _, _ in sel)}</ul>"
                      + (f"<h2>Capturas</h2>{''.join(fig(k) for k in shots)}" if shots else ""))
    trans = "".join(f"<p>{ts_link(s['s'])}{esc(s['text'])}</p>" for s in segments)
    page = f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Acta — {esc(title)}</title><style>{CSS}</style></head>
<body><main><div id="side"><video id="v" src="video{Path(title).suffix}" controls preload="metadata"></video>
<p id="pick" hidden>No se encuentra el vídeo junto al informe. Ábrelo: <input type="file" accept="video/*"></p></div>
<div><h1>Acta: {esc(title)}</h1><p class="meta">Duración {fmt(dur)} · idioma {esc(lang)} · nivel {level} ·
generado {time.strftime('%Y-%m-%d %H:%M')}</p>
<h2>Resumen</h2><div class="tldr">{esc(red['resumen'])}</div>
<h2>Decisiones</h2><ul>{dec or "<li>—</li>"}</ul>
<h2>Tareas</h2><table><tr><th>Tarea</th><th>Responsable</th><th>Plazo</th></tr>{tasks or "<tr><td colspan=3>—</td></tr>"}</table>
{more}
{desarrollo}
<h2>Transcripción</h2><details><summary>Mostrar transcripción completa</summary>{trans}</details>
</div></main><script>{JS}</script></body></html>"""
    (out / "index.html").write_text(page, encoding="utf-8")
    return shots


def put_file(src, dst):
    """Enlace duro, si no simbólico, si no copia (Windows: entre unidades no hay enlace duro y el simbólico pide permisos)."""
    for put in (os.link, os.symlink, shutil.copy):
        with contextlib.suppress(OSError):
            put(src, dst)
            return


# ---------- Orquestación ----------
def run(video, level="normal", quality="rápido", threads=PHYS, cb=lambda f, m: None):
    video = Path(video)
    wd = WORK / video_id(video)
    wd.mkdir(parents=True, exist_ok=True)
    timings = {}
    stage = lambda name, t0: timings.__setitem__(name, round(time.time() - t0, 1))
    dur = duration(video)

    tf = wd / f"transcript_{quality}.json"
    if not tf.exists():
        t0 = time.time()
        tf.write_text(json.dumps(transcribe(video, quality, threads, dur, lambda f, m: cb(0.45 * f, m)), ensure_ascii=False))
        stage("asr", t0)
    tr = json.loads(tf.read_text())
    if not tr["segments"]:
        raise RuntimeError("No se ha detectado voz en el vídeo")
    lang = LANG.get(tr["language"], f"el idioma de la reunión ({tr['language']})")

    kf = wd / "frames.json"  # OCR crudo; screens() lo clasifica y deduplica en cada ejecución
    if not kf.exists():
        t0 = time.time()
        kf.write_text(json.dumps(keyframes(video, wd, threads, dur, lambda f, m: cb(0.45 + 0.15 * f, m)), ensure_ascii=False))
        stage("capturas+ocr", t0)
    kfs = screens(json.loads(kf.read_text()))

    chunks = chunk(tr["segments"])
    starts = [c[0]["s"] for c in chunks]
    inputs = [map_input(c, kfs) for c in chunks]
    # la caché lleva el hash de prompt + esquema + modelo + entrada (transcripción y OCR): cambiar cualquiera la invalida
    mh = hashlib.sha1("\0".join([MAP_PROMPT, json.dumps(MAP_SCHEMA), str(llm_model()), *inputs]).encode()).hexdigest()[:8]
    vh = hashlib.sha1((mh + VALID_PROMPT).encode()).hexdigest()[:8]
    rh = hashlib.sha1((vh + SEC_PROMPT + FINAL_PROMPT + FAITHFUL + json.dumps(LEVELS[level])).encode()).hexdigest()[:8]
    mf, rf = wd / f"map_{quality}_{mh}.json", wd / f"reduce_{quality}_{level}_{rh}.json"
    maps = json.loads(mf.read_text()) if mf.exists() else []
    vf = wd / f"valid_{quality}_{vh}.json"
    if len(maps) < len(chunks) or not vf.exists() or not rf.exists():
        t0 = time.time()
        cb(0.6, "Arrancando modelo de lenguaje…")
        with llama(threads) as chat:
            stage("llm_carga", t0)
            t0 = time.time()
            for i in range(len(maps), len(chunks)):
                cb(0.6 + 0.3 * i / len(chunks), f"Resumiendo bloque {i + 1}/{len(chunks)}…")
                maps.append(map_chunk(chat, chunks[i], inputs[i], lang, kfs))
                mf.write_text(json.dumps(maps, ensure_ascii=False))  # caché incremental: se retoma si se corta
            stage("map", t0)
            t0 = time.time()
            cb(0.92, "Redactando el acta…")
            if not vf.exists():
                vf.write_text(json.dumps(validate(chat, maps, starts), ensure_ascii=False))
            valid = json.loads(vf.read_text())
            rf.write_text(json.dumps(reduce_maps(chat, maps, valid, starts, level, lang), ensure_ascii=False))
            stage("reduce", t0)
    red = json.loads(rf.read_text())
    print(score_hist(maps), flush=True)

    out = wd / f"acta_{level}_{quality}"
    shutil.rmtree(out, ignore_errors=True)
    (out / "img").mkdir(parents=True)
    for k in render(out, video.name, dur, tr["language"], red, maps, kfs, starts, tr["segments"], level):
        shutil.copy(wd / "frames" / k["img"], out / "img" / k["img"])
    zpath = wd / f"acta_{video.stem}_{level}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:  # sin el vídeo: el informe pide abrirlo
        for f in out.rglob("*"):
            z.write(f, f.relative_to(out))
    # vídeo junto al informe para el reproductor: como mucho una copia por vídeo (en wd), y de ahí enlace a cada nivel
    src = wd / f"video{video.suffix}"
    if not src.exists():
        put_file(video.resolve(), src)
    put_file(src, out / src.name)
    (wd / f"timings_{quality}_{level}.json").write_text(json.dumps(timings))
    cb(1, "Listo")
    return out, zpath, timings


def _selftest():
    assert fmt(3725) == "62:05" and parse_ts("62:05") == 3725 and parse_ts("1:02:05") == 3725
    rng = np.random.default_rng(0)
    a, b = rng.integers(0, 255, (2, THUMB_H, THUMB_W))
    noisy = a.copy(); noisy[:2] += 100  # reloj en la barra de menús (franja CROP)
    cam = lambda f: (lambda x: (x.__setitem__((slice(48, 64), slice(104, 128)), rng.integers(0, 255, (16, 24))), x)[1])(f.copy())
    # A A A(reloj) B B A A, con webcam cambiando en cada muestra -> tramos A y B; la vuelta a A no se repite
    segs = stable_segments(np.array([cam(f) for f in (a, a, noisy, b, b, a, a)]))
    assert segs == [(0, 2), (3, 4)], segs

    # ASR por ventanas: ni huecos ni repetidos, marcas absolutas; una frase que cruza el borde se hace en la siguiente
    truth = [(t, t + 8, f"s{t}") for t in range(0, 2500, 10)]
    fake = lambda st, ln: ((s - st, min(e, st + ln) - st, x) for s, e, x in truth if st <= s < st + ln)
    assert windowed(fake, 2508, 900) == truth
    assert windowed(fake, 2508, 895) == truth  # borde en mitad de una frase

    # pantallas: la barra de marcadores y los nombres de la columna de caras (cortados distinto) son interfaz;
    # la cuadrícula de caras no es pantalla; la diapositiva que crece conserva la marca solo si es casi igual
    bar = "meet.google.com/abc | Otros marcadores | Ana Pérez está presentando"
    kf = lambda t, txt: {"t": t, "img": f"k{t}.jpg", "text": f"{bar} | Luis Antonio Gar{'cía Díaz' if t % 2 else '...'} | {txt}"}
    grid = "Miguel Ángel Calle | Ricardo Maldonado Reusens | Danny alexander Guevara"
    ks = screens([kf(0, grid), kf(9, "Plan del proyecto | Fase 1 con el equipo de diseño y pruebas"),
                  kf(20, "Plan del proyecto | Fase 1 con el equipo de diseño y pruebas | Fase 2 beta pública en abril"),
                  kf(31, "Presupuesto total de doscientos mil euros para el año"),
                  kf(40, "Plan del proyecto | Fase 1 con el equipo de diseño y pruebas | Fase 2 beta pública en abril | "
                         "Fase 3 lanzamiento internacional con socios"),
                  kf(51, grid), kf(60, "Presupuesto total de doscientos mil euros para el año 2025")])
    assert [(k["t"], k["screen"]) for k in ks] == [(0, False), (9, False), (20, False), (31, False), (40, True),
                                                   (51, False), (31, True)], ks
    assert "marcadores" not in ks[6]["text"] and ks[6]["title"].startswith("Presupuesto total"), ks[6]

    assert len(chunk([{"s": i, "e": i + 1, "text": "x" * 991} for i in range(30)])) == 3
    assert [len(c) for c in chunk([{"s": i, "e": i + 1, "text": "x" * 991} for i in range(23)])] == [11, 12]  # cola unida
    pts = lambda *n: {"puntos": [{"importancia": i, "t": "00:0%d" % k, "texto": "p"} for k, i in enumerate(n)]}
    maps = [pts(5, 5, 4, 4), pts(5, 4, 4, 4, 4, 4, 1, 1)]  # todo 4-5: el presupuesto igualmente separa niveles
    n = [len(select_points(maps, LEVELS[lv]["keep"])) for lv in LEVELS]
    assert n == [2, 5, 10], n
    assert [x[2] for x in select_points(maps, 0.3)] == [5, 5, 5], "primero las notas altas"
    assert len(select_points(maps, 1.0, 4)) == 4 and min(x[2] for x in select_points(maps, 1.0)) == 4, "1 = relleno, fuera"

    sg = [{"s": 0, "text": "Hola a todos."}, {"s": 10, "text": "Bueno, pues se aprueba el"},
          {"s": 14, "text": "acta por unanimidad"}, {"s": 20, "text": "de los presentes."}]
    assert find_quote("se aprueba el acta por unanimidad", sg) == (1.0, 10)
    assert find_quote("se acordó contratar a dos personas", sg)[0] < 0.5
    dd = lambda c: {"cita": c, "texto": c, "t": "00:00"}
    fake = lambda *a: {"tema": "", "puntos": [], "tareas": [], "decisiones": [
        dd("se aprueba el acta por unanimidad"), dd("contratar a dos personas"), dd("hola a todos"),
        {**dd("se aprueba el acta por unanimidad"), "t": "00:20"}]}
    m = map_chunk(fake, [{**s, "e": s["s"] + 4} for s in sg], "", "español", [{"t": 5, "text": "Acuerdos: | Hola a todos y bienvenidos"}])
    assert [d["t"] for d in m["decisiones"]] == ["00:10", "00:20"], m  # inventada y leída de la pantalla: fuera
    mp = [{"tema": "a", "decisiones": [dd("x uno"), dd("y dos tres")], "tareas": [], "puntos": [pts(3)["puntos"][0]]}]
    v = validate(lambda *a: {"decisiones": [2], "tareas": []}, mp, [0])
    assert [d["texto"] for d in v["decisiones"]] == ["y dos tres"] and v["tareas"] == [], v
    r = reduce_maps(lambda *a: {"resumen": "r"}, mp, v, [0], "normal", "español")
    assert r["decisiones"] == v["decisiones"] and r["secciones"][0]["resumen"] == "p" and not r["mas"], r
    d = lambda t, x: {"t": t, "texto": x}
    assert [x["t"] for x in dedupe([
        d("44:59", "Notificar la resolución adoptada al correo electrónico del postulante."),
        d("79:00", "Notificar la resolución adoptada por el pleno al correo electrónico del postulante."),
        d("80:03", "Aceptación parcial de la recalificación de Juan Manuel García."),
        d("86:14", "Aceptación parcial de la recalificación de Carlos Javier Espinoza."),
        d("88:00", "Aceptación parcial de la recalificación de Kappa.")], "texto")] == ["44:59", "80:03", "86:14", "88:00"]
    tk = lambda t, x: {"t": t, "tarea": x}
    assert [x["t"] for x in dedupe([tk("25:51", "La Secretaría General del CNE notificará la resolución a los postulantes."),
                                    tk("59:28", "Notificar las resoluciones adoptadas por el pleno al correo del postulante."),
                                    tk("138:56", "Reanudar la sesión el día siguiente a las 9:00 h.")], "tarea", True)] == [
        "25:51", "138:56"]
    g = gbnf(obj(p=arr(obj(n={"enum": [1, 2]}, t=TS, c=S(9)), 3)))
    assert 'root ::= o6' in g and '"[" sp (o5 ("," sp o5){0,2})? sp "]"' in g and '("1" | "2")' in g, g
    assert 's9 ::= "\\"" ch{0,9} "\\""' in g, g
    print("ok")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Genera el acta de una reunión grabada")
    ap.add_argument("video", nargs="?")
    ap.add_argument("--nivel", default="normal", choices=LEVELS)
    ap.add_argument("--asr", default="rápido", choices=ASR_MODELS)
    ap.add_argument("--threads", type=int, default=PHYS)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest or not a.video:
        sys.exit(_selftest())
    last = [0.0]

    def cb(f, m):
        if time.time() - last[0] > 5 or f >= 1:
            last[0] = time.time()
            print(f"{f:5.0%} {m}", flush=True)
    out, z, t = run(a.video, a.nivel, a.asr, a.threads, cb)
    print(out / "index.html", z, json.dumps(t), sep="\n")
