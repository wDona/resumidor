"""Exportar una vista del registro del proyecto (requisitos, historias, interesados, decisiones) a docx, pdf, xlsx, csv, md, json, feature,
csv_jira y csv_azure. Todo sale de las entidades (registro.py), nunca del HTML. borrador=True exporta todo lo no descartado y marca
«BORRADOR – sin revisar» lo propuesto; borrador=False solo lo aprobado. Un modelo neutro (lista de operaciones) alimenta docx, html/pdf y md."""
import datetime as dt
import html
import io
import json
import re
import zipfile
from xml.sax.saxutils import escape as xesc

import exportar as X
import pipeline as P
import registro

TIPO = {"requisitos": "requisito", "historias": "historia", "interesados": "interesado", "decisiones": "decision"}
BORR = "BORRADOR – sin revisar"
BASE = ("docx", "pdf", "xlsx", "csv", "md", "json")
EXTRA = {"historias": ("feature", "csv_jira", "csv_azure"), "requisitos": ("csv_jira", "csv_azure")}
EXT = {"docx": "docx", "pdf": "pdf", "xlsx": "xlsx", "csv": "csv", "md": "md", "json": "json", "feature": "feature", "csv_jira": "jira.csv", "csv_azure": "azure.csv"}
MIME = {"docx": X.FORMATOS["docx"][1], "pdf": "application/pdf", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "csv": "text/csv; charset=utf-8", "md": "text/markdown; charset=utf-8", "json": "application/json", "feature": "text/plain; charset=utf-8",
        "csv_jira": "text/csv; charset=utf-8", "csv_azure": "text/csv; charset=utf-8"}
COLS = {"requisitos": ["Código", "Título", "Detalle", "Tipo", "Prioridad", "Estado", "Solicitante", "Criterios", "Versión", "Origen", "Revisión"],
        "historias": ["Código", "Título", "Como", "Quiero", "Para", "Criterios", "Puntos", "Épica", "Estado", "Deriva de", "Origen", "Revisión"],
        "interesados": ["Código", "Nombre", "Rol", "Organización", "Poder", "Interés", "Actitud", "Estrategia", "Canal", "Notas", "Origen", "Revisión"],
        "decisiones": ["Código", "Título", "Contexto", "Alternativas", "Consecuencias", "Decisor", "Fecha", "Estado", "Sustituye a", "Sustituida por", "Origen", "Revisión"]}
CORTAS = {"requisitos": ["Código", "Título", "Tipo", "Prioridad", "Estado", "Revisión"], "historias": ["Código", "Título", "Épica", "Puntos", "Estado", "Revisión"],
          "interesados": ["Código", "Nombre", "Rol", "Organización", "Poder", "Interés", "Actitud", "Revisión"], "decisiones": []}
TITULO = {"requisitos": "Requisitos", "historias": "Historias de usuario", "interesados": "Interesados", "decisiones": "Registro de decisiones"}


def formatos(vista):
    return BASE + EXTRA.get(vista, ())


# ---------- datos ----------
def _t(x):
    return f"[{P.fmt(x)}]"


def _origen(x, docs):
    ps = []
    for ci in x["citas"][:3]:
        d = docs.get(ci["mid"])
        ps.append(" ".join(filter(None, [f"{d[0]} ({d[1]})" if d else "", _t(ci["t"]) if ci.get("t") is not None else "", f"«{ci['texto']}»" if ci.get("texto") else ""])))
    return "; ".join(p for p in ps if p) or {"manual": "Manual", "derivado": "Derivado", "migrado": "Migrado"}.get(x["origen"], x["origen"])


def _gherkin(cr):
    """Criterios [{escenario,dado,cuando,entonces,propuesta}] -> [(escenario, propuesta, [(Given|When|Then|And, texto)])]."""
    out = []
    for k in cr if isinstance(cr, list) else []:
        if not isinstance(k, dict):
            continue
        ls = []
        for kw, campo in (("Given", "dado"), ("When", "cuando"), ("Then", "entonces")):
            for i, l in enumerate(s for s in str(k.get(campo) or "").splitlines() if s.strip()):
                ls.append((kw if i == 0 else "And", l.strip()))
        out.append((str(k.get("escenario") or "").strip(), bool(k.get("propuesta")), ls))
    return out


