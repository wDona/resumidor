"""Interfaz web local (FastAPI + página estática): vídeo -> acta HTML, vídeo condensado y preguntas. `uv run app.py`."""
import atexit
import functools
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile
import urllib.parse
import urllib.request
import uuid
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import models
import pipeline
import procs
import rag
import transcripts

THREADS = int(os.environ.get("ACTAS_THREADS", pipeline.PHYS))
STATIC, LOCK, COLA = pipeline.ROOT / "static", pipeline.ROOT / ".actas.lock", pipeline.WORK / "cola.json"
UPLOADS = pipeline.ROOT / "uploads"
TR_EXT = (".vtt", ".srt", ".txt", ".docx")
IDLE = 60  # s sin latido de la página y el servidor se cierra
IDLE_JOB = 180  # ídem con un trabajo en marcha (recarga o vuelta de la pestaña)
app = FastAPI()
beat = [time.time()]
job = {"state": "idle"}  # trabajo actual (compatibilidad con /api/job); state: idle | running | done | error; kind: acta | fondo | condensar
jlock = threading.Lock()
cola = []  # FIFO persistida en work/cola.json: {id, kind, spec, video, mid, state: pendiente|marcha|hecho|error|cancelado|interrumpido, ...}
cancelar = set()  # ids de trabajos en marcha a los que se pidió cancelar (se comprueba en cada cb)
ACTIVOS = ("pendiente", "marcha")


class Cancelado(Exception):
    pass


def guardar():
    pipeline.WORK.mkdir(exist_ok=True)
    fin = [e for e in cola if e["state"] not in ACTIVOS][-15:]  # del historial solo se guardan los últimos
    cola[:] = [e for e in cola if e["state"] in ACTIVOS or e in fin]
    COLA.write_text(json.dumps(cola, ensure_ascii=False))


try:  # reinicio: lo que estaba en marcha ya no tiene hilo (se puede reintentar); lo pendiente sigue en cola
    cola[:] = json.loads(COLA.read_text())
    for e in cola:
        if e["state"] == "marcha":
            e.update(state="interrumpido", error="El trabajo se interrumpió al cerrar la aplicación")
except (OSError, ValueError):
    pass


# ---------- LLM compartido por «Preguntar» ----------
_llm, _idx = {}, {}


def parar_llm():
    if _llm.get("proc"):
        _llm.pop("proc").terminate()
    _llm.clear()


atexit.register(parar_llm)


# ---------- Cola de trabajos (uno a la vez: la GPU no admite dos) ----------
def start(kind, spec, video, mid=""):
    with jlock:
        e = {"id": uuid.uuid4().hex[:8], "kind": kind, "spec": spec, "video": video, "mid": mid, "state": "pendiente", "t": time.time()}
        cola.append(e)
        guardar()
    kick()
    return {"id": e["id"]}


def kick():
    """Arranca el siguiente pendiente si no hay ninguno en marcha (se llama al encolar y al terminar cada trabajo)."""
    with jlock:
        e = next((e for e in cola if e["state"] == "marcha"), None) or next((e for e in cola if e["state"] == "pendiente"), None)
        if not e or e["state"] == "marcha":
            return
        e["state"] = "marcha"
        job.clear()
        job.update(state="running", kind=e["kind"], frac=0, msg="Empezando…", t0=time.time(), video=e["video"], qid=e["id"])
        pipeline.ETA.clear()
        guardar()
    parar_llm()  # dos modelos de 3 GB a la vez no caben en 8 GB

    def cb(f, m):
        if e["id"] in cancelar:
            raise Cancelado()
        job.update(frac=round(f, 4), msg=m)

    def work():
        try:
            e["result"] = FNS[e["kind"]](e["spec"])(cb)
            e["state"] = "hecho"
            job.update(state="done", frac=1, msg="Listo", result=e["result"])
        except Cancelado:
            e["state"] = "cancelado"
            job.update(state="error", error="Cancelado")
        except Exception as ex:
            e.update(state="error", error=str(ex) or type(ex).__name__)
            job.update(state="error", error=e["error"])
        cancelar.discard(e["id"])
        with jlock:
            guardar()
        kick()

    threading.Thread(target=work, daemon=True).start()


def _eta(j):
    e = pipeline.eta() if j.get("state") == "running" else None  # actas: por fases y ritmos de este equipo
    if e is not None:
        return e
    if j.get("state") == "running" and j["frac"] > 0.03:  # resto (vídeo condensado): regla de tres
        return round((time.time() - j["t0"]) * (1 - j["frac"]) / j["frac"])


@app.get("/api/job")
def get_job():
    j = dict(job)
    if (e := _eta(j)) is not None:
        j["eta"] = e
    return j


def _entry(d):
    e = next((e for e in cola if e["id"] == d.get("id")), None)
    if not e:
        raise HTTPException(404, "Ese trabajo ya no está en la cola")
    return e


