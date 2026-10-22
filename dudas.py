"""Confianza: marca lo dudoso de un documento (a posteriori, sin tocar los datos ni los hashes de la caché del acta).
Resultado en dudas.json junto a la versión, cacheado por hash del contenido: {dudas: {ruta data-p: [motivos]}, segs: {n: [motivos]}}.
Una ruta editada respecto al original deja de estar marcada (el usuario ya la revisó)."""
import bisect
import hashlib
import json
import re

import exportar as X
import pipeline as P
import rag

LP, NS, CR, PW = -1.0, 0.6, 2.4, 0.5  # umbrales de Whisper: avg_logprob, no_speech_prob, compression_ratio, probabilidad de palabra
VENT = (30, 120)  # segundos antes/después de la marca del punto donde se busca su origen
STEM = lambda w: w[:5]


def _mmss(t):
    return f"{int(t) // 60}:{int(t) % 60:02d}"


def _get(o, ruta):
    try:
        for k in ruta.split("."):
            o = o[int(k) if k.isdigit() else k]
        return o
    except (KeyError, IndexError, TypeError):
        return None


def asr_dudas(segs):
    """(por segmento {i: [motivos]}, palabras dudosas {norm: (p, i, palabra)}). Palabras con p<0.5 que son nombres, cifras o raras."""
    frec = {}
    for s in segs:
        for w in P.words(s["text"]):
            frec[w] = frec.get(w, 0) + 1
    por_seg, pal = {}, {}
    for i, s in enumerate(segs):
        m = []
        if s.get("lp") is not None and s["lp"] < LP:
            m.append(f"transcripción poco fiable (log-prob {s['lp']})")
        if s.get("ns") is not None and s["ns"] > NS:
            m.append(f"posible no-habla ({s['ns']})")
        if s.get("cr") is not None and s["cr"] > CR:
            m.append(f"texto repetitivo (compresión {s['cr']})")
        for n, w in enumerate(s.get("words") or []):
            txt = w["w"].strip(" ,.;:¿?¡!()\"«»")
            if w.get("p", 1) >= PW or not txt:
                continue
            nm = P.words(txt)
            if not nm:
                continue
            if any(ch.isdigit() for ch in txt) or (txt[:1].isupper() and n > 0) or (len(nm[0]) >= 7 and frec.get(nm[0], 0) == 1):
                pal[nm[0]] = (w["p"], i, txt)
                m.append(f"voz dudosa: «{txt}» (p={w['p']})")
        if m:
            por_seg[i] = m
    return por_seg, pal


def _items(c):
    """[(ruta, texto, t, cita|None, tipo)] de lo editable: los mismos data-p que pinta exportar.html_doc."""
    out = []
    for cl, _, its in X.bloques(c):
        for x in its if cl in ("texto", "parrafos", "lista", "tareas", "secciones") else []:
            if cl == "tareas":
                cita = (_get(c["data"], x["k"].rsplit(".", 1)[0]) or {}).get("cita", "")
                out += [(x["k"], x["texto"], x["t"], cita, "texto"), (x["kr"], x["resp"], x["t"], None, "resp"), (x["kp"], x["plazo"], x["t"], None, "plazo")]
            elif cl == "secciones":
                out += [(x["kt"], x["titulo"], x["t"], None, "texto"), (x["kr"], x["resumen"], x["t"], None, "texto")]
                out += [(p["k"], p["texto"], p["t"], None, "texto") for p in x["puntos"]]
            else:
                out.append((x["k"], x["texto"], x.get("t"), x.get("cita") if "cita" in x else None, "texto"))
    return out


