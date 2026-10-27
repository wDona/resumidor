"""E2E real: pipeline completo sobre tests_data/reunion.vtt con la CLI `claude` (suscripción del usuario), en un ACTAS_WORK temporal.
uv run python -X utf8 tools/e2e_cli.py [--plantilla acta|raid|requisitos|comite] [--nivel normal] [--max-llm-calls 40] [--poblar [--derivar]]"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--plantilla", default="acta")
ap.add_argument("--nivel", default="normal")
ap.add_argument("--max-llm-calls", type=int, default=40)
ap.add_argument("--poblar", action="store_true", help="después, la pasada poblar (F3b) y su comparación con la verdad del fixture")
ap.add_argument("--derivar", action="store_true", help="tras --poblar, derivar historias/Gherkin/preguntas (F5) de los requisitos y buscar lo inventado")
a = ap.parse_args()
sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp = tempfile.mkdtemp(prefix="actas_e2e_")
os.environ["ACTAS_WORK"], os.environ["ACTAS_NO_EMBED"] = tmp, "1"
import carpetas  # noqa: E402
import nube  # noqa: E402
import pipeline as P  # noqa: E402

st = {"n": 0, "cost": 0.0, "in": 0, "out": 0}
_run = subprocess.run


def run(cmd, *k, **kw):
    if str(cmd[0]).lower().rsplit(".", 1)[0].endswith("claude"):
        st["n"] += 1
        if st["n"] > a.max_llm_calls:
            raise SystemExit(f"ABORTADO: más de {a.max_llm_calls} llamadas al LLM")
    r = _run(cmd, *k, **kw)
    try:
        j = json.loads(r.stdout)
        st["cost"] += j.get("total_cost_usd") or 0
        st["in"] += (j.get("usage") or {}).get("input_tokens") or 0
        st["out"] += (j.get("usage") or {}).get("output_tokens") or 0
    except (ValueError, TypeError, AttributeError):
        pass
    return r


nube.subprocess.run = run
cfg = nube.norm({"proveedor": "cli:claude"})
nube.guardar(confirmado=["cli:claude"])  # solo en el work temporal
t0 = time.time()
try:
    out, _, _ = P.run(None, a.nivel, "rápido", 2, lambda f, m: None, transcript=ROOT / "tests_data" / "reunion.vtt", nube=cfg, plantilla=a.plantilla)
finally:
    print(f"\nllamadas={st['n']} tiempo={time.time() - t0:.0f}s coste=US${st['cost']:.3f} tokens={st['in']}in/{st['out']}out")
print("acta.json:", out / "acta.json")
D = json.loads((out / "acta.json").read_text(encoding="utf-8"))
txt = lambda x: json.dumps(x, ensure_ascii=False)
print("claves:", sorted(D))
dec, tar = D.get("decisiones") or [], D.get("tareas") or []
print(f"decisiones={len(dec)} (esp 2) tareas={len(tar)} (esp 3)")
for x in dec:
    print("  D:", x.get("texto"), "| cita:", x.get("cita"), "| verif:", x.get("b"), x.get("n"))
for x in tar:
    print("  T:", x.get("tarea"), "|", x.get("responsable"), "|", x.get("plazo"), "| cita:", x.get("cita"))
for s in D.get("secciones_plantilla") or []:
    its = s.get("items") or []
    print(f"  sec {s.get('id')} seguir={s.get('seguir')} n={len(its)}")
    for x in its:
        print("    -", txt(x)[:230])
bad = [w for w in ("adelantar la beta", "acta anterior", "informe de incidencias", "preguntas frecuentes") if any(w in txt(x).lower() for x in dec + tar)]
print("distractores en decisiones/tareas (debe estar vacío):", bad)
print("tareas con responsable+plazo:", sum(bool(x.get("responsable") and x.get("plazo")) for x in tar))
print("sin cita:", sum(not x.get("cita") for x in dec + tar), "| marca:", D.get("nube"))
mid = out.parent.name
ms = [{"id": mid, "label": "e2e", "mtime": time.time()}]
for it in carpetas.items_doc(carpetas.docs(ms)[0]):
    print("  pendiente:", it["tipo"], it["tipo_ent"], "|", it["texto"][:60], "|", it["resp"], "|", it["plazo"])

# ---------- --poblar: pasada F3b sobre la misma reunión y comparación con lo que dice de verdad tests_data/reunion.vtt ----------
if a.poblar:
    import re
    import poblar
    import registro
    VERDAD = {"decisiones": {"D1 Carlos confirma la fecha con el proveedor": r"proveedor|quince|15", "D2 campaña de correo en la beta abierta": r"campa[ñn]a|correo"},
              "riesgos": {"R1 retraso del proveedor -> beta cerrada": r"proveedor|retras"},
              "preguntas": {"P1 quién redacta las preguntas frecuentes": r"preguntas frecuentes|faq"},
              "requisitos": {"REQ1 pagar con Bizum": r"bizum", "REQ2 búsqueda < 2 s": r"segundos|búsqueda|busqueda", "REQ3 no guardar datos de pago en el móvil": r"datos de pago|guard"},
              "interesados": {"INT1 Elena Ruiz (directora comercial, Hoteles Sol)": r"elena", "INT2 Pedro Gómez (resp. seguridad, cliente)": r"pedro"}}
    vistos, crudo = {v: [] for v in poblar.VISTAS}, {v: 0 for v in poblar.VISTAS}
    _comprobar = poblar.comprobar

    def comprobar(r, segs, texto, vistas):
        ok = _comprobar(r, segs, texto, vistas)
        for v in vistas:
            crudo[v] += len(r.get(v) or [])
        for v, it in ok:
            vistos[v].append(it)
        return ok
    poblar.comprobar = comprobar
    (out.parent / "meta.json").write_text(json.dumps({"carpeta": "E2E", "nombre": "e2e"}))
    n0, c0, t1 = st["n"], st["cost"], time.time()
    info = poblar.poblar("E2E", ms, lambda: nube.backend(cfg))
    print(f"\nPOBLAR llamadas={st['n'] - n0} tiempo={time.time() - t1:.0f}s coste=US${st['cost'] - c0:.3f} | info: creadas={info['creadas']} citas={info['citas']} descartadas={info['descartadas']}")
    print(f"{'vista':12} {'modelo':>6} {'verif':>5} {'TP':>3} {'FP':>3} {'FN':>3}")
    filas = []
    for v, tr in VERDAD.items():
        its, libres, fp = vistos[v], dict(tr), []
        for it in its:
            s = (it["texto"] + " " + it["cita"]).lower()
            k = next((k for k, rx in libres.items() if re.search(rx, s)), None)
            libres.pop(k) if k else fp.append(it)
        print(f"{v:12} {crudo[v]:>6} {len(its):>5} {len(tr) - len(libres):>3} {len(fp):>3} {len(libres):>3}")
        filas.append((v, its, fp, libres))
    for v, its, fp, libres in filas:
        for it in its:
            print(f"  {v[:3].upper()} {'FP ' if it in fp else 'ok '} [{P.fmt(it['t'])}] {it['texto']} | " + " · ".join(f"{k}={x}" for k, x in it.items() if k not in ('texto', 'cita', 't') and x) + f" | «{it['cita']}»")
        for k in libres:
            print(f"  {v[:3].upper()} FN  {k}")
    print("registro:", {t: len([x for x in registro.listar("E2E", t) if x["revision"] not in registro.OCULTA]) for t in ("decision", "requisito", "interesado", "riesgo", "pregunta")})

# ---------- --derivar: F5 sobre los requisitos que dejó --poblar; lo inventado (cifras/nombres que no están en el requisito ni su cita) ----------
if a.poblar and a.derivar:
    import derivar
    crudo = {}
    _comp = derivar.comprobar

    def comp(r, req, citas):
        crudo[req["codigo"]] = r
        return _comp(r, req, citas)
    derivar.comprobar = comp
    n0, c0, t1 = st["n"], st["cost"], time.time()
    info = derivar.derivar("E2E", lambda: nube.backend(cfg))
    print(f"\nDERIVAR llamadas={st['n'] - n0} tiempo={time.time() - t1:.0f}s coste=US${st['cost'] - c0:.3f} | creadas={info['creadas']} descartadas={info['descartadas']} omitidas={info['omitidas']}")
    vivos = lambda t: [x for x in registro.listar("E2E", t) if x["revision"] not in registro.OCULTA and x["campos"].get("fuente") == "derivar"]
    for req in registro.listar("E2E", "requisito"):
        if req["revision"] in registro.OCULTA:
            continue
        citas = [x["texto"] for x in registro.citas(req["id"])]
        fuente = " ".join([req["titulo"], req["detalle"] or "", *(str(v) for v in req["campos"].values()), *citas])
        r = crudo.get(req["codigo"]) or {}
        malos = [(k, derivar.inventado([t], fuente)) for h in r.get("historias") or [] for k, t in
                 [("hu", h.get(x, "")) for x in ("como", "quiero", "para")] + [("crit", c.get(x, "")) for c in h.get("criterios") or [] for x in ("dado", "cuando", "entonces")]] +                 [("preg", derivar.inventado([p], fuente)) for p in r.get("preguntas") or []]
        malos = [(k, m) for k, m in malos if m]
        rels = lambda t, rel: [x for x in vivos(t) if any(y["b"] == req["id"] and y["tipo"] == rel for y in registro.completas([x])[0]["relaciones"])]
        hs, ps = rels("historia", "deriva_de"), rels("pregunta", "afecta")
        print(f"\n{req['codigo']} {req['titulo']} | solicitante={req['campos'].get('solicitante', '—')} | citas={citas}")
        print(f"  modelo: {len(r.get('historias') or [])} historias, {sum(len(h.get('criterios') or []) for h in r.get('historias') or [])} criterios, {len(r.get('preguntas') or [])} preguntas"
              f" | INVENTADO en la respuesta cruda (lo quita el filtro): {malos or 'nada'}")
        for h in hs:
            k = h["campos"]
            print(f"  {h['codigo']} Como {k['como']} | quiero {k['quiero']} | para {k['para'] or '—'} | citas heredadas={len(registro.citas(h['id']))}")
            for c in k["criterios"]:
                print(f"     Escenario: {c['escenario']} | Dado {c['dado']} | Cuando {c['cuando']} | Entonces {c['entonces']}")
        for p in ps:
            print(f"  {p['codigo']} ? {p['titulo']}")
        campos = lambda x: [x["campos"][k] for k in ("como", "quiero", "para")] + [c[k] for c in x["campos"]["criterios"] for k in ("escenario", "dado", "cuando", "entonces")]
        sobrevive = [x for x in hs + ps if derivar.inventado(campos(x) if x["tipo"] == "historia" else [x["titulo"]], fuente)]
        print("  inventado que SOBREVIVE al filtro (debe estar vacío):", [x["codigo"] for x in sobrevive])
