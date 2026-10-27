"""Modelos que la app baja sola la primera vez (reanudable, con tamaño y SHA256). Mismo código en todos los SO."""
import hashlib, json, os, re, threading, urllib.request
from pathlib import Path

import pipeline as P

HF = "https://huggingface.co/"
_W, _E = HF + "mobiuslabsgmbh/faster-whisper-large-v3-turbo/resolve/main/", HF + "onnx-community/embeddinggemma-300m-ONNX/resolve/main/"
M = P.ROOT / "models"
# (ruta en models/, url, sha256 o None, bytes). Sin sha256 (ficheros pequeños no LFS) solo se exige que no esté vacío.
FILES = [
    (P.LLM[0], P.LLM[1], "298fcb5fe7a77ccc79745ae24751560c5ac56874caff4bb39b1f2055bd72b8bb", 2583221408),
    ("gemma-4-E4B-it-Q4_0.gguf", HF + "unsloth/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q4_0.gguf",
     "4a403d2e4d80281063e4f517b1c061ded8476b4011a4fc2ba7dbff707075547e", 4836002944),  # chat de Preguntar (rag.GEMMA)
    ("whisper-large-v3-turbo/model.bin", _W + "model.bin", "e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da", 1617884929),
    ("whisper-large-v3-turbo/config.json", _W + "config.json", None, 2263),
    ("whisper-large-v3-turbo/preprocessor_config.json", _W + "preprocessor_config.json", None, 340),
    ("whisper-large-v3-turbo/tokenizer.json", _W + "tokenizer.json", None, 2710337),
    ("whisper-large-v3-turbo/vocabulary.json", _W + "vocabulary.json", None, 1068114),
    ("gemma-emb/tokenizer.json", _E + "tokenizer.json", "4dda02faaf32bc91031dc8c88457ac272b00c1016cc679757d1c441b248b9c47", 20323312),
    ("gemma-emb/onnx/model_quantized.onnx", _E + "onnx/model_quantized.onnx", "172efde319fe1542dc41f31be6154910b05b78f7a861c265c4600eec906bd6d8", 567874),
    ("gemma-emb/onnx/model_quantized.onnx_data", _E + "onnx/model_quantized.onnx_data", "705626e28e4c23c82ade34566b4197d97f534c12275fa406dfb71e9937d388c0", 308890624),
    (P.OCR_REC[0], P.OCR_REC[1], P.OCR_REC[2], 7_500_000),
    (P.DIAR_EMB[0], P.DIAR_EMB[1], P.DIAR_EMB[2], 27_000_000),
]
GEMMA = "gemma-4-E4B-it-Q4_0.gguf"
HFU = lambda r, n: HF + f"unsloth/{r}/resolve/main/{n}"
pre = lambda *p: [f for f in FILES if f[0].startswith(p)]
# Elegibles: id -> (nombre, para qué sirve, [ficheros]). Los ids de LLM son la "calidad" del acta que los usa (Alta usa el de rápida).
CAT = {
    "voz": ("Whisper large-v3-turbo", "Voz: transcribe los vídeos (calidad)", pre("whisper-large")),
    "busq": ("EmbeddingGemma", "Búsqueda: acta (notas de los puntos) y Preguntar", pre("gemma-emb")),
    "peq": ("OCR y hablantes", "Texto de la pantalla y nombres de hablantes (ficheros pequeños)", pre(P.OCR_REC[0], P.DIAR_EMB[0])),
    "rápida": ("Qwen3.5-4B", "Redactor de las actas Rápida y Alta; ligero, vale para cualquier equipo", [FILES[0]]),
    "alta9": ("Qwen3.5-9B", "Redactor del acta Alta+; más fiel en reuniones largas", [(P.LLM_DE["alta9"], HFU("Qwen3.5-9B-GGUF", P.LLM_DE["alta9"]),
             "17670346b4260ddcb0173965145155885024f3c9a4a24389a3370751edbcde24", 5379417312)]),
    "muyalta": ("Gemma 4 26B-A4B", "Redactor del acta Muy alta; modelo grande (MoE), necesita bastante memoria", [(P.LLM_DE["muyalta"],
                HFU("gemma-4-26B-A4B-it-qat-GGUF", P.LLM_DE["muyalta"]), "a7c5bc715f5ff8e99a3e8901ce7d2b42b402c669bf24f7c5250747633d0f5891", 14249047104)]),
    "maxima": ("Qwen3.6-35B-A3B", "Redactor del acta Máxima; el mayor (MoE), necesita mucha memoria", [(P.LLM_DE["maxima"],
               HFU("Qwen3.6-35B-A3B-GGUF", P.LLM_DE["maxima"]), "ac0e2c1189e055faa36eff361580e79c5bd6f8e76bffb4ce547f167d53e31a61", 22134528992)]),
    "chat": ("Gemma 4 E4B", "Chat de Preguntar; mejor que el Qwen si hay memoria", [FILES[1]]),
}
LLMS = [i for i in CAT if i in P.NIVELES]  # redactores
tam = lambda i: sum(f[3] for f in CAT[i][2])
st = {"state": "idle", "done": 0, "total": 0, "msg": ""}  # idle | running | done | error
_lock = threading.Lock()


