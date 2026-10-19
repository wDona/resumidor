"""Interfaz web local (FastAPI + página estática): vídeo -> acta HTML, vídeo condensado y preguntas. `uv run app.py`."""
import atexit
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import models
import pipeline
import rag

THREADS = int(os.environ.get("ACTAS_THREADS", pipeline.PHYS))
STATIC, LOCK, JOBF = pipeline.ROOT / "static", pipeline.ROOT / ".actas.lock", pipeline.WORK / "job.json"
UPLOADS = pipeline.ROOT / "uploads"
IDLE = 60  # s sin latido de la página y el servidor se cierra
app = FastAPI()
beat = [time.time()]
job = {"state": "idle"}  # state: idle | running | done | error; kind: acta | condensar
jlock = threading.Lock()


def save_job():
    pipeline.WORK.mkdir(exist_ok=True)
    JOBF.write_text(json.dumps(job, ensure_ascii=False))


try:  # recarga/reinicio: un trabajo que figuraba en marcha ya no tiene hilo
    job.update(json.loads(JOBF.read_text()))
    if job["state"] == "running":
        job.update(state="error", error="El trabajo se interrumpió al cerrar la aplicación")
except (OSError, ValueError):
    pass


# ---------- LLM compartido por «Preguntar» ----------
_llm, _idx = {}, {}


def parar_llm():
    if _llm.get("proc"):
        _llm.pop("proc").terminate()
    _llm.clear()


atexit.register(parar_llm)


# ---------- Trabajos ----------
def start(kind, fn, **info):
    with jlock:
        if job["state"] == "running":
            raise HTTPException(409, "Ya hay un trabajo en marcha")
        job.clear()
        job.update(state="running", kind=kind, frac=0, msg="Empezando…", t0=time.time(), **info)
        save_job()
    parar_llm()  # dos modelos de 3 GB a la vez no caben en 8 GB

    def cb(f, m):
        job.update(frac=round(f, 4), msg=m)

    def work():
        try:
            job["result"] = fn(cb)
            job.update(state="done", frac=1, msg="Listo")
        except Exception as e:
            job.update(state="error", error=str(e) or type(e).__name__)
        save_job()

    threading.Thread(target=work, daemon=True).start()


@app.get("/api/job")
def get_job():
    j = dict(job)
    if j.get("state") == "running" and j["frac"] > 0.03:
        j["eta"] = round((time.time() - j["t0"]) * (1 - j["frac"]) / j["frac"])
    if j.get("state") == "running":
        save_job()
    return j


@app.post("/api/generar")
def generar(d: dict):
    video = Path(d.get("video", ""))
    if not video.is_file():
        raise HTTPException(400, "Elige primero un vídeo")
    names = {n: v.strip() for n, v in re.findall(r"[Hh]ablante\s*(\d+)\s*=\s*([^,;\n]+)", d.get("nombres") or "")}
    nivel, asr = d.get("nivel", "normal"), d.get("asr", "rápido")
    if nivel not in pipeline.LEVELS or asr not in pipeline.ASR_MODELS:
        raise HTTPException(400, "Opción no válida")

    def fn(cb):
        out, _, _ = pipeline.run(video, nivel, asr, THREADS, cb, names, bool(d.get("hablantes")))
        return {"id": out.parent.name, "acta": out.name}
    start("acta", fn, video=video.name)


@app.post("/api/condensar")
def condensar(d: dict):
    wd, asr, pct = pipeline.WORK / Path(d["id"]).name, d.get("asr", "rápido"), int(d.get("pct", 40))
    if not (wd / f"cortes_{asr}.json").exists():
        raise HTTPException(400, "Genera primero el acta")

    def fn(cb):
        pipeline.condense(wd, asr, pct, THREADS, cb)
        return {"id": wd.name}
    start("condensar", fn, video=wd.name)


