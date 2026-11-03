// Marco del rediseño (REDISENO.md): raíl, rutas #/…, omnibox, paleta Ctrl+K, Inicio, hoja Añadir, Biblioteca, Pendientes, Enviar, Buscar,
// barra de acciones del Documento (Extraído, Fuente) y extras del Proyecto («Auto: …», ⋯ Más, Automático, importar Excel/CSV, añadir a proyecto).
// Usa los globales de app.js, carpeta.js, ajustes.js y exportar.js. enviar.js y descargar.js son opcionales: window.Enviar?, window.Descargar?.

const enc = encodeURIComponent, norm = s => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const KIND_T = {video: "Vídeo", audio: "Audio", pdf: "PDF", texto: "Texto", imagen: "Imagen"};
const TIPO_T = {tarea: "Tarea", decision: "Decisión", requisito: "Requisito", historia: "Historia", interesado: "Interesado", riesgo: "Riesgo", pregunta: "Pregunta", hito: "Hito"};
const TIPO_TAB = {tarea: "pendientes", decision: "decisiones", requisito: "requisitos", historia: "historias", interesado: "interesados", riesgo: "riesgos", pregunta: "preguntas", hito: "hitos"};
const editable = t => !!t?.closest?.("input, textarea, select, [contenteditable=true]");
const sinEnviar = () => aviso("El módulo de envío no está disponible");
const ICO = {inicio: '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/>', bib: '<path d="M4 4h6v16H4zM14 4h6v16h-6z"/>', pend: '<path d="M9 11l3 3 8-8"/><path d="M20 12v7a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h11"/>',
  env: '<path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4z"/>', proy: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>', mas: '<path d="M12 5v14M5 12h14"/>',
  aj: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>', rec: '<circle cx="12" cy="12" r="6"/>'};
const ico = k => { const s = el("span", {className: "ri", "aria-hidden": "true"}); s.innerHTML = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICO[k]}</svg>`; return s; };
const badgeT = (t, cls = "") => el("span", {className: "badge " + cls, textContent: t});

// ---------- rutas: #/ · #/biblioteca · #/pendientes · #/enviar · #/cola · #/p/<proyecto>/<pestaña> · #/d/<id>/<versión> · #/buscar/<q> · #/ajustes/<pestaña> ----------
let rutaLista = false, rutaRep = false;  // rutaLista: hasta aplicar la ruta inicial no se reescribe el hash; rutaRep: al seguir una ruta se reemplaza (no se apila)
function rutaHash() {
  const v = vistaAct;
  if (v === "home") return fsel === undefined ? "#/" : fsel === null ? "#/biblioteca" : "#/p/" + enc(fsel) + (fsel ? "/" + ftab : "");
  if (v === "res") return cur ? "#/d/" + cur.id + (ver ? "/" + enc(ver) : "") : "#/";
  if (v === "ajustes") return "#/ajustes/" + tabAj;
  if (v === "buscar") return "#/buscar/" + enc(BQ.q);
  if (v === "preg") return location.hash;
  return "#/" + ({bib: "biblioteca", pend: "pendientes", enviar: "enviar", cola: "cola", grabar: "grabar", uso: "uso"}[v] || "");
}
const desdeTxt = h => h.startsWith("#/p/") ? decodeURIComponent(h.split("/")[2] || "") || sinC() : h.startsWith("#/buscar") ? "Resultados" :
  {"#/biblioteca": "Biblioteca", "#/pendientes": "Pendientes", "#/enviar": "Enviar", "#/cola": "Cola"}[h] || "Inicio";
function rutaSync() {
  if (vistaAct === "home" && fsel === null) { fsel = undefined; vista("bib"); pintarBib(); return; }  // «todos los documentos» = Biblioteca
  if (rutaLista) { const h = rutaHash(); if (h !== location.hash && !(h === "#/" && !location.hash)) history[rutaRep ? "replaceState" : "pushState"](null, "", h); }
  document.body.classList.remove("rail-open"); pintarSide(); omniScope();
}
async function rutaIr() {
  const h = location.hash, [, a = "", b = "", c = ""] = h.split("/").map(x => { try { return decodeURIComponent(x); } catch { return x; } });
  if (/^#\/(ajustes|modelos|plantillas)/.test(h)) return;  // ajustes.js (ruta_)
  if (rutaLista && h === rutaHash()) return;
  rutaRep = true;
  try {
  if (a === "biblioteca") { vista("bib"); pintarBib(); }
  else if (a === "pendientes") { vista("pend"); pintarPendPag(); }
  else if (a === "enviar") { vista("enviar"); window.Enviar ? Enviar.montar($("env-raiz")) : $("env-raiz").replaceChildren(el("p", {className: "muted", textContent: "El módulo de envío no está disponible."})); }
  else if (a === "cola") { vista("cola"); sondear(); }
  else if (a === "grabar") grabarAbrir();
  else if (a === "p") { fsel = b; if (c) { ftab = c; lsSet("ftab", c); } fsucio = true; ir("home"); }
  else if (a === "d" && b) { const l = rutaLista; rutaLista = false; try { await abrir(b, c || undefined); } catch (x) { aviso(x.message); } finally { rutaLista = l; rutaSync(); } }
  else if (a === "buscar") buscarIr(b);
  else { fsel = undefined; ir("home"); }
  } finally { rutaRep = false; }
}
addEventListener("popstate", () => rutaIr());
const cierraPal = () => document.querySelector("dialog.pal")?.close();
addEventListener("hashchange", cierraPal); addEventListener("popstate", cierraPal);

// ---------- raíl izquierdo (plegable: iconos + texto → solo iconos; en móvil, panel) ----------
function pintarSide() {
  const r = vistaAct, cnt = c => todas.filter(m => (m.carpeta || "") === c).length, sin = todas.some(m => !m.carpeta);
  const pend = Object.values(RES).reduce((s, x) => s + (x?.pend || 0), 0);
  const a = (h, k, t, on, n) => el("a", {href: h, className: "nav", title: t, "aria-current": on ? "page" : "false"}, ico(k), el("span", {className: "rt", textContent: t}), el("span", {className: "c", textContent: n || ""}));
  $("side").replaceChildren(
    a("#/", "inicio", "Inicio", r === "home" && fsel === undefined), a("#/biblioteca", "bib", "Biblioteca", r === "bib", todas.length),
    a("#/pendientes", "pend", "Pendientes", r === "pend", pend), a("#/enviar", "env", "Enviar", r === "enviar"),
    el("div", {className: "t"}, el("span", {className: "rt", textContent: cap(pl(nm("carpeta")))})),
    ...carpetas.map(c => soltable(a("#/p/" + enc(c), "proy", c, r === "home" && fsel === c, cnt(c)), c)),
    ...(sin ? [soltable(a("#/p/", "proy", sinC(), r === "home" && fsel === "", cnt("")), "")] : []),
    el("button", {type: "button", className: "nav m", title: cap(nm("carpeta")) + " nuevo", onclick: () => { if (vistaAct !== "home") irInicio(); nuevaCarpeta(); }}, ico("mas"), el("span", {className: "rt", textContent: "Nuevo"})),
    el("span", {className: "grow"}),
    ...(GR.activa ? [el("button", {type: "button", className: "nav rec", title: "Grabando", onclick: () => grabarAbrir()}, ico("rec"), el("span", {className: "rt", textContent: "Grabando…"}))] : []),
    a("#/ajustes/general", "aj", "Ajustes", r === "ajustes"));
}
const railToggle = () => {
  if (matchMedia("(max-width: 860px)").matches) document.body.classList.toggle("rail-open");
  else { document.body.classList.toggle("rail-min"); lsSet("rail-min", document.body.classList.contains("rail-min")); }
  $("rail-t").setAttribute("aria-expanded", document.body.classList.contains("rail-open") || !document.body.classList.contains("rail-min") && !matchMedia("(max-width: 860px)").matches);
};
$("rail-t").onclick = railToggle;
document.body.classList.toggle("rail-min", !!lsGet("rail-min", false));
$("b-ajustes").hidden = false;
$("inicio").onclick = null;  // enlace normal a #/

// ---------- omnibox: buscar o preguntar (tecla /), alcance todo | proyecto | documento ----------
function omniScope() {
  const s = $("omni-c"), v = s.value, p = vistaAct === "home" && fsel ? fsel : vistaAct === "res" && cur?.carpeta ? cur.carpeta : "";
  s.replaceChildren(new Option("Todo", ""), ...(p ? [new Option(p, "p:" + p)] : []), ...(vistaAct === "res" && cur ? [new Option("Este documento", "d:" + cur.id)] : []));
  if ([...s.options].some(o => o.value === v)) s.value = v;
}
$("omni").onsubmit = e => { e.preventDefault(); const q = $("buscar").value.trim(); if (!q) return; if (location.hash === "#/buscar/" + enc(q)) buscarIr(q); else location.hash = "#/buscar/" + enc(q); };
addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); paleta(); }
  else if (e.key === "/" && !editable(e.target) && !document.querySelector("dialog[open]")) { e.preventDefault(); $("buscar").focus(); $("buscar").select(); }
  else if (e.key.toLowerCase() === "n" && !e.ctrlKey && !e.metaKey && !e.altKey && !editable(e.target) && !document.querySelector("dialog[open]")) { e.preventDefault(); formNuevo(); }
});
// «+ Añadir» se contrae a icono al bajar en vistas largas
let scrT = 0; addEventListener("scroll", () => { if (!scrT) scrT = requestAnimationFrame(() => { scrT = 0; document.body.classList.toggle("scr", scrollY > 160); }); }, {passive: true});

// ---------- Buscar (resultado del omnibox): respuesta con citas, fragmentos y elementos ----------
const BQ = {q: "", tipo: ""};
const esPregunta = q => /[?¿]/.test(q) || /^(qu[eé]|qui[eé]n|cu[aá]ndo|c[oó]mo|d[oó]nde|por qu[eé]|cu[aá]l|cu[aá]nt)/i.test(q);
async function buscarIr(q) {
  BQ.q = q; $("buscar").value = q; const sc = $("omni-c").value, c = sc.startsWith("p:") ? sc.slice(2) : "", d = sc.startsWith("d:") ? sc.slice(2) : "";
  if (vistaAct !== "buscar") vista("buscar"); else rutaSync();
  document.title = q + " · Buscar · Actas"; $("bus-t").textContent = "Resultados de «" + q + "»";
  const chip = (v, t) => el("button", {type: "button", className: "fchip", "aria-pressed": BQ.tipo === v, textContent: t, onclick: () => { BQ.tipo = v; buscarIr(q); }});
  $("bus-f").replaceChildren(el("div", {className: "row wrap", role: "group", ariaLabel: "Tipo"}, chip("", "Todo"), ...Object.entries(KIND_T).map(([k, t]) => chip(k, t)),
    chip("tarea", "Tareas"), chip("decision", "Decisiones"), chip("requisito", "Requisitos"), chip("riesgo", "Riesgos")),
    el("small", {textContent: sc ? "En: " + $("omni-c").selectedOptions[0].text + " · cambia el alcance junto al buscador" : "En todo · elige un proyecto junto al buscador para acotar"}));
  const skI = () => el("li", {className: "bus-i", "aria-hidden": "true"}, ...sk(3));
  $("bus-fr").replaceChildren(skI(), skI(), skI()); $("bus-el").replaceChildren(skI()); $("bus-fr").setAttribute("aria-busy", "true");
  let r;
  try { r = await api("/api/buscar?" + new URLSearchParams({q, c, tipo: BQ.tipo, limit: 40})); }
  catch { r = {fragmentos: todas.filter(m => (!c || m.carpeta === c) && norm(m.label + " " + m.carpeta).includes(norm(q))).map(m => ({doc: m.id, titulo: m.label, c: m.carpeta, kind: m.kind, snippet: ""})), elementos: []}; }
  if (BQ.q !== q) return;
  const fr = r.fragmentos.filter(f => !d || f.doc === d), els = r.elementos.filter(x => !d || x.doc === d);
  $("bus-fr").replaceChildren(...(fr.length ? fr.map(f => {
    const loc = f.loc || (f.t != null ? mmss(f.t) : ""), go = () => fallo(citaDoc)(f.doc, f.t, f.loc);
    const p = el("p", {className: "bus-s"}); p.innerHTML = f.snippet || "";  // el servidor escapa el HTML y solo añade <mark>
    return el("li", {className: "bus-i"}, el("div", {className: "row wrap"}, el("button", {type: "button", className: "doc-l", textContent: f.titulo || f.doc, onclick: go}),
      ...(loc ? [el("button", {type: "button", className: "cite", textContent: loc, onclick: go})] : []), el("span", {className: "muted", textContent: [KIND_T[f.kind] || f.tipo_fuente, f.c].filter(Boolean).join(" · ")})), p);
  }) : [el("li", {className: "muted", textContent: "Sin fragmentos."})])); $("bus-fr").removeAttribute("aria-busy"); escalona($("bus-fr"), true); escalona($("bus-el"), true);
  $("bus-el").replaceChildren(...(els.length ? els.map(x => el("li", {className: "bus-i"}, el("div", {className: "row wrap"}, badgeT(TIPO_T[x.tipo] || x.tipo, "acc"), el("b", {textContent: (x.codigo ? x.codigo + " · " : "") + x.texto})),
    el("small", {}, [x.estado, x.c].filter(Boolean).join(" · ") + " · ", el("a", {href: "#", textContent: "Abrir en el proyecto", onclick: ev => { ev.preventDefault(); irElemento(x.c, x.tipo, x.id); }})))) : [el("li", {className: "muted", textContent: "Sin elementos."})]));
  // Respuesta: el mismo panel de Preguntar, en el proyecto o documento del alcance (o en el del mejor fragmento)
  const docs = d ? [] : carpetas, s = el("select", {ariaLabel: "Preguntar en"}, ...(d ? [new Option("Este documento", "d")] : []), ...docs.map(x => new Option(x, "c:" + x)), ...(!d && todas.some(m => !m.carpeta) ? [new Option(sinC(), "c:")] : []));
  s.value = d ? "d" : "c:" + (c || fr[0]?.c || carpetas[0] || "");
  const preguntar = () => { if (s.value === "d") { const a = cur.actas.find(x => x.name === ver) || cur.actas[0]; setQ(cur.id + "|" + (a?.asr || cur.asr)); } else setQ(s.value); $("pregunta").value = q; $("qform").requestSubmit(); };
  $("bus-resp").hidden = !s.options.length;
  $("bus-q").replaceChildren(el("div", {className: "row wrap"}, el("label", {className: "muted", textContent: "Preguntar en"}), s, el("button", {type: "button", className: "sec", textContent: "Preguntar «" + q.slice(0, 40) + "»", onclick: preguntar})), $("qpanel"));
  $("qpanel").hidden = true;
  if (esPregunta(q) && s.options.length) { $("qpanel").hidden = false; preguntar(); }
}
function irElemento(c, tipo, id) { fsel = c; vista("home"); fIr(TIPO_TAB[tipo] || "revision", {ids: [id]}); }

// ---------- citas → fuente: [mm:ss] al vídeo; p. 12 / § Título a la pestaña Fuente ----------
let FUENTE = null;
async function citaDoc(id, t, loc) {
  if (!cur || cur.id !== id || vistaAct !== "res") await abrir(id);
  if (!cur || cur.id !== id) return;
  if (t != null) citaIr(t, loc);
}
function citaIr(t, loc) {
  if (cur.video) return mpSeek(t, cur.videourl, cur.m.label);
  tab("p-video");
  const salta = () => { const ss = [...$("p-fuente").querySelectorAll(".fu-s")]; const s = ss.find(x => x.dataset.loc === loc) || ss.filter(x => +x.dataset.t <= t).pop() || ss[0]; if (s) { s.closest("details").open = true; fResalta([s]); } };
  FUENTE?.id === cur.id ? salta() : docFuente().then(salta);
}

// ---------- Documento: barra de acciones, Extraído y Fuente ----------
const DST = {p: null};  // nombres de presets y destinos para «Enviar a X»
async function nombresDst() { if (!DST.p) DST.p = Promise.all([api("/api/destinos").catch(() => ({destinos: []})), api("/api/presets").catch(() => [])]).then(([d, p]) => Object.fromEntries([...d.destinos.map(x => ["d:" + x.id, x.nombre]), ...p.map(x => ["p:" + x.id, x.nombre])])); return DST.p; }
async function envLbl() { const u = lsGet("env.ultimo", null), n = u && (await nombresDst())[u]; $("d-env").textContent = n ? "Enviar a " + n : "Enviar…"; $("d-env").title = n ? "Último destino (1 clic). ▾ para elegir otro." : "Elegir a dónde enviar"; }
async function envUltimo(sel) {
  if (!window.Enviar) return sinEnviar();
  const u = lsGet("env.ultimo", null), n = u && (await nombresDst())[u];
  if (!n) return Enviar.enviar(sel);
  const r = await post("/api/enviar", {...(u.startsWith("p:") ? {preset: u.slice(2)} : {destino: u.slice(2), que: ["documento"]}), ...sel});
  aviso(r.estado === "ok" ? "Enviado a " + n : "Envío: " + r.estado + (r.error ? " — " + r.error : ""));
}
const docSel = () => ({doc: cur.id + "/" + ver});
$("d-preg").onclick = () => tab("p-preg");
$("d-env").onclick = fallo(() => envUltimo(docSel()));
$("d-env-m").onclick = () => window.Enviar ? Enviar.enviar(docSel()) : sinEnviar();
$("d-aproy").onclick = () => aProyecto([cur.id]);
$("d-anon").onclick = () => abrirAnon(null);
$("d-cond").onclick = () => { tab("p-video"); $("cond").scrollIntoView({block: "start"}); };
$("d-desc").onclick = () => window.Descargar ? Descargar.abrir({docs: [cur.id + (ver ? "/" + ver : "")]}) : sinEnviar();
$("d-dud").onclick = () => { if ($("dud-bar").hidden) return aviso("No hay frases dudosas en este documento"); tab("p-acta"); $("dud-sig").click(); };
document.addEventListener("click", e => { const it = e.target.closest(".menu .pop [role=menuitem]"); if (it) it.closest("details").open = false; });
function docTab(p) {  // lo llama tab() de app.js
  $("d-cond").hidden = !cur.video || !!cur.solo; envLbl();
  if (p === "p-ext" && !cur.solo) docExt();
  if (p === "p-video") docFuente();
}
async function docExt() {
  const w = $("p-ext"), id = cur.id, c = cur.carpeta || "";
  w.replaceChildren(el("p", {className: "muted", textContent: "Cargando…"}));
  const [reg, pen] = await Promise.all([api("/api/reg?" + new URLSearchParams({c})).catch(() => ({items: []})), api("/api/exp/pendientes?" + new URLSearchParams({c})).catch(() => ({items: []}))]);
  if (cur.id !== id) return;
  const regT = reg.items.some(x => x.tipo === "tarea");  // si el registro ya tiene las tareas, los pendientes serían duplicados
  const its = [...pen.items.filter(p => !regT && p.mid === id).map(p => ({tipo: "tarea", titulo: p.texto, estado: p.estado, dueno: p.resp, extra: p.plazo, t: p.t})),
    ...reg.items.filter(x => x.citas?.some(q => q.mid === id)).map(x => ({tipo: x.tipo, id: x.id, codigo: x.codigo, titulo: x.titulo, estado: x.estado, rev: x.revision, dueno: x.dueno, t: x.citas.find(q => q.mid === id).t}))];
  $("t-ext").textContent = "Extraído" + (its.length ? " (" + its.length + ")" : "");
  const grupos = Object.keys(TIPO_T).map(k => [k, its.filter(x => x.tipo === k)]).filter(([, l]) => l.length);
  w.replaceChildren(...(grupos.length ? grupos.map(([k, l]) => el("section", {className: "card ext-g"}, H(TIPO_T[k] + " · " + l.length, ...(c ? [el("button", {className: "link", textContent: "Abrir en el proyecto", onclick: () => irElemento(c, k, l[0].id)})] : [])),
    el("ul", {className: "f-lst"}, ...l.map(x => el("li", {}, ...(x.rev === "propuesto" ? [badgeT("Por revisar", "w"), " "] : []), (x.codigo ? x.codigo + " · " : "") + x.titulo,
      [x.dueno, x.extra, x.estado].filter(Boolean).map(v => " · " + v).join(""), " ", ...(x.t != null ? [el("button", {type: "button", className: "cite", textContent: FUENTE?.id === id ? locDe(x.t) : mmss(x.t), onclick: () => citaIr(x.t)})] : []))))))
    : [el("p", {className: "vacio", textContent: c ? "Todavía no se ha extraído nada de este documento." : "Mueve el documento a un " + nm("carpeta").toLowerCase() + " para extraer tareas, decisiones y requisitos con su cita."})]));
}
const locDe = t => (FUENTE?.partes || []).filter(p => p.t <= t).pop()?.loc || mmss(t);
async function docFuente() {
  const w = $("p-fuente"), id = cur.id;
  if (FUENTE?.id === id) return;
  w.replaceChildren(el("p", {className: "muted", textContent: "Cargando la fuente…"}));
  let f; try { f = await api("/api/fuente/" + id); } catch (x) { w.replaceChildren(el("p", {className: "muted", textContent: x.message})); return; }
  if (cur.id !== id) return;
  FUENTE = {...f, id}; if (cur.solo && cur.m.label === id && f.nombre) { cur.m.label = f.nombre; $("cab-titulo").textContent = f.nombre; document.title = f.nombre + " · Actas"; }  // la lista no incluye los solo buscables
  const media = f.kind === "video" || f.kind === "audio";
  const sec = p => el("section", {className: "fu-s", "data-t": p.t ?? 0, "data-loc": p.loc || ""}, el("h3", {}, media ? el("a", {href: "#", className: "ts", textContent: mmss(p.t || 0), onclick: e => { e.preventDefault(); mpSeek(p.t || 0, cur.videourl, cur.m.label); }}) : p.loc || ""), el("p", {textContent: p.texto}));
  const ia = el("button", {type: "button", className: "sec sm", textContent: f.kind === "imagen" ? "Describir con IA" : "Describir capturas con IA",
    onclick: fallo(async () => { await post("/api/describir", {id, gpu: $("usar-gpu").checked}); aviso("Añadido a la cola"); sondear(); FUENTE = null; })});
  const nodos = [el("div", {className: "row wrap fu-h"}, el("b", {textContent: f.nombre || ""}), ...(f.paginas ? [el("span", {className: "muted", textContent: f.paginas + " págs."})] : []),
    el("span", {className: "grow"}), ...(f.url && !media ? [el("a", {className: "btn sec sm", href: f.url, target: "_blank", rel: "noopener", textContent: "Abrir el original"})] : []), ...(f.kind !== "audio" && f.kind !== "pdf" && f.kind !== "texto" ? [ia] : [])),
    ...(f.vision === "no_disponible" && (f.kind === "imagen" || f.kind === "video") ? [el("p", {className: "aviso w"}, "Sin modelo con visión: las imágenes no se describen solas. ", el("a", {href: "#/ajustes/modelos", textContent: "Instalar uno recomendado"}), " o configúralo en ", el("a", {href: "#/ajustes/avanzado", textContent: "Ajustes › Avanzado"}), ".")] : [])];
  if (f.kind === "imagen") {
    const du = el("textarea", {rows: 3, value: f.descripcion || "", id: "fu-du"}), dia = el("textarea", {rows: 3, value: f.descripcion_ia || "", id: "fu-dia"});
    nodos.push(el("div", {className: "fu-img"}, el("img", {src: f.url, alt: f.descripcion || f.descripcion_ia || f.nombre || "Imagen"}),
      el("div", {}, el("div", {className: "field"}, el("label", {htmlFor: "fu-du", textContent: "Tu descripción"}), du), el("div", {className: "field"}, el("label", {htmlFor: "fu-dia", textContent: "Descripción de la IA"}), dia),
        el("button", {type: "button", className: "pri sm", textContent: "Guardar descripciones", onclick: fallo(async () => { await post("/api/imagen/" + id, {descripcion: du.value, descripcion_ia: dia.value}); aviso("Guardado: ya se puede buscar"); })}))),
      ...(f.ocr_texto ? [el("details", {open: true}, el("summary", {textContent: "Texto reconocido (OCR)"}), el("pre", {className: "fu-ocr", textContent: f.ocr_texto}))] : []));
  }
  if (f.partes?.length) nodos.push(el("details", {open: !media}, el("summary", {textContent: (media ? "Transcripción · " : "Texto · ") + f.partes.length + (media ? " tramos" : " partes")}), el("div", {className: "fu-p"}, ...f.partes.map(sec))));
  w.replaceChildren(...nodos);
}

// ---------- Añadir: hoja con archivos, objetivo («¿Qué quieres sacar y dónde?»), proyecto y ajustes de procesado plegados ----------
const AN = {files: [], plan: null, defecto: [], goal: lsGet("an.goal", ""), buscable: false};
const IMG_RE = /\.(png|jpe?g|webp)$/i, TXT_RE = /\.(pdf|md|txt|docx|html?)$/i, TR_RE = /\.(vtt|srt)$/i;
const GOALS = [
  {id: "acta", t: "Acta de reunión", d: "Tareas y decisiones", p: "acta", q: ["tareas", "decisiones"]},
  {id: "req", t: "Requisitos e historias", d: "Para el equipo de producto", p: "requisitos", q: ["requisitos", "historias"]},
  {id: "res", t: "Resumen y puntos clave", d: "Lo esencial, con citas", p: "video", q: ["resumen"]},
  {id: "seg", t: "Seguimiento / informe", d: "Tareas, decisiones y riesgos", p: "raid", q: ["tareas", "decisiones", "riesgos"]},
  {id: "ent", t: "Entrevista", d: "Respuestas y citas", p: "periodistica", q: ["resumen"]},
  {id: "cla", t: "Apuntes de clase", d: "Conceptos y resumen", p: "clase", q: ["resumen"]},
  {id: "bus", t: "Solo hacerlo buscable", d: "Sin resumir: barato, ideal para PDF grandes", b: true, q: []},
  {id: "otro", t: "Otro…", d: "Todas las plantillas"}];
function anGoals() {
  const uso = new Set(AJ.perfil_uso || []), gs = [...GOALS].sort((a, b) => (b.p && uso.has(b.p)) - (a.p && uso.has(a.p)));
  $("an-goals").replaceChildren(...gs.map(g => el("button", {type: "button", className: "goal", "aria-pressed": AN.goal === g.id, onclick: () => anGoal(g.id, true)}, el("b", {textContent: g.t}), el("small", {textContent: g.d}))));
}
function anGoal(id, user) {
  const g = GOALS.find(x => x.id === id); AN.goal = g ? id : ""; if (user) lsSet("an.goal", AN.goal);
  AN.buscable = !!g?.b;
  if (g?.p) { if (![...$("plantilla").options].some(o => o.value === g.p) && PL.some(t => t.id === g.p)) $("plantilla").append(new Option(plantDe(g.p).nombre, g.p)); if (PL.some(t => t.id === g.p)) { $("plantilla").value = g.p; $("plantilla").onchange(); } }
  if (id === "otro" && user) { const v = $("plantilla").value; $("plantilla").replaceChildren(...PL.map(t => new Option(t.nombre, t.id))); $("plantilla").value = v; $("plantilla").focus(); }
  anCheck(); anGoals(); anBoton();
}
const anChips = () => !!window.Enviar?.presetsObjetivo;  // los objetivos van como chips dentro del checklist (enviar.js): sin la fila de tarjetas
function anCheck() {  // casillas «qué → dónde»: las del proyecto (sus recetas) + las del objetivo
  const g = GOALS.find(x => x.id === AN.goal), q = g?.q || [], c = $("n-carpeta").value === NUEVA_C ? "" : $("n-carpeta").value;
  $("an-goals").hidden = anChips();
  if (anChips()) {  // «Solo hacerlo buscable» llega como plan.solo_buscable → el trabajo va con buscable
    AN.plan = {carpeta: c, salidas: [...AN.defecto]}; AN.buscable = false;
    return Enviar.checklist($("an-check"), {plan: AN.plan, carpeta: c, onChange: p => { AN.plan = {...p, carpeta: c}; AN.buscable = !!p.solo_buscable;
      if (p.plantilla && PL.some(t => t.id === p.plantilla)) { if (![...$("plantilla").options].some(o => o.value === p.plantilla)) $("plantilla").append(new Option(plantDe(p.plantilla).nombre, p.plantilla)); $("plantilla").value = p.plantilla; $("plantilla").onchange(); }
      anBoton(); }});
  }
  AN.plan = {carpeta: c, salidas: g?.b ? [] : [...AN.defecto, ...q.filter(k => !AN.defecto.some(s => s.que === k)).map(k => ({que: k, como: "documento"}))]};
  if (!window.Enviar) { $("an-check").replaceChildren(el("p", {className: "muted", textContent: "Se extraerá: " + (q.join(", ") || "solo el documento") + "."})); AN.plan = null; return; }
  $("an-check").replaceChildren(...(g?.b ? [el("p", {className: "muted", textContent: "Se lee y se indexa sin resumir: luego lo encuentras con Buscar y Preguntar."})] : []));
  if (!g?.b) Enviar.checklist($("an-check"), {plan: AN.plan, carpeta: c, onChange: p => { AN.plan = p; anBoton(); }});
}
async function anProyecto() {
  const c = $("n-carpeta").value; AN.defecto = [];
  if (c && c !== NUEVA_C && window.Enviar) AN.defecto = ((await api("/api/carpetas/" + enc(c) + "/plan_defecto").catch(() => null))?.salidas || []).map(({receta, ...s}) => s);
  anCheck();
}
function anAdd(path, extra = {}) {
  if (!path || AN.files.some(f => f.path === path)) return;
  if (TR_RE.test(path)) return setTr(path);
  AN.files.push({path, name: path.split(/[\\/]/).pop(), img: IMG_RE.test(path), ...extra}); anRuta(); anPintar();
}
const anRuta = () => { const p = AN.files.find(f => f.path)?.path || ""; if (p !== ruta) setRuta(p); };
const stamp = () => new Date().toISOString().slice(0, 19).replace(/\D/g, "");
async function anSubir(files) {
  if (!$("v-nuevo").open) formNuevo();
  for (const f0 of files) {
    const f = f0.name === "image.png" ? new File([f0], "captura-" + stamp() + ".png", {type: f0.type}) : f0;
    const it = {path: "", name: f.name, img: IMG_RE.test(f.name) || f.type.startsWith("image/"), subiendo: true};
    if (!TR_RE.test(f.name)) { AN.files.push(it); anPintar(); }
    try { const p = (await api("/api/upload?name=" + enc(f.name), {method: "PUT", body: f})).path; if (TR_RE.test(f.name)) setTr(p); else it.path = p; }
    catch (x) { it.err = x.message; }
    it.subiendo = false; anRuta(); anPintar();
  }
}
function anPintar() {
  const ok = AN.files.filter(f => f.path);
  $("an-files").replaceChildren(...AN.files.map(f => el("li", {className: f.err ? "err" : ""}, el("span", {className: "badge", textContent: f.img ? "Imagen" : /\.zip$/i.test(f.name) ? "Zip" : /\.(eml|msg)$/i.test(f.name) ? "Correo" : TXT_RE.test(f.name) ? "Documento" : "Vídeo/audio"}),
    el("span", {className: "n", textContent: f.name}), el("small", {textContent: f.subiendo ? "Copiando…" : f.err || ""}),
    el("button", {type: "button", className: "qx", textContent: "✕", ariaLabel: "Quitar " + f.name, onclick: () => { AN.files.splice(AN.files.indexOf(f), 1); anRuta(); anPintar(); }}))));
  $("an-desc-w").hidden = !AN.files.some(f => f.img);
  const enl = $("enlace").value.trim();
  $("an-tc-w").hidden = !(ok.length ? ok.every(f => TXT_RE.test(f.name)) : /\.(pdf|md|txt|docx|html?)(\?|$)/i.test(enl));
  anBoton();
}
function anBoton() {
  const n = AN.files.filter(f => f.path).length + ($("enlace").value.trim() ? 1 : 0), t = plantDe($("plantilla").value);
  $("generar").textContent = reuse ? "Generar " + (t?.documento?.singular || "documento") : AN.buscable ? "Hacer buscable" + (n > 1 ? " " + n + " archivos" : "") : n > 1 ? "Procesar " + n + " archivos" : "Procesar";
  $("generar").disabled = AN.files.some(f => f.subiendo);
  const s = AN.plan?.salidas || [];
  $("an-res").textContent = reuse ? "" : AN.buscable ? "Solo buscable: sin resumen ni extracción" : s.length ? s.length + (s.length === 1 ? " salida: " : " salidas: ") + s.map(x => x.que).join(", ") : "";
}
const anParams = dest => ({buscable: !reuse && AN.buscable, descripcion: $("an-desc").value.trim(), tal_cual: !reuse && !$("an-tc-w").hidden && $("an-tc").checked,
  ...(!reuse && AN.plan ? {plan: {...AN.plan, carpeta: dest, plantilla: $("plantilla").value, ...($("an-nombre").value.trim() ? {nombre: $("an-nombre").value.trim()} : {}), ...(AN.buscable ? {solo_buscable: true} : {})}} : {})});
function anLimpiar() { AN.files = []; setRuta(""); setTr(""); $("enlace").value = ""; $("enlace").oninput(); $("an-desc").value = ""; $("an-tc").checked = false; $("an-nombre").value = ""; anPintar(); }
function anEnlace(u) { if (!$("v-nuevo").open) formNuevo(); $("enlace").value = u; $("enlace").oninput(); }
async function anPegar() {
  try {
    for (const it of await navigator.clipboard.read()) { const t = it.types.find(x => x.startsWith("image/")); if (t) { const b = await it.getType(t); await anSubir([new File([b], "captura-" + stamp() + "." + t.split("/")[1], {type: t})]); $("an-desc").focus(); return; } }
    aviso("No hay ninguna imagen en el portapapeles");
  } catch { if (!$("v-nuevo").open) formNuevo(); aviso("Pulsa Ctrl+V para pegar la captura"); }
}
// la hoja: abrirla monta el objetivo y el plan del proyecto; «Otra versión» (reuse) solo enseña tipo y ajustes
const formNuevo1 = formNuevo;
formNuevo = function (m, a) {
  formNuevo1(m, a);
  $("an-obj").hidden = $("an-nombre").closest(".field").hidden = !!m; $("an-av").open = !!m; $("form-t").textContent = m ? $("form-t").textContent : "Añadir";
  if (!m) { anGoals(); if (AN.goal && !anChips()) anGoal(AN.goal); anProyecto(); }
  anPintar();
};
$("n-carpeta").addEventListener("change", anProyecto);
$("an-x").onclick = () => $("v-nuevo").close();
$("an-cancel").onclick = () => { anLimpiar(); $("v-nuevo").close(); };
$("an-elegir").onclick = () => $("an-file").click();
$("an-file").onchange = () => { anSubir([...$("an-file").files]); $("an-file").value = ""; };
$("an-pegar").onclick = anPegar;
$("enlace").addEventListener("input", anPintar);
$("nueva").onclick = () => formNuevo();
// Inicio: zona grande de soltar
$("h-elegir").onclick = () => { formNuevo(); $("an-file").click(); };
$("h-pegar").onclick = anPegar;
$("h-grabar").onclick = () => grabarAbrir();
$("h-enl").onsubmit = e => { e.preventDefault(); const u = $("h-enl-i").value.trim(); if (u) { anEnlace(u); $("h-enl-i").value = ""; } };
// toda la ventana acepta soltar archivos o enlaces (no los arrastres internos de documentos a proyectos) y pegar capturas o enlaces
const arrastreExt = e => !arrastrando && [...(e.dataTransfer?.types || [])].some(t => t === "Files" || t === "text/uri-list");
addEventListener("dragover", e => { if (arrastreExt(e)) { e.preventDefault(); document.body.classList.add("soltando"); } });
addEventListener("dragleave", e => { if (!e.relatedTarget) document.body.classList.remove("soltando"); });
addEventListener("drop", e => {
  document.body.classList.remove("soltando");
  if (!arrastreExt(e) || e.defaultPrevented) return;
  e.preventDefault(); const fs = [...e.dataTransfer.files], u = (e.dataTransfer.getData("text/uri-list") || "").split("\n")[0].trim();
  if (fs.length) anSubir(fs); else if (/^https?:\/\//i.test(u)) anEnlace(u);
});
addEventListener("paste", e => {
  const fs = [...(e.clipboardData?.files || [])];
  if (fs.length) { e.preventDefault(); anSubir(fs); return; }
  const t = (e.clipboardData?.getData("text") || "").trim();
  if (!editable(e.target) && /^https?:\/\/\S+$/i.test(t)) { e.preventDefault(); anEnlace(t); }
});

// ---------- Inicio: tira del flujo, Continúa, Por revisar ----------
const INI = {p: null, t: 0};
function iniDatos() {
  if (INI.p && Date.now() - INI.t < 30000) return INI.p;
  INI.t = Date.now();
  return INI.p = Promise.all([Promise.all(carpetas.slice(0, 12).map(c => api("/api/reg?" + new URLSearchParams({c})).then(r => ({c, r})).catch(() => null))),
    api("/api/envios?limit=200").catch(() => [])]).then(([regs, env]) => ({regs: regs.filter(Boolean), env}));
}
function pintarInicio() {
  const vacio = !todas.length && !cola.items.length, act = cola.items.filter(e => ACT.includes(e.state)), run = act.find(e => e.state === "marcha");
  $("h-flujo").hidden = $("h-cont").hidden = vacio;
  const pl0 = lsGet("an.goal", ""), g = GOALS.find(x => x.id === pl0);
  $("h-receta").replaceChildren(el("span", {className: "muted", textContent: "Al terminar: "}), g ? g.t + (g.q?.length ? " (" + g.q.join(", ") + ")" : "") : "el documento y lo que digan las recetas del proyecto", " · ",
    el("button", {type: "button", className: "link", textContent: "Cambiar", onclick: () => formNuevo()}));
  // Continúa: lo que se está procesando y lo último
  const nuevas = act.filter(e => e.kind === "acta" && !e.mid).map(e => el("div", {className: "h-ci"}, el("span", {className: "n"}, el("b", {textContent: e.video}), el("small", {textContent: "Procesando"})),
    badgeT(e.state === "marcha" ? "Procesando " + Math.round(e.frac * 100) + " %" : "En cola", "acc")));
  const recientes = todas.slice(0, 6).map(m => { const e = act.find(x => x.mid === m.id), r = RES[m.carpeta || ""] || {};
    return el("button", {type: "button", className: "h-ci", onclick: fallo(() => abrir(m.id))}, el("span", {className: "n"}, el("b", {textContent: m.label}),
      el("small", {textContent: [m.carpeta || sinC(), fechaC(m.mtime), m.dur ? Math.round(m.dur / 60) + " min" : KIND_T[m.kind]].filter(Boolean).join(" · ")})),
      e ? badgeT(e.state === "marcha" ? "Procesando" : "En cola", "acc") : r.sug ? badgeT(r.sug + " por revisar", "w") : badgeT("Listo", "ok")); });
  $("h-cont-l").replaceChildren(...nuevas, ...recientes); escalona($("h-cont-l"));
  // tira del flujo (contadores clicables); los del registro y los envíos llegan después
  const tile = (n, t, v, s, f) => el("button", {type: "button", className: "fl", onclick: f}, el("span", {className: "fl-t", textContent: n + " · " + t}), v == null ? el("b", {className: "sk sk-n", "aria-label": "Cargando"}) : el("b", {textContent: v}), el("small", {textContent: s}));
  const pinta = (rev, apr, hoy, ult) => $("h-flujo").replaceChildren(
    tile(1, "En cola", act.length, run ? "Procesando: " + nombreDe(run) : act.length ? "Esperando turno" : "Nada en marcha", () => { location.hash = "#/cola"; }),
    tile(2, "Por revisar", rev, "Elementos extraídos sin aprobar", () => $("rev").scrollIntoView({block: "start"})),
    tile(3, "Listo para enviar", apr, "Elementos aprobados", () => { location.hash = "#/enviar"; }),
    tile(4, "Enviado hoy", hoy, ult || "Historial en Enviar", () => { location.hash = "#/enviar"; }));
  pinta();
  // sugerencias: lo listo de la cola ya; lo del registro cuando llega (mismo hueco: esqueleto si la última vez hubo)
  const listo = cola.items.filter(e => e.kind === "acta" && e.state === "hecho" && e.mid && todas.some(m => m.id === e.mid)).pop();
  sugerencias(listo ? [{k: "doc:" + listo.mid, t: "Documento listo: " + nombreDe(listo), s: "Revísalo antes de enviarlo", b: "Abrir", f: fallo(() => abrir(listo.mid))}] : [], true);
  iniDatos().then(({regs, env}) => {
    if (vistaAct !== "home" || fsel !== undefined) return;
    const rev = regs.flatMap(({c, r}) => r.items.filter(x => x.revision === "propuesto").map(x => ({...x, c}))), apr = regs.reduce((s, {r}) => s + (r.contadores?.por_revision?.aprobado || 0), 0);
    const hoy = env.filter(e => e.estado === "ok" && e.t * 1000 >= new Date().setHours(0, 0, 0, 0)), u = hoy[0];
    pinta(rev.length + Object.values(RES).reduce((s, x) => s + (x?.sug || 0), 0), apr, hoy.length, u ? "Última: " + (u.destino || "") + " · " + new Date(u.t * 1000).toLocaleTimeString("es", {hour: "2-digit", minute: "2-digit"}) : "");
    $("rev-reg").replaceChildren(...rev.slice(0, 6).map(x => { const ci = x.citas?.[0], d = ci && todas.find(m => m.id === ci.mid);
      return el("div", {className: "rv-i"}, badgeT(TIPO_T[x.tipo] || x.tipo, "acc"), el("span", {className: "n", textContent: x.titulo}),
        el("small", {textContent: [x.c, d && d.label + (ci.t != null ? " · " + mmss(ci.t) : "")].filter(Boolean).join(" · ")}),
        el("button", {type: "button", className: "sec sm", textContent: "Revisar", onclick: () => { fsel = x.c; vista("home"); fIr("revision", {ids: [x.id]}); }})); }));
    $("rev-acc").replaceChildren(...(rev.length ? [el("button", {type: "button", className: "sec sm", textContent: "Aprobar todo (" + rev.length + ")", onclick: fallo(async () => {
      const cs = [...new Set(rev.map(x => x.c))];
      for (const c of cs) await post("/api/reg/revisar", {c, ids: rev.filter(x => x.c === c).map(x => x.id), accion: "aprobar"});
      INI.p = null; aviso(rev.length + " aprobados", {txt: "Deshacer", fn: fallo(async () => { for (const c of cs) await post("/api/reg/deshacer", {c}); INI.p = null; pintarHome(); })}); pintarHome();
    })})] : []));
    if (rev.length) $("rev").hidden = false;
    const n = rev.length + Object.values(RES).reduce((s, x) => s + (x?.sug || 0), 0), c0 = rev[0]?.c ?? Object.keys(RES).find(c => RES[c]?.sug);
    sugerencias([...(n && c0 != null ? [{k: "rev:" + n, t: n + " por revisar", s: "Propuestos por la IA, sin aprobar", b: "Revisar", w: 1, f: () => { fsel = c0; vista("home"); fIr("revision"); }}] : []),
      ...(apr ? [{k: "env:" + apr, t: apr + (apr === 1 ? " elemento listo" : " elementos listos") + " para enviar", s: "Aprobados y sin enviar", b: "Enviar", f: () => { location.hash = "#/enviar"; }}] : []),
      ...(listo ? [{k: "doc:" + listo.mid, t: "Documento listo: " + nombreDe(listo), s: "Revísalo antes de enviarlo", b: "Abrir", f: fallo(() => abrir(listo.mid))}] : [])]);
  });
}
// Inicio › Sugerencias: tarjetas descartables (lo descartado vuelve si cambia: la clave lleva el número o el documento)
function sugerencias(l, prov, anim = !prov) {  // prov: lista provisional (falta el registro): esqueleto si la última vez hubo sugerencias
  const fuera = lsGet("ini.sug.x", []), vis = l.filter(x => !fuera.includes(x.k)), esperando = prov && INI.nSug > 0;
  if (!prov) INI.nSug = vis.length;
  $("h-sug").replaceChildren(...vis.map(x => el("div", {className: "sug-c" + (x.w ? " w" : "")}, el("span", {className: "n"}, el("b", {textContent: x.t}), el("small", {textContent: x.s})),
    el("button", {type: "button", className: "sec sm", textContent: x.b, onclick: x.f}),
    el("button", {type: "button", className: "qx", textContent: "✕", ariaLabel: "Descartar: " + x.t, title: "Descartar", onclick: () => { lsSet("ini.sug.x", [...fuera, x.k].slice(-40)); sugerencias(l, false, false); $("h-sug").querySelector(".qx")?.focus(); }}))),
    ...(esperando && !vis.length ? [el("div", {className: "sk-c", "aria-hidden": "true"}, ...sk(2))] : []));
  if (anim) escalona($("h-sug"));
}

// ---------- Biblioteca: una sola lista con chips de tipo, filtros, selección múltiple y vista previa ----------
const BIB = {ms: [], sel: new Set(), tipo: "", c: "*", est: "", dias: 0, q: "", act: null};
async function pintarBib() {
  if (!BIB.ms.length) $("bib-tb").replaceChildren(...Array.from({length: 6}, () => el("tr", {className: "sk-r", "aria-hidden": "true"}, el("td", {colSpan: 6}, el("span", {className: "sk"})))));
  BIB.ms = unicas(await api("/api/meetings").catch(() => todas)); BIB.sel = new Set([...BIB.sel].filter(id => BIB.ms.some(m => m.id === id))); pintarBibL(); }
const bibEst = m => cola.items.some(e => ACT.includes(e.state) && e.mid === m.id) ? "cola" : m.actas ? "listo" : "buscable";
function pintarBibL() {
  const ms = BIB.ms, ok = m => (!BIB.tipo || m.kind === BIB.tipo) && (BIB.c === "*" || (m.carpeta || "") === BIB.c) && (!BIB.est || bibEst(m) === BIB.est)
    && (!BIB.dias || m.mtime * 1000 > Date.now() - BIB.dias * 864e5) && (!BIB.q || norm(m.label + " " + m.carpeta).includes(norm(BIB.q)));
  const vis = ms.filter(ok), chip = (v, t, n) => el("button", {type: "button", className: "fchip", "aria-pressed": BIB.tipo === v, onclick: () => { BIB.tipo = v; pintarBibL(); }}, t, el("i", {textContent: " " + n}));
  const sel = (lab, v, ops, f) => { const s = el("select", {ariaLabel: lab, onchange: () => { f(s.value); pintarBibL(); }}, ...ops.map(([k, t]) => new Option(t, k))); s.value = v; return s; };
  const q = el("input", {type: "search", value: BIB.q, placeholder: "Filtrar por nombre", ariaLabel: "Filtrar por nombre", oninput: () => { BIB.q = q.value; pintarBibL(); q.focus(); }});
  $("bib-n").textContent = vis.length + " de " + ms.length;
  if (document.activeElement?.closest?.("#bib-f")?.type !== "search") $("bib-f").replaceChildren(
    el("div", {className: "row wrap", role: "group", ariaLabel: "Tipo"}, chip("", "Todo", ms.length), ...Object.entries(KIND_T).map(([k, t]) => [k, t, ms.filter(m => m.kind === k).length]).filter(x => x[2]).map(x => chip(...x))),
    el("div", {className: "row wrap"}, sel(cap(nm("carpeta")), BIB.c, [["*", "Todos los " + pl(nm("carpeta").toLowerCase())], ...carpetas.map(c => [c, c]), ["", sinC()]], v => BIB.c = v),
      sel("Estado", BIB.est, [["", "Cualquier estado"], ["listo", "Listo"], ["buscable", "Solo buscable"], ["cola", "En cola"]], v => BIB.est = v),
      sel("Fecha", String(BIB.dias), [["0", "Cualquier fecha"], ["1", "Hoy"], ["7", "Últimos 7 días"], ["30", "Últimos 30 días"]], v => BIB.dias = +v), q));
  else $("bib-f").querySelector("[role=group]").replaceWith(el("div", {className: "row wrap", role: "group", ariaLabel: "Tipo"}, chip("", "Todo", ms.length), ...Object.entries(KIND_T).map(([k, t]) => [k, t, ms.filter(m => m.kind === k).length]).filter(x => x[2]).map(x => chip(...x))));
  const ESTT = {listo: ["Listo", "ok"], buscable: ["Solo buscable", ""], cola: ["En cola", "acc"]};
  $("bib-tb").replaceChildren(...vis.map(m => {
    const ck = el("input", {type: "checkbox", checked: BIB.sel.has(m.id), ariaLabel: "Seleccionar " + m.label, onchange: () => { ck.checked ? BIB.sel.add(m.id) : BIB.sel.delete(m.id); bibBulk(); }});
    const tr = el("tr", {className: "f" + (BIB.act === m.id ? " on" : ""), draggable: true, ondragstart: ev => { arrastrando = m; ev.dataTransfer.effectAllowed = "move"; ev.dataTransfer.setData("text/plain", m.id); }, ondragend: () => { arrastrando = null; }},
      el("td", {}, ck), el("td", {}, el("button", {type: "button", className: "doc-l", textContent: m.label, onclick: () => bibVer(m), ondblclick: fallo(() => abrir(m.id))})),
      el("td", {textContent: KIND_T[m.kind] || m.kind || ""}), el("td", {textContent: m.carpeta || ""}), el("td", {textContent: fechaC(m.mtime)}), el("td", {}, badgeT(...ESTT[bibEst(m)])));
    return tr;
  })); escalona($("bib-tb"));
  $("bib-v").hidden = !!vis.length; $("bib-v").textContent = ms.length ? "Nada coincide con los filtros." : "Aún no hay nada. Pulsa «+ Añadir» o suelta archivos en cualquier parte.";
  $("bib-all").checked = vis.length > 0 && vis.every(m => BIB.sel.has(m.id));
  $("bib-all").onchange = () => { vis.forEach(m => $("bib-all").checked ? BIB.sel.add(m.id) : BIB.sel.delete(m.id)); pintarBibL(); };
  bibBulk();
}
function bibEnviar(ids) {  // un envío por documento; los solo buscables no tienen acta que enviar
  const con = ids.filter(id => BIB.ms.find(m => m.id === id)?.actas);
  if (!con.length) return aviso("Los documentos solo buscables no se envían: usa «Resumir y extraer» antes");
  Enviar.enviar({docs: con, omitidos: ids.length - con.length});
}
function bibBulk() {
  const ids = [...BIB.sel], n = ids.length, cs = [...new Set(ids.map(id => BIB.ms.find(m => m.id === id)?.carpeta || ""))];
  $("bib-bulk").hidden = !n; $("bib-h").classList.toggle("sel", !!n);  // la selección sustituye al título
  $("bib-bulk").replaceChildren(el("button", {type: "button", className: "gh ic", textContent: "✕", ariaLabel: "Quitar selección", title: "Quitar selección (Esc)", onclick: () => { BIB.sel.clear(); pintarBibL(); $("bib-all").focus(); }}),
    el("b", {textContent: n + (n === 1 ? " seleccionado" : " seleccionados")}), el("span", {className: "grow"}),
    el("button", {type: "button", className: "sec sm", textContent: "Enviar", onclick: () => !window.Enviar ? sinEnviar() : n === 1 ? Enviar.enviar({doc: ids[0]}) : bibEnviar(ids)}),
    el("button", {type: "button", className: "sec sm", textContent: "Añadir a " + nm("carpeta").toLowerCase() + "…", onclick: () => aProyecto(ids)}),
    el("button", {type: "button", className: "sec sm", textContent: "Exportar / descargar", onclick: () => window.Descargar ? Descargar.abrir({docs: ids}) : sinEnviar()}),
  );
}
$("v-bib").addEventListener("keydown", e => { if (e.key === "Escape" && BIB.sel.size && (e.target.type === "checkbox" || !editable(e.target))) { BIB.sel.clear(); pintarBibL(); $("bib-all").focus(); } });
async function bibVer(m) {
  BIB.act = m.id; pintarBibL(); const p = $("bib-p");
  const acc = el("div", {className: "row wrap"}, ...(m.actas ? [el("button", {type: "button", className: "pri sm", textContent: "Abrir", onclick: fallo(() => abrir(m.id))})] : []),
    el("button", {type: "button", className: "sec sm", textContent: "Enviar", onclick: () => window.Enviar ? Enviar.enviar({doc: m.id}) : sinEnviar()}),
    el("button", {type: "button", className: "sec sm", textContent: "Añadir a " + nm("carpeta").toLowerCase(), onclick: () => aProyecto([m.id])}),
    el("button", {type: "button", className: "sec sm", textContent: "Descargar", onclick: () => window.Descargar ? Descargar.abrir({docs: [m.id]}) : sinEnviar()}),
    el("button", {type: "button", className: "sec sm", textContent: "Renombrar", onclick: () => renombrar(m, p)}), el("button", {type: "button", className: "sec sm", textContent: "Mover", onclick: () => mover(m, p)}));
  p.replaceChildren(el("h2", {textContent: m.label}), el("p", {className: "muted", textContent: [KIND_T[m.kind], m.carpeta || sinC(), fechaC(m.mtime), m.dur ? Math.round(m.dur / 60) + " min" : "", m.actas > 1 ? m.actas + " versiones" : ""].filter(Boolean).join(" · ")}), acc,
    m.actas ? el("div", {className: "bib-res", "aria-busy": "true"}, ...sk(4)) : el("p", {className: "muted", textContent: "Solo buscable: se encuentra con Buscar y Preguntar."}));
  if (!m.actas) return;
  try {
    const d = await api("/api/meeting/" + m.id), a = d.actas.reduce((x, y) => y.mtime > x.mtime ? y : x), doc = (await api(`/api/doc/${m.id}/${a.name}`)).datos;
    if (BIB.act !== m.id) return;
    p.lastChild.replaceWith(el("div", {className: "bib-res"}, el("h3", {textContent: "Resumen"}), el("p", {textContent: doc.resumen || "—"}),
      ...((doc.puntos || []).length ? [el("h3", {textContent: "Puntos clave"}), el("ul", {}, ...doc.puntos.slice(0, 6).map(x => el("li", {textContent: x.texto || x})))] : [])));
  } catch (x) { p.lastChild.textContent = x.message; }
}

// ---------- Pendientes de todos los proyectos ----------
// marcar hecho (o descartar) no pide confirmación: snackbar con «Deshacer» que lo reabre
const hechoDeshacer = (c, p, luego, txt = "Hecho") => aviso(txt + ": «" + (p.texto.length > 48 ? p.texto.slice(0, 47) + "…" : p.texto) + "»", {txt: "Deshacer", fn: fallo(async () => {
  await post("/api/exp/pendientes", {c, id: p.id, estado: "abierto"}); await cargarLista(); fsucio = true; await luego(); })});
async function pintarPendPag() {
  const cs = Object.keys(RES).filter(c => RES[c]?.pend), w = $("pend-l");
  if (!w.querySelector("table")) w.replaceChildren(el("div", {"aria-busy": "true"}, ...sk(5)));
  const its = (await Promise.all(cs.map(c => api("/api/exp/pendientes?" + new URLSearchParams({c, estado: "abierto", orden: "plazo"})).then(r => r.items.filter(p => p.estado === "abierto").map(p => ({...p, c}))).catch(() => []))))
    .flat().sort((a, b) => (!!b.vencido - !!a.vencido) || (!!b.pronto - !!a.pronto) || (a.fecha || "9").localeCompare(b.fecha || "9"));
  $("pend-f").textContent = its.length ? its.length + " abiertos" : "";
  if (!its.length) return w.replaceChildren(el("p", {className: "vacio", textContent: "No hay pendientes abiertos."}));
  w.replaceChildren(el("table", {}, el("thead", {}, el("tr", {}, ...["Hecho", "Pendiente", cap(nm("carpeta")), "Responsable", "Plazo"].map(t => el("th", {scope: "col", textContent: t})))),
    el("tbody", {}, ...its.map(p => { const chk = el("input", {type: "checkbox", ariaLabel: "Marcar hecho: " + p.texto, onchange: fallo(async () => { chk.disabled = true; try { await post("/api/exp/pendientes", {c: p.c, id: p.id, estado: "hecho"}); } catch (e) { chk.disabled = chk.checked = false; throw e; } await cargarLista(); pintarPendPag(); hechoDeshacer(p.c, p, pintarPendPag); })});
      return el("tr", {className: "f"}, el("td", {}, chk), el("td", {}, p.texto, " ", ...(p.mid ? [fLink(p)] : [])), el("td", {}, el("a", {href: "#/p/" + enc(p.c) + "/pendientes", textContent: p.c || sinC()})), el("td", {textContent: p.resp || ""}),
        el("td", {}, p.vencido ? el("b", {className: "err", textContent: "Vencido"}) : p.plazo || (p.fecha ? fFecha(p.fecha) : "Sin fecha")));
    }))));
}

// ---------- Proyecto: «Auto: …», Automático, ⋯ Más, aprobar todo, importar Excel/CSV, .zip, añadir a proyecto ----------
const QUE_T = {documento: "documento", resumen: "resumen", tareas: "tareas", decisiones: "decisiones", requisitos: "requisitos", historias: "historias", riesgos: "riesgos", interesados: "interesados", informe: "informe"};
const DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"];
async function recetasTxt(c) {
  const [rs, ns] = await Promise.all([api("/api/recetas?c=" + enc(c)).catch(() => []), nombresDst()]);
  const sal = r => (r.plan?.salidas || (r.presets || []).map(p => ({preset: p}))).map(s => (s.que ? QUE_T[s.que] || s.que : "") + " → " + (s.como === "documento" ? "documento" : ns["p:" + s.preset] || ns["d:" + s.destino] || "destino")).join(" · ");
  return rs.map(r => ({r, txt: (r.cuando?.tipo === "programado" ? "cada " + ({dia: "día", semana: DIAS[r.cuando.dia_semana || 0], mes: "mes"}[r.cuando.cada] || "") + (r.cuando.hora ? " " + r.cuando.hora : "") + ": " : "") + (sal(r) || r.nombre)}));
}
async function fAutoLinea(c) {
  const l = (await recetasTxt(c)).filter(x => x.r.activa);
  if (fuC !== c) return;
  $("f-auto").hidden = !l.length; $("f-auto").textContent = "Auto: " + l.map(x => x.txt).join(" · ");
  $("f-auto").onclick = () => { fScrollA = "f-auto-card"; fIr("ajustes"); };
}
function fAuto(c) {  // Proyecto › Ajustes › Automático: sus recetas (al terminar y programadas) + el plan por defecto de Añadir
  const lista = el("ul", {className: "list"}), plan = el("div");
  const carga = async () => {
    const l = await recetasTxt(c);
    lista.replaceChildren(...(l.length ? l.map(({r, txt}) => { const sw = el("input", {type: "checkbox", checked: !!r.activa, ariaLabel: "Activa: " + (r.nombre || txt), onchange: fallo(async () => { await api("/api/recetas/" + r.id, {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({activa: sw.checked})}); fAutoLinea(c); })});
      return el("li", {}, el("label", {className: "check"}, sw, el("span", {}, el("b", {textContent: r.nombre || "Receta"}), el("small", {textContent: txt + (r.proximo_iso ? " · próximo: " + r.proximo_iso.replace("T", " ") : "") + (r.atrasado ? " · atrasado" : "")}))),
        el("span", {className: "grow"}), el("button", {className: "sec sm", textContent: "Enviar ahora", onclick: fallo(async () => { await post("/api/recetas/" + r.id + "/ahora"); aviso("Enviado"); })}),
        el("button", {className: "sec sm dng", textContent: "Quitar", onclick: fallo(async () => { await api("/api/recetas/" + r.id, {method: "DELETE"}); carga(); fAutoLinea(c);
          aviso("Receta «" + (r.nombre || txt) + "» quitada", {txt: "Deshacer", fn: fallo(async () => { const {id, ...x} = r; await post("/api/recetas", x); carga(); fAutoLinea(c); })}); })}));
    }) : [el("li", {className: "muted", textContent: "Sin recetas: nada se envía solo desde este " + nm("carpeta").toLowerCase() + "."})]));
  };
  carga();
  if (window.Enviar) api("/api/carpetas/" + enc(c) + "/plan_defecto").then(p => Enviar.checklist(plan, {plan: p, carpeta: c, onChange: () => {}})).catch(() => {});
  return el("div", {className: "card", id: "f-auto-card"}, H("Automático", el("button", {className: "link", textContent: "Recargar", onclick: () => { carga(); fAutoLinea(c); }})),
    el("p", {className: "muted", textContent: "Lo que se envía solo al terminar cada documento de este " + nm("carpeta").toLowerCase() + " o de forma programada. Al añadir aquí, estas casillas ya vienen marcadas."}),
    lista, ...(window.Enviar ? [el("h3", {textContent: "Nueva receta"}), plan] : [el("p", {className: "muted", textContent: "El módulo de envío no está disponible."})]));
}
async function fAprobarTodo(c) {
  const ids = (await api("/api/reg?" + new URLSearchParams({c, revision: "propuesto"}))).items.map(x => x.id);
  if (!ids.length) return aviso("No hay nada por revisar");
  await post("/api/reg/revisar", {c, ids, accion: "aprobar"}); INI.p = null;
  aviso(ids.length + " aprobados", {txt: "Deshacer", fn: fallo(async () => { await post("/api/reg/deshacer", {c}); fsucio = true; pintarHome(); })});
  fsucio = true; pintarHome();
}
async function deshacerPasada(c) {
  const u = (await Promise.all(["poblar", "derivar"].map(k => api("/api/reg/" + k + "/estado?c=" + enc(c)).catch(() => ({}))))).map(x => x.ultimo).filter(x => x && x.lote).sort((x, y) => y.t - x.t)[0];
  if (!u) return aviso("No hay ninguna pasada de IA que deshacer");
  if (!confirm("¿Deshacer la última pasada de IA (" + new Date(u.t * 1000).toLocaleString("es") + ")? Se quitan los elementos que propuso y no has tocado.")) return;
  const r = await post("/api/reg/deshacer-pasada", {c, lote: u.lote}); aviso("Pasada deshecha (" + (r.revertidas ?? r.revertida ?? 0) + ")"); fsucio = true; pintarHome();
}
function regImportar(c, vista) {
  const inp = el("input", {type: "file", accept: ".xlsx,.csv", hidden: true}); document.body.append(inp);
  inp.onchange = fallo(async () => {
    const f = inp.files[0]; inp.remove(); if (!f) return;
    const fd = new FormData(); fd.append("file", f); fd.append("c", c); if (fImportable(vista)) fd.append("vista", vista);
    importarPrevia(c, await api("/api/reg/importar/previa", {method: "POST", body: fd}));
  });
  inp.click();
}
function importarPrevia(c, r) {
  const {d, b, f} = dialogo("Importar " + (r.vista || "") + " desde Excel/CSV", "Vista previa: nada cambia hasta que pulses Aplicar. Nunca se borra nada y se puede deshacer.");
  const sel = new Set([...r.nuevos.map(x => String(x.fila)), ...r.modificados.map(x => String(x.id))]);
  const chk = k => el("input", {type: "checkbox", checked: true, onchange: e => e.target.checked ? sel.add(k) : sel.delete(k)});
  b.append(el("p", {className: "muted", textContent: "Columnas reconocidas: " + (r.columnas_reconocidas || []).join(", ") + ((r.columnas_ignoradas || []).length ? " · ignoradas: " + r.columnas_ignoradas.join(", ") : "") + " · sin cambios: " + (r.iguales ?? 0)}),
    ...(r.nuevos.length ? [el("h3", {textContent: "Nuevos · " + r.nuevos.length}), el("ul", {className: "imp-l"}, ...r.nuevos.map(x => el("li", {}, el("label", {className: "check"}, chk(String(x.fila)), el("span", {}, el("b", {textContent: x.titulo}), el("small", {textContent: "Fila " + x.fila}))))))] : []),
    ...(r.modificados.length ? [el("h3", {textContent: "Modificados · " + r.modificados.length}), el("ul", {className: "imp-l"}, ...r.modificados.map(x => el("li", {}, el("label", {className: "check"}, chk(String(x.id)),
      el("span", {}, el("b", {textContent: (x.codigo || x.id) + " · fila " + x.fila}), ...Object.entries(x.cambios).map(([k, [a, z]]) => el("small", {}, k + ": ", el("s", {textContent: a ?? "—"}), " → " + (z ?? "—"))))))))] : []),
    ...(r.desconocidas.length ? [el("h3", {textContent: "Filas que no se importan · " + r.desconocidas.length}), el("ul", {className: "imp-l"}, ...r.desconocidas.map(x => el("li", {textContent: "Fila " + x.fila + ": " + x.motivo})))] : []),
    ...(!r.nuevos.length && !r.modificados.length ? [el("p", {className: "aviso", textContent: "No hay nada nuevo ni cambiado que importar."})] : []));
  const ap = el("button", {type: "button", className: "pri", textContent: "Aplicar", disabled: !r.nuevos.length && !r.modificados.length, onclick: fallo(async () => {
    ap.disabled = true; let x; try { x = await post("/api/reg/importar/aplicar", {token: r.token, seleccion: [...sel]}); } catch (e) { ap.disabled = false; throw e; } d.close();
    aviso(x.creadas + " nuevos · " + x.modificadas + " modificados", {txt: "Deshacer", fn: fallo(async () => { await post("/api/reg/deshacer", {c}); fsucio = true; pintarHome(); })});
    fsucio = true; pintarHome(); })});
  f.append(el("span"), el("div", {className: "row"}, el("button", {type: "button", className: "sec", textContent: "Cancelar", onclick: () => d.close()}), ap));
}
async function importarZip(c) {
  const p = (await post("/api/pick", {tipo: "zip"})).path; if (!p) return;
  const m = await post("/api/importar", {path: p, ...(c ? {carpeta: c} : {})}); await cargarLista(); aviso("Documento importado"); abrir(m.id);
}
function aProyecto(mids) {
  const {d, b, f} = dialogo("Añadir a " + nm("carpeta").toLowerCase(), "Sin reprocesar: incorpora sus tareas, decisiones, riesgos y requisitos, y queda buscable en el " + nm("carpeta").toLowerCase() + ".");
  if (!carpetas.length) { b.append(el("p", {textContent: "Aún no hay ningún " + nm("carpeta").toLowerCase() + ". Créalo desde el menú lateral («Nuevo»)."})); return; }
  const s = el("select", {id: "ap-c"}, ...carpetas.map(c => new Option(c, c))), mv = el("input", {type: "radio", name: "ap-m", checked: true}), cp = el("input", {type: "radio", name: "ap-m"}), env = el("input", {type: "checkbox"});
  if (carpetas.includes(fsel)) s.value = fsel;
  b.append(el("div", {className: "field"}, el("label", {htmlFor: "ap-c", textContent: cap(nm("carpeta"))}), s),
    el("fieldset", {}, el("legend", {textContent: "Cómo"}), el("label", {className: "check"}, mv, el("span", {textContent: "Mover"})), el("label", {className: "check"}, cp, el("span", {textContent: "Copiar (sigue también donde está)"}))),
    el("label", {className: "check"}, env, el("span", {textContent: "Enviar también según las recetas del " + nm("carpeta").toLowerCase()})));
  const ok = el("button", {type: "button", className: "pri", textContent: "Añadir", onclick: fallo(async () => {
    const antes = mids.map(id => [id, (todas.find(m => m.id === id) || BIB.ms.find(m => m.id === id))?.carpeta || ""]);
    ok.disabled = true; let r; try { r = await post("/api/doc/a-proyecto", {mids, c: s.value, modo: cp.checked ? "copiar" : "mover", enviar: env.checked}); } catch (e) { ok.disabled = false; throw e; } d.close();
    BIB.sel.clear(); await cargarLista(); sondear(); if (vistaAct === "bib") pintarBib();
    const txt = "Añadido a " + s.value + (r.poblando?.length ? " · extrayendo sus elementos" : "");
    // deshacer = devolver cada documento a su carpeta (lo ya incorporado al proyecto se revisa allí); las copias no se deshacen desde aquí
    if (cp.checked) aviso(txt); else aviso(txt, {txt: "Deshacer", fn: fallo(async () => { for (const [id, c] of antes) await post("/api/meta", {id, carpeta: c}); await cargarLista(); if (vistaAct === "bib") pintarBib(); else if (vistaAct === "home") pintarHome(); })});
  })});
  f.append(el("span"), el("div", {className: "row"}, el("button", {type: "button", className: "sec", textContent: "Cancelar", onclick: () => d.close()}), ok));
}
const proyAcc = () => [
  ["Línea de tiempo", () => fIr("linea")], ["Comparar documentos", () => fIr("comparar")], ["Glosario", () => { fScrollA = "f-glos"; fIr("ajustes"); }],
  ["Regenerar con IA", () => fEnCola("/api/reg/poblar", {c: fuC})], ["Derivar historias de requisitos", () => fEnCola("/api/reg/derivar", {c: fuC})], ["Deshacer la última pasada IA", () => deshacerPasada(fuC)],
  ["Importar desde Excel/CSV", () => regImportar(fuC, ftab)], ["Importar .zip de Actas", () => importarZip(fuC)], ["Descargar…", () => window.Descargar ? Descargar.abrir({c: fuC}) : sinEnviar()],
  ["Automático (envíos)", () => { fScrollA = "f-auto-card"; fIr("ajustes"); }], ["Ajustes del " + nm("carpeta").toLowerCase(), () => fIr("ajustes")]];
$("f-mas-l").prepend(...proyAcc().map(([t, f]) => el("button", {type: "button", role: "menuitem", textContent: t, onclick: fallo(async () => f())})), el("div", {className: "sep", role: "separator"}));
$("f-env").onclick = () => window.Enviar ? Enviar.enviar({c: fuC}) : sinEnviar();

// ---------- paleta Ctrl+K: navegación + todas las acciones (también las escondidas) + búsqueda ----------
function palCmds() {
  const C = (g, t, f) => ({g, t, f}), go = h => () => { location.hash = h; }, clk = id => () => $(id).click(), vis = id => !$(id).hidden;
  const L = [];
  if (vistaAct === "res" && cur?.solo) L.push(C("Documento", "Resumir y extraer", clk("d-resumir")), C("Documento", "Ver la fuente", () => tab("p-video")), C("Documento", "Preguntar", () => tab("p-preg")), C("Documento", "Descargar…", clk("d-desc")),
    C("Documento", "Renombrar", clk("m-ren")), C("Documento", "Mover", clk("m-mover")), C("Documento", "Añadir a " + nm("carpeta").toLowerCase() + "…", clk("d-aproy")));
  else if (vistaAct === "res" && cur) {
    const a = cur.actas.find(x => x.name === ver);
    L.push(C("Documento", "Preguntar", () => tab("p-preg")), C("Documento", "Ver resumen", () => tab("p-acta")), C("Documento", "Ver lo extraído", () => tab("p-ext")), C("Documento", "Ver la fuente", () => tab("p-video")),
      C("Documento", $("d-env").textContent, clk("d-env")), C("Documento", "Enviar a…", clk("d-env-m")), ...FMT.map(([f, t]) => C("Exportar", t, () => exportar(f))), C("Documento", "Descargar…", clk("d-desc")),
      C("Documento", "Editar el texto", clk("d-editar")), C("Documento", "Renombrar", clk("m-ren")), C("Documento", "Mover", clk("m-mover")), C("Documento", "Añadir a " + nm("carpeta").toLowerCase() + "…", clk("d-aproy")),
      C("Documento", "Anonimizar…", clk("d-anon")), C("Documento", "Borrador de correo", clk("d-correo")), ...(cur.video ? [C("Documento", (cur.audio ? "Audio" : "Vídeo") + " condensado", clk("d-cond"))] : []),
      ...(vis("fondo") ? [C("Documento", $("fondo").textContent, clk("fondo"))] : []), ...(vis("dl-zip") ? [C("Documento", "Descargar (.zip)", clk("dl-zip"))] : []), ...(vis("dl-vid") ? [C("Documento", $("dl-vid").textContent, clk("dl-vid"))] : []),
      C("Documento", "Otra versión…", clk("d-otra")), C("Documento", "Renombrar versión", clk("d-vren")), C("Documento", "Dudas: siguiente frase dudosa", clk("d-dud")), ...(vis("d-rest") ? [C("Documento", "Restaurar original", clk("d-rest"))] : []),
      ...(a?.sin ? [] : []));
  }
  if (vistaAct === "home" && fsel) {
    L.push(...FTOP.filter(([k]) => k !== "extraido").map(([k, t]) => C(fsel, t, () => fIr(k))), C(fsel, "Por revisar", () => fIr("revision")), ...FEXT.map(([k, t]) => C(fsel, "Extraído · " + t, () => fIr(k))),
      C(fsel, "Aprobar todo lo pendiente de revisar", () => fAprobarTodo(fsel)), ...proyAcc().map(([t, f]) => C(fsel, t, f)),
      C(fsel, "Enviar " + nm("carpeta").toLowerCase(), clk("f-env")), C(fsel, "Añadir documento aquí", () => formNuevo()), C(fsel, "Renombrar " + nm("carpeta").toLowerCase(), clk("f-ren")), C(fsel, "Quitar " + nm("carpeta").toLowerCase(), clk("f-quitar")));
  }
  L.push(C("Acción", "Añadir archivos, enlace o captura", () => formNuevo()), C("Acción", "Elegir archivos…", () => { formNuevo(); $("an-file").click(); }), C("Acción", "Pegar captura", anPegar),
    C("Acción", "Grabar reunión", () => grabarAbrir()), C("Acción", "Importar documento exportado (.zip)", () => $("b-importar").click()), C("Acción", "Nuevo " + nm("carpeta").toLowerCase(), () => { irInicio(); nuevaCarpeta(); }),
    C("Acción", "Asistente: ¿para qué usas la app?", () => abrirUso(false)), C("Vista", simple() ? "Cambiar a modo avanzado" : "Cambiar a modo simple", () => guardarAj({modo: simple() ? "avanzado" : "simple"})),
    C("Vista", "Contraer o mostrar el menú lateral", railToggle),
    C("Ajustes", "Carpetas vigiladas", () => ajIr("general", "aj-vig")), C("Ajustes", "Conectar con otras herramientas de IA (MCP)", () => ajIr("avanzado", "aj-mcp")),
    C("Ir a", "Inicio", go("#/")), C("Ir a", "Biblioteca", go("#/biblioteca")), C("Ir a", "Pendientes", go("#/pendientes")), C("Ir a", "Enviar: destinos, recetas e historial", go("#/enviar")), C("Ir a", "Cola de trabajos", go("#/cola")),
    ...[["general", "General"], ["modelos", "Modelos"], ["plantillas", "Plantillas"], ["enviar", "Enviar"], ["avanzado", "Avanzado y perfiles de uso"]].map(([k, t]) => C("Ajustes", t, () => abrirAjustes(k))),
    ...carpetas.map(c => C(cap(nm("carpeta")), c, go("#/p/" + enc(c)))), ...todas.slice(0, 60).map(m => C("Documento", m.label, () => abrir(m.id))));
  return L;
}
function paleta() {
  if (document.querySelector("dialog.pal")) return;
  const cmds = palCmds(), d = el("dialog", {className: "pal", ariaLabel: "Paleta de comandos"}), ul = el("ul", {id: "pal-l", role: "listbox", ariaLabel: "Resultados"});
  const q = el("input", {type: "search", placeholder: "Acción, " + nm("carpeta").toLowerCase() + ", documento o búsqueda…", ariaLabel: "Comando", role: "combobox", "aria-controls": "pal-l", "aria-expanded": "true", "aria-autocomplete": "list"});
  let sel = 0, vis = [];
  const run = c => { d.close(); setTimeout(() => fallo(async () => c.f())(), 0); };
  const pint = () => {
    const t = norm(q.value).trim(), w = t.split(/\s+/);
    vis = cmds.filter(c => !t || w.every(x => norm(c.g + " " + c.t).includes(x))).slice(0, 80);
    if (q.value.trim()) vis.push({g: "Buscar", t: "Buscar «" + q.value.trim() + "»", f: () => { $("buscar").value = q.value.trim(); $("omni").requestSubmit(); }});
    sel = Math.max(0, Math.min(sel, vis.length - 1));
    ul.replaceChildren(...vis.map((c, i) => el("li", {role: "option", id: "pal-" + i, "aria-selected": i === sel, onclick: () => run(c), onmousemove: () => { if (sel !== i) { sel = i; pint(); } }}, el("span", {className: "pal-g", textContent: c.g}), el("span", {textContent: c.t}))));
    q.setAttribute("aria-activedescendant", vis.length ? "pal-" + sel : ""); ul.children[sel]?.scrollIntoView({block: "nearest"});
  };
  q.oninput = () => { sel = 0; pint(); };
  q.onkeydown = e => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); sel = (sel + (e.key === "ArrowDown" ? 1 : -1) + vis.length) % Math.max(vis.length, 1); pint(); }
    else if (e.key === "Enter") { e.preventDefault(); if (vis[sel]) run(vis[sel]); }
  };
  d.append(q, ul, el("p", {className: "pal-n muted", textContent: "↑↓ elegir · Intro ejecutar · Esc cerrar"})); d.onclose = () => d.remove(); document.body.append(d); d.showModal(); pint();
}

// ---------- Ajustes › General: carpetas vigiladas · Ajustes › Avanzado: MCP ----------
const jsonH = {"Content-Type": "application/json"};
function ajVigiladas() {
  const lista = el("ul", {className: "list"}), hace = t => { const s = Math.round(Date.now() / 1000 - t); return s < 90 ? "hace " + s + " s" : s < 5400 ? "hace " + Math.round(s / 60) + " min" : new Date(t * 1000).toLocaleString("es"); };
  const carga = async () => {
    const l = await api("/api/vigiladas").catch(() => []);
    lista.replaceChildren(...(l.length ? l.map(v => {
      const e = v.estado || {}, sw = el("input", {type: "checkbox", checked: !!v.activa, ariaLabel: "Activa: " + v.ruta, onchange: fallo(async () => { await api("/api/vigiladas/" + v.id, {method: "PATCH", headers: jsonH, body: JSON.stringify({activa: sw.checked})}); carga(); })});
      return el("li", {}, el("label", {className: "check"}, sw, el("span", {}, el("b", {textContent: v.ruta}), el("small", {className: e.error ? "err" : "", textContent: ["→ " + (v.carpeta || sinC()), v.recursivo && "con subcarpetas", v.mover && "mueve a Procesados/",
          e.error || (e.ultima ? "Última revisión " + hace(e.ultima) : "Sin revisar aún"), e.encoladas ? e.encoladas + " en cola" : ""].filter(Boolean).join(" · ")}))),
        el("span", {className: "grow"}), el("button", {className: "sec sm", textContent: "Revisar ahora", onclick: fallo(async () => { await post("/api/vigiladas/" + v.id + "/revisar"); carga(); sondear(); })}),
        el("button", {className: "sec sm dng", textContent: "Quitar", onclick: fallo(async () => { await api("/api/vigiladas/" + v.id, {method: "DELETE"}); carga();
          aviso("Ya no se vigila " + v.ruta + " (no se borra nada)", {txt: "Deshacer", fn: fallo(async () => { await post("/api/vigiladas", {ruta: v.ruta, carpeta: v.carpeta || "", recursivo: !!v.recursivo, mover: !!v.mover, activa: !!v.activa, ...(v.plan ? {plan: v.plan} : {})}); carga(); })}); })}));
    }) : [el("li", {className: "muted", textContent: "Ninguna todavía."})]));
  };
  const rt = el("input", {id: "vg-r", required: true, placeholder: "C:\\Users\\…\\OneDrive\\Grabaciones"}), c = el("select", {id: "vg-c"}, new Option(sinC(), ""), ...carpetas.map(x => new Option(x, x)));
  const rec = el("input", {type: "checkbox"}), mov = el("input", {type: "checkbox"}), chk = el("div"); let plan = null;
  c.onchange = () => { plan = null; if (window.Enviar && c.value) Enviar.checklist(chk, {plan: {carpeta: c.value, salidas: []}, carpeta: c.value, onChange: p => { plan = p; }}); else chk.replaceChildren(); };
  const f = el("form", {className: "vg-add"}, el("h3", {textContent: "Vigilar una carpeta"}),
    el("div", {className: "cols"}, el("div", {className: "field"}, el("label", {htmlFor: "vg-r", textContent: "Ruta de la carpeta"}), rt), el("div", {className: "field"}, el("label", {htmlFor: "vg-c", textContent: "Añadir a"}), c)),
    el("label", {className: "check"}, rec, el("span", {textContent: "Incluir subcarpetas"})), el("label", {className: "check"}, mov, el("span", {textContent: "Mover lo procesado a «Procesados/»"})), chk,
    el("button", {className: "pri", textContent: "Vigilar esta carpeta"}));
  f.onsubmit = fallo(async e => { e.preventDefault(); await post("/api/vigiladas", {ruta: rt.value.trim(), carpeta: c.value, recursivo: rec.checked, mover: mov.checked, activa: true, ...(plan?.salidas?.length ? {plan} : {})}); rt.value = ""; carga(); aviso("Carpeta vigilada"); });
  carga();
  return el("section", {className: "card", id: "aj-vig"}, el("h2", {textContent: "Carpetas vigiladas"}),
    el("p", {className: "muted", textContent: "Lo que caiga en estas carpetas entra solo en la cola. Ideal para la carpeta de OneDrive donde caen las grabaciones de Teams."}), lista, f);
}
function ajMcp() {
  const cuerpo = el("div");
  const pinta = async () => {
    const [a, cf] = await Promise.all([api("/api/mcp/ajustes"), api("/api/mcp/config")]), set = async b => { await post("/api/mcp/ajustes", b); await pinta(); };
    const copia = (t, txt) => el("div", {className: "field"}, el("div", {className: "row"}, el("b", {textContent: t}), el("span", {className: "grow"}),
      el("button", {type: "button", className: "sec sm", textContent: "Copiar", onclick: fallo(async () => { await navigator.clipboard.writeText(txt); aviso("Copiado"); })})), el("pre", {className: "fu-ocr", textContent: txt}));
    const h = Object.entries(cf.http?.headers || {}).map(([k, v]) => k + ": " + v).join("\n");
    cuerpo.replaceChildren(chk2("Activar el servidor MCP", !!a.activo, v => set({activo: v})), chk2("Pedir token (recomendado)", !!a.token_requerido, v => set({token_requerido: v})),
      chk2("Permitir que añadan trabajos a la cola", !!a.permitir_encolar, v => set({permitir_encolar: v}), "Pueden encolar archivos; nunca borrar."),
      ...(a.activo ? [copia("Claude Desktop (claude_desktop_config.json)", cf.claude_desktop), copia("Claude Code", cf.claude_code), copia("HTTP (otras herramientas)", cf.http.url + (h ? "\n" + h : "")),
        ...(a.token_requerido ? [el("button", {type: "button", className: "sec sm", textContent: "Regenerar token", onclick: fallo(() => set({regenerar_token: true}))})] : [])] : []));
  };
  pinta().catch(x => cuerpo.replaceChildren(el("p", {className: "muted", textContent: x.message})));
  return el("section", {className: "card", id: "aj-mcp"}, el("h2", {textContent: "Conectar con otras herramientas de IA (MCP)"}),
    el("p", {className: "aviso w", textContent: "Las herramientas conectadas (Claude Desktop, Copilot, Cursor…) pueden enviar a la nube lo que reciben. Con «Anonimizar por defecto» activo, Actas no les entrega contenido."}), cuerpo);
}
const ajIr = (t, id) => { abrirAjustes(t); setTimeout(() => $(id)?.scrollIntoView({block: "start"}), 300); };

// ---------- arranque: la ruta del enlace (#/…) ----------
rutaIr().finally(() => { rutaLista = true; });
