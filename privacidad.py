"""Anonimizar un documento: detecta datos personales (DNI/NIE/NIF, teléfonos, emails, IBAN, tarjetas, matrículas y personas),
el usuario revisa la lista y `aplicar` crea una copia derivada (acta_anonima.json, transcript_anonimo.json, img_anon/) junto
al original; el original y la edición no se tocan. Los exports con anon=1 leen esa copia (exportar.carga(..., anon=True))."""
import hashlib
import json
import re
import shutil
import time
from pathlib import Path

import pipeline as P

ANON, ANON_TR, ANON_IMG, ANON_META = "acta_anonima.json", "transcript_anonimo.json", "img_anon", "anon.json"
LETRAS = "TRWAGMYFPDXBNJZSQVHLCKE"
SIN_REEMPLAZO = {"img", "plantilla", "nivel"}  # claves de los datos que nunca se tocan
GENERICOS = {"todos", "equipo", "todo el equipo", "nadie", "por definir", "pendiente", "sin asignar", "—", "-", "n/a"}
STOP = {"de", "del", "la", "el", "los", "las", "y", "da", "do", "van", "von"}


# ---------- validadores ----------
def dni_ok(s):
    """DNI (8 cifras + letra), NIE (X/Y/Z + 7 cifras + letra) o CIF (letra + 7 cifras + control), con su dígito/letra de control."""
    s = re.sub(r"[ -]", "", s).upper()
    if re.fullmatch(r"\d{8}[A-Z]", s):
        return LETRAS[int(s[:8]) % 23] == s[8]
    if re.fullmatch(r"[XYZ]\d{7}[A-Z]", s):
        return LETRAS[int(str("XYZ".index(s[0])) + s[1:8]) % 23] == s[8]
    if re.fullmatch(r"[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]", s):
        d = [int(c) for c in s[1:8]]
        tot = d[1] + d[3] + d[5] + sum(sum(divmod(2 * x, 10)) for x in d[0::2])
        ctl = (10 - tot % 10) % 10
        return s[8] in (str(ctl), "JABCDEFGHI"[ctl])
    return False


def iban_ok(s):
    s = re.sub(r"[ -]", "", s).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s) or (s[:2] == "ES" and len(s) != 24):
        return False
    return int("".join(str(int(c, 36)) for c in s[4:] + s[:4])) % 97 == 1


def luhn_ok(s):
    d = [int(c) for c in re.sub(r"[ -]", "", s)]
    if not 13 <= len(d) <= 19:
        return False
    return sum(x if i % 2 == 0 else (x * 2 - 9 if x > 4 else x * 2) for i, x in enumerate(reversed(d))) % 10 == 0


def tel_ok(s):
    """Móvil/fijo español de 9 cifras (6-9...) o internacional con +; con puntos como separador solo si lleva prefijo (si no, es un importe)."""
    pref = s.lstrip().startswith(("+", "00"))
    d = re.sub(r"\D", "", s)
    if "." in s and not pref:
        return False
    if pref:
        return 8 <= len(d) <= 15
    return len(d) == 9 and d[0] in "6789"


def _digs(v):
    d = re.sub(r"\D", "", v)
    return d.removeprefix("0034") if d.startswith("0034") else d[2:] if d.startswith("34") and len(d) == 11 else d


