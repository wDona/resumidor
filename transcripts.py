"""Transcripciones exportadas (Teams, Zoom, Meet, Otter…: .vtt .srt .txt .docx) -> segmentos {"s","e","text","spk"?} como los del
ASR, y desfase respecto al vídeo. Solo biblioteca estándar."""
import html
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict
from math import ceil
from pathlib import Path
from statistics import median

MAXSEG = 20   # s: largo máximo de un segmento al fundir cues (el ASR da hasta ~30)
GAP = 2.0     # s: pausa máxima entre cues del mismo hablante para fundirlos
T = r"(?:\d{1,2}:)?\d{1,2}:\d{1,2}(?:[.,]\d{1,3})?"  # 0:0:0.0 · 00:01:02.345 · 1:05 · 00:01:02,500
NO_SPK = {"unknown", "desconocido", "unknown speaker", "orador desconocido", "hablante desconocido", "?"}
ts = lambda x: sum(float(p.replace(",", ".")) * m for p, m in zip(reversed(x.split(":")), (1, 60, 3600)))
NFC = lambda t: unicodedata.normalize("NFC", t)


def speaker(n):
    """Nombre limpio, o None si no dice quién (Unknown, número de teléfono…)."""
    n = " ".join(NFC(n or "").split())
    return None if not n or n.lower() in NO_SPK or re.fullmatch(r"\+?[\d\s().-]{6,}", n) else n


def name_split(text):
    """«Ana García: texto» -> (nombre, texto). Nombre de 1-5 palabras, <= 40 letras, sin cifras solas ni puntuación de frase."""
    m = re.match(r"([^:：\n]{1,40}?)\s*[:：]\s+(\S.*)$", text, re.S)
    if m and len(m[1].split()) <= 5 and not re.search(r"[.!?¿¡;]", m[1]) and not re.fullmatch(r"[\d\s:.,]+", m[1]) \
            and (m[1][0].isupper() or m[1][0] in "+0123456789"):
        return m[1], m[2]
    return None, text


def clean(t):
    return NFC(" ".join(html.unescape(re.sub(r"<[^>]+>", "", t)).split()))


def cues(raw):
    """WebVTT y SRT: bloques con «ini --> fin»; lo anterior (id, GUID) y NOTE/STYLE se ignoran. <v Nombre>…</v> de Teams."""
    out = []
    for b in re.split(r"\n\s*\n", raw):
        lines = b.strip().split("\n")
        i = next((k for k, l in enumerate(lines) if "-->" in l), None)
        m = i is not None and re.search(rf"({T})\s*-->\s*({T})", lines[i])
        if not m:
            continue
        body = " ".join(lines[i + 1:])
        parts = re.findall(r"<v(?:\.[^\s>]*)?\s+([^>]*)>(.*?)(?:</v>|(?=<v[\s.])|$)", body) or [(None, body)]
        for who, txt in parts:
            if txt := clean(txt):
                out.append({"s": ts(m[1]), "e": ts(m[2]), "text": txt, "spk": speaker(who) if who else None, "pre": not who})
    # «Nombre: texto» (Zoom, SRT) solo si ese nombre sale en 2 cues o más: «Primero: …» suelto no es un hablante
    cand = [name_split(c["text"]) if c.pop("pre") else (None, c["text"]) for c in out]
    n = Counter(w for w, _ in cand if w)
    for c, (w, txt) in zip(out, cand):
        if w and n[w] >= 2:
            c["spk"], c["text"] = speaker(w), txt
    return out


HMS = re.compile(r"(?:(\d+)\s*(?:horas?|hours?)\s+)?(?:(\d+)\s*(?:minutos?|minutes?)\s+)?(\d+)\s*(?:segundos?|seconds?)\b")
HEAD = (re.compile(rf"^[\[(]\s*({T})\s*[\])]\s*(?:([^:\n]{{1,40}}?)\s*:)?\s*(.*)$"),   # [00:01:02] Ana García: texto
        re.compile(rf"^({T})\s+([^:\n]{{1,40}}?)\s*:\s*(.*)$"),                          # 00:01:02 Ana García: texto
        re.compile(rf"^(.{{1,40}}?)\s*[\[(]?\s*({T})\s*[\])]?\s*:?$"))                   # Ana García  0:05 · Ana (00:01:02)