def adopt(f):
    """Si el fichero ya está en la caché de Hugging Face (faster-whisper, hf_hub), lo enlaza en models/ sin copiar ni bajar."""
    import os, re
    m = re.match(HF + r"([^/]+)/([^/]+)/resolve/main/(.+)$", f[1])
    if not m:
        return
    hub = Path(os.environ.get("HF_HUB_CACHE") or Path(os.environ.get("HF_HOME") or Path.home() / ".cache/huggingface") / "hub")
    for src in sorted((hub / f"models--{m[1]}--{m[2]}" / "snapshots").glob(f"*/{m[3]}")):
        if src.is_file() and src.stat().st_size > 0:
            p = M / f[0]
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.symlink_to(src.resolve())
            except OSError:  # Windows sin permiso de enlaces: se baja
                p.unlink(missing_ok=True)
            return


def ok(f):
    p = M / f[0]
    if not p.exists():
        adopt(f)
    return p.is_file() and p.stat().st_size > 0 and not p.with_name(p.name + ".part").exists()


def instalado(i):
    return all(ok(f) for f in CAT[i][2])


def estado(i):
    """-> ("ok" recomendado | "aviso" usable pero no recomendado | "no" no cabe, GB que necesita)."""
    e, need = P.evaluar(tam(i), P.NIVELES[i][1] if i in P.NIVELES else None)
    return ("aviso" if i == "chat" and e == "ok" and P.chat_model()[0] != "gemma" else e), need


def recomendados(est=estado):
    """Esenciales + Rápida + UN redactor mayor (Alta+ si está «ok»; si no, el nivel más alto «ok») + chat si procede; el resto, solo con badge."""
    ok_ = [i for i in CAT if est(i)[0] == "ok"]
    mayor = [i for i in ok_ if i in LLMS and i != "rápida"]
    return [i for i in ok_ if i not in LLMS or i == "rápida" or i == ("alta9" if "alta9" in mayor else mayor[-1] if mayor else None)]


def catalogo():
    return [{"id": i, "nombre": n, "uso": u, "bytes": tam(i), "instalado": instalado(i), "estado": (e := estado(i))[0], "necesita": round(e[1], 1)}
            for i, (n, u, f) in CAT.items()]


def missing(ids):
    return [f for i in ids for f in CAT[i][2] if not ok(f)]


