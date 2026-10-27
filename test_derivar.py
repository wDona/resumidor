"""Pruebas de derivar.py (F5) con chat falso: el requisito sale de poblar (test_poblar) sobre tests_data/reunion.vtt. Sin LLM."""
import contextlib
import json
import time

import carpetas
import derivar
import nube
import pipeline
import poblar
import registro
from test_poblar import C, cl, correr, ms  # noqa: F401  (cl: fixture)

D = {"historias": [
    {"como": "Elena Ruiz", "quiero": "pagar con Bizum en la aplicación", "para": "—", "criterios": [
        {"escenario": "Pago con Bizum", "dado": "Dado que el cliente está pagando", "cuando": "elige Bizum", "entonces": "la aplicación permite pagar con Bizum"},
        {"escenario": "Importe máximo", "dado": "un pago con Bizum", "cuando": "supera 500 euros", "entonces": "se rechaza"},
        {"escenario": "Pasarela", "dado": "un pago con Bizum", "cuando": "se confirma", "entonces": "lo procesa Redsys"}]},
    {"como": "director financiero", "quiero": "cobrar 30 euros de comisión por pago", "para": "—", "criterios": [
        {"escenario": "Comisión", "dado": "un pago", "cuando": "se cobra", "entonces": "se añade la comisión"}]}],
     "preguntas": ["¿Qué importe máximo admite el pago con Bizum?", "¿Se cobra la comisión de 2 euros?", "¿Lo valida Redsys?"]}


def chat(sistema, user, schema, max_tokens, temperature=0.2):
    chat.n += 1
    chat.user = user
    assert not nube.valida(D, schema)
    return json.loads(json.dumps(D))


ctx = lambda: contextlib.nullcontext(chat)


def base(app):
    chat.n = 0
    correr(app, vistas=["requisitos"])
    return registro.listar(C, "requisito")[0]


def der(tipo, **f):
    return [x for x in registro.listar(C, tipo, **f) if x["campos"].get("fuente") == "derivar"]


def test_prompt_y_esquema():
    req = {"codigo": "REQ-001", "titulo": "Pagar con Bizum", "detalle": "", "prioridad": "", "campos": {"tipo_req": "funcional", "solicitante": "—"}}
    sis, usr = derivar.prompt(req, ["la aplicación debe permitir pagar con Bizum"], ["Bizum"])
    assert "SOLO" in sis and "pregunta en vez de inventarlo" in sis and "«usuario»" in sis and "Bizum" in sis
    assert "REQ-001 (tipo: funcional)" in usr and "«la aplicación debe permitir pagar con Bizum»" in usr and "solicitante" not in usr
    assert pipeline.gbnf(derivar.ESQUEMA) and "{" not in sis.format(lang="español").replace("{lang}", "")


def test_inventado():
    f = "La aplicación debe permitir pagar con Bizum. Elena Ruiz"
    assert derivar.inventado(["Pagar con Bizum", "Elena Ruiz lo pide", "La aplicación paga"], f) == []
    assert derivar.inventado(["supera 500 euros", "lo procesa Redsys", "¿Lo valida Redsys?"], f) == ["500", "Redsys", "Redsys"]


def test_deriva_con_cita_relacion_y_preguntas(cl):
    _, app = cl
    req = base(app)
    r = derivar.derivar(C, ctx)
    assert r["llamadas"] == 1 and r["creadas"] == {"historia": 1, "pregunta": 1} and r["descartadas"] == 3 and "REQ-001" in chat.user
    h = der("historia")[0]
    assert (h["origen"], h["revision"], h["estado"]) == ("derivado", "propuesto", "backlog")
    k = h["campos"]
    assert (k["como"], k["quiero"], k["para"], k["epica"], k["puntos"]) == ("Elena Ruiz", "pagar con Bizum en la aplicación", "", "REQ-001", "")
    # el criterio con 500 € y el de Redsys (no se dicen) fuera; «Dado que…» sin la palabra clave
    assert k["criterios"] == [{"escenario": "Pago con Bizum", "dado": "el cliente está pagando", "cuando": "elige Bizum", "entonces": "la aplicación permite pagar con Bizum", "propuesta": True}]
    # cita heredada (las dos reuniones) y deriva_de
    assert sorted((c["mid"], c["texto"]) for c in registro.citas(h["id"])) == sorted((c["mid"], c["texto"]) for c in registro.citas(req["id"]))
    rel = registro.completas([h])[0]["relaciones"]
    assert rel == [{"a": h["id"], "b": req["id"], "tipo": "deriva_de", "propuesta": False}]
    p = der("pregunta")[0]
    assert p["titulo"] == "¿Qué importe máximo admite el pago con Bizum?" and p["campos"]["fuente_req"] == "REQ-001" and p["origen"] == "derivado"
    assert registro.completas([p])[0]["relaciones"][0]["tipo"] == "afecta" and registro.citas(p["id"])
    assert carpetas.leer(C)["derivar"]["requisitos"] == ["REQ-001"]


def test_rol_no_dicho_es_usuario(cl):
    _, app = cl
    base(app)
    D2 = {"historias": [{"como": "gestor de reservas", "quiero": "pagar con Bizum", "para": "—", "criterios": []}], "preguntas": []}
    derivar.derivar(C, lambda: contextlib.nullcontext(lambda *a, **k: json.loads(json.dumps(D2))))
    assert der("historia")[0]["campos"]["como"] == "usuario"


