"""F3b «IA primero»: pasada transversal `poblar` sobre las reuniones de un proyecto, independiente de la plantilla del documento.
Extrae requisitos, decisiones, interesados (nombre, rol y organización: nada de contacto, D5), riesgos y preguntas abiertas, cada uno
con su cita literal verificada en la transcripción, y los deja en el registro como entidad(origen='reunion', revision='propuesto').

Invariantes:
- Nube/CLI: una llamada al LLM por bloque de transcripción (pipeline.chunk_eq, ~10k caracteres) con todas las vistas pedidas en un solo esquema.
  Modelo local (local=True): una llamada por vista y bloque, con el esquema acotado a esa vista.
- Sin cita encontrada en la transcripción (pipeline.find_quote >= CITA_MIN) o con cifras que no se dicen (rag.bad_nums): fuera.
- Las entidades llevan campos.fuente='poblar' y ruta 'poblar.<tipo>.<h>' (h de la cita): registro.sincronizar no las empareja con
  ítems del acta ni las marca huérfanas.
- Nunca pisa: lo que se parece a una entidad existente del mismo tipo (misma (mid, h), cita en el mismo minuto o texto parecido) no se
  crea; si esa entidad está viva y no tiene cita de esta reunión, recibe la cita. Lo descartado o fusionado no reaparece ni recibe citas.
  Así «Regenerar con IA» solo añade lo nuevo y respeta lo editado/aprobado.
"""
import json
import re
import time
import uuid

import carpetas
import pipeline as P
import rag
import registro

CITA_MIN = 0.75  # fracción de pares de palabras de la cita que tienen que estar seguidos en la transcripción
CERCA = (30, 0.6)  # misma reunión, citas a <= 30 s y coseno >= 0.6: lo mismo dicho con otras palabras (p. ej. la decisión del acta)
SIM_DUP = 0.85     # coseno (carpetas.sim) a partir del cual el texto es el de una entidad existente, venga de donde venga
N_MAX = 8        # elementos como mucho por vista y bloque
VACIO = re.compile(r"^\s*(—|-|–|n/?a|ninguno|ninguna|no se dice|sin (datos|definir)|desconocid[oa])?\s*\.?\s*$", re.I)
CONTACTO = re.compile(r"\S+@\S+\.\w+|\+?\d[\d .\-]{7,}\d")  # D5: correos y teléfonos fuera de interesados
# vista -> (tipo de entidad, descripción para el prompt, campos propios {nombre: tope de caracteres})
VISTAS = {
    "requisitos": ("requisito", "necesidades o condiciones que el sistema, producto o servicio DEBE cumplir según lo dicho («la aplicación debe…», "
                   "«tiene que permitir…», «no puede…», «en menos de N segundos»). NO son requisitos: tareas o encargos de personas (quién hará "
                   "qué y cuándo), decisiones de calendario o de lanzamiento, problemas actuales sin una condición exigida, ni opiniones. tipo_req: "
                   "funcional, no funcional o restricción; prioridad: solo si se dice («imprescindible», «deseable»…); solicitante: quien lo pide, "
                   "solo si se nombra.", {"tipo_req": 20, "prioridad": 30, "solicitante": 60}),
    "decisiones": ("decision", "solo acuerdos firmes tomados HOY en esta reunión sobre el proyecto («decidimos…», «se aprueba…», «queda "
                   "acordado…»). NO son decisiones: propuestas o ideas sin aprobar («se propuso…», «deberíamos…»); lo que se deja pendiente, se "
                   "aplaza o se verá en otra reunión («lo dejamos pendiente de decidir» es una pregunta abierta, no una decisión); la fecha u "
                   "organización de la próxima reunión; lo leído de un acta o informe anterior. Una decisión puede encargar algo a alguien («decidimos "
                   "que Ana revise…»): sí es decisión; un encargo o compromiso que nadie decide («me encargo yo de…») no lo es. decisor: quien "
                   "decide, solo si se dice.", {"decisor": 60}),
    "interesados": ("interesado", "personas u organizaciones con interés o influencia en el proyecto (cliente, patrocinador, usuarios, "
                    "proveedores, responsables) de las que se dice su cargo o su organización. Aquí texto = el nombre tal como se dice (persona "
                    "u organización); rol: cargo o papel que se dice; organizacion: empresa o área que se dice. Solo nombre, rol y organización: "
                    "nunca teléfonos, correos ni otros datos de contacto o personales. Quien solo participa en la reunión sin que se diga su rol "
                    "u organización no es un interesado.", {"rol": 60, "organizacion": 60}),
    "riesgos": ("riesgo", "algo que PUEDE ocurrir en el futuro y perjudicar al proyecto, dicho como riesgo, amenaza o condición («si X se "
                "retrasa, Y no podrá…», «hay un riesgo…»). Un problema que ya existe hoy no es un riesgo. probabilidad e impacto: solo si se "
                "dicen con palabras («alta», «bajo»…), nunca los estimes; responsable: quien lo vigila, solo si se dice.",
                {"probabilidad": 20, "impacto": 20, "responsable": 60}),
    "preguntas": ("pregunta", "cuestiones que quedan ABIERTAS en la reunión: preguntas sin respuesta y lo que se deja pendiente de decidir o "
                  "de aclarar («¿quién…?», «eso lo dejamos pendiente»). texto = la cuestión formulada como pregunta. No incluyas las que se "
                  "responden en la propia reunión. dirigida_a: a quién se dirige, solo si se dice.", {"dirigida_a": 60}),
}
CABECERA = """Extraes los elementos de un proyecto de un fragmento de transcripción automática (con errores) de una reunión, con marcas \
[mm:ss] y, a veces, «Nombre:» de quien habla. Los revisará una persona: solo lo que se DICE en el fragmento, sin deducir ni completar; no \
inventes nombres, cifras, fechas, prioridades ni responsables. Ante la duda, déjalo fuera: mejor una lista vacía que un elemento dudoso. \
Cada elemento sale una sola vez, en la lista que le corresponde.
Cada elemento: cita = copia LITERAL de la transcripción (de 4 a 15 palabras seguidas, sin la marca [mm:ss] ni el nombre de quien habla) \
que lo prueba; texto = una frase autocontenida de máx. 25 palabras; los demás campos, solo si se dicen expresamente; si no, "—".
"""
FINAL = "Listas vacías si no hay. Escribe en {lang}."


