// Carpeta = expediente (diseño: design/Carpeta.dc.html): Resumen | Pendientes | Línea de tiempo | Preguntar | Comparar | Ajustes.
// Se engancha a app.js por pintarHome() -> carpetaVista(c) y por sondear() -> carpetaTrasCola(); usa los ganchos #f-tabs / #f-panel / #f-nuevo.
const FTABS = [["resumen", "Resumen"], ["revision", "Revisión"], ["pendientes", "Pendientes"], ["requisitos", "Requisitos"], ["historias", "Historias"], ["interesados", "Interesados"], ["decisiones", "Decisiones"], ["informe", "Informe"], ["linea", "Línea de tiempo"], ["preguntar", "Preguntar"], ["comparar", "Comparar"], ["ajustes", "Ajustes"]];
// pestañas del registro (F3/F4): tipo de entidad que muestra cada una. Para sustituir el placeholder de una vista (F4) basta con registrar su función en FVISTAS[clave] = (c, e) => nodos.
const FREG = {requisitos: "requisito", historias: "historia", interesados: "interesado", decisiones: "decision"}, FVISTAS = {};
let fReg = {rev: 0, tipos: {}, proyecto: false};  // contadores del registro de la carpeta abierta (para mostrar/ocultar pestañas)
const fTabVisible = k => k === "revision" || !(k in FREG || k === "informe") || fReg.proyecto || !!fReg.tipos[FREG[k]];
const fTabTxt = (k, t) => k === "revision" ? t + " (" + fReg.rev + ")" : t;
async function fCargaReg(c, tipoCarpeta) {
  try {
    const r = await api("/api/reg?" + new URLSearchParams({c}));
    fReg = {rev: r.contadores?.por_revision?.propuesto || 0, tipos: r.contadores?.por_tipo || {}, proyecto: tipoCarpeta === "Proyecto"};
  } catch { fReg = {rev: 0, tipos: {}, proyecto: tipoCarpeta === "Proyecto"}; }
  pintaTabs();
}
let ftab = lsGet("ftab", "resumen"), fuC = null, fsucio = true, fseq = 0, fpen = {estado: "abierto", resp: "", orden: "plazo"}, fcmp = {a: "", b: ""};
const fFecha = iso => iso ? new Date(iso + "T12:00").toLocaleDateString("es", {day: "numeric", month: "short", year: "numeric"}) : "";
const carpetaTrasCola = () => { fsucio = true; };
const fEnCola = async (url, body) => { await post(url, {...body, gpu: $("usar-gpu").checked}); aviso("Añadido a la cola"); sondear(); };
// abre un documento en su minuto exacto (como las marcas del propio documento)
async function irMinuto(mid, ver, t) { await abrir(mid, ver); if (cur.video && t) mpSeek(t, cur.videourl, cur.m.label); }
const fLink = (r, txt) => el("a", {href: "#", className: "ts", textContent: txt || (r.doc + " · " + mmss(r.t || 0)), onclick: e => { e.preventDefault(); fallo(irMinuto)(r.mid, r.ver, r.t); }});

function carpetaVista(c) {
  const on = typeof c === "string" && c !== "";
  $("f-tabs").hidden = $("f-panel").hidden = $("f-nuevo").hidden = !on;
  for (const id of ["f-plant", "f-estilo", "f-preguntar"]) $(id).hidden = true;  // pasan a las pestañas Ajustes y Preguntar
  $("docs-w").hidden = on && ftab !== "resumen";
  if (!on) { fuC = null; return; }
  $("f-nuevo").textContent = "+ Nuevo " + nm("documento");
  pintaTabs();
  if (fuC === c && !fsucio) return;
  fuC = c; fsucio = false; pintaTabs(); fRender();
}
function pintaTabs() {
  if (fuC === null) return;
  if (!fTabVisible(ftab)) ftab = "resumen";
  $("f-tabs").replaceChildren(...FTABS.filter(([k]) => fTabVisible(k)).map(([k, t]) => el("button", {role: "tab", textContent: fTabTxt(k, t), "aria-selected": k === ftab, onclick: () => { ftab = k; lsSet("ftab", k); fsucio = true; pintarHome(); }})));
}
$("f-nuevo").onclick = () => formNuevo();
// «+ Nuevo documento» dentro de la carpeta hereda perfil, estilo (al exportar), glosario y carpeta (en el servidor) e idioma por defecto
const formNuevo0 = formNuevo;
formNuevo = function (m, a) {
  formNuevo0(m, a);
  const c = m ? m.carpeta : typeof fsel === "string" ? fsel : "";
  if (c) api("/api/exp?c=" + encodeURIComponent(c)).then(e => { if (e.ajustes.idioma && !m) { $("idioma").value = e.ajustes.idioma; $("idioma").onchange(); } }).catch(() => {});
};