# ---------- detectores (el orden manda: lo ya cubierto no se vuelve a marcar) ----------
DETECTORES = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), None, lambda v: v.lower()),
    ("iban", re.compile(r"(?<![\w])[A-Z]{2}\d{2}(?:[ -]?[A-Z0-9]{4}){2,7}(?:[ -]?[A-Z0-9]{1,4})?(?![\w])"), iban_ok, lambda v: re.sub(r"[ -]", "", v).upper()),
    ("tarjeta", re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?!\d)"), luhn_ok, lambda v: re.sub(r"\D", "", v)),
    ("dni", re.compile(r"(?<![\w])(?:\d{8}|[XYZxyz]\d{7}|[A-HJNP-SUVWa-hjnp-suvw]\d{7})[ -]?[A-Za-z0-9](?![\w])"), dni_ok, lambda v: re.sub(r"[ -]", "", v).upper()),
    ("matricula", re.compile(r"(?<![\w-])(?:\d{4}[ -]?[BCDFGHJKLMNPRSTVWXYZ]{3}|[A-Z]{1,2}[ -]?\d{4}[ -]?[A-Z]{1,2})(?![\w-])"), None, lambda v: re.sub(r"[ -]", "", v)),
    ("telefono", re.compile(r"(?<![\w+.-])(?:(?:\+|00)34[ .-]?)?[6-9]\d{2}[ .-]?\d{3}[ .-]?\d{3}(?![\w])|(?<![\w+.-])(?:(?:\+|00)34[ .-]?)?[6-9]\d{2}[ .-]?\d{2}[ .-]?\d{2}[ .-]?\d{2}(?![\w])"
                            r"|(?<![\w+.])\+(?!34)\d{1,3}[ .-]?(?:\d[ .-]?){6,11}\d(?![\w])"), tel_ok, lambda v: _digs(v)),
]
ETIQUETA = {"email": "[EMAIL]", "iban": "[IBAN]", "tarjeta": "[TARJETA]", "dni": "[DNI]", "matricula": "[MATRÍCULA]", "telefono": "[TELÉFONO]"}


def detectar_texto(t):
    """[(tipo, clave canónica, valor tal cual, ini, fin)] sin solapes."""
    out, tomado = [], []
    for tipo, rx, ok, canon in DETECTORES:
        for m in rx.finditer(t):
            if any(m.start() < e and m.end() > s for s, e in tomado) or (ok and not ok(m[0])):
                continue
            tomado.append((m.start(), m.end()))
            out.append((tipo, canon(m[0].strip()), m[0].strip(), m.start(), m.end()))
    return sorted(out, key=lambda x: x[3])


