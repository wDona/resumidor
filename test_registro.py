"""Pruebas de registro.py (work/registro.db): entidades, historial y deshacer, fusionar, sincronizar con los documentos, migración de
expedientes.json y escrituras concurrentes. Sin LLM. `uv run pytest test_registro.py`"""
import datetime as dt
import json
import sqlite3
import threading
import time

import pytest

import carpetas
import pipeline
import registro
from test_carpetas import C, HOY, cl, ms  # noqa: F401 (cl: fixture con 3 reuniones sintéticas)

P0 = "aaaa1111|acta_normal_impaaaa|tareas.0"


@pytest.fixture()
def work(tmp_path, monkeypatch):
    w = tmp_path / "work"
    w.mkdir()
    monkeypatch.setattr(pipeline, "WORK", w)
    return w


def test_crud_historial_deshacer(work):
    a = registro.crear("P", "riesgo", titulo="Retraso", dueno="Ana")
    b = registro.crear("P", "riesgo", titulo="Otro")
    assert (a["codigo"], b["codigo"], a["revision"], a["estado"], a["editado"]) == ("R-001", "R-002", "propuesto", "abierto", 0)
    assert registro.crear("P", "requisito", titulo="Login")["codigo"] == "REQ-001" and registro.crear("Q", "riesgo", titulo="x")["codigo"] == "R-001"  # por proyecto y tipo
    with pytest.raises(ValueError):
        registro.crear("P", "nada", titulo="x")
    registro.editar(a["id"], {"titulo": "Retraso del proveedor", "campos": {"impacto": 4}}, lote="L1")
    registro.borrar(b["id"], lote="L1")
    x = {e["id"]: e for e in registro.listar("P", "riesgo")}
    assert x[a["id"]]["editado"] == 1 and x[a["id"]]["campos"] == {"impacto": 4} and x[b["id"]]["revision"] == "descartado"
    assert registro.editar(a["id"], {"estado": "hecho"}, lote="L2")["editado"] == 1  # estado no es contenido, pero no des-edita
    assert [h["accion"] for h in registro.historial(a["id"])] == ["crear", "editar", "editar"] and registro.historial(a["id"])[1]["antes"]["titulo"] == "Retraso"
    assert registro.deshacer("P") == 1 and registro.listar("P", id=a["id"])[0]["estado"] == "abierto"
    assert registro.deshacer("P") == 2  # el lote L1 entero
    x = {e["id"]: e for e in registro.listar("P", "riesgo")}
    assert (x[a["id"]]["titulo"], x[a["id"]]["editado"], x[a["id"]]["campos"], x[b["id"]]["revision"]) == ("Retraso", 0, {}, "propuesto")
    registro.deshacer("P"), registro.deshacer("P")  # crear requisito, crear b
    assert [e["id"] for e in registro.listar("P", "riesgo")] == [a["id"]] and registro.deshacer("nadie") == 0


def test_fusionar(work):
    cita = lambda t: {"mid": "m1", "ver": "v", "t": t, "texto": f"cita {t}"}
    d, o1, o2 = (registro.crear("P", "requisito", titulo=t, cita=cita(i)) for i, t in enumerate(["Login", "Entrar", "Acceso"]))
    hu = registro.crear("P", "historia", titulo="Como usuario quiero entrar")
    with registro._db(escribe=True) as db:
        db.execute("INSERT INTO relacion(a, b, tipo) VALUES (?,?,'deriva_de')", (hu["id"], o1["id"]))
    registro.fusionar(d["id"], [o1["id"], o2["id"], d["id"]])
    assert [c["texto"] for c in registro.citas(d["id"])] == ["cita 0", "cita 1", "cita 2"]
    xs = {e["id"]: e for e in registro.listar("P", "requisito")}
    assert all(xs[o]["revision"] == "fusionado" and xs[o]["fusionado_en"] == d["id"] for o in (o1["id"], o2["id"]))
    with registro._db() as db:
        rel = {tuple(r) for r in db.execute("SELECT a, b, tipo FROM relacion")}
    assert {(hu["id"], d["id"], "deriva_de"), (o1["id"], d["id"], "fusion"), (o2["id"], d["id"], "fusion"), (hu["id"], o1["id"], "deriva_de")} == rel
    registro.deshacer("P")
    xs = {e["id"]: e for e in registro.listar("P", "requisito")}
    assert len(registro.citas(d["id"])) == 1 and xs[o1["id"]]["revision"] == "propuesto" and xs[o1["id"]]["fusionado_en"] is None
    with registro._db() as db:
        assert [tuple(r) for r in db.execute("SELECT a, b, tipo FROM relacion")] == [(hu["id"], o1["id"], "deriva_de")]


