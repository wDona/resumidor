const $ = id => document.getElementById(id);
const api = (url, opt) => fetch(url, opt).then(async r => { if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText); return r.json(); });
const post = (url, body) => api(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body || {})});
const mmss = t => { t = Math.floor(t); const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60, p = n => String(n).padStart(2, "0"); return (h ? h + ":" + p(m) : p(m)) + ":" + p(s); };
const el = (tag, props = {}, ...kids) => { const e = document.createElement(tag); for (const k in props) k.startsWith("data-") ? e.setAttribute(k, props[k]) : e[k] = props[k]; e.append(...kids); return e; };
let corriendo = false;
addEventListener("beforeunload", e => { if (corriendo) { e.preventDefault(); e.returnValue = "Se está generando un acta; si cierras, se cancelará"; } });
setInterval(() => fetch("/api/latido", {method: "POST"}).catch(() => {}), 5000); fetch("/api/latido", {method: "POST"});

// ---- pestañas ----
document.querySelectorAll("nav button").forEach(b => b.onclick = () => {
  document.querySelectorAll("nav button").forEach(x => { x.setAttribute("aria-selected", x === b); $(x.dataset.tab).hidden = x !== b; });
  if (b.dataset.tab === "preguntar") cargarReuniones();
});
const vista = v => ["nuevo", "job", "res"].forEach(n => $("v-" + n).hidden = n !== v);

// ---- elegir vídeo y transcripción ----
let ruta = "", rutaTr = "", hablaTr = false;
const setRuta = p => { ruta = p; $("ruta").value = p; };
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
$("quitar-tr").onclick = () => { setTr(""); $("info-tr").textContent = "Sustituye a la transcripción automática; con vídeo se alinea sola. Sin vídeo, el acta no lleva capturas ni reproductor."; };
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
  const c = $("usar-gpu"), v = (() => { try { return localStorage.getItem("usar-gpu"); } catch { return null; } })();
  const gb = g.vram_mb ? `, ${Math.round(g.vram_mb / 1024)} GB` : "";
  c.disabled = !g.ok; c.checked = g.ok && (v === null ? g.default : v === "1");
  c.parentElement.title = "";
  $("info-gpu").textContent = !g.ok ? "GPU no encontrada o no válida" : (g.default ? "Se te recomienda usar la GPU" : "No se te recomienda usar la GPU") + ` (${g.name}${gb})`;
  const chat = () => { const [gem, why] = g[c.checked && g.ok ? "chat_gpu" : "chat_cpu"]; return `Chat: ${gem ? "gemma-4-E4B" : g.llm} (${why})`; };
  const ram = () => $("info-ram").textContent = `RAM: ${g.ram_gb || "?"} GB` + (g.ok && g.vram_mb ? ` · VRAM: ${Math.round(g.vram_mb / 1024)} GB (${g.name})` : "") + " · " + chat() + (g.ram_gb && g.ram_gb < 8 ? ". Poca RAM: el proceso puede ir muy lento o fallar" : "");
  ram();
  c.onchange = () => { ram(); try { localStorage.setItem("usar-gpu", c.checked ? "1" : "0"); } catch {} };
  const al = g.llm; $("calidad").options[0].textContent = `Rápida (${al})`; $("calidad").options[1].textContent = `Alta (${al}, 2 pasadas)`;
}).catch(() => {});
$("calidad").onchange = () => { $("aviso-alta").hidden = $("calidad").value !== "alta"; };

