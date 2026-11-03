"""Tipos de destino de destinos.py (tabla). Cada tipo: crear/actualizar(conf, secretos, opciones, x[, id_externo]) -> (id, url); probar(opciones, secretos) -> None|str.
modo "items": un envío por elemento (x: titulo, cuerpo, codigo, dueno, fecha_limite…); modo "pagina": un envío (x: titulo, md, ficheros[(nombre, bytes)], json).
Solo stdlib. Servidores propios: URL base en cada tipo HTTP + verificación TLS desactivable / CA propia (ver `tls`)."""
import base64
import contextlib
import datetime as dt
import hashlib
import hmac
import json
import re
import shutil
import smtplib
import ssl
import subprocess
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from email.message import EmailMessage
from pathlib import Path

import pipeline as P

_L = threading.local()


@contextlib.contextmanager
def tls(o):
    """Contexto TLS de las llamadas HTTP de este hilo: o["verificar_tls"] falso -> sin verificar (servidor propio autofirmado); o["ca"] -> ese .pem."""
    ctx = None
    if o.get("verificar_tls") in (False, "false", 0, "0"):
        ctx = ssl._create_unverified_context()
    elif o.get("ca"):
        ctx = ssl.create_default_context(cafile=str(Path(o["ca"]).expanduser()))
    _L.ctx = ctx
    try:
        yield
    finally:
        _L.ctx = None


def http(met, url, h=None, body=None, raw=False):
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    hd = {"User-Agent": "actas", **({"Content-Type": "application/json"} if isinstance(body, (dict, list)) else {}), **(h or {})}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data, hd, method=met), timeout=25, context=getattr(_L, "ctx", None)) as r:
            b = r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read()[:300].decode('utf-8', 'replace')}") from None
    except (urllib.error.URLError, OSError, ssl.SSLError) as e:
        raise RuntimeError(f"Sin conexión: {getattr(e, 'reason', e)}") from None
    return b if raw or b.strip()[:1] not in (b"{", b"[") else json.loads(b)


def _basic(u, p):
    return {"Authorization": "Basic " + base64.b64encode(f"{u}:{p}".encode()).decode()}


def _bearer(t):
    return {"Authorization": "Bearer " + t}


def _lista(s):
    return [x.strip() for x in (s if isinstance(s, list) else str(s or "").replace(";", ",").split(",")) if str(x).strip()]


def _cuerpo(x):
    p = [x["cuerpo"]] if x.get("cuerpo") else []
    p += [f"{a}: {x[k]}" for k, a in (("dueno", "Responsable"), ("fecha_limite", "Plazo"), ("prioridad", "Prioridad")) if x.get(k)]
    p += [f"Origen: {x['origen']}"] if x.get("origen") else []
    p += [f"Enlace: {u}" for u in x.get("enlaces", [])]
    return "\n\n".join(p)


def _tit(x):
    return ((f"{x['codigo']} " if x.get("codigo") else "") + x["titulo"])[:250]


U = lambda o, d: (o.get("url") or d).rstrip("/")


# ---------- trackers (un ítem = una incidencia) ----------
def _gh(c, s, o, x, n=None, api="/repos/{repo}/issues", base="https://api.github.com", pre="token "):
    r = http("PATCH" if n else "POST", U(o, base) + api.format(repo=o["repo"]) + (f"/{n}" if n else ""), {"Authorization": pre + s["token"], "Accept": "application/vnd.github+json"},
             {"title": _tit(x), "body": _cuerpo(x), **({"labels": _lista(o.get("etiquetas"))} if o.get("etiquetas") else {})})
    return str(r["number"]), r["html_url"]


def _gitea(c, s, o, x, n=None):  # Gitea/Forgejo: API tipo GitHub bajo /api/v1 (las etiquetas piden ids: no se envían)
    r = http("PATCH" if n else "POST", f"{o['url'].rstrip('/')}/api/v1/repos/{o['repo']}/issues" + (f"/{n}" if n else ""), {"Authorization": "token " + s["token"]}, {"title": _tit(x), "body": _cuerpo(x)})
    return str(r["number"]), r["html_url"]


def _gl(c, s, o, x, n=None):
    r = http("PUT" if n else "POST", f"{U(o, 'https://gitlab.com')}/api/v4/projects/{urllib.parse.quote(o['proyecto'], safe='')}/issues" + (f"/{n}" if n else ""), {"PRIVATE-TOKEN": s["token"]},
             {"title": _tit(x), "description": _cuerpo(x), "labels": ",".join(_lista(o.get("etiquetas")))})
    return str(r["iid"]), r["web_url"]


def _jh(o, s):
    cloud = o.get("modo", "cloud") == "cloud"
    return ("3" if cloud else "2"), (_basic(o["email"], s["token"]) if cloud else _bearer(s["token"])), o["url"].rstrip("/")


