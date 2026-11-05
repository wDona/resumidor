"""Pruebas de destinos.py / destinos_tipos.py: servidor HTTP falso local que captura peticiones (webhook, GitHub, Jira, Linear, Notion, Todoist, WebDAV, Slack, Teams,
Power Automate), carpeta en tmp, planes/recetas (al terminar y programadas con reloj inyectado), descargas y SigV4 con el vector de AWS. Sin red ni llavero real."""

import datetime as dt
import hashlib
import hmac
import io
import json
import ssl
import threading
import time
import types
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import destinos

HILO = destinos._hilo
import destinos_tipos as T
import registro
import test_carpetas as TC
from test_carpetas import C, cl  # noqa: F401


class Mock:
    def __init__(self):
        self.reqs, self.n = [], 0
        m = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def go(self):
                b = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                m.reqs.append({"m": self.command, "p": self.path, "h": dict(self.headers), "b": b})
                r = m.resp(self.command, self.path, b)
                d = json.dumps(r).encode() if r is not None else b""
                self.send_response(201 if self.command in ("PUT", "MKCOL") else 200)
                self.send_header("Content-Length", str(len(d)))
                self.end_headers()
                self.wfile.write(d)

            do_GET = do_POST = do_PUT = do_PATCH = do_MKCOL = do_PROPFIND = go

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def resp(self, met, p, b):
        if "/issues" in p:
            if met == "PATCH":
                n = int(p.rsplit("/", 1)[1])
            else:
                self.n += 1
                n = self.n
            return {"number": n, "html_url": f"{self.url}/i/{n}"}
        if "/rest/api/" in p and met == "POST":
            self.n += 1
            return {"key": f"P-{self.n}"}
        if p == "/graphql":
            return {"data": {"issueCreate": {"success": True, "issue": {"id": "L1", "url": f"{self.url}/l/1"}}}}
        if p == "/v1/pages":
            return {"id": "pg1", "url": f"{self.url}/n/pg1"}
        if p.endswith("/tasks"):
            self.n += 1
            return {"id": str(self.n), "url": f"{self.url}/t/{self.n}"}
        if "getUploadURLExternal" in p:
            return {"ok": True, "upload_url": f"{self.url}/up", "file_id": "F1"}
        if "completeUploadExternal" in p:
            return {"ok": True}
        return {"ok": True} if met in ("GET", "POST") else None


@pytest.fixture()
def mk():
    m = Mock()
    yield m
    m.srv.shutdown()


@pytest.fixture()
def E(cl, monkeypatch):  # noqa: F811
    t, app = cl
    mem = {}
    kr = types.SimpleNamespace(
        get_password=lambda s, k: mem.get((s, k)),
        set_password=lambda s, k, v: mem.__setitem__((s, k), v),
        delete_password=lambda s, k: mem.pop((s, k), None),
        errors=types.SimpleNamespace(PasswordDeleteError=KeyError, KeyringError=OSError),
    )
    monkeypatch.setattr(destinos, "_kr", lambda: kr)
    monkeypatch.setattr(destinos, "_docs_inf", lambda c: ())
    registro.sincronizar(C, TC.carpetas.docs(app._ms(C)))
    return t, mem


def dest(t, tipo, **cfg):
    return t.post("/api/destinos", json={"tipo": tipo, "nombre": tipo, "config": cfg}).json()["id"]


def enviar(t, d, que, **k):
    return t.post("/api/enviar", json={"destino": d, "que": que, "c": C, **k}).json()


def test_secretos_fuera_del_json_y_catalogo(E, mk):
    t, mem = E
    i = dest(t, "github", token="SECRETO-TK", repo="o/r", url=mk.url)
    assert "SECRETO-TK" not in destinos.CFG().read_text(encoding="utf-8") and mem[(destinos.SERV, f"{i}:token")] == "SECRETO-TK"
    cat = t.get("/api/destinos").json()
    assert {
        "github",
        "gitlab",
        "gitea",
        "jira",
        "linear",
        "notion",
        "todoist",
        "trello",
        "azure",
        "webdav",
        "s3",
        "sftp",
        "correo",
        "slack",
        "teams",
        "power_automate",
        "webhook",
        "carpeta",
    } <= set(cat["tipos"])
    assert cat["destinos"][0]["secretos"] == {"token": True} and "token" not in cat["destinos"][0]["config"]
    assert any(f["id"] == "verificar_tls" for f in cat["tipos"]["github"]["campos"])
    assert t.post(f"/api/destinos/{i}/probar").json()["ok"]
    assert t.delete(f"/api/destinos/{i}").json()["ok"] and (destinos.SERV, f"{i}:token") not in mem


