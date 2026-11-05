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


# ---- fase 2: B1 innovación y A3 vista de equipo ----
def test_entidades_de_innovacion_y_equipo(cl):
    t, _ = cl
    t.post("/api/ajustes", json={"yo": {"nombre": "Ana Pérez", "correo": ""}})
    for tipo, tit, est in (
        ("idea", "Pago con un clic", "nueva"),
        ("hipotesis", "Creemos que…", ""),
        ("experimento", "Test A/B", "matar"),
        ("insight", "Odian rellenar", ""),
    ):
        r = t.post("/api/reg", json={"c": C, "tipo": tipo, "titulo": tit, **({"estado": est} if est else {})})
        assert r.status_code == 200, r.text
    ids = {x["tipo"]: x["codigo"] for x in t.get("/api/reg", params={"c": C}).json()["items"]}
    assert ids["idea"] == "IDEA-001" and ids["insight"] == "INS-001"
    t.post("/api/reg", json={"c": C, "tipo": "tarea", "titulo": "Llamar", "dueno": "Ana", "fecha_limite": "2020-01-01"})
    t.post("/api/reg", json={"c": C, "tipo": "pregunta", "titulo": "¿Precio?", "campos": {"dirigida_a": "Luis"}})
    eq = {p["nombre"]: p for p in t.get("/api/reg/equipo", params={"c": C}).json()}
    assert eq["Luis"]["preguntas"] == 1


def test_migracion_quita_check_de_tipo(tmp_path, monkeypatch):
    import sqlite3

    import registro

    monkeypatch.setattr(pipeline, "WORK", tmp_path)
    db = registro.conectar()
    sql = db.execute("SELECT sql FROM sqlite_master WHERE name='entidad'").fetchone()[0]
    assert "CHECK (tipo IN" not in sql
    db.close()
    # una base antigua (CHECK con la lista vieja, esquema 4) se pone al día sin perder filas
    viejo = tmp_path / "v"
    viejo.mkdir()
    d = sqlite3.connect(viejo / "registro.db")
    d.executescript(registro.ESQUEMA[0].replace(f"CHECK (tipo IN ({registro._lista(registro.TIPOS)}))", "CHECK (tipo IN ('tarea'))"))
    d.executescript("".join(registro.ESQUEMA[1:4]) + "PRAGMA user_version=4;")
    d.execute("INSERT INTO proyecto(carpeta) VALUES ('X')")
    d.execute("INSERT INTO entidad(id, proyecto_id, tipo, titulo) VALUES ('a', 1, 'tarea', 'T')")
    d.commit()
    d.close()
    monkeypatch.setattr(pipeline, "WORK", viejo)
    registro._revisado.discard(str(viejo))
    db = registro.conectar()
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    db.execute("INSERT INTO entidad(id, proyecto_id, tipo, titulo) VALUES ('b', 1, 'idea', 'I')")
    assert db.execute("SELECT count(*) FROM entidad").fetchone()[0] == 2


# ---- fase 4: B3 embudo de ideas ----
def test_embudo_puntuacion_votos_y_excel(cl):
    import export_registro as XR

    t, _ = cl
    assert XR.puntuacion({"impacto": 8, "confianza": "5", "facilidad": 2}) == 80
    assert XR.puntuacion({"impacto": 8}) is None
    assert XR.puntuacion({"alcance": 10, "impacto": 3, "confianza": 4, "esfuerzo": 6}, "rice") == 20
    a = t.post(
        "/api/reg", json={"c": C, "tipo": "idea", "titulo": "Baja", "revision": "aprobado", "campos": {"impacto": 2, "confianza": 2, "facilidad": 2}}
    ).json()
    b = t.post(
        "/api/reg", json={"c": C, "tipo": "idea", "titulo": "Alta", "revision": "aprobado", "campos": {"impacto": 9, "confianza": 9, "facilidad": 9}}
    ).json()
    for quien in ("Ana", "Luis", "Ana"):  # un voto por persona
        t.patch(f"/api/reg/{a['id']}", json={"c": C, "cambios": {"campos": {f"voto:{quien}": 1}}})
    t.patch(f"/api/reg/{a['id']}", json={"c": C, "cambios": {"campos": {"voto:Luis": None}, "estado": "en evaluación"}})
    _, filas = XR.cargar(C, "ideas")
    assert [f["Título"] for f in filas] == ["Alta", "Baja"] and filas[0]["Puntuación"] == "729.0" and filas[1]["Votos"] == "1"
    assert t.get("/api/reg/exportar", params={"c": C, "vista": "ideas", "fmt": "xlsx"}).status_code == 200
    assert t.post("/api/exp/ajustes", json={"c": C, "puntuacion": "otra"}).status_code == 400
    assert t.post("/api/exp/ajustes", json={"c": C, "puntuacion": "rice"}).json()["ajustes"]["puntuacion"] == "rice"
    assert XR.cargar(C, "ideas")[1][0]["Puntuación"] == ""  # sin alcance/esfuerzo no hay RICE
    assert b["codigo"] == "IDEA-002"


