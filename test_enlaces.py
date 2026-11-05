"""Enlaces inteligentes (enlaces.py + app), importar zip en carpeta y «Ya está hecho, no resumir». Servidor http local, sin red ni modelos."""

import contextlib
import http.server
import io
import json
import threading
import time
import zipfile

import pytest

import documentos
import enlaces
import pipeline
import poblar
import registro
from test_documentos import PDF, buscar, cl, esperar, subir  # noqa: F401  (cl es un fixture)

HTML = """<html><head><title>Obra: calendario</title><meta property="og:site_name" content="Diario Obra">
<meta property="article:published_time" content="2026-10-01"><script>var x='NO_SALE';</script><style>.a{}</style></head><body>
<nav>menu NAVEGACION</nav><header>cabecera HEADER</header><div class="side"><p>Enlaces relacionados cortos</p></div>
<article><h1>Obra: calendario</h1><h2>Fachada</h2><p>La fachada se pinta de azul en marzo con andamios alquilados.</p>
<ul><li>Pedir los andamios a la empresa de alquiler</li></ul><table><tr><td>Fase</td><td>Mes</td></tr><tr><td>Pintura</td><td>Marzo</td></tr></table>
<p>El presupuesto de pintura queda aprobado por la propiedad.</p></article><footer>pie FOOTER</footer></body></html>"""


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        r = {"/doc.pdf": ("application/pdf", PDF), "/articulo": ("text/html; charset=utf-8", HTML.encode()), "/grande.pdf": ("application/pdf", PDF * 40)}.get(
            self.path
        )
        if not r:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", r[0])
        self.send_header("Content-Length", str(len(r[1])))
        self.end_headers()
        self.wfile.write(r[1])

    def log_message(self, *a):
        pass


@pytest.fixture
def web():
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


def test_ssrf_y_esquema():
    for u in ("file:///etc/passwd", "ftp://x/y"):
        with pytest.raises(ValueError):
            enlaces.comprobar(u)
    with pytest.raises(ValueError, match="red local"):
        enlaces.comprobar("http://127.0.0.1:1/")
    enlaces.comprobar("http://127.0.0.1:1/", red_local=True)
    assert (
        enlaces.es_microsoft("https://contoso.sharepoint.com/x")
        and enlaces.es_microsoft("https://1drv.ms/u/s!a")
        and not enlaces.es_microsoft("https://example.com/sharepoint.com")
    )


def test_pagina_a_md():
    t, md = enlaces.pagina_a_md(HTML, "https://x.org/a")
    assert t == "Obra: calendario"
    assert all(x not in md for x in ("NO_SALE", "NAVEGACION", "HEADER", "FOOTER", "relacionados"))
    assert "Fuente: https://x.org/a" in md and "Diario Obra" in md and "2026-10-01" in md
    assert "## Fachada" in md and "- Pedir los andamios" in md and "Pintura | Marzo" in md and "presupuesto de pintura" in md


def test_traer(tmp_path, web):
    with pytest.raises(ValueError):
        enlaces.traer(web + "/doc.pdf", tmp_path)  # loopback bloqueado
    k, f = enlaces.traer(web + "/doc.pdf", tmp_path / "a", red_local=True)
    assert (k, f.suffix, f.read_bytes()) == ("fichero", ".pdf", PDF)
    k, f = enlaces.traer(web + "/articulo", tmp_path / "b", red_local=True)
    assert k == "pagina" and f.suffix == ".md" and "calendario" in f.read_text(encoding="utf-8")
    with pytest.raises(RuntimeError, match="demasiado grande"):
        enlaces.traer(web + "/grande.pdf", tmp_path / "c", red_local=True, max_mb=0)
    import urllib.error

    with pytest.raises(urllib.error.HTTPError):
        enlaces.traer(web + "/no", tmp_path / "d", red_local=True)


def test_enlace_job(cl, web):
    t, app = cl
    c = {"buscable": True, "carpeta": "Obra", "gpu": False}
    t.post("/api/generar", json={**c, "enlace": web + "/doc.pdf"})
    for _ in range(300):
        if not any(e["state"] in app.ACTIVOS for e in app.cola):
            break
        time.sleep(0.05)
    assert "red local" in app.cola[-1]["error"]  # por defecto, bloqueado
    t.post("/api/ajustes", json={"enlaces_red_local": True})
    app.cola.clear()
    t.post("/api/generar", json={**c, "enlace": web + "/doc.pdf"})
    t.post("/api/generar", json={**c, "enlace": web + "/articulo"})
    esperar(app)
    ms = {m["label"]: m for m in t.get("/api/meetings").json()}
    assert set(ms) == {"doc.pdf", "Obra calendario.md"} or any("calendario" in k for k in ms), ms.keys()
    assert buscar(t, "presupuesto", c="Obra")["fragmentos"] and buscar(t, "andamios", c="Obra")["fragmentos"]
    mid = next(m["id"] for k, m in ms.items() if "calendario" in k)
    assert json.loads((pipeline.WORK / mid / "meta.json").read_text(encoding="utf-8"))["url"].endswith("/articulo")
    app.cola.clear()
    t.post("/api/generar", json={**c, "enlace": web + "/404"})
    for _ in range(300):
        if not any(e["state"] in app.ACTIVOS for e in app.cola):
            break
        time.sleep(0.05)
    assert "ya no existe" in app.cola[-1]["error"]


