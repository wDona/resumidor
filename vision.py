"""Descripción de imágenes con IA (pantallazos, fotos de pizarras, capturas del vídeo), siempre en una llamada de chat estilo OpenAI con
la imagen en image_url (data: base64). Quién describe, por este orden (elegir()):
1) el servidor de visión de Ajustes (vision = {url, modelo}: LM Studio, Ollama, vLLM…): si es local (localhost) sin más; si no, solo
   con «Permitir enviar imágenes a la nube» (nube_imagenes, apagado de serie);
2) el proveedor de nube del trabajo, solo con nube_imagenes (las CLI no aceptan imágenes);
3) local: llama-server con Gemma 4 E4B + su mmproj (modelo «vision» del catálogo de Modelos, opcional).
Sin ninguno: None (la interfaz ve vision: "no_disponible" y sugiere instalarlo). Las capturas del vídeo se describen solo con la opción
«Describir capturas con IA» (describir_capturas, apagada de serie: cuesta tiempo)."""
import base64
import contextlib
import io
import json
import urllib.parse
import urllib.request
from pathlib import Path

import pipeline as P

PROMPT = ("Describe en español, de forma objetiva y en 120 palabras como mucho, qué muestra esta imagen o captura de pantalla: qué aplicación "
          "o pantalla es, mensajes de error visibles, gráficos (qué miden y su tendencia), tablas o diagramas. Si salen personas, descríbelas "
          "sin identificarlas (nunca digas quién es). No copies todo el texto: el texto de la imagen ya se lee aparte. Responde solo con la descripción.")
LADO = 1280      # px: lado mayor de la imagen que se envía (más no mejora la descripción y encarece)
MAX_TOK = 300
FALTA = "Para describir imágenes con IA instala el modelo de visión en Modelos (o configura un servidor de visión en Ajustes)."


def es_local(url):
    return urllib.parse.urlsplit(url).hostname in ("localhost", "127.0.0.1", "::1")


def _local():
    """(gguf, mmproj) del modelo «vision» si está instalado."""
    import models
    fs = models.CAT["vision"][2]
    return tuple(models.M / f[0] for f in fs) if models.instalado("vision") else None


def elegir(aj, nube=None):
    """-> {"proveedor", "url", "modelo"} (API) | {"local": (gguf, mmproj)} | None. aj: ajustes; nube: config de nube del trabajo."""
    aj = aj or {}
    v = aj.get("vision") or {}
    if v.get("url") and v.get("modelo") and (es_local(v["url"]) or aj.get("nube_imagenes")):
        return {"proveedor": "propio", "url": str(v["url"]).rstrip("/"), "modelo": str(v["modelo"])}
    if nube and not nube["proveedor"].startswith("cli:") and aj.get("nube_imagenes") and not nube.get("anonimizar"):  # una imagen no se seudonimiza
        return {k: nube[k] for k in ("proveedor", "url", "modelo")}
    m = _local()
    return {"local": m} if m else None


def estado(cfg):
    """Lo que ve la interfaz: local | servidor | nube | no_disponible."""
    return "no_disponible" if not cfg else "local" if "local" in cfg else "servidor" if cfg["proveedor"] == "propio" and es_local(cfg["url"]) else "nube"


def _jpeg(path):
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((LADO, LADO))
        b = io.BytesIO()
        im.save(b, "JPEG", quality=85)
    return base64.b64encode(b.getvalue()).decode()


def cuerpo(path, modelo="", tope="max_tokens"):
    return {"model": modelo, "temperature": 0.2, tope: MAX_TOK, "messages": [{"role": "user", "content": [
        {"type": "text", "text": PROMPT}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + _jpeg(path)}}]}]}


def _pedir(url, body, cab=None, prov=None, k=""):
    """Única salida a la red (las pruebas la sustituyen). -> texto de la respuesta."""
    if prov:
        import nube
        r = nube._post(url, prov, k, body)
    else:
        req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
        r = json.load(urllib.request.urlopen(req, timeout=900))
    return (r["choices"][0]["message"]["content"] or "").strip()


@contextlib.contextmanager
def sesion(cfg, threads=P.PHYS, gpu=None):
    """describe(ruta) -> texto. Con el modelo local, un solo llama-server para todas las imágenes del trabajo."""
    if "local" in cfg:
        gguf, mm = cfg["local"]
        url, proc = P.launch(gguf, 4096, threads, ["--mmproj", str(mm), "-rea", "off"], "llama-vision.log", gpu)
        try:
            yield lambda p: P.call(url, lambda: _pedir(url + "/v1/chat/completions", cuerpo(p)))
        finally:
            proc.terminate()
            proc.wait(10)
        return
    import nube
    p = cfg["proveedor"]
    k = nube.clave(p) or ""
    if not k and p != "propio":
        raise RuntimeError(f"Falta la clave de {nube.PROV[p][0]}")
    yield lambda f: _pedir(f"{cfg['url']}/chat/completions", cuerpo(f, cfg["modelo"], nube.PROV[p][3]), prov=p, k=k)


def capturas(out, cfg, cb=lambda f, m: None):
    """Describe las capturas que lleva el documento (acta.json «capturas») y guarda descripcion_ia en cada una; caché por imagen en
    <reunión>/capturas_ia.json (la leen Buscar y Preguntar). -> nº de descritas ahora."""
    cache = Path(out).parent / "capturas_ia.json"
    ya = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    acta = json.loads((Path(out) / "acta.json").read_text(encoding="utf-8"))
    falta = [k for k in acta.get("capturas", []) if k["img"] not in ya]
    if falta:
        with sesion(cfg) as desc:
            for i, k in enumerate(falta):
                cb(i / len(falta), f"Describiendo capturas con IA… {i + 1}/{len(falta)}")
                ya[k["img"]] = {"t": k["t"], "texto": desc(Path(out) / "img" / k["img"])}
                cache.write_text(json.dumps(ya), encoding="utf-8")  # ASCII: cp1252 (Windows) no escribe todo Unicode
    for k in acta.get("capturas", []):
        if k["img"] in ya:
            k["descripcion_ia"] = ya[k["img"]]["texto"]
    (Path(out) / "acta.json").write_text(json.dumps(acta, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(falta)
