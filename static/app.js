const $ = id => document.getElementById(id);
// 409 {msg, faltan}: falta instalar modelos -> se abre Ajustes › Modelos con el aviso
const det = (j, st) => { const d = j.detail; if (d && d.faltan) { abrirModelos(d.msg, d.faltan); return d.msg; } return d || st; };
const api = (url, opt) => fetch(url, opt).then(async r => { if (!r.ok) throw new Error(det(await r.json().catch(() => ({})), r.statusText)); return r.json(); });
const post = (url, body) => api(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body || {})});
const mmss = t => { t = Math.floor(t); const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60, p = n => String(n).padStart(2, "0"); return (h ? h + ":" + p(m) : p(m)) + ":" + p(s); };
const el = (tag, props = {}, ...kids) => { const e = document.createElement(tag); for (const k in props) k.startsWith("data-") || k.startsWith("aria-") ? e.setAttribute(k, props[k]) : e[k] = props[k]; e.append(...kids); return e; };
const lsGet = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} };
let corriendo = false;
const GR = {activa: false, dev: null, est: null, notas: [], cfg: null};  // grabar.js

let PL = [], CP = {}, DEF = {}, IDI = {}, SERIE = {}, CE = {}, ESTILOS = [];  // plantillas (ver plantillas.js)
addEventListener("beforeunload", e => { if (corriendo) { e.preventDefault(); e.returnValue = "Hay trabajos en la cola; si cierras, se cancelarán"; } });
setInterval(() => fetch("/api/latido", {method: "POST"}).catch(() => {}), 5000); fetch("/api/latido", {method: "POST"});

// ---- elegir vídeo y transcripción ----
const INFO_TR = "Sustituye a la transcripción automática; con vídeo se alinea sola. Sin vídeo, el documento no lleva capturas ni reproductor.";
let ruta = "", rutaTr = "", hablaTr = false;
const setRuta = p => { ruta = p; $("ruta").value = p; typeof notasForm === "function" && notasForm(p); };
const setTr = async p => {
  rutaTr = ""; hablaTr = false; $("ruta-tr").value = p; $("quitar-tr").hidden = !p;
  try {
    if (p) {
      const r = await post("/api/transcripcion", {path: p}); rutaTr = p; hablaTr = r.hablantes.length > 0;
      $("info-tr").textContent = r.formato + " · " + r.segmentos + " segmentos · " + (hablaTr ? r.hablantes.length + " hablantes con nombre" : "sin nombres de hablantes");
    }
  } catch (err) { $("ruta-tr").value = ""; $("quitar-tr").hidden = true; $("info-tr").textContent = err.message; }
  $("hablantes").disabled = hablaTr; if (hablaTr) $("hablantes").checked = false; $("hint-hab").hidden = !hablaTr;
};
$("quitar-tr").onclick = () => { setTr(""); $("info-tr").textContent = INFO_TR; };
const elegir = (btn, tipo, set) => btn.onclick = async () => {
  btn.disabled = true;
  try { const r = (await post("/api/pick", {tipo})).path; if (r) set(r); } finally { btn.disabled = false; }
};
elegir($("elegir"), "video", setRuta); elegir($("elegir-tr"), "transcripcion", setTr);
const soltar = (zona, set, msg) => {
  zona.ondragover = e => { e.preventDefault(); zona.classList.add("over"); };
  zona.ondragleave = () => zona.classList.remove("over");
  zona.ondrop = async e => {
    e.preventDefault(); zona.classList.remove("over");
    const f = e.dataTransfer.files[0]; if (!f) return;
    $(msg).textContent = "Copiando " + f.name + "…";
    try { set((await api("/api/upload?name=" + encodeURIComponent(f.name), {method: "PUT", body: f})).path); $(msg).textContent = ""; }
    catch (err) { $(msg).textContent = err.message; }
  };
};
soltar($("drop"), p => /\.(vtt|srt|txt|docx)$/i.test(p) ? setTr(p) : setRuta(p), "subida"); soltar($("drop-tr"), setTr, "info-tr");

// ---- GPU: autodetectada; la elección manual se recuerda ----
api("/api/gpu").then(g => {
  const c = $("usar-gpu"), v = lsGet("usar-gpu", null);
  const gb = g.vram_mb ? `, ${Math.round(g.vram_mb / 1024)} GB de VRAM` : g.igpu ? ", gráfica integrada (usa la RAM del sistema)" : "";
  c.disabled = !g.ok; c.checked = g.ok && (v === null ? g.default : v === "1" || v === true);
  $("info-gpu").textContent = !g.ok ? "GPU no encontrada o no válida" : (g.default ? "Se te recomienda usar la GPU" : "No se te recomienda usar la GPU") + ` (${g.name}${gb})`;
  const chat = () => { const [gem, why] = g[c.checked && g.ok ? "chat_gpu" : "chat_cpu"]; return `Chat: ${gem ? "gemma-4-E4B" : g.llm} (${why})`; };
  const ram = () => $("info-ram").textContent = `RAM: ${g.ram_gb || "?"} GB` + (g.ok && g.vram_mb ? ` · VRAM: ${Math.round(g.vram_mb / 1024)} GB (${g.name})` : g.ok && g.igpu ? ` · ${g.name}: gráfica integrada (usa la RAM del sistema)` : "") + " · " + chat() + (g.ram_gb && g.ram_gb < 8 ? ". Poca RAM: el proceso puede ir muy lento o fallar" : "");
  ram();
  c.onchange = () => { ram(); lsSet("usar-gpu", c.checked ? "1" : "0"); };
  niveles(g.niveles);
}).catch(() => {});
let NIV = [];
const GB = b => (b / 1e9).toFixed(1).replace(".", ",") + " GB";
const nivelInfo = q => NIV.find(n => n.id === q);
const ESTADO = {ok: "cómodo", aviso: "lento", no: "no cabe"};
// selector de calidad: el <select> oculto guarda el valor; las tarjetas lo muestran (modelo y si cabe); «no cabe» deshabilitado
function niveles(l) {
  NIV = l; const c = $("calidad"), v = c.value;
  c.innerHTML = ""; for (const n of l) c.add(new Option(`${n.nombre} (${n.modelo})`, n.id));
  l.forEach((n, i) => c.options[i].disabled = n.estado === "no");
  c.value = l.some(n => n.id === v && n.estado !== "no") ? v : "rápida"; c.onchange();
}
function pintarCal() {
  $("cal-niv").replaceChildren(...NIV.map(n => {
    const b = el("button", {type: "button", role: "radio", className: "chip", "aria-checked": n.id === $("calidad").value, "aria-disabled": n.estado === "no",
      onclick: () => { if (n.estado === "no") return; $("calidad").value = n.id; $("calidad").onchange(); }},
      el("b", {textContent: n.nombre}), el("small", {textContent: n.modelo + " · " + (!n.instalado ? "sin instalar" : ESTADO[n.estado] || "")}));
    return b;
  }));
}
$("calidad").onchange = () => {
  const n = nivelInfo($("calidad").value); pintarCal(); if (!n) return;
  const t = [n.tiempo > 1 && `Tarda aprox. ${n.tiempo}× lo que Rápida`, n.estado === "no" && `No cabe en este equipo (necesita ~${Math.ceil(n.necesita)} GB de memoria)`,
    n.estado === "aviso" && "No tienes los recursos recomendados para este modelo, puede tardar más de lo normal", n.pers && "Modelo no probado con la app: la calidad del documento puede variar"].filter(Boolean);
  $("aviso-alta").textContent = t.join(". "); $("aviso-alta").hidden = !t.length;
  $("bajar-nivel").hidden = n.instalado; $("bajar-nivel").textContent = `Descargar ${n.modelo} (${GB(n.bytes)})`;
  $("info-alta").hidden = n.id === "rápida";
};
$("bajar-nivel").onclick = async () => { await post("/api/modelos", {ids: [nivelInfo($("calidad").value).m]}); abrirModelos(); };
const NIVELES_D = ["breve", "normal", "detallado"];
function pintarNivel() {
  $("seg-nivel").replaceChildren(...NIVELES_D.map(n => el("button", {type: "button", role: "radio", textContent: cap(n), "aria-checked": $("nivel").value === n, "aria-selected": $("nivel").value === n, onclick: () => { $("nivel").value = n; pintarNivel(); }})));
}

