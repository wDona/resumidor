"""Carpeta = expediente: datos libres, pendientes de todos sus documentos (con estado propio), seguimiento automático,
línea de tiempo, estado actual, comparar dos documentos y glosario. Todo vive en work/registro.db (registro.py; por nombre de carpeta):
leer()/editar() siguen dando el expediente como dict; los pendientes son entidades del registro. Los documentos solo se leen. Las rutas HTTP están en app.py; aquí, la lógica (la prueban test_carpetas.py y los documentos de prueba)."""
import calendar
import copy
import datetime as dt
import hashlib
import json
import re
import time
import uuid
from collections import Counter

import numpy as np

import exportar
import pipeline as P
import plantillas
import rag
import registro

LOCK = registro.LOCK  # el mismo: editar() (leer, cambiar, guardar) y las escrituras del registro no se cruzan
DEF = {"tipo": "", "datos": [], "glosario": [], "glos_ignorados": [], "ajustes": {"anon": None, "idioma": ""}, "estados": {}, "manuales": [],
       "sugeridos": {}, "notas": [], "eventos": [], "estado_txt": None, "comparar_txt": {}}
ESTADOS = ("abierto", "hecho", "descartado")
# etiqueta del tipo de carpeta según el perfil por defecto (los nombres del asistente de uso); sin perfil: el nombre general de ajustes
TIPO_PERFIL = {"comunidad": "Comunidad", "consulta": "Paciente", "seleccion": "Candidato", "clase": "Asignatura", "obra": "Obra",
               "periodistica": "Estudio", "cualitativa": "Estudio", "video": "Serie", "comercial": "Cliente",
               "raid": "Proyecto", "requisitos": "Proyecto", "comite": "Proyecto", "daily": "Proyecto", "retro": "Proyecto"}
SUGERIDOS = {"comunidad": ["Dirección", "Administrador", "Nº de vecinos"], "cliente": ["Contacto", "Teléfono"], "paciente": ["Referencia interna"],
             "candidato": ["Referencia interna", "Puesto"], "proyecto": ["Código", "Cliente", "Sponsor", "Jefe de proyecto", "Fase", "Fecha de inicio", "Fecha fin prevista", "Presupuesto"], "asignatura": ["Curso", "Docente"],
             "obra": ["Dirección", "Promotor"], "estudio": ["Responsable"], "serie": ["Canal"]}
SENSIBLES = {"paciente", "candidato"}  # solo una referencia interna: nada que identifique a la persona
# (casi todas son nunca_recortar en su perfil; «incidencias» de la junta de vecinos no, pero también es accionable)
ACCION = {"compromisos", "pasos", "siguiente", "incidencias", "pendientes", "checklist", "derramas"}  # secciones de otros perfiles que son accionables
SUP, IGUAL, CAMB = 0.80, 0.92, 0.65  # coseno: decisión posterior que sustituye a otra · mismo punto sin cambios · mismo punto cambiado


# ---------- almacén ----------
def leer(c):
    return {**copy.deepcopy(DEF), **registro.expediente(c)}


def editar(c, fn):
    """fn(expediente) -> valor; guarda lo que fn cambie (una transacción del registro; lo de pendientes, también en su historial)."""
    with LOCK:
        e = leer(c)
        antes = copy.deepcopy(e)
        r = fn(e)
        registro.guardar_expediente(c, antes, e)
        return r


def renombrar(old, new):
    """La carpeta cambia de nombre (new) o se quita (new vacío): su expediente se mueve o se aparta (no se borra; registro.renombrar).
    ValueError si new ya tiene datos en el registro."""
    registro.renombrar(old, new)


def evento(e, tipo, **k):
    e["eventos"].append({"t": time.time(), "tipo": tipo, **k})
    del e["eventos"][:-500]


def tipo_de(e, perfil, general):
    return e["tipo"] or TIPO_PERFIL.get(perfil or "") or general or "Carpeta"


def sugerencias(tipo):
    return SUGERIDOS.get((tipo or "").casefold(), ["Responsable", "Referencia"])


def guardar_datos(c, tipo, datos):
    lim = lambda x, n: str(x or "").strip()[:n]
    ds = [{"k": lim(x.get("k"), 60), "v": lim(x.get("v"), 300)} for x in datos if isinstance(x, dict) and lim(x.get("k"), 60)][:40]
    editar(c, lambda e: e.update(datos=ds, **({"tipo": lim(tipo, 40)} if tipo is not None else {})))


def guardar_ajustes(c, anon, idioma):
    editar(c, lambda e: e["ajustes"].update(anon=anon if isinstance(anon, bool) else None, idioma=str(idioma or "")[:12]))


