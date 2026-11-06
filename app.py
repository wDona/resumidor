"""Interfaz web local (FastAPI + página estática): vídeo -> acta HTML, vídeo condensado y preguntas. `uv run app.py`."""

import atexit
import base64
import contextlib
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
from collections import Counter
import urllib.parse
import urllib.request
import uuid
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

import models
import nube
import pipeline
import buscar
import carpetas
import correo
import documentos
import msgraph
import dudas
import enlaces
import export_registro
import exportar
import destinos
import agentes
import investigacion
import mcp_servidor
import vigiladas
import grabar
import plantillas
import poblar
import preguntar_reg
import privacidad
import procs
import registro
import servidor
import rag
import transcripts
import vision

THREADS = int(os.environ.get("ACTAS_THREADS", pipeline.PHYS))
STATIC, LOCK, COLA = pipeline.ROOT / "static", (pipeline.WORK if os.environ.get("ACTAS_WORK") else pipeline.ROOT) / ".actas.lock", pipeline.WORK / "cola.json"
UPLOADS = pipeline.ROOT / "uploads"
SUBIR_MAX = 50 << 20  # /api/subir: documentos, no vídeos
TR_EXT = (".vtt", ".srt", ".txt", ".docx")
AUDIO = (".mp3", ".m4a", ".wav", ".ogg", ".opus", ".flac", ".aac")
IDLE = 60  # s sin latido de la página y el servidor se cierra
IDLE_JOB = 180  # ídem con un trabajo en marcha (recarga o vuelta de la pestaña)
PUERTO = 47320  # puerto por defecto de la app local
app = FastAPI()
app.include_router(destinos.router)
app.router.on_startup.append(destinos.iniciar)  # planificador de envíos programados (un hilo)
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
    COLA.write_text(json.dumps(cola, ensure_ascii=False), encoding="utf-8")


try:  # reinicio: lo que estaba en marcha ya no tiene hilo (se puede reintentar); lo pendiente sigue en cola
    cola[:] = json.loads(pipeline.leer_texto(COLA))
    for e in cola:
        if e["state"] == "marcha":
            e.update(state="interrumpido", error="El trabajo se interrumpió al cerrar la aplicación")
except (OSError, ValueError):
    pass


# ---------- Modelos en la nube (opcionales; nube.py) ----------
def _nube_spec(d, tpl=None):
    """Si el trabajo pide nube: la valida (visible en Ajustes, plantilla que la permite, primera vez confirmada, clave o CLI) y deja en d["nube"]
    la configuración normalizada (sin clave). Sin d["nube"] no hace nada."""
    if not d.get("nube"):
        d.pop("nube", None)
        return None
    ok, why = nube.permitida(tpl, _ajustes())
    if not ok:
        raise HTTPException(403, why)
    try:
        cfg = nube.norm(d["nube"])
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    p = cfg["proveedor"]
    if servidor.ACTIVO and p.startswith("cli:"):
        raise HTTPException(400, "En el servidor no hay CLIs de IA: usa un proveedor con clave")
    if p not in nube.estado()["confirmado"]:
        raise HTTPException(409, {"msg": "Confirma antes el envío de texto a este proveedor", "confirmar": p})
    if p.startswith("cli:"):
        if not nube.cli_ruta(p[4:]):
            raise HTTPException(400, f"No se encuentra {nube.CLIS[p[4:]][0]} en este equipo")
    elif not nube.clave(p) and p != "propio":
        raise HTTPException(400, f"Falta la clave de {nube.PROV[p][0]}")
    d["nube"] = cfg
    return cfg


def _tpl_de(mid):
    """Plantilla de la última versión de la reunión (para saber si admite la nube)."""
    try:
        f = max((pipeline.WORK / Path(mid).name).glob("acta_*/acta.json"), key=lambda x: x.stat().st_mtime)
        n = json.loads(f.read_text(encoding="utf-8")).get("plantilla")
        return next((t for t in plantillas.todas() if t["nombre"] == n), None) if n else None
    except (ValueError, OSError):
        return None


@app.get("/api/nube")
def get_nube():
    a = _ajustes() or AJ_DEF
    return {**nube.info(), "visible": bool(a.get("nube_visible", True)), "anonimizar_defecto": bool(a.get("anonimizar_defecto"))}


@app.post("/api/nube/clave")
def nube_clave(d: dict):
    """Guarda la clave en el llavero del sistema (vacía = la borra). Nunca se devuelve: solo enmascarada."""
    if d.get("proveedor") not in nube.PROV:
        raise HTTPException(400, "Proveedor no válido")
    try:
        nube.poner_clave(d["proveedor"], str(d.get("clave") or ""))
    except RuntimeError as ex:
        raise HTTPException(400, str(ex))
    return nube.info()


@app.post("/api/nube/url")
def nube_url(d: dict):
    p, u = d.get("proveedor"), str(d.get("url") or "").strip().rstrip("/")
    if p not in nube.PROV or u and not u.startswith(("https://", "http://")):
        raise HTTPException(400, "Dirección no válida")
    nube.guardar(urls={**nube.estado()["urls"], p: u})
    return nube.info()


@app.post("/api/nube/modelos")
def nube_modelos(d: dict):
    """Lista los modelos del proveedor (GET /models con su clave); lista vacía = escribir el nombre a mano."""
    return {"modelos": nube.modelos(d.get("proveedor"), str(d.get("url") or "").strip() or None)}


@app.post("/api/nube/confirmar")
def nube_confirmar(d: dict):
    p = d.get("proveedor")
    if p not in nube.PROV and p not in [c["id"] for c in nube.detectar_clis()]:
        raise HTTPException(400, "Proveedor no válido")
    e = nube.estado()
    nube.guardar(confirmado=sorted({*e["confirmado"], p}), modelos={**e["modelos"], **({p: str(d["modelo"])[:100]} if d.get("modelo") else {})})
    return nube.info()


@app.post("/api/nube/precios")
def nube_precios(d: dict):
    """Precio editable por modelo (USD por millón de tokens: entrada, salida); vacío lo quita."""
    m = str(d.get("modelo") or "").strip()[:100]
    if not m:
        raise HTTPException(400, "Falta el modelo")
    pr = dict(nube.estado()["precios"])
    try:
        pr[m] = [float(d["entrada"]), float(d["salida"])]
    except (KeyError, TypeError, ValueError):
        pr.pop(m, None)
    nube.guardar(precios=pr)
    return nube.info()


@app.post("/api/nube/estimar")
def nube_estimar(d: dict):
    """Tokens (y coste si hay precio) antes de ejecutar: de los caracteres, de los minutos de la reunión (~900 car./min) o de la transcripción."""
    ch = int(d.get("chars") or 0) or int(float(d.get("minutos") or 0) * 900)
    if not ch and d.get("reuse"):
        tf = pipeline.WORK / Path(d["reuse"]).name / f"transcript_{d.get('asr', 'calidad')}.json"
        ch = sum(len(x["text"]) for x in json.loads(tf.read_text(encoding="utf-8"))["segments"]) if tf.is_file() else 0
    if not ch and d.get("video") and Path(d["video"]).is_file():
        ch = int(pipeline.duration(Path(d["video"])) / 60 * 900)
    if not ch and d.get("transcripcion") and Path(d["transcripcion"]).is_file():
        ch = Path(d["transcripcion"]).stat().st_size
    if not ch:
        raise HTTPException(400, "Sin datos para estimar: elige antes el vídeo o la transcripción")
    return nube.estimar(ch, {"modelo": str(d.get("modelo") or "")})


# ---------- LLM compartido por «Preguntar» ----------
_llm, _idx = {}, {}


def parar_llm():
    if _llm.get("proc"):
        _llm.pop("proc").terminate()
    _llm.clear()


atexit.register(parar_llm)
atexit.register(rag.emb_stop)
atexit.register(lambda: grabar.activa() and grabar.activa().parar())  # queda en «Recuperar grabación»


# ---------- Cola de trabajos (uno a la vez: la GPU no admite dos) ----------
def start(kind, spec, video, mid=""):
    sp = spec if isinstance(spec, dict) else {}
    servidor.ia_local(sp.get("nube"), sin_llm=bool(sp.get("buscable") or sp.get("tal_cual")))  # en el servidor, solo nube o sin LLM
    with jlock:
        e = {"id": uuid.uuid4().hex[:8], "kind": kind, "spec": spec, "video": video, "mid": mid, "state": "pendiente", "t": time.time()}
        cola.append(e)
        guardar()
    kick()
    return {"id": e["id"]}


aux = {"on": False, "espera": 0}  # tarea suelta con LLM (anonimizar, correo): excluyente con la cola y con «Preguntar»


@contextlib.contextmanager
def gpu_exclusiva():
    """Espera a que no haya trabajo en marcha, para el LLM del chat y retiene la GPU (un solo modelo a la vez); al salir reanuda la cola."""
    servidor.ia_local()
    with jlock:
        aux["espera"] += 1
    try:
        while True:
            with jlock:
                if not aux["on"] and not any(e["state"] == "marcha" for e in cola):
                    aux["on"] = True
                    break
            time.sleep(1)
    finally:
        with jlock:
            aux["espera"] -= 1
    try:
        parar_llm()
        yield
    finally:
        aux["on"] = False
        kick()


@app.get("/api/aux")
def get_aux():
    return {"estado": "ejecutando" if aux["on"] else "esperando" if aux["espera"] else ""}


def kick():
    """Arranca el siguiente pendiente si no hay ninguno en marcha (se llama al encolar y al terminar cada trabajo)."""
    with jlock:
        if aux["on"]:
            return
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
            with contextlib.suppress(Exception):  # índice de Buscar al día (si falla, se pone al día en la siguiente búsqueda)
                buscar.sincronizar(meetings())
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


def _doc(pid):
    """Cómo se llama lo que genera la plantilla («acta», «apuntes»…), para la interfaz."""
    try:
        return plantillas.get(pid)["documento"]["singular"]
    except (ValueError, KeyError, TypeError):
        return "documento"


@app.get("/api/cola")
def get_cola():
    items = [{k: v for k, v in e.items() if k != "spec"} | {"doc": _doc(e["spec"].get("plantilla"))} for e in cola]
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
    return {
        **pipeline.gpu_info(),
        "ram_gb": pipeline.ram_gb(),
        "chat_gpu": rag.chat_choice(True),
        "chat_cpu": rag.chat_choice(False),
        "llm": pipeline.llm_label(),
        "niveles": niveles(),
    }


def niveles():
    """Calidades del acta (de serie + personalizadas) con su modelo, estado en este equipo (ok/aviso/no), si está instalado y su tamaño."""
    out = []
    for q, n in pipeline.NIVELES.items():
        m, path = "rápida" if q == "alta" else q, pipeline.acta_model(q)
        inst, pers = bool(path and path.is_file()), q in pipeline.PERS or q in pipeline.OVER
        size = path.stat().st_size if inst else models.tam(m)
        e, need = pipeline.evaluar(size, n[1])
        out.append(
            {
                "id": q,
                "nombre": n[0],
                "modelo": pipeline.llm_label(path) if pers else models.CAT[m][0] if m in models.CAT else n[0],
                "tiempo": n[2],
                "m": m,
                "estado": e,
                "instalado": inst,
                "bytes": size,
                "necesita": round(need, 1),
                "pers": pers,
            }
        )
    return out


def falta(d, accion, video=True):
    """409 con lo que falta instalar (la interfaz abre Modelos con ese aviso). Con nube no hace falta el modelo redactor local."""
    txt, ids = models.faltan(accion, d.get("calidad") or ("alta" if d.get("alta") else "rápida"), video, bool(d.get("nube")))
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
        return f"No se pudieron leer las sesiones de {b}: ciérralo del todo y reintenta" + (
            ", o prueba con Firefox (Chrome y Edge suelen bloquear esto en Windows)" if nav != "firefox" else ""
        )
    if "unsupported url" in t:
        return "Enlace no compatible: no se encontró ningún vídeo ni audio en esa dirección"
    if any(
        x in t
        for x in (
            "http error 401",
            "http error 403",
            "sign in",
            "log in",
            "login",
            "private",
            "members-only",
            "members only",
            "confirm you",
            "not a bot",
            "forbidden",
            "authentication",
            "age-restricted",
            "permission",
        )
    ):
        return (
            f"Sin permiso: el enlace no es público. Inicia sesión en ese sitio con {b} y elígelo arriba, o descárgalo a mano"
            if nav
            else "Sin permiso: el enlace no es público. Inicia sesión en ese sitio con tu navegador y elígelo arriba en «Usar sesión del navegador», o descárgalo a mano"
        )
    if any(
        x in t
        for x in ("http error 404", "http error 410", "not found", "removed", "no longer available", "unavailable", "expired", "does not exist", "deleted")
    ):
        return "El enlace ya no existe: no se encuentra, lo han quitado o ha caducado"
    if any(x in t for x in ("urlopen", "name or service", "name resolution", "timed out", "connection", "network", "getaddrinfo", "unable to download", "ssl")):
        return "Error de red: no se pudo descargar. Revisa la conexión a internet y reintenta"
    return (
        "No se pudo descargar el enlace: "
        + re.sub(r"^(ERROR: )?(\[[^\]]+\] )?", "", str(ex).strip().splitlines()[0] if str(ex).strip() else type(ex).__name__)[:200]
    )


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

    opts = {
        "outtmpl": str(dest / "%(title).80B.%(ext)s"),
        "windowsfilenames": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [hook],
        "format": "bestaudio/best" if solo_audio else "bv*+ba/b",
        "format_sort": ["res:1080", "ext"],
        "retries": 3,
        "socket_timeout": 30,
        "color": "never",
    }
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


def resolver_enlace(url, solo_audio, nav, cb):
    """Enlace inteligente -> ("media", ruta) | ("doc", ruta): extractor propio de yt-dlp = vídeo/audio; fichero directo o página = documento
    (mismo camino que una subida). Nubes de Microsoft: yt-dlp una vez y, si falla, un mensaje con la salida práctica."""
    import tempfile

    red = bool((_ajustes() or {}).get("enlaces_red_local"))
    try:
        enlaces.comprobar(url, red)
    except ValueError as ex:
        raise RuntimeError(str(ex)) from None
    if enlaces.es_microsoft(url):
        try:
            return "media", descargar(url, solo_audio, nav, cb)
        except RuntimeError as ex:
            raise RuntimeError(
                "No se pudo bajar este enlace de OneDrive/SharePoint/Teams/Stream (suele pedir iniciar sesión). Usa la carpeta de OneDrive "
                "sincronizada en tu equipo, o descarga el fichero a mano y súbelo. Detalle: " + str(ex)
            ) from None
    if enlaces.especifico(url):
        return "media", descargar(url, solo_audio, nav, cb)
    (UPLOADS / "enlaces").mkdir(parents=True, exist_ok=True)
    dest = tempfile.mkdtemp(dir=UPLOADS / "enlaces")
    try:
        k, f = enlaces.traer(url, dest, cb, red)
    except ValueError as ex:
        raise RuntimeError(str(ex)) from None
    except (OSError, urllib.error.URLError) as ex:  # HTTPError y timeouts incluidos
        raise RuntimeError(error_descarga(ex, nav)) from None
    return ("media" if f.suffix.lower() in enlaces.MEDIA else "doc"), f


