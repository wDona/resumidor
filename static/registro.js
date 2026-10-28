// Registro de entidades (requisitos, decisiones, riesgos…): tabla editable genérica + bandeja de revisión.
// IA primero -> el humano revisa/edita; nada sin cita; lo no revisado se marca. API: /api/reg (ver PLAN.md F3).
// registroTabla(host, {c, tipo, columnas, onChange, fijos, vacio, filtro?(items)->items}); columna {render(item)} = celda derivada de solo lectura -> {recargar}   |   registroBandeja(host, c, onChange)
const REG_TIPOS = {requisito: "Requisitos", historia: "Historias", interesado: "Interesados", decision: "Decisiones", tarea: "Tareas", riesgo: "Riesgos", incidencia: "Incidencias", supuesto: "Supuestos", dependencia: "Dependencias", pregunta: "Preguntas", hito: "Hitos"};
const REG_ESTADOS = ["abierto", "en curso", "hecho", "bloqueado", "descartado"], REG_PRIO = ["alta", "media", "baja"];
const REG_COLS = {  // columnas por defecto por tipo; cada vista de F4 puede pasar las suyas
  requisito: [{k: "codigo", label: "Código", w: 90}, {k: "titulo", label: "Requisito", tipo: "area"}, {k: "estado", label: "Estado", tipo: "select", opciones: REG_ESTADOS}, {k: "prioridad", label: "Prioridad", tipo: "select", opciones: REG_PRIO}, {k: "dueno", label: "Responsable"}],
  historia: [{k: "codigo", label: "Código", w: 90}, {k: "titulo", label: "Historia", tipo: "area"}, {k: "estado", label: "Estado", tipo: "select", opciones: REG_ESTADOS}],
  interesado: [{k: "titulo", label: "Nombre"}, {k: "detalle", label: "Rol", tipo: "area"}, {k: "campos.organizacion", label: "Organización"}],
  riesgo: [{k: "codigo", label: "Código", w: 90}, {k: "titulo", label: "Riesgo", tipo: "area"}, {k: "campos.probabilidad", label: "Probabilidad"}, {k: "campos.impacto", label: "Impacto"}, {k: "dueno", label: "Responsable"}],
  pregunta: [{k: "codigo", label: "Código", w: 90}, {k: "titulo", label: "Pregunta", tipo: "area"}, {k: "estado", label: "Estado", tipo: "select", opciones: REG_ESTADOS}, {k: "campos.dirigida_a", label: "Dirigida a"}],
  decision: [{k: "codigo", label: "Código", w: 90}, {k: "titulo", label: "Decisión", tipo: "area"}, {k: "estado", label: "Estado", tipo: "select", opciones: REG_ESTADOS}, {k: "fecha_alta", label: "Fecha", tipo: "fecha"}],
};
const REG_DEF = [{k: "codigo", label: "Código", w: 90}, {k: "titulo", label: "Título", tipo: "area"}, {k: "estado", label: "Estado", tipo: "select", opciones: REG_ESTADOS}, {k: "dueno", label: "Responsable"}];
const REG_REV = [["", "Todas"], ["propuesto", "Propuestas"], ["aprobado", "Aprobadas"], ["descartado", "Descartadas"], ["fusionado", "Fusionadas"]];
const regQ = o => new URLSearchParams(Object.fromEntries(Object.entries(o).filter(([, v]) => v !== "" && v != null && v !== false))).toString();
const regAviso = e => aviso(e.message || String(e));
const regEnCampo = () => { const a = document.activeElement; return a && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) || a?.isContentEditable; };
let REG_ACTIVA = null;  // tabla que recibe los atajos de teclado (la última tocada)
// tras aprobar/descartar/fusionar/deshacer: refresca el contador de la pestaña «Revisión (n)» (carpeta.js)
const regContadores = c => { if (typeof fCargaReg === "function") fCargaReg(c, fReg.proyecto ? "Proyecto" : ""); };

