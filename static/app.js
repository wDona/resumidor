const $ = id => document.getElementById(id);
// 409 {msg, faltan}: falta instalar modelos -> se abre Modelos con el aviso
const det = (j, st) => { const d = j.detail; if (d && d.faltan) { abrirModelos(d.msg, d.faltan); return d.msg; } return d || st; };
const api = (url, opt) => fetch(url, opt).then(async r => { if (!r.ok) throw new Error(det(await r.json().catch(() => ({})), r.statusText)); return r.json(); });
const post = (url, body) => api(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body || {})});
const mmss = t => { t = Math.floor(t); const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60, p = n => String(n).padStart(2, "0"); return (h ? h + ":" + p(m) : p(m)) + ":" + p(s); };
const el = (tag, props = {}, ...kids) => { const e = document.createElement(tag); for (const k in props) k.startsWith("data-") || k.startsWith("aria-") ? e.setAttribute(k, props[k]) : e[k] = props[k]; e.append(...kids); return e; };
let corriendo = false;
addEventListener("beforeunload", e => { if (corriendo) { e.preventDefault(); e.returnValue = "Hay trabajos en la cola; si cierras, se cancelarán"; } });
setInterval(() => fetch("/api/latido", {method: "POST"}).catch(() => {}), 5000); fetch("/api/latido", {method: "POST"});

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
  const gb = g.vram_mb ? `, ${Math.round(g.vram_mb / 1024)} GB de VRAM` : g.igpu ? ", gráfica integrada (usa la RAM del sistema)" : "";
  c.disabled = !g.ok; c.checked = g.ok && (v === null ? g.default : v === "1");
  c.parentElement.title = "";
  $("info-gpu").textContent = !g.ok ? "GPU no encontrada o no válida" : (g.default ? "Se te recomienda usar la GPU" : "No se te recomienda usar la GPU") + ` (${g.name}${gb})`;
  const chat = () => { const [gem, why] = g[c.checked && g.ok ? "chat_gpu" : "chat_cpu"]; return `Chat: ${gem ? "gemma-4-E4B" : g.llm} (${why})`; };
  const ram = () => $("info-ram").textContent = `RAM: ${g.ram_gb || "?"} GB` + (g.ok && g.vram_mb ? ` · VRAM: ${Math.round(g.vram_mb / 1024)} GB (${g.name})` : g.ok && g.igpu ? ` · ${g.name}: gráfica integrada (usa la RAM del sistema)` : "") + " · " + chat() + (g.ram_gb && g.ram_gb < 8 ? ". Poca RAM: el proceso puede ir muy lento o fallar" : "");
  ram();
  c.onchange = () => { ram(); try { localStorage.setItem("usar-gpu", c.checked ? "1" : "0"); } catch {} };
  niveles(g.niveles);
}).catch(() => {});
let NIV = [];
const GB = b => (b / 1e9).toFixed(1).replace(".", ",") + " GB";
const nivelInfo = q => NIV.find(n => n.id === q);
// selector de calidad: modelo entre paréntesis; "no cabe" deshabilitado; no instalado -> botón Descargar
function niveles(l) {
  NIV = l; const c = $("calidad"), v = c.value;
  c.innerHTML = ""; for (const n of l) c.add(new Option(`${n.nombre} (${n.modelo})` + (n.estado === "no" ? " — no cabe" : !n.instalado ? ` — no instalado, ${GB(n.bytes)}` : ""), n.id));
  l.forEach((n, i) => c.options[i].disabled = n.estado === "no");
  c.value = l.some(n => n.id === v && n.estado !== "no") ? v : "rápida"; c.onchange();
}
$("calidad").onchange = () => {
  const n = nivelInfo($("calidad").value); if (!n) return;
  const t = [n.tiempo > 1 && `Tarda aprox. ${n.tiempo}× lo que Rápida`, n.estado === "no" && `No cabe en este equipo (necesita ~${Math.ceil(n.necesita)} GB de memoria)`,
    n.estado === "aviso" && "No tienes los recursos recomendados para este modelo, puede tardar más de lo normal", n.pers && "Modelo no probado con la app: la calidad del acta puede variar"].filter(Boolean);
  $("aviso-alta").textContent = t.join(". "); $("aviso-alta").hidden = !t.length;
  $("bajar-nivel").hidden = n.instalado; $("bajar-nivel").textContent = `Descargar ${n.modelo} (${GB(n.bytes)})`;
  $("info-alta").hidden = n.id === "rápida";
};
$("bajar-nivel").onclick = async () => { await post("/api/modelos", {ids: [nivelInfo($("calidad").value).m]}); abrirModelos(); };

