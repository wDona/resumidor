// Ajustes (General · Modelos · Plantillas · Perfiles de uso), asistente de primer arranque y modo simple. Se carga tras app.js.
let AJ = {modo: "simple", uso: ["empresa"], perfil_uso: ["acta", "onboarding", "comercial"], nombres: {carpeta: "Proyecto", documento: "documento", nuevo_boton: "+ Nuevo"},
  nube_visible: true, anonimizar_defecto: false, existe: true};
let GPUREC = false, sq = "r";  // GPUREC: GPU recomendada (el modo simple no la pregunta); sq: Rápido (r) | Calidad (c)
const simple = () => AJ.modo !== "avanzado";
const nm = k => AJ.nombres[k];
const pl = w => /[aeiouáéíóú]$/i.test(w) ? w + "s" : w + "es";
const sinC = () => "Sin " + nm("carpeta").toLowerCase();
const guardarAj = async patch => { AJ = await post("/api/ajustes", patch); aplicar(); aviso("Guardado"); };
api("/api/gpu").then(g => GPUREC = !!(g.ok && g.default)).catch(() => {});

// uso: perfiles (ids de plantillas.py), nombre de carpeta y privacidad de cada opción del asistente
const USOS = [
  {id: "empresa", t: "Reuniones de empresa", p: ["acta", "onboarding", "comercial"], c: "Proyecto"},
  {id: "fincas", t: "Administración de fincas", p: ["comunidad", "obra"], c: "Comunidad"},
  {id: "salud", t: "Salud / consulta", p: ["consulta"], c: "Paciente", sens: 1},
  {id: "abogacia", t: "Abogacía / asesoría", p: ["consulta", "cualitativa"], c: "Cliente", sens: 1},
  {id: "rrhh", t: "RRHH", p: ["seleccion", "onboarding"], c: "Candidato", anon: 1},
  {id: "educacion", t: "Educación", p: ["clase"], c: "Asignatura"},
  {id: "periodismo", t: "Periodismo / investigación", p: ["periodistica", "cualitativa"], c: "Estudio"},
  {id: "comercial", t: "Comercial / soporte", p: ["comercial"], c: "Cliente"},
  {id: "creador", t: "Creador de contenido", p: ["video"], c: "Serie"},
  {id: "obra", t: "Construcción / inspección", p: ["obra"], c: "Obra"},
  {id: "otro", t: "Otro", p: [], c: "Carpeta"}];
const NOTA_SENS = "Los datos de salud y los de clientes son especialmente protegidos (RGPD art. 9 y secreto profesional): por eso la nube viene desactivada. Si tu organización lo permite, puedes activarla en Ajustes.";
let UP = [];  // perfiles de uso propios (/api/perfiles-uso)
const cargarUP = () => api("/api/perfiles-uso").then(l => UP = l).catch(() => {});
const propioUso = p => ({id: p.id, t: p.nombre, p: p.plantillas, c: p.carpeta, d: p.documento, nb: p.nuevo_boton, nonube: !p.nube, anon: p.anonimizar, propio: 1});
const usos = () => [...USOS, ...UP.map(propioUso)];

function aplicar() {
  const c = document.body.classList;
  c.toggle("simple", simple()); c.toggle("avanzado", !simple()); c.toggle("sin-nube", !AJ.nube_visible);
  $("nueva").textContent = nm("nuevo_boton");
  if (vistaAct === "home" && typeof todas !== "undefined") pintarHome();
  if (vistaAct === "ajustes" && tabAj === "general") pintarAjustes();
}

// ---- nuevo documento en modo simple: «Tipo» + Rápido/Calidad; el resto es automático ----
const calidadAuto = () => [...NIV].reverse().find(n => !n.pers && n.id !== "rápida" && n.estado === "ok" && n.instalado)
  || (n => n && n.instalado && n.estado !== "no" ? n : null)(nivelInfo("alta"));
