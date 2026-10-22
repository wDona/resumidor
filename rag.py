"""Preguntas sobre UNA reunión ya procesada. Recupera tramos de 15 s (y textos de pantalla) con BM25 + embeddinggemma-300m
fusionados por RRF; el LLM solo elige tramos y escribe una frase en estilo indirecto con sus palabras; el código
comprueba que cada palabra de contenido de la frase está en el tramo citado (o sus vecinos) y si no, la cambia por la
cita literal. Cada pregunta es independiente: ni historial ni caché de prompt."""
import json, os, re, socket, subprocess, sys, time, urllib.request
from collections import Counter
from pathlib import Path

import numpy as np

import pipeline as P

MMR_T, MMR_W = 0.75, 6.0  # MMR: penaliza a un tramo por lo que se parece (coseno > MMR_T) a los ya elegidos (votaciones repetidas…)
WHY = re.compile(r"\bpor qu[eé]\b|\bmotivo|\braz[oó]n\b|\bcausa\b", re.I)
REASON = {"porque", "motivo", "motivos", "motivacion", "motivaciones", "razon", "razones", "debido", "causa", "causas", "dado"}
TOPK, RRF_K, POOL, MAX_SCREEN = 8, 60, 30, 2  # como mucho 2 trozos de pantalla en el top: si no, tapan la voz
MIN_COS = float(os.environ.get("ACTAS_RAG_MIN_COS", 0.35))  # bajo esto: "No se menciona" sin LLM (calibrado en eval/)
CAP_WORDS = 1300  # carpeta: palabras de fragmentos como mucho en el prompt
MAX_LINES = 2  # con 3 líneas el LLM rellena con paráfrasis que la verificación descarta (medido: +10 pts de descartes)
CTX_WORDS = 20  # palabras de contexto de cada vecino ±1 que se enseñan al LLM junto a cada fragmento
NOT_SAID = "No se menciona en la reunión."
GEMMA = "gemma-4-E4B-it-Q4_0.gguf"


_gpu_chat = [None]  # casilla "Usar GPU" de la última pregunta (la fija server)


def chat_choice(gpu=None):
    """-> (usa gemma, motivo corto): la regla de P.chat_model, pero con Qwen si el gguf de gemma no está descargado."""
    m, why = P.chat_model(gpu)
    if m == "gemma" and not (P.ROOT / "models" / GEMMA).exists():
        return False, "Gemma no descargado: usando Qwen"
    return m == "gemma", why


def chat_model():
    """Modelo del chat según la memoria (chat_choice): gemma-4-E4B o el 4B de las actas."""
    return P.ROOT / "models" / GEMMA if chat_choice(_gpu_chat[0])[0] else P.llm_model()


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
        self.lang = json.loads((self.wd / f"transcript_{quality}.json").read_text()).get("language") or "es"

    def acta(self):
        """(resumen, [(t, texto)...]) del acta breve (o la más corta que haya) de esta reunión; (None, []) si no hay."""
        fs = sorted(self.wd.glob("acta_*/acta.json"), key=lambda f: ("_p-" in f.parent.name or "_i-" in f.parent.name, "breve" not in f.parent.name, "alta" in f.parent.name, f.parent.name))
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

    multi, topk = False, TOPK

    def search(self, q, k=None):
        """-> (índices de los k mejores por RRF, coseno denso máximo)."""
        q0, q, k = q, expand(q), k or self.topk
        dense = self.emb @ embed([q], True, self.threads)[0]
        rrf = Counter()
        for sc in (dense, self.bm25(q)):
            for r, i in enumerate(np.argsort(-sc)[:POOL]):
                if sc[i] > 0:
                    rrf[int(i)] += 1 / (RRF_K + r + 1)
        if WHY.search(q0):  # «¿por qué…?»: tercera lista con los tramos que dan una razón (porque, motivo…), por parecido denso
            for r, i in enumerate([i for i in np.argsort(-dense)[:4 * POOL] if REASON & set(P.words(self.segs[i]["text"]))][:POOL]):
                rrf[int(i)] += 2 / (RRF_K + r + 1)  # doble peso: es lo que pide la pregunta
        top = rrf.most_common()
        rel = {i: sc / top[0][1] for i, sc in top}
        voz, pick = [i for i, _ in top if self.segs[i]["kind"] == "voz"], []
        while voz:  # MMR sobre las voces: relevancia (RRF normalizado) menos penalización por parecido a lo ya elegido
            best = max(voz, key=lambda i: rel[i] - MMR_W * max(0.0, max((self.emb[i] @ self.emb[j] for j in pick), default=0.0) - MMR_T))
            pick.append(best)
            voz.remove(best)
        it = iter(pick)  # las voces ocupan sus huecos del RRF en el orden MMR; la pantalla se queda donde estaba
        ranked = [next(it) if self.segs[i]["kind"] == "voz" else i for i, _ in top]
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


