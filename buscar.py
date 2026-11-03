"""Búsqueda global sobre todos los documentos (work/buscar.db, FTS5 de sqlite3 de serie, sin acentos ni mayúsculas): fragmentos de
transcripción o texto (con su página/sección), OCR de pantallas del vídeo y de imágenes, descripciones de imágenes; y las entidades del
registro (tareas, decisiones, requisitos, riesgos…). El índice se pone al día solo: cada documento guarda una firma (su transcripción
más reciente y sus capturas); al buscar (y al acabar un trabajo) se reindexa lo que cambió y se quita lo que ya no existe."""
import html
import json
import re
import sqlite3
import threading
import unicodedata

import pipeline as P
import registro

LOCK = threading.Lock()
FUENTE = {"imagen": "imagen", "descripción": "descripcion", "descripción IA": "descripcion_ia"}  # loc -> tipo de fuente (el resto: texto si hay loc, voz si no)
TIPOS_FUENTE = ("voz", "texto", "pantalla", "imagen", "descripcion", "descripcion_ia")


def _con():
    db = sqlite3.connect(P.WORK / "buscar.db", timeout=15)
    db.executescript("""CREATE VIRTUAL TABLE IF NOT EXISTS frag USING fts5(text, mid UNINDEXED, tipo UNINDEXED, t UNINDEXED, loc UNINDEXED,
                          tokenize='unicode61 remove_diacritics 2');
                        CREATE TABLE IF NOT EXISTS doc(mid TEXT PRIMARY KEY, firma TEXT);""")
    return db


def fragmentos(wd, asr):
    """(tipo, t, loc, texto) de un documento: tramos de la transcripción/texto (~15 s, nunca cruzan de página) y pantallas con texto."""
    tr = json.loads((wd / f"transcript_{asr}.json").read_text())
    for s in P.merge_segs(tr["segments"]):
        loc = s.get("loc")
        yield FUENTE.get(loc, "texto" if loc else "voz"), s["s"], loc, s["text"]
    kf = next((f for f in (wd / "frames2.json", wd / "frames.json") if f.exists()), None)
    for k in P.screens(json.loads(kf.read_text())) if kf else []:
        if k["screen"] and k["text"].strip():
            yield "pantalla", k["t"], None, k["text"].replace(" | ", " · ")
    ci = wd / "capturas_ia.json"  # capturas del documento descritas con IA (vision.capturas)
    for x in json.loads(ci.read_text()).values() if ci.exists() else []:
        yield "descripcion_ia", x["t"], None, x["texto"]


def _firma(wd, asr):
    fs = [wd / f"transcript_{asr}.json", wd / "frames2.json", wd / "frames.json", wd / "capturas_ia.json"]
    return asr + ":" + ":".join(str(f.stat().st_mtime_ns) for f in fs if f.exists())


def sincronizar(ms):
    """ms: app.meetings() (la más reciente primero). Reindexa lo cambiado; borra lo que ya no está."""
    vivos = {}
    for m in ms:
        if not m.get("sin"):
            vivos.setdefault(m["id"], m["asr"])
    with LOCK, _con() as db:
        have = dict(db.execute("SELECT mid, firma FROM doc"))
        for mid in have.keys() - vivos.keys():
            db.execute("DELETE FROM frag WHERE mid=?", (mid,))
            db.execute("DELETE FROM doc WHERE mid=?", (mid,))
        for mid, asr in vivos.items():
            wd = P.WORK / mid
            try:
                f = _firma(wd, asr)
                if have.get(mid) == f:
                    continue
                rows = [(x, mid, ti, t, loc) for ti, t, loc, x in fragmentos(wd, asr)]
            except (OSError, ValueError, KeyError):  # a medio escribir o dañado: se reintenta en la siguiente búsqueda
                continue
            db.execute("DELETE FROM frag WHERE mid=?", (mid,))
            db.executemany("INSERT INTO frag(text, mid, tipo, t, loc) VALUES (?,?,?,?,?)", rows)
            db.execute("INSERT OR REPLACE INTO doc VALUES (?,?)", (mid, f))
    db.close()


