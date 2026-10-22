"""Prueba de humo de una instalación: arranca app.py sin navegador, ping, baja modelos, acta de extremo a extremo y Preguntar.
Uso (con el python de la instalación): python tools/smoke.py [--min] <carpeta_app> <vídeo>
--min: solo ping, modelos, transcribir + LLM (acta breve de un clip corto) y una pregunta; chat fijado a Qwen."""
import json, os, subprocess, sys, time, urllib.request
from pathlib import Path

MIN = "--min" in sys.argv
args = [a for a in sys.argv[1:] if a != "--min"]
app, video = Path(args[0]), args[1]
env = {**os.environ, "ACTAS_NO_BROWSER": "1"}
if MIN:
    env.setdefault("ACTAS_CHAT", "qwen")
(app / ".actas.lock").unlink(missing_ok=True)
proc = subprocess.Popen([sys.executable, "-X", "utf8", "app.py"], cwd=app, env=env)


def call(path, body=None, method=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method or ("POST" if body is not None else "GET"), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def wait(path, field, done, what, limit):
    t0 = time.time()
    while time.time() - t0 < limit:
        call("/api/latido", {})
        j = call(path)
        print(f"{what}: {j.get(field)} {j.get('msg', '')}", flush=True)
        if j[field] == done:
            return j
        if j[field] == "error":
            sys.exit(f"{what} falló: {j.get('error') or j.get('msg')}")
        time.sleep(20)
    sys.exit(f"{what}: tiempo agotado")


try:
    lock = app / ".actas.lock"
    for _ in range(60):
        if lock.exists() and lock.read_text().strip():
            break
        time.sleep(1)
    base = f"http://127.0.0.1:{lock.read_text().strip()}"
    for _ in range(30):
        try:
            assert call("/api/ping") == "actas"
            break
        except OSError:
            time.sleep(1)
    print("ping ok", flush=True)
    call("/api/modelos", {"ids": ["voz", "busq", "peq", "rápida"]} if MIN else {})  # CI: voz, búsqueda, OCR y el 4B (nada se instala solo); completo: los recomendados
    wait("/api/modelos", "state", "done", "modelos", 3600)
    t0 = time.time()
    call("/api/generar", {"video": video, "nivel": "breve" if MIN else "normal", "asr": "calidad"})
    j = wait("/api/job", "state", "done", "acta", 3600)
    acta = app / "work" / j["result"]["id"] / j["result"]["acta"] / "index.html"
    assert acta.is_file() and acta.stat().st_size > 500, acta
    print(f"acta ok {acta} ({time.time() - t0:.0f} s)", flush=True)
    if not MIN:
        vtt = app / "work" / "smoke.vtt"  # transcripción importada sin vídeo: sin ASR ni capturas, solo el LLM
        vtt.write_text("WEBVTT\n\n" + "".join(f"{i}\n00:00:{5 * i:02d}.000 --> 00:00:{5 * i + 4:02d}.000\n<v {n}>{t}</v>\n\n" for i, (n, t) in enumerate(
            [("Laura", "Buenos días a todos. Hoy revisamos el presupuesto del proyecto."), ("Carlos", "El plan cuesta veinticinco euros al mes."),
             ("Laura", "Decidimos lanzar la versión nueva el martes."), ("Carlos", "Yo me encargo de enviar el informe final."),
             ("Laura", "Gracias y hasta la próxima reunión.")]) ), encoding="utf-8")
        call("/api/generar", {"transcripcion": str(vtt), "nivel": "breve"})
        j2 = wait("/api/job", "state", "done", "acta (transcripción)", 3600)
        h = (app / "work" / j2["result"]["id"] / j2["result"]["acta"] / "index.html").read_text(encoding="utf-8")
        assert "Participantes: Laura, Carlos" in h and "<video" not in h, h[:2000]
        print("acta importada ok", flush=True)
    r = urllib.request.urlopen(urllib.request.Request(base + "/api/preguntar", data=json.dumps(
        {"sel": f"{j['result']['id']}|calidad", "q": "¿De qué se habló?"}).encode(), headers={"Content-Type": "application/json"}), timeout=900).read().decode()
    print("preguntar:", r[:300], flush=True)
    assert '"k": "error"' not in r, r
finally:
    if os.name == "nt":  # terminate() no mata al llama-server hijo y bloquearía la desinstalación
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()
