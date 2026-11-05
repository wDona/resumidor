"""B2: envío a plataformas, descargas multi-selección, planes/recetas (al terminar y programadas) e historial. Los tipos de destino viven en destinos_tipos.py (tabla).
Config sin secretos en work/destinos.json (destinos, presets, recetas); secretos en el llavero del sistema; historial work/envios.jsonl; idempotencia work/envios_mapa.json.
Nunca se envía vídeo ni audio. Con anonimización activa (ajuste/carpeta/preset/petición) solo sale la copia anonimizada; si falta, error (nunca en claro).
Plan = {carpeta, nombre, plantilla?, solo_buscable?, salidas:[{que, como: destino|documento, preset?|destino?, nombre?}]}."""

import csv
import datetime as dt
import hashlib
import io
import json
import os
import threading
import time
import urllib.parse
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

import carpetas
import export_registro
import exportar
import informe
import pipeline as P
import privacidad
import registro
import destinos_tipos as T

router = APIRouter()
LOCK = threading.RLock()
SERV = "actas-destinos"
QUE = ("documento", "resumen", "tareas", "decisiones", "requisitos", "historias", "riesgos", "interesados", "informe")
REG = {"tareas": "tarea", "decisiones": "decision", "requisitos": "requisito", "historias": "historia", "riesgos": "riesgo", "interesados": "interesado"}
TIT = {
    "tareas": "Tareas",
    "decisiones": "Decisiones",
    "requisitos": "Requisitos",
    "historias": "Historias de usuario",
    "riesgos": "Riesgos",
    "interesados": "Interesados",
}
INTERNO = "@proyecto"
DOCQ = ("documento", "resumen", "transcripcion")
OWN = ("md", "json", "csv")
AUDIO = (".mp3", ".m4a", ".wav", ".ogg", ".opus", ".flac", ".aac")
CFG = lambda: P.WORK / "destinos.json"
LOG = lambda: P.WORK / "envios.jsonl"
MAPA = lambda: P.WORK / "envios_mapa.json"


class NadaNuevo(Exception):
    pass


