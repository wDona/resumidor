"""Servidor MCP (Streamable HTTP, POST /mcp, JSON-RPC 2.0) para que Claude Desktop/Code, Copilot, Cursor u Open WebUI consulten la biblioteca.
Solo desde este equipo y, si está activado, con token Bearer. Herramientas: buscar, preguntar (modelo local), documento, pendientes, proyectos
y encolar (solo con el permiso de Ajustes). Ajustes en work/mcp.json. `python app.py --mcp-stdio` es un puente stdio -> /mcp para clientes sin HTTP.
Para agentes que manejan la app entera (UTCP, con permisos por token): agentes.py."""

import asyncio
import hmac
import json
import secrets
import sys
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

import carpetas
import exportar
import pipeline as P

router = APIRouter()
PROTO = "2025-06-18"
LOCAL = ("127.0.0.1", "::1", "testclient")
A = None  # el módulo app (lo pone app.py: importarlo aquí duplicaría el módulo cuando corre como __main__)
CFG = lambda: P.WORK / "mcp.json"
DEF = {"activo": False, "token_requerido": True, "token": "", "permitir_encolar": False}

TOOLS = [
    {
        "name": "buscar",
        "description": "Busca en todos los documentos (reuniones, audios, PDF, textos, imágenes) y en tareas/decisiones/riesgos. Devuelve fragmentos con título, minuto [mm:ss] o página y el id del documento.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string"},
                "proyecto": {"type": "string", "description": "Proyecto/carpeta (vacío = todos)"},
                "tipo": {"type": "string", "description": "video|audio|pdf|texto|imagen|voz|pantalla|tarea|decision|riesgo…"},
                "limite": {"type": "integer"},
            },
            "required": ["q"],
        },
    },
    {
        "name": "preguntar",
        "description": "Responde con citas a una pregunta sobre un proyecto o un documento, con el modelo local.",
        "inputSchema": {
            "type": "object",
            "properties": {"pregunta": {"type": "string"}, "proyecto": {"type": "string"}, "documento": {"type": "string", "description": "id del documento"}},
            "required": ["pregunta"],
        },
    },
    {
        "name": "documento",
        "description": "Resumen/acta de un documento en Markdown (usa la copia anonimizada si existe).",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    },
    {
        "name": "pendientes",
        "description": "Tareas, decisiones y riesgos abiertos de un proyecto.",
        "inputSchema": {"type": "object", "properties": {"proyecto": {"type": "string"}}, "required": ["proyecto"]},
    },
    {"name": "proyectos", "description": "Lista de proyectos con su número de documentos.", "inputSchema": {"type": "object", "properties": {}}},
    {
        "name": "encolar",
        "description": "Añade archivos (rutas en el equipo de Actas) a la cola. Solo si el usuario lo permite en Ajustes.",
        "inputSchema": {
            "type": "object",
            "properties": {"rutas": {"type": "array", "items": {"type": "string"}}, "proyecto": {"type": "string"}},
            "required": ["rutas"],
        },
    },
]


