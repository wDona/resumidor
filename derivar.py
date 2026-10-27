"""F5: requisitos -> historias de usuario + criterios Gherkin + preguntas abiertas. «Nada sin cita; lo derivado es propuesta».

Invariantes:
- Una llamada al LLM por requisito (nube, CLI o modelo local: el esquema ya es pequeño). Entrada: solo el requisito (título, detalle,
  tipo_req, prioridad, solicitante) y sus citas literales; nada más del proyecto.
- Lo que trae cifras (rag.bad_nums) o nombres propios que no están en el requisito ni en su cita se tira (historia entera si es en
  como/quiero/para; solo ese criterio o esa pregunta si no). «como» = el rol del interesado del proyecto que coincide con el solicitante (campos.rol; es texto fuente permitido), si no el solicitante,
  si no «usuario»; un «como» que no sale del texto -> «usuario».
- Salida: entidad(origen='derivado', revision='propuesto', campos.fuente='derivar'); historias con criterios[].propuesta=true, relación
  deriva_de (historia -> requisito) y las citas del requisito heredadas; preguntas con relación afecta (pregunta -> requisito) y las citas.
- Nunca pisa ni resucita: lo parecido (carpetas.sim >= SIM_DUP o mismas palabras) a algo ya derivado de ese requisito, en cualquier
  revisión (título actual o campos.clave = el texto con que se derivó, por si se editó), no se crea; lo existente no se toca. Toda la pasada es un lote del historial (Ctrl+Z la deshace).
"""
import re
import time
import uuid

import carpetas
import pipeline as P
import rag
import registro
from poblar import _limpio

SIM_DUP = 0.85
SISTEMA = """Derivas historias de usuario de UN requisito de un proyecto; las revisará una persona. Usa SOLO lo que dicen el requisito y \
sus citas literales de la reunión: nada de conocimiento externo ni de lo «habitual» en estos sistemas.
historias (1 a 3; una sola si el requisito pide una sola cosa): como = quien lo pide o lo usa: el rol del solicitante si se indica «rol del solicitante»; si no el solicitante si se indica; si no, un \
rol que aparezca en el texto (cliente, administrador…); si no, «usuario». quiero = lo que pide el requisito, con sus palabras. para = \
el beneficio solo si se dice; si no, «—».
criterios (1 a 4 por historia): escenarios de aceptación Gherkin. escenario = nombre corto; dado, cuando, entonces = solo la frase, \
sin las palabras Dado/Cuando/Entonces. Solo condiciones que dice el requisito; cada escenario distinto (no repitas el mismo con otras \
palabras: si el requisito solo da para uno, uno).
Prohibido añadir cifras, plazos, límites, nombres de personas, productos, formatos o tecnologías que no estén en el requisito o la cita: \
si hace falta un dato que no se dice, escribe una pregunta en vez de inventarlo.
preguntas (0 a 4): lo que el requisito NO dice y hace falta para implementarlo (límites, casos de error, quién, cuánto, formato…), \
como pregunta; solo las que bloquean la implementación, sin repetir lo que ya responde el requisito.
Escribe en {lang}."""
CRIT = P.obj(escenario=P.S(100), dado=P.S(160), cuando=P.S(160), entonces=P.S(160))
ESQUEMA = P.obj(historias=P.arr(P.obj(como=P.S(80), quiero=P.S(160), para=P.S(160), criterios=P.arr(CRIT, 4, 1)), 3, 1), preguntas=P.arr(P.S(200), 4))
GHERKIN = re.compile(r"^\s*(dado|cuando|entonces|y)\s+(que\s+)?", re.I)
PALABRA = re.compile(r"[^\W\d_]+")


def rol_de(c, nombre):
    """Rol (campos.rol) del interesado vivo del proyecto cuyo nombre es el del solicitante o lo contiene/está contenido («Elena» / «Elena Ruiz»); '' si no hay."""
    a = set(P.words(_limpio(nombre)))
    for x in registro.listar(c, "interesado") if a else ():
        b, rol = set(P.words(x["titulo"])), _limpio(x["campos"].get("rol"))
        if rol and x["revision"] not in registro.OCULTA and b and (a <= b or b <= a):
            return rol
    return ""


