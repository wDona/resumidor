"""Proyecto compartido por una carpeta sincronizada (OneDrive o SharePoint; docs/plan-equipos.md, A2). Sin servidor.

En la carpeta compartida:
  proyecto.json             nombre, tipo, datos, glosario y enlaces del proyecto
  eventos/<instalación>.jsonl  cambios del registro, uno por línea; cada instalación solo escribe en el suyo (OneDrive no ve conflictos)
  actas/*.md                los documentos de quien los procesó
  transcripciones/*.md      solo si el proyecto lo permite (por defecto no)
Nunca se comparte registro.db (SQLite en carpetas sincronizadas se corrompe) ni los vídeos.

Sincronizar = exportar lo que cambió aquí desde la última vez (diferencia con lo último conocido, campo a campo) y luego leer las líneas
nuevas de los demás. Conflictos: por campo, gana el cambio más reciente (t), y queda en el historial con su autor.
Estado local en work/compartir/<proyecto>.json. app.py llama a montar().

Con un servidor de equipo (docs/servidor.md) es lo mismo por HTTP: el escritorio guarda la carpeta en un espejo local (work/espejos/) y en
cada sincronización sube sus líneas nuevas y baja las de los demás (/api/servidor/sync); las reuniones viajan como zip ligero del acta
(sin vídeo; la transcripción solo si el proyecto lo permite) y el servidor las importa con el mismo validador que «Importar acta»."""

import hashlib
import io
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

import carpetas
import exportar
import pipeline as P
import registro
import servidor

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
    registro.sincronizar(c, carpetas.docs(A._ms(c)))  # los ítems de actas aún no abiertas en Pendientes también viajan
    for x in registro.listar(c):
        cur, prev = _plano(x), s["ultimo"].get(x["id"], {})
        cambios = {k: v for k, v in cur.items() if prev.get(k) != v}
        cambios.update({k: None for k in prev if k not in cur})  # clave de campos quitada
        if not cambios:
            continue
        t = x["modificado"] or ahora
        if servidor.ACTIVO:  # en el servidor sincroniza quien llama, pero el cambio lo hizo otro usuario de la web
            h = registro.historial(x["id"])
            autor = (h[-1].get("autor") if h else None) or quien
        else:
            autor = quien
        lineas.append({"t": t, "inst": yo, "autor": autor, "id": x["id"], "tipo": x["tipo"], "cambios": cambios})
        s["ultimo"][x["id"]] = cur
        s["t"].setdefault(x["id"], {}).update({k: t for k in cambios})
    if lineas:
        (raiz / "eventos").mkdir(parents=True, exist_ok=True)
        with open(raiz / "eventos" / f"{yo}.jsonl", "a", encoding="utf-8", newline="\n") as f:
            f.writelines(json.dumps(e, ensure_ascii=False) + "\n" for e in lineas)
    e = registro.expediente(c)
    pj = {
        "actas_proyecto": 1,
        "nombre": c,
        "tipo": e.get("tipo") or "",
        "datos": e.get("datos") or [],
        "glosario": e.get("glosario") or [],
        "enlaces": e.get("enlaces") or [],
    }
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
    if c not in A.get_carpetas():
        A.carpeta({"nuevo": c})
    carpetas.guardar_datos(c, pj.get("tipo") or None, pj.get("datos") or [])
    if pj.get("glosario") and not registro.expediente(c).get("glosario"):
        carpetas.editar(c, lambda e: e.update(glosario=pj["glosario"]))
    if pj.get("enlaces") and not registro.expediente(c).get("enlaces"):
        guardar_enlaces(c, pj["enlaces"])
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
        for c in [c for c in A.get_carpetas() if estado(c)]:
            try:
                ahora(c)
            except Exception as ex:  # noqa: BLE001 - el bucle no se cae; el error queda en el estado del proyecto
                log.warning("compartir: %s: %s", c, ex)


# ---------- servidor de equipo: cliente (escritorio) ----------
FICH_EV = re.compile(r"[0-9a-f]{12}\.jsonl")
MAX = 8 << 20  # bytes de eventos por petición (lo que falte va en la siguiente)
SERV_KR = "actas-servidor"
ENVIO = threading.Lock()  # un envío al servidor a la vez


def conexion():
    """(url, token) del servidor de equipo configurado en Ajustes; ("", "") si no hay."""
    url = str((A._ajustes() or {}).get("servidor_url") or "").rstrip("/")
    try:
        import keyring

        tok = keyring.get_password(SERV_KR, "token") or ""
    except Exception:  # noqa: BLE001 - sin llavero no hay token
        tok = ""
    return url, tok


