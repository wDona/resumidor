"""Humo extremo a extremo de /api/reg con TestClient (sin LLM): una entidad de cada tipo, filtros, PATCH, revisar, deshacer, relación «aplicar»,
exportación de todas las vistas y comprobación estática de que cada URL /api/reg de las vistas JS tiene ruta en app.py."""
import os
import re
from pathlib import Path

import export_registro
from test_carpetas import C, cl  # noqa: F401

STATIC = Path(__file__).parent / "static"
SIN_RUTA_OK = {"/api/reg/derivar"}  # llega con F5


def mk(t, tipo, titulo, **k):
    r = t.post("/api/reg", json={"c": C, "tipo": tipo, "titulo": titulo, **k})
    assert r.status_code == 200, r.text
    return r.json()


def patch(t, x, cambios):
    return t.patch(f"/api/reg/{x['id']}", json={"c": C, "cambios": cambios})


def lista(t, **p):
    return {i["titulo"]: i for i in t.get("/api/reg", params={"c": C, **p}).json()["items"]}


def test_flujo_completo(cl):
    t, _ = cl
    rq = mk(t, "requisito", "El sistema permitirá reservar", prioridad="alta", campos={"solicitante": "Ana", "tipo_req": "funcional"})
    mk(t, "requisito", "Exportar a PDF", prioridad="baja", campos={"solicitante": "Luis", "tipo_req": "no funcional"})
    hu = mk(t, "historia", "Reservar pista", campos={"como": "socio", "quiero": "reservar", "para": "jugar", "epica": "Reservas",
                                                     "criterios": [{"escenario": "ok", "dado": "d", "cuando": "c", "entonces": "e"}]})
    assert hu["campos"]["criterios"][0]["escenario"] == "ok"
    t.post("/api/reg/relacion", json={"c": C, "a": hu["id"], "b": rq["id"], "tipo": "deriva_de"})
    it = mk(t, "interesado", "Ana", campos={"poder": 4, "interes": 2})
    vieja, nueva = mk(t, "decision", "Usar Excel"), mk(t, "decision", "Usar la app")

    # filtros
    assert set(lista(t, tipo="requisito", prioridad="alta")) == {rq["titulo"]}
    assert set(lista(t, tipo="requisito", campo_solicitante="Luis")) == {"Exportar a PDF"}
    assert set(lista(t, tipo="requisito", campo_tipo_req="funcional", prioridad="alta")) == {rq["titulo"]}
    assert lista(t, tipo="requisito", campo_solicitante="nadie") == {}

    # PATCH: vaciar poder/interés, validaciones, fecha_alta
    r = patch(t, it, {"campos": {"poder": "", "interes": ""}})
    assert r.status_code == 200 and r.json()["campos"]["poder"] == "" and r.json()["campos"]["interes"] == ""
    assert patch(t, it, {"campos": {"poder": 5, "interes": 1}}).status_code == 200
    for mal in (0, 6, "alto", 2.5, True):
        assert patch(t, it, {"campos": {"poder": mal}}).status_code == 400, mal
    assert patch(t, rq, {"campos": {"poder": "alto"}}).status_code == 200  # solo se valida en interesados
    assert patch(t, vieja, {"fecha_alta": "2026-02-01"}).json()["fecha_alta"] == "2026-02-01"
    assert patch(t, vieja, {"fecha_alta": "ayer"}).status_code == 400
    assert patch(t, vieja, {"fecha_alta": ""}).status_code == 200

    # revisar + deshacer
    assert t.post("/api/reg/revisar", json={"c": C, "ids": [hu["id"]], "accion": "descartar"}).status_code == 200
    assert t.post("/api/reg/deshacer", json={"c": C}).json()["revertidas"] == 1
    assert lista(t, tipo="historia")["Reservar pista"]["revision"] == "aprobado"

    # relación «aplicar»: un solo paso para deshacer
    assert t.post("/api/reg/relacion", json={"c": C, "a": nueva["id"], "b": vieja["id"], "tipo": "sustituye", "aplicar": True}).status_code == 200
    d = lista(t, tipo="decision")
    assert d["Usar Excel"]["estado"] == "sustituida" and any(x["tipo"] == "sustituye" and not x["propuesta"] for x in d["Usar la app"]["relaciones"])
    assert t.post("/api/reg/deshacer", json={"c": C}).json()["revertidas"] >= 1
    d = lista(t, tipo="decision")
    assert d["Usar Excel"]["estado"] == "" and not [x for x in d["Usar la app"]["relaciones"] if x["tipo"] == "sustituye"]
    assert t.post("/api/reg/relacion", json={"c": C, "a": nueva["id"], "b": vieja["id"], "tipo": "sustituye", "aplicar": True}).status_code == 200

    # exportación: toda vista x todo formato
    for vista in export_registro.COLS:
        for fmt in export_registro.formatos(vista):
            if fmt == "pdf" and not os.environ.get("ACTAS_TEST_PDF"):
                continue
            r = t.get("/api/reg/exportar", params={"c": C, "vista": vista, "fmt": fmt})
            assert r.status_code == 200 and r.content, (vista, fmt, r.status_code, r.text[:200])


def test_urls_js_tienen_ruta(cl):
    _, app = cl
    rutas = [re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", r.path) + "$") for r in app.app.routes if r.path.startswith("/api/reg")]
    sin = set()
    for f in ("registro", "requisitos", "historias", "interesados", "decisiones", "carpeta"):
        for u in re.findall(r"""["'`](/api/reg[^"'`?\s]*)""", (STATIC / f"{f}.js").read_text(encoding="utf8")):
            if u.endswith("/"):  # prefijo de una URL con id concatenado: "/api/reg/" + id + "/historial"
                ok = any(r.pattern.startswith("^" + re.escape(u)) for r in rutas)
            else:
                ok = any(r.match(u) for r in rutas)
            if not ok:
                sin.add(u)
    print("JS->ruta sin coincidencia:", sorted(sin))
    assert sin <= SIN_RUTA_OK, sin