def test_github_una_por_item_idempotente_y_actualiza(E, mk):
    t, _ = E
    i = dest(t, "github", token="tk", repo="o/r", etiquetas="actas", url=mk.url)
    r = enviar(t, i, ["tareas"])
    assert r["estado"] == "ok" and len(r["items"]) == 5 and {x["accion"] for x in r["items"]} == {"creado"} and r["enlaces"][0].startswith(mk.url)
    rq = [x for x in mk.reqs if x["m"] == "POST"]
    b = json.loads(rq[0]["b"])
    assert rq[0]["h"]["Authorization"] == "token tk" and b["labels"] == ["actas"] and "Origen:" in b["body"] and "Responsable" in b["body"]
    n = len(mk.reqs)
    assert {x["accion"] for x in enviar(t, i, ["tareas"])["items"]} == {"omitido"} and len(mk.reqs) == n  # reenviar no duplica ni llama
    x = next(x for x in registro.listar(C, "tarea") if x["titulo"].startswith("Arreglar"))
    registro.editar(x["id"], {"titulo": "Arreglar la puerta del garaje YA"})
    r = enviar(t, i, ["tareas"])
    assert sorted(y["accion"] for y in r["items"]) == ["actualizado"] + ["omitido"] * 4 and any(q["m"] == "PATCH" for q in mk.reqs)
    h = t.get("/api/envios").json()
    assert len(h) == 3 and h[0]["estado"] == "ok"


def test_solo_aprobados_y_error_reintentar(E, mk):
    t, _ = E
    i = dest(t, "github", token="tk", repo="o/r", url=mk.url)
    r = enviar(t, i, ["tareas"], solo_aprobados=True)
    assert r["estado"] == "error" and "Nada que enviar" in r["error"]  # las del acta están propuestas
    j = dest(t, "github", token="tk", repo="o/r", url="http://127.0.0.1:9")
    r = enviar(t, j, ["decisiones"])
    assert r["estado"] == "error" and "Sin conexión" in r["error"] and t.get("/api/envios").json()[0]["reintentable"]
    t.patch(f"/api/destinos/{j}", json={"config": {"url": mk.url}})
    r2 = t.post(f"/api/envios/{r['id']}/reintentar").json()
    assert r2["estado"] == "ok" and r2["de"] == r["id"]


def test_webhook_firma_hmac_y_json(E, mk):
    t, _ = E
    i = dest(t, "webhook", url=mk.url + "/hook", firma="clave", cabeceras='{"X-Extra":"1"}')
    r = enviar(t, i, ["decisiones", "resumen"], doc="aaaa1111")
    assert r["estado"] == "ok"
    q = mk.reqs[-1]
    assert q["h"]["X-Actas-Signature"] == "sha256=" + hmac.new(b"clave", q["b"], hashlib.sha256).hexdigest() and q["h"]["X-Extra"] == "1"
    j = json.loads(q["b"])
    assert (
        j["origen"] == "actas"
        and j["resumen"]
        and j["items"][0]["tipo"] == "decision"
        and "Junta" in j["items"][0]["origen"]
        and j["items"][0]["enlaces"][0].startswith("/api/vista/")
    )
    assert enviar(t, i, ["decisiones", "resumen"], doc="aaaa1111")["items"][0]["accion"] == "omitido"
    # la transcripción solo va en lo maquetado (html, docx, pdf) o aparte (srt/vtt): nunca en texto (JSON, Discord, Teams, .md)
    assert enviar(t, i, ["documento"], doc="aaaa1111")["estado"] == "ok"
    j = json.loads(mk.reqs[-1]["b"])
    assert "Junta de enero" in j["texto"] and "Buenos días a todos" not in j["texto"] and "Capturas" not in j["texto"]
    d = dest(t, "webhook", url=mk.url + "/discord", mensaje="discord")
    assert enviar(t, d, ["documento"], doc="aaaa1111")["estado"] == "ok" and "Buenos días a todos" not in json.loads(mk.reqs[-1]["b"])["content"]
    tt = dest(t, "teams", webhook=mk.url + "/teams-doc")
    assert enviar(t, tt, ["documento"], doc="aaaa1111")["estado"] == "ok"
    card = json.dumps(json.loads(mk.reqs[-1]["b"]), ensure_ascii=False)
    assert "Junta de enero" in card and "Hoy hablamos del ascensor" not in card and "Ver vídeo" not in card
    import destinos

    vid = TC.pipeline.WORK / "aaaa1111" / "video.mp4"
    vid.write_bytes(b"")
    try:  # con grabación: enlace al vídeo al pie de la tarjeta
        assert enviar(t, dest(t, "teams", webhook=mk.url + "/teams-loc"), ["documento"], doc="aaaa1111")["estado"] == "ok"
        assert "actions" not in json.loads(mk.reqs[-1]["b"])["attachments"][0]["content"]  # sin url_base pública: el enlace solo abriría aquí
        destinos._escribir(destinos.CFG(), {**destinos.cfg(), "url_base": "https://actas.example.com/"})
        assert enviar(t, dest(t, "teams", webhook=mk.url + "/teams-vid"), ["documento"], doc="aaaa1111")["estado"] == "ok"
        ac = json.loads(mk.reqs[-1]["b"])["attachments"][0]["content"]["actions"]
        assert ac[0]["title"] == "Ver vídeo" and ac[0]["url"] == "https://actas.example.com/files/aaaa1111/video.mp4"
    finally:
        vid.unlink()
        destinos._escribir(destinos.CFG(), {**destinos.cfg(), "url_base": ""})
    import exportar

    ver = next(p.name for p in (TC.pipeline.WORK / "aaaa1111").glob("acta_*"))
    c = exportar.carga("aaaa1111", ver, False)
    assert "Buenos días a todos" not in exportar.md(c) and "Buenos días a todos" in exportar.html_doc(c)
    assert "Buenos días a todos" in exportar.exportar("aaaa1111", ver, "vtt")[0].decode()  # aparte, como documento propio
    import destinos

    ext, b = destinos._gen({"mid": "aaaa1111", "ver": ver}, "transcripcion", "md", False, False, [])
    assert ext == "md" and "Buenos días a todos" in b.decode() and b.decode().startswith("# Transcripción")


