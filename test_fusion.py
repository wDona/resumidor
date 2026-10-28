"""fusionar/separar del registro: relleno de vacíos, nota «Fusionado desde…», deshacer, separar y errores. Sin LLM."""
import pytest

import registro
from test_carpetas import C, cl  # noqa: F401
from test_registro import work  # noqa: F401

cita = lambda t: {"mid": "m1", "ver": "v", "t": t, "texto": f"cita {t}"}


def test_rellena_vacios_y_nota(work):
    d = registro.crear("P", "decision", titulo="Usar Postgres", cita=cita(0))
    o = registro.crear("P", "decision", titulo="Base de datos: Postgres 16", detalle="Por soporte JSON", dueno="Ana", campos={"alternativas": "MySQL"}, cita=cita(1))
    x = registro.fusionar(d["id"], [o["id"]])
    assert (x["detalle"], x["dueno"], x["campos"]["alternativas"]) == ("Por soporte JSON\nFusionado desde D-002: Base de datos: Postgres 16", "Ana", "MySQL")
    assert x["titulo"] == "Usar Postgres" and len(registro.citas(d["id"])) == 2
    assert registro.fusionadas([d["id"]])[d["id"]][0]["codigo"] == "D-002"
    assert registro.completas([registro.de("P", d["id"])])[0]["fusionadas"][0]["citas"] == 1
    # no pisa lo que el destino ya tiene; el detalle distinto va a la nota
    o2 = registro.crear("P", "decision", titulo="Usar Postgres", detalle="Otro motivo", dueno="Luis")
    x = registro.fusionar(d["id"], [o2["id"]])
    assert x["dueno"] == "Ana" and x["detalle"].endswith("\nFusionado desde D-003: Otro motivo")


def test_deshacer(work):
    d = registro.crear("P", "decision", titulo="A", cita=cita(0))
    o = registro.crear("P", "decision", titulo="B", detalle="det", revision="aprobado", cita=cita(1))
    registro.fusionar(d["id"], [o["id"]])
    registro.deshacer("P")
    x, y = registro.de("P", d["id"]), registro.de("P", o["id"])
    assert (x["detalle"], x["editado"], y["revision"], y["fusionado_en"]) == ("", 0, "aprobado", None)
    assert len(registro.citas(d["id"])) == 1 and registro.fusionadas([d["id"]]) == {}


def test_separar(work):
    d = registro.crear("P", "decision", titulo="A", detalle="base", cita=cita(0))
    o = registro.crear("P", "decision", titulo="B", dueno="Ana", revision="aprobado", cita=cita(1))
    o2 = registro.crear("P", "decision", titulo="C", cita=cita(2))
    registro.fusionar(d["id"], [o["id"], o2["id"]])
    registro.editar(d["id"], {"titulo": "A editada"})  # un cambio posterior: separar no lo toca
    x = registro.separar(d["id"], o["id"])
    y = registro.de("P", o["id"])
    assert (y["revision"], y["fusionado_en"]) == ("aprobado", None)
    assert (x["titulo"], x["dueno"], x["detalle"]) == ("A editada", "", "base\nFusionado desde D-003: C")
    assert [c["texto"] for c in registro.citas(d["id"])] == ["cita 0", "cita 2"]
    assert [f["id"] for f in registro.fusionadas([d["id"]])[d["id"]]] == [o2["id"]]
    with registro._db() as db:
        assert not db.execute("SELECT 1 FROM relacion WHERE a=? AND tipo='fusion'", (o["id"],)).fetchone()
    with pytest.raises(ValueError, match="no está fusionado"):
        registro.separar(d["id"], o["id"])
    registro.deshacer("P")  # Ctrl+Z tras separar: vuelve a estar fusionada, con sus citas
    assert registro.de("P", o["id"])["revision"] == "fusionado" and len(registro.citas(d["id"])) == 3
    assert registro.de("P", d["id"])["dueno"] == "Ana"


def test_errores(work):
    r1, r2 = (registro.crear("P", "riesgo", titulo=t) for t in "ab")
    q = registro.crear("P", "requisito", titulo="c")
    with pytest.raises(ValueError, match="mismo tipo"):
        registro.fusionar(r1["id"], [q["id"]])
    registro.borrar(r2["id"])
    with pytest.raises(ValueError, match="descartado"):
        registro.fusionar(r2["id"], [r1["id"]])


def test_api(cl):
    t, _ = cl
    a, b = (t.post("/api/reg", json={"c": C, "tipo": "decision", "titulo": n}).json() for n in ("Login", "Entrar"))
    t.post("/api/reg/fusionar", json={"c": C, "destino": a["id"], "origenes": [b["id"]]})
    r = t.get("/api/reg", params={"c": C, "tipo": "decision", "revision": "fusionado"}).json()
    assert r["contadores"]["fusionadas"] == 1 and r["items"][0]["fusionado_en"] == a["id"] and r["items"][0]["fusionado_en_codigo"] == a["codigo"]
    x = t.post("/api/reg/separar", json={"c": C, "destino": a["id"], "origen": b["id"]}).json()
    assert [i["revision"] for i in x["items"]] == ["aprobado", "aprobado"] and x["items"][0]["fusionadas"] == []
    assert t.post("/api/reg/separar", json={"c": C, "destino": a["id"], "origen": b["id"]}).status_code == 400
    assert t.post("/api/reg/separar", json={"c": C, "destino": a["id"], "origen": a["id"]}).status_code == 400