# ---------- Vídeo de entrada ----------
@app.post("/api/pick")
def pick():
    """Diálogo nativo de Tk en un subproceso (Tk no admite hilos ajenos al principal): devuelve la ruta real, sin copiar."""
    code = ("import tkinter as t, tkinter.filedialog as f\nr=t.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
            "print(f.askopenfilename(title='Elegir vídeo', filetypes=[('Vídeo', '*.mp4 *.mkv *.webm *.mov *.avi *.m4v'), ('Todos', '*')]))")
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8")
    return {"path": p.stdout.strip()}


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
def meetings():
    out = []
    for tf in sorted(pipeline.WORK.glob("*/transcript_*.json"), key=os.path.getmtime, reverse=True):
        v = next(tf.parent.glob("video.*"), None)
        asr = tf.stem.split("_", 1)[1]
        out.append({"sel": f"{tf.parent.name}|{asr}", "id": tf.parent.name, "asr": asr, "mtime": int(tf.stat().st_mtime),
                    "name": (v.resolve().name if v else tf.parent.name) + ("" if asr == "rápido" else " (calidad)"),
                    "video": f"/files/{tf.parent.name}/{v.name}" if v else None})
    return out


@app.get("/api/meetings")
def get_meetings():
    return meetings()


@app.get("/api/meeting/{mid}")
def meeting(mid: str):
    wd = pipeline.WORK / Path(mid).name
    actas = [{"name": d.name, "nivel": d.name.split("_")[1], "asr": d.name.split("_")[2], "url": f"/files/{wd.name}/{d.name}/index.html",
              "zip": next((f"/files/{wd.name}/{z.name}" for z in wd.glob(f"acta_*_{d.name.split('_')[1]}.zip")), None)}
             for d in sorted(wd.glob("acta_*_*")) if (d / "index.html").exists()]
    if not actas:
        raise HTTPException(404, "Sin actas")
    rec = {c.stem.split("_", 1)[1]: pipeline.recommend_pct(json.loads(c.read_text())) for c in wd.glob("cortes_*.json")}
    conds = [{"name": c.name, "url": f"/files/{wd.name}/{c.name}"} for c in sorted(wd.glob("condensado_*.mp4"))]
    return {"id": wd.name, "actas": actas, "recomendado": rec, "condensados": conds}


@app.get("/files/{mid}/{path:path}")
def files(mid: str, path: str):
    """work/<hash>/...: FileResponse sirve Range (el <video> puede saltar) y sigue enlaces simbólicos (vídeo en otro disco)."""
    parts = Path(mid, path).parts
    f = pipeline.WORK.joinpath(*parts)
    if ".." in parts or not f.is_file():
        raise HTTPException(404)
    return FileResponse(f)


# ---------- Preguntar ----------
@app.post("/api/preguntar")
def preguntar(d: dict):
    sel, q = d.get("sel"), (d.get("q") or "").strip()
    if not sel or not q:
        raise HTTPException(400, "Elige una reunión y escribe la pregunta")
    wd, asr = sel.split("|")
    wd = str(pipeline.WORK / Path(wd).name)
    if job["state"] == "running":
        raise HTTPException(409, "Hay un trabajo en marcha: espera a que termine")

    def events():
        line = lambda **k: json.dumps(k, ensure_ascii=False) + "\n"
        try:
            if sel not in _idx:
                _idx[sel] = rag.Index(wd, asr, THREADS)
            idx = _idx[sel]
            if not _llm.get("url"):
                yield line(k="arranque")
                _llm["url"], _llm["proc"] = rag.server(THREADS)
            for kind, v in rag.answer(idx, q, _llm["url"]):
                if kind == "candidatos":
                    yield line(k="candidatos", items=[{"t": idx.segs[i]["s"], "text": idx.segs[i]["text"][:200]} for i in v])
                elif kind == "frase":
                    s = idx.segs[v["i"]]
                    yield line(k="frase", t=s["s"], ok=v["ok"], text=v["frase"] if v["ok"] else v["cita"],
                               cita=[{"t": idx.segs[j]["s"], "text": idx.segs[j]["text"], "main": j == v["i"]} for j in idx.window(v["i"])])
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
def bajar_modelos():
    models.start()
    return models.status()


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
    LOCK.write_text(str(port))
    atexit.register(lambda: LOCK.unlink(missing_ok=True))
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))

    def vigila():
        while time.time() - beat[0] < IDLE:
            time.sleep(2)
        srv.should_exit = True
    threading.Thread(target=vigila, daemon=True).start()
    if not os.environ.get("ACTAS_NO_BROWSER"):  # CI/pruebas sin navegador
        threading.Timer(1, webbrowser.open, [f"http://127.0.0.1:{port}"]).start()
    srv.run()
