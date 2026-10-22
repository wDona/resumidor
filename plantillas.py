"""Plantillas: qué se extrae de la grabación y cómo se redacta (acta de reunión, entrevista, clase…).
Las de serie viven aquí (solo lectura; «Duplicar» para editar); las del usuario, en work/plantillas/<id>.json. Una del usuario con
el id de una de serie la sustituye (importar → reemplazar) y «Restablecer» la borra. pipeline.prompts() las convierte en prompts."""
import json
import re

import pipeline as P

DIR = P.WORK / "plantillas"
IDIOMAS = {"reunión": "el de la reunión", **{k: v.split(" (")[0] for k, v in P.IDIOMAS.items()}}
BLOQUES = ("resumen", "desarrollo", "detalle", "transcripcion")  # bloques fijos del documento; el resto son secciones
TITULOS = {"resumen": "Resumen", "desarrollo": "Desarrollo", "detalle": "Detalle por partes", "transcripcion": "Transcripción"}
RESERV = {"tema", "puntos", "relato", *BLOQUES}  # ids que no puede tener una sección (claves del map o bloques)
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
CAMPO = re.compile(r"[a-z0-9_]{1,30}")
NOTAS = [{"nombre": "Importante", "seccion": None, "atajo": "Ctrl+1"}, {"nombre": "Revisar", "seccion": None, "atajo": "Ctrl+2"}]


def sec(id, nombre, descripcion, campos=(), nunca=False):
    return {"id": id, "nombre": nombre, "descripcion": descripcion, "campos": list(campos), "nunca_recortar": nunca}


def doc(singular, plural, femenino):
    return {"singular": singular, "plural": plural, "femenino": femenino}


ACTA, INFORME, APUNTES, FICHA, NOTAS_DOC = doc("acta", "actas", True), doc("informe", "informes", False), doc("apuntes", "apuntes", False), \
    doc("ficha", "fichas", True), doc("notas", "notas", True)


def base(id, nombre, descripcion, secciones, que="", como="", notas=None, nube=True, orden=None, titulos=None, documento=INFORME, escala=False):
    """documento: cómo se llama lo que sale (la interfaz dice «Generar informe», «Descargar apuntes»…); escala: el editor muestra
    la escala de importancia (solo donde afinarla tiene sentido)."""
    ids = [s["id"] for s in secciones]
    return {"id": id, "nombre": nombre, "descripcion": descripcion, "documento": dict(documento), "secciones": secciones,
            "que_destacar": que, "como_redactar": como, "escala": dict(P.ESCALA), "mostrar_escala": escala, "orden": orden or ["resumen", *ids, "desarrollo", "detalle", "transcripcion"],
            "titulos": {**TITULOS, **(titulos or {})}, "opciones": {"capturas": True, "marcas": True}, "idioma_acta": "reunión",
            "nube_permitida": nube, "notas_rapidas": notas or [dict(n) for n in NOTAS]}


