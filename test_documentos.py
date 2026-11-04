"""Ingesta de documentos (PDF, Markdown, TXT, DOCX, HTML, imagen), modo «solo buscable», lote .zip, /api/buscar y descripción de
imágenes con IA (vision.py). Sin red ni modelos: el OCR y la llamada de visión se sustituyen."""
import io
import shutil
import time
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import documentos
import nube
import pipeline
import registro
import vision


def pdf(pages):
    """PDF mínimo (Helvetica, una línea por página; "" = página sin capa de texto, como una escaneada)."""
    objs, kids = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"], []
    for t in pages:
        s = f"BT /F1 12 Tf 72 720 Td ({t}) Tj ET" if t else ""
        objs.append(f"<< /Length {len(s)} >>\nstream\n{s}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {len(objs)} 0 R >>")
        kids.append(len(objs))
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    x = len(out)
    return out + (f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offs)
                  + f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF").encode()


PDF = pdf(["Primera pagina: el presupuesto anual sube un diez por ciento.", "Segunda pagina: el servidor nuevo se compra en enero.", ""])


def png():
    b = io.BytesIO()
    Image.new("RGB", (64, 48), "white").save(b, "PNG")
    return b.getvalue()


@pytest.fixture
def cl(tmp_path, monkeypatch):
    w = tmp_path / "work"
    w.mkdir()
    monkeypatch.setenv("ACTAS_CPU", "1")
    monkeypatch.setattr(pipeline, "WORK", w)
    import app
    for k, v in {"UPLOADS": tmp_path / "uploads", "CARPETAS": w / "carpetas.json", "AJUSTES": w / "ajustes.json", "COLA": w / "cola.json"}.items():
        monkeypatch.setattr(app, k, v)
    monkeypatch.setattr(documentos, "ocr", lambda im: ["TEXTO LEIDO POR OCR"])
    monkeypatch.setattr(vision, "_local", lambda: None)  # sin modelo de visión instalado
    app.cola.clear()
    return TestClient(app.app), app


def subir(t, nombre, datos):
    return t.put("/api/upload", params={"name": nombre}, content=datos).json()["path"]


def esperar(app, s=60):
    fin = time.time() + s
    while any(e["state"] in app.ACTIVOS for e in app.cola):
        assert time.time() < fin, "la cola no termina"
        time.sleep(0.05)
    assert all(e["state"] == "hecho" for e in app.cola), [e.get("error") for e in app.cola]


def buscar(t, q, **p):
    return t.get("/api/buscar", params={"q": q, **p}).json()


def test_formatos(tmp_path, monkeypatch):
    monkeypatch.setattr(documentos, "ocr", lambda im: ["Texto escaneado"])
    (tmp_path / "a.pdf").write_bytes(PDF)
    r = documentos.leer(tmp_path / "a.pdf")
    assert [s["loc"] for s in r["segments"]] == ["p. 1", "p. 2", "p. 3"] and r["importada"]["ocr"] == [3] and r["importada"]["tipo"] == "pdf"
    st = [s["s"] for s in r["segments"]]
    assert all(isinstance(x, int) for x in st) and st == sorted(set(st))  # inicios enteros y distintos: la marca lleva a su trozo
    lab = documentos.etiqueta(documentos.locs(r["segments"]))
    assert [lab(s["s"]) for s in r["segments"]] == ["p. 1", "p. 2", "p. 3"] and documentos.etiqueta(None)(65) == "01:05"
    (tmp_path / "b.md").write_text("Intro.\n\n# Diseño\n\nTexto **clave** con [enlace](http://x).\n\n## API\n\n- uno\n\n```\n# no es título\n```\n", encoding="utf-8")
    assert [(s["loc"], s["text"]) for s in documentos.leer(tmp_path / "b.md")["segments"]] == [
        ("§ Inicio", "Intro."), ("§ Diseño", "Diseño. Texto clave con enlace."), ("§ Diseño › API", "API. uno # no es título")]
    (tmp_path / "t.md").write_text("# Comisión de obras\n\nAsisten tres.\n\n## Presupuesto\n\nSe aprueba.\n\n## Calendario\n\nEn enero.", encoding="utf-8")
    assert [s["loc"] for s in documentos.leer(tmp_path / "t.md")["segments"]] == ["§ Comisión de obras", "§ Presupuesto", "§ Calendario"]  # título raíz único: no se repite
    (tmp_path / "c.html").write_text("<html><head><title>T</title><script>x()</script></head><body><h1>Hola</h1><p>Uno &amp; dos</p></body></html>", encoding="utf-8")
    assert [(s["loc"], s["text"]) for s in documentos.leer(tmp_path / "c.html")["segments"]] == [("§ Hola", "Hola. Uno & dos")]
    (tmp_path / "d.txt").write_text("Párrafo uno.\n\nPárrafo dos.", encoding="utf-8")
    assert [s["loc"] for s in documentos.leer(tmp_path / "d.txt")["segments"]] == ["¶ 1", "¶ 2"]
    import docx
    doc = docx.Document()
    doc.add_heading("Capítulo", 1)
    doc.add_paragraph("Contenido.")
    doc.save(tmp_path / "e.docx")
    assert [(s["loc"], s["text"]) for s in documentos.leer(tmp_path / "e.docx")["segments"]] == [("§ Capítulo", "Capítulo. Contenido.")]
    # un .txt con marcas sigue siendo una transcripción; uno sin marcas, un documento
    (tmp_path / "f.txt").write_text("[00:00:05] Ana: Hola a todos.\n[00:00:09] Luis: Empezamos.", encoding="utf-8")
    assert "tipo" not in pipeline.import_transcript(tmp_path / "f.txt", None, 1, 0, lambda f, m: None)["importada"]
    assert pipeline.import_transcript(tmp_path / "d.txt", None, 1, 0, lambda f, m: None)["importada"]["tipo"] == "texto"
    assert len(documentos._trozos("palabra " * 200)) == 3 and pipeline.merge_segs([{"s": 0, "e": 1, "text": "a", "loc": "p. 1"}, {"s": 1, "e": 2, "text": "b", "loc": "p. 2"}])[1]["loc"] == "p. 2"