// ---- vistas: home (carpetas + reuniones) | nuevo | cola | res (reunión) | preg (carpeta) ----
let vistaAct = "home";
const vista = v => { vistaAct = v; ["home", "nuevo", "cola", "res", "preg"].forEach(n => $("v-" + n).hidden = n !== v); scrollTo(0, 0); };
const ir = v => { if (v === "home") pintarHome(); vista(v); };
const aviso = t => { const n = $("toast") || document.body.appendChild(el("div", {id: "toast", role: "status"})); n.textContent = t; n.hidden = false; clearTimeout(aviso.t); aviso.t = setTimeout(() => n.hidden = true, 3500); };
$("inicio").onclick = e => { e.preventDefault(); ir("home"); };
$("nuevo-volver").onclick = $("cola-volver").onclick = $("preg-volver").onclick = () => ir("home");
$("b-cola").onclick = () => { vista("cola"); sondear(); };
$("nueva").onclick = () => formNuevo();

// ---- nueva acta (o otra versión de una reunión: reuse) ----
let reuse = null;
const VACIO_SUB = $("form-sub").textContent;
function formNuevo(m, a) {
  reuse = m ? {id: m.id, asr: a.asr} : null;
  $("form-t").textContent = m ? "Otra versión de «" + m.label + "»" : "Nueva acta";
  $("form-sub").textContent = m ? "Rehace el acta con otro nivel o calidad aprovechando la transcripción y las capturas ya hechas. Con el mismo nivel y calidad que una versión existente, la sustituye." : VACIO_SUB;
  $("f-fuente").hidden = $("f-hab").hidden = !!m; $("form-err").textContent = "";
  if (m) {  // propone la primera combinación que aún no existe
    const hay = n => cur.actas.some(x => x.name === n);
    const [n, c] = ["normal", "breve", "detallado"].flatMap(n => NIV.map(q => q.id).map(c => [n, c])).find(([n, c]) => !hay(`acta_${n}_${a.asr}${c === "rápida" ? "" : "_" + c}`)) || [a.nivel, a.calidad];
    $("nivel").value = n; $("calidad").value = c; $("calidad").onchange();
  }
  vista("nuevo");
}
const params = () => ({video: reuse ? "" : ruta, enlace: reuse || ruta ? "" : $("enlace").value.trim(), solo_audio: $("solo-audio").checked, navegador: $("navegador").value, transcripcion: reuse ? "" : rutaTr, nivel: $("nivel").value, calidad: $("calidad").value, asr: reuse ? reuse.asr : "calidad", reuse: reuse?.id,
  hablantes: $("hablantes").checked, gpu: $("usar-gpu").checked, nombres: $("nombres").value});
$("form").onsubmit = async e => {
  e.preventDefault();
  if (!reuse && !ruta && !rutaTr && !$("enlace").value.trim()) { $("form-err").textContent = "Elige un vídeo, un audio, un enlace o una transcripción"; return; }
  try { await post("/api/generar", params()); if (!reuse) { setRuta(""); setTr(""); $("enlace").value = ""; } vista("cola"); sondear(); } catch (err) { $("form-err").textContent = err.message; }
};

