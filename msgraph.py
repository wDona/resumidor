"""Microsoft 365 vía Microsoft Graph (solo stdlib): inicio de sesión por código de dispositivo (OAuth2 device code), token de refresco en el llavero del
sistema, y destinos: OneDrive/SharePoint, Planner, To Do, OneNote, canal de Teams y correo de Outlook. Hay que registrar una app en Entra ID
(cliente público, «Permitir flujos de cliente público») y dar su client_id (y tenant) aquí o en ACTAS_MS_CLIENT_ID / ACTAS_MS_TENANT: no hay valores por defecto.
`TIPOS_GRAPH` usa el mismo esquema que destinos_tipos.TIPOS (se mezcla con `TIPOS.update(msgraph.TIPOS_GRAPH)`)."""
import base64
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException

import pipeline as P

SERV = "actas-msgraph"
LOGIN = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com/v1.0"
BASE = ("offline_access", "User.Read")
FUNCIONES = {"archivos": "Files.ReadWrite", "tareas": "Tasks.ReadWrite", "onenote": "Notes.Create", "teams": "ChannelMessage.Send", "correo": "Mail.Send"}
SIMPLE = 4_000_000  # Graph: PUT simple hasta 4 MB; más -> sesión de subida
TROZO = 320 * 1024 * 10  # múltiplo de 320 KiB (requisito de Graph)
MAIL_MAX = 3_000_000  # sendMail con adjuntos en línea: la petición entera ronda los 4 MB
AADSTS = {"65001": "Falta el consentimiento: un administrador (o tú) debe aceptar los permisos de la aplicación en Entra ID",
          "90094": "Se necesita el consentimiento de un administrador del tenant para estos permisos",
          "90095": "Se necesita el consentimiento de un administrador del tenant para estos permisos",
          "65002": "La aplicación no tiene el consentimiento del administrador",
          "700016": "No se encuentra la aplicación: revisa el client_id y el tenant",
          "700021": "La aplicación debe permitir «flujos de cliente público» (Autenticación en Entra ID)",
          "7000218": "La aplicación debe permitir «flujos de cliente público» (Autenticación en Entra ID)",
          "70011": "Permiso (scope) no válido o no concedido a la aplicación",
          "53003": "Una política de acceso condicional bloquea el inicio de sesión",
          "50076": "Se requiere autenticación multifactor: vuelve a iniciar sesión",
          "50079": "Se requiere autenticación multifactor: vuelve a iniciar sesión",
          "50034": "La cuenta no existe en ese tenant",
          "900144": "Falta el client_id de la aplicación"}
_AT = {"t": "", "exp": 0}
_L = {"estado": "ninguno", "msg": ""}  # inicio de sesión en curso
_sleep = time.sleep


# ---------- configuración y llavero ----------
def _fich():
    return P.WORK / "msgraph.json"


