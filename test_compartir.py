"""A2 (docs/plan-equipos.md): dos instalaciones comparten un proyecto por una carpeta (como OneDrive). Sin LLM ni red."""

import json

import pipeline
from test_carpetas import C, cl  # noqa: F401


def _instalacion(monkeypatch, app, w):
    """Cambia «de máquina»: otro work/ (registro.db, ajustes, carpetas e identificador de instalación propios)."""
    w.mkdir(exist_ok=True)
    monkeypatch.setattr(pipeline, "WORK", w)
    monkeypatch.setattr(app, "CARPETAS", w / "carpetas.json")
    monkeypatch.setattr(app, "AJUSTES", w / "ajustes.json")


def test_dos_instalaciones(cl, tmp_path, monkeypatch):
    t, app = cl
    wa, wb, sh = pipeline.WORK, tmp_path / "work-b", tmp_path / "OneDrive" / "Comunidad A"
    sh.mkdir(parents=True)
    t.post("/api/ajustes", json={"yo": {"nombre": "Ana", "correo": ""}})
    pa = t.get("/api/exp/pendientes", params={"c": C}).json()["items"]
    assert pa
    r = t.post("/api/compartir", json={"c": C, "ruta": str(sh)})
    assert r.status_code == 200 and r.json()["compartido"], r.text
    assert (sh / "proyecto.json").is_file() and list((sh / "actas").glob("*.md")) and not (sh / "transcripciones").exists()
    assert not list(sh.rglob("*.db"))

    _instalacion(monkeypatch, app, wb)
    t.post("/api/ajustes", json={"yo": {"nombre": "Luis", "correo": ""}})
    assert t.post("/api/compartir/unirse", json={"ruta": str(sh)}).json()["c"] == C
    pb = t.get("/api/exp/pendientes", params={"c": C}).json()["items"]
    assert sorted(p["texto"] for p in pb) == sorted(p["texto"] for p in pa)
    x = next(p for p in pb if p["texto"] == pa[0]["texto"])
    assert x["tipo"] == "Compartido" and x["doc"] == "De Ana"
    assert t.post("/api/exp/pendientes", json={"c": C, "id": x["id"], "estado": "hecho"}).status_code == 200
    t.patch(f"/api/reg/{x['eid']}", json={"c": C, "cambios": {"dueno": "Luis"}})
    t.post("/api/compartir", json={"c": C})

    _instalacion(monkeypatch, app, wa)
    assert t.post("/api/compartir", json={"c": C}).status_code == 200
    h = t.get(f"/api/reg/{x['eid']}/historial", params={"c": C}).json()
    assert h[-1]["autor"] == "Luis"
    y = next(p for p in t.get("/api/exp/pendientes", params={"c": C, "estado": "todos"}).json()["items"] if p["eid"] == x["eid"])
    assert (y["estado"], y["resp"]) == ("hecho", "Luis")
    # sin eco: volver a sincronizar no reenvía lo recibido
    assert t.post("/api/compartir", json={"c": C}).status_code == 200
    ev = [json.loads(ln) for f in (sh / "eventos").glob("*.jsonl") for ln in f.read_text(encoding="utf-8").splitlines()]
    assert sum(1 for e in ev if e["id"] == x["eid"] and "dueno" in e["cambios"] and e["cambios"]["dueno"] == "Luis") == 1


def test_carpeta_que_no_es_compartida(cl, tmp_path):
    t, _ = cl
    assert t.post("/api/compartir/unirse", json={"ruta": str(tmp_path)}).status_code == 400
    assert t.post("/api/compartir", json={"c": C, "ruta": str(tmp_path / "no-existe")}).status_code == 400


