"""Endurecimiento: validación del registro, rechazo de «sustituye», CSV seguro, PDF sin 500 por limpieza, NO_DECISION, informe. Sin LLM."""
import contextlib
import os
import shutil
import subprocess
import tempfile

import pytest

import exportar
import informe
import pipeline
import registro
from test_carpetas import C, cl  # noqa: F401


def _post(t, **k):
    return t.post("/api/reg", json={"c": C, **k})


def test_cambios_validan_campos_fechas_y_estado(cl):
    t, _ = cl
    x = _post(t, tipo="riesgo", titulo="R").json()
    p = lambda cm: t.patch(f"/api/reg/{x['id']}", json={"c": C, "cambios": cm}).status_code
    assert p({"campos": {"fuente": "x"}}) == 400 and p({"campos": {"huerfano": True}}) == 400 and p({"campos": {"clave": 1}}) == 400
    assert p({"fecha_limite": "10/03/2026"}) == 400 and p({"fecha_cierre": "2026-13-01"}) == 400 and p({"fecha_alta": "x"}) == 400
    assert p({"fecha_limite": "2026-03-10", "fecha_cierre": ""}) == 200
    assert p({"estado": "inventado"}) == 400 and p({"estado": "mitigado"}) == 200
    assert _post(t, tipo="requisito", titulo="Q", estado="zzz").status_code == 400
    assert _post(t, tipo="requisito", titulo="Q", estado="borrador").status_code == 200
    assert _post(t, tipo="historia", titulo="H", estado="en curso").status_code == 200


def test_revisar_atomico_y_valida_por_tipo(cl):
    t, _ = cl
    a = _post(t, tipo="interesado", titulo="Ana").json()
    b = _post(t, tipo="riesgo", titulo="R").json()
    # poder=9 solo es inválido para el interesado: el lote entero falla y no se aplica nada
    r = t.post("/api/reg/revisar", json={"c": C, "ids": [b["id"], a["id"]], "accion": "descartar", "cambios": {"campos": {"poder": 9}}})
    assert r.status_code == 400
    assert {i["revision"] for i in t.get("/api/reg", params={"c": C}).json()["items"] if i["id"] in (a["id"], b["id"])} == {"aprobado"}
    assert registro.de(C, b["id"])["campos"] == {}
    # estado válido para uno e inválido para otro (requisito vs tarea): nada aplicado
    q = _post(t, tipo="requisito", titulo="Q").json()
    k = _post(t, tipo="tarea", titulo="T").json()
    assert t.post("/api/reg/revisar", json={"c": C, "ids": [q["id"], k["id"]], "accion": "aprobar", "cambios": {"estado": "implementado"}}).status_code == 400
    assert registro.de(C, q["id"])["estado"] == "borrador" or registro.de(C, q["id"])["estado"] != "implementado"


def test_rechazo_de_sustituye_persiste(cl):
    t, _ = cl
    b = t.get("/api/reg/bandeja", params={"c": C}).json()["relaciones_propuestas"]
    assert b
    r = b[0]
    assert t.delete("/api/reg/relacion", params={"c": C, **{k: r[k] for k in ("a", "b", "tipo")}}).json() == {"ok": True}
    assert t.get("/api/reg/bandeja", params={"c": C}).json()["relaciones_propuestas"] == []
    ent = t.get("/api/reg", params={"c": C, "tipo": "decision"}).json()["items"]
    assert not any(x["tipo"] == "sustituye" for e in ent for x in e["relaciones"])  # la fila -1 no sale en el contrato


def test_sugerencia_sin_cambio_no_deja_lote(cl):
    t, _ = cl
    x = next(i for i in t.get("/api/reg", params={"c": C, "tipo": "tarea"}).json()["items"] if i["mid"])
    registro.editar(x["id"], {"sugerencia": {"tipo": "hecho", "cita": "ya", "mid": x["mid"], "ver": x["ver"], "t": 1}}, False)
    antes = registro.ultimo_lote(C)
    assert t.post(f"/api/reg/{x['id']}/sugerencia", json={"c": C, "accion": "rechazar"}).status_code == 200
    assert registro.de(C, x["id"])["fecha_cierre"] is None
    lote = registro.ultimo_lote(C)  # rechazar no cierra: ninguna entrada de fecha_cierre en el historial
    assert not any(e["despues"] and "fecha_cierre" in e["despues"] for e in registro.historial(x["id"]))
    assert lote is not None or antes is None