def config():
    try:
        d = json.loads(_fich().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    return {"tenant": d.get("tenant") or os.environ.get("ACTAS_MS_TENANT") or "organizations", "client_id": d.get("client_id") or os.environ.get("ACTAS_MS_CLIENT_ID") or "",
            "cuenta": d.get("cuenta", ""), "scopes": d.get("scopes", [])}


def _guardar(**kw):
    P.WORK.mkdir(exist_ok=True)
    _fich().write_text(json.dumps({**config(), **kw}, ensure_ascii=False, indent=1), encoding="utf-8")


def _refresco(v=None):
    import keyring
    if v is None:
        try:
            return keyring.get_password(SERV, "refresh") or ""
        except Exception:
            return ""
    try:
        keyring.set_password(SERV, "refresh", v) if v else keyring.delete_password(SERV, "refresh")
    except keyring.errors.PasswordDeleteError:
        pass
    except keyring.errors.KeyringError:
        raise RuntimeError("Este equipo no tiene un llavero del sistema donde guardar la sesión de Microsoft de forma segura") from None


# ---------- HTTP ----------
def _error(b):
    try:
        j = json.loads(b)
    except ValueError:
        return b[:200].decode("utf-8", "replace")
    desc = j.get("error_description") or ""
    k = re.search(r"AADSTS(\d+)", desc)
    if k and k[1] in AADSTS:
        return f"{AADSTS[k[1]]} (AADSTS{k[1]})"
    e = j.get("error")
    return (e.get("message") if isinstance(e, dict) else desc or e or "")[:300] or "error desconocido"


def _http(met, url, h=None, body=None, form=None):
    """JSON (o b'' en 202/204). body: dict -> JSON, bytes -> tal cual; form: dict -> x-www-form-urlencoded."""
    hd = {"User-Agent": "actas", **(h or {})}
    if form is not None:
        body, hd["Content-Type"] = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    elif isinstance(body, (dict, list)):
        body, hd["Content-Type"] = json.dumps(body).encode(), hd.get("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, body, hd, method=met), timeout=60) as r:
            b = r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(_error(e.read())) from None
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"Sin conexión: {getattr(e, 'reason', e)}") from None
    return json.loads(b) if b.strip()[:1] in (b"{", b"[") else b


def _tok(form):
    c = config()
    return _http("POST", f"{LOGIN}/{urllib.parse.quote(c['tenant'])}/oauth2/v2.0/token", form={"client_id": c["client_id"], **form})


def token():
    if _AT["t"] and time.time() < _AT["exp"] - 60:
        return _AT["t"]
    r = _refresco()
    if not r:
        raise RuntimeError("No has iniciado sesión con Microsoft (Ajustes -> Microsoft 365)")
    j = _tok({"grant_type": "refresh_token", "refresh_token": r, "scope": " ".join(config()["scopes"] or BASE)})
    _AT.update(t=j["access_token"], exp=time.time() + int(j.get("expires_in", 3600)))
    j.get("refresh_token") and _refresco(j["refresh_token"])
    return _AT["t"]


def g(met, ruta, body=None, h=None):
    return _http(met, ruta if ruta.startswith("http") else GRAPH + ruta, {"Authorization": "Bearer " + token(), **(h or {})}, body)


# ---------- inicio de sesión (device code) ----------
def iniciar(tenant="", client_id="", funciones=None):
    """Pide el código de dispositivo; devuelve lo que se muestra al usuario. El sondeo lo hace `_sondear`."""
    if tenant or client_id:
        _guardar(**({"tenant": tenant.strip()} if tenant else {}), **({"client_id": client_id.strip()} if client_id else {}))
    c = config()
    if not c["client_id"]:
        raise RuntimeError("Falta el client_id de la aplicación registrada en Entra ID")
    fs = [f for f in (funciones or FUNCIONES) if f in FUNCIONES]
    sc = list(BASE) + [FUNCIONES[f] for f in fs]
    j = _http("POST", f"{LOGIN}/{urllib.parse.quote(c['tenant'])}/oauth2/v2.0/devicecode", form={"client_id": c["client_id"], "scope": " ".join(sc)})
    _L.update(estado="pendiente", msg="", sc=sc, dc=j["device_code"], cada=int(j.get("interval", 5)), fin=time.time() + int(j.get("expires_in", 900)))
    return {"user_code": j["user_code"], "verification_uri": j.get("verification_uri") or j.get("verification_url"), "expires_in": int(j.get("expires_in", 900))}


def _sondear():
    """Bloquea hasta que el usuario acepta, rechaza o caduca el código. Deja el resultado en _L."""
    cada = _L["cada"]
    try:
        while time.time() < _L["fin"]:
            _sleep(cada)
            try:
                j = _tok({"grant_type": "urn:ietf:params:oauth:grant-type:device_code", "device_code": _L["dc"]})
            except RuntimeError as e:
                t = str(e)
                if "authorization_pending" in t:
                    continue
                if "slow_down" in t:
                    cada += 5
                    continue
                raise
            _AT.update(t=j["access_token"], exp=time.time() + int(j.get("expires_in", 3600)))
            _refresco(j["refresh_token"])
            me = g("GET", "/me?$select=userPrincipalName,mail")
            _guardar(cuenta=me.get("userPrincipalName") or me.get("mail") or "", scopes=_L["sc"])
            _L.update(estado="ok", msg="")
            return
        _L.update(estado="error", msg="El código caducó: vuelve a iniciar sesión")
    except Exception as e:
        _L.update(estado="error", msg=str(e))


def cerrar():
    _refresco("")
    _AT.update(t="", exp=0)
    _L.update(estado="ninguno", msg="")
    _guardar(cuenta="", scopes=[])


# ---------- operaciones ----------
def _q(s):
    return urllib.parse.quote(s, safe="/")


def subir(nombre, datos, carpeta="", sitio="", biblioteca=""):
    """OneDrive (sitio vacío) o SharePoint (sitio = id, o «dominio:/sites/nombre»). -> (id, webUrl)."""
    raiz = f"/sites/{sitio}/drives/{biblioteca}" if sitio and biblioteca else f"/sites/{sitio}/drive" if sitio else "/me/drive"
    ruta = f"{raiz}/root:/{_q((carpeta.strip('/') + '/' if carpeta.strip('/') else '') + Path(nombre).name)}:"
    if len(datos) <= SIMPLE:
        r = g("PUT", ruta + "/content", datos, {"Content-Type": "application/octet-stream"})
    else:
        u = g("POST", ruta + "/createUploadSession", {"item": {"@microsoft.graph.conflictBehavior": "rename"}})["uploadUrl"]
        n = len(datos)
        for i in range(0, n, TROZO):  # la URL de subida ya va firmada: sin Authorization
            r = _http("PUT", u, {"Content-Range": f"bytes {i}-{min(i + TROZO, n) - 1}/{n}", "Content-Type": "application/octet-stream"}, datos[i:i + TROZO])
    return r["id"], r.get("webUrl", "")


def _cuerpo(x):
    p = [x["cuerpo"]] if x.get("cuerpo") else []
    p += [f"{a}: {x[k]}" for k, a in (("dueno", "Responsable"), ("fecha_limite", "Plazo")) if x.get(k)]
    return "\n\n".join(p)


def _tit(x):
    return ((f"{x['codigo']} " if x.get("codigo") else "") + x["titulo"])[:250]


def _fecha(x):
    f = str(x.get("fecha_limite") or "")[:10]
    return f if len(f) == 10 and f[:4].isdigit() and f[4] == "-" and f[5:7].isdigit() and f[7] == "-" and f[8:].isdigit() else ""  # solo ISO


def planner(x, plan, cubo=""):
    t = {"planId": plan, "title": _tit(x), **({"bucketId": cubo} if cubo else {}), **({"dueDateTime": _fecha(x) + "T12:00:00Z"} if _fecha(x) else {})}
    r = g("POST", "/planner/tasks", t)
    if _cuerpo(x):  # la descripción vive en /details y pide If-Match
        d = g("GET", f"/planner/tasks/{r['id']}/details")
        g("PATCH", f"/planner/tasks/{r['id']}/details", {"description": _cuerpo(x)[:30000]}, {"If-Match": d["@odata.etag"], "Prefer": "return=minimal"})
    return r["id"], f"https://tasks.office.com/Home/Task/{r['id']}"


def todo(x, lista=""):
    if not lista:
        ls = g("GET", "/me/todo/lists")["value"]
        lista = next((l["id"] for l in ls if l.get("wellknownListName") == "defaultList"), ls[0]["id"] if ls else "")
    t = {"title": _tit(x), "body": {"content": _cuerpo(x), "contentType": "text"}, **({"dueDateTime": {"dateTime": _fecha(x) + "T00:00:00", "timeZone": "UTC"}} if _fecha(x) else {})}
    r = g("POST", f"/me/todo/lists/{lista}/tasks", t)
    return r["id"], "https://to-do.live.com/tasks/"


def md_html(md):
    """Markdown mínimo -> HTML: títulos #, viñetas -, párrafos."""
    out, li = [], False
    for ln in str(md).splitlines():
        t = ln.strip()
        b = t.startswith(("- ", "* "))
        out.append("</ul>" if li and not b else "<ul>" if b and not li else "")
        li = b
        if b:
            out.append(f"<li>{html.escape(t[2:])}</li>")
        elif t.startswith("#"):
            n = min(len(t) - len(t.lstrip("#")), 3) + 1
            out.append(f"<h{n}>{html.escape(t.lstrip('# '))}</h{n}>")
        elif t:
            out.append(f"<p>{html.escape(t)}</p>")
    return "".join(out) + ("</ul>" if li else "")


def onenote(titulo, md, seccion=""):
    h = f"<!DOCTYPE html><html><head><title>{html.escape(titulo)}</title></head><body>{md_html(md)}</body></html>"
    r = g("POST", f"/me/onenote/sections/{seccion}/pages" if seccion else "/me/onenote/pages", h.encode(), {"Content-Type": "text/html"})
    return r["id"], (r.get("links") or {}).get("oneNoteWebUrl", {}).get("href", "")


def teams(titulo, md, equipo, canal):
    r = g("POST", f"/teams/{equipo}/channels/{canal}/messages", {"subject": titulo[:250], "body": {"contentType": "html", "content": md_html(md)[:28000]}})
    return r["id"], r.get("webUrl", "")


def correo(asunto, cuerpo_html, para, adjuntos=(), cc=""):
    """Envía con Outlook (Mail.Send). adjuntos: [(nombre, bytes)]."""
    if sum(len(b) for _, b in adjuntos) > MAIL_MAX:
        raise RuntimeError("Adjuntos demasiado grandes para enviar por correo de Graph (máx. ~3 MB): súbelos a OneDrive")
    dest = lambda s: [{"emailAddress": {"address": a.strip()}} for a in str(s).replace(";", ",").split(",") if a.strip()]
    if not dest(para):
        raise RuntimeError("Falta el destinatario")
    m = {"subject": asunto, "body": {"contentType": "html", "content": cuerpo_html}, "toRecipients": dest(para), "ccRecipients": dest(cc),
         "attachments": [{"@odata.type": "#microsoft.graph.fileAttachment", "name": n, "contentBytes": base64.b64encode(b).decode()} for n, b in adjuntos]}
    g("POST", "/me/sendMail", {"message": m, "saveToSentItems": True})
    return "", ""


# ---------- tipos de destino (esquema de destinos_tipos.TIPOS) ----------
def F(id, etiqueta, tipo="texto", req=False, preset=False, **k):
    return {"id": id, "etiqueta": etiqueta, "tipo": tipo, "req": req, "preset": preset, **k}


def _pagina_ficheros(x):
    return x.get("ficheros") or [(x["titulo"] + ".md", x["md"].encode())]


def _onedrive(c, s, o, x, n=None):
    r = [subir(nom, b, o.get("carpeta", ""), o.get("sitio", ""), o.get("biblioteca", "")) for nom, b in _pagina_ficheros(x)]
    return r[0]


def _planner(c, s, o, x, n=None):
    return planner(x, o["plan"], o.get("cubo", ""))


def _todo(c, s, o, x, n=None):
    return todo(x, o.get("lista", ""))


def _onenote(c, s, o, x, n=None):
    return onenote(x["titulo"], x["md"], o.get("seccion", ""))


def _teams(c, s, o, x, n=None):
    return teams(x["titulo"], x["md"], o["equipo"], o["canal"])


def _outlook(c, s, o, x, n=None):
    return correo(o.get("asunto") or x["titulo"], md_html(x["md"]), o["para"], x.get("ficheros") or (), o.get("cc", ""))


def _p(o, s):
    g("GET", "/me?$select=id")


TIPOS_GRAPH = {
    "ms_onedrive": {"nombre": "Microsoft 365: OneDrive / SharePoint", "modo": "pagina", "http": True, "archivos": True, "crear": _onedrive, "probar": _p,
                    "campos": [F("carpeta", "Carpeta (ruta en la biblioteca)", preset=True), F("sitio", "SharePoint: id del sitio (vacío = tu OneDrive)", preset=True), F("biblioteca", "SharePoint: id de la biblioteca (vacío = la predeterminada)", preset=True)]},
    "ms_planner": {"nombre": "Microsoft 365: Planner", "modo": "items", "http": True, "crear": _planner, "probar": _p,
                   "campos": [F("plan", "ID del plan", req=True, preset=True), F("cubo", "ID del cubo (opcional)", preset=True)]},
    "ms_todo": {"nombre": "Microsoft 365: To Do", "modo": "items", "http": True, "crear": _todo, "probar": _p,
                "campos": [F("lista", "ID de la lista (vacío = Tareas)", preset=True)]},
    "ms_onenote": {"nombre": "Microsoft 365: OneNote", "modo": "pagina", "http": True, "crear": _onenote, "probar": _p,
                   "campos": [F("seccion", "ID de la sección (vacío = la predeterminada)", preset=True)]},
    "ms_teams": {"nombre": "Microsoft 365: canal de Teams", "modo": "pagina", "http": True, "crear": _teams, "probar": _p,
                 "campos": [F("equipo", "ID del equipo", req=True, preset=True), F("canal", "ID del canal", req=True, preset=True)]},
    "ms_outlook": {"nombre": "Microsoft 365: correo de Outlook", "modo": "pagina", "http": True, "archivos": True, "crear": _outlook, "probar": _p,
                   "campos": [F("para", "Para (coma)", req=True, preset=True), F("cc", "Cc (coma)", preset=True), F("asunto", "Asunto (vacío = título)", preset=True)]},
}

# ---------- API ----------
router = APIRouter()


@router.post("/api/ms/login")
def api_login(d: dict = None):
    d = d or {}
    try:
        r = iniciar(str(d.get("tenant") or ""), str(d.get("client_id") or ""), d.get("funciones"))
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    threading.Thread(target=_sondear, daemon=True).start()
    return r


@router.get("/api/ms/estado")
def api_estado():
    c = config()
    return {"conectado": bool(_refresco()) and bool(c["cuenta"]), "cuenta": c["cuenta"], "scopes": c["scopes"], "client_id": c["client_id"], "tenant": c["tenant"],
            "login": _L["estado"], **({"error": _L["msg"]} if _L["msg"] else {})}


@router.post("/api/ms/logout")
def api_logout():
    cerrar()
    return {"ok": True}
