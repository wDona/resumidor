"""Pruebas de importar_registro.py: exportar -> editar celdas -> reimportar (xlsx y csv), deshacer y /api/doc/a-proyecto. Sin LLM."""
import io
import json
import re
import zipfile

import export_registro as ER
import importar_registro as IR
import pipeline
import registro
from test_carpetas import C, cl  # noqa: F401


def req(t, titulo, **f):
    return t.post("/api/reg", json={"c": C, "tipo": "requisito", "titulo": titulo, **f}).json()


def editar_xlsx(datos, cambios):
    """Cambia celdas de la hoja 1 de un .xlsx exportado: {(fila, col): texto}; None borra la celda; añade filas con ('+', [..])."""
    zi, out = zipfile.ZipFile(io.BytesIO(datos)), io.BytesIO()
    with zipfile.ZipFile(out, "w") as zo:
        for n in zi.namelist():
            b = zi.read(n)
            if n == "xl/worksheets/sheet1.xml":
                s = b.decode()
                for (r, col), v in cambios.items():
                    s = re.sub(rf'(<c r="{col}{r}"[^>]*><is><t xml:space="preserve">).*?(</t>)', lambda m: m[1] + v + m[2], s, count=1, flags=re.S)
                b = s.encode()
            zo.writestr(n, b)
    return out.getvalue()


def subir(t, datos, nombre, **f):
    return t.post("/api/reg/importar/previa", files={"file": (nombre, datos)}, data={"c": C, **f})


def test_roundtrip_xlsx_deshacer(cl):
    t, _ = cl
    a = req(t, "Pagar con Bizum", prioridad="Must", estado="borrador", campos={"solicitante": "Elena"})
    b = req(t, "Exportar PDF", detalle="Informes")
    xl = t.get("/api/reg/exportar", params={"c": C, "vista": "requisitos", "fmt": "xlsx"}).content
    # sin cambios: todo igual
    r = subir(t, xl, "r.xlsx").json()
    assert r["vista"] == "requisitos" and r["iguales"] == 2 and not r["modificados"] and not r["nuevos"] and "Código" in r["columnas_reconocidas"]
    ed = editar_xlsx(xl, {(2, "B"): "Pagar con Bizum y tarjeta", (3, "E"): "should", (3, "F"): "validado"})
    r = subir(t, ed, "r.xlsx").json()
    assert [(m["codigo"], m["cambios"]) for m in r["modificados"]] == [
        ("REQ-001", {"Título": ["Pagar con Bizum", "Pagar con Bizum y tarjeta"]}),
        ("REQ-002", {"Prioridad": ["", "Should"], "Estado": ["abierto", "validado"]})]
    ap = t.post("/api/reg/importar/aplicar", json={"token": r["token"], "seleccion": [b["id"]]}).json()
    assert (ap["modificadas"], ap["creadas"]) == (1, 0)
    assert registro.de(C, a["id"])["titulo"] == "Pagar con Bizum" and registro.de(C, b["id"])["prioridad"] == "Should"
    assert t.post("/api/reg/importar/aplicar", json={"token": r["token"]}).status_code == 404  # token de un solo uso
    # todo en un lote: deshacer lo revierte
    r = subir(t, ed, "r.xlsx").json()
    assert t.post("/api/reg/importar/aplicar", json={"token": r["token"]}).json()["modificadas"] == 1  # b ya estaba aplicado
    assert t.post("/api/reg/deshacer", json={"c": C}).json()["revertidas"] == 1
    assert registro.de(C, a["id"])["titulo"] == "Pagar con Bizum"


def test_nuevos_desconocidas_csv(cl):
    t, _ = cl
    req(t, "Uno", prioridad="Must")
    csv = "﻿Código;Título;Prioridad;Estado;Tipo\r\nREQ-001;Uno;Must;abierto;\r\n;Nuevo manual;should;borrador;no funcional\r\nREQ-099;Fantasma;;;\r\n;Raro;Urgentísima;;\r\n;;;;\r\n;Sin tipo ok;;;chorradas\r\n"
    r = subir(t, csv.encode("utf-8"), "r.csv", vista="requisitos").json()
    assert r["iguales"] == 1 and [n["titulo"] for n in r["nuevos"]] == ["Nuevo manual"]
    assert sorted(d["fila"] for d in r["desconocidas"]) == [4, 5, 6] and "REQ-099" in r["desconocidas"][0]["motivo"]
    ap = t.post("/api/reg/importar/aplicar", json={"token": r["token"]}).json()
    n = ap["items"][0]
    assert (ap["creadas"], n["origen"], n["revision"], n["prioridad"], n["estado"], n["campos"]["tipo_req"], n["citas"]) == (1, "manual", "aprobado", "Should", "borrador", "no funcional", [])
    assert n["campos"]["importado"] is True
    assert t.post("/api/reg/deshacer", json={"c": C}).json()["revertidas"] == 1 and len(registro.listar(C, "requisito")) == 1
    # coma, latin-1 y vista deducida por las columnas
    r = subir(t, "Nombre,Rol,Poder,Interés\nAna,jefa,5,3\nLuis,,2,x\n".encode("cp1252"), "i.csv").json()
    assert r["vista"] == "interesados" and len(r["nuevos"]) == 1 and r["desconocidas"][0]["fila"] == 3