def faltan(accion, calidad="rápida", video=True, nube=False):
    """Qué hay que instalar para `accion` ("generar" | "fondo" | "preguntar") -> (mensaje, [ids]); ("", []) si está todo."""
    m = "rápida" if calidad in ("rápida", "alta") else calidad
    llm = lambda: [] if nube or (f := P.acta_model(calidad)) and f.is_file() or m not in CAT else [m]
    hay = any(instalado(i) for i in LLMS) or any(Path(r).is_file() for r in P.OVER.values())
    rol = lambda r: bool(P.ROLES.get(r)) and Path(P.ROLES[r]).is_file() or (r == "emb" and os.environ.get("ACTAS_NO_EMBED") == "1")  # rol sustituido por un .gguf propio
    if accion == "preguntar":
        ids = [i for i in ([] if rol("emb") else ["busq"]) + ([] if nube or rol("chat") or instalado("chat") or hay else ["chat" if P.chat_model()[0] == "gemma" else "rápida"]) if not instalado(i)]
        txt = "Para preguntar necesitas: "
    else:
        ids = [i for i in (["voz", "peq"] * bool(video)) + ([] if rol("emb") else ["busq"]) if not instalado(i)] + llm()
        txt = "Para generar actas necesitas: " if accion == "generar" else "Para la búsqueda a fondo necesitas: "
    nom = {"voz": "voz", "busq": "búsqueda", "peq": "OCR y hablantes", "chat": "un modelo de chat"}
    return (txt + " + ".join(nom.get(i, "un modelo redactor") for i in ids) + " (instálalos en Modelos).", ids) if ids else ("", [])


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        while b := fh.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def fetch(f):
    """Baja f a <ruta>.part reanudando donde se quedó; verifica sha256 y renombra."""
    p = M / f[0]
    p.parent.mkdir(parents=True, exist_ok=True)
    part = p.with_name(p.name + ".part")
    for _ in range(2):  # 2.º intento: desde cero si el hash no cuadra
        have = part.stat().st_size if part.exists() else 0
        req = urllib.request.Request(f[1], headers={"Range": f"bytes={have}-"} if have else {})
        with urllib.request.urlopen(req, timeout=60) as r:
            if have and r.status != 206:  # el servidor no admite Range
                have = 0
            st["done"] += have
            with open(part, "ab" if have else "wb") as out:
                while b := r.read(1 << 20):
                    out.write(b)
                    st["done"] += len(b)
        if f[2] is None or sha(part) == f[2]:
            part.replace(p)
            return
        part.unlink()
    raise RuntimeError(f"{f[0]}: la descarga está dañada (SHA256 distinto)")


def run(ids):
    try:
        todo = missing(ids)
        st.update(total=sum(f[3] for f in todo), done=0)
        for f in todo:
            st["msg"] = f"Descargando {Path(f[0]).name}…"
            st["done"] = st["total"] - sum(g[3] for g in todo[todo.index(f):])  # re-sincroniza con los tamaños nominales
            fetch(f)
        st.update(state="done", done=st["total"], msg="Listo")
    except Exception as e:
        st.update(state="error", msg="No se pudo descargar: comprueba la conexión a internet y vuelve a intentarlo. " + str(e)[:200])


def start(ids=None):
    """Instala los `ids` (None: los recomendados para este equipo). Los que no caben se pueden bajar; su nivel queda bloqueado."""
    ids = recomendados() if ids is None else [i for i in ids if i in CAT]
    with _lock:
        if st["state"] != "running":
            st.update(state="running", msg="Empezando…")
            threading.Thread(target=run, args=(list(ids),), daemon=True).start()


def borrar(i):
    """Quita un modelo instalado (y el fichero al que apunta su enlace)."""
    if i not in CAT or st["state"] == "running":
        return False
    for f in CAT[i][2]:
        p = M / f[0]
        for q in (p.resolve(), p, p.with_name(p.name + ".part")):
            q.unlink(missing_ok=True)
    return True


def status():
    if st["state"] != "running":
        st.update(state="error" if st["state"] == "error" else "done" if st["state"] == "done" else "idle")
    return {**st, "catalogo": catalogo(), "recomendados": recomendados()}


