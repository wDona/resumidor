"""Documentos (PDF, Markdown, TXT, DOCX, HTML) e imágenes como «transcripción»: segmentos {s, e, text, loc} donde loc dice de
dónde sale cada trozo («p. 12», «§ Diseño › API», «¶ 3», «imagen», «descripción») y s/e son una marca de tiempo ficticia a CPS
letras por segundo (como el habla). Así el map/reduce, la verificación de citas, el RAG, el registro y los ritmos de la ETA
funcionan sin cambios; al mostrar una cita se enseña su loc en vez del [mm:ss].
PDF: texto con pypdfium2; las páginas sin capa de texto (escaneadas) se renderizan y pasan por RapidOCR, como las capturas."""
import functools
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import numpy as np

import pipeline as P
import transcripts

TEXTO = (".pdf", ".md", ".markdown", ".txt", ".docx", ".html", ".htm")
IMAGEN = (".png", ".jpg", ".jpeg", ".webp")
EXT = TEXTO + IMAGEN
FORMATO = {".pdf": "PDF", ".md": "Markdown", ".markdown": "Markdown", ".txt": "Texto", ".docx": "DOCX", ".html": "HTML", ".htm": "HTML"}
CPS = 15         # letras por «segundo»: ~2,5 palabras/s, el ritmo del habla (los ritmos medidos del map valen igual)
TOPE = 59000     # s: las marcas del esquema del map llegan a 999:59; un documento enorme comprime su tiempo ficticio para caber
TROZO = 300      # letras por segmento (~20 s ficticios: como los del ASR)
MIN_TXT = 20     # letras/cifras por debajo de las cuales una página del PDF se toma por escaneada (OCR)


def tipo(path):
    """pdf | imagen | texto (lo que muestra la interfaz)."""
    ext = Path(path).suffix.lower()
    return "pdf" if ext == ".pdf" else "imagen" if ext in IMAGEN else "texto"


@functools.cache
def _motor():
    from rapidocr_onnxruntime import RapidOCR
    rec = P.model_file(P.OCR_REC)  # None: modelo de serie
    return RapidOCR(intra_op_num_threads=P.PHYS, inter_op_num_threads=1, **({"rec_model_path": str(rec)} if rec else {}))


def ocr(im):
    """Líneas de texto de una imagen PIL (mismo OCR y limpieza que las capturas del vídeo)."""
    res, _ = _motor()(np.ascontiguousarray(np.asarray(im.convert("RGB"))[:, :, ::-1]))
    return [x for _, t, sc in res or [] if float(sc) > 0.6 and (x := P.clean_ocr(t))]


def _trozos(texto, n=TROZO):
    """Trozos de ~n letras que acaban en fin de frase (o de 2n como mucho: tablas, texto sin puntos)."""
    out, cur, k = [], [], 0
    for w in texto.split():
        cur.append(w)
        k += len(w) + 1
        if k >= 2 * n or k >= n and w[-1] in ".!?…:;":
            out.append(" ".join(cur))
            cur, k = [], 0
    return out + [" ".join(cur)] * bool(cur)


def segmentos(partes):
    """[(loc, texto)] -> [{s, e, text, loc}] con tiempo ficticio proporcional a las letras. Inicios enteros y distintos: la marca
    [mm:ss] (que trunca al segundo) lleva siempre a su trozo y a su loc."""
    tr = [(loc, x) for loc, t in partes for x in _trozos(t)]
    cps = max(CPS, sum(len(x) + 1 for _, x in tr) / TOPE)
    out, a = [], 0.0
    for loc, x in tr:
        s = max(round(a), out[-1]["s"] + 1 if out else 0)
        a += (len(x) + 1) / cps
        out.append({"s": s, "e": max(round(a), s + 1), "text": x, "loc": loc})
    return out


def _md(t):
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    return re.sub(r"^\s*(?:[>*+-]|\d+[.)])\s+|[*`]|^\s*\|?[\s:|-]*-{3,}[\s:|-]*$", "", t).replace("|", " ")


def secciones(lineas):
    """Líneas estilo Markdown -> [(«§ Título › Subtítulo», texto)]: cada encabezado abre sección (su texto entra en ella)."""
    ruta, out, buf = [], [], []

    def corta():
        if t := "\n".join(buf).strip():
            out.append(("§ " + " › ".join(ruta) if ruta else "§ Inicio", t))
        buf.clear()
    fence = False
    for l in lineas:
        if l.strip().startswith("```"):
            fence = not fence
            continue
        if not fence and (m := re.match(r"\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", l)):
            corta()
            ruta[len(m[1]) - 1:] = [_md(m[2]).strip()]
            buf.append(ruta[-1] + ".")
        else:
            buf.append(l if fence else _md(l))
    corta()
    return out


class _Html(HTMLParser):
    BLOQUE = {"p", "div", "li", "br", "tr", "td", "th", "section", "article", "header", "footer", "ul", "ol", "table", "blockquote", "pre", "title"}

    def __init__(self):
        super().__init__()
        self.out, self.oculto = [""], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.oculto += 1
        elif re.fullmatch(r"h[1-6]", tag):
            self.out.append("#" * int(tag[1]) + " ")
        elif tag in self.BLOQUE:
            self.out.append("")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.oculto = max(0, self.oculto - 1)
        elif tag in self.BLOQUE or re.fullmatch(r"h[1-6]", tag):
            self.out.append("")

    def handle_data(self, d):
        if not self.oculto:
            self.out[-1] += re.sub(r"\s+", " ", d)


