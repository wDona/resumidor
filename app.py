"""Interfaz Gradio: subir vídeo -> acta HTML con vídeo, capturas y marcas de tiempo."""
import atexit
import html
import json
import os
import re
from pathlib import Path
from urllib.parse import quote

import gradio as gr

import pipeline
import rag

THREADS = int(os.environ.get("ACTAS_THREADS", pipeline.PHYS))


def generar(video, nivel, asr, nombres, progress=gr.Progress()):
    if not video:
        raise gr.Error("Sube primero un vídeo")
    parar_llm()  # dos modelos de 3 GB a la vez no caben en 8 GB
    names = {n: v.strip() for n, v in re.findall(r"[Hh]ablante\s*(\d+)\s*=\s*([^,;\n]+)", nombres or "")}
    try:  # con todo en caché (p. ej. solo cambian los nombres) no se repite ni el ASR ni el LLM
        out, zpath, _ = pipeline.run(video, nivel, asr, THREADS, lambda f, m: progress(f, desc=m), names)
    except Exception as e:
        raise gr.Error(str(e))
    src = f"/gradio_api/file={quote((out / 'index.html').as_posix())}"
    rec = pipeline.recommend_pct(json.loads((out.parent / f"cortes_{asr}.json").read_text()))
    return (f'<iframe src="{src}" style="width:100%;height:85vh;border:1px solid #ddd;border-radius:6px"></iframe>',
            str(zpath), gr.Slider(value=rec, label=f"% del vídeo a quitar (recomendado: {rec} %)"), str(out.parent))


def condensar(wd, asr, pct, progress=gr.Progress()):
    if not wd:
        raise gr.Error("Genera primero el acta")
    try:
        out, _, _ = pipeline.condense(wd, asr, int(pct), THREADS, lambda f, m: progress(f, desc=m))
    except Exception as e:
        raise gr.Error(str(e))
    # <video> nativo: el reproductor de gr.Video reaplica "muted" en cada repintado y el botón de silencio no responde
    src = f"/gradio_api/file={quote(Path(out).as_posix())}"
    return f'<video src="{src}" controls preload="metadata" style="width:100%;max-height:70vh"></video>', str(out)


# ---------- Preguntar: una pregunta = una llamada independiente (sin historial; lo de abajo es solo visual) ----------
_llm, _idx = {}, {}


def parar_llm():
    if _llm.get("proc"):
        _llm.pop("proc").terminate()
    _llm.clear()


atexit.register(parar_llm)


def reuniones():
    """Reuniones ya procesadas (con transcripción), la más reciente primero: (nombre del vídeo, carpeta)."""
    out = []
    for wd in sorted(pipeline.WORK.glob("*/transcript_*.json"), key=os.path.getmtime, reverse=True):
        v = next(wd.parent.glob("video.*"), None)
        name = (v.resolve().name if v else wd.parent.name) + ("" if "rápido" in wd.name else " (calidad)")
        out.append((name, f"{wd.parent}|{wd.stem.split('_', 1)[1]}"))
    return out


def video_html(sel):
    v = next(Path(sel.split("|")[0]).glob("video.*"), None) if sel else None
    return (f'<video id="qav" controls preload="metadata" style="width:100%;max-height:45vh" '
            f'src="/gradio_api/file={quote(v.as_posix())}"></video>') if v else ""


def ts(t):
    return f'<a class="ts" href="#" data-t="{int(t)}">[{pipeline.fmt(t)}]</a>'


def cita(idx, i):
    """Cita literal desplegable con los tramos vecinos (en gris)."""
    parts = [f'<span style="opacity:{1 if j == i else .55}">{ts(idx.segs[j]["s"])} {html.escape(idx.segs[j]["text"])}</span>'
             for j in idx.window(i)]
    return f'<details><summary>cita literal</summary><blockquote>{"<br>".join(parts)}</blockquote></details>'


