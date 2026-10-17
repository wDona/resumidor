"""Vídeo de reunión -> acta HTML (resumen + capturas + marcas de tiempo). Todo local, CPU."""
import bisect, contextlib, functools, hashlib, html, json, os, re, shutil, socket, subprocess, sys, tempfile, time, unicodedata, urllib.request, zipfile
from collections import Counter
from itertools import groupby
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
# quién habla: sherpa-onnx (huella de voz CAM++ de 3D-Speaker, 27 MB)
DIAR_EMB = ("3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx",
            "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
            "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx",
            "aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2")
DIAR_THR, DIAR_PIECE, DIAR_MIN = 0.6, 5, 1.2  # umbral de distancia coseno (más alto = menos hablantes) / s máx. y mín. por trozo
DIAR_MERGE = 0.2  # grupos con centroides a menos distancia coseno = la misma voz (medido: misma voz 0.01-0.12, voces distintas ≥ 0.42)
MIN_CHARS = 30                # letras OCR (sin interfaz ni nombres, ver screens) para considerar un frame "pantalla compartida"
CHUNK_CHARS = 10000           # ~3k tokens de transcripción por bloque del map
ASR_WIN = 900                 # s de audio por ventana del ASR: la RAM no crece con la duración de la reunión
ASR_MODELS = {"rápido": "small", "calidad": "large-v3-turbo"}
LLM = ("Qwen3.5-4B-Q4_0.gguf", "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_0.gguf")
# ponytail: núcleos físicos = lógicos / 2 (SMT de 2 hilos, p. ej. i5-1135G7 4C/8T); con más hilos que núcleos llama.cpp
# genera a menos de la mitad de velocidad. Sin SMT se queda con la mitad: --threads / ACTAS_THREADS lo corrigen
PHYS = max(1, (os.cpu_count() or 2) // 2)
# keep = fracción de puntos (ranking global por importancia) que entra en el acta; pts = puntos a la vista (breve: los
# "puntos clave", siempre esos si los hay, aunque keep diera menos); shots = máx. de capturas; dec/tar = máx. de decisiones/tareas (las elige el LLM); None = todas.
# secs = una sección por bloque del map con su resumen.
# tldr/sec = largo pedido del resumen global/de sección y los caracteres que se le piden; el tope duro de la gramática es un
# 50 % más (un modelo pequeño a veces entra en bucle y agotaría max_tokens) y, si se alcanza, se recorta en la última frase
# completa (sentences): nunca a mitad de palabra
LEVELS = {
    "breve": dict(keep=0.2, pts=8, shots=3, dec=5, tar=5, secs=False, tldr=("2-3 frases", 450), sec=None),
    "normal": dict(keep=0.5, pts=None, shots=10, dec=12, tar=10, secs=True, tldr=("4-6 frases", 750),
                   sec=("2-3 frases", 350)),
    "detallado": dict(keep=1.0, pts=None, shots=None, dec=None, tar=None, secs=True,
                      tldr=("un párrafo de 6-10 frases", 1200), sec=("3-5 frases", 600)),
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


def pcm16k(video, start, length):
    """Audio mono 16 kHz de una ventana vía ffmpeg (PyAV 19 rompe el decode_audio de faster-whisper 1.2.1); solo esa ventana
    en RAM: faster-whisper hace la STFT de todo lo que recibe de una vez; con la reunión entera eran 7 GB en 2 h 20."""
    return np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{start:.2f}", "-t", str(length), "-i", str(video),
                                         "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                                        capture_output=True, check=True).stdout, np.float32)


def transcribe(video, quality, threads, dur, cb):
    from faster_whisper import WhisperModel
    name = ASR_MODELS[quality]
    cb(0, f"Cargando modelo de voz ({name})…")
    model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=threads)
    lang = [None]  # se detecta en la primera ventana y se fija para las demás

    def win(start, length):
        segs, info = model.transcribe(pcm16k(video, start, length), language=lang[0], vad_filter=True,
                                      beam_size=1 if name == "small" else 5, condition_on_previous_text=False)
        lang[0] = lang[0] or info.language
        for s in segs:
            cb(min((start + s.end) / dur, 1), f"Transcribiendo… {fmt(start + s.end)} / {fmt(dur)}")
            yield s.start, s.end, s.text.strip()
    segs = windowed(win, dur, ASR_WIN)
    return {"language": lang[0], "segments": [{"s": round(s, 1), "e": round(e, 1), "text": t} for s, e, t in segs if t]}


# ---------- Quién habla ----------
def diarize(video, segments, threads, cb):
    """{"turns": [(inicio, fin, huella)], "prints": huella de voz de cada trozo}; vacío sin modelos (sin red). Sin el modelo de
    segmentación de sherpa-onnx (lo más caro, ~18 s por cada 5 min en el ProBook): se toma como unidad los segmentos del ASR
    (ya sin silencios), partidos en trozos de <= DIAR_PIECE s, y de cada uno se saca la huella de voz con 3D-Speaker CAM++ (~0,007x
    tiempo real). Por ventanas de ASR_WIN como el ASR (la RAM no crece con la duración). Los trozos se agrupan en speaker_turns."""
    import sherpa_onnx as so
    emb = model_file(DIAR_EMB)
    if not emb:
        return {"turns": [], "prints": []}
    ex = so.SpeakerEmbeddingExtractor(so.SpeakerEmbeddingExtractorConfig(model=str(emb), num_threads=threads))
    turns, prints = [], []
    for w in range(0, int(segments[-1]["e"] // ASR_WIN) + 1):
        cb(min(w * ASR_WIN / segments[-1]["e"], 1), f"Separando hablantes… {fmt(w * ASR_WIN)}")
        pcm = pcm16k(video, w * ASR_WIN, ASR_WIN)
        for sg in segments:
            if not w * ASR_WIN <= sg["s"] < (w + 1) * ASR_WIN:
                continue
            n = max(1, round((sg["e"] - sg["s"]) / DIAR_PIECE))
            step = (sg["e"] - sg["s"]) / n
            for i in range(n):
                a, b = sg["s"] + i * step, sg["s"] + (i + 1) * step
                x = pcm[int((a - w * ASR_WIN) * 16000):int((b - w * ASR_WIN) * 16000)]
                if b - a < DIAR_MIN or len(x) < 16000 * DIAR_MIN:
                    continue
                st = ex.create_stream()
                st.accept_waveform(16000, x)
                st.input_finished()
                e = np.array(ex.compute(st))
                prints.append([round(float(v), 4) for v in e / np.linalg.norm(e)])
                turns.append((round(a, 2), round(b, 2), len(prints) - 1))
    return {"turns": turns, "prints": prints}


def speaker_turns(turns, prints, thr=DIAR_THR, small=0.04):
    """Agrupa las huellas de todos los trozos (distancia coseno < thr = misma voz): turnos [(inicio, fin, hablante)]. Los
    grupos con < small del total (ruido, una frase suelta) se funden con el hablante grande más parecido."""
    import sherpa_onnx as so
    X = np.array(prints)
    lab = np.array(so.FastClustering(so.FastClusteringConfig(num_clusters=-1, threshold=thr))(X)) if len(X) > 1 else np.zeros(len(X), int)
    big = [k for k, v in Counter(lab.tolist()).items() if v >= small * len(lab)]
    if big and len(big) < len(set(lab.tolist())):
        cen = np.array([X[lab == k].mean(0) for k in big])
        lab = np.array([big[int(np.argmax(cen @ x))] for x in X])
    while len(ks := sorted(set(lab.tolist()))) > 1:  # el clustering parte a veces una sola voz en dos con el mismo centroide
        cen = np.array([X[lab == k].mean(0) for k in ks])
        cen /= np.linalg.norm(cen, axis=1, keepdims=True)
        d = 1 - cen @ cen.T + 2 * np.eye(len(ks))
        i, j = np.unravel_index(d.argmin(), d.shape)
        if d[i, j] >= DIAR_MERGE:
            break
        lab[lab == ks[j]] = ks[i]
    return sorted((s, e, int(lab[k])) for s, e, k in turns)


def assign_speakers(segments, turns):
    """«Hablante N» de cada segmento: el turno con más solape (None si ninguno), numerados por orden de aparición. Con un
    solo hablante, ninguno (no aporta nada)."""
    if not turns:
        return [None] * len(segments)
    a, b, k = np.array(turns).T
    out, names = [], {}
    for s in segments:
        ov = np.bincount(k.astype(int), np.clip(np.minimum(b, s["e"]) - np.maximum(a, s["s"]), 0, None))
        out.append(names.setdefault(ov.argmax(), f"Hablante {len(names) + 1}") if ov.max() > 0 else None)
    return out if len(names) > 1 else [None] * len(segments)


who = lambda s: f"{s['spk']}: " if s.get("spk") else ""


def rename(text, names):
    """«Hablante 2» -> el nombre que le dé el usuario ({"2": "Luis"}); solo al pintar el acta, sin repetir nada."""
    return re.sub(r"\b[Hh]ablante (\d+)\b", lambda m: names.get(m[1], m[0]), text) if names else text


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


def model_file(spec):
    """Ruta del modelo (nombre, url, sha256) en models/; lo baja la primera vez. None si no hay red."""
    name, url, sha = spec
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


def screens(kfs, vocab=None):
    """Marca qué frames son pantalla compartida (k["screen"]), deja en k["text"] solo su contenido y deduplica.
    Antes de contar letras y comparar se quita la interfaz de la videollamada: líneas cuyas dos primeras palabras salen
    en >= 30 % de los frames (barra de marcadores, "X está presentando", nombres de la columna de caras aunque el OCR los
    corte distinto, paneles de la aplicación). Solo cuentan las líneas con >= 2 palabras y alguna en minúscula de >= 3
    letras: los nombres bajo las caras de Meet/Zoom/Teams y los botones no, así que una cuadrícula de caras no es pantalla.
    Repetidas (mismo texto, o una contiene a la otra: viñetas que van apareciendo, volver a una pantalla ya vista):
    queda la más completa; hereda la marca de la primera aparición solo si su texto es casi igual (>= 90 %). También si
    es la misma página desplazada (scroll): las >= 3 últimas líneas de una son las primeras de la otra.
    Pie de captura (title) = primera línea de texto, solo si >= 70 % de sus palabras salen en `vocab` (la transcripción):
    en vídeos de baja resolución el OCR da basura («aal fngora oe egunad») y es mejor el pie genérico."""
    key = lambda line: " ".join(words(line)[:2])
    lines = [[x for x in k["text"].split(" | ") if key(x)] for k in kfs]
    freq = Counter(n for ls in lines for n in {key(x) for x in ls})
    ui = {n for n, c in freq.items() if c >= max(5, 0.3 * len(kfs))}
    def real(line):
        w = [v for v in words(line) if len(v) >= 3]
        return not vocab or sum(v in vocab for v in w) >= 0.7 * len(w)
    kept = []  # [(palabras, líneas, keyframe)]
    for k, ls in zip(kfs, lines):
        body = [x for x in ls if key(x) not in ui]
        prose = [x for x in body if " " in x.strip() and re.search(r"(?<!\w)[a-záéíóúüñ]{3,}", x)]
        k.update(text=" | ".join(body), title=next((x for x in prose if len(x.split()) >= 3 and real(x)), "")[:90],
                 screen=sum(c.isalnum() for x in prose for c in x) >= MIN_CHARS,
                 end=int(re.search(r"\d+", k["img"])[0]))
        if not k["screen"]:
            continue
        w, ln = words(k["text"]), [" ".join(words(x)) for x in body]
        scroll = lambda a, b: any(a[-n:] == b[:n] for n in range(3, min(len(a), len(b)) + 1))
        for n, (ow, ol, o) in enumerate(kept):
            sm = SequenceMatcher(None, ow, w, autojunk=False)
            m = sum(b.size for b in sm.get_matching_blocks())
            if m >= DUP * min(len(ow), len(w)) or scroll(ol, ln) or scroll(ln, ol):
                keep, drop = (k, o) if len(w) > len(ow) else (o, k)
                if m >= 0.9 * max(len(ow), len(w)):
                    keep["t"] = min(k["t"], o["t"])
                drop["screen"] = False
                kept[n] = (max(w, ow, key=len), max(ln, ol, key=len), keep)
                break
        else:
            kept.append((w, ln, k))
    return kfs


def keyframes(video, wd, threads, dur, cb):
    import cv2
    from rapidocr_onnxruntime import RapidOCR
    segs = stable_segments(sample_thumbs(video, threads, dur, lambda f, m: cb(f * 0.5, m)))
    (wd / "frames").mkdir(exist_ok=True)
    rec = model_file(OCR_REC)  # None: modelo chino/inglés de serie
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
                             # sin caché de prompts en RAM (8 GB por defecto); 2 checkpoints del estado (modelo híbrido: sin ellos
                             # no se reutiliza nada; cada uno ≈ 50 MB, los 32 de serie eran +3 GB): así el prompt de sistema,
                             # igual en todos los bloques del map y en cada verificación, se lee una sola vez (-11 s por llamada
                             # con el del map; -ub 256/1024 no acelera la lectura). Sin "thinking" y sin mmap: con mmap los pesos
                             # reempaquetados para AVX quedan duplicados (≈4,9 GB de RSS en vez de 3,2 GB con Qwen3.5-4B)
                             "-cram", "0", "-ctxcp", "2", "-rea", "off", "-lm", "none",
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
                    "temperature": 0.2, "seed": 0, "max_tokens": max_tokens, "grammar": gbnf(schema),
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
arr = lambda item, n, lo=0: {"type": "array", "items": item, "maxItems": n, "minItems": lo}
# la cita va antes que el texto: el modelo primero copia la frase que lo prueba y luego redacta a partir de ella
TASK = obj(cita=S(100), tarea=S(160), responsable=S(60), plazo=S(60), t=TS)
def sentences(s, cap):
    """Texto que llegó al tope `cap` de la gramática: se recorta en la última frase completa (si queda al menos la mitad)
    o en la última palabra completa con «…». Nunca a mitad de palabra."""
    s = s.strip()
    if len(s) < cap or s[-1] in ".!?…»)\"”":
        return s
    i = max(s.rfind(c) for c in ".!?…")
    if i >= len(s) // 2:
        return s[:i + 1]
    return s.rsplit(" ", 1)[0].rstrip(",;: ") + "…"


PT_MAX = 160
MAP_SCHEMA = obj(tema=S(100), puntos=arr(obj(texto=S(PT_MAX), importancia={"enum": [1, 2, 3, 4, 5]}, t=TS), 10, 6),
                 decisiones=arr(obj(cita=S(100), texto=S(160), t=TS), 5), tareas=arr(TASK, 5))
MAP_MAX = 1600  # peor caso con todos los topes llenos (≈ 1500 tokens); lo normal son 500-900


def gbnf(schema):
    """Esquema (solo obj/arr/STR/S/TS/enum de aquí) -> gramática GBNF compacta: sin saltos de línea ni sangría (menos
    tokens; con json_schema Gemma se quedaba generando espacios hasta max_tokens) y con maxItems/maxLength como límite duro."""
    # ch: solo ASCII imprimible (sin " ni \), latín (tildes, ñ, ¿¡, «») y comillas/rayas/… tipográficas; sin \uXXXX: el
    # 4B a veces cerraba una cadena con un carácter chino
    rules = {"sp": '" "?', "ts": r'"\"" [0-9] [0-9]? [0-9]? ":" [0-5] [0-9] "\""',
             "ch": r'[\x20\x21\x23-\x5B\x5D-\x7E¡-ſ–—‘-”…€] | "\\" ["\\/nt]',
             "str": r'"\"" ch* "\""'}
    lit = json.dumps

    def g(s):
        if "enum" in s:
            return "(" + " | ".join(json.dumps(json.dumps(v)) for v in s["enum"]) + ")"
        if s.get("type") == "array":
            if not s["maxItems"]:
                return '"[" sp "]"'
            it = g(s["items"])
            lo = s.get("minItems", 0)
            return f'"[" sp ({it} ("," sp {it}){{{max(0, lo - 1)},{s["maxItems"] - 1}}}){"?" * (not lo)} sp "]"'
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
y, a veces, texto de la pantalla compartida. Lo marcado «(lectura en voz alta)» es alguien leyendo el documento que se ve \
en pantalla (p. ej. el acta anterior): es lectura, nunca una decisión ni una tarea de hoy.
tema: título breve del fragmento.
puntos: de 6 a 10 ideas, de mayor a menor importancia, repartidas por todo el fragmento (principio, mitad y final); cada \
una, una frase autocontenida de máx. 20 palabras, sin repetir ideas; t = marca donde empieza.
importancia: 5 = decisión, compromiso o cifra clave; 4 = información nueva relevante (también preguntas del público y \
sus respuestas); 3 = contexto útil; 2 = detalle o ejemplo; 1 = saludos, presentaciones, agradecimientos, despedidas y \
logística, siempre. Como mucho un 5 y dos 4 por cada cinco puntos; la mayoría 2-3.
Fidelidad: las opiniones y propuestas no son hechos («X opina que…», «se propone…»); nombra a quien habla solo si el \
texto lo deja claro, si no, en impersonal. «Hablante N:» al inicio de una línea es quien habla según la voz \
(automático): úsalo para atribuir opiniones y como responsable de quien se compromete en primera persona («me encargo yo»). No confundas a quien habla con a quien se nombra: los cargos de la reunión \
(consejera, secretario, presidenta) no son candidatos ni postulantes, y los autores o juristas citados no participan. En \
comparaciones (A frente a B) no cambies qué va con cada uno. En una demostración o tutorial, «se muestra cómo…», nunca \
«se propone» ni «se acuerda». No mezcles cifras ni nombres de partes distintas; votos, abstenciones y números solo si se \
dicen; lo leído de un acta anterior se cuenta como lectura («el acta anterior recoge…»), no como acuerdo de hoy.
decisiones: solo acuerdos tomados en esta reunión («se aprueba…», «acordamos…», votación con resultado, aplazar un \
punto a la próxima sesión, suspender la sesión). NO son \
decisiones: lo que se lee en voz alta de un acta anterior (aunque diga «Acuerdos» o «queda aprobada»: el acta se aprueba \
hoy cuando los presentes la votan o dicen estar de acuerdo), los pasos de una demostración o ejemplo («ahora creo un \
webinar…»), opiniones, observaciones ni propuestas sin aprobar («deberíamos», «se podría»).
tareas: solo encargos o compromisos explícitos de alguien para después de la reunión (quién hará qué); no lo son \
consejos o recomendaciones generales, lo que ya se hizo («se ha cursado un oficio»), pasos de una demostración ni \
ofrecimientos de cortesía («podéis contactarme»). Sin repetir: una acción que se repite (p. ej. notificar cada \
resolución) es una sola tarea. responsable: quien la hará (no a quien va dirigida), solo si el texto lo nombra; plazo: \
solo si se dice; si no, "—".
cita: copia literal de la transcripción (máx. 12 palabras) que prueba la decisión o tarea; si no la hay, no la incluyas.
Listas vacías si no hay. Solo lo que dice el texto; no inventes. Escribe en {lang}."""

FAITHFUL = "Usa solo lo recibido: no añadas hechos, cifras, votos ni abstenciones. Atribuye las opiniones a quien las dice."
SEC_PROMPT = """Redactas una sección del acta de una reunión. Recibes sus puntos clave con marcas [mm:ss].
resumen: {n} que los sinteticen. {faithful} No digas que se acordó o decidió algo si la viñeta no lo dice. Escribe en {lang}."""
# Verificación de cada decisión/tarea candidata: una llamada corta por candidata con la cita y la transcripción de alrededor
# (el map ve 3k tokens y no distingue bien un acuerdo de hoy de un acta leída, un consejo de charla o una cortesía).
# Clasificar en vez de sí/no: un modelo pequeño dice «sí» a casi todo, pero elige bien la categoría.
VERIFY_PROMPT = """Revisas una decisión o tarea propuesta para el acta de una reunión. Recibes el tema, un extracto de la \
transcripción automática (con errores) alrededor del momento, con marcas [mm:ss], y la propuesta con su cita literal.
tipo: qué es de verdad la cita dentro del extracto:
acuerdo = la reunión decide o aprueba algo hoy («se aprueba», «estamos de acuerdo», votación con resultado); también \
aprobar hoy el acta de la sesión anterior, aplazar un punto a la próxima sesión y suspender o levantar la sesión;
encargo = alguien recibe el encargo o se compromete a hacer algo después de la reunión; también lo que manda hacer una \
resolución o informe que se vota hoy («disponer que la Secretaría notifique…»);
hecho = se cuenta algo que ya ocurrió antes de la reunión («se ha cursado», «se envió»); lo que se manda hacer no es hecho;
lectura = la cita es parte del acta de otra sesión u otro documento leído en voz alta que cuenta acuerdos de otro día \
(las líneas marcadas «(lectura en voz alta)»); aprobar hoy ese acta no es lectura, es acuerdo;
demostracion = pasos de una demostración, tutorial o ejemplo;
consejo = explicación, consejo o recomendación general de una charla o curso;
propuesta = sugerencia, opinión o hipótesis que nadie aprueba («deberíamos», «se podría», «queríamos sugerir»);
cortesia = saludo, agradecimiento, ofrecimiento («podéis contactarme») o algo sobre la propia llamada (micro, chat, cámara);
tramite = paso de procedimiento sin contenido (pasar lista, tomar votación, leer el orden del día)."""
TIPOS = ["acuerdo", "encargo", "hecho", "lectura", "demostracion", "consejo", "propuesta", "cortesia", "tramite"]
FINAL_PROMPT = """Redactas el acta de una reunión. Recibes, en orden cronológico, {src} con marcas [mm:ss], y las \
decisiones y tareas numeradas.
titulo: título del acta (máx. 10 palabras) según el contenido: tipo de reunión y tema principal.
{pick}resumen: resumen general de {tldr}: de qué trata (de principio a fin, no solo el comienzo), {what}. Las decisiones parecidas, juntas en una frase y sin \
inventar cuántas. Nada de saludos, agradecimientos ni despedidas.
{faithful} Escribe en {lang}."""


def chunk(segments):
    """Bloques del mismo tamaño, como mucho ~CHUNK_CHARS: n = ceil(total / CHUNK_CHARS) y se corta cada total / n. Ni
    bloque de cola diminuto (solo traería la despedida) ni uno gigante (la cola unida al anterior dejaba sin puntos los
    últimos 14 min de una reunión: el map da como mucho 10 por bloque)."""
    size = [len(x["text"]) + 9 for x in segments]
    n = max(1, -(-sum(size) // CHUNK_CHARS))
    out, acc = [[] for _ in range(n)], 0
    for s, z in zip(segments, size):
        out[min(n - 1, int(acc + z / 2) * n // sum(size))].append(s)
        acc += z
    return [c for c in out if c]


def merge_segs(segs, span=15):
    """Funde segmentos seguidos hasta `span` s: menos marcas [mm:ss] = menos tokens de entrada (hay reuniones con miles de
    segmentos de 2-3 palabras)."""
    out = []
    for s in segs:
        if out and s["s"] - out[-1]["s"] < span and s.get("spk") == out[-1].get("spk"):
            out[-1] = {**out[-1], "e": s["e"], "text": out[-1]["text"] + " " + s["text"]}
        else:
            out.append(s)
    return out


def map_input(segs, kfs, allsegs=()):
    """Texto del bloque para el map; los tramos en que se lee en voz alta lo que hay en pantalla van marcados (el 4B no
    distingue por sí solo el acta anterior leída de los acuerdos de hoy)."""
    t0, t1 = segs[0]["s"], segs[-1]["e"]
    rd = lambda s: allsegs and reading(s["s"] + 7, allsegs, kfs) >= 0.25
    text = "\n".join(f"[{fmt(s['s'])}] {who(s)}{'(lectura en voz alta) ' * bool(rd(s))}{s['text']}" for s in merge_segs(segs))
    screens = [f"[{fmt(k['t'])}] {k['text'][:600]}" for k in kfs if k["screen"] and t0 <= k["t"] <= t1]
    if screens:
        text += "\n\nTexto en pantalla compartida:\n" + "\n".join(screens)[:2500]
    return text


def find_quote(quote, segs, sw=None, near=None):
    """(fracción de pares de palabras de la cita que están en la transcripción, inicio del segmento donde empieza).
    Comprobación barata de que la decisión/tarea sale del fragmento; de paso da su marca exacta. Si la cita sale varias
    veces («se aprueba el presente informe»), la más cercana a `near` (la marca que propuso el modelo)."""
    q = words(quote)
    qb = set(zip(q, q[1:]))
    sw = sw or [words(s["text"]) for s in segs]
    best, key = (0, segs[0]["s"]), (0, 0)
    for i in range(len(segs) if qb else 0):
        w = sw[i] + [x for s in sw[i + 1:i + 8] for x in s][:len(q)]  # la cita puede cruzar segmentos cortos
        f = len(qb & set(zip(w, w[1:]))) / len(qb)
        k = (round(f, 2), -abs(segs[i]["s"] - near) if near is not None else i)  # empate: la última / la más cercana
        if f and k >= key:
            best, key = (f, segs[i]["s"]), k
    return best


def content_pairs(t):
    w = [x for x in words(t) if len(x) >= 4]
    return set(zip(w, w[1:]))


def reading(t, segs, kfs, win=45):
    """¿Se está leyendo en voz alta lo que hay en pantalla en el momento t? Fracción de pares de palabras con contenido
    (>= 4 letras) de la transcripción a ±win s que salen en el texto de las pantallas visibles entonces. Leer el acta
    anterior compartida da 0,3-0,6 sostenido; hablar sobre una diapositiva, <= 0,15."""
    said = content_pairs(" ".join(s["text"] for s in segs if t - win <= s["s"] <= t + win))
    shown = content_pairs(" ".join(k["text"] for k in kfs if k["t"] <= t + win and k.get("end", k["t"]) + STEP >= t - win))
    return len(said & shown) / len(said) if len(said) >= 20 else 0.0


READ_NOTE = "Lectura del documento en pantalla: "


def mark_reading(maps, segments, kfs):
    """Puntos dichos mientras se lee en voz alta lo que hay en pantalla (p. ej. el acta anterior): nota <= 2 (casi nunca
    entran en breve) y, si suenan a acuerdo, con READ_NOTE delante para que no pasen por acuerdos de hoy."""
    for m in maps:
        for p in m["puntos"]:
            if reading(parse_ts(p["t"]), segments, kfs) >= 0.25:
                p["importancia"] = min(p["importancia"], 2)
                if re.search(r"acuerd|acord|aprueb|aprob|design", p["texto"], re.I) and not p["texto"].startswith(READ_NOTE):
                    p["texto"] = READ_NOTE + p["texto"][:1].lower() + p["texto"][1:]
    return maps


COURTESY = re.compile(r"contact|alguna duda|cualquier (duda|consulta|pregunta)|no dud[eé]is|escr[ií]b(an|idme|irme)", re.I)
APPROVE = re.compile(r"\b(de acuerdo|aprob|aprueb|conform|unanimidad)", re.I)
COND = re.compile(r"\b(deber[ií]amos|habr[ií]a que|podr[ií]amos|se podr[ií]a|ser[ií]a (bueno|conveniente|importante)|"
                  r"propongo|sugiero|sugerir|quer[ií]amos|ojal[aá])\b", re.I)


def map_chunk(chat, segs, text, lang, kfs=()):
    """Map de un bloque. Decisiones/tareas sin su cita en la transcripción se descartan (inventadas); su marca pasa a la de
    la cita. Las que se leen de la pantalla, las condicionales y el resto de dudas las decide verify()."""
    m = chat(MAP_PROMPT.format(lang=lang), text, MAP_SCHEMA, MAP_MAX)
    t0, t1 = segs[0]["s"], segs[-1]["e"]
    for p in m["puntos"]:
        p["texto"] = sentences(p["texto"], PT_MAX)
        if not t0 - 5 <= parse_ts(p["t"]) <= t1 + 5:  # marca inventada fuera del bloque: al inicio del bloque
            p["t"] = fmt(t0)
    seen = set()  # el modelo a veces repite el mismo punto tal cual
    m["puntos"] = [p for p in m["puntos"] if not (k := " ".join(words(p["texto"]))) in seen and not seen.add(k)]
    sw = [words(s["text"]) for s in segs]
    for k in ("decisiones", "tareas"):
        keep = []
        for it in m[k]:
            own = parse_ts(it["t"])
            f, t = find_quote(it["cita"], segs, sw, own if t0 - 5 <= own <= t1 + 5 else None)
            if f < 0.5:
                print(f"  descartada (cita no está en el bloque): {it.get('texto') or it['tarea']}", flush=True)
            else:
                keep.append({**it, "t": fmt(t)})
        m[k] = keep
    return m


skel = lambda x: [w for w in x.split()[1:] if w[:1].islower()]  # esqueleto: sin nombres propios ni cifras
same = lambda a, b, r: len(skel(b)) >= 3 and SequenceMatcher(None, skel(a), skel(b), autojunk=False).ratio() >= r


def select_points(maps, keep, cap=None, floor=0, uniq=False):
    """Puntos [(t, texto, nota, bloque)] que entran en el acta: `keep` del total (y como mucho `cap`), por presupuesto y no
    por umbral: aunque el modelo puntúe todo 4-5, cada nivel muestra un contenido distinto. Cuotas por tiempo: los bloques
    (del mismo tamaño) se agrupan en g = min(k, bloques) tramos seguidos y cada tramo aporta k // g puntos, los mejores suyos
    (nota, orden en el bloque); el resto, y lo que un tramo no llene, por ranking global. Sin cuotas, con muchas notas 5 el
    desempate elegía los primeros bloques y breve perdía la segunda mitad. Las notas 1 (saludos, logística) nunca entran.
    Con `uniq` (breve) se salta el punto con el mismo esqueleto que uno ya elegido: en un pleno, 26 «se aprueba la
    recalificación de X» llenaban los 8 puntos clave y no quedaba sitio para el patrón de voto ni la suspensión."""
    allp = sorted((-p["importancia"], n, parse_ts(p["t"]), p["texto"], b) for b, m in enumerate(maps)
                  for n, p in enumerate(m["puntos"]) if p["importancia"] > 1)
    k = min(max(1, floor or 0, round(keep * len(allp))), cap or len(allp)) if allp else 0
    g = min(k, len(maps))
    pick = []

    def take(cands, n):
        for x in cands:
            if n <= 0:
                return
            if x not in pick and not (uniq and any(same(p[3], x[3], 0.75) for p in pick)):
                pick.append(x)
                n -= 1
    for j in range(g):
        take([x for x in allp if x[4] * g // len(maps) == j], k // g)
    take(allp, k - len(pick))
    return sorted((t, txt, -neg, b) for neg, _, t, txt, b in pick)


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


def said(value, ctx, task=""):
    """Responsable/plazo solo si lo dice la transcripción de alrededor (>= la mitad de sus palabras) y no sale en la propia
    tarea («pedir a la gerencia…»: es a quien va dirigida); si no, "—". El map inventaba «Secretaría Técnica»,
    «Audiencia», «El orador»."""
    if re.fullmatch(r"Hablante \d+", value):  # etiqueta de voz: solo si esa voz habla ahí
        return value if re.search(rf"\b{value}\b", ctx) else "—"
    st = {w for w in words(value) if len(w) >= 4}  # palabras enteras: con raíces, «consejeros» casaba con «consejo»
    return value if st and len(st & set(words(ctx))) >= 0.5 * len(st) and not st <= set(words(task)) else "—"


def verify(chat, maps, segments, kfs, win=45):
    """Decisiones y tareas deduplicadas que de verdad lo son. El map ve un bloque y confunde el acta anterior leída en voz
    alta, consejos de una charla, pasos de una demo o cortesías con acuerdos y encargos. Filtros baratos primero (cita
    condicional, tarea = responsable, lectura de la pantalla visible en ese momento) y después una llamada corta por
    candidata: cita + transcripción a ±win s, clasificada con una rúbrica (VERIFY_PROMPT); solo quedan acuerdo/encargo.
    Una sola vez por map (caché), así todos los niveles muestran las mismas."""
    out = {}
    for name, key, loose in (("decisiones", "texto", False), ("tareas", "tarea", True)):
        out[name] = []
        for it in dedupe([{**x, "b": b} for b, m in enumerate(maps) for x in m[name]], key, loose):
            t = parse_ts(it["t"])
            ctx = [s for s in segments if t - win <= s["s"] <= t + win]
            f = reading(t, segments, kfs, win)
            if f >= 0.25 and name == "decisiones":  # lo leído («el acta anterior queda aprobada») se suele votar justo después:
                kw = {w for w in words(it[key]) if len(w) >= 4}  # si a <= 5 min se aprueba algo con sus palabras, va ahí
                later = ([s for s in segments if t < s["s"] <= t + 300 and APPROVE.search(s["text"]) and  # la última:
                          kw & set(words(s["text"])) and reading(s["s"], segments, kfs, win) < 0.25] or [None])[-1]  # antes se anuncia
                if later:
                    t, f, it = later["s"], 0.0, {**it, "t": fmt(later["s"]), "cita": later["text"][:100]}
                    ctx = [s for s in segments if t - win <= s["s"] <= t + win]
            why = ("condicional" if COND.search(it["cita"]) and not re.search(r"aprob|aprueb|acord", it["cita"], re.I) else
                   "tarea = responsable" if name == "tareas" and set(words(it[key])) <= set(words(it["responsable"])) else
                   "cortesía" if name == "tareas" and COURTESY.search(it["cita"] + " " + it[key]) else
                   f"leída de la pantalla ({f:.2f})" if f >= 0.25 else "")
            if not why:
                text = (f"Tema: {maps[it['b']]['tema']}\n\nExtracto:\n" +
                        "\n".join(f"[{fmt(s['s'])}] {who(s)}{'(lectura en voz alta) ' * (reading(s['s'] + 7, segments, kfs) >= 0.25)}"
                                  f"{s['text']}" for s in merge_segs(ctx)) +
                        f"\n\nPropuesta ({name[:-1].replace('decisione', 'decisión')}): {it[key]}\nCita: «{it['cita']}»")
                tipo = chat(VERIFY_PROMPT, text, obj(tipo={"enum": TIPOS}), 30)["tipo"]
                why = "" if tipo in ("acuerdo", "encargo") else tipo
            if why:
                print(f"  descartada ({why}): {it[key]}", flush=True)
            else:
                ctext = " ".join(who(s) + s["text"] for s in ctx)
                out[name].append({**it, **({"responsable": said(it["responsable"], ctext, it[key]),
                                            "plazo": said(it["plazo"], ctext)} if name == "tareas" else {})})
    return out


def group(items, key):
    """Decisiones repetitivas en una (la primera, con n = cuántas): «se aprueba parcialmente la recalificación de X / de Y…»
    se distinguen solo por el nombre propio. Esqueleto = palabras en minúscula; iguales al 75 % (aceptar frente a negar
    queda en ~50 %) y >= 3 palabras."""
    out = []
    for it in items:
        for o in out:
            if same(o[key], it[key], 0.75):
                o["n"] += 1
                break
        else:
            out.append({**it, "n": 1})
    return out


def reduce_maps(chat, maps, valid, starts, level, lang):
    """Reduce jerárquico, nunca se pasa de contexto ni recorta: (1) una sección por bloque del map (título = su tema,
    viñetas = sus puntos elegidos) y el LLM solo redacta su resumen a partir de esas viñetas; (2) el título y el resumen
    global salen de los resúmenes de sección (breve: de los puntos elegidos). En los niveles con tope, las decisiones
    repetitivas se agrupan y, si aún hay más que el tope, el LLM elige las más importantes."""
    cfg = LEVELS[level]
    dec = group(valid["decisiones"], "texto") if cfg["dec"] else valid["decisiones"]
    tar = valid["tareas"]
    sel = select_points(maps, cfg["keep"], floor=cfg["pts"], uniq=not cfg["secs"])
    bullets = lambda pts: "\n".join(f"- [{fmt(t)}] {x}" for t, x, _, _ in pts)
    ask = lambda n, c: f"{n} (como mucho unos {c} caracteres)"
    secs = []
    for b, m in enumerate(maps if cfg["secs"] else []):
        pts = [p for p in sel if p[3] == b]
        if pts:
            n, c = cfg["sec"]
            res = sentences(chat(SEC_PROMPT.format(n=ask(n, c), faithful=FAITHFUL, lang=lang), bullets(pts),
                                 obj(resumen=S(c * 3 // 2)), 500, 1.1)["resumen"], c * 3 // 2) if len(pts) > 1 else pts[0][1]
            secs.append({"titulo": m["tema"], "t": starts[b], "b": b, "resumen": res})
    if secs:
        src, text = "los resúmenes de cada parte", "\n\n".join(f"[{fmt(s['t'])}] {s['titulo']}: {s['resumen']}" for s in secs)
    else:
        src = "los temas de cada parte y los puntos clave"  # los temas: que el resumen recorra toda la reunión
        text = "Partes:\n" + "\n".join(f"[{fmt(t)}] {m['tema']}" for t, m in zip(starts, maps)) + "\n\nPuntos clave:\n" + bullets(sel)
    fields, pick = {"titulo": S(80)}, ""
    for name, items, n, what, key in (("decisiones", dec, cfg["dec"], "decisiones", "texto"),
                                      ("tareas", tar, cfg["tar"], "tareas", "tarea")):
        if items:
            text += f"\n\n{what.capitalize()}:\n" + "\n".join(
                f"{i}. [{x['t']}] {x[key]}" + (f" (y {x['n'] - 1} más parecidas)" if x.get("n", 1) > 1 else "")
                for i, x in enumerate(items, 1))
        if n and len(items) > n:
            fields[name] = arr({"enum": list(range(1, len(items) + 1))}, n)
            pick += f"{name}: números de las {n} {what} más importantes.\n"
    c = cfg["tldr"][1]
    fields["resumen"] = S(c * 3 // 2)
    what = ("qué se decidió y qué queda pendiente" if dec or tar else
            "sin decir que se acordó, decidió o quedó pendiente nada: no hay decisiones ni tareas")
    red = chat(FINAL_PROMPT.format(src=src, tldr=ask(cfg["tldr"][0], c), pick=pick, what=what, faithful=FAITHFUL,
                                   lang=lang), text, obj(**fields), 1000, 1.1)
    top = lambda items, name: [items[i - 1] for i in sorted(set(red[name]))] if name in red else items
    return {"titulo": sentences(red["titulo"], 80).rstrip("."), "resumen": sentences(red["resumen"], c * 3 // 2),
            "secciones": secs, "decisiones": top(dec, "decisiones"), "tareas": top(tar, "tareas"),
            "mas": bool(cfg["dec"] and len(dec) > cfg["dec"] or cfg["tar"] and len(tar) > cfg["tar"])}


def pick_shots(kfs, sel, n):
    """Capturas relevantes: peso = suma de notas de los puntos elegidos cerca de la captura; las n de más peso (o todas)."""
    scr = [k for k in kfs if k["screen"]]
    if n is None:
        return scr
    w = lambda k: sum(p[2] for p in sel if k["t"] + SHOT_WIN[0] <= p[0] <= k["t"] + SHOT_WIN[1])
    ws = lambda k: set(words(k["text"]))
    # casi repetidas (la misma tabla de precios con otro detalle): como mucho una cada 3 min si comparten >= la mitad
    near = lambda a, b: abs(a["t"] - b["t"]) < 180 and len(ws(a) & ws(b)) >= 0.5 * min(len(ws(a)), len(ws(b)))
    out = []
    for k in sorted(scr, key=w, reverse=True):
        if len(out) < n and not any(near(k, o) for o in out):
            out.append(k)
    return sorted(out, key=lambda k: k["t"])


# ---------- Informe HTML ----------
CSS = """body{font:16px/1.5 system-ui,sans-serif;margin:0;color:#222;background:#fafafa}
main{display:grid;grid-template-columns:minmax(320px,44%) 1fr;gap:24px;padding:16px;max-width:1500px;margin:auto}
#side{position:sticky;top:16px;align-self:start}video{width:100%;background:#000;border-radius:6px}
@media(max-width:900px){main{grid-template-columns:1fr}#side{position:sticky;top:0;z-index:1;background:#fafafa}}
h1{font-size:1.4em;margin:.2em 0}h2{border-bottom:2px solid #ddd;padding-bottom:4px;margin-top:1.6em}
.spk{font-size:13px;color:#c2185b;margin-right:6px}a.ts{font:13px monospace;color:#06c;text-decoration:none;margin-right:6px;cursor:pointer}a.ts:hover{text-decoration:underline}
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


def render(out, title, dur, lang, red, maps, kfs, starts, segments, level, vext=".mp4", names=None):
    """Escribe index.html y devuelve las capturas que muestra (solo esas se copian a img/). names: {"2": "Luis"}."""
    cfg = LEVELS[level]
    at = [s["s"] for s in segments]
    spk = lambda t, x: (lambda k: f'<span class="spk">{k}</span>' if k and k not in x else "")(  # quien habla en t
        segments[max(0, bisect.bisect_right(at, t + 1) - 1)].get("spk"))
    sel = select_points(maps, cfg["keep"], cfg["pts"], cfg["pts"], not cfg["secs"])
    shots = pick_shots(kfs, sel, cfg["shots"])
    esc = html.escape
    li = lambda t, x: f"<li>{ts_link(t)}{spk(t, x)}{esc(x)}</li>"
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
    dec = "".join(li(parse_ts(d["t"]), d["texto"] + (f" (y {d['n'] - 1} más parecidas)" if d.get("n", 1) > 1 else ""))
                  for d in sorted(red["decisiones"], key=lambda d: parse_ts(d["t"])))
    tasks = "".join(f"<tr><td>{ts_link(parse_ts(t['t']))}{esc(t['tarea'])}</td><td>{esc(t['responsable'])}</td>"
                    f"<td>{esc(t['plazo'])}</td></tr>" for t in sorted(red["tareas"], key=lambda t: parse_ts(t["t"])))
    if cfg["secs"]:
        desarrollo = f"<h2>Desarrollo</h2>{''.join(body)}"
    else:  # breve: unos pocos puntos clave con marca y las capturas más relevantes
        desarrollo = (f"<h2>Puntos clave</h2><ul>{''.join(li(t, x) for t, x, _, _ in sel)}</ul>"
                      + (f"<h2>Capturas</h2>{''.join(fig(k) for k in shots)}" if shots else ""))
    trans = "".join(f"<p>{ts_link(s['s'])}{f'<b>{w}:</b> ' if (w := s.get('spk')) and (not i or w != segments[i - 1].get('spk')) else ''}"
                    f"{esc(s['text'])}</p>" for i, s in enumerate(segments))
    page = f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Acta — {esc(title)}</title><style>{CSS}</style></head>
<body><main><div id="side"><video id="v" src="video{vext}" controls preload="metadata"></video>
<p id="pick" hidden>No se encuentra el vídeo junto al informe. Ábrelo: <input type="file" accept="video/*"></p></div>
<div><h1>Acta: {esc(title)}</h1><p class="meta">Duración {fmt(dur)} · idioma {esc(LANG.get(lang, lang).split()[0])} · nivel {level} ·
generado {time.strftime('%Y-%m-%d %H:%M')}</p>
<h2>Resumen</h2><div class="tldr">{esc(red['resumen'])}</div>
<h2>Decisiones</h2><ul>{dec or "<li>—</li>"}</ul>
<h2>Tareas</h2><table><tr><th>Tarea</th><th>Responsable</th><th>Plazo</th></tr>{tasks or "<tr><td colspan=3>—</td></tr>"}</table>
{more}
{desarrollo}
<h2>Transcripción</h2><details><summary>Mostrar transcripción completa</summary>{trans}</details>
</div></main><script>{JS}</script></body></html>"""
    (out / "index.html").write_text(rename(page, names), encoding="utf-8")
    (out / "acta.json").write_text(rename(json.dumps({  # lo mismo que index.html, legible por máquina (eval/score.py)
        "titulo": title, "duracion": round(dur), "nivel": level, "resumen": red["resumen"],
        "puntos": [{"t": t, "texto": x} for t, x, _, b in sel if not secs or any(b == s["b"] for s in secs)],
        "secciones": [{"t": s["t"], "titulo": s["titulo"], "resumen": s["resumen"]} for s in secs],
        "decisiones": [{**d, "t": parse_ts(d["t"])} for d in red["decisiones"]],
        "tareas": [{**t, "t": parse_ts(t["t"])} for t in red["tareas"]],
        "capturas": [{"t": k["t"], "img": k["img"], "titulo": k["title"]} for k in shots]}, ensure_ascii=False, indent=1),
        names), encoding="utf-8")
    return shots


def put_file(src, dst):
    """Enlace duro, si no simbólico, si no copia (Windows: entre unidades no hay enlace duro y el simbólico pide permisos).
    Nunca simbólico a un temporal (la subida de Gradio vive en /tmp: tras reiniciar, el acta perdía el vídeo)."""
    tmp = Path(src).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
    for put in (os.link, shutil.copy) if tmp else (os.link, os.symlink, shutil.copy):
        with contextlib.suppress(OSError):
            put(src, dst)
            return


# ---------- Vídeo condensado ----------
SIL_GAP, MERGE_GAP, MIN_KEEP, FADE = 1.5, 2.0, 3.0, 0.05  # s


def seg_importance(segments, maps, valid):
    """Nota de cada segmento: la más alta de los puntos del map que caen en él o empiezan hasta 45 s antes (un punto resume
    lo que se dice a partir de su marca) y 5 en decisiones y tareas; 1 (relleno) si no hay ninguno."""
    pts = [(parse_ts(p["t"]), p["importancia"]) for m in maps for p in m["puntos"]] + [
        (parse_ts(x["t"]), 5) for k in ("decisiones", "tareas") for x in valid[k]]
    return [max([n for t, n in pts if s["s"] - 45 <= t <= s["e"]], default=1) for s in segments]


def timeline(segs, dur, gap=SIL_GAP, pad=0.25):
    """Partición de [0, dur] en tramos [a, b, nota]: cada segmento (s, e, nota) con los silencios cortos pegados y los
    silencios de más de `gap` s como tramos de nota 0 (con `pad` s de margen a cada lado para no cortar sílabas)."""
    out, last = [], 0.0  # last = fin de la voz anterior
    for s, e, n in [*segs, (dur, dur, None)]:
        if s - last > gap:
            if out:
                out[-1][1] = last + pad
            out.append([out[-1][1] if out else 0.0, s - pad if n is not None else dur, 0])
        elif out:
            out[-1][1] = max(s, out[-1][0])
        if n is not None:
            out.append([out[-1][1] if out else 0.0, e, n])
            last = max(last, e)
    return out


def runs(flags, val):
    return [[i for i, _ in g] for v, g in groupby(enumerate(flags), lambda x: x[1]) if v == val]


def condense_plan(units, pct):
    """Tramos (a, b) que se conservan para quitar ~pct % del vídeo: primero los silencios largos (los más largos antes) y
    después los segmentos de menos nota. Cortes en bordes de segmento; un corte con voz de menos de MERGE_GAP s no compensa
    el salto (se conserva) y lo conservado de menos de MIN_KEEP s se quita. Búsqueda binaria del nº de tramos quitados."""
    total = units[-1][1]
    span = lambda r: units[r[-1]][1] - units[r[0]][0]
    order = sorted(range(len(units)), key=lambda i: (units[i][2], units[i][0] - units[i][1]))

    def keeps(k):
        cut = [False] * len(units)
        for i in order[:k]:
            cut[i] = True
        for r in runs(cut, True):
            if span(r) < MERGE_GAP and any(units[i][2] for i in r):
                for i in r:
                    cut[i] = False
        for r in runs(cut, False):
            if span(r) < MIN_KEEP:
                for i in r:
                    cut[i] = True
        return [(units[r[0]][0], units[r[-1]][1]) for r in runs(cut, False)]
    lo, hi = 0, len(units)
    while lo < hi:
        mid = (lo + hi) // 2
        lo, hi = (lo, mid) if 1 - sum(b - a for a, b in keeps(mid)) / total >= pct / 100 else (mid + 1, hi)
    return keeps(lo)


def recommend_pct(units):
    """% a quitar recomendado: silencios largos + voz de nota <= 2, entre 20 y 70."""
    return int(min(70, max(20, round(100 * sum(b - a for a, b, n in units if n <= 2) / units[-1][1]))))


@functools.cache
def h264(threads):
    """QuickSync (h264_qsv, el ProBook lo tiene) si funciona de verdad; si no, libx264."""
    qsv = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=256x256:d=0.2", "-c:v", "h264_qsv",
                          "-f", "null", "-"], capture_output=True).returncode == 0
    return (["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "26"] if qsv else
            ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-threads", str(threads)])


def condense(wd, quality, pct, threads=PHYS, cb=lambda f, m: None):
    """work/<hash>/condensado_<pct>.mp4 a partir de los tramos que guardó run(); pct = 0 usa el recomendado. Una pasada de
    ffmpeg: trim/atrim por tramo (con fundido corto de audio en cada corte) + concat, en un guion de filtros (-/filter_complex:
    sin límite de largo de la línea de órdenes de Windows)."""
    wd = Path(wd)
    units = json.loads((wd / f"cortes_{quality}.json").read_text())
    pct = pct or recommend_pct(units)
    keeps = condense_plan(units, pct)
    if not keeps:
        raise RuntimeError("No queda nada que conservar: baja el porcentaje")
    video, out = next(wd.glob("video.*")), wd / f"condensado_{pct}.mp4"
    graph = "".join(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}];"
                    f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS,"
                    f"afade=d={FADE},afade=t=out:st={b - a - FADE:.3f}:d={FADE}[a{i}];" for i, (a, b) in enumerate(keeps))
    graph += "".join(f"[v{i}][a{i}]" for i in range(len(keeps))) + f"concat=n={len(keeps)}:v=1:a=1[v][a]"
    script = wd / "condensado.ffgraph"
    script.write_text(graph)
    kept = sum(b - a for a, b in keeps)
    t0 = time.time()
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-/filter_complex", str(script), "-map", "[v]",
                          "-map", "[a]", *h264(threads), "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
                          "-progress", "pipe:1", "-nostats", str(out)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in p.stdout:
        if line.startswith("out_time_us=") and line[12:].strip().isdigit():
            cb(min(int(line[12:]) / 1e6 / kept, 1), f"Codificando vídeo condensado… {fmt(int(line[12:]) / 1e6)} / {fmt(kept)}")
    if p.wait():
        raise RuntimeError("ffmpeg: " + p.stderr.read()[-500:])
    return out, pct, {"tramos": len(keeps), "dur": round(units[-1][1]), "queda": round(kept), "s": round(time.time() - t0, 1)}


# ---------- Orquestación ----------
def run(video, level="normal", quality="rápido", threads=PHYS, cb=lambda f, m: None, names=None, speakers=False):
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

    dh = hashlib.sha1(repr((DIAR_EMB, DIAR_PIECE, DIAR_MIN)).encode()).hexdigest()[:8]
    sf = wd / f"hablantes_{dh}.json"
    if speakers and not sf.exists():  # opcional: con voces parecidas o mal audio se equivoca a menudo
        t0 = time.time()
        sf.write_text(json.dumps(diarize(video, tr["segments"], threads, lambda f, m: cb(0.45 + 0.05 * f, m))))
        stage("hablantes", t0)
    for s, k in zip(tr["segments"], assign_speakers(tr["segments"], speaker_turns(**json.loads(sf.read_text()))) if speakers
                    else []):
        if k:
            s["spk"] = k

    kf = wd / "frames.json"  # OCR crudo; screens() lo clasifica y deduplica en cada ejecución
    if not kf.exists():
        t0 = time.time()
        kf.write_text(json.dumps(keyframes(video, wd, threads, dur, lambda f, m: cb(0.5 + 0.1 * f, m)), ensure_ascii=False))
        stage("capturas+ocr", t0)
    kfs = screens(json.loads(kf.read_text()), {w for s in tr["segments"] for w in words(s["text"])})

    chunks = chunk(tr["segments"])
    starts = [c[0]["s"] for c in chunks]
    inputs = [map_input(c, kfs, tr["segments"]) for c in chunks]
    # la caché lleva el hash de prompt + esquema + modelo + entrada (transcripción y OCR): cambiar cualquiera la invalida
    mh = hashlib.sha1("\0".join([MAP_PROMPT, json.dumps(MAP_SCHEMA), str(llm_model()), *inputs]).encode()).hexdigest()[:8]
    vh = hashlib.sha1((mh + VERIFY_PROMPT + COND.pattern + APPROVE.pattern + COURTESY.pattern).encode()).hexdigest()[:8]
    rh = hashlib.sha1((vh + SEC_PROMPT + FINAL_PROMPT + FAITHFUL + READ_NOTE + json.dumps(LEVELS[level])).encode()).hexdigest()[:8]
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
            maps = mark_reading(maps, tr["segments"], kfs)  # tras guardar la caché: es barato y así se puede ajustar
            if not vf.exists():
                vf.write_text(json.dumps(verify(chat, maps, tr["segments"], kfs), ensure_ascii=False))
            valid = json.loads(vf.read_text())
            rf.write_text(json.dumps(reduce_maps(chat, maps, valid, starts, level, lang), ensure_ascii=False))
            stage("reduce", t0)
    red = json.loads(rf.read_text())
    maps = mark_reading(maps, tr["segments"], kfs)
    imp = seg_importance(tr["segments"], maps, json.loads(vf.read_text()))  # para el vídeo condensado
    (wd / f"cortes_{quality}.json").write_text(json.dumps(timeline([(s["s"], s["e"], n) for s, n in zip(tr["segments"], imp)], dur)))
    print(score_hist(maps), flush=True)

    out = wd / f"acta_{level}_{quality}"
    shutil.rmtree(out, ignore_errors=True)
    (out / "img").mkdir(parents=True)
    for k in render(out, red.get("titulo") or video.stem, dur, tr["language"], red, maps, kfs, starts, tr["segments"], level, video.suffix,
                    names):
        shutil.copy(wd / "frames" / k["img"], out / "img" / k["img"])
    zpath = wd / f"acta_{video.stem}_{level}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:  # sin el vídeo: el informe pide abrirlo
        for f in out.rglob("*"):
            z.write(f, f.relative_to(out))
    # vídeo junto al informe para el reproductor: como mucho una copia por vídeo (en wd), y de ahí enlace a cada nivel
    src = wd / f"video{video.suffix}"
    if src.is_symlink() and not src.exists():  # enlace roto (temporal ya borrado): se rehace
        src.unlink()
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

    for n, want in ((30, [10, 10, 10]), (23, [8, 7, 8]), (3, [3])):  # mismo tamaño, sin cola ni bloque gigante
        segs = [{"s": i, "e": i + 1, "text": "x" * 991} for i in range(n)]
        ch = chunk(segs)
        assert [len(c) for c in ch] == want and [x for c in ch for x in c] == segs, [len(c) for c in ch]  # nada se pierde
    pts = lambda *n: {"puntos": [{"importancia": i, "t": "00:0%d" % k, "texto": "p"} for k, i in enumerate(n)]}
    maps = [pts(5, 5, 4, 4), pts(5, 4, 4, 4, 4, 4, 1, 1)]  # todo 4-5: el presupuesto igualmente separa niveles
    n = [len(select_points(maps, LEVELS[lv]["keep"])) for lv in LEVELS]
    assert n == [2, 5, 10], n
    assert [x[2] for x in select_points(maps, 0.3)] == [5, 5, 5], "primero las notas altas"
    assert len(select_points(maps, 1.0, 4)) == 4 and min(x[2] for x in select_points(maps, 1.0)) == 4, "1 = relleno, fuera"
    many = [pts(5, 5, 5, 3)] * 14  # 42 notas 5: breve reparte por tiempo, no se queda con los 8 primeros bloques
    assert sorted({x[3] for x in select_points(many, 0.2, 8)}) == [0, 2, 4, 6, 7, 9, 11, 13]
    rep = [{"puntos": [{"importancia": 5, "t": "00:01", "texto": f"Se aprueba la recalificación de {x}"} for x in
                        ("Ana Ruiz", "Luis Mera")] + [{"importancia": 3, "t": "00:02", "texto": "Se suspende la sesión hasta mañana"}]}]
    assert [x[1][:5] for x in select_points(rep, 1.0, 2, uniq=True)] == ["Se ap", "Se su"], "breve: sin repetidos"

    sg = [{"s": 0, "text": "Hola a todos."}, {"s": 10, "text": "Bueno, pues se aprueba el"},
          {"s": 14, "text": "acta por unanimidad"}, {"s": 20, "text": "de los presentes."}]
    assert find_quote("se aprueba el acta por unanimidad", sg) == (1.0, 10)
    assert find_quote("se acordó contratar a dos personas", sg)[0] < 0.5
    dd = lambda c: {"cita": c, "texto": c, "t": "00:00"}
    fake = lambda *a: {"tema": "", "puntos": [], "tareas": [], "decisiones": [
        dd("se aprueba el acta por unanimidad"), dd("contratar a dos personas"), dd("hola a todos"),
        {**dd("se aprueba el acta por unanimidad"), "t": "00:20"}]}
    m = map_chunk(fake, [{**s, "e": s["s"] + 4} for s in sg], "", "español")
    assert [d["t"] for d in m["decisiones"]] == ["00:10", "00:00", "00:10"], m  # inventada fuera; marca = la de la cita
    assert find_quote("se aprueba el presente informe", [{"s": t, "text": "se aprueba el presente informe"}
                                                         for t in (100, 200, 300)], near=210) == (1.0, 200)
    # lectura de la pantalla: leer en voz alta el texto visible entonces sí; lo mismo con otra pantalla, no
    doc = ("Acuerdos del consejo regional: comunicar a las instituciones integrantes que asistirán titular y alterno; "
           "solicitar inspecciones sobre emanación de fuertes olores siempre que previamente existan resultados médicos")
    rd = [{"s": t, "text": doc} for t in range(0, 90, 10)]
    assert reading(40, rd, [{"t": 0, "end": 90, "text": doc}]) > 0.9
    assert reading(40, rd, [{"t": 200, "end": 300, "text": doc}]) == 0
    mk = mark_reading([{"puntos": [{"t": "00:40", "importancia": 5, "texto": "Se acuerda comunicar a las instituciones"},
                                   {"t": "05:00", "importancia": 5, "texto": "Se acuerda otra cosa"}]}],
                      rd, [{"t": 0, "end": 90, "text": doc}])[0]["puntos"]
    assert [(p["importancia"], p["texto"][:21]) for p in mk] == [(2, READ_NOTE[:21]), (5, "Se acuerda otra cosa")], mk
    # verify: condicional, tarea = responsable y leída de la pantalla sin llamar al LLM; el resto lo clasifica el LLM;
    # responsable solo si lo dice la transcripción
    seg = [{"s": 0, "e": 9, "text": "Bien, se aprueba el acta. María Gómez enviará el informe el lunes."},
           {"s": 100, "e": 109, "text": "Deberíamos invitar a la zona naval. No veo el chat."}]
    tsk = lambda c, x, r, t: {"cita": c, "tarea": x, "responsable": r, "plazo": "—", "t": t}
    mp = [{"tema": "a", "puntos": [], "decisiones": [{"cita": "se aprueba el acta", "texto": "Se aprueba el acta", "t": "00:00"},
                                                     {"cita": "deberíamos invitar a la zona naval", "texto": "Invitar a la zona naval", "t": "01:40"}],
           "tareas": [tsk("María Gómez enviará el informe", "Enviar el informe", "María Gómez", "00:00"),
                      tsk("enviará el informe el lunes", "Preparar el presupuesto anual", "Secretaría Técnica", "00:00"),
                      tsk("No veo el chat", "David López", "David López", "01:40"),
                      tsk("invitar a la zona naval", "Contactar al ponente si hay dudas", "—", "01:40")]}]
    calls = []
    v = verify(lambda sy, u, *a: calls.append(u) or {"tipo": "acuerdo" if "Se aprueba" in u else "encargo"}, mp, seg, [])
    assert [d["texto"] for d in v["decisiones"]] == ["Se aprueba el acta"] and len(calls) == 3, (v, calls)
    assert [(t["tarea"], t["responsable"]) for t in v["tareas"]] == [("Enviar el informe", "María Gómez"),
                                                                 ("Preparar el presupuesto anual", "—")], v
    dc = lambda t, x: {"t": t, "texto": x}
    rdoc = [{"s": t, "e": t + 9, "text": doc} for t in range(0, 90, 10)] + [
        {"s": 200, "e": 209, "text": "¿Estamos de acuerdo con el acta? Sí, de acuerdo, queda aprobada."}]
    mp2 = [{"tema": "a", "puntos": [], "tareas": [], "decisiones": [
        {"cita": "comunicar a las instituciones integrantes", "texto": "Comunicar a las instituciones", "t": "00:40"},
        {"cita": "solicitar inspecciones", "texto": "Se aprueba el acta anterior con correcciones", "t": "00:40"}]}]
    v2 = verify(lambda *a: {"tipo": "acuerdo"}, mp2, rdoc, [{"t": 0, "end": 90, "text": doc}])
    assert [(d["texto"][:15], d["t"]) for d in v2["decisiones"]] == [("Se aprueba el a", "03:20")], v2  # leída: fuera / re-anclada
    rp = [dc("10:00", f"Se aprueba parcialmente la recalificación de {x}") for x in ("Ana Ruiz", "Luis Mera", "Eva Paz")]
    assert [x["n"] for x in group(rp + [dc("99:00", "Se suspende la sesión hasta mañana")], "texto")] == [3, 1]
    r = reduce_maps(lambda *a: {"resumen": "r", "titulo": "Pleno"}, mp, v, [0], "normal", "español")
    assert r["decisiones"][0]["texto"] == "Se aprueba el acta" and r["titulo"] == "Pleno" and not r["mas"], r
    assert sentences("Uno dos tres. Cuatro cin", 24) == "Uno dos tres." and sentences("a" * 5 + " bb cc", 11) == "aaaaa bb…"
    assert sentences("Frase corta sin punto", 100) == "Frase corta sin punto"
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
    assert '("," sp ("1")){1,4}) sp "]"' in gbnf(obj(p=arr({"enum": [1]}, 5, 2))), "minItems sin ? final"
    assert '("\\"si\\"" | "\\"no\\"")' in gbnf(obj(x={"enum": ["si", "no"]})), "enum de cadenas con comillas JSON"
    assert 's9 ::= "\\"" ch{0,9} "\\""' in g and "¡-ſ" in g and "u\" [0-9" not in g, g  # sin CJK ni \\uXXXX
    with tempfile.TemporaryDirectory() as d:  # el vídeo subido a un temporal se enlaza duro o se copia, nunca simbólico
        (Path(d) / "a.mp4").write_bytes(b"v")
        put_file(Path(d) / "a.mp4", Path(d) / "b.mp4")
        assert not (Path(d) / "b.mp4").is_symlink() and (Path(d) / "b.mp4").read_bytes() == b"v"

    # quién habla: el turno con más solape, numerados por orden de aparición; sin solape, nadie; una sola voz, nadie
    sg = [{"s": 1, "e": 9}, {"s": 8, "e": 15}, {"s": 16, "e": 19}, {"s": 30, "e": 31}]
    assert assign_speakers(sg, [(0, 10, 5), (10, 20, 3)]) == ["Hablante 1", "Hablante 2", "Hablante 2", None]
    u, v = [1.0, 0.0], [0.0, 1.0]  # dos voces, una con 5 trozos y la otra con 5, más un trozo suelto cercano a la segunda
    st = speaker_turns([(i, i + 1, i) for i in range(11)], [u] * 5 + [v] * 5 + [[0.1, 0.99]])
    assert [x[2] for x in st] == [st[0][2]] * 5 + [st[5][2]] * 6 and st[0][2] != st[5][2], st
    w = [0.99, 0.1]  # casi la misma voz que u: se funde aunque el clustering la separe
    assert len({x[2] for x in speaker_turns([(i, i + 1, i) for i in range(10)], [u] * 5 + [w] * 5, thr=0.001)}) == 1
    assert assign_speakers(sg, [(0, 20, 0)]) == [None] * 4 and assign_speakers(sg, []) == [None] * 4
    assert said("Hablante 2", "Hablante 2: me encargo yo") == "Hablante 2" and said("Hablante 3", "Hablante 2: yo") == "—"
    assert rename("Hablante 1 y el hablante 12 con Hablante 3", {"1": "Ana", "12": "Luis"}) == "Ana y el Luis con Hablante 3"
    assert merge_segs([{"s": 0, "e": 2, "text": "a", "spk": "Hablante 1"}, {"s": 3, "e": 4, "text": "b", "spk": "Hablante 2"}])[1]["text"] == "b"

    # vídeo condensado: partición sin huecos, silencios largos primero, % pedido ±3, reglas de unión y de mínimo
    segs, t = [], 0.0
    for i in range(600):
        t += rng.choice([0.2, 0.8, 1.2, 2.5, 6.0], p=[.4, .3, .1, .1, .1])  # pausas cortas y alguna larga
        d = float(rng.uniform(1, 9))
        segs.append((t, t + d, int(rng.choice([1, 2, 3, 4, 5], p=[.3, .3, .2, .1, .1]))))
        t += d
    u = timeline(segs, t + 4)
    assert u[0][0] == 0 and u[-1][1] == t + 4 and all(x[1] == y[0] for x, y in zip(u, u[1:])) and all(x[0] < x[1] for x in u)
    sil = sum(b - a for a, b, n in u if n == 0) / u[-1][1]
    assert all(b - a > SIL_GAP - 0.5 for a, b, n in u if n == 0) and 0.05 < sil < 0.3, sil
    edges = {x[0] for x in u} | {u[-1][1]}
    for pct in (25, 40, 55, 70):
        ks = condense_plan(u, pct)
        got = 100 * (1 - sum(b - a for a, b in ks) / u[-1][1])
        assert abs(got - pct) <= 3, (pct, got)
        assert all(a in edges and b in edges for a, b in ks) and all(b - a >= MIN_KEEP for a, b in ks), "cortes en bordes"
        for (_, b), (a, _) in zip(ks, ks[1:]):  # lo quitado con voz dura al menos MERGE_GAP
            assert a - b >= MERGE_GAP or all(n == 0 for x, y, n in u if b <= x < a), (b, a)
    ks = condense_plan(u, 100 * sil / 2)  # menos que los silencios: solo se quitan silencios
    gone = lambda i: not any(a <= u[i][0] < b for a, b in ks)  # solo cae voz suelta de < MIN_KEEP entre silencios quitados
    assert all(u[r[-1]][1] - u[r[0]][0] < MIN_KEEP for r in runs([n == 0 for *_, n in u], False) if any(map(gone, r))), "silencios primero"
    assert recommend_pct([[0, 10, 0], [10, 100, 4]]) == 20 and recommend_pct([[0, 90, 2], [90, 100, 5]]) == 70
    assert recommend_pct([[0, 20, 0], [20, 40, 1], [40, 100, 3]]) == 40
    print("ok")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Genera el acta de una reunión grabada")
    ap.add_argument("video", nargs="?")
    ap.add_argument("--nivel", default="normal", choices=LEVELS)
    ap.add_argument("--asr", default="rápido", choices=ASR_MODELS)
    ap.add_argument("--threads", type=int, default=PHYS)
    ap.add_argument("--hablantes", action="store_true", help="separar quién habla (experimental)")
    ap.add_argument("--condensar", type=int, metavar="PCT", help="además, vídeo condensado quitando PCT %% (0 = el recomendado)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest or not a.video:
        sys.exit(_selftest())
    last = [0.0]

    def cb(f, m):
        if time.time() - last[0] > 5 or f >= 1:
            last[0] = time.time()
            print(f"{f:5.0%} {m}", flush=True)
    out, z, t = run(a.video, a.nivel, a.asr, a.threads, cb, speakers=a.hablantes)
    print(out / "index.html", z, json.dumps(t), sep="\n")
    if a.condensar is not None:
        v, pct, st = condense(out.parent, a.asr, a.condensar, a.threads, cb)
        print(v, f"quitado {pct} %", json.dumps(st), sep="\n")
