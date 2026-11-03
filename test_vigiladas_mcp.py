"""Carpetas vigiladas (pasadas a mano, sin hilos ni esperas) y servidor MCP (TestClient) sobre la carpeta sintética de test_carpetas."""
import io
import json

from fastapi.testclient import TestClient

import mcp_servidor
import vigiladas
from test_carpetas import C, cl  # noqa: F401


def rpc(t, met, p=None, i=1, **kw):
    return t.post("/mcp", json={"jsonrpc": "2.0", "id": i, "method": met, "params": p or {}}, **kw)


def texto(t, nombre, **args):
    return rpc(t, "tools/call", {"name": nombre, "arguments": args}).json()["result"]["content"][0]["text"]


def test_vigilada_estable_y_recuerda(cl, tmp_path):
    t, _ = cl
    cola = []
    vigiladas.configurar(lambda r, c, p: cola.append((r, c, p)) or {"ids": ["x"], "omitidas": []}, (".mp4", ".pdf"))
    vigiladas._vistos.clear()
    d = tmp_path / "onedrive"
    d.mkdir()
    for n in ("a.mp4", "~$b.pdf", "c.tmp", "d.part", ".~lock.e.pdf", "f.xyz", "g.crdownload"):
        (d / n).write_bytes(b"1")
    v = t.post("/api/vigiladas", json={"ruta": str(d), "carpeta": "P", "mover": True}).json()
    assert t.post("/api/vigiladas", json={"ruta": str(d / "no")}).status_code == 400
    assert t.post(f"/api/vigiladas/{v['id']}/revisar").json()["estado"]["encoladas"] == 0 and not cola  # primera pasada: aún no es estable
    (d / "a.mp4").write_bytes(b"123")  # cambia: otra espera
    vigiladas.tick()
    assert not cola
    r = t.post(f"/api/vigiladas/{v['id']}/revisar").json()
    assert r["estado"]["encoladas"] == 1 and cola[0][0] == [str(d / "Procesados" / "a.mp4")] and cola[0][1] == "P" and (d / "Procesados" / "a.mp4").exists()
    vigiladas._vistos.clear()  # «reinicio»: no se repite
    vigiladas.tick()
    vigiladas.tick()
    assert len(cola) == 1
    assert t.patch(f"/api/vigiladas/{v['id']}", json={"activa": False, "mover": False}).json()["activa"] is False
    assert t.delete(f"/api/vigiladas/{v['id']}").json() == {"ok": True} and t.get("/api/vigiladas").json() == []


def test_vigilada_error_no_rompe(cl, tmp_path):
    t, _ = cl
    vigiladas.configurar(lambda r, c, p: 1 / 0, (".pdf",))
    vigiladas._vistos.clear()
    d = tmp_path / "w"
    d.mkdir()
    (d / "a.pdf").write_bytes(b"1")
    v = t.post("/api/vigiladas", json={"ruta": str(d)}).json()
    vigiladas.tick()
    vigiladas.tick()
    assert "a.pdf" in vigiladas._estado[v["id"]]["error"]
    (d / "a.pdf").unlink()
    d.rmdir()
    assert "carpeta" in t.post(f"/api/vigiladas/{v['id']}/revisar").json()["estado"]["error"]


def test_mcp_acceso(cl):
    t, app = cl
    assert rpc(t, "ping").status_code == 403  # desactivado
    a = t.post("/api/mcp/ajustes", json={"activo": True}).json()
    assert a["token"] and rpc(t, "ping").status_code == 401
    assert rpc(t, "ping", headers={"Authorization": "Bearer mal"}).status_code == 401
    h = {"Authorization": "Bearer " + a["token"]}
    assert rpc(t, "ping", headers=h).json()["result"] == {}
    assert rpc(t, "ping", headers={**h, "Origin": "https://evil.example"}).status_code == 403
    assert rpc(TestClient(app.app, client=("10.0.0.5", 1)), "ping", headers=h).status_code == 403
    assert t.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=h).status_code == 202
    cfg = t.get("/api/mcp/config").json()
    assert a["token"] in cfg["claude_code"] and "--mcp-stdio" in cfg["claude_desktop"]
    assert t.post("/api/mcp/ajustes", json={"token_requerido": False}).json()["token_requerido"] is False and rpc(t, "ping").status_code == 200


def test_mcp_herramientas(cl):
    t, _ = cl
    t.post("/api/mcp/ajustes", json={"activo": True, "token_requerido": False})
    i = rpc(t, "initialize", {}).json()["result"]
    assert i["protocolVersion"] == "2025-06-18" and "tools" in i["capabilities"]
    assert [x["name"] for x in rpc(t, "tools/list").json()["result"]["tools"]] == ["buscar", "preguntar", "documento", "pendientes", "proyectos"]  # encolar: con permiso
    b = texto(t, "buscar", q="ascensor", proyecto=C)
    assert "ascensor" in b and "doc " in b
    assert "aaaa1111" in texto(t, "buscar", q="derrama")
    assert C in texto(t, "proyectos")
    assert "puerta del garaje" in texto(t, "pendientes", proyecto=C)
    assert "Junta de enero" in texto(t, "documento", id="aaaa1111")
    assert rpc(t, "tools/call", {"name": "documento", "arguments": {"id": "nope"}}).json()["result"]["isError"]
    assert rpc(t, "tools/call", {"name": "encolar", "arguments": {"rutas": ["/x"]}}).json()["result"]["isError"]
    assert rpc(t, "tools/call", {"name": "zzz"}).json()["error"]["code"] == -32602
    assert rpc(t, "nada").json()["error"]["code"] == -32601
    t.post("/api/mcp/ajustes", json={"permitir_encolar": True})
    assert "encolar" in [x["name"] for x in rpc(t, "tools/list").json()["result"]["tools"]]


def test_mcp_stdio(cl, monkeypatch):
    t, _ = cl
    t.post("/api/mcp/ajustes", json={"activo": True, "token_requerido": False})

    class R:
        def __init__(s, b):
            s.b = b

        def read(s):
            return s.b

        def __enter__(s):
            return s

        def __exit__(s, *a):
            pass
    monkeypatch.setattr(mcp_servidor.urllib.request, "urlopen", lambda req, timeout=0: R(t.post("/mcp", content=req.data).content))
    out = io.StringIO()
    mcp_servidor.stdio("http://x", io.StringIO('{"jsonrpc":"2.0","id":7,"method":"ping"}\n{"jsonrpc":"2.0","method":"notifications/initialized"}\n'), out)
    assert json.loads(out.getvalue()) == {"jsonrpc": "2.0", "id": 7, "result": {}}


def test_mcp_respeta_anonimizar_por_defecto(monkeypatch):
    import mcp_servidor as M
    monkeypatch.setattr(M.A, "_ajustes", lambda: {"anonimizar_defecto": True})
    r = M._llamar({"name": "proyectos", "arguments": {}})
    assert r["isError"] and "Anonimizar" in r["content"][0]["text"]
