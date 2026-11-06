"""Agentes que usan Actas en nombre de un usuario (docs/plan-agentes.md), en el escritorio y en el servidor de equipo.

- Tokens `agt_<id>_<secreto>` con nombre y permisos (leer, escribir, ia, borrar), en WORK/agentes.json (solo el hash del secreto).
- Un token de agente solo llega a las operaciones de OPS y con su permiso; lo demás, 403. Lo que hace queda en el historial como
  «Ana (agente: Investigación)».
- GET /utcp: manual UTCP 1.0 con las operaciones que ese token puede usar; el agente llama a la API real.
- Envoltorios en texto donde la API no sirve tal cual a un agente: documentos de un proyecto, acta en Markdown y «preguntar» (que en
  la interfaz es un flujo NDJSON).
app.py llama a montar() después de servidor.montar() (este filtro va por fuera: corre antes)."""

import hashlib
import hmac
import json
import re
import secrets
import threading
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

import pipeline as P
import registro
import servidor

router = APIRouter()
LOCK = threading.Lock()
PERMISOS = ("leer", "escribir", "ia", "borrar")
A = None  # el módulo app (lo pone app.py)
M = None  # mcp_servidor (reutiliza sus herramientas en texto)

S, I, B, N = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}, {"type": "object"}
C = {"type": "string", "description": "Nombre del proyecto"}
NUBE = {
    "type": "object",
    "description": "Modelo en la nube, p. ej. {proveedor: 'anthropic', modelo: '…'} (ver operación «nube»). En el servidor es obligatorio.",
}


def _o(props, req=()):
    return {"type": "object", "properties": props, "required": list(req)}