def cfg():
    try:
        d = json.loads(CFG().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    return {**DEF, **{k: d[k] for k in DEF if k in d}} if isinstance(d, dict) else dict(DEF)


def _guardar(c):
    P.WORK.mkdir(exist_ok=True)
    CFG().write_text(json.dumps(c, indent=1), encoding="utf-8")


def _local(r: Request):
    if (r.client.host if r.client else "") not in LOCAL:
        raise HTTPException(403, "Solo desde este equipo")
    o = r.headers.get("origin")  # un sitio web no puede hablar con el servidor local (DNS rebinding)
    if o and not o.split("//", 1)[-1].split(":")[0].strip("[]") in ("127.0.0.1", "localhost", "::1", "testclient"):
        raise HTTPException(403, "Origen no permitido")


# ---------- herramientas ----------
def _mm(t):
    t = int(t or 0)
    return f"{t // 60:02d}:{t % 60:02d}"


def _sel(proyecto, documento):
    if documento:
        m = next((m for m in A.meetings() if m["id"] == documento), None)
        if not m:
            raise ValueError("Documento no encontrado")
        return m["sel"]
    return "c:" + (proyecto or "")


def t_buscar(a):
    r = A.buscar.buscar(
        A.meetings(), str(a.get("q") or "").strip()[:300], a.get("proyecto") or None, str(a.get("tipo") or ""), max(1, min(int(a.get("limite") or 10), 50))
    )
    out = [
        f"- {f['titulo']} {('p. ' + str(f['loc'])) if f.get('loc') else '[' + _mm(f.get('t')) + ']'} (doc {f['doc']}, proyecto {f['c'] or '-'}): "
        + f["snippet"].replace("<mark>", "«").replace("</mark>", "»")
        for f in r["fragmentos"]
    ]
    out += [f"- [{e.get('tipo')}] {e.get('titulo') or e.get('texto')} (proyecto {e.get('c') or '-'})" for e in r["elementos"]]
    return "\n".join(out) or "Sin resultados."


def t_preguntar(a):
    q = str(a.get("pregunta") or "").strip()
    nube = {"nube": a["nube"]} if a.get("nube") else {}  # MCP nunca la pasa: modelo local; un agente (agentes.py) puede
    resp = A.preguntar({"sel": _sel(a.get("proyecto"), a.get("documento")), "q": q, **nube})
    txt, citas = [], []

    async def leer():
        async for b in resp.body_iterator:
            for ln in (b if isinstance(b, str) else b.decode()).splitlines():
                if ln.strip():
                    yield json.loads(ln)

    async def todo():
        return [e async for e in leer()]

    for e in asyncio.run(todo()):
        k = e.get("k")
        if k == "frase":
            txt.append(e["text"])
            citas.append(f"[{_mm(e['t'])}] {e.get('n', '')}".strip() + (f" ({e['loc']})" if e.get("loc") else ""))
        elif k in ("nada", "error"):
            txt.append(e["text"])
        elif k == "pendientes":
            txt += [e["resp"]] + [f"- {i['texto']} ({i['resp'] or '-'}, {i['plazo'] or 'sin plazo'})" for i in e["items"]]
        elif k == "lista":
            txt.append(json.dumps({x: e[x] for x in e if x not in ("k", "en")}, ensure_ascii=False))
    return "\n".join(txt) + ("\n\nCitas: " + "; ".join(citas) if citas else "")


def t_documento(a):
    wd = P.WORK / Path(str(a.get("id") or "")).name
    vs = sorted((d for d in wd.glob("acta_*_*") if (d / "acta.json").is_file()), key=lambda d: d.stat().st_mtime, reverse=True)
    if not vs:
        raise ValueError("Documento sin resumen/acta")
    return exportar.md(exportar.carga(wd.name, vs[0].name, anon=(vs[0] / "acta_anonima.json").is_file()))


def t_pendientes(a):
    c = str(a.get("proyecto") or "")
    xs = carpetas.listar(c, A._ms(c))["items"]
    return (
        "\n".join(
            f"- [{x['tipo_ent']}] {x['texto']} (resp: {x['resp'] or '-'}, plazo: {x['plazo'] or '-'}{', VENCIDO' if x['vencido'] else ''}; doc {x['mid'] or '-'})"
            for x in xs
        )
        or "Nada abierto."
    )


def t_proyectos(a):
    n = {}
    for m in A.meetings():
        n[m["carpeta"] or ""] = n.get(m["carpeta"] or "", 0) + 1
    for c in A.carpetas_vacias():
        n.setdefault(c, 0)
    return "\n".join(f"- {c or '(sin proyecto)'}: {k} documentos" for c, k in sorted(n.items())) or "Sin proyectos."


def t_encolar(a):
    if not cfg()["permitir_encolar"]:
        raise PermissionError("El usuario no permite añadir archivos desde herramientas externas (Ajustes)")
    rutas = a.get("rutas")
    if not isinstance(rutas, list) or not rutas or not all(isinstance(r, str) for r in rutas):
        raise ValueError("Indica rutas[]")
    r = A._encolar(rutas, str(a.get("proyecto") or "").strip()[:120])
    return f"Encolados: {len(r['ids'])}" + (". Omitidos: " + "; ".join(r["omitidas"][:5]) if r["omitidas"] else "")


FN = {"buscar": t_buscar, "preguntar": t_preguntar, "documento": t_documento, "pendientes": t_pendientes, "proyectos": t_proyectos, "encolar": t_encolar}


def _carpeta_anon(a):
    """True si la carpeta consultada (proyecto, o la del documento) tiene «anonimizar» propio activado."""
    c = a.get("proyecto")
    if c is None and (a.get("documento") or a.get("id")):
        c = A.meta(P.WORK / Path(str(a.get("documento") or a.get("id"))).name).get("carpeta", "")
    return bool(c) and bool(carpetas.leer(str(c))["ajustes"].get("anon"))


def _llamar(p):
    f = FN.get(p.get("name"))
    if not f:
        raise KeyError(p.get("name"))
    if p.get("name") != "encolar" and (
        (A._ajustes() or {}).get("anonimizar_defecto") or _carpeta_anon(p.get("arguments") or {})
    ):  # lo que sale hacia otra herramienta (que puede usar la nube) también es «exportar»
        return {
            "content": [
                {
                    "type": "text",
                    "text": "«Anonimizar por defecto» está activo en Actas: no se entrega contenido a herramientas externas. Desactívalo en Ajustes si quieres usarlas.",
                }
            ],
            "isError": True,
        }
    try:
        return {"content": [{"type": "text", "text": f(p.get("arguments") or {})}]}
    except HTTPException as e:
        t = e.detail if isinstance(e.detail, str) else json.dumps(e.detail, ensure_ascii=False)
    except Exception as e:  # el error de la herramienta va al modelo (isError), no rompe el protocolo
        t = str(e) or e.__class__.__name__
    return {"content": [{"type": "text", "text": t}], "isError": True}


def responder(m):
    """Un mensaje JSON-RPC -> respuesta (dict) o None si era una notificación."""
    if not isinstance(m, dict) or m.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Petición no válida"}}
    i, me, p = m.get("id"), m.get("method"), m.get("params") or {}
    if "id" not in m:
        return None
    ok = lambda r: {"jsonrpc": "2.0", "id": i, "result": r}
    err = lambda c, t: {"jsonrpc": "2.0", "id": i, "error": {"code": c, "message": t}}
    if me == "initialize":
        return ok(
            {
                "protocolVersion": PROTO,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "actas", "version": "1"},
                "instructions": "Biblioteca local de reuniones y documentos: busca, pregunta con citas, lee resúmenes y consulta pendientes.",
            }
        )
    if me == "ping":
        return ok({})
    if me == "tools/list":
        return ok({"tools": _visibles()})
    if me == "tools/call":
        try:
            return ok(_llamar(p))
        except KeyError:
            return err(-32602, f"Herramienta desconocida: {p.get('name')}")
    return err(-32601, f"Método no encontrado: {me}")


