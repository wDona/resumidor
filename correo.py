"""Borrador de correo del documento: el contenido (resumen, decisiones, tareas con responsable/plazo/minuto) sale de los datos,
sin LLM; el modelo local solo redacta la frase de apertura y la de cierre (cortas, sin datos nuevos). Sin modelo, texto de plantilla.
Se descarga como .eml (RFC 5322, X-Unsent: 1, texto + HTML, PDF opcional)."""
import html
import json
import re
from email.message import EmailMessage
from email.utils import format_datetime

import exportar as X
import pipeline as P
import rag

fm = P.fmt
VACIO = " —-"
# (saludo a todos, saludo a {n}, apertura, cierre) por tono; {t} = título
TONOS = {
    "es": {"formal": ("Estimados/as:", "Estimado/a {n}:", "Les remito el resumen de «{t}» y lo acordado.", "Quedo a su disposición para cualquier aclaración. Un cordial saludo."),
           "cercano": ("Hola a todos:", "Hola {n},", "Os paso el resumen de «{t}».", "Si veis algo que no cuadre, decídmelo. ¡Un abrazo!"),
           "breve": ("Hola:", "Hola {n}:", "Resumen de «{t}»:", "Gracias.")},
    "en": {"formal": ("Dear all,", "Dear {n},", "Please find below the summary of “{t}” and what was agreed.", "Please let me know if anything needs clarifying. Kind regards."),
           "cercano": ("Hi all,", "Hi {n},", "Here is the summary of “{t}”.", "Tell me if anything looks off. Cheers!"),
           "breve": ("Hi,", "Hi {n},", "Summary of “{t}”:", "Thanks.")},
}
ROT = {"es": dict(res="Resumen", dec="Decisiones", tar="Tareas", comp="Compromisos", sig="Siguiente paso", val="Valoración", plazo="plazo", min="min",
                  para="Todo el equipo", asunto={"acta": "Resumen y tareas: {t}", "cliente": "Seguimiento: {t}", "interno": "Valoración interna: {t}"}),
       "en": dict(res="Summary", dec="Decisions", tar="Tasks", comp="Commitments", sig="Next step", val="Assessment", plazo="due", min="min",
                  para="Everyone", asunto={"acta": "Summary and tasks: {t}", "cliente": "Follow-up: {t}", "interno": "Internal assessment: {t}"})}


def estilo(c):
    """acta | cliente (comercial: compromisos y siguiente paso) | interno (entrevistas: valoración)."""
    pid = (c["tpl"] or {}).get("id", "acta")
    return "cliente" if pid == "comercial" else "interno" if pid in ("seleccion", "periodistica", "cualitativa") else "acta"


def _sec(D, *ids):
    return [x for s in D.get("secciones_plantilla", []) if s["id"] in ids for x in s["items"]]


def contenido(c, resp=None, breve=False, l="es"):
    """Parte determinista: [(título, [líneas])] según el estilo; resp: solo lo de esa persona (más el resumen)."""
    D, R, et = c["data"], ROT[l], estilo(c)
    sol = lambda s: (s or "").strip(VACIO)
    mio = lambda r: resp is None or resp.casefold() in (r or "").casefold()
    res = sol(D.get("resumen"))
    if breve and res:
        res = re.split(r"(?<=[.!?])\s", res)[0]
    sec = [(R["res"], [res])] if res else []
    tareas = [f"{x['tarea']}" + "".join(f" ({k}: {sol(v)})" for k, v in ((R["plazo"], x.get("plazo")), ("resp.", None if resp else x.get("responsable"))) if sol(v)) + f" [{R['min']} {fm(x['t'])}]"
              for x in D.get("tareas", []) if mio(x.get("responsable"))]
    if et == "cliente":
        comp = [x["texto"] + "".join(f" ({k}: {sol(x.get(k))})" for k in ("responsable", "plazo") if sol(x.get(k))) for x in _sec(D, "compromisos") if mio(x.get("responsable"))]
        sec += [(R["comp"], comp + tareas), (R["sig"], [f"{x['texto']}" + (f" ({sol(x.get('fecha'))})" if sol(x.get("fecha")) else "") for x in _sec(D, "siguiente")][:2])] if resp is None else [(R["comp"], comp + tareas)]
    elif et == "interno":
        sec += [(R["val"], [x["texto"] + (f" ({sol(x.get('criterio') or x.get('competencia'))})" if sol(x.get("criterio") or x.get("competencia")) else "") for x in _sec(D, "valoracion", "competencias", "dudas")])]
    else:
        sec += [(R["dec"], [x["texto"] for x in D.get("decisiones", [])] if resp is None else []), (R["tar"], tareas)]
    return [(t, ls) for t, ls in sec if ls]