@app.get("/api/cola")
def get_cola():
    items = [{k: v for k, v in e.items() if k != "spec"} for e in cola]
    for i in items:
        if i["state"] == "marcha":
            i.update(frac=job.get("frac", 0), msg=job.get("msg", ""), eta=_eta(job), t0=job.get("t0"))
    return {"n": sum(e["state"] in ACTIVOS for e in cola), "items": items}


@app.post("/api/cola/cancelar")
def cola_cancelar(d: dict):
    """Pendiente: sale de la cola. En marcha: se corta en el siguiente aviso de progreso (cooperativo)."""
    with jlock:
        e = _entry(d)
        if e["state"] == "pendiente":
            e["state"] = "cancelado"
        elif e["state"] == "marcha":
            cancelar.add(e["id"])
        guardar()
    return {}


@app.post("/api/cola/reintentar")
def cola_reintentar(d: dict):
    with jlock:
        e = _entry(d)
        if e["state"] in ACTIVOS or e["state"] == "hecho":
            raise HTTPException(400, "Ese trabajo no se puede reintentar")
        cola.remove(e)
        e.update(state="pendiente", t=time.time())
        e.pop("error", None)
        cola.append(e)
        guardar()
    kick()
    return {}


@app.post("/api/cola/quitar")
def cola_quitar(d: dict):
    with jlock:
        e = _entry(d)
        if e["state"] == "marcha":
            raise HTTPException(400, "Cancélalo primero")
        cola.remove(e)
        guardar()
    return {}


@app.post("/api/cola/mover")
def cola_mover(d: dict):
    """Sube (-1) o baja (1) un pendiente respecto a los demás pendientes."""
    with jlock:
        e = _entry(d)
        p = [x for x in cola if x["state"] == "pendiente"]
        j = p.index(e) + (-1 if d.get("d", 0) < 0 else 1) if e in p else -1
        if 0 <= j < len(p):
            a, b = cola.index(e), cola.index(p[j])
            cola[a], cola[b] = cola[b], cola[a]
            guardar()
    return {}


@app.get("/api/gpu")
def gpu():
    """GPU + RAM + modelo del chat con y sin GPU (la interfaz elige según la casilla)."""
    return {**pipeline.gpu_info(), "ram_gb": pipeline.ram_gb(), "chat_gpu": rag.chat_choice(True), "chat_cpu": rag.chat_choice(False),
            "llm": pipeline.llm_label(), "niveles": niveles()}


def niveles():
    """Calidades del acta (de serie + personalizadas) con su modelo, estado en este equipo (ok/aviso/no), si está instalado y su tamaño."""
    out = []
    for q, n in pipeline.NIVELES.items():
        m, path = "rápida" if q == "alta" else q, pipeline.acta_model(q)
        inst, pers = bool(path and path.is_file()), q in pipeline.PERS or q in pipeline.OVER
        size = path.stat().st_size if inst else models.tam(m)
        e, need = pipeline.evaluar(size, n[1])
        out.append({"id": q, "nombre": n[0], "modelo": pipeline.llm_label(path) if pers else models.CAT[m][0] if m in models.CAT else n[0], "tiempo": n[2], "m": m, "estado": e,
                    "instalado": inst, "bytes": size, "necesita": round(need, 1), "pers": pers})
    return out


def falta(d, accion, video=True):
    """409 con lo que falta instalar (la interfaz abre Modelos con ese aviso)."""
    txt, ids = models.faltan(accion, d.get("calidad") or ("alta" if d.get("alta") else "rápida"), video)
    if ids:
        raise HTTPException(409, {"msg": txt, "faltan": ids})


# ---------- Descarga desde un enlace (yt-dlp) ----------
NAVEGADORES = {"firefox": "Firefox", "chrome": "Chrome", "edge": "Edge", "safari": "Safari"}


def url_valida(url):
    u = urllib.parse.urlsplit(url)
    return u.scheme in ("http", "https") and bool(u.netloc)


def error_descarga(ex, nav=""):
    """Mensaje claro en español a partir del texto de la excepción de yt-dlp (DownloadError, CookieLoadError…)."""
    t, b = f"{type(ex).__name__} {ex}".lower(), NAVEGADORES.get(nav, "el navegador")
    if "drm" in t:
        return "Este sitio protege el vídeo (DRM): descárgalo a mano"
    if "cookie" in t or "keyring" in t or "dpapi" in t or "decrypt" in t or "database is locked" in t or "unsupported browser" in t:
        return (f"No se pudieron leer las sesiones de {b}: ciérralo del todo y reintenta, o prueba con Firefox "
                "(Chrome y Edge suelen bloquear esto en Windows)")
    if "unsupported url" in t:
        return "Enlace no compatible: no se encontró ningún vídeo ni audio en esa dirección"
    if any(x in t for x in ("http error 401", "http error 403", "sign in", "log in", "login", "private", "members-only", "members only", "confirm you", "not a bot", "forbidden", "authentication", "age-restricted", "permission")):
        return (f"Sin permiso: el enlace no es público. Inicia sesión en ese sitio con {b} y elígelo arriba, o descárgalo a mano" if nav else
                "Sin permiso: el enlace no es público. Inicia sesión en ese sitio con tu navegador y elígelo arriba en «Usar sesión del navegador», o descárgalo a mano")
    if any(x in t for x in ("http error 404", "http error 410", "not found", "removed", "no longer available", "unavailable", "expired", "does not exist", "deleted")):
        return "El enlace ya no existe: no se encuentra, lo han quitado o ha caducado"
    if any(x in t for x in ("urlopen", "name or service", "name resolution", "timed out", "connection", "network", "getaddrinfo", "unable to download", "ssl")):
        return "Error de red: no se pudo descargar. Revisa la conexión a internet y reintenta"
    return "No se pudo descargar el enlace: " + re.sub(r"^(ERROR: )?(\[[^\]]+\] )?", "", str(ex).strip().splitlines()[0] if str(ex).strip() else type(ex).__name__)[:200]


