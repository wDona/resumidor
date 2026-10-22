// Ajustes › Plantillas: qué se busca en la grabación y cómo se redacta el documento.
let pe = null, pSel = "acta";
const LIBRES = ["resumen", "desarrollo", "detalle", "transcripcion"];
async function abrirPlant(id) { await cargarPlant(); if (id) pSel = id; if (!PL.some(t => t.id === pSel)) pSel = "acta"; if (tabAj !== "plantillas" || vistaAct !== "ajustes") abrirAjustes("plantillas"); else pintarPlant(); }
async function pintarTabPlant(sub) { await cargarPlant(); if (!todas.length) await cargarLista().catch(() => {}); if (sub === "nueva") return nuevaPlant(); if (!PL.some(t => t.id === pSel)) pSel = "acta"; pintarPlant(); }
async function nuevaPlant() {
  const b = plantDe("acta"); let nom = "Nueva plantilla", i = 1; while (PL.some(t => t.nombre === nom)) nom = "Nueva plantilla " + ++i;
  const c = await post("/api/plantillas", {plantilla: {...structuredClone(b), serie: undefined, editable: undefined, id: "", nombre: nom, base: undefined, descripcion: ""}});
  await abrirPlant(c.id); aviso("Plantilla creada: ponle nombre y secciones");
}
function pintarPlant() {
  const nav = t => el("button", {className: "nav", "aria-current": t.id === pSel ? "page" : "false", onclick: () => { pSel = t.id; pintarPlant(); }}, el("span", {textContent: t.nombre}), el("span", {className: "c", textContent: t.serie && t.editable ? "modificada" : ""}));
  const tuyas = PL.filter(t => !t.serie), serie = PL.filter(t => t.serie);
  $("plant-lista").replaceChildren(el("button", {className: "pri", textContent: "+ Nueva plantilla", onclick: fallo(nuevaPlant)}),
    ...(tuyas.length ? [el("div", {className: "t", textContent: "Tuyas"}), ...tuyas.map(nav)] : []), el("div", {className: "t", textContent: "De serie"}), ...serie.map(nav),
    el("div", {className: "row wrap pie"}, el("label", {className: "btn sec sm", htmlFor: "plant-imp", textContent: "Importar .json"})));
  const t = plantDe(pSel); pe = structuredClone(t); delete pe.serie; delete pe.editable; pintarEd(t);
}
const campo = (lab, inp) => el("div", {className: "field"}, el("label", {textContent: lab}), inp);
const txt = (obj, k, area, extra = {}) => { const i = el(area ? "textarea" : "input", {value: obj[k] ?? "", ...extra}); i.oninput = () => obj[k] = i.value; return i; };
const chk = (obj, k, lab, cb) => { const i = el("input", {type: "checkbox", checked: !!obj[k]}); i.onchange = () => { obj[k] = i.checked; cb?.(); }; return el("label", {className: k === "nube_permitida" ? "check solo-nube" : "check"}, i, " " + lab); };
const mover_ = (arr, i, d) => { const j = i + d; if (j < 0 || j >= arr.length) return; [arr[i], arr[j]] = [arr[j], arr[i]]; pintarEd(); };
const boton = (t, f, cls = "sec") => el("button", {type: "button", className: cls, textContent: t, onclick: fallo(async () => f())});
function pintarEd(t = plantDe(pSel)) {
  const ed = t.editable, base = SERIE[pe.base || pe.id] || {}, re = () => pintarEd(t);
  const secs = pe.secciones.map((s, i) => el("div", {className: "psec"},
    el("div", {className: "row"}, el("input", {value: s.nombre, ariaLabel: "Nombre de la sección", oninput: e => s.nombre = e.target.value}),
      el("input", {value: s.id, ariaLabel: "Id", title: "Id (minúsculas, cifras y _)", style: "max-width:9em", oninput: e => {
        const o = s.id; s.id = e.target.value; pe.orden = pe.orden.map(b => b === o ? s.id : b); pe.notas_rapidas.forEach(n => n.seccion === o && (n.seccion = s.id)); }}),
      boton("↑", () => mover_(pe.secciones, i, -1)), boton("↓", () => mover_(pe.secciones, i, 1)), boton("✕", () => { pe.secciones.splice(i, 1); pe.orden = pe.orden.filter(b => b !== s.id); re(); })),
    txt(s, "descripcion", true, {ariaLabel: "Qué debe buscar el modelo", placeholder: "Qué debe buscar el modelo"}),
    el("div", {className: "row"}, el("label", {textContent: "Campos"}), el("input", {value: s.campos.join(", "), placeholder: "responsable, fecha, gravedad…", title: "Además de la cita y el minuto, que van siempre",
      oninput: e => s.campos = e.target.value.split(",").map(x => x.trim().toLowerCase().replace(/\s+/g, "_")).filter(Boolean)}), chk(s, "nunca_recortar", "No recortar nunca"))));
  const orden = pe.orden.map((b, i) => el("div", {className: "row"}, el("span", {textContent: LIBRES.includes(b) ? b : (pe.secciones.find(s => s.id === b)?.nombre || b), style: "min-width:9em"}),
    el("input", {value: pe.titulos[b] || "", placeholder: "Título (vacío = el nombre)", oninput: e => pe.titulos[b] = e.target.value}),
    boton("↑", () => mover_(pe.orden, i, -1)), boton("↓", () => mover_(pe.orden, i, 1))));
  const notas = pe.notas_rapidas.map((n, i) => el("div", {className: "row"}, txt(n, "nombre", false, {ariaLabel: "Nota"}),
    (sel => { sel.value = n.seccion || ""; sel.onchange = () => n.seccion = sel.value || null; return sel; })(el("select", {}, new Option("— sin sección —", ""), ...pe.secciones.map(s => new Option(s.nombre, s.id)))),
    txt(n, "atajo", false, {ariaLabel: "Atajo", style: "max-width:7em"}), boton("✕", () => { pe.notas_rapidas.splice(i, 1); re(); })));
  const reset = (k, v) => boton("Restablecer", () => { pe[k] = v; re(); });
  const esc = el("details", {open: !!pe.mostrar_escala}, el("summary", {textContent: "Opciones avanzadas de la plantilla"}),
    chk(pe, "mostrar_escala", "Ajustar la escala de importancia", re),
    ...(pe.mostrar_escala ? [el("small", {textContent: "La nota de cada idea al resumir: con 1 nunca entra; al recortar, primero las más altas. Las secciones «no recortar nunca» entran siempre."}),
      ...["5", "4", "3", "2", "1"].map(k => el("div", {className: "row"}, el("label", {textContent: k}), txt(pe.escala, k, false, {placeholder: DEF[k]}))),
      boton("Restablecer valores por defecto", () => { pe.escala = {...DEF}; re(); })] : []));
  const probar = el("select", {ariaLabel: "Reunión"}, ...todas.filter(m => !m.sin).map(m => new Option(m.label, m.id + "|" + m.asr)));
  const acciones = [
    ...(ed ? [boton("Guardar", guardarPlant, "pri")] : []),
    boton("Duplicar", async () => { const c = await post("/api/plantillas", {plantilla: {...pe, id: "", nombre: pe.nombre + " (copia)", base: pe.base || (t.serie ? t.id : undefined)}}); await abrirPlant(c.id); aviso("Duplicada: ya puedes editarla"); }),
    boton("Exportar", () => { const a = el("a", {href: URL.createObjectURL(new Blob([JSON.stringify(pe, null, 1)], {type: "application/json"})), download: pe.id + ".json"}); a.click(); }),
    ...(ed ? [boton(t.serie ? "Restablecer" : "Eliminar", async () => { if (!confirm(t.serie ? "¿Volver a la plantilla de serie?" : "¿Eliminar la plantilla «" + t.nombre + "»?")) return; await post("/api/plantillas/borrar", {id: t.id}); if (!t.serie) pSel = "acta"; await abrirPlant(); })] : [])];
  $("plant-ed").replaceChildren(el("fieldset", {disabled: !ed},
    el("h2", {textContent: t.nombre}), ...(ed ? [] : [el("p", {className: "muted", textContent: "Plantilla de serie: no se edita. Duplícala para cambiarla."})]),
    campo("Nombre", txt(pe, "nombre")), campo("Descripción", txt(pe, "descripcion")),
    el("div", {className: "row"}, el("label", {textContent: "Documento"}), txt(pe.documento, "singular", false, {ariaLabel: "Singular", placeholder: "acta, informe, apuntes…"}),
      txt(pe.documento, "plural", false, {ariaLabel: "Plural"}), chk(pe.documento, "femenino", "femenino")),
    el("h3", {textContent: "Secciones"}), el("small", {textContent: "Cada elemento lleva su minuto y una cita literal comprobada en la transcripción. «decisiones» y «tareas» usan la verificación del acta de reunión."}),
    ...secs, boton("+ sección", () => { pe.secciones.push({id: "seccion" + (pe.secciones.length + 1), nombre: "Nueva sección", descripcion: "", campos: [], nunca_recortar: false}); pe.orden.splice(pe.orden.indexOf("desarrollo") >>> 0, 0, pe.secciones.at(-1).id); re(); }),
    el("h3", {textContent: "Qué destacar"}), txt(pe, "que_destacar", true), reset("que_destacar", base.que_destacar || ""),
    el("h3", {textContent: "Cómo redactar"}), txt(pe, "como_redactar", true), reset("como_redactar", base.como_redactar || ""),
    el("small", {textContent: "Cambiar las secciones, qué destacar o la escala repite el resumen por bloques (lo lento). Cambiar cómo redactar solo repite la redacción final (rápido: se reutiliza lo ya resumido)."}),
    el("h3", {textContent: "Orden y títulos del documento"}), ...orden,
    el("h3", {textContent: "Notas rápidas"}), el("small", {textContent: "Para marcar momentos durante una grabación (fase posterior)."}), ...notas,
    boton("+ nota", () => { pe.notas_rapidas.push({nombre: "Nota", seccion: null, atajo: ""}); re(); }),
    el("h3", {textContent: "Opciones"}), chk(pe.opciones, "capturas", "Capturas de pantalla"), chk(pe.opciones, "marcas", "Marcas de tiempo [mm:ss]"),
    chk(pe, "nube_permitida", "Se puede procesar en la nube (desmárcalo para datos sensibles)"),
    campo("Idioma del documento", (sel => { sel.value = pe.idioma_acta; sel.onchange = () => pe.idioma_acta = sel.value; return sel; })(el("select", {}, ...Object.entries(IDI).map(([k, n]) => new Option(cap(n), k))))),
    esc),
    el("div", {className: "row wrap"}, ...acciones),
    el("h3", {textContent: "Probar con una reunión"}), el("small", {textContent: "Genera otra versión de esa reunión con esta plantilla (no sustituye a las demás)."}),
    el("div", {className: "row"}, probar, boton("Probar", async () => {
      if (!probar.value) return; if (ed) await guardarPlant();
      const [id, asr] = probar.value.split("|");
      await post("/api/generar", {reuse: id, asr, nivel: "normal", calidad: $("calidad").value || "rápida", gpu: $("usar-gpu").checked, plantilla: pe.id});
      aviso("Añadido a la cola"); sondear();
    })));
}
async function guardarPlant() { const t = await post("/api/plantillas", {plantilla: pe}); await abrirPlant(t.id); aviso("Plantilla guardada"); }
$("plant-imp").onchange = fallo(async () => {  // importar .json: si ya existe, reemplazar o guardar como copia
  const f = $("plant-imp").files[0]; $("plant-imp").value = ""; if (!f) return;
  let t; try { t = JSON.parse(await f.text()); } catch { throw new Error("El fichero no es un JSON válido"); }
  const subir = async modo => { const r = await post("/api/plantillas", {plantilla: t, modo}); $("plant-msg").replaceChildren(); await abrirPlant(r.id); aviso("Plantilla importada"); };
  try { await subir("importar"); } catch (err) {
    if (!/^Ya hay/.test(err.message)) throw err;
    $("plant-msg").replaceChildren(el("div", {className: "row wrap card"}, el("span", {textContent: err.message + ": "}),
      boton("Reemplazar", () => subir("reemplazar"), "pri"), boton("Guardar como copia", () => subir("copia")), boton("Cancelar", async () => $("plant-msg").replaceChildren())));
  }
});