// ---- fusionar / separar (compartido por la tabla genérica, decisiones, requisitos e interesados) ----
const REG_FEM = /^(decision|historia|tarea|incidencia|dependencia|pregunta)$/;
const regNombre = (tipo, n) => n === 1 ? ({decision: "decisión"}[tipo] || tipo) : (REG_TIPOS[tipo] || tipo).toLowerCase();
const regCod = it => it.codigo || "«" + (it.titulo || "").slice(0, 40) + "»";
const regDeshacerYa = (c, listo) => async () => { try { const r = await post("/api/reg/deshacer", {c}); aviso(r.revertidas ? "Deshecho" : "Nada que deshacer"); regContadores(c); if (listo) await listo(); } catch (e) { regAviso(e); } };
async function regFusionarYa(c, destino, origenes, listo, cods = {}) {
  try {
    const r = await post("/api/reg/fusionar", {c, destino, origenes}), os = origenes.map(id => cods[id]).filter(Boolean);
    aviso((os.length ? os.join(", ") : origenes.length) + " " + (REG_FEM.test(r.tipo) ? "fusionada" : "fusionado") + (origenes.length > 1 ? "s" : "") + " en " + regCod(r), {txt: "Deshacer", fn: regDeshacerYa(c, listo)});
    regContadores(c); if (listo) await listo();
  } catch (e) { regAviso(e); }
}
async function regSeparar(c, destino, origen, listo) {
  try { const [d, o] = (await post("/api/reg/separar", {c, destino, origen})).items; aviso(regCod(o) + " " + (REG_FEM.test(o.tipo) ? "separada" : "separado") + " de " + regCod(d), {txt: "Deshacer", fn: regDeshacerYa(c, listo)}); regContadores(c); if (listo) await listo(); }
  catch (e) { regAviso(e); }
}
// vista previa: items (>=2) lado a lado; el elegido (radio) se queda y los demás se ocultan dentro de él
function regDialogoFusion(c, items, destino, listo) {
  items = items.filter(Boolean);
  if (items.length < 2) return;
  let dest = items.some(x => x.id === destino) ? destino : items[0].id;
  const {d, b, f} = dialogo("Fusionar " + regNombre(items[0].tipo, 2), "Elige cuál se queda. Nada se borra: lo fusionado se oculta dentro y puedes separarlo después.", "reg-fus-d");
  const exp = el("p", {className: "reg-fus-exp"}), caja = {};
  const actualiza = () => {
    const de = items.find(x => x.id === dest), os = items.filter(x => x.id !== dest).map(regCod);
    for (const x of items) caja[x.id].classList.toggle("dest", x.id === dest);
    exp.textContent = os.join(", ") + (os.length > 1 ? " se ocultan" : " se oculta") + " y sus citas y relaciones pasan a " + regCod(de) + " (lo que " + regCod(de) + " tenga vacío se completa; el texto distinto queda como nota); puedes separarlas después.";
  };
  const cols = el("div", {className: "reg-fus-cols", role: "radiogroup", ariaLabel: "Cuál se queda"}, ...items.map(x => {
    const n = (x.citas || []).length;
    return caja[x.id] = el("label", {className: "reg-fus-it"},
      el("span", {className: "reg-fus-top"}, el("input", {type: "radio", name: "reg-fus-dest", value: x.id, checked: x.id === dest, onchange: () => { dest = x.id; actualiza(); }}), el("b", {textContent: x.codigo || ""}), el("span", {className: "muted reg-fus-q", textContent: "se queda"})),
      el("h4", {textContent: x.titulo || "(sin título)"}),
      x.detalle ? el("p", {textContent: x.detalle}) : el("p", {className: "muted", textContent: "Sin texto"}),
      el("small", {className: "muted", textContent: n + (n === 1 ? " cita" : " citas") + ((x.fusionadas || []).length ? " · ya fusiona " + x.fusionadas.length : "")}));
  }));
  b.append(cols, exp); actualiza();
  const cods = Object.fromEntries(items.map(x => [x.id, regCod(x)]));
  f.append(el("span", {className: "grow"}), el("button", {type: "button", className: "sec", textContent: "Cancelar", onclick: () => d.close()}),
    el("button", {type: "button", className: "pri", textContent: "Fusionar", onclick: () => { d.close(); regFusionarYa(c, dest, items.filter(x => x.id !== dest).map(x => x.id), listo, cods); }}));
  d.querySelector("input[type=radio]:checked")?.focus();
}
// «Fusiona N …» desplegable en el destino, con «Separar» por cada fusionada ("" si no fusiona nada)
function regFusiona(it, c, listo) {
  const fs = it.fusionadas || [];
  if (!fs.length) return "";
  return el("details", {className: "reg-fus"}, el("summary", {textContent: "Fusiona " + fs.length + " " + regNombre(it.tipo, fs.length)}),
    el("ul", {}, ...fs.map(x => el("li", {}, el("b", {textContent: x.codigo || ""}), " " + x.titulo + " ", el("small", {className: "muted", textContent: "· " + x.fecha + " · " + x.citas + (x.citas === 1 ? " cita" : " citas")}), " ",
      el("button", {className: "link", type: "button", textContent: "Separar", ariaLabel: "Separar " + (x.codigo || x.titulo), onclick: () => regSeparar(c, it.id, x.id, listo)})))));
}
// botón «Separar» de una fusionada (vista «Fusionadas»)
const regBotonSeparar = (it, c, listo, cl = "sec sm") => it.revision === "fusionado" && it.fusionado_en ? [el("button", {className: cl, type: "button", textContent: "Separar", title: "Vuelve a ser independiente", onclick: () => regSeparar(c, it.fusionado_en, it.id, listo)})] : [];
// fusionadas dentro de una lista de destinos (chip «Fusionadas (n)» sin pedir otra lista)
const regNumFusionadas = xs => xs.reduce((n, x) => n + (x.fusionadas || []).length, 0);

