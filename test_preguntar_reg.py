"""F7: /api/preguntar contesta sin LLM las preguntas de lista del proyecto desde el registro; si no entiende, corre la RAG."""
import json

import registro
from test_carpetas import C, cl  # noqa: F401


def poner(t, tipo, titulo, cita=None, **f):
    x = t.post("/api/reg", json={"c": C, "tipo": tipo, "titulo": titulo, **f}).json()
    if cita:
        registro.citar(x["id"], {"mid": "aaaa1111", "ver": "acta_normal_impaaaa", "t": cita, "texto": titulo})
    return x


def pregunta(t, q, sel="c:" + C):
    r = t.post("/api/preguntar", json={"sel": sel, "q": q})
    assert r.status_code == 200, r.text
    ev = [json.loads(l) for l in r.text.splitlines()]
    return next((e for e in ev if e["k"] == "lista"), ev)


def textos(r):
    return [i["texto"] for i in r["items"]]


def test_riesgos_abiertos_y_conteo(cl, monkeypatch):
    t, app = cl
    poner(t, "riesgo", "Retraso del proveedor", cita=65, dueno="Ana")
    poner(t, "riesgo", "Fuga de agua en el sótano", dueno="Javier")
    poner(t, "riesgo", "Sobrecoste del ascensor", dueno="Ana", estado="mitigado")
    r = pregunta(t, "¿Qué riesgos abiertos hay?")
    assert textos(r) == ["Retraso del proveedor", "Fuga de agua en el sótano"] and r["n"] == 2 and r["items"][0]["codigo"] == "R-001"
    c = r["items"][0]["citas"][0]
    assert (c["mid"], c["t"], c["doc"]) == ("aaaa1111", 65, "Junta enero")  # [mm:ss] enlazable
    r = pregunta(t, "¿Cuántos riesgos abiertos tenemos?")
    assert r["cuenta"] and r["n"] == 2
    assert textos(pregunta(t, "riesgos cerrados")) == ["Sobrecoste del ascensor"]
    assert textos(pregunta(t, "¿Qué riesgos tiene Ana?")) == ["Retraso del proveedor", "Sobrecoste del ascensor"]  # filtro por responsable (sin filtro de estado)
    assert textos(pregunta(t, "riesgos abiertos de Ana")) == ["Retraso del proveedor"]


def test_decisiones_sobre_tema_ordenadas(cl):
    t, _ = cl
    poner(t, "decision", "Cambiar la puerta del garaje", estado="")
    poner(t, "decision", "Cuota extra de jardinería y riego del patio", estado="")
    r = pregunta(t, "¿Qué decidimos sobre la puerta del garaje?")
    assert textos(r)[0] == "Cambiar la puerta del garaje" and "Cuota extra de jardinería y riego del patio" not in textos(r)
    r = pregunta(t, "decisiones sobre el ascensor")  # las propuestas del acta (derrama del ascensor), marcadas sin revisar
    assert r["items"] and all(i["sin_revisar"] for i in r["items"]) and "ascensor" in r["items"][0]["texto"].casefold()


def test_requisitos_de_solicitante_y_prioridad(cl):
    t, _ = cl
    poner(t, "requisito", "Exportar el informe a PDF", dueno="Marta", prioridad="must")
    poner(t, "requisito", "Modo oscuro", dueno="Marta", prioridad="could")
    poner(t, "requisito", "Alta de vecinos por correo", dueno="Pedro")
    assert textos(pregunta(t, "¿Qué requisitos tiene Marta?")) == ["Exportar el informe a PDF", "Modo oscuro"]
    assert textos(pregunta(t, "requisitos de Marta con prioridad must")) == ["Exportar el informe a PDF"]
    assert textos(pregunta(t, "requisitos de informe")) == ["Exportar el informe a PDF"]


def test_preguntas_interesados_historias_hitos_incidencias(cl):
    t, _ = cl
    poner(t, "pregunta", "¿Quién paga la derrama?")
    poner(t, "interesado", "Marta Gómez", detalle="Presidenta de la comunidad")
    poner(t, "interesado", "Pedro Ruiz", detalle="Fontanero")
    poner(t, "historia", "Como vecino quiero ver las cuentas")
    poner(t, "hito", "Entrega del ascensor")
    poner(t, "incidencia", "Gotera en el portal")
    assert textos(pregunta(t, "¿Qué preguntas abiertas hay?")) == ["¿Quién paga la derrama?"]
    assert textos(pregunta(t, "¿Quiénes son los interesados?")) == ["Marta Gómez", "Pedro Ruiz"]
    assert textos(pregunta(t, "¿Quién es Pedro Ruiz?")) == ["Pedro Ruiz"]
    assert textos(pregunta(t, "historias de usuario")) == ["Como vecino quiero ver las cuentas"]
    assert textos(pregunta(t, "¿Qué hitos tenemos?")) == ["Entrega del ascensor"]
    r = pregunta(t, "incidencias abiertas")  # la manual (aprobada) y la propuesta por el acta
    assert textos(r) == ["Gotera en el portal"] * 2 and [i["sin_revisar"] for i in r["items"]] == [False, True]


def test_propuestos_sin_revisar_y_descartados(cl):
    t, _ = cl
    a = poner(t, "riesgo", "Riesgo aprobado")
    b = poner(t, "riesgo", "Riesgo borrado")
    t.delete(f"/api/reg/{b['id']}", params={"c": C})  # descartado
    p = registro.crear(C, "riesgo", titulo="Riesgo propuesto", revision="propuesto", origen="derivado")
    r = pregunta(t, "riesgos")
    assert textos(r) == ["Riesgo aprobado", "Riesgo propuesto"]  # aprobado primero; el descartado no sale
    assert [i["sin_revisar"] for i in r["items"]] == [False, True] and a["id"] != p["id"]


def test_sin_intencion_cae_a_la_rag_y_acta_unica_no_cambia(cl, monkeypatch):
    t, app = cl
    poner(t, "riesgo", "Retraso del proveedor")
    llamadas = []
    monkeypatch.setattr(app, "falta", lambda *a, **k: None)  # sin modelos instalados en el test

    def indice(sel):
        llamadas.append(sel)
        raise RuntimeError("RAG")
    monkeypatch.setattr(app, "indice", indice)
    r = pregunta(t, "¿Qué dijo Laura de la puerta del garaje?")  # sin tipo de entidad
    assert llamadas == ["c:" + C] and any(e["k"] == "error" and e["text"] == "RAG" for e in r)
    llamadas.clear()
    r = pregunta(t, "riesgos sobre la luna llena")  # tipo sí, tema que no está en el registro: RAG
    assert llamadas == ["c:" + C]
    llamadas.clear()
    mid = "aaaa1111"
    sel = next(e["sel"] for e in app.meetings() if e["id"] == mid)
    pregunta(t, "¿Qué riesgos hay?", sel=sel)  # una sola reunión: nunca el registro
    assert llamadas == [sel]
    llamadas.clear()
    r = pregunta(t, "¿Qué riesgos hay?")
    assert r["k"] == "lista" and not llamadas