def test_jira_linear_todoist_notion(E, mk):
    t, _ = E
    j = dest(t, "jira", url=mk.url, modo="cloud", email="a@b.c", token="jt", proyecto="PRJ")
    r = enviar(t, j, ["decisiones"], doc="bbbb2222")
    assert r["estado"] == "ok" and r["enlaces"][0] == f"{mk.url}/browse/P-1"
    q = next(x for x in mk.reqs if "/rest/api/3/issue" in x["p"])
    assert (
        q["h"]["Authorization"].startswith("Basic ")
        and json.loads(q["b"])["fields"]["description"]["type"] == "doc"
        and json.loads(q["b"])["fields"]["project"] == {"key": "PRJ"}
    )
    s = dest(t, "jira", url=mk.url, modo="server", token="pat", proyecto="PRJ")
    enviar(t, s, ["decisiones"], doc="bbbb2222")
    q = [x for x in mk.reqs if "/rest/api/2/issue" in x["p"]][0]
    assert q["h"]["Authorization"] == "Bearer pat" and isinstance(json.loads(q["b"])["fields"]["description"], str)
    li = dest(t, "linear", url=mk.url + "/graphql", token="lin_key", equipo="TEAM")
    assert enviar(t, li, ["decisiones"], doc="bbbb2222")["estado"] == "ok"
    q = [x for x in mk.reqs if x["p"] == "/graphql"][0]
    assert q["h"]["Authorization"] == "lin_key" and json.loads(q["b"])["variables"]["i"]["teamId"] == "TEAM"
    td = dest(t, "todoist", url=mk.url + "/rest/v2", token="td", proyecto="123")
    assert (
        enviar(t, td, ["tareas"], doc="aaaa1111")["estado"] == "ok"
        and json.loads([x for x in mk.reqs if x["p"].endswith("/tasks")][0]["b"])["project_id"] == "123"
    )
    nt = dest(t, "notion", url=mk.url, token="nt", padre="PAD")
    assert enviar(t, nt, ["documento"], doc="aaaa1111")["estado"] == "ok"
    q = [x for x in mk.reqs if x["p"] == "/v1/pages"][0]
    assert q["h"]["Notion-Version"] and json.loads(q["b"])["parent"] == {"page_id": "PAD"}


def test_notion_limites_bloques():
    bl = T._bloques("# T\n" + "x" * 4500 + "\n" + "\n".join(f"- [ ] t{i}" for i in range(150)))
    assert (
        len(bl) == 152 and all(len(r["text"]["content"]) <= 2000 for b in bl for r in b[b["type"]]["rich_text"]) and len(bl[1]["paragraph"]["rich_text"]) == 3
    )


