"""Pruebas de /api/reg (registro genérico y bandeja) con TestClient sobre la carpeta sintética de test_carpetas. Sin LLM."""
import shutil

import pipeline
import registro
from test_carpetas import C, cl  # noqa: F401 (cl: fixture con 3 reuniones sintéticas)


def ids(r):
    return {x["titulo"]: x["id"] for x in r["items"]}


def todos(t, **p):
    return [i["id"] for i in t.get("/api/reg", params={"c": C, **p}).json()["items"]]


def test_crear_listar_filtrar(cl):
    t, _ = cl
    x = t.post("/api/reg", json={"c": C, "tipo": "riesgo", "titulo": "Retraso del proveedor", "dueno": "Ana", "campos": {"impacto": 4}}).json()
    assert (x["tipo"], x["origen"], x["revision"], x["codigo"], x["editado"], x["huerfano"], x["citas"], x["relaciones"]) == ("riesgo", "manual", "aprobado", "R-001", False, False, [], [])
    r = t.get("/api/reg", params={"c": C}).json()
    assert x["id"] in ids(r).values() and r["contadores"]["por_tipo"]["riesgo"] == 1 and r["contadores"]["por_revision"]["propuesto"] > 0  # las del acta entran propuestas
    assert todos(t, tipo="riesgo") == [x["id"]]
    assert todos(t, q="PROVEEDOR", dueno="an") == [x["id"]] and todos(t, q="R-001") == [x["id"]]
    dec = t.get("/api/reg", params={"c": C, "tipo": "decision"}).json()["items"]
    assert dec and dec[0]["citas"] and dec[0]["revision"] == "propuesto" and dec[0]["origen"] == "reunion"


def test_patch_historial_borrar(cl):
    t, _ = cl
    x = t.post("/api/reg", json={"c": C, "tipo": "tarea", "titulo": "A"}).json()
    y = t.patch(f"/api/reg/{x['id']}", json={"c": C, "cambios": {"titulo": "B", "campos": {"k": 1}}}).json()
    assert (y["titulo"], y["editado"], y["campos"]) == ("B", True, {"k": 1})
    h = t.get(f"/api/reg/{x['id']}/historial", params={"c": C}).json()
    assert [e["accion"] for e in h] == ["crear", "editar"] and h[1]["antes"]["titulo"] == "A" and set(h[1]) == {"t", "accion", "antes", "despues", "lote"}
    assert t.delete(f"/api/reg/{x['id']}", params={"c": C}).json() == {"ok": True}
    assert x["id"] not in todos(t) and todos(t, revision="descartado") == [x["id"]]
    assert t.post("/api/reg/deshacer", json={"c": C}).json()["revertidas"] == 1
    assert x["id"] in todos(t)


def test_revisar_lote_deshacer_y_resync(cl):
    t, _ = cl
    ps = t.get("/api/reg/bandeja", params={"c": C}).json()["propuestos"]
    tareas = [p["id"] for p in ps if p["tipo"] == "tarea"][:3]
    assert len(tareas) == 3
    r = t.post("/api/reg/revisar", json={"c": C, "ids": tareas, "accion": "aprobar", "cambios": {"prioridad": "alta"}}).json()
    assert r["ok"] and {i["revision"] for i in r["items"]} == {"aprobado"} and {i["prioridad"] for i in r["items"]} == {"alta"}
    d = t.post("/api/reg/deshacer", json={"c": C}).json()
    assert d["revertidas"] == 3 and {i["revision"] for i in d["items"]} == {"propuesto"} and {i["prioridad"] for i in d["items"]} == {""}
    # descartar no resucita con la resincronización
    t.post("/api/reg/revisar", json={"c": C, "ids": tareas[:1], "accion": "descartar"})
    for _ in range(2):
        assert tareas[0] not in todos(t)
        t.get("/api/reg/bandeja", params={"c": C})
    assert t.get("/api/reg", params={"c": C}).json()["contadores"]["por_revision"]["descartado"] == 1


def test_fusionar(cl):
    t, _ = cl
    a, b = (t.post("/api/reg", json={"c": C, "tipo": "requisito", "titulo": n}).json() for n in ("Login", "Entrar"))
    r = t.post("/api/reg/fusionar", json={"c": C, "destino": a["id"], "origenes": [b["id"]]}).json()
    assert r["id"] == a["id"] and any(x["tipo"] == "fusion" for x in r["relaciones"])
    assert b["id"] not in todos(t) and todos(t, revision="fusionado") == [b["id"]]
    assert t.post("/api/reg/deshacer", json={"c": C}).json()["revertidas"] == 3  # editar origen + nota en destino + fusionar
    assert t.post("/api/reg/fusionar", json={"c": C, "destino": a["id"], "origenes": [a["id"]]}).status_code == 400