def _acta_fn(d):
    video, tr, url = Path(d.get("video") or ""), d.get("transcripcion") or "", (d.get("enlace") or "").strip()
    video = video if video.is_file() else None
    names = {n: v.strip() for n, v in re.findall(r"[Hh]ablante\s*(\d+)\s*=\s*([^,;\n]+)", d.get("nombres") or "")}
    nivel, asr, calidad, reuse = d.get("nivel", "normal"), d.get("asr", "calidad"), d.get("calidad", "rápida"), d.get("reuse")
    carp0 = str(d.get("carpeta") or "").strip()[:120] or (meta(pipeline.WORK / Path(reuse).name).get("carpeta", "") if reuse else "")

    tc = bool(d.get("tal_cual"))  # «Ya está hecho, no resumir»: el documento es el acta tal cual (sin LLM); se indexa y poblar extrae sus ítems con cita
    bus = bool(d.get("buscable")) or tc  # «solo buscable»: sin LLM ni acta; seguimiento y poblar tampoco (tal_cual sí puebla)

    def fn(cb):
        dl, tmp, tr = None, None, d.get("transcripcion") or ""
        if url:  # la descarga es la 1.ª fase del trabajo; luego sigue el proceso normal con el fichero bajado
            k, f = resolver_enlace(url, bool(d.get("solo_audio")), d.get("navegador") or "", cb)
            if f.suffix.lower() == ".zip":  # lote o acta exportada: como subir el zip
                r = lote({**d, "enlace": "", "video": ""}, f)
                shutil.rmtree(f.parent, ignore_errors=True)
                return {**r, "id": (r.get("ids") or [r.get("id")])[0]}
            if k == "media":
                dl = f
            else:
                tr, tmp = str(f), f.parent
        out, _, _ = pipeline.run(
            dl or video,
            nivel,
            asr,
            THREADS,
            cb,
            names,
            bool(d.get("hablantes")),
            tr or None,
            calidad,
            d.get("gpu"),
            reuse=(Path(reuse).name, asr) if reuse else None,
            plantilla=d.get("plantilla") or None,
            idioma=d.get("idioma") or carpetas.leer(carp0)["ajustes"]["idioma"] or None,
            habla=d.get("habla") or None,
            glosario=carpetas.terminos_prompt(carp0) or None,
            pistas=d.get("pistas") or None,
            nube=d.get("nube"),
            descripcion=str(d.get("descripcion") or "").strip()[:2000],
            buscable=bus,
            vision=vision.elegir(_ajustes(), d.get("nube")) if tr and documentos.tipo(tr) == "imagen" else None,
        )  # glosario e idioma de la carpeta (vacíos: nada cambia)
        wd = out if bus else out.parent
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
        ver = documentos.acta_tal_cual(wd, d.get("nombre_acta")) if tc else out.name
        if url:
            (wd / "meta.json").write_text(json.dumps({**meta(wd), "url": url}, ensure_ascii=False), encoding="utf-8")
        if tc:
            (wd / "meta.json").write_text(json.dumps({**meta(wd), "tal_cual": True}, ensure_ascii=False), encoding="utf-8")
        if dl and not any(m.is_symlink() for m in wd.glob("video.*")):  # ya hay enlace duro/copia en la reunión
            shutil.rmtree(dl.parent, ignore_errors=True)
        if (carp := str(d.get("carpeta") or "").strip()[:120]) and not meta(wd).get("carpeta"):  # carpeta pedida al generar
            (wd / "meta.json").write_text(json.dumps({**meta(wd), "carpeta": carp}, ensure_ascii=False), encoding="utf-8")
        if not bus and (_ajustes() or {}).get("describir_capturas") and (vc := vision.elegir(_ajustes(), d.get("nube"))):
            try:  # «Describir capturas con IA»: las que lleva el documento; un fallo no estropea el documento
                vision.capturas(out, vc, cb)
            except Cancelado:
                raise
            except Exception as ex:
                print("describir capturas:", ex, flush=True)
        if carp0 and not reuse and not bus:  # seguimiento: ¿el documento nuevo cierra o cambia pendientes abiertos de la carpeta? (propone; nunca cierra)
            cb(0.99, "Revisando los pendientes de la carpeta…")
            try:
                carpetas.seguimiento(carp0, _ms(carp0), wd.name, _llm_ctx(d, [m["id"] for m in _ms(carp0)], carpetas.terminos_prompt(carp0)), THREADS)
            except Cancelado:
                raise
            except Exception as ex:  # el documento ya está hecho: un fallo del seguimiento no lo estropea (se puede repetir desde Pendientes)
                print("seguimiento:", ex, flush=True)
        pob = bool(
            carp0
            and (tc or not bus)
            and (_ajustes() or AJ_DEF).get("poblar_auto", True)
            and _tipo_carpeta(carp0).casefold() == "proyecto"
            and not (d.get("nube") and not nube.permitida(_tpl_de(wd.name), _ajustes())[0])
        )  # F3b: solo carpetas «Proyecto» (nunca sensibles): la IA puebla las vistas del proyecto (trabajo aparte en la cola, tras este)
        if pob:
            start(
                "poblar",
                {
                    **{k: d[k] for k in ("nube", "calidad", "alta", "gpu") if d.get(k)},
                    "c": carp0,
                    "mid": wd.name,
                    "auto": True,
                    **({"vistas": [*poblar.VISTAS, "tareas"]} if tc else {}),
                    **({"plan": d["plan"]} if d.get("plan") is not None else {}),
                },
                carp0,
                wd.name,
            )
        if tc or not bus:  # «solo buscable» no extrae nada: no hay qué enviar
            destinos.tras_documento(wd.name, ver, d.get("plan"), pob)  # envíos/recetas: hilo aparte, nunca rompe el trabajo
        if d.get("grabacion"):  # grabación: ya hay transcripción y medio en la reunión; fuera las pistas
            grabar.limpiar(pipeline.WORK / "grabaciones" / Path(d["grabacion"]).name)
        return {"id": wd.name, "acta": ver if tc else None if bus else out.name}

    return fn


def _tipo_carpeta(c):
    """Etiqueta de tipo de la carpeta (la del expediente, la de su perfil o el nombre general de ajustes)."""
    return carpetas.tipo_de(carpetas.leer(c), _carpetas()["plantillas"].get(c), ((_ajustes() or AJ_DEF)["nombres"]).get("carpeta"))


def _llm_ctx(d, mids=(), glos=()):
    """Contexto de un LLM de los actas (el nivel elegido) para las pasadas cortas sobre una carpeta."""
    calidad = d.get("calidad") or ("alta" if d.get("alta") else "rápida")
    if d.get("nube"):  # corre dentro de un trabajo de la cola: la pasada del modelo local de nombres no coincide con otro LLM
        cfg = nube.con_nombres(d["nube"], [pipeline.WORK / Path(m).name for m in mids], glos)
        return lambda: nube.backend(cfg)
    return lambda: pipeline.llama(THREADS, model=pipeline.acta_model(calidad), gpu=d.get("gpu"), capas=pipeline.MOE.get(calidad, 0))


def _ms(c):
    """Reuniones de una carpeta ("" = sin carpeta), la más reciente primero."""
    return [m for m in meetings() if (m["carpeta"] or "") == c]


def _carpeta_job(op):
    """Trabajos en cola de una carpeta (un solo LLM a la vez): seguimiento | estado | comparar."""

    def mk(d):
        c = d["c"]

        def fn(cb):
            cb(0.05, "Arrancando modelo de lenguaje…")
            ctx = _llm_ctx(d, [m["id"] for m in _ms(c)], carpetas.terminos_prompt(c))
            if op == "seguimiento":
                n = carpetas.seguimiento(c, _ms(c), d["mid"], ctx, THREADS)
                return {"carpeta": c, "sugerencias": n}
            with ctx() as chat:
                cb(0.5, "Redactando…")
                (carpetas.redactar_estado(c, _ms(c), chat) if op == "estado" else carpetas.redactar_comparacion(c, _ms(c), d["a"], d["b"], chat))
            return {"carpeta": c}

        return fn

    return mk


@app.post("/api/generar")
def generar(d: dict):
    """Encola un acta nueva (video/transcripcion) u otra versión de una reunión ya procesada (reuse = id, asr = su transcripción).
    Un documento o imagen en «video» (mismo flujo de soltar/elegir) entra como transcripción (documentos.py); un .zip, como lote.
    buscable: solo transcribir/leer e indexar, sin LLM. descripcion: texto del usuario sobre la imagen o el documento (también buscable)."""
    if (d.get("plan") or {}).get("repetir"):  # «Repetir cada…» de Añadir: una receta programada de la carpeta (una vez, también para lotes)
        try:
            destinos.programar_desde_plan(d["plan"])
        except ValueError as ex:
            raise HTTPException(400, str(ex))
        d = {**d, "plan": {k: x for k, x in d["plan"].items() if k != "repetir"}}
    v = Path(d.get("video") or "")
    if v.suffix.lower() == ".zip" and not d.get("reuse"):
        return lote(d, v)
    if v.suffix.lower() in TR_EXT + documentos.EXT:
        d = {**d, "video": "", "transcripcion": str(v)}
    if d.get("tal_cual") and (
        d.get("reuse") or Path(d.get("video") or "").is_file() or Path(d.get("transcripcion") or "x").suffix.lower() in (".vtt", ".srt", *documentos.IMAGEN)
    ):
        raise HTTPException(400, "«Ya está hecho, no resumir» vale para un documento de texto (Word, PDF, Markdown, texto o HTML) o un enlace a uno")
    video, tr, reuse, url = Path(d.get("video") or ""), d.get("transcripcion") or "", d.get("reuse"), (d.get("enlace") or "").strip()
    if url and not url_valida(url):
        raise HTTPException(400, "El enlace debe empezar por http:// o https://")
    if d.get("navegador") and d["navegador"] not in NAVEGADORES:
        raise HTTPException(400, "Navegador no válido")
    if tr and (Path(tr).suffix.lower() not in TR_EXT + documentos.EXT or not Path(tr).is_file()):
        raise HTTPException(400, "La transcripción debe ser un fichero .vtt, .srt, .txt o .docx (o un documento: PDF, Markdown, HTML, imagen)")
    if reuse:
        if not (pipeline.WORK / Path(reuse).name / f"transcript_{d.get('asr')}.json").exists():
            raise HTTPException(400, "Reunión no encontrada")
        if _solo_acta(reuse, d.get("asr")):
            raise HTTPException(400, "Esta acta se importó sin transcripción: no se puede rehacer")
    elif not (video.is_file() or tr or url):
        raise HTTPException(400, "Elige un vídeo, un audio, un enlace o una transcripción")
    if (
        d.get("nivel", "normal") not in pipeline.LEVELS
        or d.get("asr", "calidad") not in pipeline.ASR_MODELS
        and not reuse
        or d.get("calidad", "rápida") not in pipeline.NIVELES
    ):
        raise HTTPException(400, "Opción no válida")
    try:
        plantillas.get(d.get("plantilla") or None)
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    if (d.get("idioma") or "reunión") not in plantillas.IDIOMAS or (d.get("habla") or "auto") not in ("auto", "mezcla", *pipeline.IDIOMAS):
        raise HTTPException(400, "Idioma no válido")
    _nube_spec(d, plantillas.get(d.get("plantilla") or None))
    n = next(x for x in niveles() if x["id"] == d.get("calidad", "rápida"))
    if n["estado"] == "no" and not d.get("nube") and not d.get("buscable") and not d.get("tal_cual"):
        raise HTTPException(400, f"El nivel «{n['nombre']}» no cabe en este equipo (necesita ~{n['necesita']:.0f} GB de memoria)")
    falta(
        d,
        "buscable" if d.get("buscable") or d.get("tal_cual") else "generar",
        bool(
            video.is_file()
            or url
            and not d.get("tal_cual")
            and (Path(urllib.parse.urlsplit(url).path).suffix.lower() in enlaces.MEDIA or enlaces.es_microsoft(url) or enlaces.especifico(url))
            or reuse
            and next((pipeline.WORK / Path(reuse).name).glob("video.*"), None)
        )
        and not tr,
    )
    r = start(
        "acta",
        d,
        (video if video.is_file() else Path(tr)).name
        if not reuse and not url
        else url[:80]
        if not reuse
        else meta(pipeline.WORK / Path(reuse).name).get("nombre") or Path(reuse).name,
        Path(reuse).name if reuse else "",
    )
    adj = adjuntos_correo(d, v) if v.suffix.lower() in documentos.CORREO and not reuse else []  # tras encolar el correo: si este falla, no entra nada
    return {**r, "adjuntos": adj} if adj else r  # correo: sus adjuntos ya están en la cola, en la misma carpeta


@app.post("/api/fondo")
def fondo(d: dict):
    """Búsqueda a fondo de decisiones y tareas de un acta ya generada: mismo trabajo en cola que generar (un solo LLM a la vez)
    y se rehace el acta en su carpeta."""
    wd, nivel, asr = pipeline.WORK / Path(d.get("id", "")).name, d.get("nivel", "normal"), d.get("asr", "calidad")
    if nivel not in pipeline.LEVELS or not (wd / f"transcript_{asr}.json").exists():
        raise HTTPException(400, "Genera primero el acta")
    if _solo_acta(wd.name, asr):
        raise HTTPException(400, "Esta acta se importó sin transcripción: no se puede buscar a fondo")
    _nube_spec(d)
    falta(d, "fondo")
    return start("fondo", d, wd.name, wd.name)


def _fondo_fn(d):
    wd, nivel, asr = pipeline.WORK / Path(d["id"]).name, d.get("nivel", "normal"), d.get("asr", "calidad")

    def fn(cb):
        out, _, _ = pipeline.run(
            None,
            nivel,
            asr,
            THREADS,
            cb,
            calidad=d.get("calidad") or ("alta" if d.get("alta") else "rápida"),
            gpu=d.get("gpu"),
            fondo=True,
            reuse=(wd.name, asr),
            nube=d.get("nube"),
        )
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


def _poblar_fn(d):
    """F3b: pasada `poblar` (poblar.py) sobre la carpeta d["c"]: solo d["mid"] si viene; d["vistas"]: solo esas."""
    c = d["c"]

    def fn(cb):
        ms = _ms(c)
        r = poblar.poblar(
            c,
            ms,
            _llm_ctx(d, [m["id"] for m in ms], carpetas.terminos_prompt(c)),
            [d["mid"]] if d.get("mid") else None,
            d.get("vistas"),
            carpetas.terminos_prompt(c),
            cb,
            local=not d.get("nube"),
        )
        if r.get("req_nuevos"):  # F5: tras la pasada (automática o «Regenerar con IA»), historias de los requisitos nuevos (trabajo aparte en la cola)
            start(
                "derivar",
                {
                    **{k: d[k] for k in ("nube", "calidad", "alta", "gpu") if d.get(k)},
                    "c": c,
                    "ids": r["req_nuevos"],
                    **({"auto": True} if d.get("auto") else {}),
                },
                c,
            )
        if d.get("mid"):
            if not d.get("sin_recetas"):  # «Añadir a proyecto» sin «enviar también»
                destinos.tras_poblar(c, d["mid"], d.get("plan"))
        return {"carpeta": c, **{k: r[k] for k in ("creadas", "citas", "llamadas")}}

    return fn


def _describir_fn(d):
    """Rehace con IA la descripción de una imagen, o (rehacer) la de las capturas de los documentos de una reunión."""

    def fn(cb):
        wd = pipeline.WORK / d["mid"]
        cfg = vision.elegir(_ajustes(), d.get("nube"))
        if not cfg:
            raise RuntimeError(vision.FALTA)
        cb(0.1, "Describiendo con IA…")
        if _kind(wd) == "imagen":
            with vision.sesion(cfg, THREADS, d.get("gpu")) as desc:
                ia = desc(next(wd.glob("fuente.*")))
            documentos.reescribir(_tr_de(wd), descripcion_ia=ia)
        else:
            (wd / "capturas_ia.json").unlink(missing_ok=True)
            for out in sorted(wd.glob("acta_*_*")):
                if (out / "acta.json").exists():
                    vision.capturas(out, cfg, cb)
        return {"id": wd.name, "acta": None}

    return fn


FNS = {
    "acta": _acta_fn,
    "describir": _describir_fn,
    "fondo": _fondo_fn,
    "condensar": _condensar_fn,
    "poblar": _poblar_fn,
    **{k: _carpeta_job(k) for k in ("seguimiento", "estado", "comparar")},
}


# ---------- Vídeo de entrada ----------
@app.post("/api/pick")
def pick(d: dict = None):
    """Diálogo nativo de Tk en un subproceso (Tk no admite hilos ajenos al principal): devuelve la ruta real, sin copiar.
    {"tipo": "transcripcion"} elige una transcripción en vez de un vídeo."""
    tipo = (
        ("Transcripción", "*" + " *".join(TR_EXT))
        if (d or {}).get("tipo") == "transcripcion"
        else ("Modelo GGUF", "*.gguf")
        if (d or {}).get("tipo") == "modelo"
        else ("Vídeo, audio, documento o imagen", " ".join("*" + x for x in (*MEDIA, *documentos.EXT, ".zip")))
    )
    code = "import tkinter as t, tkinter.filedialog as f\nr=t.Tk(); r.withdraw(); r.attributes('-topmost', True)\n" + (
        "print(f.askdirectory(title='Elegir la carpeta compartida (OneDrive o SharePoint sincronizada)'))"
        if (d or {}).get("tipo") == "carpeta"
        else f"print(f.askopenfilename(title='Elegir {tipo[0].lower()}', filetypes=[{tipo!r}, ('Todos', '*')]))"
    )
    p = subprocess.run([sys.executable, "-X", "utf8", "-c", code], capture_output=True, text=True, encoding="utf-8")
    return {"path": p.stdout.strip()}


ZIP_OK = re.compile(r"index\.html|acta\.json|transcript\.json|video\.[A-Za-z0-9]{2,4}|img/[\w.\-]+")