class Multi(Index):
    """Varias reuniones (una carpeta) como un solo índice: mismo search/MMR sobre todos los tramos; cada tramo lleva su reunión (m)."""
    multi, topk = True, 12

    def __init__(self, parts):  # parts: [(nombre, url del vídeo, Index)]
        ix = [p[2] for p in parts]
        self.names, self.vids = [p[0] for p in parts], [p[1] for p in parts]
        self.segs = [dict(s, m=m) for m, x in enumerate(ix) for s in x.segs]
        self.emb, self.threads = np.vstack([x.emb for x in ix]), ix[0].threads
        self.docs = [d for x in ix for d in x.docs]
        self.df = Counter(w for d in self.docs for w in d)
        self.len = np.concatenate([x.len for x in ix])
        self.voz = [i for i, s in enumerate(self.segs) if s["kind"] == "voz"]
        self.lang = next((x.lang for x in ix if not x.lang.startswith("es")), "es")  # ponytail: una reunión en otro idioma obliga a citar literal en todas

    def acta(self):
        return None, []

    def window(self, i):  # los vecinos no cruzan de reunión
        return [j for j in super().window(i) if self.segs[j]["m"] == self.segs[i]["m"]]

    def search(self, q, k=None):
        ids, cos = super().search(q, k)
        out, w = [], 0
        for i in ids:  # tope de palabras: el contexto del LLM es fijo
            w += len(self.segs[i]["text"].split())
            if out and w > CAP_WORDS:
                break
            out.append(i)
        return out, cos


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


def _nv(m):
    """Lecturas posibles de una cifra: 34,75 = 34.75; 1.000 / 1,000 = 1000."""
    r = {m.replace(",", ".")}
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", m):
        r.add(re.sub(r"[.,]", "", m))
    return r


NUMRE = r"\d+(?:[.,]\d+)*"


def bad_nums(frase, text):
    """Cifras de la frase que NO aparecen enteras en el texto citado (34,75 != 75). También cuenta las dichas en letra."""
    have = set().union(*(_nv(m) for m in re.findall(NUMRE, text)), {NUM[w] for w in P.words(text) if w in NUM})
    return [m for m in re.findall(NUMRE, frase) if not _nv(m) & have]


QUOTE = re.compile(r"«([^»]+)»")


def quote_ok(q, text):
    """La cita (con «…» para saltos) es subcadena literal del texto, sin mayúsculas, tildes ni puntuación; >= 3 palabras."""
    fold = lambda t: " " + " ".join(P.words(t)) + " "
    parts = [fold(x) for x in re.split(r"…|\.\.\.", q) if P.words(x)]
    return sum(len(p.split()) for p in parts) >= 3 and all(p in fold(text) for p in parts)


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
    rows = [f"[{n}] ({idx.names[idx.segs[i]['m']] + ', ' if idx.multi else ''}{P.fmt(idx.segs[i]['s'])}{', texto en pantalla' if idx.segs[i]['kind'] == 'pantalla' else ''}) "
            f"{idx.segs[i]['text']}{ctx(i)}" for n, i in enumerate(ids, 1)]
    nota = " (tras «‖», contexto: final del fragmento anterior y principio del siguiente)" if needs_ctx(q) else ""
    if WHY.search(q):
        nota += " (la pregunta pide una RAZÓN: usa los fragmentos que la den; los que solo dicen el resultado o repiten que ya se explicó, no sirven)"
    return f"Fragmentos{nota}:\n" + "\n".join(rows) + f"\n\nPregunta: {q}"