function regInsignias(it) {
  const b = (t, cl, title) => el("span", {className: "badge " + cl, textContent: t, title: title || ""}), r = [];
  if (it.huerfano) r.push(b("Huérfano: ya no está en el documento", "w", "La cita ya no se encuentra en el documento de origen"));
  if (it.revision === "propuesto" && (it.origen === "reunion" || it.origen === "derivado")) r.push(b("IA · propuesto", "acc", "Propuesto automáticamente: revísalo"));
  else if (it.origen === "derivado") r.push(b("Derivado", "acc"));
  if (it.origen === "manual") r.push(b("Manual", ""));
  if (it.origen === "migrado") r.push(b("Migrado", ""));
  if (it.editado) r.push(b("Editado", "ok", "Modificado a mano"));
  if (it.revision === "descartado" || it.revision === "fusionado") r.push(b(it.revision === "fusionado" ? (REG_FEM.test(it.tipo) ? "Fusionada" : "Fusionado") + (it.fusionado_en_codigo ? " en " + it.fusionado_en_codigo : "") : "Descartado", "no"));
  if (it.sugerencia) r.push(b("Sugerencia: " + (it.sugerencia.tipo || ""), "w"));
  return r;
}

function registroTabla(host, o) {
  const {c, tipo} = o, cols = o.columnas || REG_COLS[tipo] || REG_DEF, fijos = o.fijos || {};
  const S = {items: [], cont: null, sel: new Set(), f: {q: "", estado: "", dueno: "", revision: fijos.revision ?? (o.foco ? "" : lsGet("reg-rev", ""))}, foco: -1, hist: null, abiertas: new Set(), ids: o.foco?.ids || null, resaltar: !!o.foco};
  let seq = 0;
  const raiz = el("div", {className: "reg", tabIndex: -1}), barra = el("div", {className: "reg-bar"}), chips = el("div", {className: "reg-chips"}), acciones = el("div", {className: "reg-acc"}), cuerpo = el("div", {className: "reg-wrap"}), panel = el("aside", {className: "reg-hist", hidden: true});
  raiz.append(barra, chips, acciones, cuerpo, panel); host.replaceChildren(raiz);
  raiz.addEventListener("focusin", () => REG_ACTIVA = api_); raiz.addEventListener("pointerdown", () => REG_ACTIVA = api_);

  const cambio = () => { o.onChange && o.onChange(); };
  const val = (it, k) => k.startsWith("campos.") ? (it.campos || {})[k.slice(7)] ?? "" : it[k] ?? "";
  async function cargar() {
    const n = ++seq;
    try {
      const r = await api("/api/reg?" + regQ({c, tipo, ...fijos, revision: S.f.revision, estado: S.f.estado, q: S.f.q, dueno: S.f.dueno}));
      if (n !== seq) return;
      S.foco = -1; S.items = o.filtro ? o.filtro(r.items) : r.items; S.cont = r.contadores; S.sel = new Set([...S.sel].filter(id => r.items.some(i => i.id === id)));
      if (S.ids) S.items = S.items.filter(i => S.ids.includes(i.id));  // foco desde el informe (fIr)
      pintar();
      if (S.resaltar && typeof fResaltaIds === "function") { S.resaltar = false; fResaltaIds(cuerpo, S.ids); }
    } catch (e) { if (n === seq) cuerpo.replaceChildren(el("p", {className: "err", textContent: e.message})); }
  }
  async function patch(it, k, v) {
    const antes = val(it, k);
    if (String(antes) === String(v)) return;
    const cambios = k.startsWith("campos.") ? {campos: {[k.slice(7)]: v}} : {[k]: v};
    if (k.startsWith("campos.")) (it.campos ||= {})[k.slice(7)] = v; else it[k] = v;  // optimista
    it.editado = true;
    try { Object.assign(it, await api("/api/reg/" + encodeURIComponent(it.id), {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({c, cambios})})); cambio(); }
    catch (e) { if (k.startsWith("campos.")) it.campos[k.slice(7)] = antes; else it[k] = antes; regAviso(e); }
    pintar();
  }
  // cambio de revisión: la bandeja se repinta entera (secciones y contadores); el resto recarga la tabla (respeta el filtro de revisión)
  const trasRevisar = () => { S.sel.clear(); if (o.trasRevisar) return o.trasRevisar(); regContadores(c); cambio(); return cargar(); };
  const revisar = async (ids, accion, cambios) => {
    if (!ids.length) return;
    try { await post("/api/reg/revisar", {c, ids, accion, ...(cambios ? {cambios} : {})}); aviso(({aprobar: "Aprobado", restaurar: "Restaurado"}[accion] || "Descartado") + " · " + ids.length + ". Ctrl+Z para deshacer"); await trasRevisar(); } catch (e) { regAviso(e); }
  };
  const porId = id => S.items.find(x => x.id === id);
  const fusionar = (destino, origenes) => { if (destino && origenes.length) regDialogoFusion(c, [destino, ...origenes].map(porId), destino, trasRevisar); };
  async function deshacer() {
    try { const r = await post("/api/reg/deshacer", {c}); aviso(r.revertidas ? "Deshecho (" + r.revertidas + ")" : "Nada que deshacer"); await trasRevisar(); } catch (e) { regAviso(e); }
  }
  async function historial(it) {
    S.hist = it.id; panel.hidden = false; panel.replaceChildren(el("p", {className: "muted", textContent: "Cargando…"}));
    try {
      const h = await api("/api/reg/" + encodeURIComponent(it.id) + "/historial?c=" + encodeURIComponent(c));
      panel.replaceChildren(el("div", {className: "sec-h"}, el("h3", {textContent: "Historial · " + (it.codigo || it.titulo)}), el("button", {className: "sec sm", textContent: "Cerrar", onclick: () => { S.hist = null; panel.hidden = true; }})),
        ...(h.length ? h.map(x => el("div", {className: "reg-h"}, el("b", {textContent: x.accion}), el("small", {className: "muted", textContent: " " + new Date(x.t * (x.t < 1e11 ? 1000 : 1)).toLocaleString("es")}),
          el("div", {textContent: [x.antes && "Antes: " + (typeof x.antes === "string" ? x.antes : JSON.stringify(x.antes)), x.despues && "Después: " + (typeof x.despues === "string" ? x.despues : JSON.stringify(x.despues))].filter(Boolean).join("  →  ")}))) : [el("p", {className: "muted", textContent: "Sin cambios registrados."})]));
    } catch (e) { panel.replaceChildren(el("p", {className: "err", textContent: e.message})); }
  }

  function celda(it, col) {
    if (col.render) { const x = col.render(it); return x instanceof Node ? x : el("span", {textContent: x ?? ""}); }  // columna derivada, solo lectura
    const v = val(it, col.k), ed = col.editable !== false && it.revision !== "fusionado", t = col.tipo || "texto";
    const f = {ariaLabel: col.label + (it.codigo ? " de " + it.codigo : "")};
    if (!ed) return el("span", {textContent: v});
    let ctl;
    if (t === "select") {
      const ops = col.opciones || []; ctl = el("select", f, new Option("—", ""), ...(v && !ops.includes(v) ? [v, ...ops] : ops).map(x => new Option(x, x))); ctl.value = v;
      ctl.onchange = () => patch(it, col.k, ctl.value);
    } else {
      ctl = t === "area" ? el("textarea", {...f, rows: 2, value: v}) : el("input", {...f, type: t === "fecha" ? "date" : t === "num" ? "number" : "text", value: v});
      ctl.onchange = () => patch(it, col.k, t === "num" && ctl.value !== "" ? Number(ctl.value) : ctl.value);
      if (t === "area") ctl.onkeydown = e => { if (e.key === "Escape") ctl.blur(); };
    }
    return ctl;
  }
  function origen(it) {
    const ci = (it.citas || [])[0], fl = ci?.mid ? ci : it.mid ? {mid: it.mid, ver: it.ver, t: it.t || 0} : null;
    const tx = el("span", {className: "reg-or"});
    if (it.codigo) tx.append(el("b", {textContent: it.codigo}), " ");
    if (fl) tx.append(fLink({mid: fl.mid, ver: fl.ver, t: fl.t}, "[" + mmss(fl.t || 0) + "]"));
    else tx.append(el("span", {className: "muted", textContent: it.origen === "manual" ? "—" : "sin cita"}));
    if ((it.citas || []).length) tx.append(" ", el("button", {className: "link", textContent: S.abiertas.has(it.id) ? "ocultar cita" : "ver cita", title: (it.citas[0].texto || "").slice(0, 300), onclick: () => { S.abiertas.has(it.id) ? S.abiertas.delete(it.id) : S.abiertas.add(it.id); pintar(); }}));
    tx.append(regFusiona(it, c, trasRevisar));
    return tx;
  }
  function fila(it, i) {
    const chk = el("input", {type: "checkbox", checked: S.sel.has(it.id), ariaLabel: "Seleccionar " + (it.codigo || it.titulo), onchange: () => { chk.checked ? S.sel.add(it.id) : S.sel.delete(it.id); pintarAcc(); }});
    const tr = el("tr", {className: "reg-r" + (it.huerfano ? " huer" : "") + (it.revision === "propuesto" ? " prop" : "") + (it.revision === "descartado" || it.revision === "fusionado" ? " cerr" : "") + (i === S.foco ? " foco" : ""), tabIndex: 0, "data-id": it.id},
      el("td", {className: "c"}, chk), ...cols.map(col => el("td", {style: col.w ? "min-width:" + col.w + "px" : ""}, celda(it, col))),
      el("td", {}, origen(it)), el("td", {className: "reg-ins"}, ...regInsignias(it)),
      el("td", {className: "reg-ops"},
        ...(it.revision === "descartado" ? [el("button", {className: "sec sm", textContent: "Restaurar", onclick: () => revisar([it.id], "restaurar")})] : []),
        ...(it.revision === "propuesto" ? [el("button", {className: "sec sm", textContent: "Aprobar", onclick: () => revisar([it.id], "aprobar")}), el("button", {className: "link", textContent: "Descartar", onclick: () => revisar([it.id], "descartar")})] : []),
        ...regBotonSeparar(it, c, trasRevisar),
        el("button", {className: "link", textContent: "Historial", onclick: () => historial(it)}),
        ...(it.origen === "manual" ? [el("button", {className: "link", textContent: "Quitar", onclick: async () => { try { await api("/api/reg/" + encodeURIComponent(it.id) + "?c=" + encodeURIComponent(c), {method: "DELETE"}); await trasRevisar(); } catch (e) { regAviso(e); } }})] : [])));
    tr.onfocus = () => { S.foco = i; };
    const out = [tr];
    if (S.abiertas.has(it.id)) out.push(el("tr", {className: "reg-cita"}, el("td", {colSpan: cols.length + 4}, ...(it.citas || []).map(ci => el("blockquote", {}, "«" + (ci.texto || "") + "» ", ci.mid ? fLink({mid: ci.mid, ver: ci.ver, t: ci.t}, "[" + mmss(ci.t || 0) + "]") : "", ci.verificada === false ? el("span", {className: "badge w", textContent: "cita sin verificar"}) : "")))));
    return out;
  }
  function pintarAcc() {
    const n = S.sel.size, ids = [...S.sel];
    const dest = el("select", {ariaLabel: "Fusionar con", hidden: true}, new Option("Fusionar con…", ""), ...S.items.filter(x => !S.sel.has(x.id)).map(x => new Option((x.codigo ? x.codigo + " · " : "") + x.titulo.slice(0, 60), x.id)));
    dest.onchange = () => dest.value && fusionar(dest.value, ids);
    acciones.replaceChildren(...(o.sinFiltros ? [] : [el("button", {className: "sec", textContent: "Deshacer", title: "Ctrl+Z", onclick: deshacer})]), el("span", {className: "grow"}),
      ...(n ? [el("span", {className: "muted", textContent: n + (n === 1 ? " seleccionada" : " seleccionadas")}),
        el("button", {className: "pri sm", textContent: "Aprobar", onclick: () => revisar(ids, "aprobar")}), el("button", {className: "sec sm", textContent: "Descartar", onclick: () => revisar(ids, "descartar")}),
        el("button", {className: "sec sm", textContent: n > 1 ? "Fusionar…" : "Fusionar con…", onclick: () => { if (n > 1) regDialogoFusion(c, ids.map(porId), ids[0], trasRevisar); else { dest.hidden = false; dest.focus(); } }}), dest] : []));
  }
  function pintar() {
    const co = S.cont || {}, pr = co.por_revision || {}, ph = (S.items.filter(i => i.huerfano).length, co.huerfanos ?? 0);
    chips.replaceChildren(...REG_REV.filter(() => !fijos.revision).map(([k, t]) => el("button", {className: "f-pill", "aria-pressed": S.f.revision === k, textContent: t + " · " + (k === "fusionado" ? co.fusionadas ?? 0 : k ? pr[k] ?? 0 : (pr.propuesto ?? 0) + (pr.aprobado ?? 0)), onclick: () => { S.f.revision = k; lsSet("reg-rev", k); cargar(); }})),
      ...(ph ? [el("span", {className: "badge w", textContent: "Huérfanos · " + ph})] : []),
      ...(S.ids && typeof fChipFoco === "function" ? [fChipFoco(S.items.length, () => { S.ids = null; cargar(); }, o.foco.etiqueta)] : []));
    const resp = [...new Set(S.items.map(i => i.dueno).filter(Boolean))].sort(), est = [...new Set([...REG_ESTADOS, ...S.items.map(i => i.estado).filter(Boolean)])];
    const q = el("input", {type: "search", value: S.f.q, placeholder: "Buscar…", ariaLabel: "Buscar", onchange: ev => { S.f.q = ev.target.value; cargar(); }});
    const se = el("select", {ariaLabel: "Estado", onchange: ev => { S.f.estado = ev.target.value; cargar(); }}, new Option("Todos los estados", ""), ...est.map(x => new Option(x, x))); se.value = S.f.estado;
    const sd = el("select", {ariaLabel: "Responsable", onchange: ev => { S.f.dueno = ev.target.value; cargar(); }}, new Option("Todos los responsables", ""), ...resp.map(x => new Option(x, x))); sd.value = S.f.dueno;
    const add = el("button", {className: "sec", textContent: "+ Añadir", onclick: async () => {
      try { const e = await post("/api/reg", {c, tipo: tipo || o.tipoNuevo || "requisito", titulo: "Nuevo", detalle: "", estado: "abierto"}); S.foco = -1; S.items.unshift(e); cambio(); pintar(); raiz.querySelector("[data-id='" + e.id + "'] textarea, [data-id='" + e.id + "'] input[type=text]")?.select(); } catch (e) { regAviso(e); }
    }});
    barra.replaceChildren(q, ...(o.sinFiltros ? [] : [se, sd]), el("span", {className: "grow"}), ...(o.sinFiltros ? [] : [add]));
    pintarAcc();
    const todos = el("input", {type: "checkbox", ariaLabel: "Seleccionar todo", checked: S.items.length > 0 && S.sel.size === S.items.length, onchange: ev => { S.sel = ev.target.checked ? new Set(S.items.map(i => i.id)) : new Set(); pintar(); }});
    cuerpo.replaceChildren(S.items.length ? el("table", {className: "reg-t"}, el("thead", {}, el("tr", {}, el("th", {className: "c"}, todos), ...cols.map(col => el("th", {scope: "col", textContent: col.label})), el("th", {textContent: "Origen"}), el("th", {textContent: "Estado de revisión"}), el("th"))),
      el("tbody", {}, ...S.items.flatMap(fila))) : el("div", {className: "vacio", textContent: o.vacio || "Nada que mostrar con estos filtros. Usa «+ Añadir» o espera a que la IA proponga elementos."}));
  }
  // atajos: A aprobar, D descartar, E editar, J/K navegar, F fusionar con la anterior (solo fuera de campos de texto)
  function tecla(e) {
    if (e.ctrlKey && e.key.toLowerCase() === "z" && !regEnCampo()) { e.preventDefault(); deshacer(); return true; }
    if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey || regEnCampo()) return false;
    const t = e.target;
    if (!(t === raiz || t.closest?.(".reg-r")) || !raiz.contains(t) || t.closest?.("button, a, select, summary, [contenteditable]") || document.querySelector("dialog[open], [role=dialog], [aria-modal=true]")) return false;
    const k = e.key.toLowerCase(), it = S.items[S.foco];
    if (k === "j" || k === "k") { S.foco = Math.max(0, Math.min(S.items.length - 1, S.foco + (k === "j" ? 1 : -1))); const tr = raiz.querySelectorAll(".reg-r"); tr.forEach((r, i) => r.classList.toggle("foco", i === S.foco)); tr[S.foco]?.focus(); }
    else if (!it) return false;
    else if (k === "a") revisar([it.id], "aprobar");
    else if (k === "d") revisar([it.id], "descartar");
    else if (k === "e") raiz.querySelectorAll(".reg-r")[S.foco]?.querySelector("textarea, input[type=text], select")?.focus();
    else if (k === "f") { const prev = S.items[S.foco - 1]; if (prev) fusionar(prev.id, [it.id]); }
    else return false;
    e.preventDefault(); return true;
  }
  const api_ = {recargar: cargar, tecla, vivo: () => raiz.isConnected};
  if (!REG_ACTIVA?.vivo()) REG_ACTIVA = api_;  // la anterior pudo desaparecer al repintar (bandeja): si no, Ctrl+Z quedaría muerto
  cargar();
  return api_;
}
document.addEventListener("keydown", e => { if (REG_ACTIVA) { if (!REG_ACTIVA.vivo()) REG_ACTIVA = null; else REG_ACTIVA.tecla(e); } });

