"""Configuración de equipo (docs/plan-equipos.md, A6): un .actas-equipo.json con plantillas propias, estilos (con logo y .docx base),
perfiles de uso, presets de «Qué hacer» (objetivos) y nombres de la interfaz, para que todo el equipo trabaje igual.
Nunca lleva destinos ni secretos, ni reuniones, ni datos de proyectos. Importar fusiona por id: lo del fichero sustituye a lo que
tenga el mismo id; lo demás se queda. app.py llama a montar()."""

import base64
import json

from fastapi import APIRouter, HTTPException

import destinos
import exportar
import plantillas

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