function hintCalidad() {
  const n = calidadAuto();
  $("sp-hint").textContent = n ? "Mejor resultado" + (n.tiempo > 1 ? ` · tarda ~${n.tiempo}× más` : "") + ` (${n.nombre})` : "Mejor resultado · primero hay que instalar los modelos";
}
function formSimple() { setQ_(sq); hintCalidad(); pintarCal(); }
function setQ_(q) { sq = q; document.querySelectorAll("#sp-cal .chip").forEach(b => b.setAttribute("aria-checked", b.dataset.q === q)); }
document.querySelectorAll("#sp-cal .chip").forEach(b => b.onclick = () => setQ_(b.dataset.q));
let focoModo = false;
$("av-form").onclick = () => { focoModo = true; abrirAjustes("general"); };  // «Opciones avanzadas» -> Ajustes › General › Modo
function paramsSimple() {
  if (!simple()) return {};
  let calidad = "rápida";
  if (sq === "c") {
    const n = calidadAuto();
    if (!n) { abrirModelos("Para la opción «Calidad» hay que instalar antes los modelos recomendados."); throw new Error("Faltan los modelos recomendados"); }
    calidad = n.id;
  }
  return {nivel: "normal", calidad, habla: reuse ? "" : "auto", idioma: "reunión", hablantes: false, nombres: "", gpu: GPUREC};
}

// ---- asistente: «¿Para qué vas a usar la app?» (primer arranque o desde Ajustes) ----
async function abrirUso(primera) {
  if (!PL.length) await cargarPlant().catch(() => {});
  await cargarUP();
  const sel = new Set(primera ? [] : AJ.uso), cuerpo = $("uso-cuerpo"), U = usos();
  const resumen = el("div", {className: "resumen"}), ok = el("button", {className: "pri", textContent: primera ? "Siguiente" : "Aplicar", disabled: !sel.size});
  const nombresDe = us => ({carpeta: us[0].c, documento: us[0].d || "documento", nuevo_boton: us[0].nb || "+ Nuevo"});
  const act = () => {
    const us = U.filter(u => sel.has(u.id)); ok.disabled = !us.length; resumen.hidden = !us.length; if (!us.length) return;
    const perf = [...new Set(us.flatMap(u => u.p))].map(p => PL.find(t => t.id === p)?.nombre).filter(Boolean);
    resumen.replaceChildren(el("b", {textContent: "Con esta elección"}), el("ul", {},
      el("li", {textContent: "Se llamará «" + nombresDe(us).carpeta + "» a las carpetas." }), el("li", {textContent: "Tipos de documento: " + (perf.join(", ") || "los eliges tú") + "."}),
      el("li", {textContent: us.some(u => u.sens || u.nonube) ? "Procesar en la nube: oculto. Todo se queda en este equipo." : "Todo se procesa en este equipo."}),
      ...(us.some(u => u.sens || u.anon) ? [el("li", {textContent: "Anonimizar por defecto: se activará (próximamente)."})] : [])),
      ...(us.some(u => u.sens) ? [el("p", {className: "muted", style: "margin:8px 0 0", textContent: NOTA_SENS})] : []));
  };
  ok.onclick = fallo(async () => {
    const us = U.filter(u => sel.has(u.id)), n = nombresDe(us), perf = [...new Set(us.flatMap(u => u.p))].filter(p => PL.some(t => t.id === p));
    if (!primera && us[0].id === "otro") Object.assign(n, AJ.nombres);
    AJ = await post("/api/ajustes", {uso: [...sel], perfil_uso: perf.length ? perf : AJ.perfil_uso, nombres: n, nube_visible: !us.some(u => u.sens || u.nonube), anonimizar_defecto: us.some(u => u.sens || u.anon)});
    aplicar();
    if (primera) { irInicio(); $("d-crear").showModal(); } else { abrirAjustes("general"); aviso("Guardado"); }
  });
  cuerpo.replaceChildren(
    ...(primera ? [el("ol", {className: "pasos"}, el("li", {className: "on"}, el("b", {textContent: "1"}), "Para qué lo usas"), el("li", {}, el("b", {textContent: "2"}), "Modelos"))] : []),
    el("h1", {textContent: "¿Para qué vas a usar la app?"}),
    el("p", {className: "muted", style: "margin:6px 0 16px", textContent: "Elige uno o varios. Solo prepara perfiles y nombres; puedes cambiarlo todo después en Ajustes sin perder nada."}),
    el("div", {className: "chips", role: "group", ariaLabel: "Usos"}, ...U.map(u => el("button", {type: "button", role: "checkbox", className: "chip", "aria-checked": sel.has(u.id),
      onclick: e => { sel.has(u.id) ? sel.delete(u.id) : sel.add(u.id); e.currentTarget.setAttribute("aria-checked", sel.has(u.id)); act(); }},
      el("b", {textContent: u.t}), el("small", {textContent: u.p.length ? u.p.map(p => PL.find(t => t.id === p)?.nombre).filter(Boolean).join(" · ") : "Eliges tú los perfiles y los nombres"})))),
    el("p", {}, el("button", {className: "link", type: "button", textContent: "+ Crear un perfil de uso propio", onclick: () => abrirAjustes("perfiles", "nuevo")})),
    resumen,
    el("div", {className: "row wrap"}, ok, primera ? el("button", {className: "sec", textContent: "Saltar, configurar luego", onclick: fallo(async () => { AJ = await post("/api/ajustes", {}); aplicar(); irInicio(); })})
      : el("button", {className: "sec", textContent: "Cancelar", onclick: () => abrirAjustes("general")})));
  act(); vista("uso");
}
$("dc-imp").onclick = () => { $("d-crear").close(); aviso("Usa «Importar» para abrir un documento exportado (.zip)"); };
$("dc-crear").onclick = () => { $("d-crear").close(); abrirModelos(null, null, true); };