# ---------- textos del documento ----------
def _walk(o, ruta=""):
    if isinstance(o, dict):
        for k, v in o.items():
            if k not in SIN_REEMPLAZO:
                yield from _walk(v, f"{ruta}.{k}" if ruta else k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _walk(v, f"{ruta}.{i}" if ruta else str(i))
    elif isinstance(o, str):
        yield ruta, o


def _mapa(o, fn):
    if isinstance(o, dict):
        return {k: (v if k in SIN_REEMPLAZO else _mapa(v, fn)) for k, v in o.items()}
    if isinstance(o, list):
        return [_mapa(v, fn) for v in o]
    return fn(o) if isinstance(o, str) else o


def frames(wd):
    """{img: {text, lines?, wh?}} del OCR de las capturas (frames2.json con cajas en transcripciones nuevas; frames.json solo texto)."""
    out = {}
    for f in ("frames.json", "frames2.json"):
        try:
            for k in json.loads((Path(wd) / f).read_text()):
                out[k["img"]] = {**out.get(k["img"], {}), **{a: k[a] for a in ("text", "lines", "wh") if a in k}}
        except (OSError, ValueError, KeyError):
            pass
    return out


def corpus(c):
    """[(origen, texto)]: datos del documento (con ruta), transcripción y OCR de las capturas del documento."""
    out = [(r, t) for r, t in _walk(c["data"]) if t.strip()]
    out += [(f"trans.{i}", s["text"]) for i, s in enumerate(c["segs"])] + [(f"trans.{i}.spk", s["spk"]) for i, s in enumerate(c["segs"]) if s.get("spk")]
    fr = frames(c["d"].parent)
    out += [(f"ocr.{k['img']}", fr[k["img"]]["text"]) for k in c["data"].get("capturas", []) if fr.get(k["img"], {}).get("text")]
    return out


def _nombres_conocidos(c):
    """Personas que el propio documento ya nombra: hablantes, nombres.json, responsables de tareas y campos persona/responsable."""
    ns = [s["spk"] for s in c["segs"] if s.get("spk") and not re.fullmatch(r"Hablante \d+", s["spk"])]
    try:
        nm = json.loads((c["d"].parent / "nombres.json").read_text()).get("names")
        ns += [str(v) for v in (nm.values() if isinstance(nm, dict) else nm or [])]
    except (OSError, ValueError, AttributeError):
        pass
    D = c["data"]
    cand = [x.get("responsable", "") for x in D.get("tareas", [])] + [str(x[k]) for s in D.get("secciones_plantilla", []) for x in s["items"] for k in ("responsable", "persona", "propietario") if x.get(k)]
    for r in cand:
        ns += re.split(r"\s*(?:,|/|;|\by\b|\be\b|&)\s*", r)
    out = []
    for n in ns:
        n = n.strip(" .—-")
        if len(n) >= 2 and n.casefold() not in GENERICOS and n not in out:
            out.append(n)
    return out


def _llm_personas(textos):
    """Una pasada del LLM local (JSON con gramática) sobre trozos del texto -> nombres de persona que aparecen literalmente."""
    modelo = P.llm_model()
    if not modelo:
        return None
    txt = "\n".join(textos)
    trozos = [txt[i:i + 4000] for i in range(0, len(txt), 4000)]
    if len(trozos) > 8:  # ponytail: como mucho 8 trozos repartidos; mejora: pasadas con más contexto en GPU
        trozos = [trozos[round(i * (len(trozos) - 1) / 7)] for i in range(8)]
    sis = ("Lista los nombres de persona (nombre propio de personas físicas, con apellidos si aparecen) que aparecen en el texto. "
           "No incluyas empresas, lugares, productos ni cargos. Copia cada nombre tal cual está escrito; si no hay ninguno, lista vacía.")
    out = []
    with P.llama(P.PHYS, ctx=8192, model=modelo) as chat:
        for tz in trozos:
            r = chat(sis, tz, P.obj(personas=P.arr(P.S(60), 30)), 600)
            out += [n.strip() for n in r["personas"] if n.strip() and n.strip() in tz]
    return list(dict.fromkeys(out))


def _letra(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _ctx(t, a, b, n=35):
    return ("…" if a > n else "") + t[max(0, a - n):b + n].replace("\n", " ") + ("…" if b + n < len(t) else "")


def _reg_persona(nombres):
    """Regex de los nombres (más largos primero) con sus alias de una palabra (nombre de pila…) cuando no chocan con otra persona."""
    pares = {}
    for sug, v in nombres:
        pares.setdefault(v, sug)
    for sug, v in nombres:
        for w in v.split():
            if len(w) >= 3 and w[0].isupper() and w.casefold() not in STOP and len(v.split()) > 1:
                pares.setdefault(w, sug)
    if not pares:
        return None, pares
    return re.compile(r"(?<!\w)(" + "|".join(re.escape(k) for k in sorted(pares, key=len, reverse=True)) + r")(?!\w)"), pares


def detectar(c, llm=True):
    """-> {items: [{tipo, valor, n, ejemplos, sugerido}], sin_modelo, capturas_sin_cajas}. No toca nada en disco."""
    tx = corpus(c)
    grupos = {}
    for origen, t in tx:
        for tipo, clave, valor, a, b in detectar_texto(t):
            g = grupos.setdefault((tipo, clave), {"tipo": tipo, "valor": valor, "n": 0, "ejemplos": [], "sugerido": ETIQUETA[tipo]})
            g["n"] += 1
            if len(g["ejemplos"]) < 3:
                g["ejemplos"].append(_ctx(t, a, b))
    conocidos = _nombres_conocidos(c)
    sin_modelo = False
    hallados = []
    if llm:
        hallados = _llm_personas([t for o, t in tx if not o.startswith("ocr.") and not o.endswith(".spk")])
        sin_modelo = hallados is None
        hallados = hallados or []
    else:
        sin_modelo = True
    pers = {}
    for n in conocidos + hallados:
        if n.casefold() not in GENERICOS and not any(n == m for m in pers):
            pers[n] = None
    for n in list(pers):  # una persona "Carlos" ya contenida en "Carlos Pérez" no se lista dos veces
        if any(m != n and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", m) for m in pers):
            del pers[n]
    k = 0
    for n in pers:
        rx = re.compile(rf"(?<!\w){re.escape(n)}(?!\w)")
        cnt, ej = 0, []
        for o, t in tx:
            for m in rx.finditer(t):
                cnt += 1
                if len(ej) < 3:
                    ej.append(_ctx(t, m.start(), m.end()))
        if cnt or n in conocidos:
            grupos[("persona", n)] = {"tipo": "persona", "valor": n, "n": cnt, "ejemplos": ej, "sugerido": f"Persona {_letra(k)}"}
            k += 1
    fr = frames(c["d"].parent)
    return {"items": sorted(grupos.values(), key=lambda g: (g["tipo"] == "persona", g["tipo"], -g["n"])), "sin_modelo": sin_modelo,
            "capturas_sin_cajas": [k["img"] for k in c["data"].get("capturas", []) if fr.get(k["img"], {}).get("text") and "lines" not in fr[k["img"]]]}


# ---------- aplicar ----------
class Sustituidor:
    """Reemplaza en un texto los datos marcados (regex por clave canónica; personas/manuales literales con alias de una palabra)."""

    def __init__(self, items):
        its = [i for i in items if i.get("incluir", True) and str(i.get("valor", "")).strip()]
        self.reg = {}
        pers = []
        for i in its:
            v, sug = str(i["valor"]).strip(), str(i.get("sugerido") or "").strip()
            if i.get("tipo") in ETIQUETA:
                sug = sug or ETIQUETA[i["tipo"]]
                d = next((x for x in DETECTORES if x[0] == i["tipo"]), None)
                self.reg[(i["tipo"], d[3](v))] = sug
            else:
                pers.append((sug or "[PERSONA]", v))
        self.rx, self.lit = _reg_persona(pers)

    def __call__(self, t):
        if not t:
            return t
        for tipo, clave, _, a, b in reversed(detectar_texto(t)):
            if (tipo, clave) in self.reg:
                t = t[:a] + self.reg[(tipo, clave)] + t[b:]
        return self.rx.sub(lambda m: self.lit[m[1]], t) if self.rx else t

    def toca(self, t):
        """El texto contiene algún dato marcado."""
        return self(t) != t


def _desenfocar(img, caja, sus):
    from PIL import ImageFilter
    x0, y0, x1, y1 = (int(v) for v in caja)
    r = img.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(max(12, (y1 - y0))))
    img.paste(r, (x0, y0))


def aplicar(c, items):
    """Crea la copia anonimizada junto a la versión. -> resumen {reemplazos, difuminadas, omitidas, motivo}."""
    from PIL import Image
    sus = Sustituidor(items)
    d = c["d"]
    cuenta = [0]

    def f(t):
        n = sus(t)
        cuenta[0] += n != t
        return n
    data = _mapa(c["data"], f)
    segs = []
    for s in c["segs"]:
        n = {**s, "text": f(s["text"])}
        if s.get("spk"):
            n["spk"] = f(s["spk"])
        if n["text"] != s["text"]:
            n.pop("words", None)  # los tiempos por palabra ya no encajan con el texto cambiado: los subtítulos se reparten por caracteres
        segs.append(n)
    img_o, img_a = d / "img", d / ANON_IMG
    shutil.rmtree(img_a, ignore_errors=True)
    img_a.mkdir()
    fr, omitidas, borrosas = frames(d.parent), [], 0
    for k in c["data"].get("capturas", []):
        src = img_o / k["img"]
        if not src.is_file():
            continue
        e = fr.get(k["img"])
        if not e or "text" not in e:
            omitidas.append({"img": k["img"], "motivo": "sin OCR guardado: no se puede comprobar"})
            continue
        if not sus.toca(e["text"]):
            shutil.copy2(src, img_a / k["img"])
        elif e.get("lines") and e.get("wh"):
            im = Image.open(src).convert("RGB")
            fx, fy = im.width / e["wh"][0], im.height / e["wh"][1]
            for x0, y0, x1, y1, txt in e["lines"]:
                if sus.toca(txt):
                    _desenfocar(im, (max(0, x0 * fx - 4), max(0, y0 * fy - 4), min(im.width, x1 * fx + 4), min(im.height, y1 * fy + 4)), sus)
                    borrosas += 1
            im.save(img_a / k["img"], quality=90)
        else:
            omitidas.append({"img": k["img"], "motivo": "contiene datos marcados y no hay cajas del OCR (transcripción anterior): omitida"})
    (d / ANON).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / ANON_TR).write_text(json.dumps({"segments": segs}, ensure_ascii=False), encoding="utf-8")
    res = {"reemplazos": cuenta[0], "difuminadas": borrosas, "omitidas": omitidas}
    (d / ANON_META).write_text(json.dumps({**res, "items": [i for i in items if i.get("incluir", True)], "ts": int(time.time()), "fuente": fuente(c)}, ensure_ascii=False), encoding="utf-8")
    return res


def fuente(c):
    return hashlib.sha1(json.dumps(c["data"], sort_keys=True).encode()).hexdigest()[:12]


def estado(c):
    """{existe, obsoleta, ...} de la copia anonimizada de la versión (obsoleta: el documento se editó después)."""
    try:
        m = json.loads((c["d"] / ANON_META).read_text())
    except (OSError, ValueError):
        return {"existe": False}
    return {"existe": (c["d"] / ANON).is_file(), "obsoleta": m.get("fuente") != fuente(c), "reemplazos": m["reemplazos"], "difuminadas": m["difuminadas"],
            "omitidas": m["omitidas"], "items": m["items"], "ts": m["ts"]}


def borrar(d):
    for f in (ANON, ANON_TR, ANON_META):
        (d / f).unlink(missing_ok=True)
    shutil.rmtree(d / ANON_IMG, ignore_errors=True)


def demo():
    assert dni_ok("12345678Z") and not dni_ok("12345678A") and dni_ok("X1234567L") and not dni_ok("X1234567A") and dni_ok("A58818501") and not dni_ok("A58818502")
    assert iban_ok("ES91 2100 0418 4502 0005 1332") and not iban_ok("ES91 2100 0418 4502 0005 1333")
    assert luhn_ok("4539 1488 0343 6467") and not luhn_ok("4539 1488 0343 6468")
    assert tel_ok("612 345 678") and tel_ok("+34 612345678") and tel_ok("+44 20 7946 0958") and not tel_ok("512 345 678") and not tel_ok("612.345.678")
    r = {(t, k) for t, k, *_ in detectar_texto("Mi DNI 12345678Z, 12345678A no, mail a.b@x.es, tel 612 34 56 78, IBAN ES91 2100 0418 4502 0005 1332, coche 1234 BCD")}
    assert r == {("dni", "12345678Z"), ("email", "a.b@x.es"), ("telefono", "612345678"), ("iban", "ES9121000418450200051332"), ("matricula", "1234BCD")}, r
    s = Sustituidor([{"tipo": "dni", "valor": "12345678Z", "sugerido": "[DNI]"}, {"tipo": "persona", "valor": "Carlos Pérez", "sugerido": "Persona A"}])
    assert s("Carlos Pérez (12345678-z) y Carlos") == "Persona A ([DNI]) y Persona A"
    print("ok")


if __name__ == "__main__":
    demo()
