"""Escala de la matriz de interesados, mapa de riesgos con códigos e ids de KPIs. Sin LLM ni red."""
import informe
import registro
from test_carpetas import C, cl  # noqa: F401
from test_informe import D, H, reg  # noqa: F401


def inter(t, nombre, po, it):
    return t.post("/api/reg", json={"c": C, "tipo": "interesado", "titulo": nombre, "campos": {"poder": po, "interes": it}}).json()


def vals(t, x):
    return {i["titulo"]: (i["campos"]["poder"], i["campos"]["interes"]) for i in t.get("/api/reg", params={"c": C, "tipo": "interesado"}).json()["items"]}


def test_get_set_y_validacion(cl):
    t, _ = cl
    assert t.get("/api/reg/matriz", params={"c": C}).json() == {"niveles_poder": 6, "niveles_interes": 6, "niveles": 6}
    assert inter(t, "A", 3, 1)["campos"]["poder"] == 3
    assert inter(t, "H", 2.5, 3.5)["campos"] == {"poder": 2.5, "interes": 3.5}
    assert inter(t, "W", 3.0, 6)["campos"] == {"poder": 3, "interes": 6} and isinstance(inter(t, "W2", 3.0, 6)["campos"]["poder"], int)
    for mal in (7, 0.5, 2.3, 6.5, "x", True):
        r = t.post("/api/reg", json={"c": C, "tipo": "interesado", "titulo": "X", "campos": {"poder": mal, "interes": 1}})
        assert r.status_code == 400, mal
    assert "0,5" in r.json()["detail"]
    for body in ({"niveles": n} for n in (2, 11, "5", True, None)):
        assert t.post("/api/reg/matriz", json={"c": C, **body}).status_code == 400
    assert t.post("/api/reg/matriz", json={"c": C}).status_code == 400 and t.post("/api/reg/matriz", json={"c": C, "niveles_poder": 2}).status_code == 400
    assert t.post("/api/reg/matriz", json={"c": "Nope", "niveles": 5}).status_code == 404
    r = t.post("/api/reg/matriz", json={"c": C, "niveles": 8}).json()
    assert (r["niveles"], r["niveles_poder"], r["niveles_interes"]) == (8, 8, 8)
    # ejes independientes
    r = t.post("/api/reg/matriz", json={"c": C, "niveles_poder": 4}).json()
    assert (r["niveles_poder"], r["niveles_interes"]) == (4, 8)
    assert t.get("/api/reg/matriz", params={"c": C}).json() == {"niveles_poder": 4, "niveles_interes": 8, "niveles": 4}
    assert inter(t, "B", 4, 8)["campos"]["interes"] == 8
    assert t.post("/api/reg", json={"c": C, "tipo": "interesado", "titulo": "Y", "campos": {"poder": 5}}).status_code == 400
    assert t.post("/api/reg", json={"c": C, "tipo": "interesado", "titulo": "Z", "campos": {"interes": 9}}).status_code == 400
    assert "matriz_niveles" not in t.get("/api/exp", params={"c": C}).json()["ajustes"]


def test_reescalar_con_medios_y_deshacer(cl):
    t, _ = cl
    a, b = inter(t, "A", 1, 6), inter(t, "B", 3.5, 2)
    inter(t, "Vacio", "", "")
    r = t.post("/api/reg/matriz", json={"c": C, "niveles": 10, "reescalar": True}).json()
    assert r["ok"] and r["niveles"] == 10 and {i["id"] for i in r["items"]} == {a["id"], b["id"]}
    assert vals(t, 0)["A"] == (1, 10) and vals(t, 0)["B"] == (5.5, 3)  # 3.5 -> 2.5*9/5+1 = 5.5; 2 -> 1*9/5+1 = 2.8 -> 3
    t.post("/api/reg/matriz", json={"c": C, "niveles": 3, "reescalar": True})
    assert vals(t, 0)["A"] == (1, 3)
    assert t.post("/api/reg/deshacer", json={"c": C}).json()["revertidas"] >= 2  # un solo deshacer: valores y niveles
    assert t.get("/api/reg/matriz", params={"c": C}).json()["niveles"] == 10 and vals(t, 0)["A"] == (1, 10)
    t.post("/api/reg/deshacer", json={"c": C})
    assert t.get("/api/reg/matriz", params={"c": C}).json()["niveles"] == 6 and vals(t, 0)["A"] == (1, 6) and vals(t, 0)["B"] == (3.5, 2)


def test_reescalar_por_eje_y_deshacer_ambos(cl):
    t, _ = cl
    inter(t, "A", 6, 6), inter(t, "B", 4, 2)
    r = t.post("/api/reg/matriz", json={"c": C, "niveles_poder": 3, "niveles_interes": 10, "reescalar": True}).json()
    assert (r["niveles_poder"], r["niveles_interes"]) == (3, 10)
    assert vals(t, 0) == {"A": (3, 10), "B": (2, 3)}  # poder 4: 3*2/5+1=2.2 -> 2; interés 2: 1*9/5+1=2.8 -> 3
    t.post("/api/reg/deshacer", json={"c": C})
    assert t.get("/api/reg/matriz", params={"c": C}).json() == {"niveles_poder": 6, "niveles_interes": 6, "niveles": 6}
    assert vals(t, 0) == {"A": (6, 6), "B": (4, 2)}


