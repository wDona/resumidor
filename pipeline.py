"""Vídeo de reunión -> acta HTML (resumen + capturas + marcas de tiempo). Todo local, CPU."""
import contextlib, hashlib, html, json, os, re, shutil, socket, subprocess, sys, time, urllib.request, zipfile
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "work"
STEP = 3                      # s entre muestras de vídeo
THUMB_W, THUMB_H = 128, 72    # miniatura en gris para detectar cambios
CUT = 0.03                    # fracción de píxeles cambiados que cuenta como "cambio de pantalla"
MIN_CHARS = 80                # letras OCR para considerar un frame "pantalla compartida"
CHUNK_CHARS = 10000           # ~3k tokens de transcripción por bloque del map
ASR_MODELS = {"rápido": "small", "calidad": "large-v3-turbo"}
LEVELS = {
    "breve": dict(min_imp=5, tldr="2-3 frases", sec="1 frase"),
    "normal": dict(min_imp=4, tldr="4-6 frases", sec="2-3 frases"),
    "detallado": dict(min_imp=1, tldr="un párrafo de 6-10 frases", sec="3-5 frases"),
}
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
def transcribe(video, quality, threads, dur, cb):
    from faster_whisper import WhisperModel
    name = ASR_MODELS[quality]
    cb(0, f"Cargando modelo de voz ({name})…")
    model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=threads)
    # audio vía ffmpeg (PyAV 19 rompe el decode_audio de faster-whisper 1.2.1)
    # ponytail: todo el audio en RAM (~230 MB/h, float32 16 kHz, igual que faster-whisper); trocear si 8 GB no llegan
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    segs, info = model.transcribe(np.frombuffer(pcm, np.float32), vad_filter=True, beam_size=1 if name == "small" else 5,
                                  condition_on_previous_text=False)
    out = []
    for s in segs:
        out.append({"s": round(s.start, 1), "e": round(s.end, 1), "text": s.text.strip()})
        cb(min(s.end / dur, 1), f"Transcribiendo… {fmt(s.end)} / {fmt(dur)}")
    return {"language": info.language, "segments": out}


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


def stable_segments(thumbs, cut=CUT, min_len=2):
    """[(inicio, fin)] en índices de muestra: tramos estables (>= min_len muestras) sin repetir pantallas ya vistas.
    Se compara con el inicio del tramo (no con el frame anterior) para que un cambio gradual también corte."""
    # dHash probado y descartado: en imágenes planas (diapositiva blanca vs. mosaico oscuro) apenas cambia.
    diff = lambda i, j: (np.abs(thumbs[i] - thumbs[j]) > 32).mean()
    segs, start = [], 0
    for i in range(1, len(thumbs) + 1):
        if i == len(thumbs) or diff(i, start) > cut:
            if i - start >= min_len and all(diff(i - 1, e) > cut for _, e in segs):
                segs.append((start, i - 1))
            start = i
    return segs


def keyframes(video, wd, threads, dur, cb):
    from rapidocr_onnxruntime import RapidOCR
    segs = stable_segments(sample_thumbs(video, threads, dur, lambda f, m: cb(f * 0.5, m)))
    (wd / "frames").mkdir(exist_ok=True)
    ocr = RapidOCR(intra_op_num_threads=threads, inter_op_num_threads=1)
    out = []
    for n, (a, b) in enumerate(segs):
        cb(0.5 + 0.5 * n / len(segs), f"Leyendo texto de capturas… {n + 1}/{len(segs)}")
        img = wd / "frames" / f"k{b * STEP:06d}.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(b * STEP), "-i", str(video), "-frames:v", "1",
                        "-vf", "scale='min(1280,iw)':-2", "-q:v", "3", str(img)], check=True)
        res, _ = ocr(str(img))
        lines = [t for _, t, sc in (res or []) if float(sc) > 0.6]
        # letras, no palabras: el modelo OCR (chino+inglés) a menudo pega las palabras latinas sin espacios
        chars = sum(c.isalnum() for t in lines for c in t)
        out.append({"t": a * STEP, "img": img.name, "screen": chars >= MIN_CHARS, "text": " | ".join(lines)})
    # pantallas que solo añaden texto (viñetas que van apareciendo): quedarse con la más completa
    scr = [k for k in out if k["screen"]]
    for k, nxt in zip(scr, scr[1:]):
        a, b = k["text"].lower(), nxt["text"].lower()
        if sum(m.size for m in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()) >= 0.85 * len(a):
            nxt["t"], k["screen"] = k["t"], False
    return out