def descargar(url, solo_audio, nav, cb, dest=None):
    """Baja url a UPLOADS/enlaces/<tmp>/ y devuelve la ruta del fichero (video o solo audio). Fase del trabajo en cola:
    el progreso va al cb del trabajo. Las cookies del navegador las lee yt-dlp en memoria: no se guardan ni se registran."""
    import tempfile
    import yt_dlp
    (UPLOADS / "enlaces").mkdir(parents=True, exist_ok=True)
    dest = Path(dest or tempfile.mkdtemp(dir=UPLOADS / "enlaces"))
    vistos = []

    def hook(h):
        if h["status"] != "downloading":
            return
        if h["filename"] not in vistos:
            vistos.append(h["filename"])
        n = len((h.get("info_dict") or {}).get("requested_formats") or [1])
        tot = h.get("total_bytes") or h.get("total_bytes_estimate") or 0
        f = ((len(vistos) - 1) + (h["downloaded_bytes"] / tot if tot else 0)) / max(n, len(vistos))
        e = h.get("eta")
        cb(min(f, 1), f"Descargando… {f * 100:.0f} %" + (f" · faltan {int(e) // 60}:{int(e) % 60:02d}" if e else ""))
    opts = {"outtmpl": str(dest / "%(title).80B.%(ext)s"), "windowsfilenames": True, "noplaylist": True, "quiet": True, "no_warnings": True,
            "noprogress": True, "progress_hooks": [hook], "format": "bestaudio/best" if solo_audio else "bv*+ba/b", "format_sort": ["res:1080", "ext"],
            "retries": 3, "socket_timeout": 30, "color": "never"}
    if nav:
        opts["cookiesfrombrowser"] = (nav,)
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=True)
    except Exception as ex:
        if isinstance(ex, Cancelado):
            raise
        raise RuntimeError(error_descarga(ex, nav)) from None
    f = next((Path(r["filepath"]) for r in (info or {}).get("requested_downloads") or [] if r.get("filepath")), None)
    f = f if f and f.is_file() else max(dest.glob("*.*"), key=lambda x: x.stat().st_size, default=None)
    if not f:
        raise RuntimeError("No se pudo descargar el enlace: no se obtuvo ningún fichero")
    return f


def _acta_fn(d):
    video, tr, url = Path(d.get("video") or ""), d.get("transcripcion") or "", (d.get("enlace") or "").strip()
    video = video if video.is_file() else None
    names = {n: v.strip() for n, v in re.findall(r"[Hh]ablante\s*(\d+)\s*=\s*([^,;\n]+)", d.get("nombres") or "")}
    nivel, asr, calidad, reuse = d.get("nivel", "normal"), d.get("asr", "calidad"), d.get("calidad", "rápida"), d.get("reuse")

    def fn(cb):
        dl = None
        if url:  # la descarga es la 1.ª fase del trabajo; luego sigue el proceso normal con el fichero bajado
            dl = descargar(url, bool(d.get("solo_audio")), d.get("navegador") or "", cb)
        out, _, _ = pipeline.run(dl or video, nivel, asr, THREADS, cb, names, bool(d.get("hablantes")), tr or None, calidad, d.get("gpu"),
                                 reuse=(Path(reuse).name, asr) if reuse else None)
        if dl and not any(m.is_symlink() for m in out.parent.glob("video.*")):  # ya hay enlace duro/copia en la reunión
            shutil.rmtree(dl.parent, ignore_errors=True)
        return {"id": out.parent.name, "acta": out.name}
    return fn