def test_sin_duplicar_resucitar_ni_pisar(cl):
    _, app = cl
    req = base(app)
    derivar.derivar(C, ctx)
    assert derivar.derivar(C, ctx)["llamadas"] == 0  # por defecto: solo requisitos sin historias
    r = derivar.derivar(C, ctx, ids=[req["id"]])
    assert r["creadas"] == {} and r["omitidas"] == 2
    h, p = der("historia")[0], der("pregunta")[0]
    registro.editar(h["id"], {"titulo": "Editada a mano"})
    registro.borrar(p["id"])
    r = derivar.derivar(C, ctx, ids=[req["id"]])
    assert r["creadas"] == {} and registro.de(C, h["id"])["titulo"] == "Editada a mano" and len(der("pregunta")) == 1
    assert der("pregunta")[0]["revision"] == "descartado"


def test_no_huerfanas_y_deshacer(cl):
    _, app = cl
    base(app)
    info = derivar.derivar(C, ctx)
    registro.sincronizar(C, carpetas.docs(ms(app)))
    assert not any(x["campos"].get("huerfano") for t in ("historia", "pregunta") for x in der(t))
    assert registro.deshacer(C) == 0 and der("historia")  # la pasada es un lote auto: Ctrl+Z no la quita
    assert registro.deshacer_pasada(C, info["lote"]) == 2 and not der("historia") and not der("pregunta")


def test_endpoint_cola_y_estado(cl, monkeypatch):
    t, app = cl
    monkeypatch.setattr(app, "falta", lambda *a, **k: None)
    monkeypatch.setattr(app, "_llm_ctx", lambda d, mids=(), glos=(): ctx)
    assert t.post("/api/reg/derivar", json={"c": C}).status_code == 400  # aún no hay requisitos
    req = base(app)
    assert t.post("/api/reg/derivar", json={"c": C, "ids": ["nada"]}).status_code == 400
    q = t.post("/api/reg/derivar", json={"c": C, "ids": [req["id"]]}).json()["id"]
    for _ in range(200):
        e = next(e for e in t.get("/api/cola").json()["items"] if e["id"] == q)
        if e["state"] not in ("pendiente", "marcha"):
            break
        time.sleep(0.05)
    assert e["state"] == "hecho" and e["result"]["creadas"] == {"historia": 1, "pregunta": 1}, e
    est = t.get("/api/reg/derivar/estado", params={"c": C}).json()
    assert est["en_cola"] is False and est["ultimo"]["llamadas"] == 1
    it = t.get("/api/reg", params={"c": C, "tipo": "historia"}).json()["items"]
    assert it[0]["citas"] and it[0]["relaciones"][0]["tipo"] == "deriva_de"
    assert t.post("/api/reg/derivar", json={"c": C}).status_code == 400  # ya no quedan requisitos sin historias


def test_encadenado_tras_poblar_auto(cl, monkeypatch):
    _, app = cl
    pedidos = []
    monkeypatch.setattr(app, "start", lambda kind, spec, video, mid="": pedidos.append((kind, spec)))
    monkeypatch.setattr(app, "_llm_ctx", lambda d, mids=(), glos=(): lambda: contextlib.nullcontext(poblar_chat))
    from test_poblar import chat as poblar_chat
    poblar_chat.n = 0
    app._poblar_fn({"c": C, "vistas": ["requisitos"], "nube": {"proveedor": "cli:claude"}, "auto": True})(lambda f, m: None)
    req = registro.listar(C, "requisito")[0]
    assert pedidos == [("derivar", {"nube": {"proveedor": "cli:claude"}, "c": C, "ids": [req["id"]], "auto": True})]
    app._poblar_fn({"c": C, "vistas": ["requisitos"], "auto": True})(lambda f, m: None)  # sin requisitos nuevos: nada
    app._poblar_fn({"c": C, "vistas": ["requisitos"]})(lambda f, m: None)  # manual sin requisitos nuevos: nada
    assert len(pedidos) == 1 and poblar.VISTAS


def test_encadenado_tras_poblar_manual(cl, monkeypatch):
    _, app = cl
    pedidos = []
    monkeypatch.setattr(app, "start", lambda kind, spec, video, mid="": pedidos.append((kind, spec)))
    monkeypatch.setattr(app, "_llm_ctx", lambda d, mids=(), glos=(): lambda: contextlib.nullcontext(poblar_chat))
    from test_poblar import chat as poblar_chat
    poblar_chat.n = 0
    app._poblar_fn({"c": C, "vistas": ["requisitos"], "gpu": 1})(lambda f, m: None)
    req = registro.listar(C, "requisito")[0]
    assert pedidos == [("derivar", {"gpu": 1, "c": C, "ids": [req["id"]]})]


def test_como_usa_el_rol_del_interesado(cl):
    _, app = cl
    req = base(app)
    registro.editar(req["id"], {"campos": {**req["campos"], "solicitante": "Elena"}})
    registro.crear(C, "interesado", titulo="Elena Ruiz", revision="aprobado", origen="manual", campos={"rol": "directora de tienda"})
    assert derivar.rol_de(C, "Elena") == "directora de tienda" and derivar.rol_de(C, "Pedro") == "" and derivar.rol_de(C, "—") == ""
    req = registro.de(C, req["id"])
    _, usr = derivar.prompt(req, [], rol="directora de tienda")
    assert "rol del solicitante: directora de tienda" in usr
    derivar.derivar(C, ctx)
    assert der("historia")[0]["campos"]["como"] == "directora de tienda"
