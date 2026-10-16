"""Interfaz Gradio: subir vídeo -> acta HTML con vídeo, capturas y marcas de tiempo."""
import os
from urllib.parse import quote

import gradio as gr

import pipeline

THREADS = int(os.environ.get("ACTAS_THREADS", pipeline.PHYS))


def generar(video, nivel, asr, progress=gr.Progress()):
    if not video:
        raise gr.Error("Sube primero un vídeo")
    try:
        out, zpath, _ = pipeline.run(video, nivel, asr, THREADS, lambda f, m: progress(f, desc=m))
    except Exception as e:
        raise gr.Error(str(e))
    src = f"/gradio_api/file={quote((out / 'index.html').as_posix())}"
    return f'<iframe src="{src}" style="width:100%;height:85vh;border:1px solid #ddd;border-radius:6px"></iframe>', str(zpath)


with gr.Blocks(title="Actas de reuniones") as demo:
    gr.Markdown("## Actas de reuniones\nSube la grabación de una videollamada y genera un acta con resumen, "
                "capturas de la pantalla compartida y marcas de tiempo que saltan al momento del vídeo. Todo local.")
    with gr.Row():
        video = gr.File(label="Vídeo de la reunión", file_types=["video"])
        with gr.Column():
            nivel = gr.Dropdown(list(pipeline.LEVELS), value="normal", label="Nivel de detalle")
            asr = gr.Dropdown(list(pipeline.ASR_MODELS), value="rápido", label="Calidad de transcripción",
                              info="rápido = whisper small · calidad = large-v3-turbo (más lento)")
            boton = gr.Button("Generar acta", variant="primary")
    informe = gr.HTML()
    descarga = gr.File(label="Descargar acta (.zip, sin el vídeo)")
    boton.click(generar, [video, nivel, asr], [informe, descarga])

if __name__ == "__main__":
    pipeline.WORK.mkdir(exist_ok=True)
    demo.queue().launch(allowed_paths=[str(pipeline.WORK)], inbrowser=True)