// ---- generar / condensar ----
const params = () => ({video: ruta, transcripcion: rutaTr, nivel: $("nivel").value, calidad: $("calidad").value, asr: "calidad", hablantes: $("hablantes").checked, gpu: $("usar-gpu").checked, nombres: $("nombres").value});
$("form").onsubmit = async e => {
  e.preventDefault();
  if (!ruta && !rutaTr) { $("subida").textContent = "Elige un vídeo o una transcripción"; return; }
  try { await post("/api/generar", params()); seguir(); } catch (err) { $("subida").textContent = err.message; }
};
$("fondo").onclick = async () => {
  const a = cur.actas.find(a => a.name === $("sel-acta").value);
  try { await post("/api/fondo", {id: cur.id, nivel: a.nivel, asr: a.asr, alta: a.alta, gpu: $("usar-gpu").checked}); seguir(); }
  catch (err) { alert(err.message); }
};
$("condensar").onclick = async () => {
  try { await post("/api/condensar", {id: cur.id, asr: $("sel-acta").selectedOptions[0].dataset.asr, pct: +$("pct").value}); seguir(); }
  catch (err) { alert(err.message); }
};
let timer;
function seguir() {
  clearInterval(timer); vista("job"); $("job-ok").hidden = true; $("job-err").textContent = "";
  const tick = async () => {
    const j = await api("/api/job").catch(() => null); if (!j) return;
    corriendo = j.state === "running";
    if (j.state === "running") {
      $("job-t").textContent = j.kind === "condensar" ? "Generando vídeo condensado" : j.kind === "fondo" ? "Buscando decisiones y tareas a fondo · " + (j.video || "") : "Generando acta · " + (j.video || "");
      $("job-msg").textContent = j.msg; $("job-bar").style.width = Math.round(j.frac * 100) + "%";
      $("job-eta").textContent = Math.round(j.frac * 100) + " %" + (j.eta != null ? " · quedan unos " + (j.eta > 90 ? Math.round(j.eta / 60) + " min" : j.eta + " s") : "");
      return;
    }
    clearInterval(timer);
    if (j.state === "done") { await abrir(j.result.id, j.result.acta); }
    else { $("job-t").textContent = "Ha fallado"; $("job-err").textContent = j.error || ""; $("job-ok").hidden = false; }
  };
  timer = setInterval(tick, 1500); tick();
}
$("job-ok").onclick = () => { vista("nuevo"); cargarLista(); };