@app.post("/api/importar")
def importar(d: dict):
    """Importa un acta exportada por la app (zip ligero o «con vídeo»): se valida el zip (solo ficheros esperados, sin rutas fuera,
    tamaños razonables) y se crea una reunión en work/ visible sin modelos. Con transcript.json también se podrá preguntar."""
    zp, carp = Path(d.get("path", "")), str(d.get("carpeta") or d.get("c") or "").strip()[:120]
    if zp.suffix.lower() != ".zip" or not zp.is_file() or not zipfile.is_zipfile(zp):
        raise HTTPException(400, "Elige un .zip de acta exportado por la aplicación")
    with zipfile.ZipFile(zp) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        names = {i.filename for i in infos}
        vid = lambda i: i.filename.startswith("video.")
        if not (infos and {"index.html", "acta.json"} <= names) or any(not ZIP_OK.fullmatch(i.filename) for i in infos) or len(names) != len(infos):
            raise HTTPException(400, "El zip no es un acta de esta aplicación")
        if sum(i.file_size for i in infos) > 20 * 2**30 or any(
            i.file_size > 300 * 2**20 or i.file_size > 1000 * max(i.compress_size, 1024) for i in infos if not vid(i)
        ):
            raise HTTPException(400, "El zip tiene un tamaño sospechoso")
        try:
            acta = json.loads(z.read("acta.json"))
            tr = json.loads(z.read("transcript.json")) if "transcript.json" in names else None
        except ValueError:
            raise HTTPException(400, "El zip está dañado")
        h = hashlib.sha1(
            (("srv|" + d["clave"]) if d.get("clave") else f"{zp.name}|{zp.stat().st_size}|{zp.stat().st_mtime_ns}").encode()
        ).hexdigest()  # clave: la reunión del escritorio que el servidor sustituye al reenviarla (compartir.py)
        wd, nivel = pipeline.WORK / ("z" + h[:15]), acta.get("nivel") if acta.get("nivel") in pipeline.LEVELS else "normal"
        out = wd / f"acta_{nivel}_zip{h[15:21]}"
        shutil.rmtree(out, ignore_errors=True)
        (out / "img").mkdir(parents=True)
        for i in infos:
            dst = (wd / i.filename) if vid(i) else (wd / f"transcript_zip{h[15:21]}.json") if i.filename == "transcript.json" else out / i.filename
            with z.open(i) as src, open(dst, "wb") as f:
                shutil.copyfileobj(src, f)
    if tr is None:
        (wd / f"transcript_zip{h[15:21]}.json").write_text(json.dumps({"segments": [], "language": "es", "solo_acta": True}), encoding="utf-8")
    for v in wd.glob("video.*"):
        pipeline.put_file(v, out / v.name)
    nombre = {"nombre": acta["titulo"]} if acta.get("titulo") else {}  # nunca el nombre del .zip
    (wd / "meta.json").write_text(
        json.dumps({**meta(wd), **nombre, **({"carpeta": carp} if carp else {}), **({"remoto": d["clave"]} if d.get("clave") else {})}, ensure_ascii=False),
        encoding="utf-8",
    )
    if (
        not servidor.ACTIVO  # en el servidor el registro llega ya hecho desde el escritorio
        and carp
        and tr
        and tr.get("segments")
        and (_ajustes() or AJ_DEF).get("poblar_auto", True)
        and _tipo_carpeta(carp).casefold() == "proyecto"
    ):
        start("poblar", {"c": carp, "mid": wd.name, "auto": True}, carp, wd.name)  # como un documento nuevo del proyecto
    return {"id": wd.name}


@app.post("/api/transcripcion")
def transcripcion(d: dict):
    """Vista previa de una transcripción elegida: formato, nº de segmentos y de hablantes con nombre."""
    p = Path(d.get("path", ""))
    if p.suffix.lower() not in TR_EXT or not p.is_file():
        raise HTTPException(400, "Elige un fichero .vtt, .srt, .txt o .docx")
    try:
        r = transcripts.parse(p)
    except ValueError:  # .txt/.docx sin marcas de tiempo: documento de texto (citas por párrafo o sección)
        try:
            r = documentos.leer(p)
        except (ValueError, OSError, RuntimeError, zipfile.BadZipFile) as e:
            raise HTTPException(400, str(e))
        return {"formato": r["importada"]["formato"], "segmentos": len(r["segments"]), "hablantes": [], "tipo": r["importada"]["tipo"]}
    except (OSError, zipfile.BadZipFile) as e:
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


# ---------- Grabar reunión (sin bot: micrófono + audio del sistema) y notas ----------
def _rec():
    r = grabar.activa()
    if not r:
        raise HTTPException(409, "No hay ninguna grabación en curso")
    return r


@app.get("/api/grabar/dispositivos")
def grabar_dispositivos():
    return grabar.dispositivos()


@app.get("/api/grabar/estado")
def grabar_estado():
    r = grabar.activa()
    return {
        "activa": r.estado() if r else None,
        "notas": grabar.leer_notas(r.wd) if r else [],
        "cfg": r.cfg if r else None,
        "recuperables": grabar.recuperables(pipeline),
    }


@app.post("/api/grabar/iniciar")
def grabar_iniciar(d: dict):
    """{mic_id, sistema_id, pantalla, carpeta, perfil, calidad, nombre, nombres}: empieza a grabar (dos pistas + pantalla opcional)."""
    try:
        plantillas.get(d.get("perfil") or None)
        r = grabar.iniciar(
            pipeline,
            {
                k: d.get(k)
                for k in ("mic_id", "sistema_id", "pantalla", "carpeta", "perfil", "calidad", "nombre", "nombres", "nivel", "asr", "idioma", "habla", "gpu")
            },
        )
    except (ValueError, RuntimeError) as ex:
        raise HTTPException(400, str(ex))
    return r.estado()


@app.post("/api/grabar/pausa")
def grabar_pausa(d: dict):
    r = _rec()
    r.pausar() if d.get("pausa", True) else r.reanudar()
    grabar._meta(r.wd, estado="pausada" if r.pausada else "grabando")
    return r.estado()


@app.post("/api/grabar/nota")
def grabar_nota(d: dict):
    """Nota con el minuto actual de la grabación; sin texto = solo marca el momento (botón rápido)."""
    r = _rec()
    n = grabar.leer_notas(r.wd)
    n.append({"id": uuid.uuid4().hex[:8], "t": r.elapsed(), "texto": d.get("texto") or "", "boton": d.get("boton") or "", "seccion": d.get("seccion") or None})
    return grabar.guardar_notas(r.wd, n)


@app.put("/api/grabar/notas")
def grabar_notas(d: dict):
    return grabar.guardar_notas(_rec().wd, d.get("notas") or [])


def _grabacion_a_cola(wd, ex=None):
    """Cierra los tramos de una grabación y encola el documento (pistas -> «Yo»/«Otros»). Si algo falla, queda en «Recuperar grabación»."""
    m, ex = grabar.meta(wd), ex or {}
    c = {**m.get("cfg", {}), **{k: v for k, v in ex.items() if v not in (None, "")}}
    grabar._meta(wd, estado="parada")
    try:
        fin = grabar.finalizar(wd)
    except (RuntimeError, subprocess.CalledProcessError) as ex2:
        raise HTTPException(400, str(ex2) if isinstance(ex2, RuntimeError) else "No se pudo cerrar la grabación (ffmpeg)")
    medio = Path(fin["medio"])
    wdm = pipeline.WORK / pipeline.video_id(medio)
    grabar.guardar_notas(wdm, grabar.leer_notas(wd))
    nombre = (c.get("nombre") or "").strip() or "Reunión " + time.strftime("%Y-%m-%d %H:%M", time.localtime(m.get("inicio") or time.time()))
    (wdm / "meta.json").write_text(
        json.dumps({**meta(wdm), "nombre": nombre, **({"carpeta": c["carpeta"]} if c.get("carpeta") else {})}, ensure_ascii=False), encoding="utf-8"
    )
    spec = {
        "video": str(medio),
        "pistas": fin["pistas"],
        "nombres": c.get("nombres") or grabar.NOMBRES,
        "carpeta": c.get("carpeta") or "",
        "plantilla": c.get("perfil") or "",
        "calidad": c.get("calidad") or "rápida",
        "nivel": c.get("nivel") or "normal",
        "asr": c.get("asr") or "calidad",
        "idioma": c.get("idioma") or "",
        "habla": c.get("habla") or "",
        "gpu": c.get("gpu"),
        "grabacion": wd.name,
    }
    r = generar(spec)
    grabar._meta(wd, estado="encolada", cola=r["id"])
    return {**r, "id_reunion": wdm.name}


@app.post("/api/grabar/parar")
def grabar_parar(d: dict):
    """Para la grabación y encola el documento con el perfil/calidad/carpeta elegidos."""
    r = _rec()
    r.parar()
    return _grabacion_a_cola(r.wd, d)


@app.post("/api/grabar/recuperar")
def grabar_recuperar(d: dict):
    """Grabación sin cerrar: {id} la cierra y genera el documento; {id, descartar: true} la borra."""
    wd = pipeline.WORK / "grabaciones" / Path(d.get("id") or "").name
    if not (wd / "rec.json").exists() or (grabar.activa() and grabar.activa().wd == wd):
        raise HTTPException(404, "Grabación no encontrada")
    if d.get("descartar"):
        shutil.rmtree(wd, ignore_errors=True)
        return {"ok": True}
    return _grabacion_a_cola(wd, d)


def _wd_notas(d):
    """Reunión (id) o vídeo aún sin procesar (ruta): su carpeta de trabajo, donde viven las notas (notas.json)."""
    if d.get("id"):
        wd = pipeline.WORK / Path(d["id"]).name
        if not wd.is_dir():
            raise HTTPException(404, "Reunión no encontrada")
        return wd
    v = Path(d.get("video") or "")
    if not v.is_file():
        raise HTTPException(400, "Elige un vídeo o una reunión")
    return pipeline.WORK / pipeline.video_id(v)


MEDIA = (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".mp3", ".m4a", ".wav", ".ogg", ".opus", ".flac", ".aac")


@app.get("/api/previa")
def previa(video: str):
    """Vídeo/audio elegido y aún sin procesar, para ponerle notas viéndolo (solo ficheros multimedia; sirve Range)."""
    f = Path(video)
    if f.suffix.lower() not in MEDIA or not f.is_file():
        raise HTTPException(404, "Fichero no encontrado")
    return FileResponse(f)


@app.get("/api/notas")
def get_notas(id: str = "", video: str = ""):
    return grabar.leer_notas(_wd_notas({"id": id, "video": video}))


@app.put("/api/notas")
def put_notas(d: dict):
    """Notas de un vídeo (antes de generar) o de una reunión; al generar entran en el documento."""
    return grabar.guardar_notas(_wd_notas(d), d.get("notas") or [])


# ---------- Reuniones ----------
def _solo_acta(mid, asr):
    try:
        return bool(json.loads((pipeline.WORK / Path(mid).name / f"transcript_{asr}.json").read_text(encoding="utf-8")).get("solo_acta"))
    except (OSError, ValueError):
        return False


def meta(wd):
    """work/<id>/meta.json: {"nombre": nombre a mostrar, "carpeta": carpeta}; no se renombra nada en disco."""
    try:
        return json.loads(pipeline.leer_texto(Path(wd) / "meta.json"))
    except (OSError, ValueError):
        return {}


def resumen(wd):
    """(nº de actas, duración en s, título generado) de una reunión, sacados del acta más reciente que se pueda leer (la editada si existe)."""
    ds = sorted((d for d in wd.glob("acta_*_*") if (d / "index.html").exists()), key=lambda d: d.stat().st_mtime, reverse=True)
    for d in ds:
        try:
            a = json.loads((d / (exportar.EDITADA if (d / exportar.EDITADA).is_file() else "acta.json")).read_text(encoding="utf-8"))
            return len(ds), a.get("duracion") or 0, (a.get("titulo") or "").strip()
        except (OSError, ValueError):
            pass
    return len(ds), 0, ""


def _kind(wd, v=None, exacto=False):
    """video | audio | pdf | texto | imagen. En listas, el audio sale de la extensión (sin ffprobe por cada reunión)."""
    v = v or next(wd.glob("video.*"), None)
    if v:
        return "audio" if (es_audio(v) if exacto else v.suffix.lower() in AUDIO) else "video"
    f = next(wd.glob("fuente.*"), None)
    return documentos.tipo(f) if f else "texto"