// ---- Bandeja de revisión: lo propuesto por la IA agrupado por tipo + sugerencias, relaciones y huérfanos ----
async function registroBandeja(host, c, onChange) {
  const raiz = el("div", {className: "reg-bandeja"});  // se monta al tener los datos: al repintar no parpadea ni salta el scroll
  if (!host.firstChild) host.append(el("p", {className: "muted", textContent: "Cargando…"}));
  const rec = () => { onChange && onChange(); return registroBandeja(host, c, onChange); };
  const deshacer = async () => { try { const r = await post("/api/reg/deshacer", {c}); aviso(r.revertidas ? "Deshecho (" + r.revertidas + ")" : "Nada que deshacer"); await rec(); } catch (e) { regAviso(e); } };
  let b;
  try { b = await api("/api/reg/bandeja?c=" + encodeURIComponent(c)); } catch (e) { host.replaceChildren(raiz); raiz.append(el("p", {className: "err", textContent: e.message})); return; }
  const grupos = {};
  for (const p of b.propuestos || []) (grupos[p.tipo] ||= []).push(p);
  const aprobar = async ids => { try { await post("/api/reg/revisar", {c, ids, accion: "aprobar"}); aviso("Aprobado · " + ids.length + ". Ctrl+Z para deshacer"); rec(); } catch (e) { regAviso(e); } };
  const todos = (b.propuestos || []).map(p => p.id);
  let pasada = null;  // último lote de IA (poblar/derivar) más reciente
  try { const e = await Promise.all(["poblar", "derivar"].map(k => api("/api/reg/" + k + "/estado?c=" + encodeURIComponent(c)))); pasada = e.map(x => x.ultimo).filter(u => u && u.lote).sort((x, y) => y.t - x.t)[0] || null; } catch (e) { /* sin estado: sin botón */ }
  host.replaceChildren(raiz);
  // Ctrl+Z en la bandeja aunque no quede ninguna tabla (p. ej. tras «Aprobar todo»); las tablas toman el relevo al tocarlas
  REG_ACTIVA = {recargar: rec, vivo: () => raiz.isConnected, tecla: e => { if (e.ctrlKey && e.key.toLowerCase() === "z" && !regEnCampo()) { e.preventDefault(); deshacer(); return true; } return false; }};
  raiz.append(el("div", {className: "sec-h"}, el("h2", {textContent: "Para revisar · " + todos.length}), el("span", {className: "grow"}),
    el("button", {className: "sec", textContent: "Deshacer", title: "Ctrl+Z", onclick: deshacer}),
    ...(pasada ? [el("button", {className: "sec", textContent: "Deshacer última pasada IA", onclick: async () => { try { const r = await post("/api/reg/deshacer-pasada", {c, lote: pasada.lote}); aviso("Pasada deshecha (" + r.revertidas + ")"); rec(); } catch (e) { regAviso(e); } }})] : []),
    el("button", {className: "pri", textContent: "Aprobar todo", disabled: !todos.length, onclick: () => aprobar(todos)})),
    el("p", {className: "muted", textContent: "Lo marcado «IA · propuesto» lo ha extraído la IA con su cita. Atajos: J/K navegar, A aprobar, D descartar, E editar, F fusionar con la anterior, Ctrl+Z deshacer."}));
  if (!todos.length) raiz.append(el("p", {className: "vacio", textContent: "No hay nada pendiente de revisar."}));
  for (const [t, l] of Object.entries(grupos)) {
    const w = el("div", {className: "card reg-g"});
    raiz.append(el("section", {}, el("div", {className: "sec-h"}, el("h3", {textContent: (REG_TIPOS[t] || t) + " · " + l.length}), el("span", {className: "grow"}),
      el("button", {className: "sec sm", textContent: "Aprobar todo (" + (REG_TIPOS[t] || t).toLowerCase() + ")", onclick: () => aprobar(l.map(x => x.id))})), w));
    registroTabla(w, {c, tipo: t, fijos: {revision: "propuesto"}, sinFiltros: true, onChange: () => { onChange && onChange(); }, trasRevisar: rec, vacio: "Revisado."});
  }
  if ((b.sugerencias || []).length) raiz.append(el("section", {className: "card"}, el("div", {className: "sec-h"}, el("h3", {textContent: "Sugerencias de seguimiento · " + b.sugerencias.length})),
    el("ul", {className: "f-lst"}, ...b.sugerencias.map(s => {
      const g = s.sugerencia || {}, ci = g.cita ? [" «" + g.cita + "» ", ...(g.mid ? [fLink({mid: g.mid, ver: g.ver, t: g.t}, "[" + mmss(g.t || 0) + "]"), " "] : [])] : [" "];
      const res = accion => async () => { try { await post("/api/reg/" + encodeURIComponent(s.id) + "/sugerencia", {c, accion}); aviso((accion === "aceptar" ? "Aceptada" : "Rechazada") + ". Ctrl+Z para deshacer"); rec(); } catch (e) { regAviso(e); } };
      return el("li", {}, (s.titulo || "") + " ", el("span", {className: "badge w", textContent: g.tipo === "hecho" ? "Propone: hecho" : "Propone: actualizado (nota)"}), ...ci,
        el("button", {className: "sec sm", textContent: "Aceptar", onclick: res("aceptar")}), el("button", {className: "link", textContent: "Rechazar", onclick: res("rechazar")}));
    }))));
  if ((b.relaciones_propuestas || []).length) raiz.append(el("section", {className: "card"}, el("div", {className: "sec-h"}, el("h3", {textContent: "Relaciones propuestas · " + b.relaciones_propuestas.length})),
    el("ul", {className: "f-lst"}, ...b.relaciones_propuestas.map(r => el("li", {}, "«" + r.a_titulo + "» " + (r.tipo === "sustituye" || !r.tipo ? "sustituye a" : r.tipo) + " «" + r.b_titulo + "» ",
      el("button", {className: "sec sm", textContent: "Aceptar", onclick: async () => { try { await post("/api/reg/relacion", {c, a: r.a, b: r.b, tipo: r.tipo}); rec(); } catch (e) { regAviso(e); } }}),
      el("button", {className: "link", textContent: "Rechazar", onclick: async () => { try { await api("/api/reg/relacion?" + new URLSearchParams({c, a: r.a, b: r.b, tipo: r.tipo || "sustituye"}), {method: "DELETE"}); rec(); } catch (e) { regAviso(e); } }}))))));
  if ((b.huerfanos || []).length) raiz.append(el("section", {className: "card"}, el("div", {className: "sec-h"}, el("h3", {textContent: "Huérfanos · " + b.huerfanos.length}), el("small", {className: "muted", textContent: "Ya no están en el documento de origen. Confirma si siguen vigentes o descártalos."})),
    el("ul", {className: "f-lst"}, ...b.huerfanos.map(h => el("li", {}, el("span", {className: "badge w", textContent: "Huérfano: ya no está en el documento"}), " " + (h.codigo ? h.codigo + " · " : "") + h.titulo + " ",
      el("button", {className: "link", textContent: "Descartar", onclick: () => revisarUno(c, h.id, rec)}))))));
}
async function revisarUno(c, id, rec) { try { await post("/api/reg/revisar", {c, ids: [id], accion: "descartar"}); rec(); } catch (e) { regAviso(e); } }