// ---- cola de trabajos ----
const ACT = ["pendiente", "marcha"], KIND = {acta: "Generar acta", fondo: "Búsqueda a fondo", condensar: "Vídeo condensado"};
let cola = {n: 0, items: []}, vistos = new Set(), colaKey = "";
const nombreDe = e => (e.mid && todas.find(m => m.id === e.mid)?.label) || e.video;
const minutos = s => s > 90 ? "unos " + Math.round(s / 60) + " min" : "unos " + s + " s";
async function sondear() {
  const c = await api("/api/cola").catch(() => null); if (!c) return;
  const act = new Set(c.items.filter(e => ACT.includes(e.state)).map(e => e.id));
  const fin = c.items.filter(e => vistos.has(e.id) && !act.has(e.id));
  vistos = act; cola = c; corriendo = c.n > 0; $("n-cola").textContent = c.n;
  const k = c.items.map(e => e.id + e.state).join();
  if (fin.length) {  // algo terminó: refrescar lista y, si es la reunión abierta, su página
    await cargarLista();
    if (vistaAct === "res" && fin.some(e => e.state === "hecho" && e.mid === cur.id)) await abrir(cur.id, ver, true);
  } else if (k !== colaKey && vistaAct === "home") pintarHome();
  pintarCola(k);
}
function pintarCola(k) {
  if (k !== colaKey) {
    colaKey = k; const it = cola.items, pend = it.filter(e => e.state === "pendiente");
    const grp = t => el("li", {className: "grp", textContent: t});
    const fila = e => {
      const b = (txt, url, extra, lbl) => { const x = el("button", {className: "sec", textContent: txt, ariaLabel: lbl || txt}); x.onclick = fallo(async () => { x.disabled = true; await post(url, {id: e.id, ...extra}); await sondear(); }); return x; };
      const bs = e.state === "marcha" ? [b("Cancelar", "/api/cola/cancelar")]
        : e.state === "pendiente" ? [b("↑", "/api/cola/mover", {d: -1}, "Subir"), b("↓", "/api/cola/mover", {d: 1}, "Bajar"), b("Quitar", "/api/cola/cancelar")]
        : [...(e.state === "hecho" ? [] : [b("Reintentar", "/api/cola/reintentar")]), b("Quitar", "/api/cola/quitar")];
      if (e.state === "hecho" && e.result?.id) { const o = el("button", {className: "sec", textContent: "Abrir"}); o.onclick = fallo(() => abrir(e.result.id, e.result.acta)); bs.unshift(o); }
      const d = e.state === "pendiente" ? "En espera (" + (pend.indexOf(e) + 1) + " de " + pend.length + ")" : e.state === "hecho" ? "Terminado" : e.state === "marcha" ? "" : e.state === "cancelado" ? "Cancelado" : (e.state === "interrumpido" ? "Interrumpido: " : "Ha fallado: ") + (e.error || "");
      return el("li", {}, el("div", {className: "n"}, el("b", {textContent: KIND[e.kind] + " · " + nombreDe(e)}), el("div", {className: e.state === "error" ? "d err" : "d", textContent: d, id: e.state === "marcha" ? "q-msg" : ""})),
        el("span", {}, ...bs.flatMap(x => [x, " "])), ...(e.state === "marcha" ? [el("div", {className: "bar full"}, el("div", {id: "q-bar"})), el("p", {className: "muted full", id: "q-eta"})] : []));
    };
    const r = it.filter(e => e.state === "marcha"), h = it.filter(e => !ACT.includes(e.state)).reverse();
    $("q-lista").replaceChildren(...(r.length ? [grp("En marcha"), ...r.map(fila)] : []), ...(pend.length ? [grp("En espera"), ...pend.map(fila)] : []), ...(h.length ? [grp("Recientes"), ...h.map(fila)] : []));
  }
  const r = cola.items.find(e => e.state === "marcha");
  if (r && $("q-bar")) {
    $("q-msg").textContent = r.msg; $("q-bar").style.width = Math.round(r.frac * 100) + "%";
    $("q-eta").textContent = Math.round(r.frac * 100) + " %" + (r.eta != null ? " · quedan " + minutos(r.eta) : "");
  }
}

