"""msgraph (Graph + device code con urllib simulado), Outlook clásico (PowerShell simulado) y /api/encolar. Sin red ni Outlook reales."""
import io
import json
import subprocess
import sys
import urllib.error
import urllib.parse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import correo
import msgraph as M


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


@pytest.fixture
def red(monkeypatch, tmp_path):
    """Router de urlopen: red.rutas = [(método, subcadena de URL, respuesta dict|bytes|(código, dict)|lista de respuestas)]; red.log guarda (método, url, cabeceras, cuerpo)."""
    monkeypatch.setattr(M.P, "WORK", tmp_path)
    store = {"r": ""}
    monkeypatch.setattr(M, "_refresco", lambda v=None: store["r"] if v is None else store.__setitem__("r", v))
    monkeypatch.setattr(M, "_sleep", lambda s: None)
    monkeypatch.setenv("ACTAS_MS_CLIENT_ID", "cid-123")
    M._AT.update(t="", exp=0)
    M._L.update(estado="ninguno", msg="")

    class R:
        rutas, log = [], []

    def urlopen(req, timeout=None):
        b = req.data if isinstance(req.data, (bytes, type(None))) else req.data.encode()
        R.log.append((req.get_method(), req.full_url, {k.lower(): v for k, v in req.header_items()}, b))
        for r in R.rutas:
            if r[0] == req.get_method() and r[1] in req.full_url:
                v = r[2].pop(0) if isinstance(r[2], list) else r[2]
                if isinstance(v, tuple):
                    raise urllib.error.HTTPError(req.full_url, v[0], "x", {}, io.BytesIO(json.dumps(v[1]).encode()))
                return Resp(v if isinstance(v, bytes) else json.dumps(v).encode())
        raise AssertionError(f"URL sin simular: {req.get_method()} {req.full_url}")
    monkeypatch.setattr(M.urllib.request, "urlopen", urlopen)
    R.store = store
    return R


def con_sesion(red):
    red.store["r"] = "RT"
    red.rutas.append(("POST", "/oauth2/v2.0/token", {"access_token": "AT", "expires_in": 3600}))


def test_login_device_code(red):
    red.rutas += [("POST", "/devicecode", {"device_code": "DC", "user_code": "ABC-123", "verification_uri": "https://microsoft.com/devicelogin", "expires_in": 900, "interval": 5}),
                  ("POST", "/token", [(400, {"error": "authorization_pending"}), (400, {"error": "slow_down"}), {"access_token": "AT", "refresh_token": "RT2", "expires_in": 3600}]),
                  ("GET", "/me", {"userPrincipalName": "ana@contoso.com"})]
    app = FastAPI()
    app.include_router(M.router)
    c = TestClient(app)
    assert c.get("/api/ms/estado").json()["conectado"] is False
    i = M.iniciar("contoso.com", "", ["archivos", "correo"])
    assert i == {"user_code": "ABC-123", "verification_uri": "https://microsoft.com/devicelogin", "expires_in": 900}
    dev = red.log[0]
    assert "contoso.com/oauth2/v2.0/devicecode" in dev[1]
    q = urllib.parse.parse_qs(dev[3].decode())
    assert q["client_id"] == ["cid-123"] and set(q["scope"][0].split()) == {"offline_access", "User.Read", "Files.ReadWrite", "Mail.Send"}
    M._sondear()
    assert M._L["estado"] == "ok" and red.store["r"] == "RT2"
    e = c.get("/api/ms/estado").json()
    assert e["conectado"] and e["cuenta"] == "ana@contoso.com" and "Mail.Send" in e["scopes"]
    assert "device_code=DC" in red.log[1][3].decode() and "grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Adevice_code" in red.log[1][3].decode()
    assert c.post("/api/ms/logout").json()["ok"] and red.store["r"] == "" and not c.get("/api/ms/estado").json()["conectado"]


def test_login_endpoint_y_sin_client_id(red, monkeypatch):
    app = FastAPI()
    app.include_router(M.router)
    monkeypatch.delenv("ACTAS_MS_CLIENT_ID")
    c = TestClient(app)
    r = c.post("/api/ms/login", json={})
    assert r.status_code == 400 and "client_id" in r.json()["detail"]
    monkeypatch.setattr(M, "_sondear", lambda: None)
    red.rutas.append(("POST", "/devicecode", {"device_code": "D", "user_code": "XYZ", "verification_uri": "u", "expires_in": 600}))
    assert c.post("/api/ms/login", json={"client_id": "nuevo", "tenant": "t1"}).json()["user_code"] == "XYZ"
    assert M.config()["client_id"] == "nuevo" and "/t1/" in red.log[-1][1]