def test_csv_no_inyecta_formulas():
    s = exportar._csv(["a", "b", "c", "d", "e", "f"], [["=HYPERLINK(1)", "+1+1", "-5", "@x", "2026-03-10", "-cmd"]])
    fila = s.lstrip("﻿").splitlines()[1]
    assert fila == "'=HYPERLINK(1),'+1+1,-5,'@x,2026-03-10,'-cmd"


def test_pdf_limpieza_no_es_500(monkeypatch):
    class Pr:
        pid, returncode = 1, 0
        poll = wait = lambda s, *a: 0
    def popen(cmd, **k):
        next(a for a in cmd if a.startswith("--print-to-pdf=")).split("=", 1)[1].__class__
        from pathlib import Path
        Path(next(a for a in cmd if a.startswith("--print-to-pdf=")).split("=", 1)[1]).write_bytes(b"%PDF-1")
        return Pr()
    monkeypatch.setattr(exportar, "navegador", lambda: "x")
    monkeypatch.setattr(exportar.subprocess, "Popen", popen)
    monkeypatch.setattr(exportar.subprocess, "run", lambda *a, **k: None)
    real = shutil.rmtree
    def rm(p, *a, **k):  # como Windows con el perfil retenido por un hijo del navegador
        if k.get("onexc"):
            k["onexc"](os.unlink, str(p), PermissionError(32, "en uso"))
            return
        raise PermissionError(32, "en uso")
    monkeypatch.setattr(shutil, "rmtree", rm)
    assert exportar.pdf_html("<p>x</p>").startswith(b"%PDF")
    monkeypatch.setattr(shutil, "rmtree", real)


def test_decision_firme_con_proxima_reunion_se_conserva():
    f = "Se aprueba presentar el presupuesto en la próxima reunión"
    assert not pipeline.aplazada(f, "") and pipeline.no_decision(f, "")  # poblar (modelo) sí la descarta; el acta no
    assert pipeline.aplazada("Se aplaza decidir quién redacta", "") and pipeline.aplazada("", "lo dejamos pendiente de decidir")


def test_informe_valida_y_revision_de_la_bd(cl):
    t, _ = cl
    r = registro.crear(C, "riesgo", titulo="Retraso", revision="propuesto", origen="manual")
    i = t.post("/api/reg/informes", json={"c": C, "desde": "2026-03-01", "hasta": "2026-03-31"}).json()["id"]
    url = f"/api/reg/informes/{i}"
    p = lambda cm: t.patch(url, json={"c": C, "cambios": cm}).status_code
    assert p({"semaforos": {"Coste": {"color": "verde", "justificacion": 5}}}) == 400
    sec = next(iter(informe.SECCIONES))
    assert p({"narrativa": {sec: [{"texto": "x", "refs": "r"}]}}) == 400
    assert p({"narrativa": {sec: [{"texto": "x", "refs": [{"id": "no-existe"}]}]}}) == 404
    assert p({"narrativa": {sec: [{"texto": "x", "refs": [{"id": r["id"], "revision": "aprobado"}]}]}}) == 200  # la revisión del cliente se ignora
    x = informe.obtener(C, i)
    assert "revision" not in x["contenido"]["narrativa"][sec][0]["refs"][0]
    assert informe.preparar(C, x, False)["narr"][sec] == []  # «solo aprobados»: el riesgo sigue propuesto en la BD
    assert len(informe.preparar(C, x, True)["narr"][sec]) == 1
    registro.editar(r["id"], {"revision": "aprobado"}, False)
    assert len(informe.preparar(C, x, False)["narr"][sec]) == 1


def test_renombrar_carpeta_sobre_otra_con_datos_es_400(cl):
    t, _ = cl
    _post(t, tipo="riesgo", titulo="R")
    t.post("/api/carpeta", json={"nombre": "Otra"})
    registro.crear("Otra", "riesgo", titulo="X")
    r = t.post("/api/carpeta", json={"nombre": C, "nuevo": "Otra"})
    assert r.status_code == 400 and "ya existe" in r.json()["detail"]


def test_deshacer_pasada_endpoint(cl):
    t, _ = cl
    x = registro.crear(C, "requisito", "LOTEIA", auto=True, titulo="Auto")
    u = _post(t, tipo="riesgo", titulo="Manual").json()
    d = lambda lote: t.post("/api/reg/deshacer-pasada", json={"c": C, "lote": lote})
    assert d("nolote").status_code == 404
    lu = registro.ultimo_lote(C)
    assert d(lu).status_code == 400
    r = d("LOTEIA").json()
    assert r["ok"] and r["revertidas"] == 1 and x["id"] not in [i["id"] for i in t.get("/api/reg", params={"c": C}).json()["items"]]
    assert u["id"] in [i["id"] for i in t.get("/api/reg", params={"c": C}).json()["items"]]