# Acta de reunión: decisiones y tareas son las de siempre (verify, búsqueda a fondo, cita de evidencia…) y sus descripciones son
# los párrafos del MAP_PROMPT: con esta plantilla los prompts y las cachés son exactamente los de antes (pipeline._selftest)
SERIE = [
    base("acta", "Acta de reunión", "Reunión con acuerdos y encargos: resumen, decisiones, tareas y desarrollo.",
         [sec("decisiones", "Decisiones", P.DEC_DESC, nunca=True), sec("tareas", "Tareas", P.TAR_DESC, ("responsable", "plazo"), True)],
         notas=[{"nombre": "Decisión", "seccion": "decisiones", "atajo": "Ctrl+1"}, {"nombre": "Tarea", "seccion": "tareas", "atajo": "Ctrl+2"},
                {"nombre": "Importante", "seccion": None, "atajo": "Ctrl+3"}, {"nombre": "Revisar", "seccion": None, "atajo": "Ctrl+4"}],
         orden=["resumen", "desarrollo", "decisiones", "tareas", "detalle", "transcripcion"],
         titulos={"desarrollo": "Desarrollo de la reunión", "decisiones": "Decisiones detectadas", "tareas": "Tareas detectadas",
                  "detalle": "Detalle por secciones"}, documento=ACTA, escala=True),
    # junta de propietarios (LPH): los acuerdos van por el camino de las decisiones del acta (verificación, búsqueda a fondo)
    base("comunidad", "Junta de vecinos / comunidad de propietarios", "Junta de propietarios: acta al estilo de la Ley de Propiedad Horizontal.",
         [sec("asistentes", "Asistentes y representación", "propietarios presentes o representados (quién representa a quién) y "
              "coeficientes o cuotas de participación, solo si se mencionan.", ("piso", "representado_por", "coeficiente")),
          sec("orden_dia", "Orden del día", "puntos del orden del día en el orden en que se tratan.", ("punto",), True),
          sec("decisiones", "Acuerdos con votación", "solo acuerdos que la junta adopta hoy sobre un punto del orden del día, con el "
              "resultado de la votación si se dice (votos a favor, en contra y abstenciones, o unanimidad); aplazar un punto a otra junta "
              "también. NO son acuerdos: propuestas sin votar, opiniones ni lo leído del acta anterior.", (), True),
          sec("derramas", "Derramas y cuotas", "derramas, cuotas o presupuestos que se aprueban o se discuten: importe y plazo de pago.",
              ("importe", "plazo"), True),
          sec("incidencias", "Incidencias y reparaciones", "averías, obras y reparaciones de la finca: qué, dónde y quién se encarga.",
              ("ubicacion", "responsable")),
          sec("ruegos", "Ruegos y preguntas", "ruegos y preguntas de los propietarios y la respuesta que reciben.", ("propietario",))],
         que="Resultados de cada votación, importes, plazos de pago, morosos y obras de la finca.",
         como="Estilo de acta de junta de propietarios: impersonal y en pasado («se aprueba por unanimidad…»), sin valoraciones.",
         notas=[{"nombre": "Acuerdo", "seccion": "decisiones", "atajo": "Ctrl+1"}, {"nombre": "Derrama", "seccion": "derramas", "atajo": "Ctrl+2"},
                {"nombre": "Importante", "seccion": None, "atajo": "Ctrl+3"}, {"nombre": "Revisar", "seccion": None, "atajo": "Ctrl+4"}],
         orden=["resumen", "asistentes", "orden_dia", "decisiones", "derramas", "incidencias", "ruegos", "desarrollo", "detalle", "transcripcion"],
         titulos={"decisiones": "Acuerdos"}, documento=ACTA),
    base("seleccion", "Entrevista de selección", "Entrevista a un candidato para un puesto.",
         [sec("perfil", "Perfil", "datos del candidato que cuenta él mismo: formación, experiencia, situación actual, disponibilidad."),
          sec("competencias", "Competencias con evidencia", "competencias que el candidato demuestra con un ejemplo concreto de lo que hizo.",
              ("competencia",), True),
          sec("valoracion", "Valoración por criterios", "cómo responde a cada criterio que pregunta el entrevistador (experiencia, "
              "motivación, encaje, idiomas…): solo lo que se oye, sin juzgar a la persona.", ("criterio", "valoracion")),
          sec("dudas", "Dudas", "respuestas vagas, contradicciones o puntos que quedan por aclarar.", (), True)],
         que="Ejemplos concretos del candidato, cifras de su experiencia y condiciones (salario, incorporación).",
         notas=[{"nombre": "Buena respuesta", "seccion": "competencias", "atajo": "Ctrl+1"},
                {"nombre": "Duda", "seccion": "dudas", "atajo": "Ctrl+2"}, {"nombre": "Bandera roja", "seccion": None, "atajo": "Ctrl+3"}],
         documento=FICHA),
    base("periodistica", "Entrevista periodística", "Entrevista para una noticia o reportaje.",
         [sec("citas", "Citas literales", "frases del entrevistado que merecen ir entre comillas en la pieza (texto = de qué habla).", (), True),
          sec("temas", "Temas", "temas de los que se habla y lo que dice el entrevistado de cada uno."),
          sec("verificar", "Datos a verificar", "cifras, fechas, nombres y afirmaciones de hecho que hay que comprobar antes de publicar.",
              ("dato",), True)],
         que="Declaraciones con titular, cifras y nombres propios."),
    base("cualitativa", "Investigación cualitativa", "Entrevista o grupo de discusión de un estudio cualitativo.",
         [sec("temas", "Temas", "temas que aparecen y qué dicen los participantes de cada uno."),
          sec("codigos", "Códigos", "códigos (etiquetas breves de análisis) que se aplican a lo dicho, con su tema.", ("codigo", "tema"), True),
          sec("citas", "Citas que los respaldan", "frases literales de los participantes que ilustran un tema o código.", ("codigo",))],
         que="Experiencias, emociones, contradicciones y vocabulario propio de los participantes.", escala=True),
    base("clase", "Clase o conferencia", "Clase, charla o conferencia: apuntes para estudiar.",
         [sec("conceptos", "Conceptos", "ideas o conceptos que se explican y su explicación.", ("concepto",)),
          sec("glosario", "Glosario", "términos técnicos que se usan y su definición según la clase (texto = la definición).", ("termino",)),
          sec("preguntas", "Preguntas tipo examen", "preguntas de examen que se responden con lo explicado (texto = la pregunta).",
              ("respuesta",))],
         que="Definiciones, fórmulas, ejemplos y lo que el ponente dice que es importante o que entra en el examen.",
         como="Tono de apuntes: claro y didáctico.", documento=APUNTES, escala=True),
    base("consulta", "Consulta profesional", "Consulta con un profesional (médico, abogado, asesor…). Datos sensibles.",
         [sec("motivo", "Motivo de la consulta", "por qué acude la persona y qué pide."),
          sec("hechos", "Hechos relatados", "lo que cuenta la persona que ha ocurrido, con fechas y cifras si las dice."),
          sec("valoracion", "Valoración", "lo que explica o valora el profesional."),
          sec("pasos", "Próximos pasos", "lo que se acuerda hacer después (pruebas, documentos, citas, gestiones).", ("responsable", "plazo"), True)],
         que="Fechas, cifras, plazos y lo que el profesional recomienda.", como="Lenguaje preciso y neutro.", nube=False, documento=NOTAS_DOC),
    base("comercial", "Llamada comercial o de soporte", "Llamada con un cliente: venta, seguimiento o soporte.",
         [sec("necesidad", "Necesidad", "qué necesita o qué problema tiene el cliente."),
          sec("objeciones", "Objeciones", "dudas, quejas u objeciones del cliente y la respuesta que recibe."),
          sec("compromisos", "Compromisos", "lo que cada parte se compromete a hacer.", ("responsable", "plazo"), True),
          sec("siguiente", "Siguiente paso", "próximo contacto o paso acordado.", ("fecha",), True)],
         que="Precios, plazos, productos y nombres del cliente."),
    base("obra", "Visita de obra o inspección", "Visita de obra, inspección o auditoría in situ.",
         [sec("incidencias", "Incidencias", "defectos, riesgos o incumplimientos que se observan.", ("gravedad", "ubicacion", "responsable"), True),
          sec("medidas", "Medidas", "medidas correctoras que se piden o acuerdan.", ("responsable", "plazo")),
          sec("pendientes", "Pendientes", "lo que queda por revisar, documentar o comprobar.", (), True)],
         que="Ubicaciones, medidas, cifras y riesgos para la seguridad.",
         notas=[{"nombre": "Incidencia", "seccion": "incidencias", "atajo": "Ctrl+1"},
                {"nombre": "Ver pantalla", "seccion": None, "atajo": "Ctrl+2"}],
         documento=doc("parte", "partes", False)),
    base("video", "Vídeo o pódcast", "Vídeo, pódcast o directo: capítulos y material para publicar.",
         [sec("capitulos", "Capítulos", "partes del contenido en orden, con un título corto cada una.", ("titulo",), True),
          sec("ideas", "Ideas de publicaciones", "momentos o frases que darían para una publicación corta en redes."),
          sec("shownotes", "Show notes", "personas, libros, herramientas, enlaces y recursos que se mencionan.", ("recurso",))],
         que="Cambios de tema, frases memorables y recursos mencionados.", como="Tono cercano, apto para publicar.", documento=NOTAS_DOC),
    base("onboarding", "Onboarding", "Sesión de incorporación o formación interna.",
         [sec("procesos", "Procesos paso a paso", "procedimientos que se explican, un paso por elemento, en orden.", ("proceso",)),
          sec("herramientas", "Herramientas y accesos", "programas, cuentas y accesos que hay que tener o pedir.", ("herramienta", "acceso")),
          sec("contactos", "Contactos", "personas o equipos a quien acudir y para qué.", ("persona", "rol")),
          sec("normas", "Normas", "normas, horarios y costumbres del equipo."),
          sec("dudas", "Dudas pendientes", "preguntas sin respuesta o temas que se dejan para más adelante.", (), True),
          sec("checklist", "Checklist", "acciones que la persona nueva tiene que hacer.", ("plazo",), True)],
         que="Pasos concretos, nombres de herramientas, personas y plazos.", documento=APUNTES),
]
SERIE_ID = {t["id"]: t for t in SERIE}


