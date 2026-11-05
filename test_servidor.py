"""Modo servidor (docs/plan-equipos.md, A7 · S1): login, bloqueos, sin IA local, autor = usuario, tokens del escritorio. Sin LLM."""

import inspect
import re

import pytest
from fastapi import HTTPException

import servidor
from test_carpetas import C, cl  # noqa: F401


@pytest.fixture
def sv(cl, monkeypatch):
    t, app = cl
    monkeypatch.setattr(servidor, "ACTIVO", True)
    servidor.SESIONES.clear()
    servidor.FALLOS.clear()
    servidor.poner("Ana", "clave-de-ana-1", admin=True)
    servidor.poner("Luis", "clave-de-luis-1")
    yield t, app
    t.cookies.clear()


def entrar(t, n, c):
    t.cookies.clear()
    return t.post("/api/login", json={"nombre": n, "clave": c})


def test_sin_sesion_no_hay_nada(sv):
    t, _ = sv
    assert t.get("/api/carpetas").status_code == 401
    assert t.get("/", follow_redirects=False).headers["location"] == "/login.html"
    assert t.get("/login.html").status_code == 200 and t.get("/api/ping").status_code == 200
    assert entrar(t, "Ana", "mala-clave-00").status_code == 401
    assert entrar(t, "Nadie", "clave-de-ana-1").status_code == 401


def test_login_autor_y_bloqueos(sv):
    t, app = sv
    assert entrar(t, "Luis", "clave-de-luis-1").status_code == 200
    assert t.get("/api/carpetas").status_code == 200
    a = t.get("/api/ajustes").json()
    assert a["servidor"] and a["yo"]["nombre"] == "Luis" and not a["admin"]
    e = t.post("/api/reg", json={"c": C, "tipo": "tarea", "titulo": "Llamar"}).json()
    t.patch(f"/api/reg/{e['id']}", json={"c": C, "cambios": {"dueno": "Ana"}})
    assert {h["autor"] for h in t.get(f"/api/reg/{e['id']}/historial", params={"c": C}).json()} == {"Luis"}
    for m, u in (("post", "/api/pick"), ("post", "/api/generar"), ("put", "/api/upload?name=x"), ("get", "/openapi.json"), ("post", "/api/grabar/iniciar")):
        assert (t.get(u) if m == "get" else getattr(t, m)(u, json={})).status_code == 403, u
    with pytest.raises(HTTPException) as ex:  # ningún trabajo de IA local en la cola
        app.start("poblar", {"c": C}, C)
    assert ex.value.status_code == 409
    assert t.post("/api/destinos", json={"tipo": "carpeta", "nombre": "x", "config": {"ruta": "/etc"}}).status_code == 400
    assert t.get("/api/usuarios").status_code == 403


def test_admin_tokens_y_contrasenas(sv):
    t, _ = sv
    entrar(t, "Ana", "clave-de-ana-1")
    assert t.post("/api/usuarios", json={"nombre": "Eva", "clave": "corta"}).status_code == 400
    assert [u["nombre"] for u in t.post("/api/usuarios", json={"nombre": "Eva", "clave": "clave-de-eva-1"}).json()] == ["Ana", "Eva", "Luis"]
    assert t.post("/api/usuarios/borrar", json={"nombre": "Ana"}).status_code == 400
    tok = t.post("/api/cuenta/token").json()["token"]
    t.cookies.clear()
    assert t.get("/api/carpetas", headers={"Authorization": "Bearer " + tok}).status_code == 200
    assert t.get("/api/carpetas", headers={"Authorization": "Bearer act_falso"}).status_code == 401
    entrar(t, "Eva", "clave-de-eva-1")
    assert t.post("/api/cuenta/clave", json={"actual": "mal", "nueva": "otra-clave-eva"}).status_code == 400
    assert t.post("/api/cuenta/clave", json={"actual": "clave-de-eva-1", "nueva": "otra-clave-eva"}).status_code == 200
    assert t.get("/api/carpetas").status_code == 401  # cambiar la contraseña cierra las sesiones
    assert entrar(t, "Eva", "otra-clave-eva").status_code == 200


def test_sin_puntos_en_la_ruta(sv):
    t, _ = sv
    entrar(t, "Luis", "clave-de-luis-1")
    for u in ("/api/vista/%2e%2e/x", "/api/fuente/..", "/files/abc/%5c..%5cusuarios.json"):
        assert t.get(u).status_code in (400, 404), u
    assert t.get("/api/vista/%2e%2e/x").status_code == 400


def test_bloqueo_por_intentos(sv):
    t, _ = sv
    for _ in range(8):
        entrar(t, "Luis", "mala-clave-00")
    assert entrar(t, "Luis", "clave-de-luis-1").status_code == 429


def test_fuera_del_servidor_nada_cambia(cl):
    t, _ = cl
    assert t.get("/api/carpetas").status_code == 200 and t.post("/api/login", json={}).status_code == 404


def test_llavero_fichero(tmp_path, monkeypatch):
    import pipeline

    monkeypatch.setattr(pipeline, "WORK", tmp_path)
    k = servidor.LlaveroFichero()
    k.set_password("actas-nube", "openai", "sk-1")
    assert k.get_password("actas-nube", "openai") == "sk-1" and k.get_password("x", "y") is None
    k.delete_password("actas-nube", "openai")
    assert k.get_password("actas-nube", "openai") is None


# Lo que una ruta abierta en el servidor NO puede hacer: leer rutas del disco que manda el navegador, abrir diálogos o lanzar procesos.
PELIGRO = re.compile(
    r"Path\(d[\[.]|Path\(str\(d|d\.get\(\"(path|video|ruta|transcripcion)\"|d\[\"(path|video|ruta)\"\]|askopen|askdirectory|subprocess|\.stream\(\)"
)
REVISADAS = {
    "/api/meta",  # Path(d["version"]).name: solo el nombre, dentro de WORK
    "/api/reg/importar/previa",  # lee el cuerpo subido, no rutas
    "/api/fondo",  # Path(d["id"]).name dentro de WORK (y la cola no corre IA local en el servidor)
    "/api/condensar",  # ídem
    "/api/describir",  # ídem
}


def test_rutas_abiertas_no_tocan_el_disco(cl):
    _, app = cl
    malas = []
    for r in app.app.routes + [x for x in __import__("destinos").router.routes]:
        p = getattr(r, "path", "")
        if not p or servidor.BLOQUEADAS.fullmatch(p) or p in REVISADAS or not getattr(r, "endpoint", None):
            continue
        if PELIGRO.search(inspect.getsource(r.endpoint)):
            malas.append(p)
    assert not malas, f"Rutas abiertas en el servidor que tocan el disco o lanzan procesos (bloquéalas en servidor.BLOQUEADAS o revísalas): {malas}"


def test_files_no_sale_de_la_reunion(cl):
    import pipeline

    t, _ = cl
    (pipeline.WORK / "abc123").mkdir(parents=True, exist_ok=True)
    (pipeline.WORK / "abc123" / "acta.json").write_text("{}", encoding="utf-8")
    (pipeline.WORK / "usuarios.json").write_text("secreto", encoding="utf-8")
    assert t.get("/files/abc123/acta.json").status_code == 200
    for u in (
        "/files/./usuarios.json",
        "/files/abc123/../usuarios.json",
        "/files/abc123/%2e%2e/usuarios.json",
        "/files/abc123//etc/passwd",
        "/files/abc123/C:/Windows/win.ini",
    ):
        assert t.get(u).status_code == 404, u