def meetings():
    out, res = [], {}
    for tf in sorted(pipeline.WORK.glob("*/transcript_*.json"), key=os.path.getmtime, reverse=True):
        v = next(tf.parent.glob("video.*"), None)
        asr = tf.stem.split("_", 1)[1]
        tj = json.loads(tf.read_text(encoding="utf-8")) if asr.startswith(("imp", "zip")) else {}
        imp = tj.get("importada")
        mt = meta(tf.parent)
        n_actas, dur, tit = res.setdefault(tf.parent.name, resumen(tf.parent))
        # el nombre del archivo solo mientras no haya acta con título generado
        base = mt.get("nombre") or tit or (v.resolve().name if v else imp["fuente"] if imp else tf.parent.name)
        out.append(
            {
                "sel": f"{tf.parent.name}|{asr}",
                "id": tf.parent.name,
                "asr": asr,
                "mtime": int(tf.stat().st_mtime),
                "label": base,
                "nombre": mt.get("nombre", ""),
                "carpeta": mt.get("carpeta", ""),
                "sin": bool(tj.get("solo_acta")),
                "remoto": bool(mt.get("remoto")),
                "actas": n_actas,
                "dur": dur,
                "name": base
                + (" (transcripción importada)" if imp and v else "" if asr.split("-")[0] == "rápido" or imp or asr.startswith("zip") else " (calidad)"),
                "video": f"/files/{tf.parent.name}/{v.name}" if v else None,
                "kind": _kind(tf.parent, v),
            }
        )
    seen = {}  # dos reuniones no se llaman igual: la más antigua se queda el nombre, las demás llevan « (2)», « (3)»…
    for e in reversed(out):
        lab, n = e["label"], 1
        while seen.setdefault(lab.casefold(), e["id"]) != e["id"]:
            n += 1
            lab = f"{e['label']} ({n})"
        e["name"], e["label"] = lab + e["name"][len(e["label"]) :], lab
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
    (wd / "meta.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    return m


def anon_defecto(mid):
    """¿Anonimizar por defecto este documento? La carpeta (si fija una opción) manda sobre el ajuste general."""
    o = carpetas.leer(meta(pipeline.WORK / Path(mid).name).get("carpeta", ""))["ajustes"]["anon"]
    return bool(o) if o is not None else bool((_ajustes() or {}).get("anonimizar_defecto"))


AJUSTES = pipeline.WORK / "ajustes.json"  # preferencias de uso (asistente inicial y pantalla Ajustes)
AJ_DEF = {
    "modo": "simple",
    "servidor_url": "",  # servidor de equipo del escritorio (compartir.py)
    "uso": ["empresa"],
    "perfil_uso": ["acta", "onboarding", "comercial"],
    "nombres": {"carpeta": "Proyecto", "documento": "documento", "nuevo_boton": "+ Añadir"},
    "nube_visible": True,
    "anonimizar_defecto": False,
    "idioma_interfaz": "es",
    "poblar_auto": True,
    "nube_imagenes": False,
    "describir_capturas": False,
    "enlaces_red_local": False,
    "vision": {},
    "tema": "auto",
    "densidad": "comoda",
    "animaciones": "completas",
    "yo": {"nombre": "", "correo": ""},
}  # yo: quien usa la app (autor en el historial del registro); apariencia (Ajustes › General); vision.py: imágenes a la nube solo con permiso; servidor {url, modelo}

AJ_APARIENCIA = {"tema": ("auto", "claro", "oscuro"), "densidad": ("comoda", "compacta"), "animaciones": ("completas", "reducidas", "no")}


def _ajustes():
    try:
        d = json.loads(AJUSTES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    nom = {**AJ_DEF["nombres"], **(d.get("nombres") or {})}
    if nom.get("nuevo_boton") == "+ Nuevo":  # el antiguo valor por defecto pasa al nuevo («+ Añadir»); un nombre propio se respeta
        nom["nuevo_boton"] = AJ_DEF["nombres"]["nuevo_boton"]
    return {**AJ_DEF, **{k: d[k] for k in AJ_DEF if k in d}, "nombres": nom}


@app.get("/api/ajustes")
def get_ajustes():
    a = _ajustes()
    n = registro.USUARIO.get()
    yo = (
        {"yo": {"nombre": n, "correo": ""}, "admin": bool(servidor.usuarios().get(n, {}).get("admin"))} if servidor.ACTIVO else {}
    )  # en el servidor «Tú» es quien ha entrado
    return {**(a or AJ_DEF), "existe": a is not None, **yo, "servidor": servidor.ACTIVO}


@app.post("/api/ajustes")
def post_ajustes(d: dict):
    """Guarda (fusiona) los ajustes válidos; todo es preferencia: no toca reuniones ni carpetas."""
    a = _ajustes() or dict(AJ_DEF)
    if d.get("modo") in ("simple", "avanzado"):
        a["modo"] = d["modo"]
    for k in ("nube_visible", "anonimizar_defecto", "poblar_auto", "nube_imagenes", "describir_capturas", "enlaces_red_local"):
        if isinstance(d.get(k), bool):
            a[k] = d[k]
    for k, ok in AJ_APARIENCIA.items():
        if d.get(k) in ok:
            a[k] = d[k]
    if isinstance(d.get("vision"), dict):  # servidor de visión (LM Studio, Ollama…): {} lo quita
        v = {k: str(d["vision"].get(k) or "").strip()[:300] for k in ("url", "modelo")}
        if v["url"] and not url_valida(v["url"]) or bool(v["url"]) != bool(v["modelo"]):
            raise HTTPException(400, "Servidor de visión: indica la dirección (http://…/v1) y el modelo")
        a["vision"] = v if v["url"] else {}
    if isinstance(d.get("uso"), list):
        a["uso"] = [str(x)[:30] for x in d["uso"]][:12]
    if isinstance(d.get("perfil_uso"), list):
        a["perfil_uso"] = [x for x in dict.fromkeys(d["perfil_uso"]) if x in {t["id"] for t in plantillas.todas()}] or a["perfil_uso"]
    if isinstance(d.get("yo"), dict):  # «Tú»: firma los cambios del registro (historial.autor)
        yo = {k: str(d["yo"].get(k) or "").strip()[:120] for k in ("nombre", "correo")}
        if yo["correo"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", yo["correo"]):
            raise HTTPException(400, "Correo no válido")
        a["yo"] = yo
    if isinstance(d.get("servidor_url"), str):  # servidor de equipo (compartir.py): solo la dirección; el token va al llavero
        a["servidor_url"] = d["servidor_url"].strip().rstrip("/")[:300]
    if isinstance(d.get("nombres"), dict):
        a["nombres"] = {**a["nombres"], **{k: str(v).strip()[:40] for k, v in d["nombres"].items() if k in AJ_DEF["nombres"] and str(v).strip()}}
    pipeline.WORK.mkdir(exist_ok=True)
    AJUSTES.write_text(json.dumps(a, ensure_ascii=False, indent=1), encoding="utf-8")
    return get_ajustes()


CARPETAS = pipeline.WORK / "carpetas.json"  # carpetas creadas aunque aún no tengan reuniones


def _carpetas():
    """carpetas.json: {"vacias": [carpetas creadas], "plantillas": {carpeta: plantilla por defecto}} (antes, solo la lista)."""
    try:
        d = json.loads(pipeline.leer_texto(CARPETAS))
    except (OSError, ValueError):
        d = {}
    return (
        {"vacias": d, "plantillas": {}, "estilos": {}}
        if isinstance(d, list)
        else {"vacias": d.get("vacias", []), "plantillas": d.get("plantillas", {}), "estilos": d.get("estilos", {})}
    )


def carpetas_vacias():
    return _carpetas()["vacias"]


@app.get("/api/carpetas/plantillas")
def carpetas_plantillas():
    return _carpetas()["plantillas"]


@app.get("/api/carpetas/estilos")
def carpetas_estilos():
    return _carpetas()["estilos"]


@app.get("/api/carpetas")
def get_carpetas():
    return sorted({*carpetas_vacias(), *(meta(f.parent).get("carpeta") for f in pipeline.WORK.glob("*/meta.json"))} - {None, ""}, key=str.casefold)


@app.post("/api/carpeta")
def carpeta(d: dict):
    """Crear (sin nombre), renombrar (nuevo) o borrar (sin nuevo) una carpeta: solo toca los meta.json; las reuniones nunca se borran."""
    old, new = (d.get("nombre") or "").strip(), (d.get("nuevo") or "").strip()[:120]
    pipeline.WORK.mkdir(exist_ok=True)
    c = _carpetas()
    if "plantilla" in d:  # {nombre, plantilla}: plantilla por defecto de la carpeta ("" = la de serie)
        try:
            plantillas.get(d["plantilla"] or None)
        except ValueError as ex:
            raise HTTPException(400, str(ex))
        c["plantillas"].pop(old, None) if not d["plantilla"] else c["plantillas"].__setitem__(old, d["plantilla"])
        CARPETAS.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
        return {}
    if "estilo" in d:  # {nombre, estilo}: estilo de organización por defecto de la carpeta ("" = ninguno)
        if d["estilo"]:
            try:
                exportar.estilo_get(d["estilo"])
            except KeyError:
                raise HTTPException(400, "No existe ese estilo")
        c["estilos"].pop(old, None) if not d["estilo"] else c["estilos"].__setitem__(old, d["estilo"])
        CARPETAS.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
        return {}
    if old:
        _ok(carpetas.renombrar, old, new)
    pl, es = c["plantillas"].pop(old, None), c["estilos"].pop(old, None)
    if new and pl:
        c["plantillas"][new] = pl
    if new and es:
        c["estilos"][new] = es
    CARPETAS.write_text(
        json.dumps(
            {"vacias": sorted(({*c["vacias"], new} if new else {*c["vacias"]}) - {old, ""}), "plantillas": c["plantillas"], "estilos": c["estilos"]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    for f in pipeline.WORK.glob("*/meta.json"):
        m = meta(f.parent)
        if m.get("carpeta") == old:
            m.pop("carpeta") if not new else m.__setitem__("carpeta", new)
            f.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    return {}


class _Sink:
    def __init__(self, f):
        self.write, self.flush = f.write, f.flush


def _stream_zip(files):
    """Zip sin compresión (el mp4 ya viene comprimido) generado al vuelo por una tubería: sin segunda copia en disco."""
    r, w = os.pipe()

    def write():
        try:
            with os.fdopen(w, "wb") as out, zipfile.ZipFile(_Sink(out), "w", zipfile.ZIP_STORED, allowZip64=True) as z:
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
def zipvideo(mid: str, acta: str, anon: int | None = None):
    """Acta + vídeo (o audio) donde el reproductor del informe lo espera (video.<ext> junto a index.html). Con anon=1 (o por defecto en ajustes) -> 409: lo anonimizado nunca lleva vídeo ni audio."""
    if bool(anon) if anon is not None else anon_defecto(mid):
        raise HTTPException(
            409,
            "No se incluye vídeo ni audio en lo anonimizado: la voz y la imagen identifican"
            + ("" if anon else " (anonimizar_defecto activo; pasa anon=0 para el original)"),
        )
    wd = pipeline.WORK / Path(mid).name
    out, v = wd / Path(acta).name, next(wd.glob("video.*"), None)
    if not (out / "index.html").exists() or not v or not v.exists():
        raise HTTPException(404, "Sin acta o sin vídeo")
    files = (
        [(f, f.relative_to(out)) for f in out.rglob("*") if f.is_file() and f.name != v.name]
        + [(v, v.name)]
        + [(t, "transcript.json") for t in wd.glob(f"transcript_{Path(acta).name.split('_')[2]}.json")]
    )
    name = (meta(wd).get("nombre") or v.resolve().stem) + (" (con audio).zip" if es_audio(v) else " (con vídeo).zip")
    return StreamingResponse(
        _stream_zip(files), media_type="application/zip", headers={"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(name)}
    )


@functools.lru_cache(maxsize=64)
def _es_audio(path, mtime):
    return not pipeline.has_video(path)


def es_audio(v):
    try:
        return _es_audio(str(v), v.stat().st_mtime_ns)
    except OSError:
        return False


def _calidad(name):
    return next((q for q in pipeline.NIVELES if q in name.split("_")[3:]), "rápida")


def _acta_json(d):
    try:
        return json.loads((d / "acta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@app.get("/api/meeting/{mid}")
def meeting(mid: str):
    wd = pipeline.WORK / Path(mid).name
    # zip: acta_<vídeo>_<nivel><resto del nombre de la versión (plantilla, idioma, calidad…)>.zip
    actas = [
        {
            "name": d.name,
            "nivel": d.name.split("_")[1],
            "asr": d.name.split("_")[2],
            "calidad": _calidad(d.name),
            "sin": _solo_acta(wd.name, d.name.split("_")[2]),
            "fondo": bool((aj := _acta_json(d)).get("fondo")),
            "nube": re.sub(r"^Redactado con | \(nube\)$", "", aj.get("nube") or "") or None,
            "url": f"/api/vista/{wd.name}/{d.name}" if (d / exportar.EDITADA).is_file() else f"/files/{wd.name}/{d.name}/index.html",
            "editado": (d / exportar.EDITADA).is_file(),
            "plantilla": aj.get("plantilla"),
            "doc": (aj.get("documento") or {}).get("singular", "acta"),
            "idioma": aj.get("idioma"),
            "mtime": (d / "index.html").stat().st_mtime,
            "zip": next(
                (f"/files/{wd.name}/{z.name}" for z in wd.glob(f"acta_*_{d.name.split('_')[1]}{''.join('_' + x for x in d.name.split('_')[3:])}.zip")), None
            ),
        }
        for d in sorted(wd.glob("acta_*_*"))
        if (d / "index.html").exists()
    ]
    trs = sorted(wd.glob("transcript_*.json"), key=os.path.getmtime, reverse=True)
    if not actas and not trs:
        raise HTTPException(404, "Sin actas")
    fu = next(wd.glob("fuente.*"), None)
    rec = {c.stem.split("_", 1)[1]: pipeline.recommend_pct(json.loads(c.read_text(encoding="utf-8"))) for c in wd.glob("cortes_*.json")}
    conds = [{"name": c.name, "url": f"/files/{wd.name}/{c.name}"} for c in sorted(wd.glob("condensado_*")) if c.suffix in (".mp4", ".m4a")]
    imp = {f.stem.split("_", 1)[1]: json.loads(f.read_text(encoding="utf-8"))["importada"] for f in wd.glob("transcript_imp*.json")}
    return {
        "id": wd.name,
        "actas": actas,
        "recomendado": rec,
        "condensados": conds,
        "video": any(wd.glob("video.*")),
        "audio": any(es_audio(v) for v in wd.glob("video.*")),
        "videourl": next((f"/files/{wd.name}/{v.name}" for v in wd.glob("video.*")), None),
        "versiones": meta(wd).get("versiones", {}),
        "importadas": imp,
        "videomb": next((round(v.stat().st_size / 1e6) for v in wd.glob("video.*") if v.exists()), 0),
        **{k: meta(wd).get(k, "") for k in ("nombre", "carpeta")},
        "kind": _kind(wd, exacto=True),
        "asr": trs[0].stem.split("_", 1)[1] if trs else None,
        "fuente": f"/files/{wd.name}/{fu.name}" if fu else None,
        "vision": vision.estado(vision.elegir(_ajustes())),
    }  # no_disponible: la interfaz sugiere instalar el modelo de visión


@app.get("/files/{mid}/{path:path}")
def files(mid: str, path: str):
    """work/<hash>/...: FileResponse sirve Range (el <video> puede saltar) y sigue enlaces simbólicos (vídeo en otro disco)."""
    base = os.path.normpath(pipeline.WORK / mid)
    f = os.path.normpath(os.path.join(base, path))  # sin resolver enlaces (el vídeo puede estar en otro disco), pero nunca fuera de la reunión
    if not re.fullmatch(r"[\w-]+", mid) or not f.startswith(base + os.sep) or not os.path.isfile(f):
        raise HTTPException(404)
    return FileResponse(f)


# ---------- Documento editable y exportaciones ----------
def _ex(fn, *a, **k):
    try:
        return fn(*a, **k)
    except FileNotFoundError:
        raise HTTPException(404, "No existe esa versión")
    except (ValueError, KeyError) as ex:
        raise HTTPException(400, str(ex))


@app.get("/api/doc/{mid}/{ver}")
def get_doc(mid: str, ver: str):
    """Datos del documento (el editado si existe) + editado + original (siempre el de la generación)."""
    c = _ex(exportar.carga, mid, ver)
    return {
        "editado": c["editado"],
        "datos": c["data"],
        "original": json.loads((c["d"] / "acta.json").read_text(encoding="utf-8")) if c["editado"] else c["data"],
    }


@app.put("/api/doc/{mid}/{ver}")
def put_doc(mid: str, ver: str, d: dict):
    """{cambios: {ruta: texto}} sobre la versión vigente -> acta_editada.json; el original no se toca."""
    _ex(exportar.guardar_edicion, mid, ver, d.get("cambios") or {})
    return {"editado": True}


@app.post("/api/doc/{mid}/{ver}/restaurar")
def restaurar_doc(mid: str, ver: str):
    _ex(exportar.restaurar, mid, ver)
    return {"editado": False}


@app.get("/api/vista/{mid}/{ver}")
def vista(mid: str, ver: str, editar: int = 0, print: int = 0, original: int = 0, anon: int = 0, dudas: int = 0):
    """HTML del documento desde los datos (editado si existe). editar=1: contenteditable + window.cambios() -> {ruta: texto}; print=1: abre el diálogo de imprimir."""
    c = _ex(exportar.carga, mid, ver, bool(anon), bool(dudas) and not editar)
    if original and c["editado"]:
        c["data"], c["editado"] = json.loads((c["d"] / "acta.json").read_text(encoding="utf-8")), False
    return HTMLResponse(exportar.html_doc(c, bool(editar), f"/files/{c['mid']}/{c['ver']}/", bool(print), exportar.estilo_para(c)))


@app.get("/api/exportar/{mid}/{ver}")
def exportar_doc(
    mid: str, ver: str, fmt: str = "docx", estilo: str | None = None, hablantes: int = 0, evento: int = 0, anon: int | None = None, dudas: int = 0
):
    """anon=1: copia anonimizada (409 si no existe); sin `anon`, vale ajustes.anonimizar_defecto; anon=0 lo desactiva. dudas=1: marca lo dudoso."""
    an = _anon(mid, ver, anon)
    try:
        datos, nombre, mime = _ex(exportar.exportar, mid, ver, fmt, estilo, bool(hablantes), bool(evento), an, bool(dudas))
    except exportar.SinNavegador as ex:
        raise HTTPException(409, str(ex))
    return Response(datos, media_type=mime, headers={"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(nombre)})


def _anon(mid, ver, anon):
    """¿Usar la copia anonimizada? anon explícito manda; si no, el ajuste anonimizar_defecto. 409 si se pide y aún no existe."""
    on = bool(anon) if anon is not None else anon_defecto(mid)
    if on and not (pipeline.WORK / Path(mid).name / Path(ver).name / privacidad.ANON).is_file():
        raise HTTPException(409, "Falta la copia anonimizada de este documento: anonimízalo primero" + ("" if anon else " (o pasa anon=0)"))
    return on


# ---------- Anonimizar ----------
@app.post("/api/anonimizar/{mid}/{ver}/detectar")
def anon_detectar(mid: str, ver: str, d: dict | None = None):
    """{items:[{tipo,valor,n,ejemplos,sugerido}], sin_modelo, capturas_sin_cajas}. Cuerpo opcional {llm:false} para saltar la pasada del modelo."""
    llm = (d or {}).get("llm", True)
    with gpu_exclusiva() if llm else contextlib.nullcontext():
        return _ex(lambda: privacidad.detectar(exportar.carga(mid, ver), llm))


@app.post("/api/anonimizar/{mid}/{ver}/aplicar")
def anon_aplicar(mid: str, ver: str, d: dict):
    """{items:[{tipo,valor,sugerido,incluir?}]} (la lista editada: sin marcar = incluir:false u omitido; añadidos a mano = tipo "persona"/"otro")
    -> crea la copia anonimizada. {reemplazos, difuminadas, omitidas:[{img,motivo}]}"""
    if not isinstance(d.get("items"), list):
        raise HTTPException(400, "Falta items")
    return _ex(lambda: privacidad.aplicar(exportar.carga(mid, ver), [i for i in d["items"] if isinstance(i, dict)]))


@app.get("/api/anonimizar/{mid}/{ver}")
def anon_estado(mid: str, ver: str):
    return _ex(lambda: privacidad.estado(exportar.carga(mid, ver)))


@app.delete("/api/anonimizar/{mid}/{ver}")
def anon_borrar(mid: str, ver: str):
    _ex(lambda: privacidad.borrar(exportar.carga(mid, ver)["d"]))
    return {"existe": False}


# ---------- Correo ----------
@app.post("/api/correo/{mid}/{ver}")
def post_correo(mid: str, ver: str, d: dict):
    """{modo:"todos"|"responsable", tono:"formal"|"cercano"|"breve", idioma?, adjuntar_pdf?, anon?} -> {correos:[{para,asunto,texto,html,eml_url}], eml_url, llm, aviso?}"""
    an = _anon(mid, ver, d.get("anon"))
    with gpu_exclusiva():
        return _ex(correo.generar, mid, ver, d.get("modo", "todos"), d.get("tono", "formal"), d.get("idioma") or "es", bool(d.get("adjuntar_pdf")), an)


@app.get("/api/correo/{mid}/{ver}/eml/{n}")
def get_eml(mid: str, ver: str, n: int):
    f = pipeline.WORK / Path(mid).name / Path(ver).name / "correos" / f"{n}.eml"
    if not f.is_file():
        raise HTTPException(404, "Genera antes el borrador")
    return Response(f.read_bytes(), media_type="message/rfc822", headers={"Content-Disposition": f'attachment; filename="borrador-{n + 1}.eml"'})


@app.post("/api/correo/{mid}/{ver}/outlook/{n}")
def post_outlook(mid: str, ver: str, n: int):
    """Abre el borrador n ya generado en Outlook clásico (Windows), con su PDF adjunto si lo llevaba. 400 con el motivo si no se puede."""
    import email
    import email.policy

    f = pipeline.WORK / Path(mid).name / Path(ver).name / "correos" / f"{n}.eml"
    if not f.is_file():
        raise HTTPException(404, "Genera antes el borrador")
    m = email.message_from_bytes(f.read_bytes(), policy=email.policy.default)
    h = m.get_body(("html", "plain"))
    pdf = next((x for x in m.iter_attachments() if x.get_content_type() == "application/pdf"), None)
    try:
        correo.abrir_outlook(
            {"para": str(m["To"] or ""), "asunto": str(m["Subject"] or ""), "html": h.get_content() if h else ""},
            pdf.get_content() if pdf else None,
            pdf.get_filename() or "documento.pdf" if pdf else "documento.pdf",
        )
    except RuntimeError as ex:
        raise HTTPException(400, str(ex))
    return {"ok": True}


# ---------- Dudas ----------
@app.get("/api/dudas/{mid}/{ver}")
def get_dudas(mid: str, ver: str):
    """{dudas:{ruta data-p:[motivos]}, segs:{n:[motivos]}, n, asr}: ruta = la misma de /api/doc y data-p de /api/vista. Lo editado deja de estar marcado."""
    r = _ex(dudas.calcular, mid, ver)
    return {k: r[k] for k in ("dudas", "segs", "n", "asr")}


@app.get("/api/estilos")
def get_estilos():
    return exportar.estilos()


@app.get("/api/estilos/{eid}")
def get_estilo(eid: str):
    return _ex(exportar.estilo_get, eid)


@app.post("/api/estilos")
def post_estilo(d: dict):
    return _ex(exportar.estilo_guardar, d)


@app.post("/api/estilos/borrar")
def borrar_estilo(d: dict):
    _ex(exportar.estilo_borrar, d.get("id", ""))
    return {}


@app.put("/api/estilos/{eid}/{clave}")
async def subir_estilo(eid: str, clave: str, request: Request, name: str = ""):
    """Cuerpo = el fichero. clave: logo (png/jpg) | base_docx (.docx)."""
    if clave not in ("logo", "base_docx"):
        raise HTTPException(404)
    return _ex(exportar.estilo_fichero, eid, clave, name, await request.body())


@app.get("/api/estilos/{eid}/{clave}")
def bajar_estilo(eid: str, clave: str):
    e = _ex(exportar.estilo_get, eid)
    if clave not in ("logo", "base_docx") or not e[clave]:
        raise HTTPException(404)
    return FileResponse(exportar._est_dir() / e[clave])


# ---------- Plantillas ----------
@app.get("/api/plantillas")
def get_plantillas():
    return {"plantillas": plantillas.todas(), "escala": pipeline.ESCALA, "idiomas": plantillas.IDIOMAS, "serie": plantillas.SERIE_ID}


@app.post("/api/plantillas")
def set_plantilla(d: dict):
    """{plantilla, modo}: guardar desde el editor (modo "") o importar un .json (modo "importar"; si el nombre o el id ya existen,
    409 y la interfaz pregunta: "reemplazar" o "copia")."""
    try:
        return plantillas.guardar(d.get("plantilla"), d.get("modo") or "")
    except FileExistsError as ex:
        raise HTTPException(409, f"Ya hay una plantilla «{ex}»")
    except (ValueError, PermissionError) as ex:
        raise HTTPException(400, str(ex))


@app.post("/api/plantillas/borrar")
def del_plantilla(d: dict):
    plantillas.borrar(d.get("id"))
    return {}


# ---------- Carpeta = expediente ----------
def _c(d):
    c = str((d or {}).get("c") or "").strip()
    if c not in get_carpetas() and c:
        raise HTTPException(404, "No existe esa carpeta")
    return c


def _ok(fn, *a, **k):
    try:
        return fn(*a, **k)
    except KeyError as ex:
        raise HTTPException(404, ex.args[0] if ex.args else "No encontrado")
    except ValueError as ex:
        raise HTTPException(400, str(ex))


@app.get("/api/exp")
def exp_get(c: str):
    """Expediente: tipo (etiqueta), datos con sugerencias por tipo, ajustes, glosario y contadores."""
    c = _c({"c": c})
    e, ms = carpetas.leer(c), _ms(c)
    perfil = _carpetas()["plantillas"].get(c)
    tipo = carpetas.tipo_de(e, perfil, ((_ajustes() or AJ_DEF)["nombres"]).get("carpeta"))
    ps = carpetas.pendientes(c, ms)
    return {
        "c": c,
        "tipo": tipo,
        "datos": e["datos"],
        "sugerencias": [k for k in carpetas.sugerencias(tipo) if k not in {x["k"] for x in e["datos"]}],
        "aviso": "Guarda solo una referencia interna: nada que identifique a la persona." if tipo.casefold() in carpetas.SENSIBLES else "",
        "ajustes": e["ajustes"],
        "perfil": perfil or "acta",
        "estilo": _carpetas()["estilos"].get(c, ""),
        "glosario": e["glosario"],
        "n_docs": len({m["id"] for m in ms}),
        "pend": sum(p["estado"] == "abierto" for p in ps),
        "sug": sum(bool(p["sugerido"]) and p["estado"] == "abierto" for p in ps),
        "anon_efectivo": bool(e["ajustes"]["anon"]) if e["ajustes"]["anon"] is not None else bool((_ajustes() or {}).get("anonimizar_defecto")),
    }


@app.post("/api/exp/datos")
def exp_datos(d: dict):
    carpetas.guardar_datos(_c(d), d.get("tipo"), d.get("datos") or [])
    return exp_get(d["c"])


@app.post("/api/exp/ajustes")
def exp_ajustes(d: dict):
    """{c, anon: true|false|null (null = el ajuste general), idioma: "" (el de la reunión) | es en fr…}"""
    if "puntuacion" in d:  # B3: ICE (por defecto) o RICE en el embudo de ideas; no toca lo demás
        if d["puntuacion"] not in ("ice", "rice"):
            raise HTTPException(400, "puntuacion: ice | rice")
        carpetas.editar(_c(d), lambda e: e["ajustes"].update(puntuacion=d["puntuacion"]))
        return exp_get(d["c"])
    if d.get("idioma") and d["idioma"] not in plantillas.IDIOMAS:
        raise HTTPException(400, "Idioma no válido")
    carpetas.guardar_ajustes(_c(d), d.get("anon"), d.get("idioma"))
    return exp_get(d["c"])


@app.get("/api/exp/pendientes")
def exp_pendientes(c: str, estado: str = "abierto", resp: str = "", orden: str = "plazo"):
    c = _c({"c": c})
    return carpetas.listar(c, _ms(c), estado, resp, orden)


@app.post("/api/exp/pendientes")
def exp_pendiente(d: dict):
    """{c, id, estado: abierto|hecho|descartado} · {c, texto, resp?, plazo?} (pendiente manual) · {c, id, borrar: true} (solo manuales)"""
    c = _c(d)
    if d.get("borrar"):
        carpetas.borrar_manual(c, d.get("id", ""))
    elif d.get("id"):
        _ok(carpetas.set_estado, c, _ms(c), d["id"], d.get("estado"))
    else:
        return carpetas.añadir_manual(c, d.get("texto"), d.get("resp"), d.get("plazo"))
    return {}


@app.post("/api/exp/sugerencia")
def exp_sugerencia(d: dict):
    """{c, id, aceptar} (o {c, todas: true, aceptar: true}): confirma o rechaza «parece hecho» / «actualizado»; solo así se cierra un pendiente."""
    c = _c(d)
    ids = [p["id"] for p in carpetas.pendientes(c, _ms(c)) if p["sugerido"] and p["estado"] == "abierto"] if d.get("todas") else [d.get("id", "")]
    for i in ids:
        _ok(carpetas.resolver_sugerencia, c, _ms(c), i, bool(d.get("aceptar")))
    return {"n": len(ids)}


@app.post("/api/exp/seguimiento")
def exp_seguimiento(d: dict):
    """{c, mid, gpu?, calidad?}: repite el seguimiento de un documento de la carpeta (trabajo en cola)."""
    c = _c(d)
    if not any(m["id"] == d.get("mid") for m in _ms(c)):
        raise HTTPException(404, "Ese documento no está en la carpeta")
    falta(d, "fondo", False)
    return start("seguimiento", {**d, "c": c}, c, d["mid"])


@app.get("/api/exp/linea")
def exp_linea(c: str):
    c = _c({"c": c})
    return carpetas.linea(c, _ms(c))


@app.post("/api/exp/notas")
def exp_notas(d: dict):
    """{c, texto, fecha?: AAAA-MM-DD} añade una nota con fecha · {c, id, borrar: true} la quita."""
    c = _c(d)
    if d.get("borrar"):
        carpetas.borrar_nota(c, d.get("id", ""))
        return {}
    return _ok(carpetas.añadir_nota, c, d.get("texto"), d.get("fecha"))


@app.get("/api/exp/estado")
def exp_estado(c: str):
    """Estado actual: decisiones vigentes (y las sustituidas), pendientes abiertos, cambios desde el documento anterior y la redacción guardada."""
    c = _c({"c": c})
    return carpetas.estado_actual(c, _ms(c))


@app.post("/api/exp/estado")
def exp_estado_regenerar(d: dict):
    """Encola la redacción del estado actual (LLM sobre los datos de arriba)."""
    c = _c(d)
    falta(d, "fondo", False)
    return start("estado", {**d, "c": c}, c)


@app.get("/api/exp/comparar")
def exp_comparar(c: str, a: str, b: str):
    """Diff determinista (embeddings) de decisiones, tareas y puntos clave entre dos documentos de la carpeta: nuevo, cambiado, ya no aparece."""
    c = _c({"c": c})
    return _ok(carpetas.comparar_ids, c, _ms(c), a, b)


@app.post("/api/exp/comparar")
def exp_comparar_redactar(d: dict):
    """{c, a, b}: encola la redacción (LLM) de las diferencias; el diff no cambia."""
    c = _c(d)
    _ok(carpetas.comparar_ids, c, _ms(c), d.get("a"), d.get("b"))
    falta(d, "fondo", False)
    return start("comparar", {**d, "c": c}, c)


@app.get("/api/exp/glosario")
def exp_glosario(c: str, sugerir: int = 0, minimo: int = 3):
    c = _c({"c": c})
    return {"glosario": carpetas.leer(c)["glosario"], "sugeridos": carpetas.sugerir_glosario(c, _ms(c), minimo) if sugerir else []}


@app.post("/api/exp/glosario")
def exp_glosario_set(d: dict):
    """{c, glosario: [{t, orto?, def?}], ignorar?: [términos sugeridos descartados]}"""
    c = _c(d)
    carpetas.glosario_set(c, d.get("glosario"), d.get("ignorar") or [])
    return {"glosario": carpetas.leer(c)["glosario"]}


# ---------- Registro genérico (/api/reg): entidades del proyecto con revisión (bandeja) ----------
def _reg_ids(c, ids):
    if not isinstance(ids, list) or not ids:
        raise HTTPException(400, "Faltan ids")
    return [_ok(registro.de, c, i)["id"] for i in dict.fromkeys(ids)]


_EST_GEN = [
    "",
    "abierto",
    "en curso",
    "hecho",
    "bloqueado",
    "descartado",
    "pendiente",
    "mitigado",
    "cerrado",
    "resuelto",
    "aceptado",
    "materializado",
    "vigente",
    "sustituida",
]
ESTADOS_TIPO = {  # estados admitidos por tipo (permisivo: los de la UI genérica + los propios de cada vista)
    **{t: _EST_GEN for t in registro.TIPOS},
    "requisito": _EST_GEN + ["borrador", "validado", "aprobado", "rechazado", "implementado"],
    "historia": _EST_GEN + ["backlog", "preparada", "hecha"],
    "decision": _EST_GEN + ["revocada"],
    "idea": _EST_GEN + ["nueva", "en evaluación", "en experimento", "escalada", "descartada"],
    "experimento": _EST_GEN + ["diseño", "terminado", "pivotar", "perseverar", "matar"],
}
RESERVADAS = ("fuente", "huerfano", "clave")  # claves de `campos` que gestiona el sistema


def _iso(v):
    try:
        time.strptime(str(v), "%Y-%m-%d")
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v)))
    except ValueError:
        return False


def _reg_cambios(cm, tipo=None, c=None):
    if not isinstance(cm, dict):
        raise HTTPException(400, "cambios debe ser un objeto")
    if mal := set(cm) - registro.EDITABLES:
        raise HTTPException(400, f"Campos no editables: {sorted(mal)}")
    if "campos" in cm and not isinstance(cm["campos"], dict):
        raise HTTPException(400, "campos debe ser un objeto")
    if res := set(cm.get("campos") or {}) & set(RESERVADAS):
        raise HTTPException(400, f"Campos reservados: {sorted(res)}")
    for k in ("fecha_limite", "fecha_cierre", "fecha_alta"):
        if cm.get(k) and not _iso(cm[k]):
            raise HTTPException(400, f"{k} debe ser AAAA-MM-DD o vacía")
    if tipo and "estado" in cm and cm["estado"] not in ESTADOS_TIPO.get(tipo, _EST_GEN):
        raise HTTPException(400, f"Estado no válido para {tipo}: {cm['estado']}")
    if tipo == "interesado":
        ne = registro.niveles_ejes(c) if c else (10, 10)  # sin proyecto: el máximo posible
        for k, n in zip(("poder", "interes"), ne):
            v = (cm.get("campos") or {}).get(k, "")
            if v != "" and v is not None:
                x = None if isinstance(v, str) else registro.num_medio(v)
                if x is None or not 1 <= x <= n:
                    raise HTTPException(400, f"{k} debe ser un número de 1 a {n} en pasos de 0,5 (o vacío)")
                cm["campos"][k] = x
    return cm


def _reg_tipo(t):
    if t not in registro.TIPOS:
        raise HTTPException(400, f"Tipo no válido: {t}")
    return t


@app.get("/api/reg")
def reg_list(
    request: Request, c: str, tipo: str = "", revision: str = "", estado: str = "", q: str = "", dueno: str = "", huerfanos: int = 0, prioridad: str = ""
):
    c = _c({"c": c})
    cf = {k[6:]: v for k, v in request.query_params.items() if k.startswith("campo_") and len(k) > 6}  # campo_<k>=<v>: igualdad sobre campos
    if tipo:
        _reg_tipo(tipo)
    if revision and revision not in ("propuesto", "aprobado", "descartado", "fusionado"):
        raise HTTPException(400, "Revisión no válida")
    registro.sincronizar(c, carpetas.docs(_ms(c)))  # lista fresca, igual que carpetas.pendientes
    todas = registro.listar(c)
    vis = [x for x in todas if x["revision"] not in registro.OCULTA]
    qs, ds = q.casefold(), dueno.casefold()
    xs = [
        x
        for x in (todas if revision else vis)
        if (not tipo or x["tipo"] == tipo)
        and (not revision or x["revision"] == revision)
        and (not estado or x["estado"] == estado)
        and (not prioridad or x["prioridad"] == prioridad)
        and all(str(x["campos"].get(k, "")) == v for k, v in cf.items())
        and (not ds or ds in x["dueno"].casefold())
        and (not huerfanos or x["campos"].get("huerfano"))
        and (not qs or any(qs in str(x[k] or "").casefold() for k in ("titulo", "detalle", "dueno", "codigo")))
    ]
    nr = Counter((x["tipo"], x["revision"]) for x in todas)  # Counter: nr[t, r] da 0 si no hay
    return {
        "items": registro.completas(xs),
        "contadores": {
            "por_tipo": dict(Counter(x["tipo"] for x in vis)),
            "por_revision": {r: sum(x["revision"] == r for x in todas) for r in ("propuesto", "aprobado", "descartado")},
            "por_tipo_revision": {
                t: {r: nr[t, r] for r in ("propuesto", "aprobado", "descartado", "fusionado")} for t in {t for t, _ in nr}
            },  # chips de revisión por tipo, incl. descartadas sin abrirlas
            "fusionadas": sum(x["revision"] == "fusionado" and (not tipo or x["tipo"] == tipo) for x in todas),  # del tipo pedido: chip «Fusionadas (n)»
            "huerfanos": sum(bool(x["campos"].get("huerfano")) for x in vis),
        },
    }


@app.get("/api/reg/exportar")
def reg_exportar(c: str, vista: str, fmt: str, borrador: int = 1, estilo: str | None = None):
    """Descarga de una vista del registro (docx pdf xlsx csv md json; historias: feature csv_jira csv_azure). borrador=1: todo lo no descartado con marca BORRADOR."""
    c = _c({"c": c})
    registro.sincronizar(c, carpetas.docs(_ms(c)))
    try:
        datos, nombre, mime = _ok(export_registro.exportar, c, vista, fmt, bool(borrador), carpetas.docs(_ms(c)), estilo)
    except exportar.SinNavegador as ex:
        raise HTTPException(409, str(ex))
    return Response(datos, media_type=mime, headers={"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(nombre)})


@app.get("/api/reg/miembros")
def reg_miembros(c: str):
    """Miembros del proyecto para elegir responsable: tú (Ajustes › Tú), hablantes con nombre, interesados y responsables ya usados."""
    c = _c({"c": c})
    ns = [((_ajustes() or AJ_DEF).get("yo") or {}).get("nombre", "")]
    for m in _ms(c):
        try:
            nm = json.loads((pipeline.WORK / m["id"] / "nombres.json").read_text(encoding="utf-8")).get("names")
            ns += [str(v) for v in (nm.values() if isinstance(nm, dict) else nm or [])]
        except (OSError, ValueError, AttributeError):
            pass
    vivos = [x for x in registro.listar(c) if x["revision"] not in ("descartado", "fusionado")]
    ns += [x["titulo"] for x in vivos if x["tipo"] == "interesado"] + [x["dueno"] or "" for x in vivos]
    out = {}
    for n in ns:
        n = str(n).strip(" .—-")
        if len(n) >= 2 and not re.fullmatch(r"(?i)hablante \d+|speaker \d+", n):
            out.setdefault(n.casefold(), n)
    return sorted(out.values(), key=str.casefold)


@app.get("/api/reg/equipo")
def reg_equipo(c: str):
    """Carga por persona (A3): tareas abiertas y vencidas, decisiones de los últimos 30 días (decisor) y preguntas abiertas dirigidas a cada uno."""
    c = _c({"c": c})
    por, hace = {}, time.strftime("%Y-%m-%d", time.localtime(time.time() - 30 * 86400))

    def suma(nombre, k):
        nombre = str(nombre or "").strip()
        if nombre:
            p = por.setdefault(nombre.casefold(), {"nombre": nombre, "abiertas": 0, "vencidas": 0, "decisiones": 0, "preguntas": 0})
            p[k] += 1

    for p in carpetas.listar(c, _ms(c), "abierto")["items"]:
        suma(p["resp"], "abiertas")
        if p.get("vencido"):
            suma(p["resp"], "vencidas")
    for x in registro.listar(c):
        if x["revision"] in registro.OCULTA:
            continue
        cm = x.get("campos") or {}
        if x["tipo"] == "decision" and (x.get("fecha_alta") or "") >= hace:
            suma(cm.get("decisor") or x["dueno"], "decisiones")
        elif x["tipo"] == "pregunta" and x["estado"] in ("", "abierto", "en curso"):
            suma(cm.get("dirigida_a"), "preguntas")
    return sorted(por.values(), key=lambda p: (-p["vencidas"], -p["abiertas"], p["nombre"].casefold()))


@app.post("/api/reg")
def reg_crear(d: dict):
    """{c, tipo, titulo, detalle?, estado?, dueno?, prioridad?, fecha_limite?, campos?}: entidad manual ya aprobada (sin cita)."""
    c = _c(d)
    f = {k: d[k] for k in ("detalle", "estado", "dueno", "prioridad", "fecha_limite", "campos") if d.get(k) not in (None, "")}
    _reg_cambios(f, d.get("tipo"), c)
    if not str(d.get("titulo") or "").strip():
        raise HTTPException(400, "Falta el título")
    return registro.completas([_ok(registro.crear, c, _reg_tipo(d.get("tipo")), titulo=str(d["titulo"]).strip(), origen="manual", revision="aprobado", **f)])[0]


@app.get("/api/reg/matriz")
def reg_matriz_get(c: str):
    p, i = registro.niveles_ejes(_c({"c": c}))
    return {"niveles_poder": p, "niveles_interes": i, "niveles": p}


@app.post("/api/reg/matriz")
def reg_matriz_set(d: dict):
    """{c, niveles_poder?, niveles_interes?, niveles? (ambos), reescalar: bool}, 3..10 cada uno: huecos de poder/interés; un solo lote deshacible.
    -> {ok, niveles_poder, niveles_interes, niveles, recortados, items}."""
    c = _c(d)
    if not c:
        raise HTTPException(404, "No existe esa carpeta")
    g = lambda k: d.get(k, d.get("niveles")) if "niveles" in d or k in d else None
    ids, rec = _ok(registro.matriz, c, g("niveles_poder"), g("niveles_interes"), bool(d.get("reescalar")))
    p, i = registro.niveles_ejes(c)
    return {
        "ok": True,
        "niveles_poder": p,
        "niveles_interes": i,
        "niveles": p,
        "recortados": rec,
        "items": registro.completas([registro.de(c, i) for i in ids]),
    }


@app.post("/api/reg/revisar")
def reg_revisar(d: dict):
    """{c, ids, accion: aprobar|descartar|restaurar, cambios?}: todo el lote es un solo paso para deshacer."""
    c, acc = _c(d), d.get("accion")
    if acc not in ("aprobar", "descartar", "restaurar"):
        raise HTTPException(400, "Acción no válida")
    cm = _reg_cambios(d.get("cambios") or {})
    with registro.LOCK:
        ids, lote = _reg_ids(c, d.get("ids")), uuid.uuid4().hex[:10]
        with registro._db(escribe=True) as db:  # una sola transacción: si una entidad falla no se aplica nada
            for i in ids:
                x = _ok(registro.de, c, i)
                _reg_cambios(cm, x["tipo"], c)
                rev = "descartado" if acc == "descartar" else "aprobado" if acc == "aprobar" or x["origen"] in ("manual", "migrado") else "propuesto"
                _ok(registro.editar, i, {**cm, "revision": rev}, lote, db)
        return {"ok": True, "items": registro.completas([registro.de(c, i) for i in ids])}


@app.post("/api/reg/{eid}/sugerencia")
def reg_sugerencia(eid: str, d: dict):
    """{c, accion: aceptar|rechazar}: resuelve la sugerencia de seguimiento (misma lógica que /api/exp/sugerencia); un lote, deshacible."""
    c, acc = _c(d), d.get("accion")
    if acc not in ("aceptar", "rechazar"):
        raise HTTPException(400, "Acción no válida")
    with registro.LOCK:
        x = _ok(registro.de, c, eid)
        s = x["sugerencia"]
        antes = registro.ultimo_lote(c)
        _ok(carpetas.resolver_sugerencia, c, _ms(c), registro.ref(x), acc == "aceptar")
        lote = registro.ultimo_lote(c)
        if acc == "aceptar" and s["tipo"] == "hecho" and lote and lote != antes:  # solo si el cierre abrió lote: mismo lote, un solo Ctrl+Z
            registro.editar(eid, {"fecha_cierre": time.strftime("%Y-%m-%d")}, lote)
        return registro.completas([registro.de(c, eid)])[0]


@app.post("/api/reg/fusionar")
def reg_fusionar(d: dict):
    c = _c(d)
    with registro.LOCK:
        dest, orig = _reg_ids(c, [d.get("destino")])[0], _reg_ids(c, d.get("origenes"))
        if dest in orig:
            raise HTTPException(400, "El destino no puede ser un origen")
        _ok(registro.fusionar, dest, orig)
        return registro.completas([registro.de(c, dest)])[0]


@app.post("/api/reg/separar")
def reg_separar(d: dict):
    """{c, destino, origen}: deshace una fusión concreta (el origen reaparece; el destino pierde lo que le trajo). Un lote, deshacible."""
    c = _c(d)
    with registro.LOCK:
        if d.get("destino") == d.get("origen"):
            raise HTTPException(400, "Destino y origen deben ser distintos")
        dest, orig = _reg_ids(c, [d.get("destino"), d.get("origen")])
        _ok(registro.separar, dest, orig)
        return {"ok": True, "items": registro.completas([registro.de(c, dest), registro.de(c, orig)])}


@app.post("/api/reg/deshacer")
def reg_deshacer(d: dict):
    c = _c(d)
    with registro.LOCK:
        ids = registro.ultimo_lote_ids(c)
        n = registro.deshacer(c)
        vivas = []
        for i in ids:
            with contextlib.suppress(KeyError):
                vivas.append(registro.de(c, i))
        return {"ok": True, "revertidas": n, "items": registro.completas(vivas)}


@app.post("/api/reg/deshacer-pasada")
def reg_deshacer_pasada(d: dict):
    """{c, lote}: revierte una pasada de IA (poblar/derivar) por su lote auto. Un lote ajeno o del usuario -> 400/404."""
    c, lote = _c(d), d.get("lote")
    with registro.LOCK:
        with registro._db() as db:
            p = registro.proyecto(c, False, db)
            r = (
                p
                and isinstance(lote, str)
                and db.execute("SELECT DISTINCT entidad_id, auto FROM historial WHERE proyecto_id=? AND lote=?", (p["id"], lote)).fetchall()
            )
        if not r:
            raise HTTPException(404, "Esa pasada no existe en la carpeta")
        if not all(x["auto"] for x in r):
            raise HTTPException(400, "Ese lote no es una pasada de IA")
        n = registro.deshacer_pasada(c, lote)
        vivas = []
        for i in {x["entidad_id"] for x in r}:
            with contextlib.suppress(KeyError):
                vivas.append(registro.de(c, i))
        return {"ok": True, "revertidas": n, "items": registro.completas(vivas)}


@app.post("/api/reg/relacion")
def reg_relacion(d: dict):
    c = _c(d)
    if d.get("aplicar") and d.get("tipo") == "sustituye":  # relación + antigua «sustituida» en un solo lote
        with registro.LOCK:
            _ok(registro.sustituir, c, d.get("a"), d.get("b"))
        return {"ok": True}
    _ok(registro.relacionar, c, d.get("a"), d.get("b"), d.get("tipo"), bool(d.get("propuesta")))
    return {"ok": True}


@app.delete("/api/reg/relacion")
def reg_relacion_borrar(c: str, a: str, b: str, tipo: str):
    _ok(registro.desrelacionar, _c({"c": c}), a, b, tipo)
    return {"ok": True}


@app.post("/api/reg/poblar")
def reg_poblar(d: dict):
    """{c, mid?, vistas?: [requisitos|decisiones|interesados|riesgos|preguntas], nube?, gpu?, calidad?}: encola la pasada `poblar`
    («Regenerar con IA»): solo añade lo nuevo; respeta lo editado, aprobado y descartado."""
    c = _c(d)
    if _tipo_carpeta(c).casefold() in carpetas.SENSIBLES:
        raise HTTPException(400, "Esta carpeta es de un tipo sensible (paciente, candidato): la IA no puebla su registro")
    ms = [m for m in _ms(c) if not d.get("mid") or m["id"] == d["mid"]]
    if not ms:
        raise HTTPException(404, "Ese documento no está en la carpeta")
    if not isinstance(d.get("vistas") or [], list) or set(d.get("vistas") or []) - set(poblar.TODAS):
        raise HTTPException(400, f"Vistas no válidas (valen: {', '.join(poblar.TODAS)})")
    if d.get("nube"):  # los documentos de una plantilla «solo en este equipo» no salen a la nube
        for m in ms:
            _nube_spec({"nube": d["nube"]}, _tpl_de(m["id"]))
        _nube_spec(d)
    falta(d, "fondo", False)
    return start("poblar", {**d, "c": c}, c, d.get("mid") or "")


@app.get("/api/reg/poblar/estado")
def reg_poblar_estado(c: str):
    """Última pasada de poblar en la carpeta {t, mids, vistas, creadas, citas, omitidas, descartadas, llamadas, segundos, coste, tokens}
    y si hay una en cola."""
    c = _c({"c": c})
    return {"ultimo": carpetas.leer(c).get("poblar"), "en_cola": any(e["kind"] == "poblar" and e["spec"].get("c") == c and e["state"] in ACTIVOS for e in cola)}


# ---------- F5: derivar historias + Gherkin + preguntas de los requisitos (derivar.py, op «derivar») ----------
import importar_registro  # noqa: E402

importar_registro.montar(sys.modules[__name__], app)  # /api/reg/importar/* y /api/doc/a-proyecto
import equipo  # noqa: E402

equipo.montar(sys.modules[__name__], app)  # /api/equipo/exportar e /api/equipo/importar (.actas-equipo.json)
import compartir  # noqa: E402

compartir.montar(sys.modules[__name__], app, bucle="pytest" not in sys.modules)  # proyecto compartido por carpeta sincronizada (A2)
import derivar  # noqa: E402


def _derivar_fn(d):
    c = d["c"]

    def fn(cb):
        r = derivar.derivar(c, _llm_ctx(d, [m["id"] for m in _ms(c)], carpetas.terminos_prompt(c)), d.get("ids"), carpetas.terminos_prompt(c), cb)
        return {"carpeta": c, **{k: r[k] for k in ("creadas", "llamadas")}}

    return fn


FNS["derivar"] = _derivar_fn


@app.post("/api/reg/derivar")
def reg_derivar(d: dict):
    """{c, ids?: [requisito], nube?, gpu?, calidad?}: encola `derivar` (sin ids: los requisitos vivos sin historias). Solo añade lo nuevo."""
    c = _c(d)
    ids = d.get("ids")
    if ids is not None:
        vivos = {x["id"] for x in registro.listar(c, "requisito") if x["revision"] not in registro.OCULTA}
        if not isinstance(ids, list) or not ids or set(ids) - vivos:
            raise HTTPException(400, "Requisitos no válidos")
    elif not derivar.pendientes(c):
        raise HTTPException(400, "No hay requisitos sin historias")
    if d.get("nube"):  # los documentos de una plantilla «solo en este equipo» no salen a la nube
        for m in _ms(c):
            _nube_spec({"nube": d["nube"]}, _tpl_de(m["id"]))
        _nube_spec(d)
    falta(d, "fondo", False)
    return start("derivar", {**d, "c": c}, c)


@app.get("/api/reg/derivar/estado")
def reg_derivar_estado(c: str):
    """Última derivación en la carpeta {t, requisitos, creadas, omitidas, descartadas, llamadas, segundos, coste, tokens} y si hay una en cola."""
    c = _c({"c": c})
    return {
        "ultimo": carpetas.leer(c).get("derivar"),
        "en_cola": any(e["kind"] == "derivar" and e["spec"].get("c") == c and e["state"] in ACTIVOS for e in cola),
    }


@app.get("/api/reg/bandeja")
def reg_bandeja(c: str):
    """Lo que espera revisión: propuestos, sugerencias de seguimiento, relaciones «sustituye» propuestas entre decisiones, huérfanos."""
    c = _c({"c": c})
    ds = carpetas.docs(_ms(c))
    registro.sincronizar(c, ds)
    vis = [x for x in registro.listar(c) if x["revision"] not in registro.OCULTA]
    dec = {(x["mid"], x["h"]): x for x in vis if x["tipo"] == "decision" and x["mid"]}
    rels = []
    if len(dec) > 1:
        with contextlib.suppress(Exception):  # ponytail: si fallan los embeddings la bandeja sigue sin propuestas de sustitución
            hechas = {
                (r["a"], r["b"]) for x in registro.completas(list(dec.values())) for r in x["relaciones"] if r["tipo"] == "sustituye"
            } | registro.rechazadas(c)
            for s in carpetas.vigentes(ds)[1]:
                viejo, nuevo = (
                    dec.get((s["mid"], carpetas._h(s["mid"], s["texto"]))),
                    dec.get((s["por"]["mid"], carpetas._h(s["por"]["mid"], s["por"]["texto"]))),
                )
                if viejo and nuevo and (nuevo["id"], viejo["id"]) not in hechas:
                    rels.append(
                        {"a": nuevo["id"], "b": viejo["id"], "tipo": "sustituye", "propuesta": True, "a_titulo": nuevo["titulo"], "b_titulo": viejo["titulo"]}
                    )
    sel = lambda f: registro.completas([x for x in vis if f(x)])
    return {
        "propuestos": sel(lambda x: x["revision"] == "propuesto"),
        "sugerencias": sel(lambda x: x["sugerencia"]),
        "relaciones_propuestas": rels,
        "huerfanos": sel(lambda x: x["campos"].get("huerfano")),
    }


@app.get("/api/reg/{eid}/historial")
def reg_historial(eid: str, c: str):
    _ok(registro.de, _c({"c": c}), eid)
    return [{k: h.get(k) for k in ("t", "accion", "antes", "despues", "lote", "autor")} for h in registro.historial(eid)]


@app.patch("/api/reg/{eid}")
def reg_editar(eid: str, d: dict):
    c = _c(d)
    with registro.LOCK:
        x = _ok(registro.de, c, eid)
        cm = _reg_cambios(d.get("cambios"), x["tipo"], c)
        if x["tipo"] == "pregunta" and (cm.get("campos") or {}).get("respuesta") and "estado" not in cm and x["estado"] in ("", "abierto", "en curso"):
            cm["estado"] = "hecho"  # responderla la cierra (se reabre a mano)
        _ok(registro.editar, eid, cm, uuid.uuid4().hex[:10])
        if cm.get("dueno") and cm["dueno"] != x["dueno"]:
            destinos.al_asignar(c, eid)  # recetas «al asignar» (A4)
        return registro.completas([registro.de(c, eid)])[0]


@app.delete("/api/reg/{eid}")
def reg_borrar(eid: str, c: str):
    c = _c({"c": c})
    with registro.LOCK:
        _ok(registro.de, c, eid)
        registro.borrar(eid)
    return {"ok": True}


# ---------- F6 Informe de estado / comité (/api/reg/informes; informe.py) ----------
import informe  # noqa: E402


def _inf_docs(c):
    ds = carpetas.docs(_ms(c))
    registro.sincronizar(c, ds)  # KPIs sobre las entidades al día (como /api/reg)
    return ds


def _inf_vista(c, x):
    return {
        **x,
        "graficos": informe.graficos(x["contenido"]["kpis"]),
        "etiquetas": informe.ETIQUETAS,
        "proyecto": {"carpeta": c, "datos": (registro.proyecto(c, False) or {}).get("datos") or []},
        "en_cola": any(e["kind"] == "informe" and e["spec"].get("c") == c and e["state"] in ACTIVOS for e in cola),
    }


def _informe_fn(d):
    """Trabajo «informe»: narrativa con IA (un LLM a la vez) en una versión nueva del informe d["id"]."""
    c = d["c"]

    def fn(cb):
        ms = _ms(c)
        ds = _inf_docs(c)
        cb(0.05, "Arrancando modelo de lenguaje…")
        with _llm_ctx(d, [m["id"] for m in ms], carpetas.terminos_prompt(c))() as chat:
            cb(0.3, "Redactando el informe…")
            x = informe.redactar_informe(c, d["id"], chat, ds)
        return {"carpeta": c, "informe": x["id"]}

    return fn


FNS["informe"] = _informe_fn


@app.get("/api/reg/informes")
def inf_listar(c: str):
    c = _c({"c": c})
    return {"items": informe.listar(c), "periodo": informe.periodo_defecto(c)}


@app.post("/api/reg/informes")
def inf_crear(d: dict):
    """{c, desde?, hasta?, titulo?}: borrador nuevo (periodo por defecto: desde el último informe o los últimos 30 días)."""
    c = _c(d)
    return _inf_vista(c, _ok(informe.crear, c, d.get("desde"), d.get("hasta"), d.get("titulo"), _inf_docs(c)))


@app.get("/api/reg/informes/{iid}")
def inf_ver(iid: int, c: str):
    c = _c({"c": c})
    return _inf_vista(c, _ok(informe.obtener, c, iid))


@app.patch("/api/reg/informes/{iid}")
def inf_editar(iid: int, d: dict):
    """{c, cambios: {titulo, desde, hasta, estado, notas, narrativa, semaforos, umbrales}} (misma versión; ver informe.editar)."""
    c = _c(d)
    return _inf_vista(c, _ok(informe.editar, c, iid, d.get("cambios")))


@app.delete("/api/reg/informes/{iid}")
def inf_borrar(iid: int, c: str):
    """Elimina esa versión (la serie entera si era la única). -> {ok, id: última versión que queda o null}."""
    c = _c({"c": c})
    return {"ok": True, "id": _ok(informe.eliminar, c, iid)}


@app.post("/api/reg/informes/{iid}/recalcular")
def inf_recalcular(iid: int, d: dict):
    c = _c(d)
    return _inf_vista(c, _ok(informe.recalcular, c, iid, _inf_docs(c)))


@app.post("/api/reg/informes/{iid}/redactar")
def inf_redactar(iid: int, d: dict):
    """{c, nube?, gpu?, calidad?}: encola la narrativa con IA (op «informe»)."""
    c = _c(d)
    _ok(informe.obtener, c, iid)
    if d.get("nube"):  # los documentos de una plantilla «solo en este equipo» no salen a la nube
        for m in _ms(c):
            _nube_spec({"nube": d["nube"]}, _tpl_de(m["id"]))
        _nube_spec(d)
    falta(d, "fondo", False)
    return start("informe", {**d, "c": c, "id": iid}, c, "")


@app.get("/api/reg/informes/{iid}/exportar")
def inf_exportar(iid: int, c: str, fmt: str, borrador: int = 1, estilo: str | None = None):
    c = _c({"c": c})
    try:
        datos, nombre, mime = _ok(informe.exportar, c, iid, fmt, bool(borrador), carpetas.docs(_ms(c)), estilo)
    except exportar.SinNavegador as ex:
        raise HTTPException(409, str(ex))
    return Response(datos, media_type=mime, headers={"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(nombre)})


@app.get("/api/carpetas/resumen")
def carpetas_resumen():
    """Para las tarjetas del inicio: {carpeta: {pend, sug, ultima}}."""
    return carpetas.resumen_home(meetings())


# ---------- Preguntar ----------
who = lambda s: (s["spk"] + ": " if s.get("spk") else "") + s["text"]  # con nombres (transcripción importada) las citas dicen quién habla


def _tramos_registro(c, es):
    """Lo generado del proyecto como tramos para Preguntar: cada entidad del registro (preguntas con su respuesta, decisiones, tareas…)
    y el resumen de cada reunión. Enlazan a donde se respondió o se dijo; lo que no viene de una reunión, al «Registro del proyecto»."""
    mi, out = {e["id"]: k for k, e in enumerate(es)}, []
    for x in registro.completas([x for x in registro.listar(c) if x["revision"] not in (*registro.OCULTA, "descartado")]):
        r, rd = x["campos"].get("respuesta"), x["campos"].get("respuesta_de") or {}
        ci = next((ci for ci in x["citas"] if ci["mid"] in mi), None)
        m, t = (mi[rd["mid"]], rd.get("t") or 0) if rd.get("mid") in mi else (mi[ci["mid"]], ci["t"] or 0) if ci else (None, 0)
        tipo = {"decision": "Decisión"}.get(x["tipo"], x["tipo"].capitalize())
        out.append(
            {
                "s": t,
                "m": m,
                "text": " ".join(
                    filter(
                        None,
                        [
                            f"{tipo} {x['codigo']}:" if x["codigo"] else f"{tipo}:",
                            x["titulo"].rstrip(".") + ".",
                            x["detalle"],
                            x["dueno"] and f"Responsable: {x['dueno']}.",
                            x["estado"] and f"Estado: {x['estado']}.",
                            r and f"Respuesta: {r}",
                        ],
                    )
                ),
            }
        )
    for k, e in enumerate(es):
        if res := indice(e["sel"]).acta()[0]:
            out.append({"s": 0, "m": k, "text": f"Resumen de «{e['label']}»: {res}"})
    return out


def indice(sel):
    """Índice RAG de una reunión ("id|asr") o de una carpeta ("c:nombre": la última transcripción de cada reunión de la carpeta + lo
    generado del proyecto, ver _tramos_registro; un cambio en el registro rehace solo el índice de la carpeta)."""
    if sel.startswith("c:"):
        es = list({e["id"]: e for e in reversed(meetings()) if e["carpeta"] == sel[2:] and not e["sin"]}.values())
        if not es:
            raise HTTPException(400, "Carpeta vacía")
        ex = _tramos_registro(sel[2:], es)
        key = "c:" + repr([(e["sel"], e["label"]) for e in es]) + hashlib.sha1(repr(ex).encode()).hexdigest()[:10]
        if key not in _idx:
            for k in [k for k in _idx if k.startswith("c:" + repr([(e["sel"], e["label"]) for e in es]))]:
                del _idx[k]  # la versión anterior del registro
            _idx[key] = rag.Multi([(e["label"], e["video"], indice(e["sel"])) for e in es], ex)
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
    cg = sel[2:] if sel.startswith("c:") else meta(pipeline.WORK / Path(sel.split("|")[0]).name).get("carpeta", "")  # carpeta: su glosario y sus pendientes
    ms = _ms(cg) if sel.startswith("c:") else [m for m in _ms(cg) if m["id"] == sel.split("|")[0]]
    if (pq := carpetas.pregunta_pendientes(cg, ms, q)) is not None:  # «¿qué tiene pendiente Ana?»: lista determinista de los datos, sin LLM
        vid = {m["id"]: m["video"] for m in ms}
        its = [
            {k: p[k] for k in ("texto", "resp", "plazo", "fecha", "dias", "tipo", "mid", "ver", "doc", "t", "pronto", "vencido")} | {"v": vid.get(p["mid"])}
            for p in pq["items"]
        ]
        return StreamingResponse(
            iter(
                [
                    json.dumps({"k": "pendientes", "resp": pq["resp"], "items": its, "en": rag.lang_q(q)}, ensure_ascii=False) + "\n",
                    json.dumps({"k": "fin"}) + "\n",
                ]
            ),
            media_type="application/x-ndjson",
        )
    if (
        sel.startswith("c:") and (registro.sincronizar(cg, carpetas.docs(ms)) or True) and (rq := preguntar_reg.pregunta(cg, q, ms)) is not None
    ):  # «riesgos abiertos», «qué decidimos sobre X»: del registro, sin LLM
        return StreamingResponse(
            iter([json.dumps({"k": "lista", **rq, "en": rag.lang_q(q)}, ensure_ascii=False) + "\n", json.dumps({"k": "fin"}) + "\n"]),
            media_type="application/x-ndjson",
        )
    if aux["on"] or any(e["state"] == "marcha" for e in cola):
        raise HTTPException(409, "Hay un trabajo en marcha: espera a que termine")
    if d.get("nube"):  # también los documentos de una plantilla «solo en este equipo» quedan fuera de la nube
        for m in ms:
            _nube_spec({"nube": d["nube"]}, _tpl_de(m["id"]))
        _nube_spec(d)
    falta(d, "preguntar")
    if not sel.startswith("c:") and _solo_acta(*sel.split("|")):
        raise HTTPException(400, "Esta acta se importó sin transcripción: no se puede preguntar sobre ella")
    og = lambda t: carpetas.ortografia(cg, t)  # ortografía del glosario en lo que se muestra (lo verificado no cambia)

    def events():
        line = lambda **k: json.dumps(k, ensure_ascii=False) + "\n"
        try:
            idx = indice(sel)
            multi = idx.multi
            inf = lambda i: (
                ({"n": idx.names[idx.segs[i]["m"]], "v": idx.vids[idx.segs[i]["m"]]} if multi else {})
                | (  # carpeta: reunión y vídeo de cada tramo
                    {"loc": idx.segs[i]["loc"]} if idx.segs[i].get("loc") else {}
                )
            )  # documento: página o sección
            gpu = pipeline.use_gpu(d.get("gpu"))
            if d.get("nube"):  # nube: sin servidor local ni GPU; la respuesta lleva la marca
                url = d["nube"]
                if url.get("anonimizar"):  # nombres conocidos y los del modelo local (este va en exclusiva: nunca a la vez que la cola)
                    with gpu_exclusiva():
                        url = nube.con_nombres(url, [pipeline.WORK / m["id"] for m in ms], carpetas.terminos_prompt(cg))
                yield line(k="marca", text=nube.marca(url))
            else:
                if _llm.get("gpu") not in (None, gpu):  # cambió la casilla: otro servidor (solo uno a la vez en la GPU)
                    parar_llm()
                if not _llm.get("url"):
                    yield line(k="arranque")
                    _llm["url"], _llm["proc"] = rag.server(THREADS, gpu=gpu)
                    _llm["gpu"] = gpu
                url = _llm["url"]
            for kind, v in rag.answer(idx, q, url):
                if pipeline.NOTICE:
                    yield line(k="aviso", text=pipeline.NOTICE.pop())
                if kind == "candidatos":
                    yield line(k="candidatos", items=[{"t": idx.segs[i]["s"], "text": og(who(idx.segs[i])[:200]), **inf(i)} for i in v])
                elif kind == "frase":
                    s = idx.segs[v["i"]]
                    refs = v.get("refs", [v["i"]])  # estilo interpretativo: puede citar varios tramos
                    yield line(
                        k="frase",
                        t=s["s"],
                        **inf(v["i"]),
                        ok=v["ok"],
                        text=og(v["frase"] if v["ok"] else v["cita"]),
                        kind=v.get("kind", "dijo"),
                        mas=[{"t": idx.segs[j]["s"], **inf(j)} for j in refs[1:]],
                        cita=[
                            {"t": idx.segs[j]["s"], "text": og(who(idx.segs[j])), "main": j in refs, **inf(j)}
                            for j in dict.fromkeys(k for r in refs for k in idx.window(r))
                        ],
                    )
                elif kind == "nada":
                    yield line(k="nada", text=rag.no_dice(q))
        except Exception as e:
            yield line(k="error", text=str(e))
        yield line(k="fin")

    return StreamingResponse(events(), media_type="application/x-ndjson")


LOTE_MAX, LOTE_GB = 500, 20  # ficheros y GB descomprimidos como mucho por zip de lote
BASURA = re.compile(r"^(?:\.|~\$|__MACOSX$)|^(?:thumbs\.db|desktop\.ini)$", re.I)


def adjuntos_correo(d, v):
    """Adjuntos compatibles de un .eml/.msg -> a la cola con las mismas opciones (carpeta, plan…). Devuelve sus ids; los demás se ignoran."""
    try:
        c = documentos.correo(v)
    except Exception as ex:
        raise HTTPException(400, f"No se puede leer el correo: {ex}")
    ok, ids = MEDIA + TR_EXT + documentos.EXT + (".zip",), []
    h = hashlib.sha1(f"{v.name}|{v.stat().st_size}|{v.stat().st_mtime_ns}".encode()).hexdigest()[:12]
    for n, a in enumerate(c["adjuntos"][:LOTE_MAX]):
        nombre = Path(str(a.get("nombre") or "")).name
        if not nombre or BASURA.search(nombre) or Path(nombre).suffix.lower() not in ok:
            continue
        f = UPLOADS / f"correo_{h}" / str(n) / nombre
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(a["datos"])
        try:
            r = generar({**d, "video": str(f), "transcripcion": "", "enlace": "", "descripcion": ""})
            ids += r.get("ids") or [r["id"]]
        except HTTPException:
            pass  # un adjunto que no se puede procesar no impide el correo
    return ids


def lote(d, zp):
    """Zip de ficheros sueltos: cada uno compatible (vídeo, audio, documento, imagen, transcripción; también en subcarpetas) entra en la
    cola con las mismas opciones, uno tras otro. Un zip exportado por la app (index.html + acta.json en la raíz) se importa como siempre.
    Seguro: solo se usa el nombre del fichero (nunca la ruta del zip), se saltan ocultos/__MACOSX y se limitan número y tamaños."""
    if not zp.is_file() or not zipfile.is_zipfile(zp):
        raise HTTPException(400, "El .zip no se puede abrir")
    ok = MEDIA + TR_EXT + documentos.EXT
    with zipfile.ZipFile(zp) as z:
        if {"index.html", "acta.json"} <= set(z.namelist()):
            return importar({"path": str(zp), "carpeta": d.get("carpeta")})
        infos, omitidos = [], []
        for i in z.infolist():
            partes = re.split(r"[\\/]", i.filename)
            if i.is_dir() or any(BASURA.search(x) for x in partes if x):
                continue
            if Path(partes[-1]).suffix.lower() not in ok or i.file_size > 1000 * max(i.compress_size, 1024) and Path(partes[-1]).suffix.lower() not in MEDIA:
                omitidos.append(partes[-1])  # no compatible o comprimido de forma sospechosa (bomba)
            else:
                infos.append((i, partes[-1]))
        if not infos:
            raise HTTPException(400, "El zip no tiene ficheros compatibles (vídeo, audio, PDF, Markdown, texto, Word, HTML o imagen)")
        if len(infos) > LOTE_MAX or sum(i.file_size for i, _ in infos) > LOTE_GB * 2**30:
            raise HTTPException(400, f"El zip es demasiado grande (como mucho {LOTE_MAX} ficheros y {LOTE_GB} GB)")
        h = hashlib.sha1(f"{zp.name}|{zp.stat().st_size}|{zp.stat().st_mtime_ns}".encode()).hexdigest()[:12]
        fs = []
        for n, (i, nombre) in enumerate(infos):
            f = UPLOADS / f"lote_{h}" / str(n) / nombre
            f.parent.mkdir(parents=True, exist_ok=True)
            with z.open(i) as src, open(f, "wb") as dst:  # zipfile corta en el tamaño declarado y comprueba el CRC
                shutil.copyfileobj(src, dst)
            fs.append(f)
    ids, errores = [], []
    for f in fs:
        try:
            ids.append(generar({**d, "video": str(f), "transcripcion": "", "enlace": "", "descripcion": ""})["id"])
        except HTTPException as ex:
            errores.append({"fichero": f.name, "error": ex.detail})
    if not ids:
        raise HTTPException(400, errores[0]["error"])
    return {"lote": len(ids), "ids": ids, "errores": errores, "omitidos": omitidos}


@app.get("/api/buscar")
def get_buscar(q: str = "", c: str = "", tipo: str = "", limit: int = 20):
    """Búsqueda global (buscar.py): {fragmentos: [...], elementos: [...]}. c: carpeta (vacío = todas); tipo: video|audio|pdf|texto|imagen,
    voz|pantalla|descripcion o un tipo de entidad (tarea, decision, requisito…)."""
    return buscar.buscar(meetings(), q.strip()[:300], c or None, tipo, max(1, min(limit, 200)))


def _tr_de(wd):
    trs = sorted(wd.glob("transcript_*.json"), key=os.path.getmtime, reverse=True)
    if not trs:
        raise HTTPException(404, "Documento no encontrado")
    return trs[0]


@app.post("/api/imagen/{mid}")
def editar_imagen(mid: str, d: dict):
    """{descripcion?, descripcion_ia?}: lo que el usuario corrige de una imagen (entra al momento en Buscar y Preguntar)."""
    wd = pipeline.WORK / Path(mid).name
    try:
        documentos.reescribir(_tr_de(wd), **{k: d[k] for k in ("descripcion", "descripcion_ia") if k in d})
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    return get_fuente(mid)


@app.post("/api/describir")
def describir(d: dict):
    """{id, gpu?, nube?}: encola rehacer con IA la descripción de una imagen (o de las capturas de una reunión). 409 si no hay modelo de visión."""
    wd = pipeline.WORK / Path(d.get("id") or "").name
    _tr_de(wd)
    if d.get("nube"):
        _nube_spec(d, _tpl_de(wd.name))
    if not vision.elegir(_ajustes(), d.get("nube")):
        raise HTTPException(409, {"msg": vision.FALTA, "faltan": ["vision"]})
    return start("describir", {k: d[k] for k in ("gpu", "nube") if d.get(k)} | {"mid": wd.name}, meta(wd).get("nombre") or wd.name, wd.name)


@app.get("/api/fuente/{mid}")
def get_fuente(mid: str):
    """Lo que la vista «Fuente» enseña de un documento: kind, url del original (PDF/imagen…), descripción y su texto por página/sección
    [{loc, t, texto}] (t: la marca a la que apuntan las citas del documento)."""
    wd = pipeline.WORK / Path(mid).name
    tr = json.loads(_tr_de(wd).read_text(encoding="utf-8"))
    partes = []
    for s in tr["segments"]:
        if partes and partes[-1]["loc"] == s.get("loc"):
            partes[-1]["texto"] += " " + s["text"]
        else:
            partes.append({"loc": s.get("loc"), "t": s["s"], "texto": s["text"]})
    fu, imp = next(wd.glob("fuente.*"), None), tr.get("importada") or {}
    ci = wd / "capturas_ia.json"
    return {
        "kind": _kind(wd, exacto=True),
        "url": f"/files/{wd.name}/{fu.name}" if fu else None,
        "nombre": imp.get("fuente"),
        "paginas": imp.get("paginas"),
        "ocr": imp.get("ocr", []),
        "partes": partes,
        "vision": vision.estado(vision.elegir(_ajustes())),
        **{k: imp.get(k, "") for k in ("descripcion", "descripcion_ia", "ocr_texto") if imp.get("tipo") == "imagen"},
        "capturas_ia": json.loads(ci.read_text(encoding="utf-8")) if ci.exists() else {},
    }


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
def modelos_encontrados(emb: bool = False):
    """GGUF del equipo (emb=true: solo de embeddings) + la configuración (niveles, extra y roles)."""
    return {"encontrados": models.escanear(emb), "config": json.loads(pipeline.leer_texto(pipeline.MODELOS)) if pipeline.MODELOS.exists() else {}}


@app.post("/api/modelos/usar")
def usar_modelo(d: dict):
    """{ruta, nivel: calidad | "pers" | "chat" | "emb" | "", nombre?}"""
    if not models.usar(d.get("ruta", ""), d.get("nivel", ""), d.get("nombre", "")):
        raise HTTPException(400, "Elige un fichero .gguf y un nivel válido")
    parar_llm(), rag.emb_stop(), _idx.clear()  # el chat y el índice se rehacen con el modelo nuevo
    return {**modelos_encontrados(), "roles": models.roles()}


@app.get("/api/modelos/roles")
def get_roles():
    """Búsqueda (emb) y Chat de Preguntar (chat): modelo en uso, si es el de serie y si cabe en este equipo."""
    return models.roles()


@app.post("/api/modelos/roles/quitar")
def quitar_rol(d: dict):
    if d.get("rol") not in models.ROLES:
        raise HTTPException(400, "Rol no válido")
    models.quitar_rol(d["rol"])
    parar_llm(), rag.emb_stop(), _idx.clear()
    return models.roles()


@app.post("/api/modelos/hf/info")
def hf_info(d: dict):
    """{entrada: URL de Hugging Face o «usuario/repo[/fichero.gguf]»} -> ficheros .gguf con su tamaño."""
    try:
        return models.hf_info(d.get("entrada", ""))
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    except OSError as ex:
        raise HTTPException(502, "No se pudo consultar Hugging Face: " + str(ex)[:150])


@app.post("/api/modelos/hf/bajar")
def hf_bajar(d: dict):
    """{repo, fichero, nivel: calidad | "pers" | "chat" | "emb", bytes?, nombre?}: descarga y asigna; el progreso sale en GET /api/modelos."""
    try:
        models.hf_bajar(d.get("repo", ""), d.get("fichero", ""), d.get("nivel", "pers"), d.get("nombre", ""), int(d.get("bytes") or 0))
    except (ValueError, RuntimeError) as ex:
        raise HTTPException(400, str(ex))
    return models.status()


# ---------- Perfiles de uso propios (se suman a los de serie del asistente) ----------
PERFILES = pipeline.WORK / "perfiles_uso.json"


def _perfiles():
    try:
        d = json.loads(PERFILES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return d if isinstance(d, list) else []


@app.get("/api/perfiles-uso")
def get_perfiles():
    return _perfiles()


@app.post("/api/perfiles-uso")
def set_perfil(d: dict):
    """Crea (sin id) o edita (con id) un perfil de uso: {id?, nombre, plantillas, carpeta, documento, nuevo_boton, nube, anonimizar}."""
    nombre = str(d.get("nombre") or "").strip()[:60]
    ids = {t["id"] for t in plantillas.todas()}
    pl = [x for x in dict.fromkeys(d.get("plantillas") or []) if x in ids]
    if not nombre or not pl:
        raise HTTPException(400, "Pon un nombre y elige al menos una plantilla")
    txt = lambda k, v: str(d.get(k) or v).strip()[:40] or v
    ps = _perfiles()
    pid = d.get("id") or "u-" + hashlib.sha1((nombre + str(time.time())).encode()).hexdigest()[:8]
    if d.get("id") and not any(p["id"] == pid for p in ps):
        raise HTTPException(404, "No existe ese perfil")
    p = {
        "id": pid,
        "nombre": nombre,
        "plantillas": pl,
        "carpeta": txt("carpeta", "Carpeta"),
        "documento": txt("documento", "documento"),
        "nuevo_boton": txt("nuevo_boton", "+ Añadir"),
        "nube": bool(d.get("nube", True)),
        "anonimizar": bool(d.get("anonimizar", False)),
    }
    pipeline.WORK.mkdir(exist_ok=True)
    PERFILES.write_text(
        json.dumps([p if x["id"] == pid else x for x in ps] + ([] if any(x["id"] == pid for x in ps) else [p]), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return p


@app.post("/api/perfiles-uso/borrar")
def del_perfil(d: dict):
    PERFILES.write_text(json.dumps([p for p in _perfiles() if p["id"] != d.get("id")], ensure_ascii=False, indent=1), encoding="utf-8")
    return _perfiles()


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


def _encolar(rutas, c="", recursivo=False, plan=None):
    """«Enviar a → Actas» / menú contextual: encola vídeos, audios y transcripciones (y el contenido de carpetas) con las opciones por defecto,
    por el mismo camino que /api/generar. -> {ids, omitidas}."""
    fs, om = [], []
    for r in rutas:
        p = Path(str(r))
        if p.is_dir():
            fs += sorted(x for x in (p.rglob("*") if recursivo else p.iterdir()) if x.is_file())
        elif p.is_file():
            fs.append(p)
        else:
            om.append(f"{r}: no existe")
    ids = []
    for p in fs:
        if p.suffix.lower() not in (*MEDIA, *TR_EXT, *documentos.EXT, ".zip"):  # lo mismo que admite soltar/elegir
            om.append(f"{p.name}: formato no admitido") if p in map(Path, rutas) else None
            continue
        try:
            r = generar(
                {"video": str(p), **({"carpeta": c} if c else {}), **({"plan": plan} if plan else {})}
            )  # generar decide: medio, transcripción, documento o lote .zip
            ids += r.get("ids") or [r["id"]]
        except HTTPException as e:
            om.append(f"{p.name}: {e.detail}")
    return {"ids": ids, "omitidas": om}


@app.post("/api/subir")
def subir(d: dict, request: Request):
    """{c, nombre, base64, resumir?, perfil?, nube?}: añade un documento (agentes y servidor de equipo, donde no hay rutas del disco).
    Sin resumir solo se lee e indexa (sin IA); con resumir se hace también el resumen (en el servidor, con nube). -> {id del trabajo}."""
    c = _c(d)
    nombre = Path(str(d.get("nombre") or "")).name.strip()[:120]
    ok = documentos.TEXTO + (documentos.IMAGEN if d.get("nube") or not servidor.ACTIVO else ())  # imágenes: describirlas pide IA
    if Path(nombre).suffix.lower() not in ok:
        raise HTTPException(400, "Formato no admitido: " + ", ".join(sorted({e.lstrip(".") for e in ok})))
    ps = agentes.permisos(request)
    if d.get("resumir") and ps is not None and "ia" not in ps:
        raise HTTPException(403, "Este agente no tiene el permiso «ia»: sube sin resumir")
    b64 = str(d.get("base64") or "")
    if len(b64) > SUBIR_MAX * 4 // 3 + 4:
        raise HTTPException(413, f"Como mucho {SUBIR_MAX >> 20} MB")
    try:
        datos = base64.b64decode(b64, validate=True)
    except ValueError:
        raise HTTPException(400, "base64 no válido")
    if not datos:
        raise HTTPException(400, "Fichero vacío")
    f = pipeline.WORK / "subidas" / uuid.uuid4().hex[:8] / nombre
    f.parent.mkdir(parents=True)
    f.write_bytes(datos)
    spec = {"video": str(f), "carpeta": c, "buscable": not d.get("resumir")}
    spec |= {k: v for k, v in (("plantilla", d.get("perfil")), ("nube", d.get("nube"))) if v}
    try:
        return generar(spec)
    except HTTPException:
        shutil.rmtree(f.parent, ignore_errors=True)
        raise


@app.post("/api/encolar")
def encolar(d: dict, request: Request):
    if (request.client.host if request.client else "") not in ("127.0.0.1", "::1", "testclient"):
        raise HTTPException(403, "Solo desde este equipo")
    rutas = d.get("rutas")
    if not isinstance(rutas, list) or not rutas or not all(isinstance(r, str) for r in rutas):
        raise HTTPException(400, "Indica rutas[]")
    r = _encolar(rutas, str(d.get("c") or "").strip()[:120], bool(d.get("recursivo")))
    if not r["ids"]:
        raise HTTPException(400, "Nada que encolar: " + "; ".join(r["omitidas"][:3]))
    return r


mcp_servidor.A = sys.modules[__name__]
vigiladas.configurar(lambda r, c, p: _encolar(r, c, plan=p), (*MEDIA, *TR_EXT, *documentos.EXT, ".zip"))
app.router.on_startup.append(vigiladas.iniciar)
app.router.routes.extend(vigiladas.router.routes + mcp_servidor.router.routes)
app.router.routes.extend(msgraph.router.routes)  # (include_router rompe test_urls_js_tienen_ruta: _IncludedRouter no tiene .path)
servidor.montar(app)
agentes.A, agentes.M = sys.modules[__name__], mcp_servidor
investigacion.A = sys.modules[__name__]
app.router.routes.extend(investigacion.router.routes)
agentes.montar(app)  # después de servidor.montar: su filtro corre antes
app.mount("/", StaticFiles(directory=STATIC, html=True))


def vivo():
    """URL de otra instancia en marcha (el lock guarda su puerto), o None."""
    try:
        url = f"http://127.0.0.1:{int(LOCK.read_text(encoding='utf-8'))}"
        return url if urllib.request.urlopen(url + "/api/ping", timeout=2).read() == b'"actas"' else None
    except (OSError, ValueError):
        return None


if __name__ == "__main__":
    if "--mcp-stdio" in sys.argv:  # puente stdio -> /mcp de la instancia en marcha (clientes MCP que no hablan HTTP)
        if not (url := vivo()):
            sys.exit("Actas no está en marcha: ábrela primero.")
        sys.exit(mcp_servidor.stdio(url))
    pipeline.WORK.mkdir(parents=True, exist_ok=True)
    if servidor.ACTIVO:  # Coolify/Docker: toda la red, sin navegador, sin apagarse por inactividad, sin lock de instancia
        uvicorn.run(
            app,
            host=os.environ.get("ACTAS_HOST", "0.0.0.0"),
            port=int(os.environ.get("ACTAS_PORT", 8000)),
            log_level="info",
            proxy_headers=True,
            forwarded_allow_ips="*",
        )
        sys.exit()
    if sys.stdout is None:  # pythonw (Windows, sin consola): uvicorn y print necesitan un destino
        sys.stdout = sys.stderr = open(pipeline.WORK / "app.log", "a", encoding="utf-8")
    enc = None
    if "--encolar" in sys.argv:  # app.py --encolar <rutas…> [--carpeta X]: a la instancia en marcha, o arranca y encola
        a = sys.argv[sys.argv.index("--encolar") + 1 :]
        carp = ""
        if "--carpeta" in a:
            i = a.index("--carpeta")
            carp, a = " ".join(a[i + 1 : i + 2]), a[:i] + a[i + 2 :]
        enc = ([str(Path(x).resolve()) for x in a], carp)
        for _ in range(16 if LOCK.exists() else 1):  # arranque en curso (varias selecciones a la vez): esperar al puerto
            if vivo() or not LOCK.exists():
                break
            time.sleep(0.5)
    if url := vivo():
        if enc:
            urllib.request.urlopen(
                urllib.request.Request(url + "/api/encolar", json.dumps({"rutas": enc[0], "c": enc[1]}).encode(), {"Content-Type": "application/json"}),
                timeout=30,
            )
        os.environ.get("ACTAS_NO_BROWSER") or webbrowser.open(url)
        sys.exit()
    if os.environ.get("ACTAS_PORT"):  # puerto fijo (pruebas); uvicorn lo abre con SO_REUSEADDR
        port = int(os.environ["ACTAS_PORT"])
    else:  # siempre el mismo (marcadores y localStorage sobreviven al reinicio); si está ocupado, uno libre cualquiera
        for p in (PUERTO, 0):
            with socket.socket() as s:
                try:
                    s.bind(("127.0.0.1", p))
                except OSError:
                    continue
                port = s.getsockname()[1]
                break
    procs.cleanup_stale()
    LOCK.write_text(str(port), encoding="utf-8")
    atexit.register(lambda: LOCK.unlink(missing_ok=True))
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))

    def vigila():
        while grabar.activa() or time.time() - beat[0] < (IDLE_JOB if any(e["state"] in ACTIVOS for e in cola) else IDLE):
            time.sleep(2)
        srv.should_exit = True

    threading.Thread(target=vigila, daemon=True).start()
    kick()  # retoma lo que quedó pendiente
    if enc:
        _encolar(*enc)
    if not os.environ.get("ACTAS_NO_BROWSER"):  # CI/pruebas sin navegador
        threading.Timer(1, webbrowser.open, [f"http://127.0.0.1:{port}"]).start()
    procs.on_signal(lambda: setattr(srv, "should_exit", True))
    srv.run()
