"""Agentes con token y permisos (docs/plan-agentes.md): manual UTCP, operaciones permitidas, autoría, subir documentos. Sin LLM."""

import base64

import agentes
import servidor
from test_carpetas import C, cl  # noqa: F401
from test_servidor import entrar, sv  # noqa: F401


def _tok(t, permisos, nombre="Investigación"):
    r = t.post("/api/agentes", json={"nombre": nombre, "permisos": permisos})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_permisos_y_manual(cl):
    t, _ = cl
    t.post("/api/ajustes", json={"yo": {"nombre": "Ana", "correo": ""}})
    lee = _tok(t, ["leer"])
    m = t.get("/utcp", headers=lee).json()
    nombres = {x["name"] for x in m["tools"]}
    assert {"proyectos", "buscar", "fuente", "documentos"} <= nombres and not nombres & {"crear_elemento", "preguntar", "borrar_elemento"}
    b = next(x for x in m["tools"] if x["name"] == "fuente")
    assert b["tool_call_template"]["url"].endswith("/api/fuente/{mid}") and b["inputs"]["required"] == ["mid"]
    assert "agt_" not in str(m)
    assert C in t.get("/api/carpetas", headers=lee).json()
    assert [d["id"] for d in t.get("/api/agente/documentos", params={"c": C}, headers=lee).json()]
    assert t.post("/api/reg", json={"c": C, "tipo": "insight", "titulo": "x"}, headers=lee).status_code == 403  # sin «escribir»
    assert t.get("/api/ajustes", headers=lee).status_code == 403  # fuera de la lista
    assert t.post("/api/agentes", json={"nombre": "x", "permisos": ["borrar"]}, headers=lee).status_code == 403  # no se da permisos
    assert t.get("/api/carpetas", headers={"Authorization": "Bearer agt_000000000000_x"}).status_code == 401
    assert t.get("/utcp").status_code == 401  # el manual depende del token

    esc = _tok(t, ["leer", "escribir"], "Síntesis")
    x = t.post("/api/reg", json={"c": C, "tipo": "insight", "titulo": "Los vecinos piden más transparencia"}, headers=esc).json()
    h = t.get(f"/api/reg/{x['id']}/historial", params={"c": C}, headers=esc).json()
    assert h[-1]["autor"] == "Ana (agente: Síntesis)"
    assert t.delete(f"/api/reg/{x['id']}", params={"c": C}, headers=esc).status_code == 403
    assert "Investigación" in str(t.get("/api/agentes").json())
    i = next(a["id"] for a in t.get("/api/agentes").json() if a["nombre"] == "Síntesis")
    t.post("/api/agentes/borrar", json={"id": i})
    assert t.get("/api/carpetas", headers=esc).status_code == 401  # revocado


def test_subir_documento(cl, monkeypatch):
    t, app = cl
    lanzados = []
    monkeypatch.setattr(app, "start", lambda kind, spec, video, mid="": lanzados.append(spec) or {"id": "j1"})
    esc = _tok(t, ["leer", "escribir"])
    b64 = base64.b64encode("# Entrevista 1\n\nEl portal no se entiende.".encode()).decode()
    r = t.post("/api/subir", json={"c": C, "nombre": "../entrevista-1.md", "base64": b64}, headers=esc)
    assert r.json() == {"id": "j1"} and lanzados[0]["buscable"] and lanzados[0]["carpeta"] == C
    assert lanzados[0]["transcripcion"].endswith("entrevista-1.md") and "subidas" in lanzados[0]["transcripcion"]
    assert t.post("/api/subir", json={"c": C, "nombre": "a.md", "base64": b64, "resumir": True}, headers=esc).status_code == 403  # sin «ia»
    assert t.post("/api/subir", json={"c": C, "nombre": "a.exe", "base64": b64}, headers=esc).status_code == 400
    assert t.post("/api/subir", json={"c": C, "nombre": "a.md", "base64": "no es base64!"}, headers=esc).status_code == 400


