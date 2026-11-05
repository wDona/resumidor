"""Reduce jerárquico de documentos enormes (sin LLM real): grupos en orden, marcas conservadas, lo corto no cambia."""

import pipeline

VALID = {"decisiones": [{"t": "00:01", "texto": "Se aprueba X"}], "tareas": []}
PARTE = "Resumen de la parte. " + "palabra " * 70


def run(n, calls):
    # bloque b = página b; t = b*60 s (marca ficticia, como documentos.py)
    maps = [
        {
            "tema": f"Sección {b}",
            "puntos": [{"texto": f"Contenido {k} de la página {b} " * 3, "importancia": 3, "t": pipeline.fmt(b * 60 + k)} for k in range(1, 5)],
        }
        for b in range(n)
    ]

    def chat(system, text, schema, *a):
        calls.append((system, text))
        if "tramo consecutivo" in system:  # el tramo devuelve su primera y última marca
            ts = [l.split("]")[0] + "]" for l in text.split("\n")]
            return {"resumen": f"Tramo {ts[0]} a {ts[-1]}."}
        if "titulo" in schema["properties"]:
            return {"titulo": "T", "resumen": "R"}
        return {"resumen": PARTE}

    return pipeline.reduce_maps(chat, maps, VALID, [b * 60 for b in range(n)], "normal", "español")


def test_documento_enorme_agrupa_y_conserva_marcas():
    calls = []
    run(300, calls)
    grupos = [t for s, t in calls if "tramo consecutivo" in s]
    assert len(grupos) > 3 and all(len(t) <= pipeline.FINAL_CHARS for t in grupos)
    final = calls[-1][1]
    partes = final.split("\n\nDecisiones")[0]
    assert len(partes) <= pipeline.FINAL_CHARS and "Se aprueba X" in final
    marcas = [pipeline.parse_ts(l.split("]")[0][1:]) for l in partes.split("\n")]
    assert marcas == sorted(marcas) and marcas[0] == 0 and marcas[-1] > 250 * 60  # cubre el final (el recorte duro lo perdía)
    assert "Tramo [" in partes  # las marcas citadas se conservan


def test_documento_corto_igual_que_siempre():
    calls = []
    run(5, calls)
    assert not any("tramo consecutivo" in s for s, _ in calls)
    esperado = (
        "\n\n".join(f"[{pipeline.fmt(b * 60)}] Sección {b}: {pipeline.sentences(PARTE, 525)}" for b in range(5)) + "\n\nDecisiones:\n1. [00:01] Se aprueba X"
    )
    assert calls[-1][1] == esperado


def test_claves_cache_solo_cambian_en_largos(monkeypatch):
    P = pipeline.prompts()
    k = lambda n: pipeline.cache_keys(P, "m", ["x"] * n, "normal", False)
    corto, largo = k(16), k(17)
    monkeypatch.setattr(pipeline, "GROUP_PROMPT", "")
    assert k(16) == corto and k(17) != largo
