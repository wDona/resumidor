"""Preguntas sobre UNA reunión ya procesada. Recupera tramos de 15 s (y textos de pantalla) con BM25 + embeddinggemma-300m
fusionados por RRF; el LLM solo elige tramos y escribe una frase en estilo indirecto con sus palabras; el código
comprueba que cada palabra de contenido de la frase está en el tramo citado (o sus vecinos) y si no, la cambia por la
cita literal. Cada pregunta es independiente: ni historial ni caché de prompt."""
import json, os, re, socket, subprocess, sys, time, urllib.request
from collections import Counter
from pathlib import Path

import numpy as np

import pipeline as P

TOPK, RRF_K, POOL, MAX_SCREEN = 8, 60, 30, 2  # como mucho 2 trozos de pantalla en el top: si no, tapan la voz
MIN_COS = float(os.environ.get("ACTAS_RAG_MIN_COS", 0.35))  # bajo esto: "No se menciona" sin LLM (calibrado en eval/)
MAX_LINES = 2  # con 3 líneas el LLM rellena con paráfrasis que la verificación descarta (medido: +10 pts de descartes)
CTX_WORDS = 20  # palabras de contexto de cada vecino ±1 que se enseñan al LLM junto a cada fragmento
NOT_SAID = "No se menciona en la reunión."
GEMMA = "gemma-4-E4B-it-Q4_0.gguf"


def chat_model():
    """Modelo del chat: gemma-4-E4B (estilo interpretativo) si está; ACTAS_CHAT=qwen vuelve al 4B de las actas (estilo literal)."""
    g = P.ROOT / "models" / GEMMA
    return g if os.environ.get("ACTAS_CHAT", "gemma") != "qwen" and g.exists() else P.llm_model()


def interp():
    return chat_model().name == GEMMA

STOP = set("""a al algo algun alguna alguno algunos algunas ante antes aqui asi aun bajo bien cada como con contra cual
cuales cuando de del desde donde dos el ella ellas ello ellos en entre era eran es esa esas ese eso esos esta estas este
esto estos fue fueron ha han hasta hay la las le les lo los mas me mi mis mucho muchos muy nada ni nos nosotros o os otra
otras otro otros para pero poco por porque pues que quien quienes se sea segun ser si sido sin sobre solo su sus tal
tambien tan tanto te ti todo todos toda todas tu tus un una uno unos unas usted ustedes y ya yo el eh bueno entonces
digamos fijense aca alli ahi decir dice dijo dicen dijeron dicho menciona menciono mencionan comenta comento explica
explico indica indico senala senalo afirma afirmo habla hablo cuenta conto comentaron explicaron senalaron mencionaron
pantalla mostro muestra muestran mostraron puede pueden podemos puedo podria poder tiene tienen tengo tenemos tener
hace hacen hacer hago hecho va van vamos voy ir esta estan estoy estamos estar estaba son soy somos eres hubo habia
haber he hemos sera seran estara estaran habra""".split())
NUM = dict(zip("""cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince dieciseis
diecisiete dieciocho diecinueve veinte""".split(), map(str, range(21))))
NUM.update(treinta="30", cuarenta="40", cincuenta="50", sesenta="60", setenta="70", ochenta="80", noventa="90",
           cien="100", ciento="100", mil="1000")
NEG = {"no", "ni", "nunca", "sin", "ningun", "ninguna", "ninguno"}
SUF = sorted("""arian erian irian aria eria iria rian ria ian aban aran eran ara era ira an en ia amientos imientos amiento imiento aciones uciones acion ucion mente ables ibles able ible ando iendo
ados idos adas idas ado ido ada ida ar er ir es os as a o e s""".split(), key=len, reverse=True)


def stem(w):
    """Raíz pobre en español (pliegue de tildes ya hecho por P.words): número en letra -> cifra, sin sufijos comunes."""
    w = NUM.get(w, w)
    if w.isdigit():
        return w
    for s in SUF:
        if w.endswith(s) and len(w) - len(s) >= 3:
            return w[:-len(s)]
    return w


