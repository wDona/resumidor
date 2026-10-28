"""Registro del proyecto en work/registro.db (sqlite3 de serie, WAL): una fila `proyecto` por carpeta y sus entidades (tareas, riesgos,
decisiones…) con cita, relaciones, historial e informes. carpetas.py lo usa por debajo sin cambiar su API: leer()/editar() siguen dando
el expediente como dict (expediente() y guardar_expediente() lo traducen).

Invariantes que no se ven a simple vista:
- Escrituras siempre en _db(escribe=True): bajo LOCK (el mismo objeto que carpetas.LOCK) y en una transacción; lecturas sin LOCK (WAL).
  Una conexión por llamada; las funciones aceptan `db` para encadenarse dentro de la misma transacción.
- id legado de una entidad (el `id` de los pendientes de siempre): el suyo si no viene de un documento (manuales «m:…»); si viene, mid|ver|ruta.
  sincronizar() empareja primero por ese id y luego por (mid, h): un acta rehecha (otra versión) conserva estado, nota y sugerencia.
- Las entidades de poblar.py (campos.fuente='poblar', ruta 'poblar.<tipo>.<h>') y derivar.py (fuente='derivar') no son ítems del acta: sincronizar() las ignora.
- sincronizar() no borra ni pisa: lo que ya no está en su documento queda con campos.huerfano; lo editado (editado=1) conserva su contenido;
  lo descartado o fusionado sigue emparejado (no reaparece). No escribe historial: deshacer() solo revierte lotes del usuario.
- editado=1 solo cuando cambia el contenido (CONTENIDO); estado, nota, revisión o sugerencia no cuentan.
- Lo que el expediente dice de un id que aún no es entidad (estados de expedientes.json, o una sugerencia antes de la primera
  sincronización) va a proyecto.extra.estados_legado / sugeridos_legado y se aplica al crear la entidad; existiendo la entidad, manda ella.
- Migración: user_version 0 y work/expedientes.json → todo en una transacción y luego expedientes.json.migrado. Deshacerla: borrar
  registro.db (-wal, -shm) y devolver el nombre; se repite sola. Ítems de documentos anteriores a la migración entran aprobado/migrado (D3)
  en TODAS las carpetas (también las que no estaban en el JSON); los de reuniones nuevas, propuesto/reunion. La hora es una sola
  (meta.migrado_t): la de la migración, o 0 si no había expedientes.json (todo entra propuesto). Un JSON ilegible o que no cuadra
  (recuentos antes/después, salvo lo omitido en rep["omitidos"]) no se migra ni se renombra: se avisa en el log y se reintenta al arrancar.
- historial.auto=1: lotes de pasadas en segundo plano (poblar, derivar). deshacer() (Ctrl+Z) los salta; deshacer_pasada(c, lote) los quita.
- Códigos (R-003): contador por proyecto y tipo que no baja (tabla contador): deshacer o borrar no hace que un código se repita.
- Renombrar sobre una carpeta con datos en el registro: ValueError (no se fusionan ni se pisan). Quitar una carpeta no borra su registro: el
  proyecto queda como «<nombre> [eliminada <fecha>]» con extra.carpeta_eliminada (recuperable renombrándolo).
"""
import contextlib
import datetime as dt
import json
import logging
import sqlite3
import threading
import time
import uuid

import pipeline as P

LOCK = threading.RLock()
log = logging.getLogger(__name__)
TIPOS = {"decision": "D", "tarea": "T", "riesgo": "R", "incidencia": "INC", "supuesto": "S", "dependencia": "DEP", "requisito": "REQ", "historia": "HU",
         "pregunta": "P", "interesado": "INT", "hito": "H"}  # tipo -> prefijo del código (por proyecto y tipo: R-003)
CONTENIDO = {"titulo", "detalle", "dueno", "prioridad", "fecha_limite"}
OCULTA = ("descartado", "fusionado")
ECOLS = ("id", "proyecto_id", "tipo", "codigo", "titulo", "detalle", "estado", "revision", "origen", "dueno", "prioridad", "fecha_limite", "fecha_alta",
         "fecha_cierre", "campos", "mid", "ver", "ruta", "h", "editado", "sugerencia", "fusionado_en", "orden", "creado", "modificado")
JSONS = {"datos", "ajustes", "glosario", "extra", "campos", "sugerencia", "antes", "despues"}
PCOLS = ("tipo", "datos", "ajustes", "glosario")  # del expediente, con columna propia; manuales/estados/sugeridos son entidades; el resto, extra
LEGADO = ("estados_legado", "sugeridos_legado", "migrado_t", "carpeta_eliminada")  # migrado_t: de antes de meta.migrado_t (solo se lee al subir el esquema)
_lista = lambda xs: ",".join(f"'{x}'" for x in xs)
ESQUEMA = [f"""
CREATE TABLE proyecto(id INTEGER PRIMARY KEY, carpeta TEXT NOT NULL UNIQUE, tipo TEXT, datos TEXT, ajustes TEXT, glosario TEXT, extra TEXT NOT NULL DEFAULT '{{}}');
CREATE TABLE entidad(id TEXT PRIMARY KEY, proyecto_id INTEGER NOT NULL REFERENCES proyecto(id) ON DELETE CASCADE,
  tipo TEXT NOT NULL CHECK (tipo IN ({_lista(TIPOS)})), codigo TEXT, titulo TEXT NOT NULL DEFAULT '', detalle TEXT NOT NULL DEFAULT '',
  estado TEXT NOT NULL DEFAULT '', revision TEXT NOT NULL DEFAULT 'propuesto' CHECK (revision IN ('propuesto','aprobado','descartado','fusionado')),
  origen TEXT NOT NULL DEFAULT 'manual' CHECK (origen IN ('reunion','manual','derivado','migrado')),
  dueno TEXT NOT NULL DEFAULT '', prioridad TEXT NOT NULL DEFAULT '', fecha_limite TEXT, fecha_alta TEXT, fecha_cierre TEXT, campos TEXT NOT NULL DEFAULT '{{}}',
  mid TEXT, ver TEXT, ruta TEXT, h TEXT, editado INTEGER NOT NULL DEFAULT 0, sugerencia TEXT, fusionado_en TEXT, orden REAL, creado REAL, modificado REAL,
  UNIQUE(proyecto_id, mid, ver, ruta));
CREATE INDEX entidad_vista ON entidad(proyecto_id, tipo, revision, estado);
CREATE INDEX entidad_h ON entidad(proyecto_id, mid, h);
CREATE TABLE cita(id INTEGER PRIMARY KEY, entidad_id TEXT NOT NULL REFERENCES entidad(id) ON DELETE CASCADE, mid TEXT, ver TEXT, t REAL, texto TEXT,
  verificada INTEGER NOT NULL DEFAULT 0);
CREATE INDEX cita_entidad ON cita(entidad_id);
CREATE TABLE relacion(a TEXT NOT NULL REFERENCES entidad(id) ON DELETE CASCADE, b TEXT NOT NULL REFERENCES entidad(id) ON DELETE CASCADE,
  tipo TEXT NOT NULL CHECK (tipo IN ('deriva_de','sustituye','bloquea','mitiga','afecta','responde','solicita','fusion')),
  propuesta INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(a, b, tipo));
CREATE TABLE historial(id INTEGER PRIMARY KEY, proyecto_id INTEGER NOT NULL REFERENCES proyecto(id) ON DELETE CASCADE, entidad_id TEXT, t REAL,
  accion TEXT NOT NULL, antes TEXT, despues TEXT, lote TEXT NOT NULL);
CREATE INDEX historial_lote ON historial(proyecto_id, lote);
CREATE TABLE informe(id INTEGER PRIMARY KEY, proyecto_id INTEGER NOT NULL REFERENCES proyecto(id) ON DELETE CASCADE, titulo TEXT, desde TEXT, hasta TEXT,
  semaforos TEXT, contenido TEXT, estado TEXT NOT NULL DEFAULT 'borrador', creado REAL, modificado REAL);
""", """
ALTER TABLE informe ADD COLUMN serie INTEGER;
ALTER TABLE informe ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
CREATE INDEX informe_serie ON informe(proyecto_id, serie, version);
""", """
ALTER TABLE historial ADD COLUMN auto INTEGER NOT NULL DEFAULT 0;
CREATE TABLE meta(k TEXT PRIMARY KEY, v);
CREATE TABLE contador(proyecto_id INTEGER NOT NULL REFERENCES proyecto(id) ON DELETE CASCADE, tipo TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY(proyecto_id, tipo));
"""]  # una entrada por versión del esquema (user_version = cuántas se han aplicado); solo se añaden al final
ultima_migracion = None  # informe {antes, despues} de la última migración de expedientes.json en este proceso