def _norm(t):
    return "".join(c for c in unicodedata.normalize("NFKD", t.casefold()) if not unicodedata.combining(c))


def elementos(q, c=None, tipo="", limit=20):
    """Entidades del registro (no descartadas ni fusionadas) cuyo título + detalle contiene todas las palabras de q."""
    ws = [_norm(w) for w in re.findall(r"\w+", q)]
    if not ws:
        return []
    db = registro.conectar()
    try:
        rows = db.execute("SELECT e.id, e.tipo, e.codigo, e.titulo, e.detalle, e.estado, e.mid, p.carpeta FROM entidad e JOIN proyecto p ON p.id = e.proyecto_id "
                          "WHERE e.revision NOT IN ('descartado', 'fusionado')" + " AND p.carpeta = ?" * (c is not None) + " AND e.tipo = ?" * bool(tipo),
                          [*([c] if c is not None else []), *([tipo] if tipo else [])]).fetchall()
    finally:
        db.close()
    # ponytail: recorrido en Python (cientos-miles de entidades); FTS5 también para el registro si crece a cientos de miles
    out = []
    for r in rows:
        tit, txt = _norm(r["titulo"]), _norm(r["titulo"] + " " + r["detalle"])
        if all(w in txt for w in ws):
            out.append((-sum(w in tit for w in ws), {"tipo": r["tipo"], "id": r["id"], "codigo": r["codigo"], "texto": r["titulo"], "detalle": r["detalle"][:200],
                                                   "estado": r["estado"], "doc": r["mid"], "c": r["carpeta"]}))
    return [x for _, x in sorted(out, key=lambda x: x[0])][:limit]


def buscar(ms, q, c=None, tipo="", limit=20):
    """{fragmentos: [{doc, titulo, kind, c, sel, tipo_fuente, t, loc, snippet, score}], elementos: [...]}. c: carpeta (None = todas);
    tipo: clase de documento (video|audio|pdf|texto|imagen), de fuente (voz|texto|pantalla|imagen|descripcion) o de entidad (tarea…)."""
    sincronizar(ms)
    ws = re.findall(r"\w+", q)
    info = {}
    for m in ms:
        info.setdefault(m["id"], m)
    docs = [mid for mid, m in info.items() if (c is None or (m["carpeta"] or "") == c) and (not tipo or tipo in TIPOS_FUENTE or tipo == m.get("kind"))]
    frags = []
    if ws and docs and tipo not in registro.TIPOS:
        db = _con()
        try:
            rows = db.execute("SELECT mid, tipo, t, loc, snippet(frag, 0, char(2), char(3), '…', 24), bm25(frag) FROM frag WHERE frag MATCH ? "
                              "AND mid IN (SELECT value FROM json_each(?))" + " AND tipo = ?" * (tipo in TIPOS_FUENTE) + " ORDER BY bm25(frag) LIMIT ?",
                              [" ".join('"' + w.replace('"', "") + '"*' for w in ws), json.dumps(docs), *([tipo] if tipo in TIPOS_FUENTE else []), limit]).fetchall()
        finally:
            db.close()
        for mid, ti, t, loc, sn, sc in rows:
            m = info[mid]
            frags.append({"doc": mid, "titulo": m["label"], "kind": m.get("kind"), "c": m["carpeta"], "sel": m["sel"], "tipo_fuente": ti,
                          **({"loc": loc} if loc else {"t": t}), "snippet": html.escape(sn).replace("\x02", "<mark>").replace("\x03", "</mark>"), "score": round(-sc, 3)})
    els = elementos(q, c, tipo if tipo in registro.TIPOS else "", limit) if not tipo or tipo in registro.TIPOS else []
    return {"fragmentos": frags, "elementos": els}
