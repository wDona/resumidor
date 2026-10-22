"""Comprobación rápida (sin GPU ni descargas): reglas de memoria por nivel en 4 equipos y el escáner de GGUF en una carpeta falsa.
Uso: python tools/check_niveles.py"""
import json, os, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import models, pipeline as P

GB = 2**30
sz = {q: models.tam(q) for q in ("alta9", "muyalta", "maxima")}
# (nombre, ram, vram_mb, mac) -> estado por nivel
casos = {
    "ProBook 16 GB iGPU": (16, 0, False, dict(alta9="aviso", muyalta="no", maxima="no")),
    "dev 31 GB RX6600 8 GB": (31, 8176, False, dict(alta9="ok", muyalta="ok", maxima="ok")),
    "Mac M1 16 GB": (16, 0, True, dict(alta9="ok", muyalta="no", maxima="no")),
    "Mac 32 GB": (32, 0, True, dict(alta9="ok", muyalta="ok", maxima="ok")),
}
for nom, (ram, vram, mac, esp) in casos.items():
    for q, e in esp.items():
        r = P.evaluar(sz[q], P.NIVELES[q][1], ram, vram, mac)[0]
        assert r == e, (nom, q, r, e)
assert P.evaluar(2.6e9, None, 8, 0, False)[0] == "ok"  # Rápida/Alta nunca avisan

fake = lambda ok: (lambda i: ("ok" if i in ok else "no", 0))
t_ = ("voz", "busq", "peq", "rápida", "chat")
assert models.recomendados(fake(t_ + ("alta9", "muyalta", "maxima"))) == [*t_[:4], "alta9", "chat"]  # Alta+ gana si está ok
assert models.recomendados(fake(t_ + ("muyalta", "maxima"))) == [*t_[:4], "maxima", "chat"]  # sin Alta+, el más alto
assert models.recomendados(fake(t_ + ("alta9",))) == [*t_[:4], "alta9", "chat"]
assert models.recomendados(fake(t_)) == list(t_)
assert models.recomendados(fake(("rápida", "alta9")))== ["rápida", "alta9"]

with tempfile.TemporaryDirectory() as t:  # escáner: LM Studio, HF, Ollama con manifest, mmproj/pequeño descartados
    t = Path(t)
    def gguf(p, n=600_000_000):
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"GGUF"); f.truncate(n)
    gguf(t / ".lmstudio/models/a/b/modelo-q4.gguf"); gguf(t / ".lmstudio/models/a/b/mmproj-x.gguf"); gguf(t / ".lmstudio/models/a/b/chico.gguf", 10_000)
    gguf(t / ".cache/huggingface/hub/models--x--y/snapshots/1/y-Q4.gguf")
    gguf(t / ".ollama/models/blobs/sha256-abc")
    mf = t / ".ollama/models/manifests/registry.ollama.ai/library/qwen3/8b"; mf.parent.mkdir(parents=True)
    mf.write_text(json.dumps({"layers": [{"mediaType": "application/vnd.ollama.image.model", "digest": "sha256:abc"}]}))
    old = Path.home
    Path.home = classmethod(lambda c: t)
    try:
        r = {(x["origen"], x["nombre"]) for x in models.escanear()}
    finally:
        Path.home = old
    assert r >= {("LM Studio", "modelo-q4"), ("Hugging Face", "y-Q4"), ("Ollama", "qwen3:8b")}, r
    assert not any("mmproj" in n or n == "chico" for _, n in r), r
print("ok")