// ---- reuniones y carpetas ----
let cur, ver, tabAct = "p-acta", todas = [], carpetas = [], fsel = null;  // fsel: null = todas, "" = sin carpeta, otro = esa carpeta
const fallo = f => (...a) => f(...a).catch(err => alert(err.message));
const refrescarTodo = async () => { await cargarLista(); if (vistaAct === "res") await abrir(cur.id, ver, true); };
// formulario en la propia página (sin prompt/confirm): campo opcional + botón + Cancelar; Esc cancela
function enLinea(donde, {valor, lista, texto, boton = "Guardar"}, hecho) {
  document.querySelector("form.inline")?.remove();
  const f = el("form", {className: "inline row"}), c = el("button", {type: "button", className: "sec", textContent: "Cancelar"});
  const i = valor != null ? el("input", {value: valor, ariaLabel: texto}) : null;
  if (i && lista?.length) { i.setAttribute("list", "dl-carpetas"); f.append(el("datalist", {id: "dl-carpetas"}, ...lista.map(v => el("option", {value: v})))); }
  f.append(el("span", {textContent: texto}), ...(i ? [i] : []), el("button", {className: "pri", textContent: boton}), c);
  c.onclick = () => f.remove();
  f.onkeydown = e => e.key === "Escape" && f.remove();
  f.onsubmit = e => { e.preventDefault(); fallo(async () => { await hecho(i ? i.value.trim() : ""); f.remove(); })(); };
  donde.append(f); (i || c).focus(); i?.select();
}
const renombrar = (m, donde) => enLinea(donde, {valor: m.nombre || m.label, texto: "Nombre (vacío = el original)"},
  async n => { await post("/api/meta", {id: m.id, nombre: n}); await refrescarTodo(); });
const mover = (m, donde) => enLinea(donde, {valor: m.carpeta || "", lista: carpetas, texto: "Carpeta (nueva o existente; vacío = sin carpeta)", boton: "Mover"},
  async c => { await post("/api/meta", {id: m.id, carpeta: c}); await refrescarTodo(); });
const carpetaOp = (nombre, borrar, donde) => enLinea(donde, borrar ? {texto: "Se quita la carpeta «" + nombre + "»: las reuniones pasan a «Sin carpeta» y no se borran.", boton: "Quitar"}
  : {valor: nombre, texto: "Nuevo nombre de la carpeta"}, async nuevo => {
    if (!borrar && (!nuevo || nuevo === nombre)) return;
    await post("/api/carpeta", {nombre, nuevo}); if (fsel === nombre) fsel = borrar ? null : nuevo; await refrescarTodo();
  });
const unicas = ms => { const v = new Set(); return ms.filter(m => !v.has(m.id) && v.add(m.id)); };
async function cargarLista() {
  [todas, carpetas] = await Promise.all([api("/api/meetings").then(ms => unicas(ms).filter(m => m.actas)), api("/api/carpetas")]);
  if (fsel && !carpetas.includes(fsel)) fsel = null;
  pintarHome();
}
const plural = n => n + " reunion" + (n === 1 ? "" : "es");
function pintarHome() {
  const cnt = c => todas.filter(m => c === null || (m.carpeta || "") === c).length;
  const nav = (txt, v) => el("li", {}, el("button", {className: "nav", textContent: txt, "aria-current": fsel === v, onclick: () => { fsel = v; pintarHome(); }}, el("span", {className: "c", textContent: cnt(v)})));
  $("carpetas").replaceChildren(nav("Todas", null), ...carpetas.map(c => nav("📁 " + c, c)), nav("Sin carpeta", ""));
  const ms = todas.filter(m => fsel === null || (m.carpeta || "") === fsel);
  $("ftit").textContent = (fsel === null ? "Todas" : fsel === "" ? "Sin carpeta" : "📁 " + fsel) + " · " + plural(ms.length);
  for (const id of ["f-preguntar", "f-ren", "f-quitar"]) $(id).hidden = !fsel;
  const act = cola.items.filter(e => ACT.includes(e.state)), est = e => e.state === "marcha" ? "⏳ generando" : "⏳ en cola (" + (act.indexOf(e) + 1) + "/" + act.length + ")";
  const nuevas = fsel === null || fsel === "" ? act.filter(e => e.kind === "acta" && !e.mid).map(e => el("li", {className: "fila-v"}, el("span", {className: "n", textContent: e.video}), el("span", {className: "st", textContent: est(e)}))) : [];
  const fila = m => {
    const e = act.find(e => e.mid === m.id), f = new Date(m.mtime * 1000);
    const b = el("button", {className: "fila", onclick: fallo(() => abrir(m.id))}, el("span", {className: "n", textContent: "▶ " + m.label + (fsel === null && m.carpeta ? "  📁 " + m.carpeta : "")}),
      el("span", {className: "d", textContent: f.toLocaleDateString("es", {day: "2-digit", month: "2-digit"})}), el("span", {className: "d", textContent: m.dur ? Math.round(m.dur / 60) + " min" : ""}),
      el("span", {className: "d", textContent: m.actas + (m.actas === 1 ? " acta" : " actas")}), el("span", {className: "st", textContent: e ? est(e) : ""}));
    return el("li", {}, b);
  };
  $("lista").replaceChildren(...nuevas, ...ms.map(fila));
}
$("f-ren").onclick = () => carpetaOp(fsel, false, $("ed-carpeta"));
$("f-quitar").onclick = () => carpetaOp(fsel, true, $("ed-carpeta"));
$("nueva-carpeta").onclick = () => enLinea($("ed-side"), {valor: "", texto: "Nombre de la carpeta nueva", boton: "Crear"}, async n => { if (!n) return; await post("/api/carpeta", {nuevo: n}); fsel = n; await cargarLista(); });
$("f-preguntar").onclick = () => { $("preg-tit").textContent = "Preguntar · 📁 " + fsel; $("p-fcarpeta").append($("qpanel")); setQ("c:" + fsel, null); vista("preg"); };