# ---------- documentos de la carpeta ----------
def docs(ms):
    """Último documento (acta) de cada reunión de `ms` (meetings() de una carpeta), por fecha: lleva los datos (lo editado manda)."""
    out, vistos = [], set()
    for m in ms:
        if m["id"] in vistos:
            continue
        vistos.add(m["id"])
        vs = [f.parent for f in (P.WORK / m["id"]).glob("acta_*/acta.json")]
        if not vs:
            continue
        d = max(vs, key=lambda x: (x / "acta.json").stat().st_mtime)
        try:
            data = json.loads((d / (exportar.EDITADA if (d / exportar.EDITADA).is_file() else "acta.json")).read_text())
            tpl = next((t for t in plantillas.todas() if t["nombre"] == data.get("plantilla")), None) or plantillas.get("acta")
        except (OSError, ValueError):
            continue
        out.append({"mid": m["id"], "ver": d.name, "asr": d.name.split("_")[2], "nombre": m["label"], "mtime": m["mtime"], "data": data, "tpl": tpl,
                    "sin": m.get("sin"), "fecha": dt.date.fromtimestamp(m["mtime"]).isoformat()})
    return sorted(out, key=lambda x: x["mtime"])


def _ref(d, t=0):
    return {"mid": d["mid"], "ver": d["ver"], "doc": d["nombre"], "fecha": d["fecha"], "t": t or 0}


# ---------- pendientes ----------
DIAS = ["lunes", "martes", "mi[eé]rcoles", "jueves", "viernes", "s[aá]bado", "domingo"]


def plazo_fecha(txt, ref):
    """Plazo en texto -> date o None: las fechas de exportar.fecha + «mañana», «el viernes», «la semana que viene», «final de mes»."""
    if f := exportar.fecha(txt, ref):
        return f
    s = (txt or "").lower()
    if re.search(r"\bhoy\b", s):
        return ref
    if re.search(r"\bma[ñn]ana\b", s):
        return ref + dt.timedelta(1)
    for i, rx in enumerate(DIAS):
        if re.search(rf"\b{rx}\b", s):
            return ref + dt.timedelta((i - ref.weekday()) % 7 or 7) + dt.timedelta(7 * bool(re.search(r"semana que viene|pr[oó]xima semana|siguiente semana", s)))
    if re.search(r"(fin|final) de mes", s):
        return ref.replace(day=calendar.monthrange(ref.year, ref.month)[1])
    return None


def _vacio(v):
    return not str(v or "").strip(" —-.") or str(v).strip().lower() in ("n/a", "sin plazo", "sin fecha")


def _h(mid, texto):
    return hashlib.sha1((mid + "|" + " ".join(P.words(texto))).encode()).hexdigest()[:10]


def items_doc(d):
    """Pendientes de un documento: tareas + items de secciones accionables (compromisos, pasos, siguiente, incidencias, pendientes, checklist,
    derramas con plazo). id = documento|versión|ruta del dato (la misma ruta de /api/doc)."""
    D, out = d["data"], []
    ref = dt.date.fromtimestamp(d["mtime"])
    seg = {s.get("id"): s["seguir"] for s in (d.get("tpl") or {}).get("secciones", []) if s.get("seguir")}  # sección → entidad que sigue (tarea, riesgo…)

    def add(k, tipo, texto, resp, plazo, t, cita, ent="tarea"):
        texto = str(texto or "").strip()
        if texto:
            resp, plazo = ("" if _vacio(resp) else str(resp).strip()), ("" if _vacio(plazo) else str(plazo).strip())
            f = plazo_fecha(plazo, ref)
            out.append({**_ref(d, t), "fecha_doc": d["fecha"], "id": f"{d['mid']}|{d['ver']}|{k}", "tipo": tipo, "tipo_ent": ent, "texto": texto, "resp": resp, "plazo": plazo,
                        "cita": cita or "", "h": _h(d["mid"], texto), "fecha": f and f.isoformat()})  # fecha = fecha límite (la del documento, fecha_doc)
    for i, x in enumerate(D.get("tareas") or []):
        add(f"tareas.{i}", "Tarea", x.get("tarea"), x.get("responsable"), x.get("plazo"), x.get("t"), x.get("cita"))  # tipo_ent="tarea"
    for si, s in enumerate(D.get("secciones_plantilla") or []):
        ent = s.get("seguir") or seg.get(s.get("id"))
        if not ent and s.get("id") not in ACCION:
            continue  # sin `seguir` se sigue el conjunto fijo ACCION (plantillas de usuario antiguas)
        for j, x in enumerate(s.get("items") or []):
            plazo = x.get("plazo") or x.get("fecha") or ""
            if s["id"] == "derramas" and _vacio(plazo):
                continue  # una derrama sin plazo es información, no un pendiente
            txt = x.get("texto") or ""
            if s["id"] == "derramas" and not _vacio(x.get("importe")):
                txt += f" ({x['importe']})"
            add(f"secciones_plantilla.{si}.items.{j}", s.get("nombre", s["id"]), txt, x.get("responsable"), plazo, x.get("t"), x.get("cita"), ent or "tarea")
    return out