async function fRender() {
  const c = fuC, n = ++fseq, p = $("f-panel");
  if (p.contains($("qpanel"))) { $("qpanel").hidden = true; document.querySelector("main").append($("qpanel")); }  // el panel de preguntas se conserva al cambiar de pestaña
  try {
    const e = await api("/api/exp?c=" + encodeURIComponent(c));
    await fCargaReg(c, e.tipo);
    if (n !== fseq) return;
    const nodos = await ({resumen: tResumen, revision: tRevision, requisitos: tVista, historias: tVista, interesados: tVista, decisiones: tVista, informe: tVista, pendientes: tPendientes, linea: tLinea, preguntar: tPreguntar, comparar: tComparar, ajustes: tAjustes})[ftab](c, e, ftab);
    if (n !== fseq) return;
    p.replaceChildren(...nodos);
    const pl_ = PL.find(t => t.id === e.perfil);
    $("fsub").textContent = [e.tipo, pl_ && "Perfil: " + pl_.nombre, ...e.datos.slice(0, 2).map(d => d.v), plural(e.n_docs), e.pend ? e.pend + (e.pend === 1 ? " pendiente" : " pendientes") : ""].filter(Boolean).join(" · ");
    $("docs-w").hidden = ftab !== "resumen";
  } catch (err) { if (n === fseq) p.replaceChildren(el("p", {className: "err", textContent: err.message})); }
}
const fRe = () => { fsucio = true; return fRender(); };
const H = (t, ...k) => el("div", {className: "sec-h"}, el("h2", {textContent: t}), ...k);

// ---- inicio: pendientes abiertos de todas las carpetas (vencidos y con plazo primero) ----
let hpSeq = 0;
async function homePend() {
  const cs = carpetas.filter(c => RES[c]?.pend), n = ++hpSeq;
  const rs = await Promise.all(cs.map(c => api("/api/exp/pendientes?" + new URLSearchParams({c, estado: "abierto", orden: "plazo"}))
    .then(r => r.items.filter(p => p.estado === "abierto").map(p => ({...p, c}))).catch(() => [])));
  if (n !== hpSeq) return;
  const its = rs.flat().sort((a, b) => (!!b.vencido - !!a.vencido) || (!!b.pronto - !!a.pronto) || (a.fecha || "9").localeCompare(b.fecha || "9"));
  $("h-pend").hidden = !its.length; $("h-pend-n").textContent = its.length > 5 ? "5 de " + its.length : "";
  $("h-pend-l").replaceChildren(...its.slice(0, 5).map(p => {
    const chk = el("input", {type: "checkbox", ariaLabel: "Marcar hecho: " + p.texto, onchange: fallo(async () => { chk.disabled = true; await post("/api/exp/pendientes", {c: p.c, id: p.id, estado: "hecho"}); await cargarLista(); })});
    const f = p.vencido ? el("b", {className: "hp-f err", textContent: "Vencido"}) : el("span", {className: "hp-f" + (p.pronto ? " w" : ""), textContent: p.plazo || (p.fecha ? fFecha(p.fecha) : "Sin fecha")});
    return el("li", {}, chk, el("div", {className: "hp-t"}, el("span", {textContent: p.texto}),
      el("small", {}, el("a", {href: "#", textContent: p.c, onclick: e => { e.preventDefault(); fsel = p.c; ftab = "pendientes"; lsSet("ftab", ftab); fsucio = true; pintarHome(); }}), p.resp ? " · " + p.resp : "")), f);
  }));
}

// ---- banner «parece hecho» ----
function bannerSug(c, sug) {
  if (!sug.length) return [];
  const hechos = sug.filter(p => p.sugerido.tipo === "hecho").length, n = sug.length;
  return [el("div", {className: "aviso f-sug"}, el("div", {}, el("b", {textContent: n === 1 ? "Un documento nuevo parece cerrar o cambiar 1 pendiente" : "Los documentos nuevos parecen cerrar o cambiar " + n + " pendientes"}),
    el("div", {className: "muted", textContent: sug.slice(0, 2).map(p => "«" + p.texto + "»").join(" y ") + (n > 2 ? "…" : "") + " Confirma antes de cerrarlos."})),
    el("div", {className: "row"}, ...(ftab === "pendientes" ? [] : [el("button", {className: "sec", textContent: "Revisar", onclick: () => { ftab = "pendientes"; lsSet("ftab", ftab); fsucio = true; pintarHome(); }})]),
      el("button", {className: "pri", textContent: hechos === n ? "Cerrar los " + n : "Aceptar los " + n, onclick: fallo(async () => { await post("/api/exp/sugerencia", {c, todas: true, aceptar: true}); await fRe(); })})))];
}

