"""Evalúa rag.py con eval/rag_preguntas.json: recall@8, "No se menciona", trampas, paráfrasis, descartes y latencias.
uv run eval/rag_score.py [--solo-recuperacion] [--m reunion]   (ACTAS_LLM_URL reutiliza un llama-server ya arrancado)"""
import json, os, statistics, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pipeline as P
import rag

D = json.loads((Path(__file__).parent / "rag_preguntas.json").read_text())
args = sys.argv[1:]
only = args[args.index("--m") + 1] if "--m" in args else None
retr_only = "--solo-recuperacion" in args
threads = int(os.environ.get("ACTAS_THREADS", 2))

idxs, rows = {}, []
url, proc = (None, None) if retr_only else rag.server(threads)
fold = lambda t: " ".join(P.words(t))
try:
    for q in D["preguntas"]:
        if only and q["m"] != only:
            continue
        if q["m"] not in idxs:
            t0 = time.time()
            idxs[q["m"]] = rag.Index(P.WORK / D["meetings"][q["m"]], threads=threads)
            print(f"índice {q['m']}: {len(idxs[q['m']].segs)} tramos, {time.time() - t0:.1f} s", flush=True)
        idx, gold = idxs[q["m"]], set(q.get("gold", []))
        hit = lambda i: any(P.fmt(idx.segs[j]["s"]) in gold for j in idx.window(i))
        r = {"m": q["m"], "type": q["type"], "q": q["q"]}
        if retr_only:
            ids, cos = idx.search(q["q"])
            r.update(cos=cos, recall=any(hit(i) for i in ids) if gold else None)
            rows.append(r)
            print(f"{'·' if r['recall'] is None else '✓' if r['recall'] else '✗'} {cos:.3f} {q['type'][:5]} {q['q']}")
            continue
        frases, nada = [], None
        for kind, v in rag.answer(idx, q["q"], url):
            if kind == "candidatos":
                r["recall"] = any(hit(i) for i in v) if gold else None
            elif kind == "frase":
                frases.append({**v, "t": P.fmt(idx.segs[v["i"]]["s"]), "hit": hit(v["i"]), "seg": idx.segs[v["i"]]["text"]})
            elif kind == "nada":
                nada = v
            else:
                r.update(v)
        shown = " ".join(f["frase"] if f["ok"] else f["seg"] for f in frases)  # lo que ve el usuario
        model = fold(" ".join(f["frase"] for f in frases))                    # lo que escribió el LLM
        said = fold(" ".join(f["frase"] for f in frases if f["ok"]))           # frases que pasan la verificación
        r.update(nada=nada, frases=frases,
                 must_ok=all(any(a in fold(shown) for a in m.split("|")) for m in q.get("must", [])),
                 raw_inference=any(w in model for w in q.get("forbid", [])),
                 shown_inference=any(w in said for w in q.get("forbid", [])))
        if q["type"] == "absent":
            r["ok"] = bool(nada)
        elif q["type"] == "trap":
            r["ok"] = not r["shown_inference"] and (not gold or any(f["hit"] for f in frases))
        else:
            r["ok"] = not nada and any(f["hit"] for f in frases) and r["must_ok"]
        rows.append(r)
        print(f"{'✓' if r['ok'] else '✗'} {q['type'][:5]} {r.get('total')} s  {q['q']}  -> "
              + (rag.NOT_SAID + f" ({nada})" if nada else " | ".join(
                  f"[{f['t']}{'' if f['hit'] else '?'}] {f['frase'] if f['ok'] else 'DESCARTADA ' + str(f['faltan'])}"
                  for f in frases)), flush=True)
finally:
    if proc:
        proc.terminate()

import resource
print("RAM pico MB:", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024)
pct = lambda xs: f"{100 * sum(xs) / len(xs):.0f}% ({sum(xs)}/{len(xs)})" if xs else "–"
rec = [r["recall"] for r in rows if r.get("recall") is not None]
print("\nrecall@8:", pct(rec))
if retr_only:
    for t in ("absent", "trap", "factual", "paraphrase"):
        cs = sorted(round(r["cos"], 3) for r in rows if r["type"] == t)
        print(f"cos {t}: {cs}")
    sys.exit()
by = lambda t: [r["ok"] for r in rows if r["type"] == t]
fr = [f for r in rows for f in r["frases"]]
ans = [r for r in rows if r["type"] in ("factual", "paraphrase")]
print("factual:", pct(by("factual")), "· paráfrasis:", pct(by("paraphrase")), "· trampas:", pct(by("trap")),
      "· ausentes:", pct(by("absent")))
print("falso 'no se menciona' en respondibles:", pct([bool(r["nada"]) for r in ans]),
      "· el LLM infirió en trampas (antes de verificar):", pct([r["raw_inference"] for r in rows if r["type"] == "trap"]))
print("frases descartadas por la verificación:", pct([not f["ok"] for f in fr]))
for k in ("recuperacion", "primer_token", "prefill", "gen", "total"):
    xs = sorted(r[k] for r in rows if r.get(k) is not None)
    if xs:
        print(f"{k}: p50 {statistics.median(xs):.2f} s · p90 {xs[int(0.9 * (len(xs) - 1))]:.2f} s · máx {xs[-1]:.2f} s")
toks = [r["prompt_tok"] for r in rows if r.get("prompt_tok")]
if toks:
    print("tokens de prompt: p50", statistics.median(toks))
(Path(__file__).parent / "rag_resultados.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