// ---- Ajustes: pestañas ----
const TABS = ["general", "modelos", "plantillas", "perfiles"];
let tabAj = "general";
function abrirAjustes(t = "general", sub) {
  tabAj = TABS.includes(t) ? t : "general";
  const h = "#/ajustes/" + tabAj; if (location.hash !== h) history.pushState(null, "", h);
  vista("ajustes"); history.replaceState(null, "", h);
  document.querySelectorAll("#aj-tabs a").forEach(a => { const on = a.dataset.t === tabAj; a.setAttribute("aria-selected", on); on ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"); });
  for (const x of TABS) $({general: "aj-general", modelos: "aj-modelos", plantillas: "aj-plant", perfiles: "aj-perfiles"}[x]).hidden = x !== tabAj;
  document.title = "Ajustes · Actas";
  if (tabAj === "general") pintarAjustes(); else if (tabAj === "modelos") pintarTabModelos(); else if (tabAj === "plantillas") pintarTabPlant(sub); else pintarTabPerfiles(sub);
}
$("aj-volver").onclick = e => { e.preventDefault(); irInicio(); };
function ruta_() {  // #/ajustes[/tab]; las rutas antiguas #/modelos y #/plantillas redirigen
  const h = location.hash, m = h.match(/^#\/(ajustes|modelos|plantillas)(?:\/(\w+))?/);
  if (!m) return false;
  abrirAjustes(m[1] === "ajustes" ? m[2] : m[1]); return true;
}
addEventListener("hashchange", () => { if (/^#\/(ajustes|modelos|plantillas)/.test(location.hash)) { const t = location.hash.match(/^#\/ajustes\/(\w+)/)?.[1]; if (vistaAct !== "ajustes" || (t && t !== tabAj) || !t) ruta_(); } });

// ---- Ajustes › General ----
function pintarAjustes() {
  const U = usos(), u = U.filter(x => AJ.uso.includes(x.id));
  const card = (t, ...k) => el("section", {className: "card"}, el("h2", {textContent: t}), ...k);
  const radio = (v, t, d) => el("label", {className: "opt"}, el("input", {type: "radio", name: "modo", checked: AJ.modo === v, onchange: fallo(async () => { await guardarAj({modo: v}); })}), el("span", {}, el("b", {textContent: t}), el("small", {textContent: d})));
  const chk2 = (lab, v, f, nota) => el("label", {className: "check"}, el("input", {type: "checkbox", checked: v, onchange: fallo(async e => f(e.target.checked))}), el("span", {}, lab, ...(nota ? [el("small", {textContent: nota})] : [])));
  const nom = (k, lab) => el("div", {className: "field"}, el("label", {textContent: lab}), el("input", {value: nm(k), onchange: fallo(async e => { if (e.target.value.trim()) await guardarAj({nombres: {[k]: e.target.value}}); })}));
  $("aj-general").replaceChildren(
    card("Modo", el("div", {id: "modo-g", role: "radiogroup", ariaLabel: "Modo"}, radio("simple", "Simple", "Pocas decisiones: eliges el tipo de documento y Rápido o Calidad; lo demás es automático."),
      radio("avanzado", "Avanzado", "Todas las opciones: niveles de calidad, idiomas, hablantes, plantillas, búsqueda a fondo, modelos locales…"))),
    card("Perfil de uso", el("p", {className: "muted", textContent: u.length ? u.map(x => x.t).join(", ") : "Sin elegir"}),
      el("div", {className: "row wrap"}, el("button", {className: "sec", textContent: "Cambiar perfil de uso", onclick: () => abrirUso(false)}), el("button", {className: "link", textContent: "Gestionar perfiles de uso", onclick: () => abrirAjustes("perfiles")})),
      el("small", {textContent: "Vuelve a ejecutar el asistente. No toca tus carpetas ni documentos."}),
      el("h4", {textContent: "Tipos de documento que se ofrecen al crear"}),
      el("div", {className: "perfiles"}, ...PL.map(t => chk2(t.nombre, AJ.perfil_uso.includes(t.id), async v => {
        const l = v ? [...AJ.perfil_uso, t.id] : AJ.perfil_uso.filter(x => x !== t.id); if (!l.length) { aviso("Debe quedar al menos un tipo"); return pintarAjustes(); } await guardarAj({perfil_uso: l}); })))),
    card("Nombres", el("div", {className: "cols"}, nom("carpeta", "Carpeta (singular)"), nom("documento", "Documento (singular)")), nom("nuevo_boton", "Botón de crear")),
    card("Privacidad", ...(u.some(x => x.sens) ? [el("p", {className: "aviso", textContent: NOTA_SENS})] : []),
      chk2("Mostrar opciones de procesar en la nube", AJ.nube_visible, v => guardarAj({nube_visible: v}), "Por ahora todo se procesa en este equipo."),
      chk2("Anonimizar por defecto", AJ.anonimizar_defecto, v => guardarAj({anonimizar_defecto: v}), "Exportar y Correo usan la copia anonimizada; siempre puedes desmarcarlo al exportar.")));
  $("aj-general").append(Object.assign(card("Estilos de organización", el("p", {className: "muted", textContent: "Cabecera, pie, color, logo y firmas que llevan los documentos que exportas. Cada " + nm("carpeta").toLowerCase() + " puede tener uno por defecto."}), el("div", {id: "est-w"})), {className: "card solo-av"}));
  pintarEstilos();
  if (focoModo) { focoModo = false; document.querySelector("#modo-g input:checked")?.focus(); }
}

// ---- Ajustes › Perfiles de uso (CRUD sobre /api/perfiles-uso) ----
let upSel = null, upEd = null;
async function pintarTabPerfiles(sub) {
  if (!PL.length) await cargarPlant().catch(() => {});
  await cargarUP(); if (sub === "nuevo") { upSel = "nuevo"; upEd = {nombre: "", plantillas: [], carpeta: "Carpeta", documento: "documento", nuevo_boton: "+ Nuevo", nube: true, anonimizar: false}; }
  else if (upSel !== "nuevo" || !upEd) { if (!usos().some(x => x.id === upSel)) upSel = UP[0]?.id || "empresa"; upEd = null; }
  const li = x => el("button", {className: "nav", "aria-current": x.id === upSel ? "page" : "false", onclick: () => { upSel = x.id; upEd = null; pintarTabPerfiles(); }}, el("span", {textContent: x.t}), el("span", {className: "c", textContent: AJ.uso.includes(x.id) ? "en uso" : ""}));
  $("up-lista").replaceChildren(el("button", {className: "pri", textContent: "+ Nuevo perfil de uso", style: "margin-bottom:8px", onclick: () => { upSel = "nuevo"; upEd = null; pintarTabPerfiles("nuevo"); }}),
    ...(UP.length ? [el("div", {className: "t", textContent: "Tuyos"}), ...UP.map(propioUso).map(li)] : []), el("div", {className: "t", textContent: "De serie · solo lectura"}), ...USOS.map(li));
  pintarUP();
}
function pintarUP() {
  const x = usos().find(u => u.id === upSel), nuevo = upSel === "nuevo", p = nuevo ? upEd : x?.propio ? {...UP.find(q => q.id === x.id)} : null;
  const ed = $("up-ed");
  if (!p) {  // de serie: resumen y duplicar
    ed.replaceChildren(el("h2", {textContent: x.t}), el("p", {className: "muted", textContent: "Perfil de serie: no se edita. Duplícalo para ajustarlo."}),
      el("p", {textContent: "Tipos de documento: " + (x.p.map(i => PL.find(t => t.id === i)?.nombre).filter(Boolean).join(", ") || "los eliges tú")}), el("p", {textContent: "Las carpetas se llaman «" + x.c + "»."}),
      el("div", {className: "row wrap"}, el("button", {className: "sec", textContent: "Duplicar como perfil propio", onclick: () => { upEd = {nombre: x.t + " (mío)", plantillas: [...x.p], carpeta: x.c, documento: "documento", nuevo_boton: "+ Nuevo", nube: !x.sens, anonimizar: !!(x.sens || x.anon)}; upSel = "nuevo"; pintarTabPerfiles(); }}), usarBtn(x)));
    return;
  }
  const t = (k, lab) => el("div", {className: "field"}, el("label", {textContent: lab}), el("input", {value: p[k] ?? "", oninput: e => p[k] = e.target.value}));
  const ck = (k, lab) => el("label", {className: "check"}, el("input", {type: "checkbox", checked: !!p[k], onchange: e => p[k] = e.target.checked}), el("span", {textContent: lab}));
  const guardar = fallo(async () => { const r = await post("/api/perfiles-uso", p); upSel = r.id; upEd = null; await pintarTabPerfiles(); aviso("Perfil guardado"); });
  ed.replaceChildren(el("h2", {textContent: nuevo ? "Nuevo perfil de uso" : p.nombre}), t("nombre", "Nombre"),
    el("h3", {textContent: "Tipos de documento que ofrece"}), el("div", {className: "perfiles"}, ...PL.map(tp => el("label", {className: "check"}, el("input", {type: "checkbox", checked: p.plantillas.includes(tp.id),
      onchange: e => p.plantillas = e.target.checked ? [...p.plantillas, tp.id] : p.plantillas.filter(i => i !== tp.id)}), el("span", {textContent: tp.nombre})))),
    el("h3", {textContent: "Nombres"}), el("div", {className: "cols"}, t("carpeta", "Carpeta (singular)"), t("documento", "Documento (singular)")), t("nuevo_boton", "Botón de crear"),
    el("h3", {textContent: "Privacidad"}), ck("nube", "Mostrar opciones de procesar en la nube"), ck("anonimizar", "Anonimizar por defecto (próximamente)"),
    el("div", {className: "row wrap", style: "margin-top:16px"}, el("button", {className: "pri", textContent: "Guardar", onclick: guardar}), ...(nuevo ? [] : [usarBtn(propioUso(p)),
      el("button", {className: "sec dng", textContent: "Eliminar", onclick: fallo(async () => { if (!confirm("¿Eliminar el perfil «" + p.nombre + "»?")) return; await post("/api/perfiles-uso/borrar", {id: p.id}); upSel = null; await pintarTabPerfiles(); })})])));
}
const usarBtn = x => el("button", {className: "sec", textContent: "Usar este perfil", onclick: fallo(async () => {
  const perf = x.p.filter(i => PL.some(t => t.id === i));
  AJ = await post("/api/ajustes", {uso: [x.id], perfil_uso: perf.length ? perf : AJ.perfil_uso, nombres: {carpeta: x.c, documento: x.d || "documento", nuevo_boton: x.nb || "+ Nuevo"}, nube_visible: !(x.sens || x.nonube), anonimizar_defecto: !!(x.sens || x.anon)});
  aplicar(); aviso("Perfil aplicado"); pintarTabPerfiles(); })});

api("/api/ajustes").then(a => { AJ = a; aplicar(); if (!a.existe && !/^#\/(modelos|ajustes)/.test(location.hash)) abrirUso(true); }).catch(() => {});

// ---- Estilos de organización (/api/estilos): cabecera, pie, color, campos formales, firmas, logo y .docx base ----
const CAMPOS_E = [["numero", "Nº"], ["tipo", "Tipo de sesión"], ["lugar", "Lugar"], ["hora_inicio", "Hora de inicio"], ["hora_fin", "Hora de fin"], ["convocatoria", "Convocatoria"], ["asistentes", "Asistentes"], ["ausentes", "Ausentes"]];
let estEd = null;
async function pintarEstilos() {
  const w = $("est-w"); if (!w) return;
  ESTILOS = await api("/api/estilos").catch(() => ESTILOS);
  if (estEd) return editorEstilo(w);
  w.replaceChildren(...(ESTILOS.length ? ESTILOS.map(e => el("div", {className: "mrow"}, el("span", {className: "grow"}, el("b", {textContent: e.nombre}), el("small", {textContent: [e.cabecera, e.color, e.logo && "con logo", e.base_docx && "con .docx base"].filter(Boolean).join(" · ")})),
    el("button", {className: "sec sm", textContent: "Editar", onclick: () => { estEd = structuredClone(e); pintarEstilos(); }}))) : [el("p", {className: "muted", textContent: "Aún no hay estilos."})]),
    el("button", {className: "pri", textContent: "+ Nuevo estilo", onclick: () => { estEd = {nombre: "", cabecera: "", pie: "{título} · {fecha} · pág. {página}", color: "", campos: {}, firmas: [], logo: "", base_docx: ""}; pintarEstilos(); }}));
}
function editorEstilo(w) {
  const e = estEd, nuevo = !e.id, ficheros = {}, quitar = {};
  const t = (k, lab, ayuda) => el("div", {className: "field"}, el("label", {textContent: lab}), el("input", {value: e[k] || "", oninput: ev => e[k] = ev.target.value}), ...(ayuda ? [el("small", {textContent: ayuda})] : []));
  const firmas = el("div"), pf = () => firmas.replaceChildren(...e.firmas.map((f, i) => el("div", {className: "firma"}, el("input", {value: f.cargo, placeholder: "Cargo", ariaLabel: "Cargo", oninput: ev => f.cargo = ev.target.value}),
    el("input", {value: f.nombre, placeholder: "Nombre", ariaLabel: "Nombre", oninput: ev => f.nombre = ev.target.value}), el("button", {type: "button", className: "sec", textContent: "✕", ariaLabel: "Quitar firma", onclick: () => { e.firmas.splice(i, 1); pf(); }}))));
  pf();
  const fich = (k, lab, acc) => el("div", {className: "field"}, el("label", {textContent: lab}), el("div", {className: "row wrap"}, el("input", {type: "file", accept: acc, ariaLabel: lab, onchange: ev => ficheros[k] = ev.target.files[0]}),
    ...(e[k] ? [el("span", {className: "muted", textContent: "Ya hay uno cargado"}), el("button", {type: "button", className: "link", textContent: "Quitar", onclick: ev => { quitar[k] = true; ev.target.previousSibling.textContent = "Se quitará al guardar"; ev.target.remove(); }})] : [])));
  const color = el("input", {type: "color", value: e.color || "#1d5fd1", ariaLabel: "Color", oninput: ev => e.color = ev.target.value}), sinc = el("input", {type: "checkbox", checked: !e.color, onchange: ev => { e.color = ev.target.checked ? "" : color.value; }});
  color.oninput = () => { e.color = color.value; sinc.checked = false; };
  const guardar = fallo(async () => {
    const d = {...e, campos: e.campos || {}}; for (const k in quitar) d[k] = "";
    const r = await post("/api/estilos", d);
    for (const [k, f] of Object.entries(ficheros)) if (f) await api(`/api/estilos/${r.id}/${k}?name=${encodeURIComponent(f.name)}`, {method: "PUT", body: f});
    estEd = null; await pintarEstilos(); aviso("Estilo guardado");
  });
  w.replaceChildren(el("h3", {textContent: nuevo ? "Nuevo estilo" : e.nombre}), t("nombre", "Nombre"), t("cabecera", "Cabecera"), t("pie", "Pie", "Puedes usar {fecha}, {título} y {página}."),
    el("div", {className: "field"}, el("label", {textContent: "Color"}), el("div", {className: "colorf"}, color, el("label", {className: "check", style: "margin:0"}, sinc, "Sin color"))),
    fich("logo", "Logo (png o jpg, hasta 5 MB)", "image/png,image/jpeg"), fich("base_docx", "Documento Word de base (.docx, opcional)", ".docx"),
    el("h4", {textContent: "Campos del encabezado formal"}), el("div", {className: "cols"}, ...CAMPOS_E.map(([k, lab]) => el("div", {className: "field"}, el("label", {textContent: lab}), el("input", {value: (e.campos || {})[k] || "", oninput: ev => (e.campos ||= {})[k] = ev.target.value})))),
    el("h4", {textContent: "Firmas"}), firmas, el("button", {type: "button", className: "sec sm", textContent: "+ Firma", onclick: () => { e.firmas.push({cargo: "", nombre: ""}); pf(); }}),
    el("div", {className: "row wrap", style: "margin-top:16px"}, el("button", {className: "pri", textContent: "Guardar", onclick: guardar}), el("button", {className: "sec", textContent: "Cancelar", onclick: () => { estEd = null; pintarEstilos(); }}),
      ...(nuevo ? [] : [el("button", {className: "sec dng", textContent: "Eliminar", onclick: fallo(async () => { if (!confirm("¿Eliminar el estilo «" + e.nombre + "»?")) return; await post("/api/estilos/borrar", {id: e.id}); estEd = null; await pintarEstilos(); })})])));
}