def _crit_txt(x, h):
    cr = x["campos"].get("criterios")
    if h:
        return "\n".join(f"{e or 'Escenario'}{' (propuesta)' if p else ''}: " + " ".join(f"{k} {t}" for k, t in ls) for e, p, ls in _gherkin(cr))
    return "\n".join(map(str, cr)) if isinstance(cr, list) else str(cr or "")


def cargar(c, vista, borrador=True, docs=()):
    """-> (items, filas): items = entidades completas (dict del contrato) de la vista; filas = [{columna: texto}] en el mismo orden."""
    if vista not in TIPO:
        raise ValueError(f"Vista desconocida: {vista}")
    todas = registro.listar(c)
    cod = {x["id"]: x["codigo"] for x in todas}
    docs = {d["mid"]: (d["data"].get("titulo") or d["nombre"], d["fecha"]) for d in docs}
    xs = [x for x in todas if x["tipo"] == TIPO[vista] and (x["revision"] == "aprobado" or (borrador and x["revision"] == "propuesto"))]
    xs.sort(key=lambda x: x["codigo"] or "")
    items, filas = registro.completas(xs), []
    for x in items:
        k, rel = x["campos"], x["relaciones"]
        a = lambda tipo: ", ".join(cod.get(r["b"], "") for r in rel if r["tipo"] == tipo and r["a"] == x["id"])
        de = lambda tipo: ", ".join(cod.get(r["a"], "") for r in rel if r["tipo"] == tipo and r["b"] == x["id"])
        f = {"Código": x["codigo"], "Título": x["titulo"], "Nombre": x["titulo"], "Estado": x["estado"], "Origen": _origen(x, docs), "Revisión": BORR if x["revision"] == "propuesto" else "Aprobado"}
        if vista == "requisitos":
            f |= {"Detalle": x["detalle"], "Tipo": k.get("tipo_req"), "Prioridad": x["prioridad"], "Solicitante": k.get("solicitante"), "Criterios": _crit_txt(x, False), "Versión": k.get("version")}
        elif vista == "historias":
            f |= {"Como": k.get("como"), "Quiero": k.get("quiero"), "Para": k.get("para"), "Criterios": _crit_txt(x, True), "Puntos": k.get("puntos"), "Épica": k.get("epica"), "Deriva de": a("deriva_de")}
        elif vista == "interesados":
            f |= {k2: k.get(k3) for k2, k3 in (("Rol", "rol"), ("Organización", "organizacion"), ("Poder", "poder"), ("Interés", "interes"), ("Actitud", "actitud"),
                                                ("Estrategia", "estrategia"), ("Canal", "canal"))} | {"Notas": x["detalle"]}
        else:
            f |= {"Contexto": x["detalle"], "Alternativas": k.get("alternativas"), "Consecuencias": k.get("consecuencias"), "Decisor": k.get("decisor"), "Fecha": k.get("fecha") or x["fecha_alta"],
                  "Sustituye a": a("sustituye"), "Sustituida por": de("sustituye")}
        filas.append({c2: _s(f.get(c2)) for c2 in COLS[vista]})
    return items, filas


def _s(v):
    return "" if v is None else "\n".join(map(str, v)) if isinstance(v, list) else str(v)


