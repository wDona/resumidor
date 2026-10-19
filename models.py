"""Modelos que la app baja sola la primera vez (reanudable, con tamaño y SHA256). Mismo código en todos los SO."""
import hashlib, threading, urllib.request
from pathlib import Path

import pipeline as P

HF = "https://huggingface.co/"
_W, _E = HF + "Systran/faster-whisper-small/resolve/main/", HF + "onnx-community/embeddinggemma-300m-ONNX/resolve/main/"
M = P.ROOT / "models"
# (ruta en models/, url, sha256 o None, bytes). Sin sha256 (ficheros pequeños no LFS) solo se exige que no esté vacío.
FILES = [
    (P.LLM[0], P.LLM[1], "298fcb5fe7a77ccc79745ae24751560c5ac56874caff4bb39b1f2055bd72b8bb", 2583221408),
    ("whisper-small/model.bin", _W + "model.bin", "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671", 483546902),
    ("whisper-small/config.json", _W + "config.json", None, 2370),
    ("whisper-small/tokenizer.json", _W + "tokenizer.json", None, 2203239),
    ("whisper-small/vocabulary.txt", _W + "vocabulary.txt", None, 459861),
    ("gemma-emb/tokenizer.json", _E + "tokenizer.json", "4dda02faaf32bc91031dc8c88457ac272b00c1016cc679757d1c441b248b9c47", 20323312),
    ("gemma-emb/onnx/model_quantized.onnx", _E + "onnx/model_quantized.onnx", "172efde319fe1542dc41f31be6154910b05b78f7a861c265c4600eec906bd6d8", 567874),
    ("gemma-emb/onnx/model_quantized.onnx_data", _E + "onnx/model_quantized.onnx_data", "705626e28e4c23c82ade34566b4197d97f534c12275fa406dfb71e9937d388c0", 308890624),
    (P.OCR_REC[0], P.OCR_REC[1], P.OCR_REC[2], 7_500_000),
    (P.DIAR_EMB[0], P.DIAR_EMB[1], P.DIAR_EMB[2], 27_000_000),
]
st = {"state": "idle", "done": 0, "total": sum(f[3] for f in FILES), "msg": ""}  # idle | running | done | error
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


def missing():
    return [f for f in FILES if not ok(f)]


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


def run():
    try:
        todo = missing()
        st.update(total=sum(f[3] for f in FILES), done=sum(f[3] for f in FILES if f not in todo))
        for f in todo:
            st["msg"] = f"Descargando {Path(f[0]).name}…"
            st["done"] = st["total"] - sum(g[3] for g in todo[todo.index(f):])  # re-sincroniza con los tamaños nominales
            fetch(f)
        st.update(state="done", done=st["total"], msg="Listo")
    except Exception as e:
        st.update(state="error", msg="No se pudo descargar: comprueba la conexión a internet y vuelve a intentarlo. " + str(e)[:200])


def start():
    with _lock:
        if st["state"] != "running":
            st.update(state="running", msg="Empezando…")
            threading.Thread(target=run, daemon=True).start()


def status():
    if st["state"] != "running":
        st.update(state="done" if not missing() else ("error" if st["state"] == "error" else "idle"))
    return {**st, "need": bool(missing())}