# ---- fase 5: B4 memoria de innovación entre proyectos ----
def test_ideas_parecidas_en_otros_proyectos(cl):
    t, _ = cl
    t.post("/api/carpeta", json={"nuevo": "Lab viejo"})
    t.post(
        "/api/reg",
        json={
            "c": "Lab viejo",
            "tipo": "idea",
            "titulo": "Pagar con Bizum en la tienda online",
            "estado": "descartada",
            "campos": {"motivo": "Comisiones altas"},
        },
    )
    t.post("/api/reg", json={"c": "Lab viejo", "tipo": "idea", "titulo": "Mascota para la oficina"})
    x = t.post("/api/reg", json={"c": C, "tipo": "idea", "titulo": "Pago con Bizum en la tienda"}).json()
    r = t.get("/api/reg/parecidas", params={"id": x["id"]}).json()
    assert [(p["titulo"], p["carpeta"], p["estado"], p["porque"]) for p in r] == [
        ("Pagar con Bizum en la tienda online", "Lab viejo", "descartada", "Comisiones altas")
    ]
    assert t.get("/api/reg/parecidas", params={"texto": "mascota oficina"}).json()[0]["titulo"] == "Mascota para la oficina"
    assert t.get("/api/reg/parecidas", params={"id": "nada"}).status_code == 404


# ---- fase 5: B5 informe de portafolio ----
def test_portafolio(cl):
    import io
    import zipfile

    t, _ = cl
    t.post("/api/reg", json={"c": C, "tipo": "idea", "titulo": "Bizum", "estado": "escalada", "campos": {"motivo": "Gustó en el piloto"}})
    t.post("/api/reg", json={"c": C, "tipo": "idea", "titulo": "Chat"})
    t.post("/api/reg", json={"c": C, "tipo": "experimento", "titulo": "Test A/B", "estado": "diseño", "campos": {"metrica": "conversión"}})
    t.post("/api/reg", json={"c": C, "tipo": "experimento", "titulo": "Landing", "estado": "matar", "detalle": "Nadie hizo clic"})
    t.post("/api/reg", json={"c": C, "tipo": "insight", "titulo": "Odian rellenar formularios"})
    p = t.get("/api/portafolio", params={"fmt": "json"}).json()
    assert p["embudo"] == [[C, 1, 0, 0, 1, 0]] and p["curso"] == [[C, "EXP-001", "Test A/B", "diseño", "conversión"]]
    assert [d[2:] for d in p["decisiones"]] == [["Bizum", "escalada", "Gustó en el piloto"], ["Landing", "matar", "Nadie hizo clic"]]
    md = t.get("/api/portafolio", params={"fmt": "md"}).text
    assert "## Experimentos en curso" in md and "- Odian rellenar formularios" in md
    r = t.get("/api/portafolio")
    assert r.status_code == 200 and len(zipfile.ZipFile(io.BytesIO(r.content)).namelist()) > 5
    assert t.get("/api/portafolio", params={"fmt": "doc"}).status_code == 400