# ---------- modelo del documento (docx, html, md) ----------
def _cuadrante(items, filas, niv=6, niv_i=None):
    """Matriz 2×2: alto > punto medio de su eje ((N+1)/2; N = niv para poder, niv_i para interés), bajo < punto medio. Solo hay cuadrante si AMBOS valores
    difieren del medio; si uno lo iguala está en el límite entre dos cuadrantes; si ambos, en el centro. -> (matriz, sin clasificar, [(texto, nombre)])."""
    n = lambda v: registro.num_medio(v) or 0
    mp, mi = (niv + 1) / 2, ((niv_i or niv) + 1) / 2
    q, sin, lim = {(p, i): [] for p in (0, 1) for i in (0, 1)}, [], []
    G, M, I, S = "Gestionar de cerca", "Mantener satisfecho", "Mantener informado", "Monitorizar"
    for x, f in zip(items, filas):
        po, it = n(f["Poder"]), n(f["Interés"])
        nom = f["Nombre"] + (" (borrador)" if f["Revisión"] == BORR else "")
        if not (po and it):
            sin.append(nom)
        elif po == mp and it == mi:
            lim.append(("En el centro (entre las cuatro zonas)", nom))
        elif po == mp:  # entre alto y bajo poder, del lado de su interés
            lim.append((f"En el límite entre {G} y {M}" if it > mi else f"En el límite entre {I} y {S}", nom))
        elif it == mi:  # entre bajo y alto interés, del lado de su poder
            lim.append((f"En el límite entre {G} y {I}" if po > mp else f"En el límite entre {M} y {S}", nom))
        else:
            q[(po > mp, it > mi)].append(nom)
    cel = lambda p, i, lab: f"{lab}\n" + (", ".join(q[(p, i)]) or "—")
    return [["Interés alto", cel(0, 1, I), cel(1, 1, G)],
            ["Interés bajo", cel(0, 0, S), cel(1, 0, M)]], sin, lim


def modelo(c, vista, items, filas, borrador):
    cols, cortas = COLS[vista], CORTAS[vista]
    m = [("t", TITULO[vista]), ("p", f"Proyecto: {c or 'Sin carpeta'} · {dt.date.today():%d/%m/%Y}")]
    nb = sum(f["Revisión"] == BORR for f in filas)
    if nb:
        m.append(("aviso", f"{BORR.upper()}: {nb} de {len(filas)} elementos están propuestos y aún no han sido revisados."))
    elif borrador:
        m.append(("p", "Todos los elementos están revisados."))
    else:
        m.append(("p", "Solo elementos aprobados."))
    if vista == "interesados":
        np_, ni = registro.niveles_ejes(c) if c else (registro.NIVELES_DEF,) * 2
        mat, sin, lim = _cuadrante(items, filas, np_, ni)
        m += [("h", "Matriz poder / interés", False), ("p", f"Escala: Poder 1–{np_} · Interés 1–{ni} (valores intermedios 0,5 = entre casillas)."),
              ("tabla", ["", "Poder bajo", "Poder alto"], mat)]
        for t in dict.fromkeys(t for t, _ in lim):
            m.append(("p", f"{t}: " + ", ".join(nm for tt, nm in lim if tt == t)))
        m += [("p", "Sin clasificar: " + ", ".join(sin))] if sin else []
        m.append(("h", "Listado", False))
    if cortas:
        m.append(("tabla", cortas, [[f[k] for k in cortas] for f in filas]))
    elif not filas:
        m.append(("p", "Sin elementos."))
    for x, f in zip(items, filas):
        kv = [(k, f[k]) for k in cols if k not in cortas and k not in ("Código", "Título", "Nombre", "Revisión") and f[k].strip()]
        if not cortas or kv:
            nom = f"{f['Código']} — {f.get('Título') or f['Nombre']}" + (f"  [{BORR}]" if f["Revisión"] == BORR else "")
            m += [("h", nom, vista == "decisiones" and (f["Sustituida por"] != "" or x["estado"].lower().startswith("sustitu"))), ("kv", kv + ([("Revisión", f["Revisión"])] if not cortas else []))]
    return m


