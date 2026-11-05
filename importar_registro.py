"""Importar de vuelta un .xlsx/.csv exportado (export_registro) a las vistas del registro, y meter documentos ya procesados en un proyecto.
Rutas: /api/reg/importar/previa, /api/reg/importar/aplicar, /api/doc/a-proyecto. Solo stdlib. app.py llama a montar(). Nunca borra entidades."""

import csv
import datetime as dt
import io
import os
import re
import shutil
import threading
import time
import unicodedata
import uuid
import zipfile
from email.parser import BytesParser
from email.policy import HTTP
from pathlib import Path
from xml.etree import ElementTree as ET

from fastapi import APIRouter, HTTPException, Request

import export_registro as ER
import registro

router = APIRouter()
A = None  # módulo app (montar): sus ayudantes _c, _tipo_carpeta, start, set_meta…
MAX_BYTES, MAX_FILAS, MAX_HOJA = 5_000_000, 5000, 60_000_000  # fichero subido, filas útiles, hoja descomprimida (anti zip-bomb)
TTL, MAX_TOK = 1800, 20
PREVIAS, _lk = {}, threading.Lock()
PRIO = ["Must", "Should", "Could", "Won't"]
TIPO_REQ = ["funcional", "no funcional", "restricción"]
CODIGO = {"codigo", "id", "cod", "ref", "referencia", "identificador"}
# vista -> [(cabecera exportada, destino, alias separados por coma)]; destino: columna de entidad o campos.<clave>
CAMPOS = {
    "requisitos": [
        ("Título", "titulo", "nombre,requisito"),
        ("Detalle", "detalle", "descripcion"),
        ("Tipo", "campos.tipo_req", ""),
        ("Prioridad", "prioridad", "moscow"),
        ("Estado", "estado", ""),
        ("Solicitante", "campos.solicitante", "peticionario"),
        ("Versión", "campos.version", ""),
    ],
    "historias": [
        ("Título", "titulo", "nombre"),
        ("Como", "campos.como", ""),
        ("Quiero", "campos.quiero", ""),
        ("Para", "campos.para", ""),
        ("Puntos", "campos.puntos", "estimacion"),
        ("Épica", "campos.epica", ""),
        ("Estado", "estado", ""),
    ],
    "interesados": [
        ("Nombre", "titulo", "titulo"),
        ("Rol", "campos.rol", ""),
        ("Organización", "campos.organizacion", "empresa"),
        ("Poder", "campos.poder", ""),
        ("Interés", "campos.interes", ""),
        ("Actitud", "campos.actitud", ""),
        ("Estrategia", "campos.estrategia", ""),
        ("Canal", "campos.canal", ""),
        ("Notas", "detalle", "detalle"),
    ],
    "decisiones": [
        ("Título", "titulo", "nombre"),
        ("Contexto", "detalle", "detalle"),
        ("Alternativas", "campos.alternativas", ""),
        ("Consecuencias", "campos.consecuencias", ""),
        ("Decisor", "campos.decisor", ""),
        ("Fecha", "campos.fecha", ""),
        ("Estado", "estado", ""),
    ],
}
IGNORADAS = {"criterios", "origen", "revision", "deriva de", "sustituye a", "sustituida por"}  # las escribe el sistema o no se editan en tabla


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"\s+", " ", s).strip(" :*")


def _mapa(vista):
    m = {}
    for cab, dest, alias in CAMPOS[vista]:
        for n in [cab, *filter(None, alias.split(","))]:
            m[norm(n)] = (cab, dest)
    return m


# ---------- lectura de ficheros ----------
def _texto(v):
    if isinstance(v, float):
        return str(int(v)) if v == int(v) else repr(v)
    return "" if v is None else str(v).replace("\r\n", "\n").replace("\r", "\n").strip()


def leer_csv(datos):
    try:
        t = datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        t = datos.decode("cp1252", "replace")
    l1 = t.split("\n", 1)[0]
    sep = ";" if l1.count(";") > l1.count(",") else ","
    return list(csv.reader(io.StringIO(t, newline=""), delimiter=sep))


