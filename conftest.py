"""Fixtures comunes: sin modelos de embeddings (ACTAS_NO_EMBED=1) y una reunión sintética (tests_data/reunion.vtt) en un work temporal."""
import json
from pathlib import Path

import pytest

import transcripts

VTT = Path(__file__).parent / "tests_data" / "reunion.vtt"
MID = "c8f5001c5e212d71"
VERS = ["acta_normal_rápido", "acta_normal_rápido_p-clase"]


@pytest.fixture(autouse=True)
def _entorno(monkeypatch, tmp_path):
    monkeypatch.setenv("ACTAS_NO_EMBED", "1")
    import pipeline
    monkeypatch.setattr(pipeline, "RITMOS", tmp_path / "ritmos.json")  # RITMOS se calcula al importar: que no dependa de work/ ni lo ensucie


def _acta(plantilla):
    cita = lambda t: "Decidimos " + t
    return {"titulo": "Reunión de seguimiento", "duracion": 132, "nivel": "normal", "resumen": "Se revisa el lanzamiento de la aplicación de reservas.",
            "relato": [{"t": 0, "texto": "Laura abre la reunión y repasa el estado del lanzamiento."}, {"t": 18, "texto": "Se acuerda el calendario de la campaña de correo."}],
            "puntos": [{"t": 18, "texto": "El proveedor de pagos debe confirmar la fecha del 15 de noviembre"}, {"t": 36, "texto": "La búsqueda es lenta en móviles antiguos"}],
            "secciones": [{"t": 0, "titulo": "Proveedor de pagos", "resumen": "Se pide confirmar la fecha.", "puntos": [{"t": 18, "texto": "Fecha prevista: 15 de noviembre"}]},
                          {"t": 48, "titulo": "Campaña de correo", "resumen": "Se pospone a la beta abierta.", "puntos": [{"t": 54, "texto": "Beta abierta como momento del correo"}]}],
            "decisiones": [{"cita": cita("proveedor"), "texto": "Carlos confirma la fecha con el proveedor de pagos", "t": 18, "b": 0, "n": 1},
                           {"cita": cita("correo"), "texto": "La campaña de correo se lanza en la beta abierta", "t": 54, "b": 0, "n": 1}],
            "tareas": [{"cita": "x", "tarea": "Arreglar la búsqueda", "responsable": "Javier", "plazo": "20/11/2026", "t": 36, "b": 0},
                       {"cita": "x", "tarea": "Confirmar la fecha con el proveedor", "responsable": "Carlos", "plazo": "El viernes", "t": 90, "b": 0},
                       {"cita": "x", "tarea": "Actualizar el plan de lanzamiento", "responsable": "Marta", "plazo": "Antes del lunes", "t": 96, "b": 0}],
            "capturas": [], "plantilla": plantilla, "secciones_plantilla": []}


@pytest.fixture(scope="session")
def src(tmp_path_factory):
    """work/<MID> sintético: transcript_rápido.json + las dos versiones de VERS (acta.json e index.html)."""
    d = tmp_path_factory.mktemp("src") / MID
    d.mkdir()
    t = transcripts.parse(VTT)
    (d / "transcript_rápido.json").write_text(json.dumps({"language": "es", "segments": t["segments"]}, ensure_ascii=False), encoding="utf-8")
    for v, pl in zip(VERS, ["Acta de reunión", "Clase o conferencia"]):
        (d / v).mkdir()
        (d / v / "acta.json").write_text(json.dumps(_acta(pl), ensure_ascii=False), encoding="utf-8")
        (d / v / "index.html").write_text("<!doctype html><title>x</title><body><p>Documento de prueba</p>", encoding="utf-8")
    return d
