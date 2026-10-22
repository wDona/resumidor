"""Pruebas de carpetas.py (expediente) y de sus endpoints sobre una carpeta de prueba con 3 reuniones sintéticas en un work temporal; sin LLM
(el seguimiento con modelo se prueba aparte, ver README). `uv run pytest test_carpetas.py`"""
import datetime as dt
import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import carpetas
import pipeline
import rag

C = "Comunidad A"
HOY = dt.date(2026, 3, 10)


def acta(titulo, decisiones=(), tareas=(), secs=(), puntos=()):
    return {"titulo": titulo, "duracion": 600, "nivel": "normal", "resumen": titulo + ".", "relato": [], "puntos": [{"t": t, "texto": x} for t, x in puntos], "secciones": [],
            "decisiones": [{"cita": "x", "texto": x, "t": t, "b": 0, "n": 1} for t, x in decisiones],
            "tareas": [{"cita": "x", "tarea": a, "responsable": r, "plazo": p, "t": t, "b": 0} for t, a, r, p in tareas], "capturas": [],
            "plantilla": "Junta de vecinos / comunidad de propietarios", "secciones_plantilla": [{"id": i, "nombre": n, "items": its} for i, n, its in secs]}


def doc(work, mid, nombre, dias, ac, segs, ver="acta_normal_imp"):
    wd = work / mid
    (wd / (ver + mid[:4])).mkdir(parents=True)
    (wd / (ver + mid[:4]) / "acta.json").write_text(json.dumps(ac, ensure_ascii=False))
    (wd / (ver + mid[:4]) / "index.html").write_text("<!doctype html><title>x</title><body><p>Documento de prueba</p>")
    tf = wd / f"transcript_imp{mid[:4]}.json"
    tf.write_text(json.dumps({"language": "es", "segments": [{"s": s, "e": s + 8, "text": t, "spk": k} for s, t, k in segs],
                              "importada": {"fuente": "x.vtt", "formato": "WebVTT", "segmentos": len(segs), "hablantes": [], "desfase": 0, "aviso": None}}, ensure_ascii=False))
    (wd / "meta.json").write_text(json.dumps({"carpeta": C, "nombre": nombre}))
    t = time.time() - dias * 86400
    os.utime(tf, (t, t)), os.utime(wd / (ver + mid[:4]) / "acta.json", (t, t))
    return wd


def construir(w):
    """Tres reuniones sintéticas en «Comunidad A» (enero, febrero, marzo)."""
    doc(w, "aaaa1111", "Junta enero", 40, acta(
        "Junta de enero", decisiones=[(300, "Se aprueba la derrama de 500 euros por vivienda para cambiar el ascensor.")],
        tareas=[(100, "Arreglar la puerta del garaje", "Javier", "El viernes"), (200, "Pedir tres presupuestos de pintura del portal", "Ana", "Sin plazo")],
        secs=[("derramas", "Derramas y cuotas", [{"texto": "Derrama del ascensor", "importe": "500 euros", "plazo": "31/03/2026", "t": 300}, {"texto": "Cuota extra de jardinería", "importe": "20 euros", "plazo": "—", "t": 310}]),
              ("incidencias", "Incidencias y reparaciones", [{"texto": "Gotera en el portal", "ubicacion": "portal", "responsable": "Administración", "t": 400}]),
              ("ruegos", "Ruegos y preguntas", [{"texto": "Un vecino pide más luz", "propietario": "Marta", "t": 450}])],
        puntos=[(50, "Se revisan las cuentas del año anterior"), (120, "Se habla del color del portal")]),
        [(0, "Buenos días a todos. Hoy hablamos del ascensor y de la puerta del garaje.", "Laura"), (100, "Javier arregla la puerta del garaje el viernes.", "Javier"),
         (200, "Ana pedirá tres presupuestos de pintura del portal. Hablamos con Marta Gómez y con Pedro Ruiz, de la empresa Otis.", "Ana"),
         (300, "Se aprueba la derrama de 500 euros por vivienda para cambiar el ascensor.", "Laura")])
    doc(w, "bbbb2222", "Junta febrero", 20, acta(
        "Junta de febrero", decisiones=[(150, "Se aprueba la derrama de 600 euros por vivienda para cambiar el ascensor."), (260, "Se contrata a la empresa Otis para el mantenimiento.")],
        tareas=[(120, "Enviar el acta de la junta a todos los vecinos", "Secretaría", "Mañana")],
        puntos=[(50, "Se revisan las cuentas del año anterior"), (400, "Se habla de la limpieza de la escalera")]),
        [(0, "Buenos días. Seguimos con el ascensor y con Otis.", "Laura"), (150, "Se aprueba la derrama de 600 euros por vivienda para cambiar el ascensor.", "Laura"),
         (260, "Se contrata a la empresa Otis para el mantenimiento. Marta Gómez lo gestiona con Pedro Ruiz.", "Laura")])
    doc(w, "cccc3333", "Junta marzo", 1, acta("Junta de marzo", tareas=[(90, "Contactar con el fontanero", "Pedro Ruiz", "Final de mes")]),
        [(0, "Buenos días. Revisamos pendientes.", "Laura"), (90, "Javier: ya arreglamos la puerta del garaje esta semana, quedó perfecta.", "Javier"),
         (200, "Marta Gómez vigila la gotera del portal con Pedro Ruiz.", "Marta")])


