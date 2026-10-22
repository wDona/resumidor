// Ajustes, asistente inicial («¿Para qué vas a usar la app?») y modo simple. Se carga tras app.js (usa sus helpers).
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

function aplicar() {
  const c = document.body.classList, n = nm("carpeta");
  c.toggle("simple", simple()); c.toggle("avanzado", !simple()); c.toggle("sin-nube", !AJ.nube_visible);
  $("nueva").textContent = nm("nuevo_boton"); $("side").firstElementChild.textContent = cap(pl(n)); $("nueva-carpeta").textContent = "+ " + n.toLowerCase();
  document.querySelectorAll(".n-carpetas").forEach(e => e.textContent = cap(pl(n)));
  if (vistaAct === "home" && typeof todas !== "undefined") pintarHome();
}

// ---- inicio simple: tarjetas de carpetas ----
function homeSimple() {
  const s = simple(), raiz = s && fsel === null;
  $("side").hidden = s; $("cards").hidden = !raiz; $("fcab").hidden = raiz; $("lista").hidden = raiz; $("f-atras").hidden = !s || raiz; $("nueva").hidden = raiz;
  if (!raiz) return false;
  const fecha = ms => ms.length ? new Date(Math.max(...ms.map(m => m.mtime)) * 1000).toLocaleDateString("es", {day: "2-digit", month: "2-digit"}) : "";
  const card = (titulo, v) => {
    const ms = todas.filter(m => (m.carpeta || "") === v), d = nm("documento");
    return el("button", {className: "fcard", onclick: () => { fsel = v; pintarHome(); }}, el("b", {textContent: v === "" ? sinC() : "📁 " + v}),
      el("small", {textContent: ms.length + " " + (ms.length === 1 ? d : pl(d)) + (ms.length ? " · último " + fecha(ms) : "")}));
  };
  const nueva = el("button", {className: "fcard nueva", textContent: "+ " + nm("carpeta").toLowerCase()});
  nueva.onclick = () => enLinea($("cards"), {valor: "", texto: "Nombre (" + nm("carpeta").toLowerCase() + " nuevo)", boton: "Crear"},
    async n => { if (!n) return; await post("/api/carpeta", {nuevo: n}); fsel = n; await cargarLista(); });
  const sin = todas.some(m => !m.carpeta);
  $("cards").replaceChildren(el("button", {className: "pri grande", textContent: nm("nuevo_boton"), onclick: () => formNuevo()}),
    ...carpetas.map(c => card(c, c)), ...(sin ? [card("", "")] : []), nueva,
    ...(!carpetas.length && !sin ? [el("p", {className: "muted", textContent: "Todavía no hay nada. Pulsa «" + nm("nuevo_boton") + "» para empezar."})] : []));
  return true;
}
$("f-atras").onclick = () => { fsel = null; pintarHome(); };

// ---- nueva (modo simple): perfil + Rápido/Calidad; el resto es automático ----
const calidadAuto = () => [...NIV].reverse().find(n => !n.pers && n.id !== "rápida" && n.estado === "ok" && n.instalado)
  || (n => n && n.instalado && n.estado !== "no" ? n : null)(nivelInfo("alta"));
function hintCalidad() {
  const n = calidadAuto();
  $("sp-hint").textContent = n ? "Mejor resultado" + (n.tiempo > 1 ? ` · tarda ~${n.tiempo}× más` : "") + ` (${n.nombre})` : "Mejor resultado · primero hay que instalar los modelos";
}
function formSimple(m) {
  $("form").classList.remove("av"); $("av-form").textContent = "Opciones avanzadas"; $("sp-err").hidden = true;
  if (!simple()) return;
  const sel = CP[m ? m.carpeta || "" : fsel || ""] || AJ.perfil_uso[0] || "acta", ids = [...new Set([...AJ.perfil_uso, sel])].filter(id => PL.some(t => t.id === id));
  const pintar = () => $("sp-cards").replaceChildren(...ids.map(id => { const t = plantDe(id);
    return el("button", {type: "button", role: "radio", className: "chip", "aria-checked": id === $("plantilla").value, onclick: () => { $("plantilla").value = id; $("plantilla").onchange(); pintar(); }},
      el("b", {textContent: t.nombre}), el("small", {textContent: t.descripcion}));
  }));
  $("plantilla").value = sel; $("plantilla").onchange(); pintar(); setQ_(sq); hintCalidad();
}
function setQ_(q) { sq = q; document.querySelectorAll("#sp-cal .chip").forEach(b => b.setAttribute("aria-checked", b.dataset.q === q)); }
document.querySelectorAll("#sp-cal .chip").forEach(b => b.onclick = () => setQ_(b.dataset.q));
$("av-form").onclick = () => { const f = $("form"); f.classList.toggle("av"); $("av-form").textContent = f.classList.contains("av") ? "Ocultar opciones avanzadas" : "Opciones avanzadas"; };
function paramsSimple() {
  if (!simple() || $("form").classList.contains("av")) return {};
  let calidad = "rápida";
  if (sq === "c") {
    const n = calidadAuto();
    if (!n) { abrirModelos("Para la opción «Calidad» hay que instalar antes los modelos recomendados."); throw new Error("Faltan los modelos recomendados"); }
    calidad = n.id;
  }
  return {nivel: "normal", calidad, habla: reuse ? "" : "auto", idioma: "reunión", hablantes: false, nombres: "", gpu: GPUREC};
}

