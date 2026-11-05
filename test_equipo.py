"""Fase 1 de docs/plan-equipos.md: autor en el historial (Ajustes › Tú), miembros del proyecto y configuración de equipo. Sin LLM."""

import json

import pipeline
import plantillas
from test_carpetas import C, cl  # noqa: F401


def test_autor_en_historial_y_miembros(cl):
    t, _ = cl
    assert t.post("/api/ajustes", json={"yo": {"nombre": "Ana Pérez", "correo": "mal"}}).status_code == 400
    assert t.post("/api/ajustes", json={"yo": {"nombre": "Ana Pérez", "correo": "ana@ejemplo.com"}}).json()["yo"]["nombre"] == "Ana Pérez"
    e = t.post("/api/reg", json={"c": C, "tipo": "requisito", "titulo": "Pagar con Bizum"}).json()
    assert t.patch(f"/api/reg/{e['id']}", json={"c": C, "cambios": {"dueno": "Luis Gómez"}}).status_code == 200
    h = t.get(f"/api/reg/{e['id']}/historial", params={"c": C}).json()
    assert h and all(x["autor"] == "Ana Pérez <ana@ejemplo.com>" for x in h)
    ms = t.get("/api/reg/miembros", params={"c": C}).json()
    assert "Ana Pérez" in ms and "Luis Gómez" in ms and not any(m.lower().startswith("hablante ") for m in ms)


def test_configuracion_de_equipo_ida_y_vuelta(cl):
    t, app = cl
    pl = {**plantillas.SERIE_ID["retro"], "id": "retro-equipo", "nombre": "Retro del equipo"}
    plantillas.guardar(pl)
    t.post("/api/estilos", json={"nombre": "Corporativo", "color": "#123456"})
    t.post("/api/perfiles-uso", json={"nombre": "Innovación", "plantillas": ["ideacion", "demo"]})
    t.post("/api/objetivos", json={"nombre": "Al canal", "plan": {"salidas": []}})
    t.post("/api/ajustes", json={"nombres": {"carpeta": "Iniciativa"}})
    d = t.get("/api/equipo/exportar").json()
    assert d["actas_equipo"] == 1 and "destinos" not in d
    assert [p["id"] for p in d["plantillas"]] == ["retro-equipo"] and d["estilos"][0]["nombre"] == "Corporativo"
    # en otro equipo: todo vacío y se importa
    plantillas.borrar("retro-equipo")
    for f in (pipeline.WORK / "estilos").glob("*.json"):
        f.unlink()
    app.PERFILES.unlink()
    t.post("/api/ajustes", json={"nombres": {"carpeta": "Proyecto"}})
    r = t.post("/api/equipo/importar", json=d).json()
    assert r["errores"] == [] and r["importado"] == {"plantillas": 1, "estilos": 1, "perfiles_uso": 1, "objetivos": 1}
    assert "retro-equipo" in plantillas.propias() and t.get("/api/ajustes").json()["nombres"]["carpeta"] == "Iniciativa"
    assert any(p["nombre"] == "Innovación" for p in json.loads(app.PERFILES.read_text(encoding="utf-8")))
    assert t.post("/api/equipo/importar", json={"otra": 1}).status_code == 400


def test_plantillas_de_innovacion():
    for i in ("ideacion", "entrevista-usuario", "demo"):
        assert plantillas.validar(plantillas.SERIE_ID[i])["secciones"]