def test_webdav_docx_y_carpeta_vault(E, mk, tmp_path):
    t, _ = E
    w = dest(t, "webdav", url=mk.url + "/dav", usuario="u", clave="p", ruta="Actas/2026", formatos=["docx"])
    r = enviar(t, w, ["documento"], doc="aaaa1111")
    assert r["estado"] == "ok"
    puts = [x for x in mk.reqs if x["m"] == "PUT"]
    assert puts[0]["p"].endswith(".docx") and puts[0]["b"][:2] == b"PK" and [x["p"] for x in mk.reqs if x["m"] == "MKCOL"] == ["/dav/Actas", "/dav/Actas/2026"]
    assert puts[0]["h"]["Authorization"].startswith("Basic ")
    (tmp_path / "boveda").mkdir()
    c = dest(t, "carpeta", ruta=str(tmp_path / "boveda"), subcarpeta="Actas", vault=True)
    r = enviar(t, c, ["documento", "tareas"], doc="aaaa1111")
    assert r["estado"] == "ok"
    md = next((tmp_path / "boveda" / "Actas").glob("*.md")).read_text(encoding="utf-8")
    assert md.startswith("---\ntitle:") and "- [ ] Arreglar la puerta del garaje" in md and "[[" in md and "Origen:" in md
    (tmp_path / "ms").mkdir()
    c2 = dest(t, "carpeta", ruta=str(tmp_path / "ms"))
    enviar(t, c2, ["tareas", "documento"], doc="aaaa1111", formatos=["docx", "csv_jira", "md"])
    fs = list((tmp_path / "ms").iterdir())
    assert len(fs) >= 3 and any(p.suffix == ".docx" for p in fs) and any(p.name.endswith("tareas.jira.csv") for p in fs)


def test_slack_y_teams_payloads(E, mk):
    t, _ = E
    s = dest(t, "slack", webhook=mk.url + "/services/X/Y/Z", bot="xoxb", canal="C1", url=mk.url)
    r = enviar(t, s, ["resumen", "tareas", "decisiones"], doc="aaaa1111", formatos=["md", "docx"])
    assert r["estado"] == "ok"
    m = json.loads(next(x for x in mk.reqs if x["p"] == "/services/X/Y/Z")["b"])
    tx = json.dumps(m, ensure_ascii=False)
    assert (
        m["blocks"][0]["type"] == "header"
        and "☐" in tx
        and "Arreglar la puerta del garaje" in tx
        and "*Decisiones*" in tx
        and all(len(b["text"]["text"]) <= 3000 for b in m["blocks"][1:])
    )
    assert any("getUploadURLExternal" in x["p"] for x in mk.reqs) and any("completeUploadExternal" in x["p"] for x in mk.reqs)
    big = {"titulo": "T", "json": {"items": [{"tipo": "tarea", "titulo": f"tarea {i}", "dueno": "A", "fecha_limite": "x", "codigo": ""} for i in range(9000)]}}
    assert len(T.slack_mensajes(big)) > 1 and all(len(x["blocks"]) <= 40 for x in T.slack_mensajes(big))
    tm = T.teams_payload(
        {"titulo": "T", "json": {"items": [{"tipo": "tarea", "titulo": "y" * 200, "dueno": "A", "fecha_limite": "", "codigo": ""} for i in range(500)]}}
    )
    assert (
        tm["type"] == "message" and tm["attachments"][0]["contentType"] == "application/vnd.microsoft.card.adaptive" and len(json.dumps(tm).encode()) <= 27500
    )
    assert tm["attachments"][0]["content"]["body"][-1]["text"].startswith("… ver más")
    tt = dest(t, "teams", webhook=mk.url + "/teams")
    assert enviar(t, tt, ["tareas"], doc="aaaa1111")["estado"] == "ok" and json.loads(mk.reqs[-1]["b"])["attachments"][0]["content"]["type"] == "AdaptiveCard"


def test_power_automate(E, mk):
    t, _ = E
    p = dest(t, "power_automate", webhook=mk.url + "/pa", adjuntar=True)
    r = enviar(t, p, ["tareas", "documento"], doc="aaaa1111", formatos=["docx"])
    assert r["estado"] == "ok"
    j = json.loads(mk.reqs[-1]["b"])
    assert set(j) >= {"origen", "proyecto", "documento", "enlace_local", "elementos", "archivo"} and j["elementos"][0]["tipo"] == "tarea"
    assert set(j["elementos"][0]) == {"tipo", "titulo", "descripcion", "responsable", "fecha", "prioridad", "cita"}
    assert j["archivo"]["nombre"].endswith(".docx") and j["archivo"]["base64"]
    ay = [f for f in t.get("/api/destinos").json()["tipos"]["power_automate"]["campos"] if f["id"] == "webhook"][0]["ayuda"]
    assert '"elementos"' in ay