// ---- Resumen ----
async function tResumen(c, e) {
  const [est, pen] = await Promise.all([api("/api/exp/estado?c=" + encodeURIComponent(c)), api("/api/exp/pendientes?c=" + encodeURIComponent(c))]);
  const nodos = [...bannerSug(c, pen.sugeridos)];
  // datos de la carpeta (clave/valor libres con sugerencias por tipo)
  let datos = e.datos.map(d => ({...d})), tipo = e.tipo;
  const caja = el("div", {className: "card"}), pintD = () => {
    const rows = datos.map((d, i) => el("div", {className: "row f-dato"}, el("input", {value: d.k, ariaLabel: "Dato", placeholder: "Dato", oninput: ev => d.k = ev.target.value, style: "flex:0 1 200px"}),
      el("input", {value: d.v, ariaLabel: "Valor de " + d.k, placeholder: "Valor", oninput: ev => d.v = ev.target.value}),
      el("button", {className: "sec sm", textContent: "×", ariaLabel: "Quitar " + d.k, onclick: () => { datos.splice(i, 1); pintD(); }})));
    const sug = e.sugerencias.filter(k => !datos.some(d => d.k === k));
    caja.replaceChildren(H("Datos de " + (tipo ? "la " : "") + "carpeta" + (tipo ? " · " + tipo : "")), ...(e.aviso ? [el("p", {className: "aviso w", textContent: e.aviso})] : []), ...rows,
      el("div", {className: "row wrap", style: "margin-top:8px"}, ...sug.map(k => el("button", {className: "sec sm", textContent: "+ " + k, onclick: () => { datos.push({k, v: ""}); pintD(); }})),
        el("button", {className: "sec sm", textContent: "+ Otro dato", onclick: () => { datos.push({k: "", v: ""}); pintD(); }}), el("span", {className: "grow"}),
        el("button", {className: "pri sm", textContent: "Guardar datos", onclick: fallo(async () => { await post("/api/exp/datos", {c, datos}); aviso("Datos guardados"); await fRe(); })})));
  };
  pintD(); nodos.push(caja);
  // estado actual
  const dv = est.decisiones, red = est.redaccion;
  nodos.push(el("div", {className: "card"}, H("Estado actual", el("button", {className: "sec sm", textContent: red ? "Regenerar resumen" : "Generar resumen", onclick: fallo(() => fEnCola("/api/exp/estado", {c}))})),
    ...(red ? [el("ul", {className: "f-red"}, ...red.frases.map(f => el("li", {}, f.texto + " ", ...f.refs.flatMap(r => [fLink(r), " "])))),
      ...(est.obsoleta ? [el("p", {className: "muted", textContent: "Hay documentos nuevos desde que se generó: regenéralo para incluirlos."})] : [])] : [el("p", {className: "muted", textContent: "Aún no hay resumen redactado; abajo, los datos con su fuente."})]),
    el("h3", {textContent: "Decisiones vigentes · " + dv.vigentes.length}), ...(dv.vigentes.length ? [el("ul", {className: "f-lst"}, ...dv.vigentes.map(x => el("li", {}, x.texto + " ", fLink(x))))] : [el("p", {className: "muted", textContent: "Ninguna."})]),
    ...(dv.superadas.length ? [el("details", {}, el("summary", {textContent: "Sustituidas por una decisión posterior · " + dv.superadas.length}),
      el("ul", {className: "f-lst"}, ...dv.superadas.map(x => el("li", {}, el("s", {textContent: x.texto}), " ", fLink(x), " → ahora: " + x.por.texto + " ", fLink(x.por)))))] : []),
    el("h3", {textContent: "Pendientes abiertos · " + est.pendientes.length}),
    el("p", {}, est.pendientes.slice(0, 3).map(p => p.texto).join(" · ") || "Ninguno. ", " ", el("a", {href: "#", textContent: "Ver todos", onclick: ev => { ev.preventDefault(); ftab = "pendientes"; lsSet("ftab", ftab); fsucio = true; pintarHome(); }})),
    ...(est.cambios ? [el("h3", {textContent: "Desde el documento anterior"}), cambiosResumen(est.cambios, c)] : [])));
  return nodos;
}
function cambiosResumen(cm, c) {
  const n = (k, t) => cm[k][t].length, txt = [["decisiones", "decisiones"], ["tareas", "tareas"], ["puntos", "puntos clave"]].map(([k, t]) => `${t}: ${n(k, "nuevo")} nuevas, ${n(k, "cambiado")} cambiadas, ${n(k, "ya_no")} ya no aparecen`).join(" · ");
  return el("p", {}, txt + " ", el("a", {href: "#", textContent: "Comparar", onclick: e => { e.preventDefault(); fcmp = {a: cm.a.mid, b: cm.b.mid}; ftab = "comparar"; lsSet("ftab", ftab); fsucio = true; pintarHome(); }}));
}