@app.post("/api/generar")
def generar(d: dict):
    """Encola un acta nueva (video/transcripcion) u otra versión de una reunión ya procesada (reuse = id, asr = su transcripción)."""
    video, tr, reuse, url = Path(d.get("video") or ""), d.get("transcripcion") or "", d.get("reuse"), (d.get("enlace") or "").strip()
    if url and not url_valida(url):
        raise HTTPException(400, "El enlace debe empezar por http:// o https://")
    if d.get("navegador") and d["navegador"] not in NAVEGADORES:
        raise HTTPException(400, "Navegador no válido")
    if tr and (Path(tr).suffix.lower() not in TR_EXT or not Path(tr).is_file()):
        raise HTTPException(400, "La transcripción debe ser un fichero .vtt, .srt, .txt o .docx")
    if reuse:
        if not (pipeline.WORK / Path(reuse).name / f"transcript_{d.get('asr')}.json").exists():
            raise HTTPException(400, "Reunión no encontrada")
        if _solo_acta(reuse, d.get("asr")):
            raise HTTPException(400, "Esta acta se importó sin transcripción: no se puede rehacer")
    elif not (video.is_file() or tr or url):
        raise HTTPException(400, "Elige un vídeo, un audio, un enlace o una transcripción")
    if d.get("nivel", "normal") not in pipeline.LEVELS or d.get("asr", "calidad") not in pipeline.ASR_MODELS and not reuse or d.get("calidad", "rápida") not in pipeline.NIVELES:
        raise HTTPException(400, "Opción no válida")
    n = next(x for x in niveles() if x["id"] == d.get("calidad", "rápida"))
    if n["estado"] == "no":
        raise HTTPException(400, f"El nivel «{n['nombre']}» no cabe en este equipo (necesita ~{n['necesita']:.0f} GB de memoria)")
    falta(d, "generar", bool(video.is_file() or url or reuse and next((pipeline.WORK / Path(reuse).name).glob("video.*"), None)) and not tr)
    return start("acta", d, (video if video.is_file() else Path(tr)).name if not reuse and not url else url[:80] if not reuse else meta(pipeline.WORK / Path(reuse).name).get("nombre") or Path(reuse).name, Path(reuse).name if reuse else "")


@app.post("/api/fondo")
def fondo(d: dict):
    """Búsqueda a fondo de decisiones y tareas de un acta ya generada: mismo trabajo en cola que generar (un solo LLM a la vez)
    y se rehace el acta en su carpeta."""
    wd, nivel, asr = pipeline.WORK / Path(d.get("id", "")).name, d.get("nivel", "normal"), d.get("asr", "calidad")
    if nivel not in pipeline.LEVELS or not (wd / f"transcript_{asr}.json").exists():
        raise HTTPException(400, "Genera primero el acta")
    if _solo_acta(wd.name, asr):
        raise HTTPException(400, "Esta acta se importó sin transcripción: no se puede buscar a fondo")
    falta(d, "fondo")
    return start("fondo", d, wd.name, wd.name)


def _fondo_fn(d):
    wd, nivel, asr = pipeline.WORK / Path(d["id"]).name, d.get("nivel", "normal"), d.get("asr", "calidad")

    def fn(cb):
        out, _, _ = pipeline.run(None, nivel, asr, THREADS, cb, calidad=d.get("calidad") or ("alta" if d.get("alta") else "rápida"), gpu=d.get("gpu"), fondo=True, reuse=(wd.name, asr))
        return {"id": wd.name, "acta": out.name}
    return fn


@app.post("/api/condensar")
def condensar(d: dict):
    wd, asr = pipeline.WORK / Path(d["id"]).name, d.get("asr", "calidad")
    if not (wd / f"cortes_{asr}.json").exists():
        raise HTTPException(400, "Genera primero el acta")
    if _solo_acta(wd.name, asr):
        raise HTTPException(400, "Esta acta se importó sin transcripción: no se puede buscar a fondo")
    return start("condensar", d, wd.name, wd.name)


def _condensar_fn(d):
    wd, asr, pct = pipeline.WORK / Path(d["id"]).name, d.get("asr", "calidad"), int(d.get("pct", 40))

    def fn(cb):
        pipeline.condense(wd, asr, pct, THREADS, cb)
        return {"id": wd.name}
    return fn


FNS = {"acta": _acta_fn, "fondo": _fondo_fn, "condensar": _condensar_fn}


# ---------- Vídeo de entrada ----------
@app.post("/api/pick")
def pick(d: dict = None):
    """Diálogo nativo de Tk en un subproceso (Tk no admite hilos ajenos al principal): devuelve la ruta real, sin copiar.
    {"tipo": "transcripcion"} elige una transcripción en vez de un vídeo."""
    tipo = ("Transcripción", "*" + " *".join(TR_EXT)) if (d or {}).get("tipo") == "transcripcion" else \
        ("Modelo GGUF", "*.gguf") if (d or {}).get("tipo") == "modelo" else ("Vídeo o audio", "*.mp4 *.mkv *.webm *.mov *.avi *.m4v *.mp3 *.m4a *.wav *.ogg *.opus *.flac *.aac")
    code = ("import tkinter as t, tkinter.filedialog as f\nr=t.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
            f"print(f.askopenfilename(title='Elegir {tipo[0].lower()}', filetypes=[{tipo!r}, ('Todos', '*')]))")
    p = subprocess.run([sys.executable, "-X", "utf8", "-c", code], capture_output=True, text=True, encoding="utf-8")
    return {"path": p.stdout.strip()}


ZIP_OK = re.compile(r"index\.html|acta\.json|transcript\.json|video\.[A-Za-z0-9]{2,4}|img/[\w.\-]+")