def test_anonimizacion_nunca_en_claro(E, mk):
    t, _ = E
    t.post("/api/reg", json={"c": C, "tipo": "riesgo", "titulo": "Avisar a juan.perez@correo.es del retraso", "detalle": "Tel 612 34 56 78"})
    i = dest(t, "webhook", url=mk.url + "/h")
    r = enviar(t, i, ["riesgos"], anonimizar=True)
    j = json.dumps(json.loads(mk.reqs[-1]["b"]))
    assert r["estado"] == "ok" and "juan.perez" not in j and "[EMAIL]" in j and "612 34" not in j
    n = len(mk.reqs)
    r = enviar(t, i, ["documento"], doc="aaaa1111", anonimizar=True)
    assert r["estado"] == "error" and "anonimizada" in r["error"] and len(mk.reqs) == n  # sin copia anonimizada: no sale nada
    assert enviar(t, i, ["informe"], anonimizar=True)["estado"] == "error"


def test_plan_documento_en_proyecto_y_nombre(E):
    plan = destinos.normalizar_plan(
        {
            "carpeta": C,
            "nombre": "Comité 28-oct",
            "salidas": [
                {"que": "decisiones", "como": "documento"},
                {"que": "tareas", "como": "documento", "nombre": "Pendientes"},
                {"que": "riesgos", "como": "destino", "destino": "nope"},
            ],
        }
    )
    assert plan["salidas"][2]["configurar"] and "configurar" not in plan["salidas"][0]
    es = destinos.ejecutar_plan(plan, {"doc": "bbbb2222"})
    assert [e["estado"] for e in es] == ["ok", "ok", "error"] and "sin destino" in es[2]["error"]
    import app as A

    assert {"Comité 28-oct – decisiones", "Pendientes"} <= {m["label"] for m in A.meetings() if m["carpeta"] == C}
    nuevo = next(m for m in A.meetings() if m["label"] == "Pendientes")
    assert nuevo["sin"] and (destinos.P.WORK / nuevo["id"] / "acta_normal_impdoc" / "index.html").is_file()
    n = len(A.meetings())
    destinos.ejecutar_plan(plan, {"doc": "bbbb2222"})
    assert len(A.meetings()) == n  # idempotente: reescribe, no duplica


def test_recetas_al_terminar_no_rompe(E, mk, monkeypatch):
    t, _ = E
    monkeypatch.setattr(destinos, "_hilo", lambda fn, *a: fn(*a))
    i = dest(t, "webhook", url=mk.url + "/r")
    p = t.post("/api/presets", json={"nombre": "Decisiones al hook", "destino": i, "que": ["decisiones"]}).json()["id"]
    rc = t.post(
        "/api/recetas",
        json={"nombre": "r", "activa": True, "cuando": {"carpeta": C, "plantilla": "Junta de vecinos / comunidad de propietarios"}, "presets": [p]},
    ).json()
    destinos.tras_documento("aaaa1111", "acta_normal_impaaaa", None, poblando=True)
    assert not mk.reqs  # esperaba a poblar
    destinos.tras_poblar(C, "aaaa1111")
    assert len(mk.reqs) == 1 and t.get("/api/envios").json()[0]["meta"] == {"receta": rc["id"]}
    t.patch(f"/api/recetas/{rc['id']}", json={"cuando": {"carpeta": "Otra"}})
    destinos.tras_documento("aaaa1111", "acta_normal_impaaaa", None)
    assert len(mk.reqs) == 1  # no coincide
    t.patch(f"/api/recetas/{rc['id']}", json={"activa": False})
    destinos.tras_documento(
        "aaaa1111", "acta_normal_impaaaa", {"salidas": [{"que": "decisiones", "como": "destino", "destino": "nope", "configurar": True}]}
    )  # plan roto: solo historial
    assert t.get("/api/envios").json()[0]["estado"] == "error"
    monkeypatch.setattr(destinos, "_hilo", HILO)  # el hilo de verdad (sin monkeypatch.undo(): devolvería WORK al work/ real)
    monkeypatch.setattr(destinos, "_auto", lambda *a: 1 / 0)
    destinos.tras_documento("x", "y")  # nunca lanza (el hilo registra el error)
    for _ in range(100):  # esperar al hilo antes de que acabe la prueba (y se restaure WORK)
        if any("division by zero" in e.get("error", "") for e in t.get("/api/envios").json()):
            break
        time.sleep(0.02)
    else:
        raise AssertionError("el hilo no registró el error")


