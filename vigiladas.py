"""Carpetas vigiladas (p. ej. OneDrive donde caen las grabaciones de Teams): un hilo mira cada 10 s; un fichero se encola cuando es estable
(mismo tamaño y fecha en dos pasadas). Lo ya encolado se recuerda (ruta+tamaño+fecha) para no repetir tras reiniciar. work/vigiladas.json."""

import fnmatch
import hashlib
import json
import shutil
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException

import destinos
import pipeline as P

router = APIRouter()
LOCK = threading.RLock()
CFG = lambda: P.WORK / "vigiladas.json"
HECHAS = lambda: P.WORK / "vigiladas_hechas.json"
TEMP = ("~$*", "*.tmp", "*.part", "*.crdownload", ".~lock*", ".*")
MAX_HECHAS = 20000
_ctx = {"enc": None, "exts": ()}  # enc(rutas, c, plan) -> {ids, omitidas}; lo pone app.py
_estado, _vistos = {}, {}  # id -> último resultado; ruta -> (tamaño, mtime) de la pasada anterior
_parar, _hilo = threading.Event(), []


def configurar(enc, exts):
    _ctx.update(enc=enc, exts=tuple(exts))


def _leer(f, defecto):
    try:
        return json.loads(Path(f).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def lista():
    d = _leer(CFG(), [])
    return d if isinstance(d, list) else []


def _guardar(xs):
    P.WORK.mkdir(exist_ok=True)
    CFG().write_text(json.dumps(xs, ensure_ascii=False, indent=1), encoding="utf-8")


def _firma(p, st):
    return hashlib.sha1(f"{p}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()


def _candidatos(v):
    r = Path(v["ruta"])
    for p in r.rglob("*") if v.get("recursivo") else r.iterdir():
        if "Procesados" in p.relative_to(r).parts[:-1]:
            continue
        if p.is_file() and p.suffix.lower() in _ctx["exts"] and not any(fnmatch.fnmatch(p.name.lower(), t.lower()) for t in TEMP):
            yield p


def revisar(v):
    """Una pasada sobre una carpeta: encola lo estable y nuevo. Devuelve (y recuerda) su estado {ultima, encoladas, error}."""
    est = {"ultima": time.time(), "encoladas": 0, "error": ""}
    _estado[v["id"]] = est
    try:
        hechas = _leer(HECHAS(), {})
        if not Path(v["ruta"]).is_dir():
            raise OSError("La carpeta no existe o no es accesible")
        for p in list(_candidatos(v)):
            try:
                st = p.stat()
                k, f = str(p), _firma(p, st)
                if f in hechas:
                    continue
                if _vistos.get(k) != (st.st_size, st.st_mtime_ns):  # primera vez o sigue cambiando: esperar a la siguiente pasada
                    _vistos[k] = (st.st_size, st.st_mtime_ns)
                    continue
                _vistos.pop(k, None)
                hechas[f] = int(time.time())  # antes de encolar: si algo falla no se reintenta cada 10 s
                if v.get("mover"):  # se mueve ANTES de encolar: la cola apunta al fichero ya en Procesados/
                    d = p.parent / "Procesados"
                    d.mkdir(exist_ok=True)
                    q = d / p.name if not (d / p.name).exists() else d / f"{p.stem}_{int(time.time())}{p.suffix}"
                    shutil.move(str(p), str(q))
                    p = q
                r = _ctx["enc"]([str(p)], v.get("carpeta") or "", v.get("plan") or None)
                est["encoladas"] += len(r["ids"])
                if not r["ids"] and r["omitidas"]:
                    est["error"] = "; ".join(r["omitidas"][:3])
            except Exception as ex:  # un fichero malo no frena los demás
                est["error"] = f"{p.name}: {ex}"[:300]
        if len(hechas) > MAX_HECHAS:
            hechas = dict(sorted(hechas.items(), key=lambda kv: kv[1])[-MAX_HECHAS // 2 :])
        P.WORK.mkdir(exist_ok=True)
        HECHAS().write_text(json.dumps(hechas), encoding="utf-8")
    except Exception as ex:
        est["error"] = str(ex)[:300]
    return est


def tick():
    for v in lista():
        if v.get("activa", True):
            with LOCK:
                revisar(v)


def iniciar():
    """Arranca (una vez) el hilo: pasada cada 10 s. Nunca rompe la app."""
    if _hilo:
        return

    def bucle():
        while not _parar.is_set():
            try:
                tick()
            except Exception:
                pass
            _parar.wait(10)

    _hilo.append(threading.Thread(target=bucle, daemon=True, name="actas-vigiladas"))
    _hilo[0].start()


# ---------- API ----------
def _limpio(d, o=None):
    o = o or {}
    ruta = str(d.get("ruta", o.get("ruta", ""))).strip()
    if not ruta or not Path(ruta).expanduser().is_dir():
        raise HTTPException(400, "La carpeta no existe")
    try:
        plan = (destinos.normalizar_plan(d["plan"]) if d["plan"] else None) if "plan" in d else o.get("plan")
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    b = lambda k, x: d[k] if isinstance(d.get(k), bool) else o.get(k, x)
    return {
        "id": o.get("id") or uuid.uuid4().hex[:8],
        "ruta": str(Path(ruta).expanduser()),
        "carpeta": str(d.get("carpeta", o.get("carpeta", ""))).strip()[:120],
        "recursivo": b("recursivo", False),
        "activa": b("activa", True),
        "mover": b("mover", False),
        **({"plan": plan} if plan else {}),
    }


def _pub(v):
    return {**v, "estado": _estado.get(v["id"]) or {"ultima": None, "encoladas": 0, "error": ""}}


@router.get("/api/vigiladas")
def api_lista():
    return [_pub(v) for v in lista()]


@router.post("/api/vigiladas")
def api_crear(d: dict):
    with LOCK:
        v = _limpio(d)
        _guardar(lista() + [v])
    return _pub(v)


@router.patch("/api/vigiladas/{i}")
def api_editar(i: str, d: dict):
    with LOCK:
        xs = lista()
        n = next((n for n, v in enumerate(xs) if v["id"] == i), None)
        if n is None:
            raise HTTPException(404, "No existe")
        xs[n] = _limpio(d, xs[n])
        _guardar(xs)
    return _pub(xs[n])


@router.delete("/api/vigiladas/{i}")
def api_borrar(i: str):
    with LOCK:
        xs = lista()
        _guardar([v for v in xs if v["id"] != i])
        _estado.pop(i, None)
    return {"ok": any(v["id"] == i for v in xs)}


@router.post("/api/vigiladas/{i}/revisar")
def api_revisar(i: str):
    v = next((v for v in lista() if v["id"] == i), None)
    if not v:
        raise HTTPException(404, "No existe")
    with LOCK:
        revisar(v)
    return _pub(v)