@pytest.mark.parametrize("cod,frag", [("65001", "consentimiento"), ("90094", "administrador"), ("700016", "client_id"), ("7000218", "público")])
def test_errores_aadsts(red, cod, frag):
    red.rutas.append(("POST", "/devicecode", (400, {"error": "invalid_grant", "error_description": f"AADSTS{cod}: The user ... Trace ID: 1"})))
    with pytest.raises(RuntimeError) as e:
        M.iniciar()
    assert frag in str(e.value) and cod in str(e.value)


def test_codigo_caducado(red):
    red.rutas.append(("POST", "/devicecode", {"device_code": "D", "user_code": "U", "verification_uri": "u", "expires_in": 600}))
    M.iniciar()
    red.rutas.append(("POST", "/token", (400, {"error": "expired_token"})))
    M._sondear()
    assert M._L["estado"] == "error"


def test_refresco_y_sin_sesion(red):
    with pytest.raises(RuntimeError, match="No has iniciado sesión"):
        M.token()
    red.store["r"] = "RT"
    red.rutas.append(("POST", "/token", {"access_token": "AT2", "refresh_token": "RT3", "expires_in": 3600}))
    assert M.token() == "AT2" and red.store["r"] == "RT3" and M.token() == "AT2" and len(red.log) == 1
    assert "refresh_token=RT" in red.log[0][3].decode()