def test_programada_reloj_inyectado_solo_nuevo_atrasado(E, mk):
    t, _ = E
    i = dest(t, "webhook", url=mk.url + "/s")
    p = t.post("/api/presets", json={"nombre": "dec", "destino": i, "que": ["decisiones"]}).json()["id"]
    ahora = dt.datetime.now().replace(second=0, microsecond=0)
    h = ahora - dt.timedelta(minutes=30)
    rc = t.post(
        "/api/recetas",
        json={
            "nombre": "sem",
            "activa": True,
            "cuando": {"tipo": "programado", "carpeta": C, "cada": "dia", "hora": f"{h.hour:02d}:{h.minute:02d}"},
            "presets": [p],
        },
    ).json()
    assert rc["proximo_iso"] and dt.datetime.fromisoformat(rc["proximo_iso"]) > ahora
    assert destinos.tick(ahora) == [] and not mk.reqs  # aún no toca
    futuro = dt.datetime.fromtimestamp(rc["proximo"]) + dt.timedelta(hours=2)  # la app estuvo cerrada: una sola ejecución, «atrasado»
    es = destinos.tick(futuro)
    assert len(es) == 1 and es[0]["estado"] == "ok" and es[0]["meta"]["atrasado"] is True and len(json.loads(mk.reqs[-1]["b"])["items"]) == 3
    r = next(x for x in t.get("/api/recetas").json() if x["id"] == rc["id"])
    assert r["ultimo_envio"] and r["atrasado"] and dt.datetime.fromisoformat(r["proximo_iso"]) > futuro
    n = len(mk.reqs)
    assert destinos.tick(dt.datetime.fromtimestamp(r["proximo"]) + dt.timedelta(minutes=1)) == [] and len(mk.reqs) == n  # solo nuevo: sin novedades, no envía
    destinos._poner_receta(rc["id"], ultimo_envio=__import__("time").time())
    __import__("time").sleep(0.05)  # reloj inyectado en el futuro: el «último envío» real se fija aquí
    t.post("/api/reg", json={"c": C, "tipo": "decision", "titulo": "Decisión nueva"})
    es = t.post(f"/api/recetas/{rc['id']}/ahora").json()
    assert len(es) == 1 and [x["titulo"] for x in json.loads(mk.reqs[-1]["b"])["items"]] == ["Decisión nueva"]
    assert destinos.proximo_tras({"cada": "semana", "dia_semana": 0, "hora": "09:00"}, dt.datetime(2026, 11, 3, 10, 0)) == dt.datetime(2026, 11, 9, 9, 0)
    assert destinos.proximo_tras({"cada": "mes", "dia_mes": 5, "hora": "08:30"}, dt.datetime(2026, 11, 3, 10, 0)) == dt.datetime(2026, 11, 5, 8, 30)
    assert t.post("/api/recetas", json={"cuando": {"tipo": "programado", "cada": "dia"}}).status_code == 400


def test_descargar_zip_unico_y_omitidos(E):
    t, _ = E
    r = t.post("/api/descargar", json={"docs": ["aaaa1111"], "que": ["documento"], "formatos": ["md"]})
    assert r.status_code == 200 and r.content.startswith(b"# ") and "Junta" in r.headers["content-disposition"]
    r = t.post(
        "/api/descargar",
        json={
            "docs": ["aaaa1111", "bbbb2222"],
            "c": C,
            "que": ["documento", "tareas", "decisiones", "resumen"],
            "formatos": ["md", "docx", "xlsx", "csv_jira", "srt"],
        },
    )
    z = zipfile.ZipFile(io.BytesIO(r.content))
    nombres = z.namelist()
    assert (
        "Junta de enero · documento.docx" in nombres
        and "Junta de enero · tareas.jira.csv" in nombres
        and f"{C} · decisiones.xlsx" in nombres
        and "Junta de febrero · resumen.md" in nombres
    )
    assert "LEEME.txt" in nombres and "documento · xlsx: combinación no válida" in z.read("LEEME.txt").decode()
    assert t.post("/api/descargar", json={"docs": ["aaaa1111"], "que": ["documento"], "formatos": ["xlsx"]}).status_code == 400
    o = t.get("/api/descargar/opciones").json()
    assert "docx" in o["que"]["documento"]["documento"] and "xlsx" in o["que"]["requisitos"]["proyecto"] and "csv_jira" in o["que"]["tareas"]["documento"]
    ids = [x["id"] for x in registro.listar(C, "decision")][:1]
    r = t.post("/api/descargar", json={"c": C, "ids": ids, "que": ["decisiones"], "formatos": ["json"]})
    assert len(json.loads(r.content)) == 1