// ---- Modelos en modo simple: solo «Instalar lo recomendado» ----
function modSimple(m) {
  const rec = m.catalogo.filter(c => m.recomendados.includes(c.id) && !c.instalado), b = rec.reduce((a, c) => a + c.bytes, 0);
  if (simple() && $("mod-intro").textContent.startsWith("Elige qué")) $("mod-intro").textContent = "Modelos de inteligencia artificial que se ejecutan en este equipo.";
  $("mod-s-txt").textContent = rec.length ? "Para este equipo se recomienda instalar " + rec.map(c => c.nombre).join(", ") + ". Se descarga una sola vez y después todo funciona sin internet." : "Ya está instalado todo lo recomendado para este equipo.";
  $("mod-srec").hidden = !rec.length; $("mod-srec").textContent = "Instalar lo recomendado (" + GB(b) + ")"; $("mod-simple").hidden = false;
}
$("mod-srec").onclick = () => instalar(null);
$("mod-scerrar").onclick = () => $("mod-cerrar").click();
$("mod-todos").onclick = () => { document.body.classList.add("mod-todos"); abrirModelos(); };

// ---- asistente inicial ----
async function abrirUso(primera) {
  if (!PL.length) await cargarPlant().catch(() => {});
  const sel = new Set(primera ? [] : AJ.uso), cuerpo = $("uso-cuerpo");
  const paso1 = () => {
    const ok = el("button", {className: "pri", textContent: "Continuar", disabled: !sel.size, onclick: () => paso2()});
    cuerpo.replaceChildren(el("h2", {textContent: "¿Para qué vas a usar la app?"}),
      el("p", {className: "muted", textContent: "Elige una o varias. Solo prepara perfiles y nombres; puedes cambiarlo todo después en Ajustes sin perder nada."}),
      el("div", {className: "chips usos"}, ...USOS.map(u => el("button", {type: "button", role: "checkbox", className: "chip", "aria-checked": sel.has(u.id),
        onclick: e => { sel.has(u.id) ? sel.delete(u.id) : sel.add(u.id); e.currentTarget.setAttribute("aria-checked", sel.has(u.id)); ok.disabled = !sel.size; }},
        el("b", {textContent: u.t}), el("small", {textContent: u.p.length ? u.p.map(p => plantDe(p).nombre).join(" · ") : "Eliges tú los perfiles y los nombres"})))),
      el("div", {className: "row wrap"}, ok, primera ? el("button", {className: "sec", textContent: "Ahora no", onclick: fallo(async () => { AJ = await post("/api/ajustes", {}); aplicar(); ir("home"); })})
        : el("button", {className: "sec", textContent: "Cancelar", onclick: () => abrirAjustes()})));
  };
  const paso2 = () => {
    const us = [...sel].map(i => USOS.find(u => u.id === i)), perf = new Set(us.flatMap(u => u.p)), n = {...AJ.nombres, carpeta: us[0].c, documento: "documento", nuevo_boton: "+ Nuevo"};
    if (!primera && us[0].id === "otro") Object.assign(n, AJ.nombres);
    let nube = !us.some(u => u.sens), anon = us.some(u => u.sens || u.anon);
    const inp = (k, lab) => el("div", {className: "field"}, el("label", {textContent: lab}), el("input", {value: n[k], oninput: e => n[k] = e.target.value}));
    const chk2 = (lab, v, f) => el("label", {className: "check"}, el("input", {type: "checkbox", checked: v, onchange: e => f(e.target.checked)}), " " + lab);
    const ok = el("button", {className: "pri", textContent: "Empezar"});
    ok.onclick = fallo(async () => {
      if (!perf.size) throw new Error("Elige al menos un perfil");
      AJ = await post("/api/ajustes", {uso: [...sel], perfil_uso: [...perf], nombres: n, nube_visible: nube, anonimizar_defecto: anon}); aplicar(); ir("home"); aviso("Listo");
    });
    cuerpo.replaceChildren(el("h2", {textContent: "Confirma tu configuración"}),
      el("h3", {textContent: "Perfiles"}), el("small", {textContent: "Cada perfil define qué se busca y cómo se redacta el documento."}),
      el("div", {className: "perfiles"}, ...PL.map(t => chk2(t.nombre, perf.has(t.id), v => v ? perf.add(t.id) : perf.delete(t.id)))),
      el("h3", {textContent: "Nombres"}), inp("carpeta", "Cómo llamas a las carpetas (singular)"), inp("documento", "Cómo llamas a lo que se genera (singular)"), inp("nuevo_boton", "Texto del botón de crear"),
      el("h3", {textContent: "Privacidad"}),
      ...(us.some(u => u.sens) ? [el("p", {className: "aviso", textContent: NOTA_SENS})] : []),
      chk2("Mostrar opciones de procesar en la nube", nube, v => nube = v), chk2("Anonimizar por defecto (próximamente)", anon, v => anon = v),
      el("div", {className: "row wrap"}, ok, el("button", {className: "sec", textContent: "Atrás", onclick: paso1})));
  };
  vista("uso"); paso1();
}