def docx(m, est, c):
    from docx.shared import RGBColor
    B = X.doc_base(est, {"{fecha}": f"{dt.date.today():%d/%m/%Y}", "{título}": c, "{titulo}": c})
    doc, H = B.doc, B.H
    rojo = lambda r: (setattr(r, "bold", True), setattr(r.font.color, "rgb", RGBColor(0xB0, 0x20, 0x20)))
    for op in m:
        if op[0] == "t":
            H(op[1], 0)
        elif op[0] == "p":
            doc.add_paragraph(op[1])
        elif op[0] == "aviso":
            rojo(doc.add_paragraph().add_run(op[1]))
        elif op[0] == "h":
            h = H(op[1], 1)
            for r in h.runs:
                r.font.strike = op[2]
        elif op[0] == "kv":
            for k, v in op[1]:
                p = doc.add_paragraph()
                p.add_run(f"{k}: ").bold = True
                r = p.add_run(v)
                if v == BORR:
                    rojo(r)
        else:
            t = doc.add_table(rows=1, cols=len(op[1]))
            B.estilo(t, "Table Grid")
            for cel, n in zip(t.rows[0].cells, op[1]):
                cel.text = n
                if cel.paragraphs[0].runs:
                    cel.paragraphs[0].runs[0].bold = True
            for fila in op[2]:
                for cel, v in zip(t.add_row().cells, fila):
                    cel.text = v
                    if v == BORR:
                        rojo(cel.paragraphs[0].runs[0])
    b = io.BytesIO()
    doc.save(b)
    return b.getvalue()


CSS = "h1,h2{break-after:avoid}.aviso{background:#ffe58a;color:#000;padding:8px 12px;border-radius:6px;font-weight:600}.borr{color:#b02020;font-weight:700}td{white-space:pre-line}dt{font-weight:600}"


def html_(m, est, c):
    e, h = html.escape, []
    cel = lambda v: f'<span class="borr">{e(v)}</span>' if v == BORR else e(v)
    for op in m:
        if op[0] == "t":
            h.append(f"<h1>{e(op[1])}</h1>")
        elif op[0] == "p":
            h.append(f'<p class="meta">{e(op[1])}</p>')
        elif op[0] == "aviso":
            h.append(f'<p class="aviso">{e(op[1])}</p>')
        elif op[0] == "h":
            h.append(f"<h2>{'<s>' if op[2] else ''}{e(op[1]).replace(e(BORR), '<span class=borr>' + e(BORR) + '</span>')}{'</s>' if op[2] else ''}</h2>")
        elif op[0] == "kv":
            h.append("<dl>" + "".join(f"<dt>{e(k)}</dt><dd>{cel(v)}</dd>" for k, v in op[1]) + "</dl>")
        else:
            h.append("<table><tr>" + "".join(f"<th>{e(n)}</th>" for n in op[1]) + "</tr>" + "".join("<tr>" + "".join(f"<td>{cel(v)}</td>" for v in f) + "</tr>" for f in op[2]) + "</table>")
    col = (f":root{{--acc:{est['color']};--acc-d:{est['color']}}}" if est and est.get("color") else "")
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>{e(m[0][1])}</title><style>{X.CSS}{CSS}{col}</style></head><body>'
            f'{X.cabecera_estilo(est)}{"".join(h)}</body></html>')


def md(m):
    cel = lambda v: v.replace("|", "\\|").replace("\n", "<br>")
    o = []
    for op in m:
        if op[0] == "t":
            o.append(f"# {op[1]}\n")
        elif op[0] == "p":
            o.append(op[1] + "\n")
        elif op[0] == "aviso":
            o.append(f"> **{op[1]}**\n")
        elif op[0] == "h":
            o.append(f"## {'~~' + op[1] + '~~' if op[2] else op[1]}\n")
        elif op[0] == "kv":
            o.append("\n".join(f"- **{k}:** {v.replace(chr(10), '  ' + chr(10) + '  ')}" for k, v in op[1]) + "\n")
        else:
            o.append("| " + " | ".join(op[1]) + " |\n|" + "---|" * len(op[1]) + "\n" + "\n".join("| " + " | ".join(cel(v) for v in f) + " |" for f in op[2]) + "\n")
    return "\n".join(o)


