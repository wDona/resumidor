"""Clasifica cada ítem del gold por la PRIMERA etapa donde desaparece (ver eval/perdidas.md):
a = ASR (no está en la transcripción), b = map (ninguna salida del map lo cubre), c = selección/filtro (está en el map pero no en
el acta), d = redacción (seleccionado pero ausente del acta final), e = presente.
Coincidencia: regex del gold sobre texto normalizado, en la ventana del gold ±90 s (claves y e: como score.py).
Reutiliza las cachés (run() ya hecho): captura maps/red al pasar por render().
uv run eval/perdidas.py [--tag v2] [--solo larga_cne,real_clickmeeting] [--nivel normal] [-v]   (--tag: sufijo de ACTAS_TAG con que se generó)"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))
import pipeline as P  # noqa: E402
from score import hit, norm  # noqa: E402

arg = lambda k, d: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d
level, tag, verbose = arg("--nivel", "normal"), arg("--tag", ""), "-v" in sys.argv
cap = {}
_render = P.render


def spy(*a, **k):
    cap.update(red=a[4], maps=a[5], segments=a[8])
    return _render(*a, **k)


P.render = spy
W = 90
tot, lost, dist = {}, [], []
print(f"{'reunión':20} {'ítems':>5} a b c d e")
for gf in sorted((ROOT / "eval" / "gold").glob("*.json")):
    g = json.loads(gf.read_text())
    if "--solo" in sys.argv and g["video"] not in arg("--solo", "").split(","):
        continue
    video = ROOT / "samples" / f"{g['video']}.mp4"
    P.run(video, level, "rápido")
    red, maps, segs = cap["red"], cap["maps"], cap["segments"]
    wd = P.WORK / g["hash"]
    acta = json.loads((wd / f"acta_{level}_rápido{'_' + tag if tag else ''}" / "acta.json").read_text())
    sel = P.select_points(maps, P.LEVELS[level]["keep"], P.LEVELS[level]["pts"], P.LEVELS[level]["pts"], not P.LEVELS[level]["secs"])
    seltxt = [(t, x) for t, x, _, _ in sel] + [(P.parse_ts(d["t"]), d["texto"]) for d in red["decisiones"]] + \
             [(P.parse_ts(d["t"]), d["tarea"]) for d in red["tareas"]]
    content = " \n ".join([acta["resumen"]] + [p["texto"] for p in acta["puntos"]] + [r["texto"] for r in acta["relato"]] +
                          [s["titulo"] + ". " + s["resumen"] for s in acta["secciones"]] +
                          [d["texto"] for d in acta["decisiones"]] + [t["tarea"] + " " + t.get("responsable", "") for t in acta["tareas"]])
    mp = [(P.parse_ts(p["t"]), p["texto"]) for m in maps for p in m["puntos"]] + \
         [(P.parse_ts(r["t"]), r["texto"]) for m in maps for r in m.get("relato", [])] + \
         [(P.parse_ts(d["t"]), d["texto"]) for m in maps for d in m["decisiones"]] + \
         [(P.parse_ts(d["t"]), d["tarea"]) for m in maps for d in m["tareas"]]
    items = [(k, x, tuple(x["t"])) for k in ("decisiones", "tareas") for x in g[k]] + [("claves", x, (x["t"], x["t"])) for x in g["claves"]]
    cnt = dict.fromkeys("abcde", 0)
    for kind, x, (lo, hi) in items:
        rx = lambda txt: any(re.search(r, norm(txt)) for r in ([x["re"]] if isinstance(x["re"], str) else x["re"]))
        inw = lambda lst: [txt for t, txt in lst if lo - W <= t <= hi + W]
        coarse = rx(content) if kind == "claves" else any(rx(t) for t in inw(
            [(p["t"], p["texto"]) for p in acta["puntos"]] + [(r["t"], r["texto"]) for r in acta["relato"]]))
        in_acta = coarse or any(hit(d["texto"], d["t"], x) for d in acta["decisiones"] + [{**t, "texto": t["tarea"]} for t in acta["tareas"]]) \
            if kind != "claves" else coarse
        st = ("a" if not rx(" ".join(s["text"] for s in segs if lo - W <= s["s"] <= hi + W)) else
              "b" if not any(rx(t) for t in inw(mp)) else
              "e" if in_acta else "d" if any(rx(t) for t in inw(seltxt)) else "c")
        cnt[st] += 1
        tot[st] = tot.get(st, 0) + 1
        if st != "e":
            lost.append(f"| {g['video']} | {kind[:-1] if kind != 'claves' else 'clave'} {x.get('id', '')} (t={lo}) {x['texto'][:60]} | {st} |")
    print(f"{g['video']:20} {len(items):5} " + " ".join(str(cnt[k]) for k in "abcde"))
    tf = wd / f"timings_rápido_{level}{'_' + tag if tag else ''}.json"
    if tf.exists() and "tipos" in (t := json.loads(tf.read_text())):
        dist.append(f"| {g['video']} | " + " ".join(f"{k}:{v}" for k, v in t["tipos"].items()) + f" | {t['protegidos']} |")
print(f"{'TOTAL':20} {sum(tot.values()):5} " + " ".join(str(tot.get(k, 0)) for k in "abcde"))
if verbose or True:
    print("\n".join(lost))
if dist:
    print("\n| reunión | tipos | protegidos |\n|---|---|---|\n" + "\n".join(dist))