# Valoraciones que casi nunca se dicen tal cual: se busca también el dato del que saldrían («¿es caro?» -> el precio).
# El LLM no ve esta expansión, solo la recuperación.
EXPAND = {("caro", "cara", "barato", "barata", "costoso", "economico", "precio", "cuesta", "vale"): "precio cuesta vale dólares pagar plan",
          ("antiguo", "antigua", "viejo", "vieja", "nuevo", "nueva", "moderno", "reciente"): "año fecha creado",
          ("largo", "larga", "corto", "corta", "dura", "duracion"): "duración horas minutos tiempo",
          ("grande", "pequeno", "pequena", "enorme"): "tamaño número cantidad"}


def expand(q):
    w = set(P.words(q))
    return " ".join([q, *(v for k, v in EXPAND.items() if w & set(k))])


SCREEN_Q = re.compile(r"pantalla|bot[oó]n|men[uú]|ventana|icono|diapositiva|\bse ven?\b|captura", re.I)


# Preguntas de definición: el contexto ±1 solo ayuda ahí (la definición suele continuar en el tramo vecino); en el resto
# alargaba el prompt (+10 s) y el LLM parafraseaba más (paráfrasis 93% -> 71% medido).
DEF_Q = re.compile(r"\bqu[eé] (es|son|significa|signific[oa]n)\b|\ben qu[eé] consiste|\bpara qu[eé] (sirve|sirven|se usa|se usan|se utiliza)", re.I)


# Preguntas generales («¿de qué va la reunión?») -> se responden con el acta breve; de propósito («¿para qué sirve X?») ->
# deducción marcada a partir de las funciones que se mostraron o dijeron.
GEN_Q = re.compile(r"\bde qu[eé] (va|trata|tratan|se habl[oó]|hablan?)\b.*\b(reuni[oó]n|sesi[oó]n|charla|webinar|v[ií]deo|llamada|encuentro)\b|"
                   r"\b(resum[ei]|resumen)\b.*\b(reuni[oó]n|sesi[oó]n|charla|webinar|v[ií]deo)\b|\bde qu[eé] (va|trata) (esto|todo)\b", re.I)
PURP_Q = re.compile(r"\bpara qu[eé] (sirve|sirven|se usa|se utiliza|es)\b|\bde qu[eé] (va|trata) (el|la|este|esta|ese|esa)\b|\bqu[eé] (hace|permite) (el|la|este|esta)\b", re.I)
needs_ctx = lambda q: bool(DEF_Q.search(q) or (interp() and PURP_Q.search(q)))


def terms(text):
    ws = P.words(text)
    # además, pares pegados: el ASR dice «click meeting» y la pregunta (o la pantalla) «clickmeeting»
    return [stem(w) for w in ws if w not in STOP or w in NUM] + \
           [a + b for a, b in zip(ws, ws[1:]) if a not in STOP and b not in STOP and len(a) > 2 and len(b) > 2]


# ---------- índice ----------
def units(wd, quality="rápido"):
    """Tramos de voz de ~15 s (marcas del ASR) y, aparte, el texto de cada pantalla compartida en trozos de 60 palabras."""
    tr = json.loads((Path(wd) / f"transcript_{quality}.json").read_text())
    segs = [{"s": x["s"], "e": x["e"], "text": x["text"].strip(), "kind": "voz", "spk": x.get("spk")} for x in P.merge_segs(tr["segments"])]
    kf = Path(wd) / "frames.json"
    for k in P.screens(json.loads(kf.read_text())) if kf.exists() else []:
        # sin URLs ni tokens kilométricos (barra de direcciones): solo meten ruido en BM25 y en el embedding
        w = [x for x in k["text"].replace(" | ", " · ").split() if len(x) < 25 and "/" not in x and "=" not in x] \
            if k["screen"] else []
        segs += [{"s": k["t"], "e": k["t"], "text": " ".join(w[i:i + 60]), "kind": "pantalla"} for i in range(0, len(w), 60)]
    return segs


_enc = None
REPO, ONNX = "onnx-community/embeddinggemma-300m-ONNX", "onnx/model_quantized.onnx"
QP, DP = "task: search result | query: ", "title: none | text: "  # prompts oficiales de EmbeddingGemma