def pendientes(c, ms, hoy=None):
    """Todos los pendientes de la carpeta (de sus documentos y los manuales) con su estado, plazo y sugerencia de seguimiento."""
    hoy, ds, res = hoy or dt.date.today(), docs(ms), []
    ents = registro.sincronizar(c, ds)  # cada ítem es una entidad: su estado sigue al texto si se rehace el documento (registro.py)
    for d in ds:
        for it in items_doc(d):
            x = ents[it["id"]]
            if x["revision"] not in registro.OCULTA:
                ed = {"texto": x["titulo"], "resp": x["dueno"]} if x["editado"] else {}  # editada a mano: manda la entidad
                res.append({**it, **ed, "tipo_ent": x["tipo"], "mtime": d["mtime"], "manual": False, "estado": x["estado"], "nota": x["campos"].get("nota", ""), "sugerido": x["sugerencia"]})
    for x in registro.listar(c, origen="manual"):
        if x["revision"] in registro.OCULTA:
            continue
        pl = x["campos"].get("plazo", "")
        f = plazo_fecha(pl, dt.date.fromtimestamp(x["creado"]))
        res.append({"id": x["id"], "tipo": "Manual", "tipo_ent": x["tipo"], "texto": x["titulo"], "resp": x["dueno"], "plazo": pl, "t": 0, "cita": "", "mid": "", "ver": "", "doc": "", "h": "",
                    "fecha": f and f.isoformat(), "mtime": x["creado"], "manual": True, "estado": x["estado"], "nota": x["campos"].get("nota", ""), "sugerido": x["sugerencia"]})
    for p in res:
        dias = (dt.date.fromisoformat(p["fecha"]) - hoy).days if p["fecha"] else None
        p["dias"], p["vencido"] = dias, dias is not None and dias < 0 and p["estado"] == "abierto"
        p["pronto"] = dias is not None and 0 <= dias <= 7 and p["estado"] == "abierto"  # «vence pronto»: en la próxima semana
    return res


def listar(c, ms, estado="abierto", resp="", orden="plazo", hoy=None):
    """Filtra por estado (abierto|hecho|descartado|todos) y responsable; orden plazo (sin fecha al final) | doc."""
    ps = pendientes(c, ms, hoy)
    resps = sorted({p["resp"] for p in ps if p["resp"]}, key=str.casefold)
    xs = [p for p in ps if estado in ("todos", p["estado"]) and (not resp or resp.casefold() in p["resp"].casefold())]
    xs.sort(key=(lambda p: (p["fecha"] is None, p["fecha"] or "", p["mtime"])) if orden == "plazo" else (lambda p: (p["mtime"], p["t"])))
    cnt = Counter(p["estado"] for p in ps)
    return {"items": xs, "responsables": resps, "n": {k: cnt.get(k, 0) for k in ESTADOS}, "sugeridos": [p for p in ps if p["sugerido"] and p["estado"] == "abierto"]}


def _buscar(c, ms, pid, hoy=None):
    p = next((p for p in pendientes(c, ms, hoy) if p["id"] == pid), None)
    if not p:
        raise KeyError("Ese pendiente ya no existe")
    return p


def set_estado(c, ms, pid, estado, hoy=None):
    if estado not in ESTADOS:
        raise ValueError("Estado no válido")
    p = _buscar(c, ms, pid, hoy)

    def f(e):
        e["estados"][pid] = {**e["estados"].get(pid, {}), "estado": estado, "t": time.time(), "mid": p["mid"], "h": p["h"]}
        e["sugeridos"].pop(pid, None)
        evento(e, "pendiente", id=pid, texto=p["texto"], de=p["estado"], a=estado)
    editar(c, f)