// ---- Pendientes ----
async function tPendientes(c, e) {
  const q = new URLSearchParams({c, estado: fpen.estado === "cerrados" ? "todos" : fpen.estado === "decisiones" ? "abierto" : fpen.estado, resp: fpen.resp, orden: fpen.orden});
  const [r, est] = await Promise.all([api("/api/exp/pendientes?" + q), fpen.estado === "decisiones" ? api("/api/exp/estado?c=" + encodeURIComponent(c)) : null]);
  const pill = (k, t, on) => el("button", {className: "f-pill", "aria-pressed": fpen.estado === k, textContent: t, onclick: () => { fpen.estado = k; fRe(); }});
  const sel = el("select", {ariaLabel: "Responsable", onchange: ev => { fpen.resp = ev.target.value; fRe(); }}, new Option("Todos", ""), ...r.responsables.map(x => new Option(x, x)));
  sel.value = fpen.resp;
  const ord = el("select", {ariaLabel: "Ordenar", onchange: ev => { fpen.orden = ev.target.value; fRe(); }}, new Option("Por plazo", "plazo"), new Option("Por documento", "doc"));
  ord.value = fpen.orden;
  const cerr = r.n.hecho + r.n.descartado;
  const barra = el("div", {className: "toolbar f-barra"}, el("div", {className: "row wrap"}, pill("abierto", "Abiertos · " + r.n.abierto), pill("cerrados", "Cerrados · " + cerr), pill("decisiones", "Decisiones")),
    el("span", {className: "grow"}), ...(fpen.estado === "decisiones" ? [] : [el("label", {className: "row"}, "Responsable", sel), el("label", {className: "row"}, "Orden", ord)]));
  const items = fpen.estado === "cerrados" ? r.items.filter(p => p.estado !== "abierto") : r.items;
  let lista;
  if (fpen.estado === "decisiones") {
    lista = el("div", {className: "card"}, el("h3", {textContent: "Decisiones vigentes (la última manda)"}), el("ul", {className: "f-lst"}, ...est.decisiones.vigentes.map(x => el("li", {}, x.texto + " ", fLink(x)))),
      ...(est.decisiones.superadas.length ? [el("details", {}, el("summary", {textContent: "Sustituidas · " + est.decisiones.superadas.length}), el("ul", {className: "f-lst"}, ...est.decisiones.superadas.map(x => el("li", {}, el("s", {textContent: x.texto}), " ", fLink(x)))))] : []));
  } else lista = el("div", {className: "f-tabla"}, el("div", {className: "pr h"}, el("span"), el("span", {textContent: "Pendiente"}), el("span", {textContent: "Responsable"}), el("span", {textContent: "Fecha límite"}), el("span", {textContent: "Origen"})),
    ...(items.length ? items.map(p => filaPend(c, p)) : [el("div", {className: "vacio", textContent: fpen.estado === "abierto" ? "No hay pendientes abiertos." : "Nada cerrado todavía."})]));
  const add = el("form", {className: "row wrap f-add"}, el("input", {id: "pm-t", placeholder: "Añadir un pendiente a mano…", ariaLabel: "Pendiente", style: "flex:2 1 220px"}),
    el("input", {id: "pm-r", placeholder: "Responsable", ariaLabel: "Responsable", style: "flex:1 1 130px"}), el("input", {id: "pm-p", placeholder: "Plazo (15/03/2026, el viernes…)", ariaLabel: "Plazo", style: "flex:1 1 170px"}), el("button", {className: "sec", textContent: "Añadir"}));
  add.onsubmit = fallo(async ev => { ev.preventDefault(); await post("/api/exp/pendientes", {c, texto: $("pm-t").value, resp: $("pm-r").value, plazo: $("pm-p").value}); await fRe(); });
  return [...bannerSug(c, r.sugeridos), barra, lista, add, el("p", {className: "muted", textContent: "Cada pendiente enlaza al minuto exacto del documento donde se acordó. Marcar o desmarcar es siempre a mano: el seguimiento automático solo propone."})];
}
function filaPend(c, p) {
  const chk = el("input", {type: "checkbox", checked: p.estado !== "abierto", ariaLabel: p.estado === "abierto" ? "Marcar hecho: " + p.texto : "Reabrir: " + p.texto});
  chk.onchange = fallo(async () => { await post("/api/exp/pendientes", {c, id: p.id, estado: chk.checked ? "hecho" : "abierto"}); await fRe(); });
  const sg = p.sugerido && p.estado === "abierto" ? p.sugerido : null;
  const plazo = p.vencido ? [el("b", {className: "err", textContent: "Vencido"}), " " + (p.plazo || fFecha(p.fecha))] : p.pronto ? [el("span", {className: "badge w", textContent: "Vence pronto"}), " " + (p.plazo || fFecha(p.fecha))] : [p.plazo || (p.fecha ? fFecha(p.fecha) : "Sin fecha")];
  const acc = [];
  if (p.estado === "abierto") acc.push(el("button", {className: "link", textContent: "Descartar", ariaLabel: "Descartar: " + p.texto, onclick: fallo(async () => { await post("/api/exp/pendientes", {c, id: p.id, estado: "descartado"}); await fRe(); })}));
  if (p.manual) acc.push(el("button", {className: "link", textContent: "Quitar", ariaLabel: "Quitar: " + p.texto, onclick: fallo(async () => { await post("/api/exp/pendientes", {c, id: p.id, borrar: true}); await fRe(); })}));
  return el("div", {className: "pr" + (sg ? " sug" : "") + (p.estado !== "abierto" ? " cerr" : "")}, el("span", {className: "pc"}, chk),
    el("span", {className: "pt"}, el("span", {className: p.estado === "abierto" ? "" : "tach", textContent: p.texto}), " ", el("small", {className: "tipo", textContent: p.tipo}),
      ...(p.estado === "descartado" ? [el("span", {className: "badge", textContent: "descartado"})] : []), ...(sg ? [el("b", {className: "q", textContent: sg.tipo === "hecho" ? " ¿cerrado?" : " ¿actualizado?"})] : []),
      ...(p.nota ? [el("small", {textContent: p.nota})] : []),
      ...(sg ? [el("div", {className: "ev"}, "«" + sg.cita + "» ", fLink({mid: sg.mid, ver: sg.ver, t: sg.t}, sg.doc + " · " + mmss(sg.t)), " ",
        el("button", {className: "sec sm", textContent: sg.tipo === "hecho" ? "Sí, cerrar" : "Sí, anotar", onclick: fallo(async () => { await post("/api/exp/sugerencia", {c, id: p.id, aceptar: true}); await fRe(); })}),
        el("button", {className: "link", textContent: "No", onclick: fallo(async () => { await post("/api/exp/sugerencia", {c, id: p.id, aceptar: false}); await fRe(); })}))] : []), ...(acc.length ? [el("div", {className: "ac"}, ...acc)] : [])),
    el("span", {className: "pw", textContent: p.resp || "—"}), el("span", {className: "pf"}, ...plazo), el("span", {className: "po"}, p.manual ? "Manual" : fLink(p)));
}