def _j(v):
    return None if v is None else json.dumps(v, ensure_ascii=False)


def _json():
    return P.WORK / "expedientes.json"


# ---------- conexión y esquema ----------
def conectar():
    """Conexión nueva (quien la abre la cierra). La primera vez crea o pone al día el esquema y migra expedientes.json."""
    P.WORK.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(P.WORK / "registro.db", timeout=15, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    if str(P.WORK) not in _revisado or db.execute("PRAGMA user_version").fetchone()[0] < len(ESQUEMA):
        with LOCK:
            _preparar(db)
    return db


_revisado = set()  # WORKs ya preparados en este proceso (una migración pendiente se reintenta una vez por arranque)


def _preparar(db):
    global ultima_migracion
    db.execute("PRAGMA journal_mode=WAL")
    try:
        db.execute("BEGIN IMMEDIATE")
        v0 = db.execute("PRAGMA user_version").fetchone()[0]  # releída con el cerrojo: otro proceso puede haberla subido ya
        for s in "".join(ESQUEMA[v0:]).split(";"):  # una transacción para todo el esquema (executescript haría COMMIT)
            if s.strip():
                db.execute(s)
        if 0 < v0 < 3:  # registro de antes de meta.migrado_t: la de su migración (la misma en todos los proyectos) o 0
            db.execute("INSERT OR IGNORE INTO meta(k, v) SELECT 'migrado_t', COALESCE(MAX(json_extract(extra, '$.migrado_t')), 0) FROM proyecto")
        elif v0 == 0 and not _json().is_file():
            db.execute("INSERT OR IGNORE INTO meta(k, v) VALUES ('migrado_t', 0)")
        db.execute(f"PRAGMA user_version={len(ESQUEMA)}")
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    _revisado.add(str(P.WORK))
    if not _json().is_file() or db.execute("SELECT 1 FROM meta WHERE k='migrado_t'").fetchone():
        return
    try:  # migración en su propia transacción: si falla, el esquema queda y la app arranca sin migrar (se reintenta al arrancar)
        db.execute("BEGIN IMMEDIATE")
        rep = None if db.execute("SELECT 1 FROM meta WHERE k='migrado_t'").fetchone() else migrar_json(db)
        db.execute("COMMIT")
    except Exception as ex:  # noqa: BLE001
        if db.in_transaction:
            db.execute("ROLLBACK")
        log.error("registro: NO se migró expedientes.json (queda intacto; se reintentará al arrancar): %s", ex)
        return
    if rep:
        _json().replace(_json().with_name("expedientes.json.migrado"))
        ultima_migracion = rep
        log.warning("registro: migrado expedientes.json -> registro.db antes=%s despues=%s omitidos=%s", rep["antes"], rep["despues"], rep["omitidos"])


@contextlib.contextmanager
def _db(db=None, escribe=False):
    if db is not None:  # ya dentro de una transacción de quien llama
        yield db
        return
    with LOCK if escribe else contextlib.nullcontext():
        db = conectar()
        try:
            if escribe:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if escribe:
                db.execute("COMMIT")
        finally:
            if db.in_transaction:
                db.execute("ROLLBACK")
            db.close()


def _fila(r):
    return r and {k: (json.loads(r[k]) if k in JSONS and r[k] is not None else r[k]) for k in r.keys()}


def _ent(r):
    x = _fila(r)
    if x:
        x["campos"] = x["campos"] or {}
    return x


def _uno(db, eid):
    x = _ent(db.execute("SELECT * FROM entidad WHERE id=?", (eid,)).fetchone())
    if not x:
        raise KeyError("Esa entidad no existe")
    return x


def ref(x):
    """id legado (el de los pendientes): mid|ver|ruta si viene de un documento; si no, el propio id."""
    return x["id"] if x["mid"] is None else f"{x['mid']}|{x['ver']}|{x['ruta']}"


# ---------- proyecto ----------
def proyecto(c, crear=True, db=None):
    """Fila del proyecto de la carpeta c (JSON ya decodificado); la crea si no existe (salvo crear=False: entonces None)."""
    with _db(db, crear) as db:
        q = lambda: db.execute("SELECT * FROM proyecto WHERE carpeta=?", (c,)).fetchone()
        r = q()
        if not r and crear:
            db.execute("INSERT INTO proyecto(carpeta) VALUES (?)", (c,))
            r = q()
        return _fila(r)


def _con_datos(db, pid):
    """¿El proyecto tiene algo que perder? (entidades, informes o algo guardado en el expediente)"""
    p = _fila(db.execute("SELECT * FROM proyecto WHERE id=?", (pid,)).fetchone())
    return bool(any(p[k] for k in PCOLS) or any(p["extra"].values()) or
                db.execute("SELECT 1 FROM entidad WHERE proyecto_id=? UNION ALL SELECT 1 FROM informe WHERE proyecto_id=? LIMIT 1", (pid, pid)).fetchone())


def renombrar(old, new):
    """Mueve el proyecto a otra carpeta (new) o lo aparta (new vacío). Nunca borra datos: sobre una carpeta que ya tiene registro -> ValueError
    (salvo que el de old esté vacío); quitar la carpeta deja el proyecto como «old [eliminada …]» con extra.carpeta_eliminada."""
    with _db(escribe=True) as db:
        o = db.execute("SELECT id FROM proyecto WHERE carpeta=?", (old,)).fetchone()
        if old == new or not o:
            return
        if not _con_datos(db, o[0]):
            db.execute("DELETE FROM proyecto WHERE id=?", o)  # nada que mover ni que guardar
            return
        if not new:
            ext = proyecto(old, False, db)["extra"]
            db.execute("UPDATE proyecto SET carpeta=?, extra=? WHERE id=?", (f"{old} [eliminada {time.strftime('%Y-%m-%d %H:%M')} #{o[0]}]",
                                                                             _j({**ext, "carpeta_eliminada": {"nombre": old, "t": time.time()}}), o[0]))
            return
        n = db.execute("SELECT id FROM proyecto WHERE carpeta=?", (new,)).fetchone()
        if n and _con_datos(db, n[0]):
            raise ValueError(f"La carpeta «{new}» ya existe y tiene datos en el registro: elige otro nombre")
        if n:
            db.execute("DELETE FROM proyecto WHERE id=?", n)
        db.execute("UPDATE proyecto SET carpeta=? WHERE id=?", (new, o[0]))


# ---------- entidades ----------
def _hist(db, pid, eid, accion, antes, despues, lote, auto=False):
    db.execute("INSERT INTO historial(proyecto_id, entidad_id, t, accion, antes, despues, lote, auto) VALUES (?,?,?,?,?,?,?,?)",
               (pid, eid, time.time(), accion, _j(antes), _j(despues), lote or uuid.uuid4().hex[:10], int(auto)))


def _poner(db, eid, cambios):
    cambios = {**cambios, "modificado": time.time()}
    db.execute(f"UPDATE entidad SET {', '.join(f'{k}=?' for k in cambios)} WHERE id=?", [_j(v) if k in JSONS else v for k, v in cambios.items()] + [eid])


def crear(c, tipo, lote=None, db=None, cita=None, auto=False, **f):
    """Entidad nueva en el proyecto de c (lo crea si hace falta). f: columnas de entidad; cita: {mid, ver, t, texto, verificada}.
    lote=False: sin historial (sincronizar, migración). auto=True: lote de una pasada en segundo plano (deshacer() no lo toca)."""
    if tipo not in TIPOS or set(f) - set(ECOLS):
        raise ValueError(f"Entidad no válida: {tipo} {sorted(set(f) - set(ECOLS))}")
    with _db(db, True) as db:
        p = proyecto(c, db=db)["id"]
        pre = TIPOS[tipo] + "-"  # contador que no baja; el MAX cubre los registros de antes de la tabla contador
        n = max(db.execute("SELECT COALESCE(MAX(n), 0) FROM contador WHERE proyecto_id=? AND tipo=?", (p, tipo)).fetchone()[0],
                db.execute("SELECT COALESCE(MAX(CAST(substr(codigo, ?) AS INTEGER)), 0) FROM entidad WHERE proyecto_id=? AND tipo=? AND codigo LIKE ?",
                           (len(pre) + 1, p, tipo, pre + "%")).fetchone()[0])
        db.execute("INSERT INTO contador(proyecto_id, tipo, n) VALUES (?,?,?) ON CONFLICT(proyecto_id, tipo) DO UPDATE SET n=excluded.n", (p, tipo, n + 1))
        t = time.time()
        x = {"id": uuid.uuid4().hex[:10], "estado": "" if tipo == "decision" else "abierto", "creado": t, "campos": {}, **f,
             "proyecto_id": p, "tipo": tipo, "codigo": f"{TIPOS[tipo]}-{n + 1:03d}", "modificado": t}
        x.setdefault("fecha_alta", dt.date.fromtimestamp(x["creado"]).isoformat())
        db.execute(f"INSERT INTO entidad({', '.join(x)}) VALUES ({', '.join('?' * len(x))})", [_j(v) if k in JSONS else v for k, v in x.items()])
        if cita:
            citar(x["id"], cita, db)
        if lote is not False:
            _hist(db, p, x["id"], "crear", None, {k: v for k, v in x.items() if k != "proyecto_id"}, lote, auto)
        return _uno(db, x["id"])


def citar(eid, cita, db=None):
    """Añade una cita {mid, ver, t, texto, verificada} a la entidad; no toca su contenido ni su revisión (poblar: lo mismo dicho en otra reunión)."""
    with _db(db, True) as db:
        db.execute("INSERT INTO cita(entidad_id, mid, ver, t, texto, verificada) VALUES (?,?,?,?,?,?)",
                   (eid, cita.get("mid"), cita.get("ver"), cita.get("t"), cita.get("texto"), int(bool(cita.get("verificada")))))


def editar(eid, cambios, lote=None, db=None):
    """Cambia columnas de la entidad (campos se fusiona) y lo apunta en el historial con antes/después. lote=False: sin historial."""
    if set(cambios) - set(ECOLS) or {"id", "proyecto_id"} & set(cambios):
        raise ValueError("Cambio no válido")
    with _db(db, True) as db:
        x = _uno(db, eid)
        if "campos" in cambios:
            cambios = {**cambios, "campos": {**x["campos"], **cambios["campos"]}}
        cambios = {k: v for k, v in cambios.items() if x[k] != v}
        if not cambios:
            return x
        if CONTENIDO & set(cambios) and not x["editado"]:
            cambios["editado"] = 1
        _poner(db, eid, cambios)
        if lote is not False:
            _hist(db, x["proyecto_id"], eid, "editar", {k: x[k] for k in cambios}, cambios, lote)
        return _uno(db, eid)


def borrar(eid, lote=None, db=None):
    """Borrado lógico: revision='descartado' (ni se borra ni reaparece al sincronizar)."""
    return editar(eid, {"revision": "descartado"}, lote, db)


RELLENA = ("titulo", "detalle", "dueno", "prioridad", "fecha_limite")  # columnas que fusionar() copia al destino si allí están vacías
NO_RELLENA = ("fuente", "huerfano", "clave", "seccion")  # claves de campos que no se copian (del sistema o del documento)


def fusionar(destino, origenes, lote=None):
    """Los orígenes pasan a «fusionado» (fusionado_en=destino, relación «fusion»); el destino recibe copia de sus citas y relaciones,
    rellena con los del origen sus campos VACÍOS y, si el texto del origen dice otra cosa, una línea «Fusionado desde D-xx: …» en su detalle.
    Un registro «fusionar» por origen (origen, revisión previa, citas, relaciones, relleno, nota) para separar(); todo en un lote (Ctrl+Z)."""
    lote = lote or uuid.uuid4().hex[:10]
    with _db(escribe=True) as db:
        d = _uno(db, destino)
        if d["revision"] in OCULTA:
            raise ValueError("El destino de la fusión está descartado o fusionado")
        for o in dict.fromkeys(origenes):
            if o == destino:
                continue
            x, hecho = _uno(db, o), {"origen": o, "citas": [], "rel": []}
            if (x["tipo"], x["proyecto_id"]) != (d["tipo"], d["proyecto_id"]):
                raise ValueError("Solo se fusionan entidades del mismo tipo y proyecto")
            if x["revision"] in OCULTA:
                raise ValueError(f"{x['codigo'] or 'El origen'} ya está descartado o fusionado")
            hecho["revision"] = x["revision"]
            for r in db.execute("SELECT mid, ver, t, texto, verificada FROM cita WHERE entidad_id=?", (o,)).fetchall():
                hecho["citas"].append(db.execute("INSERT INTO cita(entidad_id, mid, ver, t, texto, verificada) VALUES (?,?,?,?,?,?)", (destino, *r)).lastrowid)
            rels = [(destino if a == o else a, destino if b == o else b, t, p) for a, b, t, p in
                    db.execute("SELECT a, b, tipo, propuesta FROM relacion WHERE (a=? OR b=?) AND tipo!='fusion'", (o, o)).fetchall()] + [(o, destino, "fusion", 0)]
            for a, b, t, p in rels:
                if a != b and db.execute("INSERT OR IGNORE INTO relacion(a, b, tipo, propuesta) VALUES (?,?,?,?)", (a, b, t, p)).rowcount:
                    hecho["rel"].append([a, b, t])
            d = _uno(db, destino)
            rel = {k: x[k] for k in RELLENA if not str(d[k] or "").strip() and str(x[k] or "").strip()}
            rc = {k: v for k, v in x["campos"].items() if k not in NO_RELLENA and v not in ("", None) and d["campos"].get(k) in ("", None)}
            resto = [s for s in (x["titulo"] if "titulo" not in rel and x["titulo"].strip() != d["titulo"].strip() else "",
                                 x["detalle"] if "detalle" not in rel and x["detalle"].strip() not in ("", d["detalle"].strip()) else "") if s.strip()]
            nota = f"Fusionado desde {x['codigo'] or o}: " + " — ".join(s.strip() for s in resto) if resto else ""
            cambios = {**rel, **({"campos": rc} if rc else {})}
            if nota:
                det = cambios.get("detalle", d["detalle"])
                cambios["detalle"] = (det.rstrip() + "\n" if det.strip() else "") + nota
            if cambios:
                editar(destino, cambios, lote, db)
            hecho.update(relleno={**rel, "campos": rc}, nota=nota)
            editar(o, {"revision": "fusionado", "fusionado_en": destino}, lote, db)
            _hist(db, d["proyecto_id"], destino, "fusionar", None, hecho, lote)
        return _uno(db, destino)


def separar(destino, origen, lote=None):
    """Deshace UNA fusión aunque haya habido cambios después: el origen vuelve a su revisión previa y el destino pierde las citas y relaciones
    que le trajo, la nota «Fusionado desde…» y lo rellenado que siga igual. Un lote propio (Ctrl+Z vuelve a fusionar).
    Límites: una relación que ya traían dos orígenes se quita al separar el primero; fusiones de antes de este registro solo
    recuperan la revisión del origen y la relación «fusion» (no se sabe qué citas trajeron)."""
    lote = lote or uuid.uuid4().hex[:10]
    with _db(escribe=True) as db:
        x, d = _uno(db, origen), _uno(db, destino)
        if x["revision"] != "fusionado" or x["fusionado_en"] != destino:
            raise ValueError(f"{x['codigo'] or 'Ese elemento'} no está fusionado en {d['codigo'] or 'ese destino'}")
        f = next((json.loads(r[0]) for r in db.execute("SELECT despues FROM historial WHERE entidad_id=? AND accion='fusionar' ORDER BY id DESC", (destino,))
                  if json.loads(r[0]).get("origen") == origen), None)
        if f is None:  # fusión antigua: la revisión previa sale del «editar» que la marcó fusionada
            prev = next((json.loads(r[0]).get("revision") for r in db.execute("SELECT antes FROM historial WHERE entidad_id=? AND accion='editar' AND despues LIKE '%fusionado%' ORDER BY id DESC", (origen,))), None)
            f = {"revision": prev or "propuesto", "citas": [], "rel": [[origen, destino, "fusion"]], "relleno": {}, "nota": ""}
        cs = [dict(r) for r in db.execute(f"SELECT * FROM cita WHERE id IN ({','.join('?' * len(f['citas']))})", f["citas"])] if f["citas"] else []
        rs = [list(r) for a, b, t in f["rel"] for r in db.execute("SELECT a, b, tipo, propuesta FROM relacion WHERE a=? AND b=? AND tipo=?", (a, b, t))]
        db.executemany("DELETE FROM cita WHERE id=?", [(c["id"],) for c in cs])
        db.executemany("DELETE FROM relacion WHERE a=? AND b=? AND tipo=?", [r[:3] for r in rs])
        _hist(db, d["proyecto_id"], destino, "separar", {"citas": cs, "rel": rs}, {"origen": origen}, lote)
        rel = f.get("relleno") or {}
        cambios = {k: "" for k, v in rel.items() if k != "campos" and d[k] == v and k != "titulo"}  # el título no se vacía nunca
        if rc := {k: "" for k, v in (rel.get("campos") or {}).items() if d["campos"].get(k) == v}:
            cambios["campos"] = rc
        if f.get("nota") and f["nota"] in (det := cambios.get("detalle", d["detalle"])):
            cambios["detalle"] = (det.replace("\n" + f["nota"], "", 1) if "\n" + f["nota"] in det else det.replace(f["nota"], "", 1)).strip()
        if cambios:
            editar(destino, cambios, lote, db)
        editar(origen, {"revision": f["revision"], "fusionado_en": None}, lote, db)
        return _uno(db, destino)


def fusionadas(ids, db=None):
    """{destino: [{id, codigo, titulo, fecha, citas}]} de lo fusionado (y aún oculto) en cada id."""
    if not ids:
        return {}
    out = {}
    with _db(db) as db:
        for r in db.execute(f"SELECT e.id, e.codigo, e.titulo, e.modificado, e.fusionado_en, (SELECT COUNT(*) FROM cita WHERE entidad_id=e.id) "
                            f"FROM entidad e WHERE e.revision='fusionado' AND e.fusionado_en IN ({','.join('?' * len(ids))}) ORDER BY e.modificado", list(ids)):
            out.setdefault(r[4], []).append({"id": r[0], "codigo": r[1], "titulo": r[2], "fecha": dt.datetime.fromtimestamp(r[3] or 0).strftime("%Y-%m-%d %H:%M"), "citas": r[5]})
    return out


def _ultimo(db, c):
    """(id del proyecto, último lote del USUARIO) o None: los lotes auto (poblar, derivar) no son pasos de Ctrl+Z."""
    p = proyecto(c, False, db)
    r = p and db.execute("SELECT lote FROM historial WHERE proyecto_id=? AND auto=0 ORDER BY id DESC LIMIT 1", (p["id"],)).fetchone()
    return r and (p["id"], r[0])


def deshacer(c):
    """Revierte el último lote del usuario del proyecto (en orden inverso) y lo quita del historial. -> nº de cambios revertidos."""
    with _db(escribe=True) as db:
        r = _ultimo(db, c)
        return _revertir(db, *r) if r else 0


def deshacer_pasada(c, lote):
    """Revierte un lote concreto (p. ej. una pasada de poblar/derivar, que deshacer() salta). -> nº de cambios revertidos."""
    with _db(escribe=True) as db:
        p = proyecto(c, False, db)
        return _revertir(db, p["id"], lote) if p else 0


def _revertir(db, pid, lote):
    hs = db.execute("SELECT * FROM historial WHERE proyecto_id=? AND lote=? ORDER BY id DESC", (pid, lote)).fetchall()
    for h in hs:
        antes, despues = (json.loads(h[k]) if h[k] else None for k in ("antes", "despues"))
        if h["accion"] == "crear":
            db.execute("DELETE FROM entidad WHERE id=?", (h["entidad_id"],))
        elif h["accion"] == "editar":
            _poner(db, h["entidad_id"], antes)
        elif h["accion"] == "niveles":
            _extra(db, h["proyecto_id"], matriz_niveles_poder=antes.get("niveles_poder", antes.get("niveles")),
                   matriz_niveles_interes=antes.get("niveles_interes", antes.get("niveles")))
        elif h["accion"] == "fusionar":
            db.executemany("DELETE FROM cita WHERE id=?", [(i,) for i in despues["citas"]])
            db.executemany("DELETE FROM relacion WHERE a=? AND b=? AND tipo=?", despues["rel"])
        elif h["accion"] == "separar":  # vuelve a poner las citas (mismo id: la fusión las sigue reconociendo) y relaciones que quitó
            for ci in antes["citas"]:
                db.execute(f"INSERT OR IGNORE INTO cita({', '.join(ci)}) VALUES ({', '.join('?' * len(ci))})", list(ci.values()))
            db.executemany("INSERT OR IGNORE INTO relacion(a, b, tipo, propuesta) VALUES (?,?,?,?)", antes["rel"])
    db.execute("DELETE FROM historial WHERE proyecto_id=? AND lote=?", (pid, lote))
    return len(hs)


# ---------- escala de la matriz de interesados (poder/interés 1..N; N en proyecto.extra) ----------
NIVELES_DEF = 6


def _extra(db, pid, **k):
    ext = json.loads(db.execute("SELECT extra FROM proyecto WHERE id=?", (pid,)).fetchone()[0] or "{}")
    db.execute("UPDATE proyecto SET extra=? WHERE id=?", (_j({**ext, **k}), pid))


def niveles_ejes(c, db=None):
    """(huecos de poder, huecos de interés); cae en `matriz_niveles` (antiguo, un solo N) y luego en NIVELES_DEF."""
    e = ((proyecto(c, False, db) or {}).get("extra") or {})
    return (int(e.get("matriz_niveles_poder") or e.get("matriz_niveles") or NIVELES_DEF),
            int(e.get("matriz_niveles_interes") or e.get("matriz_niveles") or NIVELES_DEF))


def niveles(c, db=None):
    return niveles_ejes(c, db)[0]


def num_medio(v):
    """Valor de poder/interés como número múltiplo de 0,5 (int si es entero) o None si no lo es."""
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None
    try:
        f = float(str(v).strip().replace(",", ".")) if isinstance(v, str) else float(v)
    except ValueError:
        return None
    return (int(f) if f == int(f) else f) if f * 2 == int(f * 2) else None


def matriz(c, poder=None, interes=None, reescalar=False):
    """Pone los huecos de la matriz de interesados (poder = filas, interés = columnas; 3..10 cada eje; None = no cambia), en un solo lote del usuario
    (deshacer lo revierte todo, niveles incluidos). reescalar: cada eje se remapea proporcionalmente a pasos de 0,5; si no, solo se recorta lo que pase.
    -> (ids cambiados, recortados). ValueError si algún nivel no vale o no hay ninguno."""
    if poder is None and interes is None:
        raise ValueError("Falta niveles_poder o niveles_interes")
    for n in (poder, interes):
        if n is not None and (isinstance(n, bool) or not isinstance(n, int) or not 3 <= n <= 10):
            raise ValueError("niveles debe ser un entero de 3 a 10")
    lote, cambiados, recortados = uuid.uuid4().hex[:10], [], 0
    with _db(escribe=True) as db:
        pid = proyecto(c, db=db)["id"]
        op, oi = niveles_ejes(c, db)
        np_, ni = poder or op, interes or oi
        for r in db.execute("SELECT id FROM entidad WHERE proyecto_id=? AND tipo='interesado'", (pid,)).fetchall():
            x = _uno(db, r[0])
            cm = {}
            for k, old, nuevo in (("poder", op, np_), ("interes", oi, ni)):
                v = num_medio(x["campos"].get(k, ""))
                if v is None:
                    continue
                n = min(max(int(((v - 1) * (nuevo - 1) / (old - 1) + 1) * 2 + 0.5) / 2, 1), nuevo) if reescalar else min(v, nuevo)
                n = int(n) if n == int(n) else n
                if n != v:
                    cm[k] = n
                    recortados += not reescalar
            if cm:
                editar(x["id"], {"campos": cm}, lote, db)
                cambiados.append(x["id"])
        if (np_, ni) != (op, oi):
            _hist(db, pid, None, "niveles", {"niveles_poder": op, "niveles_interes": oi}, {"niveles_poder": np_, "niveles_interes": ni}, lote)
            _extra(db, pid, matriz_niveles_poder=np_, matriz_niveles_interes=ni)
    return cambiados, recortados


def historial(eid):
    with _db() as db:
        return [_fila(r) for r in db.execute("SELECT * FROM historial WHERE entidad_id=? ORDER BY id", (eid,))]


def listar(c, tipo=None, db=None, **filtros):
    """Entidades del proyecto de c por orden de creación; filtros: columna=valor (revision='aprobado', origen='manual'…)."""
    if set(filtros) - set(ECOLS):
        raise ValueError("Filtro no válido")
    if db is None and _vacio():
        return []
    with _db(db) as db:
        p = proyecto(c, False, db)
        if not p:
            return []
        w = {"proyecto_id": p["id"], **({"tipo": tipo} if tipo else {}), **filtros}
        return [_ent(r) for r in db.execute(f"SELECT * FROM entidad WHERE {' AND '.join(f'{k}=?' for k in w)} ORDER BY creado, rowid", list(w.values()))]


def citas(eid):
    with _db() as db:
        return [dict(r) for r in db.execute("SELECT * FROM cita WHERE entidad_id=? ORDER BY id", (eid,))]


# ---------- documentos -> entidades ----------
def _items(d):
    """Ítems seguibles de un documento (carpetas.items_doc) + sus decisiones, con el mismo formato."""
    import carpetas  # importa este módulo: aquí, para no hacer un ciclo al cargar
    return carpetas.items_doc(d) + [{**carpetas._ref(d, x.get("t")), "fecha_doc": d["fecha"], "id": f"{d['mid']}|{d['ver']}|decisiones.{i}", "tipo": "Decisiones",
                                     "tipo_ent": "decision", "texto": x["texto"], "resp": "", "plazo": "", "cita": x.get("cita") or "", "h": carpetas._h(d["mid"], x["texto"]),
                                     "fecha": None} for i, x in enumerate(d["data"].get("decisiones") or []) if str(x.get("texto") or "").strip()]


def _del_doc(it):
    return {"titulo": it["texto"], "dueno": it["resp"], "fecha_limite": it["fecha"], "fecha_alta": it["fecha_doc"], "ver": it["ver"],
            "ruta": it["id"].split("|", 2)[2], "h": it["h"]}


def sincronizar(c, docs):
    """Pone al día las entidades de la carpeta con sus documentos (carpetas.docs()). Idempotente; ver el docstring del módulo.
    -> {id legado: entidad} de los ítems actuales (también los descartados/fusionados: quien muestra decide)."""
    its = [(d, it) for d in docs for it in _items(d)]
    with _db() as db:  # primero en seco y sin cerrojo (casi siempre no hay nada que cambiar); el cerrojo, solo si algo difiere
        try:
            return _sincronizar(db, c, its, True)
        except _Cambia:
            pass
    with _db(escribe=True) as db:  # rehace la comparación dentro de la transacción: otro pudo escribir entre medias
        return _sincronizar(db, c, its, False)


class _Cambia(Exception):
    """_sincronizar en seco: hay algo que escribir."""


def _sincronizar(db, c, its, seco):
    def escribe():
        if seco:
            raise _Cambia
    p = proyecto(c, False, db)
    if not p and its:
        escribe()
        p = proyecto(c, db=db)
    if not p:
        return {}
    ents = [x for x in map(_ent, db.execute("SELECT * FROM entidad WHERE proyecto_id=? AND mid IS NOT NULL ORDER BY creado, rowid", (p["id"],)))
            if x["campos"].get("fuente") not in ("poblar", "derivar")]  # las de poblar.py/derivar.py no son ítems del acta: ni se emparejan ni quedan huérfanas
    por_ref, por_h, par = {ref(x): x for x in ents}, {}, {}
    for x in ents:
        por_h.setdefault((x["mid"], x["h"]), []).append(x)
    for _, it in its:  # 1) mismo id legado y mismo texto
        if (x := por_ref.get(it["id"])) and x["h"] == it["h"]:
            par[it["id"]] = x
    usados = {x["id"] for x in par.values()}
    for _, it in its:  # 2) mismo texto en la reunión (acta rehecha, o un ítem anterior quitado: las posiciones se corren)
        if it["id"] not in par and (x := next((x for x in por_h.get((it["mid"], it["h"]), []) if x["id"] not in usados), None)):
            par[it["id"]] = x
            usados.add(x["id"])
    for _, it in its:  # 3) misma posición con el texto retocado, si nadie más la reclamó
        if it["id"] not in par and (x := por_ref.get(it["id"])) and x["id"] not in usados:
            par[it["id"]] = x
            usados.add(x["id"])
    ids_it = {it["id"] for _, it in its}
    for x in ents:  # (ver, ruta) que pasa a otra entidad (ítems corridos o reordenados): se aparta antes, por UNIQUE(proyecto_id, mid, ver, ruta)
        if (r := ref(x)) in ids_it and par.get(r) is not x:
            escribe()
            x["ruta"] = f"{x['ruta']}~{x['id']}"  # el emparejado recibe la suya abajo; el huérfano se queda con esta
            _poner(db, x["id"], {"ruta": x["ruta"]})
    ext = p["extra"]
    leg, sl = ext.get("estados_legado") or {}, ext.get("sugeridos_legado") or {}
    mig = (db.execute("SELECT v FROM meta WHERE k='migrado_t'").fetchone() or [0])[0] or 0
    leg_h = {(v.get("mid"), v.get("h")): v for v in leg.values() if isinstance(v, dict) and v.get("h")}
    for d, it in its:
        nuevo = _del_doc(it)
        if x := par.get(it["id"]):  # ya existe: sigue al documento (salvo el contenido editado a mano)
            campos = {**x["campos"], **({} if x["editado"] else {"seccion": it["tipo"], "plazo": it["plazo"]})}
            campos.pop("huerfano", None)
            nuevo = {k: v for k, v in {**nuevo, "campos": campos}.items() if not (x["editado"] and k in CONTENIDO)}
            if cambios := {k: v for k, v in nuevo.items() if x[k] != v}:
                escribe()
                _poner(db, x["id"], cambios)
                db.execute("UPDATE cita SET ver=?, t=?, texto=? WHERE entidad_id=? AND mid=?", (it["ver"], it["t"], it["cita"], x["id"], it["mid"]))
            continue
        if it["tipo_ent"] == "decision" and P.aplazada(it["texto"], it["cita"]):
            continue  # aplazada: no es decisión (una firme que cita la próxima reunión sí lo es) (solo al crear; las existentes no se tocan)
        escribe()
        s = leg.get(it["id"]) or leg_h.get((it["mid"], it["h"])) or {}
        viejo = d["mtime"] <= mig
        par[it["id"]] = crear(c, it["tipo_ent"], False, db, cita={"mid": it["mid"], "ver": it["ver"], "t": it["t"], "texto": it["cita"]}, **nuevo, mid=it["mid"],
                              campos={"seccion": it["tipo"], "plazo": it["plazo"], **({"nota": s["nota"]} if s.get("nota") else {})},
                              **({"estado": s["estado"]} if s.get("estado") else {}), sugerencia=sl.get(it["id"]),
                              revision="aprobado" if viejo else "propuesto", origen="migrado" if viejo else "reunion")
    for x in ents:
        if x["id"] not in usados and not x["campos"].get("huerfano"):
            escribe()
            _poner(db, x["id"], {"campos": {**x["campos"], "huerfano": True}})
    return par


# ---------- el expediente de carpetas.py (dict) sobre el registro ----------
def _vacio():
    """Sin registro.db ni expedientes.json no hay nada que leer: las lecturas no crean el fichero."""
    return not (P.WORK / "registro.db").is_file() and not _json().is_file()


def expediente(c, db=None):
    """Lo guardado del expediente de c como dict (claves de carpetas.DEF; solo las que hay): {} si la carpeta no tiene proyecto."""
    if db is None and _vacio():
        return {}
    with _db(db) as db:
        p = proyecto(c, False, db)
        if not p:
            return {}
        ents = [_ent(r) for r in db.execute("SELECT * FROM entidad WHERE proyecto_id=? ORDER BY creado, rowid", (p["id"],))]
    ext = p["extra"]
    e = {**{k: p[k] for k in PCOLS if p[k] is not None}, **{k: v for k, v in ext.items() if k not in LEGADO}}
    e["manuales"] = [{"id": x["id"], "texto": x["titulo"], "resp": x["dueno"], "plazo": x["campos"].get("plazo", ""), "creado": x["creado"]}
                     for x in ents if x["origen"] == "manual" and x["revision"] not in OCULTA]
    e["estados"] = {**(ext.get("estados_legado") or {}), **{ref(x): {"estado": x["estado"], "t": x["modificado"], "mid": x["mid"] or "", "h": x["h"] or "",
                                                                     **({"nota": x["campos"]["nota"]} if x["campos"].get("nota") else {})} for x in ents if x["estado"]}}
    e["sugeridos"] = {k: v for k, v in {**(ext.get("sugeridos_legado") or {}), **{ref(x): x["sugerencia"] for x in ents}}.items() if v}
    return e


def guardar_expediente(c, antes, e):
    """Escribe lo que cambió entre `antes` y `e` (dicts de expediente) en una transacción; los cambios de entidades, en un lote del historial."""
    lote = uuid.uuid4().hex[:10]
    with _db(escribe=True) as db:
        p = proyecto(c, db=db)
        ext = {**p["extra"], **{k: v for k, v in e.items() if k not in PCOLS + ("manuales", "estados", "sugeridos")}}
        ya = {m["id"] for m in antes["manuales"]}
        for m in e["manuales"]:
            if m["id"] not in ya:
                crear(c, "tarea", lote, db, id=m["id"], titulo=m["texto"], dueno=m["resp"], campos={"plazo": m["plazo"]}, creado=m["creado"], origen="manual", revision="aprobado")
        for i in ya - {m["id"] for m in e["manuales"]}:
            borrar(i, lote, db)
        ents = {ref(x): x for x in map(_ent, db.execute("SELECT * FROM entidad WHERE proyecto_id=?", (p["id"],)))}
        for k, kl in (("estados", "estados_legado"), ("sugeridos", "sugeridos_legado")):
            leg = ext[kl] = dict(ext.get(kl) or {})
            for pid in {*antes[k], *e[k]}:
                v = e[k].get(pid)
                if v == antes[k].get(pid):
                    continue
                x = ents.get(pid)
                if not x:  # aún no es entidad: se aplicará al crearla (sincronizar)
                    leg.__setitem__(pid, v) if v is not None else leg.pop(pid, None)
                    continue
                leg.pop(pid, None)
                if k == "sugeridos":
                    editar(x["id"], {"sugerencia": v}, lote, db)
                else:
                    v = v or {}
                    nota = {"campos": {"nota": v.get("nota", "")}} if v.get("nota") or x["campos"].get("nota") else {}
                    editar(x["id"], {"estado": v.get("estado", "abierto"), **nota}, lote, db)
        db.execute("UPDATE proyecto SET tipo=?, datos=?, ajustes=?, glosario=?, extra=? WHERE id=?", (*(_j(e.get(k)) if k != "tipo" else e.get(k) for k in PCOLS), _j(ext), p["id"]))


# ---------- migración desde expedientes.json ----------
def _cuentas(es):
    """es: [(expediente o extra, manuales, glosario)] -> recuentos para comparar antes/después."""
    n = lambda k: sum(len(x.get(k) or []) for x, _, _ in es)
    return {"carpetas": len(es), "manuales": sum(m for _, m, _ in es), "estados": n("estados"), "sugeridos": n("sugeridos"), "notas": n("notas"),
            "eventos": n("eventos"), "glosario": sum(g for _, _, g in es)}


def migrar_json(db):
    """expedientes.json -> proyecto + entidades, dentro de la transacción de quien llama (_preparar). -> {antes, despues} (recuentos).
    Manuales -> tareas manual/aprobado con su id, estado y sugerencia; estados y sugeridos de documentos -> extra.*_legado (los aplica
    sincronizar() al crear cada entidad: por id y luego por (mid, h)). meta.migrado_t = ahora (D3, para todas las carpetas).
    JSON ilegible o recuentos que no cuadran -> ValueError (quien llama deshace la transacción y deja el fichero). Lo mal formado (manual que no
    es objeto, sin id o con id repetido, texto nulo, estados que no son objeto…) se corrige u omite y se anota en rep["omitidos"]."""
    try:
        todo = json.loads(_json().read_text(encoding="utf-8"))
    except (OSError, ValueError) as ex:
        raise ValueError(f"expedientes.json ilegible: {ex}") from ex
    if not isinstance(todo, dict):
        raise ValueError("expedientes.json no es un objeto {carpeta: expediente}")
    t, om, nuevas, menos = time.time(), [], {}, 0
    ids = {r[0] for r in db.execute("SELECT id FROM entidad")}
    db.execute("INSERT OR REPLACE INTO meta(k, v) VALUES ('migrado_t', ?)", (t,))
    for c, e in todo.items():
        if not isinstance(e, dict):
            om.append({"carpeta": c, "motivo": "el expediente no es un objeto"})
            continue
        for k, tipo in (("estados", dict), ("sugeridos", dict), ("manuales", list)):
            if e.get(k) is not None and not isinstance(e[k], tipo):
                om.append({"carpeta": c, "motivo": f"«{k}» con formato no válido"})
        est, sug, mans = (e[k] if isinstance(e.get(k), tipo) else tipo() for k, tipo in (("estados", dict), ("sugeridos", dict), ("manuales", list)))
        e = {**e, "estados": est, "sugeridos": sug, "manuales": mans}
        resto = {k: v for k, v in e.items() if k not in PCOLS + ("manuales", "estados", "sugeridos")}
        ext = {**resto, "estados_legado": est, "sugeridos_legado": sug}
        if o := proyecto(c, False, db):  # ya tenía registro (migración reintentada tras usar la app): solo se completa lo que falta
            db.execute("UPDATE proyecto SET tipo=?, datos=?, ajustes=?, glosario=?, extra=? WHERE id=?",
                       (o["tipo"] or e.get("tipo"), *(_j(o[k] or e.get(k)) for k in PCOLS[1:]), _j({**ext, **{k: v for k, v in o["extra"].items() if v}}), o["id"]))
            om.append({"carpeta": c, "motivo": "ya tenía registro: solo se completó lo que faltaba (fuera de los recuentos)"})
        else:
            db.execute("INSERT INTO proyecto(carpeta, tipo, datos, ajustes, glosario, extra) VALUES (?,?,?,?,?,?)", (c, e.get("tipo"), *(_j(e.get(k)) for k in PCOLS[1:]), _j(ext)))
            nuevas[c] = e
        for m in mans:
            if not isinstance(m, dict):
                om.append({"carpeta": c, "manual": m, "motivo": "no es un objeto"})
                menos += c in nuevas
                continue
            i = m.get("id") if isinstance(m.get("id"), str) and m.get("id") else ""
            nid = i if i and i not in ids else f"m:{uuid.uuid4().hex[:8]}"
            if nid != i:
                om.append({"carpeta": c, "manual": i, "id": nid, "motivo": "id repetido: id nuevo" if i else "sin id: id nuevo"})
            ids.add(nid)
            s = est.get(i) if isinstance(est.get(i), dict) else {}
            crear(c, "tarea", False, db, id=nid, titulo=str(m.get("texto") or ""), dueno=str(m.get("resp") or ""), origen="manual", revision="aprobado",
                  creado=m["creado"] if isinstance(m.get("creado"), (int, float)) else t, estado=str(s.get("estado") or "abierto"), sugerencia=sug.get(i),
                  campos={"plazo": str(m.get("plazo") or ""), **({"nota": s["nota"]} if s.get("nota") else {})})
    ps = {c: proyecto(c, False, db) for c in nuevas}
    man = {c: db.execute("SELECT COUNT(*) FROM entidad WHERE proyecto_id=? AND origen='manual'", (p["id"],)).fetchone()[0] for c, p in ps.items()}
    antes = _cuentas([(e, len(e["manuales"]), len(e.get("glosario") or [])) for e in nuevas.values()])
    despues = _cuentas([({**p["extra"], "estados": p["extra"].get("estados_legado"), "sugeridos": p["extra"].get("sugeridos_legado")}, man[c], len(p["glosario"] or []))
                        for c, p in ps.items()])
    if despues != {**antes, "manuales": antes["manuales"] - menos}:
        raise ValueError(f"los recuentos no cuadran: antes={antes} despues={despues} omitidos={om}")
    return {"antes": antes, "despues": despues, "omitidos": om}


# ---------- API genérica (/api/reg): serialización, relaciones, pertenencia al proyecto ----------
EDITABLES = {"titulo", "detalle", "estado", "dueno", "prioridad", "fecha_limite", "fecha_cierre", "fecha_alta", "campos"}  # whitelist de PATCH / revisar.cambios
REL_TIPOS = ("deriva_de", "sustituye", "bloquea", "mitiga", "afecta", "responde", "solicita", "fusion")


def completas(xs):
    """Entidades -> JSON del contrato: + huerfano, editado bool, citas y relaciones (las de cada una, como a o b)."""
    if not xs:
        return []
    ids = [x["id"] for x in xs]
    q = ",".join("?" * len(ids))
    with _db() as db:
        ci, re_ = {}, {}
        for r in db.execute(f"SELECT entidad_id, mid, ver, t, texto, verificada FROM cita WHERE entidad_id IN ({q}) ORDER BY id", ids):
            ci.setdefault(r[0], []).append({"mid": r[1], "ver": r[2], "t": r[3], "texto": r[4], "verificada": bool(r[5])})
        for r in db.execute(f"SELECT a, b, tipo, propuesta FROM relacion WHERE (a IN ({q}) OR b IN ({q})) AND propuesta>=0", ids + ids):  # propuesta=-1: propuesta rechazada, no se muestra
            rel = {"a": r[0], "b": r[1], "tipo": r[2], "propuesta": bool(r[3])}
            for k in {r[0], r[1]}:
                re_.setdefault(k, []).append(rel)
        fu = fusionadas(ids, db)
        dest = {x["fusionado_en"] for x in xs if x["fusionado_en"]}
        cod = {r[0]: r[1] for r in db.execute(f"SELECT id, codigo FROM entidad WHERE id IN ({','.join('?' * len(dest))})", list(dest))} if dest else {}
    return [{k: x[k] for k in ECOLS if k not in ("proyecto_id", "orden")} | {"editado": bool(x["editado"]), "huerfano": bool(x["campos"].get("huerfano")),
            "citas": ci.get(x["id"], []), "relaciones": re_.get(x["id"], []), "fusionadas": fu.get(x["id"], []),
            "fusionado_en_codigo": cod.get(x["fusionado_en"])} for x in xs]


def de(c, eid):
    """Entidad eid si es del proyecto de c; KeyError si no."""
    with _db() as db:
        x = _uno(db, eid)
        p = proyecto(c, False, db)
        if not p or p["id"] != x["proyecto_id"]:
            raise KeyError("Esa entidad no existe")
        return x


def relacionar(c, a, b, tipo, propuesta=False):
    if tipo not in REL_TIPOS or a == b:
        raise ValueError("Relación no válida")
    de(c, a), de(c, b)
    with _db(escribe=True) as db:
        db.execute("INSERT INTO relacion(a, b, tipo, propuesta) VALUES (?,?,?,?) ON CONFLICT(a, b, tipo) DO UPDATE SET propuesta=excluded.propuesta", (a, b, tipo, int(bool(propuesta))))


def sustituir(c, a, b):
    """a sustituye a b (decisiones): relación firme + b pasa a «sustituida», todo en UN lote (un solo deshacer; la relación se quita al deshacer)."""
    if a == b:
        raise ValueError("Relación no válida")
    de(c, a), de(c, b)
    lote = uuid.uuid4().hex[:10]
    with _db(escribe=True) as db:
        if db.execute("INSERT INTO relacion(a, b, tipo, propuesta) VALUES (?,?,'sustituye',0) ON CONFLICT(a, b, tipo) DO NOTHING", (a, b)).rowcount:
            _hist(db, _uno(db, a)["proyecto_id"], a, "fusionar", None, {"citas": [], "rel": [[a, b, "sustituye"]]}, lote)  # deshacer() borra despues["rel"]
        db.execute("UPDATE relacion SET propuesta=0 WHERE a=? AND b=? AND tipo='sustituye'", (a, b))
        editar(b, {"estado": "sustituida"}, lote, db)


def desrelacionar(c, a, b, tipo):
    """Quita la relación firme; si era una propuesta (o no hay fila), anota el rechazo (propuesta=-1) para que no reaparezca."""
    de(c, a), de(c, b)
    with _db(escribe=True) as db:
        if not db.execute("DELETE FROM relacion WHERE a=? AND b=? AND tipo=? AND propuesta=0", (a, b, tipo)).rowcount:
            db.execute("INSERT INTO relacion(a, b, tipo, propuesta) VALUES (?,?,?,-1) ON CONFLICT(a, b, tipo) DO UPDATE SET propuesta=-1", (a, b, tipo))


def rechazadas(c, tipo="sustituye"):
    """{(a, b)} de propuestas de relación rechazadas por el usuario en el proyecto de c."""
    with _db() as db:
        p = proyecto(c, False, db)
        return p and {(r[0], r[1]) for r in db.execute("SELECT r.a, r.b FROM relacion r JOIN entidad e ON e.id=r.a WHERE r.propuesta=-1 AND r.tipo=? AND e.proyecto_id=?", (tipo, p["id"]))} or set()


def ultimo_lote_ids(c):
    """ids de las entidades tocadas por el último lote del usuario (el que revertirá deshacer(); para devolverlas tras deshacer)."""
    with _db() as db:
        r = _ultimo(db, c)
        return r and [h[0] for h in db.execute("SELECT DISTINCT entidad_id FROM historial WHERE proyecto_id=? AND lote=? AND entidad_id IS NOT NULL", r)] or []


def ultimo_lote(c):
    """Id del último lote del usuario en el historial del proyecto (None si no hay; los auto no cuentan)."""
    with _db() as db:
        r = _ultimo(db, c)
        return r and r[1]
