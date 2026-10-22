// Ajustes › Modelos: catálogo (instalar/quitar), modelos locales (GGUF detectados, archivo, Hugging Face) y roles (búsqueda y chat de Preguntar).
const BADGE = {ok: ["Recomendado", "ok"], aviso: ["Usable (no recomendado)", "w"], no: ["No compatible", "no"]};
const AV = {aviso: "No tienes los recursos recomendados para este modelo, puede tardar más de lo normal", no: n => `Tu equipo no tiene memoria suficiente para este modelo (necesita ~${Math.ceil(n)} GB): no se podrá usar`};
let MOD = null, pend = {msg: null, faltan: [], rec: false};
const avisoM = (e, need) => e === "aviso" ? AV.aviso : e === "no" ? AV.no(need) : "";
const badge = e => el("span", {className: "badge " + (BADGE[e]?.[1] || ""), textContent: BADGE[e]?.[0] || ""});
const total = () => MOD.catalogo.filter(c => !c.instalado && $("mc-" + c.id)?.checked).reduce((a, c) => a + c.bytes, 0);
const recNiveles = async () => niveles((await api("/api/gpu")).niveles);

function abrirModelos(msg, faltan, rec) { pend = {msg: msg || null, faltan: faltan || [], rec: !!rec}; abrirAjustes("modelos"); }
async function pintarTabModelos() {
  const m = await fetch("/api/modelos").then(r => r.json()).catch(() => null); if (!m) return;
  $("mod-intro").textContent = pend.msg || (simple() ? "Modelos de inteligencia artificial que se ejecutan en este equipo. Se descargan una sola vez y después todo funciona sin internet."
    : "Elige qué modelos instalar. Se descargan una sola vez y después funciona sin internet; si se corta, sigue donde se quedó. Sin modelos puedes ver e importar documentos.");
  if (m.state === "running" || m.state === "error") return seguir(m);
  $("mod-prog").hidden = true; const p = pend; pend = {msg: null, faltan: [], rec: false};
  pintarModelos(m, p.faltan); modSimple(m);
  if (p.rec) $("mod-selrec").click();
  if (!simple() || document.body.classList.contains("mod-todos")) { pintarEncontrados(); pintarRoles(); }
  if (!simple()) pintarNiveles();
}
// niveles de calidad (design/Ajustes.dc.html): qué modelo usa cada nivel, si cabe en este equipo y descarga del que falte
async function pintarNiveles() {
  const g = await api("/api/gpu").catch(() => null); if (!g) return;
  const EQ = {ok: ["Cómodo", "ok"], aviso: ["Lento", "w"], no: ["No cabe", "no"]};
  $("mod-niv-sub").textContent = "Este equipo: " + (g.ok ? g.name + (g.vram_mb ? " · " + Math.round(g.vram_mb / 1024) + " GB de VRAM" : "") : "sin GPU") + " · " + (g.ram_gb || "?") + " GB de RAM.";
  $("mod-niv-t").replaceChildren(...g.niveles.map(n => el("tr", {}, el("td", {className: "b", textContent: n.nombre}), el("td", {textContent: n.modelo}),
    el("td", {className: "eq " + (EQ[n.estado]?.[1] || ""), textContent: EQ[n.estado]?.[0] || ""}),
    el("td", {}, n.instalado ? el("span", {className: "muted", textContent: "Instalado"}) : el("button", {className: "sec sm", textContent: (n.estado === "no" ? "Descargar igualmente · " : "Descargar · ") + GB(n.bytes),
      onclick: fallo(async () => { await post("/api/modelos", {ids: [n.m]}); pintarTabModelos(); })})))));
}
function pintarModelos(m, faltan = []) {
  MOD = m; const L = $("mod-lista"); L.replaceChildren();
  for (const c of m.catalogo) {
    const w = el("small", {className: "warn", hidden: true}), cb = el("input", {type: "checkbox", id: "mc-" + c.id, checked: c.instalado, disabled: c.instalado});
    const row = el("div", {className: "mrow"}, el("label", {}, cb, el("span", {}, el("b", {textContent: c.nombre}), " ", el("span", {className: "muted", textContent: c.uso}))),
      badge(c.estado), el("span", {className: "muted", textContent: c.instalado ? "instalado" : GB(c.bytes)}), w);
    const act = () => { const t = c.estado !== "ok" && (cb.checked && !c.instalado || c.instalado && c.estado === "no") ? avisoM(c.estado, c.necesita) : ""; w.textContent = t; w.hidden = !t; resumenTotal(); };
    cb.onchange = act;
    if (c.instalado) row.insertBefore(el("button", {className: "sec sm", textContent: "Quitar", ariaLabel: "Quitar " + c.nombre, onclick: async () => { if (confirm(`¿Quitar ${c.nombre} y liberar ${GB(c.bytes)}?`)) try { pintarModelos(await post("/api/modelos/borrar", {id: c.id})); modSimple(MOD); await recNiveles(); } catch (e) { alert(e.message); } }}), w);
    L.append(row);
  }
  for (const i of faltan) if ($("mc-" + i)) $("mc-" + i).checked = true;
  for (const c of m.catalogo) $("mc-" + c.id).onchange();
}
function resumenTotal() { $("mod-total").textContent = "Descarga total: " + GB(total()); $("mod-inst").textContent = `Instalar seleccionados (${GB(total())})`; $("mod-inst").disabled = !total(); }
function modSimple(m) {
  const rec = m.catalogo.filter(c => m.recomendados.includes(c.id) && !c.instalado), b = rec.reduce((a, c) => a + c.bytes, 0);
  $("mod-s-txt").textContent = rec.length ? "Para este equipo se recomienda instalar " + rec.map(c => c.nombre).join(", ") + ". Se descarga una sola vez y después todo funciona sin internet." : "Ya está instalado todo lo recomendado para este equipo.";
  $("mod-srec").hidden = !rec.length; $("mod-srec").textContent = "Instalar lo recomendado (" + GB(b) + ")";
}
// ---- modelos locales ----
const NIVELES_U = () => NIV.map(n => [n.id, "Redactar: " + n.nombre]);
const USOS_M = () => [["", "Sin usar"], ...NIVELES_U(), ["pers", "Nivel personalizado"], ["chat", "Chat de Preguntar"], ["emb", "Búsqueda (embeddings)"]];
async function pintarEncontrados() {
  const r = await api("/api/modelos/encontrados"), L = $("mod-enc-lista"), lv = r.config.levels || {}, ro = r.config.roles || {}, ex = (r.config.extra || []).map(e => e.ruta); L.replaceChildren();
  for (const e of r.encontrados) {
    const cur = Object.keys(lv).find(q => lv[q] === e.ruta) || Object.keys(ro).find(q => ro[q] === e.ruta) || (ex.includes(e.ruta) ? "pers" : "");
    const s = el("select", {ariaLabel: "Usar " + e.nombre + " para", onchange: fallo(async ev => { await post("/api/modelos/usar", {ruta: e.ruta, nivel: ev.target.value, nombre: e.nombre}); await recNiveles(); aviso("Guardado"); pintarEncontrados(); pintarRoles(); })},
      ...USOS_M().map(([v, t]) => new Option(t, v)));
    s.value = cur;
    L.append(el("div", {className: "mrow"}, el("label", {style: "pointer-events:none"}, el("span", {}, el("b", {textContent: e.nombre}), el("small", {className: "ruta", textContent: `${e.origen} · ${e.ruta}`}))), badge(e.estado), el("span", {className: "muted", textContent: GB(e.bytes)}), s,
      ...(e.estado === "no" ? [el("small", {className: "warn", textContent: AV.no(e.necesita)})] : [])));
  }
  if (!r.encontrados.length) L.append(el("p", {className: "muted", textContent: "No se encontró ninguno. Usa «+ Añadir modelo»."}));
}
async function pintarRoles() {
  const [ro, ch, em] = await Promise.all([api("/api/modelos/roles"), api("/api/modelos/encontrados"), api("/api/modelos/encontrados?emb=true")]);
  const fila = (rol, tit, nota, cand) => {
    const r = ro[rol], s = el("select", {id: "rol-" + rol, ariaLabel: tit}); s.add(new Option("Por defecto: " + (r.defecto ? r.nombre : "modelo de serie"), ""));
    const l = [...cand]; if (r.ruta && !l.some(c => c.ruta === r.ruta)) l.unshift({ruta: r.ruta, nombre: r.nombre, bytes: r.bytes});
    for (const c of l) s.add(new Option(c.nombre + (c.origen ? " · " + c.origen : ""), c.ruta)); s.value = r.defecto ? "" : r.ruta;
    s.onchange = fallo(async () => { r.defecto || !s.value ? 0 : 0; if (!s.value) await post("/api/modelos/roles/quitar", {rol}); else await post("/api/modelos/usar", {ruta: s.value, nivel: rol}); aviso("Guardado"); pintarRoles(); });
    return el("div", {className: "field"}, el("label", {htmlFor: "rol-" + rol, textContent: tit}), s, el("small", {textContent: nota + (r.reindexa ? ". " + r.reindexa : "")}),
      ...(!r.defecto && r.estado && r.estado !== "ok" ? [el("small", {className: "warn", textContent: avisoM(r.estado, r.necesita)})] : []));
  };
  $("mod-roles-l").replaceChildren(fila("emb", "Búsqueda (embeddings)", "Encuentra los fragmentos relevantes antes de responder", em.encontrados), fila("chat", "Chat de Preguntar", "Redacta la respuesta con lo encontrado", ch.encontrados),
    el("button", {className: "link", textContent: "+ Añadir otro modelo", onclick: () => dlgAdd()}));
}
// ---- añadir modelo: archivo local, detectado o Hugging Face ----
function dlgAdd() {
  const d = $("d-add"), c = $("d-add-c");
  const destino = el("select", {id: "add-dest", ariaLabel: "Usar como"}, ...USOS_M().filter(([v]) => v).map(([v, t]) => new Option(t, v))); destino.value = "pers";
  const cerrar = el("button", {className: "sec", textContent: "Cancelar", onclick: () => d.close()});
  const paso0 = () => c.replaceChildren(el("p", {className: "muted", textContent: "¿De dónde viene el modelo (.gguf)?"}),
    el("div", {className: "chips"},
      el("button", {className: "chip", type: "button", onclick: () => paso("archivo")}, el("b", {textContent: "Archivo en este equipo"}), el("small", {textContent: "Elige un .gguf; se usa donde está, sin copiarlo"})),
      el("button", {className: "chip", type: "button", onclick: () => { d.close(); document.body.classList.add("mod-todos"); $("mod-loc").scrollIntoView({behavior: "smooth"}); }}, el("b", {textContent: "Detectado en este equipo"}), el("small", {textContent: "LM Studio, Ollama, Hugging Face, Jan, GPT4All: elige uno de la lista «Tus modelos locales»"})),
      el("button", {className: "chip", type: "button", onclick: () => paso("hf")}, el("b", {textContent: "Hugging Face"}), el("small", {textContent: "Pega una URL o «usuario/repo» y descárgalo"}))), el("div", {className: "row"}, cerrar));
  const paso = tipo => {
    const msg = el("p", {className: "err", role: "alert"}), campo = el("div", {className: "field"}, el("label", {htmlFor: "add-dest", textContent: "Usar como"}), destino);
    if (tipo === "archivo") {
      c.replaceChildren(campo, msg, el("div", {className: "row"}, el("button", {className: "sec", textContent: "Atrás", onclick: paso0}), el("button", {className: "pri", textContent: "Elegir archivo…", onclick: fallo(async () => {
        const r = (await post("/api/pick", {tipo: "modelo"})).path; if (!r) return;
        try { await post("/api/modelos/usar", {ruta: r, nivel: destino.value}); await recNiveles(); d.close(); aviso("Modelo añadido"); pintarEncontrados(); pintarRoles(); } catch (e) { msg.textContent = e.message; } })})));
      return;
    }
    const ent = el("input", {id: "add-hf", placeholder: "usuario/repo  o  https://huggingface.co/…", ariaLabel: "Modelo de Hugging Face"}), lista = el("div", {id: "add-hf-l"}), go = el("button", {className: "pri", textContent: "Descargar", disabled: true});
    const bus = el("button", {type: "button", className: "sec", textContent: "Buscar", onclick: async () => {
      msg.textContent = ""; lista.replaceChildren(); go.disabled = true; bus.disabled = true;
      try {
        const r = await post("/api/modelos/hf/info", {entrada: ent.value}); let sel = r.archivos[0];
        lista.replaceChildren(el("p", {className: "muted", textContent: r.repo}), ...r.archivos.map((a, i) => el("label", {className: "opt"}, el("input", {type: "radio", name: "hff", checked: !i, onchange: () => sel = a}),
          el("span", {}, el("b", {textContent: a.fichero}), el("small", {textContent: GB(a.bytes) + (a.estado !== "ok" ? " · " + avisoM(a.estado, a.necesita) : "")})))));
        go.disabled = false; go.onclick = fallo(async () => { try { await post("/api/modelos/hf/bajar", {repo: r.repo, fichero: sel.fichero, nivel: destino.value, bytes: sel.bytes, nombre: sel.fichero.replace(/\.gguf$/i, "")}); d.close(); pintarTabModelos(); } catch (e) { msg.textContent = e.message; } });
      } catch (e) { msg.textContent = e.message; } finally { bus.disabled = false; }
    }});
    ent.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); bus.click(); } };
    c.replaceChildren(el("div", {className: "field"}, el("label", {htmlFor: "add-hf", textContent: "Modelo de Hugging Face"}), el("div", {className: "row"}, ent, bus)), lista, campo, msg,
      el("div", {className: "row"}, el("button", {className: "sec", textContent: "Atrás", onclick: paso0}), go));
    ent.focus();
  };
  paso0(); d.showModal();
}
$("mod-add").onclick = dlgAdd;
// ---- instalar / progreso ----
async function instalar(ids) {
  $("mod-prog").hidden = false; $("mod-reint").hidden = true; $("mod-msg").textContent = "Empezando…";
  try { seguir(await post("/api/modelos", ids ? {ids} : {})); } catch (e) { $("mod-msg").textContent = e.message; }
}
let segTimer = 0;
async function seguir(m) {
  if (tabAj !== "modelos" || vistaAct !== "ajustes") return;  // si el usuario se va a otra pantalla, la descarga sigue y al volver se retoma
  ["mod-simple", "mod-cat", "mod-loc", "mod-roles"].forEach(i => $(i).hidden = true); $("mod-prog").hidden = false; $("mod-reint").hidden = true;
  const p = m.total ? Math.min(100, Math.round(m.done / m.total * 100)) : 0;
  $("mod-msg").textContent = m.msg; $("mod-bar").style.width = p + "%";
  $("mod-pct").textContent = p + " % · " + (m.done / 1e9).toFixed(2) + " de " + (m.total / 1e9).toFixed(2) + " GB";
  if (m.state === "error") { $("mod-reint").hidden = false; return; }
  if (m.state === "done") { await recNiveles(); ["mod-simple", "mod-cat", "mod-loc", "mod-roles"].forEach(i => $(i).hidden = false); $("mod-prog").hidden = true; pintarTabModelos(); return; }
  clearTimeout(segTimer); segTimer = setTimeout(async () => seguir(await api("/api/modelos")), 1000);
}
$("mod-selrec").onclick = () => { for (const c of MOD.catalogo) if (!c.instalado) $("mc-" + c.id).checked = MOD.recomendados.includes(c.id); MOD.catalogo.forEach(c => $("mc-" + c.id).onchange()); };
$("mod-inst").onclick = () => instalar(MOD.catalogo.filter(c => !c.instalado && $("mc-" + c.id).checked).map(c => c.id));
$("mod-reint").onclick = () => instalar(MOD.catalogo.filter(c => !c.instalado && $("mc-" + c.id)?.checked).map(c => c.id));
$("mod-srec").onclick = () => instalar(null);
$("mod-todos").onclick = () => { document.body.classList.add("mod-todos"); pintarTabModelos(); };

// ---- arranque: todo está definido ya ----
arranque(); cargarUP(); ruta_();