def _txt(v, n, que):
    if not isinstance(v, str):
        raise ValueError(f"{que}: debe ser texto")
    if len(v) > n:
        raise ValueError(f"{que}: como mucho {n} caracteres")
    return v.strip()


def validar(t):
    """Plantilla del editor o de un .json importado -> plantilla limpia (con lo que falte por defecto); ValueError con el motivo."""
    if not isinstance(t, dict):
        raise ValueError("No es una plantilla (se esperaba un objeto JSON)")
    d = base("x", "", "", [])
    nombre = _txt(t.get("nombre"), 80, "Nombre")
    if not nombre:
        raise ValueError("Falta el nombre")
    out = {"id": str(t.get("id") or ""), "nombre": nombre, "descripcion": _txt(t.get("descripcion", ""), 300, "Descripción"),
           "que_destacar": _txt(t.get("que_destacar", ""), 1000, "Qué destacar"),
           "como_redactar": _txt(t.get("como_redactar", ""), 1000, "Cómo redactar")}
    if out["id"] and not ID.fullmatch(out["id"]):
        raise ValueError("Id no válido (minúsculas, cifras y guiones)")
    dc = t.get("documento") or INFORME
    if not isinstance(dc, dict):
        raise ValueError("Documento no válido")
    out["documento"] = {"singular": _txt(dc.get("singular") or "informe", 30, "Documento"), "plural": _txt(dc.get("plural") or
                        (dc.get("singular") or "informe") + "s", 30, "Documento"), "femenino": bool(dc.get("femenino"))}
    out["mostrar_escala"] = bool(t.get("mostrar_escala"))
    if t.get("base") in SERIE_ID:
        out["base"] = t["base"]
    secs = t.get("secciones")
    if not isinstance(secs, list) or not 1 <= len(secs) <= 8:
        raise ValueError("Entre 1 y 8 secciones")
    out["secciones"], vistos = [], set()
    for i, s in enumerate(secs, 1):
        if not isinstance(s, dict):
            raise ValueError(f"Sección {i}: no válida")
        sid = str(s.get("id") or "")
        if not CAMPO.fullmatch(sid) or sid in RESERV or sid in vistos:
            raise ValueError(f"Sección {i}: id no válido o repetido («{sid}»; minúsculas, cifras y _)")
        vistos.add(sid)
        campos = s.get("campos", [])
        if not isinstance(campos, list) or len(campos) > 6 or not all(isinstance(c, str) and CAMPO.fullmatch(c) for c in campos):
            raise ValueError(f"Sección {i}: campos no válidos (hasta 6; minúsculas, cifras y _)")
        desc = _txt(s.get("descripcion", ""), 2000, f"Sección {i}")
        if not desc:
            raise ValueError(f"Sección {i}: falta la descripción para el modelo")
        out["secciones"].append({"id": sid, "nombre": _txt(s.get("nombre") or sid, 80, f"Sección {i}"), "descripcion": desc,
                                 "campos": list(dict.fromkeys(campos)), "nunca_recortar": bool(s.get("nunca_recortar"))})
    esc = t.get("escala", d["escala"])
    if not isinstance(esc, dict) or sorted(esc) != ["1", "2", "3", "4", "5"] or not all(_txt(v, 300, "Escala") for v in esc.values()):
        raise ValueError("Escala: un texto para cada nota de 1 a 5")
    out["escala"] = {k: esc[k].strip() for k in "12345"}
    todos = [*BLOQUES, *vistos]
    orden = t.get("orden", d["orden"])
    if not isinstance(orden, list) or not set(orden) <= set(todos) or len(set(orden)) != len(orden):
        raise ValueError("Orden de bloques no válido")
    out["orden"] = orden + [b for b in todos if b not in orden]  # lo que falte, al final
    tit = t.get("titulos", {})
    if not isinstance(tit, dict):
        raise ValueError("Títulos no válidos")
    out["titulos"] = {k: _txt(tit.get(k) or TITULOS.get(k, ""), 80, "Título") for k in todos if tit.get(k) or k in TITULOS}
    op = t.get("opciones", {})
    out["opciones"] = {k: bool(op.get(k, True)) if isinstance(op, dict) else True for k in ("capturas", "marcas")}
    out["idioma_acta"] = t.get("idioma_acta", "reunión")
    if out["idioma_acta"] not in IDIOMAS:
        raise ValueError("Idioma del acta no válido")
    out["nube_permitida"] = bool(t.get("nube_permitida", True))
    notas = t.get("notas_rapidas", d["notas_rapidas"])
    if not isinstance(notas, list) or len(notas) > 12:
        raise ValueError("Notas rápidas: como mucho 12")
    out["notas_rapidas"] = [{"nombre": _txt(n.get("nombre"), 40, "Nota rápida"), "seccion": n.get("seccion") if n.get("seccion") in vistos else None,
                             "atajo": _txt(n.get("atajo") or "", 20, "Atajo")} for n in notas if isinstance(n, dict) and n.get("nombre")]
    return out