// ---- vistas ----
let vistaAct = "home";
const VISTAS = ["home", "nuevo", "grabar", "cola", "res", "preg", "ajustes", "uso"];
const vista = v => { vistaAct = v; VISTAS.forEach(n => $("v-" + n).hidden = n !== v); scrollTo(0, 0);
  if (v !== "ajustes" && location.hash) history.replaceState(null, "", location.pathname); document.title = "Actas"; if (v !== "res" && v !== "preg") mpCerrar(); };
const ir = v => { if (v === "home") pintarHome(); vista(v); };
const aviso = t => { const n = $("toast") || document.body.appendChild(el("div", {id: "toast", role: "status"})); n.textContent = t; n.hidden = false; clearTimeout(aviso.t); aviso.t = setTimeout(() => n.hidden = true, 3500); };
const irInicio = () => { fsel = undefined; ir("home"); };
$("inicio").onclick = e => { e.preventDefault(); irInicio(); };
$("nuevo-volver").onclick = $("cola-volver").onclick = e => { e.preventDefault(); ir("home"); };
$("preg-volver").onclick = e => { e.preventDefault(); mpCerrar(); ir("home"); };
$("b-cola").onclick = () => { vista("cola"); sondear(); };
$("nueva").onclick = () => formNuevo();
$("b-ajustes").onclick = () => abrirAjustes();

// ---- nuevo documento (o otra versión de uno existente: reuse) ----
let reuse = null;
const VACIO_SUB = $("form-sub").textContent, NUEVA_C = "\u0001nueva";
function carpetaSel(v) {
  const s = $("n-carpeta"); s.replaceChildren(new Option(sinC(), ""), ...carpetas.map(c => new Option(c, c)), new Option("+ " + cap(nm("carpeta")) + " nueva…", NUEVA_C));
  s.value = v && carpetas.includes(v) ? v : ""; $("n-carpeta-nueva").hidden = true; $("n-carpeta-nueva").value = "";
}
$("n-carpeta-l").textContent = "Guardar en";
$("n-carpeta").onchange = () => {
  const n = $("n-carpeta").value === NUEVA_C; $("n-carpeta-nueva").hidden = !n; if (n) $("n-carpeta-nueva").focus();
  const p = CP[$("n-carpeta").value]; if (p && !reuse && PL.some(t => t.id === p)) { $("plantilla").value = p; $("plantilla").onchange(); }
};
function formNuevo(m, a) {
  reuse = m ? {id: m.id, asr: a.asr} : null;
  $("form-t").textContent = m ? "Otra versión de «" + m.label + "»" : "Nuevo " + nm("documento");
  $("form-sub").textContent = m ? "Rehace el documento con otra plantilla, nivel o calidad aprovechando la transcripción y las capturas ya hechas. Con el mismo nivel y calidad que una versión existente, la sustituye." : VACIO_SUB;
  $("f-fuente-c").hidden = $("f-hab").hidden = !!m; $("n-carpeta").closest(".field").hidden = !!m; $("form-err").textContent = "";
  $("n-carpeta-l").textContent = "Guardar en"; $("plantilla-l").textContent = "Tipo";
  carpetaSel(m ? m.carpeta || "" : typeof fsel === "string" ? fsel : "");
  if (m) {  // propone la primera combinación que aún no existe
    const hay = n => cur.actas.some(x => x.name === n);
    const [n, c] = ["normal", "breve", "detallado"].flatMap(n => NIV.map(q => q.id).map(c => [n, c])).find(([n, c]) => !hay(`acta_${n}_${a.asr}${c === "rápida" ? "" : "_" + c}`)) || [a.nivel, a.calidad];
    $("nivel").value = n; $("calidad").value = c; $("calidad").onchange();
  }
  pintarNivel(); plantForm(CP[m ? m.carpeta || "" : typeof fsel === "string" ? fsel : ""] || "acta");
  vista("nuevo"); formSimple(m);
}
$("enlace").oninput = () => { const v = !!$("enlace").value.trim(); $("l-solo-audio").hidden = !v; if (!v) $("solo-audio").checked = false; };  // «solo audio» solo con enlace
const params = () => ({carpeta: reuse ? "" : $("n-carpeta").value === NUEVA_C ? $("n-carpeta-nueva").value.trim() : $("n-carpeta").value, video: reuse ? "" : ruta, enlace: reuse || ruta ? "" : $("enlace").value.trim(), solo_audio: $("solo-audio").checked, navegador: $("navegador").value, transcripcion: reuse ? "" : rutaTr, nivel: $("nivel").value, calidad: $("calidad").value, asr: reuse ? reuse.asr : "calidad", reuse: reuse?.id,
  hablantes: $("hablantes").checked, gpu: $("usar-gpu").checked, nombres: $("nombres").value, plantilla: $("plantilla").value, idioma: $("idioma").value, habla: reuse ? "" : $("habla").value, ...paramsSimple()});
$("form").onsubmit = async e => {
  e.preventDefault();
  if (!reuse && !ruta && !rutaTr && !$("enlace").value.trim()) { $("form-err").textContent = "Elige un vídeo, un audio, un enlace o una transcripción"; return; }
  try {
    let dest = reuse ? "" : $("n-carpeta").value;
    if (dest === NUEVA_C) { dest = $("n-carpeta-nueva").value.trim(); if (!dest) { $("form-err").textContent = "Escribe el nombre de la " + nm("carpeta").toLowerCase() + " nueva"; return; } await post("/api/carpeta", {nuevo: dest}); }
    const r = await post("/api/generar", params());
    if (!reuse) { setRuta(""); setTr(""); $("enlace").value = ""; $("enlace").oninput(); }
    $("form-err").textContent = ""; vista("cola"); sondear();
  } catch (err) { $("form-err").textContent = err.message; }
};

