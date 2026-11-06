"""Investigaciones de un proyecto: documentos en Markdown escritos por una persona o por un agente (agentes.py), con una guía de
redacción opcional (GUIA) y exportación a .md o .docx con el estilo de organización del proyecto (exportar.doc_base).
Se guardan en WORK/investigaciones/<proyecto>/<id>.json. app.py monta el router."""

import hashlib
import io
import json
import re
import time
import uuid
import urllib.parse

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, Response

import exportar
import pipeline as P
import registro

router = APIRouter()
A = None  # el módulo app (lo pone app.py)

GUIA = """# Guía para redactar una investigación (opcional)

Úsala si no te piden otro formato. Escribe en Markdown; se exporta a Word con el estilo del proyecto.

## Estructura
1. **Problema**: qué pasa, por qué importa y a quién afecta, en uno a tres párrafos. Solo si quien pide la investigación lo ha
   planteado antes o es evidente; si no, se empieza por las formas de resolverlo.
2. **Formas de resolverlo**: los enfoques posibles (no productos). Un párrafo corto por enfoque, con la idea en negrita al principio: «**Mantén conversaciones limpias:** …».
3. **Soluciones exploradas**: qué hace cada una, enlace y dato clave (ahorro, coste, madurez). Si son muchas, una tabla `Nombre | Enlace | Resumen`. Riesgos solo si son importantes; los pequeños o irrelevantes no se mencionan.
4. **A tener en cuenta**: conflictos, solapes, costes ocultos o incompatibilidades entre soluciones. Solo si los hay.
5. **Propuesta**: qué recomiendas y cuándo conviene cada alternativa.
6. **Extras** (opcional): alternativas descartadas, cómo medir el resultado, enlaces de interés.

## Estilo
- Cada frase aporta un dato o contexto. Sin introducciones genéricas ni conclusiones que repiten lo ya dicho.
- Secciones pequeñas con títulos que dicen de qué hablan (`##`, `###`). Párrafos de una a cuatro frases.
- Tablas para comparar, listas para enumerar, párrafos para razonar.
- Cifras con su origen; si no están verificadas: «declarado por el autor».
- Enlaces completos. Una nota al pie de tabla (`*Los ahorros son declarados por los autores.`) vale más que repetirlo en cada fila.

## Esqueleto
```markdown
# <Título>

<Contexto en una o dos frases: por qué se investiga ahora.>

## Problema
<solo si se planteó antes o es evidente>

## Formas de resolverlo
**<Enfoque 1>:** <…>

**<Enfoque 2>:** <…>

## Soluciones exploradas
| Nombre | Enlace | Resumen |
|---|---|---|
| <…> | <https://…> | <…> |

### A tener en cuenta
- <conflicto o riesgo importante>

## Propuesta
<…>

## Extras
<…>
```
"""


def _dir(c):
    return P.WORK / "investigaciones" / hashlib.sha1(c.encode()).hexdigest()[:16]


def _leer(c, iid):
    f = _dir(c) / f"{iid}.json"
    if not re.fullmatch(r"[0-9a-f]{10}", iid) or not f.is_file():
        raise HTTPException(404, "No existe esa investigación")
    return json.loads(f.read_text(encoding="utf-8"))


def listar(c):
    xs = [json.loads(f.read_text(encoding="utf-8")) for f in _dir(c).glob("*.json")] if _dir(c).is_dir() else []
    return [{k: x[k] for k in ("id", "titulo", "autor", "t")} for x in sorted(xs, key=lambda x: -x["t"])]


def guardar(c, md, titulo="", iid=None):
    md = str(md or "").strip()
    if not md:
        raise ValueError("La investigación está vacía")
    if len(md) > 2_000_000:
        raise ValueError("Demasiado larga")
    titulo = str(titulo or "").strip()[:200] or next((ln[2:].strip() for ln in md.splitlines() if ln.startswith("# ")), "") or "Investigación"
    x = _leer(c, iid) if iid else {"id": uuid.uuid4().hex[:10], "creado": int(time.time())}
    x.update(titulo=titulo, md=md, autor=registro.autor() or "", t=int(time.time()))
    _dir(c).mkdir(parents=True, exist_ok=True)
    (_dir(c) / f"{x['id']}.json").write_text(json.dumps(x, ensure_ascii=False), encoding="utf-8")
    return x