def test_descargar_respeta_anonimizacion(E):
    t, _ = E
    r = t.post("/api/descargar", json={"docs": ["aaaa1111"], "que": ["documento"], "formatos": ["docx"], "anon": True})
    assert r.status_code == 400 and "anonimiz" in r.json()["detail"]
    r = t.post("/api/descargar", json={"c": C, "que": ["decisiones", "informe"], "formatos": ["docx", "md"], "anon": True})
    assert r.status_code == 200 and r.content.startswith(b"# ")  # solo el md propio (anonimizado); docx del registro e informe se omiten


def test_sigv4_vector_aws():
    h = {"host": "example.amazonaws.com", "x-amz-date": "20150830T123600Z"}
    a = T.sigv4(
        "GET",
        "/",
        "",
        h,
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "AKIDEXAMPLE",
        "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
        "us-east-1",
        "service",
        "20150830T123600Z",
    )
    assert a == (
        "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, SignedHeaders=host;x-amz-date, "
        "Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"
    )


def test_s3_put_firmado(E, mk):
    t, _ = E
    s = dest(t, "s3", endpoint=mk.url, bucket="bk", prefijo="actas", region="eu-west-1", acceso="AK", secreto="SK")
    r = enviar(t, s, ["tareas"], doc="aaaa1111")
    assert r["estado"] == "ok"
    q = [x for x in mk.reqs if x["m"] == "PUT"][0]
    assert (
        q["p"].startswith("/bk/actas/")
        and q["h"]["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AK/")
        and "eu-west-1/s3/aws4_request" in q["h"]["Authorization"]
    )
    assert t.post(f"/api/destinos/{s}/probar").json()["ok"]


def test_sftp_openssh_sin_contrasenas(E, monkeypatch):
    t, _ = E
    calls = []

    def run(cmd, input=None, **k):
        calls.append((cmd, input))
        return types.SimpleNamespace(returncode=0, stdout="256 SHA256:abc host (ED25519)" if cmd[0] == "ssh-keygen" else "", stderr="")

    monkeypatch.setattr(T.subprocess, "run", run)
    monkeypatch.setattr(T.shutil, "which", lambda c: "/usr/bin/" + c)
    s = dest(t, "sftp", host="vps.local", usuario="deploy", puerto=2222, clave="~/.ssh/id", dir="/srv/actas", comando="")
    r = enviar(t, s, ["tareas"], doc="aaaa1111", formatos=["md"])
    assert r["estado"] == "ok" and len(calls) == 1
    cmd, inp = calls[0]
    assert (
        cmd[0] == "sftp"
        and "-P" in cmd
        and "2222" in cmd
        and "BatchMode=yes" in cmd
        and "StrictHostKeyChecking=accept-new" in cmd
        and cmd[-1] == "deploy@vps.local"
        and "-i" in cmd
    )
    assert 'put "' in inp and '"/srv/actas/' in inp
    pr = t.post(f"/api/destinos/{s}/probar").json()
    assert pr["ok"] and "SHA256:abc" in pr["mensaje"]
    j = dest(t, "sftp", host="h", usuario="u", dir="/x; rm -rf /", comando="")
    assert enviar(t, j, ["tareas"], doc="aaaa1111")["estado"] == "error"
    k = dest(t, "sftp", host="h", usuario="u", dir="/ok", comando="systemctl reload app")
    calls.clear()
    enviar(t, k, ["tareas"], doc="aaaa1111")
    assert [c[0][0] for c in calls] == ["sftp", "ssh"]


def test_tls_toggle_y_gitea(E, mk, monkeypatch):
    t, _ = E
    seen, orig = [], T.http
    monkeypatch.setattr(T, "http", lambda *a, **k: (seen.append(getattr(T._L, "ctx", None)), orig(*a, **k))[1])
    g = dest(t, "gitea", url=mk.url, token="g", repo="o/r", verificar_tls=False)
    assert enviar(t, g, ["decisiones"], doc="bbbb2222")["estado"] == "ok" and seen and seen[0] is not None and seen[0].verify_mode == ssl.CERT_NONE
    assert t.post(f"/api/destinos/{g}/probar").json()["aviso"]
    seen.clear()
    g2 = dest(t, "gitea", url=mk.url, token="g", repo="o/r")
    enviar(t, g2, ["decisiones"], doc="bbbb2222")
    assert seen[0] is None and [x for x in mk.reqs if "/api/v1/repos/o/r/issues" in x["p"]]