def _frases(c, tono, l, resp):
    """Apertura y cierre: plantilla; si hay modelo local, redactadas por él (validadas: sin cifras que no estén en el resumen)."""
    t = c["data"]["titulo"]
    ap, ci = TONOS.get(l, TONOS["es"])[tono][2:]
    ap = ap.format(t=t)
    modelo = P.llm_model()
    if not modelo:
        return ap, ci, False
    try:
        with P.llama(P.PHYS, ctx=4096, model=modelo) as chat:
            r = chat(f"Escribes el borrador de un correo de seguimiento tras una reunión, en {l}, tono {tono}. Solo dos frases cortas: una apertura que presente el resumen y un cierre. "
                     "No añadas datos, cifras, fechas ni nombres que no estén en la entrada. No saludes con nombre ni firmes.",
                     f"Título: {t}\nResumen: {(c['data'].get('resumen') or '')[:600]}", P.obj(apertura=P.S(200), cierre=P.S(140)), 200)
        ref = t + " " + (c["data"].get("resumen") or "")
        if all(x.strip() and not rag.bad_nums(x, ref) for x in (r["apertura"], r["cierre"])):
            return r["apertura"].strip(), r["cierre"].strip(), True
    except Exception as ex:  # sin servidor/modelo que arranque: se queda la plantilla
        print("  correo: sin LLM:", ex, flush=True)
    return ap, ci, False


def _html(saludo, ap, sec, ci):
    e = html.escape
    return ("<div style=\"font-family:Segoe UI,Arial,sans-serif;font-size:14px\">" + (f"<p>{e(saludo)}</p>" if saludo else "") + f"<p>{e(ap)}</p>"
            + "".join(f"<h3 style=\"margin:14px 0 4px\">{e(t)}</h3>" + ("<ul>" + "".join(f"<li>{e(x)}</li>" for x in ls) + "</ul>" if len(ls) > 1 or t != sec[0][0] else f"<p>{e(ls[0])}</p>") for t, ls in sec)
            + f"<p>{e(ci)}</p></div>")


def borradores(c, modo="todos", tono="formal", idioma="es", llm=True):
    """-> [{para, asunto, texto, html}] (para = nombre del responsable, sin dirección) y si el LLM redactó las frases."""
    l = idioma if idioma in ROT else "es"
    tono = tono if tono in ("formal", "cercano", "breve") else "formal"
    R, et = ROT[l], estilo(c)
    ap, ci, por_llm = _frases(c, tono, l, None) if llm else (TONOS.get(l, TONOS["es"])[tono][2].format(t=c["data"]["titulo"]), TONOS.get(l, TONOS["es"])[tono][3], False)
    asunto = R["asunto"][et].format(t=c["data"]["titulo"])
    resp = []
    if modo == "responsable" and et != "interno":
        resp = list(dict.fromkeys(r.strip() for x in c["data"].get("tareas", []) + _sec(c["data"], "compromisos") for r in re.split(r"\s*(?:,|/|;|\by\b|&)\s*", x.get("responsable") or "") if r.strip(VACIO)))
    out = []
    for r in resp or [None]:
        sec = contenido(c, r, tono == "breve", l)
        if not sec:
            continue
        sa = TONOS.get(l, TONOS["es"])[tono]
        saludo = sa[1].format(n=r) if r else sa[0]
        txt = "\n\n".join(([saludo] if saludo else []) + [ap] + [f"{t}\n" + "\n".join(f"- {x}" if len(ls) > 1 else x for x in ls) for t, ls in sec] + [ci])
        out.append({"para": r or R["para"], "asunto": asunto, "texto": txt, "html": _html(saludo, ap, sec, ci)})
    return out, por_llm