def exportado(nombre="Acta"):
    e = io.BytesIO()
    with zipfile.ZipFile(e, "w") as z:
        z.writestr("index.html", "<p>x</p>")
        z.writestr("acta.json", json.dumps({"titulo": nombre, "nivel": "normal"}))
        z.writestr("transcript.json", json.dumps({"segments": [{"s": 0, "e": 5, "text": "Decidimos comprar el servidor"}], "language": "es"}))
    return e.getvalue()


def test_importar_en_carpeta(cl, monkeypatch):
    t, app = cl
    pedidos = []
    monkeypatch.setattr(app, "start", lambda kind, spec, video, mid="": pedidos.append((kind, spec["c"], mid)))
    r = t.post("/api/importar", json={"path": subir(t, "a.zip", exportado()), "carpeta": "Obra"}).json()
    assert next(m for m in t.get("/api/meetings").json() if m["id"] == r["id"])["carpeta"] == "Obra"
    assert pedidos == [("poblar", "Obra", r["id"])]  # carpeta «Proyecto» por defecto: poblar como un documento nuevo
    assert t.post("/api/importar", json={"path": subir(t, "b.zip", exportado("B"))}).json()["id"] and len(pedidos) == 1  # sin carpeta: como siempre


MD = """# Acta de reunión de obra

## Acuerdos
Se decide que la fachada se pinta de azul en marzo.

## Pendientes
Luis enviará el presupuesto de andamios antes del viernes.
Existe el riesgo de que la lluvia retrase la pintura de la fachada.
"""
R = {
    "requisitos": [],
    "interesados": [],
    "preguntas": [],
    "riesgos": [
        {
            "cita": "el riesgo de que la lluvia retrase la pintura",
            "texto": "La lluvia puede retrasar la pintura",
            "probabilidad": "—",
            "impacto": "—",
            "responsable": "—",
        }
    ],
    "decisiones": [{"cita": "Se decide que la fachada se pinta de azul", "texto": "La fachada se pinta de azul en marzo", "decisor": "—"}],
    "tareas": [
        {"cita": "Luis enviará el presupuesto de andamios", "texto": "Luis envía el presupuesto de andamios", "responsable": "Luis", "plazo": "viernes"}
    ],
}


def test_tal_cual(cl, monkeypatch):
    t, app = cl
    monkeypatch.setattr(pipeline, "llama", lambda *a, **k: pytest.fail("tal_cual no usa LLM al generar"))
    pedidos = []
    orig = app.start
    monkeypatch.setattr(app, "start", lambda kind, spec, video, mid="": pedidos.append((kind, spec)) or orig(kind, spec, video, mid))
    chat = lambda sis, user, esq, mx, temperature=0.2: json.loads(json.dumps({k: v for k, v in R.items() if k in esq["properties"]}))
    monkeypatch.setattr(app, "_llm_ctx", lambda d, mids=(), glos=(): lambda: contextlib.nullcontext(chat))
    r = t.post("/api/generar", json={"video": subir(t, "acta_obra.md", MD.encode()), "tal_cual": True, "carpeta": "Obra", "gpu": False})
    assert r.status_code == 200, r.text
    esperar(app)
    j = next(e for e in app.cola if e["kind"] == "acta")
    mid, ver = j["result"]["id"], j["result"]["acta"]
    assert ver.startswith("acta_normal_")
    a = json.loads((pipeline.WORK / mid / ver / "acta.json").read_text(encoding="utf-8"))
    assert a["tal_cual"] and a["resumen"] == "" and any("fachada" in x["texto"] for x in a["relato"])
    assert "Luis enviará" in (pipeline.WORK / mid / ver / "index.html").read_text(encoding="utf-8")
    assert json.loads((pipeline.WORK / mid / "meta.json").read_text(encoding="utf-8"))["tal_cual"] and buscar(t, "andamios", c="Obra")["fragmentos"]
    k, spec = next(p for p in pedidos if p[0] == "poblar")
    assert spec["mid"] == mid and "tareas" in spec["vistas"]
    tipos = {x["tipo"]: x for tipo in ("tarea", "decision", "riesgo") for x in registro.listar("Obra", tipo)}
    assert set(tipos) == {"tarea", "decision", "riesgo"}
    tar = tipos["tarea"]
    assert tar["dueno"] == "Luis" and tar["origen"] == "reunion" and tar["campos"]["plazo"] == "viernes"
    # la cita lleva la loc del documento
    assert documentos.etiqueta(a["locs"])(0).startswith("§")
    assert t.post("/api/generar", json={"video": subir(t, "v.srt", b"x"), "tal_cual": True}).status_code == 400