# ---------- Markdown -> Word ----------
INLINE = re.compile(r"(\*\*[^*]+\*\*|__[^_]+__|\*[^*\s][^*]*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|<https?://[^>\s]+>|https?://[^\s)|]+)")


def _enlace(par, texto, url):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE as RT

    rid = par.part.relate_to(url, RT.HYPERLINK, is_external=True)
    h = OxmlElement("w:hyperlink")
    h.set(qn("r:id"), rid)
    r, rp = OxmlElement("w:r"), OxmlElement("w:rPr")
    for tag, val in (("w:color", "0563C1"), ("w:u", "single")):
        e = OxmlElement(tag)
        e.set(qn("w:val"), val)
        rp.append(e)
    t = OxmlElement("w:t")
    t.text = texto
    t.set(qn("xml:space"), "preserve")
    r.append(rp)
    r.append(t)
    h.append(r)
    par._p.append(h)


def _inline(par, txt):
    for parte in INLINE.split(txt):
        if not parte:
            continue
        if parte[:2] in ("**", "__") and parte[-2:] == parte[:2] and len(parte) > 4:
            _inline_fmt(par, parte[2:-2], bold=True)
        elif parte[0] == "*" and parte[-1] == "*" and len(parte) > 2:
            _inline_fmt(par, parte[1:-1], italic=True)
        elif parte[0] == "`" and parte[-1] == "`":
            par.add_run(parte[1:-1]).font.name = "Consolas"
        elif parte[0] == "[" and (m := re.fullmatch(r"\[([^\]]+)\]\(([^)\s]+)\)", parte)):
            _enlace(par, m[1], m[2]) if m[2].startswith(("http://", "https://", "mailto:")) else par.add_run(m[1])
        elif parte[0] == "<" and parte[-1] == ">":
            _enlace(par, parte[1:-1], parte[1:-1])
        elif parte.startswith(("http://", "https://")):
            _enlace(par, parte, parte)
        else:
            par.add_run(parte)


def _inline_fmt(par, txt, bold=False, italic=False):
    n = len(par.runs)
    _inline(par, txt)
    for r in par.runs[n:]:
        r.bold = r.bold or bold
        r.italic = r.italic or italic


def _sombra(cel, color="E7ECF3"):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear")
    sh.set(qn("w:fill"), color)
    cel._tc.get_or_add_tcPr().append(sh)


def _anchos(t, filas, total=6.3):
    """Columnas según lo que llevan (la más larga de cada una, con tope), no todas iguales."""
    from docx.shared import Inches

    n = len(filas[0])
    largo = [min(max(len(re.sub(r"\]\([^)]*\)|[*`<>]", "", f[i])) if i < len(f) else 0 for f in filas), 60) + 4 for i in range(n)]
    for fila in t.rows:
        for cel, k in zip(fila.cells, largo):
            cel.width = Inches(total * k / sum(largo))


def _celdas(ln):
    return [x.strip() for x in ln.strip().strip("|").split("|")]