@pytest.fixture()
def cl(tmp_path, monkeypatch):
    w = tmp_path / "work"
    w.mkdir()
    monkeypatch.setattr(pipeline, "WORK", w)
    construir(w)
    import app
    monkeypatch.setattr(app, "CARPETAS", w / "carpetas.json")
    monkeypatch.setattr(app, "AJUSTES", w / "ajustes.json")
    return TestClient(app.app), app


def ms():
    import app
    return [m for m in app.meetings() if m["carpeta"] == C]


def test_plazo_fecha():
    ref = dt.date(2026, 3, 10)  # martes
    f = carpetas.plazo_fecha
    assert f("31/03/2026", ref) == dt.date(2026, 3, 31) and f("El viernes", ref) == dt.date(2026, 3, 13) and f("Viernes de la semana que viene", ref) == dt.date(2026, 3, 20)
    assert f("mañana", ref) == dt.date(2026, 3, 11) and f("Final de mes", ref) == dt.date(2026, 3, 31) and f("Antes del lunes", ref) == dt.date(2026, 3, 16) and f("—", ref) is None


def test_pendientes_agregados(cl):
    ps = {p["texto"]: p for p in carpetas.pendientes(C, ms(), HOY)}
    assert "Cuota extra de jardinería" not in ps and "Un vecino pide más luz" not in ps  # derrama sin plazo y ruegos no son pendientes
    assert set(ps) >= {"Arreglar la puerta del garaje", "Pedir tres presupuestos de pintura del portal", "Derrama del ascensor (500 euros)", "Gotera en el portal", "Contactar con el fontanero"}
    p = ps["Arreglar la puerta del garaje"]
    assert p["id"] == "aaaa1111|acta_normal_impaaaa|tareas.0" and p["t"] == 100 and p["resp"] == "Javier" and p["mid"] == "aaaa1111"
    assert ps["Derrama del ascensor (500 euros)"]["id"].endswith("secciones_plantilla.0.items.0") and ps["Derrama del ascensor (500 euros)"]["fecha"] == "2026-03-31"
    assert ps["Gotera en el portal"]["resp"] == "Administración" and ps["Gotera en el portal"]["tipo"] == "Incidencias y reparaciones"
    # orden por plazo: lo que tiene fecha va primero, sin fecha al final; «vence pronto» = dentro de 7 días
    r = carpetas.listar(C, ms(), orden="plazo", hoy=dt.date(2026, 3, 25))
    fs = [p["fecha"] for p in r["items"]]
    assert fs == sorted(f for f in fs if f) + [None] * fs.count(None)
    pr = {p["texto"]: p for p in r["items"]}
    assert pr["Derrama del ascensor (500 euros)"]["pronto"] and not pr["Derrama del ascensor (500 euros)"]["vencido"]
    assert carpetas.listar(C, ms(), hoy=dt.date(2026, 4, 5))["items"][0]["vencido"]
    assert "Javier" in r["responsables"] and [p["resp"] for p in carpetas.listar(C, ms(), resp="ana")["items"]] == ["Ana"]