// ---- cola de trabajos ----
const ACT = ["pendiente", "marcha"], KIND = {acta: "Generar documento", fondo: "Búsqueda a fondo", condensar: "Vídeo condensado", seguimiento: "Seguimiento de pendientes", estado: "Resumen del estado", comparar: "Resumen de diferencias"};
let cola = {n: 0, items: []}, vistos = new Set(), colaKey = "";
const nombreDe = e => (e.mid && todas.find(m => m.id === e.mid)?.label) || e.video;
const minutos = s => s > 90 ? "unos " + Math.round(s / 60) + " min" : "unos " + s + " s";
const titCola = e => (e.kind === "acta" ? "Generar " + (e.doc || "documento") : KIND[e.kind]) + " · " + nombreDe(e);
async function sondear() {
  const c = await api("/api/cola").catch(() => null); if (!c) return;
  const act = new Set(c.items.filter(e => ACT.includes(e.state)).map(e => e.id));
  const fin = c.items.filter(e => vistos.has(e.id) && !act.has(e.id));
  vistos = act; cola = c; corriendo = c.n > 0;
  const k = c.items.map(e => e.id + e.state).join();
  if (fin.length) {  // algo terminó: refrescar lista y, si es la reunión abierta, su página
    carpetaTrasCola(fin); await cargarLista();
    if (vistaAct === "res" && fin.some(e => e.state === "hecho" && e.mid === cur.id)) await abrir(cur.id, ver, true);
  } else if (k !== colaKey && vistaAct === "home") pintarHome();
  pintarCola(k); pintarPill();
}
function pintarPill() {
  const r = cola.items.find(e => e.state === "marcha"), n = cola.n;
  $("cola-mini").hidden = !r; if (r) $("cola-mini").firstChild.style.width = Math.round(r.frac * 100) + "%";
  $("cola-txt").textContent = n ? " · " + (r ? "1 de " + n : n + " en espera") + (r && r.eta != null ? " · " + minutos(r.eta) : "") : "";
  $("b-cola").setAttribute("aria-label", "Cola de trabajos" + (n ? ", " + n : ""));
  if (vistaAct === "home") { const c = document.querySelector("#side [data-cola]"); if (c) c.textContent = n || ""; }
}
function pintarCola(k) {
  if (k !== colaKey) {
    colaKey = k; const it = cola.items, pend = it.filter(e => e.state === "pendiente");
    const bt = (e, txt, url, extra, lbl) => { const x = el("button", {className: "sec sm", textContent: txt, ariaLabel: lbl || txt}); x.onclick = fallo(async () => { x.disabled = true; await post(url, {id: e.id, ...extra}); await sondear(); }); return x; };
    const ab = e => { const o = el("button", {className: "sec sm", textContent: "Abrir"}); o.onclick = fallo(() => abrir(e.result.id, e.result.acta)); return o; };
    const card = (t, ...kids) => el("section", {className: "card"}, el("h2", {textContent: t}), ...kids);
    const run = it.filter(e => e.state === "marcha").map(e => el("section", {className: "card curso"},
      el("div", {className: "q-it"}, el("div", {className: "n"}, el("div", {className: "k", textContent: "En curso"}), el("h3", {textContent: titCola(e)}), el("div", {className: "d", id: "q-msg"})),
        el("div", {className: "acc"}, bt(e, "Cancelar", "/api/cola/cancelar"))),
      el("div", {className: "bar", role: "progressbar", ariaLabel: "Progreso"}, el("div", {id: "q-bar"})), el("p", {className: "muted", id: "q-eta", style: "margin:8px 0 0"}),
      // Gancho: etapas del procesado (Audio, Transcripción, Capturas, Resumen…) cuando el proceso las exponga
      el("div", {id: "q-etapas", hidden: true})));
    const esp = pend.map((e, i) => el("div", {className: "q-it"}, el("span", {className: "num", textContent: i + 1}),
      el("div", {className: "n"}, el("b", {textContent: titCola(e)}), el("div", {className: "d", textContent: "En espera (" + (i + 1) + " de " + pend.length + ")"})),
      el("div", {className: "acc"}, ...(simple() ? [] : [bt(e, "↑", "/api/cola/mover", {d: -1}, "Subir"), bt(e, "↓", "/api/cola/mover", {d: 1}, "Bajar")]), bt(e, "Quitar", "/api/cola/cancelar"))));
    const mal = it.filter(e => e.state === "error" || e.state === "interrumpido").map(e => el("div", {className: "q-it"},
      el("div", {className: "n"}, el("b", {textContent: titCola(e)}), el("div", {className: "d err", textContent: (e.state === "interrumpido" ? "Interrumpido: " : "Ha fallado: ") + (e.error || "")})),
      el("div", {className: "acc"}, bt(e, "Reintentar", "/api/cola/reintentar"), bt(e, "Quitar", "/api/cola/quitar"))));
    const hec = it.filter(e => e.state === "hecho" || e.state === "cancelado").reverse().map(e => el("div", {className: "q-it"},
      el("div", {className: "n"}, el("b", {textContent: titCola(e)}), el("div", {className: "d", textContent: e.state === "hecho" ? "Terminado" : "Cancelado"})),
      el("div", {className: "acc"}, ...(e.state === "hecho" && e.result?.id ? [ab(e)] : []), bt(e, "Quitar", "/api/cola/quitar"))));
    const lim = el("button", {className: "sec sm", textContent: "Limpiar", onclick: fallo(async () => { for (const e of it.filter(e => !ACT.includes(e.state) && e.state !== "error" && e.state !== "interrumpido")) await post("/api/cola/quitar", {id: e.id}); await sondear(); })});
    $("q-lista").replaceChildren(...run, ...(pend.length ? [card("En espera · " + pend.length, ...esp)] : []),
      ...(mal.length ? [Object.assign(card("Necesita tu ayuda · " + mal.length, ...mal), {className: "card ayuda"})] : []),
      ...(hec.length ? [card("Terminados · " + hec.length, ...hec, el("div", {className: "row", style: "margin-top:10px"}, lim))] : []),
      ...(!it.length ? [el("div", {className: "card vacio", textContent: "No hay trabajos. Crea un documento con «" + nm("nuevo_boton") + "»."})] : []));
    $("q-sub").textContent = pend.length || it.some(e => e.state === "marcha") ? (it.some(e => e.state === "marcha") ? "1 en curso" : "") + (pend.length ? (it.some(e => e.state === "marcha") ? " · " : "") + pend.length + " en espera" : "") + ". Puedes cerrar esta ventana de trabajo y seguir usando la aplicación." : "Se procesa un trabajo a la vez; el resto espera su turno.";
  }
  const r = cola.items.find(e => e.state === "marcha");
  if (r && $("q-bar")) {
    $("q-msg").textContent = r.msg; $("q-bar").style.width = Math.round(r.frac * 100) + "%";
    $("q-eta").textContent = Math.round(r.frac * 100) + " %" + (r.eta != null ? " · quedan " + minutos(r.eta) : "");
  }
  const ep = $("en-proc-bar"); if (r && ep) { ep.style.width = Math.round(r.frac * 100) + "%"; $("en-proc-eta").textContent = r.msg + (r.eta != null ? " · quedan " + minutos(r.eta) : ""); }
}