def docx(md, est=None, titulo=""):
    """Markdown (títulos, párrafos, negrita/cursiva/código, enlaces, listas, tablas, citas, bloques de código) -> bytes de .docx."""
    B = exportar.doc_base(est, {"{fecha}": time.strftime("%d/%m/%Y"), "{título}": titulo, "{titulo}": titulo})
    doc, H, estilo = B.doc, B.H, B.estilo
    lineas, i, par = md.replace("\r\n", "\n").split("\n"), 0, []

    def suelta():
        if par:
            _inline(doc.add_paragraph(), " ".join(par))
            par.clear()

    while i < len(lineas):
        ln = lineas[i]
        s = ln.strip()
        if s.startswith("```"):
            suelta()
            j = i + 1
            while j < len(lineas) and not lineas[j].strip().startswith("```"):
                j += 1
            p = doc.add_paragraph()
            p.add_run("\n".join(lineas[i + 1 : j])).font.name = "Consolas"
            i = j + 1
            continue
        if m := re.match(r"(#{1,4})\s+(.*)", s):
            suelta()
            H(m[2].strip(), 0 if len(m[1]) == 1 else len(m[1]) - 1)
        elif s.startswith("|") and i + 1 < len(lineas) and re.fullmatch(r"\|?\s*:?-{2,}.*", lineas[i + 1].strip()):
            suelta()
            cab, filas = _celdas(s), []
            i += 2
            while i < len(lineas) and lineas[i].strip().startswith("|"):
                filas.append(_celdas(lineas[i]))
                i += 1
            t = doc.add_table(rows=1, cols=len(cab))
            estilo(t, "Table Grid")
            for cel, v in zip(t.rows[0].cells, cab):
                _inline_fmt(cel.paragraphs[0], v, bold=True)
            for f in filas:
                for cel, v in zip(t.add_row().cells, f + [""] * (len(cab) - len(f))):
                    _inline(cel.paragraphs[0], v)
            _anchos(t, [cab, *filas])
            for cel in t.rows[0].cells:
                _sombra(cel)  # después del ancho: Word quiere w:tcW antes que w:shd
            doc.add_paragraph()
            continue
        elif m := re.match(r"(\s*)([-*+]|\d+[.)])\s+(.*)", ln):
            suelta()
            nivel = min(len(m[1].expandtabs(4)) // 2, 2)
            nombre = ("List Number" if m[2][0].isdigit() else "List Bullet") + (f" {nivel + 1}" if nivel else "")
            p = estilo(doc.add_paragraph(), nombre)
            if not p.style or p.style.name != nombre:
                p.add_run(("    " * nivel) + ("• " if not m[2][0].isdigit() else m[2] + " "))
            _inline(p, m[3])
        elif s.startswith(">"):
            suelta()
            _inline(estilo(doc.add_paragraph(), "Quote"), s.lstrip("> ").strip())
        elif re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s) or not s:
            suelta()
        else:
            par.append(s)
        i += 1
    suelta()
    b = io.BytesIO()
    doc.save(b)
    return b.getvalue()


# ---------- rutas ----------
@router.get("/api/investigaciones/guia", response_class=PlainTextResponse)
def api_guia():
    """Guía de redacción (opcional): estructura (Problema) · Formas de resolverlo · Soluciones exploradas · Propuesta · Extras, y estilo."""
    return GUIA


@router.get("/api/investigaciones")
def api_listar(c: str):
    return listar(A._c({"c": c}))


@router.post("/api/investigaciones")
def api_guardar(d: dict):
    """{c, markdown, titulo?, id?}: guarda una investigación nueva o sustituye la del id."""
    c = A._c(d)
    try:
        x = guardar(c, d.get("markdown"), d.get("titulo"), d.get("id"))
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    return {k: x[k] for k in ("id", "titulo", "autor", "t")}


@router.get("/api/investigaciones/{iid}")
def api_ver(iid: str, c: str, fmt: str = "json", estilo: str | None = None):
    """fmt: json (con el Markdown), md o docx (estilo de organización: el pedido o el del proyecto)."""
    c = A._c({"c": c})
    x = _leer(c, iid)
    if fmt == "json":
        return x
    nombre = re.sub(r'[\\/:*?"<>|]+', "", x["titulo"])[:80] or "investigacion"
    if fmt == "md":
        datos, mime = x["md"].encode(), "text/markdown; charset=utf-8"
    elif fmt == "docx":
        datos = docx(x["md"], exportar.estilo_para({"carpeta": c}, estilo), x["titulo"])
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        raise HTTPException(400, "Formato: json, md o docx")
    return Response(datos, media_type=mime, headers={"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(f"{nombre}.{fmt}")})


@router.delete("/api/investigaciones/{iid}")
def api_borrar(iid: str, c: str):
    c = A._c({"c": c})
    _leer(c, iid)
    (_dir(c) / f"{iid}.json").unlink()
    return {"ok": True}