def analizar(c, fr=None):
    """-> {dudas, segs}. c: documento cargado (exportar.carga); fr: {img: {t?, text}} OCR de capturas (privacidad.frames)."""
    segs, D = c["segs"], c["data"]
    por_seg, pal = asr_dudas(segs)
    starts = [s["s"] for s in segs]
    todo = "\n".join(s["text"] for s in segs)
    ocr = [(k["t"], fr[k["img"]]["text"]) for k in D.get("capturas", []) if fr and fr.get(k["img"], {}).get("text")]
    todo_ocr = "\n".join(t for _, t in ocr)
    dudas = {}

    def add(r, m):
        if m not in dudas.setdefault(r, []):
            dudas[r].append(m)
    for ruta, txt, t, cita, tipo in _items(c):
        if not (txt or "").strip(" —-"):
            continue
        if t is None:  # resumen: sin marca de tiempo, se compara con todo
            lo, hi = 0, len(segs)
            src_ocr, w_lo, w_hi = todo_ocr, -1e9, 1e9
        else:
            lo, hi = bisect.bisect_left(starts, t - VENT[0]), bisect.bisect_right(starts, t + VENT[1])
            src_ocr, w_lo, w_hi = "\n".join(x for tt, x in ocr if t - VENT[0] <= tt <= t + VENT[1]), t - VENT[0], t + VENT[1]
        src = "\n".join(s["text"] for s in segs[lo:hi]) + "\n" + src_ocr
        if tipo == "resp":
            if not any(w in set(P.words(todo + " " + todo_ocr)) for w in P.words(txt)):
                add(ruta, "el responsable no aparece en la transcripción")
            continue
        if tipo == "texto" and cita is not None:
            if not cita.strip():
                add(ruta, "sin cita que lo respalde")
            elif len(P.words(cita)) >= 3 and not rag.quote_ok(cita, src) and not rag.quote_ok(cita, todo + "\n" + todo_ocr):
                add(ruta, "la cita no aparece literalmente en la transcripción")
        if lo < hi or t is None:
            ref = src + "\n" + (cita or "")
            malas = rag.bad_nums(P.hh(txt), P.hh(ref))
            ws = set(P.words(ref))
            malas += [m for m in P.MONTHS if m in P.words(txt) and m not in ws]
            if malas:
                add(ruta, "cifra o fecha que no está en el origen: " + ", ".join(dict.fromkeys(malas)))
        if tipo == "texto" and (lo < hi or t is None):
            cw = [STEM(w) for w in P.words(txt) if len(w) >= 5 and not w.isdigit()]
            have = {STEM(w) for w in P.words(src + " " + (cita or ""))}
            if len(cw) >= 4 and sum(w in have for w in cw) / len(cw) < 0.3:
                add(ruta, f"poca coincidencia con la transcripción ({round(100 * sum(w in have for w in cw) / len(cw))} %)")
        # voz: palabras dudosas que el punto usa, y segmentos poco fiables de su zona
        mine = set(P.words(txt))
        for w in sorted(mine & set(pal)):
            p, i, orig = pal[w]
            if t is None or lo <= i < hi:
                add(ruta, f"voz dudosa: «{orig}» (p={p})")
        if t is not None:
            a, b = bisect.bisect_left(starts, t - 3), bisect.bisect_right(starts, t + 25)
            for i in range(a, b):
                for m in por_seg.get(i, []):
                    if not m.startswith("voz dudosa"):
                        add(ruta, f"{m} en {_mmss(segs[i]['s'])}")
    return {"dudas": dudas, "segs": {str(i): m for i, m in por_seg.items()}}


def calcular(mid, ver):
    """Dudas de la versión vigente (cacheadas en dudas.json por contenido). -> {dudas, segs, n, hash}."""
    import privacidad
    c = X.carga(mid, ver)
    fr = privacidad.frames(c["d"].parent)
    h = hashlib.sha1(json.dumps([c["data"], c["segs"], fr and {k: v.get("text") for k, v in fr.items()}], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    f = c["d"] / "dudas.json"
    try:
        cache = json.loads(f.read_text())
        if cache.get("hash") == h:
            return cache
    except (OSError, ValueError):
        pass
    r = analizar(c, fr)
    if c["editado"]:  # lo editado ya lo revisó el usuario
        orig = json.loads((c["d"] / "acta.json").read_text())
        r["dudas"] = {k: v for k, v in r["dudas"].items() if _get(c["data"], k) == _get(orig, k)}
    r.update(n=len(r["dudas"]), hash=h, asr=any("words" in s or "lp" in s for s in c["segs"]))
    f.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    return r


def demo():
    segs = [{"s": 0, "e": 5, "text": "Hola a todos, hablamos con Marlowe sobre el presupuesto de 500 euros", "lp": -1.4,
             "words": [{"w": "Marlowe", "s": 1, "e": 2, "p": 0.31}, {"w": "500", "s": 3, "e": 4, "p": 0.9}]},
            {"s": 10, "e": 15, "text": "Javier envia el informe el viernes", "lp": -0.3}]
    ps, pal = asr_dudas(segs)
    assert 0 in ps and 1 not in ps and "marlowe" in pal, (ps, pal)
    c = {"segs": segs, "data": {"resumen": "Se habló con Marlowe y se fijó un presupuesto de 700 euros",
                                "decisiones": [{"t": 0, "texto": "Se aprueba el presupuesto de 500 euros", "cita": "el presupuesto de 500 euros"},
                                               {"t": 0, "texto": "Se compra una nave", "cita": "compramos una nave grande"}],
                                "tareas": [], "capturas": []}, "tpl": {"orden": ["resumen", "decisiones"], "titulos": {}, "id": "acta"}, "d": None, "img": "img"}
    r = analizar(c)["dudas"]
    assert "voz dudosa" in r["resumen"][-1] and any("700" in m for m in r["resumen"]), r
    assert "decisiones.0.texto" not in r or all("cita" not in m for m in r["decisiones.0.texto"]), r
    assert any("cita no aparece" in m for m in r["decisiones.1.texto"]), r
    print("ok")


if __name__ == "__main__":
    demo()