# (nombre, método, ruta, permiso, descripción, parámetros de ruta/URL, cuerpo JSON o None)
OPS = [
    ("proyectos", "GET", "/api/carpetas", "leer", "Lista de nombres de proyecto.", {}, None),
    ("proyecto", "GET", "/api/exp", "leer", "Ficha del proyecto: tipo, datos, ajustes, glosario y contadores.", {"c": C}, None),
    (
        "documentos",
        "GET",
        "/api/agente/documentos",
        "leer",
        "Documentos de un proyecto: id, nombre, tipo de origen, fecha y si tienen acta/resumen.",
        {"c": C},
        None,
    ),
    ("documento", "GET", "/api/agente/documento/{mid}", "leer", "Acta o resumen de un documento, en Markdown.", {"mid": S}, None),
    (
        "fuente",
        "GET",
        "/api/fuente/{mid}",
        "leer",
        "Texto original de un documento por página o sección: [{loc ('p. 12', '§ Título'…), t, texto}]. Para citar con precisión.",
        {"mid": S},
        None,
    ),
    (
        "buscar",
        "GET",
        "/api/buscar",
        "leer",
        "Busca en documentos y elementos. tipo: pdf|texto|imagen|video|audio o un tipo de elemento (tarea, insight, riesgo…).",
        {"q": S, "c": C, "tipo": S, "limit": I},
        None,
    ),
    (
        "pendientes",
        "GET",
        "/api/exp/pendientes",
        "leer",
        "Tareas, decisiones y riesgos de un proyecto. estado: abierto|hecho|todos.",
        {"c": C, "estado": S},
        None,
    ),
    (
        "elementos",
        "GET",
        "/api/reg",
        "leer",
        "Elementos del registro (tarea, decision, riesgo, requisito, pregunta, hipotesis, insight, idea…) con sus citas.",
        {"c": C, "tipo": S, "estado": S, "q": S, "revision": {"type": "string", "description": "propuesto|aprobado|descartado"}},
        None,
    ),
    ("historial", "GET", "/api/reg/{eid}/historial", "leer", "Cambios de un elemento, con autor.", {"eid": S, "c": C}, None),
    ("informes", "GET", "/api/reg/informes", "leer", "Informes del proyecto.", {"c": C}, None),
    ("informe", "GET", "/api/reg/informes/{iid}", "leer", "Un informe con su contenido.", {"iid": I, "c": C}, None),
    (
        "exportar_informe",
        "GET",
        "/api/reg/informes/{iid}/exportar",
        "leer",
        "Descarga el informe. fmt: md|json|docx|pdf|pptx|xlsx (md y json, en texto).",
        {"iid": I, "c": C, "fmt": S, "borrador": I},
        None,
    ),
    (
        "cola",
        "GET",
        "/api/cola",
        "leer",
        "Trabajos: {n: cuántos quedan, items: [{id, state: pendiente|marcha|hecho|error|cancelado, frac, msg, error}]}. Espera a n = 0.",
        {},
        None,
    ),
    ("enlaces", "GET", "/api/enlaces", "leer", "Enlaces del proyecto (repositorio, Jira, carpeta compartida, propios).", {"c": C}, None),
    ("destinos", "GET", "/api/destinos", "leer", "Destinos configurados (Jira, Planner, GitHub…) para «enviar».", {}, None),
    ("nube", "GET", "/api/nube", "leer", "Proveedores de IA en la nube configurados y sus modelos.", {}, None),
    ("perfiles", "GET", "/api/plantillas", "leer", "Perfiles de resumen (acta de reunión, entrevista, informe…).", {}, None),
    ("crear_proyecto", "POST", "/api/carpeta", "escribir", "Crea un proyecto.", {}, _o({"nuevo": C}, ["nuevo"])),
    (
        "datos_proyecto",
        "POST",
        "/api/exp/datos",
        "escribir",
        "Tipo y datos clave del proyecto (sustituye la lista).",
        {},
        _o({"c": C, "tipo": S, "datos": {"type": "array", "items": _o({"k": S, "v": S})}}, ["c"]),
    ),
    (
        "subir",
        "POST",
        "/api/subir",
        "escribir",
        "Añade un documento al proyecto (fichero en base64). Sin resumir: se lee e indexa sin IA. resumir=true hace además el resumen"
        " (permiso ia; en el servidor, con nube). Devuelve el id del trabajo: consúltalo en «cola».",
        {},
        _o({"c": C, "nombre": S, "base64": S, "resumir": B, "perfil": S, "nube": NUBE}, ["c", "nombre", "base64"]),
    ),
    (
        "encolar",
        "POST",
        "/api/encolar",
        "escribir",
        "Solo escritorio: añade ficheros o carpetas de este equipo por su ruta.",
        {},
        _o({"rutas": {"type": "array", "items": S}, "c": C, "recursivo": B}, ["rutas"]),
    ),
    (
        "crear_elemento",
        "POST",
        "/api/reg",
        "escribir",
        "Crea un elemento ya aprobado: tipo tarea|decision|riesgo|requisito|pregunta|hipotesis|insight|idea|supuesto|…",
        {},
        _o({"c": C, "tipo": S, "titulo": S, "detalle": S, "estado": S, "dueno": S, "prioridad": S, "fecha_limite": S, "campos": N}, ["c", "tipo", "titulo"]),
    ),
    (
        "editar_elemento",
        "PATCH",
        "/api/reg/{eid}",
        "escribir",
        "Cambia campos de un elemento: cambios = {titulo, detalle, estado, dueno, prioridad, fecha_limite, campos}.",
        {"eid": S},
        _o({"c": C, "cambios": N}, ["c", "cambios"]),
    ),
    (
        "revisar",
        "POST",
        "/api/reg/revisar",
        "escribir",
        "Aprueba, descarta o restaura propuestas de la IA.",
        {},
        _o({"c": C, "ids": {"type": "array", "items": S}, "accion": {"type": "string", "enum": ["aprobar", "descartar", "restaurar"]}}, ["c", "ids", "accion"]),
    ),
    (
        "relacionar",
        "POST",
        "/api/reg/relacion",
        "escribir",
        "Relaciona dos elementos. tipo: deriva_de|sustituye|bloquea|mitiga|afecta|responde|solicita.",
        {},
        _o({"c": C, "a": S, "b": S, "tipo": S}, ["c", "a", "b", "tipo"]),
    ),
    (
        "crear_informe",
        "POST",
        "/api/reg/informes",
        "escribir",
        "Borrador de informe del periodo (por defecto, desde el último informe).",
        {},
        _o({"c": C, "titulo": S, "desde": S, "hasta": S}, ["c"]),
    ),
    (
        "editar_informe",
        "PATCH",
        "/api/reg/informes/{iid}",
        "escribir",
        "Cambia un informe: cambios = {titulo, desde, hasta, estado, notas, narrativa}.",
        {"iid": I},
        _o({"c": C, "cambios": N}, ["c", "cambios"]),
    ),
    (
        "guardar_enlaces",
        "POST",
        "/api/enlaces",
        "escribir",
        "Sustituye los enlaces propios del proyecto.",
        {},
        _o({"c": C, "enlaces": {"type": "array", "items": _o({"nombre": S, "url": S})}}, ["c", "enlaces"]),
    ),
    (
        "enviar",
        "POST",
        "/api/enviar",
        "escribir",
        "Envía a un destino configurado. que: documento|resumen|tareas|decisiones|requisitos|historias|riesgos|interesados|informe.",
        {},
        _o({"c": C, "destino": S, "que": {"type": "array", "items": S}, "doc": S, "ids": {"type": "array", "items": S}}, ["destino", "que"]),
    ),
    (
        "preguntar",
        "POST",
        "/api/agente/preguntar",
        "ia",
        "Responde con citas a una pregunta sobre un proyecto o un documento.",
        {},
        _o({"pregunta": S, "c": C, "documento": S, "nube": NUBE}, ["pregunta"]),
    ),
    (
        "extraer",
        "POST",
        "/api/reg/poblar",
        "ia",
        "Encola la extracción con IA de elementos (requisitos, decisiones, riesgos, interesados, preguntas) de los documentos; quedan como"
        " propuestas para «revisar».",
        {},
        _o({"c": C, "mid": S, "vistas": {"type": "array", "items": S}, "nube": NUBE}, ["c"]),
    ),
    (
        "redactar_informe",
        "POST",
        "/api/reg/informes/{iid}/redactar",
        "ia",
        "Encola la redacción con IA de la narrativa del informe.",
        {"iid": I},
        _o({"c": C, "nube": NUBE}, ["c"]),
    ),
    (
        "guia_investigacion",
        "GET",
        "/api/investigaciones/guia",
        "leer",
        "Guía opcional para redactar una investigación (estructura y estilo compacto). Úsala si el usuario no pide otro formato.",
        {},
        None,
    ),
    ("investigaciones", "GET", "/api/investigaciones", "leer", "Investigaciones del proyecto (id, título, autor, fecha).", {"c": C}, None),
    (
        "investigacion",
        "GET",
        "/api/investigaciones/{iid}",
        "leer",
        "Una investigación. fmt: json (con el Markdown) | md | docx (Word con el estilo del proyecto).",
        {"iid": S, "c": C, "fmt": S},
        None,
    ),
    (
        "guardar_investigacion",
        "POST",
        "/api/investigaciones",
        "escribir",
        "Guarda una investigación en Markdown (con id, la sustituye). Se exporta a .md o .docx con «investigacion».",
        {},
        _o({"c": C, "markdown": S, "titulo": S, "id": S}, ["c", "markdown"]),
    ),
    ("borrar_investigacion", "DELETE", "/api/investigaciones/{iid}", "borrar", "Borra una investigación.", {"iid": S, "c": C}, None),
    ("borrar_elemento", "DELETE", "/api/reg/{eid}", "borrar", "Borra un elemento.", {"eid": S, "c": C}, None),
    ("borrar_informe", "DELETE", "/api/reg/informes/{iid}", "borrar", "Borra una versión de un informe.", {"iid": I, "c": C}, None),
]
_RX = [(o, re.compile("^" + re.sub(r"\{\w+\}", r"[^/]+", o[2]) + "$")) for o in OPS]
SOLO_ESCRITORIO = {"encolar"}


