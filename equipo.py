"""Configuración de equipo (docs/plan-equipos.md, A6): un .actas-equipo.json con plantillas propias, estilos (con logo y .docx base),
perfiles de uso, presets de «Qué hacer» (objetivos) y nombres de la interfaz, para que todo el equipo trabaje igual.
Nunca lleva destinos ni secretos, ni reuniones, ni datos de proyectos. Importar fusiona por id: lo del fichero sustituye a lo que
tenga el mismo id; lo demás se queda. app.py llama a montar()."""

import base64
import datetime as dt
import json

from fastapi import APIRouter, HTTPException

import carpetas
import destinos
import exportar
import plantillas
import registro

router = APIRouter()
A = None  # módulo app (montar): _perfiles, PERFILES, _ajustes, AJ_DEF, post_ajustes, pipeline
VERSION = 1


def exportar_equipo():
    est = []
    for e in exportar.estilos():
        fich = {}
        for k in ("logo", "base_docx"):
            if e.get(k) and (exportar._est_dir() / e[k]).is_file():
                fich[k] = {"nombre": e[k], "b64": base64.b64encode((exportar._est_dir() / e[k]).read_bytes()).decode()}
        est.append({**e, "ficheros": fich})
    return {
        "actas_equipo": VERSION,
        "plantillas": list(plantillas.propias().values()),
        "estilos": est,
        "perfiles_uso": A._perfiles(),
        "objetivos": [{"id": i, **v} for i, v in destinos.cfg()["objetivos"].items()],
        "nombres": (A._ajustes() or A.AJ_DEF)["nombres"],
    }


def importar_equipo(d):
    if not isinstance(d, dict) or d.get("actas_equipo") != VERSION:
        raise ValueError("No es un fichero de configuración de equipo de Actas (.actas-equipo.json)")
    n, err = {"plantillas": 0, "estilos": 0, "perfiles_uso": 0, "objetivos": 0}, []
    for t in d.get("plantillas") or []:
        try:
            plantillas.guardar(t, "reemplazar")
            n["plantillas"] += 1
        except (ValueError, PermissionError, TypeError, KeyError) as ex:
            err.append(f"Plantilla «{(t or {}).get('nombre', '?')}»: {ex}")
    for e in d.get("estilos") or []:
        try:
            g = exportar.estilo_guardar({k: v for k, v in e.items() if k not in ("logo", "base_docx", "ficheros")})
            for k, f in (e.get("ficheros") or {}).items():
                if k in ("logo", "base_docx"):
                    exportar.estilo_fichero(g["id"], k, f["nombre"], base64.b64decode(f["b64"]))
            n["estilos"] += 1
        except (ValueError, KeyError, TypeError) as ex:
            err.append(f"Estilo «{(e or {}).get('nombre', '?')}»: {ex}")
    ids = {t["id"] for t in plantillas.todas()}
    ps = {p["id"]: p for p in A._perfiles()}
    for p in d.get("perfiles_uso") or []:
        if isinstance(p, dict) and p.get("id") and p.get("nombre") and any(x in ids for x in p.get("plantillas") or []):
            ps[p["id"]] = {**p, "plantillas": [x for x in p["plantillas"] if x in ids]}
            n["perfiles_uso"] += 1
    if n["perfiles_uso"]:
        A.pipeline.WORK.mkdir(exist_ok=True)
        A.PERFILES.write_text(json.dumps(list(ps.values()), ensure_ascii=False, indent=1), encoding="utf-8")
    with destinos.LOCK:
        cf = destinos.cfg()
        for o in d.get("objetivos") or []:
            try:
                cf["objetivos"][str(o["id"])] = destinos._val_objetivo(o)  # los destinos que aquí no existan quedan «por configurar»
                n["objetivos"] += 1
            except (ValueError, KeyError, TypeError) as ex:
                err.append(f"Preset «{(o or {}).get('nombre', '?')}»: {ex}")
        destinos._escribir(destinos.CFG(), cf)
    if isinstance(d.get("nombres"), dict):
        A.post_ajustes({"nombres": d["nombres"]})
    return {"importado": n, "errores": err}


# ---------- B4: memoria de innovación entre proyectos ----------
INNOV = ("idea", "experimento", "insight", "hipotesis")
PARECIDA = 0.6  # coseno mínimo (embeddings de serie; sin modelo, vocabulario)


def _txt(x):
    return " ".join(filter(None, [x["titulo"], str(x["campos"].get("problema") or ""), x["detalle"]]))


def parecidas(texto, sin=None, n=5):
    """Ideas, experimentos, aprendizajes e hipótesis de TODOS los proyectos que se parecen a `texto` (sin LLM): [{id, codigo, tipo,
    titulo, carpeta, estado, fecha, porque, parecido}] de más a menos parecido."""
    if registro._vacio() or not texto.strip():
        return []
    with registro._db() as db:
        filas = db.execute(
            f"SELECT e.*, p.carpeta AS _c FROM entidad e JOIN proyecto p ON p.id = e.proyecto_id WHERE e.tipo IN ({registro._lista(INNOV)})"
            " AND e.revision NOT IN ('descartado', 'fusionado') AND e.id != ?",
            (sin or "",),
        ).fetchall()
    xs = [(r["_c"], registro._ent(r)) for r in filas]
    if not xs:
        return []
    S = carpetas.sim([texto], [_txt(x) for _, x in xs])[0]
    out = []
    for i in sorted(range(len(xs)), key=lambda i: -S[i])[:n]:
        if S[i] < PARECIDA:
            break
        c, x = xs[i]
        k = x["campos"]
        porque = next((str(k[a]) for a in ("motivo", "aprendizaje", "resultado", "exito") if k.get(a)), "") or x["detalle"]
        out.append(
            {
                **{a: x[a] for a in ("id", "codigo", "tipo", "titulo", "estado")},
                "carpeta": c,
                "fecha": dt.date.fromtimestamp(x["modificado"]).isoformat() if x["modificado"] else "",
                "porque": porque[:300],
                "parecido": round(float(S[i]), 2),
            }
        )
    return out