def test_estados_y_alias(cl):
    pid = "aaaa1111|acta_normal_impaaaa|tareas.0"
    carpetas.set_estado(C, ms(), pid, "hecho", HOY)
    assert carpetas.listar(C, ms(), "hecho", hoy=HOY)["n"]["hecho"] == 1 and "Arreglar la puerta del garaje" not in [p["texto"] for p in carpetas.listar(C, ms(), hoy=HOY)["items"]]
    carpetas.set_estado(C, ms(), pid, "abierto", HOY)  # marcar y desmarcar a mano
    assert carpetas.listar(C, ms(), hoy=HOY)["n"]["abierto"] > carpetas.listar(C, ms(), "hecho", hoy=HOY)["n"]["hecho"]
    carpetas.set_estado(C, ms(), pid, "descartado", HOY)
    # si se rehace el documento (versión nueva, otra ruta), el estado sigue al texto
    w = pipeline.WORK / "aaaa1111"
    (w / "acta_normal_impaaaa").rename(w / "acta_normal_impaaaa_v2")
    ps = {p["texto"]: p for p in carpetas.pendientes(C, ms(), HOY)}
    assert ps["Arreglar la puerta del garaje"]["estado"] == "descartado" and ps["Arreglar la puerta del garaje"]["id"].startswith("aaaa1111|acta_normal_impaaaa_v2|")
    with pytest.raises(ValueError):
        carpetas.set_estado(C, ms(), pid, "roto")
    with pytest.raises(KeyError):
        carpetas.set_estado(C, ms(), "zzzz|x|tareas.9", "hecho")


def test_manuales_notas_linea(cl):
    m = carpetas.añadir_manual(C, "Llamar al seguro", "Ana", "15/03/2026")
    assert any(p["id"] == m["id"] and p["manual"] and p["fecha"] == "2026-03-15" for p in carpetas.pendientes(C, ms(), HOY))
    carpetas.set_estado(C, ms(), m["id"], "hecho", HOY)
    carpetas.añadir_nota(C, "Hablé con el administrador", "2026-02-01")
    with pytest.raises(ValueError):
        carpetas.añadir_nota(C, "x", "ayer")
    lin = carpetas.linea(C, ms())
    assert [x["mid"] for x in lin if x["tipo"] == "doc"] == ["cccc3333", "bbbb2222", "aaaa1111"]  # el más reciente primero
    assert [x["tipo"] for x in lin].count("doc") == 3 and any(x["tipo"] == "nota" and x["fecha"] == "2026-02-01" for x in lin)
    assert any(x["tipo"] == "pendiente" and x["a"] == "hecho" for x in lin) and [x["t"] for x in lin] == sorted((x["t"] for x in lin), reverse=True)
    carpetas.borrar_manual(C, m["id"])
    assert not any(p["id"] == m["id"] for p in carpetas.pendientes(C, ms(), HOY))


def test_sugerencias_nunca_cierran(cl):
    pid = "aaaa1111|acta_normal_impaaaa|tareas.0"
    s = {"tipo": "hecho", "cita": "ya arreglamos la puerta del garaje", "t": 90, "mid": "cccc3333", "ver": "x", "doc": "Junta marzo", "fecha": "2026-03-09"}
    carpetas.editar(C, lambda e: e["sugeridos"].__setitem__(pid, s))
    p = next(p for p in carpetas.pendientes(C, ms(), HOY) if p["id"] == pid)
    assert p["estado"] == "abierto" and p["sugerido"]["cita"] == s["cita"]  # propuesto, no cerrado
    carpetas.resolver_sugerencia(C, ms(), pid, False, HOY)
    assert next(p for p in carpetas.pendientes(C, ms(), HOY) if p["id"] == pid)["sugerido"] is None
    carpetas.editar(C, lambda e: e["sugeridos"].__setitem__(pid, s))
    carpetas.resolver_sugerencia(C, ms(), pid, True, HOY)
    assert next(p for p in carpetas.pendientes(C, ms(), HOY) if p["id"] == pid)["estado"] == "hecho"
    pid2 = "aaaa1111|acta_normal_impaaaa|tareas.1"
    carpetas.editar(C, lambda e: e["sugeridos"].__setitem__(pid2, {**s, "tipo": "actualizado", "cita": "Ana pedirá los presupuestos la semana que viene"}))
    carpetas.resolver_sugerencia(C, ms(), pid2, True, HOY)
    p2 = next(p for p in carpetas.pendientes(C, ms(), HOY) if p["id"] == pid2)
    assert p2["estado"] == "abierto" and "semana que viene" in p2["nota"]