def _n_ent():
    with registro._db() as db:
        return db.execute("SELECT COUNT(*) FROM entidad").fetchone()[0]


def test_sincronizar(cl):
    ds = carpetas.docs(ms())
    ents = registro.sincronizar(C, ds)
    n = _n_ent()
    assert n == len(ents) == sum(len(carpetas.items_doc(d)) for d in ds) + 3  # + 3 decisiones
    assert registro.sincronizar(C, ds).keys() == ents.keys() and _n_ent() == n  # idempotente
    x = ents[P0]
    assert (x["tipo"], x["origen"], x["revision"], x["titulo"], x["dueno"], x["codigo"]) == ("tarea", "reunion", "propuesto", "Arreglar la puerta del garaje", "Javier", "T-001")
    assert registro.citas(x["id"])[0]["t"] == 100 and {e["tipo"] for e in ents.values()} >= {"tarea", "decision", "incidencia"}
    # documento rehecho (otra versión): mismo texto -> misma entidad, con su estado; sin duplicar
    carpetas.set_estado(C, ms(), P0, "hecho", HOY)
    w = pipeline.WORK / "aaaa1111"
    (w / "acta_normal_impaaaa").rename(w / "acta_normal_impaaaa_v2")
    ents = registro.sincronizar(C, carpetas.docs(ms()))
    y = ents["aaaa1111|acta_normal_impaaaa_v2|tareas.0"]
    assert y["id"] == x["id"] and y["estado"] == "hecho" and _n_ent() == n
    # lo editado a mano no lo pisa el documento; lo descartado no reaparece; lo que desaparece queda huérfano
    registro.editar(y["id"], {"titulo": "Puerta del garaje (revisado)"})
    t1 = ents["aaaa1111|acta_normal_impaaaa_v2|tareas.1"]
    registro.borrar(t1["id"])
    f = w / "acta_normal_impaaaa_v2" / "acta.json"
    ac = json.loads(f.read_text())
    ac["tareas"][0]["tarea"] = "Arreglar la puerta del garaje y el portero"
    ac["secciones_plantilla"] = ac["secciones_plantilla"][:1]  # fuera la gotera
    f.write_text(json.dumps(ac, ensure_ascii=False))
    ps = {p["id"]: p for p in carpetas.pendientes(C, ms(), HOY)}
    assert ps["aaaa1111|acta_normal_impaaaa_v2|tareas.0"]["texto"] == "Puerta del garaje (revisado)" and "aaaa1111|acta_normal_impaaaa_v2|tareas.1" not in ps
    assert "Gotera en el portal" not in [p["texto"] for p in ps.values()] and _n_ent() == n
    got = next(e for e in registro.listar(C) if e["titulo"] == "Gotera en el portal")
    assert got["campos"]["huerfano"] is True and registro.listar(C, id=t1["id"])[0]["revision"] == "descartado"
    registro.sincronizar(C, carpetas.docs(ms()))
    assert _n_ent() == n and registro.listar(C, id=y["id"])[0]["titulo"] == "Puerta del garaje (revisado)"