def test_relacion(cl):
    t, _ = cl
    a, b = (t.post("/api/reg", json={"c": C, "tipo": "decision", "titulo": n}).json() for n in ("uno", "dos"))
    assert t.post("/api/reg/relacion", json={"c": C, "a": a["id"], "b": b["id"], "tipo": "sustituye"}).json() == {"ok": True}
    assert t.post("/api/reg/relacion", json={"c": C, "a": a["id"], "b": b["id"], "tipo": "nada"}).status_code == 400
    assert t.get("/api/reg", params={"c": C, "q": "uno"}).json()["items"][0]["relaciones"] == [{"a": a["id"], "b": b["id"], "tipo": "sustituye", "propuesta": False}]
    assert t.delete("/api/reg/relacion", params={"c": C, "a": a["id"], "b": b["id"], "tipo": "sustituye"}).json() == {"ok": True}
    assert t.get("/api/reg", params={"c": C, "q": "uno"}).json()["items"][0]["relaciones"] == []


def test_bandeja_huerfanos_y_sustituye(cl):
    t, _ = cl
    b = t.get("/api/reg/bandeja", params={"c": C}).json()
    assert set(b) == {"propuestos", "sugerencias", "relaciones_propuestas", "huerfanos"} and b["propuestos"] and b["huerfanos"] == []
    # las dos derramas (enero 500, febrero 600) son casi la misma decisión: la de febrero sustituye a la de enero
    rp = b["relaciones_propuestas"]
    assert rp and rp[0]["tipo"] == "sustituye" and rp[0]["propuesta"] and "600" in rp[0]["a_titulo"] and "500" in rp[0]["b_titulo"]
    t.post("/api/reg/relacion", json={"c": C, **{k: rp[0][k] for k in ("a", "b", "tipo")}})
    assert t.get("/api/reg/bandeja", params={"c": C}).json()["relaciones_propuestas"] == []
    # un documento que desaparece deja huérfanos, visibles y marcados
    shutil.rmtree(pipeline.WORK / "cccc3333")
    b = t.get("/api/reg/bandeja", params={"c": C}).json()
    assert b["huerfanos"] and all(h["huerfano"] for h in b["huerfanos"])
    r = t.get("/api/reg", params={"c": C}).json()
    assert r["contadores"]["huerfanos"] == len(b["huerfanos"]) and any(i["huerfano"] for i in r["items"])
    assert set(todos(t, huerfanos=1)) == {h["id"] for h in b["huerfanos"]}


def test_sugerencias_en_bandeja(cl):
    t, _ = cl
    x = t.get("/api/reg", params={"c": C, "tipo": "tarea"}).json()["items"][0]
    registro.editar(x["id"], {"sugerencia": {"propone": "hecho"}}, False)
    assert [s["id"] for s in t.get("/api/reg/bandeja", params={"c": C}).json()["sugerencias"]] == [x["id"]]


def test_errores(cl):
    t, _ = cl
    x = t.post("/api/reg", json={"c": C, "tipo": "riesgo", "titulo": "A"}).json()
    assert t.post("/api/reg", json={"c": C, "tipo": "nada", "titulo": "A"}).status_code == 400
    assert t.post("/api/reg", json={"c": C, "tipo": "riesgo", "titulo": " "}).status_code == 400
    assert t.post("/api/reg", json={"c": C, "tipo": "riesgo", "titulo": "A", "campos": 3}).status_code == 400
    assert t.post("/api/reg", json={"c": "No existe", "tipo": "riesgo", "titulo": "A"}).status_code == 404
    assert t.get("/api/reg", params={"c": C, "tipo": "nada"}).status_code == 400
    assert t.get("/api/reg", params={"c": C, "revision": "x"}).status_code == 400
    for cm in ({"id": "z"}, {"revision": "aprobado"}, {"nada": 1}, "x"):
        assert t.patch(f"/api/reg/{x['id']}", json={"c": C, "cambios": cm}).status_code == 400
    assert t.patch("/api/reg/zzz", json={"c": C, "cambios": {"titulo": "x"}}).status_code == 404
    assert t.delete("/api/reg/zzz", params={"c": C}).status_code == 404
    assert t.get("/api/reg/zzz/historial", params={"c": C}).status_code == 404
    assert t.post("/api/reg/revisar", json={"c": C, "ids": [x["id"]], "accion": "x"}).status_code == 400
    assert t.post("/api/reg/revisar", json={"c": C, "ids": [], "accion": "aprobar"}).status_code == 400
    assert t.post("/api/reg/revisar", json={"c": C, "ids": [x["id"], "zzz"], "accion": "descartar"}).status_code == 404
    assert x["id"] in todos(t)  # el 404 no dejó nada a medias
    # una entidad de otro proyecto no es accesible desde esta carpeta
    assert t.post("/api/carpeta", json={"nombre": "Otra"}).status_code == 200
    assert t.patch(f"/api/reg/{x['id']}", json={"c": "Otra", "cambios": {"titulo": "x"}}).status_code == 404


def _sugerir(t, tipo):
    x = next(i for i in t.get("/api/reg", params={"c": C, "tipo": "tarea"}).json()["items"] if i["mid"])
    registro.editar(x["id"], {"sugerencia": {"tipo": tipo, "cita": "ya está", "mid": x["mid"], "ver": x["ver"], "t": 90}}, False)
    return x["id"]