def _acceso(r: Request):
    """Solo este equipo, activado en Ajustes y, si se pide, con el token. Devuelve la respuesta 401 o None."""
    _local(r)
    c = cfg()
    if not c["activo"]:
        raise HTTPException(403, "El servidor MCP está desactivado (Ajustes)")
    if c["token_requerido"] and not (
        c["token"] and hmac.compare_digest(r.headers.get("authorization", "").encode(), ("Bearer " + c["token"]).encode())
    ):  # sin token guardado: cerrado, no abierto
        return JSONResponse({"error": "Token no válido"}, 401, {"WWW-Authenticate": "Bearer"})


def _visibles():
    return [t for t in TOOLS if t["name"] != "encolar" or cfg()["permitir_encolar"]]


@router.post("/mcp")
async def mcp(r: Request):
    if no := _acceso(r):
        return no
    try:
        m = json.loads(await r.body())
    except ValueError:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON no válido"}}, 400)
    loop = asyncio.get_running_loop()  # las herramientas son síncronas (LLM, sqlite): fuera del bucle de eventos
    rs = [x for x in await asyncio.gather(*(loop.run_in_executor(None, responder, x) for x in (m if isinstance(m, list) else [m]))) if x]
    if not rs:
        return Response(status_code=202)
    return JSONResponse(rs if isinstance(m, list) else rs[0])


@router.get("/mcp")
def mcp_get():
    return Response(status_code=405, headers={"Allow": "POST"})


# ---------- ajustes y configuración para pegar ----------
def _pub(c):
    return {k: c[k] for k in DEF}


@router.get("/api/mcp/ajustes")
def api_get(r: Request):
    _local(r)
    return _pub(cfg())


@router.post("/api/mcp/ajustes")
def api_post(d: dict, r: Request):
    """{activo?, token_requerido?, permitir_encolar?, regenerar_token?}: el token se genera al activar por primera vez."""
    _local(r)
    c = cfg()
    for k in ("activo", "token_requerido", "permitir_encolar"):
        if isinstance(d.get(k), bool):
            c[k] = d[k]
    if d.get("regenerar_token") or (c["activo"] and c["token_requerido"] and not c["token"]):
        c["token"] = secrets.token_urlsafe(24)
    _guardar(c)
    return _pub(c)


@router.get("/api/mcp/config")
def api_config(r: Request):
    """Fragmentos listos para pegar: claude_desktop (stdio, no necesita token), claude_code (comando) y http (URL + cabecera)."""
    _local(r)
    c = cfg()
    url = f"http://127.0.0.1:{r.url.port or 80}/mcp"
    h = f' --header "Authorization: Bearer {c["token"]}"' if c["token_requerido"] and c["token"] else ""
    app_py = str(Path(getattr(A, "__file__", "app.py")).resolve()) if A else "app.py"
    return {
        "activo": c["activo"],
        "url": url,
        "claude_desktop": json.dumps({"mcpServers": {"actas": {"command": sys.executable, "args": [app_py, "--mcp-stdio"]}}}, indent=2),
        "claude_code": f"claude mcp add --transport http actas {url}{h}",
        "http": {"url": url, "headers": {"Authorization": "Bearer " + c["token"]} if h else {}},
    }


# ---------- puente stdio ----------
def stdio(url, entrada=None, salida=None):
    """Lee líneas JSON-RPC de stdin y las reenvía a la instancia en marcha (url = su base); escribe cada respuesta en una línea."""
    entrada, salida = entrada or sys.stdin, salida or sys.stdout
    c = cfg()
    cab = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        **({"Authorization": "Bearer " + c["token"]} if c["token_requerido"] and c["token"] else {}),
    }
    for ln in entrada:
        if not ln.strip():
            continue
        try:
            with urllib.request.urlopen(urllib.request.Request(url + "/mcp", ln.encode(), cab), timeout=600) as x:
                o = x.read().decode()
        except Exception as e:
            try:
                i = json.loads(ln).get("id")
            except ValueError:
                i = None
            o = json.dumps({"jsonrpc": "2.0", "id": i, "error": {"code": -32000, "message": f"Actas no responde: {e}"}}) if i is not None else ""
        if o.strip():
            salida.write(o.strip().replace("\n", " ") + "\n")
            salida.flush()