def test_migracion(cl):
    w = pipeline.WORK
    h = carpetas._h("aaaa1111", "Pedir tres presupuestos de pintura del portal")
    sug = {"tipo": "hecho", "cita": "ya arreglamos la puerta", "t": 90, "mid": "cccc3333", "ver": "x", "doc": "Junta marzo", "fecha": "2026-03-09"}
    viejo = {
        C: {"tipo": "Comunidad", "datos": [{"k": "Dirección", "v": "C/ Sol 4"}], "glosario": [{"t": "Otys", "orto": "Otis", "def": ""}], "glos_ignorados": ["Pedro Ruiz"],
            "ajustes": {"anon": True, "idioma": "en"},
            "estados": {P0: {"estado": "hecho", "t": 1, "mid": "aaaa1111", "h": "x"},
                        "aaaa1111|acta_vieja|tareas.1": {"estado": "descartado", "nota": "no hace falta", "t": 2, "mid": "aaaa1111", "h": h},  # por (mid, h)
                        "m:00000001": {"estado": "hecho", "nota": "Actualizado: «x»", "t": 3, "mid": "", "h": ""}},
            "manuales": [{"id": "m:00000001", "texto": "Llamar al seguro", "resp": "Ana", "plazo": "15/03/2026", "creado": 1.7e9},
                         {"id": "m:00000002", "texto": "Renovar el contrato", "resp": "", "plazo": "", "creado": 1.7e9 + 1}],
            "sugeridos": {"m:00000002": sug, "bbbb2222|acta_normal_impbbbb|tareas.0": {**sug, "tipo": "actualizado"}},
            "notas": [{"id": "n1", "fecha": "2026-02-01", "texto": "Hablé con el administrador", "t": 5}],
            "eventos": [{"t": 6, "tipo": "pendiente", "id": P0, "texto": "x", "de": "abierto", "a": "hecho"}], "estado_txt": {"t": 7, "n_docs": 3, "frases": []}, "comparar_txt": {}},
        "Otra": {"tipo": "", "datos": [], "notas": [], "eventos": []}}
    (w / "expedientes.json").write_text(json.dumps(viejo, ensure_ascii=False), encoding="utf-8")

    def comprobar():
        rep = registro.ultima_migracion
        assert rep["antes"] == rep["despues"] == {"carpetas": 2, "manuales": 2, "estados": 3, "sugeridos": 2, "notas": 1, "eventos": 1, "glosario": 1}
        assert not (w / "expedientes.json").exists() and (w / "expedientes.json.migrado").is_file()
        e = carpetas.leer(C)
        assert (e["tipo"], e["datos"], e["ajustes"], e["glosario"], e["glos_ignorados"]) == ("Comunidad", viejo[C]["datos"], {"anon": True, "idioma": "en"}, viejo[C]["glosario"], ["Pedro Ruiz"])
        assert e["notas"] == viejo[C]["notas"] and e["eventos"] == viejo[C]["eventos"] and e["estado_txt"]["n_docs"] == 3 and carpetas.leer("Otra")["eventos"] == []
        assert [m["id"] for m in e["manuales"]] == ["m:00000001", "m:00000002"]
        ps = {p["texto"]: p for p in carpetas.pendientes(C, ms(), HOY)}
        assert ps["Arreglar la puerta del garaje"]["estado"] == "hecho" and ps["Pedir tres presupuestos de pintura del portal"]["estado"] == "descartado"
        assert ps["Pedir tres presupuestos de pintura del portal"]["nota"] == "no hace falta" and ps["Enviar el acta de la junta a todos los vecinos"]["sugerido"]["tipo"] == "actualizado"
        assert ps["Llamar al seguro"]["estado"] == "hecho" and ps["Llamar al seguro"]["manual"] and ps["Llamar al seguro"]["fecha"] == "2026-03-15"
        assert ps["Renovar el contrato"]["sugerido"] == sug and ps["Gotera en el portal"]["estado"] == "abierto"
        ents = registro.listar(C)
        assert {(x["origen"], x["revision"]) for x in ents if x["mid"]} == {("migrado", "aprobado")}  # D3
        assert {(x["origen"], x["revision"]) for x in ents if not x["mid"]} == {("manual", "aprobado")}

    registro.conectar().close()
    comprobar()
    # repetible: rollback = borrar registro.db y devolver el nombre
    for s in ("", "-wal", "-shm"):
        (w / f"registro.db{s}").unlink(missing_ok=True)
    (w / "expedientes.json.migrado").rename(w / "expedientes.json")
    registro.ultima_migracion = None
    registro.conectar().close()
    comprobar()