// ---- reuniones y carpetas ----
// fsel: undefined = inicio, null = todos los documentos, "" = sin carpeta, otro = esa carpeta
let cur, ver, tabAct = "p-acta", todas = [], carpetas = [], fsel, desde, RES = {};
const fallo = f => (...a) => f(...a).catch(err => alert(err.message));
const refrescarTodo = async () => { await cargarLista(); if (vistaAct === "res") await abrir(cur.id, ver, true); };
// formulario en la propia página (sin prompt/confirm): campo opcional + botón + Cancelar; Esc cancela
function enLinea(donde, {valor, lista, texto, boton = "Guardar"}, hecho) {
  document.querySelector("form.inline-f")?.remove();
  const f = el("form", {className: "inline-f row wrap"}), c = el("button", {type: "button", className: "sec", textContent: "Cancelar"});
  const i = valor != null ? el("input", {value: valor, ariaLabel: texto, style: "flex:1 1 220px"}) : null;
  if (i && lista?.length) { i.setAttribute("list", "dl-carpetas"); f.append(el("datalist", {id: "dl-carpetas"}, ...lista.map(v => el("option", {value: v})))); }
  f.append(el("span", {textContent: texto, style: "flex:1 1 100%"}), ...(i ? [i] : []), el("button", {className: "pri", textContent: boton}), c);
  c.onclick = () => f.remove();
  f.onkeydown = e => { if (e.key === "Escape") f.remove(); };
  f.onsubmit = e => { e.preventDefault(); fallo(async () => { await hecho(i ? i.value.trim() : ""); f.remove(); })(); };
  donde.append(f); (i || c).focus(); i?.select();
}
const renombrar = (m, donde) => enLinea(donde, {valor: m.nombre || m.label, texto: "Nombre (vacío = el original)"},
  async n => { await post("/api/meta", {id: m.id, nombre: n}); await refrescarTodo(); });
const mover = (m, donde) => enLinea(donde, {valor: m.carpeta || "", lista: carpetas, texto: cap(nm("carpeta").toLowerCase()) + " (nueva o existente; vacío = " + sinC().toLowerCase() + ")", boton: "Mover"},
  async c => { await post("/api/meta", {id: m.id, carpeta: c}); await refrescarTodo(); });
const carpetaOp = (nombre, borrar, donde) => enLinea(donde, borrar ? {texto: "Se quita «" + nombre + "»: los " + pl(nm("documento")) + " pasan a «" + sinC() + "» y no se borran.", boton: "Quitar"}
  : {valor: nombre, texto: "Nuevo nombre"}, async nuevo => {
    if (!borrar && (!nuevo || nuevo === nombre)) return;
    await post("/api/carpeta", {nombre, nuevo}); if (fsel === nombre) fsel = borrar ? null : nuevo; await refrescarTodo();
  });
const unicas = ms => { const v = new Set(); return ms.filter(m => !v.has(m.id) && v.add(m.id)); };
async function cargarLista() {
  [todas, carpetas, CP, CE, ESTILOS, RES] = await Promise.all([api("/api/meetings").then(ms => unicas(ms).filter(m => m.actas)), api("/api/carpetas"), api("/api/carpetas/plantillas"),
    api("/api/carpetas/estilos").catch(() => ({})), api("/api/estilos").catch(() => []), api("/api/carpetas/resumen").catch(() => ({})), PL.length ? null : cargarPlant()]);
  if (fsel && !carpetas.includes(fsel)) fsel = undefined;
  pintarHome();
}
const plural = n => n + " " + (n === 1 ? nm("documento") : pl(nm("documento")));
const fechaC = t => new Date(t * 1000).toLocaleDateString("es", {day: "numeric", month: "short"});
function pintarSide() {
  const cnt = c => todas.filter(m => c === null || (m.carpeta || "") === c).length, sin = todas.some(m => !m.carpeta);
  const item = (txt, act, f, n, extra = {}) => el("button", {className: "nav" + (extra.m ? " m" : ""), "aria-current": act ? "page" : "false", onclick: f}, el("span", {textContent: txt}), el("span", {className: "c" + (extra.a ? " a" : ""), textContent: n ?? ""}));
  const cl = item("Cola", false, () => { vista("cola"); sondear(); }, cola.n || "", {a: 1}); cl.lastChild.setAttribute("data-cola", "");
  $("side").replaceChildren(item("Inicio", fsel === undefined, irInicio), item(GR.activa ? "● Grabando…" : "● Grabar reunión", false, () => grabarAbrir(), "", {m: 1}), item(cap(pl(nm("documento"))) , fsel === null, () => { fsel = null; pintarHome(); }, cnt(null)), cl,
    el("div", {className: "t", textContent: cap(pl(nm("carpeta")))}),
    ...carpetas.map(c => item(c, fsel === c, () => { fsel = c; pintarHome(); }, cnt(c))), ...(sin || fsel === "" ? [item(sinC(), fsel === "", () => { fsel = ""; pintarHome(); }, cnt(""), {m: 1})] : []),
    item("+ " + cap(nm("carpeta")) + " nuevo", false, nuevaCarpeta, "", {m: 1}), el("hr"),
    el("a", {className: "nav m", href: "#/ajustes/plantillas"}, el("span", {textContent: "Plantillas"})), el("a", {className: "nav m", href: "#/ajustes/general"}, el("span", {textContent: "Ajustes"})));
}
const nuevaCarpeta = () => enLinea($("ed-home"), {valor: "", texto: "Nombre de la " + nm("carpeta").toLowerCase() + " nueva", boton: "Crear"}, async n => { if (!n) return; await post("/api/carpeta", {nuevo: n}); fsel = n; await cargarLista(); });
function pintarHome() {
  pintarSide();
  const ini = fsel === undefined, act = cola.items.filter(e => ACT.includes(e.state)), est = e => e.state === "marcha" ? "Generando" : "En cola (" + (act.indexOf(e) + 1) + "/" + act.length + ")";
  $("h-inicio").hidden = !ini; $("f-cab").hidden = ini; $("proys-w").hidden = !ini;
  if (ini) {
    $("h-tit").textContent = "Inicio"; $("h-sub").textContent = todas.length ? "" : "Todavía no hay nada. Pulsa «" + nm("nuevo_boton") + "» para crear tu primer " + nm("documento") + " o «Importar» para abrir uno exportado.";
    $("proys-t").textContent = cap(pl(nm("carpeta")));
    const ult = c => todas.filter(m => (m.carpeta || "") === c).reduce((a, m) => Math.max(a, m.mtime), 0);
    const card = c => { const n = todas.filter(m => (m.carpeta || "") === c).length, r = RES[c] || {}, u = Math.max(ult(c), r.ultima || 0);
      return el("button", {className: "proy", onclick: () => { fsel = c; pintarHome(); }}, el("b", {textContent: c || sinC()}),
        el("small", {textContent: plural(n) + (u ? " · última actividad " + fechaC(u) : "") + (CP[c] && PL.length ? " · " + plantDe(CP[c]).nombre : "")}),
        ...(r.pend || r.sug ? [el("small", {className: "f-card-p"}, el("b", {textContent: (r.pend || 0) + (r.pend === 1 ? " pendiente" : " pendientes")}), r.sug ? " · " + r.sug + " por revisar" : "")] : [])); };
    const nueva = el("button", {className: "proy nueva", textContent: "+ " + cap(nm("carpeta")) + " nuevo", onclick: nuevaCarpeta});
    $("proys").replaceChildren(...carpetas.map(card), ...(todas.some(m => !m.carpeta) && carpetas.length ? [card("")] : []), nueva);
    const r = act.find(e => e.state === "marcha");
    $("en-proc").replaceChildren(...(act.length ? [el("div", {className: "en-proc"},
      el("div", {className: "r"}, el("strong", {textContent: r ? "Generando · " + nombreDe(r) : "En cola"}), el("span", {className: "muted", textContent: act.length > 1 ? (act.length - (r ? 1 : 0)) + " más en espera" : ""})),
      ...(r ? [el("div", {className: "bar", role: "progressbar", ariaLabel: "Progreso"}, el("div", {id: "en-proc-bar"}))] : []),
      el("div", {className: "d muted"}, el("span", {id: "en-proc-eta"}), r ? " · " : "", el("a", {href: "#", textContent: "Ver cola", onclick: e => { e.preventDefault(); vista("cola"); sondear(); }})))] : []));
    pintarCola(colaKey);
  } else {
    const c = fsel; $("ftit").textContent = c === null ? cap(pl(nm("documento"))) : c === "" ? sinC() : c;
    $("fsub").textContent = plural(todas.filter(m => c === null || (m.carpeta || "") === c).length);
    for (const id of ["f-preguntar", "f-ren", "f-quitar", "f-plant"]) $(id).hidden = !c;
    $("f-estilo").hidden = !c || !ESTILOS.length;
    if (c && ESTILOS.length) { $("f-estilo").replaceChildren(new Option("Estilo por defecto: ninguno", ""), ...ESTILOS.map(e => new Option("Estilo: " + e.nombre, e.id))); $("f-estilo").value = CE[c] || ""; }
    $("f-plant-l").hidden = !c;
    if (c) { $("f-plant").replaceChildren(...PL.map(t => new Option("Tipo por defecto: " + t.nombre, t.id))); $("f-plant").value = CP[c] || "acta"; }
  }
  carpetaVista(!ini && fsel ? fsel : null);
  const ms = todas.filter(m => ini || fsel === null || (m.carpeta || "") === fsel).slice(0, ini ? 8 : 1e9);
  $("docs-t").textContent = ini ? "Documentos recientes" : fsel === null ? "Todos" : "Documentos";
  const nuevas = ini || fsel === null || fsel === "" ? act.filter(e => e.kind === "acta" && !e.mid) : [];
  const fila = m => {
    const e = act.find(e => e.mid === m.id), f = fechaC(m.mtime);
    return el("tr", {className: "f"}, el("td", {}, el("button", {className: "doc-l", textContent: m.label, onclick: fallo(() => abrir(m.id))})), el("td", {textContent: m.carpeta || ""}), el("td", {textContent: f}),
      el("td", {textContent: m.dur ? Math.round(m.dur / 60) + " min" : ""}), el("td", {textContent: m.actas > 1 ? m.actas + " versiones" : ""}),
      el("td", {}, ...(e ? [el("span", {className: "badge acc", textContent: est(e)})] : [])));
  };
  $("lista").replaceChildren(...nuevas.map(e => el("tr", {}, el("td", {textContent: e.video}), el("td"), el("td"), el("td"), el("td"), el("td", {}, el("span", {className: "badge acc", textContent: est(e)})))), ...ms.map(fila));
  $("vacio").hidden = !!(ms.length || nuevas.length); $("tabla").firstChild.hidden = !$("vacio").hidden;
  $("vacio").textContent = "Aún no hay " + pl(nm("documento")) + (fsel ? " en «" + fsel + "»" : "") + ".";
  document.querySelectorAll("#tabla th")[1].hidden = false;
}
$("f-ren").onclick = () => carpetaOp(fsel, false, $("ed-carpeta"));
$("f-quitar").onclick = () => carpetaOp(fsel, true, $("ed-carpeta"));
$("f-preguntar").onclick = () => { $("preg-tit").textContent = "Preguntar · " + fsel; $("p-fcarpeta").append($("qpanel")); setQ("c:" + fsel); vista("preg"); };
$("f-estilo").onchange = fallo(async () => { await post("/api/carpeta", {nombre: fsel, estilo: $("f-estilo").value}); CE = await api("/api/carpetas/estilos"); aviso("Estilo guardado"); });
$("f-plant").onchange = fallo(async () => { await post("/api/carpeta", {nombre: fsel, plantilla: $("f-plant").value === "acta" ? "" : $("f-plant").value}); CP = await api("/api/carpetas/plantillas"); aviso("Tipo por defecto guardado"); });