// ---- pantalla Ajustes ----
function abrirAjustes() { history.replaceState(null, "", "#/ajustes"); vista("ajustes"); pintarAjustes(); }
function pintarAjustes() {
  const sec = (t, ...k) => [el("h3", {textContent: t}), ...k], u = USOS.filter(x => AJ.uso.includes(x.id));
  const radio = (v, t, d) => el("label", {className: "check"}, el("input", {type: "radio", name: "modo", checked: AJ.modo === v, onchange: fallo(async () => { await guardarAj({modo: v}); pintarAjustes(); })}), el("span", {}, el("b", {textContent: t}), el("small", {textContent: d})));
  const chk2 = (lab, v, f, nota) => el("label", {className: "check"}, el("input", {type: "checkbox", checked: v, onchange: fallo(async e => f(e.target.checked))}), el("span", {}, lab, ...(nota ? [el("small", {textContent: nota})] : [])));
  const nom = (k, lab) => el("div", {className: "field"}, el("label", {textContent: lab}), el("input", {value: nm(k), onchange: fallo(async e => { if (e.target.value.trim()) await guardarAj({nombres: {[k]: e.target.value}}); })}));
  $("aj-cuerpo").replaceChildren(
    ...sec("Modo", radio("simple", "Simple", "Pocas decisiones: eliges el perfil y Rápido o Calidad; lo demás es automático."), radio("avanzado", "Avanzado", "Todas las opciones: calidad, idiomas, hablantes, plantillas, búsqueda a fondo…")),
    ...sec("Perfil de uso", el("p", {className: "muted", textContent: u.length ? u.map(x => x.t).join(", ") : "Sin elegir"}),
      el("button", {className: "sec", textContent: "Cambiar perfil de uso", onclick: () => abrirUso(false)}),
      el("small", {textContent: "Vuelve a ejecutar el asistente. No toca tus carpetas ni documentos."}),
      el("h4", {textContent: "Perfiles que se ofrecen al crear"}),
      el("div", {className: "perfiles"}, ...PL.map(t => chk2(t.nombre, AJ.perfil_uso.includes(t.id), async v => {
        const l = v ? [...AJ.perfil_uso, t.id] : AJ.perfil_uso.filter(x => x !== t.id); if (!l.length) { aviso("Debe quedar al menos un perfil"); return pintarAjustes(); } await guardarAj({perfil_uso: l}); })))),
    ...sec("Nombres", nom("carpeta", "Carpeta (singular)"), nom("documento", "Documento (singular)"), nom("nuevo_boton", "Botón de crear")),
    ...sec("Privacidad", ...(u.some(x => x.sens) ? [el("p", {className: "aviso", textContent: NOTA_SENS})] : []),
      chk2("Mostrar opciones de procesar en la nube", AJ.nube_visible, v => guardarAj({nube_visible: v}), "Por ahora todo se procesa en este equipo."),
      chk2("Anonimizar por defecto", AJ.anonimizar_defecto, v => guardarAj({anonimizar_defecto: v}), "Próximamente: se guarda tu preferencia.")));
}
$("b-ajustes").onclick = abrirAjustes; $("aj-volver").onclick = () => ir("home");
addEventListener("hashchange", () => location.hash === "#/ajustes" && vistaAct !== "ajustes" && abrirAjustes());

api("/api/ajustes").then(a => { AJ = a; aplicar(); if (!a.existe && location.hash !== "#/modelos") abrirUso(true); else if (location.hash === "#/ajustes") abrirAjustes(); }).catch(() => {});