def _f():
    return P.WORK / "agentes.json"


def _leer():
    try:
        d = json.loads(_f().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _escribir(d):
    P.WORK.mkdir(parents=True, exist_ok=True)
    tmp = _f().with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_f())


def _sha(t):
    return hashlib.sha256(t.encode()).hexdigest()


def crear(usuario, nombre, permisos):
    nombre = str(nombre or "").strip()[:60]
    if not nombre:
        raise ValueError("Ponle un nombre al agente")
    ps = [p for p in PERMISOS if p in (permisos or [])]
    if not ps:
        raise ValueError("Elige al menos un permiso")
    i, sec = secrets.token_hex(6), secrets.token_urlsafe(32)
    with LOCK:
        d = _leer()
        d[i] = {"nombre": nombre, "usuario": usuario or "", "hash": _sha(sec), "permisos": ps, "creado": int(time.time()), "usado": 0}
        _escribir(d)
    return f"agt_{i}_{sec}", i


def listar(usuario=None):
    return [
        {"id": i, **{k: x[k] for k in ("nombre", "usuario", "permisos", "creado", "usado")}}
        for i, x in sorted(_leer().items(), key=lambda kv: kv[1]["creado"])
        if usuario is None or x["usuario"] == usuario
    ]


def borrar(i, usuario=None):
    with LOCK:
        d = _leer()
        if i in d and (usuario is None or d[i]["usuario"] == usuario):
            d.pop(i)
            _escribir(d)


