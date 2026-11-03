from test_destinos import E  # noqa: F401  (fixture)
from test_carpetas import cl  # noqa: F401


def test_objetivos_crud(E):
    t, _ = E
    g = t.get("/api/objetivos").json()
    assert g and all(o["serie"] and o["id"].startswith("serie:") for o in g)
    assert next(o for o in g if o["id"] == "serie:buscable")["plan"]["solo_buscable"] is True
    r = t.post("/api/objetivos", json={"nombre": " Mío ", "plan": {"salidas": [{"que": "tareas", "como": "documento"}]}, "plantilla": "acta"})
    assert r.status_code == 200, r.text
    i = r.json()["id"]
    assert r.json()["nombre"] == "Mío" and r.json()["fijado"] is False
    assert t.patch(f"/api/objetivos/{i}", json={"fijado": True}).json()["fijado"] is True
    assert [o for o in t.get("/api/objetivos").json() if not o.get("serie")][0]["plantilla"] == "acta"
    assert t.post("/api/objetivos", json={"nombre": "x", "plan": {"salidas": [{"que": "nada"}]}}).status_code == 400
    assert t.post("/api/objetivos", json={"nombre": " "}).status_code == 400
    assert t.patch("/api/objetivos/serie:reunion", json={"nombre": "z"}).status_code == 404
    assert t.delete(f"/api/objetivos/{i}").status_code == 200
    assert t.delete(f"/api/objetivos/{i}").status_code == 404