def prompt(vistas, glosario=()):
    """(sistema, esquema) de una pasada con las vistas pedidas. glosario: términos de la carpeta (como en pipeline.prompts)."""
    sis = CABECERA + "".join(f"{v}: {VISTAS[v][1]}\n" for v in vistas) + FINAL
    if glosario:
        sis += "\nTérminos de este proyecto (escríbelos exactamente así): " + "; ".join(glosario).replace("{", "(").replace("}", ")") + "."
    item = lambda v: P.arr(P.obj(cita=P.S(160), texto=P.S(200), **{k: P.S(n) for k, n in VISTAS[v][2].items()}), N_MAX)
    return sis, P.obj(**{v: item(v) for v in vistas})


def _limpio(v):
    v = str(v or "").strip()
    return "" if VACIO.match(v) else v


def comprobar(r, segs, texto, vistas):
    """Respuesta del modelo para un bloque -> [(vista, elemento con t)] verificados: cita literal en el bloque, sin cifras que no se dicen,
    sin datos de contacto; decisiones sin los falsos positivos conocidos. Lo descartado se imprime (como en pipeline)."""
    sw, out = [P.words(s["text"]) for s in segs], []
    for v in vistas:
        for it in r.get(v) or []:
            it = {k: _limpio(x) for k, x in it.items()}
            cita = re.sub(r"^\s*(\[[\d:]+\]\s*)?([A-ZÁÉÍÓÚÑ][\w .]{0,30}:\s+)?", "", it.get("cita", "")).strip(" «»\"'")
            f, t = P.find_quote(cita, segs, sw) if len(P.words(cita)) >= 3 else (0, 0)
            nums = rag.bad_nums(" ".join(x for k, x in it.items() if k != "cita"), texto)
            por = ("sin cita en la transcripción" if f < CITA_MIN or not it.get("texto") else f"cifras que no se dicen: {nums}" if nums else
                   "no es una decisión" if v == "decisiones" and P.no_decision(it["texto"], cita) else "")
            if por:
                print(f"  poblar: descartado ({por}): {v} {it.get('texto')}", flush=True)
                continue
            if v == "interesados" and not it.get("rol"):  # solo con rol dicho (prompt y aquí)
                print(f"  poblar: descartado (interesado sin rol): {it.get('texto')}", flush=True)
                continue
            if v == "interesados":
                it = {k: CONTACTO.sub("", x).strip() for k, x in it.items()}
            out.append((v, {**it, "cita": cita, "t": t}))
    return out


