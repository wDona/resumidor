"""F7 · Preguntar sobre todo el proyecto: preguntas de lista («riesgos abiertos», «qué decidimos sobre X», «quiénes son los interesados»)
contestadas SIN LLM desde las entidades del registro. pregunta() -> None si la pregunta no va de eso (entonces corre la RAG)."""
import re

import carpetas
import pipeline as P
import rag
import registro

# tipo de entidad -> (regex de la pregunta, título de la lista); las tareas/pendientes ya las contesta carpetas.pregunta_pendientes
TIPOS = {
    "riesgo": (r"riesgos?", "Riesgos"),
    "decision": (r"decisi[oó]n(?:es)?|decidimos|decidido|decidieron|acordamos|acordado", "Decisiones"),
    "requisito": (r"requisitos?|requerimientos?", "Requisitos"),
    "historia": (r"historias?(?: de usuario)?", "Historias de usuario"),
    "pregunta": (r"preguntas? (?:abiertas?|pendientes?|sin (?:responder|resolver))|dudas?|cuestiones (?:abiertas|pendientes)", "Preguntas abiertas"),
    "interesado": (r"interesados?|stakeholders?|qui[eé]n(?:es)? (?:es|son|era|eran)\b", "Interesados"),
    "hito": (r"hitos?", "Hitos"),
    "incidencia": (r"incidencias?", "Incidencias"),
}
CERRADO = {"hecho", "cerrado", "cerrada", "resuelto", "resuelta", "mitigado", "mitigada", "sustituida", "completado", "completada", "descartado"}
CUENTA = re.compile(r"\bcu[aá]nt[oa]s\b|\bn[uú]mero de\b|\bhow many\b", re.I)
ABIERTO = re.compile(r"\b(?:abiert[oa]s?|vigentes?|activ[oa]s?|vivos?|pendientes?)\b", re.I)
CERRADA = re.compile(r"\b(?:cerrad[oa]s?|resuelt[oa]s?|mitigad[oa]s?|hech[oa]s?|completad[oa]s?)\b", re.I)
PRIO = re.compile(r"\b(must|should|could)\b|prioridad (alta|media|baja)|\b(alta|media|baja) prioridad", re.I)
TEMA = re.compile(r"\b(?:sobre|acerca de|respecto a|en relaci[oó]n (?:a|con)|de|del|para|con|qui[eé]n(?:es)? (?:es|son|era|eran))\s+(.+)", re.I)
IGN = set(P.words("abiertos abiertas vigentes cerrados cerradas pendientes tenemos hay todos todas proyecto cuantos cuantas cuales que quienes quien son es los las del de la el y en"
                  " must should could prioridad alta media baja riesgo riesgos decision decisiones decidimos requisito requisitos historia historias hito hitos incidencia incidencias"
                  " usuario con para interesado interesados stakeholders pregunta preguntas duda dudas cuestiones sobre acerca respecto"))
MAX = 40


def _cerrada(x):
    return x["estado"].casefold() in CERRADO


def pregunta(c, q, ms=()):
    """None, o {titulo, n, items:[{codigo, texto, resp, estado, sin_revisar, citas:[{mid, ver, t, doc, v}]}]}; ms: reuniones de la carpeta (nombre/vídeo de las citas)."""
    tipos = [t for t, (rx, _) in TIPOS.items() if re.search(rx, q, re.I)]
    if not tipos:
        return None
    todas = [x for x in registro.listar(c) if x["revision"] not in registro.OCULTA and x["revision"] != "descartado" and x["tipo"] in tipos]
    if not todas:
        return None  # nada en el registro de ese tipo: que decida la RAG
    xs = todas
    fq = " " + " ".join(P.words(q)) + " "
    resp = next((r for r in sorted({x["dueno"] for x in xs if x["dueno"]}, key=len, reverse=True) if any(f" {' '.join(P.words(w))} " in fq for w in [r, *r.split()] if len(w) > 2)), "")
    if resp:
        xs = [x for x in xs if resp.casefold() in x["dueno"].casefold()]
    if m := PRIO.search(q):
        pr = next(g for g in m.groups() if g).casefold()
        xs = [x for x in xs if x["prioridad"].casefold() == pr]
    if CERRADA.search(q):
        xs = [x for x in xs if _cerrada(x)]
    elif ABIERTO.search(q):
        xs = [x for x in xs if not _cerrada(x)]
    nom = {w for r in [resp] if r for w in P.words(r)}
    tema = ""
    if m := TEMA.search(q):  # «sobre X», «de Y»: lo que quede sin palabras de filtro ni nombre del responsable
        tema = " ".join(w for w in P.words(m.group(1)) if w not in IGN and w not in nom)
    if ts := set(rag.terms(tema)):
        xs = [x for x in xs if ts & set(rag.terms(x["titulo"] + " " + x["detalle"] + " " + x["codigo"]))]
        if not xs:
            return None  # el tema no está en el registro: quizá sí en las transcripciones
        sc = carpetas.sim([tema], [x["titulo"] + " " + x["detalle"] for x in xs])[0]
    else:
        tema, sc = "", [0] * len(xs)
    orden = sorted(range(len(xs)), key=lambda i: (xs[i]["revision"] != "aprobado", -sc[i], i))
    xs = [xs[i] for i in orden]
    cs = {x["id"]: x["citas"] for x in registro.completas(xs)}
    nm = {m["id"]: m for m in ms}
    items = [{"codigo": x["codigo"], "texto": x["titulo"], "resp": x["dueno"], "estado": x["estado"], "sin_revisar": x["revision"] == "propuesto",
              "citas": [{"mid": ci["mid"], "ver": ci["ver"], "t": ci["t"] or 0, "doc": (nm.get(ci["mid"]) or {}).get("label", ""), "v": (nm.get(ci["mid"]) or {}).get("video")}
                        for ci in cs[x["id"]][:3] if ci["mid"]]} for x in xs]
    tit = " y ".join(TIPOS[t][1] for t in tipos if any(x["tipo"] == t for x in todas))
    f = [resp and "de " + resp, tema and "sobre «" + tema + "»", PRIO.search(q) and PRIO.search(q).group(0), CERRADA.search(q) and "cerrados" or ABIERTO.search(q) and "abiertos"]
    return {"titulo": tit + (" (" + ", ".join(filter(None, f)) + ")" if any(f) else ""), "n": len(items), "cuenta": bool(CUENTA.search(q)), "items": items[:MAX]}