// ---- Línea de tiempo ----
async function tLinea(c) {
  const ev = await api("/api/exp/linea?c=" + encodeURIComponent(c));
  const f = el("form", {className: "row wrap f-add"}, el("input", {type: "date", id: "nt-f", ariaLabel: "Fecha de la nota", value: new Date().toISOString().slice(0, 10), style: "flex:0 0 160px"}),
    el("input", {id: "nt-t", placeholder: "Nota sobre la carpeta (una llamada, un acuerdo verbal…)", ariaLabel: "Nota", style: "flex:3 1 260px"}), el("button", {className: "pri", textContent: "Añadir nota"}));
  f.onsubmit = fallo(async ev2 => { ev2.preventDefault(); await post("/api/exp/notas", {c, texto: $("nt-t").value, fecha: $("nt-f").value}); await fRe(); });
  const T = {estado: {hecho: "marcó como hecho", descartado: "descartó", abierto: "reabrió", actualizado: "anotó una actualización de"}};
  const fila = x => {
    let tag, cuerpo;
    if (x.tipo === "doc") { tag = "Documento"; cuerpo = [fLink({mid: x.mid, ver: x.ver, t: 0}, x.titulo), el("div", {className: "muted", textContent: (x.resumen || "") + (x.n_pend ? " · " + x.n_pend + " pendientes" : "")})]; }
    else if (x.tipo === "nota") { tag = "Nota"; cuerpo = [x.texto + " ", el("button", {className: "link", textContent: "Quitar", ariaLabel: "Quitar nota", onclick: fallo(async () => { await post("/api/exp/notas", {c, id: x.id, borrar: true}); await fRe(); })})]; }
    else if (x.tipo === "pendiente") { tag = "Pendiente"; cuerpo = [(T.estado[x.a] || x.a) + " «" + x.texto + "»" + (x.cita ? " · «" + x.cita + "»" : "")]; }
    else if (x.tipo === "sugerido") { tag = "Seguimiento"; cuerpo = ["Parece " + (x.a === "hecho" ? "hecho" : "actualizado") + ": «" + x.texto + "» · «" + x.cita + "» ", fLink({mid: x.mid, ver: "", t: x.t_doc}, x.doc + " · " + mmss(x.t_doc))]; }
    else { tag = "Pendiente"; cuerpo = ["Añadido a mano: «" + x.texto + "»"]; }
    return el("li", {}, el("span", {className: "badge" + (x.tipo === "doc" ? " acc" : "")}, tag), el("span", {className: "d", textContent: fFecha(x.fecha)}), el("span", {className: "n tl-c"}, ...cuerpo));
  };
  return [f, el("ul", {className: "list card f-tl"}, ...(ev.length ? ev.map(fila) : [el("li", {className: "vacio", textContent: "Todavía no hay nada en la línea de tiempo."})]))];
}

