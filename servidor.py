"""Modo servidor (docs/plan-equipos.md, A7): ACTAS_SERVIDOR=1 -> la app escucha en la red (Coolify, Docker) con usuarios y contraseñas
propios, sin IA local y sin nada que toque el disco del servidor por una ruta que mande el navegador. Sin la variable, nada cambia.

- Sesión: cookie HttpOnly + SameSite=Lax; el escritorio usa un token personal (Authorization: Bearer).
- Usuarios en WORK/usuarios.json (scrypt); el primer administrador sale de ACTAS_ADMIN / ACTAS_ADMIN_CLAVE.
- Secretos (claves de la nube, tokens de destinos): fichero WORK/secretos.json con permisos 600 (no hay llavero en un contenedor).
app.py llama a montar()."""

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.parse

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

import pipeline as P
import registro

ACTIVO = os.environ.get("ACTAS_SERVIDOR") == "1"
COOKIE = "actas_s"
DURA = 14 * 86400  # una sesión dura dos semanas
# lo que en un servidor leería o escribiría rutas de SU disco que manda el navegador, abriría diálogos, grabaría, vigilaría carpetas,
# descargaría o usaría modelos locales, o abriría Outlook; también la documentación automática de la API
BLOQUEADAS = re.compile(
    r"/api/(pick|encolar|upload|generar|transcripcion|importar|previa|notas|grabar|vigiladas|modelos|compartir|descargar|mcp)(/.*)?"
    r"|/api/nube/estimar|/api/servidor/(conexion|enviar)|/api/correo/[^/]+/[^/]+/outlook/.*|/mcp|/utcp(/.*)?|/docs.*|/redoc|/openapi\.json"
)
LIBRES = {"/api/login", "/api/ping", "/login.html", "/favicon.ico", "/favicon.svg"}
DESTINOS_NO = {"carpeta", "sftp"}  # escriben en el disco del servidor o ejecutan un comando tras subir
router = APIRouter()
LOCK = threading.Lock()
SESIONES = {}  # ponytail: en memoria (reiniciar = volver a entrar); a disco si molesta
FALLOS = {}  # nombre -> (fallos seguidos, bloqueado hasta)


def _f():
    return P.WORK / "usuarios.json"