// ---- página de una reunión ----
const cap = s => s[0].toUpperCase() + s.slice(1);
const defecto = a => [cap(a.nivel), (nivelInfo(a.calidad)?.nombre || "Rápida") + (nivelInfo(a.calidad)?.pers ? " · " + nivelInfo(a.calidad).modelo : ""), a.fondo && "a fondo", a.name.split("_").slice(3).filter(x => !(x in {alta:1, alta9:1, muyalta:1, maxima:1} || /^p[0-9a-f]{6}$/.test(x))).join(" ")].filter(Boolean).join(" · ");
const etiqueta = a => cur.versiones[a.name] || defecto(a);
async function abrir(id, acta, quedar) {
  cur = await api("/api/meeting/" + id);
  cur.m = todas.find(m => m.id === id) || {id, label: cur.nombre || id, nombre: cur.nombre, carpeta: cur.carpeta};
  ver = (cur.actas.find(a => a.name === acta) || cur.actas.find(a => a.name === ver && quedar) || cur.actas[0]).name;
  $("cab-carpeta").textContent = cur.carpeta || "Todas"; $("cab-titulo").textContent = cur.m.label;
  const au = cur.audio; $("t-video").hidden = !cur.video; $("t-video").textContent = au ? "Audio" : "Vídeo"; $("vvideo").style.height = au ? "54px" : "";
  $("cond-t").textContent = au ? "Audio condensado" : "Vídeo condensado"; $("condensar").textContent = au ? "Generar audio condensado" : "Generar vídeo condensado";
  if (cur.video) $("vvideo").src = cur.videourl; else $("vvideo").removeAttribute("src");
  vista("res"); pintarVers(); cambiarActa(); pintarConds(); tab(quedar && !(tabAct === "p-video" && !cur.video) ? tabAct : "p-acta");
}
const tab = p => {
  tabAct = p;
  document.querySelectorAll("#mtabs button").forEach(b => { b.setAttribute("aria-selected", b.dataset.p === p); $(b.dataset.p).hidden = b.dataset.p !== p; });
  if (p !== "p-video") $("vvideo").pause();
  if (p === "p-preg") { $("p-preg").append($("qpanel")); const a = cur.actas.find(a => a.name === ver); setQ(cur.id + "|" + a.asr, cur.videourl); $("preguntar-b").disabled = $("pregunta").disabled = a.sin; $("pregunta").placeholder = a.sin ? "Acta importada sin transcripción: no se puede preguntar" : ""; }
};
document.querySelectorAll("#mtabs button").forEach(b => b.onclick = () => tab(b.dataset.p));
function pintarVers() {
  const a = cur.actas.find(a => a.name === ver), ren = el("button", {className: "sec", textContent: "✎", ariaLabel: "Renombrar esta versión", title: "Renombrar esta versión"}), otra = el("button", {className: "sec", textContent: "+ generar otra"});
  ren.onclick = () => enLinea($("ed-res"), {valor: etiqueta(a), texto: "Nombre de la versión (vacío = el original)"}, async n => {
    await post("/api/meta", {id: cur.id, version: ver, vnombre: n === defecto(a) ? "" : n}); cur.versiones = (await api("/api/meeting/" + cur.id)).versiones; pintarVers();
  });
  otra.onclick = () => formNuevo(cur.m, a);
  $("vers").replaceChildren(...cur.actas.map(x => el("button", {role: "tab", className: "vt", textContent: etiqueta(x), "aria-selected": x.name === ver, onclick: () => { ver = x.name; pintarVers(); cambiarActa(); }})), ren, otra);
}
function cambiarActa() {
  const a = cur.actas.find(a => a.name === ver);
  $("acta-frame").src = a.url + "?v=" + Date.now(); $("fondo").disabled = a.fondo; $("fondo").textContent = a.fondo ? "Búsqueda a fondo hecha" : "Buscar todas a fondo"; $("dl-zip").hidden = !a.zip; if (a.zip) { $("dl-zip").href = a.zip; $("dl-zip").download = cur.nombre ? cur.nombre + ".zip" : ""; }
  $("dl-vid").hidden = !cur.video; $("dl-vid").href = "/api/zipvideo/" + cur.id + "/" + a.name; $("dl-vid").textContent = "Descargar con " + (cur.audio ? "audio" : "vídeo") + " (" + cur.videomb + " MB)";
  const imp = cur.importadas[a.asr];
  $("imp-info").textContent = imp ? "Transcripción importada: " + imp.fuente + " (" + imp.formato + ", " + imp.segmentos + " segmentos, " + imp.hablantes.length + " hablantes)" +
    (cur.video ? (imp.aviso ? "" : " · desfase aplicado " + (imp.desfase >= 0 ? "+" : "") + Math.round(imp.desfase) + " s") : (cur.audio ? " · solo audio: sin capturas" : " · sin vídeo: sin capturas ni reproductor")) + (imp.aviso ? ". " + imp.aviso : "") : "";
  $("imp-info").className = imp && imp.aviso ? "err" : "muted"; $("cond").hidden = !cur.video;
  const rec = cur.recomendado[a.asr]; if (rec) { $("pct").value = rec; $("pct-o").textContent = rec; $("rec").textContent = "Recomendado para esta reunión: " + rec + " %. Primero los silencios largos, después lo menos importante."; }
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
$("volver").onclick = () => {
  $("acta-frame").src = "about:blank"; ["vvideo", "qav", "cvideo"].forEach(i => $(i).pause());
  fsel = fsel === null ? null : cur.carpeta || ""; ir("home");
};
function pintarConds() {
  $("cvideo").hidden = true; $("cvideo").removeAttribute("src");
  $("conds").replaceChildren(...cur.condensados.map(c => {
    const vb = el("button", {className: "sec", textContent: "Ver"}); vb.onclick = () => { $("cvideo").src = c.url; $("cvideo").hidden = false; $("cvideo").play(); };
    return el("li", {}, el("span", {className: "n", textContent: c.name}), el("span", {}, vb, " ", el("a", {className: "btn sec", href: c.url, download: c.name, textContent: "Descargar"})));
  }));
}

// ---- preguntar (panel único #qpanel: se monta en la pestaña de la reunión o en la vista de carpeta) ----
let qsel = "";
function setQ(sel, video) {  // sel: "id|asr" o "c:carpeta"; video: url (null = sin vídeo hasta que una marca lo pida)
  if (sel !== qsel) $("respuestas").replaceChildren();
  qsel = sel; $("qpanel").hidden = false; const v = $("qav"); v.hidden = !video;
  if (video && !v.src.endsWith(video)) v.src = video;
  v.classList.toggle("audio", /\.(mp3|m4a|wav|ogg|opus|flac|aac)$/i.test(video || ""));  // solo audio: barra de controles, sin caja negra
}

// v: undefined = vídeo del selector; en carpetas, la url del vídeo de esa reunión (null = reunión sin vídeo); n: nombre de la reunión
const ts = (t, v, n) => el("a", {className: "ts", href: "#", textContent: "[" + (n ? n + " · " : "") + mmss(t) + "]", onclick: e => {
  e.preventDefault(); const q = $("qav"); if (v === null) return;
  const go = () => { q.currentTime = Math.floor(t); q.play(); };
  q.hidden = false; if (v && !q.src.endsWith(v)) { q.addEventListener("loadedmetadata", go, {once: true}); q.src = v; } else go();
}});
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
  else if (ev.k === "aviso") cuerpo.insertBefore(el("p", {}, el("small", {textContent: ev.text})), estado);
  else if (ev.k === "nada") cuerpo.insertBefore(el("p", {}, el("b", {textContent: ev.text})), estado);
  else if (ev.k === "error") cuerpo.append(el("p", {className: "err", textContent: ev.text}));
}