def embed(texts, query=False, threads=2):
    global _enc
    if _enc is None:
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer
        d = P.ROOT / "models" / "gemma-emb"
        get = lambda f: str(d / f) if (d / f).is_file() else hf_hub_download(REPO, f, local_dir=d)  # local (models.py) o Hugging Face
        tok = Tokenizer.from_file(get("tokenizer.json"))
        tok.enable_truncation(512)
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        _enc = tok, ort.InferenceSession(get(ONNX), so, providers=["CPUExecutionProvider"])
    tok, sess = _enc
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    out = np.zeros((len(texts), 768), np.float32)
    for b in range(0, len(order), 16):  # lotes de longitud parecida: poco relleno
        ids = order[b:b + 16]
        tok.enable_padding()
        enc = tok.encode_batch([(QP if query else DP) + texts[i] for i in ids])
        feed = {"input_ids": np.array([e.ids for e in enc], np.int64), "attention_mask": np.array([e.attention_mask for e in enc], np.int64)}
        v = sess.run(["sentence_embedding"], feed)[0]  # ya agrupado y proyectado por el propio modelo
        out[ids] = v / np.linalg.norm(v, axis=1, keepdims=True)
    return out


class Index:
    def __init__(self, wd, quality="rápido", threads=2):
        self.segs = units(wd, quality)
        texts = [s["text"] for s in self.segs]
        import hashlib
        h = hashlib.sha1("\0".join([ONNX, *texts]).encode()).hexdigest()[:8]
        f = Path(wd) / f"rag_{quality}_{h}.npy"
        self.emb = np.load(f) if f.exists() else embed(texts, False, threads)
        if not f.exists():
            np.save(f, self.emb)
        self.threads = threads
        self.docs = [Counter(terms(t)) for t in texts]
        self.df = Counter(w for d in self.docs for w in d)
        self.len = np.array([sum(d.values()) for d in self.docs], float)
        self.voz = [i for i, s in enumerate(self.segs) if s["kind"] == "voz"]
        self.wd = Path(wd)

    def acta(self):
        """(resumen, [(t, texto)...]) del acta breve (o la más corta que haya) de esta reunión; (None, []) si no hay."""
        fs = sorted(self.wd.glob("acta_*/acta.json"), key=lambda f: ("breve" not in f.parent.name, "alta" in f.parent.name, f.parent.name))
        try:
            a = json.loads(fs[0].read_text())
        except (IndexError, ValueError):
            return None, []
        rel = [(r["t"], r["texto"]) for r in a.get("relato", [])] or [(x.get("t", 0), x.get("titulo", "")) for x in a.get("secciones", [])]
        return a.get("resumen"), rel

    def seg_at(self, t):
        """Índice del tramo de voz que contiene el segundo t."""
        return next((i for i in reversed(self.voz) if self.segs[i]["s"] <= t + 1), self.voz[0])

    def bm25(self, q, k1=1.5, b=0.75):
        n, sc = len(self.docs), np.zeros(len(self.docs))
        norm = k1 * (1 - b + b * self.len / max(1, self.len.mean()))
        for w in set(terms(q)):
            if self.df[w]:
                idf = np.log(1 + (n - self.df[w] + 0.5) / (self.df[w] + 0.5))
                tf = np.array([d[w] for d in self.docs], float)
                sc += idf * tf * (k1 + 1) / (tf + norm)
        return sc

    def search(self, q, k=TOPK):
        """-> (índices de los k mejores por RRF, coseno denso máximo)."""
        q0, q = q, expand(q)
        dense = self.emb @ embed([q], True, self.threads)[0]
        rrf = Counter()
        for sc in (dense, self.bm25(q)):
            for r, i in enumerate(np.argsort(-sc)[:POOL]):
                if sc[i] > 0:
                    rrf[int(i)] += 1 / (RRF_K + r + 1)
        ranked = [i for i, _ in rrf.most_common()]
        scr = [i for i in ranked if self.segs[i]["kind"] == "pantalla"][:MAX_SCREEN]
        # el texto de pantalla (OCR) es secundario: solo si se pregunta por lo que se ve o si ninguna voz se parece
        if SCREEN_Q.search(q0) or not self.voz or dense[self.voz].max() < MIN_COS:
            out = [i for i in ranked if self.segs[i]["kind"] == "voz" or i in scr]
        else:
            out = [i for i in ranked if self.segs[i]["kind"] == "voz"]
        return out[:k], float(dense.max())

    def cita(self, i, q):
        """Texto literal que se enseña si la frase no se verifica: el tramo de voz entero; de una pantalla, solo el
        pasaje (~25 palabras) donde está lo preguntado, no el volcado de OCR."""
        t = self.segs[i]["text"]
        if self.segs[i]["kind"] == "voz":
            return t
        w, qs = t.split(), {stem(x) for x in P.words(q) if x not in STOP}
        c = next((k for k, x in enumerate(w) if qs & {stem(y) for y in P.words(x)}), 0)
        return ("… " if c > 8 else "") + " ".join(w[max(0, c - 8):c + 17]) + (" …" if c + 17 < len(w) else "")

    def window(self, i):
        """El tramo y sus vecinos ±1 de voz (contexto al desplegar y margen de la verificación)."""
        if self.segs[i]["kind"] != "voz":
            return [i]
        j = self.voz.index(i)
        return self.voz[max(0, j - 1):j + 2]