@app.post("/api/importar")
def importar(d: dict):
    """Importa un acta exportada por la app (zip ligero o «con vídeo»): se valida el zip (solo ficheros esperados, sin rutas fuera,
    tamaños razonables) y se crea una reunión en work/ visible sin modelos. Con transcript.json también se podrá preguntar."""
    zp = Path(d.get("path", ""))
    if zp.suffix.lower() != ".zip" or not zp.is_file() or not zipfile.is_zipfile(zp):
        raise HTTPException(400, "Elige un .zip de acta exportado por la aplicación")
    with zipfile.ZipFile(zp) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        names = {i.filename for i in infos}
        vid = lambda i: i.filename.startswith("video.")
        if not (infos and {"index.html", "acta.json"} <= names) or any(not ZIP_OK.fullmatch(i.filename) for i in infos) or len(names) != len(infos):
            raise HTTPException(400, "El zip no es un acta de esta aplicación")
        if sum(i.file_size for i in infos) > 20 * 2**30 or any(i.file_size > 300 * 2**20 or i.file_size > 1000 * max(i.compress_size, 1024) for i in infos if not vid(i)):
            raise HTTPException(400, "El zip tiene un tamaño sospechoso")
        try:
            acta = json.loads(z.read("acta.json"))
            tr = json.loads(z.read("transcript.json")) if "transcript.json" in names else None
        except ValueError:
            raise HTTPException(400, "El zip está dañado")
        h = hashlib.sha1(f"{zp.name}|{zp.stat().st_size}|{zp.stat().st_mtime_ns}".encode()).hexdigest()
        wd, nivel = pipeline.WORK / ("z" + h[:15]), acta.get("nivel") if acta.get("nivel") in pipeline.LEVELS else "normal"
        out = wd / f"acta_{nivel}_zip{h[15:21]}"
        shutil.rmtree(out, ignore_errors=True)
        (out / "img").mkdir(parents=True)
        for i in infos:
            dst = (wd / i.filename) if vid(i) else (wd / f"transcript_zip{h[15:21]}.json") if i.filename == "transcript.json" else out / i.filename
            with z.open(i) as src, open(dst, "wb") as f:
                shutil.copyfileobj(src, f)
    if tr is None:
        (wd / f"transcript_zip{h[15:21]}.json").write_text(json.dumps({"segments": [], "language": "es", "solo_acta": True}))
    for v in wd.glob("video.*"):
        pipeline.put_file(v, out / v.name)
    nombre = re.sub(r"( \(con (vídeo|audio)\))?\.zip$", "", zp.name) if not acta.get("titulo") else acta["titulo"]
    (wd / "meta.json").write_text(json.dumps({**meta(wd), "nombre": nombre}, ensure_ascii=False))
    return {"id": wd.name}


@app.post("/api/transcripcion")
def transcripcion(d: dict):
    """Vista previa de una transcripción elegida: formato, nº de segmentos y de hablantes con nombre."""
    p = Path(d.get("path", ""))
    if p.suffix.lower() not in TR_EXT or not p.is_file():
        raise HTTPException(400, "Elige un fichero .vtt, .srt, .txt o .docx")
    try:
        r = transcripts.parse(p)
    except (ValueError, OSError, zipfile.BadZipFile) as e:
        raise HTTPException(400, str(e))
    return {"formato": r["formato"], "segmentos": len(r["segments"]), "hablantes": r["speakers"]}


@app.put("/api/upload")
async def upload(request: Request, name: str):
    """Alternativa al diálogo: arrastrar y soltar. Se escribe a disco por trozos (vídeos de GB)."""
    UPLOADS.mkdir(exist_ok=True)
    dest = UPLOADS / Path(name).name
    with open(dest, "wb") as f:
        async for chunk in request.stream():
            f.write(chunk)
    return {"path": str(dest)}


# ---------- Reuniones ----------
def _solo_acta(mid, asr):
    try:
        return bool(json.loads((pipeline.WORK / Path(mid).name / f"transcript_{asr}.json").read_text()).get("solo_acta"))
    except (OSError, ValueError):
        return False


def meta(wd):
    """work/<id>/meta.json: {"nombre": nombre a mostrar, "carpeta": carpeta}; no se renombra nada en disco."""
    try:
        return json.loads((Path(wd) / "meta.json").read_text())
    except (OSError, ValueError):
        return {}


def resumen(wd):
    """(nº de actas, duración en s) de una reunión: la duración sale del acta.json de la primera acta que la tenga."""
    ds = [d for d in wd.glob("acta_*_*") if (d / "index.html").exists()]
    for d in ds:
        try:
            return len(ds), json.loads((d / "acta.json").read_text()).get("duracion") or 0
        except (OSError, ValueError):
            pass
    return len(ds), 0


