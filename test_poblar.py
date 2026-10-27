"""Pruebas de poblar.py (F3b) con un chat falso de respuesta fija sobre dos reuniones con la transcripción de tests_data/reunion.vtt. Sin LLM."""
import contextlib
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

import carpetas
import nube
import pipeline
import poblar
import registro
import transcripts
from conftest import VTT, _acta

C = "Proyecto Reservas"
MIDS = ("aaaa1111", "bbbb2222")
R = {"requisitos": [{"cita": "la aplicación debe permitir pagar con Bizum", "texto": "La aplicación debe permitir pagar con Bizum", "tipo_req": "funcional",
                     "prioridad": "—", "solicitante": "Elena Ruiz"},
                    {"cita": "el sistema exportará los informes en PDF", "texto": "Exportar informes en PDF", "tipo_req": "funcional", "prioridad": "—", "solicitante": "—"}],
     "decisiones": [{"cita": "Decidimos que Carlos confirme con ellos la fecha", "texto": "Carlos confirma con el proveedor la fecha del quince de noviembre", "decisor": "Laura"},
                    {"cita": "Eso lo dejamos pendiente de decidir", "texto": "Se aplaza decidir quién redacta las preguntas frecuentes", "decisor": "—"},
                    {"cita": "La próxima reunión será el martes que viene", "texto": "La próxima reunión será el martes", "decisor": "—"}],
     "interesados": [{"cita": "Elena Ruiz, la directora comercial de Hoteles Sol", "texto": "Elena Ruiz", "rol": "directora comercial",
                      "organizacion": "Hoteles Sol elena@hotelessol.com"}],
     "riesgos": [{"cita": "si el proveedor de pagos se retrasa, la beta cerrada no podrá empezar", "texto": "Retraso del proveedor de pagos: la beta cerrada no empieza",
                  "probabilidad": "—", "impacto": "—", "responsable": "—"},
                 {"cita": "si el proveedor de pagos se retrasa", "texto": "El retraso costará 40.000 euros", "probabilidad": "alta", "impacto": "—", "responsable": "—"}],
     "preguntas": [{"cita": "¿quién redacta las preguntas frecuentes para la beta?", "texto": "¿Quién redacta las preguntas frecuentes de la beta?", "dirigida_a": "—"}]}


def chat(sistema, user, schema, max_tokens, temperature=0.2):
    chat.n += 1
    assert not nube.valida(R, schema)  # la respuesta fija cumple el esquema (igual que se exige a la nube)
    return json.loads(json.dumps(R))


@pytest.fixture()
def cl(tmp_path, monkeypatch):
    w = tmp_path / "work"
    w.mkdir()
    monkeypatch.setattr(pipeline, "WORK", w)
    segs = transcripts.parse(VTT)["segments"]
    for i, mid in enumerate(MIDS):
        wd, t = w / mid, time.time() - (len(MIDS) - i) * 86400
        (wd / "acta_normal_imp1").mkdir(parents=True)
        (wd / "acta_normal_imp1" / "acta.json").write_text(json.dumps(_acta("Acta de reunión"), ensure_ascii=False), encoding="utf-8")
        (wd / "transcript_imp1.json").write_text(json.dumps({"language": "es", "segments": segs}, ensure_ascii=False), encoding="utf-8")
        (wd / "meta.json").write_text(json.dumps({"carpeta": C, "nombre": f"Reunión {i + 1}"}))
        for f in (wd / "transcript_imp1.json", wd / "acta_normal_imp1" / "acta.json"):
            os.utime(f, (t, t))
    import app
    monkeypatch.setattr(app, "CARPETAS", w / "carpetas.json")
    monkeypatch.setattr(app, "AJUSTES", w / "ajustes.json")
    chat.n = 0
    return TestClient(app.app), app


def ms(app):
    return [m for m in app.meetings() if m["carpeta"] == C]


def correr(app, **k):
    return poblar.poblar(C, ms(app), lambda: contextlib.nullcontext(chat), **k)


def de(tipo, **f):
    return [x for x in registro.listar(C, tipo, **f) if x["campos"].get("fuente") == "poblar"]


def test_prompt_y_esquema():
    sis, esq = poblar.prompt(list(poblar.VISTAS), ["Bizum"])
    assert set(esq["properties"]) == set(poblar.VISTAS) and all(f"{v}:" in sis for v in poblar.VISTAS)
    assert "LITERAL" in sis and "pendiente de decidir" in sis and "próxima reunión" in sis and "no es un riesgo" in sis and "Bizum" in sis
    assert "contacto" in sis and not any(k in json.dumps(esq) for k in ("telefono", "correo", "email"))  # D5
    assert pipeline.gbnf(esq) and sis.format(lang="español").endswith("Términos de este proyecto (escríbelos exactamente así): Bizum.")  # vale para el modelo local
    assert set(poblar.prompt(["riesgos"])[1]["properties"]) == {"riesgos"}