def _entidad(v, it, d):
    """Elemento verificado -> columnas de registro.crear."""
    tipo, ex = VISTAS[v][0], {k: it[k] for k in VISTAS[v][2] if it.get(k)}
    h = carpetas._h(d["mid"], it["cita"])
    f = {"titulo": it["texto"], "mid": d["mid"], "ver": d["ver"], "ruta": f"poblar.{tipo}.{h}", "h": h, "origen": "reunion", "revision": "propuesto",
         "fecha_alta": d["fecha"], "campos": {"fuente": "poblar", "seccion": v.capitalize(), **ex}}
    if tipo == "interesado":
        f["detalle"] = ex.get("rol", "")
    if tipo == "riesgo" and ex.get("responsable"):
        f["dueno"] = ex["responsable"]
    if tipo == "requisito" and ex.get("prioridad"):
        f["prioridad"] = ex["prioridad"]
    return tipo, f


def _nombre(t):
    return set(P.words(t))


def _igual(tipo, f, t, q, x, cx, s):
    """¿La entidad existente x (con sus citas cx = [(mid, t, texto)]; s = coseno de los títulos) es lo mismo que el elemento nuevo f (cita q
    en el segundo t)? Misma cita en la misma reunión = lo mismo, aunque se haya editado el título."""
    if x["mid"] == f["mid"] and x["h"] == f["h"] or any(m == f["mid"] and P.words(tx or "") == P.words(q) for m, _, tx in cx):
        return True
    if tipo == "interesado":  # nombres: uno contiene al otro («Elena» / «Elena Ruiz»)
        a, b = _nombre(x["titulo"]), _nombre(f["titulo"])
        return bool(a and b) and (a <= b or b <= a)
    # ponytail: umbrales fijos medidos en el fixture; una pasada de fusión propuesta (relación «fusion») si se quedan cortos
    return s >= SIM_DUP or s >= CERCA[1] and any(m == f["mid"] and abs((tt or 0) - t) <= CERCA[0] for m, tt, _ in cx)


def guardar(c, d, items, lote):
    """Elementos verificados de un documento -> registro. -> {creadas: {tipo: n}, citas: n, omitidas: n} (omitidas = ya estaban
    descartadas/fusionadas). Compara con las entidades del proyecto del mismo tipo y con las creadas en esta misma pasada."""
    res = {"creadas": {}, "citas": 0, "omitidas": 0}
    if ts := [it["texto"] for v, it in items if VISTAS[v][0] != "interesado"]:  # embeddings ANTES del cerrojo de escritura: dentro, carpetas.sim tira de su caché
        with registro._db() as db:
            q = registro.proyecto(c, False, db)
            ya = [r[0] for r in db.execute("SELECT titulo FROM entidad WHERE proyecto_id=?", (q["id"],))] if q else []
        carpetas.sim(ts, ya + ts)  # ponytail: un título editado por otro entre medias se embebe dentro del cerrojo (uno, raro)
    with registro._db(escribe=True) as db:
        p = registro.proyecto(c, db=db)["id"]
        for v, it in items:
            tipo, f = _entidad(v, it, d)
            pool = [registro._ent(r) for r in db.execute("SELECT * FROM entidad WHERE proyecto_id=? AND tipo=?", (p, tipo))]
            cx = {x["id"]: [tuple(r) for r in db.execute("SELECT mid, t, texto FROM cita WHERE entidad_id=?", (x["id"],))] for x in pool}
            s = carpetas.sim([f["titulo"]], [y["titulo"] for y in pool])[0] if pool and tipo != "interesado" else [0] * len(pool)
            x = max((y for y, sy in zip(pool, s) if _igual(tipo, f, it["t"], it["cita"], y, cx[y["id"]], sy)), key=lambda y: (y["mid"] == d["mid"], s[pool.index(y)]), default=None)
            cita = {"mid": d["mid"], "ver": d["ver"], "t": it["t"], "texto": it["cita"], "verificada": True}
            if x is None:
                x = registro.crear(c, tipo, lote, db, cita=cita, auto=True, **f)
                if tipo == "requisito":
                    res.setdefault("ids", []).append(x["id"])
                res["creadas"][tipo] = res["creadas"].get(tipo, 0) + 1
            elif x["revision"] in registro.OCULTA:
                res["omitidas"] += 1
            elif not any(m == d["mid"] for m, _, _ in cx[x["id"]]):  # lo mismo dicho en otra reunión: una cita más, sin tocar su contenido
                registro.citar(x["id"], cita, db)
                res["citas"] += 1
    return res