def test_subir_simple_y_sesion(red):
    con_sesion(red)
    red.rutas.append(("PUT", "/me/drive/root:/Actas/a%20b.md:/content", {"id": "i1", "webUrl": "https://od/a"}))
    assert M.subir("a b.md", b"hola", "Actas") == ("i1", "https://od/a")
    put = red.log[-1]
    assert put[2]["authorization"] == "Bearer AT" and put[3] == b"hola"
    red.rutas += [("POST", "/sites/S/drive/root:/g.bin:/createUploadSession", {"uploadUrl": "https://up.example/sess"}), ("PUT", "up.example", [{}, {"id": "i2", "webUrl": "w2"}])]
    big = b"z" * (M.SIMPLE + 1)
    red.rutas[-1] = ("PUT", "up.example", [{}] * ((len(big) - 1) // M.TROZO) + [{"id": "i2", "webUrl": "w2"}])
    assert M.subir("g.bin", big, sitio="S") == ("i2", "w2")
    trozos = [x for x in red.log if "up.example" in x[1]]
    assert b"".join(t[3] for t in trozos) == big and "authorization" not in trozos[0][2]
    assert trozos[0][2]["content-range"] == f"bytes 0-{M.TROZO - 1}/{len(big)}" and trozos[-1][2]["content-range"].endswith(f"-{len(big) - 1}/{len(big)}")


def test_planner_todo_onenote_teams_correo(red):
    con_sesion(red)
    x = {"titulo": "Enviar informe", "codigo": "T-1", "cuerpo": "detalle", "dueno": "Ana", "fecha_limite": "2026-11-20"}
    red.rutas += [("POST", "/planner/tasks", {"id": "pt"}), ("GET", "/planner/tasks/pt/details", {"@odata.etag": "W/1"}), ("PATCH", "/planner/tasks/pt/details", b""),
                  ("GET", "/me/todo/lists", {"value": [{"id": "L0", "wellknownListName": "none"}, {"id": "L1", "wellknownListName": "defaultList"}]}),
                  ("POST", "/me/todo/lists/L1/tasks", {"id": "td"}), ("POST", "/me/onenote/pages", {"id": "pg", "links": {"oneNoteWebUrl": {"href": "https://on/1"}}}),
                  ("POST", "/teams/E/channels/C/messages", {"id": "m1", "webUrl": "https://t/m"}), ("POST", "/me/sendMail", b"")]
    assert M.TIPOS_GRAPH["ms_planner"]["crear"](None, {}, {"plan": "P"}, x)[0] == "pt"
    pl = json.loads(next(a for a in red.log if a[1].endswith("/planner/tasks"))[3])
    assert pl["title"] == "T-1 Enviar informe" and pl["planId"] == "P" and pl["dueDateTime"].startswith("2026-11-20")
    assert [a for a in red.log if a[0] == "PATCH"][0][2]["if-match"] == "W/1"
    assert M.TIPOS_GRAPH["ms_todo"]["crear"](None, {}, {}, x)[0] == "td"
    assert json.loads(red.log[-1][3])["dueDateTime"]["dateTime"].startswith("2026-11-20")
    n = M.TIPOS_GRAPH["ms_onenote"]["crear"](None, {}, {}, {"titulo": "Acta <1>", "md": "# Hola\n- a\n- b\ntexto & más"})
    assert n == ("pg", "https://on/1")
    o = red.log[-1]
    assert o[2]["content-type"] == "text/html" and b"<title>Acta &lt;1&gt;</title>" in o[3] and b"<ul><li>a</li><li>b</li></ul>" in o[3] and b"&amp;" in o[3]
    assert M.TIPOS_GRAPH["ms_teams"]["crear"](None, {}, {"equipo": "E", "canal": "C"}, {"titulo": "T", "md": "x"}) == ("m1", "https://t/m")
    M.TIPOS_GRAPH["ms_outlook"]["crear"](None, {}, {"para": "a@x.es; b@y.es", "cc": ""}, {"titulo": "Asunto", "md": "cuerpo", "ficheros": [("a.pdf", b"PDF")]})
    m = json.loads(red.log[-1][3])["message"]
    assert m["subject"] == "Asunto" and [r["emailAddress"]["address"] for r in m["toRecipients"]] == ["a@x.es", "b@y.es"] and m["attachments"][0]["name"] == "a.pdf"
    with pytest.raises(RuntimeError, match="demasiado grandes"):
        M.correo("s", "h", "a@b.c", [("g", b"0" * (M.MAIL_MAX + 1))])


def test_esquema_tipos():
    assert set(M.TIPOS_GRAPH) == {"ms_onedrive", "ms_planner", "ms_todo", "ms_onenote", "ms_teams", "ms_outlook"}
    for t in M.TIPOS_GRAPH.values():
        assert t["modo"] in ("items", "pagina") and callable(t["crear"]) and callable(t["probar"]) and t["nombre"].startswith("Microsoft 365")
        assert all({"id", "etiqueta", "tipo", "req", "preset"} <= set(f) for f in t["campos"])


# ---------- Outlook clásico ----------
COR = {"para": "Ana", "asunto": "Resumen", "texto": "t", "html": "<p>h' \"$(x)</p>"}


def test_outlook_no_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="solo está disponible en Windows"):
        correo.abrir_outlook(COR)


def test_outlook_powershell(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    visto = {}

    def run(args, **kw):
        spec = json.loads(open(args[-1], encoding="utf-8").read())
        visto.update(args=args, spec=spec, ps=open(args[-2], encoding="utf-8-sig").read(), adj=[open(a, "rb").read() for a in spec["adjuntos"]])
        return subprocess.CompletedProcess(args, visto.get("rc", 0), "", "")
    monkeypatch.setattr(subprocess, "run", run)
    correo.abrir_outlook(COR, b"%PDF", "a.pdf")
    assert visto["spec"]["html"] == COR["html"] and visto["spec"]["para"] == "" and visto["adj"] == [b"%PDF"] and visto["args"][0] == "powershell"
    assert "New-Object -ComObject Outlook.Application" in visto["ps"] and "Asunto" not in visto["ps"] and COR["html"] not in visto["ps"] and ".Display()" in visto["ps"]
    correo.abrir_outlook({**COR, "para": "ana@x.es"})
    assert visto["spec"]["para"] == "ana@x.es"
    visto["rc"] = 3
    with pytest.raises(RuntimeError, match="nuevo Outlook"):
        correo.abrir_outlook(COR)


# ---------- /api/encolar ----------
def test_encolar(monkeypatch, tmp_path):
    import app
    llamadas = []
    monkeypatch.setattr(app, "generar", lambda d: llamadas.append(d) or {"id": f"id{len(llamadas)}"})
    (tmp_path / "v.mp4").write_bytes(b"x")
    (tmp_path / "t.vtt").write_bytes(b"x")
    (tmp_path / "x.exe").write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "w.mp3").write_bytes(b"x")
    c = TestClient(app.app)
    r = c.post("/api/encolar", json={"rutas": [str(tmp_path), str(tmp_path / "nada.mp4")], "c": "Clientes"})
    assert r.status_code == 200 and len(r.json()["ids"]) == 2  # carpeta no recursiva: v.mp4 y t.vtt
    assert {tuple(d) for d in llamadas} == {("video", "carpeta")} and all(d["carpeta"] == "Clientes" for d in llamadas)
    assert any("no existe" in o for o in r.json()["omitidas"])
    llamadas.clear()
    assert len(c.post("/api/encolar", json={"rutas": [str(tmp_path)], "recursivo": True}).json()["ids"]) == 3
    assert c.post("/api/encolar", json={"rutas": [str(tmp_path / "x.exe")]}).status_code == 400
    assert c.post("/api/encolar", json={"rutas": []}).status_code == 400
    assert TestClient(app.app, client=("8.8.8.8", 1)).post("/api/encolar", json={"rutas": [str(tmp_path / "v.mp4")]}).status_code == 403
