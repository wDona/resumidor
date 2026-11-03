"""Enlaces inteligentes (stdlib): clasifica una URL y trae su contenido a un fichero local que entra por el mismo camino que una subida.
  - fichero directo (pdf, docx, md, txt, html, zip, imagen, eml, msg, audio/vídeo por extensión o Content-Type): descarga en streaming con tope y timeout;
  - página HTML: texto del artículo -> .md con título, sitio, URL y fecha;
  - lo demás (vídeo/audio de un sitio con extractor propio de yt-dlp, nubes de Microsoft) lo decide app.py con `especifico` / `es_microsoft`.
Seguridad (SSRF): solo http/https; sin IPs privadas/loopback/link-local salvo `red_local`; se revisa también cada redirección."""
import html as _h
import html.parser
import ipaddress
import mimetypes
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MAX_MB = 500        # tope de descarga de un fichero (el vídeo va por yt-dlp, que no pasa por aquí)
MAX_HTML = 5 * 2**20
TIMEOUT = 30
UA = "Mozilla/5.0 (compatible; actas)"
DOC = (".pdf", ".docx", ".md", ".markdown", ".txt", ".html", ".htm", ".png", ".jpg", ".jpeg", ".webp", ".zip", ".eml", ".msg")
MEDIA = (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".mp3", ".m4a", ".wav", ".ogg", ".opus", ".flac", ".aac")
CT = {"application/pdf": ".pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx", "text/markdown": ".md",
      "text/plain": ".txt", "application/zip": ".zip", "application/x-zip-compressed": ".zip", "message/rfc822": ".eml", "application/vnd.ms-outlook": ".msg",
      "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
MS = re.compile(r"(^|\.)(1drv\.ms|onedrive\.live\.com|sharepoint\.com|teams\.microsoft\.com|microsoftstream\.com)$")


def es_microsoft(url):
    return bool(MS.search((urllib.parse.urlsplit(url).hostname or "").lower()))


def especifico(url):
    """True si yt-dlp tiene un extractor propio (no el genérico) para la URL."""
    try:
        from yt_dlp.extractor import gen_extractors
    except ImportError:
        return False
    return any(ie.suitable(url) and ie.ie_key() != "Generic" for ie in gen_extractors())


def comprobar(url, red_local=False):
    """ValueError con motivo en español si la URL no es segura de abrir."""
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("El enlace debe empezar por http:// o https://")
    if red_local:
        return
    try:
        ips = {a[4][0] for a in socket.getaddrinfo(u.hostname, u.port or 80, proto=socket.IPPROTO_TCP)}
    except socket.gaierror:
        return  # sin resolver: fallará al abrir con error de red
    for ip in ips:
        a = ipaddress.ip_address(ip.split("%")[0])
        if a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast or a.is_unspecified:
            raise ValueError("Enlace a la red local bloqueado: actívalo en Ajustes («Permitir enlaces a la red local») si es lo que quieres")


class _Redir(urllib.request.HTTPRedirectHandler):
    def __init__(self, red_local):
        self.red_local = red_local

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        comprobar(urllib.parse.urljoin(req.full_url, newurl), self.red_local)  # ponytail: DNS rebinding no cubierto; fijar IP si hace falta
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def abrir(url, red_local=False, timeout=TIMEOUT):
    comprobar(url, red_local)
    op = urllib.request.build_opener(_Redir(red_local))
    return op.open(urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"}), timeout=timeout)


def _nombre(r, url):
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", r.headers.get("Content-Disposition") or "", re.I)
    n = urllib.parse.unquote(m[1]) if m else urllib.parse.unquote(Path(urllib.parse.urlsplit(url).path).name)
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", n).strip(" .")[:100]


def traer(url, dest, cb=lambda f, m: None, red_local=False, max_mb=MAX_MB, timeout=TIMEOUT):
    """Baja url a la carpeta dest. -> ("fichero", ruta) | ("pagina", ruta del .md). Lanza las excepciones de urllib (el llamador las traduce),
    ValueError (enlace no permitido) o RuntimeError (no compatible / demasiado grande)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with abrir(url, red_local, timeout) as r:
        ct = (r.headers.get_content_type() or "").lower()
        nombre = _nombre(r, r.geturl())
        ext = Path(nombre).suffix.lower()
        ext = CT.get(ct) or (ext if ext in DOC + MEDIA else "") or (mimetypes.guess_extension(ct) or "" if ct.startswith(("audio/", "video/")) else "")
        if ext not in DOC + MEDIA and ct in ("text/html", "application/xhtml+xml"):
            ext = ".html"
        if ext in (".html", ".htm") and (ct in ("text/html", "application/xhtml+xml", "") or not Path(nombre).suffix):  # página, no fichero .html para descargar
            raw = r.read(MAX_HTML + 1)[:MAX_HTML]
            cs = r.headers.get_content_charset() or (re.search(rb"charset=[\"']?([\w-]+)", raw[:3000]) or [0, b"utf-8"])[1]
            txt = raw.decode(cs if isinstance(cs, str) else cs.decode(), "replace")
            titulo, md = pagina_a_md(txt, r.geturl())
            f = dest / ((re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", titulo)[:80].strip(" .") or "pagina") + ".md")
            f.write_text(md, encoding="utf-8")
            return "pagina", f
        if ext not in DOC + MEDIA:
            raise RuntimeError("Enlace no compatible: no es un documento, un audio, un vídeo ni una página con texto")
        n = Path(nombre).stem[:80] or "descarga"
        f = dest / (n + ext)
        tot, hecho, tope = int(r.headers.get("Content-Length") or 0), 0, max_mb * 2**20
        if tot > tope:
            raise RuntimeError(f"El fichero es demasiado grande (máximo {max_mb} MB)")
        with open(f, "wb") as o:
            while b := r.read(1 << 20):
                hecho += len(b)
                if hecho > tope:
                    o.close()
                    f.unlink(missing_ok=True)
                    raise RuntimeError(f"El fichero es demasiado grande (máximo {max_mb} MB)")
                o.write(b)
                cb(min(hecho / tot, 1) if tot else 0.5, f"Descargando… {hecho >> 20} MB")
    return "fichero", f


# ---------- artículo de una página ----------
_SALTA = {"script", "style", "nav", "header", "footer", "aside", "form", "noscript", "svg", "template", "iframe", "button", "select"}
_VOID = {"br", "img", "hr", "meta", "link", "input", "source", "wbr", "col", "area", "base", "embed", "param", "track"}
_BLOQ = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "div", "section", "article", "main", "br", "tr", "pre", "blockquote", "ul", "ol", "table", "dd", "dt", "figcaption"}


class _Art(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pila, self.n, self.salta = [], 0, 0  # pila: (tag, id); salta: profundidad dentro de un bloque ignorado
        self.buf, self.kind = [], "p"
        self.lineas = []  # (ids de los contenedores abiertos, texto)
        self.fila, self.celda = None, None
        self.titulo = self.og = self.sitio = self.fecha = self.t_title = ""
        self.en_title = False

    def _flush(self):
        t = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        self.buf = []
        if t and not self.salta:
            self.lineas.append((tuple(i for _, i in self.pila), self.kind, t))
        self.kind = "p"

    def handle_starttag(self, tag, a):
        a = dict(a)
        if tag == "meta":
            k, v = (a.get("property") or a.get("name") or "").lower(), a.get("content") or ""
            if k == "og:title":
                self.og = v
            elif k == "og:site_name":
                self.sitio = v
            elif k in ("article:published_time", "date", "dc.date", "og:article:published_time", "pubdate") and not self.fecha:
                self.fecha = v
            return
        if tag == "time" and a.get("datetime") and not self.fecha:
            self.fecha = a["datetime"]
        if tag == "title":
            self.en_title = True
        if tag in _VOID:
            if tag == "br" and not self.salta:
                self._flush()
            return
        if self.salta or tag in _SALTA:
            self.salta += 1
            self.pila.append((tag, -1))
            return
        if tag in _BLOQ:
            self._flush()
        self.n += 1
        self.pila.append((tag, self.n))
        if tag == "tr":
            self.fila = []
        if tag in ("td", "th"):
            self.celda = []
        if tag in ("h1", "h2", "h3", "li", "pre"):
            self.kind = tag

    def handle_endtag(self, tag):
        if tag == "title":
            self.en_title = False
        if tag in _VOID or not any(t == tag for t, _ in self.pila):
            return
        while self.pila:  # cierra hasta el tag (HTML mal cerrado)
            t, i = self.pila.pop()
            if i == -1:
                self.salta -= 1
            elif t == "tr" and self.fila is not None:
                self._flush()
                if any(self.fila):
                    self.lineas.append((tuple(j for _, j in self.pila), "p", " | ".join(self.fila)))
                self.fila = None
            elif t in ("td", "th") and self.celda is not None and self.fila is not None:
                self.fila.append(re.sub(r"\s+", " ", "".join(self.celda)).strip())
                self.celda = None
            if t == tag:
                break
        if tag in _BLOQ:
            self._flush()

    def handle_data(self, d):
        if self.en_title:
            self.t_title += d
        if self.salta:
            return
        if self.celda is not None:
            self.celda.append(d)
        else:
            self.buf.append(d)

    def close(self):
        super().close()
        self._flush()


def pagina_a_md(txt, url):
    """HTML -> (título, markdown). Prefiere <article>/<main>; si no, el contenedor más profundo con >= 60 % del texto."""
    p = _Art()
    p.feed(txt)
    p.close()
    ls = p.lineas
    tot = sum(len(t) for _, _, t in ls) or 1
    por = {}
    for anc, _, t in ls:
        for i in anc:
            por[i] = por.get(i, 0) + len(t)
    cand = [i for i in por if por[i] >= 0.6 * tot]  # ids crecen con la profundidad: el mayor es el más hondo
    # ponytail: heurística de densidad simple; Readability completo si falla en sitios raros
    elegido = max(cand) if cand else None
    ls = [x for x in ls if elegido in x[0]] if elegido else ls
    titulo = re.sub(r"\s+", " ", p.og or p.t_title or next((t for _, k, t in ls if k == "h1"), "") or urllib.parse.urlsplit(url).netloc).strip()
    sitio = p.sitio or urllib.parse.urlsplit(url).netloc
    out = [f"# {titulo}", "", f"Fuente: {url}", f"Sitio: {sitio}" + (f" · Fecha: {p.fecha[:25]}" if p.fecha else ""), ""]
    for _, k, t in ls:
        if k == "h1" and t == titulo:
            continue
        out += [f"## {t}" if k in ("h1", "h2") else f"### {t}" if k == "h3" else f"- {t}" if k == "li" else t, ""]
    return titulo, "\n".join(out)