# ---------- LLM (llama-server) ----------
@contextlib.contextmanager
def llama(threads, ctx=8192):
    exe = next((p for p in ROOT.glob("bin/**/llama-server*") if p.is_file()), None)
    model = next(iter(sorted(ROOT.glob("models/*.gguf"))), None)
    if not exe or not model:
        raise RuntimeError("Falta bin/**/llama-server o models/*.gguf (ver README)")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    log = open(WORK / "llama-server.log", "w")
    proc = subprocess.Popen([str(exe), "-m", str(model), "-c", str(ctx), "-t", str(threads), "-np", "1",
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
                    "temperature": 0.2, "max_tokens": max_tokens,
                    "response_format": {"type": "json_schema", "json_schema": {"name": "r", "schema": schema}}}
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
MAP_SCHEMA = obj(tema=STR, puntos=arr(obj(texto=STR, importancia={"enum": [1, 2, 3, 4, 5]}, t=TS), 15),
                 decisiones=arr(obj(texto=STR, t=TS), 8), tareas=arr(TASK, 8))
REDUCE_SCHEMA = obj(resumen=STR, secciones=arr(obj(titulo=STR, t=TS, resumen=STR), 15),
                    decisiones=arr(obj(texto=STR, t=TS), 20), tareas=arr(TASK, 20))

MAP_PROMPT = """Eres un asistente que redacta actas de reuniones. Recibes un fragmento de la transcripción automática \
(puede tener errores) con marcas [mm:ss] y, a veces, texto leído de la pantalla compartida.
Extrae los puntos del fragmento, también los secundarios. Cada punto: una frase concisa y autocontenida (máx. 30 palabras); \
t = marca [mm:ss] de la línea donde empieza; importancia: 5 = decisión, compromiso o dato crítico; 4 = información importante; \
3 = información útil; 2 = detalle secundario; 1 = charla, saludos, logística. Usa toda la escala: pocos puntos merecen un 5.
Lista también las decisiones tomadas y las tareas asignadas (tarea = qué hay que hacer, sin repetir responsable ni plazo; si no se mencionan, "—").
Usa solo lo que aparece en el texto, no inventes. Escribe en {lang}."""

REDUCE_PROMPT = """Eres un asistente que redacta actas de reuniones. Recibes los puntos clave extraídos de cada bloque \
de una reunión, en orden cronológico, con marcas [mm:ss].
Redacta el acta final:
- resumen: resumen general de {tldr}.
- secciones: agrupa por tema en orden cronológico; t = marca del primer punto de la sección; resumen de {sec}.
- decisiones y tareas: fusiona duplicados, conserva la marca t más temprana; en tareas no repitas responsable ni plazo en el texto.
Usa solo la información recibida, no inventes. Escribe en {lang}."""


def chunk(segments):
    out, cur = [], []
    for s in segments:
        cur.append(s)
        if sum(len(x["text"]) + 9 for x in cur) > CHUNK_CHARS:
            out.append(cur)
            cur = []
    return out + [cur] if cur else out


def map_chunk(chat, segs, kfs, lang):
    t0, t1 = segs[0]["s"], segs[-1]["e"]
    text = "\n".join(f"[{fmt(s['s'])}] {s['text']}" for s in segs)
    screens = [f"[{fmt(k['t'])}] {k['text'][:600]}" for k in kfs if k["screen"] and t0 <= k["t"] <= t1]
    if screens:
        text += "\n\nTexto en pantalla compartida:\n" + "\n".join(screens)[:2500]
    return chat(MAP_PROMPT.format(lang=lang), text, MAP_SCHEMA, 2000)


def reduce_maps(chat, maps, level, lang):
    for min_imp in (3, 4, 5):  # ponytail: un solo reduce; si no cabe se sube el umbral. Reduce jerárquico si 3 h no caben
        parts = []
        for m in maps:
            pts = "\n".join(f"- [{p['t']}] {p['texto']}" for p in m["puntos"] if p["importancia"] >= min_imp)
            dec = "\n".join(f"- DECISIÓN [{d['t']}] {d['texto']}" for d in m["decisiones"])
            tar = "\n".join(f"- TAREA [{t['t']}] {t['tarea']} (responsable: {t['responsable']}; plazo: {t['plazo']})"
                            for t in m["tareas"])
            parts.append(f"## {m['tema']}\n" + "\n".join(x for x in (pts, dec, tar) if x))
        text = "\n\n".join(parts)
        if len(text) < 16000:
            break
    cfg = LEVELS[level]
    return chat(REDUCE_PROMPT.format(lang=lang, tldr=cfg["tldr"], sec=cfg["sec"]), text, REDUCE_SCHEMA, 3000)


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
    esc = html.escape
    sections = sorted(red["secciones"], key=lambda s: parse_ts(s["t"])) or [{"titulo": "Reunión", "t": "00:00", "resumen": ""}]
    starts = [0] + [parse_ts(s["t"]) for s in sections[1:]]
    # una diapositiva que aparece justo antes (<20 s) del primer punto de una sección abre esa sección
    starts = [min([st] + [k["t"] for k in kfs if k["screen"] and st - 20 <= k["t"] < st]) for st in starts]
    items = [(parse_ts(p["t"]), f"<li>{ts_link(parse_ts(p['t']))}{esc(p['texto'])}</li>")
             for m in maps for p in m["puntos"] if p["importancia"] >= LEVELS[level]["min_imp"]]
    items += [(k["t"], f'<figure><a href="img/{k["img"]}" target="_blank"><img src="img/{k["img"]}" loading="lazy"></a>'
                       f'<figcaption>{ts_link(k["t"])}Pantalla compartida</figcaption></figure>')
              for k in kfs if k["screen"]]
    body = []
    for i, s in enumerate(sections):
        end = starts[i + 1] if i + 1 < len(sections) else 1e9
        inner = [h for t, h in sorted(items, key=lambda x: x[0]) if starts[i] <= t < end]
        lis = "".join(x if x.startswith("<li>") else f"</ul>{x}<ul>" for x in inner)
        body.append(f"<h3>{ts_link(starts[i])}{esc(s['titulo'])}</h3><p>{esc(s['resumen'])}</p><ul>{lis}</ul>")
    dec = "".join(f"<li>{ts_link(parse_ts(d['t']))}{esc(d['texto'])}</li>" for d in sorted(red["decisiones"], key=lambda d: parse_ts(d["t"]))) or "<li>—</li>"
    tasks = "".join(f"<tr><td>{ts_link(parse_ts(t['t']))}{esc(t['tarea'])}</td><td>{esc(t['responsable'])}</td>"
                    f"<td>{esc(t['plazo'])}</td></tr>" for t in sorted(red["tareas"], key=lambda t: parse_ts(t["t"])))
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
<h2>Desarrollo</h2>{''.join(body)}
<h2>Transcripción</h2><details><summary>Mostrar transcripción completa</summary>{trans}</details>
</div></main><script>{JS}</script></body></html>"""
    (out / "index.html").write_text(page, encoding="utf-8")


# ---------- Orquestación ----------
def run(video, level="normal", quality="rápido", threads=os.cpu_count(), cb=lambda f, m: None):
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

    kf = wd / "keyframes.json"
    if not kf.exists():
        t0 = time.time()
        kf.write_text(json.dumps(keyframes(video, wd, threads, dur, lambda f, m: cb(0.45 + 0.15 * f, m)), ensure_ascii=False))
        stage("capturas+ocr", t0)
    kfs = json.loads(kf.read_text())

    chunks = chunk(tr["segments"])
    mf, rf = wd / f"map_{quality}.json", wd / f"reduce_{quality}_{level}.json"
    maps = json.loads(mf.read_text()) if mf.exists() else []
    if len(maps) < len(chunks) or not rf.exists():
        t0 = time.time()
        cb(0.6, "Arrancando modelo de lenguaje…")
        with llama(threads) as chat:
            stage("llm_carga", t0)
            t0 = time.time()
            for i in range(len(maps), len(chunks)):
                cb(0.6 + 0.3 * i / len(chunks), f"Resumiendo bloque {i + 1}/{len(chunks)}…")
                maps.append(map_chunk(chat, chunks[i], kfs, lang))
                mf.write_text(json.dumps(maps, ensure_ascii=False))  # caché incremental: se retoma si se corta
            stage("map", t0)
            t0 = time.time()
            cb(0.92, "Redactando el acta…")
            rf.write_text(json.dumps(reduce_maps(chat, maps, level, lang), ensure_ascii=False))
            stage("reduce", t0)
    red = json.loads(rf.read_text())

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
    a, b = rng.integers(0, 255, 100), rng.integers(0, 255, 100)
    noisy = a.copy(); noisy[:2] += 100
    # A A A(ruido) B B A A -> tramos A y B; la vuelta a A no se repite
    segs = stable_segments(np.array([a, a, noisy, b, b, a, a]))
    assert segs == [(0, 2), (3, 4)], segs
    assert len(chunk([{"s": i, "e": i + 1, "text": "x" * 991} for i in range(25)])) == 3
    print("ok")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Genera el acta de una reunión grabada")
    ap.add_argument("video", nargs="?")
    ap.add_argument("--nivel", default="normal", choices=LEVELS)
    ap.add_argument("--asr", default="rápido", choices=ASR_MODELS)
    ap.add_argument("--threads", type=int, default=os.cpu_count())
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