def test_limites_y_formatos(cl):
    t, _ = cl
    assert subir(t, b"x", "a.pdf").status_code == 400
    assert subir(t, b"no zip", "a.xlsx", vista="requisitos").status_code == 400
    assert subir(t, b"a;b\n1;2\n", "a.csv", vista="requisitos").status_code == 400  # ninguna columna reconocida
    assert subir(t, b"Titulo\nX\n", "a.csv", vista="cosas").status_code == 400
    assert subir(t, b"x" * (IR.MAX_BYTES + 20_000), "a.csv", vista="requisitos").status_code == 413
    assert IR._fecha(46000.0) == "2025-12-09" and IR._fecha("3/4/2026") == "2026-04-03"


def test_a_proyecto(cl, monkeypatch):
    t, app = cl
    lanzados = []
    monkeypatch.setattr(app, "start", lambda kind, spec, video, mid="": lanzados.append((kind, spec, mid)) or {"id": f"j{len(lanzados)}"})
    monkeypatch.setattr(app, "_tipo_carpeta", lambda c: "Proyecto")
    mid = next(m["id"] for m in app.meetings() if m["carpeta"] == C)
    nueva = "Proyecto Nuevo"
    app.carpetas  # noqa: B018
    t.post("/api/carpeta", json={"nuevo": nueva})
    r = t.post("/api/doc/a-proyecto", json={"mids": [mid], "c": nueva, "modo": "mover"}).json()
    assert r == {"ok": True, "mids": [mid], "poblando": ["j1"]} and lanzados[0][1]["c"] == nueva and lanzados[0][1]["mid"] == mid
    assert json.loads((pipeline.WORK / mid / "meta.json").read_text(encoding="utf-8"))["carpeta"] == nueva
    r = t.post("/api/doc/a-proyecto", json={"mids": [mid], "c": C, "modo": "copiar"}).json()
    nid = r["mids"][0]
    assert nid != mid and (pipeline.WORK / mid / "meta.json").exists() and json.loads((pipeline.WORK / nid / "meta.json").read_text(encoding="utf-8"))["carpeta"] == C
    assert t.post("/api/doc/a-proyecto", json={"mids": ["nope"], "c": C, "modo": "mover"}).status_code == 404
    assert t.post("/api/doc/a-proyecto", json={"mids": [mid], "c": C, "modo": "x"}).status_code == 400
    monkeypatch.setattr(app, "_ajustes", lambda: {"poblar_auto": False})  # respeta poblar_auto
    assert t.post("/api/doc/a-proyecto", json={"mids": [mid], "c": C, "modo": "mover"}).json()["poblando"] == []
    monkeypatch.setattr(app, "_ajustes", lambda: {"poblar_auto": True})
    monkeypatch.setattr(app, "_tipo_carpeta", lambda c: "Paciente")  # sensible: nunca
    assert t.post("/api/doc/a-proyecto", json={"mids": [mid], "c": C, "modo": "mover"}).json()["poblando"] == []



def test_a_proyecto_sin_enviar_no_lanza_recetas(cl, monkeypatch):
    t, A = cl
    llamadas = []
    monkeypatch.setattr(A.destinos, "tras_documento", lambda *a, **k: llamadas.append(a))
    monkeypatch.setattr(A, "_tipo_carpeta", lambda c: "otra")  # sin poblar: el envío depende solo de «enviar»
    mid = next(p.parent.parent.name for p in A.pipeline.WORK.glob("*/acta_*/acta.json"))
    assert t.post("/api/doc/a-proyecto", json={"mids": [mid], "c": C, "modo": "copiar"}).status_code == 200
    assert llamadas == []
    assert t.post("/api/doc/a-proyecto", json={"mids": [mid], "c": C, "modo": "copiar", "enviar": True}).status_code == 200
    assert len(llamadas) == 1
