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
# keep = fracción de puntos (ranking global por importancia) que entra en el acta; shots = máx. de capturas (None = todas)
# secs = secciones por tema; extra = cifras y citas. Decisiones y tareas siempre entran.
LEVELS = {
    "breve": dict(keep=0.2, shots=3, secs=False, extra=False, tldr="2-3 frases", sec=""),
    "normal": dict(keep=0.5, shots=10, secs=True, extra=False, tldr="4-6 frases", sec="2-3 frases"),
    "detallado": dict(keep=1.0, shots=None, secs=True, extra=True, tldr="un párrafo de 6-10 frases", sec="3-5 frases"),
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

        def chat(system, user, schema, max_tokens):
            body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "temperature": 0.2, "max_tokens": max_tokens, "grammar": gbnf(schema)}
            req = urllib.request.Request(url + "/v1/chat/completions", json.dumps(body).encode(),
                                         {"Content-Type": "application/json"})
            r = json.load(urllib.request.urlopen(req, timeout=7200))
            return json.loads(r["choices"][0]["message"]["content"])
        yield chat
    finally:
        proc.terminate()
        proc.wait(10)
        log.close()


def obj(**props):
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


STR = {"type": "string"}
TS = {"type": "string", "pattern": "^[0-9]{1,3}:[0-5][0-9]$"}
arr = lambda item, n: {"type": "array", "items": item, "maxItems": n}
TASK = obj(tarea=STR, responsable=STR, plazo=STR, t=TS)
MAP_SCHEMA = obj(tema=STR, puntos=arr(obj(texto=STR, importancia={"enum": [1, 2, 3, 4, 5]}, t=TS), 10),
                 datos=arr(obj(texto=STR, t=TS), 4), decisiones=arr(obj(texto=STR, t=TS), 5), tareas=arr(TASK, 5))


def reduce_schema(secs):
    return obj(resumen=STR, secciones=arr(obj(titulo=STR, t=TS, resumen=STR), 15)) if secs else obj(resumen=STR)


def gbnf(schema):
    """Esquema (solo obj/arr/STR/TS/enum de aquí) -> gramática GBNF compacta: sin saltos de línea ni sangría (menos tokens;
    con json_schema Gemma se quedaba generando espacios hasta max_tokens) y con maxItems como límite duro."""
    rules = {"sp": '" "?', "ts": r'"\"" [0-9] [0-9]? [0-9]? ":" [0-5] [0-9] "\""',
             "str": r'"\"" ([^"\\\x7F\x00-\x1F] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F]{4}))* "\""'}
    lit = lambda v: json.dumps(json.dumps(v) if not isinstance(v, str) else v)

    def g(s):
        if "enum" in s:
            return "(" + " | ".join(lit(v) for v in s["enum"]) + ")"
        if s.get("type") == "array":
            it = g(s["items"])
            return f'"[" sp ({it} ("," sp {it}){{0,{s["maxItems"] - 1}}})? sp "]"'
        if s.get("type") == "object":
            body = ' "," sp '.join(f'{lit(json.dumps(k) + ":")} sp {g(v)}' for k, v in s["properties"].items())
            name = f"o{len(rules)}"
            rules[name] = f'"{{" sp {body} sp "}}"'
            return name
        return "ts" if "pattern" in s else "str"
    rules["root"] = g(schema)
    return "\n".join(f"{k} ::= {v}" for k, v in rules.items())

# Salida corta a propósito: generar es lo caro en CPU (~5-11 tok/s); 10 puntos de <= 20 palabras ≈ 500 tokens por bloque
MAP_PROMPT = """Redactas actas de reuniones. Recibes un fragmento de transcripción automática (con errores) con marcas [mm:ss] \
y, a veces, texto de la pantalla compartida.
puntos: hasta 10 ideas del fragmento, de mayor a menor importancia; cada una, una frase autocontenida de máx. 20 palabras; \
t = marca donde empieza.
importancia: 5 = decisión, compromiso o cifra clave; 4 = información nueva relevante; 3 = contexto útil; 2 = detalle o ejemplo; \
1 = relleno (saludos, logística). Como mucho un 5 y dos 4 por cada cinco puntos; la mayoría 2-3.
datos: cifras, nombres, fechas o citas literales (máx. 4).
decisiones y tareas: solo las acordadas o asignadas explícitamente; si no hay, lista vacía. En tareas, responsable y plazo \
"—" si no se dicen.
Solo lo que dice el texto; no inventes. Escribe en {lang}."""