def usuarios():
    try:
        return json.loads(_f().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _guardar(us):
    P.WORK.mkdir(parents=True, exist_ok=True)
    tmp = _f().with_suffix(".tmp")
    tmp.write_text(json.dumps(us, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(_f())


def _hash(clave, sal):
    return hashlib.scrypt(clave.encode(), salt=bytes.fromhex(sal), n=2**14, r=8, p=1).hex()


def _sha(t):
    return hashlib.sha256(t.encode()).hexdigest()


def poner(nombre, clave, admin=False):
    """Alta o cambio de contraseña. Nombre: 1-60 caracteres sin < > ni saltos; contraseña de 10 o más."""
    nombre = str(nombre or "").strip()
    if not re.fullmatch(r"[^<>\n\r\t]{1,60}", nombre):
        raise ValueError("Nombre no válido")
    if len(str(clave or "")) < 10:
        raise ValueError("La contraseña necesita 10 caracteres o más")
    with LOCK:
        us = usuarios()
        sal = secrets.token_hex(16)
        us[nombre] = {**us.get(nombre, {}), "sal": sal, "hash": _hash(clave, sal), "admin": bool(admin) or us.get(nombre, {}).get("admin", False)}
        _guardar(us)
    for t, (n, _) in list(SESIONES.items()):  # cambiar la contraseña cierra sus otras sesiones
        if n == nombre:
            SESIONES.pop(t, None)


def comprobar(nombre, clave):
    n, hasta = FALLOS.get(nombre, (0, 0))
    if hasta > time.time():
        raise PermissionError("Demasiados intentos: espera unos minutos")
    u = usuarios().get(nombre)
    ok = bool(u) and hmac.compare_digest(_hash(clave, u["sal"]), u["hash"])
    if not ok:
        FALLOS[nombre] = (n + 1, time.time() + 900 if n + 1 >= 8 else 0)
        time.sleep(0.5)
    else:
        FALLOS.pop(nombre, None)
    return ok


def arrancar():
    """Primer administrador desde el entorno (solo si aún no hay usuarios) y secretos a fichero."""
    if not usuarios() and os.environ.get("ACTAS_ADMIN") and os.environ.get("ACTAS_ADMIN_CLAVE"):
        poner(os.environ["ACTAS_ADMIN"], os.environ["ACTAS_ADMIN_CLAVE"], admin=True)
    import keyring

    keyring.set_keyring(LlaveroFichero())


def quien(request):
    """Usuario de la petición (cookie de sesión o token del escritorio), o None."""
    t = request.cookies.get(COOKIE)
    if t and (s := SESIONES.get(t)) and s[1] > time.time():
        return s[0]
    a = request.headers.get("authorization", "")
    if a.lower().startswith("bearer ") and (h := _sha(a[7:].strip())):
        return next((n for n, u in usuarios().items() if u.get("token") and hmac.compare_digest(u["token"], h)), None)
    return None


async def filtro(request: Request, call_next):
    if not ACTIVO:
        return await call_next(request)
    p = request.url.path
    if any(s in (".", "..") or "\\" in s for s in urllib.parse.unquote(request.scope.get("raw_path", b"").decode("latin-1") or p).split("/")):
        return JSONResponse({"detail": "Ruta no válida"}, 400)  # nada de salir de WORK con %2e%2e, ni barras invertidas
    if BLOQUEADAS.fullmatch(p):
        return JSONResponse({"detail": "No disponible en el servidor"}, 403)
    if p in LIBRES:
        return await call_next(request)
    n = quien(request)
    if not n:
        if p.startswith(("/api/", "/files/")):
            return JSONResponse({"detail": "Inicia sesión"}, 401)
        return RedirectResponse("/login.html", 303)
    tok = registro.USUARIO.set(n)  # el autor del historial es quien ha entrado
    try:
        return await call_next(request)
    finally:
        registro.USUARIO.reset(tok)


def _yo(request):
    if not ACTIVO:
        raise HTTPException(404, "Solo en modo servidor")
    n = quien(request)
    if not n:
        raise HTTPException(401, "Inicia sesión")
    return n, usuarios().get(n, {})


def _admin(request):
    n, u = _yo(request)
    if not u.get("admin"):
        raise HTTPException(403, "Solo un administrador")
    return n


def _ok(fn, *a, **k):
    try:
        return fn(*a, **k)
    except ValueError as ex:
        raise HTTPException(400, str(ex))


# ---------- API (solo existe en modo servidor: montar() no la añade en el escritorio) ----------
@router.post("/api/login")
def api_login(d: dict, request: Request, response: Response):
    if not ACTIVO:
        raise HTTPException(404, "Solo en modo servidor")
    try:
        ok = comprobar(str(d.get("nombre") or "").strip(), str(d.get("clave") or ""))
    except PermissionError as ex:
        raise HTTPException(429, str(ex))
    if not ok:
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    t = secrets.token_urlsafe(32)
    SESIONES[t] = (str(d["nombre"]).strip(), time.time() + DURA)
    https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(COOKIE, t, max_age=DURA, httponly=True, samesite="lax", secure=https)
    return {"nombre": SESIONES[t][0]}


@router.post("/api/logout")
def api_logout(request: Request, response: Response):
    SESIONES.pop(request.cookies.get(COOKIE, ""), None)
    response.delete_cookie(COOKIE)
    return {}


@router.get("/api/yo")
def api_yo(request: Request):
    n, u = _yo(request)
    return {"nombre": n, "admin": bool(u.get("admin")), "token": bool(u.get("token"))}


@router.post("/api/cuenta/clave")
def api_clave(d: dict, request: Request):
    n, _ = _yo(request)
    if not comprobar(n, str(d.get("actual") or "")):
        raise HTTPException(400, "La contraseña actual no es correcta")
    _ok(poner, n, str(d.get("nueva") or ""))
    return {}


@router.post("/api/cuenta/token")
def api_token(request: Request):
    """Token personal para el escritorio («Enviar al servidor»): se enseña una vez; generar otro anula el anterior."""
    n, _ = _yo(request)
    t = "act_" + secrets.token_urlsafe(32)
    with LOCK:
        us = usuarios()
        us[n]["token"] = _sha(t)
        _guardar(us)
    return {"token": t}


@router.get("/api/usuarios")
def api_usuarios(request: Request):
    _admin(request)
    return [{"nombre": n, "admin": bool(u.get("admin"))} for n, u in sorted(usuarios().items())]


@router.post("/api/usuarios")
def api_usuario(d: dict, request: Request):
    """{nombre, clave, admin?}: alta, o nueva contraseña de alguien que la olvidó."""
    _admin(request)
    _ok(poner, d.get("nombre"), d.get("clave"), bool(d.get("admin")))
    return api_usuarios(request)


@router.post("/api/usuarios/borrar")
def api_borrar(d: dict, request: Request):
    yo = _admin(request)
    n = str(d.get("nombre") or "")
    if n == yo:
        raise HTTPException(400, "No puedes borrarte a ti")
    with LOCK:
        us = usuarios()
        us.pop(n, None)
        _guardar(us)
    for t, (m, _) in list(SESIONES.items()):
        if m == n:
            SESIONES.pop(t, None)
    return api_usuarios(request)


# ---------- secretos a fichero (keyring) ----------
try:
    from keyring.backend import KeyringBackend
except ImportError:  # sin keyring no hay nada que sustituir
    KeyringBackend = object


class LlaveroFichero(KeyringBackend):
    """Llavero en WORK/secretos.json con permisos 600. ponytail: en claro dentro del volumen de datos; cifrar si el volumen se comparte."""

    priority = 1

    def _f(self):
        return P.WORK / "secretos.json"

    def _leer(self):
        try:
            return json.loads(self._f().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _escribir(self, d):
        tmp = self._f().with_suffix(".tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self._f())

    def get_password(self, servicio, usuario):
        return self._leer().get(f"{servicio}|{usuario}")

    def set_password(self, servicio, usuario, clave):
        with LOCK:
            d = self._leer()
            d[f"{servicio}|{usuario}"] = clave
            self._escribir(d)

    def delete_password(self, servicio, usuario):
        import keyring.errors

        with LOCK:
            d = self._leer()
            if d.pop(f"{servicio}|{usuario}", None) is None:
                raise keyring.errors.PasswordDeleteError("No existe")
            self._escribir(d)


def ia_local(nube=None):
    """El servidor no usa IA local (start() y gpu_exclusiva() de app.py lo comprueban): solo trabajos con un proveedor de la nube con API,
    nunca una CLI (ejecuta programas). pipeline.sin_ia_local() lo cierra también abajo, al lanzar un modelo."""
    if ACTIVO and not (isinstance(nube, dict) and nube.get("proveedor") and not str(nube["proveedor"]).startswith("cli:")):
        raise HTTPException(409, "En el servidor no hay IA local: elige un modelo en la nube (Ajustes › Modelos en la nube) o procesa en el escritorio")


def destino_permitido(tipo):
    if ACTIVO and tipo in DESTINOS_NO:
        raise ValueError("Ese destino no está disponible en el servidor (escribe en su disco o ejecuta comandos)")


def montar(app):
    """Siempre se monta (los tests cambian ACTIVO); fuera del modo servidor el filtro deja pasar todo y la API responde 404."""
    if ACTIVO:
        arrancar()
    app.middleware("http")(filtro)
    for r in router.routes:
        app.router.routes.insert(0, r)  # antes del StaticFiles montado en «/»