def propias():
    """Plantillas guardadas por el usuario (las que no se pueden leer se saltan)."""
    out = {}
    for f in sorted(DIR.glob("*.json")):
        try:
            out[f.stem] = {**validar(json.loads(f.read_text(encoding="utf-8"))), "id": f.stem}
        except (OSError, ValueError):
            pass
    return out


def todas():
    """[plantilla + serie (es de serie), editable (está en work/plantillas)]: de serie primero, en su orden."""
    pr = propias()
    return [{**pr.get(t["id"], t), "serie": True, "editable": t["id"] in pr} for t in SERIE] + \
           [{**t, "serie": False, "editable": True} for i, t in pr.items() if i not in SERIE_ID]


def get(pid):
    pid = pid or "acta"
    t = propias().get(pid) or SERIE_ID.get(pid)
    if not t:
        raise ValueError(f"No existe la plantilla «{pid}»")
    return t


def nuevo_id(nombre):
    s = re.sub(r"[^a-z0-9]+", "-", nombre.lower().translate(str.maketrans("áéíóúüñç", "aeiouunc"))).strip("-")[:30] or "plantilla"
    ids, i, out = {t["id"] for t in todas()}, 1, s
    while out in ids:
        i += 1
        out = f"{s}-{i}"
    return out


def guardar(t, modo=""):
    """Guarda una plantilla del usuario. Sin id: nueva. Con id: sustituye (de serie no, salvo modo «reemplazar» al importar).
    Nombre o id que ya existe al importar (modo «»): FileExistsError para que la interfaz pregunte reemplazar / guardar como copia."""
    t = validar(t)
    ex = {x["id"]: x for x in todas()}
    if modo == "copia" or not t["id"]:
        nom = t["nombre"]
        while modo == "copia" and any(x["nombre"].casefold() == nom.casefold() for x in ex.values()):
            nom = nom + " (copia)"
        t["nombre"], t["id"] = nom, nuevo_id(nom)
    elif modo == "importar" and (t["id"] in ex or any(x["nombre"].casefold() == t["nombre"].casefold() for x in ex.values())):
        raise FileExistsError(t["nombre"])
    elif t["id"] in ex and not ex[t["id"]]["editable"] and modo != "reemplazar":
        raise PermissionError("Las plantillas de serie no se editan: duplícala")
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"{t['id']}.json").write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")
    return t