REDUCE_PROMPT = """Eres un asistente que redacta actas de reuniones. Recibes los puntos clave extraídos de cada bloque \
de una reunión, en orden cronológico, con marcas [mm:ss].
Redacta el acta final:
- resumen: resumen general de {tldr}.
{secs}Usa solo la información recibida, no inventes. Escribe en {lang}."""


def chunk(segments):
    out, cur = [], []
    for s in segments:
        cur.append(s)
        if sum(len(x["text"]) + 9 for x in cur) > CHUNK_CHARS:
            out.append(cur)
            cur = []
    return out + [cur] if cur else out


def map_input(segs, kfs):
    t0, t1 = segs[0]["s"], segs[-1]["e"]
    text = "\n".join(f"[{fmt(s['s'])}] {s['text']}" for s in segs)
    screens = [f"[{fmt(k['t'])}] {k['text'][:600]}" for k in kfs if k["screen"] and t0 <= k["t"] <= t1]
    if screens:
        text += "\n\nTexto en pantalla compartida:\n" + "\n".join(screens)[:2500]
    return text


def map_chunk(chat, segs, text, lang):
    m = chat(MAP_PROMPT.format(lang=lang), text, MAP_SCHEMA, 1000)
    t0, t1 = segs[0]["s"], segs[-1]["e"]
    for item in (x for k in ("puntos", "datos", "decisiones", "tareas") for x in m[k]):
        if not t0 - 5 <= parse_ts(item["t"]) <= t1 + 5:  # marca inventada fuera del bloque: al inicio del bloque
            item["t"] = fmt(t0)
    return m


def select_points(maps, keep):
    """Puntos [(t, texto, nota)] que entran en el acta: ranking global (nota, orden en el bloque), se queda `keep`.
    Por presupuesto y no por umbral: aunque el modelo puntúe todo 4-5, cada nivel muestra un contenido distinto."""
    allp = sorted(((-p["importancia"], n, parse_ts(p["t"]), p["texto"]) for m in maps for n, p in enumerate(m["puntos"])),
                  key=lambda x: x[:2])
    return sorted((t, txt, -neg) for neg, _, t, txt in allp[:max(1, round(keep * len(allp))) if allp else 0])


def score_hist(maps):
    c = [sum(p["importancia"] == k for m in maps for p in m["puntos"]) for k in range(1, 6)]
    return "puntos por nota " + " ".join(f"{k}:{n}" for k, n in zip(range(1, 6), c)) + f" (total {sum(c)})"


def reduce_maps(chat, maps, level, lang):
    cfg = LEVELS[level]
    keep = cfg["keep"]
    while True:  # ponytail: un solo reduce; si no cabe se reduce la fracción. Reduce jerárquico si 3 h no caben
        sel = select_points(maps, keep)
        text = "\n".join(f"- [{fmt(t)}] {x}" for t, x, _ in sel)
        dec = "\n".join(f"- DECISIÓN [{d['t']}] {d['texto']}" for m in maps for d in m["decisiones"])
        tar = "\n".join(f"- TAREA [{t['t']}] {t['tarea']} (responsable: {t['responsable']}; plazo: {t['plazo']})"
                        for m in maps for t in m["tareas"])
        text = "\n\n".join(x for x in (text, dec, tar) if x)
        if len(text) < 16000 or keep < 0.05:
            break
        keep *= 0.8
    secs = f"- secciones: agrupa por tema en orden cronológico; t = marca del primer punto de la sección; resumen de {cfg['sec']}.\n" if cfg["secs"] else ""
    red = chat(REDUCE_PROMPT.format(lang=lang, tldr=cfg["tldr"], secs=secs), text, reduce_schema(cfg["secs"]), 2000)
    # decisiones y tareas tal cual del map: reescribirlas con el LLM costaba cientos de tokens generados y no aportaba
    return {**red, "decisiones": [d for m in maps for d in m["decisiones"]], "tareas": [t for m in maps for t in m["tareas"]]}


def pick_shots(kfs, sel, n):
    """Capturas relevantes: peso = suma de notas de los puntos elegidos cerca de la captura; las n de más peso (o todas)."""
    scr = [k for k in kfs if k["screen"]]
    if n is None:
        return scr
    w = lambda k: sum(sc for t, _, sc in sel if k["t"] + SHOT_WIN[0] <= t <= k["t"] + SHOT_WIN[1])
    return sorted(sorted(scr, key=w, reverse=True)[:n], key=lambda k: k["t"])


