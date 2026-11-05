"""Proyecto compartido por una carpeta sincronizada (OneDrive o SharePoint; docs/plan-equipos.md, A2). Sin servidor.

En la carpeta compartida:
  proyecto.json             nombre, tipo, datos y glosario del proyecto
  eventos/<instalación>.jsonl  cambios del registro, uno por línea; cada instalación solo escribe en el suyo (OneDrive no ve conflictos)
  actas/*.md                los documentos de quien los procesó
  transcripciones/*.md      solo si el proyecto lo permite (por defecto no)
Nunca se comparte registro.db (SQLite en carpetas sincronizadas se corrompe) ni los vídeos.

Sincronizar = exportar lo que cambió aquí desde la última vez (diferencia con lo último conocido, campo a campo) y luego leer las líneas
nuevas de los demás. Conflictos: por campo, gana el cambio más reciente (t), y queda en el historial con su autor.
Estado local en work/compartir/<proyecto>.json. app.py llama a montar()."""

import hashlib
import json
import logging
import re
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException

import carpetas
import exportar
import pipeline as P
import registro

router = APIRouter()
A = None  # módulo app (montar)
LOCK = threading.RLock()
log = logging.getLogger(__name__)
COLS = ("tipo", "codigo", "titulo", "detalle", "estado", "revision", "origen", "dueno", "prioridad", "fecha_limite", "fecha_alta", "fecha_cierre")
NO_CAMPOS = ("huerfano", "clave")  # claves de `campos` que son de esta instalación
CADA = 60  # segundos entre sincronizaciones automáticas


def _dir():
    return P.WORK / "compartir"


def _fich(c):
    return _dir() / (hashlib.sha1(c.encode()).hexdigest()[:16] + ".json")