def server(threads, ctx=None, gpu=None):
    """llama-server propio (puerto libre) o el de ACTAS_LLM_URL. -> (url, proceso o None)."""
    if os.environ.get("ACTAS_LLM_URL"):
        return os.environ["ACTAS_LLM_URL"], None
    P.WORK.mkdir(exist_ok=True)
    _gpu_chat[0] = gpu
    return P.launch(chat_model(), ctx or (6144 if interp() else 4096), threads, ["-cram", "0", "-ctxcp", "0", "-rea", "off", "-lm", "none"],
                    "llama-server-rag.log", gpu)


def stream(url, user, n, system=SYSTEM, gram=None, max_tokens=80 * MAX_LINES):
    """Genera los trozos de texto del LLM; el último elemento es el dict de tiempos de llama-server."""
    body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0, "max_tokens": max_tokens, "grammar": gram or grammar(n), "stream": True,
            "cache_prompt": False, "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(url + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    for retry in (True, False):
        timings, n = {}, 0
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                for raw in r:
                    line = raw.decode().strip()
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    d = json.loads(line[6:])
                    timings = d.get("timings", timings)
                    for c in d.get("choices", []):
                        if c.get("delta", {}).get("content"):
                            n += 1
                            yield c["delta"]["content"]
            break
        except OSError as e:  # servidor muerto o sin memoria de GPU: si aún no salió texto, se reinicia (CPU) y se repite
            if n or not retry or not P.recover(url, e):
                raise
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
    for ch in stream(url, prompt(idx, order, q), len(order), system=SYSTEM + (SYSTEM_M if idx.multi else "")):
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
[n] Se deduce que <conclusión razonable; es una deducción, no un hecho dicho>, porque se dijo que «<cita literal: de 5 a 20 \
palabras copiadas EXACTAS del fragmento, sin cambiar nada>».
Reglas: máximo 3 líneas «Se dijo» y 1 «Se deduce». La deducción solo si ayuda a responder (p. ej. el propósito de \
una herramienta a partir de las funciones que se muestran); cada deducción cita el fragmento en que se apoya y no inventa \
cifras ni hechos. Si la pregunta supone algo que los fragmentos no dicen, no lo des por cierto. \
Si ningún fragmento trata lo preguntado, escribe solo: NINGUNO"""
SYSTEM_EN = """
Los fragmentos están en otro idioma: escribe tú en español, pero tras cada «Se dijo que <frase>» añade la cita literal \
(de 5 a 20 palabras copiadas EXACTAS del fragmento, en su idioma) entre «», así: [n] Se dijo que <frase> «<cita>». La cita de \
«porque se dijo que» también va tal cual, en el idioma del fragmento."""
SYSTEM_M = """
Los fragmentos son de VARIAS reuniones: el nombre de la reunión va delante de la hora. Cada línea cita fragmentos y la \
aplicación muestra de qué reunión es cada uno, así que no escribas nombres de reunión en la frase. No juntes en una misma \
línea fragmentos de reuniones distintas; si dos reuniones dicen cosas distintas, una línea para cada una. Las deducciones \
siguen siendo deducciones, solo con la cita de su propio fragmento."""
SYSTEM_G = """Resumes una reunión a partir de su resumen y de los momentos numerados de su acta.
Escribe 3 líneas, cada una con su idea y el número del momento que la apoya: [n] <idea>. Solo lo que dice el acta, \
sin inventar nombres, cifras ni conclusiones."""


SYSTEM_J = """Eres un revisor estricto de respuestas sobre una reunión. Recibes una pregunta y afirmaciones numeradas, cada una \
con el fragmento en que dice apoyarse. Para cada una responde SI o NO.
DIJO: SI si el fragmento dice eso sin añadir nada y aporta datos sobre el asunto concreto de la pregunta, aunque no la \
conteste del todo; NO si habla de otro asunto o solo comparte alguna palabra con la pregunta.
DEDUCE: SI solo si la cita citada sostiene la conclusión sin que haga falta suponer nada más Y la conclusión responde a lo \
preguntado; NO si la cita solo describe hechos y la conclusión da una opinión, recomendación o valoración que la cita no dice."""


def judge(url, q, items):
    """items: [(tipo, frase, texto citado)] -> [bool]: el mismo gemma revisa en UNA llamada si cada frase está respaldada por su
    cita y responde a la pregunta (SI/NO por gramática). ponytail: un solo voto de un modelo de 4B; no es una prueba formal."""
    user = f"Pregunta: {q}\n\n" + "\n\n".join(
        f"{k}. {t.upper()}: {f}\n   Fragmento: {x[:700]}" for k, (t, f, x) in enumerate(items, 1))
    gram = "root ::= " + " ".join(f'"{k}: " yn "\\n"' for k in range(1, len(items) + 1)) + '\nyn ::= "SI" | "NO"'
    out = "".join(c for c in stream(url, user, 0, system=SYSTEM_J, gram=gram, max_tokens=8 * len(items) + 8) if isinstance(c, str))
    return [bool(re.search(rf"^{k}: SI", out, re.M)) for k in range(1, len(items) + 1)]


def grammar_i(n, general=False, quote=False):
    refs = 'refs ::= "[" id "]" ("[" id "]")?\nid ::= ' + " | ".join(f'"{i}"' for i in range(1, n + 1))
    txt = 'txt ::= [^\\n\\[\\]«»"‖]{3,260}\nq ::= [^\\n\\[\\]«»]{12,160}\ndtxt ::= [^\\n\\[\\]«»"‖.]{3,200}'  # dtxt: una sola oración
    if general:
        return f'root ::= g{{2,3}}\ng ::= refs " " txt "\\n"\n{refs}\n{txt}'
    dq = ' " «" q "»"' if quote else ""
    return (f'root ::= "NINGUNO" | d{{1,3}} e{{0,1}}\nd ::= refs " Se dijo que " txt{dq} "\\n"\n'
            f'e ::= refs " " ("Se deduce que" | "Probablemente") " " dtxt ", porque se dijo que «" q "»\\n"\n{refs}\n{txt}')


LINE_I = re.compile(r"^((?:\[\d+\])+) (Se dijo que|Se deduce que|Probablemente)? ?(.+)")


def answer_i(idx, q, url):
    """Como answer() pero interpretativo. Eventos "frase" con kind dijo|deduce|resumen y refs (todos los tramos citados).
    «Se dijo» se verifica como siempre (contra la unión de los tramos citados); «Se deduce» y el resumen solo exigen
    que sus cifras estén en lo citado (o en el acta)."""
    t0 = time.time()
    resumen, rel = idx.acta() if GEN_Q.search(q) else (None, [])
    general = bool(rel)
    es = idx.lang.startswith("es")  # en otro idioma la frase (en español) no se puede comparar palabra a palabra: se exige la cita literal
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
        if resumen:  # lo primero, el resumen global del propio acta (ya revisado): los momentos sueltos no dicen «de qué va»
            n_out0 = {"i": order[0], "refs": [order[0]], "kind": "resumen", "frase": resumen.strip(), "ok": True, "faltan": [],
                      "cita": idx.cita(order[0], q)}
    else:
        yield "candidatos", ids
        if cos < MIN_COS:
            yield "nada", "umbral"
            yield "fin", {**st, "total": round(time.time() - t0, 2)}
            return
        order = sorted(ids, key=lambda i: (idx.segs[i]["kind"] != "voz", idx.segs[i]["s"]))
        user = prompt(idx, order, q)
        args = dict(system=SYSTEM_I + ("" if es else SYSTEM_EN) + (SYSTEM_M if idx.multi else ""), gram=grammar_i(len(order), quote=not es), max_tokens=420)
    buf, n_out, t1, first, seen, dijo, pend = "", 0, time.time(), None, set(), set(), []
    if general and resumen:
        n_out += 1
        yield "frase", n_out0
    ded_n = ded_ok = 0  # dijo: tramos citados por las líneas «Se dijo»
    text_of = lambda js: " ".join(idx.segs[k]["text"] for j in js for k in idx.window(j))

    def check(frase, js):  # palabras sin respaldo (es) o ["cita"] si la cita literal no está (otro idioma)
        if es:
            return verify(frase, text_of(js))
        m = QUOTE.search(frase)
        return [] if m and quote_ok(m[1], text_of(js)) else ["cita"]
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
                miss = check(frase, refs)
                if miss and len(refs) == 1:  # el LLM a veces se equivoca de tramo: si sale entera de otro, es de ese
                    j = next((j for j in order if j not in seen and not check(frase, [j])), None)
                    if j is not None:
                        refs, miss = [j], []
                if bad_nums(frase, text_of(refs)):
                    continue  # cifra que no está entera en lo citado: se descarta la frase
                if idx.segs[refs[0]]["kind"] == "pantalla" and miss and not SCREEN_Q.search(q):
                    continue
                if idx.segs[refs[0]]["kind"] == "pantalla":
                    frase = re.sub(r"^Se dijo que", "En pantalla se mostró que", frase)
                seen.add(refs[0])
                dijo.update(refs)
            else:  # deducción / resumen: sin cifras inventadas
                if kind == "deduce":
                    if "»" not in frase:
                        frase = re.split(r"\.\s", frase + " ", 1)[0].rstrip(".") + "."  # una sola oración (la gramática ya cierra en la cita)
                    if not set(refs) <= dijo:
                        continue  # una deducción solo puede citar lo que ya sostiene los hechos de esta respuesta
                    ded_n += 1
                    qm = QUOTE.search(frase.split(", porque se dijo que ", 1)[-1])
                    if not qm or not quote_ok(qm[1], text_of(refs)):
                        continue  # «porque se dijo que «…»» es un hecho: la cita tiene que ser literal del fragmento citado
                    ded_ok += 1
                miss = bad_nums(frase, allowed or text_of(refs))
                if miss:
                    continue
            ev = {"i": refs[0], "refs": refs, "kind": kind, "frase": frase, "ok": not miss, "faltan": miss,
                  "cita": idx.cita(refs[0], q)}
            if general:
                n_out += 1
                yield "frase", ev
            else:
                pend.append(ev)
    if pend and os.environ.get("ACTAS_JUDGE", "1") != "0":
        t2 = time.time()
        # solo se revisan las que se enseñan como frase (ok); las no verificadas ya salen como cita literal
        rev = [e for e in pend if e["ok"]]
        try:
            vs = judge(url, q, [(e["kind"], e["frase"], text_of(e["refs"])) for e in rev]) if rev else []
        except Exception:  # sin revisor: mejor mostrar lo verificado que nada
            vs = [True] * len(rev)
        bad = {id(e) for e, v in zip(rev, vs) if not v}
        pend = [e for e in pend if id(e) not in bad]
        good = {j for e in pend if e["kind"] == "dijo" for j in e["refs"]}
        pend = [e for e in pend if e["kind"] == "dijo" or set(e["refs"]) <= good]  # la deducción pierde su base -> cae
        st["juez"] = round(time.time() - t2, 2)
    for ev in pend:
        n_out += 1
        yield "frase", ev
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
    assert bad_nums("Se dijo que son 75,75 dólares", "cuesta 34,75 dólares") == ["75,75"]
    assert bad_nums("son 34.75 y 1000", "cuesta 34,75 y 1.000 mil") == []
    assert bad_nums("son 75", "cuesta 34,75") == ["75"]
    assert quote_ok("Lo que haría en MI ordenador", "dice: lo que haría, en mi ordenador, sería") and not quote_ok("lo que haré en mi ordenador", "lo que haría en mi ordenador")
    assert quote_ok("lo que haría … sería presentarme", "lo que haría en mi ordenador sería presentarme") and not quote_ok("hola mundo", "hola mundo")
    g = grammar(3)
    assert '"1" | "2" | "3"' in g and "NINGUNO" in g
    e = os.environ.pop("ACTAS_CHAT", None)  # regla del chat con RAM/VRAM falsas
    assert P.chat_model(ram=8, vram_mb=0)[0] == "qwen" and P.chat_model(ram=16, vram_mb=0)[0] == "gemma" and P.chat_model(ram=8, vram_mb=8000)[0] == "gemma"
    os.environ["ACTAS_CHAT"] = "qwen"; assert P.chat_model(ram=64, vram_mb=0)[0] == "qwen"
    os.environ["ACTAS_CHAT"] = "gemma"; assert P.chat_model(ram=4, vram_mb=0)[0] == "gemma"
    os.environ.pop("ACTAS_CHAT"); e and os.environ.__setitem__("ACTAS_CHAT", e)
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
