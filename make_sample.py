"""Genera samples/reunion_sintetica.mp4: reunión falsa en español (espeak-ng + diapositivas PIL).
Mezcla vista de participantes (caras) y pantalla compartida, para probar el pipeline sin grabación real."""
import subprocess, tempfile, wave
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "samples" / "reunion_sintetica.mp4"
W, H = 1280, 720
VOICES = {"Laura": "es+f3", "Carlos": "es+m3", "Marta": "es+f2", "Javier": "es-419+m1"}
COLORS = {"Laura": "#7b4b94", "Carlos": "#2e6f95", "Marta": "#b5543c", "Javier": "#3c8d5a"}


def font(size, bold=False):
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default(size)


def heads(active):
    im = Image.new("RGB", (W, H), "#1e1e1e")
    d = ImageDraw.Draw(im)
    for i, name in enumerate(VOICES):
        x, y = (i % 2) * W // 2, (i // 2) * H // 2
        d.rectangle([x + 8, y + 8, x + W // 2 - 8, y + H // 2 - 8], fill="#2b2b2b",
                    outline="#3ddc84" if name == active else "#2b2b2b", width=6)
        cx, cy = x + W // 4, y + H // 4 - 10
        d.ellipse([cx - 70, cy - 70, cx + 70, cy + 70], fill=COLORS[name])
        d.text((cx, cy), name[0], font=font(70, True), fill="white", anchor="mm")
        d.text((x + 24, y + H // 2 - 50), name, font=font(22), fill="white")
    return im


def slide(title, bullets, presenter, app=False):
    im = Image.new("RGB", (W, H), "#f4f4f4" if app else "white")
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 34], fill="#3ddc84")
    d.text((W // 2, 17), f"{presenter} está compartiendo pantalla", font=font(16), fill="black", anchor="mm")
    d.text((70, 80), title, font=font(44, True), fill="#1d3557")
    d.line([70, 145, W - 70, 145], fill="#e63946", width=4)
    for i, b in enumerate(bullets):
        y = 180 + i * (52 if app else 70)
        if app:
            d.rectangle([70, y - 6, W - 70, y + 40], outline="#bbbbbb", fill="white")
            d.text((90, y), b, font=font(24), fill="#333333")
        else:
            d.text((80, y), "•  " + b, font=font(30), fill="#222222")
    return im


S1 = ("Resultados del tercer trimestre", ["Usuarios activos mensuales: 42.000 (+18%)",
      "Ingresos: 120.000 € (objetivo 130.000 €)", "Tasa de abandono: del 9% al 6%"])
S2 = ("Incidencias abiertas", ["Pagos móviles: nueva librería del proveedor el 15/11",
      "Búsqueda lenta en móviles antiguos", "Error de sincronización del calendario"])
S3 = ("Plan de lanzamiento", ["Fase 1: beta cerrada, 500 usuarios, 2 semanas (1 de diciembre)",
      "Fase 2: beta abierta en España y México", "Fase 3: lanzamiento general el 12 de enero"])
S4 = ("Canales de marketing", ["Redes sociales", "Acuerdos con gimnasios y centros de estética",
      "Campaña de correo a usuarios de la versión anterior", "Presupuesto marketing: 40.000 €"])
S5 = ("Presupuesto del semestre: 200.000 €", ["Desarrollo: 120.000 €", "Marketing: 40.000 €",
      "Infraestructura: 25.000 €", "Reserva: 15.000 €"])
DEMO = ("Reservas · Buscar centro", ["Buscar: \"yoga madrid centro\"", "Estudio Yoga Sol — 4,8 ★ — 1,2 km",
        "Centro Zen Retiro — 4,6 ★ — 2,0 km", "Gimnasio Fit Plaza — 4,1 ★ — 2,4 km",
        "Tiempo de respuesta: 6,4 s (objetivo < 1 s)"])

# (hablante, escena, texto). Escena: None = caras; (diapositiva, nº de viñetas visibles, presentador, es_app)
SCRIPT = [
    ("Javier", None, "Hola, buenos días. ¿Qué tal el fin de semana? Yo estuve en la montaña con la familia, hizo un tiempo estupendo."),
    ("Marta", None, "Qué envidia. Yo me quedé en casa con un resfriado, pero ya estoy mejor."),
    ("Laura", None, "Buenos días a todos, gracias por conectaros. Hoy tenemos la reunión de seguimiento del proyecto de la nueva aplicación de reservas. El orden del día es el siguiente: primero, Carlos nos presentará los resultados del tercer trimestre; después, Marta revisará el plan de lanzamiento; y por último hablaremos del presupuesto y repartiremos las tareas. ¿Os parece bien?"),
    ("Carlos", None, "Perfecto, por mi parte todo bien. Voy a compartir pantalla en un momento."),
    ("Marta", None, "De acuerdo. Yo tengo preparadas las diapositivas del lanzamiento."),
    ("Javier", None, "Bien. Solo un apunte: tengo que salir a las once y media, así que si podemos ver el presupuesto antes de esa hora, mejor."),
    ("Laura", None, "Sin problema, Javier, lo tendremos en cuenta. Carlos, cuando quieras."),
    ("Carlos", (S1, 1, "Carlos", False), "Vale, ¿veis mi pantalla? Esta es la primera diapositiva, con los resultados del tercer trimestre. Los usuarios activos mensuales han llegado a cuarenta y dos mil, lo que supone un crecimiento del dieciocho por ciento respecto al trimestre anterior."),
    ("Carlos", (S1, 2, "Carlos", False), "Los ingresos han sido de ciento veinte mil euros, un poco por debajo del objetivo, que era de ciento treinta mil. La principal causa es el retraso en la integración con los pagos móviles."),
    ("Carlos", (S1, 3, "Carlos", False), "Por otro lado, la tasa de abandono ha bajado del nueve al seis por ciento, sobre todo gracias a las notificaciones de recordatorio que lanzamos en julio."),
    ("Marta", (S1, 3, "Carlos", False), "Carlos, una pregunta. ¿El problema de los pagos móviles ya está resuelto o sigue bloqueado?"),
    ("Carlos", (S2, 3, "Carlos", False), "Buena pregunta, os enseño la siguiente diapositiva. Sigue bloqueado parcialmente. El proveedor de pagos nos ha prometido la nueva versión de su librería para el quince de noviembre. Además tenemos dos incidencias abiertas: la lentitud de la pantalla de búsqueda en móviles antiguos, y un error de sincronización del calendario en algunos dispositivos."),
    ("Javier", (S2, 3, "Carlos", False), "Lo de la búsqueda lo he estado mirando. Si queréis os lo enseño ahora mismo en la aplicación."),
    ("Laura", (S2, 3, "Carlos", False), "Sí, adelante, comparte tú."),
    ("Javier", (DEMO, 5, "Javier", True), "Vale. Esta es la pantalla de búsqueda en un móvil de gama baja. Si busco yoga madrid centro, fijaos que tarda más de seis segundos en mostrar los resultados. El objetivo es que tarde menos de un segundo."),
    ("Javier", (DEMO, 5, "Javier", True), "Creo que es un problema de índices en la base de datos, porque en los móviles nuevos pasa lo mismo cuando hay muchos centros cerca. Puedo encargarme yo de arreglarlo."),
    ("Laura", (DEMO, 5, "Javier", True), "Genial, apunto que Javier se encarga del rendimiento de la búsqueda. ¿Para cuándo podrías tenerlo?"),
    ("Javier", (DEMO, 5, "Javier", True), "Para el viernes de la semana que viene debería estar listo."),
    ("Carlos", None, "Pues eso es todo por mi parte."),
    ("Laura", None, "Gracias, Carlos. Marta, te toca."),
    ("Marta", (S3, 3, "Marta", False), "Gracias. Os comparto mi pantalla. El plan de lanzamiento tiene tres fases. La primera es una beta cerrada con quinientos usuarios durante dos semanas. La segunda es una beta abierta en España y México. Y la tercera es el lanzamiento general, previsto para el doce de enero."),
    ("Marta", (S4, 4, "Marta", False), "En cuanto al marketing, proponemos centrarnos en tres canales: redes sociales, acuerdos con gimnasios y centros de estética, y una campaña de correo electrónico a los usuarios de la versión anterior. El presupuesto estimado para marketing es de cuarenta mil euros."),
    ("Carlos", (S4, 4, "Marta", False), "Me parece bien, pero yo dejaría la campaña de correo para la fase de beta abierta, no antes, para no quemar la base de usuarios."),
    ("Marta", (S4, 4, "Marta", False), "Tiene sentido. Lo cambio en el plan."),
    ("Laura", (S4, 4, "Marta", False), "Entonces decidimos que la campaña de correo electrónico se lanzará en la fase de beta abierta. ¿Todos de acuerdo?"),
    ("Javier", (S4, 4, "Marta", False), "De acuerdo."),
    ("Carlos", (S4, 4, "Marta", False), "Sí, de acuerdo."),
    ("Marta", (S3, 3, "Marta", False), "Vuelvo un momento a la diapositiva anterior para confirmar las fechas. La beta cerrada empezaría el uno de diciembre, siempre que los pagos móviles estén listos a mediados de noviembre."),
    ("Laura", None, "Vale. Marta, ¿puedes dejar de compartir? Pasamos al presupuesto."),
    ("Laura", (S5, 4, "Laura", False), "Comparto yo la tabla del presupuesto. Tenemos un total de doscientos mil euros para el semestre. Desarrollo se lleva ciento veinte mil, marketing cuarenta mil, infraestructura veinticinco mil, y quedan quince mil de reserva."),
    ("Javier", (S5, 4, "Laura", False), "Yo pediría subir infraestructura a treinta mil. Con la beta abierta vamos a necesitar más servidores, y no quiero que el sistema se caiga el primer día."),
    ("Laura", (S5, 4, "Laura", False), "Lo podemos sacar de la reserva. Queda decidido: infraestructura sube a treinta mil euros y la reserva baja a diez mil."),
    ("Carlos", (S5, 4, "Laura", False), "Perfecto."),
    ("Laura", None, "Bueno, repasemos las tareas antes de que Javier se vaya. Javier arregla el rendimiento de la búsqueda para el viernes de la semana que viene. Carlos habla con el proveedor de pagos para confirmar la fecha del quince de noviembre. Marta actualiza el plan de lanzamiento con la campaña de correo en la beta abierta, y lo envía antes del lunes. Y yo preparo la convocatoria de la beta cerrada."),
    ("Marta", None, "Una cosa más: necesitamos a alguien que redacte las preguntas frecuentes para la beta."),
    ("Carlos", None, "Me lo quedo yo, no hay problema. Lo tendré a final de mes."),
    ("Laura", None, "Perfecto. La próxima reunión será el martes que viene a la misma hora. Gracias a todos y buen día."),
    ("Javier", None, "Gracias, hasta luego."),
]

if __name__ == "__main__":
    OUT.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        concat, wavs = [], []
        for i, (who, scene, text) in enumerate(SCRIPT):
            wav = td / f"{i:03d}.wav"
            subprocess.run(["espeak-ng", "-v", VOICES[who], "-s", "125", "-g", "6", "-w", wav, text], check=True)
            with wave.open(str(wav)) as w:
                dur = w.getnframes() / w.getframerate() + 0.5  # 0.5 s de silencio tras cada frase
            img = td / f"{i:03d}.png"
            (heads(who) if scene is None else slide(scene[0][0], scene[0][1][:scene[1]], scene[2], scene[3])).save(img)
            concat.append(f"file '{img}'\nduration {dur:.3f}\n")
            wavs.append(f"file '{wav}'\n")
            # silencio de 0.5 s
            sil = td / f"{i:03d}s.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono", "-t", "0.5", sil], check=True)
            wavs.append(f"file '{sil}'\n")
        concat.append(f"file '{img}'\n")  # el demuxer concat ignora la duración del último
        (td / "v.txt").write_text("".join(concat))
        (td / "a.txt").write_text("".join(wavs))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", td / "v.txt",
                        "-f", "concat", "-safe", "0", "-i", td / "a.txt", "-vf", "fps=15,format=yuv420p",
                        "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-c:a", "aac", "-b:a", "64k",
                        "-shortest", OUT], check=True)
    print(OUT)