def test_concurrencia(work):
    errores = []

    def tarea(i):
        try:
            for j in range(10):
                registro.crear("P", "tarea", titulo=f"t{i}.{j}")
                carpetas.añadir_nota("P", f"nota {i}.{j}", "2026-01-01")
        except Exception as e:  # noqa: BLE001
            errores.append(e)
    hs = [threading.Thread(target=tarea, args=(i,)) for i in range(8)]
    [h.start() for h in hs]
    [h.join() for h in hs]
    xs = registro.listar("P", "tarea")
    assert not errores and len(xs) == 80 and sorted(x["codigo"] for x in xs) == [f"T-{n:03d}" for n in range(1, 81)] and len(carpetas.leer("P")["notas"]) == 80
    assert dt.date.fromisoformat(xs[0]["fecha_alta"])


def test_migracion_json_corrupto_no_se_pierde(work):
    f = work / "expedientes.json"
    f.write_text('{"C": {"tipo": ', encoding="utf-8")
    registro.conectar().close()  # la app arranca igual, sin migrar
    assert f.read_text(encoding="utf-8") == '{"C": {"tipo": ' and not (work / "expedientes.json.migrado").exists()
    with registro._db() as db:
        assert not db.execute("SELECT 1 FROM meta WHERE k='migrado_t'").fetchone()
    f.write_text(json.dumps({"C": {"tipo": "X"}}), encoding="utf-8")  # arreglado: se migra en el siguiente arranque
    registro._revisado.clear()
    registro.conectar().close()
    assert (work / "expedientes.json.migrado").is_file() and carpetas.leer("C")["tipo"] == "X"


def test_migracion_items_mal_formados(work):
    viejo = {"A": {"manuales": [{"id": "m:1", "texto": None, "resp": None}, "basura", {"texto": "sin id"}, {"id": "m:2", "texto": "dos"}],
                   "estados": {"m:1": {"estado": "hecho"}}},
             "B": {"manuales": [{"id": "m:1", "texto": "repetido en otra carpeta"}], "estados": ["no", "es", "objeto"]},
             "Z": "no es un expediente"}
    (work / "expedientes.json").write_text(json.dumps(viejo), encoding="utf-8")
    registro.conectar().close()
    rep = registro.ultima_migracion
    assert (work / "expedientes.json.migrado").is_file() and (rep["antes"]["manuales"], rep["despues"]["manuales"]) == (5, 4)
    assert {o["motivo"] for o in rep["omitidos"]} == {"el expediente no es un objeto", "«estados» con formato no válido", "no es un objeto", "sin id: id nuevo",
                                                      "id repetido: id nuevo"}
    a = {x["titulo"]: x for x in registro.listar("A", origen="manual")}
    assert set(a) == {"", "sin id", "dos"} and a[""]["id"] == "m:1" and a[""]["estado"] == "hecho" and a["sin id"]["id"].startswith("m:")
    b = registro.listar("B", origen="manual")
    assert [x["titulo"] for x in b] == ["repetido en otra carpeta"] and b[0]["id"] != "m:1"


def test_migrado_t_global(cl):
    """Con expedientes.json, migrado_t vale para TODAS las carpetas (C no está en el JSON); sin él, 0: todo entra propuesto."""
    (pipeline.WORK / "expedientes.json").write_text(json.dumps({"Otra": {"tipo": ""}}), encoding="utf-8")
    ents = registro.sincronizar(C, carpetas.docs(ms()))
    assert {(x["origen"], x["revision"]) for x in ents.values()} == {("migrado", "aprobado")}