def test_cita_literal_del_seguimiento(cl):
    class Ix:  # lo mínimo de rag.Index que usa verificar_seguimiento
        segs = [{"s": 0, "text": "Buenos días. Revisamos pendientes.", "kind": "voz"}, {"s": 90, "text": "Javier: ya arreglamos la puerta del garaje esta semana, quedó perfecta.", "kind": "voz"}]
        window = lambda self, i: [j for j in (i - 1, i, i + 1) if 0 <= j < 2]
    ix = Ix()
    assert carpetas.verificar_seguimiento(ix, [1], "ya arreglamos la puerta del garaje esta semana") == 1
    assert carpetas.verificar_seguimiento(ix, [1], "Ya arreglamos la puerta del garaje") == 1  # sin mayúsculas ni puntuación
    assert carpetas.verificar_seguimiento(ix, [1], "la puerta del garaje se rompió ayer") is None  # inventada
    assert carpetas.verificar_seguimiento(ix, [0], "ya arreglamos la puerta") == 1  # cita en un tramo vecino -> minuto de ese tramo


def test_decisiones_comparar_estado(cl):
    ds = carpetas.docs(ms())
    assert [d["mid"] for d in ds] == ["aaaa1111", "bbbb2222", "cccc3333"]
    vig, sup = carpetas.vigentes(ds)
    assert [x["texto"] for x in sup] == ["Se aprueba la derrama de 500 euros por vivienda para cambiar el ascensor."] and sup[0]["por"]["mid"] == "bbbb2222"
    assert {x["texto"][:30] for x in vig} == {"Se aprueba la derrama de 600 e", "Se contrata a la empresa Otis "}
    cm = carpetas.comparar(ds[0], ds[1])
    assert [x["ahora"]["texto"][:30] for x in cm["decisiones"]["cambiado"]] == ["Se aprueba la derrama de 600 e"]  # misma decisión, otra cifra
    assert [x["texto"][:20] for x in cm["decisiones"]["nuevo"]] == ["Se contrata a la emp"]
    assert [x["texto"] for x in cm["tareas"]["nuevo"]] == ["Enviar el acta de la junta a todos los vecinos"] and len(cm["tareas"]["ya_no"]) == 2
    assert cm["puntos"]["igual"] == 1 and [x["texto"] for x in cm["puntos"]["nuevo"]] == ["Se habla de la limpieza de la escalera"]
    assert all(x["mid"] and x["ver"] and "t" in x for k in ("decisiones", "tareas") for x in cm[k]["nuevo"] + cm[k]["ya_no"])  # cada elemento cita documento y minuto
    est = carpetas.estado_actual(C, ms(), HOY)
    assert est["n_docs"] == 3 and est["ultimo"]["mid"] == "cccc3333" and est["cambios"]["b"]["mid"] == "cccc3333" and est["redaccion"] is None


def test_glosario(cl):
    assert carpetas.terminos(C) == [] and carpetas.terminos_prompt(C) == [] and carpetas.ortografia(C, "hola Otis") == "hola Otis"
    sug = {x["t"]: x["n"] for x in carpetas.sugerir_glosario(C, ms(), minimo=2)}
    assert sug["Pedro Ruiz"] == 3 and "Marta Gómez" in sug and "Buenos" not in sug and "Hoy" not in sug and sug.get("Otis", 0) >= 2
    carpetas.glosario_set(C, [{"t": "Otys", "orto": "Otis", "def": "empresa del ascensor"}, {"t": "otys"}, {"t": "Ana"}], ignorar=["Pedro Ruiz"])
    assert carpetas.terminos(C) == ["Otis", "Ana"] and carpetas.terminos_prompt(C) == ["Otis (empresa del ascensor)", "Ana"]
    assert carpetas.ortografia(C, "La empresa Otys y OTYS.") == "La empresa Otis y Otis."
    assert "Pedro Ruiz" not in [x["t"] for x in carpetas.sugerir_glosario(C, ms(), minimo=2)] and "Otis" not in [x["t"] for x in carpetas.sugerir_glosario(C, ms(), minimo=1)]
    carpetas.renombrar(C, "Otra")
    assert carpetas.terminos("Otra") == ["Otis", "Ana"] and carpetas.terminos(C) == []


