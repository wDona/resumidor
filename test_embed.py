"""ACTAS_NO_EMBED=1 sin el ONNX: vectores léxicos en pipeline.embed / rag.embed y models.faltan sin «busq». `uv run pytest test_embed.py`"""
import numpy as np

import models
import pipeline
import rag


def test_lexico_sin_onnx(monkeypatch):
    monkeypatch.setattr(rag.P, "ROOT", pipeline.ROOT / "no-existe")
    assert rag.no_embed()
    v = pipeline.embed(["El proveedor de pagos retrasa la entrega", "El proveedor retrasa los pagos", "La playa estaba llena de gente"])
    assert v.shape[0] == 3 and np.allclose(np.linalg.norm(v, axis=1), 1, atol=1e-5)
    assert v[0] @ v[1] > v[0] @ v[2] + .2
    assert (rag.embed(["pagos"], True)[0] @ v[1]) > (rag.embed(["pagos"], True)[0] @ v[2])


def test_faltan_sin_busq(monkeypatch):
    monkeypatch.setattr(models, "instalado", lambda i: False)
    monkeypatch.delenv("ACTAS_NO_EMBED", raising=False)
    assert "busq" in models.faltan("generar", nube=True)[1]
    monkeypatch.setenv("ACTAS_NO_EMBED", "1")
    assert "busq" not in models.faltan("generar", nube=True)[1] and "busq" not in models.faltan("preguntar", nube=True)[1]


def test_no_embed_exige_sidecar(monkeypatch, tmp_path):
    """Con el .onnx pero sin su `.onnx_data`, el modelo no carga: no_embed debe seguir en léxico (no fingir que el ONNX está)."""
    d = tmp_path / "models" / "gemma-emb" / "onnx"
    d.mkdir(parents=True)
    (d / "model_quantized.onnx").write_bytes(b"x")
    monkeypatch.setattr(rag.P, "ROOT", tmp_path)
    monkeypatch.setenv("ACTAS_NO_EMBED", "1")
    assert rag.no_embed()
    (d / "model_quantized.onnx_data").write_bytes(b"x")
    assert not rag.no_embed() or not __import__("importlib.util").util.find_spec("onnxruntime")


def test_indice_lexico_y_onnx_no_comparten_cache(monkeypatch, tmp_path):
    """Un índice léxico (1024-d) no debe cargarse cuando se pasa a ONNX (768-d): la clave incluye «lex»."""
    monkeypatch.setattr(rag, "units", lambda wd, q: [{"text": "el proveedor retrasa los pagos", "kind": "voz"}, {"text": "la playa estaba llena", "kind": "voz"}])
    (tmp_path / "transcript_rápido.json").write_text("{}")
    monkeypatch.setattr(rag, "_enc", None)
    monkeypatch.setattr(rag, "no_embed", lambda: True)
    a = rag.Index(tmp_path)
    assert a.emb.shape[1] == 1024 and len(list(tmp_path.glob("rag_*.npy"))) == 1
    monkeypatch.setattr(rag, "no_embed", lambda: False)  # ahora «hay ONNX» (falso, de 768-d)
    monkeypatch.setattr(rag, "embed", lambda t, q=False, th=2, std=False: np.ones((len(t), 768), np.float32))
    b = rag.Index(tmp_path)
    assert b.emb.shape[1] == 768 and len(list(tmp_path.glob("rag_*.npy"))) == 2