okname = lambda n: name_split(n + ": x")[0] is not None


def lines_txt(raw):
    """Cabeceras de hablante con marca (Otter, Meet, Fireflies, tl;dv, DOCX de Teams) y el texto que sigue hasta la siguiente."""
    out = []
    for l in raw.split("\n"):
        l = HMS.sub(lambda m: f"{int(m[1] or 0)}:{int(m[2] or 0)}:{m[3]}", l.strip())
        if not l:
            continue
        if m := HEAD[0].match(l) or HEAD[1].match(l):
            ok = m[2] is None or okname(m[2])
            h = (m[1], m[2] if ok else None, m[3] if ok else f"{m[2]}: {m[3]}")
        elif (m := HEAD[2].match(l)) and len(m[1].split()) <= 5 and not re.search(r"[.!?¿¡:;]", m[1]) and okname(m[1]):
            h = (m[2], m[1], "")
        else:
            h = None
        if h:
            out.append({"s": ts(h[0]), "e": None, "spk": speaker(h[1]), "text": clean(h[2])})
        elif out:
            out[-1]["text"] = (out[-1]["text"] + " " + clean(l)).strip()
    return [o for o in out if o["text"]]


def docx_text(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    return "\n".join(html.unescape("".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", p.replace("<w:tab/>", "<w:t> </w:t>"))))
                     for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S))


def split_long(s, maxdur=30):
    """Un párrafo largo de TXT (Otter) en trozos de ~MAXSEG s por frases, con tiempos repartidos por nº de letras."""
    if s["e"] - s["s"] <= maxdur:
        return [s]
    sents, n = re.split(r"(?<=[.!?…])\s+", s["text"]), ceil((s["e"] - s["s"]) / MAXSEG)
    goal, out, cur, done = len(s["text"]) / n, [], [], 0
    for x in sents:
        cur.append(x)
        if sum(map(len, cur)) >= goal or x is sents[-1]:
            a = s["s"] + (s["e"] - s["s"]) * done / len(s["text"])
            done += sum(map(len, cur)) + len(cur)
            out.append({**s, "s": round(a, 1), "e": round(s["s"] + (s["e"] - s["s"]) * min(done / len(s["text"]), 1), 1), "text": " ".join(cur)})
            cur = []
    return out


def merge(segs):
    """Cues seguidos del mismo hablante (o sin él) y con poca pausa, en segmentos de <= MAXSEG s."""
    out = []
    for s in segs:
        p = out[-1] if out else None
        if p and p.get("spk") == s.get("spk") and s["s"] - p["e"] < GAP and s["e"] - p["s"] <= MAXSEG:
            p["e"], p["text"] = max(p["e"], s["e"]), p["text"] + " " + s["text"]
        else:
            out.append(dict(s))
    return out


def parse(path):
    """-> {"formato", "segments", "speakers"} (hablantes en orden de aparición). ValueError si no se reconoce."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".docx":
        raw, fmt = NFC(docx_text(p)), "DOCX"
    else:
        raw = NFC(p.read_bytes().decode("utf-8-sig", "replace").replace("\r\n", "\n").replace("\r", "\n"))
        fmt = ("WebVTT" if raw.lstrip().startswith("WEBVTT") or ext == ".vtt" else "SRT") if "-->" in raw else "TXT"
    segs = cues(raw) if fmt in ("WebVTT", "SRT") else lines_txt(raw)
    segs = sorted((s for s in segs if s["text"]), key=lambda s: s["s"])
    if not segs:
        raise ValueError("No se reconoce el formato de la transcripción (.vtt, .srt, .txt con marcas de tiempo o .docx)")
    for s, nxt in zip(segs, segs[1:] + [None]):  # sin fin: el inicio del siguiente (el último, por su largo)
        if s["e"] is None or s["e"] < s["s"]:
            s["e"] = nxt["s"] if nxt and nxt["s"] > s["s"] else s["s"] + max(2, len(s["text"].split()) / 2.5)
    segs = merge([x for s in segs for x in split_long(s)])
    segs = [{"s": round(s["s"], 1), "e": round(s["e"], 1), "text": s["text"], **({"spk": s["spk"]} if s.get("spk") else {})}
            for s in segs]
    return {"formato": fmt, "segments": segs, "speakers": list(dict.fromkeys(s["spk"] for s in segs if "spk" in s))}


# ---------- idioma y desfase ----------
ES = set("el la los las de que y en un una es por con para se no lo al del su pero como más esto está".split())
EN = set("the and of to in is that it for you with this are was on be have not but they we".split())


def language(segs):
    w = re.findall(r"\w+", " ".join(s["text"] for s in segs[:200]).lower())
    return "en" if sum(x in EN for x in w) > sum(x in ES for x in w) else "es"


def _tok(segs):
    """(palabra sin tildes, instante) con la marca repartida por posición dentro de cada segmento."""
    out = []
    for s in segs:
        ws = re.findall(r"\w+", "".join(c for c in unicodedata.normalize("NFD", s["text"].lower()) if not unicodedata.combining(c)))
        out += [(w, s["s"] + (s["e"] - s["s"]) * (i + .5) / len(ws)) for i, w in enumerate(ws)]
    return out


def align(sample, segs, lim=600):
    """Desfase d (s) tal que instante_del_vídeo = instante_de_la_transcripción + d, con |d| <= lim: cada palabra de la muestra
    (ASR de un trozo del vídeo) vota por la diferencia con cada aparición de la misma palabra en la transcripción. -> (d, seguro):
    seguro si el pico (±2 s) tiene >= 6 votos y al menos el doble que el mejor pico lejano. ponytail: palabras >= 5 letras y
    <= 6 apariciones, O(muestra x apariciones); sin voz en la muestra no hay votos."""
    B = _tok(segs)
    freq, idx = Counter(w for w, _ in B), defaultdict(list)
    for w, t in B:
        if len(w) >= 5 and freq[w] <= 6:
            idx[w].append(t)
    votes = Counter(round(t - u) for w, t in _tok(sample) if len(w) >= 5 for u in idx.get(w, ()) if abs(t - u) <= lim)
    if not votes:
        return 0.0, False
    near = lambda d: sum(votes[k] for k in range(d - 2, d + 3))
    best = max(votes, key=near)
    rest = max((near(k) for k in votes if abs(k - best) > 6), default=0)
    d = median(k for k in range(best - 3, best + 4) for _ in range(votes[k]))
    return float(d), near(best) >= 6 and near(best) >= 2 * rest


# ---------- prueba ----------
def _selftest():
    import tempfile
    P = lambda name, data: (lambda f: (f.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8")), parse(f))[1])(Path(d) / name)
    with tempfile.TemporaryDirectory() as d:
        # Teams: GUID como id, horas sin relleno, <v>, entidades y etiquetas; hablante desconocido; fusión del mismo hablante
        teams = ("﻿WEBVTT\r\n\r\n3f2c1a9e-1111-4a2b-9c3d-000000000001/15-0\r\n0:0:1.5 --> 0:0:4.0\r\n"
                 "<v Ana García>Hola a todos, &amp; bienvenidos.</v>\r\n\r\n3f2c1a9e-1111-4a2b-9c3d-000000000001/16-0\r\n"
                 "00:00:04.100 --> 00:00:06.000\r\n<v Ana García><i>Empezamos</i> ya.</v>\r\n\r\nNOTE nada\r\n\r\n"
                 "00:00:30.000 --> 00:00:33.000\r\n<v Unknown>Se oye mal</v>\r\n\r\n00:00:34.000 --> 00:00:36.000\r\n"
                 "<v Luis Pérez>Vale, lo hago yo.</v>\r\n")
        r = P("t.vtt", teams)
        assert r["formato"] == "WebVTT" and r["speakers"] == ["Ana García", "Luis Pérez"], r
        assert r["segments"][0] == {"s": 1.5, "e": 6.0, "text": "Hola a todos, & bienvenidos. Empezamos ya.", "spk": "Ana García"}, r
        assert "spk" not in r["segments"][1] and r["segments"][2]["spk"] == "Luis Pérez" and len(r["segments"]) == 3, r
        # Zoom: «Nombre: texto» en 2 cues = hablante; «Primero: …» suelto (1 vez) no
        z = ("WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.000\nMarta Gil: Buenos días.\n\n2\n00:00:20.000 --> 00:00:23.000\n"
             "Primero: el orden del día.\n\n3\n00:00:50.000 --> 00:00:52.000\nMarta Gil: Seguimos.\n")
        r = P("z.vtt", z)
        assert [s.get("spk") for s in r["segments"]] == ["Marta Gil", None, "Marta Gil"] and r["segments"][1]["text"].startswith("Primero"), r
        # SRT: coma en los ms, «Nombre:» opcional, sin ids ni fin ordenado
        r = P("s.srt", "1\n00:00:01,200 --> 00:00:02,000\nJosé: Hola\n\n2\n00:01:00,000 --> 00:01:01,500\nJosé: Adiós <b>ya</b>\n")
        assert r["formato"] == "SRT" and r["segments"][1] == {"s": 60.0, "e": 61.5, "text": "Adiós ya", "spk": "José"}, r
        # TXT: [hh:mm:ss] Nombre: · «Nombre  0:05» · «Nombre (00:01:02)», con teléfono y texto en varias líneas; fin = siguiente inicio
        txt = ("Reunión de equipo\n[00:00:05] Ana García: Hola.\n[00:00:09] Luis: Buenas, ¿qué tal?\nTodo bien.\n"
               "Ana García  0:20\nVamos con el primer punto.\n+34 600 123 456 (00:00:40)\nNo me oyen\n"
               "Luis 01:00:02\nFin.\n")
        r = P("o.txt", txt)
        assert [(s["s"], s.get("spk")) for s in r["segments"]] == [(5.0, "Ana García"), (9.0, "Luis"), (20.0, "Ana García"), (40.0, None),
                                                                (3602.0, "Luis")], r
        assert r["segments"][1]["text"] == "Buenas, ¿qué tal? Todo bien." and r["segments"][0]["e"] == 9.0, r
        # DOCX de Teams: «Nombre   0 minutos 5 segundos» y el texto debajo
        import io
        body = "".join(f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>" for t in (
            "Ana García   0 minutos 5 segundos", "Hola &amp; adiós.", "Luis Pérez   1 minutos 2 segundos", "Vale.", "Ana García   2 minutos 10 segundos", "Sí."))
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, "w") as zf:
            zf.writestr("word/document.xml", f'<?xml version="1.0"?><w:document xmlns:w="x"><w:body>{body}</w:body></w:document>')
        r = P("d.docx", bio.getvalue())
        assert r["formato"] == "DOCX" and [(s["s"], s["spk"], s["text"]) for s in r["segments"]] == [
            (5.0, "Ana García", "Hola & adiós."), (62.0, "Luis Pérez", "Vale."), (130.0, "Ana García", "Sí.")], r
        try:
            P("x.txt", "nada que ver\n")
            raise SystemExit("debió fallar")
        except ValueError:
            pass
        long = {"s": 0, "e": 100, "text": " ".join(f"Frase número {i} de prueba." for i in range(20)), "spk": "A"}
        parts = split_long(long)
        assert len(parts) >= 4 and parts[0]["s"] == 0 and parts[-1]["e"] == 100 and all(p["e"] - p["s"] <= 30 for p in parts), parts
    assert speaker("Desconocido") is None and speaker("+34 600 123 456") is None and speaker("  Ana   Ruiz ") == "Ana Ruiz"
    assert name_split("Son las 10:30 ya") == (None, "Son las 10:30 ya") and name_split("hola: que tal")[0] is None
    assert language([{"text": "the cat and the dog are in the house"}]) == "en" and language([{"text": "el gato y la casa"}]) == "es"
    # desfase: la muestra (ASR del vídeo) = la transcripción + 7 s; con otro texto, no hay certeza
    import random
    rng = random.Random(1)
    vocab = [f"palabra{chr(97 + i // 26)}{chr(97 + i % 26)}" for i in range(300)]
    segs = [{"s": 4.0 * i, "e": 4.0 * i + 3.5, "text": " ".join(rng.choice(vocab) for _ in range(9))} for i in range(200)]
    sample = [{"s": s["s"] + 7, "e": s["e"] + 7, "text": s["text"]} for s in segs[20:50]]
    d, ok = align(sample, segs)
    assert ok and abs(d - 7) <= 1, (d, ok)
    d, ok = align([{"s": 0, "e": 3, "text": " ".join(rng.choice(vocab) for _ in range(300))}], segs)
    assert not ok, (d, ok)
    print("ok transcripts")


if __name__ == "__main__":
    _selftest()