// ---- página de un documento ----
const cap = s => s[0].toUpperCase() + s.slice(1);
const defecto = a => [a.plantilla, a.idioma && "en " + (IDI[a.idioma] || a.idioma), cap(a.nivel), (nivelInfo(a.calidad)?.nombre || "Rápida") + (nivelInfo(a.calidad)?.pers ? " · " + nivelInfo(a.calidad).modelo : ""), a.fondo && "a fondo", a.name.split("_").slice(3).filter(x => !(x in {alta:1, alta9:1, muyalta:1, maxima:1} || /^p[0-9a-f]{6}$/.test(x) || /^[pi]-/.test(x))).join(" ")].filter(Boolean).join(" · ");
const etiqueta = a => cur.versiones[a.name] || defecto(a);
async function abrir(id, acta, quedar) {
  cur = await api("/api/meeting/" + id);
  cur.m = todas.find(m => m.id === id) || {id, label: cur.nombre || id, nombre: cur.nombre, carpeta: cur.carpeta};
  if (simple()) { const u = cur.actas.reduce((x, y) => y.mtime > x.mtime ? y : x); if (!acta || !cur.actas.some(a => a.name === acta)) acta = u.name; }
  ver = (cur.actas.find(a => a.name === acta) || cur.actas.find(a => a.name === ver && quedar) || cur.actas[0]).name;
  if (!quedar) desde = fsel;
  $("cab-carpeta").textContent = desde === undefined ? "Inicio" : desde === null ? cap(pl(nm("documento"))) : desde || cur.carpeta || sinC(); $("cab-titulo").textContent = cur.m.label;
  const au = cur.audio; $("t-video").hidden = !cur.video; $("t-video").textContent = au ? "Audio" : "Vídeo";
  $("cond-t").textContent = au ? "Audio condensado" : "Vídeo condensado"; $("condensar").textContent = au ? "Generar audio condensado" : "Generar vídeo condensado";
  if (cur.video) mpCargar(cur.videourl, cur.m.label, !!au); else mpCerrar();
  vista("res"); document.title = cur.m.label + " · Actas"; pintarVers(); cambiarActa(); pintarConds(); tab(quedar && !(tabAct === "p-video" && !cur.video) ? tabAct : "p-acta");
}
const tab = p => {
  tabAct = p;
  document.querySelectorAll("#mtabs button").forEach(b => { b.setAttribute("aria-selected", b.dataset.p === p); $(b.dataset.p).hidden = b.dataset.p !== p; });
  ubicar();
  if (p === "p-video" && typeof notasRes === "function") notasRes();
  if (p === "p-preg") { $("p-preg").append($("qpanel")); const a = cur.actas.find(a => a.name === ver); setQ(cur.id + "|" + a.asr); $("preguntar-b").disabled = $("pregunta").disabled = a.sin; $("pregunta").placeholder = a.sin ? "Documento importado sin transcripción: no se puede preguntar" : "Escribe tu pregunta…"; }
};
document.querySelectorAll("#mtabs button").forEach(b => b.onclick = () => tab(b.dataset.p));
function pintarVers() {
  const a = cur.actas.find(a => a.name === ver), ren = el("button", {className: "sec", textContent: "✎", ariaLabel: "Renombrar esta versión", title: "Renombrar esta versión", style: "min-height:40px"}), otra = el("button", {className: "sec", textContent: "+ Otra versión", style: "min-height:40px;font-size:14px"});
  ren.onclick = () => enLinea($("ed-res"), {valor: etiqueta(a), texto: "Nombre de la versión (vacío = el original)"}, async n => {
    await post("/api/meta", {id: cur.id, version: ver, vnombre: n === defecto(a) ? "" : n}); cur.versiones = (await api("/api/meeting/" + cur.id)).versiones; pintarVers();
  });
  otra.onclick = () => formNuevo(cur.m, a);
  $("vers").replaceChildren(...(simple() ? [] : [el("div", {className: "seg", role: "tablist"}, ...cur.actas.map(x => el("button", {role: "tab", textContent: etiqueta(x) + (x.editado ? " · editado" : ""), "aria-selected": x.name === ver, onclick: () => { ver = x.name; pintarVers(); cambiarActa(); }})))]), ...(simple() ? [] : [ren]), otra);
}
function cambiarActa() {
  const a = cur.actas.find(a => a.name === ver), nd = a.doc || "acta"; editando = false; pintarAcciones(a);
  $("t-acta").textContent = cap(nd); $("dl-zip").textContent = "Descargar (.zip)"; $("fondo").hidden = !!a.plantilla;
  $("cab-meta").replaceChildren(...[cur.m.dur ? Math.round(cur.m.dur / 60) + " min" : "", cap(nd), a.idioma && (IDI[a.idioma] || a.idioma), cap(a.nivel), nivelInfo(a.calidad)?.nombre, a.editado && "editado", cur.carpeta].filter(Boolean).map(t => el("span", {textContent: t})));
  $("acta-frame").src = `/api/vista/${cur.id}/${a.name}?v=` + Date.now();  // desde los datos: lleva data-p (marcas de dudas) y lo editado $("fondo").disabled = a.fondo; $("fondo").textContent = a.fondo ? "Búsqueda a fondo hecha" : "Buscar todas a fondo"; $("dl-zip").hidden = !a.zip; if (a.zip) { $("dl-zip").href = a.zip; $("dl-zip").download = cur.nombre ? cur.nombre + ".zip" : ""; }
  $("dl-vid").hidden = !cur.video; $("dl-vid").href = "/api/zipvideo/" + cur.id + "/" + a.name; $("dl-vid").textContent = "Descargar con " + (cur.audio ? "audio" : "vídeo") + " (" + cur.videomb + " MB)";
  const imp = cur.importadas[a.asr];
  $("imp-info").textContent = imp ? "Transcripción importada: " + imp.fuente + " (" + imp.formato + ", " + imp.segmentos + " segmentos, " + imp.hablantes.length + " hablantes)" +
    (cur.video ? (imp.aviso ? "" : " · desfase aplicado " + (imp.desfase >= 0 ? "+" : "") + Math.round(imp.desfase) + " s") : (cur.audio ? " · solo audio: sin capturas" : " · sin vídeo: sin capturas ni reproductor")) + (imp.aviso ? ". " + imp.aviso : "") : "";
  $("imp-info").className = imp && imp.aviso ? "err" : "muted"; $("imp-info").hidden = !imp; $("cond").hidden = !cur.video;
  zipAnon(); const rec = cur.recomendado[a.asr]; if (rec) { $("pct").value = rec; $("pct-o").textContent = rec; $("rec").textContent = "Recomendado para esta reunión: " + rec + " %. Primero los silencios largos, después lo menos importante."; }
}
$("fondo").onclick = async () => {
  const a = cur.actas.find(a => a.name === ver);
  try { await post("/api/fondo", {id: cur.id, nivel: a.nivel, asr: a.asr, calidad: a.calidad, gpu: $("usar-gpu").checked}); aviso("Añadido a la cola"); sondear(); }
  catch (err) { alert(err.message); }
};
$("condensar").onclick = async () => {
  try { await post("/api/condensar", {id: cur.id, asr: cur.actas.find(a => a.name === ver).asr, pct: +$("pct").value}); aviso("Añadido a la cola"); sondear(); }
  catch (err) { alert(err.message); }
};
$("m-ren").onclick = () => renombrar(cur.m, $("ed-res"));
$("m-mover").onclick = () => mover(cur.m, $("ed-res"));
$("pct").oninput = () => $("pct-o").textContent = $("pct").value;
$("volver").onclick = e => {
  e.preventDefault(); $("acta-frame").src = "about:blank"; mpCerrar(); $("cvideo").pause();
  fsel = typeof desde === "string" && desde && !carpetas.includes(desde) ? undefined : desde; ir("home");
};
function pintarConds() {
  $("cvideo").hidden = true; $("cvideo").removeAttribute("src");
  $("conds").replaceChildren(...cur.condensados.map(c => {
    const vb = el("button", {className: "sec sm", textContent: "Ver"}); vb.onclick = () => { $("cvideo").src = c.url; $("cvideo").hidden = false; $("cvideo").play(); };
    return el("li", {}, el("span", {className: "n", textContent: c.name}), vb, el("a", {className: "btn sec sm", href: c.url, download: c.name, textContent: "Descargar"}));
  }));
}