def test_sugerencia_aceptar_rechazar_deshacer(cl):
    t, _ = cl
    url = lambda i: f"/api/reg/{i}/sugerencia"
    h = _sugerir(t, "hecho")
    r = t.post(url(h), json={"c": C, "accion": "aceptar"}).json()
    assert (r["estado"], r["sugerencia"]) == ("hecho", None) and r["fecha_cierre"]
    assert t.post("/api/reg/deshacer", json={"c": C}).json()["revertidas"] >= 1  # un solo paso: cierre + fecha_cierre
    r = t.get("/api/reg", params={"c": C, "tipo": "tarea"}).json()["items"]
    r = next(i for i in r if i["id"] == h)
    assert (r["estado"], r["fecha_cierre"]) == ("abierto", None) and r["sugerencia"]["tipo"] == "hecho"
    r = t.post(url(h), json={"c": C, "accion": "rechazar"}).json()
    assert (r["estado"], r["sugerencia"]) == ("abierto", None)
    t.post("/api/reg/deshacer", json={"c": C})
    assert next(i for i in t.get("/api/reg", params={"c": C, "tipo": "tarea"}).json()["items"] if i["id"] == h)["sugerencia"]
    r = t.post(url(h), json={"c": C, "accion": "aceptar"}).json()
    assert r["estado"] == "hecho"
    assert t.post(url(h), json={"c": C, "accion": "x"}).status_code == 400
    assert t.post(url("zzz"), json={"c": C, "accion": "aceptar"}).status_code == 404
    assert t.post(url(h), json={"c": C, "accion": "aceptar"}).status_code == 404  # ya resuelta


def test_descartar_listar_restaurar(cl):
    t, _ = cl
    ps = t.get("/api/reg/bandeja", params={"c": C}).json()["propuestos"]
    m = t.post("/api/reg", json={"c": C, "tipo": "riesgo", "titulo": "M"}).json()["id"]
    p = ps[0]["id"]
    t.post("/api/reg/revisar", json={"c": C, "ids": [p, m], "accion": "descartar"})
    r = t.get("/api/reg", params={"c": C, "revision": "descartado"}).json()
    assert {i["id"] for i in r["items"]} == {p, m} and r["contadores"]["por_revision"]["descartado"] == 2
    assert p not in todos(t)
    x = t.post("/api/reg/revisar", json={"c": C, "ids": [p, m], "accion": "restaurar"}).json()
    assert {i["id"]: i["revision"] for i in x["items"]} == {p: "propuesto", m: "aprobado"}
    assert t.post("/api/reg/deshacer", json={"c": C}).json()["revertidas"] == 2
    assert todos(t, revision="descartado") and p not in todos(t)


def test_forma_que_lee_registro_js(cl):
    """Toda propiedad que registro.js lee de entidades/bandeja/historial existe en las respuestas reales."""
    from pathlib import Path
    t, _ = cl
    js = (Path(__file__).parent / "static" / "registro.js").read_text(encoding="utf-8")
    t.post("/api/reg", json={"c": C, "tipo": "riesgo", "titulo": "A"})
    h = _sugerir(t, "hecho")
    ents = t.get("/api/reg", params={"c": C}).json()
    it = next(i for i in ents["items"] if i["id"] == h)
    b = t.get("/api/reg/bandeja", params={"c": C}).json()
    usadas = {"id", "codigo", "titulo", "huerfano", "revision", "origen", "editado", "sugerencia", "citas", "mid", "ver", "dueno", "estado", "detalle", "campos"}
    assert usadas <= set(it) and all(f"it.{k}" in js or f"s.{k}" in js or f"x.{k}" in js or f"h.{k}" in js for k in usadas - {"detalle", "ver", "mid", "estado", "dueno"})
    assert {"mid", "ver", "t", "texto", "verificada"} <= set(it["citas"][0])
    assert {"tipo", "cita", "mid", "ver", "t"} <= set(it["sugerencia"])
    assert {"propuestos", "sugerencias", "relaciones_propuestas", "huerfanos"} <= set(b)
    assert {"items", "contadores"} == set(ents) and {"por_tipo", "por_revision", "huerfanos"} <= set(ents["contadores"]) and {"propuesto", "aprobado", "descartado"} <= set(ents["contadores"]["por_revision"])
    t.patch(f"/api/reg/{h}", json={"c": C, "cambios": {"prioridad": "alta"}})
    hs = t.get(f"/api/reg/{h}/historial", params={"c": C}).json()
    assert hs and {"t", "accion", "antes", "despues"} <= set(hs[0]) and 1e9 < hs[0]["t"] < 1e11  # segundos epoch: el JS no los multiplica por 1000 de más
    assert all(k in js for k in ("a_titulo", "b_titulo", "por_revision", "contadores", "relaciones_propuestas"))
    assert {"a", "b", "tipo", "a_titulo", "b_titulo"} <= set(b["relaciones_propuestas"][0])
