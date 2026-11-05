"""Lectura de correos recibidos (.eml y .msg de Outlook), solo stdlib -> {asunto, de, fecha, texto, adjuntos:[{nombre, datos}]}.
.msg = fichero compuesto OLE/CFB (MS-CFB) con propiedades MAPI (MS-OXMSG): lector mínimo, solo lo necesario (nada de escritura, ni RTF, ni mensajes anidados)."""

import datetime as dt
import re
import struct
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path

LIBRE, FIN = 0xFFFFFFFF, 0xFFFFFFFE


class _Txt(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.p, self.skip = [], 0

    def handle_starttag(self, t, a):
        self.skip += t in ("style", "script", "head")
        self.p.append("\n" if t in ("br", "p", "div", "tr", "li", "h1", "h2", "h3", "table") else "")

    def handle_endtag(self, t):
        self.skip -= t in ("style", "script", "head") and self.skip > 0
        self.p.append("\n" if t in ("p", "div", "tr", "li", "h1", "h2", "h3", "table") else "")

    def handle_data(self, d):
        self.skip or self.p.append(d)


def html_a_texto(h):
    t = _Txt()
    t.feed(h)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t\xa0]+", " ", "".join(t.p))).strip()


# ---------- .eml ----------
def _eml(b):
    m = BytesParser(policy=policy.default).parsebytes(b)
    cuerpo = m.get_body(("plain", "html"))
    texto = ""
    if cuerpo is not None:
        texto = cuerpo.get_content()
        texto = html_a_texto(texto) if cuerpo.get_content_subtype() == "html" else texto.strip()
    adj = [
        {
            "nombre": p.get_filename() or "adjunto",
            "datos": p.get_payload(decode=True) or bytes(p.get_content()) if p.get_content_type() == "message/rfc822" else p.get_payload(decode=True) or b"",
        }
        for p in m.iter_attachments()
    ]
    try:
        fecha = m["date"].datetime.isoformat() if m["date"] else ""
    except (ValueError, AttributeError):
        fecha = str(m["date"] or "")
    return {"asunto": str(m["subject"] or ""), "de": str(m["from"] or ""), "fecha": fecha, "texto": texto, "adjuntos": adj}