def test_preguntas_de_pendientes(cl):
    r = carpetas.pregunta_pendientes(C, ms(), "¿Qué tiene pendiente Ana?")
    assert r["resp"] == "Ana" and [p["texto"] for p in r["items"]] == ["Pedir tres presupuestos de pintura del portal"]
    r = carpetas.pregunta_pendientes(C, ms(), "What does Pedro Ruiz have pending?")
    assert r["resp"] == "Pedro Ruiz" and [p["texto"] for p in r["items"]] == ["Contactar con el fontanero"]
    assert len(carpetas.pregunta_pendientes(C, ms(), "¿Qué tareas hay por hacer?")["items"]) >= 5
    assert carpetas.pregunta_pendientes(C, ms(), "¿Por qué se aprobó la derrama?") is None and carpetas.pregunta_pendientes(C, ms(), "¿Quién arregló la tarea del garaje?") is None


def test_endpoints(cl):
    c, app = cl
    q = {"c": C}
    e = c.get("/api/exp", params=q).json()
    assert e["n_docs"] == 3 and e["pend"] >= 5 and e["tipo"] == "Proyecto" and "Responsable" in e["sugerencias"]
    pl = c.post("/api/carpeta", json={"nombre": C, "plantilla": "comunidad"}).status_code
    e = c.get("/api/exp", params=q).json()
    assert pl == 200 and e["tipo"] == "Comunidad" and e["sugerencias"] == ["Dirección", "Administrador", "Nº de vecinos"]
    e = c.post("/api/exp/datos", json={"c": C, "datos": [{"k": "Dirección", "v": "C/ Sol 4"}, {"k": "", "v": "x"}]}).json()
    assert e["datos"] == [{"k": "Dirección", "v": "C/ Sol 4"}] and "Dirección" not in e["sugerencias"]
    assert c.post("/api/exp/datos", json={"c": C, "tipo": "Paciente", "datos": []}).json()["aviso"]  # tipo sensible: solo referencia interna
    c.post("/api/exp/datos", json={"c": C, "tipo": "", "datos": []})
    assert c.get("/api/exp", params={"c": "Nada"}).status_code == 404
    # pendientes: estado, filtro, manual
    r = c.get("/api/exp/pendientes", params={**q, "resp": "Javier"}).json()
    pid = r["items"][0]["id"]
    assert [p["resp"] for p in r["items"]] == ["Javier"] and c.post("/api/exp/pendientes", json={"c": C, "id": pid, "estado": "hecho"}).status_code == 200
    assert c.get("/api/exp/pendientes", params={**q, "estado": "hecho"}).json()["n"]["hecho"] == 1
    assert c.post("/api/exp/pendientes", json={"c": C, "id": pid, "estado": "xx"}).status_code == 400 and c.post("/api/exp/pendientes", json={"c": C, "id": "no|existe|x", "estado": "hecho"}).status_code == 404
    m = c.post("/api/exp/pendientes", json={"c": C, "texto": "Renovar el seguro", "resp": "Ana", "plazo": "mañana"}).json()
    assert c.post("/api/exp/pendientes", json={"c": C, "id": m["id"], "borrar": True}).status_code == 200
    # notas, línea de tiempo, ajustes, glosario, estado, comparar
    assert c.post("/api/exp/notas", json={"c": C, "texto": "Llamó el administrador", "fecha": "2026-01-05"}).status_code == 200
    assert {x["tipo"] for x in c.get("/api/exp/linea", params=q).json()} >= {"doc", "nota", "pendiente", "manual"}
    assert c.post("/api/exp/ajustes", json={"c": C, "anon": True, "idioma": "en"}).json()["ajustes"] == {"anon": True, "idioma": "en"}
    assert c.post("/api/exp/ajustes", json={"c": C, "idioma": "xx"}).status_code == 400
    assert app.anon_defecto("aaaa1111") is True and c.post("/api/exp/ajustes", json={"c": C, "anon": False}).status_code == 200 and app.anon_defecto("aaaa1111") is False
    c.post("/api/exp/ajustes", json={"c": C, "anon": None})
    assert app.anon_defecto("aaaa1111") is False  # sin opción de carpeta: el ajuste general (apagado en este work)
    g = c.post("/api/exp/glosario", json={"c": C, "glosario": [{"t": "Otys", "orto": "Otis"}]}).json()["glosario"]
    assert g[0]["orto"] == "Otis" and any(x["t"] == "Pedro Ruiz" for x in c.get("/api/exp/glosario", params={**q, "sugerir": 1, "minimo": 2}).json()["sugeridos"])
    est = c.get("/api/exp/estado", params=q).json()
    assert len(est["decisiones"]["superadas"]) == 1 and est["cambios"] and est["pendientes"]
    a, b = "aaaa1111", "bbbb2222"
    cm = c.get("/api/exp/comparar", params={**q, "a": b, "b": a}).json()  # el orden da igual: a es el anterior
    assert cm["a"]["mid"] == a and cm["b"]["mid"] == b and c.get("/api/exp/comparar", params={**q, "a": a, "b": a}).status_code == 404
    res = c.get("/api/carpetas/resumen").json()[C]
    assert res["pend"] >= 4 and res["ultima"] > 0
    # preguntar por pendientes: lista determinista con enlaces (no usa LLM ni GPU)
    r = c.post("/api/preguntar", json={"sel": "c:" + C, "q": "¿Qué tiene pendiente Ana?"})
    ev = [json.loads(x) for x in r.text.splitlines()]
    assert ev[0]["k"] == "pendientes" and ev[0]["resp"] == "Ana" and ev[0]["items"][0]["mid"] == "aaaa1111" and ev[0]["items"][0]["t"] == 200 and ev[-1]["k"] == "fin"
    r = c.post("/api/preguntar", json={"sel": "bbbb2222|imp" + "bbbb", "q": "what is pending?"})
    assert [json.loads(x)["items"][0]["texto"] for x in r.text.splitlines()[:1]] == ["Enviar el acta de la junta a todos los vecinos"]
    # renombrar la carpeta mueve el expediente
    c.post("/api/carpeta", json={"nombre": C, "nuevo": "Comunidad B"})
    e = c.get("/api/exp", params={"c": "Comunidad B"}).json()
    assert e["glosario"][0]["orto"] == "Otis" and e["n_docs"] == 3


