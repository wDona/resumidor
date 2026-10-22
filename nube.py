"""Modelos en la nube (opcional, desactivado por defecto). Misma interfaz que pipeline.llama(): chat(system, user, schema, max_tokens) -> dict.
Dos vías: API compatible con OpenAI (clave en el llavero del sistema) o la CLI oficial que el usuario ya tiene con sesión iniciada
(claude, codex, gemini, copilot: sin tocar tokens). Solo sale texto (transcripción y texto leído en pantalla); nunca audio, vídeo ni capturas."""
import contextlib
import json
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

import pipeline as P

SERV = "actas-nube"
# id: nombre, URL base, json (2 = json_schema, 1 = solo json_object, 0 = ninguno), parámetro de tope de tokens, ¿GET /models?
PROV = {
    "openai": ("OpenAI", "https://api.openai.com/v1", 2, "max_completion_tokens", True),
    "anthropic": ("Anthropic (Claude)", "https://api.anthropic.com/v1", 0, "max_tokens", True),
    "gemini": ("Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", 2, "max_tokens", True),
    "mistral": ("Mistral", "https://api.mistral.ai/v1", 2, "max_tokens", True),
    "deepseek": ("DeepSeek", "https://api.deepseek.com/v1", 1, "max_tokens", True),
    "kimi": ("Kimi (Moonshot)", "https://api.moonshot.ai/v1", 1, "max_tokens", True),
    "groq": ("Groq", "https://api.groq.com/openai/v1", 2, "max_tokens", True),
    "xai": ("xAI (Grok)", "https://api.x.ai/v1", 2, "max_tokens", True),
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1", 2, "max_tokens", True),
    "azure": ("Azure OpenAI", "", 2, "max_completion_tokens", False),  # URL: https://<recurso>.openai.azure.com/openai/v1 ; modelo = nombre del despliegue
    "github": ("GitHub Models", "https://models.github.ai/inference", 2, "max_tokens", False),
    "propio": ("Servidor propio", "", 2, "max_tokens", True),  # vLLM / Ollama / LM Studio: URL base con /v1
}
CLIS = {"claude": ("Claude Code", ["claude", "-p", "--output-format", "json", "--max-turns", "1"]),
        "codex": ("Codex CLI", ["codex", "exec", "-"]),
        "gemini": ("Gemini CLI", ["gemini", "-p", "Responde a lo que recibes por la entrada estándar."]),
        "copilot": ("GitHub Copilot CLI", ["copilot", "-p", "Responde a lo que recibes por la entrada estándar."])}
CLI_AVISO = ("Gasta el cupo de tu suscripción y es más lento. Algunos proveedores reservan la suscripción al uso personal: "
             "en una empresa, lo habitual es usar una clave de API.")
ENVIA = "Se envía: texto de la transcripción y el texto leído en pantalla"
NUNCA = "Nunca sale de tu equipo: audio, vídeo, capturas, búsqueda"
FICHERO = lambda: P.WORK / "nube.json"
MODOS = ["json_schema", "json_object", "texto"]
_MODO = {}  # (proveedor, url) -> índice en MODOS que funcionó (se recuerda mientras corre la aplicación)
TOK = [0, 0]  # tokens enviados y recibidos (contador de la sesión)