def test_pdf_buscable_y_buscar(cl):
    t, app = cl
    r = t.post("/api/generar", json={"video": subir(t, "informe.pdf", PDF), "buscable": True, "carpeta": "Obra", "gpu": False}).json()
    esperar(app)
    mid = app.cola[-1]["result"]["id"]
    assert app.cola[-1]["result"]["acta"] is None and r["id"] == app.cola[-1]["id"]
    m = next(x for x in t.get("/api/meetings").json() if x["id"] == mid)
    assert (m["kind"], m["label"], m["carpeta"], m["actas"]) == ("pdf", "informe.pdf", "Obra", 0)
    d = t.get(f"/api/meeting/{mid}").json()
    assert (d["actas"], d["kind"], d["video"], d["vision"]) == ([], "pdf", False, "no_disponible") and d["fuente"].endswith("/fuente.pdf")
    assert t.get(d["fuente"]).content == PDF
    f = t.get(f"/api/fuente/{mid}").json()
    assert [p["loc"] for p in f["partes"]] == ["p. 1", "p. 2", "p. 3"] and (f["paginas"], f["ocr"]) == (3, [3])
    x = buscar(t, "PRESUPUÉSTO")["fragmentos"]  # sin acentos ni mayúsculas
    assert len(x) == 1 and (x[0]["doc"], x[0]["loc"], x[0]["tipo_fuente"], x[0]["kind"], x[0]["titulo"]) == (mid, "p. 1", "texto", "pdf", "informe.pdf")
    assert "<mark>presupuesto</mark>" in x[0]["snippet"] and x[0]["score"] > 0 and "t" not in x[0]
    assert buscar(t, "leido")["fragmentos"][0]["loc"] == "p. 3"  # página escaneada: OCR
    assert buscar(t, "presupuesto", c="Otra")["fragmentos"] == [] and buscar(t, "presupuesto", c="Obra")["fragmentos"]
    assert buscar(t, "presupuesto", tipo="video")["fragmentos"] == [] and buscar(t, "presupuesto", tipo="pdf")["fragmentos"]
    assert buscar(t, "presu")["fragmentos"]  # prefijo
    shutil.rmtree(pipeline.WORK / mid)  # documento borrado: sale del índice
    assert buscar(t, "presupuesto")["fragmentos"] == []


def test_imagen_con_ia(cl, monkeypatch):
    t, app = cl
    cuerpos = []
    monkeypatch.setattr(vision, "elegir", lambda aj, nube=None: {"proveedor": "propio", "url": "http://127.0.0.1:9/v1", "modelo": "vl"})
    monkeypatch.setattr(nube, "clave", lambda p: "")
    monkeypatch.setattr(vision, "_pedir", lambda url, body, **k: cuerpos.append((url, body)) or "Panel con un gráfico de ventas al alza.")
    t.post("/api/generar", json={"video": subir(t, "panel.png", png()), "buscable": True, "descripcion": "Cuadro de mando del lunes", "gpu": False})
    esperar(app)
    mid = app.cola[-1]["result"]["id"]
    url, body = cuerpos[0]
    content = body["messages"][0]["content"]
    assert url == "http://127.0.0.1:9/v1/chat/completions" and body["model"] == "vl" and content[0]["text"] == vision.PROMPT
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    f = t.get(f"/api/fuente/{mid}").json()
    assert (f["kind"], f["descripcion"], f["descripcion_ia"], f["ocr_texto"], f["vision"]) == (
        "imagen", "Cuadro de mando del lunes", "Panel con un gráfico de ventas al alza.", "TEXTO LEIDO POR OCR", "servidor") and f["url"].endswith("fuente.png")
    assert buscar(t, "ventas")["fragmentos"][0]["tipo_fuente"] == "descripcion_ia" and buscar(t, "cuadro")["fragmentos"][0]["tipo_fuente"] == "descripcion"
    assert buscar(t, "ocr")["fragmentos"][0]["tipo_fuente"] == "imagen"
    assert t.post(f"/api/imagen/{mid}", json={"descripcion_ia": "Gráfico de devoluciones"}).json()["descripcion_ia"] == "Gráfico de devoluciones"
    assert buscar(t, "devoluciones")["fragmentos"] and not buscar(t, "ventas")["fragmentos"]
    assert t.post(f"/api/imagen/{mid}", json={"descripcion": "", "descripcion_ia": ""}).status_code == 200  # aún queda el OCR
    t.post("/api/describir", json={"id": mid})  # rehacer con IA
    esperar(app)
    assert t.get(f"/api/fuente/{mid}").json()["descripcion_ia"] == "Panel con un gráfico de ventas al alza." and len(cuerpos) == 2
    monkeypatch.setattr(vision, "elegir", lambda aj, nube=None: None)
    r = t.post("/api/describir", json={"id": mid})
    assert r.status_code == 409 and r.json()["detail"]["faltan"] == ["vision"]