// ---- reuniones previas y resultado ----
let cur;
const fallo = f => (...a) => f(...a).catch(err => alert(err.message));
const refrescarTodo = async () => { await cargarLista(); if (!$("preguntar").hidden) await cargarReuniones(); };
const renombrar = fallo(async m => { const n = prompt("Nombre de la reunión (vacío = el original)", m.nombre || m.label); if (n !== null) { await post("/api/meta", {id: m.id, nombre: n}); await refrescarTodo(); } });
const mover = fallo(async (m, ms) => {
  const ex = [...new Set(ms.map(x => x.carpeta).filter(Boolean))];
  const c = prompt("Carpeta (nueva o existente" + (ex.length ? ": " + ex.join(", ") : "") + "). Vacío = sin carpeta", m.carpeta);
  if (c !== null) { await post("/api/meta", {id: m.id, carpeta: c}); await refrescarTodo(); }
});
const carpetaOp = fallo(async (nombre, borrar) => {
  const nuevo = borrar ? "" : prompt("Nuevo nombre de la carpeta", nombre);
  if (nuevo === null || nuevo === nombre || (borrar && !confirm("Se quita la carpeta «" + nombre + "»; las reuniones pasan a «Sin carpeta» y no se borran."))) return;
  await post("/api/carpeta", {nombre, nuevo}); await refrescarTodo();
});
const unicas = ms => { const v = new Set(); return ms.filter(m => !v.has(m.id) && v.add(m.id)); };
async function cargarLista() {
  const ms = await api("/api/meetings"); const ul = $("lista"); ul.replaceChildren();
  const un = unicas(ms), g = {};
  un.forEach(m => (g[m.carpeta] ||= []).push(m));
  const fila = m => {
    const b = el("button", {className: "sec", textContent: "Abrir"}); b.onclick = () => abrir(m.id).catch(err => alert(err.message));
    const r = el("button", {className: "sec", textContent: "Renombrar"}); r.onclick = () => renombrar(m);
    const c = el("button", {className: "sec", textContent: "Carpeta"}); c.onclick = () => mover(m, un);
    return el("li", {}, el("div", {className: "n"}, el("div", {textContent: m.label}), el("div", {className: "d", textContent: new Date(m.mtime * 1000).toLocaleString("es")})), el("span", {}, b, " ", r, " ", c));
  };
  for (const k of [...Object.keys(g).filter(Boolean).sort(), ...(g[""] ? [""] : [])]) {
    const sm = el("summary", {textContent: (k ? "📁 " + k : "Sin carpeta") + " (" + g[k].length + ") "});
    if (k) {
      const r = el("button", {className: "sec", textContent: "Renombrar carpeta"}), d = el("button", {className: "sec", textContent: "Quitar carpeta"});
      r.onclick = e => { e.preventDefault(); carpetaOp(k); }; d.onclick = e => { e.preventDefault(); carpetaOp(k, true); };
      sm.append(r, " ", d);
    }
    ul.append(el("details", {open: true}, sm, el("ul", {className: "list"}, ...g[k].map(fila))));
  }
}
async function abrir(id, acta) {
  cur = await api("/api/meeting/" + id);
  const s = $("sel-acta"); s.replaceChildren(...cur.actas.map(a => el("option", {value: a.name, textContent: a.nivel + " · " + a.asr + (a.alta ? " · alta" : "") + (a.fondo ? " · a fondo" : ""), "data-asr": a.asr})));
  if (acta) s.value = acta;
  vista("res"); cambiarActa(); pintarConds();
}
function cambiarActa() {
  const a = cur.actas.find(a => a.name === $("sel-acta").value);
  $("acta-frame").src = a.url + "?v=" + Date.now(); $("fondo").disabled = a.fondo; $("fondo").textContent = a.fondo ? "Búsqueda a fondo hecha" : "Buscar todas a fondo"; $("dl-zip").hidden = !a.zip; if (a.zip) { $("dl-zip").href = a.zip; $("dl-zip").download = cur.nombre ? cur.nombre + ".zip" : ""; }
  $("dl-vid").hidden = !cur.video; $("dl-vid").href = "/api/zipvideo/" + cur.id + "/" + a.name; $("dl-vid").textContent = "Descargar con vídeo (" + cur.videomb + " MB)";
  const imp = cur.importadas[a.asr];
  $("imp-info").textContent = imp ? "Transcripción importada: " + imp.fuente + " (" + imp.formato + ", " + imp.segmentos + " segmentos, " + imp.hablantes.length + " hablantes)" +
    (cur.video ? (imp.aviso ? "" : " · desfase aplicado " + (imp.desfase >= 0 ? "+" : "") + Math.round(imp.desfase) + " s") : " · sin vídeo: sin capturas ni reproductor") + (imp.aviso ? ". " + imp.aviso : "") : "";
  $("imp-info").className = imp && imp.aviso ? "err" : "muted"; $("cond").hidden = !cur.video;
  const rec = cur.recomendado[a.asr]; if (rec) { $("pct").value = rec; $("pct-o").textContent = rec; $("rec").textContent = "Recomendado para esta reunión: " + rec + " %. Primero los silencios largos, después lo menos importante."; }
}
$("sel-acta").onchange = cambiarActa;
$("pct").oninput = () => $("pct-o").textContent = $("pct").value;
$("volver").onclick = () => { $("acta-frame").src = "about:blank"; vista("nuevo"); cargarLista(); };
function pintarConds() {
  $("cvideo").hidden = true; $("cvideo").removeAttribute("src");
  $("conds").replaceChildren(...cur.condensados.map(c => {
    const ver = el("button", {className: "sec", textContent: "Ver"}); ver.onclick = () => { $("cvideo").src = c.url; $("cvideo").hidden = false; $("cvideo").play(); };
    return el("li", {}, el("span", {className: "n", textContent: c.name}), el("span", {}, ver, " ", el("a", {className: "btn sec", href: c.url, download: c.name, textContent: "Descargar"})));
  }));
}