// ---- preguntar (panel único #qpanel: se monta en la pestaña del documento o en la vista de carpeta) ----
let qsel = "";
function setQ(sel) {  // sel: "id|asr" o "c:carpeta"
  if (sel !== qsel) $("respuestas").replaceChildren();
  qsel = sel; $("qpanel").hidden = false;
}
// v: undefined = vídeo del selector; en carpetas, la url del vídeo de esa reunión (null = reunión sin vídeo); n: nombre de la reunión
const ts = (t, v, n) => el("a", {className: "ts", href: "#", textContent: mmss(t) + (n ? " · " + n : ""), onclick: e => { e.preventDefault(); if (v !== null) mpSeek(t, v, n); }});
$("qform").onsubmit = async e => {
  e.preventDefault(); const q = $("pregunta").value.trim(); if (!q || !qsel) return;
  $("preguntar-b").disabled = true;
  const box = el("div", {className: "card resp"}, el("h3", {textContent: q})), cuerpo = el("div"), frag = el("details", {open: true}, el("summary", {textContent: "Fragmentos recuperados"}));
  box.append(cuerpo, frag); $("respuestas").prepend(box);
  const estado = el("p", {textContent: "Buscando en la reunión…"}); cuerpo.append(estado);
  try {
    const r = await fetch("/api/preguntar", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({sel: qsel, q, gpu: $("usar-gpu").checked})});
    if (!r.ok) throw new Error(det(await r.json().catch(() => ({})), r.statusText));
    const rd = r.body.getReader(), dec = new TextDecoder(); let buf = "";
    for (;;) {
      const {done, value} = await rd.read(); if (done) break;
      buf += dec.decode(value, {stream: true}); const lines = buf.split("\n"); buf = lines.pop();
      for (const l of lines.filter(Boolean)) evento(JSON.parse(l), cuerpo, frag, estado);
    }
  } catch (err) { cuerpo.append(el("p", {className: "err", textContent: err.message})); }
  estado.remove(); frag.open = false; $("preguntar-b").disabled = false; $("pregunta").value = "";
};
function evento(ev, cuerpo, frag, estado) {
  if (ev.k === "arranque") estado.textContent = "Arrancando el modelo de lenguaje…";
  else if (ev.k === "candidatos") { estado.textContent = "Buscando en la reunión…"; frag.append(el("ol", {}, ...ev.items.map(i => el("li", {}, ts(i.t, i.v, i.n), " " + i.text)))); }
  else if (ev.k === "frase") {
    const quote = el("blockquote"); ev.cita.forEach((c, n) => quote.append(...(n ? [el("br")] : []), el("span", {className: c.main ? "" : "o"}, ts(c.t, c.v, c.n), " " + c.text)));
    cuerpo.insertBefore(el("p", ev.kind === "deduce" ? {style: "font-style:italic"} : {}, ...(ev.n ? [el("b", {textContent: ev.n + ": "})] : []), ev.ok ? ev.text : "Se dijo: «" + ev.text + "» ", ev.ok ? "" : el("small", {textContent: "(texto literal: la frase del modelo no se pudo verificar)"}), " ", ts(ev.t, ev.v, ev.n), ...(ev.mas || []).flatMap(m => [" ", ts(m.t, m.v, m.n)]),
      el("details", {}, el("summary", {textContent: "cita literal"}), quote)), estado);
  }
  else if (ev.k === "pendientes") {  // pregunta sobre pendientes: lista determinista de los datos de la carpeta, con enlaces al minuto
    const T = {es: ["Pendientes abiertos", "Pendiente de", "No hay pendientes abiertos", "plazo"], en: ["Open items", "Pending for", "No open items", "due"], fr: ["Points ouverts", "En attente pour", "Aucun point ouvert", "échéance"],
      de: ["Offene Punkte", "Offen für", "Keine offenen Punkte", "Frist"], pt: ["Pendentes abertos", "Pendente de", "Nenhum pendente aberto", "prazo"], it: ["Aperti", "In sospeso per", "Nessuna attività aperta", "scadenza"]}[ev.en] || ["Open items", "Pending for", "No open items", "due"];
    cuerpo.insertBefore(el("div", {}, el("p", {}, el("b", {textContent: ev.items.length ? (ev.resp ? T[1] + " " + ev.resp : T[0]) + " · " + ev.items.length : T[2]})),
      el("ul", {className: "f-lst"}, ...ev.items.map(p => el("li", {}, p.texto + (ev.resp ? "" : p.resp ? " — " + p.resp : "") + (p.plazo ? " · " + T[3] + ": " + p.plazo : "") + " ", p.mid ? fLink(p) : "")))), estado);
  }
  else if (ev.k === "aviso") cuerpo.insertBefore(el("p", {}, el("small", {textContent: ev.text})), estado);
  else if (ev.k === "nada") cuerpo.insertBefore(el("p", {}, el("b", {textContent: ev.text})), estado);
  else if (ev.k === "error") cuerpo.append(el("p", {className: "err", textContent: ev.text}));
}

