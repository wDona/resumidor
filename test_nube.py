"""Pruebas de nube.py: servidor OpenAI falso local (con y sin json_schema), CLIs falsas en el PATH, llavero en memoria, coste, claves de caché,
marca en los exports y ocultación. Nunca toca la red real ni las CLIs reales. `uv run pytest test_nube.py`"""
import json
import os
import shutil
import stat
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import keyring
import keyring.backend
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import nube
import pipeline

SRC = Path(__file__).parent / "work" / "c8f5001c5e212d71"
VER = "acta_normal_rápido"
SCHEMA = pipeline.obj(tema=pipeline.S(50), n=pipeline.arr({"enum": [1, 2]}, 3), t=pipeline.TS)
KEY = "sk-secreto-1234567890"


def ejemplo(s):
    """Instancia mínima válida de un esquema (lo que haría un modelo obediente)."""
    if "enum" in s:
        return s["enum"][0]
    if s["type"] == "object":
        return {k: ejemplo(v) for k, v in s["properties"].items()}
    return [ejemplo(s["items"])] if s["type"] == "array" else "0:05" if "description" in s else "texto"


class Falso(BaseHTTPRequestHandler):
    log = []
    fallos = {}  # modelo -> nº de respuestas inválidas que aún debe dar

    def log_message(s, *a):
        pass

    def _j(s, code, o):
        b = json.dumps(o).encode()
        s.send_response(code)
        s.send_header("Content-Type", "application/json")
        s.end_headers()
        s.wfile.write(b)

    def do_GET(s):
        Falso.log.append(("GET", s.path, s.headers.get("Authorization")))
        s._j(200, {"data": [{"id": "models/m-b"}, {"id": "m-a"}]})

    def do_POST(s):
        b = json.loads(s.rfile.read(int(s.headers["Content-Length"])))
        Falso.log.append(("POST", s.path, s.headers.get("Authorization"), b))
        rf, m = b.get("response_format"), b["model"]
        if m == "sin-schema" and rf and rf["type"] == "json_schema":
            return s._j(400, {"error": {"message": "response_format json_schema is not supported"}})
        if m == "sin-nada" and rf:
            return s._j(400, {"error": {"message": "response_format unsupported"}})
        sch = rf["json_schema"]["schema"] if rf and rf["type"] == "json_schema" else SCHEMA
        txt = json.dumps(ejemplo(sch))
        if Falso.fallos.get(m):
            Falso.fallos[m] -= 1
            txt = '{"tema": 5}'
        if m == "sin-nada":
            txt = "```json\n" + txt + "\n```"
        if m == "correo":  # texto libre con el seudónimo recibido
            txt = "Escribe a " + b["messages"][1]["content"].split("a ")[-1]
        s._j(200, {"choices": [{"message": {"content": txt}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})


@pytest.fixture()
def srv(monkeypatch):
    Falso.log, Falso.fallos = [], {}
    h = HTTPServer(("127.0.0.1", 0), Falso)
    threading.Thread(target=h.serve_forever, daemon=True).start()
    nube._MODO.clear()
    monkeypatch.setattr(nube._post, "fast", True)
    yield f"http://127.0.0.1:{h.server_port}/v1"
    h.shutdown()


class Mem(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(s):
        s.d = {}

    def get_password(s, a, b):
        return s.d.get((a, b))

    def set_password(s, a, b, c):
        s.d[(a, b)] = c

    def delete_password(s, a, b):
        if (a, b) not in s.d:
            raise keyring.errors.PasswordDeleteError("no")
        del s.d[(a, b)]


@pytest.fixture()
def kr(tmp_path, monkeypatch):
    k = Mem()
    prev = keyring.get_keyring()
    keyring.set_keyring(k)
    monkeypatch.setattr(pipeline, "WORK", tmp_path / "work")
    (tmp_path / "work").mkdir()
    yield k
    keyring.set_keyring(prev)


def cfg(url, modelo="ok", **kw):
    nube.poner_clave("propio", KEY)
    return nube.norm({"proveedor": "propio", "modelo": modelo, "url": url, **kw})


def test_json_schema_y_lista_de_modelos(srv, kr):
    c = cfg(srv)
    r = nube.chat_fn(c)("sis", "usuario", SCHEMA, 100)
    assert r == {"tema": "texto", "n": [1], "t": "0:05"}
    post = [x for x in Falso.log if x[0] == "POST"][0]
    assert post[2] == "Bearer " + KEY and post[3]["response_format"]["type"] == "json_schema"
    assert "maxLength" not in json.dumps(post[3]["response_format"]) and "pattern" not in json.dumps(post[3])  # esquema compatible
    assert nube.modelos("propio", srv) == ["m-a", "m-b"]


def test_sin_json_schema_baja_de_modo(srv, kr):
    r = nube.chat_fn(cfg(srv, "sin-schema"))("sis", "u", SCHEMA, 100)
    assert r["tema"] == "texto"
    ps = [x[3] for x in Falso.log if x[0] == "POST"]
    assert ps[0]["response_format"]["type"] == "json_schema" and ps[1]["response_format"]["type"] == "json_object" and "esquema JSON" in ps[1]["messages"][0]["content"]
    n = len(ps)
    nube.chat_fn(cfg(srv, "sin-schema"))("sis", "u", SCHEMA, 100)  # recuerda el modo: una sola llamada
    assert len([x for x in Falso.log if x[0] == "POST"]) == n + 1
    r = nube.chat_fn(cfg(srv, "sin-nada"))("sis", "u", SCHEMA, 100)  # sin response_format y con bloque ```json
    assert r["tema"] == "texto"


def test_reintento_con_el_error(srv, kr):
    Falso.fallos["ok"] = 1
    r = nube.chat_fn(cfg(srv))("sis", "u", SCHEMA, 100)
    assert r["n"] == [1]
    ps = [x[3] for x in Falso.log if x[0] == "POST"]
    assert len(ps) == 2 and "no es válida" in ps[1]["messages"][-1]["content"] and "falta" in ps[1]["messages"][-1]["content"]
    Falso.fallos["ok"] = 2
    with pytest.raises(RuntimeError, match="JSON válido"):
        nube.chat_fn(cfg(srv))("sis", "u", SCHEMA, 100)


def test_anonimizar_va_y_vuelve(srv, kr):
    c = cfg(srv, "correo", anonimizar=True)
    out = nube.texto(c, "s", "Contacta a ana@ejemplo.com hoy, a ana@ejemplo.com")
    env = [x[3] for x in Falso.log if x[0] == "POST"][0]["messages"][1]["content"]
    assert "ana@ejemplo.com" not in env and "[EMAIL_1]" in env
    assert "ana@ejemplo.com" in out and "[EMAIL_1]" not in out
    an = nube.Anon()
    assert an.vuelta({"a": [an.ida("IBAN ES9121000418450200051332")]}) == {"a": ["IBAN ES9121000418450200051332"]}


def test_cli_falsas(tmp_path, monkeypatch, kr):
    b = tmp_path / "bin"
    b.mkdir()
    for n, cuerpo in {"claude": 'import sys,json;e=sys.stdin.read();print(json.dumps({"result":"{\\"tema\\":\\"c\\",\\"n\\":[2],\\"t\\":\\"1:00\\"}","is_error":False}))',
                      "codex": 'import sys;sys.stdin.read();print("```json\\n{\\"tema\\":\\"x\\",\\"n\\":[1],\\"t\\":\\"0:01\\"}\\n```")',
                      "gemini": 'import sys;assert "esquema" in sys.stdin.read();print("{\\"tema\\":\\"g\\",\\"n\\":[],\\"t\\":\\"0:02\\"}")'}.items():
        f = b / n
        f.write_text(f"#!{os.sys.executable}\n{cuerpo}\n")
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(b) + os.pathsep + "/usr/bin:/bin")
    assert [c["id"] for c in nube.detectar_clis()] == ["cli:claude", "cli:codex", "cli:gemini"]
    for p, tema in (("claude", "c"), ("codex", "x"), ("gemini", "g")):
        assert nube.chat_fn(nube.norm({"proveedor": "cli:" + p}))("s", "u", SCHEMA, 10)["tema"] == tema
    assert nube.marca(nube.norm({"proveedor": "cli:claude"})) == "Redactado con Claude Code (suscripción) (nube)"


def test_llavero_y_enmascarado(kr, tmp_path):
    nube.poner_clave("openai", KEY)
    assert nube.clave("openai") == KEY and nube.enmascarada("openai") == "sk-…7890"
    assert KEY not in json.dumps(nube.info()) and not list((tmp_path / "work").glob("*"))  # nada en disco
    nube.poner_clave("openai", "")
    assert nube.clave("openai") == ""
    keyring.set_keyring(keyring.backends.fail.Keyring())
    with pytest.raises(RuntimeError, match="llavero"):
        nube.poner_clave("openai", KEY)


def test_coste_y_cache(kr):
    e = nube.estimar(60000, {"modelo": "m"})
    assert e["entrada"] > 60000 / 3.5 and e["coste"] is None and e["bloques"] == 6
    nube.guardar(precios={"m": [1.0, 2.0]})
    assert nube.estimar(60000, {"modelo": "m"})["coste"] == round((e["entrada"] * 1 + e["salida"] * 2) / 1e6, 2)
    a, b = (nube.id_cache(nube.norm({"proveedor": "openai", "modelo": m})) for m in ("x", "y"))
    P = pipeline.prompts()
    ks = {pipeline.cache_keys(P, m, ["i"], "normal", False)[0] for m in (a, b, "/models/local.gguf", nube.id_cache(nube.norm({"proveedor": "openai", "modelo": "x", "anonimizar": True})))}
    assert len(ks) == 4


def test_oculta(kr):
    aj = {"nube_visible": False}
    assert not nube.permitida(None, aj)[0] and not nube.permitida({"nube_permitida": False}, {"nube_visible": True})[0]
    assert "RGPD" in nube.permitida({"nube_permitida": False})[1] and nube.permitida({"nube_permitida": True}, {"nube_visible": True})[0]
    import app
    d = {"nube": {"proveedor": "openai", "modelo": "x"}}
    with pytest.raises(HTTPException) as e:
        app._nube_spec(dict(d), {"nube_permitida": False})
    assert e.value.status_code == 403
    nube.poner_clave("openai", KEY)
    with pytest.raises(HTTPException) as e:  # primer uso: pide confirmación explícita
        app._nube_spec(dict(d))
    assert e.value.status_code == 409 and e.value.detail["confirmar"] == "openai"
    nube.guardar(confirmado=["openai"])
    assert app._nube_spec(dict(d))["modelo"] == "x"


def test_pipeline_marca_y_exports(srv, kr, tmp_path, monkeypatch):
    """pipeline.run con transcripción importada y el servidor falso: sin GPU, con la marca en acta.json, index.html y los exports."""
    import exportar
    t = json.loads((SRC / "transcript_rápido.json").read_text())["segments"][:40]
    vtt = tmp_path / "r.vtt"
    ts = lambda x: f"{int(x) // 3600:02d}:{int(x) // 60 % 60:02d}:{x % 60:06.3f}"
    vtt.write_text("WEBVTT\n\n" + "\n".join(f"{ts(s['s'])} --> {ts(s['e'])}\n{s['text']}\n" for s in t))
    c = cfg(srv, "ok")
    out, _, _ = pipeline.run(None, "normal", "rápido", 2, lambda f, m: None, transcript=vtt, nube=c)
    d = json.loads((out / "acta.json").read_text())
    assert d["nube"] == "Redactado con Servidor propio / ok (nube)" and "Redactado con Servidor propio / ok (nube)" in (out / "index.html").read_text()
    assert any(x[0] == "POST" for x in Falso.log) and not list(pipeline.WORK.glob("llama-server*"))
    mid = out.parent
    cc = exportar.carga(mid.name, out.name)
    assert "Redactado con" in exportar.html_doc(cc) and "Redactado con" in exportar.md(cc)
    from docx import Document
    import io
    assert any("Redactado con" in p.text for p in Document(io.BytesIO(exportar.docx_bytes(cc))).paragraphs)
    # cache: la misma entrada en local usa otras claves (otro map_*.json)
    assert len(list(mid.glob("map_*.json"))) == 1