def resolver_sugerencia(c, ms, pid, aceptar, hoy=None):
    """El usuario confirma o rechaza «parece hecho»/«actualizado». Nunca se cierra solo: aceptar «hecho» cierra; «actualizado» deja la nota."""
    s = leer(c)["sugeridos"].get(pid)
    if not s:
        raise KeyError("No hay sugerencia para ese pendiente")
    if aceptar and s["tipo"] == "hecho":
        return set_estado(c, ms, pid, "hecho", hoy)
    if aceptar:  # actualizado: sigue abierto, con la nota
        p = _buscar(c, ms, pid, hoy)

        def g(e):
            e["estados"][pid] = {**e["estados"].get(pid, {"estado": p["estado"]}), "nota": "Actualizado: «" + s["cita"] + "»", "t": time.time(), "mid": p["mid"], "h": p["h"]}
            evento(e, "pendiente", id=pid, texto=p["texto"], de="abierto", a="actualizado", cita=s["cita"])
            e["sugeridos"].pop(pid, None)
        editar(c, g)
    else:
        editar(c, lambda e: e["sugeridos"].pop(pid, None))


def añadir_manual(c, texto, resp="", plazo=""):
    texto = str(texto or "").strip()[:300]
    if not texto:
        raise ValueError("Escribe el pendiente")
    m = {"id": "m:" + uuid.uuid4().hex[:8], "texto": texto, "resp": str(resp or "").strip()[:60], "plazo": str(plazo or "").strip()[:60], "creado": time.time()}

    def f(e):
        e["manuales"].append(m)
        evento(e, "manual", id=m["id"], texto=texto)
    editar(c, f)
    return m


def borrar_manual(c, pid):
    def f(e):
        e["manuales"] = [m for m in e["manuales"] if m["id"] != pid]
        e["estados"].pop(pid, None)
        e["sugeridos"].pop(pid, None)
    editar(c, f)


# ---------- notas y línea de tiempo ----------
def añadir_nota(c, texto, fecha=None):
    texto = str(texto or "").strip()[:2000]
    if not texto:
        raise ValueError("Escribe la nota")
    try:
        fecha = dt.date.fromisoformat(fecha) if fecha else dt.date.today()
    except ValueError:
        raise ValueError("Fecha no válida (AAAA-MM-DD)")
    n = {"id": uuid.uuid4().hex[:8], "fecha": fecha.isoformat(), "texto": texto, "t": time.time()}
    editar(c, lambda e: e["notas"].append(n))
    return n


def borrar_nota(c, nid):
    editar(c, lambda e: e.update(notas=[n for n in e["notas"] if n["id"] != nid]))


def linea(c, ms):
    """Documentos, notas del usuario y cambios de estado de pendientes, del más reciente al más antiguo."""
    e, out = leer(c), []
    for d in docs(ms):
        out.append({**_ref(d), "tipo": "doc", "t": d["mtime"], "titulo": d["data"].get("titulo") or d["nombre"], "resumen": (d["data"].get("resumen") or "")[:240],
                    "n_pend": len(items_doc(d))})
    for n in e["notas"]:
        out.append({"tipo": "nota", "t": dt.datetime.combine(dt.date.fromisoformat(n["fecha"]), dt.time(12)).timestamp(), "fecha": n["fecha"], "id": n["id"], "texto": n["texto"]})
    for v in e["eventos"]:
        out.append({**v, "fecha": dt.date.fromtimestamp(v["t"]).isoformat()})
    return sorted(out, key=lambda x: -x["t"])


# ---------- glosario ----------
def glosario_set(c, lista, ignorar=()):
    ls, vistos = [], set()
    for x in lista if isinstance(lista, list) else []:
        t = str(x.get("t") or "").strip()[:60] if isinstance(x, dict) else ""
        if t and t.casefold() not in vistos:
            vistos.add(t.casefold())
            ls.append({"t": t, "orto": str(x.get("orto") or "").strip()[:60], "def": str(x.get("def") or "").strip()[:160]})
    editar(c, lambda e: e.update(glosario=ls[:200], glos_ignorados=sorted({*e["glos_ignorados"], *map(str, ignorar)})[:500]))


def terminos(c):
    """Términos para el ASR (hotwords): la ortografía correcta de cada entrada, como mucho 40. Sin glosario: lista vacía."""
    return [x["orto"] or x["t"] for x in leer(c)["glosario"]][:40] if c else []


def terminos_prompt(c):
    """«Término (definición)» por entrada, para el map/reduce («términos de este proyecto»)."""
    return [(x["orto"] or x["t"]) + (f" ({x['def']})" if x["def"] else "") for x in leer(c)["glosario"]][:40] if c else []