def verificar(cabecera):
    """'Bearer agt_…' -> (id, datos) o None."""
    m = re.fullmatch(r"(?i:bearer)\s+agt_([0-9a-f]{12})_(\S+)", (cabecera or "").strip())
    if not m:
        return None
    x = _leer().get(m[1])
    if not x or not hmac.compare_digest(x["hash"], _sha(m[2])):
        return None
    if servidor.ACTIVO and x["usuario"] not in servidor.usuarios():
        return None  # el usuario se borró: sus agentes también
    if time.time() - x.get("usado", 0) > 60:  # no escribir en cada petición
        with LOCK:
            d = _leer()
            if m[1] in d:
                d[m[1]]["usado"] = int(time.time())
                _escribir(d)
    return m[1], x


def op_de(metodo, ruta):
    return next((o for o, rx in _RX if o[1] == metodo and rx.match(ruta)), None)


def permisos(request):
    """Permisos del agente de la petición, o None si no la hace un agente."""
    return request.scope.get("actas_permisos")


async def filtro(request: Request, call_next):
    a = request.headers.get("authorization", "")
    if not re.match(r"(?i:bearer)\s+agt_", a):
        return await call_next(request)
    v = verificar(a)
    if not v:
        return JSONResponse({"detail": "Token de agente no válido"}, 401, {"WWW-Authenticate": "Bearer"})
    i, x = v
    p = request.url.path
    if not (request.method == "GET" and p == "/utcp"):
        o = op_de(request.method, p)
        if not o or (servidor.ACTIVO and o[0] in SOLO_ESCRITORIO):
            return JSONResponse({"detail": "Esta operación no está disponible para agentes"}, 403)
        if o[3] not in x["permisos"]:
            return JSONResponse({"detail": f"Este agente no tiene el permiso «{o[3]}»"}, 403)
    quien = x["usuario"] or registro.autor() or "Usuario"
    request.scope["actas_agente"] = f"{quien} (agente: {x['nombre']})"
    request.scope["actas_permisos"] = x["permisos"]
    tok = registro.USUARIO.set(request.scope["actas_agente"])
    try:
        return await call_next(request)
    finally:
        registro.USUARIO.reset(tok)