# ---------- Modelos GGUF que el usuario ya tiene ----------
def escanear(emb=False):
    """GGUF de otros programas (LM Studio, Ollama, Hugging Face, Jan, GPT4All) + models/ + los añadidos a mano. Rápido: nombre y tamaño, sin hashes.
    -> [{nombre, ruta, bytes, origen, estado, necesita}]; sin vision (mmproj), embeddings ni ficheros < 500 MB.
    emb=True: al revés, solo modelos de embeddings (cualquier tamaño)."""
    h, env = Path.home(), os.environ
    hub = Path(env.get("HF_HUB_CACHE") or Path(env.get("HF_HOME") or h / ".cache/huggingface") / "hub")
    ollama = [Path(env["OLLAMA_MODELS"])] if env.get("OLLAMA_MODELS") else []
    ollama += [h / ".ollama/models", Path("/usr/share/ollama/.ollama/models")]
    ap = Path(env.get("APPDATA", h / "AppData/Roaming")); la = Path(env.get("LOCALAPPDATA", h / "AppData/Local")); lib = h / "Library/Application Support"
    carpetas = [("Esta app", M), ("LM Studio", h / ".lmstudio/models"), ("LM Studio", h / ".cache/lm-studio/models"), ("Hugging Face", hub),
                ("Jan", h / "jan/models"), ("Jan", ap / "Jan/data/models"), ("Jan", lib / "Jan/data/models"),
                ("GPT4All", h / ".local/share/nomic.ai/GPT4All"), ("GPT4All", la / "nomic.ai/GPT4All"), ("GPT4All", lib / "nomic.ai/GPT4All")]
    de_serie = {f[0] for _, _, fs in CAT.values() for f in fs}
    vistos, out = set(), []

    def add(p, nombre, origen, libre=False):
        try:
            r = p.resolve()
            n = r.stat().st_size
            es_emb = bool(re.search(r"embed|bge-|e5-|gte-|nomic", nombre, re.I)) and not re.search(r"mmproj|rerank", nombre, re.I)
            if r in vistos or not r.is_file() or (not libre and (not es_emb if emb else n < 500e6 or es_emb or re.search(r"mmproj|rerank", nombre, re.I))):
                return
            with open(r, "rb") as fh:
                if fh.read(4) != b"GGUF":
                    return
        except OSError:
            return
        vistos.add(r)
        e, need = P.evaluar(n, None)
        out.append({"nombre": nombre, "ruta": str(r), "bytes": n, "origen": origen, "estado": e, "necesita": round(need, 1)})

    for origen, d in carpetas:
        for f in sorted(d.rglob("*.gguf")) if d.is_dir() else []:
            if f.name not in de_serie:
                add(f, re.sub(r"\.gguf$", "", f.name), origen)
    for o in ollama:  # manifests/<host>/<espacio>/<modelo>/<etiqueta> -> blob "sha256-<hash>" (GGUF sin extensión)
        for mf in sorted((o / "manifests").rglob("*")) if (o / "manifests").is_dir() else []:
            try:
                dg = next(l["digest"] for l in json.loads(mf.read_text())["layers"] if l["mediaType"].endswith("image.model"))
            except (OSError, ValueError, StopIteration, KeyError):
                continue
            add(o / "blobs" / dg.replace(":", "-"), f"{mf.parent.name}:{mf.name}", "Ollama")
    try:
        for e in json.loads(P.MODELOS.read_text()).get("extra", []):
            add(Path(e["ruta"]), e["nombre"], "Añadido", not emb)
    except (OSError, ValueError):
        pass
    return out


ROLES = ("chat", "emb")  # roles intercambiables: chat de Preguntar y búsqueda (embeddings)


def _cfg():
    try:
        return json.loads(P.MODELOS.read_text())
    except (OSError, ValueError):
        return {}


def usar(ruta, nivel, nombre=""):
    """Guarda en P.MODELOS que `ruta` (se referencia, no se copia) sustituye al modelo de `nivel` (una calidad), es un nivel «Personalizado»
    (nivel="pers") o hace de rol ("chat" = Preguntar, "emb" = búsqueda por embeddings); nivel="" la quita de todo. -> False si no es un .gguf
    o el nivel no existe."""
    p = Path(ruta)
    if p.suffix.lower() != ".gguf" or not p.is_file() or nivel not in (*P.BASE, *ROLES, "pers", ""):
        return False
    c = _cfg()
    lv, ex = c.get("levels", {}), [e for e in c.get("extra", []) if e["ruta"] != str(p)]
    lv = {q: r for q, r in lv.items() if r != str(p)}
    ro = {r: x for r, x in c.get("roles", {}).items() if x != str(p) and r != nivel}
    if nivel in P.BASE:
        lv[nivel] = str(p)
    elif nivel in ROLES:
        ro[nivel] = str(p)
    elif nivel == "pers":
        ex.append({"ruta": str(p), "nombre": nombre or P.llm_label(p)})
    P.MODELOS.parent.mkdir(exist_ok=True)
    P.MODELOS.write_text(json.dumps({"levels": lv, "extra": ex, "roles": ro}, ensure_ascii=False, indent=1))
    P.cargar_modelos()
    return True