# ---------- XLSX (stdlib; ponytail: sin estilos más allá de cabecera en negrita; XlsxWriter/openpyxl no están en el entorno sin red) ----------
def xlsx(hojas):
    """{nombre de hoja: (cabecera, filas)} -> bytes de .xlsx: cabecera en negrita e inmovilizada, autofiltro, anchos por contenido."""
    limpia = lambda s: xesc(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(s)))
    col = lambda i: (col(i // 26 - 1) if i >= 26 else "") + chr(65 + i % 26)
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    hs, b = [], io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for n, (cab, filas) in enumerate(hojas.values(), 1):
            filas = [cab] + [list(f) for f in filas]
            w = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{min(60, max(8, max(len(max(str(f[i]).splitlines() or [""], key=len)) for f in filas) + 2))}" customWidth="1"/>' for i in range(len(cab)))
            rows = "".join(f'<row r="{r}">' + "".join(f'<c r="{col(i)}{r}" t="inlineStr" s="{1 if r == 1 else 2}"><is><t xml:space="preserve">{limpia(v)}</t></is></c>' for i, v in enumerate(f)) + "</row>"
                           for r, f in enumerate(filas, 1))
            z.writestr(f"xl/worksheets/sheet{n}.xml", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet {ns}><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
                       f'<cols>{w}</cols><sheetData>{rows}</sheetData><autoFilter ref="A1:{col(len(cab) - 1)}{len(filas)}"/></worksheet>')
            hs.append(n)
        nombres = [re.sub(r"[\[\]:*?/\\]", "_", k)[:31] for k in hojas]
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{n}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for n in hs) + "</Types>")
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{xesc(k)}" sheetId="{n}" r:id="rId{n}"/>' for n, k in zip(hs, nombres)) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{n}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{n}.xml"/>' for n in hs)
                   + f'<Relationship Id="rId{len(hs) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr("xl/styles.xml", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet {ns}><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
                   '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs>'
                   '<cellXfs count="3"><xf/><xf fontId="1" applyFont="1"/><xf applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf></cellXfs></styleSheet>')
    return b.getvalue()


# ---------- feature (Gherkin), Jira, Azure ----------
def feature(c, items, filas, borrador):
    o = [f"# Historias de «{c}» · {dt.date.today():%Y-%m-%d}" + (" · incluye BORRADOR (sin revisar)" if borrador else " · solo aprobadas"), ""]
    grupos = {}
    for x, f in zip(items, filas):
        grupos.setdefault(x["campos"].get("epica") or f"\0{x['id']}", []).append((x, f))
    for ep, hus in grupos.items():
        o.append(f"Feature: {ep if ep[0] != chr(0) else hus[0][1]['Título']}")
        for x, f in hus:
            k = x["campos"]
            o += [f"  # {f['Código']} {f['Título']}" + (f" [{BORR}]" if f["Revisión"] == BORR else "")]
            if k.get("como") or k.get("quiero") or k.get("para"):
                o += [f"  # Como {k.get('como', '')} quiero {k.get('quiero', '')} para {k.get('para', '')}"]
            for e, prop, ls in _gherkin(k.get("criterios")):
                tags = ["@" + f["Código"]] + (["@borrador"] if f["Revisión"] == BORR else []) + (["@propuesta"] if prop else [])
                o += ["", "  " + " ".join(tags), f"  Scenario: {e or f['Título']}"] + [f"    {kw} {t}" for kw, t in ls]
        o.append("")
    return "\n".join(o)


PRIO = {"must": ("Highest", 1), "should": ("High", 2), "could": ("Medium", 3), "won": ("Low", 4)}


def _prio(p):
    return next((v for k, v in PRIO.items() if p.strip().lower().startswith(k)), ("", ""))


def _gtxt(x):
    return "\n".join(f"Scenario: {e or 'Escenario'}{' (propuesta)' if p else ''}\n" + "\n".join(f"{kw} {t}" for kw, t in ls) for e, p, ls in _gherkin(x["campos"].get("criterios")))