def _adf(t):
    return {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": ln}]} for ln in t.splitlines() if ln.strip()]}


def _jira(c, s, o, x, n=None):
    v, h, u = _jh(o, s)
    d = _cuerpo(x)
    f = {"summary": _tit(x), "description": _adf(d) if v == "3" else d}
    if n:
        http("PUT", f"{u}/rest/api/{v}/issue/{n}", h, {"fields": f})
        return n, f"{u}/browse/{n}"
    r = http("POST", f"{u}/rest/api/{v}/issue", h, {"fields": {**f, "project": {"key": o["proyecto"]}, "issuetype": {"name": o.get("tipo_issue") or "Task"}}})
    return r["key"], f"{u}/browse/{r['key']}"


def _gql(o, s, q, v):
    r = http("POST", U(o, "https://api.linear.app/graphql"), {"Authorization": s["token"]}, {"query": q, "variables": v})
    if r.get("errors"):
        raise RuntimeError(str(r["errors"][0].get("message", r["errors"]))[:300])
    return r["data"]


def _linear(c, s, o, x, n=None):
    i = {"title": _tit(x), "description": _cuerpo(x)}
    if n:
        r = _gql(o, s, "mutation($id:String!,$i:IssueUpdateInput!){issueUpdate(id:$id,input:$i){success issue{id url}}}", {"id": n, "i": i})["issueUpdate"]
    else:
        r = _gql(o, s, "mutation($i:IssueCreateInput!){issueCreate(input:$i){success issue{id url}}}", {"i": {**i, "teamId": o["equipo"]}})["issueCreate"]
    return r["issue"]["id"], r["issue"]["url"]


def _todoist(c, s, o, x, n=None):
    b = {"content": _tit(x)[:500], "description": _cuerpo(x), "labels": _lista(o.get("etiquetas"))}
    if not n:
        b |= {"project_id": o["proyecto"]} if o.get("proyecto") else {}
        b |= {"due_string": x["fecha_limite"]} if x.get("fecha_limite") and x["fecha_limite"][:1].isdigit() else {}
    r = http("POST", f"{U(o, 'https://api.todoist.com/rest/v2')}/tasks" + (f"/{n}" if n else ""), _bearer(s["token"]), b)
    return str(r["id"]), r.get("url", "")


def _trh(s):
    return {"Authorization": f'OAuth oauth_consumer_key="{s["clave_api"]}", oauth_token="{s["token"]}"'}


def _trello(c, s, o, x, n=None):
    q = urllib.parse.urlencode({"name": _tit(x), "desc": _cuerpo(x), **({} if n else {"idList": o["lista"]})})
    r = http("PUT" if n else "POST", f"{U(o, 'https://api.trello.com/1')}/cards" + (f"/{n}" if n else "") + "?" + q, _trh(s))
    return r["id"], r.get("shortUrl", "")


def _azure(c, s, o, x, n=None):
    h = {**_basic("", s["token"]), "Content-Type": "application/json-patch+json"}
    b = [{"op": "add", "path": "/fields/System.Title", "value": _tit(x)}, {"op": "add", "path": "/fields/System.Description", "value": _cuerpo(x).replace("\n", "<br>")}]
    q = f"{o['url'].rstrip('/')}/{urllib.parse.quote(o['proyecto'])}/_apis/wit/workitems"
    r = http("PATCH", f"{q}/{n}?api-version=7.1", h, [{**p, "op": "replace"} for p in b]) if n else http("POST", f"{q}/${urllib.parse.quote(o.get('tipo_item') or 'Task')}?api-version=7.1", h, b)
    return str(r["id"]), r.get("_links", {}).get("html", {}).get("href", "")


# ---------- páginas / documentos ----------
def _bloques(md):
    out = []
    for ln in (z.strip() for z in md.splitlines()):
        if not ln:
            continue
        t, txt = "paragraph", ln
        for p, tt in (("### ", "heading_3"), ("## ", "heading_2"), ("# ", "heading_1"), ("- [ ] ", "to_do"), ("- [x] ", "to_do"), ("- ", "bulleted_list_item")):
            if ln.startswith(p):
                t, txt = tt, ln[len(p):]
                break
        b = {"rich_text": [{"type": "text", "text": {"content": txt[i:i + 2000]}} for i in range(0, len(txt), 2000)]}
        out.append({"object": "block", "type": t, t: b | ({"checked": False} if t == "to_do" else {})})
    return out


def _notion(c, s, o, x, n=None):
    u, h = U(o, "https://api.notion.com"), {**_bearer(s["token"]), "Notion-Version": "2022-06-28"}
    if n:  # ponytail: actualizar = archivar la página anterior y crear otra (no se diferencian bloques)
        http("PATCH", f"{u}/v1/pages/{n}", h, {"archived": True})
    bl = _bloques(x["md"])
    r = http("POST", f"{u}/v1/pages", h, {"parent": {"page_id": o["padre"]}, "properties": {"title": {"title": [{"type": "text", "text": {"content": x["titulo"][:2000]}}]}}, "children": bl[:100]})
    for i in range(100, len(bl), 100):
        http("PATCH", f"{u}/v1/blocks/{r['id']}/children", h, {"children": bl[i:i + 100]})
    return r["id"], r.get("url", "")


def _outline(c, s, o, x, n=None):
    d = {"title": x["titulo"], "text": x["md"]}
    r = http("POST", o["url"].rstrip("/") + ("/api/documents.update" if n else "/api/documents.create"), _bearer(s["token"]), {**d, **({"id": n} if n else {"collectionId": o["coleccion"], "publish": True})})["data"]
    return r["id"], o["url"].rstrip("/") + r.get("url", "")


def _bookstack(c, s, o, x, n=None):
    u = o["url"].rstrip("/")
    r = http("PUT" if n else "POST", f"{u}/api/pages" + (f"/{n}" if n else ""), {"Authorization": f"Token {o['token_id']}:{s['token_secreto']}"}, {"name": x["titulo"], "markdown": x["md"], **({} if n else {"book_id": int(o["libro"])})})
    return str(r["id"]), f"{u}/link/{r['id']}"


def _paperless(c, s, o, x, n=None):
    nom, b = next(((a, d) for a, d in x["ficheros"] if not a.endswith(".md")), (x["ficheros"][0][0].removesuffix(".md") + ".txt", x["md"].encode()))
    bd, crlf = uuid.uuid4().hex, b"\r\n"
    body = b"".join(f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in (("title", x["titulo"]),)) + \
        f'--{bd}\r\nContent-Disposition: form-data; name="document"; filename="{nom}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + b + crlf + f"--{bd}--\r\n".encode()
    r = http("POST", o["url"].rstrip("/") + "/api/documents/post_document/", {"Authorization": "Token " + s["token"], "Content-Type": "multipart/form-data; boundary=" + bd}, body, raw=True)
    return r.decode().strip('"\n'), o["url"].rstrip("/") + "/documents/"


def _dav_h(o, s):
    return _basic(o["usuario"], s["clave"]) if o.get("usuario") else {}


def _dav(c, s, o, x, n=None):
    base, h = o["url"].rstrip("/"), _dav_h(o, s)
    acum = base
    for p in (q for q in o.get("ruta", "").split("/") if q):
        acum += "/" + urllib.parse.quote(p)
        try:
            http("MKCOL", acum, h)
        except RuntimeError:
            pass  # ya existe (405) o sin permiso: el PUT dirá
    u = ""
    for nom, b in x["ficheros"]:
        u = acum + "/" + urllib.parse.quote(nom)
        http("PUT", u, h, b, raw=True)
    return "", u


def _carpeta(c, s, o, x, n=None):
    d = Path(o["ruta"]).expanduser() / o.get("subcarpeta", "")
    for nom, b in x["ficheros"]:
        p = (d / nom).resolve()
        if not p.is_relative_to(d.resolve()):
            raise RuntimeError(f"Ruta no permitida: {nom}")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
    return "", (d / x["ficheros"][0][0]).as_uri()


def _ok_dir(o):
    if not Path(o["ruta"]).expanduser().is_dir():
        raise RuntimeError("La carpeta no existe")


# ---------- webhooks ----------
def _webhook(c, s, o, x, n=None):
    b = {"json": {"titulo": x["titulo"], "enviado": dt.datetime.now().isoformat(timespec="seconds"), "origen": "actas", **x["json"]}, "discord": {"content": f"**{x['titulo']}**\n{x['md']}"[:2000]}}[o.get("mensaje") or "json"]
    body = json.dumps(b, ensure_ascii=False).encode()
    h = {"Content-Type": "application/json", **json.loads(s.get("cabeceras") or "{}")}
    if s.get("firma"):
        h["X-Actas-Signature"] = "sha256=" + hmac.new(s["firma"].encode(), body, hashlib.sha256).hexdigest()
    http("POST", o["url"], h, body, raw=True)
    return "", o["url"].split("?")[0]


TIPNAME = {"tarea": "Tareas", "decision": "Decisiones", "riesgo": "Riesgos", "requisito": "Requisitos", "historia": "Historias de usuario", "interesado": "Interesados"}


def _linea(i, mrk):
    return ("☐ " if i["tipo"] == "tarea" else "• ") + (f"*{i['codigo']}* " if i.get("codigo") and mrk else f"{i['codigo']} " if i.get("codigo") else "") + i["titulo"] + \
        (f" — {i['dueno']}" if i.get("dueno") else "") + (f" ({i['fecha_limite']})" if i.get("fecha_limite") else "")


def _trozos(lineas, n):
    out, cur = [], ""
    for ln in lineas:
        ln = ln[:n]
        if cur and len(cur) + len(ln) + 1 > n:
            out.append(cur)
            cur = ""
        cur += ("\n" if cur else "") + ln
    return out + ([cur] if cur else [])


def slack_mensajes(x):
    """Block Kit: cabecera, resumen, y por tipo una lista (secciones de <=2900 car.); en mensajes de <=40 bloques."""
    js, sec = x["json"], lambda t: {"type": "section", "text": {"type": "mrkdwn", "text": t}}
    bl = [sec(t) for t in _trozos((js.get("resumen") or "").splitlines(), 2900)]
    for tp, nom in TIPNAME.items():
        for k, t in enumerate(_trozos([_linea(i, True) for i in js["items"] if i["tipo"] == tp], 2900)):
            bl.append(sec((f"*{nom}*\n" if k == 0 else "") + t))
    bl = bl or [sec(t) for t in _trozos(js.get("texto", "").splitlines(), 2900)]
    cab = {"type": "header", "text": {"type": "plain_text", "text": x["titulo"][:150]}}
    return [{"text": x["titulo"], "blocks": ([cab] if i == 0 else []) + bl[i:i + 39]} for i in range(0, max(len(bl), 1), 39)]


def _slack(c, s, o, x, n=None):
    for m in slack_mensajes(x):
        http("POST", s["webhook"], None, m, raw=True)
    fs = [f for f in x["ficheros"] if not f[0].endswith(".md")]
    if s.get("bot") and o.get("canal") and fs:  # subida de archivos (API nueva): getUploadURLExternal -> PUT bytes -> completeUploadExternal
        api, h = U(o, "https://slack.com/api"), _bearer(s["bot"])
        for nom, b in fs:
            r = http("POST", api + "/files.getUploadURLExternal", {**h, "Content-Type": "application/x-www-form-urlencoded"}, urllib.parse.urlencode({"filename": nom, "length": len(b)}).encode())
            if not r.get("ok"):
                raise RuntimeError("Slack: " + str(r.get("error")))
            http("POST", r["upload_url"], None, b, raw=True)
            r = http("POST", api + "/files.completeUploadExternal", h, {"files": [{"id": r["file_id"], "title": nom}], "channel_id": o["canal"]})
            if not r.get("ok"):
                raise RuntimeError("Slack: " + str(r.get("error")))
    return "", s["webhook"].split("/services")[0]


def teams_payload(x, limite=27000):
    """Tarjeta adaptable para un webhook de Workflows (~28 KB): si no cabe, se recorta y se avisa «ver más en el documento»."""
    js = x["json"]
    tb = lambda t, **k: {"type": "TextBlock", "text": t, "wrap": True, **k}
    body = [tb(x["titulo"], weight="Bolder", size="Large")] + ([tb(js["resumen"])] if js.get("resumen") else [])
    for tp, nom in TIPNAME.items():
        its = [i for i in js["items"] if i["tipo"] == tp]
        if its:
            body += [tb(nom, weight="Bolder", spacing="Medium")] + [tb(_linea(i, False), spacing="Small") for i in its]
    if len(body) == 1:
        body += [tb(ln) for ln in js.get("texto", "").splitlines() if ln.strip()]
    card = lambda b: {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard", "version": "1.4", "body": b}}]}
    if len(json.dumps(card(body)).encode()) <= limite:
        return card(body)
    while len(body) > 2 and len(json.dumps(card(body + [tb("… ver más en el documento")])).encode()) > limite:
        body.pop()
    return card(body + [tb("… ver más en el documento", isSubtle=True)])


def _teams(c, s, o, x, n=None):
    http("POST", s["webhook"], None, teams_payload(x), raw=True)
    return "", ""


def _p_slack(o, s):
    http("POST", s["webhook"], None, {"text": "Prueba de Actas: conexión correcta"}, raw=True)


def _p_teams(o, s):
    _teams(None, s, o, {"titulo": "Prueba de Actas", "json": {"items": [], "texto": "Conexión correcta"}})


# ---------- servidores propios: SFTP (OpenSSH del sistema), S3 (SigV4) ----------
def _ssh(o, puerto="-p"):
    kh = P.WORK / "known_hosts"
    return ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={kh}", "-o", "ConnectTimeout=15", puerto, str(o.get("puerto") or 22)] + (["-i", str(Path(o["clave"]).expanduser())] if o.get("clave") else [])


def _run(cmd, inp=None):
    if not shutil.which(cmd[0]):
        raise RuntimeError(f"Falta «{cmd[0]}» (cliente OpenSSH del sistema)")
    r = subprocess.run(cmd, input=inp, capture_output=True, text=True, timeout=180)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip()[-300:] or f"{cmd[0]} falló")
    return r.stdout


def _sftp(c, s, o, x, n=None):
    d = (o.get("dir") or ".").rstrip("/") or "/"
    if not re.fullmatch(r"[\w./ ~-]+", d) or any(re.search(r'["\n\\]', f[0]) for f in x["ficheros"]):
        raise RuntimeError("Ruta remota o nombre de fichero con caracteres no permitidos")
    dest = f"{o['usuario']}@{o['host']}"
    with tempfile.TemporaryDirectory() as t:
        cmds = [f'-mkdir "{d}"']
        for i, (nom, b) in enumerate(x["ficheros"]):
            (Path(t) / str(i)).write_bytes(b)
            cmds.append(f'put "{Path(t) / str(i)}" "{d}/{nom}"')
        _run(["sftp", "-b", "-", *_ssh(o, "-P"), dest], "\n".join(cmds) + "\n")
    if o.get("comando"):  # solo si el usuario lo escribió (desactivado por defecto)
        _run(["ssh", *_ssh(o), dest, o["comando"]])
    return "", f"sftp://{dest}:{o.get('puerto') or 22}{d if d.startswith('/') else '/' + d}/{x['ficheros'][0][0]}"


def _p_sftp(o, s):
    _run(["ssh", *_ssh(o), f"{o['usuario']}@{o['host']}", "true"])
    kh = P.WORK / "known_hosts"
    h = o["host"] if str(o.get("puerto") or 22) == "22" else f"[{o['host']}]:{o['puerto']}"
    try:
        fp = _run(["ssh-keygen", "-l", "-F", h, "-f", str(kh)]).strip().splitlines()[-1]
    except Exception:
        fp = "(sin huella)"
    return f"Conexión correcta. Huella del servidor (compárala con la real): {fp}"


def sigv4(met, path, query, hd, ph, ak, sk, region, service, amz):
    """AWS Signature V4 -> valor de Authorization. hd: cabeceras a firmar (claves en minúscula); path ya codificado."""
    ns = sorted(hd)
    creq = "\n".join([met, path, query, "".join(f"{k}:{' '.join(str(hd[k]).split())}\n" for k in ns), ";".join(ns), ph])
    sc = f"{amz[:8]}/{region}/{service}/aws4_request"
    k = ("AWS4" + sk).encode()
    for m in (amz[:8], region, service, "aws4_request"):
        k = hmac.new(k, m.encode(), hashlib.sha256).digest()
    sig = hmac.new(k, "\n".join(["AWS4-HMAC-SHA256", amz, sc, hashlib.sha256(creq.encode()).hexdigest()]).encode(), hashlib.sha256).hexdigest()
    return f"AWS4-HMAC-SHA256 Credential={ak}/{sc}, SignedHeaders={';'.join(ns)}, Signature={sig}"


def _s3req(met, o, s, key, body=b"", query=""):
    ep = o["endpoint"].rstrip("/")
    path = f"/{o['bucket']}" + (f"/{urllib.parse.quote(key, safe='/~')}" if key else "")
    ph, amz = hashlib.sha256(body).hexdigest(), dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    hd = {"host": urllib.parse.urlparse(ep).netloc, "x-amz-content-sha256": ph, "x-amz-date": amz}
    a = sigv4(met, path, query, hd, ph, s["acceso"], s["secreto"], o.get("region") or "us-east-1", "s3", amz)
    return http(met, ep + path + (f"?{query}" if query else ""), {"x-amz-content-sha256": ph, "x-amz-date": amz, "Authorization": a}, body or None, raw=True)


def _s3(c, s, o, x, n=None):
    k = ""
    for nom, b in x["ficheros"]:
        k = "/".join(p for p in (o.get("prefijo", "").strip("/"), nom) if p)
        _s3req("PUT", o, s, k, b)
    return k, f"{o['endpoint'].rstrip('/')}/{o['bucket']}/{k}"



PA_SCHEMA = {"type": "object", "properties": {"origen": {"type": "string"}, "proyecto": {"type": "string"}, "documento": {"type": "string"}, "enlace_local": {"type": "string"},
             "elementos": {"type": "array", "items": {"type": "object", "properties": {k: {"type": "string"} for k in ("tipo", "titulo", "descripcion", "responsable", "fecha", "prioridad", "cita")}}},
             "archivo": {"type": "object", "properties": {"nombre": {"type": "string"}, "base64": {"type": "string"}}}}}


def pa_payload(o, x):
    js = x["json"]
    d = {"origen": "actas", "proyecto": js.get("carpeta") or "", "documento": (js.get("documento") or {}).get("titulo") or x["titulo"], "enlace_local": js.get("enlace") or "",
         "elementos": [{"tipo": i["tipo"], "titulo": i["titulo"], "descripcion": i.get("cuerpo", ""), "responsable": i.get("dueno", ""), "fecha": i.get("fecha_limite", ""), "prioridad": i.get("prioridad", ""), "cita": i.get("origen", "")} for i in js["items"]]}
    if o.get("adjuntar") in (True, "true", 1) and x["ficheros"]:
        nom, b = next((f for f in x["ficheros"] if not f[0].endswith(".md")), x["ficheros"][0])
        if len(b) <= 4_000_000:
            d["archivo"] = {"nombre": nom, "base64": base64.b64encode(b).decode()}
    return d


def _pa(c, s, o, x, n=None):
    http("POST", s["webhook"], None, pa_payload(o, x), raw=True)
    return "", ""


def _p_pa(o, s):
    http("POST", s["webhook"], None, {"origen": "actas", "proyecto": "", "documento": "Prueba de Actas", "enlace_local": "", "elementos": []}, raw=True)

# ---------- correo ----------
def _smtp(o, s):
    ssl_ = o.get("seguridad") == "ssl"
    sv = (smtplib.SMTP_SSL if ssl_ else smtplib.SMTP)(o["servidor"], int(o.get("puerto") or (465 if ssl_ else 587)), timeout=20)
    try:
        if o.get("seguridad", "starttls") == "starttls":
            sv.starttls()
        if o.get("usuario"):
            sv.login(o["usuario"], s.get("clave", ""))
    except Exception:
        sv.close()
        raise
    return sv


def _correo(c, s, o, x, n=None):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = o["de"], ", ".join(_lista(o["para"])), x["titulo"]
    m.set_content(x["md"])
    for nom, b in x["ficheros"]:
        m.add_attachment(b, maintype="application", subtype="octet-stream", filename=nom)
    with _smtp(o, s) as sv:
        sv.send_message(m)
    return "", "mailto:" + m["To"]


def _p_smtp(o, s):
    with _smtp(o, s):
        pass


# ---------- catálogo ----------
def F(id, etiqueta, tipo="texto", req=False, preset=False, **k):
    return {"id": id, "etiqueta": etiqueta, "tipo": tipo, "req": req, "preset": preset, **k}


FMT = F("formatos", "Documento y formatos", "lista", preset=True, opciones=["md", "docx", "pdf", "obsidian", "notion", "ics", "csv", "xlsx", "json", "srt", "vtt"], defecto=["md"])
TOK = F("token", "Token", "secreto", True)
URLF = lambda d, req=False: F("url", "URL base (servidor propio: cambia aquí)", "url", req, defecto=d)
ET = F("etiquetas", "Etiquetas (coma)", preset=True)
TLS = [F("verificar_tls", "Verificar certificado TLS", "booleano", defecto=True, ayuda="Desactívalo solo para un servidor propio con certificado autofirmado: la conexión deja de comprobar a quién se conecta."),
       F("ca", "Certificado CA propio (ruta .pem)", "ruta")]
_h = lambda url: http("GET", url[0], url[1])
TIPOS = {
    "carpeta": {"nombre": "Carpeta local / Obsidian / Logseq", "modo": "pagina", "archivos": True, "crear": _carpeta, "probar": lambda o, s: _ok_dir(o),
                "campos": [F("ruta", "Carpeta (o bóveda)", "ruta", True), F("subcarpeta", "Subcarpeta", preset=True), F("vault", "Bóveda Obsidian/Logseq (enlaces [[ ]] y adjuntos)", "booleano", preset=True), FMT]},
    "webhook": {"nombre": "Webhook (n8n, Zapier, Make, Discord…)", "modo": "pagina", "http": True, "crear": _webhook, "probar": None,
                "campos": [F("url", "URL del webhook", "url", True), F("firma", "Secreto de firma HMAC-SHA256 (cabecera X-Actas-Signature)", "secreto"), F("cabeceras", "Cabeceras (JSON)", "secreto"),
                           F("mensaje", "Formato", "opcion", preset=True, opciones=["json", "discord"], defecto="json")]},
    "slack": {"nombre": "Slack", "modo": "pagina", "http": True, "archivos": True, "crear": _slack, "probar": _p_slack,
              "campos": [F("webhook", "URL del webhook entrante", "secreto", True, ayuda="El webhook solo envía texto (Block Kit). Para adjuntar el PDF/documento añade token de bot y canal."), F("bot", "Token de bot (xoxb-…, opcional: subir archivos)", "secreto"),
                         F("canal", "ID del canal (con el bot)", preset=True), FMT, URLF("https://slack.com/api")]},
    "teams": {"nombre": "Microsoft Teams (Workflows)", "modo": "pagina", "http": True, "crear": _teams, "probar": _p_teams,
              "campos": [F("webhook", "URL del flujo «Cuando se recibe una solicitud de webhook de Teams»", "secreto", True, ayuda="Contenido en línea (tarjeta adaptable, ~28 KB): los webhooks no pueden adjuntar archivos. Los conectores O365 antiguos están retirados.")]},
    "github": {"nombre": "GitHub Issues", "modo": "items", "http": True, "crear": _gh, "actualizar": _gh, "probar": lambda o, s: http("GET", U(o, "https://api.github.com") + "/user", {"Authorization": "token " + s["token"]}),
               "campos": [TOK, F("repo", "Repositorio (propietario/nombre)", req=True, preset=True), ET, URLF("https://api.github.com")]},
    "gitea": {"nombre": "Gitea / Forgejo Issues", "modo": "items", "http": True, "crear": _gitea, "actualizar": _gitea, "probar": lambda o, s: http("GET", o["url"].rstrip("/") + "/api/v1/user", {"Authorization": "token " + s["token"]}),
              "campos": [URLF("", True), TOK, F("repo", "Repositorio (propietario/nombre)", req=True, preset=True)]},
    "gitlab": {"nombre": "GitLab Issues (gitlab.com o propio)", "modo": "items", "http": True, "crear": _gl, "actualizar": _gl, "probar": lambda o, s: http("GET", U(o, "https://gitlab.com") + "/api/v4/user", {"PRIVATE-TOKEN": s["token"]}),
               "campos": [TOK, F("proyecto", "Proyecto (id o ruta)", req=True, preset=True), ET, URLF("https://gitlab.com")]},
    "jira": {"nombre": "Jira (Cloud, Server o Data Center)", "modo": "items", "http": True, "crear": _jira, "actualizar": _jira, "probar": lambda o, s: http("GET", f"{_jh(o, s)[2]}/rest/api/{_jh(o, s)[0]}/myself", _jh(o, s)[1]),
             "campos": [F("url", "URL de Jira", "url", True), F("modo", "Tipo", "opcion", True, opciones=["cloud", "server"], defecto="cloud"), F("email", "Correo (Cloud)"), F("token", "Token API (Cloud) o PAT (Server/DC)", "secreto", True),
                        F("proyecto", "Clave del proyecto", req=True, preset=True), F("tipo_issue", "Tipo de incidencia", preset=True, defecto="Task")]},
    "linear": {"nombre": "Linear", "modo": "items", "http": True, "crear": _linear, "actualizar": _linear, "probar": lambda o, s: _gql(o, s, "{viewer{id}}", {}),
               "campos": [F("token", "API key", "secreto", True), F("equipo", "ID del equipo", req=True, preset=True), URLF("https://api.linear.app/graphql")]},
    "notion": {"nombre": "Notion", "modo": "pagina", "http": True, "crear": _notion, "actualizar": _notion, "probar": lambda o, s: http("GET", U(o, "https://api.notion.com") + "/v1/users/me", {**_bearer(s["token"]), "Notion-Version": "2022-06-28"}),
               "campos": [F("token", "Token de la integración interna", "secreto", True), F("padre", "ID de la página padre", req=True, preset=True), URLF("https://api.notion.com")]},
    "outline": {"nombre": "Outline (propio)", "modo": "pagina", "http": True, "crear": _outline, "actualizar": _outline, "probar": lambda o, s: http("POST", o["url"].rstrip("/") + "/api/auth.info", _bearer(s["token"]), {}),
                "campos": [URLF("", True), TOK, F("coleccion", "ID de la colección", req=True, preset=True)]},
    "bookstack": {"nombre": "BookStack (propio)", "modo": "pagina", "http": True, "crear": _bookstack, "actualizar": _bookstack, "probar": lambda o, s: http("GET", o["url"].rstrip("/") + "/api/books?count=1", {"Authorization": f"Token {o['token_id']}:{s['token_secreto']}"}),
                  "campos": [URLF("", True), F("token_id", "Token ID", req=True), F("token_secreto", "Token secreto", "secreto", True), F("libro", "ID del libro", req=True, preset=True)]},
    "paperless": {"nombre": "Paperless-ngx (propio)", "modo": "pagina", "http": True, "archivos": True, "crear": _paperless, "probar": lambda o, s: http("GET", o["url"].rstrip("/") + "/api/documents/?page_size=1", {"Authorization": "Token " + s["token"]}),
                  "campos": [URLF("", True), TOK, {**FMT, "defecto": ["pdf"]}]},
    "todoist": {"nombre": "Todoist", "modo": "items", "http": True, "crear": _todoist, "actualizar": _todoist, "probar": lambda o, s: http("GET", U(o, "https://api.todoist.com/rest/v2") + "/projects", _bearer(s["token"])),
                "campos": [TOK, F("proyecto", "ID del proyecto", preset=True), ET, URLF("https://api.todoist.com/rest/v2")]},
    "trello": {"nombre": "Trello", "modo": "items", "http": True, "crear": _trello, "actualizar": _trello, "probar": lambda o, s: http("GET", U(o, "https://api.trello.com/1") + "/members/me", _trh(s)),
               "campos": [F("clave_api", "API key", "secreto", True), TOK, F("lista", "ID de la lista", req=True, preset=True), URLF("https://api.trello.com/1")]},
    "azure": {"nombre": "Azure DevOps (nube o Server)", "modo": "items", "http": True, "crear": _azure, "actualizar": _azure, "probar": lambda o, s: http("GET", o["url"].rstrip("/") + "/_apis/projects?api-version=7.1", _basic("", s["token"])),
              "campos": [F("url", "Organización (https://dev.azure.com/org)", "url", True), F("token", "PAT", "secreto", True), F("proyecto", "Proyecto", req=True, preset=True), F("tipo_item", "Tipo de work item", preset=True, defecto="Task")]},
    "webdav": {"nombre": "WebDAV / Nextcloud", "modo": "pagina", "http": True, "archivos": True, "crear": _dav, "probar": lambda o, s: http("PROPFIND", o["url"], {**_dav_h(o, s), "Depth": "0"}),
               "campos": [F("url", "URL WebDAV (Nextcloud: …/remote.php/dav/files/USUARIO)", "url", True), F("usuario", "Usuario"), F("clave", "Contraseña / token de app", "secreto"), F("ruta", "Carpeta remota", preset=True), FMT]},
    "s3": {"nombre": "S3 compatible (AWS, MinIO, Garage, B2, Wasabi, R2)", "modo": "pagina", "http": True, "archivos": True, "crear": _s3, "probar": lambda o, s: _s3req("GET", o, s, "", query="max-keys=0"),
           "campos": [F("endpoint", "Endpoint (https://s3.amazonaws.com, https://minio.local:9000…)", "url", True), F("region", "Región", defecto="us-east-1"), F("bucket", "Bucket", req=True), F("prefijo", "Prefijo", preset=True),
                      F("acceso", "Access key", "secreto", True), F("secreto", "Secret key", "secreto", True), FMT]},
    "sftp": {"nombre": "SFTP / SSH (OpenSSH del sistema)", "modo": "pagina", "archivos": True, "crear": _sftp, "probar": _p_sftp,
             "campos": [F("host", "Servidor", req=True), F("puerto", "Puerto", "numero", defecto=22), F("usuario", "Usuario", req=True), F("clave", "Ruta de la clave privada (o ssh-agent si vacío)", "ruta", ayuda="Nunca contraseñas: solo clave o agente. La huella del servidor se muestra al probar."),
                        F("dir", "Carpeta remota", preset=True), F("comando", "Comando tras subir (vacío = desactivado)", preset=True), FMT]},
    "power_automate": {"nombre": "Power Automate (Microsoft 365)", "modo": "pagina", "http": True, "archivos": True, "crear": _pa, "probar": _p_pa,
                       "campos": [F("webhook", "URL del desencadenador «Cuando se recibe una solicitud HTTP» / webhook de Teams", "secreto", True,
                                    ayuda="Desencadenador estándar (no premium). En el flujo usa «Analizar JSON» con este esquema y crea tareas de Planner/To Do, elementos de Lists, páginas de OneNote, archivos de SharePoint o correos de Outlook con tus propios permisos: " + json.dumps(PA_SCHEMA)),
                                  F("adjuntar", "Adjuntar el documento (base64, máx. 4 MB)", "booleano", preset=True), {**FMT, "opciones": ["pdf", "docx", "md"], "defecto": ["pdf"]}]},
    "correo": {"nombre": "Correo SMTP", "modo": "pagina", "archivos": True, "crear": _correo, "probar": _p_smtp,
               "campos": [F("servidor", "Servidor SMTP", req=True), F("puerto", "Puerto", "numero"), F("seguridad", "Seguridad", "opcion", opciones=["starttls", "ssl", "ninguna"], defecto="starttls"), F("usuario", "Usuario"),
                          F("clave", "Contraseña", "secreto"), F("de", "Remitente", req=True), F("para", "Destinatarios (coma)", req=True, preset=True), FMT]},
}
for _t in TIPOS.values():
    if _t.pop("http", False):
        _t["campos"] = _t["campos"] + TLS
SECRETOS = {t: [f["id"] for f in v["campos"] if f["tipo"] == "secreto"] for t, v in TIPOS.items()}