def test_verifica_deduplica_y_respeta(cl):
    _, app = cl
    r = correr(app)
    assert r["llamadas"] == 2 and r["creadas"] == {"requisito": 1, "interesado": 1, "riesgo": 1, "pregunta": 1}
    # sin cita en la transcripción (PDF), «se aplaza decidir», la próxima reunión y cifras inventadas (40.000): fuera, en las dos reuniones
    assert r["descartadas"] == 2 * 4
    assert [x["titulo"] for x in de("requisito")] == ["La aplicación debe permitir pagar con Bizum"]
    i = de("interesado")[0]
    assert (i["titulo"], i["detalle"], i["campos"]["organizacion"]) == ("Elena Ruiz", "directora comercial", "Hoteles Sol") and "@" not in json.dumps(i)
    assert i["campos"]["rol"] == "directora comercial" and "prioridad" not in de("requisito")[0]["campos"]  # «—» no se guarda
    # la decisión ya la tenía el acta (misma reunión y minuto): no se duplica
    assert not de("decision") and len(registro.listar(C, "decision")) == 4
    # la segunda reunión dice lo mismo: una cita más en la misma entidad (verificada, con su minuto)
    ci = registro.citas(de("requisito")[0]["id"])
    assert sorted(c["mid"] for c in ci) == list(MIDS) and all(c["verificada"] and c["t"] == 120 for c in ci) and r["citas"] == 4
    assert all(x["revision"] == "propuesto" and x["origen"] == "reunion" for t in ("requisito", "riesgo", "pregunta", "interesado") for x in de(t))
    # descartada no resucita; editada y aprobada no se tocan; volver a pasar no añade nada
    req, rie, pre = de("requisito")[0], de("riesgo")[0], de("pregunta")[0]
    registro.borrar(req["id"])
    registro.editar(rie["id"], {"titulo": "Riesgo editado a mano"})
    registro.editar(pre["id"], {"revision": "aprobado"})
    r2 = correr(app)
    assert r2["creadas"] == {} and r2["citas"] == 0 and r2["omitidas"] == 2
    assert de("requisito", revision="descartado")[0]["id"] == req["id"] and len(de("requisito")) == 1
    assert registro.de(C, rie["id"])["titulo"] == "Riesgo editado a mano" and registro.de(C, pre["id"])["revision"] == "aprobado"
    assert len(registro.citas(req["id"])) == 2  # a lo descartado tampoco se le añaden citas
    # solo una vista y solo una reunión
    assert correr(app, vistas=["riesgos"], mids=[MIDS[0]])["llamadas"] == 1


def test_no_quedan_huerfanas(cl):
    """sincronizar() no empareja ni marca huérfanas las de poblar aunque el acta cambie; las del acta sí quedan huérfanas."""
    _, app = cl
    correr(app)
    f = pipeline.WORK / MIDS[0] / "acta_normal_imp1" / "acta.json"
    a = json.loads(f.read_text(encoding="utf-8"))
    a["decisiones"] = []
    f.write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")
    import carpetas
    registro.sincronizar(C, carpetas.docs(ms(app)))
    assert not any(x["campos"].get("huerfano") for t in poblar.VISTAS.values() for x in de(t[0]))
    assert sum(bool(x["campos"].get("huerfano")) for x in registro.listar(C, "decision")) == 2


def test_endpoint_cola_y_estado(cl, monkeypatch):
    t, app = cl
    monkeypatch.setattr(app, "falta", lambda *a, **k: None)
    monkeypatch.setattr(app, "_llm_ctx", lambda d, mids=(), glos=(): lambda: contextlib.nullcontext(chat))
    assert t.post("/api/reg/poblar", json={"c": C, "vistas": ["nada"]}).status_code == 400
    assert t.post("/api/reg/poblar", json={"c": C, "mid": "zzz"}).status_code == 404
    q = t.post("/api/reg/poblar", json={"c": C, "vistas": ["requisitos", "preguntas"]}).json()["id"]
    for _ in range(200):
        e = next(e for e in t.get("/api/cola").json()["items"] if e["id"] == q)
        if e["state"] not in ("pendiente", "marcha"):
            break
        time.sleep(0.05)
    assert e["state"] == "hecho" and e["result"]["creadas"] == {"requisito": 1, "pregunta": 1}, e
    est = t.get("/api/reg/poblar/estado", params={"c": C}).json()
    # modelo local (sin nube): una llamada por vista y reunión
    assert est["en_cola"] is False and est["ultimo"]["llamadas"] == 4 and est["ultimo"]["vistas"] == ["requisitos", "preguntas"]
    it = t.get("/api/reg", params={"c": C, "tipo": "requisito"}).json()["items"]
    assert it[0]["citas"][0]["verificada"] and it[0]["revision"] == "propuesto" and not it[0]["huerfano"]
    # Ctrl+Z no quita la pasada (lote auto); deshacer_pasada la quita entera (un lote)
    assert t.post("/api/reg/deshacer", json={"c": C}).json()["revertidas"] == 0 and de("requisito")
    assert registro.deshacer_pasada(C, est["ultimo"]["lote"]) == 2 and not de("requisito")