# ---------- verificación ----------
def verify(frase, allowed_text):
    """-> palabras de contenido de la frase que NO están en el texto permitido (vacío = verificada). Compara raíces sin
    tildes; las cifras (también las dichas en letra) tienen que coincidir exactas."""
    ok = set(terms(allowed_text))
    body = re.sub(r"^\s*(se dijo que|en pantalla se mostr[oó] que)\s*", "", frase, flags=re.I)
    keep = lambda w: w in NUM or w.isdigit() or w == "no" or (len(w) > 2 and w not in STOP)  # "da", "un"… no cuentan
    fw, src = P.words(body), P.words(allowed_text)
    bad = [w for w in dict.fromkeys(fw) if keep(w) and stem(w) not in ok]
    # cifra que en el original siempre va negada («ya no vale 25 sino 30») y en la frase no: dato invertido.
    # ponytail: solo cifras y negación a <= 3 palabras; un análisis sintáctico cubriría el resto
    neg = lambda ws, k: any(x in NEG for x in ws[max(0, k - 3):k])
    for k, w in enumerate(fw):
        occ = [j for j, x in enumerate(src) if stem(x) == stem(w)] if stem(w).isdigit() else []
        if occ and all(neg(src, j) for j in occ) and not neg(fw, k):
            bad.append("no " + w)
    return bad


# ---------- LLM ----------
SYSTEM = """Respondes preguntas sobre una reunión usando SOLO los fragmentos numerados de su transcripción.
Por cada fragmento que responda directamente a la pregunta, escribe una línea:
[n] Se dijo que <frase>.
<frase>: lo que dice ese fragmento sobre lo preguntado, en estilo indirecto y copiando sus palabras, lo más literal \
posible. Prohibido: sinónimos, palabras de la pregunta que no estén en el fragmento, añadir o corregir datos, \
conclusiones, opiniones o valoraciones tuyas. Si se pregunta \
por una valoración (caro, bueno, antiguo…) o un dato que no se dijo, escribe solo lo que sí se dijo.
Ejemplo: fragmento «la torre fue creada en 1843», pregunta «¿es antigua la torre?» -> [n] Se dijo que la torre fue \
creada en 1843.
Cada fragmento, una sola vez; solo los que responden, máximo 2 líneas. Si alguno responde aunque sea en parte, úsalo; solo si ninguno trata lo preguntado, escribe solo: \
NINGUNO"""


def grammar(n):
    ids = " | ".join(f'"{i}"' for i in range(1, n + 1))
    return (f'root ::= "NINGUNO" | line{{1,{MAX_LINES}}}\nline ::= "[" id "] Se dijo que " txt "\\n"\n'
            f'id ::= {ids}\ntxt ::= [^\\n\\[\\]]{{3,220}}')