def test_migrado_t_sin_json_y_registro_antiguo(work):
    registro.conectar().close()
    with registro._db() as db:
        assert db.execute("SELECT v FROM meta WHERE k='migrado_t'").fetchone()[0] == 0
    p = registro.proyecto("P")
    with registro._db(escribe=True) as db:  # registro de la versión 2 del esquema: migrado_t por proyecto
        db.execute("UPDATE proyecto SET extra=? WHERE id=?", (json.dumps({"migrado_t": 123.5}), p["id"]))
    db = registro.conectar()
    db.executescript("DROP TABLE meta; DROP TABLE contador; ALTER TABLE historial DROP COLUMN auto; PRAGMA user_version=2;")
    db.close()
    registro.crear("P", "riesgo", titulo="x", lote="L")  # sube el esquema al conectar
    with registro._db() as db:
        assert db.execute("SELECT v FROM meta WHERE k='migrado_t'").fetchone()[0] == 123.5
    assert registro.deshacer("P") == 1


def test_renombrar_no_pierde_datos(work):
    a = registro.crear("A", "riesgo", titulo="de A")
    registro.crear("B", "riesgo", titulo="de B")
    with pytest.raises(ValueError):
        carpetas.renombrar("A", "B")
    assert [x["titulo"] for x in registro.listar("B")] == ["de B"] and [x["titulo"] for x in registro.listar("A")] == ["de A"]
    registro.proyecto("Vacia")  # sin datos: se puede renombrar encima
    carpetas.renombrar("A", "Vacia")
    assert [x["titulo"] for x in registro.listar("Vacia")] == ["de A"] and registro.proyecto("A", False) is None
    carpetas.renombrar("Vacia", "")  # quitar la carpeta aparta su registro, no lo borra
    assert registro.proyecto("Vacia", False) is None and registro.listar("Vacia") == []
    with registro._db() as db:
        r = db.execute("SELECT p.carpeta, p.extra FROM proyecto p JOIN entidad e ON e.proyecto_id=p.id WHERE e.id=?", (a["id"],)).fetchone()
    assert r[0].startswith("Vacia [eliminada ") and json.loads(r[1])["carpeta_eliminada"]["nombre"] == "Vacia"
    assert "carpeta_eliminada" not in registro.expediente(r[0])


def test_deshacer_salta_lotes_auto(work):
    u = registro.crear("P", "riesgo", titulo="usuario", lote="U")
    registro.crear("P", "requisito", titulo="pasada", lote="AUTO", auto=True)
    assert registro.ultimo_lote("P") == "U" and registro.ultimo_lote_ids("P") == [u["id"]]
    assert registro.deshacer("P") == 1 and [x["titulo"] for x in registro.listar("P")] == ["pasada"] and registro.deshacer("P") == 0
    assert registro.deshacer_pasada("P", "AUTO") == 1 and registro.listar("P") == []


def test_codigos_no_se_repiten(work):
    xs = [registro.crear("P", "riesgo", titulo=f"r{i}") for i in range(5)]
    assert [x["codigo"] for x in xs] == [f"R-00{i}" for i in range(1, 6)]
    registro.deshacer("P"), registro.deshacer("P")  # fuera R-005 y R-004
    with registro._db(escribe=True) as db:
        db.execute("DELETE FROM entidad WHERE id=?", (xs[1]["id"],))  # y R-002
    assert [registro.crear("P", "riesgo", titulo="n")["codigo"] for _ in range(2)] == ["R-006", "R-007"]
    with registro._db(escribe=True) as db:
        db.execute("DELETE FROM contador")  # registro de antes de la tabla contador: manda el mayor código
    assert registro.crear("P", "riesgo", titulo="m")["codigo"] == "R-008"
    cods = [x["codigo"] for x in registro.listar("P")]
    assert len(cods) == len(set(cods))