// ---- preguntar ----
let reuniones = [];
async function cargarReuniones() {
  const prev = $("reunion").value; reuniones = await api("/api/meetings");
  const g = {}; unicas(reuniones).forEach(m => m.carpeta && (g[m.carpeta] = (g[m.carpeta] || 0) + 1));
  const cs = Object.keys(g).sort();
  $("reunion").replaceChildren(...reuniones.map(m => el("option", {value: m.sel, textContent: (m.carpeta ? "📁 " + m.carpeta + " / " : "") + m.name})),
    ...(cs.length ? [el("optgroup", {label: "Carpetas (todas sus reuniones)"}, ...cs.map(c => el("option", {value: "c:" + c, textContent: "📁 Carpeta " + c + " (" + g[c] + " reunion" + (g[c] > 1 ? "es" : "") + ")"})))] : []));
  if ($("reunion").querySelector(`option[value="${CSS.escape(prev)}"]`)) $("reunion").value = prev;
  cambiarReunion();
}
function cambiarReunion() { const m = reuniones.find(m => m.sel === $("reunion").value); const v = $("qav"); v.hidden = !m || !m.video; if (m && m.video && !v.src.endsWith(m.video)) v.src = m.video; }
$("renombrar").onclick = () => { const v = $("reunion").value; if (v.startsWith("c:")) return carpetaOp(v.slice(2)); const m = reuniones.find(m => m.sel === v); if (m) renombrar(m); };
$("reunion").onchange = cambiarReunion; $("refrescar").onclick = cargarReuniones;
// v: undefined = vídeo del selector; en carpetas, la url del vídeo de esa reunión (null = reunión sin vídeo); n: nombre de la reunión
const ts = (t, v, n) => el("a", {className: "ts", href: "#", textContent: "[" + (n ? n + " · " : "") + mmss(t) + "]", onclick: e => {
  e.preventDefault(); const q = $("qav"); if (v === null) return;
  const go = () => { q.currentTime = Math.floor(t); q.play(); };
  q.hidden = false; if (v && !q.src.endsWith(v)) { q.addEventListener("loadedmetadata", go, {once: true}); q.src = v; } else go();
}});
$("qform").onsubmit = async e => {
  e.preventDefault(); const q = $("pregunta").value.trim(); if (!q || !$("reunion").value) return;
  $("preguntar-b").disabled = true;
  const box = el("div", {className: "card resp"}, el("h3", {textContent: q})), cuerpo = el("div"), frag = el("details", {open: true}, el("summary", {textContent: "Fragmentos recuperados"}));
  box.append(cuerpo, frag); $("respuestas").prepend(box);
  const estado = el("p", {textContent: "Buscando en la reunión…"}); cuerpo.append(estado);
  try {
    const r = await fetch("/api/preguntar", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({sel: $("reunion").value, q, gpu: $("usar-gpu").checked})});
    if (!r.ok) throw new Error((await r.json()).detail);
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
  else if (ev.k === "aviso") cuerpo.insertBefore(el("p", {}, el("small", {textContent: ev.text})), estado);
  else if (ev.k === "nada") cuerpo.insertBefore(el("p", {}, el("b", {textContent: ev.text})), estado);
  else if (ev.k === "error") cuerpo.append(el("p", {className: "err", textContent: ev.text}));
}

// ---- arranque: retomar un trabajo en marcha ----
cargarLista();
api("/api/job").then(j => { if (j.state === "running") seguir(); });

// ---- primera vez: descarga de modelos (bloquea la página hasta terminar) ----
async function modelos() {
  let m = await api("/api/modelos").catch(() => null);
  if (!m || (!m.need && m.state !== "running")) return $("modelos").hidden = true;
  $("modelos").hidden = false; $("mod-reint").hidden = true;
  if (m.falta && m.state === "idle") $("mod-gb").textContent = "unos " + (m.falta / 1e9).toFixed(1).replace(".", ",") + " GB de modelos";
  if (m.state === "idle") m = await post("/api/modelos");
  const p = Math.min(100, Math.round(m.done / m.total * 100));
  $("mod-msg").textContent = m.msg; $("mod-bar").style.width = p + "%";
  $("mod-pct").textContent = p + " % · " + (m.done / 1e9).toFixed(2) + " de " + (m.total / 1e9).toFixed(2) + " GB";
  if (m.state === "error") { $("mod-reint").hidden = false; return; }
  setTimeout(modelos, 1000);
}
$("mod-reint").onclick = async () => { await post("/api/modelos"); modelos(); };
modelos();