def test_agentes_en_el_servidor(sv, monkeypatch):
    t, app = sv
    monkeypatch.setattr(app, "start", lambda kind, spec, video, mid="": {"id": "j1"})
    entrar(t, "Luis", "clave-de-luis-1")
    h = _tok(t, ["leer", "escribir"])
    t.cookies.clear()
    m = t.get("/utcp", headers=h).json()
    assert "encolar" not in {x["name"] for x in m["tools"]}  # rutas del disco: solo escritorio
    assert t.post("/api/encolar", json={"rutas": ["/etc"]}, headers=h).status_code == 403
    assert t.post("/api/reg", json={"c": C, "tipo": "insight", "titulo": "Desde el servidor"}, headers=h).status_code == 200
    b64 = base64.b64encode(b"hola").decode()
    assert t.post("/api/subir", json={"c": C, "nombre": "notas.txt", "base64": b64}, headers=h).status_code == 200
    assert t.post("/api/subir", json={"c": C, "nombre": "foto.png", "base64": b64}, headers=h).status_code == 400  # imagen sin nube
    assert t.post("/api/agente/preguntar", json={"pregunta": "¿qué?"}, headers=h).status_code == 403  # sin «ia»
    entrar(t, "Ana", "clave-de-ana-1")
    assert t.get("/api/agentes").json() == []  # cada uno ve los suyos
    assert t.post("/api/subir", json={"c": C, "nombre": "a.md", "base64": b64}).status_code == 200  # subir a mano desde la web
    assert t.post("/api/subir", json={"c": C, "nombre": "a.md", "base64": b64, "tal_cual": True}).status_code == 409  # extraer pide nube
    plan = {"salidas": [{"que": "decisiones"}, {"que": "tareas"}, {"que": "documento"}]}
    assert app._pedidas({"plan": plan}, False) == ["decisiones"] and app._pedidas({"plan": plan}, True) == ["decisiones", "tareas"]
    assert app._pedidas({}, False) is None and app._pedidas({"plan": {"salidas": [{"que": "informe"}]}}, True) == []
    t.post("/api/usuarios/borrar", json={"nombre": "Luis"})
    t.cookies.clear()
    assert t.get("/api/carpetas", headers=h).status_code == 401  # sin su usuario, sus agentes tampoco
    servidor.ia_local(None, sin_llm=True)  # leer e indexar no usa LLM: permitido en el servidor
    assert agentes.op_de("GET", "/api/fuente/abc")[0] == "fuente" and agentes.op_de("POST", "/api/fuente/abc") is None


MD = """# Guía de ahorro de tokens

El coste de la computación sube: se investiga cómo usar la IA por menos.

## Formas de resolverlo
**Mantén conversaciones limpias:** más contexto no es mejor; usa `/clear`.

- Comprimir la salida de shell
  - con [rtk](https://github.com/rtk-ai/rtk)
1. Primero esto

## Soluciones exploradas
| Nombre | Link | Resumen |
|---|---|---|
| rtk | https://github.com/rtk-ai/rtk | Filtra la salida *de shell* |

> Los ahorros son declarados por los autores.
"""


def test_investigaciones(cl):
    import io

    from docx import Document

    t, _ = cl
    h = _tok(t, ["leer", "escribir"])
    assert "Formas de resolverlo" in t.get("/api/investigaciones/guia", headers=h).text
    x = t.post("/api/investigaciones", json={"c": C, "markdown": MD}, headers=h).json()
    assert x["titulo"] == "Guía de ahorro de tokens" and x["autor"].endswith("(agente: Investigación)")
    assert [i["id"] for i in t.get("/api/investigaciones", params={"c": C}, headers=h).json()] == [x["id"]]
    assert t.get(f"/api/investigaciones/{x['id']}", params={"c": C, "fmt": "md"}, headers=h).text == MD.strip()
    r = t.get(f"/api/investigaciones/{x['id']}", params={"c": C, "fmt": "docx"}, headers=h)
    assert r.status_code == 200 and ".docx" in r.headers["content-disposition"]
    d = Document(io.BytesIO(r.content))
    ps = {p.text: p for p in d.paragraphs}
    assert ps["Guía de ahorro de tokens"].style.name == "Title" and ps["Formas de resolverlo"].style.name == "Heading 1"
    p = next(p for p in d.paragraphs if p.text.startswith("Mantén"))
    assert p.runs[0].bold and "**" not in p.text and "`" not in p.text
    assert next(p for p in d.paragraphs if "Comprimir" in p.text).style.name == "List Bullet"
    assert any(p.style.name == "List Bullet 2" for p in d.paragraphs) and any(p.style.name == "List Number" for p in d.paragraphs)
    tb = d.tables[0]
    assert [c.text for c in tb.rows[0].cells] == ["Nombre", "Link", "Resumen"] and tb.rows[1].cells[2].text == "Filtra la salida de shell"
    assert "github.com/rtk-ai/rtk" in str([r.target_ref for r in d.part.rels.values()])  # enlace de verdad
    assert t.delete(f"/api/investigaciones/{x['id']}", params={"c": C}, headers=h).status_code == 403  # sin «borrar»
    x2 = t.post("/api/investigaciones", json={"c": C, "markdown": "# Otra\n\nTexto", "id": x["id"]}, headers=h).json()
    assert x2["id"] == x["id"] and x2["titulo"] == "Otra"
    assert t.post("/api/investigaciones", json={"c": C, "markdown": "  "}, headers=h).status_code == 400