def test_sin_reescalar_recorta(cl):
    t, _ = cl
    t.post("/api/reg/matriz", json={"c": C, "niveles": 10})
    inter(t, "A", 9, 2), inter(t, "B", 4, 10)
    r = t.post("/api/reg/matriz", json={"c": C, "niveles": 5, "reescalar": False}).json()
    assert r["niveles"] == 5 and r["recortados"] == 2 and vals(t, 0) == {"A": (5, 2), "B": (4, 5)}
    assert t.post("/api/reg/deshacer", json={"c": C}).json()["revertidas"] >= 2 and vals(t, 0)["A"] == (9, 2)


def test_export_punto_medio(cl):
    import export_registro as ER
    t, _ = cl
    inter(t, "Alto", 5, 4), inter(t, "Bajo", 1, 2), inter(t, "MedioP", 3.5, 5), inter(t, "MedioI", 5, 3.5), inter(t, "Centro", 3.5, 3.5), inter(t, "Mixto", 6, 1)
    m = ER.exportar(C, "interesados", "md")[0].decode()
    assert "Poder 1–6 · Interés 1–6" in m and "0,5" in m
    assert "En el límite entre Gestionar de cerca y Mantener satisfecho: MedioP" in m
    assert "En el límite entre Gestionar de cerca y Mantener informado: MedioI" in m
    assert "En el centro (entre las cuatro zonas): Centro" in m
    mat, sin, lim = ER._cuadrante(*ER.cargar(C, "interesados")[:2], 6)
    assert {n for _, n in lim} == {"MedioP", "MedioI", "Centro"}
    assert "Alto" in mat[0][2] and "Bajo" in mat[1][1] and "Mixto" in mat[1][2]
    # punto medio por eje: poder 10 (5.5) e interés 4 (2.5)
    mat, sin, lim = ER._cuadrante(*ER.cargar(C, "interesados")[:2], 10, 4)
    assert "Alto" in mat[0][1] and "Bajo" in mat[1][1] and "Mixto" in mat[1][2]


def test_mapa_codigos_leyenda_ids_y_antiguo(reg):
    t, x = reg
    g = informe.graficos(informe.kpis(C, D, H))
    assert "R-001" in g["calor"] and "Alto ≥12" in g["calor"] and "Medio 6–11" in g["calor"] and "Bajo &lt;6" in g["calor"]
    assert "R-001 Retraso del proveedor — P4 × I4 = 16 (Luis)" in g["calor_lista"]
    k = informe.kpis(C, D, H)
    ids = k["ids"]
    assert ids["tareas_abiertas"] == [x["t1"]["id"], x["t2"]["id"]] or set(ids["tareas_abiertas"]) == {x["t1"]["id"], x["t2"]["id"]}
    assert ids["tareas_vencidas"] == [x["t1"]["id"]] and ids["tareas_cerradas"] == [x["t3"]["id"]]
    assert x["r3"]["id"] in ids["riesgos_sin_valorar"] and ids["riesgos_altos"] == [x["r1"]["id"]]
    assert len(ids["riesgos_abiertos"]) == k["riesgos"]["total"] and ids["decisiones"] == [x["d1"]["id"]]
    assert len(ids["requisitos"]) == 2 and len(ids["historias"]) == 1 and len(ids["hitos_vencidos"]) == k["hitos"]["vencidos"]
    assert set(ids) == {"tareas_abiertas", "tareas_vencidas", "tareas_cerradas", "riesgos_abiertos", "riesgos_sin_valorar", "riesgos_altos", "decisiones",
                        "preguntas_abiertas", "escalados", "requisitos", "historias", "hitos_vencidos"}
    # informe guardado antes de estos cambios: sin ids ni sev/dueno en la matriz
    vie = {**k, "riesgos": {**k["riesgos"], "matriz": [{"p": c["p"], "i": c["i"], "items": [{"codigo": a["codigo"], "titulo": a["titulo"]} for a in c["items"]]} for c in k["riesgos"]["matriz"]]}}
    vie.pop("ids")
    g2 = informe.graficos(vie)
    assert "R-001 Retraso del proveedor — P4 × I4 = 16" in g2["calor_lista"]
    i = t.post("/api/reg/informes", json={"c": C, "desde": D, "hasta": H}).json()
    assert i["etiquetas"]["p"] == "Probabilidad" and "ids" in i["contenido"]["kpis"] and "calor_lista" in i["graficos"]
    md = t.get(f"/api/reg/informes/{i['id']}/exportar", params={"c": C, "fmt": "md"}).text
    assert "Mapa de riesgos" in md and "Probabilidad" in md and "R-001" in md