# ---------- Informe HTML ----------
CSS = """body{font:16px/1.5 system-ui,sans-serif;margin:0;color:#222;background:#fafafa}
main{display:grid;grid-template-columns:minmax(320px,44%) 1fr;gap:24px;padding:16px;max-width:1500px;margin:auto}
#side{position:sticky;top:16px;align-self:start}video{width:100%;background:#000;border-radius:6px}
@media(max-width:900px){main{grid-template-columns:1fr}#side{position:sticky;top:0;z-index:1;background:#fafafa}}
h1{font-size:1.4em;margin:.2em 0}h2{border-bottom:2px solid #ddd;padding-bottom:4px;margin-top:1.6em}
a.ts{font:13px monospace;color:#06c;text-decoration:none;margin-right:6px;cursor:pointer}a.ts:hover{text-decoration:underline}
.meta{color:#666;font-size:14px}.tldr{background:#fff;border-left:4px solid #c2185b;padding:10px 14px}
figure{margin:10px 0 14px}figure img{max-width:100%;border:1px solid #ccc;border-radius:4px}
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


def render(out, title, dur, lang, red, maps, kfs, segments, level):
    cfg = LEVELS[level]
    sel = select_points(maps, cfg["keep"])
    shots = pick_shots(kfs, sel, cfg["shots"])
    esc = html.escape
    sections = sorted(red.get("secciones", []), key=lambda s: parse_ts(s["t"])) or [{"titulo": "Reunión", "t": "00:00", "resumen": ""}]
    starts = [0] + [parse_ts(s["t"]) for s in sections[1:]]
    # una diapositiva que aparece justo antes (<20 s) del primer punto de una sección abre esa sección
    starts = [min([st] + [k["t"] for k in kfs if k["screen"] and st - 20 <= k["t"] < st]) for st in starts]
    items = [(t, f"<li>{ts_link(t)}{esc(x)}</li>") for t, x, _ in sel]
    items += [(k["t"], f'<figure><a href="img/{k["img"]}" target="_blank"><img src="img/{k["img"]}" loading="lazy"></a>'
                       f'<figcaption>{ts_link(k["t"])}Pantalla compartida</figcaption></figure>')
              for k in shots]
    body = []
    for i, s in enumerate(sections):
        end = starts[i + 1] if i + 1 < len(sections) else 1e9
        inner = [h for t, h in sorted(items, key=lambda x: x[0]) if starts[i] <= t < end]
        lis = "".join(x if x.startswith("<li>") else f"</ul>{x}<ul>" for x in inner)
        body.append(f"<h3>{ts_link(starts[i])}{esc(s['titulo'])}</h3><p>{esc(s['resumen'])}</p><ul>{lis}</ul>")
    dec = "".join(f"<li>{ts_link(parse_ts(d['t']))}{esc(d['texto'])}</li>" for d in sorted(red["decisiones"], key=lambda d: parse_ts(d["t"]))) or "<li>—</li>"
    tasks = "".join(f"<tr><td>{ts_link(parse_ts(t['t']))}{esc(t['tarea'])}</td><td>{esc(t['responsable'])}</td>"
                    f"<td>{esc(t['plazo'])}</td></tr>" for t in sorted(red["tareas"], key=lambda t: parse_ts(t["t"])))
    figs = "".join(h for _, h in items if h.startswith("<figure>"))
    datos = "".join(f"<li>{ts_link(parse_ts(d['t']))}{esc(d['texto'])}</li>" for m in maps for d in m["datos"])
    if cfg["secs"]:
        desarrollo = f"<h2>Desarrollo</h2>{''.join(body)}" + (f"<h2>Cifras y citas</h2><ul>{datos}</ul>" if cfg["extra"] and datos else "")
    else:  # breve: sin desarrollo, solo las capturas más relevantes
        desarrollo = f"<h2>Capturas</h2>{figs}" if figs else ""
    trans = "".join(f"<p>{ts_link(s['s'])}{esc(s['text'])}</p>" for s in segments)
    page = f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Acta — {esc(title)}</title><style>{CSS}</style></head>
<body><main><div id="side"><video id="v" src="video{Path(title).suffix}" controls preload="metadata"></video>
<p id="pick" hidden>No se encuentra el vídeo junto al informe. Ábrelo: <input type="file" accept="video/*"></p></div>
<div><h1>Acta: {esc(title)}</h1><p class="meta">Duración {fmt(dur)} · idioma {esc(lang)} · nivel {level} ·
generado {time.strftime('%Y-%m-%d %H:%M')}</p>
<h2>Resumen</h2><div class="tldr">{esc(red['resumen'])}</div>
<h2>Decisiones</h2><ul>{dec}</ul>
<h2>Tareas</h2><table><tr><th>Tarea</th><th>Responsable</th><th>Plazo</th></tr>{tasks}</table>
{desarrollo}
<h2>Transcripción</h2><details><summary>Mostrar transcripción completa</summary>{trans}</details>
</div></main><script>{JS}</script></body></html>"""
    (out / "index.html").write_text(page, encoding="utf-8")


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
    inputs = [map_input(c, kfs) for c in chunks]
    # la caché lleva el hash de prompt + esquema + modelo + entrada (transcripción y OCR): cambiar cualquiera la invalida
    mh = hashlib.sha1("\0".join([MAP_PROMPT, json.dumps(MAP_SCHEMA), str(llm_model()), *inputs]).encode()).hexdigest()[:8]
    rh = hashlib.sha1((mh + REDUCE_PROMPT + json.dumps(LEVELS[level])).encode()).hexdigest()[:8]
    mf, rf = wd / f"map_{quality}_{mh}.json", wd / f"reduce_{quality}_{level}_{rh}.json"
    maps = json.loads(mf.read_text()) if mf.exists() else []
    if len(maps) < len(chunks) or not rf.exists():
        t0 = time.time()
        cb(0.6, "Arrancando modelo de lenguaje…")
        with llama(threads) as chat:
            stage("llm_carga", t0)
            t0 = time.time()
            for i in range(len(maps), len(chunks)):
                cb(0.6 + 0.3 * i / len(chunks), f"Resumiendo bloque {i + 1}/{len(chunks)}…")
                maps.append(map_chunk(chat, chunks[i], inputs[i], lang))
                mf.write_text(json.dumps(maps, ensure_ascii=False))  # caché incremental: se retoma si se corta
            stage("map", t0)
            t0 = time.time()
            cb(0.92, "Redactando el acta…")
            rf.write_text(json.dumps(reduce_maps(chat, maps, level, lang), ensure_ascii=False))
            stage("reduce", t0)
    red = json.loads(rf.read_text())
    print(score_hist(maps), flush=True)

    out = wd / f"acta_{level}_{quality}"
    shutil.rmtree(out, ignore_errors=True)
    (out / "img").mkdir(parents=True)
    for k in kfs:
        if k["screen"]:
            shutil.copy(wd / "frames" / k["img"], out / "img" / k["img"])
    render(out, video.name, dur, tr["language"], red, maps, kfs, tr["segments"], level)
    zpath = wd / f"acta_{video.stem}_{level}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:  # sin el vídeo: el informe pide abrirlo
        for f in out.rglob("*"):
            z.write(f, f.relative_to(out))
    dst = out / f"video{video.suffix}"  # vídeo junto al informe para el reproductor; sin copiar si se puede
    for put in (os.link, os.symlink, shutil.copy):
        with contextlib.suppress(OSError):
            put(video.resolve(), dst)
            break
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

    assert len(chunk([{"s": i, "e": i + 1, "text": "x" * 991} for i in range(25)])) == 3
    pts = lambda *n: {"puntos": [{"importancia": i, "t": "00:0%d" % k, "texto": "p"} for k, i in enumerate(n)]}
    maps = [pts(5, 5, 4, 4), pts(5, 4, 4, 4, 4, 4)]  # todo 4-5: el presupuesto igualmente separa niveles
    n = [len(select_points(maps, LEVELS[lv]["keep"])) for lv in LEVELS]
    assert n == [2, 5, 10], n
    assert [x[2] for x in select_points(maps, 0.3)] == [5, 5, 5], "primero las notas altas"
    g = gbnf(obj(p=arr(obj(n={"enum": [1, 2]}, t=TS), 3)))
    assert 'root ::= o4' in g and '"[" sp (o3 ("," sp o3){0,2})? sp "]"' in g and '("1" | "2")' in g, g
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