def test_auto_tras_el_documento(cl, monkeypatch):
    """Al terminar un documento de una carpeta se encola `poblar` de esa reunión, salvo con el ajuste poblar_auto apagado."""
    t, app = cl
    pedidos = []
    monkeypatch.setattr(app, "start", lambda kind, spec, video, mid="": pedidos.append((kind, spec, mid)))
    monkeypatch.setattr(app.carpetas, "seguimiento", lambda *a, **k: 0)
    monkeypatch.setattr(app.pipeline, "run", lambda *a, **k: (pipeline.WORK / MIDS[1] / "acta_normal_imp1", None, None))
    d = {"carpeta": C, "transcripcion": "x.vtt", "nube": {"proveedor": "cli:claude"}}
    carpetas.guardar_datos(C, "Proyecto", [])
    app._acta_fn(d)(lambda f, m: None)
    assert pedidos == [("poblar", {"nube": {"proveedor": "cli:claude"}, "c": C, "mid": MIDS[1], "auto": True}, MIDS[1])]
    assert t.post("/api/ajustes", json={"poblar_auto": False}).json()["poblar_auto"] is False
    app._acta_fn(d)(lambda f, m: None)
    assert len(pedidos) == 1


def test_seguidos_no_se_funden(cl):
    """Dos requisitos distintos en segmentos seguidos (02:00 y 02:06) son dos entidades (fallo visto en la pasada real)."""
    _, app = cl
    rq = lambda q, t: {"cita": q, "texto": t, "tipo_req": "—", "prioridad": "—", "solicitante": "—"}
    r = {"requisitos": [rq("la aplicación debe permitir pagar con Bizum", "La aplicación debe permitir pagar con Bizum"),
                        rq("la búsqueda tiene que responder en menos de dos segundos", "La búsqueda debe responder en menos de dos segundos")]}
    info = poblar.poblar(C, ms(app), lambda: contextlib.nullcontext(lambda *a, **k: json.loads(json.dumps(r))), mids=[MIDS[0]], vistas=["requisitos"])
    assert info["creadas"] == {"requisito": 2}


def chat_vistas(sistema, user, schema, max_tokens, temperature=0.2):
    """Como chat, pero solo devuelve las vistas del esquema (el modelo local recibe un esquema de una vista)."""
    chat.n += 1
    return {v: json.loads(json.dumps(R))[v] for v in schema["properties"]}


def test_local_una_llamada_por_vista(cl):
    _, app = cl
    r = poblar.poblar(C, ms(app), lambda: contextlib.nullcontext(chat_vistas), local=True)
    assert r["llamadas"] == 2 * len(poblar.VISTAS) == chat.n and r["creadas"] == {"requisito": 1, "interesado": 1, "riesgo": 1, "pregunta": 1}
    chat.n = 0
    r = poblar.poblar(C, ms(app), lambda: contextlib.nullcontext(chat_vistas), local=False)
    assert r["llamadas"] == 2 == chat.n  # nube/CLI: una llamada combinada por bloque


def test_interesado_sin_rol_fuera():
    segs = [{"s": 0, "e": 5, "text": "Elena Ruiz, la directora comercial de Hoteles Sol, y Pedro Gil estaban."}]
    r = {"interesados": [{"cita": "Elena Ruiz, la directora comercial", "texto": "Elena Ruiz", "rol": "—", "organizacion": "Hoteles Sol"},
                         {"cita": "Elena Ruiz, la directora comercial", "texto": "Elena", "rol": "directora comercial", "organizacion": "—"}]}
    ok = poblar.comprobar(r, segs, segs[0]["text"], ["interesados"])
    assert [it["texto"] for _, it in ok] == ["Elena"]


@pytest.mark.parametrize("tipo, esperado", [("Obra", 0), ("Paciente", 0), ("Candidato", 0), ("Proyecto", 1)])
def test_auto_solo_en_carpetas_proyecto(cl, monkeypatch, tipo, esperado):
    """El auto-poblar solo corre en carpetas «Proyecto»; nunca en las sensibles."""
    _, app = cl
    pedidos = []
    monkeypatch.setattr(app, "start", lambda kind, spec, video, mid="": pedidos.append(kind))
    monkeypatch.setattr(app.carpetas, "seguimiento", lambda *a, **k: 0)
    monkeypatch.setattr(app.pipeline, "run", lambda *a, **k: (pipeline.WORK / MIDS[1] / "acta_normal_imp1", None, None))
    carpetas.guardar_datos(C, tipo, [])
    app._acta_fn({"carpeta": C, "transcripcion": "x.vtt"})(lambda f, m: None)
    assert len(pedidos) == esperado


def test_poblar_manual_rechaza_sensibles(cl, monkeypatch):
    t, app = cl
    monkeypatch.setattr(app, "falta", lambda *a, **k: None)
    monkeypatch.setattr(app, "start", lambda *a, **k: {"id": "x"})
    carpetas.guardar_datos(C, "Paciente", [])
    r = t.post("/api/reg/poblar", json={"c": C})
    assert r.status_code == 400 and "sensible" in r.json()["detail"]
    carpetas.guardar_datos(C, "Obra", [])
    assert t.post("/api/reg/poblar", json={"c": C}).status_code == 200