def _docx(path):
    """Párrafos y tablas en orden; los estilos de título (Heading N / Title) pasan a encabezados Markdown."""
    import docx
    from docx.table import Table
    for b in docx.Document(str(path)).iter_inner_content():
        if isinstance(b, Table):
            yield from (" | ".join(dict.fromkeys(c.text.strip() for c in r.cells)) for r in b.rows)
        else:
            m = re.fullmatch(r"(?:Heading (\d)|Title)", b.style.name if b.style is not None else "")
            yield ("#" * int(m[1] or 1) + " " if m else "") + b.text


def _texto(path):
    raw = Path(path).read_bytes()
    try:
        t = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        t = raw.decode("cp1252", "replace")  # TXT de Windows antiguos
    return transcripts.NFC(t.replace("\r\n", "\n").replace("\r", "\n"))


def _pdf(path, cb):
    import pypdfium2 as pdfium
    try:
        pdf = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as ex:
        raise RuntimeError(f"No se puede abrir el PDF (¿protegido con contraseña o dañado?): {ex}")
    partes, escaneadas = [], []
    try:
        n = len(pdf)
        for i in range(n):
            cb(i / n, f"Leyendo página {i + 1}/{n}…")
            pg = pdf[i]
            t = pg.get_textpage().get_text_range()
            if sum(c.isalnum() for c in t) < MIN_TXT:  # sin capa de texto: se lee la imagen
                t = "\n".join(ocr(pg.render(scale=2).to_pil()))
                escaneadas.append(i + 1)
            partes.append((f"p. {i + 1}", re.sub(r"(\w)-\r?\n(?=[a-záéíóúüñ])", r"\1", transcripts.NFC(t))))
    finally:
        pdf.close()
    return partes, {"paginas": n, "ocr": escaneadas}


def _partes_imagen(imp):
    return [("descripción", imp["descripcion"]), ("descripción IA", imp["descripcion_ia"]), ("imagen", imp["ocr_texto"])]


def leer(path, cb=lambda f, m: None, descripcion="", vision=None):
    """Documento o imagen -> {"language", "segments", "importada"} (lo mismo que una transcripción importada, más tipo y páginas).
    Imagen: OCR + descripción del usuario + descripción con IA si hay `vision` (vision.elegir(); si falla, solo aviso)."""
    import vision as V
    p = Path(path)
    ext, extra = p.suffix.lower(), {}
    descripcion = (descripcion or "").strip()
    partes = [("descripción", descripcion)] if descripcion else []
    if ext == ".pdf":
        pp, extra = _pdf(p, cb)
        partes += pp
    elif ext in IMAGEN:
        from PIL import Image, ImageOps
        cb(0.1, "Leyendo el texto de la imagen…")
        with Image.open(p) as im:
            extra = {"descripcion": descripcion, "descripcion_ia": "", "ocr_texto": "\n".join(ocr(ImageOps.exif_transpose(im))), "vision": V.estado(vision)}
        if vision:
            cb(0.5, "Describiendo la imagen con IA…")
            try:
                with V.sesion(vision) as desc:
                    extra["descripcion_ia"] = desc(p)
            except Exception as ex:  # la imagen sigue entrando con su OCR y la descripción del usuario
                extra["aviso"] = f"No se pudo describir la imagen con IA: {ex}"
        partes = _partes_imagen(extra)
    elif ext == ".txt":
        partes += [(f"¶ {i}", x) for i, x in enumerate((x for x in re.split(r"\n\s*\n", _texto(p)) if x.strip()), 1)]
    elif ext == ".docx":
        partes += secciones(transcripts.NFC(x) for x in _docx(p))
    elif ext in (".html", ".htm"):
        h = _Html()
        h.feed(_texto(p))
        partes += secciones(h.out)
    elif ext in (".md", ".markdown"):
        partes += secciones(_texto(p).split("\n"))
    else:
        raise ValueError(f"Formato no admitido: {ext}")
    segs = segmentos(partes)
    if not segs:
        raise RuntimeError("No se ha encontrado texto en el documento" + (": añade una descripción a la imagen" if ext in IMAGEN else ""))
    return {"language": transcripts.language(segs), "segments": segs,
            "importada": {"fuente": p.name, "formato": FORMATO.get(ext, "Imagen"), "tipo": tipo(p), "segmentos": len(segs), "hablantes": [],
                          "desfase": 0, "aviso": None, **extra}}


def reescribir(tf, **campos):
    """Cambia descripcion / descripcion_ia de una imagen ya leída (transcript_*.json) y rehace sus segmentos: Buscar y Preguntar lo ven
    al momento (el índice se pone al día por la fecha del fichero). -> importada."""
    tr = json.loads(Path(tf).read_text())
    imp = tr["importada"]
    if imp.get("tipo") != "imagen":
        raise ValueError("Solo las imágenes llevan descripción")
    imp.update({k: str(v or "").strip()[:2000] for k, v in campos.items() if k in ("descripcion", "descripcion_ia")})
    segs = segmentos(_partes_imagen(imp))
    if not segs:
        raise ValueError("La imagen se quedaría sin texto: escribe una descripción")
    tr["segments"], imp["segmentos"] = segs, len(segs)
    Path(tf).write_text(json.dumps(tr, ensure_ascii=False))
    return imp


def etiqueta(locs):
    """[[s, loc], ...] (acta.json["locs"]) -> fn(t) que da la loc del trozo en t, o el [mm:ss] de siempre si no hay locs."""
    if not locs:
        return P.fmt
    import bisect
    at = [s for s, _ in locs]
    return lambda t: locs[max(0, bisect.bisect_right(at, t + 0.99) - 1)][1]


def locs(segments):
    """Dónde empieza cada loc ([[s, loc], ...]) o None si los segmentos no vienen de un documento."""
    if not segments or "loc" not in segments[0]:
        return None
    return [[s["s"], s["loc"]] for i, s in enumerate(segments) if not i or s["loc"] != segments[i - 1]["loc"]]