def _http(url, ruta, tok, cuerpo, tipo="application/json", timeout=120):
    datos = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo).encode()
    req = urllib.request.Request(url + ruta, datos, {"Authorization": "Bearer " + tok, "Content-Type": tipo, "User-Agent": "actas"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as ex:
        try:
            det = json.loads(ex.read()).get("detail")
        except ValueError:
            det = ""
        raise ValueError(f"El servidor respondió {ex.code}: {det or ex.reason}") from None
    except (urllib.error.URLError, OSError) as ex:
        raise ValueError(f"No se puede conectar con el servidor: {getattr(ex, 'reason', ex)}") from None


def probar_conexion(url, tok):
    url = url.strip().rstrip("/")
    if not url.startswith(("https://", "http://")):
        raise ValueError("La dirección empieza por https://")
    req = urllib.request.Request(url + "/api/yo", headers={"Authorization": "Bearer " + tok.strip(), "User-Agent": "actas"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as ex:
        raise ValueError("Token no válido" if ex.code == 401 else f"El servidor respondió {ex.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as ex:
        raise ValueError(f"No se puede conectar con {url}: {getattr(ex, 'reason', ex)}") from None


def _zip_reunion(mid, ver, trans):
    """Zip ligero del acta (lo que acepta «Importar acta»: index.html, acta.json, img/…, transcript.json), o None si no hay acta."""
    out = P.WORK / mid / ver
    fs = [(f, f.relative_to(out).as_posix()) for f in out.rglob("*") if f.is_file()] if out.is_dir() else []
    fs = [(f, a) for f, a in fs if A.ZIP_OK.fullmatch(a) and not a.startswith(("video.", "transcript"))]
    if not {"index.html", "acta.json"} <= {a for _, a in fs}:
        return None
    if trans and len(ver.split("_")) > 2:
        fs += [(t, "transcript.json") for t in (P.WORK / mid).glob(f"transcript_{ver.split('_')[2]}.json")][:1]
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for f, a in fs:
            z.write(f, a)
    return b.getvalue()


def _firma(mid, ver, trans):
    out = P.WORK / mid / ver
    st = sorted((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in out.rglob("*") if f.is_file()) if out.is_dir() else []
    return hashlib.sha1(json.dumps([st, bool(trans)]).encode()).hexdigest()[:16]


def enviar_servidor(c, transcripciones=None):
    """Envía el proyecto al servidor de equipo y trae lo que otros cambiaron allí. La primera vez lo da de alta (en el servidor y aquí)."""
    url, tok = conexion()
    if not (url and tok):
        raise ValueError("Configura el servidor de equipo en Ajustes (dirección y token)")
    with ENVIO:  # no LOCK: la red puede tardar minutos y el bucle y las demás carpetas siguen
        s = estado(c)
        if s and not s.get("servidor"):
            raise ValueError("Este proyecto se comparte por una carpeta: deja de compartirlo antes de enviarlo al servidor")
        if not s:
            raiz = P.WORK / "espejos" / hashlib.sha1(c.encode()).hexdigest()[:16]
            (raiz / "eventos").mkdir(parents=True, exist_ok=True)
            s = {"ultimo": {}, "t": {}, "leido": {}, "alias": {}, "docs": {}, "ruta": str(raiz), "transcripciones": False, "subido": 0, "reuniones": {}}
        s["servidor"] = url
        if transcripciones is not None:
            s["transcripciones"] = bool(transcripciones)
        _guardar(c, s)
        sincronizar(c)  # lo de aquí, al espejo
        s, yo = estado(c), instancia()
        raiz = Path(s["ruta"])
        mio = raiz / "eventos" / f"{yo}.jsonl"
        b = mio.read_bytes()[s.get("subido", 0) :][:MAX] if mio.exists() else b""
        b = b[: b.rfind(b"\n") + 1]
        tam = {g.name: g.stat().st_size for g in (raiz / "eventos").glob("*.jsonl") if g.stem != yo}
        try:
            pj = json.loads((raiz / "proyecto.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pj = {}
        r = _http(url, "/api/servidor/sync", tok, {"c": c, "inst": yo, "mio": {"desde": s.get("subido", 0), "datos": b.decode()}, "proyecto": pj, "tam": tam})
        s["subido"] = min(int(r.get("mio") or 0), mio.stat().st_size if mio.exists() else 0)  # si el servidor tiene menos (se perdió), se reenvía
        for n, o in (r.get("otros") or {}).items():
            f = raiz / "eventos" / n
            if FICH_EV.fullmatch(n) and isinstance(o, dict) and int(o.get("desde", -1)) == (f.stat().st_size if f.exists() else 0):
                with open(f, "ab") as fh:
                    fh.write(str(o.get("datos") or "").encode())
        _guardar(c, s)
        res = sincronizar(c)  # lo traído, al registro
        s = estado(c)
        env, omit = 0, 0
        for d in carpetas.docs(A._ms(c)):
            k = f"{d['mid']}/{d['ver']}"
            if A.anon_defecto(d["mid"]):
                omit += 1  # lo anonimizado no sale como acta completa
                continue
            fi = _firma(d["mid"], d["ver"], s["transcripciones"])
            if s["reuniones"].get(k) == fi or not (z := _zip_reunion(d["mid"], d["ver"], s["transcripciones"])):
                continue
            q = urllib.parse.urlencode({"c": c, "clave": k})
            _http(url, "/api/servidor/reunion?" + q, tok, z, "application/zip", timeout=600)
            s["reuniones"][k] = fi
            env += 1
            _guardar(c, s)
        return {**res, "reuniones": env, "omitidas": omit}


def ahora(c):
    """Sincroniza ya: con el servidor de equipo o con la carpeta compartida, según cómo se comparta."""
    s = estado(c)
    return enviar_servidor(c) if s and s.get("servidor") else sincronizar(c)


# ---------- servidor de equipo: lo que recibe (solo en modo servidor) ----------
INST = re.compile(r"[0-9a-f]{12}")


def recibir(d):
    """{c, inst, mio: {desde, datos}, proyecto, tam: {fichero: bytes leídos}} -> {mio: bytes que tiene de esa instalación, otros: {fichero: {desde, datos}}}."""
    c, inst = str(d.get("c") or "").strip()[:120], str(d.get("inst") or "")
    if not c or not INST.fullmatch(inst):
        raise ValueError("Petición no válida")
    raiz = P.WORK / "servidor" / hashlib.sha1(c.encode()).hexdigest()[:16]
    with LOCK:
        if c not in A.get_carpetas():
            A.carpeta({"nuevo": c})
            pj = d.get("proyecto") if isinstance(d.get("proyecto"), dict) else {}
            carpetas.guardar_datos(c, pj.get("tipo") or None, pj.get("datos") or [])
            if pj.get("glosario"):
                carpetas.editar(c, lambda e: e.update(glosario=pj["glosario"]))
            if pj.get("enlaces"):
                guardar_enlaces(c, pj["enlaces"])
        if not estado(c):
            (raiz / "eventos").mkdir(parents=True, exist_ok=True)
            _guardar(c, {"ultimo": {}, "t": {}, "leido": {}, "alias": {}, "docs": {}, "ruta": str(raiz), "transcripciones": False})
        f = raiz / "eventos" / f"{inst}.jsonl"
        tam = f.stat().st_size if f.exists() else 0
        mio = d.get("mio") if isinstance(d.get("mio"), dict) else {}
        datos = str(mio.get("datos") or "").encode()
        if datos and int(mio.get("desde", -1)) == tam and datos.endswith(b"\n") and len(datos) <= MAX:
            with open(f, "ab") as fh:
                fh.write(datos)
            tam += len(datos)
        sincronizar(c)  # aplica lo recibido y exporta lo cambiado en la web
        otros, leidos = {}, d.get("tam") if isinstance(d.get("tam"), dict) else {}
        for g in sorted((raiz / "eventos").glob("*.jsonl")):
            if g.stem == inst:
                continue
            desde = max(0, int(leidos.get(g.name) or 0))
            with open(g, "rb") as fh:
                fh.seek(desde)
                b = fh.read(MAX)
            b = b[: b.rfind(b"\n") + 1]
            if b:
                otros[g.name] = {"desde": desde, "datos": b.decode()}
        return {"c": c, "mio": tam, "otros": otros}


def _solo_servidor():
    if not servidor.ACTIVO:
        raise HTTPException(404, "Solo en el servidor de equipo")


@router.post("/api/servidor/sync")
def api_srv_sync(d: dict):
    _solo_servidor()
    try:
        return recibir(d)
    except (ValueError, KeyError) as ex:
        raise HTTPException(400, str(ex))


@router.post("/api/servidor/reunion")
async def api_srv_reunion(request: Request, c: str, clave: str):
    """Zip ligero de un acta enviado por el escritorio; la misma clave (mid/versión de allí) sustituye a la anterior."""
    _solo_servidor()
    if not re.fullmatch(r"[\w-]{1,60}/[\w.-]{1,80}", clave):
        raise HTTPException(400, "Clave no válida")
    cuerpo = await request.body()
    if len(cuerpo) > 300 << 20:
        raise HTTPException(413, "Demasiado grande")
    tmp = P.WORK / "servidor" / "subidas" / (hashlib.sha1(clave.encode()).hexdigest()[:16] + ".zip")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(cuerpo)
    try:
        return await run_in_threadpool(A.importar, {"path": str(tmp), "c": c, "clave": clave})
    finally:
        tmp.unlink(missing_ok=True)


# ---------- servidor de equipo: rutas del escritorio ----------
@router.post("/api/servidor/conexion")
def api_conexion(d: dict):
    """{url, token}: prueba y guarda (la dirección en Ajustes, el token en el llavero). {quitar: true} lo olvida."""
    import keyring

    if d.get("quitar"):
        A.post_ajustes({"servidor_url": ""})
        try:
            keyring.delete_password(SERV_KR, "token")
        except Exception:  # noqa: BLE001 - ya no estaba
            pass
        return {"url": ""}
    tok = str(d.get("token") or "").strip() or conexion()[1]  # sin token nuevo: el guardado
    try:
        yo = probar_conexion(str(d.get("url") or ""), tok)
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    keyring.set_password(SERV_KR, "token", tok)
    A.post_ajustes({"servidor_url": str(d["url"])})
    return {"url": str(d["url"]).strip().rstrip("/"), "nombre": yo.get("nombre")}


@router.post("/api/servidor/enviar")
def api_enviar(d: dict):
    c = A._c(d)
    try:
        enviar_servidor(c, d.get("transcripciones"))
    except (ValueError, KeyError, FileNotFoundError) as ex:
        raise HTTPException(400, str(ex))
    return _vista(c)


# ---------- rutas ----------
def _vista(c):
    s = estado(c)
    return (
        {"compartido": False, "servidor_url": conexion()[0]}
        if not s
        else {
            "compartido": True,
            "ruta": s["ruta"],
            "servidor": s.get("servidor", ""),
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
            ahora(c)
    except (ValueError, KeyError, FileNotFoundError) as ex:
        raise HTTPException(400, str(ex))
    return _vista(c)


def guardar_enlaces(c, xs):
    """Enlaces puestos a mano en el proyecto (canal de Teams, Figma, wiki…): [{nombre, url}], solo http(s), como mucho 30."""
    ok = []
    for x in xs if isinstance(xs, list) else []:
        url = str(x.get("url") or "").strip()[:1000] if isinstance(x, dict) else ""
        if url.startswith(("https://", "http://")) and url not in [y["url"] for y in ok]:
            ok.append({"nombre": str(x.get("nombre") or "").strip()[:80] or urllib.parse.urlsplit(url).hostname or url, "url": url})
    carpetas.editar(c, lambda e: e.update(enlaces=ok[:30]))
    return ok[:30]


@router.post("/api/enlaces")
def api_enlaces_guardar(d: dict):
    """{c, enlaces: [{nombre, url}]}: sustituye los enlaces puestos a mano."""
    c = A._c(d)
    guardar_enlaces(c, d.get("enlaces"))
    return api_enlaces(c)


@router.get("/api/enlaces")
def api_enlaces(c: str):
    """Menú «Enlaces» del proyecto: dónde se comparte (servidor o carpeta) y los destinos con los que trabaja (destinos.enlaces)."""
    import destinos

    c = A._c({"c": c})
    s = None if servidor.ACTIVO else estado(c)  # en el servidor el proyecto ya está aquí (y su ruta interna no se enseña)
    out = [{**x, "tipo": "Enlace", "propio": True} for x in registro.expediente(c).get("enlaces") or []]
    if s and s.get("servidor"):
        out.append({"nombre": "Servidor de equipo", "tipo": "Actas", "url": f"{s['servidor']}/#/p/{urllib.parse.quote(c)}"})
    elif s:
        out.append({"nombre": "Carpeta compartida", "tipo": "OneDrive o SharePoint", "carpeta": True, "ruta": s["ruta"]})
    return out + destinos.enlaces(c)


@router.post("/api/compartir/abrir")
def api_abrir(d: dict):
    """Abre en el explorador la carpeta compartida del proyecto (solo esa: la ruta sale del estado, no del navegador)."""
    import os
    import subprocess
    import sys

    s = estado(A._c(d))
    if not s or s.get("servidor") or not Path(s["ruta"]).is_dir():
        raise HTTPException(404, "Este proyecto no se comparte en una carpeta")
    if sys.platform == "win32":
        os.startfile(s["ruta"])  # noqa: S606
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", s["ruta"]])
    return {}


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