def test_carrera_al_preparar(work):
    """Dos procesos estrenan el mismo work/: el segundo relee user_version con el cerrojo y no repite el esquema."""
    f = work / "registro.db"
    z = sqlite3.connect(f, isolation_level=None)
    z.execute("PRAGMA journal_mode=WAL")
    z.execute("BEGIN IMMEDIATE")
    errores = []

    def prep():
        db = sqlite3.connect(f, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            registro._preparar(db)
        except Exception as e:  # noqa: BLE001
            errores.append(e)
        finally:
            db.close()
    hs = [threading.Thread(target=prep) for _ in range(2)]
    [h.start() for h in hs]
    time.sleep(0.3)  # los dos esperan el cerrojo
    z.execute("COMMIT")
    z.close()
    [h.join() for h in hs]
    assert not errores
    with registro._db() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == len(registro.ESQUEMA)


def test_ref_por_posicion_exige_mismo_texto(cl):
    ents = registro.sincronizar(C, carpetas.docs(ms()))
    t0, t1 = ents[P0], ents["aaaa1111|acta_normal_impaaaa|tareas.1"]
    registro.editar(t0["id"], {"estado": "hecho", "campos": {"nota": "nota de la 0"}})
    f = pipeline.WORK / "aaaa1111" / "acta_normal_impaaaa" / "acta.json"
    ac = json.loads(f.read_text())
    del ac["tareas"][0]  # la 1 pasa a ser la 0
    f.write_text(json.dumps(ac, ensure_ascii=False))
    x = registro.sincronizar(C, carpetas.docs(ms()))[P0]
    assert x["id"] == t1["id"] and x["estado"] == "abierto" and not x["campos"].get("nota")
    assert registro.listar(C, id=t0["id"])[0]["campos"]["huerfano"] is True


def test_fusionar_valida(work):
    r1, r2 = (registro.crear("P", "riesgo", titulo=t) for t in "ab")
    q = registro.crear("P", "requisito", titulo="c")
    with pytest.raises(ValueError, match="mismo tipo"):
        registro.fusionar(r1["id"], [q["id"]])
    with pytest.raises(ValueError, match="mismo tipo"):
        registro.fusionar(r1["id"], [registro.crear("Q", "riesgo", titulo="d")["id"]])
    registro.borrar(r2["id"])
    with pytest.raises(ValueError, match="descartado"):
        registro.fusionar(r2["id"], [r1["id"]])
    assert registro.listar("P", id=r1["id"])[0]["revision"] == "propuesto"  # nada a medias


def test_sincronizar_no_escribe_si_no_cambia(cl):
    ds = carpetas.docs(ms())
    registro.sincronizar(C, ds)
    k = registro.conectar()
    v = k.execute("PRAGMA data_version").fetchone()[0]  # cambia si otra conexión confirma una escritura
    registro.sincronizar(C, ds)
    registro.sincronizar(C, carpetas.docs(ms()))
    assert k.execute("PRAGMA data_version").fetchone()[0] == v
    registro.crear(C, "riesgo", titulo="x")  # control
    assert k.execute("PRAGMA data_version").fetchone()[0] != v
    k.close()


def test_sincronizar_filtra_decisiones_no_firmes(cl):
    ds = carpetas.docs(ms())
    registro.sincronizar(C, ds)
    n = len(registro.listar(C, "decision"))
    f = pipeline.WORK / "aaaa1111" / "acta_normal_impaaaa" / "acta.json"
    ac = json.loads(f.read_text())
    ac["decisiones"] += [{"cita": "x", "texto": "Se aplaza decidir quién redacta las preguntas frecuentes", "t": 200, "b": 0, "n": 1},
                         {"cita": "x", "texto": "La próxima reunión será el martes", "t": 210, "b": 0, "n": 1},
                         {"cita": "deberíamos mirarlo", "texto": "Cambiar el proveedor de pagos", "t": 220, "b": 0, "n": 1},
                         {"cita": "x", "texto": "Se aprueba el calendario de la beta", "t": 230, "b": 0, "n": 1},
                         {"cita": "x", "texto": "Se aprueba presentar el presupuesto en la próxima reunión", "t": 240, "b": 0, "n": 1}]
    f.write_text(json.dumps(ac, ensure_ascii=False))
    registro.sincronizar(C, carpetas.docs(ms()))
    assert [x["titulo"] for x in registro.listar(C, "decision")][n:] == [  # en un acta solo se descarta lo aplazado; próxima reunión / propuestas llegan como propuestos para revisar
        "La próxima reunión será el martes", "Cambiar el proveedor de pagos", "Se aprueba el calendario de la beta", "Se aprueba presentar el presupuesto en la próxima reunión"]