def borrar(pid):
    """Borra una plantilla propia (con el id de una de serie: la restablece)."""
    if ID.fullmatch(pid or ""):
        (DIR / f"{pid}.json").unlink(missing_ok=True)


def _selftest():
    for t in SERIE:
        assert validar(t) == t, t["id"]
        assert ID.fullmatch(t["id"]) and "_" not in t["id"]
    for bad in ({}, {"nombre": "x", "secciones": []}, {"nombre": "x", "secciones": [{"id": "puntos", "descripcion": "a"}]},
                {"nombre": "x", "secciones": [{"id": "a", "descripcion": "a"}], "escala": {"1": "a"}},
                {"nombre": "x", "secciones": [{"id": "a", "descripcion": "a", "campos": ["Mal campo"]}]}):
        try:
            validar(bad)
            raise AssertionError(bad)
        except ValueError:
            pass
    m = validar({"nombre": "Mínima", "secciones": [{"id": "ideas", "descripcion": "ideas"}]})  # lo que falta, por defecto
    assert m["orden"][-1] == "ideas" and m["escala"] == P.ESCALA and m["opciones"]["capturas"] and m["idioma_acta"] == "reunión"
    # exportar -> importar: el JSON exportado vuelve igual
    t = SERIE_ID["clase"]
    assert validar(json.loads(json.dumps(t, ensure_ascii=False))) == t


if __name__ == "__main__":
    _selftest()
    print("ok")