def poblar(c, ms, chat_ctx, mids=None, vistas=None, glosario=(), cb=lambda f, m: None, local=False):
    """Pasada sobre los documentos de la carpeta c (ms = sus reuniones; mids: solo esas). chat_ctx() da el chat (pipeline.llama o
    nube.backend; local=True si es el modelo local: una llamada por vista). -> resumen de la pasada (también en el expediente: carpetas.leer(c)["poblar"])."""
    import nube
    vistas = [v for v in VISTAS if v in (vistas or VISTAS)]
    todos = ds = carpetas.docs(ms)
    registro.sincronizar(c, ds)  # las decisiones del acta ya son entidades: poblar no las duplica
    ds = [d for d in ds if (not mids or d["mid"] in mids) and not d["sin"] and (P.WORK / d["mid"] / f"transcript_{d['asr']}.json").is_file()]
    grupos = [[v] for v in vistas] if local else [vistas]  # ponytail: el modelo local rinde más con un esquema de una vista; la nube con todo junto
    ps = [(g, *prompt(g, glosario)) for g in grupos]
    t0, n, coste0, tok0 = time.time(), [0], nube.COSTE[0], list(nube.TOK)
    tot = {"creadas": {}, "citas": 0, "omitidas": 0, "descartadas": 0, "req_nuevos": []}
    lote = uuid.uuid4().hex[:10]  # toda la pasada, un lote auto: Ctrl+Z (registro.deshacer) no lo toca; registro.deshacer_pasada(c, info["lote"]) sí
    trabajo = []
    for d in ds:
        tr = json.loads((P.WORK / d["mid"] / f"transcript_{d['asr']}.json").read_text())
        trabajo += [(d, tr, b) for b in P.chunk_eq(tr["segments"])]
    if trabajo:
        cb(0.05, "Arrancando modelo de lenguaje…")
        with chat_ctx() as chat:
            total = len(trabajo) * len(ps)
            for i, (d, tr, segs) in enumerate(trabajo):
                texto = P.map_input(segs, [])
                for j, (vs, sis, esq) in enumerate(ps):
                    k = i * len(ps) + j
                    cb(0.1 + 0.85 * k / total, f"Poblando el proyecto: {d['nombre']} ({k + 1}/{total})…")
                    n[0] += 1
                    r = chat(sis.format(lang=P.LANG.get(tr["language"], f"el idioma de la reunión ({tr['language']})")), texto, esq, 600 + 350 * len(vs), temperature=0.1)
                    ok = comprobar(r, segs, texto, vs)
                    tot["descartadas"] += sum(len(r.get(v) or []) for v in vs) - len(ok)
                    g = guardar(c, d, ok, lote)
                    tot["citas"] += g["citas"]
                    tot["omitidas"] += g["omitidas"]
                    tot["req_nuevos"] += g.get("ids", [])
                    for t, x in g["creadas"].items():
                        tot["creadas"][t] = tot["creadas"].get(t, 0) + x
    info = {"t": time.time(), "mids": [d["mid"] for d in ds], "vistas": vistas, **tot, "llamadas": n[0], "segundos": round(time.time() - t0, 1),
            "coste": round(nube.COSTE[0] - coste0, 4) or None, "tokens": [a - b for a, b in zip(nube.TOK, tok0)], "lote": lote}
    carpetas.editar(c, lambda e: e.update(poblar=info))
    borrador_informe(c, info, todos)
    return info


# ---------- ganchos de las fases siguientes ----------
# F5: info["req_nuevos"] (requisitos creados en la pasada); app._poblar_fn encadena con ellos el trabajo `derivar` si la pasada es automática.
def borrador_informe(c, info, docs=()):
    """F6: el último informe de la carpeta, si es borrador, se pone al día con lo nuevo en la MISMA versión (informe.tras_poblar no lanza).
    docs: los de la carpeta (carpetas.docs), para que los KPIs conserven títulos y series."""
    import informe
    return informe.tras_poblar(c, docs)