def preguntar(sel, q, hist):
    if not sel or not (q or "").strip():
        raise gr.Error("Elige una reunión y escribe la pregunta")
    wd, quality = sel.split("|")
    if sel not in _idx:
        _idx[sel] = rag.Index(wd, quality, THREADS)
    idx, q = _idx[sel], q.strip()
    head = f"<h4>{html.escape(q)}</h4>"
    cands, lines, done = "", [], False
    if not _llm.get("url"):
        yield head + "<p><i>Arrancando el modelo de lenguaje…</i></p>", hist
        _llm["url"], _llm["proc"] = rag.server(THREADS)
    for kind, v in rag.answer(idx, q, _llm["url"]):
        if kind == "candidatos":
            cands = "".join(f"<li>{ts(idx.segs[i]['s'])} {html.escape(idx.segs[i]['text'][:200])}</li>" for i in v)
        elif kind == "frase":
            s = idx.segs[v["i"]]
            txt = html.escape(v["frase"]) if v["ok"] else (f"Se dijo: «{html.escape(s['text'])}» <small style='opacity:.6'>"
                                                           "(texto literal: la frase del modelo no se pudo verificar)</small>")
            lines.append(f"<p>{txt} {ts(s['s'])}{cita(idx, v['i'])}</p>")
        elif kind == "nada":
            lines.append(f"<p><b>{rag.NOT_SAID}</b></p>")
        else:
            done = True
        body = "".join(lines) or "<p><i>Buscando en la reunión…</i></p>"
        frag = f"<details{'' if done else ' open'}><summary>Fragmentos recuperados</summary><ol>{cands}</ol></details>"
        yield head + body + frag, hist
    yield head + body + frag, [head + body] + hist


SEEK = """element.addEventListener('click', e => { const a = e.target.closest('a.ts'); if (!a) return;
e.preventDefault(); const v = document.getElementById('qav'); if (v) { v.currentTime = +a.dataset.t; v.play(); } });"""


with gr.Blocks(title="Actas de reuniones") as demo:
    gr.Markdown("## Actas de reuniones\nSube la grabación de una videollamada y genera un acta con resumen, "
                "capturas de la pantalla compartida y marcas de tiempo que saltan al momento del vídeo. Todo local.")
    with gr.Tab("Acta"):
        with gr.Row():
            video = gr.File(label="Vídeo de la reunión", file_types=["video"])
            with gr.Column():
                nivel = gr.Dropdown(list(pipeline.LEVELS), value="normal", label="Nivel de detalle")
                asr = gr.Dropdown(list(pipeline.ASR_MODELS), value="rápido", label="Calidad de transcripción",
                                  info="rápido = whisper small · calidad = large-v3-turbo (más lento)")
                nombres = gr.Textbox(label="Nombres de los hablantes (opcional)", placeholder="Hablante 1=Ana, Hablante 2=Luis",
                                     info="Se aplican al acta sin repetir nada: cámbialos y vuelve a pulsar «Generar acta»")
                boton = gr.Button("Generar acta", variant="primary")
        informe = gr.HTML()
        descarga = gr.File(label="Descargar acta (.zip, sin el vídeo)")
        with gr.Row():
            pct = gr.Slider(10, 90, value=40, step=1, label="% del vídeo a quitar",
                            info="Primero los silencios largos, después lo menos importante según el acta")
            condensa = gr.Button("Generar vídeo condensado")
        condensado = gr.HTML(label="Vídeo condensado")
        bajar = gr.File(label="Descargar vídeo condensado")
        carpeta = gr.State("")
        boton.click(generar, [video, nivel, asr, nombres], [informe, descarga, pct, carpeta])
        condensa.click(condensar, [carpeta, asr, pct], [condensado, bajar])

    with gr.Tab("Preguntar"):
        gr.Markdown("Pregunta sobre una reunión ya procesada. Solo se responde con lo dicho en ella, en estilo indirecto "
                    "y con la marca que salta al vídeo; si no se dijo: «No se menciona en la reunión». Cada pregunta es "
                    "independiente (no recuerda las anteriores).")
        with gr.Row():
            reunion = gr.Dropdown(reuniones(), label="Reunión", scale=3)
            refrescar = gr.Button("↻", scale=0)
        reproductor = gr.HTML()
        with gr.Row():
            pregunta = gr.Textbox(label="Pregunta", scale=5, submit_btn=True)
        respuesta = gr.HTML(js_on_load=SEEK)
        anteriores = gr.State([])
        pasadas = gr.HTML(js_on_load=SEEK)
        refrescar.click(lambda: gr.Dropdown(choices=reuniones()), None, reunion)
        reunion.change(lambda s: (video_html(s), []), reunion, [reproductor, anteriores])
        pregunta.submit(preguntar, [reunion, pregunta, anteriores], [respuesta, anteriores])
        anteriores.change(lambda h: "<hr>".join(h[1:]), anteriores, pasadas)

if __name__ == "__main__":
    pipeline.WORK.mkdir(exist_ok=True)
    # el vídeo de work/<hash>/ puede ser un enlace simbólico a otra carpeta: Gradio solo sirve rutas permitidas reales
    vids = {str(v.resolve().parent) for v in pipeline.WORK.glob("*/video.*")}
    demo.queue().launch(allowed_paths=[str(pipeline.WORK), *vids], inbrowser=True)
