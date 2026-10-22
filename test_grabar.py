"""Pruebas de grabar.py: tramos/unión, fusión por pista, ventanas de notas, notas -> documento (con un LLM falso).
La captura real y el trabajo completo (2 pistas + notas, CPU) se prueban aparte (ver README). `uv run pytest test_grabar.py`"""
import json
import wave

import numpy as np

import grabar
import pipeline

seg = lambda s, e, t: {"s": s, "e": e, "text": t}


def test_tramos_union_y_mezcla():
    grabar._selftest()


def test_fusion_diafonia_conserva_solapes_distintos():
    m = grabar.fusionar({"Hablante 1": [seg(0, 4, "creo que sí lo vemos mañana")], "Hablante 2": [seg(1, 5, "el presupuesto sube un diez por ciento")]}, eco="Hablante 1")
    assert [s["spk"] for s in m] == ["Hablante 1", "Hablante 2"]  # hablan a la vez con textos distintos: ambos


def test_recuperacion_tras_corte(tmp_path):
    (tmp_path / "mic_000.pcm").write_bytes(np.full(grabar.SR * 2, 900, "<i2").tobytes() + b"\x07")  # corte a mitad de muestra
    (tmp_path / "sistema_000.pcm").write_bytes(np.full(grabar.SR, 900, "<i2").tobytes())
    r = grabar.finalizar(tmp_path)
    assert r["dur"] == 2.0 and set(r["pistas"]) == {"Hablante 1", "Hablante 2"} and r["medio"].endswith(".m4a")
    with wave.open(str(tmp_path / "sistema.wav")) as w:
        assert w.getnframes() == grabar.SR * 2  # la pista corta se rellena de silencio
    assert not list(tmp_path.glob("*.pcm"))


SEGS = [seg(10 * i, 10 * i + 8, t) for i, t in enumerate(
    ["Buenos días", "Se aprueba por unanimidad contratar a Elevalia para renovar el ascensor", "La derrama será de cuarenta euros", "Marta avisa a los vecinos", "Cerramos"])]
P = pipeline.prompts(pipeline.plantillas.get("acta") if hasattr(pipeline, "plantillas") else None)


def test_extraer_cita_verificada():
    n = {"id": "a", "t": 22.0, "texto": "", "boton": "Acuerdo", "seccion": "decisiones"}
    bien = lambda *a: {"cita": "Se aprueba por unanimidad contratar a Elevalia", "texto": "Se contrata a Elevalia para renovar el ascensor"}
    it = grabar.extraer(pipeline, bien, n, SEGS, P, "español", "m")
    assert it["usuario"] and it["t"] == "00:10" and it["cita"].startswith("Se aprueba")
    mal = lambda *a: {"cita": "Se rechaza el presupuesto de la obra", "texto": "Se rechaza el presupuesto"}
    assert grabar.extraer(pipeline, mal, n, SEGS, P, "español", "m") is None  # cita inventada
    cifra = lambda *a: {"cita": "Se aprueba por unanimidad contratar a Elevalia", "texto": "Se contrata a Elevalia por 90000 euros"}
    assert grabar.extraer(pipeline, cifra, n, SEGS, P, "español", "m") is None  # cifra que no se dice


def test_aplicar_y_render(tmp_path):
    import copy
    maps = [{"tema": "t", "puntos": [{"texto": "Hablan del ascensor", "importancia": 2, "t": "00:10"}, {"texto": "Lejano", "importancia": 2, "t": "03:00"}], "decisiones": [], "tareas": [], "relato": [{"t": "00:00", "texto": "Reunión."}]}]
    red = {"titulo": "T", "resumen": "R", "secciones": [], "decisiones": [], "tareas": [], "mas": False}
    notas = grabar.limpia_notas([{"id": "a", "t": 22, "boton": "Acuerdo", "seccion": "decisiones"}, {"id": "b", "t": 31, "texto": "Confirmar importe"}])
    assert [n["id"] for n in grabar.pendientes(notas, P)] == ["a"]
    it = {"cita": "Se aprueba por unanimidad contratar a Elevalia", "texto": "Se contrata a Elevalia", "t": "00:10", "usuario": True, "importancia": 5}
    filas = grabar.aplicar(pipeline, notas, SEGS, maps, red, P, {"a": it})
    assert maps[0]["puntos"][0]["importancia"] == 5 and maps[0]["puntos"][1]["importancia"] == 2  # solo la ventana de ±45 s
    assert red["decisiones"] == [it] and "unanimidad" in filas[0]["dicho"] and filas[1]["texto"] == "Confirmar importe"
    for nt in (filas, None):
        o = tmp_path / str(bool(nt)); (o / "img").mkdir(parents=True)
        pipeline.render(o, "T", 50, "es", copy.deepcopy(red), copy.deepcopy(maps), [], [0], SEGS, "normal", None, notas=nt, P=P)
        h = (o / "index.html").read_text()
        assert ("Notas del usuario" in h and "marcado por ti" in h and "Confirmar importe" in h) == bool(nt)