def eml(cor, pdf=None, nombre_pdf="documento.pdf"):
    """Correo -> bytes .eml (borrador: X-Unsent: 1, sin remitente ni destinatario; el nombre va en X-Actas-Para)."""
    m = EmailMessage()
    m["Subject"] = cor["asunto"]
    m["X-Unsent"] = "1"
    m["X-Actas-Para"] = cor["para"].encode("ascii", "backslashreplace").decode()
    m["Date"] = format_datetime(__import__("datetime").datetime.now().astimezone())
    m.set_content(cor["texto"])
    m.add_alternative(cor["html"], subtype="html")
    if pdf:
        m.add_attachment(pdf, maintype="application", subtype="pdf", filename=nombre_pdf)
    return bytes(m)


def generar(mid, ver, modo="todos", tono="formal", idioma="es", adjuntar_pdf=False, anon=False):
    """Genera los borradores, guarda los .eml en correos/ junto a la versión y devuelve {correos, eml_url, llm, aviso?}."""
    c = X.carga(mid, ver, anon)
    cs, por_llm = borradores(c, modo, tono, idioma)
    if not cs:
        raise ValueError("No hay contenido para el correo")
    pdf, aviso = None, None
    if adjuntar_pdf:
        try:
            pdf = X.exportar(mid, ver, "pdf", anon=anon)[0]
        except X.SinNavegador as ex:
            aviso = f"Sin PDF adjunto: {ex}"
    d = c["d"] / "correos"
    d.mkdir(exist_ok=True)
    for f in d.glob("*.eml"):
        f.unlink()
    base = f"/api/correo/{c['mid']}/{c['ver']}/eml"
    for i, cor in enumerate(cs):
        (d / f"{i}.eml").write_bytes(eml(cor, pdf, re.sub(r"[^\w.-]+", "_", c["data"]["titulo"], flags=re.A)[:50] + ".pdf"))
        cor["eml_url"] = f"{base}/{i}"
    return {"correos": cs, "eml_url": cs[0]["eml_url"], "llm": por_llm, **({"aviso": aviso} if aviso else {})}


def demo():
    import email
    from email import policy
    c = {"data": {"titulo": "Reunión X", "resumen": "Se revisó el plan. Se acordó seguir.", "decisiones": [{"texto": "Se aprueba el plan", "t": 5}],
                  "tareas": [{"tarea": "Enviar informe", "responsable": "Javier", "plazo": "viernes", "t": 70}, {"tarea": "Llamar", "responsable": "Ana", "plazo": "—", "t": 80}]},
         "tpl": {"id": "acta"}}
    cs, llm = borradores(c, "responsable", "cercano", llm=False)
    assert [x["para"] for x in cs] == ["Javier", "Ana"] and "Enviar informe (plazo: viernes) [min 01:10]" in cs[0]["texto"] and "Llamar" not in cs[0]["texto"] and cs[0]["texto"].startswith("Hola Javier,")
    m = email.message_from_bytes(eml(cs[0], b"%PDF-1.4 x"), policy=policy.default)
    assert m["X-Unsent"] == "1" and m["Subject"].startswith("Resumen y tareas") and [p.get_content_type() for p in m.iter_parts()] == ["multipart/alternative", "application/pdf"]
    assert "Enviar informe" in m.get_body(("plain",)).get_content() and "<li>" in m.get_body(("html",)).get_content()
    print("ok")


if __name__ == "__main__":
    demo()