def _col(r):
    n = 0
    for ch in re.match(r"[A-Z]+", r).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def leer_xlsx(datos, hoja=None):
    """-> filas [[str|float]] de la hoja de nombre `hoja` (o la primera). Números como float (fechas Excel = serie); texto: sharedStrings, inlineStr, str."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    q = lambda t: "{%s}%s" % (ns["m"], t)
    comp = lambda e: "".join(t.text or "" for t in e.iter(q("t")))
    try:
        z = zipfile.ZipFile(io.BytesIO(datos))
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        hs = [(s.get("name"), rels[s.get("{%s}id" % ns["r"])]) for s in ET.fromstring(z.read("xl/workbook.xml")).find("m:sheets", ns)]
        destino = next((t for n, t in hs if hoja and n == hoja), hs[0][1])
        ruta = "xl/" + destino.lstrip("/").removeprefix("xl/")
        ss = []
        if "xl/sharedStrings.xml" in z.namelist():
            if z.getinfo("xl/sharedStrings.xml").file_size > MAX_HOJA:
                raise HTTPException(413, "El fichero es demasiado grande")
            ss = [comp(si) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns)]
        if z.getinfo(ruta).file_size > MAX_HOJA:
            raise HTTPException(413, "La hoja es demasiado grande")
        filas = []
        for row in ET.fromstring(z.read(ruta)).iter(q("row")):
            f = []
            for c in row.findall("m:c", ns):
                i = _col(c.get("r") or "A1")
                f += [""] * (i - len(f))
                t, v = c.get("t"), c.find("m:v", ns)
                if t == "inlineStr":
                    x = comp(c.find("m:is", ns))
                elif v is None or v.text is None:
                    x = ""
                elif t == "s":
                    x = ss[int(v.text)]
                elif t in ("str", "e"):
                    x = v.text
                elif t == "b":
                    x = "VERDADERO" if v.text == "1" else "FALSO"
                else:
                    x = float(v.text)
                f.append(x)
            filas.append(f)
            if len(filas) > MAX_FILAS * 2:
                raise HTTPException(413, f"Demasiadas filas (máximo {MAX_FILAS})")
        return filas
    except HTTPException:
        raise
    except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError, IndexError, AttributeError, TypeError):
        raise HTTPException(400, "No se pudo leer el .xlsx (¿es una hoja exportada por la app?)")


# ---------- validación de celdas ----------
def _fecha(v):
    if isinstance(v, float):  # serie de Excel (días desde 1899-12-30)
        if not 1 <= v < 2958466:
            raise ValueError("Fecha no válida")
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(v))).isoformat()
    s = _texto(v)
    if not s:
        return s
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return dt.date.fromisoformat(s).isoformat()
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", s)
    if not m:
        raise ValueError(f"Fecha no válida: {s} (usa AAAA-MM-DD)")
    return dt.date(int(m[3]), int(m[2]), int(m[1])).isoformat()


def _enum(s, ops, que):
    if s == "":
        return s
    r = next((o for o in ops if o.casefold() == s.casefold()), None)
    if r is None:
        raise ValueError(f"{que} no válido: «{s}»")
    return r


def validar(tipo, dest, v, c, antes):
    """Valor de la celda -> valor listo para guardar (ValueError con el motivo si no vale). `antes`: lo que hay ahora (listas)."""
    if dest == "campos.fecha":
        return _fecha(v)
    s = _texto(v)
    if dest == "estado":
        return _enum(s, A.ESTADOS_TIPO.get(tipo, A._EST_GEN), "Estado")
    if dest == "prioridad":
        return _enum(s, PRIO if tipo == "requisito" else ["alta", "media", "baja", *PRIO], "Prioridad")
    if dest == "campos.tipo_req":
        return _enum(s, TIPO_REQ, "Tipo")
    if dest in ("campos.poder", "campos.interes"):
        if s == "":
            return ""
        n = registro.niveles_ejes(c)[dest.endswith("interes")]
        x = registro.num_medio(s.replace(",", "."))
        if x is None or not 1 <= x <= n:
            raise ValueError(f"{dest[7:].capitalize()} debe ser de 1 a {n} (pasos de 0,5)")
        return x
    if dest == "campos.puntos":
        try:
            f = float(s.replace(",", ".")) if s else None
            f is not None and int(f)  # «inf»/«nan»: no son puntos
        except (ValueError, OverflowError):
            raise ValueError(f"Puntos no numérico: «{s}»")
        return "" if f is None else int(f) if f == int(f) else f
    if len(s) > 20000:
        raise ValueError("Texto demasiado largo")
    return [x for x in s.split("\n") if x.strip()] if isinstance(antes, list) else s


def _actual(x, dest):
    if dest.startswith("campos."):
        v = x["campos"].get(dest[7:])
        return x["fecha_alta"] if dest == "campos.fecha" and v is None else v
    return x[dest]


def _igual(a, b):
    if isinstance(b, (int, float)) and not isinstance(b, bool) and a not in (None, ""):
        try:
            return float(str(a).replace(",", ".")) == b
        except ValueError:
            return False
    return ER._s(a) == ER._s(b)


# ---------- previa ----------
def _multipart(ct, cuerpo):
    msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + ct.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + cuerpo)
    if not msg.is_multipart():
        raise HTTPException(400, "Se esperaba multipart/form-data")
    out = {}
    for p in msg.iter_parts():
        n = p.get_param("name", header="content-disposition")
        if n:
            out[n] = (p.get_filename(), p.get_payload(decode=True) or b"")
    return out


def analizar(c, vista, nombre, datos):
    """-> (previa sin token, operaciones, vista). Puro: no toca el registro."""
    ext = Path(nombre or "").suffix.lower()
    if ext == ".xlsx":
        filas = leer_xlsx(datos, ER.TITULO.get(vista or ""))
    elif ext in (".csv", ".txt"):
        filas = leer_csv(datos)
    else:
        raise HTTPException(400, "Solo .xlsx o .csv")
    filas = [f for f in filas if any(_texto(x) for x in f)]
    if not filas:
        raise HTTPException(400, "El fichero está vacío")
    if len(filas) > MAX_FILAS + 1:
        raise HTTPException(413, f"Demasiadas filas (máximo {MAX_FILAS})")
    cab = [norm(x) for x in filas[0]]
    if not vista:
        pts = {v: sum(h in _mapa(v) for h in cab) for v in ER.TIPO}
        vista = max(pts, key=pts.get)
        if pts[vista] < 2 or list(pts.values()).count(pts[vista]) > 1:
            raise HTTPException(400, "No se reconoce la vista por las columnas; indícala (vista=requisitos|historias|interesados|decisiones)")
    elif vista not in ER.TIPO:
        raise HTTPException(400, f"Vista desconocida: {vista}")
    tipo, mapa = ER.TIPO[vista], _mapa(vista)
    icod = next((i for i, h in enumerate(cab) if h in CODIGO), None)
    cols = {i: mapa[h] for i, h in enumerate(cab) if h in mapa and i != icod}
    if not cols:
        raise HTTPException(400, "No hay ninguna columna reconocida")
    res = {
        "vista": vista,
        "columnas_reconocidas": ([str(filas[0][icod])] if icod is not None else []) + [str(filas[0][i]) for i in cols],
        "columnas_ignoradas": [str(filas[0][i]) for i, h in enumerate(cab) if i != icod and i not in cols and h and h not in IGNORADAS],
        "nuevos": [],
        "modificados": [],
        "iguales": 0,
        "desconocidas": [],
    }
    todas = {x["codigo"].casefold(): x for x in registro.listar(c, tipo)}
    ops, vistos = [], set()
    for n, f in enumerate(filas[1:], 2):  # n = nº de fila (de las no vacías)
        cel = lambda i: f[i] if i < len(f) else ""
        cod = _texto(cel(icod)) if icod is not None else ""
        x = todas.get(cod.casefold()) if cod else None
        if cod and (not x or x["revision"] in registro.OCULTA):
            res["desconocidas"].append(
                {"fila": n, "motivo": f"El código {cod} no existe en esta vista del proyecto" if not x else f"{cod} está {x['revision']}: no se importa"}
            )
            continue
        if x and x["id"] in vistos:
            res["desconocidas"].append({"fila": n, "motivo": f"Código repetido: {cod}"})
            continue
        try:
            vals = {dest: (cb, validar(tipo, dest, cel(i), c, _actual(x, dest) if x else None)) for i, (cb, dest) in cols.items()}
            if x:
                vistos.add(x["id"])
                cam = {d: (cb, v, _actual(x, d)) for d, (cb, v) in vals.items() if not _igual(_actual(x, d), v)}
                if "titulo" in cam and not cam["titulo"][1]:
                    raise ValueError("El título no puede quedar vacío")
                if not cam:
                    res["iguales"] += 1
                    continue
                ops.append({"k": "mod", "id": x["id"], "fila": n, "d": {d: v for d, (_, v, _) in cam.items()}})
                res["modificados"].append({"id": x["id"], "codigo": x["codigo"], "fila": n, "cambios": {cb: [ER._s(a), ER._s(v)] for cb, v, a in cam.values()}})
            else:
                if not vals.get("titulo", ("", ""))[1]:
                    raise ValueError("Falta el título")
                vals = {d: (cb, v) for d, (cb, v) in vals.items() if v != ""}
                ops.append({"k": "nuevo", "fila": n, "d": {d: v for d, (_, v) in vals.items()}})
                res["nuevos"].append({"fila": n, "titulo": vals["titulo"][1], "valores": {cb: ER._s(v) for cb, v in vals.values()}})
        except ValueError as ex:
            res["desconocidas"].append({"fila": n, "motivo": str(ex)})
    return res, ops, vista


def _guardar(c, vista, ops):
    with _lk:
        for k in [k for k, v in PREVIAS.items() if time.time() - v["t"] > TTL]:
            del PREVIAS[k]
        while len(PREVIAS) >= MAX_TOK:
            del PREVIAS[min(PREVIAS, key=lambda k: PREVIAS[k]["t"])]
        tok = uuid.uuid4().hex
        PREVIAS[tok] = {"c": c, "vista": vista, "ops": ops, "t": time.time()}
        return tok


@router.post("/api/reg/importar/previa")
async def previa(request: Request):
    """multipart: file (.xlsx/.csv), c, vista? -> {token, vista, columnas_reconocidas, nuevos, modificados, iguales, desconocidas}. No cambia nada."""
    cuerpo = await request.body()
    if len(cuerpo) > MAX_BYTES + 10_000:
        raise HTTPException(413, "Fichero demasiado grande (máx. 5 MB)")
    p = _multipart(request.headers.get("content-type", ""), cuerpo)
    if "file" not in p or not p["file"][1]:
        raise HTTPException(400, "Falta el fichero (campo file)")
    c = A._c({"c": p["c"][1].decode()} if "c" in p else dict(request.query_params))
    vista = (p["vista"][1].decode().strip() if "vista" in p else request.query_params.get("vista", "")) or None
    res, ops, vista = analizar(c, vista, p["file"][0], p["file"][1])
    return {"token": _guardar(c, vista, ops), **res}


@router.post("/api/reg/importar/aplicar")
def aplicar(d: dict):
    """{token, seleccion?: [id (modificados) | fila (nuevos)]} -> un solo lote (el «deshacer» del registro lo revierte entero). Sin seleccion: todo."""
    with _lk:
        pv = PREVIAS.pop(str(d.get("token") or ""), None)
    if not pv or time.time() - pv["t"] > TTL:
        raise HTTPException(404, "La previa caducó: vuelve a subir el fichero")
    c, sel = pv["c"], d.get("seleccion")
    if sel is not None and not isinstance(sel, list):
        raise HTTPException(400, "seleccion debe ser una lista")
    sel = None if sel is None else {str(s) for s in sel}
    tipo, lote, ids, cr, mo = ER.TIPO[pv["vista"]], uuid.uuid4().hex[:10], [], 0, 0
    with registro.LOCK:
        for o in pv["ops"]:
            if sel is not None and str(o["id"] if o["k"] == "mod" else o["fila"]) not in sel:
                continue
            cam = {}
            for dest, v in o["d"].items():
                if dest.startswith("campos."):
                    cam.setdefault("campos", {})[dest[7:]] = v
                else:
                    cam[dest] = v
            if o["k"] == "mod":
                try:
                    registro.editar(o["id"], cam, lote)
                except KeyError:
                    continue
                mo += 1
                ids.append(o["id"])
            else:
                cam.setdefault("campos", {})["importado"] = True  # el CHECK de origen no admite «importado»: manual + marca
                ids.append(registro.crear(c, tipo, lote, origen="manual", revision="aprobado", **cam)["id"])
                cr += 1
        vivas = [registro.de(c, i) for i in ids]
    return {"ok": True, "lote": lote, "creadas": cr, "modificadas": mo, "items": registro.completas(vivas)}


# ---------- documentos ya procesados -> proyecto ----------
LIGABLES = (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".mp3", ".m4a", ".wav", ".ogg", ".opus", ".flac", ".aac", ".pdf", ".png", ".jpg", ".jpeg", ".webp")


def _copia(src, dst):
    try:
        if Path(src).suffix.lower() not in LIGABLES:  # un enlace duro comparte el contenido: meta.json, actas, transcripciones se reescriben en sitio
            raise OSError
        os.link(src, dst)  # los medios pesados no se duplican
    except OSError:
        shutil.copy2(src, dst)


@router.post("/api/doc/a-proyecto")
def a_proyecto(d: dict):
    """{mids, c, modo: mover|copiar, enviar?} -> mueve (o copia sin reprocesar) los documentos a la carpeta c y encola poblar de cada uno: {ok, mids, poblando}."""
    c = A._c(d)
    mids, modo = d.get("mids"), d.get("modo") or "mover"
    if not c or not isinstance(mids, list) or not mids or modo not in ("mover", "copiar"):
        raise HTTPException(400, "Hacen falta c, mids y modo (mover|copiar)")
    W = A.pipeline.WORK
    wds = []
    for m in dict.fromkeys(map(str, mids)):
        wd = W / Path(m).name
        if not wd.is_dir():
            raise HTTPException(404, f"Reunión no encontrada: {m}")
        wds.append(wd)
    nuevos = []
    for wd in wds:
        if modo == "mover":
            A.set_meta({"id": wd.name, "carpeta": c})
            nuevos.append(wd.name)
        else:
            nid = uuid.uuid4().hex[:16]
            shutil.copytree(wd, W / nid, copy_function=_copia)
            base, usados = A.meta(W / nid).get("nombre") or wd.name, {e["label"].casefold() for e in A.meetings()}
            nom = next(
                n for n in (f"{base[:100]} (copia{'' if k == 1 else f' {k}'})" for k in range(1, 1000)) if n.casefold() not in usados
            )  # set_meta rechaza nombres repetidos
            A.set_meta({"id": nid, "carpeta": c, "nombre": nom})
            nuevos.append(nid)
    pob, enviar = [], bool(d.get("enviar"))  # «enviar también»: las recetas «al terminar» de la carpeta (tras poblar si lo hay)
    if (A._ajustes() or A.AJ_DEF).get("poblar_auto", True) and A._tipo_carpeta(
        c
    ).casefold() == "proyecto":  # misma regla que tras generar un acta; las sensibles nunca
        pob = [A.start("poblar", {"c": c, "mid": m, "auto": True, **({} if enviar else {"sin_recetas": True})}, c, m)["id"] for m in nuevos]
    elif enviar:
        for m in nuevos:
            try:
                A.destinos.tras_documento(m, A.destinos._ult(m))
            except ValueError:  # sin acta («solo buscable»): nada que enviar
                pass
    return {"ok": True, "mids": nuevos, "poblando": pob}


def montar(modulo_app, app):
    global A
    A = modulo_app
    for r in router.routes:  # add_api_route y no include_router: las pruebas de rutas de app.app.routes esperan rutas planas
        app.add_api_route(r.path, r.endpoint, methods=list(r.methods))