# ---------- almacén y secretos ----------
def _leer(f, defecto):
    try:
        return json.loads(Path(f).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def _escribir(f, d):
    P.WORK.mkdir(exist_ok=True)
    f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def cfg():
    return {"destinos": {}, "presets": {}, "recetas": {}, "objetivos": {}, "url_base": "", **_leer(CFG(), {})}


def _kr():
    import keyring

    return keyring


def _sec_get(did, campo):
    try:
        return _kr().get_password(SERV, f"{did}:{campo}") or ""
    except Exception:
        return ""


def _sec_set(did, campo, v):
    kr = _kr()
    try:
        kr.set_password(SERV, f"{did}:{campo}", v) if v else kr.delete_password(SERV, f"{did}:{campo}")
    except kr.errors.PasswordDeleteError:
        pass
    except kr.errors.KeyringError:
        raise RuntimeError("Este equipo no tiene un llavero del sistema donde guardar el secreto de forma segura") from None


def _log(e):
    with LOCK:
        P.WORK.mkdir(exist_ok=True)
        with LOG().open("a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _log_error(s, ex, meta=None):
    e = {
        "id": uuid.uuid4().hex[:10],
        "t": time.time(),
        "preset": s.get("preset"),
        "destino": s.get("destino") or "",
        "que": [s["que"]] if s.get("que") else [],
        "req": None,
        "items": [],
        "enlaces": [],
        "estado": "error",
        "error": str(ex) or type(ex).__name__,
        "meta": meta or {},
    }
    _log(e)
    return e


# ---------- documentos y selección ----------
def _meta(mid):
    return _leer(P.WORK / Path(mid).name / "meta.json", {})


def _ult(mid):
    vs = list((P.WORK / Path(mid).name).glob("acta_*/acta.json"))
    if not vs:
        raise ValueError("Documento sin acta")
    return max(vs, key=lambda f: f.stat().st_mtime).parent.name


def _docs_de(c):
    """[(mid, ver)] de los documentos con acta de la carpeta c, el más reciente primero."""
    xs = [
        (m.parent, max(m.parent.glob("acta_*/acta.json"), key=lambda f: f.stat().st_mtime))
        for m in P.WORK.glob("*/meta.json")
        if _meta(m.parent.name).get("carpeta", "") == c and any(m.parent.glob("acta_*/acta.json"))
    ]
    return [(d.name, f.parent.name) for d, f in sorted(xs, key=lambda x: -x[1].stat().st_mtime)]


def _ambito(d):
    """{doc:"mid/ver"|{mid,ver}|"mid", c, ids} -> {mid, ver (documento explícito), c, ids, dm, dv (documento para documento/resumen: el explícito o el último de la carpeta)}."""
    doc = d.get("doc")
    mid, ver = (doc.split("/", 1) + [""])[:2] if isinstance(doc, str) else ((doc or {}).get("mid", ""), (doc or {}).get("ver", ""))
    if mid and not ver:
        ver = _ult(mid)
    c = d["c"] if d.get("c") is not None else (_meta(mid).get("carpeta", "") if mid else None)
    dm, dv = (mid, ver) if mid else (_docs_de(c)[:1] or [("", "")])[0] if c is not None else ("", "")
    return {"mid": mid, "ver": ver, "c": c, "ids": list(d.get("ids") or []), "dm": dm, "dv": dv}


def anon_activa(a, forzar=None):
    """Mismo criterio que app.anon_defecto: la carpeta manda sobre el ajuste general; `forzar` explícito (petición/preset) manda sobre ambos."""
    if forzar is not None:
        return bool(forzar)
    o = carpetas.leer(a["c"])["ajustes"]["anon"] if a.get("c") else None
    return bool(o) if o is not None else bool(_leer(P.WORK / "ajustes.json", {}).get("anonimizar_defecto"))


def _anonf(mids):
    """Texto -> sin datos personales: lo marcado en las copias anonimizadas de esos documentos + patrones (DNI, correo, IBAN…)."""
    its = []
    for m in mids:
        for f in (P.WORK / Path(m).name).glob(f"acta_*/{privacidad.ANON_META}"):
            its += _leer(f, {}).get("items", [])
    sus = privacidad.Sustituidor(its)

    def f(t):
        t = sus(str(t or ""))
        for tipo, _, _, a, b in reversed(privacidad.detectar_texto(t)):
            t = t[:a] + privacidad.ETIQUETA[tipo] + t[b:]
        return t

    return f


def _s(v):
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def _de_ent(x, q, an, f, base):
    nom = lambda m: privacidad.NEUTRO if an else (_meta(m).get("nombre") or m)
    org = "; ".join(
        nom(ci["mid"]) + (f" [{P.fmt(ci['t'])}]" if ci.get("t") is not None else "") + (f" «{f(ci['texto'])}»" if ci.get("texto") else "")
        for ci in x["citas"][:3]
    )
    k = [f"{a}: {_s(b)}" for a, b in (x.get("campos") or {}).items() if b not in ("", None, [], {})]
    return {
        "k": "e:" + x["id"],
        "tipo": q,
        "codigo": x["codigo"],
        "titulo": f(x["titulo"]),
        "cuerpo": f("\n".join(filter(None, [x["detalle"], *k]))),
        "dueno": f(x["dueno"]),
        "prioridad": x["prioridad"],
        "fecha_limite": x["fecha_limite"],
        "estado": x["estado"],
        "origen": org,
        "enlaces": [] if an else [f"{base}/api/vista/{ci['mid']}/{ci['ver']}" for ci in x["citas"][:3] if ci.get("ver")],
    }


def _items(q, a, aprob, an, f, base, desde=None):
    """Ítems del registro de la clase `q` (plural); sin registro y con documento explícito: tareas y decisiones del acta (sin aprobar)."""
    xs = []
    if a["c"]:
        xs = [
            x
            for x in registro.completas(registro.listar(a["c"], REG[q]))
            if x["estado"] not in registro.OCULTA and x["revision"] in (("aprobado",) if aprob else ("aprobado", "propuesto"))
        ]
        if a["ids"]:
            xs = [x for x in xs if x["id"] in a["ids"]]
        if a["mid"]:
            xs = [x for x in xs if any(ci["mid"] == a["mid"] for ci in x["citas"])]
        if desde is not None:
            xs = [x for x in xs if (x.get("modificado") or 0) > desde]
    if xs or a["ids"] or desde is not None or not (a["mid"] and q in ("tareas", "decisiones")) or aprob:
        return [_de_ent(x, REG[q], an, f, base) for x in xs]
    c = exportar.carga(a["mid"], a["ver"], an)
    return [
        {
            "k": f"a:{a['mid']}:{a['ver']}:{q}.{i}",
            "tipo": REG[q],
            "codigo": "",
            "titulo": f(x.get("tarea") or x["texto"]),
            "cuerpo": "",
            "dueno": f(x.get("responsable", "")),
            "prioridad": "",
            "fecha_limite": x.get("plazo", ""),
            "estado": "",
            "origen": f(x.get("cita", "")),
            "enlaces": [],
        }
        for i, x in enumerate(c["data"].get(q, []))
    ]


def _md_items(secs, vault):
    o = []
    for q, its in secs:
        o.append(f"\n## {TIT.get(q, q.capitalize())}\n")
        for x in its:
            who = x["dueno"] and (f"[[{x['dueno']}]]" if vault else x["dueno"])
            plazo = f" ({x['fecha_limite']})" if x["fecha_limite"] else ""
            cod = f" `{x['codigo']}`" if x["codigo"] else ""
            o.append(
                (f"- [ ] {x['titulo']}" + (f" — {who}" if who else "") + plazo + cod)
                if x["tipo"] == "tarea"
                else f"- **{x['codigo'] or x['tipo']}** {x['titulo']}" + (f" — {who}" if who else "") + plazo
            )
            o += [f"  - {ln}" for ln in x["cuerpo"].splitlines() if ln.strip()]
            o += [f"  - Origen: {x['origen']}"] if x["origen"] else []
            o += [f"  - [Documento de origen]({u})" for u in x["enlaces"][:1]]
    return "\n".join(o) + "\n"


def _docs_inf(c):
    try:
        import app

        return app._inf_docs(c)
    except Exception:
        return ()


def _informe_id(c, regenerar):
    xs, ds = informe.listar(c), _docs_inf(c)
    if not xs:
        return informe.crear(c, docs=ds)["id"]
    if regenerar:
        informe.recalcular(c, xs[0]["id"], ds)
        xs = informe.listar(c)
    return xs[0]["id"]


def _hay_nuevo(c, desde):
    return any((x.get("modificado") or 0) > desde for x in registro.listar(c)) if c else False


# ---------- generación de ficheros (descargas y adjuntos): exportar.py + export_registro.py + informe.py ----------
def _mz():
    ER = export_registro
    return {
        "documento": (("docx", "pdf", "md", "obsidian", "notion"), ()),
        "transcripcion": (("srt", "vtt", "md"), ()),
        "resumen": (("md",), ()),
        "tareas": (("csv_todoist", "csv_jira", "csv_azure", "csv_planner", "ics") + OWN, OWN),
        "riesgos": (OWN, OWN),
        "informe": ((), tuple(informe.EXT)),
        **{q: (OWN, ER.formatos(q)) for q in ("decisiones", "requisitos", "historias", "interesados")},
    }


def _gen(u, q, fmt, aprob, an, ids, base=""):
    """u = {mid, ver, c} (unidad documento) | {c} (unidad proyecto) -> (extensión, bytes)."""
    mid = u.get("mid")
    if mid and q == "transcripcion" and fmt == "md":
        c = exportar.carga(mid, u["ver"], an)
        if not c["segs"]:
            raise ValueError("Sin transcripción")
        return "md", exportar.trans_md(c).encode()
    if mid and (q in ("documento", "transcripcion") or (q == "tareas" and fmt not in OWN)):
        return exportar.FORMATOS[fmt][0], exportar.exportar(mid, u["ver"], fmt, anon=an)[0]
    if mid and q == "resumen":
        c = exportar.carga(mid, u["ver"], an)
        return "md", f"# {c['data']['titulo']}\n\n{c['data'].get('resumen', '')}\n".encode()
    if q == "informe":
        if an:
            raise ValueError("El informe no se exporta anonimizado")
        return informe.EXT[fmt], informe.exportar(u["c"], _informe_id(u["c"], False), fmt, not aprob, _docs_inf(u["c"]))[0]
    if not mid and q in export_registro.TIPO and not an and not ids:
        return export_registro.EXT[fmt], export_registro.exportar(u["c"], q, fmt, not aprob, _docs_inf(u["c"]))[0]
    if fmt not in OWN:
        raise ValueError("Con anonimizado o ids concretos solo se exporta md, json o csv")
    a = {"mid": mid or "", "ver": u.get("ver", ""), "c": u.get("c"), "ids": ids}
    its = _items(q, a, aprob, an, _anonf([mid] if mid else [m for m, _ in _docs_de(u.get("c", ""))]) if an else (lambda t: t), base)
    if not its:
        raise ValueError("Sin elementos")
    if fmt == "json":
        return "json", json.dumps([{k: v for k, v in x.items() if k != "k"} for x in its], ensure_ascii=False, indent=1).encode()
    if fmt == "csv":
        b = io.StringIO()
        w = csv.writer(b, lineterminator="\r\n")
        w.writerow(["Código", "Título", "Detalle", "Responsable", "Plazo", "Prioridad", "Estado", "Origen"])
        w.writerows([x["codigo"], x["titulo"], x["cuerpo"], x["dueno"], x["fecha_limite"], x["prioridad"], x["estado"], x["origen"]] for x in its)
        return "csv", ("﻿" + b.getvalue()).encode()
    return "md", (f"# {TIT[q]}\n" + _md_items([(q, its)], False)).encode()


def _etq(u, an):
    if u.get("mid"):
        try:
            return exportar.carga(u["mid"], u["ver"], an)["data"]["titulo"]
        except Exception:
            return u["mid"]
    return "proyecto" if an else (u.get("c") or "Sin carpeta")


def juntar(que, formatos, docs, cs, cs_docs, aprob=False, anon=None, ids=(), ultimo=(), base=""):
    """-> (ficheros [(nombre, bytes)], omitidos [texto]). docs: unidades documento explícitas; cs: proyectos explícitos; cs_docs: carpetas de los documentos (solo para
    formatos que el documento no da); ultimo: documento a usar para documento/resumen cuando no hay explícitos. Nombres «<doc o proyecto> · <qué>.<ext>»."""
    mz, files, omit, vistos = _mz(), [], [], set()

    def poner(u, q, fmt):
        an = anon_activa({"c": u.get("c")}, anon)
        e = _etq(u, an)
        try:
            ext, b = _gen(u, q, fmt, aprob, an, list(ids), base)
        except (ValueError, KeyError, FileNotFoundError, RuntimeError, exportar.SinNavegador) as ex:
            omit.append(f"{e} · {q} · {fmt}: {ex}")
            return 0
        nom, n = f"{exportar._nombre_arch(e)} · {q}.{ext}", 1
        while nom in vistos:
            n += 1
            nom = f"{exportar._nombre_arch(e)} · {q} ({n}).{ext}"
        vistos.add(nom)
        files.append((nom, b))
        return 1

    for q in que:
        for fmt in formatos:
            if q not in mz or fmt not in mz[q][0] + mz[q][1]:
                omit.append(f"{q} · {fmt}: combinación no válida")
                continue
            us = []
            if fmt in mz[q][0]:
                us += [{**d, "c": _meta(d["mid"]).get("carpeta", "")} for d in (docs or (ultimo if q in DOCQ else []))]
            if fmt in mz[q][1]:
                us += [{"c": c} for c in dict.fromkeys(list(cs) + ([] if fmt in mz[q][0] and docs else list(cs_docs)))]
            if not us:
                omit.append(f"{q} · {fmt}: nada seleccionado a lo que aplicar")
            for u in us:
                poner(u, q, fmt)
    return files, omit


def _unidad(d):
    mid, ver = (d.split("/", 1) + [""])[:2] if isinstance(d, str) else (d["mid"], d.get("ver", ""))
    return {"mid": mid, "ver": ver or _ult(mid)}


def descargar(d):
    """{docs?:[mid|mid/ver], c?, ids?, que:[…], formatos:[…], solo_aprobados?, anon?} -> (ficheros, omitidos)."""
    docs = [_unidad(x) for x in d.get("docs") or []]
    cs = [d["c"]] if d.get("c") is not None else []
    if not (docs or cs):
        raise ValueError("Elige documentos (docs) o un proyecto (c)")
    if not d.get("que") or not d.get("formatos"):
        raise ValueError("Indica qué (que) y formatos")
    return juntar(
        d["que"],
        d["formatos"],
        docs,
        cs,
        [_meta(x["mid"]).get("carpeta", "") for x in docs],
        bool(d.get("solo_aprobados")),
        d.get("anon"),
        d.get("ids") or [],
        base=cfg()["url_base"].rstrip("/"),
    )


# ---------- páginas ----------
def _publica(base):
    """¿La url_base se abre desde otro equipo? Vacía o localhost: un enlace a /files/… solo funcionaría aquí."""
    h = urllib.parse.urlsplit(base).hostname or ""
    return bool(h) and h not in ("localhost", "::1") and not h.startswith("127.")


def _front(titulo):
    return "\n".join(["---", f"title: {json.dumps(titulo, ensure_ascii=False)}", f"date: {dt.date.today()}", "tipo: seleccion", "tags: [actas]", "---", ""])


def _pagina(que, sel, a, o, titulo, an, aprob, base):
    c, md = sel["c"], []
    fmts = o.get("formatos") or ([o["formato"]] if o.get("formato") else ["md"])
    vault = o.get("vault") in (True, "true", 1)
    ficheros = []
    if "documento" in que and c:
        md.append(exportar.md(c, img="adjuntos" if vault else None, links=vault))
        if vault:
            ficheros += [
                (f"adjuntos/{k['img']}", (c["d"] / c["img"] / k["img"]).read_bytes())
                for k in c["data"].get("capturas", [])
                if (c["d"] / c["img"] / k["img"]).is_file()
            ]
    elif "resumen" in que and c and c["data"].get("resumen"):
        md.append("## Resumen\n\n" + c["data"]["resumen"])
    if sel["secs"]:
        md.append(_md_items(sel["secs"], vault))
    if sel.get("informe"):
        md.append(sel["informe"])
    cuerpo = "\n".join(md)
    omit = []
    if o.get("archivos"):  # otros formatos (docx, pdf, csv_jira, xlsx…) del mismo ámbito, con los mismos generadores que «Descargar»
        ult = [{"mid": a["dm"], "ver": a["dv"]}] if a["dm"] else []
        extra, omit = juntar(
            que,
            [f for f in fmts if f != "md"],
            [{"mid": a["mid"], "ver": a["ver"]}] if a["mid"] else [],
            [a["c"]] if a["c"] and not a["mid"] else [],
            [a["c"]] if a["c"] else [],
            aprob,
            an,
            a["ids"],
            ult,
            base,
        )
        ficheros += extra
    if "md" in fmts or not ficheros:
        fr = exportar.frontmatter(c) if vault and "documento" in que and c else _front(titulo)
        ficheros.insert(0, (f"{exportar._nombre_arch(titulo)}.md", (fr + (cuerpo if cuerpo.startswith("#") else f"# {titulo}\n\n{cuerpo}")).encode()))
    js = {
        "carpeta": "" if an else a["c"] or "",
        "documento": {"mid": a["dm"], "ver": a["dv"], "titulo": c["data"]["titulo"]} if c else None,
        "resumen": c["data"].get("resumen") if c and "resumen" in que else None,
        "enlace": f"{base}/api/vista/{a['dm']}/{a['dv']}" if a["dm"] and not an else "",
        "texto": cuerpo,
        "video": ""
        if an or not a["dm"]
        else _meta(a["dm"]).get("url")
        or next((f"{base}/files/{a['dm']}/{v.name}" for v in (P.WORK / Path(a["dm"]).name).glob("video.*") if _publica(base)), ""),
        "items": [{k: v for k, v in x.items() if k != "k"} for _, its in sel["secs"] for x in its],
    }
    return {
        "k": f"pag|{a['mid'] or a['c']}|{'+'.join(sorted(que))}",
        "titulo": titulo,
        "md": cuerpo or f"# {titulo}",
        "ficheros": ficheros,
        "json": js,
        "omitidos": omit,
        "h": hashlib.sha1(json.dumps([cuerpo, [(n, hashlib.sha1(b).hexdigest()) for n, b in ficheros]]).encode()).hexdigest(),
    }


def _doc_escribir(carpeta, titulo, md, mid=None):
    """Documento nuevo (o reescrito) dentro del proyecto: aparece en su lista y se abre. Sin tareas/decisiones propias (poblar no las duplica); el md va en el resumen."""
    nuevo = not mid
    mid = mid or uuid.uuid4().hex[:16]
    wd, ver = P.WORK / Path(mid).name, "acta_normal_impdoc"
    (wd / ver).mkdir(parents=True, exist_ok=True)
    data = {
        "titulo": titulo,
        "duracion": 0,
        "nivel": "normal",
        "resumen": md,
        "relato": [],
        "puntos": [],
        "secciones": [],
        "decisiones": [],
        "tareas": [],
        "capturas": [],
        "plantilla": "Acta de reunión",
        "secciones_plantilla": [],
    }
    (wd / ver / "acta.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    if nuevo:
        (wd / "transcript_impdoc.json").write_text(
            json.dumps({"language": "es", "segments": [], "solo_acta": True, "importada": {"fuente": titulo}}, ensure_ascii=False), encoding="utf-8"
        )
        (wd / "meta.json").write_text(json.dumps({"nombre": titulo, "carpeta": carpeta}, ensure_ascii=False), encoding="utf-8")
    try:
        html = exportar.html_doc(exportar.carga(mid, ver))
    except Exception:
        import html as H

        html = f"<!doctype html><meta charset=utf-8><title>{H.escape(titulo)}</title><h1>{H.escape(titulo)}</h1><pre>{H.escape(md)}</pre>"
    (wd / ver / "index.html").write_text(html, encoding="utf-8")
    return mid, f"/files/{mid}/{ver}/index.html"


T.TIPOS["proyecto"] = {
    "nombre": "Documento en proyecto (interno)",
    "modo": "pagina",
    "interno": True,
    "campos": [T.F("carpeta", "Proyecto", req=True, preset=True)],
    "probar": None,
    "crear": lambda c, s, o, x, n=None: _doc_escribir(o["carpeta"], x["titulo"], x["md"], n),
}
T.TIPOS["proyecto"]["actualizar"] = T.TIPOS["proyecto"]["crear"]
T.SECRETOS["proyecto"] = []


# ---------- envío ----------
def _mapa(k=None, v=None):
    with LOCK:
        m = _leer(MAPA(), {})
        if v is not None:
            m[k] = v
            _escribir(MAPA(), m)
        return m.get(k) if k else m


def _hash(x):
    return hashlib.sha1(
        json.dumps(
            {k: x.get(k, "") for k in ("titulo", "cuerpo", "dueno", "prioridad", "fecha_limite", "estado", "origen", "codigo")},
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _pseudo(k, tipo, titulo, cuerpo):
    return {
        "k": k,
        "tipo": tipo,
        "codigo": "",
        "titulo": titulo,
        "cuerpo": cuerpo,
        "dueno": "",
        "prioridad": "",
        "fecha_limite": "",
        "estado": "",
        "origen": "",
        "enlaces": [],
    }


def _envio(req):
    """req = {destino, que, formatos, solo_aprobados, anonimizar, opciones, doc|c|ids, nombre, preset?, desde?, meta?} -> entrada del historial (guardada); None si solo_nuevo y no hay novedades."""
    e = {
        "id": uuid.uuid4().hex[:10],
        "t": time.time(),
        "preset": req.get("preset"),
        "destino": req["destino"],
        "que": list(req["que"]),
        "req": req,
        "items": [],
        "enlaces": [],
        "estado": "ok",
        "error": "",
        "omitidos": [],
        "meta": req.get("meta") or {},
    }
    try:
        cf = cfg()
        d = {"tipo": "proyecto", "nombre": "Documento en proyecto", "config": {}} if req["destino"] == INTERNO else cf["destinos"].get(req["destino"])
        if not d:
            raise ValueError("Destino no configurado")
        tp = T.TIPOS[d["tipo"]]
        o = {
            **d["config"],
            **{k: v for k, v in (req.get("opciones") or {}).items() if v not in ("", None)},
            **({"formatos": req["formatos"]} if req.get("formatos") else {}),
            "archivos": bool(tp.get("archivos")),
        }
        s = {k: _sec_get(req["destino"], k) for k in T.SECRETOS[d["tipo"]]}
        falta = [f["etiqueta"] for f in tp["campos"] if f["req"] and not (s.get(f["id"]) if f["tipo"] == "secreto" else o.get(f["id"]))]
        if falta:
            raise ValueError("Falta configurar: " + ", ".join(falta))
        a = _ambito(req)
        if not (a["mid"] or a["c"] is not None):
            raise ValueError("Indica un documento (doc) o una carpeta (c)")
        interno = d["tipo"] == "proyecto"
        an = False if interno else anon_activa(a, req.get("anonimizar"))  # lo que se queda en el equipo (documento en proyecto) no sale: no se anonimiza
        if an and "informe" in req["que"]:
            raise ValueError("El informe no se envía anonimizado")
        que = [q for q in QUE if q in req["que"]]
        desde, base, aprob = req.get("desde"), cf["url_base"].rstrip("/"), bool(req.get("solo_aprobados"))
        mids = [a["mid"]] if a["mid"] else [m for m, _ in _docs_de(a["c"] or "")]
        f = _anonf(mids) if an else (lambda t: t)
        secs = [(q, _items(q, a, aprob, an, f, base, desde)) for q in que if q in REG]
        secs = [(q, i) for q, i in secs if i]
        if desde is not None and not (secs if any(q in REG for q in que) else _hay_nuevo(a["c"], desde)):
            raise NadaNuevo
        c = None
        if {"documento", "resumen"} & set(que):
            if not a["dm"]:
                raise ValueError("No hay documento del que tomar el resumen o el documento completo")
            c = exportar.carga(a["dm"], a["dv"], an)
        inf = None
        if "informe" in que:
            if not a["c"]:
                raise ValueError("El informe necesita un proyecto (c)")
            inf = informe.exportar(a["c"], _informe_id(a["c"], True), "md", not aprob, _docs_inf(a["c"]))[0].decode()
        sel = {"secs": secs, "c": c, "informe": inf}
        ak = hashlib.sha1(json.dumps([o.get(x["id"]) for x in tp["campos"] if x["preset"]], default=str).encode()).hexdigest()[:8]
        if tp["modo"] == "items":
            pend = [x for _, its in secs for x in its]
            if c and "resumen" in que:
                pend.append(_pseudo(f"a:{a['dm']}:resumen", "resumen", "Resumen: " + c["data"]["titulo"], c["data"].get("resumen", "")))
            if c and "documento" in que:
                pend.append(_pseudo(f"a:{a['dm']}:documento", "documento", c["data"]["titulo"], exportar.md(c)))
            if inf:
                pend.append(_pseudo(f"i:{a['c']}", "informe", "Informe de estado " + a["c"], inf))
            pend = [{**x, "h": _hash(x)} for x in pend]
        else:
            tit = req.get("nombre") or (
                c["data"]["titulo"] if c else f"{'proyecto' if an else a['c']} – " + ", ".join(que)
            )  # anonimizado: ni el nombre del proyecto
            pg = _pagina(que, sel, a, o, tit, an, aprob, base)
            pend = [pg | ({"k": pg["k"] + f"|{o.get('carpeta')}|{tit}"} if interno else {})]
            e["omitidos"] = pg["omitidos"]
        if not pend:
            raise ValueError("Nada que enviar con esa selección (¿solo aprobados? ¿sin elementos?)")
        with T.tls(o):
            for x in pend:
                r = {"k": x["k"], "titulo": x["titulo"], "accion": "", "id": "", "url": "", "error": ""}
                try:
                    key = f"{req['destino']}|{ak}|{x['k']}"
                    m = _mapa(key)
                    if m and m["h"] == x["h"] and not req.get("reenviar"):  # mismo contenido ya enviado; «reenviar» lo fuerza
                        r |= {"accion": "omitido", "id": m["id"], "url": m["url"]}
                    else:
                        if m and tp.get("actualizar"):
                            r["id"], r["url"] = tp["actualizar"](d["config"], s, o, x, m["id"])
                            r["accion"] = "actualizado"
                        else:
                            r["id"], r["url"] = tp["crear"](d["config"], s, o, x)
                            r["accion"] = "creado" if not m else "reenviado"
                        _mapa(key, {"h": x["h"], "id": r["id"], "url": r["url"], "t": time.time()})
                except Exception as ex:
                    r |= {"accion": "error", "error": str(ex) or type(ex).__name__}
                e["items"].append(r)
        e["enlaces"] = [r["url"] for r in e["items"] if r["url"]]
        bad = [r for r in e["items"] if r["accion"] == "error"]
        e["estado"] = "error" if len(bad) == len(e["items"]) else "parcial" if bad else "ok"
        e["error"] = "; ".join(sorted({r["error"] for r in bad}))[:500]
    except NadaNuevo:
        return None
    except Exception as ex:
        e |= {"estado": "error", "error": str(ex) or type(ex).__name__}
    _log(e)
    return e


def _pedido(d, cf=None):
    """Cuerpo de /api/enviar (preset | destino+que) -> req normalizado."""
    cf = cf or cfg()
    p = cf["presets"].get(d["preset"]) if d.get("preset") else None
    if d.get("preset") and not p:
        raise ValueError("Preset desconocido")
    p = {**(p or {}), **{k: v for k, v in d.items() if k in ("destino", "que", "formatos", "solo_aprobados", "anonimizar", "nombre") and v is not None}}
    p["opciones"] = {**(p.get("opciones") or {}), **(d.get("opciones") or {})}
    if not p.get("destino") or not p.get("que"):
        raise ValueError("Indica preset o destino + que")
    if p["destino"] != INTERNO and p["destino"] not in cf["destinos"]:
        raise ValueError("Destino no configurado")
    if set(p["que"]) - set(QUE):
        raise ValueError("Elementos no válidos: " + ", ".join(sorted(set(p["que"]) - set(QUE))))
    return {**p, **{k: d[k] for k in ("doc", "c", "ids", "desde", "meta", "reenviar") if k in d}, "preset": d.get("preset")}


# ---------- planes y recetas ----------
def normalizar_plan(p):
    """Plan limpio; las salidas hacia un destino que no existe llevan `configurar: true` (no falla: se avisa en la UI)."""
    cf, out = cfg(), []
    for s in (p or {}).get("salidas") or []:
        como = "documento" if s.get("como") == "documento" or s.get("destino") == INTERNO else "destino"
        if s.get("que") and s["que"] not in QUE:
            raise ValueError(f"Elemento no válido: {s['que']}")
        z = {"que": s.get("que", ""), "como": como, **{k: s[k] for k in ("preset", "destino", "nombre") if s.get(k)}}
        if s.get("formatos"):
            if not isinstance(s["formatos"], list) or not all(isinstance(f, str) for f in s["formatos"]):
                raise ValueError("formatos: lista de textos")
            z["formatos"] = s["formatos"]
        if como == "destino":
            if not (z.get("preset") in cf["presets"] or z.get("destino") in cf["destinos"]):
                z["configurar"] = True
            if not (z["que"] or z.get("preset") in cf["presets"]):
                raise ValueError("Cada salida necesita `que` (o un preset)")
        out.append(z)
    return {**{k: p[k] for k in ("carpeta", "nombre", "plantilla", "solo_buscable", "repetir") if k in p}, "salidas": out}


def programar_desde_plan(plan):
    """Añadir con «Repetir cada…»: crea una receta programada de la carpeta con las mismas salidas. Devuelve su id o None."""
    rp = (plan or {}).get("repetir")
    if not rp or not plan.get("carpeta"):
        return None
    pl = normalizar_plan({k: v for k, v in plan.items() if k != "repetir"})
    r = _val_receta(
        {
            "nombre": f"{plan.get('nombre') or plan['carpeta']} · cada {rp.get('cada', 'semana')}",
            "activa": True,
            "cuando": {"tipo": "programado", "carpeta": plan["carpeta"], **{k: rp[k] for k in ("cada", "dia_semana", "dia_mes", "hora") if k in rp}},
            "plan": pl,
            "solo_nuevo": True,
        }
    )
    i = uuid.uuid4().hex[:8]
    with LOCK:
        cf = cfg()
        cf["recetas"][i] = r
        _escribir(CFG(), cf)
    return i


def ejecutar_plan(plan, doc, desde=None, meta=None):
    """doc: {doc:"mid/ver"} o {c}. Una entrada de historial por salida (las que no tienen novedades, ninguna); nunca lanza."""
    r = []
    for s in plan.get("salidas", []):
        try:
            if s.get("configurar"):
                raise ValueError("Salida sin destino configurado")
            nom0 = plan.get("nombre") or ""
            ex = {k: v for k, v in (("desde", desde), ("meta", meta)) if v is not None}
            if s["como"] == "documento":
                q = s.get("que") or "resumen"
                carp = plan.get("carpeta") or doc.get("c") or (_meta(doc["doc"].split("/")[0]).get("carpeta", "") if doc.get("doc") else "")
                d = {**doc, **ex, "destino": INTERNO, "que": [q], "nombre": s.get("nombre") or f"{nom0} – {q}".strip(" –"), "opciones": {"carpeta": carp}}
            else:
                d = {
                    **doc,
                    **ex,
                    "preset": s.get("preset"),
                    "destino": s.get("destino"),
                    "que": [s["que"]] if s.get("que") else None,
                    "nombre": s.get("nombre"),
                    "formatos": s.get("formatos"),
                }
            e = _envio(_pedido(d))
            if e:
                r.append(e)
        except Exception as ex:
            r.append(_log_error(s, ex, meta))
    return r


def _tipo_fuente(mid):
    wd = P.WORK / Path(mid).name
    v = next(iter(wd.glob("video.*")), None)
    if v:
        return "audio" if v.suffix.lower() in AUDIO else "video"
    f = next(iter(wd.glob("fuente.*")), None)
    import documentos  # pdf | texto | imagen (mismo criterio que app._kind)

    return documentos.tipo(f) if f else "texto"


def _coincide(cu, mid, ver):
    ins = {
        "carpeta": _meta(mid).get("carpeta", ""),
        "plantilla": _leer(P.WORK / mid / ver / "acta.json", {}).get("plantilla", ""),
        "tipo_fuente": _tipo_fuente(mid),
    }
    return all(str(ins[k]).casefold() == str(v).casefold() for k, v in (cu or {}).items() if k in ins and v)


def _plan_de(r):
    return r.get("plan") or {"salidas": [{"preset": p, "como": "destino"} for p in r.get("presets", [])]}


def _auto(mid, ver, plan):
    """Recetas «al terminar» que coinciden + el plan del trabajo. Si el trabajo trae plan (aunque vacío), sustituye a las recetas de SU carpeta (no se envía dos veces)."""
    carp = _meta(mid).get("carpeta", "").casefold()
    for i, r in cfg()["recetas"].items():
        cu = r.get("cuando") or {}
        if (
            r.get("activa")
            and cu.get("tipo", "al_terminar") == "al_terminar"
            and _coincide(cu, mid, ver)
            and not (plan is not None and cu.get("carpeta") and cu["carpeta"].casefold() == carp)
        ):
            ejecutar_plan(_plan_de(r), {"doc": f"{mid}/{ver}"}, meta={"receta": i})
    if plan and plan.get("salidas"):
        try:
            plan = normalizar_plan(plan)
        except Exception as ex:
            _log_error({"que": "plan"}, ex, {"plan": "trabajo"})
            return
        ejecutar_plan(plan, {"doc": f"{mid}/{ver}"}, meta={"plan": "trabajo"})


def plan_defecto(c):
    """Salidas por defecto de una carpeta = sus recetas activas «al terminar» (la UI de Añadir las marca y el trabajo guarda el plan final)."""
    sal = []
    for i, r in cfg()["recetas"].items():
        cu = r.get("cuando") or {}
        if (
            r.get("activa")
            and cu.get("tipo", "al_terminar") == "al_terminar"
            and cu.get("carpeta", "").casefold() == c.casefold()
            and not any(cu.get(k) for k in ("plantilla", "tipo_fuente"))
        ):
            sal += [{**z, "receta": i} for z in normalizar_plan(_plan_de(r))["salidas"]]
    return {"carpeta": c, "salidas": sal}


def _hilo(fn, *a):
    def run():
        try:
            fn(*a)
        except Exception as ex:
            try:
                _log_error({}, ex)
            except Exception:
                pass

    threading.Thread(target=run, daemon=True).start()


def tras_documento(mid, ver, plan=None, poblando=False):
    """Gancho al acabar un documento (app._acta_fn). Si luego correrá `poblar`, las recetas esperan a tras_poblar. Nunca bloquea ni lanza."""
    if not poblando:
        _hilo(_auto, mid, ver, plan)


def tras_poblar(c, mid, plan=None):
    """Gancho al acabar `poblar` de un documento de la carpeta c (ya existen sus ítems del registro)."""
    try:
        _hilo(_auto, mid, _ult(mid), plan)
    except Exception:
        pass


# ---------- envíos programados ----------
def proximo_tras(cu, ahora):
    """Siguiente ejecución (datetime) estrictamente posterior a `ahora` de {cada: dia|semana|mes, dia_semana: 0-6 (lunes=0), dia_mes: 1-28, hora: "HH:MM"}."""
    h, m = map(int, cu.get("hora", "09:00").split(":"))
    base = ahora.replace(hour=h, minute=m, second=0, microsecond=0)
    for n in range(0, 62):
        d = base + dt.timedelta(days=n)
        if d > ahora and (
            cu["cada"] == "dia"
            or (cu["cada"] == "semana" and d.weekday() == int(cu.get("dia_semana", 0)))
            or (cu["cada"] == "mes" and d.day == int(cu.get("dia_mes", 1)))
        ):
            return d
    raise ValueError("Programación no válida")


def _poner_receta(i, **kv):
    with LOCK:
        cf = cfg()
        if i in cf["recetas"]:
            cf["recetas"][i].update(kv)
            _escribir(CFG(), cf)


def correr_receta(i, ahora=None, atrasado=False, manual=False):
    """Ejecuta una receta programada: solo lo nuevo desde el último envío correcto (si solo_nuevo). Un solo salto aunque la app haya estado cerrada mucho tiempo."""
    ahora = ahora or dt.datetime.now()
    r = cfg()["recetas"][i]
    cu = r.get("cuando") or {}
    desde = (r.get("ultimo_envio") or 0.0) if r.get("solo_nuevo", True) else None
    es = ejecutar_plan(_plan_de(r), {"c": cu.get("carpeta", "")}, desde, {"receta": i, "atrasado": bool(atrasado), "manual": bool(manual)})
    ok = bool(es) and all(e["estado"] == "ok" for e in es)  # «parcial»: no avanza ultimo_envio (los fallidos se reintentan; los ya enviados se omiten por hash)
    _poner_receta(
        i,
        ultimo_intento=ahora.timestamp(),
        atrasado=bool(atrasado),
        ultimo_resultado="sin novedades" if not es else "ok" if ok else "error",
        **({"ultimo_envio": ahora.timestamp()} if ok else {}),
        **({} if manual else {"proximo": proximo_tras(cu, ahora).timestamp()}),
    )
    return es


def tick(ahora=None):
    """Una pasada del planificador (la llama el hilo cada minuto; en pruebas, con reloj inyectado)."""
    ahora, out = ahora or dt.datetime.now(), []
    for i, r in list(cfg()["recetas"].items()):
        cu = r.get("cuando") or {}
        if not r.get("activa") or cu.get("tipo") != "programado":
            continue
        try:
            if not r.get("proximo"):
                _poner_receta(i, proximo=proximo_tras(cu, ahora).timestamp())
            elif ahora.timestamp() >= r["proximo"]:
                out += correr_receta(i, ahora, atrasado=ahora.timestamp() - r["proximo"] > 300)
        except Exception as ex:
            _log_error({}, ex, {"receta": i})
            try:
                _poner_receta(i, proximo=proximo_tras(cu, ahora).timestamp())
            except Exception:
                pass
    return out


_parar, _hilo_plan = threading.Event(), []


def iniciar():
    """Arranca (una vez) el hilo del planificador: revisa cada minuto; al arrancar ejecuta una vez lo vencido («atrasado»). Nunca rompe la app."""
    if _hilo_plan:
        return

    def bucle():
        while not _parar.is_set():
            try:
                tick()
            except Exception:
                pass
            _parar.wait(60)

    _hilo_plan.append(threading.Thread(target=bucle, daemon=True, name="actas-destinos"))
    _hilo_plan[0].start()


# ---------- carpetas sincronizadas de Microsoft ----------
def sugerencias():
    """OneDrive / SharePoint sincronizados en este equipo -> [{nombre, ruta, tipo, formatos}] (formatos de Office por defecto)."""
    out, vistos, h = [], set(), Path.home()

    def add(n, r, tipo):
        r = Path(r)
        if str(r) not in vistos and r.is_dir():
            vistos.add(str(r))
            out.append({"nombre": n, "ruta": str(r), "tipo": tipo, "formatos": ["docx", "xlsx", "pdf"]})

    for env in ("OneDriveCommercial", "OneDriveConsumer", "OneDrive"):
        if os.environ.get(env):
            add(Path(os.environ[env]).name, os.environ[env], "onedrive")
    for p in sorted(h.glob("OneDrive*")):
        add(p.name, p, "onedrive")
        org = p.name[len("OneDrive - ") :] if p.name.startswith("OneDrive - ") else ""
        for s in sorted((h / org).glob("* - *")) if org and (h / org).is_dir() else []:  # bibliotecas de SharePoint: <Org>/<Sitio> - <Biblioteca>
            add(s.name, s, "sharepoint")
    for p in sorted((h / "Library" / "CloudStorage").glob("*")) if (h / "Library" / "CloudStorage").is_dir() else []:
        add(p.name, p, "sharepoint" if p.name.startswith("SharePoint") else "onedrive") if p.name.startswith(("OneDrive-", "SharePoint-")) else None
    return out


# ---------- API ----------
def _err(f, *a):
    try:
        return f(*a)
    except HTTPException:
        raise
    except (ValueError, KeyError, FileNotFoundError) as ex:
        raise HTTPException(400, str(ex) or type(ex).__name__)
    except RuntimeError as ex:
        raise HTTPException(409, str(ex))


def _publico(i, d):
    return {"id": i, "tipo": d["tipo"], "nombre": d["nombre"], "config": d["config"], "secretos": {k: bool(_sec_get(i, k)) for k in T.SECRETOS[d["tipo"]]}}


@router.get("/api/destinos")
def api_destinos():
    cf = cfg()
    return {
        "tipos": {t: {"nombre": v["nombre"], "modo": v["modo"], "interno": bool(v.get("interno")), "campos": v["campos"]} for t, v in T.TIPOS.items()},
        "interno": INTERNO,
        "que": list(QUE),
        "destinos": [_publico(i, d) for i, d in cf["destinos"].items()],
        "url_base": cf["url_base"],
    }


@router.get("/api/destinos/sugerencias")
def api_sugerencias():
    return sugerencias()


def _guardar_destino(i, tipo, nombre, conf):
    if tipo not in T.TIPOS or T.TIPOS[tipo].get("interno"):
        raise ValueError("Tipo de destino desconocido")
    sec, campos = T.SECRETOS[tipo], {f["id"] for f in T.TIPOS[tipo]["campos"]}
    with LOCK:
        cf = cfg()
        old = cf["destinos"].get(i, {"config": {}})
        for k in sec:
            if k in conf:
                _sec_set(i, k, str(conf[k] or "").strip())
        cf["destinos"][i] = {
            "tipo": tipo,
            "nombre": nombre or T.TIPOS[tipo]["nombre"],
            "config": {**old["config"], **{k: v for k, v in conf.items() if k in campos and k not in sec}},
        }
        _escribir(CFG(), cf)
        return _publico(i, cf["destinos"][i])


@router.post("/api/destinos")
def api_dest_crear(d: dict):
    return _err(_guardar_destino, uuid.uuid4().hex[:8], d.get("tipo"), d.get("nombre"), d.get("config") or {})


@router.patch("/api/destinos/{i}")
def api_dest_editar(i: str, d: dict):
    o = cfg()["destinos"].get(i)
    if not o:
        raise HTTPException(404, "No existe")
    return _err(_guardar_destino, i, o["tipo"], d.get("nombre") or o["nombre"], d.get("config") or {})


@router.delete("/api/destinos/{i}")
def api_dest_borrar(i: str):
    with LOCK:
        cf = cfg()
        if i not in cf["destinos"]:
            raise HTTPException(404, "No existe")
        if any(p["destino"] == i for p in cf["presets"].values()):
            raise HTTPException(409, "Hay presets que usan este destino")
        t = cf["destinos"].pop(i)["tipo"]
        _escribir(CFG(), cf)
    for k in T.SECRETOS[t]:
        try:
            _sec_set(i, k, "")
        except RuntimeError:
            pass
    return {"ok": True}


@router.post("/api/destinos/{i}/probar")
def api_probar(i: str, d: dict | None = None):
    x = cfg()["destinos"].get(i)
    if not x:
        raise HTTPException(404, "No existe")
    tp = T.TIPOS[x["tipo"]]
    s = {k: _sec_get(i, k) for k in T.SECRETOS[x["tipo"]]}
    o = {**x["config"], **((d or {}).get("opciones") or {})}
    falta = [f["etiqueta"] for f in tp["campos"] if f["req"] and not f["preset"] and not (s.get(f["id"]) if f["tipo"] == "secreto" else o.get(f["id"]))]
    try:
        if falta:
            raise ValueError("Falta configurar: " + ", ".join(falta))
        with T.tls(o):
            r = tp["probar"](o, s) if tp["probar"] else None
        return {
            "ok": True,
            "mensaje": r if isinstance(r, str) else "Conexión correcta" if tp["probar"] else "Configurado (este tipo no tiene prueba sin enviar)",
            **({"aviso": "Certificado TLS sin verificar"} if o.get("verificar_tls") in (False, "false") else {}),
        }
    except Exception as ex:
        return {"ok": False, "mensaje": str(ex) or type(ex).__name__}


@router.post("/api/enviar")
def api_enviar(d: dict):
    return _err(lambda: _envio(_pedido(d)))


def _historial():
    return [json.loads(ln) for ln in LOG().read_text(encoding="utf-8").splitlines() if ln.strip()] if LOG().is_file() else []


@router.get("/api/envios")
def api_envios(limit: int = 100):
    return [
        {k: v for k, v in e.items() if k != "req"} | {"reintentable": bool(e.get("req")) and e["estado"] != "ok"}
        for e in reversed(_historial()[-max(1, limit) :])
    ]


@router.post("/api/envios/{i}/reintentar")
def api_reintentar(i: str):
    e = next((x for x in _historial() if x["id"] == i), None)
    if not e or not e.get("req"):
        raise HTTPException(404, "No existe o no se puede reintentar")
    r = _err(_envio, e["req"])
    return {**(r or {"estado": "ok", "items": [], "enlaces": []}), "de": i}


@router.get("/api/descargar/opciones")
def api_desc_opciones():
    mz = _mz()
    return {
        "que": {q: {"documento": list(v[0]), "proyecto": list(v[1])} for q, v in mz.items()},
        "formatos": sorted({f for v in mz.values() for f in v[0] + v[1]}),
    }


@router.post("/api/descargar")
def api_descargar(d: dict):
    files, omit = _err(descargar, d)
    if not files:
        raise HTTPException(400, "Nada que descargar: " + "; ".join(omit))
    if len(files) == 1:
        nom, b = files[0]
        return Response(
            b,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(nom),
                "X-Actas-Omitidos": urllib.parse.quote(json.dumps(omit, ensure_ascii=False)),
            },
        )
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for nom, b in files:
            zf.writestr(nom, b)
        if omit:
            zf.writestr("LEEME.txt", "No incluido:\n" + "\n".join("- " + x for x in omit))
    return Response(
        z.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote("Actas · descarga.zip")},
    )


def _val_preset(d):
    if not d.get("nombre"):
        raise ValueError("Falta el nombre")
    _pedido({**d, "preset": None})
    return {k: d[k] for k in ("nombre", "destino", "que", "formatos", "solo_aprobados", "anonimizar", "opciones", "fijado") if k in d}


def _val_receta(d):
    cf = cfg()
    if any(p not in cf["presets"] for p in d.get("presets", [])):
        raise ValueError("Preset desconocido")
    cu = {
        k: v
        for k, v in (d.get("cuando") or {}).items()
        if k in ("tipo", "carpeta", "plantilla", "tipo_fuente", "cada", "dia_semana", "dia_mes", "hora") and v not in ("", None)
    }
    cu.setdefault("tipo", "al_terminar")
    r = {
        "nombre": d.get("nombre", ""),
        "activa": bool(d.get("activa", False)),
        "cuando": cu,
        "presets": d.get("presets", []),
        "solo_nuevo": bool(d.get("solo_nuevo", True)),
        **{k: d[k] for k in ("ultimo_envio", "ultimo_intento", "ultimo_resultado", "atrasado") if k in d},
    }
    if cu["tipo"] == "programado":
        if not cu.get("carpeta"):
            raise ValueError("Una receta programada necesita proyecto (cuando.carpeta)")
        if cu.get("cada") not in ("dia", "semana", "mes"):
            raise ValueError("cada: dia | semana | mes")
        if "dia_semana" in cu and not 0 <= int(cu["dia_semana"]) <= 6 or "dia_mes" in cu and not 1 <= int(cu["dia_mes"]) <= 28:
            raise ValueError("dia_semana 0-6, dia_mes 1-28")
        r["proximo"] = proximo_tras(cu, dt.datetime.now()).timestamp()
    elif cu["tipo"] != "al_terminar":
        raise ValueError("cuando.tipo: al_terminar | programado")
    return {**r, **({"plan": normalizar_plan(d["plan"])} if d.get("plan") else {})}


def _crud(coleccion, val, vista=lambda x: x):
    base = f"/api/{coleccion}"

    def poner(i, d, nuevo):
        with LOCK:
            cf = cfg()
            if not nuevo and i not in cf[coleccion]:
                raise HTTPException(404, "No existe")
            ant = {} if nuevo else cf[coleccion][i]
            cf[coleccion][i] = val({**ant, **d})
            _escribir(CFG(), cf)
            return vista({"id": i, **cf[coleccion][i]})

    def borrar(i):
        with LOCK:
            cf = cfg()
            if cf[coleccion].pop(i, None) is None:
                raise HTTPException(404, "No existe")
            _escribir(CFG(), cf)
        return {"ok": True}

    def lista(c: str | None = None):
        return [vista({"id": i, **v}) for i, v in cfg()[coleccion].items() if c is None or (v.get("cuando") or {}).get("carpeta", c) == c]

    router.get(base)(lista)

    def crear(d: dict):
        return _err(poner, uuid.uuid4().hex[:8], d, True)

    def editar(i: str, d: dict):
        return _err(poner, i, d, False)

    router.post(base)(crear)
    router.patch(base + "/{i}")(editar)
    router.delete(base + "/{i}")(borrar)


def _doc(*qs):
    return [{"que": q, "como": "documento"} for q in qs]


# objetivos de «Añadir» de serie (solo lectura): id «serie:x», plan + plantilla (ids de plantillas.SERIE)
OBJ_SERIE = [
    ("reunion", "Acta de reunión", "acta", {"salidas": _doc("tareas", "decisiones")}),
    ("requisitos", "Requisitos e historias", "requisitos", {"salidas": _doc("requisitos", "historias")}),
    ("resumen", "Resumen y puntos clave", None, {"salidas": _doc("resumen")}),
    ("seguimiento", "Seguimiento / informe", "raid", {"salidas": _doc("tareas", "decisiones", "riesgos")}),
    ("entrevista", "Entrevista", "seleccion", {"salidas": _doc("resumen")}),
    ("clase", "Apuntes de clase", "clase", {"salidas": _doc("resumen", "tareas")}),
    ("buscable", "Solo hacerlo buscable", None, {"solo_buscable": True, "salidas": []}),
]


def _val_objetivo(d):
    if not str(d.get("nombre") or "").strip():
        raise ValueError("Falta el nombre")
    o = {"nombre": d["nombre"].strip(), "plan": normalizar_plan(d.get("plan") or {}), "fijado": bool(d.get("fijado", False))}
    if d.get("plantilla"):
        o["plantilla"] = str(d["plantilla"])
    return o


@router.get("/api/objetivos")
def api_objetivos():
    serie = [{"id": "serie:" + i, "nombre": n, "serie": True, "plan": pl, **({"plantilla": t} if t else {})} for i, n, t, pl in OBJ_SERIE]
    return serie + [{"id": i, **v} for i, v in cfg()["objetivos"].items()]


_crud("objetivos", _val_objetivo)
_crud("presets", _val_preset)
_crud(
    "recetas", _val_receta, lambda r: {**r, "proximo_iso": dt.datetime.fromtimestamp(r["proximo"]).isoformat(timespec="minutes") if r.get("proximo") else None}
)


@router.get("/api/carpetas/{c}/plan_defecto")
def api_plan_defecto(c: str):
    return plan_defecto(c)


@router.post("/api/recetas/{i}/ahora")
def api_receta_ahora(i: str):
    r = cfg()["recetas"].get(i)
    if not r:
        raise HTTPException(404, "No existe")
    cu = r.get("cuando") or {}
    if cu.get("tipo") == "programado":
        return [{k: v for k, v in e.items() if k != "req"} for e in correr_receta(i, manual=True)]
    ds = _docs_de(cu.get("carpeta", "")) if cu.get("carpeta") is not None else []
    if not ds:
        raise HTTPException(400, "No hay ningún documento al que aplicar la receta")
    return [{k: v for k, v in e.items() if k != "req"} for e in ejecutar_plan(_plan_de(r), {"doc": "/".join(ds[0])}, meta={"receta": i, "manual": True})]