def ortografia(c, texto):
    """Cambia en un texto mostrado las formas del glosario por su ortografía correcta (solo presentación: no toca lo verificado)."""
    for x in leer(c)["glosario"] if c else []:
        if x["orto"] and x["orto"] != x["t"]:
            texto = re.sub(rf"(?<!\w){re.escape(x['t'])}(?!\w)", x["orto"], texto, flags=re.I)
    return texto


MESES_DIAS = set("enero febrero marzo abril mayo junio julio agosto septiembre setiembre octubre noviembre diciembre lunes martes miércoles jueves viernes sábado domingo".split())


def sugerir_glosario(c, ms, minimo=3, n=30):
    """Nombres propios frecuentes de las transcripciones de la carpeta (palabras con mayúscula que no abren frase) que aún no están en el glosario."""
    cnt, ini, e = Counter(), Counter(), leer(c)
    ya = {x["t"].casefold() for x in e["glosario"]} | {x["orto"].casefold() for x in e["glosario"] if x["orto"]} | {x.casefold() for x in e["glos_ignorados"]}
    cap = re.compile(r"[A-ZÁÉÍÓÚÑ][\wáéíóúñü]{2,}(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñü]{2,})*")
    for d in docs(ms):
        try:
            segs = json.loads((P.WORK / d["mid"] / f"transcript_{d['asr']}.json").read_text())["segments"]
        except (OSError, ValueError, KeyError):
            continue
        for s in segs:
            t = s["text"]
            for m in cap.finditer(t):
                w = m.group(0)
                if w.casefold() in MESES_DIAS or w.casefold() in rag.STOP or w.casefold() in ya:
                    continue
                if m.start() == 0 or re.search(r"[.?!¿¡:]\s*$", t[:m.start()]):  # abre frase: la mayúscula no dice nada...
                    ini[w] += 1
                else:
                    cnt[w] += 1
    for w in cnt:  # ...salvo que esa misma palabra también aparezca en mitad de frase (un nombre propio): entonces cuentan todas
        cnt[w] += ini[w]
    return [{"t": w, "n": k} for w, k in cnt.most_common(n) if k >= minimo]


# ---------- parecidos (embeddings de serie; sin ellos, vocabulario) ----------
_vec = {}


def sim(a, b):
    """Matriz de coseno len(a) x len(b) entre textos: embeddings de serie (CPU) con caché; si no hay modelo, solapamiento de vocabulario."""
    if not a or not b:
        return np.zeros((len(a), len(b)))
    try:
        falta = [t for t in dict.fromkeys(a + b) if t not in _vec]
        if falta:
            _vec.update(zip(falta, rag.embed(falta, False, 2, std=True)))
        return np.array([_vec[t] for t in a]) @ np.array([_vec[t] for t in b]).T
    except Exception:
        ta, tb = [Counter(rag.terms(t)) for t in a], [Counter(rag.terms(t)) for t in b]
        nrm = lambda c: sum(v * v for v in c.values()) ** 0.5 or 1
        return np.array([[sum(x[w] * y[w] for w in x) / (nrm(x) * nrm(y)) for y in tb] for x in ta])


def _num(t):
    return sorted(str(v) for _, v in rag.cantidades(t, False))


# ---------- decisiones vigentes, comparar y estado actual ----------
def decisiones(ds):
    return [{"texto": x["texto"], "cita": x.get("cita", ""), "mt": d["mtime"], **_ref(d, x.get("t"))} for d in ds for x in d["data"].get("decisiones") or [] if x.get("texto")]


def vigentes(ds, sup=SUP):
    """(vigentes, superadas): la decisión de un documento posterior que dice casi lo mismo que otra anterior la sustituye (gana la última)."""
    xs = decisiones(ds)
    S = sim([x["texto"] for x in xs], [x["texto"] for x in xs])
    vig, sub = [], []
    for i, x in enumerate(xs):
        j = max((j for j, y in enumerate(xs) if y["mt"] > x["mt"] and S[i][j] >= sup), key=lambda j: (xs[j]["mt"], S[i][j]), default=None)
        (sub.append({**x, "por": xs[j]}) if j is not None else vig.append(x))
    return vig, sub


def _items_cmp(d):
    D = d["data"]
    return {"decisiones": [(x["texto"], "", x.get("t")) for x in D.get("decisiones") or []],
            "tareas": [(x["tarea"], " · ".join(v for v in (x.get("responsable"), x.get("plazo")) if not _vacio(v)), x.get("t")) for x in D.get("tareas") or []],
            "puntos": [(x["texto"], "", x.get("t")) for x in D.get("puntos") or []]}