def test_sugerencias_microsoft(tmp_path, monkeypatch):
    for d in ("OneDrive - Contoso", "OneDrive", "Contoso/Ventas - Documentos", "Otra/X - Y"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "Library/CloudStorage/OneDrive-Personal").mkdir(parents=True)
    monkeypatch.setattr(destinos.Path, "home", lambda: tmp_path)
    for k in ("OneDriveCommercial", "OneDriveConsumer", "OneDrive"):
        monkeypatch.delenv(k, raising=False)
    s = {x["nombre"]: x["tipo"] for x in destinos.sugerencias()}
    assert s == {"OneDrive": "onedrive", "OneDrive - Contoso": "onedrive", "Ventas - Documentos": "sharepoint", "OneDrive-Personal": "onedrive"}


def test_presets_crud(E, mk):
    t, _ = E
    i = dest(t, "webhook", url=mk.url)
    assert t.post("/api/presets", json={"nombre": "x", "destino": "nope", "que": ["tareas"]}).status_code == 400
    assert t.post("/api/presets", json={"nombre": "x", "destino": i, "que": ["nada"]}).status_code == 400
    p = t.post("/api/presets", json={"nombre": "x", "destino": i, "que": ["tareas"], "solo_aprobados": True}).json()
    assert t.delete(f"/api/destinos/{i}").status_code == 409
    assert t.patch(f"/api/presets/{p['id']}", json={"nombre": "y"}).json()["nombre"] == "y" and t.get("/api/presets").json()[0]["solo_aprobados"]
    assert t.delete(f"/api/presets/{p['id']}").json()["ok"] and t.delete(f"/api/destinos/{i}").json()["ok"]


def test_plan_defecto_carpeta_y_plan_del_trabajo_sustituye(E, mk, monkeypatch):
    t, _ = E
    monkeypatch.setattr(destinos, "_hilo", lambda fn, *a: fn(*a))
    i = dest(t, "webhook", url=mk.url + "/f")
    p = t.post("/api/presets", json={"nombre": "dec", "destino": i, "que": ["decisiones"]}).json()["id"]
    rc = t.post("/api/recetas", json={"nombre": "carpeta", "activa": True, "cuando": {"carpeta": C}, "presets": [p]}).json()
    t.post("/api/recetas", json={"nombre": "otra", "activa": True, "cuando": {"carpeta": "Otra"}, "presets": [p]})
    assert [r["id"] for r in t.get("/api/recetas", params={"c": C}).json()] == [rc["id"]] and len(t.get("/api/recetas").json()) == 2
    pd = t.get(f"/api/carpetas/{C}/plan_defecto").json()
    assert pd["carpeta"] == C and pd["salidas"] == [{"que": "", "como": "destino", "preset": p, "receta": rc["id"]}]
    destinos.tras_documento("aaaa1111", "acta_normal_impaaaa")  # sin plan: corre la receta de la carpeta
    assert len(mk.reqs) == 1
    destinos.tras_documento("aaaa1111", "acta_normal_impaaaa", {"salidas": []})  # el usuario desmarcó todo: no se envía nada, ni la receta
    assert len(mk.reqs) == 1
    n = len(mk.reqs)
    destinos.tras_documento("aaaa1111", "acta_normal_impaaaa", {"salidas": [{"que": "tareas", "como": "destino", "destino": i}]})  # plan propio: solo él
    assert len(mk.reqs) == n + 1 and json.loads(mk.reqs[-1]["b"])["items"][0]["tipo"] == "tarea"


def test_plan_conserva_formatos_y_repetir_crea_receta(E):
    t, _ = E
    pl = destinos.normalizar_plan(
        {
            "carpeta": C,
            "nombre": "Comité",
            "repetir": {"cada": "semana", "dia_semana": 0, "hora": "09:00"},
            "salidas": [{"que": "decisiones", "como": "documento", "formatos": ["docx", "pdf"]}],
        }
    )
    assert pl["salidas"][0]["formatos"] == ["docx", "pdf"] and pl["repetir"]["cada"] == "semana"
    with pytest.raises(ValueError):
        destinos.normalizar_plan({"salidas": [{"que": "tareas", "como": "documento", "formatos": "pdf"}]})
    i = destinos.programar_desde_plan(pl)
    r = t.get(f"/api/recetas?c={C}").json()
    rec = next(x for x in (r if isinstance(r, list) else r.get("recetas", [])) if x["id"] == i)
    assert rec["cuando"]["tipo"] == "programado" and rec["cuando"]["cada"] == "semana" and rec["proximo_iso"] and "repetir" not in rec["plan"]
    assert destinos.programar_desde_plan({"carpeta": C, "salidas": []}) is None