# ---------- estado en disco (sin claves) ----------
def estado():
    try:
        d = json.loads(FICHERO().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    return {"confirmado": list(d.get("confirmado", [])), "precios": dict(d.get("precios", {})), "urls": dict(d.get("urls", {})), "modelos": dict(d.get("modelos", {}))}


def guardar(**kw):
    d = {**estado(), **kw}
    P.WORK.mkdir(exist_ok=True)
    FICHERO().write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return d


# ---------- claves: solo en el llavero del sistema ----------
def _kr():
    import keyring
    return keyring


def clave(prov):
    try:
        return _kr().get_password(SERV, prov) or ""
    except Exception:
        return ""


def poner_clave(prov, k):
    """Guarda (o borra, con k vacío) la clave. Nunca va a un fichero ni al registro."""
    kr = _kr()
    try:
        kr.set_password(SERV, prov, k.strip()) if k.strip() else kr.delete_password(SERV, prov)
    except kr.errors.PasswordDeleteError:
        pass
    except kr.errors.KeyringError:
        raise RuntimeError("Este equipo no tiene un llavero del sistema donde guardar la clave de forma segura") from None


def enmascarada(prov):
    k = clave(prov)
    return "" if not k else k[:3] + "…" + k[-4:] if len(k) >= 12 else "••••••••"


# ---------- configuración ----------
def cli_ruta(c):
    return shutil.which(CLIS[c][1][0])


def norm(d):
    """Valida la elección del usuario -> {proveedor, modelo, url, anonimizar}. La clave nunca viaja en ella."""
    p = str((d or {}).get("proveedor") or "")
    if p.startswith("cli:"):
        if p[4:] not in CLIS:
            raise ValueError("Proveedor no válido")
        return {"proveedor": p, "modelo": "", "url": "", "anonimizar": bool(d.get("anonimizar"))}
    if p not in PROV:
        raise ValueError("Proveedor no válido")
    url = str(d.get("url") or estado()["urls"].get(p) or PROV[p][1]).strip().rstrip("/")
    if not url.startswith(("https://", "http://")):
        raise ValueError("Falta la dirección del servidor (https://…)")
    modelo = str(d.get("modelo") or "").strip()
    if not modelo:
        raise ValueError("Elige un modelo")
    return {"proveedor": p, "modelo": modelo, "url": url, "anonimizar": bool(d.get("anonimizar"))}


def nombre(cfg):
    p = cfg["proveedor"]
    return CLIS[p[4:]][0] + " (suscripción)" if p.startswith("cli:") else f"{PROV[p][0]} / {cfg['modelo']}"


def marca(cfg):
    """Texto visible en el documento y en los exports."""
    return f"Redactado con {nombre(cfg)} (nube)"


def id_cache(cfg):
    """Entra en las claves de caché: nube y local (o dos proveedores/modelos) nunca comparten resultados."""
    p = cfg["proveedor"]
    return f"nube:{p}:{cfg['modelo']}" + (f"@{cfg['url']}" if p == "propio" else "") + (":anon" if cfg.get("anonimizar") else "")


def permitida(plantilla=None, ajustes=None):
    """-> (sí/no, motivo). Oculta con nube_visible=false o con un perfil/plantilla que no la permite (consulta profesional)."""
    if ajustes is not None and not ajustes.get("nube_visible", True):
        return False, "Los modelos en la nube están desactivados en Ajustes."
    if plantilla is not None and not plantilla.get("nube_permitida", True):
        return False, ("Este tipo de documento no se procesa en la nube: contiene datos especialmente protegidos (RGPD art. 9) "
                       "o sujetos a secreto profesional. Se hace solo en este equipo.")
    return True, ""


def detectar_clis():
    return [{"id": "cli:" + c, "nombre": n[0], "ruta": cli_ruta(c)} for c, n in CLIS.items() if cli_ruta(c)]


# ---------- HTTP ----------
def _cab(prov, k):
    h = {"Content-Type": "application/json", "User-Agent": "actas"}
    if prov == "azure":
        h["api-key"] = k
    else:
        h["Authorization"] = "Bearer " + k
    if prov == "anthropic":
        h.update({"x-api-key": k, "anthropic-version": "2023-06-01"})
    return h


class HTTPErr(RuntimeError):
    def __init__(s, code, msg):
        super().__init__(msg)
        s.code = code


def _post(url, prov, k, body, timeout=600):
    """POST JSON con 2 reintentos en 429/5xx. Los errores llevan solo el mensaje del proveedor (nunca la clave)."""
    for i in range(3):
        req = urllib.request.Request(url, json.dumps(body).encode(), _cab(prov, k))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            txt = e.read().decode("utf-8", "replace")[:400]
            if e.code in (429, 500, 502, 503, 529) and i < 2:
                time.sleep(2 + 3 * i if not _post.fast else 0)
                continue
            msg = {401: "clave rechazada", 403: "sin permiso", 404: "modelo o dirección no encontrados", 429: "límite de uso alcanzado"}.get(e.code, f"error {e.code}")
            raise HTTPErr(e.code, f"{msg}: {txt}".replace(k, "***") if k else txt) from None
        except OSError as e:
            if i < 2:
                time.sleep(2 if not _post.fast else 0)
                continue
            raise RuntimeError(f"No se pudo conectar con el proveedor: {e}".replace(k, "***") if k else str(e)) from None


_post.fast = False  # solo pruebas: sin esperas entre reintentos


def modelos(prov, url=None):
    """Ids de modelo del proveedor (GET /models); [] si no se puede (entonces el nombre se escribe a mano)."""
    if prov not in PROV or not PROV[prov][4]:
        return []
    base = (url or estado()["urls"].get(prov) or PROV[prov][1]).rstrip("/")
    if not base:
        return []
    req = urllib.request.Request(base + "/models", headers=_cab(prov, clave(prov)))
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.load(r)
    except (OSError, ValueError):
        return []
    its = d.get("data") or d.get("models") or [] if isinstance(d, dict) else d
    return sorted({re.sub(r"^models/", "", str(x.get("id") or x.get("name") or "")) if isinstance(x, dict) else str(x) for x in its} - {""})


# ---------- esquema: validación y compatibilidad ----------
def valida(x, s, ruta="$"):
    """Error (texto) o None. Tipos, obligatorios, enum y elementos; los topes de longitud los recorta luego el pipeline."""
    if "enum" in s:
        return None if x in s["enum"] else f"{ruta}: valor fuera de {s['enum']}"
    t = s.get("type")
    if t == "object":
        if not isinstance(x, dict):
            return f"{ruta}: debe ser un objeto"
        for k in s.get("required", []):
            if k not in x:
                return f"{ruta}: falta «{k}»"
        return next((e for k, v in s["properties"].items() if k in x and (e := valida(x[k], v, f"{ruta}.{k}"))), None)
    if t == "array":
        if not isinstance(x, list):
            return f"{ruta}: debe ser una lista"
        return next((e for i, v in enumerate(x) if (e := valida(v, s["items"], f"{ruta}[{i}]"))), None)
    if t == "string" and not isinstance(x, str):
        return f"{ruta}: debe ser texto"
    return None


def _estricto(s):
    """Esquema para response_format: sin topes ni patrón (muchos proveedores los rechazan); el patrón pasa a la descripción."""
    if isinstance(s, dict):
        o = {k: _estricto(v) for k, v in s.items() if k not in ("maxLength", "minLength", "pattern", "maxItems", "minItems")}
        if "pattern" in s:
            o["description"] = "formato m:ss o mm:ss"
        return o
    return s


def _json(txt):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt.strip())
    try:
        return json.loads(t)
    except ValueError:
        a, b = t.find("{"), t.rfind("}")
        if a < 0 or b <= a:
            raise ValueError("la respuesta no es JSON") from None
        try:
            return json.loads(t[a:b + 1])
        except ValueError as e:
            raise ValueError(f"JSON mal formado ({e})") from None


