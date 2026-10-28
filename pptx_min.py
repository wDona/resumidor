"""PPTX mínimo con la biblioteca estándar (zipfile + XML): python-pptx no está disponible sin red (D1 queda así).
16:9, un patrón y un diseño en blanco; diapositivas con cuadros de texto, rectángulos de color y tablas. Sin gráficos.
Cada constructor (portada, semaforos, tabla, lista) devuelve la lista de formas (XML) de una diapositiva; pptx(diapositivas) -> bytes."""
import io
import re
import zipfile
from xml.sax.saxutils import escape

W, H = 12192000, 6858000  # 16:9 en EMU
CM = 360000
NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')
X0 = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
CT = "application/vnd.openxmlformats-officedocument."
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"


def _t(s):
    return escape(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(s)))


def _run(txt, sz=1600, b=False, color="1F2933"):
    return f'<a:r><a:rPr lang="es-ES" sz="{sz}" b="{int(b)}" dirty="0"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill></a:rPr><a:t>{_t(txt)}</a:t></a:r>'


def _par(txt, sz=1600, b=False, color="1F2933", bala=False, alg="l"):
    ppr = f'<a:pPr marL="285750" indent="-285750" algn="{alg}"><a:buFont typeface="Arial"/><a:buChar char="•"/></a:pPr>' if bala else f'<a:pPr algn="{alg}"><a:buNone/></a:pPr>'
    return f"<a:p>{ppr}{_run(txt, sz, b, color)}</a:p>"


class _Ids:
    n = 1


def _sp(x, y, w, h, pars, fill=None, anchor="t", prst="rect"):
    _Ids.n += 1
    f = f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill><a:ln><a:noFill/></a:ln>' if fill else "<a:noFill/>"
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{_Ids.n}" name="Forma {_Ids.n}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{int(x)}" y="{int(y)}"/>'
            f'<a:ext cx="{int(w)}" cy="{int(h)}"/></a:xfrm><a:prstGeom prst="{prst}"><a:avLst/></a:prstGeom>{f}</p:spPr><p:txBody><a:bodyPr wrap="square" '
            f'lIns="91440" tIns="45720" rIns="91440" bIns="45720" anchor="{anchor}"><a:normAutofit/></a:bodyPr><a:lstStyle/>{"".join(pars) or "<a:p/>"}</p:txBody></p:sp>')


def _titulo(t):
    return _sp(CM * 1.5, CM * 0.8, W - CM * 3, CM * 2, [_par(t, 3000, True, "1D5FD1")], anchor="b")


def portada(titulo, lineas, aviso=""):
    s = [_sp(0, 0, W, CM * 0.5, [], fill="1D5FD1"), _sp(CM * 2, CM * 5, W - CM * 4, CM * 3.5, [_par(titulo, 4000, True, "1D5FD1")], anchor="b"),
         _sp(CM * 2, CM * 9, W - CM * 4, CM * 3, [_par(x, 1800, color="616E7C") for x in lineas])]
    if aviso:
        s.append(_sp(CM * 2, CM * 13.5, W - CM * 4, CM * 1.6, [_par(aviso, 1600, True, "000000")], fill="FFE58A", anchor="ctr"))
    return s


def semaforos(titulo, items):
    """items: [(dimensión, color, hex, etiqueta con forma, justificación)]: una tarjeta por dimensión (color + forma + texto)."""
    s, n = [_titulo(titulo)], len(items)
    w = (W - CM * 3 - CM * 0.5 * (n - 1)) / n
    for j, (d, col, hx, lab, just) in enumerate(items):
        x = CM * 1.5 + j * (w + CM * 0.5)
        tinta = "000000" if col == "ambar" else "FFFFFF"
        s.append(_sp(x, CM * 3.6, w, CM * 2.6, [_par(d, 2000, True, tinta, alg="ctr"), _par(lab, 1600, True, tinta, alg="ctr")], fill=hx, anchor="ctr", prst="roundRect"))
        s.append(_sp(x, CM * 6.5, w, CM * 10, [_par(just, 1300, color="3E4C59")]))
    return s


def lista(titulo, frases):
    return [_titulo(titulo), _sp(CM * 1.5, CM * 3.4, W - CM * 3, H - CM * 4.4, [_par(f, 1800, bala=True) for f in frases[:12]])]


