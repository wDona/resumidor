"""Grabar reunión sin bot: dos pistas (micrófono = «Yo», audio del sistema = «Otros») + pantalla opcional, por tramos
(a prueba de cortes), notas con el minuto, y las piezas que usa el pipeline (transcripción por pista, notas -> documento).
Audio: python-soundcard (WASAPI loopback en Windows, monitores de PulseAudio/PipeWire en Linux, CoreAudio en macOS).
Vídeo: ffmpeg (gdigrab / x11grab / avfoundation) a 2 fps, en tramos con el muxer segment."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np

SR = 16000
SEG_S = int(os.environ.get("ACTAS_SEG", 180))  # s por tramo
VENT = 45  # s a cada lado de una nota que se fuerzan en el documento
PISTAS = ("mic", "sistema")
ROL = {"mic": "Hablante 1", "sistema": "Hablante 2"}  # en la transcripción; nombres por defecto «Yo» y «Otros»
NOMBRES = "Hablante 1=Yo, Hablante 2=Otros"
ACT = {"r": None}
_lock = threading.Lock()


def carpeta(pipeline):
    return pipeline.WORK / "grabaciones"


# ---------- Dispositivos ----------
def pantalla_ok():
    if sys.platform == "win32":
        return True, ""
    if sys.platform == "darwin":
        return True, "macOS pedirá permiso de grabación de pantalla la primera vez"
    if os.environ.get("XDG_SESSION_TYPE") == "wayland" or not os.environ.get("DISPLAY"):
        return False, "En Wayland no se puede grabar la pantalla (por ahora)"
    return True, ""


def dispositivos():
    """{mics, sistemas: [{id, name}], mic, sistema: elegidos por defecto, pantalla: [ok, motivo], aviso}."""
    ok, why = pantalla_ok()
    out = {"so": sys.platform, "mics": [], "sistemas": [], "mic": "", "sistema": "", "pantalla": [ok, why], "aviso": "", "error": ""}
    try:
        import soundcard as sc
        todos = sc.all_microphones(include_loopback=True)
        dm, ds = sc.default_microphone(), sc.default_speaker()
    except Exception as ex:
        out["error"] = f"No se pueden listar los dispositivos de audio: {ex}"
        return out
    bh = lambda m: "blackhole" in m.name.lower()  # macOS: sin loopback nativo, BlackHole aparece como una entrada
    out["mics"] = [{"id": m.id, "name": m.name} for m in todos if not m.isloopback and not bh(m)]
    out["sistemas"] = [{"id": m.id, "name": m.name} for m in todos if m.isloopback or bh(m)]
    out["mic"] = dm.id if dm else (out["mics"][0]["id"] if out["mics"] else "")
    ds_id = ds.id if ds else ""
    out["sistema"] = next((s["id"] for s in out["sistemas"] if s["id"] in (ds_id, ds_id + ".monitor")), out["sistemas"][0]["id"] if out["sistemas"] else "")
    if sys.platform == "darwin" and not out["sistemas"]:
        out["aviso"] = "En Mac, el audio del sistema requiere BlackHole (por ahora)"  # TODO: ScreenCaptureKit (macOS 13+) con un ayudante nativo
    return out


# ---------- Grabación ----------
def _dev(id_):
    import soundcard as sc
    return next((m for m in sc.all_microphones(include_loopback=True) if m.id == id_), None)


def _ffmpeg_video(n0, wd):
    """Orden de ffmpeg para la pantalla, a 2 fps, en tramos video_NNN.mkv."""
    enc = subprocess.run(["ffmpeg", "-v", "error", "-encoders"], capture_output=True, text=True).stdout
    cod = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "32"] if "libx264" in enc else ["-c:v", "mpeg4", "-q:v", "10"]
    if sys.platform == "win32":
        src = ["-f", "gdigrab", "-framerate", "2", "-i", "desktop"]
    elif sys.platform == "darwin":
        lst = subprocess.run(["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""], capture_output=True, text=True).stderr
        m = re.search(r"\[(\d+)\] Capture screen 0", lst)
        src = ["-f", "avfoundation", "-framerate", "10", "-capture_cursor", "1", "-i", f"{m[1] if m else 1}:none"]
    else:
        src = ["-f", "x11grab", "-framerate", "2", "-i", os.environ.get("DISPLAY", ":0")]
    return ["ffmpeg", "-y", "-v", "error", *src, "-vf", "fps=2,scale=trunc(iw/2)*2:trunc(ih/2)*2", *cod, "-pix_fmt", "yuv420p", "-g", "10",
            "-f", "segment", "-segment_time", str(SEG_S), "-segment_format", "matroska", "-segment_start_number", str(n0),
            "-reset_timestamps", "1", str(wd / "video_%03d.mkv")]


class Rec:
    def __init__(s, wd, cfg):
        s.wd, s.cfg = Path(wd), cfg
        s.nivel = {t: 0 for t in PISTAS}
        s.err, s.hilos, s.ff = {}, [], None
        s.pausada, s.parada = False, threading.Event()
        s.acum, s.t0 = 0.0, None  # s activos acumulados / instante de la última reanudación
        s.vseg = 0

    def elapsed(s):
        return s.acum + (time.monotonic() - s.t0 if s.t0 else 0)

    def _video(s):
        s.ff = subprocess.Popen(_ffmpeg_video(s.vseg, s.wd), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _parar_video(s):
        if s.ff:
            try:
                s.ff.stdin.write(b"q")
                s.ff.stdin.flush()
                s.ff.wait(15)
            except Exception:
                s.ff.kill()
            s.ff = None
            s.vseg = len(list(s.wd.glob("video_*.mkv")))

    def _pista(s, tr, dev):
        n, seg, f = 0, -1, None
        try:
            ch = dev.channels if isinstance(dev.channels, int) else len(dev.channels)
            with dev.recorder(samplerate=SR, channels=ch, blocksize=SR // 10) as r:
                s.listo[tr].set()
                while not s.parada.is_set():
                    x = r.record(numframes=SR // 5).reshape(-1, ch).mean(axis=1)
                    s.nivel[tr] = float(np.sqrt(np.mean(x * x))) if len(x) else 0.0
                    if s.pausada:
                        continue
                    if f is None or n >= SEG_S * SR:
                        f and f.close()
                        seg, n = seg + 1, 0
                        f = open(s.wd / f"{tr}_{seg:03d}.pcm", "ab")
                    f.write((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
                    f.flush()
                    n += len(x)
        except Exception as ex:
            s.err[tr] = str(ex) or type(ex).__name__
        finally:
            f and f.close()
            s.listo[tr].set()

    def iniciar(s):
        s.listo = {t: threading.Event() for t in PISTAS}
        for tr in PISTAS:
            dev = _dev(s.cfg.get(tr + "_id"))
            if dev is None:
                if tr == "mic":
                    raise RuntimeError("Elige un micrófono")
                s.listo[tr].set()  # sin audio del sistema: solo micrófono
                continue
            h = threading.Thread(target=s._pista, args=(tr, dev), daemon=True)
            h.start()
            s.hilos.append(h)
        for e in s.listo.values():
            e.wait(5)
        if s.err.get("mic"):
            raise RuntimeError("No se pudo abrir el micrófono: " + s.err["mic"])
        s.t0 = time.monotonic()
        if s.cfg.get("pantalla") and pantalla_ok()[0]:
            s._video()

    def pausar(s):
        if not s.pausada:
            s.acum, s.t0, s.pausada = s.elapsed(), None, True
            s._parar_video()

    def reanudar(s):
        if s.pausada:
            s.t0, s.pausada = time.monotonic(), False
            if s.cfg.get("pantalla") and pantalla_ok()[0]:
                s._video()

    def parar(s):
        s.acum, s.t0 = s.elapsed(), None
        s.parada.set()
        s._parar_video()
        for h in s.hilos:
            h.join(10)

    def estado(s):
        db = lambda v: round(max(0, min(1, (20 * np.log10(v + 1e-9) + 60) / 60)) * 100)
        return {"id": s.wd.name, "estado": "pausada" if s.pausada else "grabando", "elapsed": round(s.elapsed(), 1),
                "size": sum(f.stat().st_size for f in s.wd.glob("*") if f.is_file()),
                "nivel": {t: db(v) for t, v in s.nivel.items()}, "err": s.err, "pantalla": bool(s.ff), "notas": len(leer_notas(s.wd))}


def _meta(wd, **kw):
    f = Path(wd) / "rec.json"
    m = json.loads(f.read_text()) if f.exists() else {}
    m.update(kw)
    f.write_text(json.dumps(m, ensure_ascii=False))
    return m


def meta(wd):
    try:
        return json.loads((Path(wd) / "rec.json").read_text())
    except (OSError, ValueError):
        return {}


def iniciar(pipeline, cfg):
    with _lock:
        if ACT["r"] and not ACT["r"].parada.is_set():
            raise RuntimeError("Ya hay una grabación en curso")
        wd = carpeta(pipeline) / time.strftime("%Y%m%d-%H%M%S")
        wd.mkdir(parents=True)
        r = Rec(wd, cfg)
        try:
            r.iniciar()
        except Exception:
            r.parar()
            shutil.rmtree(wd, ignore_errors=True)
            raise
        _meta(wd, id=wd.name, estado="grabando", inicio=time.time(), cfg=cfg)
        ACT["r"] = r
        return r


def activa():
    r = ACT["r"]
    return r if r and not r.parada.is_set() else None


def recuperables(pipeline):
    """Grabaciones sin cerrar (la app se cerró o falló): [{id, inicio, tam, dur, cfg}], la activa no cuenta."""
    a = activa()
    out = []
    for wd in sorted(carpeta(pipeline).glob("*/rec.json"), reverse=True):
        m = meta(wd.parent)
        if m.get("estado") in ("grabando", "pausada", "parada") and not (a and a.wd == wd.parent):
            n = sum(f.stat().st_size for f in wd.parent.glob("mic_*.pcm"))
            out.append({"id": wd.parent.name, "inicio": m.get("inicio"), "dur": round(n / 2 / SR), "tam": sum(f.stat().st_size for f in wd.parent.glob("*") if f.is_file()),
                        "cfg": m.get("cfg", {}), "notas": len(leer_notas(wd.parent))})
    return out


# ---------- Cierre: tramos -> pistas -> medio ----------
def unir_pcm(files, out, minimo=0):
    """Concatena tramos PCM s16 mono en un WAV (rellena con silencio hasta `minimo` muestras); devuelve las muestras."""
    n = 0
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        for f in files:
            tam = Path(f).stat().st_size // 2 * 2  # un corte puede dejar medio byte
            with open(f, "rb") as g:
                while tam > 0 and (b := g.read(min(tam, 1 << 20))):
                    w.writeframes(b[:len(b) // 2 * 2])
                    n += len(b) // 2
                    tam -= len(b)
        if n < minimo:
            w.writeframes(bytes(2 * (minimo - n)))
    return max(n, minimo)


def mezclar(a, b, out):
    """Suma dos WAV mono del mismo largo."""
    with wave.open(str(a)) as x, wave.open(str(b)) as y, wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        while d := x.readframes(SR * 30):
            e = y.readframes(SR * 30)
            u, v = np.frombuffer(d, "<i2").astype(np.int32), np.frombuffer(e, "<i2").astype(np.int32)
            v = np.pad(v, (0, max(0, len(u) - len(v))))[:len(u)]
            w.writeframes(np.clip(u + v, -32768, 32767).astype("<i2").tobytes())


def pico(wav):
    """Amplitud máxima (0-32767) de un WAV: una pista casi plana no se transcribe."""
    m = 0
    with wave.open(str(wav)) as w:
        while d := w.readframes(SR * 60):
            m = max(m, int(np.abs(np.frombuffer(d, "<i2").astype(np.int32)).max()))
    return m


def finalizar(wd):
    """Tramos -> mic.wav, sistema.wav (mismo largo), mezcla y el medio final (grabacion.mp4 con pantalla, grabacion.m4a sin ella).
    Devuelve {medio, pistas: {«Hablante N»: wav}, dur}. Se puede repetir (recuperación)."""
    wd = Path(wd)
    fs = {t: sorted(wd.glob(f"{t}_*.pcm")) for t in PISTAS}
    n = max((sum(f.stat().st_size for f in v) // 2 for v in fs.values()), default=0)
    if n < SR:
        raise RuntimeError("La grabación está vacía")
    for t in PISTAS:
        if fs[t] or t == "mic":
            unir_pcm(fs[t], wd / f"{t}.wav", n)
    pistas = {ROL[t]: str(wd / f"{t}.wav") for t in PISTAS if (wd / f"{t}.wav").exists() and pico(wd / f"{t}.wav") > 300}
    if (wd / "sistema.wav").exists():
        mezclar(wd / "mic.wav", wd / "sistema.wav", wd / "mezcla.wav")
    else:
        shutil.copy(wd / "mic.wav", wd / "mezcla.wav")
    vs = sorted(wd.glob("video_*.mkv"))
    if vs:
        (wd / "video.txt").write_text("".join(f"file '{v.name}'\n" for v in vs))
        medio = wd / "grabacion.mp4"
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(wd / "video.txt"), "-i", str(wd / "mezcla.wav"),
               "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "48k", "-shortest", str(medio)]
    else:
        medio = wd / "grabacion.m4a"
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(wd / "mezcla.wav"), "-c:a", "aac", "-b:a", "48k", str(medio)]
    subprocess.run(cmd, check=True, capture_output=True)
    for f in [*wd.glob("*.pcm"), *wd.glob("video_*.mkv"), wd / "video.txt"]:
        f.unlink(missing_ok=True)
    return {"medio": str(medio), "pistas": pistas, "dur": round(n / SR, 1)}


def limpiar(wd):
    """Tras generar: fuera las pistas y la mezcla (el medio se queda: el reproductor del documento lo enlaza)."""
    for f in ("mic.wav", "sistema.wav", "mezcla.wav"):
        (Path(wd) / f).unlink(missing_ok=True)
    _meta(wd, estado="procesada")


# ---------- Transcripción por pista ----------
def _pal(t):
    return set(re.findall(r"\w+", t.lower()))


def fusionar(pistas, eco=None):
    """pistas {etiqueta: segmentos}; une por tiempo con `spk` = etiqueta. Eco/diafonía: si el mismo texto sale en dos pistas a la vez
    (el micro recoge los altavoces), se queda el de la pista que no es `eco`. Si hablan a la vez con textos distintos, se conservan ambos."""
    todos = sorted(({**s, "spk": k} for k, v in pistas.items() for s in v), key=lambda s: (s["s"], s["e"]))
    out = []
    for s in todos:
        d = None
        for o in out[-12:]:
            ov = min(o["e"], s["e"]) - max(o["s"], s["s"])
            if o["spk"] != s["spk"] and ov > 0.5 * min(o["e"] - o["s"], s["e"] - s["s"]):
                a, b = _pal(o["text"]), _pal(s["text"])
                if a and b and len(a & b) / len(a | b) >= 0.6:
                    d = o
                    break
        if d is None:
            out.append(s)
        elif d["spk"] == eco:  # el eco estaba ya guardado: lo sustituye la versión limpia
            out[out.index(d)] = s
    return sorted(out, key=lambda s: (s["s"], s["e"]))


def transcribir(pipeline, pistas, quality, threads, dur, cb, hot=None):
    """Transcribe cada pista por separado (etiqueta = hablante) y las funde; una pista plana se salta."""
    res, n = {}, len(pistas)
    for i, (k, wav) in enumerate(pistas.items()):
        r = pipeline.transcribe(wav, quality, threads, dur, lambda f, m, i=i: cb((i + f) / n, m), hot=hot)
        res[k] = r
    langs = [r["language"] for r in res.values() if r["segments"] and r["language"]]
    return {"language": max(set(langs), key=langs.count, default=None), "pistas": list(pistas),
            "segments": fusionar({k: r["segments"] for k, r in res.items()}, eco=ROL["mic"])}


# ---------- Notas ----------
def leer_notas(wd):
    try:
        return json.loads((Path(wd) / "notas.json").read_text())
    except (OSError, ValueError):
        return []


def limpia_notas(notas):
    out = []
    for i, n in enumerate(notas if isinstance(notas, list) else []):
        try:
            t = max(0.0, round(float(n.get("t", 0)), 1))
        except (TypeError, ValueError):
            continue
        out.append({"id": str(n.get("id") or f"n{i}-{int(t)}")[:20], "t": t, "texto": str(n.get("texto") or "").strip()[:2000],
                    "boton": str(n.get("boton") or "")[:40], "seccion": str(n.get("seccion") or "")[:40] or None})
    return sorted(out, key=lambda n: n["t"])


def guardar_notas(wd, notas):
    notas = limpia_notas(notas)
    Path(wd).mkdir(parents=True, exist_ok=True)
    f = Path(wd) / "notas.json"
    f.write_text(json.dumps(notas, ensure_ascii=False)) if notas else f.unlink(missing_ok=True)
    return notas


def hash_notas(notas):
    return hashlib.sha1(json.dumps([(n["t"], n["texto"], n["boton"], n["seccion"]) for n in notas]).encode()).hexdigest()[:8]


def ventana(segs, t, w=VENT):
    return [s for s in segs if s["e"] >= t - w and s["s"] <= t + w]


def dicho(segs, t, atras=12, adelante=3, cap=300):
    """Lo que se decía al marcar (literal): segmentos que tocan [t-atras, t+adelante], o el más cercano."""
    ss = [s for s in segs if s["e"] >= t - atras and s["s"] <= t + adelante] or sorted(segs, key=lambda s: abs(s["s"] - t))[:1]
    x = " ".join(s["text"] for s in ss).strip()
    return x if len(x) <= cap else x[:cap].rsplit(" ", 1)[0] + "…"


NOTA_PROMPT = """Revisas un fragmento de una reunión transcrita (con errores de transcripción). La persona marcó el minuto {min} con la nota «{boton}», para la sección «{nombre}» ({desc}).
Extrae del fragmento UN elemento de esa sección, el más cercano al minuto marcado. La cita es una frase copiada LITERALMENTE de la transcripción, sin cambiar palabras. El resto lo redactas solo con lo que se dice, en {lang}, sin inventar nombres, cifras ni fechas. Si el fragmento no contiene nada de esa sección, deja la cita vacía y el texto vacío."""


def _esquema(pipeline, sec, P):
    S = pipeline.S
    if sec == "decisiones":
        return pipeline.obj(cita=S(100), texto=S(160))
    if sec == "tareas":
        return pipeline.obj(cita=S(100), tarea=S(160), responsable=S(60), plazo=S(60))
    s = next(x for x in P["gen"] if x["id"] == sec)
    return pipeline.obj(cita=S(100), texto=S(160), **{c: S(60) for c in pipeline.campos(s)})


def _info(P, sec):
    if sec in ("decisiones", "tareas"):
        t = P.get("tpl") or {}
        s = next((x for x in t.get("secciones", []) if x["id"] == sec), None)
        return (s or {}).get("nombre", sec.capitalize()), (s or {}).get("descripcion") or ("lo que se acordó" if sec == "decisiones" else "lo que alguien se compromete a hacer")
    s = next((x for x in P["gen"] if x["id"] == sec), None)
    return (s["nombre"], s["descripcion"]) if s else (None, None)


def pendientes(notas, P):
    """Notas con botón de sección que esta plantilla tiene (las demás solo se marcan)."""
    return [n for n in notas if n["seccion"] and _info(P, n["seccion"])[0] and (n["seccion"] in ("decisiones", "tareas") and P["acta"] or n["seccion"] in [s["id"] for s in P["gen"]])]


def extraer(pipeline, chat, n, segs, P, lang, model):
    """Un elemento de la sección de la nota, con la cita verificada en la ventana (None si no hay). Una llamada al LLM."""
    import rag
    ws = ventana(segs, n["t"])
    if not ws:
        return None
    nombre, desc = _info(P, n["seccion"])
    texto = "\n".join(f"[{pipeline.fmt(s['s'])}] {s['text']}" for s in ws)
    pr = NOTA_PROMPT.format(min=pipeline.fmt(n["t"]), boton=n["boton"] or "Marca", nombre=nombre, desc=desc, lang=lang)
    it = chat(pr, texto, _esquema(pipeline, n["seccion"], P), 400)
    k = "tarea" if n["seccion"] == "tareas" else "texto"
    if not it.get("cita", "").strip() or not it.get(k, "").strip():
        return None
    f, t = pipeline.find_quote(it["cita"], ws, near=n["t"])
    if f < 0.8:
        print(f"  nota descartada (cita no está en la ventana): {it[k]}", flush=True)
        return None
    if rag.bad_nums(" ".join(str(v) for c, v in it.items() if c != "cita"), texto):
        print(f"  nota descartada (cifras que no se dicen): {it[k]}", flush=True)
        return None
    it[k] = pipeline.sentences(it[k], 160)
    return {**it, "t": pipeline.fmt(t), "usuario": True, "importancia": 5}


def aplicar(pipeline, notas, segs, maps, red, P, ext):
    """Las notas entran en el documento: (1) todo lo de la ventana ±45 s sube a importancia 5 (maps; sigue en el vídeo condensado);
    (2) el elemento extraído de la sección (ext {id nota: item}) se añade a decisiones/tareas/sección propia, marcado «usuario» (si ya había
    uno parecido cerca, se marca ese); (3) devuelve las filas del bloque «Notas del usuario»: minuto, nota, y lo dicho entonces (literal)."""
    pt = pipeline.parse_ts
    for n in notas:
        for m in maps:
            for k in ["puntos", *[s["id"] for s in P["gen"]]]:
                for p in m.get(k, []):
                    if abs(pt(p["t"]) - n["t"]) <= VENT:
                        p["importancia"] = 5
        it = ext.get(n["id"])
        if not it:
            continue
        sec = n["seccion"]
        if sec in ("decisiones", "tareas"):
            lst, k = red[sec], "tarea" if sec == "tareas" else "texto"
        else:
            lst, k = maps[0].setdefault(sec, []), "texto"
        ya = next((x for x in lst if abs(pt(x["t"]) - pt(it["t"])) <= VENT and (pipeline.same(x.get(k, ""), it[k], 0.6) or pipeline.words(x.get("cita", "")) == pipeline.words(it["cita"]))), None)
        if ya:
            ya["usuario"] = True
        else:
            lst.append(it if sec in ("decisiones", "tareas") else {**it, "t": it["t"]})
    return [{"t": n["t"], "nombre": n["boton"], "texto": n["texto"], "dicho": dicho(segs, n["t"]), "seccion": n["seccion"]} for n in notas]


def _selftest():
    import tempfile
    d = Path(tempfile.mkdtemp())
    for i, v in enumerate((1000, 2000)):  # dos tramos de 1 s + 1 s; el segundo con medio byte de más (corte)
        (d / f"mic_{i:03d}.pcm").write_bytes(np.full(SR, v, "<i2").tobytes() + (b"\x01" if i else b""))
    assert unir_pcm(sorted(d.glob("mic_*.pcm")), d / "a.wav", 3 * SR) == 3 * SR
    with wave.open(str(d / "a.wav")) as w:
        assert w.getnframes() == 3 * SR
    (d / "s.pcm").write_bytes(np.full(SR, 500, "<i2").tobytes())
    unir_pcm([d / "s.pcm"], d / "b.wav", 3 * SR)
    mezclar(d / "a.wav", d / "b.wav", d / "m.wav")
    with wave.open(str(d / "m.wav")) as w:
        x = np.frombuffer(w.readframes(10), "<i2")
        assert x[0] == 1500 and w.getnframes() == 3 * SR
    assert pico(d / "b.wav") == 500
    seg = lambda s, e, t: {"s": s, "e": e, "text": t}
    m = fusionar({"Hablante 1": [seg(0, 4, "hola a todos buenos días"), seg(10, 12, "sí claro")],
                  "Hablante 2": [seg(0.2, 4.2, "hola a todos, buenos días"), seg(11, 13, "adelante con el punto")]}, eco="Hablante 1")
    assert [(s["spk"], s["text"]) for s in m] == [("Hablante 2", "hola a todos, buenos días"), ("Hablante 1", "sí claro"), ("Hablante 2", "adelante con el punto")], m
    n = limpia_notas([{"t": "61.04", "texto": " x ", "boton": "Acuerdo", "seccion": "decisiones"}, {"t": 5}, {"t": "malo"}])
    assert [x["t"] for x in n] == [5.0, 61.0] and n[1]["seccion"] == "decisiones"
    ss = [seg(10 * i, 10 * i + 8, f"frase {i}") for i in range(30)]
    assert [s["text"] for s in ventana(ss, 100)][0] == "frase 5" and len(ventana(ss, 100)) == 10 and len(ventana(ss, 0)) == 5
    assert dicho(ss, 100) == "frase 8 frase 9 frase 10"
    assert hash_notas(n) == hash_notas(limpia_notas(n)) and hash_notas(n) != hash_notas(n[:1])
    print("grabar ok")


if __name__ == "__main__":
    _selftest()