def estado(c):
    try:
        return json.loads(_fich(c).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _guardar(c, s):
    _dir().mkdir(parents=True, exist_ok=True)
    tmp = _fich(c).with_suffix(".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_fich(c))


def instancia():
    f = P.WORK / "instancia"
    try:
        return f.read_text(encoding="utf-8").strip()
    except OSError:
        P.WORK.mkdir(parents=True, exist_ok=True)
        i = uuid.uuid4().hex[:12]
        f.write_text(i, encoding="utf-8")
        return i


def _plano(x):
    """Entidad -> {campo: valor} con `campos` aplanado (campos.k), lo que se compara y se envía."""
    d = {k: x[k] for k in COLS}
    d.update({f"campos.{k}": v for k, v in (x["campos"] or {}).items() if k not in NO_CAMPOS})
    return d


def _nombre_fichero(t):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", t).strip()[:90] or "documento"


# ---------- exportar ----------
def _exportar(c, s, raiz):
    yo, ahora = instancia(), time.time()
    quien = registro.autor() or f"Actas {yo[:4]}"
    lineas = []
    for x in registro.listar(c):
        cur, prev = _plano(x), s["ultimo"].get(x["id"], {})
        cambios = {k: v for k, v in cur.items() if prev.get(k) != v}
        cambios.update({k: None for k in prev if k not in cur})  # clave de campos quitada
        if not cambios:
            continue
        t = x["modificado"] or ahora
        lineas.append({"t": t, "inst": yo, "autor": quien, "id": x["id"], "tipo": x["tipo"], "cambios": cambios})
        s["ultimo"][x["id"]] = cur
        s["t"].setdefault(x["id"], {}).update({k: t for k in cambios})
    if lineas:
        (raiz / "eventos").mkdir(parents=True, exist_ok=True)
        with open(raiz / "eventos" / f"{yo}.jsonl", "a", encoding="utf-8", newline="\n") as f:
            f.writelines(json.dumps(e, ensure_ascii=False) + "\n" for e in lineas)
    e = registro.expediente(c)
    pj = {"actas_proyecto": 1, "nombre": c, "tipo": e.get("tipo") or "", "datos": e.get("datos") or [], "glosario": e.get("glosario") or []}
    f = raiz / "proyecto.json"
    try:
        igual = json.loads(f.read_text(encoding="utf-8")) == pj
    except (OSError, ValueError):
        igual = False
    if not igual:
        f.write_text(json.dumps(pj, ensure_ascii=False, indent=1), encoding="utf-8")
    _documentos(c, s, raiz)
    return len(lineas)


def _documentos(c, s, raiz):
    """Las actas de este equipo como .md (y la transcripción si el proyecto lo permite); solo si cambiaron."""
    for d in carpetas.docs(A._ms(c)):
        try:
            a = exportar.carga(d["mid"], d["ver"], anon=(P.WORK / d["mid"] / d["ver"] / "acta_anonima.json").is_file())
        except (OSError, ValueError, KeyError):
            continue
        base = _nombre_fichero(f"{d.get('fecha') or ''} {a['data'].get('titulo') or d['mid']}") + f" ({d['mid'][:6]})"
        salidas = [("actas", exportar.md(a))]
        if s.get("transcripciones"):
            try:
                salidas.append(("transcripciones", exportar.trans_md(a)))
            except (OSError, ValueError, KeyError):
                pass
        for sub, txt in salidas:
            h = hashlib.sha1(txt.encode()).hexdigest()[:12]
            k = f"{sub}/{d['mid']}"
            if s["docs"].get(k) != h:
                (raiz / sub).mkdir(parents=True, exist_ok=True)
                (raiz / sub / (base + ".md")).write_text(txt, encoding="utf-8")
                s["docs"][k] = h


# ---------- importar ----------
def _aplicar(c, s, ev):
    eid, t = s["alias"].get(ev["id"], ev["id"]), float(ev.get("t") or 0)
    tt = s["t"].setdefault(eid, {})
    nuevos = {k: v for k, v in (ev.get("cambios") or {}).items() if (k in COLS or k.startswith("campos.")) and t >= tt.get(k, 0)}
    if not nuevos:
        return 0
    cols = {k: v for k, v in nuevos.items() if k in COLS and k not in ("tipo", "codigo")}
    cm = {k[7:]: v for k, v in nuevos.items() if k.startswith("campos.")}
    try:
        x = registro.uno(eid)
    except KeyError:
        x = None
    lote = "sync-" + uuid.uuid4().hex[:6]
    if x is None:
        if ev.get("tipo") not in registro.TIPOS:
            return 0
        f = {k: v for k, v in cols.items() if v is not None and k != "origen"}
        x = registro.crear(c, ev["tipo"], lote, quien=ev.get("autor"), id=eid, campos={k: v for k, v in cm.items() if v is not None}, **f)
        cols = {k: v for k, v in cols.items() if k == "origen" or x.get(k) != v}
        cm = {}
    cambios = {**cols, **({"codigo": nuevos["codigo"]} if nuevos.get("codigo") and nuevos["codigo"] != x["codigo"] else {})}
    if cm:
        cambios["campos"] = {k: v for k, v in {**x["campos"], **cm}.items() if v is not None}
    cambios = {k: v for k, v in cambios.items() if k != "origen" or v in ("reunion", "manual", "derivado", "migrado")}
    if cambios:
        x = registro.editar(eid, cambios, lote, quien=ev.get("autor"))
        if "campos" in cambios and len(cambios["campos"]) < len(x["campos"]):  # editar() fusiona campos: quita las claves borradas fuera
            registro.editar(eid, {"campos": cambios["campos"]}, False)
    if not (x["campos"] or {}).get("remoto") and x["mid"] is None and x["origen"] != "manual":
        registro.editar(eid, {"campos": {"remoto": ev.get("autor") or "otro equipo"}}, False)  # Pendientes lo lista aunque su documento no esté aquí
    tt.update({k: t for k in nuevos})
    s["ultimo"][eid] = _plano(registro.uno(eid))
    return 1


def _importar(c, s, raiz):
    yo, n = instancia(), 0
    for f in sorted((raiz / "eventos").glob("*.jsonl")):
        if f.stem == yo:
            continue
        pos = s["leido"].get(f.name, 0)
        try:
            with open(f, "rb") as fh:
                fh.seek(pos)
                datos = fh.read()
        except OSError:
            continue
        fin = datos.rfind(b"\n") + 1  # una línea a medio sincronizar se lee la próxima vez
        for ln in datos[:fin].splitlines():
            try:
                ev = json.loads(ln)
            except ValueError:
                continue
            if isinstance(ev, dict) and ev.get("id"):
                try:
                    n += _aplicar(c, s, ev)
                except (ValueError, KeyError) as ex:
                    log.warning("compartir: evento no aplicado (%s): %s", ex, ln[:200])
        s["leido"][f.name] = pos + fin
    return n


# ---------- API de módulo ----------
def sincronizar(c):
    with LOCK:
        s = estado(c)
        if not s:
            raise KeyError("Este proyecto no se comparte")
        raiz = Path(s["ruta"])
        if not raiz.is_dir():
            s["error"] = "No se encuentra la carpeta compartida (¿OneDrive está sincronizando?)"
            _guardar(c, s)
            raise FileNotFoundError(s["error"])
        try:
            env = _exportar(c, s, raiz)
            rec = _importar(c, s, raiz)
            s.update(error="", ultima=time.time(), enviados=env, recibidos=rec)
        except OSError as ex:
            s["error"] = str(ex)
            raise
        finally:
            _guardar(c, s)
        return {"enviados": env, "recibidos": rec}


def compartir(c, ruta, transcripciones=False):
    raiz = Path(ruta)
    if not raiz.is_dir():
        raise ValueError("Elige una carpeta que exista (la de OneDrive o SharePoint sincronizada)")
    s = estado(c) or {"ultimo": {}, "t": {}, "leido": {}, "alias": {}, "docs": {}}
    s.update(ruta=str(raiz), transcripciones=bool(transcripciones))
    _guardar(c, s)
    return sincronizar(c)


def unirse(ruta):
    """Abre un proyecto compartido por otro: crea la carpeta local con su nombre, tipo, datos y glosario, y trae sus eventos."""
    raiz = Path(ruta)
    try:
        pj = json.loads((raiz / "proyecto.json").read_text(encoding="utf-8"))
        c = str(pj["nombre"]).strip()[:120]
        assert pj.get("actas_proyecto") == 1 and c
    except (OSError, ValueError, KeyError, AssertionError, TypeError):
        raise ValueError("Esa carpeta no tiene un proyecto compartido de Actas (falta proyecto.json)")
    if c not in A._carpetas():
        A.carpeta({"nuevo": c})
    carpetas.guardar_datos(c, pj.get("tipo") or None, pj.get("datos") or [])
    if pj.get("glosario") and not registro.expediente(c).get("glosario"):
        carpetas.editar(c, lambda e: e.update(glosario=pj["glosario"]))
    return {"c": c, **compartir(c, ruta, False)}


def dejar(c):
    _fich(c).unlink(missing_ok=True)


def compartidos():
    out = []
    for f in _dir().glob("*.json") if _dir().is_dir() else []:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    return out


def _bucle():
    while True:
        time.sleep(CADA)
        for c in [c for c in A._carpetas() if estado(c)]:
            try:
                sincronizar(c)
            except Exception as ex:  # noqa: BLE001 - el bucle no se cae; el error queda en el estado del proyecto
                log.warning("compartir: %s: %s", c, ex)


# ---------- rutas ----------
def _vista(c):
    s = estado(c)
    return (
        {"compartido": False}
        if not s
        else {
            "compartido": True,
            "ruta": s["ruta"],
            "transcripciones": s.get("transcripciones", False),
            "ultima": s.get("ultima"),
            "error": s.get("error", ""),
            "miembros": sorted({f.stem for f in (Path(s["ruta"]) / "eventos").glob("*.jsonl")} - {instancia()}) if Path(s["ruta"]).is_dir() else [],
        }
    )


@router.get("/api/compartir")
def api_estado(c: str):
    return _vista(A._c({"c": c}))


@router.post("/api/compartir")
def api_compartir(d: dict):
    c = A._c(d)
    try:
        if d.get("dejar"):
            dejar(c)
        elif d.get("ruta"):
            compartir(c, d["ruta"], d.get("transcripciones", False))
        elif "transcripciones" in d and estado(c):
            s = estado(c)
            s["transcripciones"] = bool(d["transcripciones"])
            _guardar(c, s)
        else:
            sincronizar(c)
    except (ValueError, KeyError, FileNotFoundError) as ex:
        raise HTTPException(400, str(ex))
    return _vista(c)


@router.post("/api/compartir/unirse")
def api_unirse(d: dict):
    try:
        return unirse(d.get("ruta") or "")
    except ValueError as ex:
        raise HTTPException(400, str(ex))


def montar(modulo_app, app, bucle=True):
    global A
    A = modulo_app
    for r in router.routes:
        app.add_api_route(r.path, r.endpoint, methods=list(r.methods))
    if bucle:
        threading.Thread(target=_bucle, daemon=True, name="compartir").start()