def test_ida_vuelta_planner_simulado(cl, monkeypatch):
    """A5: lo cerrado en el destino (aquí un Planner simulado) queda «hecho» aquí, con la fecha que tenga allí."""
    import destinos
    import destinos_tipos as T

    t, _ = cl
    x = t.post("/api/reg", json={"c": C, "tipo": "tarea", "titulo": "Pedir presupuesto"}).json()
    remoto = {"P1": {"hecho": True, "fecha": "2026-12-01"}}
    monkeypatch.setitem(T.TIPOS, "falso", {**T.TIPOS["ms_planner"], "leer": lambda c, s, o, i: remoto.get(i)})
    monkeypatch.setitem(T.SECRETOS, "falso", [])
    cf = destinos.cfg()
    cf["destinos"]["d1"] = {"tipo": "falso", "nombre": "Planner", "config": {"plan": "x"}}
    destinos._escribir(destinos.CFG(), cf)
    destinos._mapa(f"d1|abc|e:{x['id']}", {"h": "h", "id": "P1", "url": "", "t": 0})
    r = t.post("/api/destinos/d1/sincronizar").json()
    assert r == {"actualizados": 1, "errores": []}
    y = t.get(f"/api/reg/{x['id']}/historial", params={"c": C}).json()[-1]
    assert (y["despues"]["estado"], y["despues"]["fecha_limite"]) == ("hecho", "2026-12-01")
    assert y["autor"] == "Planner"
    assert t.post("/api/destinos/d1/sincronizar").json()["actualizados"] == 0  # ya está al día


def test_aviso_al_asignar(cl, monkeypatch):
    """A4: una receta «al asignar» envía el elemento (con su responsable) en cuanto alguien pasa a ser responsable."""
    import destinos
    import destinos_tipos as T

    t, _ = cl
    enviados = []
    monkeypatch.setitem(T.TIPOS, "falso", {**T.TIPOS["ms_planner"], "crear": lambda c, s, o, x, n=None: enviados.append(x) or ("1", "")})
    monkeypatch.setitem(T.SECRETOS, "falso", [])
    monkeypatch.setattr(destinos, "_hilo", lambda fn, *a: fn(*a))
    cf = destinos.cfg()
    cf["destinos"]["d1"] = {"tipo": "falso", "nombre": "Canal", "config": {"plan": "x"}}
    destinos._escribir(destinos.CFG(), cf)
    r = t.post(
        "/api/recetas",
        json={"nombre": "Avisos", "activa": True, "cuando": {"tipo": "al_asignar", "carpeta": C}, "plan": {"salidas": [{"destino": "d1", "que": "tareas"}]}},
    )
    assert r.status_code == 200, r.text
    x = t.post("/api/reg", json={"c": C, "tipo": "tarea", "titulo": "Revisar contrato", "revision": "aprobado"}).json()
    otra = t.post("/api/reg", json={"c": C, "tipo": "tarea", "titulo": "Otra"}).json()
    assert not enviados
    t.patch(f"/api/reg/{x['id']}", json={"c": C, "cambios": {"dueno": "Luis"}})
    assert [(e["titulo"], e["dueno"]) for e in enviados] == [("Revisar contrato", "Luis")] and otra["id"] not in str(enviados)
    t.patch(f"/api/reg/{x['id']}", json={"c": C, "cambios": {"detalle": "con abogados"}})
    assert len(enviados) == 1  # solo al cambiar de responsable
    assert t.post("/api/recetas", json={"nombre": "x", "cuando": {"tipo": "al_asignar"}}).status_code == 400


def test_leer_jira_y_azure(monkeypatch):
    """Fase 5: Jira y Azure DevOps de ida y vuelta, misma interfaz que Planner (leer -> {hecho, fecha})."""
    import destinos_tipos as T

    pedidas = []

    def http(met, url, h=None, body=None, raw=False):
        pedidas.append(url)
        if "/rest/api/" in url:
            return {"fields": {"status": {"statusCategory": {"key": "done"}}, "duedate": "2026-12-01"}}
        return {"fields": {"System.State": "Closed", "Microsoft.VSTS.Scheduling.DueDate": "2026-12-02T00:00:00Z"}}

    monkeypatch.setattr(T, "http", http)
    j = T.TIPOS["jira"]["leer"]({}, {"token": "t"}, {"url": "https://x.atlassian.net/", "email": "a@b.c"}, "ABC-1")
    a = T.TIPOS["azure"]["leer"]({}, {"token": "t"}, {"url": "https://dev.azure.com/org", "proyecto": "Mi proyecto"}, "7")
    assert j == {"hecho": True, "fecha": "2026-12-01"} and a == {"hecho": True, "fecha": "2026-12-02"}
    assert pedidas[0].startswith("https://x.atlassian.net/rest/api/3/issue/ABC-1") and "Mi%20proyecto/_apis/wit/workitems/7" in pedidas[1]