@router.get("/api/reg/parecidas")
def api_parecidas(texto: str = "", id: str = ""):
    """?id= (una entidad: su texto) o ?texto= (lo que se está escribiendo)."""
    try:
        x = registro.uno(id) if id else None
    except KeyError as ex:
        raise HTTPException(404, str(ex))
    return parecidas(_txt(x) if x else texto, id)


# ---------- B5: informe de portafolio (comité de innovación) ----------
FASES = ("nueva", "en evaluación", "en experimento", "escalada", "descartada")
DECIDIDO = {"terminado", "pivotar", "perseverar", "matar"}


def portafolio():
    """Lo de innovación de todos los proyectos: {fecha, embudo: [[proyecto, n por fase…]], curso, decisiones, aprendizajes} (filas de texto)."""
    if registro._vacio():
        return {"fecha": dt.date.today().isoformat(), "embudo": [], "curso": [], "decisiones": [], "aprendizajes": []}
    with registro._db() as db:
        filas = db.execute(
            f"SELECT e.*, p.carpeta AS _c FROM entidad e JOIN proyecto p ON p.id = e.proyecto_id WHERE e.tipo IN ({registro._lista(INNOV)})"
            " AND e.revision NOT IN ('descartado', 'fusionado') ORDER BY p.carpeta, e.creado"
        ).fetchall()
    xs = [(r["_c"], registro._ent(r)) for r in filas]
    emb, curso, dec, apr = {}, [], [], []
    for c, x in xs:
        k, e = x["campos"], x["estado"] or ""
        motivo = next((str(k[a]) for a in ("motivo", "resultado", "aprendizaje") if k.get(a)), "") or x["detalle"]
        if x["tipo"] == "idea":
            emb.setdefault(c, dict.fromkeys(FASES, 0))[e if e in FASES else "nueva"] += 1
            if e in ("escalada", "descartada"):
                dec.append([c, x["codigo"], x["titulo"], e, motivo[:120]])
        elif x["tipo"] == "experimento":
            (
                dec.append([c, x["codigo"], x["titulo"], e, motivo[:120]])
                if e in DECIDIDO
                else curso.append([c, x["codigo"], x["titulo"], e or "—", str(k.get("metrica") or "")])
            )
        elif x["tipo"] == "insight":
            apr.append(f"{x['titulo']} ({c})")
    return {
        "fecha": dt.date.today().isoformat(),
        "embudo": [[c, *v.values()] for c, v in emb.items()],
        "curso": curso,
        "decisiones": dec,
        "aprendizajes": apr[-15:],
    }


CAB = {
    "embudo": ["Proyecto", "Ideas", "En evaluación", "En experimento", "Escaladas", "Descartadas"],
    "curso": ["Proyecto", "Código", "Experimento", "Estado", "Métrica"],
    "decisiones": ["Proyecto", "Código", "Qué", "Decisión", "Por qué"],
}
TIT = {"embudo": "Embudo por proyecto", "curso": "Experimentos en curso", "decisiones": "Decisiones: escalar, pivotar o matar"}


def portafolio_md(p):
    tab = lambda cab, fs: (
        [" | ".join(cab), " | ".join(["---"] * len(cab))]
        + [" | ".join(str(v).replace("|", "/").replace("\n", " ") for v in f) for f in fs or [["—"] * len(cab)]]
    )
    out = ["# Portafolio de innovación", "", p["fecha"]]
    for s in ("embudo", "curso", "decisiones"):
        out += ["", "## " + TIT[s], ""] + tab(CAB[s], p[s])
    out += ["", "## Aprendizajes clave", ""] + ([f"- {a}" for a in p["aprendizajes"]] or ["—"])
    return "\n".join(out) + "\n"


def portafolio_pptx(p):
    import pptx_min as PM

    sl = [PM.portada("Portafolio de innovación", [p["fecha"], f"{len(p['embudo'])} proyectos con ideas"])]
    sl += [PM.tabla(TIT[s], CAB[s], p[s] or [["—"] * len(CAB[s])]) for s in ("embudo", "curso", "decisiones")]  # ponytail: 14 filas por tabla (pptx_min)
    sl.append(PM.lista("Aprendizajes clave", p["aprendizajes"] or ["—"]))
    return PM.pptx(sl)


@router.get("/api/portafolio")
def api_portafolio(fmt: str = "pptx"):
    from fastapi.responses import Response

    p = portafolio()
    if fmt == "json":
        return p
    if fmt not in ("pptx", "md"):
        raise HTTPException(400, "fmt: pptx | md | json")
    b, mime = (
        (portafolio_pptx(p), "application/vnd.openxmlformats-officedocument.presentationml.presentation")
        if fmt == "pptx"
        else (portafolio_md(p).encode(), "text/markdown; charset=utf-8")
    )
    return Response(b, media_type=mime, headers={"Content-Disposition": f'attachment; filename="portafolio-{p["fecha"]}.{fmt}"'})


@router.get("/api/equipo/exportar")
def api_exportar():
    return exportar_equipo()


@router.post("/api/equipo/importar")
def api_importar(d: dict):
    try:
        return importar_equipo(d)
    except ValueError as ex:
        raise HTTPException(400, str(ex))


def montar(modulo_app, app):
    global A
    A = modulo_app
    for r in router.routes:  # rutas planas, como importar_registro
        app.add_api_route(r.path, r.endpoint, methods=list(r.methods))