// ---- Preguntar (el mismo panel #qpanel de siempre, montado aquí) ----
async function tPreguntar(c) {
  const w = el("div", {id: "f-preg"});
  setQ("c:" + c); w.append($("qpanel"));
  return [w];
}

// ---- Comparar ----
async function tComparar(c) {
  const ev = await api("/api/exp/linea?c=" + encodeURIComponent(c)), ds = ev.filter(x => x.tipo === "doc").reverse();
  if (ds.length < 2) return [el("p", {className: "vacio", textContent: "Hacen falta al menos dos documentos para compararlos."})];
  if (!ds.some(d => d.mid === fcmp.a) || !ds.some(d => d.mid === fcmp.b) || fcmp.a === fcmp.b) fcmp = {a: ds[ds.length - 2].mid, b: ds[ds.length - 1].mid};
  const mk = (k, t) => { const s = el("select", {ariaLabel: t, onchange: () => { fcmp[k] = s.value; fRe(); }}, ...ds.map(d => new Option(d.titulo + " · " + fFecha(d.fecha), d.mid))); s.value = fcmp[k]; return el("label", {className: "row"}, t, s); };
  const barra = el("div", {className: "toolbar"}, mk("a", "Antes"), mk("b", "Después"));
  const cm = await api("/api/exp/comparar?" + new URLSearchParams({c, a: fcmp.a, b: fcmp.b}));
  const it = (x, extra) => el("li", {}, x.texto + (x.extra ? " (" + x.extra + ")" : "") + " ", fLink(x), ...(extra || []));
  const bloque = (k, t) => {
    const r = cm[k], v = r.nuevo.length + r.cambiado.length + r.ya_no.length;
    return el("div", {className: "card"}, H(t, el("span", {className: "muted", textContent: r.igual + " sin cambios"})),
      ...(v ? [] : [el("p", {className: "muted", textContent: "Sin diferencias."})]),
      ...(r.nuevo.length ? [el("h4", {textContent: "Nuevo · " + r.nuevo.length}), el("ul", {className: "f-lst"}, ...r.nuevo.map(x => it(x)))] : []),
      ...(r.cambiado.length ? [el("h4", {textContent: "Cambiado · " + r.cambiado.length}), el("ul", {className: "f-lst"}, ...r.cambiado.map(x => el("li", {}, el("s", {textContent: x.antes.texto + (x.antes.extra ? " (" + x.antes.extra + ")" : "")}), " ", fLink(x.antes), " → " + x.ahora.texto + (x.ahora.extra ? " (" + x.ahora.extra + ")" : "") + " ", fLink(x.ahora))))] : []),
      ...(r.ya_no.length ? [el("h4", {textContent: "Ya no aparece · " + r.ya_no.length}), el("ul", {className: "f-lst"}, ...r.ya_no.map(x => it(x)))] : []));
  };
  const red = cm.redaccion;
  return [barra, el("div", {className: "card"}, H("Resumen de las diferencias", el("button", {className: "sec sm", textContent: red ? "Regenerar" : "Redactar", onclick: fallo(() => fEnCola("/api/exp/comparar", {c, a: fcmp.a, b: fcmp.b}))})),
    ...(red ? [el("ul", {className: "f-red"}, ...red.frases.map(f => el("li", {}, f.texto + " ", ...f.refs.flatMap(r => [fLink(r), " "]))))] : [el("p", {className: "muted", textContent: "La comparación de abajo es automática (por parecido de significado); redactarla con el modelo es opcional."})])),
    bloque("decisiones", "Decisiones"), bloque("tareas", "Tareas"), bloque("puntos", "Puntos clave")];
}