# ---------- gestión (personas, nunca un agente: estas rutas no están en OPS) ----------
def _dueno(request):
    """En el servidor, el usuario de la sesión; en el escritorio, todos los agentes son del equipo (None = sin filtrar)."""
    if not servidor.ACTIVO:
        return None
    n = servidor.quien(request)
    if not n:
        raise HTTPException(401, "Inicia sesión")
    return n


@router.get("/api/agentes")
def api_listar(request: Request):
    return listar(_dueno(request))


@router.post("/api/agentes")
def api_crear(d: dict, request: Request):
    """{nombre, permisos: [leer, escribir, ia, borrar]} -> {token (solo esta vez), manual, agentes}."""
    u = _dueno(request)
    try:
        tok, _ = crear(u if u is not None else "", d.get("nombre"), d.get("permisos"))
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    return {"token": tok, "manual": _base(request) + "/utcp", "agentes": listar(u)}


@router.post("/api/agentes/borrar")
def api_borrar(d: dict, request: Request):
    u = _dueno(request)
    borrar(str(d.get("id") or ""), u)
    return listar(u)


# ---------- manual UTCP ----------
def _base(request):
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{proto}://{request.headers.get('host') or request.url.netloc}"


def manual(base, permisos_):
    auth = {"auth_type": "api_key", "api_key": "Bearer ${TOKEN}", "var_name": "Authorization", "location": "header"}
    tools = []
    for nombre, met, ruta, perm, desc, params, cuerpo in OPS:
        if perm not in permisos_ or (servidor.ACTIVO and nombre in SOLO_ESCRITORIO):
            continue
        en_ruta = re.findall(r"\{(\w+)\}", ruta)
        props = dict(params)
        if cuerpo:
            props["body"] = cuerpo
        req = en_ruta + (["body"] if cuerpo else []) + (["c"] if "c" in params and nombre != "buscar" else [])
        tpl = {"name": "actas", "call_template_type": "http", "url": base + ruta, "http_method": met, "content_type": "application/json", "auth": auth}
        if cuerpo:
            tpl["body_field"] = "body"
        tools.append(
            {
                "name": nombre,
                "description": desc,
                "inputs": {"type": "object", "properties": props, "required": req},
                "outputs": {},
                "tags": ["actas", perm],
                "tool_call_template": tpl,
            }
        )
    return {"utcp_version": "1.0.1", "manual_version": "1.0.0", "tools": tools}


@router.get("/utcp")
def api_manual(request: Request):
    """Manual UTCP del token que lo pide (solo con token de agente: así enseña lo que ese agente puede hacer)."""
    ps = permisos(request)
    if ps is None:
        raise HTTPException(401, "Pide el manual con el token del agente (Authorization: Bearer agt_…)")
    return manual(_base(request), ps)


# ---------- envoltorios en texto ----------
@router.get("/api/agente/documentos")
def api_documentos(c: str):
    c = A._c({"c": c})
    return [{k: m.get(k) for k in ("id", "nombre", "label", "mtime", "actas", "dur")} for m in A.meetings() if (m.get("carpeta") or "") == c]


@router.get("/api/agente/documento/{mid}", response_class=PlainTextResponse)
def api_documento(mid: str):
    try:
        return M.t_documento({"id": mid})
    except ValueError as ex:
        raise HTTPException(404, str(ex))


@router.post("/api/agente/preguntar", response_class=PlainTextResponse)
def api_preguntar(d: dict):
    if servidor.ACTIVO and not d.get("nube"):
        raise HTTPException(400, "En el servidor indica «nube» (operación «nube» para ver los proveedores)")
    try:
        return M.t_preguntar({"pregunta": d.get("pregunta"), "proyecto": d.get("c"), "documento": d.get("documento"), "nube": d.get("nube")})
    except ValueError as ex:
        raise HTTPException(400, str(ex))


def montar(app):
    app.middleware("http")(filtro)  # añadido después del de servidor.py: corre antes
    for r in router.routes:
        app.router.routes.insert(0, r)