def comparar(a, b):
    """a (anterior) y b (posterior): documentos de docs(). Por bloque: nuevo, cambiado {antes, ahora}, ya_no e igual (nº). Emparejado voraz por coseno."""
    ia, ib, out = _items_cmp(a), _items_cmp(b), {}
    for k in ia:
        A, B = ia[k], ib[k]
        S = sim([x[0] for x in B], [x[0] for x in A])
        pares = sorted(((S[i][j], i, j) for i in range(len(B)) for j in range(len(A)) if S[i][j] >= CAMB), reverse=True)
        ui, uj, r = set(), set(), {"nuevo": [], "cambiado": [], "ya_no": [], "igual": 0}
        for s, i, j in pares:
            if i in ui or j in uj:
                continue
            ui.add(i), uj.add(j)
            if s >= IGUAL and _num(A[j][0]) == _num(B[i][0]) and A[j][1].casefold() == B[i][1].casefold():
                r["igual"] += 1
            else:
                r["cambiado"].append({"antes": {"texto": A[j][0], "extra": A[j][1], **_ref(a, A[j][2])}, "ahora": {"texto": B[i][0], "extra": B[i][1], **_ref(b, B[i][2])}, "sim": round(float(s), 2)})
        r["nuevo"] = [{"texto": x[0], "extra": x[1], **_ref(b, x[2])} for i, x in enumerate(B) if i not in ui]
        r["ya_no"] = [{"texto": x[0], "extra": x[1], **_ref(a, x[2])} for j, x in enumerate(A) if j not in uj]
        out[k] = r
    return {"a": _ref(a), "b": _ref(b), **out}


def comparar_ids(c, ms, a, b):
    ds = {d["mid"]: d for d in docs(ms)}
    if a not in ds or b not in ds or a == b:
        raise KeyError("Elige dos documentos distintos de la carpeta")
    x, y = sorted((ds[a], ds[b]), key=lambda d: d["mtime"])
    return {**comparar(x, y), "redaccion": leer(c)["comparar_txt"].get(f"{x['mid']}|{y['mid']}")}


def estado_actual(c, ms, hoy=None):
    ds = docs(ms)
    vig, sup = vigentes(ds)
    ab = [p for p in pendientes(c, ms, hoy) if p["estado"] == "abierto"]
    e = leer(c)
    return {"n_docs": len(ds), "ultimo": _ref(ds[-1]) if ds else None, "decisiones": {"vigentes": vig, "superadas": sup},
            "pendientes": sorted(ab, key=lambda p: (p["fecha"] is None, p["fecha"] or "")),
            "cambios": comparar(ds[-2], ds[-1]) if len(ds) > 1 else None, "redaccion": e["estado_txt"],
            "obsoleta": bool(e["estado_txt"]) and e["estado_txt"].get("n_docs") != len(ds)}


# ---------- redacción con LLM (trabajos en cola) ----------
SYS_RED = """Redactas un resumen de un expediente a partir de datos numerados [n] (decisiones, pendientes, cambios). \
Escribe de 3 a 6 frases cortas. Usa SOLO lo recibido: no añadas hechos, nombres, cifras ni fechas. Cada frase termina con el número \
de la fuente que la apoya entre corchetes, por ejemplo [3] o [2][5]. Si hay una decisión sustituida por otra, cuenta solo la vigente."""


def _redactar(chat, fuentes, titulo, sistema=SYS_RED):
    """fuentes: [(texto, ref)] -> [{texto, refs:[ref]}]: cada frase cita fuentes que existen y no trae cifras que ellas no tengan."""
    user = f"{titulo}\n\n" + "\n".join(f"[{i}] {t}" for i, (t, _) in enumerate(fuentes, 1))
    r = chat(sistema, user, P.obj(frases=P.arr(P.S(300), 6, 1)), 700, temperature=0.1)
    res = []
    for f in r["frases"]:
        ns = [int(n) for n in re.findall(r"\[(\d+)\]", f) if 0 < int(n) <= len(fuentes)]
        txt = re.sub(r"\s*(\[\d+\])+", "", f).strip()
        if ns and txt and not rag.bad_nums(txt, " ".join(fuentes[n - 1][0] for n in ns)):
            res.append({"texto": txt, "refs": [fuentes[n - 1][1] for n in dict.fromkeys(ns)]})
    return res


def _src(x, pref=""):
    return (pref + x["texto"] + (f" ({x['extra']})" if x.get("extra") else ""), {k: x[k] for k in ("mid", "ver", "doc", "fecha", "t")})