// ---- Ajustes de la carpeta ----
async function tAjustes(c, e) {
  const g = await api("/api/exp/glosario?c=" + encodeURIComponent(c));
  const fld = (t, ctl, ayuda) => el("div", {className: "field"}, el("label", {textContent: t}), ctl, ...(ayuda ? [el("small", {textContent: ayuda})] : []));
  const perf = el("select", {ariaLabel: "Perfil por defecto", onchange: fallo(async ev => { await post("/api/carpeta", {nombre: c, plantilla: ev.target.value === "acta" ? "" : ev.target.value}); CP = await api("/api/carpetas/plantillas"); aviso("Perfil guardado"); fsucio = true; fRender(); })}, ...PL.map(t => new Option(t.nombre, t.id)));
  perf.value = e.perfil;
  const est = el("select", {ariaLabel: "Estilo por defecto", onchange: fallo(async ev => { await post("/api/carpeta", {nombre: c, estilo: ev.target.value}); CE = await api("/api/carpetas/estilos"); aviso("Estilo guardado"); })}, new Option("Ninguno", ""), ...ESTILOS.map(s => new Option(s.nombre, s.id)));
  est.value = e.estilo;
  const tipo = el("input", {value: e.tipo, ariaLabel: "Tipo de carpeta", list: "dl-tipos"}), idi = el("select", {ariaLabel: "Idioma del documento"}, new Option("El de la reunión", ""), ...Object.entries(IDI).filter(([k]) => k !== "reunión").map(([k, n]) => new Option(cap(n), k)));
  idi.value = e.ajustes.idioma;
  const anon = el("select", {ariaLabel: "Anonimizar por defecto"}, new Option("Como en los ajustes generales (" + (AJ.anonimizar_defecto ? "sí" : "no") + ")", ""), new Option("Sí, siempre en esta carpeta", "1"), new Option("No en esta carpeta", "0"));
  anon.value = e.ajustes.anon === null ? "" : e.ajustes.anon ? "1" : "0";
  const guardar = el("button", {className: "pri", textContent: "Guardar", onclick: fallo(async () => {
    await post("/api/exp/datos", {c, tipo: tipo.value, datos: e.datos}); await post("/api/exp/ajustes", {c, anon: anon.value === "" ? null : anon.value === "1", idioma: idi.value});
    aviso("Ajustes guardados"); await fRe();
  })});
  // glosario
  let gl = g.glosario.map(x => ({...x})), ign = [];
  const caja = el("div", {className: "card"}), sugs = el("div", {className: "row wrap"}), pintG = () => {
    caja.replaceChildren(H("Glosario"), el("p", {className: "muted", textContent: "Nombres y términos de esta carpeta. Ayudan a transcribir y redactar los documentos nuevos y corrigen la ortografía en las respuestas de Preguntar."}),
      ...(gl.length ? [el("div", {className: "pr h gl"}, el("span", {textContent: "Término"}), el("span", {textContent: "Ortografía correcta (opcional)"}), el("span", {textContent: "Definición breve (opcional)"}), el("span"))] : []),
      ...gl.map((x, i) => el("div", {className: "pr gl"}, el("input", {value: x.t, ariaLabel: "Término", oninput: ev => x.t = ev.target.value}), el("input", {value: x.orto, ariaLabel: "Ortografía correcta de " + x.t, oninput: ev => x.orto = ev.target.value}),
        el("input", {value: x.def, ariaLabel: "Definición de " + x.t, oninput: ev => x.def = ev.target.value}), el("button", {className: "sec sm", textContent: "×", ariaLabel: "Quitar " + x.t, onclick: () => { gl.splice(i, 1); pintG(); }}))),
      el("div", {className: "row wrap", style: "margin-top:8px"}, el("button", {className: "sec sm", textContent: "+ Término", onclick: () => { gl.push({t: "", orto: "", def: ""}); pintG(); }}),
        el("button", {className: "sec sm", textContent: "Sugerir desde los documentos", onclick: fallo(async () => { const r = await api("/api/exp/glosario?c=" + encodeURIComponent(c) + "&sugerir=1"); pintS(r.sugeridos); })}), el("span", {className: "grow"}),
        el("button", {className: "pri sm", textContent: "Guardar glosario", onclick: fallo(async () => { await post("/api/exp/glosario", {c, glosario: gl.filter(x => x.t.trim()), ignorar: ign}); aviso("Glosario guardado"); await fRe(); })})), sugs);
  }, pintS = l => sugs.replaceChildren(...(l.length ? [el("span", {className: "muted", textContent: "Nombres frecuentes (pulsa para añadir; × para no volver a sugerirlo):"})] : [el("span", {className: "muted", textContent: "No hay nombres frecuentes nuevos."})]),
    ...l.map(s => el("span", {className: "f-chip"}, el("button", {className: "sec sm", textContent: s.t + " · " + s.n, onclick: () => { gl.push({t: s.t, orto: "", def: ""}); pintG(); pintS(l.filter(y => y !== s)); }}),
      el("button", {className: "link", textContent: "×", ariaLabel: "No sugerir " + s.t, onclick: () => { ign.push(s.t); pintS(l.filter(y => y !== s)); }}))));
  pintG();
  return [el("div", {className: "card"}, H("Ajustes de la carpeta"), el("datalist", {id: "dl-tipos"}, ...["Proyecto", "Comunidad", "Cliente", "Paciente", "Asignatura", "Obra", "Estudio", "Serie", "Candidato"].map(v => el("option", {value: v}))),
    el("div", {className: "cols"}, fld("Perfil por defecto", perf, "El tipo de documento que propone «+ Nuevo»."), fld("Estilo por defecto", est, "Cómo se organiza al exportar."),
      fld("Tipo de carpeta", tipo, "Cambia el nombre del tipo y las sugerencias de datos."), fld("Idioma de los documentos nuevos", idi), fld("Anonimizar por defecto", anon, "Al exportar y descargar desde esta carpeta.")),
    el("div", {className: "row"}, guardar)), caja];
}