# ---------- CFB ----------
class CFB:
    """Compuesto OLE de solo lectura: .streams = {("__attach_version1.0_#00000000", "__substg1.0_37010102"): bytes, ...}."""

    def __init__(self, b):
        if b[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise ValueError("No es un fichero .msg válido")
        self.b = b
        self.ss, self.ms = (1 << struct.unpack_from("<H", b, o)[0] for o in (0x1E, 0x20))
        nfat, dir0, self.corte, mini0, nmini, dif0, ndif = (struct.unpack_from("<I", b, o)[0] for o in (0x2C, 0x30, 0x38, 0x3C, 0x40, 0x44, 0x48))
        fat_secs = list(struct.unpack_from("<109I", b, 0x4C))
        s = dif0
        for _ in range(ndif):  # DIFAT extra: lista de sectores FAT + enlace al siguiente
            v = struct.unpack_from(f"<{self.ss // 4}I", b, self._off(s))
            fat_secs += v[:-1]
            s = v[-1]
        self.fat = []
        for s in fat_secs[:nfat]:
            self.fat += struct.unpack_from(f"<{self.ss // 4}I", b, self._off(s))
        d = self._cadena(dir0)
        self.ents = []
        for i in range(0, len(d) - 127, 128):
            self.ents.append(self._ent(d, i))
        self.mini = b""
        if mini0 != FIN and nmini:
            self.minifat = []
            m = self._cadena(mini0)
            self.minifat = list(struct.unpack_from(f"<{len(m) // 4}I", m))
            self.mini = self._cadena(self.ents[0]["s"])[: self.ents[0]["z"]]
        self.streams = {}
        self._recorre(self.ents[0]["h"], ())

    @staticmethod
    def _ent(d, i):
        ln = struct.unpack_from("<H", d, i + 64)[0]
        izq, der, hijo = struct.unpack_from("<III", d, i + 68)
        ini, tam = struct.unpack_from("<IQ", d, i + 116)
        return {"n": d[i : i + max(ln - 2, 0)].decode("utf-16-le", "replace"), "t": d[i + 66], "i": izq, "d": der, "h": hijo, "s": ini, "z": tam}

    def _off(self, s):
        return (s + 1) * self.ss

    def _cadena(self, s):
        out, vistos = [], set()
        while s < FIN and s not in vistos and self._off(s) < len(self.b):
            vistos.add(s)
            out.append(self.b[self._off(s) : self._off(s) + self.ss])
            s = self.fat[s] if s < len(self.fat) else FIN
        return b"".join(out)

    def _minicadena(self, s):
        out, vistos = [], set()
        while s < FIN and s not in vistos and s < len(self.minifat):
            vistos.add(s)
            out.append(self.mini[s * self.ms : (s + 1) * self.ms])
            s = self.minifat[s]
        return b"".join(out)

    def _datos(self, e):
        return (self._minicadena(e["s"]) if e["z"] < self.corte else self._cadena(e["s"]))[: e["z"]]

    def _recorre(self, raiz, ruta):
        pila, hermanos = [raiz], []
        while pila:  # árbol binario de hermanos (rojo-negro): se recorre entero sin importar el orden
            i = pila.pop()
            if i >= len(self.ents) or i in hermanos:
                continue
            hermanos.append(i)
            e = self.ents[i]
            pila += [e["i"], e["d"]]
            if e["t"] == 2:
                self.streams[ruta + (e["n"],)] = self._datos(e)
            elif e["t"] == 1:
                self._recorre(e["h"], ruta + (e["n"],))


# ---------- .msg ----------
def _filetime(v):
    return (dt.datetime(1601, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(microseconds=v // 10)).isoformat() if v else ""


def _prop(s, ruta, tag):
    """Valor de una propiedad de cadena/binaria: stream __substg1.0_<tag><tipo> bajo `ruta` (001F UTF-16, 001E ANSI, 0102 binario)."""
    for t, f in (
        ("001F", lambda d: d.decode("utf-16-le", "replace").rstrip("\0")),
        ("001E", lambda d: d.decode("cp1252", "replace").rstrip("\0")),
        ("0102", bytes),
    ):
        d = s.get(ruta + (f"__substg1.0_{tag}{t}",))
        if d is not None:
            return f(d)
    return None


def _msg(b):
    c = CFB(b)
    s, r = c.streams, ()
    asunto = _prop(s, r, "0037") or ""
    nombre, addr = _prop(s, r, "0C1A") or "", _prop(s, r, "5D01") or _prop(s, r, "0C1F") or ""
    de = f"{nombre} <{addr}>" if nombre and addr and nombre != addr else nombre or addr
    fecha = ""
    props = s.get(("__properties_version1.0",), b"")
    for i in range(32, len(props) - 15, 16):  # cabecera de 32 bytes en el mensaje; entradas de 16: tag, flags, valor(8)
        tag, _, v = struct.unpack_from("<IIQ", props, i)
        if tag == 0x00390040 or tag == 0x0E060040 and not fecha:
            fecha = _filetime(v)
    cuerpo = _prop(s, r, "1000")
    if not cuerpo:
        h = _prop(s, r, "1013")
        h = h.decode("utf-8", "replace") if isinstance(h, bytes) else h  # 1013 viene como binario (HTML en la página de códigos del mensaje)
        cuerpo = html_a_texto(h) if h else ""
    adj = []
    for k in sorted({x[0] for x in s if len(x) == 2 and x[0].startswith("__attach_version1.0_")}):
        d = s.get((k, "__substg1.0_37010102"))
        if d is None:
            continue
        adj.append({"nombre": _prop(s, (k,), "3707") or _prop(s, (k,), "3704") or _prop(s, (k,), "3001") or "adjunto", "datos": d})
    return {"asunto": asunto, "de": de, "fecha": fecha, "texto": cuerpo.strip(), "adjuntos": adj}


def leer(ruta):
    """.eml o .msg -> {asunto, de, fecha, texto, adjuntos:[{nombre, datos}]}. ValueError si no es un correo legible."""
    p = Path(ruta)
    b = p.read_bytes()
    if p.suffix.lower() == ".msg" or b[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return _msg(b)
    if p.suffix.lower() == ".eml" or b[:64].lstrip()[:1]:
        return _eml(b)
    raise ValueError("Formato de correo no admitido (.eml o .msg)")