# ---------- anonimizar (solo regex: nada de LLM local) ----------
class Anon:
    """Cambia IBAN, DNI, teléfonos, correos… por [TIPO_n] antes de enviar y los devuelve en el resultado, en local."""
    def __init__(s):
        s.f, s.r, s.n = {}, {}, {}

    def ida(s, t):
        import privacidad
        for tipo, cl, val, a, b in reversed(privacidad.detectar_texto(t)):
            ps = s.f.get((tipo, cl))
            if not ps:
                s.n[tipo] = s.n.get(tipo, 0) + 1
                ps = s.f[(tipo, cl)] = f"[{privacidad.ETIQUETA[tipo].strip('[]')}_{s.n[tipo]}]"
                s.r[ps] = val
            t = t[:a] + ps + t[b:]
        return t

    def vuelta(s, x):
        if isinstance(x, str):
            return re.sub(r"\[[A-ZÁÉÍÓÚ]+_\d+\]", lambda m: s.r.get(m[0], m[0]), x) if s.r else x
        if isinstance(x, list):
            return [s.vuelta(v) for v in x]
        return {k: s.vuelta(v) for k, v in x.items()} if isinstance(x, dict) else x


# ---------- CLIs oficiales ----------
def _cli(c, prompt, timeout=1800):
    ruta = cli_ruta(c)
    if not ruta:
        raise RuntimeError(f"No se encuentra «{CLIS[c][1][0]}» en el equipo. Instálalo e inicia sesión.")
    r = subprocess.run([ruta, *CLIS[c][1][1:]], input=prompt, capture_output=True, text=True, timeout=timeout, cwd=tempfile.gettempdir())
    if r.returncode:
        raise RuntimeError(f"{CLIS[c][0]} falló ({r.returncode}): {(r.stderr or r.stdout).strip()[:300]}")
    out = r.stdout
    if c == "claude":
        with contextlib.suppress(ValueError):
            j = json.loads(out)
            if j.get("is_error"):
                raise RuntimeError(f"Claude Code: {str(j.get('result'))[:300]}")
            out = j.get("result", out)
    return out


