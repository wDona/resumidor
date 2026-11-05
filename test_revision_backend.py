"""Regresiones de la revisión del backend (rediseno)."""

import importar_registro
import mcp_servidor


def test_copia_no_enlaza_json_editables(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    (a / "meta.json").write_text("{}", encoding="utf-8")
    (a / "video.mp4").write_bytes(b"v")
    b.mkdir()
    for f in a.iterdir():
        importar_registro._copia(f, b / f.name)
    (b / "meta.json").write_text('{"nombre": "copia"}', encoding="utf-8")  # reescritura en sitio: no debe tocar el original
    assert (a / "meta.json").read_text(encoding="utf-8") == "{}"


def test_mcp_sin_token_guardado_no_abre(monkeypatch):
    monkeypatch.setattr(mcp_servidor, "cfg", lambda: {**mcp_servidor.DEF, "activo": True, "token_requerido": True, "token": ""})
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(mcp_servidor.router)
    r = TestClient(app).post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401