// ---- Registro: Revisión (bandeja) y vistas por tipo ----
// «Regenerar con IA» (F3b): encola /api/reg/poblar (todas las vistas o solo la de la pestaña); al terminar, carpetaTrasCola recarga la pestaña
KIND.poblar = "Poblar el proyecto con IA";
const FPOBLAR = {requisitos: "requisitos", interesados: "interesados", decisiones: "decisiones"};  // pestaña -> vista de poblar.py
function fRegenerar(c, vistas) {
  const nb = () => { try { return nubeParams("q") || nubeParams("f"); } catch { return null; } };
  const b = el("button", {className: "sec sm", textContent: "Regenerar con IA", title: "La IA vuelve a leer las reuniones y propone solo lo nuevo (respeta lo editado, aprobado y descartado)",
    onclick: fallo(async () => { b.disabled = true; try { await fEnCola("/api/reg/poblar", {c, ...(vistas ? {vistas} : {}), ...(nb() ? {nube: nb()} : {})}); } finally { b.disabled = false; } })});
  const info = el("small", {className: "muted"});
  api("/api/reg/poblar/estado?c=" + encodeURIComponent(c)).then(r => {
    const u = r.ultimo, n = u ? Object.values(u.creadas || {}).reduce((a, x) => a + x, 0) : 0;
    info.textContent = r.en_cola ? "En cola…" : u ? "Última pasada: " + new Date(u.t * 1000).toLocaleString("es") + " · " + n + (n === 1 ? " nueva" : " nuevas") + " · " + u.llamadas + " llamadas" + (u.coste ? " · US$" + u.coste.toFixed(3) : "") : "";
  }).catch(() => {});
  return el("div", {className: "row wrap", style: "margin-bottom:8px"}, b, info);
}
async function tRevision(c) {
  const w = el("div");
  registroBandeja(w, c, () => fCargaReg(c, fReg.proyecto ? "Proyecto" : ""));
  return [fRegenerar(c), w];
}
// placeholder genérico: tabla editable del tipo; cada vista de F4 lo sustituye con FVISTAS[clave]
async function tVista(c, e, k) {
  if (FVISTAS[k]) return FVISTAS[k](c, e);
  if (k === "informe") return [el("p", {className: "vacio", textContent: "Próximamente (F6)."})];
  const w = el("div");
  registroTabla(w, {c, tipo: FREG[k], onChange: () => fCargaReg(c, e.tipo)});
  return FPOBLAR[k] ? [fRegenerar(c, [FPOBLAR[k]]), w] : [w];
}