// ---- importar un documento exportado (.zip) ----
$("b-importar").onclick = async () => {
  $("b-importar").disabled = true;
  try { const r = (await post("/api/pick", {tipo: "zip"})).path; if (r) { const m = await post("/api/importar", {path: r}); await cargarLista(); aviso("Documento importado"); abrir(m.id); } }
  catch (e) { aviso(e.message); } finally { $("b-importar").disabled = false; }
};

// ---- selector de plantilla («Tipo») y de idioma del formulario ----
async function cargarPlant() { const r = await api("/api/plantillas"); PL = r.plantillas; DEF = r.escala; IDI = r.idiomas; SERIE = r.serie; idiomasForm(); }
const plantDe = id => PL.find(t => t.id === id) || PL[0];
const docDe = id => plantDe(id)?.documento?.singular || "documento";
function idiomasForm() {
  const v = $("idioma").value;
  $("idioma").replaceChildren(new Option("Según la plantilla", ""), ...Object.entries(IDI).filter(([k]) => k !== "reunión").map(([k, n]) => new Option(cap(n), k)));
  $("idioma").value = v;
}
function plantForm(id) {  // selector «Tipo»: en modo simple, solo los perfiles de uso elegidos (+ el de la carpeta); en avanzado, todos
  const ok = simple() ? new Set([...AJ.perfil_uso, id]) : null, l = PL.filter(t => !ok || ok.has(t.id));
  $("plantilla").replaceChildren(...l.map(t => new Option(t.nombre, t.id))); $("plantilla").value = plantDe(id)?.id || "acta"; $("plantilla").onchange();
}
$("plantilla").onchange = () => {
  const t = plantDe($("plantilla").value); if (!t) return;
  $("generar").textContent = "Generar " + t.documento.singular; $("info-plant").textContent = t.descripcion + (t.nube_permitida ? "" : " Solo en este equipo.");
  $("idioma").options[0].textContent = "Según la plantilla (" + (IDI[t.idioma_acta] || t.idioma_acta) + ")"; $("idioma").onchange();
};
$("idioma").onchange = () => {  // aviso: fuera de es/en conviene un modelo mayor
  const t = plantDe($("plantilla").value), i = $("idioma").value || t?.idioma_acta || "reunión";
  $("hint-idioma").textContent = i === "eu" ? "Para euskera se recomienda la calidad Muy alta." : ["reunión", "es", "en"].includes(i) ? "" : "Para este idioma se recomienda Alta+ o superior.";
  $("hint-idioma").hidden = !$("hint-idioma").textContent;
};

// ---- arranque (lo llama el último script, cuando ya está todo definido) ----
function arranque() { cargarLista().then(() => { sondear(); plantForm("acta"); }).catch(() => {}); setInterval(sondear, 2000); }

// ---- reproductor flotante (único <video>: no se recrea al cambiar de pestaña, así no se corta) ----
const MP = () => $("mp"), VID = () => $("vvideo"), esAudio = u => /\.(mp3|m4a|wav|ogg|opus|flac|aac)$/i.test(u || "");
function mpCargar(url, titulo, audio) {
  const v = VID(), m = MP(); if (!v.src.endsWith(url)) v.src = url;
  m.classList.toggle("audio", audio); $("vslot").classList.toggle("audio", audio); $("mp-t").textContent = titulo || "";
  $("mp-pip").hidden = audio || !document.pictureInPictureEnabled; m.hidden = false; m.classList.remove("min"); ubicar();
}
function mpCerrar() { VID().pause(); MP().hidden = true; if (document.pictureInPictureElement) document.exitPictureInPicture().catch(() => {}); }
function mpSeek(t, url, nombre) {
  const v = VID(), go = () => { v.currentTime = Math.floor(t); v.play().catch(() => {}); };
  if (url && !v.src.endsWith(url)) { mpCargar(url, nombre, esAudio(url)); v.addEventListener("loadedmetadata", go, {once: true}); v.src = url; }
  else { MP().hidden = false; MP().classList.remove("min"); ubicar(); go(); }
}
function ubicar() {  // en la pestaña Vídeo/Audio el reproductor se coloca grande sobre su hueco; en las demás flota abajo a la derecha
  const m = MP(), full = vistaAct === "res" && tabAct === "p-video" && !$("p-video").hidden;
  m.classList.toggle("full", full);
  if (full) { const r = $("vslot").getBoundingClientRect(); Object.assign(m.style, {left: r.left + scrollX + "px", top: r.top + scrollY + "px", width: r.width + "px"}); $("vslot").style.height = m.offsetHeight + "px"; }
  else { $("vslot").style.height = ""; if (!m.dataset.arrastrado) Object.assign(m.style, {left: "", top: "", width: ""}); }
}
addEventListener("resize", ubicar);
$("mp-x").onclick = mpCerrar;
$("mp-min").onclick = () => { MP().classList.toggle("min"); $("mp-min").setAttribute("aria-label", MP().classList.contains("min") ? "Restaurar" : "Minimizar"); };
$("mp-pip").onclick = () => (document.pictureInPictureElement ? document.exitPictureInPicture() : VID().requestPictureInPicture()).catch(e => aviso("No se pudo abrir imagen en imagen: " + e.message));
$("mp-bar").onpointerdown = e => {  // arrastrar (opcional) desde la barra
  const m = MP(); if (m.classList.contains("full") || e.target.closest("button")) return;
  const r = m.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top; $("mp-bar").setPointerCapture(e.pointerId);
  const mv = ev => { m.dataset.arrastrado = 1; Object.assign(m.style, {right: "auto", bottom: "auto", left: Math.max(0, Math.min(innerWidth - 60, ev.clientX - dx)) + "px", top: Math.max(0, Math.min(innerHeight - 40, ev.clientY - dy)) + "px"}); };
  const up = () => { $("mp-bar").removeEventListener("pointermove", mv); $("mp-bar").removeEventListener("pointerup", up); }; $("mp-bar").addEventListener("pointermove", mv); $("mp-bar").addEventListener("pointerup", up);
};
// el documento (iframe, mismo origen): su propio reproductor se oculta y sus marcas [mm:ss] mueven el de la app
$("acta-frame").onload = () => {
  let d; try { d = $("acta-frame").contentDocument; } catch { return; } if (!d || !d.body || d.location.href === "about:blank") return;
  d.head.append(Object.assign(d.createElement("style"), {textContent: "#side{display:none!important}main{padding-bottom:32px!important;display:block!important;max-width:960px!important}"}));
  d.addEventListener("click", e => {
    const a = e.target.closest("[data-t]"); if (!a || !cur?.video) return;
    e.preventDefault(); e.stopImmediatePropagation();
    if (d.getElementById("big")) d.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape"}));  // cierra el visor de capturas
    mpSeek(+a.dataset.t, cur.videourl, cur.m.label);
  }, true);
};