# ---------- el chat ----------
def _instr(schema):
    return ("\n\nResponde SOLO con un objeto JSON válido (sin texto alrededor ni bloques de código) que cumpla este esquema JSON:\n"
            + json.dumps(_estricto(schema), ensure_ascii=False))


def _http(cfg, msgs, schema, max_tokens, temperature, seed):
    """Una llamada: baja de json_schema a json_object y a texto si el proveedor no lo admite. -> texto."""
    p, url = cfg["proveedor"], cfg["url"]
    _, _, js, mt, _ = PROV[p]
    k = clave(p)
    if not k and p != "propio":
        raise RuntimeError(f"Falta la clave de {PROV[p][0]}: añádela en la configuración de la nube")
    i = _MODO.get((p, url), {2: 0, 1: 1, 0: 2}[js])
    opc = {"temperature": temperature, "seed": seed}
    while True:
        body = {"model": cfg["modelo"], "messages": msgs, mt: max_tokens, **opc}
        if MODOS[i] == "json_schema":
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "respuesta", "strict": True, "schema": _estricto(schema)}}
        elif MODOS[i] == "json_object":
            body["response_format"] = {"type": "json_object"}
            body["messages"] = [{**msgs[0], "content": msgs[0]["content"] + _instr(schema)}, *msgs[1:]]
        else:
            body["messages"] = [{**msgs[0], "content": msgs[0]["content"] + _instr(schema)}, *msgs[1:]]
        try:
            r = _post(f"{url}/chat/completions", p, k, body)
            break
        except HTTPErr as e:
            if e.code not in (400, 422):
                raise
            low = str(e).lower()
            if opc and any(w in low for w in ("temperature", "seed")):
                opc = {}
            elif i < 2:
                i += 1
            else:
                raise
    _MODO[(p, url)] = i
    u = r.get("usage") or {}
    TOK[0] += u.get("prompt_tokens") or 0
    TOK[1] += u.get("completion_tokens") or 0
    print(f"  nube {u.get('prompt_tokens')}→{u.get('completion_tokens')} tok ({MODOS[i]})", flush=True)
    try:
        return r["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("Respuesta inesperada del proveedor") from None


def chat_fn(cfg):
    """chat(system, user, schema, max_tokens, ...) -> dict ya validado, con 1 reintento que le enseña el error al modelo."""
    an = Anon() if cfg.get("anonimizar") else None
    cli = cfg["proveedor"][4:] if cfg["proveedor"].startswith("cli:") else None

    def chat(system, user, schema, max_tokens, repeat_penalty=1.0, temperature=0.2, seed=0):
        if an:
            system, user = an.ida(system), an.ida(user)
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for intento in (0, 1):
            if cli:
                txt = _cli(cli, system + _instr(schema) + "\n\n" + "\n".join(m["content"] for m in msgs[1:]))
            else:
                txt = _http(cfg, msgs, schema, max_tokens, temperature, seed)
            try:
                x = _json(txt)
                err = valida(x, schema)
            except ValueError as e:
                err = str(e)
            if not err:
                return an.vuelta(x) if an else x
            msgs += [{"role": "assistant", "content": txt}, {"role": "user", "content": f"Tu respuesta no es válida ({err}). Devuelve solo el JSON corregido."}]
        raise RuntimeError(f"El modelo de la nube no devolvió un JSON válido: {err}")
    return chat


@contextlib.contextmanager
def backend(cfg):
    """Sustituto de pipeline.llama(): sin proceso, sin GPU."""
    yield chat_fn(cfg)


def texto(cfg, system, user, max_tokens=700):
    max_tokens = max(max_tokens, 700)  # los modelos de razonamiento gastan parte en pensar
    """Chat de texto libre (Preguntar). Con anonimizar, los datos viajan con seudónimos y vuelven en claro."""
    an = Anon() if cfg.get("anonimizar") else None
    s, u = (an.ida(system), an.ida(user)) if an else (system, user)
    if cfg["proveedor"].startswith("cli:"):
        out = _cli(cfg["proveedor"][4:], s + "\n\n" + u)
    else:
        p = cfg["proveedor"]
        k = clave(p)
        if not k and p != "propio":
            raise RuntimeError(f"Falta la clave de {PROV[p][0]}")
        body = {"model": cfg["modelo"], "messages": [{"role": "system", "content": s}, {"role": "user", "content": u}], PROV[p][3]: max_tokens, "temperature": 0}
        try:
            r = _post(f"{cfg['url']}/chat/completions", p, k, body)
        except HTTPErr as e:
            if e.code not in (400, 422):
                raise
            body.pop("temperature")
            r = _post(f"{cfg['url']}/chat/completions", p, k, body)
        out = r["choices"][0]["message"]["content"] or ""
    return an.vuelta(out) if an else out


# ---------- coste ----------
def estimar(chars, cfg=None):
    """Tokens aproximados de todo el trabajo (map + verificación + redacción) a partir de los caracteres de la transcripción, y coste si
    el modelo tiene precio en la tabla editable (USD por millón de tokens [entrada, salida]); sin precio, solo tokens."""
    n = -(-chars // P.CHUNK_CHARS) or 1
    ent = int(chars / 3.5 * 1.7 + (2 * n + 4) * 1500)
    sal = n * 900 + 1500
    r = {"entrada": ent, "salida": sal, "bloques": n, "coste": None, "moneda": "USD"}
    pr = estado()["precios"].get((cfg or {}).get("modelo", ""))
    if pr and len(pr) == 2:
        r["coste"] = round((ent * float(pr[0]) + sal * float(pr[1])) / 1e6, 2)
    return r


def info():
    """Para la interfaz: proveedores, CLIs detectadas y claves (enmascaradas), confirmaciones y precios."""
    e = estado()
    return {"proveedores": [{"id": k, "nombre": v[0], "url": e["urls"].get(k) or v[1], "lista": v[4], "clave": enmascarada(k), "confirmado": k in e["confirmado"],
                             "modelo": e["modelos"].get(k, ""), "json": v[2] == 2} for k, v in PROV.items()],
            "clis": [{**c, "confirmado": c["id"] in e["confirmado"]} for c in detectar_clis()], "precios": e["precios"], "envia": ENVIA, "nunca": NUNCA, "cli_aviso": CLI_AVISO}