def csv_tracker(vista, azure, items, filas):
    rows = []
    for x, f in zip(items, filas):
        borr = f["Revisión"] == BORR
        desc = "\n\n".join(filter(None, [f"[{BORR}]" if borr else "", f["Detalle"] if vista == "requisitos" else f"Como {f['Como']} quiero {f['Quiero']} para {f['Para']}",
                                         "" if azure or vista == "requisitos" else _gtxt(x), f"Origen: {f['Origen']}"]))
        pr = _prio(x["prioridad"])
        tags = [f["Código"]] + (["borrador"] if borr else [])
        if azure:
            rows.append(["Requirement" if vista == "requisitos" else "User Story", f"{f['Código']} {f['Título']}", desc, _gtxt(x) if vista == "historias" else f["Criterios"], ";".join(tags), pr[1],
                         f["Puntos"] if vista == "historias" else ""])
        else:
            rows.append([f"{f['Código']} {f['Título']}", "Epic" if vista == "requisitos" else "Story", desc, pr[0], " ".join(tags), f["Puntos"] if vista == "historias" else "",
                         f["Título"] if vista == "requisitos" else "", f["Épica"] if vista == "historias" else ""])
    return X._csv(["Work Item Type", "Title", "Description", "Acceptance Criteria", "Tags", "Priority", "Story Points"] if azure else
                  ["Summary", "Issue Type", "Description", "Priority", "Labels", "Story Points", "Epic Name", "Epic Link"], rows)


# ---------- despacho ----------
def exportar(c, vista, fmt, borrador=True, docs=(), estilo=None):
    """-> (bytes, nombre de fichero, tipo MIME). ValueError: vista o formato desconocido; exportar.SinNavegador: pdf sin navegador.
    docs: carpetas.docs() de la carpeta (título y fecha de la reunión de cada cita)."""
    if vista not in TIPO:
        raise ValueError(f"Vista desconocida: {vista}")
    if fmt not in formatos(vista):
        raise ValueError(f"Formato desconocido para {vista}: {fmt}")
    items, filas = cargar(c, vista, borrador, docs)
    cab = COLS[vista]
    est = X.estilo_para({"carpeta": c}, estilo) if fmt in ("docx", "pdf") else None
    if fmt == "docx":
        d = docx(modelo(c, vista, items, filas, borrador), est, c)
    elif fmt == "pdf":
        d = X.pdf_html(html_(modelo(c, vista, items, filas, borrador), est, c))
    elif fmt == "xlsx":
        d = xlsx({TITULO[vista]: (cab, [[f[k] for k in cab] for f in filas])})
    elif fmt == "csv":
        d = X._csv(cab, [[f[k] for k in cab] for f in filas])
    elif fmt == "md":
        d = md(modelo(c, vista, items, filas, borrador))
    elif fmt == "json":
        d = json.dumps({"proyecto": c, "vista": vista, "generado": dt.datetime.now().isoformat(timespec="seconds"), "borrador": borrador,
                        "items": [{"codigo": x["codigo"], "titulo": x["titulo"], "detalle": x["detalle"], "estado": x["estado"], "prioridad": x["prioridad"], "revision": x["revision"],
                                   "borrador": x["revision"] == "propuesto", "campos": x["campos"], "origen": f["Origen"], "citas": x["citas"], "relaciones": x["relaciones"]}
                                  for x, f in zip(items, filas)]}, ensure_ascii=False, indent=1)
    elif fmt == "feature":
        d = feature(c, items, filas, borrador)
    else:
        d = csv_tracker(vista, fmt == "csv_azure", items, filas)
    slug = re.sub(r'[\\/:*?"<>|\n]+', "_", c).strip() or "proyecto"
    return (d.encode() if isinstance(d, str) else d), f"{slug}-{vista}.{EXT[fmt]}", MIME[fmt]