def test_vision_elegir(monkeypatch):
    monkeypatch.setattr(vision, "_local", lambda: None)
    srv, remoto = {"url": "http://localhost:1234/v1", "modelo": "qwen-vl"}, {"url": "https://vl.example.com/v1", "modelo": "x"}
    nb = {"proveedor": "openai", "url": "https://api.openai.com/v1", "modelo": "gpt", "anonimizar": False}
    assert vision.elegir({"vision": srv}) == {"proveedor": "propio", **srv} and vision.estado(vision.elegir({"vision": srv})) == "servidor"
    assert vision.elegir({"vision": remoto}) is None and vision.elegir({"vision": remoto, "nube_imagenes": True})["url"] == remoto["url"]
    assert vision.elegir({}, nb) is None  # imágenes a la nube: solo con permiso expreso
    assert vision.estado(vision.elegir({"nube_imagenes": True}, nb)) == "nube"
    assert vision.elegir({"nube_imagenes": True}, {**nb, "anonimizar": True}) is None and vision.elegir({"nube_imagenes": True}, {**nb, "proveedor": "cli:claude"}) is None
    monkeypatch.setattr(vision, "_local", lambda: ("m.gguf", "mmproj.gguf"))
    assert vision.estado(vision.elegir({})) == "local" and vision.estado(None) == "no_disponible"


def test_zip_lote(cl, tmp_path):
    t, app = cl
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("a.md", "# Diseño\n\nLa fachada se pinta de azul.")
        z.writestr("sub/b.txt", "Nota suelta sobre la grua torre.")
        z.writestr("../../evil.md", "Fuera de sitio.")
        z.writestr("__MACOSX/._a.md", "basura")
        z.writestr(".oculto.txt", "oculto")
        z.writestr("x.exe", "MZ")
    r = t.post("/api/generar", json={"video": subir(t, "lote.zip", b.getvalue()), "buscable": True, "carpeta": "Lote", "gpu": False}).json()
    assert (r["lote"], len(r["ids"]), r["omitidos"], r["errores"]) == (2, 2, ["x.exe"], [])
    assert {p.name for p in tmp_path.rglob("*") if p.is_file() and "work" not in p.parts} == {"lote.zip", "a.md", "b.txt"}  # sin «..», ocultos ni __MACOSX
    esperar(app)
    assert {m["label"] for m in t.get("/api/meetings").json() if m["carpeta"] == "Lote"} == {"a.md", "b.txt"}
    assert buscar(t, "fachada", c="Lote")["fragmentos"][0]["loc"] == "§ Diseño" and buscar(t, "grua")["fragmentos"][0]["loc"] == "¶ 1"
    e = io.BytesIO()  # zip exportado por la app: se importa como siempre
    with zipfile.ZipFile(e, "w") as z:
        z.writestr("index.html", "<p>x</p>")
        z.writestr("acta.json", '{"titulo": "Acta importada", "nivel": "normal"}')
    assert t.post("/api/generar", json={"video": subir(t, "acta.zip", e.getvalue())}).json()["id"].startswith("z")


def test_buscar_elementos(cl):
    t, _ = cl
    registro.crear("Obra", "tarea", titulo="Revisar el presupuesto anual", detalle="Con el arquitecto")
    registro.crear("Otra", "riesgo", titulo="Retraso del presupuésto")
    x = buscar(t, "presupuesto arquitecto")["elementos"]
    assert [(e["tipo"], e["texto"], e["c"]) for e in x] == [("tarea", "Revisar el presupuesto anual", "Obra")]
    assert {e["c"] for e in buscar(t, "PRESUPUESTO")["elementos"]} == {"Obra", "Otra"} and [e["c"] for e in buscar(t, "presupuesto", c="Otra")["elementos"]] == ["Otra"]
    assert buscar(t, "presupuesto", tipo="riesgo")["elementos"][0]["tipo"] == "riesgo" and buscar(t, "presupuesto", tipo="pdf")["elementos"] == []
    assert buscar(t, "")["elementos"] == [] and buscar(t, "")["fragmentos"] == []