def prompt(req, citas, glosario=(), rol=""):
    """(sistema, usuario) de un requisito (entidad) y sus citas [texto]."""
    sis = SISTEMA
    if glosario:
        sis += "\nTérminos de este proyecto (escríbelos exactamente así): " + "; ".join(glosario).replace("{", "(").replace("}", ")") + "."
    k = req["campos"]
    meta = "; ".join(f"{n}: {v}" for n, v in (("tipo", k.get("tipo_req")), ("prioridad", req.get("prioridad") or k.get("prioridad")),
                                                ("solicitante", k.get("solicitante")), ("rol del solicitante", rol)) if _limpio(v))
    usr = f"Requisito {req['codigo']}" + (f" ({meta})" if meta else "") + f":\n{req['titulo']}\n" + (f"{req['detalle']}\n" if req.get("detalle") else "")
    return sis, usr + "Citas de la reunión:\n" + ("\n".join(f"«{t}»" for t in citas if t) or "(ninguna)")


def inventado(ts, fuente):
    """Cifras y nombres propios (mayúscula a mitad de frase) de los textos ts que no están en la fuente."""
    fw, out = set(P.words(fuente)), []
    for t in ts:
        out += rag.bad_nums(t, fuente) + [m.group() for m in PALABRA.finditer(t) if m.group()[0].isupper() and m.start()
                                          and not re.search(r"[.!?¿¡:«\"]\s*$", t[:m.start()]) and not set(P.words(m.group())) <= fw]
    return out


def comprobar(r, req, citas, rol=""):
    """Respuesta del modelo -> (historias, preguntas) limpias; lo inventado fuera (se imprime, como en poblar)."""
    k = req["campos"]
    fuente = " ".join([req["titulo"], req.get("detalle") or "", *(str(k.get(x) or "") for x in ("tipo_req", "solicitante", "prioridad")), rol, *citas])
    fw = set(P.words(fuente))
    hs, ps = [], []
    for h in r.get("historias") or []:
        h = {**{x: _limpio(h.get(x)) for x in ("como", "quiero", "para")}, "criterios": h.get("criterios") or []}
        if rol:  # el rol del interesado enlazado manda sobre lo que escriba el modelo
            h["como"] = rol
        if not h["quiero"] or (mal := inventado([h[x] for x in ("como", "quiero", "para")], fuente)):
            print(f"  derivar: historia descartada ({'sin quiero' if not h['quiero'] else f'inventa {mal}'}): {h['quiero']}", flush=True)
            continue
        if not h["como"] or not any(len(w) > 3 and w in fw for w in P.words(h["como"])):  # rol que no sale del texto
            h["como"] = "usuario"
        cs = []
        for cr in h["criterios"]:
            cr = {x: GHERKIN.sub("", _limpio(cr.get(x))) if x != "escenario" else _limpio(cr.get(x)) for x in ("escenario", "dado", "cuando", "entonces")}
            if not cr["entonces"] or (mal := inventado(cr.values(), fuente)):
                print(f"  derivar: criterio descartado ({'incompleto' if not cr['entonces'] else f'inventa {mal}'}): {cr['escenario']}", flush=True)
                continue
            cs.append({**cr, "escenario": cr["escenario"][:1].upper() + cr["escenario"][1:], "propuesta": True})
        hs.append({**h, "criterios": cs})
    for p in r.get("preguntas") or []:
        p = _limpio(p)
        if p and not (mal := inventado([p], fuente)):
            ps.append(p)
        elif p:
            print(f"  derivar: pregunta descartada (inventa {mal}): {p}", flush=True)
    return hs, ps


def _norm(t):
    return " ".join(P.words(t))


def _parecido(t, ya):
    """¿t es lo mismo que alguno de los textos ya derivados?"""
    if not ya:
        return False
    return _norm(t) in map(_norm, ya) or carpetas.sim([t], ya)[0].max() >= SIM_DUP


def titulo_hu(h):
    return f"Como {h['como']}, quiero {h['quiero']}"[:300]