// ---- editar y exportar el documento (#acta-acciones es el gancho de la barra) ----
let editando = false;
const FMT = [["docx", "Word (.docx)"], ["pdf", "PDF"], ["md", "Markdown"], ["obsidian", "Obsidian (.zip)"], ["notion", "Notion (.zip)"], ["ics", "Calendario (.ics)"],
  ["csv_todoist", "Tareas · Todoist (.csv)"], ["csv_jira", "Tareas · Jira (.csv)"], ["srt", "Subtítulos (.srt)"], ["vtt", "Subtítulos (.vtt)"]];
async function descargar(fmt, extra = "") {
  const est = $("ex-est")?.value, q = "fmt=" + fmt + (est && est !== "auto" ? "&estilo=" + encodeURIComponent(est === "none" ? "" : est) : "") + extra;
  const r = await fetch(`/api/exportar/${cur.id}/${ver}?${q}`);
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    if (r.status === 409 && fmt === "pdf") { window.open(`/api/vista/${cur.id}/${ver}?print=1` + (/anon=1/.test(extra) ? "&anon=1" : "") + (/dudas=1/.test(extra) ? "&dudas=1" : "")); aviso(j.detail || "Usa Imprimir → Guardar como PDF"); return; }
    throw new Error(j.detail || r.statusText);
  }
  const nombre = decodeURIComponent((/filename\*=UTF-8''(.+)/.exec(r.headers.get("Content-Disposition") || "") || [])[1] || "documento." + fmt);
  const a = el("a", {href: URL.createObjectURL(await r.blob()), download: nombre}); document.body.append(a); a.click(); a.remove(); aviso("Descargado: " + nombre);
}
function pintarAcciones(a) {
  const box = $("acta-acciones"); box.hidden = false; box.style.display = "contents";
  if (editando) {
    box.replaceChildren(el("span", {className: "ed-bar"}, "Editando: haz clic en cualquier texto del documento.",
      el("button", {className: "pri sm", textContent: "Guardar", onclick: fallo(async () => {
        const c = $("acta-frame").contentWindow.cambios(); if (!Object.keys(c).length) { aviso("No hay cambios"); return; }
        await api(`/api/doc/${cur.id}/${ver}`, {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({cambios: c})});
        editando = false; await abrir(cur.id, ver, true); aviso("Cambios guardados"); })}),
      el("button", {className: "sec sm", textContent: "Descartar", onclick: () => { editando = false; cambiarActa(); }})));
    return;
  }
  const mas = el("div", {hidden: simple()}), ex = el("div", {className: "pop"}), item = (f, t, extra) => el("button", {type: "button", textContent: t, onclick: fallo(async () => { box.querySelector("details").open = false; await exportar(f, extra()); })});
  const hab = el("input", {type: "checkbox", id: "ex-hab"}), evt = el("input", {type: "checkbox", id: "ex-evt"});
  mas.append(el("div", {className: "t", textContent: "Más formatos"}), ...FMT.slice(2).map(([f, t]) => item(f, t, () => f === "srt" || f === "vtt" ? (hab.checked ? "&hablantes=1" : "") : f === "ics" && evt.checked ? "&evento=1" : "")),
    el("label", {className: "check", style: "font-size:14px"}, evt, "Calendario: como un solo evento"), el("label", {className: "check", style: "font-size:14px"}, hab, "Subtítulos: con quien habla"));
  ex.append(...(ESTILOS.length ? [el("div", {className: "t", textContent: "Estilo"}), (s => { s.append(new Option("El de la carpeta", "auto"), new Option("Sin estilo", "none"), ...ESTILOS.map(e => new Option(e.nombre, e.id))); return s; })(el("select", {id: "ex-est", ariaLabel: "Estilo de organización"}))] : []),
    el("div", {className: "t", textContent: "Exportar como"}), item("docx", FMT[0][1], () => ""), item("pdf", FMT[1][1], () => ""),
    el("div", {className: "t", textContent: "Opciones"}),
    el("label", {className: "check"}, el("input", {type: "checkbox", id: "ex-anon", checked: anonOn(), onchange: e => { anonSel = e.target.checked; zipAnon(); }}), "Anonimizar"),
    el("label", {className: "check"}, el("input", {type: "checkbox", id: "ex-dud"}), "Incluir marcas de dudas"),
    ...(simple() ? [el("button", {type: "button", className: "link", textContent: "Más…", style: "padding:0 12px", onclick: e => { mas.hidden = false; e.currentTarget.remove(); }})] : []), mas);
  box.replaceChildren(el("button", {className: "sec", textContent: "Correo", title: "Borrador de correo con el resumen y las tareas", onclick: abrirCorreo}), el("button", {className: "sec", textContent: "Editar", title: "Corregir el texto del documento", onclick: () => { editando = true; $("acta-frame").src = `/api/vista/${cur.id}/${ver}?editar=1`; pintarAcciones(a); }}),
    ...(a.editado ? [el("button", {className: "sec", textContent: "Restaurar original", onclick: fallo(async () => { if (!confirm("¿Volver al texto original? Se pierden tus ediciones de esta versión.")) return; await post(`/api/doc/${cur.id}/${ver}/restaurar`); await abrir(cur.id, ver, true); aviso("Original restaurado"); })})] : []),
    el("details", {className: "menu"}, el("summary", {textContent: "Exportar ▾"}), ex));
}
document.addEventListener("click", e => document.querySelectorAll("details.menu[open]").forEach(d => { if (!d.contains(e.target)) d.open = false; }));