def redactar_estado(c, ms, chat, hoy=None):
    est = estado_actual(c, ms, hoy)
    fu = [_src(x, "Decisión vigente: ") for x in est["decisiones"]["vigentes"]] + [_src(x, "Decisión anterior sustituida: ") for x in est["decisiones"]["superadas"]] + \
        [_src(p, "Pendiente abierto" + (f" de {p['resp']}" if p["resp"] else "") + (f", plazo {p['plazo']}" if p["plazo"] else "") + ": ") for p in est["pendientes"][:15] if p["mid"]]
    cb = est["cambios"] or {}
    fu += [_src(x, "Nuevo en el último documento: ") for k in ("decisiones", "tareas") for x in (cb.get(k) or {}).get("nuevo", [])]
    fu += [_src(x["ahora"], "Cambiado (antes: " + x["antes"]["texto"] + "): ") for k in ("decisiones", "tareas") for x in (cb.get(k) or {}).get("cambiado", [])]
    if not fu:
        raise RuntimeError("Aún no hay decisiones ni pendientes que resumir")
    txt = {"t": time.time(), "n_docs": est["n_docs"], "frases": _redactar(chat, fu, "Estado actual de la carpeta «" + c + "»")}
    editar(c, lambda e: e.update(estado_txt=txt))
    return txt


def redactar_comparacion(c, ms, a, b, chat):
    cm = comparar_ids(c, ms, a, b)
    fu = []
    for k in ("decisiones", "tareas", "puntos"):
        fu += [_src(i, f"Nuevo en {k}: ") for i in cm[k]["nuevo"]] + [_src(i, f"Ya no aparece en {k}: ") for i in cm[k]["ya_no"]]
        fu += [_src(i["ahora"], f"Cambiado en {k} (antes: {i['antes']['texto']}): ") for i in cm[k]["cambiado"]]
    if not fu:
        raise RuntimeError("No hay diferencias que contar")
    txt = {"t": time.time(), "frases": _redactar(chat, fu[:30], f"Diferencias entre «{cm['a']['doc']}» y «{cm['b']['doc']}»")}
    editar(c, lambda e: e["comparar_txt"].__setitem__(f"{cm['a']['mid']}|{cm['b']['mid']}", txt))
    return txt


# ---------- seguimiento: ¿el documento nuevo cierra o cambia algún pendiente abierto? ----------
SYS_SEG = """Revisas si lo dicho en una reunión NUEVA cierra o cambia pendientes anteriores. Recibes pendientes numerados y, de cada uno, \
fragmentos de la reunión nueva con su minuto. Por cada pendiente responde:
estado = «hecho» si un fragmento dice que ya se hizo, se terminó o se resolvió; «actualizado» si cambia su plazo, su responsable o su alcance; \
«ninguno» si no lo dicen (hablar del tema sin decir que está hecho es «ninguno»).
cita = copia LITERAL (de 5 a 25 palabras) del fragmento que lo prueba; vacío si es «ninguno». No inventes."""
UMBRAL_SEG = 0.5  # coseno mínimo entre el pendiente y algún tramo del documento nuevo para gastar LLM en él


def candidatos_seguimiento(idx, abiertos, umbral=UMBRAL_SEG):
    """[(pendiente, [índices de tramos])]: recuperación en el documento nuevo para cada pendiente abierto (sin LLM)."""
    out = []
    for p in abiertos:
        ids, cos = idx.search(p["texto"] + (" " + p["resp"] if p["resp"] else ""))
        ids = [i for i in ids if idx.segs[i]["kind"] == "voz"][:3]
        if ids and cos >= umbral:
            out.append((p, sorted(ids)))
    return out


def verificar_seguimiento(idx, ids, cita):
    """Tramo donde la cita aparece literal (>= 3 palabras, en el tramo o sus vecinos), o None."""
    for i in ids:
        if rag.quote_ok(cita, " ".join(idx.segs[j]["text"] for j in idx.window(i))):
            return next((j for j in idx.window(i) if rag.quote_ok(cita, idx.segs[j]["text"])), i)
    return None