def test_ajustes_carpeta_sin_glosario_no_cambian_prompts():
    import plantillas
    assert pipeline.prompts(plantillas.get("acta"), glosario=carpetas.terminos_prompt("no existe") or None) == pipeline.prompts(plantillas.get("acta"))
    assert rag.lang_q("What did Ana say?") == "en"


def test_redaccion_cita_y_verifica(cl):
    """La redacción (LLM simulado) solo conserva frases con fuente válida y sin cifras inventadas; cada una enlaza documento y minuto."""
    visto = {}

    def chat(sistema, user, schema, max_tokens, temperature=0.2):
        visto["user"] = user
        n = {l.split("] ")[1][:25]: int(l[1:l.index("]")]) for l in user.splitlines() if l.startswith("[")}
        i = next(v for k, v in n.items() if k.startswith("Decisión vigente: Se ap"))
        return {"frases": [f"La derrama vigente es de 600 euros por vivienda [{i}].", f"La derrama es de 900 euros [{i}].", "Frase sin fuente.", "Otra con fuente rota [99]."]}
    r = carpetas.redactar_estado(C, ms(), chat, HOY)
    assert [f["texto"] for f in r["frases"]] == ["La derrama vigente es de 600 euros por vivienda."]  # 900 no está en la fuente; sin fuente o fuente inexistente, fuera
    assert r["frases"][0]["refs"][0]["mid"] == "bbbb2222" and r["frases"][0]["refs"][0]["t"] == 150
    assert "sustituida" in visto["user"] and carpetas.estado_actual(C, ms(), HOY)["redaccion"]["n_docs"] == 3
    r = carpetas.redactar_comparacion(C, ms(), "aaaa1111", "bbbb2222", lambda *a, **k: {"frases": ["Hay una decisión nueva [1]."]})
    assert carpetas.comparar_ids(C, ms(), "bbbb2222", "aaaa1111")["redaccion"]["frases"][0]["refs"]