def prompt(idx, ids, q):
    def ctx(i):  # final del tramo anterior y principio del siguiente (solo voz)
        w = idx.window(i)
        if len(w) == 1 or not needs_ctx(q):
            return ""
        a = [j for j in w if j < i]
        b = [j for j in w if j > i]
        return " ‖ " + " ".join(([" ".join(idx.segs[a[0]]["text"].split()[-CTX_WORDS:])] if a else [])
                               + ([" ".join(idx.segs[b[0]]["text"].split()[:CTX_WORDS])] if b else []))
    rows = [f"[{n}] ({P.fmt(idx.segs[i]['s'])}{', texto en pantalla' if idx.segs[i]['kind'] == 'pantalla' else ''}) "
            f"{idx.segs[i]['text']}{ctx(i)}" for n, i in enumerate(ids, 1)]
    nota = " (tras «‖», contexto: final del fragmento anterior y principio del siguiente)" if needs_ctx(q) else ""
    return f"Fragmentos{nota}:\n" + "\n".join(rows) + f"\n\nPregunta: {q}"


def server(threads, ctx=None):
    """llama-server propio (puerto libre) o el de ACTAS_LLM_URL. -> (url, proceso o None).
    ponytail: copia de los argumentos de P.llama; unificar si P.llama devolviera también la url."""
    if os.environ.get("ACTAS_LLM_URL"):
        return os.environ["ACTAS_LLM_URL"], None
    exe = P.llama_exe()
    if not exe or not chat_model():
        raise RuntimeError("Falta bin/**/llama-server o models/*.gguf (ver README)")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    P.WORK.mkdir(exist_ok=True)
    proc = subprocess.Popen([str(exe), "-m", str(chat_model()), "-c", str(ctx or (6144 if interp() else 4096)), "-t", str(threads), "-np", "1", *P.GPU,
                             "-cram", "0", "-ctxcp", "0", "-rea", "off", "-lm", "none", "--host", "127.0.0.1",
                             "--port", str(port)], stdout=open(P.WORK / "llama-server-rag.log", "w"),
                            stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    for _ in range(600):
        if proc.poll() is not None:
            raise RuntimeError("llama-server terminó (ver work/llama-server-rag.log)")
        try:
            if urllib.request.urlopen(url + "/health", timeout=2).status == 200:
                return url, proc
        except OSError:
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("llama-server no arranca")


def stream(url, user, n, system=SYSTEM, gram=None, max_tokens=80 * MAX_LINES):
    """Genera los trozos de texto del LLM; el último elemento es el dict de tiempos de llama-server."""
    body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0, "max_tokens": max_tokens, "grammar": gram or grammar(n), "stream": True,
            "cache_prompt": False, "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(url + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    timings = {}
    with urllib.request.urlopen(req, timeout=600) as r:
        for raw in r:
            line = raw.decode().strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            d = json.loads(line[6:])
            timings = d.get("timings", timings)
            for c in d.get("choices", []):
                if c.get("delta", {}).get("content"):
                    yield c["delta"]["content"]
    yield timings


def answer(idx, q, url):
    """Eventos: ("candidatos", [i...]) al instante; luego ("frase", dict) por cada línea del LLM o ("nada", motivo);
    al final ("fin", tiempos). Una pregunta = una llamada sin historial."""
    if interp():
        yield from answer_i(idx, q, url)
        return
    t0 = time.time()
    ids, cos = idx.search(q)
    st = {"recuperacion": round(time.time() - t0, 3), "cos": round(cos, 3)}
    yield "candidatos", ids
    if cos < MIN_COS:
        yield "nada", "umbral"
        yield "fin", {**st, "total": round(time.time() - t0, 2)}
        return
    order = sorted(ids, key=lambda i: (idx.segs[i]["kind"] != "voz", idx.segs[i]["s"]))  # cronológico: más legible
    buf, n_out, t1, first, seen = "", 0, time.time(), None, set()
    for ch in stream(url, prompt(idx, order, q), len(order)):
        if isinstance(ch, dict):
            st.update(prefill=round(ch.get("prompt_ms", 0) / 1000, 2), gen=round(ch.get("predicted_ms", 0) / 1000, 2),
                      prompt_tok=ch.get("prompt_n"), gen_tok=ch.get("predicted_n"))
            break
        first = first or round(time.time() - t1, 2)
        buf += ch
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            m = re.match(r"\[(\d+)\] (.+)", line.strip())
            if m and order[int(m[1]) - 1] not in seen:
                i, frase = order[int(m[1]) - 1], m[2].strip()
                win = lambda i: " ".join(idx.segs[j]["text"] for j in idx.window(i))
                miss = verify(frase, win(i))
                if miss:  # a veces el LLM copia bien la frase pero se equivoca de número: si sale entera de otro, es de ese
                    i = next((j for j in order if j not in seen and not verify(frase, win(j))), i)
                    miss = verify(frase, win(i))
                if idx.segs[i]["kind"] == "pantalla" and miss and not SCREEN_Q.search(q):
                    continue  # un volcado de OCR nunca es la cita de una pregunta que no es sobre lo que se ve
                seen.add(i)
                if idx.segs[i]["kind"] == "pantalla":
                    frase = re.sub(r"^Se dijo que", "En pantalla se mostró que", frase)
                n_out += 1
                yield "frase", {"i": i, "frase": frase, "ok": not miss, "faltan": miss, "cita": idx.cita(i, q)}
    if not n_out:
        yield "nada", "llm"
    yield "fin", {**st, "primer_token": first, "total": round(time.time() - t0, 2)}


# ---------- estilo interpretativo (gemma-4-E4B): síntesis citada + deducción marcada ----------
SYSTEM_I = """Respondes preguntas sobre una reunión usando SOLO los fragmentos numerados de su transcripción.
Cada línea empieza por el número del fragmento que la apoya, o de dos si juntas ideas de ambos: [n] o [n][m].
Dos tipos de línea, los hechos primero:
[n] Se dijo que <lo que dicen los fragmentos sobre lo preguntado, con tus palabras, resumiendo o conectando varios \
si hace falta; solo datos, nombres y cifras que aparezcan en ellos>.
[n] Se deduce que <conclusión razonable; es una deducción, no un hecho dicho>, porque se dijo que <lo que dicen esos \
fragmentos en que se apoya, con sus palabras>.
Reglas: máximo 3 líneas «Se dijo» y 1 «Se deduce». La deducción solo si ayuda a responder (p. ej. el propósito de \
una herramienta a partir de las funciones que se muestran); cada deducción cita el fragmento en que se apoya y no inventa \
cifras ni hechos. Si la pregunta supone algo que los fragmentos no dicen, no lo des por cierto. \
Si ningún fragmento trata lo preguntado, escribe solo: NINGUNO"""
SYSTEM_G = """Resumes una reunión a partir de su resumen y de los momentos numerados de su acta.
Escribe 3 líneas, cada una con su idea y el número del momento que la apoya: [n] <idea>. Solo lo que dice el acta, \
sin inventar nombres, cifras ni conclusiones."""


def grammar_i(n, general=False):
    refs = 'refs ::= "[" id "]" ("[" id "]")?\nid ::= ' + " | ".join(f'"{i}"' for i in range(1, n + 1))
    txt = 'txt ::= [^\\n\\[\\]]{3,260}'
    if general:
        return f'root ::= g{{2,3}}\ng ::= refs " " txt "\\n"\n{refs}\n{txt}'
    return (f'root ::= "NINGUNO" | d{{1,3}} e{{0,1}}\nd ::= refs " Se dijo que " txt "\\n"\n'
            f'e ::= refs " " ("Se deduce que" | "Probablemente") " " txt ", porque se dijo que " txt "\\n"\n{refs}\n{txt}')


LINE_I = re.compile(r"^((?:\[\d+\])+) (Se dijo que|Se deduce que|Probablemente)? ?(.+)")


def answer_i(idx, q, url):
    """Como answer() pero interpretativo. Eventos "frase" con kind dijo|deduce|resumen y refs (todos los tramos citados).
    «Se dijo» se verifica como siempre (contra la unión de los tramos citados); «Se deduce» y el resumen solo exigen
    que sus cifras estén en lo citado (o en el acta)."""
    t0 = time.time()
    resumen, rel = idx.acta() if GEN_Q.search(q) else (None, [])
    general = bool(rel)
    ids, cos = idx.search(q)
    st = {"recuperacion": round(time.time() - t0, 3), "cos": round(cos, 3)}
    allowed = None
    if general:  # momentos del acta (como mucho 24, repartidos) -> tramo de voz donde ocurren
        rel = rel if len(rel) <= 24 else [rel[round(k * (len(rel) - 1) / 23)] for k in range(24)]
        order = [idx.seg_at(t) for t, _ in rel]
        user = (f"Resumen del acta: {resumen}\n\nMomentos:\n" + "\n".join(f"[{n}] ({P.fmt(t)}) {x}" for n, (t, x) in enumerate(rel, 1))
                + f"\n\nPregunta: {q}")
        allowed = " ".join([resumen or ""] + [x for _, x in rel])
        args = dict(system=SYSTEM_G, gram=grammar_i(len(rel), True), max_tokens=330)
        yield "candidatos", order
    else:
        yield "candidatos", ids
        if cos < MIN_COS:
            yield "nada", "umbral"
            yield "fin", {**st, "total": round(time.time() - t0, 2)}
            return
        order = sorted(ids, key=lambda i: (idx.segs[i]["kind"] != "voz", idx.segs[i]["s"]))
        user, args = prompt(idx, order, q), dict(system=SYSTEM_I, gram=grammar_i(len(order)), max_tokens=420)
    buf, n_out, t1, first, seen, dijo = "", 0, time.time(), None, set(), set()
    ded_n = ded_ok = 0  # dijo: tramos citados por las líneas «Se dijo»
    text_of = lambda js: " ".join(idx.segs[k]["text"] for j in js for k in idx.window(j))
    for ch in stream(url, user, len(order), **args):
        if isinstance(ch, dict):
            st.update(prefill=round(ch.get("prompt_ms", 0) / 1000, 2), gen=round(ch.get("predicted_ms", 0) / 1000, 2),
                      prompt_tok=ch.get("prompt_n"), gen_tok=ch.get("predicted_n"))
            break
        first = first or round(time.time() - t1, 2)
        buf += ch
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            m = LINE_I.match(line.strip())
            if not m:
                continue
            refs = list(dict.fromkeys(order[int(x) - 1] for x in re.findall(r"\d+", m[1]) if 0 < int(x) <= len(order)))
            if not refs:
                continue
            kind = "resumen" if general else "dijo" if m[2] == "Se dijo que" else "deduce"
            frase = (m[2] + " " if m[2] else "") + re.sub(r"</?[a-zA-Z][^>]*>", "", m[3]).strip()  # sin restos de HTML
            if kind == "dijo":
                if refs[0] in seen:
                    continue
                miss = verify(frase, text_of(refs))
                if miss and len(refs) == 1:  # el LLM a veces se equivoca de tramo: si sale entera de otro, es de ese
                    j = next((j for j in order if j not in seen and not verify(frase, text_of([j]))), None)
                    if j is not None:
                        refs, miss = [j], []
                if idx.segs[refs[0]]["kind"] == "pantalla" and miss and not SCREEN_Q.search(q):
                    continue
                if idx.segs[refs[0]]["kind"] == "pantalla":
                    frase = re.sub(r"^Se dijo que", "En pantalla se mostró que", frase)
                seen.add(refs[0])
                dijo.update(refs)
            else:  # deducción / resumen: sin cifras inventadas
                if kind == "deduce":
                    frase = re.split(r"\.\s", frase + " ", 1)[0].rstrip(".") + "."  # una sola oración: el LLM a veces sigue con otra
                    if not set(refs) <= dijo:
                        continue  # una deducción solo puede citar lo que ya sostiene los hechos de esta respuesta
                    ded_n += 1
                    base = frase.split(", porque se dijo que ", 1)[-1]
                    if verify(base, text_of(refs)):
                        continue  # «porque se dijo que…» es una afirmación de hecho: misma verificación que «Se dijo»
                    ded_ok += 1
                miss = [w for w in verify(frase, allowed or text_of(refs)) if w.isdigit() or w.startswith("no ")]
                if miss:
                    continue
            n_out += 1
            yield "frase", {"i": refs[0], "refs": refs, "kind": kind, "frase": frase, "ok": not miss, "faltan": miss,
                            "cita": idx.cita(refs[0], q)}
    if not n_out:
        yield "nada", "llm"
    yield "fin", {**st, "primer_token": first, "total": round(time.time() - t0, 2), "ded_n": ded_n, "ded_base_ok": ded_ok}


def resolve(arg):
    """Carpeta work/<hash> a partir del vídeo, del hash o de la ruta."""
    p = Path(arg)
    if p.is_dir():
        return p
    return P.WORK / (arg if (P.WORK / arg).is_dir() else P.video_id(p))


def _selftest():
    seg = "la torre fue creada en 1843 y la pintaron de un color femenino, el plan vale veinticinco dólares al mes"
    assert verify("Se dijo que la torre fue creada en 1843.", seg) == []
    assert verify("Se dijo que la torre es antigua.", seg) == ["antigua"]
    assert verify("Se dijo que la pintaron de color rosa.", seg) == ["rosa"]
    assert verify("Se dijo que la pintaron de un color femenino.", seg) == []
    assert verify("Se dijo que la torre fue creada en 1834.", seg) == ["1834"]
    assert verify("Se dijo que el plan vale 25 dólares al mes.", "el plan vale 25 dolares al mes") == []
    assert verify("Se dijo que el plan vale 26 dólares.", "el plan vale 25 dolares") == ["26"]
    assert verify("Se dijo que cuesta cinco dólares.", "cuesta 5 dólares") == []  # cifra en letra = en dígitos
    assert verify("Se dijo que es caro.", seg) == ["caro"]
    assert verify("Se dijo que no se puede grabar.", "se puede grabar") == ["no"]  # negación inventada
    assert verify("Se dijo que nos da 15 minutos.", "nos dan solo 15 minutos") == []
    mes = "si pago mensual este plan ya no vale 25 sino vale 30 dólares"
    assert verify("Se dijo que el plan mensual vale 25 dólares.", mes) == ["no 25"]  # recombinación con negación perdida
    assert verify("Se dijo que si paga mensual el plan ya no vale 25 sino 30 dólares.", mes) == []
    assert verify("Se dijo que se convocan a la próxima reunión.", "se convoca a la próxima reunión") == []  # conjugación
    assert verify("Se dijo que se reanudaría el martes.", "se reanudará el martes") == []
    assert verify("Se dijo que el plan vale 25 dólares.", "el plan valía 30 dólares") == ["25"]
    g = grammar(3)
    assert '"1" | "2" | "3"' in g and "NINGUNO" in g
    print("selftest ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        _selftest()
        sys.exit()
    if len(sys.argv) != 3:
        sys.exit('uso: rag.py <vídeo|hash> "pregunta"   ·   rag.py --selftest')
    idx = Index(resolve(sys.argv[1]), threads=int(os.environ.get("ACTAS_THREADS", P.PHYS)))
    url, proc = server(int(os.environ.get("ACTAS_THREADS", P.PHYS)))
    try:
        for kind, v in answer(idx, sys.argv[2], url):
            if kind == "candidatos":
                for i in v:
                    print(f"  cand [{P.fmt(idx.segs[i]['s'])}] {idx.segs[i]['text'][:110]}")
            elif kind == "frase":
                s = idx.segs[v["i"]]
                print(f"[{', '.join(P.fmt(idx.segs[j]['s']) for j in v.get('refs', [v['i']]))}] {v['frase'] if v['ok'] else 'Se dijo: «' + v['cita'] + '»'}"
                      + ("" if v["ok"] else f"  (frase descartada: {v['faltan']})"))
            elif kind == "nada":
                print(NOT_SAID, f"({v})")
            else:
                print(v)
    finally:
        if proc:
            proc.terminate()