def meetings():
    out, res = [], {}
    for tf in sorted(pipeline.WORK.glob("*/transcript_*.json"), key=os.path.getmtime, reverse=True):
        v = next(tf.parent.glob("video.*"), None)
        asr = tf.stem.split("_", 1)[1]
        tj = json.loads(tf.read_text()) if asr.startswith(("imp", "zip")) else {}
        imp = tj.get("importada")
        mt = meta(tf.parent)
        base = mt.get("nombre") or (v.resolve().name if v else imp["fuente"] if imp else tf.parent.name)
        out.append({"sel": f"{tf.parent.name}|{asr}", "id": tf.parent.name, "asr": asr, "mtime": int(tf.stat().st_mtime),
                    "label": base, "nombre": mt.get("nombre", ""), "carpeta": mt.get("carpeta", ""), "sin": bool(tj.get("solo_acta")),
                    **dict(zip(("actas", "dur"), res.setdefault(tf.parent.name, resumen(tf.parent)))),
                    "name": base + (" (transcripción importada)" if imp and v else "" if asr == "rápido" or imp or asr.startswith("zip") else " (calidad)"),
                    "video": f"/files/{tf.parent.name}/{v.name}" if v else None})
    seen = {}  # dos reuniones no se llaman igual: la más antigua se queda el nombre, las demás llevan « (2)», « (3)»…
    for e in reversed(out):
        lab, n = e["label"], 1
        while seen.setdefault(lab.casefold(), e["id"]) != e["id"]:
            n += 1
            lab = f"{e['label']} ({n})"
        e["name"], e["label"] = lab + e["name"][len(e["label"]):], lab
    return out


@app.get("/api/meetings")
def get_meetings():
    return meetings()


@app.post("/api/meta")
def set_meta(d: dict):
    """Nombre y/o carpeta de una reunión (cadena vacía = quitar). {version: carpeta del acta, vnombre} renombra una versión del acta."""
    wd = pipeline.WORK / Path(d.get("id") or "").name
    if not wd.is_dir():
        raise HTTPException(404, "Reunión no encontrada")
    m = meta(wd)
    nom = str(d.get("nombre") or "").strip()[:120]
    if nom and any(e["id"] != wd.name and e["label"].casefold() == nom.casefold() for e in meetings()):
        raise HTTPException(409, f"Ya hay otra reunión llamada «{nom}»")
    for k in ("nombre", "carpeta"):
        if k in d:
            v = str(d[k] or "").strip()[:120]
            m.pop(k, None) if not v else m.__setitem__(k, v)
    if d.get("version"):
        v, n = Path(d["version"]).name, str(d.get("vnombre") or "").strip()[:60]
        if not (wd / v / "index.html").exists():
            raise HTTPException(404, "Acta no encontrada")
        vs = m.setdefault("versiones", {})
        vs.pop(v, None) if not n else vs.__setitem__(v, n)
        m.pop("versiones") if not vs else None
    (wd / "meta.json").write_text(json.dumps(m, ensure_ascii=False))
    return m


CARPETAS = pipeline.WORK / "carpetas.json"  # carpetas creadas aunque aún no tengan reuniones


def carpetas_vacias():
    try:
        return json.loads(CARPETAS.read_text())
    except (OSError, ValueError):
        return []


@app.get("/api/carpetas")
def get_carpetas():
    return sorted({*carpetas_vacias(), *(meta(f.parent).get("carpeta") for f in pipeline.WORK.glob("*/meta.json"))} - {None, ""}, key=str.casefold)


@app.post("/api/carpeta")
def carpeta(d: dict):
    """Crear (sin nombre), renombrar (nuevo) o borrar (sin nuevo) una carpeta: solo toca los meta.json; las reuniones nunca se borran."""
    old, new = (d.get("nombre") or "").strip(), (d.get("nuevo") or "").strip()[:120]
    pipeline.WORK.mkdir(exist_ok=True)
    CARPETAS.write_text(json.dumps(sorted(({*carpetas_vacias(), new} if new else {*carpetas_vacias()}) - {old, ""}), ensure_ascii=False))
    for f in pipeline.WORK.glob("*/meta.json"):
        m = meta(f.parent)
        if m.get("carpeta") == old:
            m.pop("carpeta") if not new else m.__setitem__("carpeta", new)
            f.write_text(json.dumps(m, ensure_ascii=False))
    return {}


