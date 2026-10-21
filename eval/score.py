"""Puntúa las actas (work/<hash>/acta_<nivel>_<asr>/acta.json) contra eval/gold/*.json.

Decisiones/tareas: un elemento del acta acierta si su texto casa con un elemento del gold (regex sobre texto normalizado o
≥ 60 % de palabras en orden) y su marca cae en la ventana del gold (±60 s). P = aciertos / elementos del acta,
R = gold obligatorios recogidos / obligatorios. prohib = prohibidos que aparecen; resp✗ = responsable que no es el dicho.
claves = puntos clave mencionados (y los de la 2.ª mitad); pts2 = viñetas con marca en la 2.ª mitad;
corte = resúmenes que no acaban en signo de puntuación; nolat = caracteres no latinos.
uv run eval/score.py [-v] [--asr rápido]"""
import json, re, sys
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import words  # noqa: E402

LEVELS = ("breve", "normal", "detallado")
norm = lambda t: " ".join(words(t or ""))
END = re.compile(r"[.!?…»”\")\]]\s*$")
latin = lambda c: ord(c) <= 0x24F or 0x2000 <= ord(c) <= 0x206F or c in "€№"


def hit(text, t, g):
    n = norm(text)
    ok = any(re.search(r, n) for r in g["re"]) or \
        SequenceMatcher(None, words(text), words(g["texto"]), autojunk=False).ratio() >= 0.6
    return ok and g["t"][0] - 60 <= t <= g["t"][1] + 60


def score(acta, gold):
    dur = gold["dur"]
    pool = {"decisiones": gold["decisiones"] + [g for g in gold["tareas"] if g.get("kind") == "any"],
            "tareas": gold["tareas"] + [g for g in gold["decisiones"] if g.get("kind") == "any"]}
    got, res, bad = set(), {}, []
    for k, key in (("decisiones", "texto"), ("tareas", "tarea")):
        tp = 0
        for it in acta[k]:
            m = [g for g in pool[k] if hit(it[key], it["t"], g)]
            got |= {g["id"] for g in m}
            tp += bool(m)
            if not m:
                bad.append(f"FP {k[:3]} [{it['t'] // 60}:{it['t'] % 60:02d}] {it[key]}")
            resp = it.get("responsable", "—").strip(" —-")
            if resp and m and not any(g.get("owner") and re.search(g["owner"], norm(resp)) for g in m):
                res["resp"] = res.get("resp", 0) + 1
                bad.append(f"responsable✗ {it[key]} | {it['responsable']}")
        res[k] = tp / len(acta[k]) if acta[k] else None
    for k in ("decisiones", "tareas"):  # recall al final: un gold "any" lo puede recoger una tarea o una decisión
        req = [g["id"] for g in gold[k] if g.get("req")]
        res[k] = (res[k], sum(i in got for i in req) / len(req) if req else None)
    items = [(d["texto"], d) for d in acta["decisiones"]] + [(t["tarea"] + " " + t.get("responsable", ""), t)
                                                               for t in acta["tareas"]]
    content = " \n ".join([acta["resumen"]] + [p["texto"] for p in acta["puntos"]] +
                          [s["titulo"] + ". " + s["resumen"] for s in acta["secciones"]] + [x for x, _ in items])
    forb = 0
    for f in gold["prohibidos"]:
        hits = [x for x, _ in items if re.search(f["re"], norm(x))] if f["where"] == "items" else \
            [x for x in content.split(" \n ") if re.search(f["re"], norm(x))]
        forb += len(hits)
        bad += [f"PROHIBIDO ({f['texto']}): {x[:140]}" for x in hits]
    cov = [c for c in gold["claves"] if re.search(c["re"], norm(content))]
    late = [c for c in gold["claves"] if c["t"] > dur / 2]
    bad += [f"falta clave [{c['t'] // 60}:{c['t'] % 60:02d}] {c['texto']}" for c in gold["claves"] if c not in cov]
    sums = [acta["resumen"]] + [s["resumen"] for s in acta["secciones"]]
    cut = [s[-40:] for s in sums if not END.search(s)]
    bad += [f"cortado: …{s}" for s in cut]
    alltext = json.dumps(acta, ensure_ascii=False)
    nolat = [c for c in alltext if not latin(c)]
    pts = acta["puntos"]
    return dict(dec=res["decisiones"], tar=res["tareas"], forb=forb, resp=res.get("resp", 0),
                claves=(len(cov), len(gold["claves"])), late=(sum(c in cov for c in late), len(late)),
                pts2=(sum(p["t"] > dur / 2 for p in pts), len(pts)), cut=len(cut), nolat="".join(nolat)), bad


def main():
    alta = f"_{sys.argv[sys.argv.index('--tag') + 1]}" if "--tag" in sys.argv else ""
    verbose, asr = "-v" in sys.argv, sys.argv[sys.argv.index("--asr") + 1] if "--asr" in sys.argv else "rápido"
    f = lambda pr: "  -  " if pr is None else f"{pr:4.2f}"
    print(f"{'vídeo':18} {'nivel':9} {'dec P/R':11} {'tar P/R':11} prohib resp✗ claves 2ªmitad pts2  corte nolat")
    for gf in sorted((ROOT / "eval" / "gold").glob("*.json")):
        gold = json.loads(gf.read_text())
        for lv in LEVELS:
            p = ROOT / "work" / gold["hash"] / f"acta_{lv}_{asr}{alta}" / "acta.json"
            if not p.exists():
                print(f"{gold['video']:18} {lv:9} (sin acta.json)")
                continue
            s, bad = score(json.loads(p.read_text()), gold)
            print(f"{gold['video']:18} {lv:9} {f(s['dec'][0])}/{f(s['dec'][1])} {f(s['tar'][0])}/{f(s['tar'][1])} "
                  f"{s['forb']:6} {s['resp']:5} {s['claves'][0]:2}/{s['claves'][1]:<3} {s['late'][0]}/{s['late'][1]:<5} "
                  f"{s['pts2'][0]:2}/{s['pts2'][1]:<3} {s['cut']:4} {s['nolat'] or '-'}")
            if verbose:
                print("".join(f"    {b}\n" for b in bad), end="")


if __name__ == "__main__":
    main()