def seguimiento(c, ms, mid, chat_ctx, threads=2, hoy=None, lote=5, idx=None):
    """Una pasada del LLM (chat_ctx() da el `chat` de pipeline.llama) sobre los pendientes abiertos de documentos anteriores y el documento
    `mid`. Guarda sugerencias «hecho»/«actualizado» con cita literal verificada y minuto; no cierra nada. -> nº de sugerencias."""
    nuevo = next((d for d in docs(ms) if d["mid"] == mid), None)
    if not nuevo or nuevo["sin"] or not (P.WORK / mid / f"transcript_{nuevo['asr']}.json").is_file():
        return 0
    editar(c, lambda e: [e["sugeridos"].pop(k) for k, v in list(e["sugeridos"].items()) if v.get("mid") == mid])
    ab = [p for p in pendientes(c, ms, hoy) if p["estado"] == "abierto" and p["mid"] != mid and p["mtime"] <= nuevo["mtime"] and not p["sugerido"]]
    if not ab:
        return 0
    idx = idx or rag.Index(str(P.WORK / mid), nuevo["asr"], threads)
    cand = candidatos_seguimiento(idx, ab)
    n = 0
    if not cand:
        return 0
    with chat_ctx() as chat:
        for b in range(0, len(cand), lote):
            lot = cand[b:b + lote]
            user = "\n\n".join(f"Pendiente {k}: «{p['texto']}»" + (f" (responsable: {p['resp']})" if p["resp"] else "") + (f" (plazo: {p['plazo']})" if p["plazo"] else "") + "\n" +
                               "\n".join(f"  ({P.fmt(idx.segs[i]['s'])}) {idx.segs[i]['text']}" for i in ids) for k, (p, ids) in enumerate(lot, 1))
            sch = P.obj(r=P.arr(P.obj(n={"enum": list(range(1, len(lot) + 1))}, estado={"enum": ["hecho", "actualizado", "ninguno"]}, cita=P.S(220)), len(lot), 1))
            for x in chat(SYS_SEG, user, sch, 120 * len(lot) + 40, temperature=0.0)["r"]:
                if x["estado"] == "ninguno" or not 1 <= x["n"] <= len(lot):
                    continue
                p, ids = lot[x["n"] - 1]
                j = verificar_seguimiento(idx, ids, x["cita"])
                if j is None:
                    continue  # la cita no es literal del documento nuevo: se descarta
                s = {"tipo": x["estado"], "cita": x["cita"].strip(), "t": idx.segs[j]["s"], "mid": mid, "ver": nuevo["ver"], "doc": nuevo["nombre"], "fecha": nuevo["fecha"]}

                def f(e, p=p, s=s):
                    if e["estados"].get(p["id"], {}).get("estado", "abierto") == "abierto":
                        e["sugeridos"][p["id"]] = s
                        evento(e, "sugerido", id=p["id"], texto=p["texto"], a=s["tipo"], cita=s["cita"], doc=s["doc"], mid=mid, t_doc=s["t"])
                editar(c, f)
                n += 1
    return n


# ---------- preguntas sobre pendientes («¿qué tiene pendiente Ana?»): lista determinista, sin LLM ----------
PEND_Q = re.compile(r"pendientes?\b|por hacer|tiene(?:n)? que|le(?:s)? toca|deb(?:e|en) hacer|to-?do\b|pending|outstanding|à faire|offen\b|(?:qu[eé]|cu[aá]les|what|which|list\w*|lista\w*).{0,30}\b(?:tareas?|tasks?)\b|who has to", re.I)


def pregunta_pendientes(c, ms, q):
    """None si la pregunta no va de pendientes; si va: {resp, items} con los abiertos (solo los del responsable nombrado en la pregunta, si lo hay)."""
    if not PEND_Q.search(q):
        return None
    ab = [p for p in pendientes(c, ms) if p["estado"] == "abierto"]
    fq = " " + " ".join(P.words(q)) + " "
    resp = next((r for r in sorted({p["resp"] for p in ab if p["resp"]}, key=len, reverse=True) if any(f" {' '.join(P.words(w))} " in fq for w in [r, *r.split()] if len(w) > 2)), "")
    if resp:
        ab = [p for p in ab if resp.casefold() in p["resp"].casefold()]
    return {"resp": resp, "items": sorted(ab, key=lambda p: (p["fecha"] is None, p["fecha"] or ""))}


# ---------- tarjetas del inicio ----------
def resumen_home(todas):
    """{carpeta: {pend, sug, ultima}}: pendientes abiertos, sugerencias por revisar y última actividad (documento, nota o cambio de estado)."""
    out = {}
    for c in {m["carpeta"] for m in todas if m["carpeta"]}:
        ms = [m for m in todas if m["carpeta"] == c]
        ps = pendientes(c, ms)
        e = leer(c)
        ult = max([m["mtime"] for m in ms] + [n["t"] for n in e["notas"]] + [v["t"] for v in e["eventos"]], default=0)
        out[c] = {"pend": sum(p["estado"] == "abierto" for p in ps), "sug": sum(bool(p["sugerido"]) and p["estado"] == "abierto" for p in ps), "ultima": ult}
    return out