def tabla(titulo, cab, filas):
    _Ids.n += 1
    filas = filas[:14]
    ws = [max(4, min(60, max(len(str(f[i])) for f in [cab] + filas))) for i in range(len(cab))]
    tw = W - CM * 3
    cols = "".join(f'<a:gridCol w="{int(tw * w / sum(ws))}"/>' for w in ws)
    sz = 1400 if len(filas) <= 8 else 1100
    cel = lambda v, b, fill: (f'<a:tc><a:txBody><a:bodyPr/><a:lstStyle/>{_par(v, sz, b, "FFFFFF" if fill else "1F2933")}</a:txBody><a:tcPr>'
                              + (f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>' if fill else "") + "</a:tcPr></a:tc>")
    rows = f'<a:tr h="{CM}">' + "".join(cel(v, True, "1D5FD1") for v in cab) + "</a:tr>" + "".join(f'<a:tr h="{CM}">' + "".join(cel(v, False, None) for v in f) + "</a:tr>" for f in filas)
    return [_titulo(titulo), f'<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="{_Ids.n}" name="Tabla {_Ids.n}"/><p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr>'
            f'<p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="{int(CM * 1.5)}" y="{int(CM * 3.4)}"/><a:ext cx="{int(tw)}" cy="{CM * (len(filas) + 1)}"/></p:xfrm><a:graphic>'
            f'<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl><a:tblPr firstRow="1" bandRow="1"/><a:tblGrid>{cols}</a:tblGrid>{rows}</a:tbl>'
            "</a:graphicData></a:graphic></p:graphicFrame>"]


VACIO = '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
CLR = "".join(f'<a:{k}><a:srgbClr val="{v}"/></a:{k}>' for k, v in (("dk1", "000000"), ("lt1", "FFFFFF"), ("dk2", "1F2933"), ("lt2", "F4F5F7"), ("accent1", "1D5FD1"), ("accent2", "E08A00"),
                                                                    ("accent3", "2E9D5B"), ("accent4", "B03A8C"), ("accent5", "6B7A8F"), ("accent6", "C0392B"), ("hlink", "1D5FD1"), ("folHlink", "6B7A8F")))
FILL = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
TEMA = (f'{X0}<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Actas"><a:themeElements><a:clrScheme name="Actas">{CLR}</a:clrScheme>'
        '<a:fontScheme name="Actas"><a:majorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
        f'<a:fmtScheme name="Actas"><a:fillStyleLst>{FILL * 3}</a:fillStyleLst><a:lnStyleLst>' + f'<a:ln w="9525">{FILL}</a:ln>' * 3 +
        '</a:lnStyleLst><a:effectStyleLst>' + '<a:effectStyle><a:effectLst/></a:effectStyle>' * 3 + f'</a:effectStyleLst><a:bgFillStyleLst>{FILL * 3}</a:bgFillStyleLst></a:fmtScheme>'
        '</a:themeElements><a:objectDefaults/><a:extraClrSchemeLst/></a:theme>')
MAPA = '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'


def _rels(*rs):
    return (f'{X0}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(f'<Relationship Id="rId{i}" Type="{REL}{t}" Target="{d}"/>' for i, (t, d) in enumerate(rs, 1)) + "</Relationships>")


def pptx(diapositivas):
    """[[forma XML]] -> bytes de .pptx."""
    n = len(diapositivas)
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", f'{X0}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   f'<Default Extension="xml" ContentType="application/xml"/><Override PartName="/ppt/presentation.xml" ContentType="{CT}presentationml.presentation.main+xml"/>'
                   f'<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="{CT}presentationml.slideMaster+xml"/><Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="{CT}presentationml.slideLayout+xml"/>'
                   f'<Override PartName="/ppt/theme/theme1.xml" ContentType="{CT}theme+xml"/><Override PartName="/ppt/presProps.xml" ContentType="{CT}presentationml.presProps+xml"/>'
                   f'<Override PartName="/ppt/viewProps.xml" ContentType="{CT}presentationml.viewProps+xml"/><Override PartName="/ppt/tableStyles.xml" ContentType="{CT}presentationml.tableStyles+xml"/>'
                   + "".join(f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="{CT}presentationml.slide+xml"/>' for i in range(1, n + 1)) + "</Types>")
        z.writestr("_rels/.rels", _rels(("officeDocument", "ppt/presentation.xml")))
        z.writestr("ppt/presentation.xml", f'{X0}<p:presentation {NS} saveSubsetFonts="1"><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst><p:sldIdLst>'
                   + "".join(f'<p:sldId id="{255 + i}" r:id="rId{4 + i}"/>' for i in range(1, n + 1)) + f'</p:sldIdLst><p:sldSz cx="{W}" cy="{H}"/><p:notesSz cx="6858000" cy="9144000"/>'
                   '<p:defaultTextStyle/></p:presentation>')
        z.writestr("ppt/_rels/presentation.xml.rels", _rels(("slideMaster", "slideMasters/slideMaster1.xml"), ("theme", "theme/theme1.xml"), ("presProps", "presProps.xml"),
                                                            ("viewProps", "viewProps.xml"), ("tableStyles", "tableStyles.xml"), *(("slide", f"slides/slide{i}.xml") for i in range(1, n + 1))))
        z.writestr("ppt/presProps.xml", f"{X0}<p:presentationPr {NS}/>")
        z.writestr("ppt/viewProps.xml", f"{X0}<p:viewPr {NS}/>")
        z.writestr("ppt/tableStyles.xml", f'{X0}<a:tblStyleLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" def="{{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}}"/>')
        z.writestr("ppt/theme/theme1.xml", TEMA)
        z.writestr("ppt/slideMasters/slideMaster1.xml", f'{X0}<p:sldMaster {NS}><p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg><p:spTree>{VACIO}</p:spTree></p:cSld>'
                   f'{MAPA}<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst><p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles></p:sldMaster>')
        z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", _rels(("slideLayout", "../slideLayouts/slideLayout1.xml"), ("theme", "../theme/theme1.xml")))
        z.writestr("ppt/slideLayouts/slideLayout1.xml", f'{X0}<p:sldLayout {NS} type="blank" preserve="1"><p:cSld name="En blanco"><p:spTree>{VACIO}</p:spTree></p:cSld>'
                   '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')
        z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", _rels(("slideMaster", "../slideMasters/slideMaster1.xml")))
        for i, formas in enumerate(diapositivas, 1):
            z.writestr(f"ppt/slides/slide{i}.xml", f'{X0}<p:sld {NS}><p:cSld><p:spTree>{VACIO}{"".join(formas)}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')
            z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", _rels(("slideLayout", "../slideLayouts/slideLayout1.xml")))
    return b.getvalue()