def quitar_rol(rol):
    """Vuelve al modelo de serie de ese rol."""
    c = _cfg()
    c.get("roles", {}).pop(rol, None)
    P.MODELOS.write_text(json.dumps(c, ensure_ascii=False, indent=1))
    P.cargar_modelos()


def roles():
    """Estado de los roles: {rol: {ruta, nombre, bytes, estado, necesita, defecto}}; estado = reglas de memoria (ok/aviso/no) como los demás modelos."""
    out = {}
    for r, nom in (("chat", "Gemma 4 E4B / Qwen (según memoria)"), ("emb", "EmbeddingGemma (ONNX)")):
        p = P.ROLES.get(r)
        if p and Path(p).is_file():
            n = Path(p).stat().st_size
            e, need = P.evaluar(n, None)
            out[r] = {"ruta": p, "nombre": P.llm_label(Path(p)), "bytes": n, "estado": e, "necesita": round(need, 1), "defecto": False}
        else:
            out[r] = {"ruta": None, "nombre": nom, "defecto": True}
    out["emb"]["reindexa"] = "Se reindexarán las reuniones al preguntar" if not out["emb"]["defecto"] else ""
    return out


# ---------- Modelos de Hugging Face (repo + fichero, o URL) ----------
HFDIR = "hf"  # models/hf/<repo>/<fichero>


def hf_parse(entrada):
    """«https://huggingface.co/u/r/resolve/main/f.gguf», «u/r/f.gguf» o «u/r» -> (repo, fichero o None); ValueError si no vale."""
    e = entrada.strip().removeprefix(HF).removeprefix("hf.co/")
    m = re.match(r"([\w.-]+/[\w.-]+)(?:/(?:resolve|blob)/[^/]+/(.+?)|/(.+\.gguf))?(?:\?.*)?$", e)
    if not m:
        raise ValueError("Escribe una URL de Hugging Face o «usuario/repo» (con «/fichero.gguf» si quieres uno concreto)")
    f = m[2] or m[3]
    if f and not f.lower().endswith(".gguf"):
        raise ValueError("El fichero debe ser un .gguf")
    return m[1], f


def hf_info(entrada, abrir=urllib.request.urlopen):
    """Qué se descargaría: {repo, archivos: [{fichero, bytes, estado, necesita}]} (todos los .gguf del repo o el indicado, con su tamaño)."""
    repo, f = hf_parse(entrada)
    r = json.loads(abrir(urllib.request.Request(f"{HF}api/models/{repo}/tree/main?recursive=1", headers={"User-Agent": "actas"}), timeout=20).read())
    out = []
    for x in r:
        n = x.get("name") or x.get("path", "")
        if x.get("type") == "file" and n.lower().endswith(".gguf") and not re.search(r"mmproj", n, re.I) and (f is None or n == f):
            b = (x.get("lfs") or {}).get("size") or x.get("size", 0)
            e, need = P.evaluar(b, None)
            out.append({"fichero": n, "bytes": b, "estado": e, "necesita": round(need, 1)})
    if not out:
        raise ValueError("No hay ningún .gguf" + (f" «{f}»" if f else "") + f" en {repo}")
    return {"repo": repo, "archivos": out}


def hf_bajar(repo, fichero, nivel, nombre="", tam=0):
    """Baja (reanudable) models/hf/<repo>/<fichero> y al terminar lo asigna a `nivel` (calidad, "pers", "chat" o "emb"). Estado: el de /api/modelos."""
    hf_parse(f"{repo}/{fichero}")
    if nivel not in (*P.BASE, *ROLES, "pers"):
        raise ValueError("Nivel no válido")
    f = (f"{HFDIR}/{repo}/{fichero}", f"{HF}{repo}/resolve/main/{fichero}", None, tam)
    with _lock:
        if st["state"] == "running":
            raise RuntimeError("Ya hay una descarga en marcha")
        st.update(state="running", msg="Empezando…", done=0, total=tam)

    def run_():
        try:
            st["msg"] = f"Descargando {Path(fichero).name}…"
            fetch(f)
            if not usar(str(M / f[0]), nivel, nombre):
                raise RuntimeError("No es un .gguf válido")
            st.update(state="done", done=st["total"], msg="Listo")
        except Exception as e:
            st.update(state="error", msg="No se pudo descargar: " + str(e)[:200])
    threading.Thread(target=run_, daemon=True).start()