def guardar(c, req, hs, ps, lote):
    """Historias y preguntas verificadas de un requisito -> registro. -> {creadas: {tipo: n}, omitidas: n}."""
    res = {"creadas": {}, "omitidas": 0}
    nuevos = [("historia", titulo_hu(h), {"como": h["como"], "quiero": h["quiero"], "para": h["para"], "epica": req["codigo"] or req["campos"].get("tipo_req", ""),
                                           "puntos": "", "criterios": h["criterios"]}) for h in hs] +              [("pregunta", p, {"dirigida_a": "", "fuente_req": req["codigo"]}) for p in ps]

    def _ya(db):
        return {t: [y for x in map(registro._ent, db.execute(
            "SELECT e.* FROM entidad e JOIN relacion r ON r.a=e.id WHERE r.b=? AND r.tipo=? AND e.tipo=?", (req["id"], rel, t))) for y in {x["titulo"], x["campos"].get("clave") or x["titulo"]}]
            for t, rel in (("historia", "deriva_de"), ("pregunta", "afecta"))}  # en cualquier revisión: lo descartado no reaparece
    with registro._db() as db:  # embeddings ANTES del cerrojo de escritura: dentro, carpetas.sim tira de su caché
        ya0 = _ya(db)
    for t in ya0:
        if tt := [x[1] for x in nuevos if x[0] == t]:
            carpetas.sim(tt, ya0[t] + tt)
    with registro._db(escribe=True) as db:
        cis = [dict(x) for x in db.execute("SELECT mid, ver, t, texto, verificada FROM cita WHERE entidad_id=? ORDER BY id", (req["id"],))]
        ya = _ya(db)
        for tipo, tit, campos in nuevos:
            if _parecido(tit, ya[tipo]):
                res["omitidas"] += 1
                continue
            ya[tipo].append(tit)
            x = registro.crear(c, tipo, lote, db, auto=True, titulo=tit, origen="derivado", revision="propuesto", estado="backlog" if tipo == "historia" else "abierto",
                               campos={**campos, "fuente": "derivar", "clave": tit})
            for ci in cis:
                registro.citar(x["id"], ci, db)
            db.execute("INSERT OR IGNORE INTO relacion(a, b, tipo) VALUES (?,?,?)", (x["id"], req["id"], "deriva_de" if tipo == "historia" else "afecta"))
            res["creadas"][tipo] = res["creadas"].get(tipo, 0) + 1
    return res


def pendientes(c):
    """Requisitos vivos del proyecto sin ninguna historia derivada (en cualquier revisión)."""
    with registro._db() as db:
        con = {r[0] for r in db.execute("SELECT r.b FROM relacion r JOIN entidad e ON e.id=r.a WHERE r.tipo='deriva_de' AND e.tipo='historia'")}
    return [x["id"] for x in registro.listar(c, "requisito") if x["revision"] not in registro.OCULTA and x["id"] not in con]


def derivar(c, chat_ctx, ids=None, glosario=(), cb=lambda f, m: None):
    """Deriva los requisitos ids de la carpeta c (por defecto, pendientes(c)). chat_ctx() da el chat (pipeline.llama o nube.backend).
    -> resumen (también en el expediente: carpetas.leer(c)["derivar"])."""
    import nube
    vivos = {x["id"]: x for x in registro.listar(c, "requisito") if x["revision"] not in registro.OCULTA}
    reqs = [vivos[i] for i in (pendientes(c) if ids is None else ids) if i in vivos]
    t0, n, coste0, tok0, lote = time.time(), 0, nube.COSTE[0], list(nube.TOK), uuid.uuid4().hex[:10]
    tot = {"creadas": {}, "omitidas": 0, "descartadas": 0}
    if reqs:
        cb(0.05, "Arrancando modelo de lenguaje…")
        with chat_ctx() as chat:
            for i, req in enumerate(reqs):
                cb(0.1 + 0.85 * i / len(reqs), f"Derivando historias: {req['codigo']} ({i + 1}/{len(reqs)})…")
                citas = [x["texto"] for x in registro.citas(req["id"]) if x["texto"]]
                rol = rol_de(c, req["campos"].get("solicitante"))
                sis, usr = prompt(req, citas, glosario, rol)
                n += 1
                r = chat(sis.format(lang="español"), usr, ESQUEMA, 2800, temperature=0.1)
                hs, ps = comprobar(r, req, citas, rol)
                tot["descartadas"] += len(r.get("historias") or []) + len(r.get("preguntas") or []) - len(hs) - len(ps)
                g = guardar(c, req, hs, ps, lote)
                tot["omitidas"] += g["omitidas"]
                for t, x in g["creadas"].items():
                    tot["creadas"][t] = tot["creadas"].get(t, 0) + x
    info = {"t": time.time(), "requisitos": [x["codigo"] for x in reqs], **tot, "llamadas": n, "segundos": round(time.time() - t0, 1),
            "coste": round(nube.COSTE[0] - coste0, 4) or None, "tokens": [a - b for a, b in zip(nube.TOK, tok0)], "lote": lote}  # lote auto: registro.deshacer_pasada
    carpetas.editar(c, lambda e: e.update(derivar=info))
    return info