// ---- arranque ----
cargarLista().then(sondear); setInterval(sondear, 2000);

// ---- modelos: elegir qué instalar (primera vez y desde «Modelos»); GGUF ya presentes en el equipo ----
const BADGE = {ok: "Recomendado", aviso: "Usable (no recomendado)", no: "No compatible"};
const AV = {aviso: "No tienes los recursos recomendados para este modelo, puede tardar más de lo normal", no: n => `Tu equipo no tiene memoria suficiente para este modelo (necesita ~${Math.ceil(n)} GB): no se podrá usar`};
let MOD = null, primera = false;
const avisoM = (e, need) => e === "aviso" ? AV.aviso : e === "no" ? AV.no(need) : "";
const total = () => MOD.catalogo.filter(c => !c.instalado && $("mc-" + c.id)?.checked).reduce((a, c) => a + c.bytes, 0);
function pintarModelos(m, faltan = []) {
  MOD = m; const L = $("mod-lista"); L.innerHTML = "";
  for (const c of m.catalogo) {
    const d = document.createElement("div"); d.className = "mrow";
    d.innerHTML = `<label><input type="checkbox" id="mc-${c.id}" ${c.instalado ? "checked disabled" : ""}> <span><b></b> <span class="muted"></span></span><span class="grow"></span><span class="b"></span><span>${c.instalado ? "instalado" : GB(c.bytes)}</span></label><small class="warn" hidden></small>`;
    d.querySelector("b").textContent = c.nombre; d.querySelector(".muted").textContent = c.uso; d.querySelector(".b").textContent = BADGE[c.estado] + (c.rec ? "" : "");
    const w = d.querySelector(".warn"), cb = d.querySelector("input");
    const act = () => { const t = c.estado !== "ok" && (cb.checked && !c.instalado || c.instalado && c.estado === "no") ? avisoM(c.estado, c.necesita) : ""; w.textContent = t; w.hidden = !t; $("mod-total").textContent = "Descarga total: " + GB(total()); $("mod-inst").textContent = `Instalar seleccionados (${GB(total())})`; };
    cb.onchange = act; if (c.instalado) act();
    if (c.instalado && (c.id !== "chat" || true)) { const q = document.createElement("button"); q.className = "sec"; q.textContent = "Quitar"; q.onclick = async () => { if (confirm(`¿Quitar ${c.nombre} y liberar ${GB(c.bytes)}?`)) try { pintarModelos(await post("/api/modelos/borrar", {id: c.id})); niveles((await api("/api/gpu")).niveles); } catch (e) { alert(e.message); } }; d.append(q); }
    L.append(d);
  }
  for (const i of faltan) if ($("mc-" + i)) $("mc-" + i).checked = true;
  $("mod-total").textContent = "Descarga total: " + GB(total()); $("mod-inst").textContent = `Instalar seleccionados (${GB(total())})`;
  for (const c of m.catalogo) $("mc-" + c.id).onchange();
}
async function pintarEncontrados() {
  const r = await api("/api/modelos/encontrados"), L = $("mod-enc-lista"), lv = r.config.levels || {}, ex = (r.config.extra || []).map(e => e.ruta); L.innerHTML = "";
  for (const e of r.encontrados) {
    const d = document.createElement("div"); d.className = "mrow";
    const cur = Object.keys(lv).find(q => lv[q] === e.ruta) || (ex.includes(e.ruta) ? "pers" : "");
    d.innerHTML = `<label><span><b></b> <span class="muted"></span></span><span class="grow"></span><span class="b"></span><span>${GB(e.bytes)}</span></label><small class="warn" ${e.estado === "no" ? "" : "hidden"}></small><select><option value="">Usar para: —</option>${["rápida", "alta", "alta9", "muyalta", "maxima"].map(q => `<option value="${q}">Usar para: ${q === "alta9" ? "Alta+" : q[0].toUpperCase() + q.slice(1).replace("muyalta", "Muy alta")}</option>`).join("")}<option value="pers">Añadir como nivel Personalizado</option></select>`;
    d.querySelector("b").textContent = e.nombre; d.querySelector(".muted").textContent = `${e.origen} · ${e.ruta}`; d.querySelector(".b").textContent = BADGE[e.estado];
    d.querySelector(".warn").textContent = AV.no(e.necesita); d.querySelector("select").value = cur;
    d.querySelector("select").onchange = async ev => { await post("/api/modelos/usar", {ruta: e.ruta, nivel: ev.target.value, nombre: e.nombre}); niveles((await api("/api/gpu")).niveles); pintarEncontrados(); };
    L.append(d);
  }
  if (!r.encontrados.length) L.innerHTML = '<p class="muted">No se encontró ninguno.</p>';
}
$("mod-enc").ontoggle = () => $("mod-enc").open && pintarEncontrados();
$("mod-add").onclick = async () => { const r = (await post("/api/pick", {tipo: "modelo"})).path; if (r) { try { await post("/api/modelos/usar", {ruta: r, nivel: "pers"}); niveles((await api("/api/gpu")).niveles); } catch (e) { alert(e.message); } pintarEncontrados(); } };
async function abrirModelos(msg, faltan) {
  const m = await fetch("/api/modelos").then(r => r.json()).catch(() => null); if (!m) return;
  $("modelos").hidden = false; history.replaceState(null, "", "#/modelos");
  $("mod-intro").textContent = msg || "Elige qué modelos instalar. Se descargan una sola vez y después funciona sin internet; si se corta, sigue donde se quedó. Sin modelos puedes ver e importar actas.";
  if (m.state === "running" || m.state === "error") return seguir(m);
  $("mod-prog").hidden = true; $("mod-botones").hidden = false; pintarModelos(m, faltan);
}
async function instalar(ids) {
  $("mod-botones").hidden = true; $("mod-prog").hidden = false; $("mod-reint").hidden = true; $("mod-msg").textContent = "Empezando…";
  seguir(await post("/api/modelos", ids ? {ids} : {})); 
}
async function seguir(m) {
  $("mod-botones").hidden = true; $("mod-prog").hidden = false; $("mod-reint").hidden = true;
  const p = m.total ? Math.min(100, Math.round(m.done / m.total * 100)) : 0;
  $("mod-msg").textContent = m.msg; $("mod-bar").style.width = p + "%";
  $("mod-pct").textContent = p + " % · " + (m.done / 1e9).toFixed(2) + " de " + (m.total / 1e9).toFixed(2) + " GB";
  if (m.state === "error") { $("mod-reint").hidden = false; return; }
  if (m.state === "done") { niveles((await api("/api/gpu")).niveles); $("mod-prog").hidden = true; abrirModelos(); return; }
  setTimeout(async () => seguir(await api("/api/modelos")), 1000);
}
$("mod-rec").onclick = () => instalar(null);
$("mod-selrec").onclick = () => { for (const c of MOD.catalogo) if (!c.instalado) $("mc-" + c.id).checked = MOD.recomendados.includes(c.id); MOD.catalogo.forEach(c => $("mc-" + c.id).onchange()); };
$("mod-inst").onclick = () => instalar(MOD.catalogo.filter(c => !c.instalado && $("mc-" + c.id).checked).map(c => c.id));
$("mod-reint").onclick = () => instalar(MOD.catalogo.filter(c => !c.instalado && $("mc-" + c.id)?.checked).map(c => c.id));
const cerrarMod = () => { $("modelos").hidden = true; if (location.hash === "#/modelos") history.replaceState(null, "", location.pathname); };
$("mod-cerrar").onclick = cerrarMod; $("b-modelos").onclick = () => abrirModelos();
addEventListener("hashchange", () => location.hash === "#/modelos" ? abrirModelos() : $("modelos").hidden = true);
if (location.hash === "#/modelos") abrirModelos();  // sin ruta: la app abre en el inicio y no instala nada
// ---- importar un acta exportada (.zip) ----
$("b-importar").onclick = async () => {
  $("b-importar").disabled = true;
  try { const r = (await post("/api/pick", {tipo: "zip"})).path; if (r) { const m = await post("/api/importar", {path: r}); await cargarLista(); aviso("Acta importada"); abrir?.(m.id); } }
  catch (e) { aviso(e.message); } finally { $("b-importar").disabled = false; }
};