def _stream_zip(files):
    """Zip sin compresión (el mp4 ya viene comprimido) generado al vuelo por una tubería: sin segunda copia en disco."""
    r, w = os.pipe()

    def write():
        try:
            with os.fdopen(w, "wb") as out, zipfile.ZipFile(out, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
                for src, arc in files:
                    z.write(src, arc)
        except OSError:  # el cliente cortó la descarga
            pass
    threading.Thread(target=write, daemon=True).start()
    try:
        while chunk := os.read(r, 1 << 20):
            yield chunk
    finally:
        os.close(r)  # si el cliente corta, el hilo escritor recibe BrokenPipe y termina


@app.get("/api/zipvideo/{mid}/{acta}")
def zipvideo(mid: str, acta: str):
    """Acta + vídeo (o audio) donde el reproductor del informe lo espera (video.<ext> junto a index.html)."""
    wd = pipeline.WORK / Path(mid).name
    out, v = wd / Path(acta).name, next(wd.glob("video.*"), None)
    if not (out / "index.html").exists() or not v or not v.exists():
        raise HTTPException(404, "Sin acta o sin vídeo")
    files = [(f, f.relative_to(out)) for f in out.rglob("*") if f.is_file() and f.name != v.name] + [(v, v.name)] + [(t, "transcript.json") for t in wd.glob(f"transcript_{Path(acta).name.split('_')[2]}.json")]
    name = (meta(wd).get("nombre") or v.resolve().stem) + (" (con audio).zip" if es_audio(v) else " (con vídeo).zip")
    return StreamingResponse(_stream_zip(files), media_type="application/zip",
                             headers={"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(name)})


@functools.lru_cache(maxsize=64)
def _es_audio(path, mtime):
    return not pipeline.has_video(path)


def es_audio(v):
    try:
        return _es_audio(str(v), v.stat().st_mtime_ns)
    except OSError:
        return False


def _calidad(name):
    return next((q for q in pipeline.NIVELES if name.endswith("_" + q)), "rápida")


@app.get("/api/meeting/{mid}")
def meeting(mid: str):
    wd = pipeline.WORK / Path(mid).name
    actas = [{"name": d.name, "nivel": d.name.split("_")[1], "asr": d.name.split("_")[2], "calidad": (q := _calidad(d.name)), "sin": _solo_acta(wd.name, d.name.split("_")[2]), "fondo": (d / "acta.json").exists() and bool(json.loads((d / "acta.json").read_text()).get("fondo")), "url": f"/files/{wd.name}/{d.name}/index.html",
              "zip": next((f"/files/{wd.name}/{z.name}" for z in wd.glob(f"acta_*_{d.name.split('_', 1)[1].split('_')[0]}{("_" + q) * (q != "rápida")}.zip")), None)}
             for d in sorted(wd.glob("acta_*_*")) if (d / "index.html").exists()]
    if not actas:
        raise HTTPException(404, "Sin actas")
    rec = {c.stem.split("_", 1)[1]: pipeline.recommend_pct(json.loads(c.read_text())) for c in wd.glob("cortes_*.json")}
    conds = [{"name": c.name, "url": f"/files/{wd.name}/{c.name}"} for c in sorted(wd.glob("condensado_*")) if c.suffix in (".mp4", ".m4a")]
    imp = {f.stem.split("_", 1)[1]: json.loads(f.read_text())["importada"] for f in wd.glob("transcript_imp*.json")}
    return {"id": wd.name, "actas": actas, "recomendado": rec, "condensados": conds, "video": any(wd.glob("video.*")), "audio": any(es_audio(v) for v in wd.glob("video.*")), "videourl": next((f"/files/{wd.name}/{v.name}" for v in wd.glob("video.*")), None), "versiones": meta(wd).get("versiones", {}), "importadas": imp,
            "videomb": next((round(v.stat().st_size / 1e6) for v in wd.glob("video.*") if v.exists()), 0), **{k: meta(wd).get(k, "") for k in ("nombre", "carpeta")}}


@app.get("/files/{mid}/{path:path}")
def files(mid: str, path: str):
    """work/<hash>/...: FileResponse sirve Range (el <video> puede saltar) y sigue enlaces simbólicos (vídeo en otro disco)."""
    parts = Path(mid, path).parts
    f = pipeline.WORK.joinpath(*parts)
    if ".." in parts or not f.is_file():
        raise HTTPException(404)
    return FileResponse(f)


# ---------- Preguntar ----------
who = lambda s: (s["spk"] + ": " if s.get("spk") else "") + s["text"]  # con nombres (transcripción importada) las citas dicen quién habla


def indice(sel):
    """Índice RAG de una reunión ("id|asr") o de una carpeta ("c:nombre": la última transcripción de cada reunión de la carpeta)."""
    if sel.startswith("c:"):
        es = list({e["id"]: e for e in reversed(meetings()) if e["carpeta"] == sel[2:] and not e["sin"]}.values())
        if not es:
            raise HTTPException(400, "Carpeta vacía")
        key = "c:" + repr([(e["sel"], e["label"]) for e in es])
        if key not in _idx:
            _idx[key] = rag.Multi([(e["label"], e["video"], indice(e["sel"])) for e in es])
        return _idx[key]
    if sel not in _idx:
        wd, asr = sel.split("|")
        _idx[sel] = rag.Index(str(pipeline.WORK / Path(wd).name), asr, THREADS)
    return _idx[sel]


@app.post("/api/preguntar")
def preguntar(d: dict):
    sel, q = d.get("sel"), (d.get("q") or "").strip()
    if not sel or not q:
        raise HTTPException(400, "Elige una reunión y escribe la pregunta")
    if any(e["state"] == "marcha" for e in cola):
        raise HTTPException(409, "Hay un trabajo en marcha: espera a que termine")
    falta(d, "preguntar")
    if not sel.startswith("c:") and _solo_acta(*sel.split("|")):
        raise HTTPException(400, "Esta acta se importó sin transcripción: no se puede preguntar sobre ella")

    def events():
        line = lambda **k: json.dumps(k, ensure_ascii=False) + "\n"
        try:
            idx = indice(sel)
            multi = idx.multi
            inf = (lambda i: {"n": idx.names[idx.segs[i]["m"]], "v": idx.vids[idx.segs[i]["m"]]}) if multi else (lambda i: {})  # carpeta: reunión y vídeo de cada tramo
            gpu = pipeline.use_gpu(d.get("gpu"))
            if _llm.get("gpu") not in (None, gpu):  # cambió la casilla: otro servidor (solo uno a la vez en la GPU)
                parar_llm()
            if not _llm.get("url"):
                yield line(k="arranque")
                _llm["url"], _llm["proc"] = rag.server(THREADS, gpu=gpu)
                _llm["gpu"] = gpu
            for kind, v in rag.answer(idx, q, _llm["url"]):
                if pipeline.NOTICE:
                    yield line(k="aviso", text=pipeline.NOTICE.pop())
                if kind == "candidatos":
                    yield line(k="candidatos", items=[{"t": idx.segs[i]["s"], "text": who(idx.segs[i])[:200], **inf(i)} for i in v])
                elif kind == "frase":
                    s = idx.segs[v["i"]]
                    refs = v.get("refs", [v["i"]])  # estilo interpretativo: puede citar varios tramos
                    yield line(k="frase", t=s["s"], **inf(v["i"]), ok=v["ok"], text=v["frase"] if v["ok"] else v["cita"], kind=v.get("kind", "dijo"),
                               mas=[{"t": idx.segs[j]["s"], **inf(j)} for j in refs[1:]],
                               cita=[{"t": idx.segs[j]["s"], "text": who(idx.segs[j]), "main": j in refs, **inf(j)} for j in dict.fromkeys(k for r in refs for k in idx.window(r))])
                elif kind == "nada":
                    yield line(k="nada", text=rag.NOT_SAID)
        except Exception as e:
            yield line(k="error", text=str(e))
        yield line(k="fin")
    return StreamingResponse(events(), media_type="application/x-ndjson")


# ---------- Ciclo de vida ----------
@app.post("/api/latido")
def latido():
    beat[0] = time.time()


@app.get("/api/modelos")
def get_modelos():
    return models.status()


@app.post("/api/modelos")
def bajar_modelos(d: dict | None = None):
    """Instala esenciales + los modelos elegidos {ids:[...]}; sin ids, los recomendados."""
    models.start((d or {}).get("ids"))
    return models.status()


@app.get("/api/modelos/encontrados")
def modelos_encontrados():
    return {"encontrados": models.escanear(), "config": json.loads(pipeline.MODELOS.read_text()) if pipeline.MODELOS.exists() else {}}


@app.post("/api/modelos/usar")
def usar_modelo(d: dict):
    """{ruta, nivel: calidad | "pers" | "", nombre?}"""
    if not models.usar(d.get("ruta", ""), d.get("nivel", ""), d.get("nombre", "")):
        raise HTTPException(400, "Elige un fichero .gguf")
    return modelos_encontrados()


@app.post("/api/modelos/borrar")
def borrar_modelo(d: dict):
    if not models.borrar(d.get("id", "")):
        raise HTTPException(400, "No se puede borrar ese modelo")
    return models.status()


if os.environ.get("ACTAS_MODELOS") == "recomendados":  # instalación sin interfaz (CI): sin elegir
    models.start()


@app.get("/api/ping")
def ping():
    return "actas"


app.mount("/", StaticFiles(directory=STATIC, html=True))


def vivo():
    """URL de otra instancia en marcha (el lock guarda su puerto), o None."""
    try:
        url = f"http://127.0.0.1:{int(LOCK.read_text())}"
        return url if urllib.request.urlopen(url + "/api/ping", timeout=2).read() == b'"actas"' else None
    except (OSError, ValueError):
        return None


if __name__ == "__main__":
    pipeline.WORK.mkdir(exist_ok=True)
    if sys.stdout is None:  # pythonw (Windows, sin consola): uvicorn y print necesitan un destino
        sys.stdout = sys.stderr = open(pipeline.WORK / "app.log", "a", encoding="utf-8")
    if url := vivo():
        os.environ.get("ACTAS_NO_BROWSER") or webbrowser.open(url)
        sys.exit()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    procs.cleanup_stale()
    LOCK.write_text(str(port))
    atexit.register(lambda: LOCK.unlink(missing_ok=True))
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))

    def vigila():
        while time.time() - beat[0] < (IDLE_JOB if any(e['state'] in ACTIVOS for e in cola) else IDLE):
            time.sleep(2)
        srv.should_exit = True
    threading.Thread(target=vigila, daemon=True).start()
    kick()  # retoma lo que quedó pendiente
    if not os.environ.get("ACTAS_NO_BROWSER"):  # CI/pruebas sin navegador
        threading.Timer(1, webbrowser.open, [f"http://127.0.0.1:{port}"]).start()
    procs.on_signal(lambda: setattr(srv, "should_exit", True))
    srv.run()
