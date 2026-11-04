/* Enviar: destinos, presets, recetas, historial, checklist del plan y envío rápido. Globales: $, api, el. */
(() => {
const jh = {"Content-Type": "application/json"};
const send = (m, u, b) => api(u, {method: m, headers: jh, body: JSON.stringify(b || {})});
const ls = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
const T = (t, c, ...k) => el(t, c ? {className: c} : {}, ...k);
const btn = (txt, cls, fn, extra = {}) => el("button", {type: "button", className: "btn " + cls, textContent: txt, onclick: fn, ...extra});
const GRUPOS = [["Local", ["carpeta"]], ["Microsoft 365", ["ms_onedrive", "ms_planner", "ms_todo", "ms_onenote", "ms_teams", "ms_outlook", "teams", "power_automate", "azure"]],
  ["Tareas", ["github", "gitea", "gitlab", "jira", "linear", "todoist", "trello"]], ["Notas / wiki", ["notion", "outline", "bookstack"]],
  ["Mensajería", ["slack", "webhook"]], ["Servidor propio / VPS", ["webdav", "s3", "sftp", "paperless"]], ["Correo", ["correo"]]];
const QL = {documento: "Documento completo", resumen: "Resumen", tareas: "Tareas", decisiones: "Decisiones", riesgos: "Riesgos", requisitos: "Requisitos",
  historias: "Historias de usuario", interesados: "Interesados", informe: "Informe de estado", transcripcion: "Transcripción"};
const ORDEN = ["tareas", "decisiones", "riesgos", "requisitos", "historias", "resumen", "informe", "interesados", "documento"];
const DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"];
const CADA = {dia: "día", semana: "semana", mes: "mes"};
const FMT_LOCAL = ["pdf", "docx", "md", "xlsx", "csv"];
const FN = {pdf: "PDF", docx: "Word", md: "Markdown", xlsx: "Excel", csv: "CSV"};

let live = null;
function toast(msg, err, opts) {
  if (typeof aviso === "function") return aviso(msg, opts);  // snackbar global (app.js); errores también
  if (!err && window.snackbar) return window.snackbar(msg, opts);
  live ||= document.body.appendChild(el("div", {className: "env-toast", role: "status", "aria-live": "polite"}));
  live.textContent = msg; live.classList.toggle("env-bad", !!err); live.hidden = false;
  clearTimeout(live._t); live._t = setTimeout(() => live.hidden = true, 5000);
}
/* Chip de preset compartido (Añadir, Descargar, Enviar): icono + nombre, ★ si fijado, ⋯ solo al pasar/enfocar. «De serie» = icono ✦ + tooltip. */
function chip({nombre, icono, fijado, serie, activo, ultimo, titulo, onSelect, onMenu}) {
  const tip = [titulo, serie ? "De serie" : "", ultimo ? "Último usado" : ""].filter(Boolean).join(" · ");
  return T("span", "pchip" + (activo ? " on" : "") + (ultimo ? " ult" : ""),
    el("button", {type: "button", className: "pchip-b", "aria-pressed": !!activo, title: tip || null, onclick: onSelect},
      el("span", {className: "pchip-i", "aria-hidden": "true", textContent: icono || (serie ? "✦" : "◆")}), T("span", "pchip-n", nombre), ...(fijado ? [el("span", {className: "pchip-s", title: "Fijado", textContent: "★"})] : [])),
    ...(onMenu ? [el("button", {type: "button", className: "pchip-m", "aria-label": "Opciones de " + nombre, "aria-haspopup": "menu", textContent: "⋯", onclick: e => { e.stopPropagation(); onMenu(e.currentTarget); }})] : []));
}
/* Menú emergente anclado al chip: items [[texto, fn]] */
function menu(ancla, items) {
  document.querySelector(".env-gm")?.remove();
  const u = T("ul", "env-menu env-pmenu env-gm", ...items.map(([t, fn]) => T("li", "", btn(t, "sec env-sm env-mi", async () => { cierra(); try { await fn(); } catch (e) { fail(e); } }))));
  u.setAttribute("role", "menu");
  const cierra = () => { u.remove(); document.removeEventListener("pointerdown", fuera, true); document.removeEventListener("keydown", tecla, true); };
  const fuera = e => { if (!u.contains(e.target) && !ancla.contains(e.target)) cierra(); };
  const tecla = e => { if (e.key === "Escape") { e.stopPropagation(); cierra(); ancla.focus(); } };
  (ancla.closest(".pchip") || ancla.parentNode).append(u);
  {  // dentro de la hoja o la ventana: hacia arriba si abajo no cabe, alineado a la derecha si se sale, y con scroll propio si aún no cabe
    const hoja = ancla.closest(".sh-b, dialog")?.getBoundingClientRect(), top = Math.max(0, hoja?.top ?? 0), bot = Math.min(innerHeight, hoja?.bottom ?? innerHeight);
    const r = u.getBoundingClientRect(), abajo = bot - r.top, arriba = ancla.getBoundingClientRect().top - top, sube = r.height > abajo && arriba > abajo;
    u.classList.toggle("arriba", sube); u.style.maxHeight = Math.max(120, (sube ? arriba : abajo) - 12) + "px";
    u.classList.toggle("der", r.right > document.documentElement.clientWidth - 8);
  }
  document.addEventListener("pointerdown", fuera, true); document.addEventListener("keydown", tecla, true);
  u.querySelector("button")?.focus();
}
const fail = e => toast(e.message || String(e), true);

const mov = () => !matchMedia("(prefers-reduced-motion: reduce)").matches;
function salir(d) { if (!mov()) return d.close(); d.classList.add("saliendo"); setTimeout(() => d.close(), 160); }
const esc = (nodes) => { nodes.forEach((n, i) => n.style?.setProperty("--i", Math.min(i, 7))); return nodes; };  // entrada escalonada (máx. 8 × 30 ms)
const resumen = (p, ctx) => {
  if (p.solo_buscable && !(p.salidas || []).length) return "Solo buscable, sin documentos extra";
  const q = [...new Set((p.salidas || []).map(s => QL[s.que] || s.que))].join(", ") || "—";
  const dn = [...new Set((p.salidas || []).map(s => s.como === "documento" ? "documento del proyecto" : ctx.dest[s.destino]?.nombre || ctx.presets.find(x => x.id === s.preset)?.nombre || "?"))].join(", ");
  return q + (dn ? " → " + dn : "");
};
const FS = "env.fijadosSerie";
/* iconos SVG de 24 px (estado vacío); trazos como el resto de iconos de la app */
const SVG = {carpeta: '<path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>', correo: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>',
  slack: '<path d="M5 9h14M5 15h14M10 4L8 20M16 4l-2 16"/>', receta: '<path d="M20 12a8 8 0 1 1-2.3-5.7"/><path d="M20 4v5h-5"/>'};
const ico = k => { const s = T("span", "env-ic"); s.setAttribute("aria-hidden", "true"); s.innerHTML = `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${SVG[k]}</svg>`; return s; };

/* Cabecera común de los diálogos (Enviar, Descargar): título + «×», como la hoja Añadir */
function cabecera(titulo, cerrar) {
  const x = btn("×", "sec qi", cerrar, {"aria-label": "Cerrar"});
  return T("div", "env-dh", T("h2", "", titulo), x);
}
function dialogo(titulo, cuerpo, acciones = []) {
  const d = el("dialog", {className: "env-dlg", "aria-label": titulo});
  const cerrar = btn(acciones.length ? "Cancelar" : "Cerrar", "sec", () => salir(d));
  d.append(cabecera(titulo, () => salir(d)), cuerpo, T("div", "row env-acc", cerrar, ...acciones));  // secundario · primario
  d.addEventListener("close", () => d.remove());
  document.body.append(d); d.showModal();
  (cuerpo.querySelector?.("input:not([type=hidden]),select,textarea,button") || d.querySelector(".env-acc .pri") || cerrar).focus();  // el foco no cae en el «×»
  return d;
}

async function datos() {
  const [cat, presets, recetas] = await Promise.all([api("/api/destinos"), api("/api/presets"), api("/api/recetas")]);
  presets.sort((a, b) => !!b.fijado - !!a.fijado);
  return {cat, presets, recetas, dest: Object.fromEntries(cat.destinos.map(d => [d.id, d]))};
}


/* ---------- cuenta de Microsoft (Graph, código de dispositivo) ---------- */
function msCard() {
  const w = T("div", "env-card card env-ms"); let timer;
  const parar = () => clearTimeout(timer);
  const pintar = async () => {
    if (!w.isConnected && w._v) return parar();
    let s; try { s = await api("/api/ms/estado"); } catch (e) { w.replaceChildren(T("h3", "", "Cuenta de Microsoft"), T("p", "err", e.message)); return; }
    w._v = 1;
    const head = T("h3", "", "Cuenta de Microsoft");
    if (s.conectado) return w.replaceChildren(head, T("p", "", "Conectado como ", T("strong", "", s.cuenta || "?")),
      btn("Cerrar sesión", "sec env-sm", async () => { try { await send("POST", "/api/ms/logout"); } catch (e) { fail(e); } pintar(); }));
    const cid = el("input", {id: "env-ms-c", value: s.client_id || "", autocomplete: "off"}), tn = el("input", {id: "env-ms-t", value: s.tenant || "", placeholder: "organizations"});
    const msg = T("p", "env-msg", s.error || ""); msg.setAttribute("role", "status"); if (s.error) msg.className = "env-msg err";
    const ir = btn("Iniciar sesión con Microsoft", "pri", async () => {
      ir.disabled = true;
      try {
        const r = await send("POST", "/api/ms/login", {client_id: cid.value.trim(), tenant: tn.value.trim()});
        const fin = Date.now() + (r.expires_in || 900) * 1000;
        const cp = btn("Copiar", "sec env-sm", () => navigator.clipboard?.writeText(r.user_code).then(() => cp.textContent = "Copiado"));
        w.replaceChildren(head, T("p", "", "Abre el enlace e introduce este código:"), T("div", "env-code", r.user_code), T("div", "env-row", cp,
          el("a", {href: r.verification_uri, target: "_blank", rel: "noopener", className: "btn pri", textContent: "Abrir " + r.verification_uri.replace(/^https?:\/\//, "")})), msg);
        msg.textContent = "Esperando confirmación…";
        const sondeo = async () => {
          if (!w.isConnected) return;
          let e; try { e = await api("/api/ms/estado"); } catch {}
          if (e?.conectado || e?.error || Date.now() > fin) return pintar();
          timer = setTimeout(sondeo, 3000);
        };
        timer = setTimeout(sondeo, 3000);
      } catch (e) { msg.textContent = e.message; msg.className = "env-msg err"; ir.disabled = false; }
    });
    w.replaceChildren(head, T("div", "env-campo", el("label", {htmlFor: "env-ms-c"}, "ID de aplicación (client ID)"), cid),
      T("div", "env-campo", el("label", {htmlFor: "env-ms-t"}, "Inquilino (tenant, vacío = organizations)"), tn,
        T("small", "", "Tu TI debe registrar una aplicación en Microsoft Entra (cliente público, flujo de código de dispositivo). Sin ella, usa la carpeta sincronizada de OneDrive/SharePoint, Teams por Workflows o Power Automate, que no necesitan permisos.")),
      T("div", "env-row", ir), msg);
  };
  pintar(); return w;
}
const esMs = t => t.startsWith("ms_");
async function outlook(mid, ver, n) {
  try { const r = await send("POST", `/api/correo/${encodeURIComponent(mid)}/${encodeURIComponent(ver)}/outlook/${n}`); toast("Borrador abierto en Outlook"); return r; }
  catch (e) { fail(e); }
}

/* ---------- formulario dinámico de destino ---------- */
function campo(f, valor, d) {
  const id = "env-f-" + f.id + "-" + Math.random().toString(36).slice(2, 6);
  let inp, getv;
  const guardado = d && d.secretos && d.secretos[f.id];
  if (f.tipo === "booleano") {
    inp = el("input", {type: "checkbox", id, checked: valor ?? f.defecto ?? false}); getv = () => inp.checked;
  } else if (f.tipo === "opcion") {
    inp = el("select", {id}, ...(f.opciones || []).map(o => el("option", {value: o, textContent: o, selected: (valor ?? f.defecto) === o})));
    getv = () => inp.value;
  } else if (f.tipo === "lista") {
    const sel = new Set(valor ?? f.defecto ?? []);
    inp = el("div", {className: "env-lista", role: "group", "aria-labelledby": id + "-l"},
      ...(f.opciones || []).map(o => { const c = el("input", {type: "checkbox", value: o, checked: sel.has(o)}); return T("label", "env-chk", c, " " + o); }));
    getv = () => [...inp.querySelectorAll("input:checked")].map(c => c.value);
  } else {
    inp = el("input", {id, type: f.tipo === "secreto" ? "password" : f.tipo === "numero" ? "number" : f.tipo === "url" ? "url" : "text",
      value: f.tipo === "secreto" ? "" : valor ?? f.defecto ?? "", placeholder: guardado ? "guardado (escribe para cambiar)" : "",
      autocomplete: "off", required: !!f.req && !guardado});
    getv = () => inp.value;
  }
  const lab = f.tipo === "booleano"
    ? T("label", "env-chk", inp, " " + f.etiqueta)
    : el("label", {htmlFor: id, id: id + "-l"}, f.etiqueta + (f.req ? " *" : ""));
  const w = T("div", "env-campo", f.tipo === "booleano" ? lab : lab, ...(f.tipo === "booleano" ? [] : [inp]));
  if (guardado) w.append(T("span", "env-saved", "guardado"));
  if (f.ayuda) w.append(T("small", "", f.ayuda));
  if (f.id === "verificar_tls") {
    const aviso = T("small", "env-tls", "Sin verificar el certificado TLS: la conexión no está protegida frente a suplantación.");
    const upd = () => aviso.hidden = !!getv(); inp.addEventListener("change", upd); upd(); w.append(aviso);
  }
  return {w, id: f.id, getv, secreto: f.tipo === "secreto", inp};
}

async function formDestino(ctx, tipo, existente, alGuardar) {
  const def = ctx.cat.tipos[tipo];
  const nombre = el("input", {id: "env-nombre", value: existente?.nombre || "", placeholder: def.nombre});
  const campos = def.campos.map(f => campo(f, existente?.config?.[f.id], existente));
  const cuerpo = T("form", "env-form", ...(esMs(tipo) ? [msCard()] : []), T("div", "env-campo", el("label", {htmlFor: "env-nombre"}, "Nombre"), nombre), ...campos.map(c => c.w));
  if (tipo === "carpeta") {
    try {
      const sug = await api("/api/destinos/sugerencias"), ruta = campos.find(c => c.id === "ruta");
      if (sug.length && ruta) {
        const fm = campos.find(c => c.id === "formatos");
        ruta.w.append(T("div", "env-sug", T("small", "", "Carpetas sincronizadas detectadas (OneDrive / SharePoint):"),
          ...sug.map(s => btn(s.nombre, "sec env-sm", () => { ruta.inp.value = s.ruta; nombre.value ||= s.nombre;
            if (fm && s.formatos) fm.inp.querySelectorAll("input").forEach(c => c.checked = s.formatos.includes(c.value)); },
            {title: s.ruta}))));
      }
    } catch {}
  }
  const msg = T("p", "env-msg", ""); msg.setAttribute("role", "status");
  const ok = btn(existente ? "Guardar" : "Crear destino", "pri", async () => {
    if (!cuerpo.reportValidity()) return;
    const config = {};
    for (const c of campos) { const v = c.getv(); if (c.secreto && !v) continue; config[c.id] = v; }
    try {
      const r = existente ? await send("PATCH", "/api/destinos/" + existente.id, {nombre: nombre.value, config})
                          : await send("POST", "/api/destinos", {tipo, nombre: nombre.value, config});
      d.close(); toast("Destino guardado"); alGuardar && alGuardar(r);
    } catch (e) { msg.textContent = e.message; msg.className = "env-msg err"; }
  });
  cuerpo.addEventListener("submit", e => { e.preventDefault(); ok.click(); });
  cuerpo.append(msg);
  const d = dialogo((existente ? "Editar " : "Nuevo ") + def.nombre, cuerpo, [ok]);
  return d;
}

/* catálogo «+ Destino» */
function catalogo(ctx, alGuardar) {
  const usados = new Set(); const cont = T("div", "env-cat");
  for (const [g, tipos] of GRUPOS) {
    const ts = tipos.filter(t => ctx.cat.tipos[t] && !ctx.cat.tipos[t].interno); ts.forEach(t => usados.add(t));
    if (ts.length) cont.append(T("h3", "", g), ...(g === "Microsoft 365" ? [msCard()] : []), T("div", "env-cat-g", ...ts.map(t => btn(ctx.cat.tipos[t].nombre, "sec env-tipo", () => { d.close(); formDestino(ctx, t, null, alGuardar); }))));
  }
  const otros = Object.keys(ctx.cat.tipos).filter(t => !usados.has(t) && !ctx.cat.tipos[t].interno);
  if (otros.length) cont.append(T("h3", "", "Otros"), T("div", "env-cat-g", ...otros.map(t => btn(ctx.cat.tipos[t].nombre, "sec env-tipo", () => { d.close(); formDestino(ctx, t, null, alGuardar); }))));
  const d = dialogo("Añadir destino", cont);
}

/* ---------- presets ---------- */
function formPreset(ctx, p, alGuardar) {
  const ds = ctx.cat.destinos;
  if (!ds.length) { toast("Primero configura un destino", true); return; }
  const nombre = el("input", {id: "env-pn", value: p?.nombre || "", required: true});
  const dest = el("select", {id: "env-pd"}, ...ds.map(x => el("option", {value: x.id, textContent: x.nombre, selected: p?.destino === x.id})));
  const que = new Set(p?.que || ["resumen"]);
  const qs = T("div", "env-lista", ...ctx.cat.que.map(q => T("label", "env-chk", el("input", {type: "checkbox", value: q, checked: que.has(q)}), " " + (QL[q] || q))));
  const fs = new Set(p?.formatos || []);
  const fm = T("div", "env-lista", ...FMT_LOCAL.map(f => T("label", "env-chk", el("input", {type: "checkbox", value: f, checked: fs.has(f)}), " " + FN[f])));
  const ap = el("input", {type: "checkbox", checked: !!p?.solo_aprobados});
  const cuerpo = T("form", "env-form", T("div", "env-campo", el("label", {htmlFor: "env-pn"}, "Nombre del preset"), nombre),
    T("div", "env-campo", el("label", {htmlFor: "env-pd"}, "Destino"), dest),
    T("div", "env-campo", T("b", "", "Qué enviar"), qs), T("div", "env-campo", T("b", "", "Formatos (si el destino admite archivos)"), fm),
    T("label", "env-chk", ap, " Solo elementos aprobados"));
  const msg = T("p", "env-msg", "");
  const ok = btn("Guardar", "pri", async () => {
    if (!cuerpo.reportValidity()) return;
    const body = {nombre: nombre.value, destino: dest.value, que: [...qs.querySelectorAll("input:checked")].map(c => c.value),
      formatos: [...fm.querySelectorAll("input:checked")].map(c => c.value), solo_aprobados: ap.checked};
    try { p ? await send("PATCH", "/api/presets/" + p.id, body) : await send("POST", "/api/presets", body); d.close(); alGuardar(); }
    catch (e) { msg.textContent = e.message; msg.className = "env-msg err"; }
  });
  cuerpo.append(msg);
  const d = dialogo(p ? "Editar preset" : "Nuevo preset", cuerpo, [ok]);
}

/* ---------- recetas ---------- */
function describe(cu) {
  if (!cu || cu.tipo !== "programado") return "Al terminar un documento";
  return "Cada " + (CADA[cu.cada] || cu.cada) + (cu.cada === "semana" ? " " + DIAS[cu.dia_semana ?? 0] : cu.cada === "mes" ? " el día " + (cu.dia_mes ?? 1) : "") + " a las " + (cu.hora || "09:00");
}
function editorCuando(cu0) {
  const cu = {tipo: "al_terminar", cada: "semana", dia_semana: 0, dia_mes: 1, hora: "09:00", ...cu0};
  const mk = (id, lab, ctl) => T("div", "env-campo", el("label", {htmlFor: id}, lab), ctl);
  const tipo = el("select", {id: "env-ct"}, el("option", {value: "al_terminar", textContent: "Al terminar un documento"}), el("option", {value: "programado", textContent: "Programado"}));
  tipo.value = cu.tipo;
  const cada = el("select", {id: "env-cc"}, ...Object.entries(CADA).map(([k, v]) => el("option", {value: k, textContent: "Cada " + v})));
  cada.value = cu.cada;
  const ds = el("select", {id: "env-cs"}, ...DIAS.map((n, i) => el("option", {value: i, textContent: n}))); ds.value = cu.dia_semana;
  const dm = el("input", {id: "env-cm", type: "number", min: 1, max: 28, value: cu.dia_mes});
  const hr = el("input", {id: "env-ch", type: "time", value: cu.hora});
  const prog = T("div", "env-fila", mk("env-cc", "Frecuencia", cada), mk("env-cs", "Día de la semana", ds), mk("env-cm", "Día del mes", dm), mk("env-ch", "Hora", hr));
  const upd = () => { prog.hidden = tipo.value !== "programado"; ds.parentNode.hidden = cada.value !== "semana"; dm.parentNode.hidden = cada.value !== "mes"; };
  tipo.onchange = cada.onchange = upd; upd();
  return {w: T("div", "", mk("env-ct", "Cuándo", tipo), prog),
    get: () => tipo.value === "programado" ? {tipo: "programado", cada: cada.value, dia_semana: +ds.value, dia_mes: +dm.value, hora: hr.value} : {tipo: "al_terminar"}};
}
function formReceta(ctx, r, alGuardar) {
  const nombre = el("input", {id: "env-rn", value: r?.nombre || ""});
  const carp = el("input", {id: "env-rc", value: r?.cuando?.carpeta || "", placeholder: "Proyecto (carpeta)", autocomplete: "off"});
  const dl = el("datalist", {id: "env-rc-l"}); carp.setAttribute("list", "env-rc-l"); // proyectos existentes como sugerencias
  api("/api/carpetas").then(cs => dl.append(...cs.map(c => el("option", {value: c})))).catch(() => {});
  carp.addEventListener("focus", () => carp.isConnected && !dl.isConnected && carp.after(dl), {once: true});
  const cu = editorCuando(r?.cuando);
  const ps = new Set(r?.presets || []);
  const lp = T("div", "env-lista", ...ctx.presets.map(p => T("label", "env-chk", el("input", {type: "checkbox", value: p.id, checked: ps.has(p.id)}), " " + p.nombre)));
  if (!ctx.presets.length) lp.append(T("small", "", "Crea primero un preset."));
  const sn = el("input", {type: "checkbox", checked: r?.solo_nuevo ?? true});
  const cuerpo = T("form", "env-form", T("div", "env-campo", el("label", {htmlFor: "env-rn"}, "Nombre"), nombre),
    T("div", "env-campo", el("label", {htmlFor: "env-rc"}, "Proyecto"), carp), cu.w, T("div", "env-campo", T("b", "", "Qué presets enviar"), lp),
    T("label", "env-chk", sn, " Solo lo nuevo desde el último envío"));
  const msg = T("p", "env-msg", "");
  const ok = btn("Guardar", "pri", async () => {
    const body = {nombre: nombre.value, activa: r?.activa ?? true, cuando: {...cu.get(), carpeta: carp.value}, solo_nuevo: sn.checked,
      presets: [...lp.querySelectorAll("input:checked")].map(c => c.value)};
    try { r ? await send("PATCH", "/api/recetas/" + r.id, body) : await send("POST", "/api/recetas", body); d.close(); alGuardar(); }
    catch (e) { msg.textContent = e.message; msg.className = "env-msg err"; }
  });
  cuerpo.append(msg);
  const d = dialogo(r ? "Editar receta" : "Nueva receta", cuerpo, [ok]);
}

/* ---------- centro Enviar ---------- */
let tabEnv = "destinos";
const estado = new Map();  // id destino -> {ok, mensaje, aviso}
async function montar(raiz) {
  raiz.classList.add("env-root");
  const pintar = async () => {
    let ctx;
    try { ctx = await datos(); } catch (e) { raiz.replaceChildren(T("p", "err", e.message)); return; }
    const refrescar = () => pintar();
    const dc = ctx.cat.destinos.map(d => {
      const tp = ctx.cat.tipos[d.tipo], st = estado.get(d.id);
      const tls = d.config.verificar_tls === false || d.config.verificar_tls === "false";
      const pr = btn("Probar", "sec env-sm", async e => {
        e.target.disabled = true; e.target.textContent = "Probando…";
        try { estado.set(d.id, await send("POST", `/api/destinos/${d.id}/probar`)); } catch (x) { estado.set(d.id, {ok: false, mensaje: x.message}); }
        refrescar();
      });
      return T("div", "env-card card", T("div", "env-row", T("strong", "", d.nombre), T("span", "pill env-tipo-l", tp?.nombre || d.tipo), T("span", "grow")),
        T("p", "muted env-st" + (st ? (st.ok ? " env-ok" : " env-bad") : ""), st ? (st.ok ? "Correcto: " : "Error: ") + st.mensaje : "Sin probar"),
        ...(tls || st?.aviso ? [T("small", "env-tls", "Certificado TLS sin verificar")] : []),
        T("div", "env-row", pr, btn("Editar", "sec env-sm", () => formDestino(ctx, d.tipo, d, refrescar)),
          btn("Eliminar", "sec dng env-sm", async () => { if (!confirm(`¿Eliminar «${d.nombre}»?`)) return; try { await send("DELETE", "/api/destinos/" + d.id); refrescar(); } catch (e) { fail(e); } })));
    });
    const sDest = T("section", "env-sec", T("div", "env-row", T("h2", "", "Destinos"), T("span", "grow"), btn("+ Destino", "pri", () => catalogo(ctx, refrescar))),
      dc.length ? T("div", "env-grid", ...esc(dc)) : T("p", "muted", "Aún no hay destinos. Añade uno para enviar tareas, notas o archivos."));
    const sPre = T("section", "env-sec", T("div", "env-row", T("h2", "", "Presets"), T("span", "grow"), btn("+ Preset", "sec", () => formPreset(ctx, null, refrescar))),
      ctx.presets.length ? T("ul", "env-ul", ...esc(ctx.presets.map(p => T("li", "env-row", chip({nombre: p.nombre, fijado: p.fijado, titulo: p.fijado ? "Fijado en Enviar ▾" : "", onSelect: () => formPreset(ctx, p, refrescar),
          onMenu: a => menu(a, [[p.fijado ? "Quitar fijado" : "Fijar en Enviar ▾", async () => { await send("PATCH", "/api/presets/" + p.id, {fijado: !p.fijado}); refrescar(); }], ["Editar", () => formPreset(ctx, p, refrescar)],
            ["Eliminar", async () => { await send("DELETE", "/api/presets/" + p.id); refrescar(); }]])}),
        T("small", "env-sum", (p.que || []).map(q => QL[q] || q).join(", ") + " → " + (ctx.dest[p.destino]?.nombre || "?") + (p.solo_aprobados ? " · solo aprobados" : ""))))))  : T("p", "muted", "Un preset guarda destino + qué enviar + formatos."));
    const grupos = {};
    ctx.recetas.forEach(r => (grupos[r.cuando?.carpeta || "(Sin proyecto)"] ||= []).push(r));
    const sRec = T("section", "env-sec", T("div", "env-row", T("h2", "", "Recetas automáticas"), T("span", "grow"), btn("+ Receta", "sec", () => formReceta(ctx, null, refrescar))),
      ...Object.entries(grupos).map(([g, rs]) => T("div", "", T("h3", "", g), ...rs.map(r => {
        const tg = el("input", {type: "checkbox", checked: !!r.activa, onchange: async () => { try { await send("PATCH", "/api/recetas/" + r.id, {activa: tg.checked}); } catch (e) { tg.checked = !tg.checked; fail(e); } }});
        return T("div", "env-card card", T("div", "env-row", T("label", "env-chk", tg, " "), T("strong", "", r.nombre || "Receta"), T("span", "grow"),
          btn("Enviar ahora", "sec env-sm", async e => { e.target.disabled = true; try { const x = await send("POST", `/api/recetas/${r.id}/ahora`); toast(`Enviado (${x.length} envío${x.length === 1 ? "" : "s"})`); refrescar(); } catch (x) { fail(x); e.target.disabled = false; } }),
          btn("Editar", "sec env-sm", () => formReceta(ctx, r, refrescar)),
          btn("Eliminar", "sec dng env-sm", async () => { if (confirm("¿Eliminar la receta?")) { try { await send("DELETE", "/api/recetas/" + r.id); refrescar(); } catch (e) { fail(e); } } })),
          T("p", "muted", describe(r.cuando) + (r.proximo_iso ? " · Próximo: " + r.proximo_iso.replace("T", " ") : "") + (r.atrasado ? " · atrasado" : "") + (r.solo_nuevo ? " · solo lo nuevo" : "")));
      }))), !ctx.recetas.length ? T("p", "muted", "Sin recetas. Una receta envía automáticamente al terminar un documento o en un horario.") : "");
    const sHis = T("section", "env-sec", T("h2", "", "Historial"));
    let hay = false;
    try {
      const h = await api("/api/envios?limit=30"); hay = h.length > 0;
      sHis.append(h.length ? T("ul", "env-ul", ...h.map(e => {
        const links = [...(e.enlaces || []), ...(e.items || []).map(i => i.url)].filter(u => /^https?:\/\//i.test(u || ""));
        const errs = (e.items || []).map(i => i.error).filter(Boolean);
        return T("li", "env-hist", T("div", "env-row", T("span", "pill " + (e.estado === "ok" ? "env-ok" : "env-bad"), e.estado), T("strong", "", e.nombre || ctx.dest[e.destino]?.nombre || e.destino || "Envío"),
          T("span", "muted", e.fecha || e.ts ? new Date((e.ts || Date.parse(e.fecha) / 1000) * (e.ts ? 1000 : 1000)).toLocaleString("es") : ""), T("span", "grow"),
          ...(e.reintentable ? [btn("Reintentar", "sec env-sm", async b => { b.target.disabled = true; try { await send("POST", `/api/envios/${e.id}/reintentar`); toast("Reintentado"); refrescar(); } catch (x) { fail(x); b.target.disabled = false; } })] : [])),
          ...[...new Set(links)].map(u => el("a", {href: u, target: "_blank", rel: "noopener", textContent: u.length > 60 ? u.slice(0, 57) + "…" : u, className: "env-link"})),
          ...errs.map(x => T("small", "env-bad", x)), e.error ? T("small", "env-bad", e.error) : "");
      })) : T("p", "muted", "Todavía no se ha enviado nada."));
    } catch (e) { sHis.append(T("p", "err", e.message)); }
    const vacio = !ctx.cat.destinos.length && !ctx.presets.length && !ctx.recetas.length && !hay;
    if (vacio) {  // estado vacío que enseña: tres destinos típicos + catálogo
      const sug = ["carpeta", "correo", "slack"].filter(t => ctx.cat.tipos[t]);
      raiz.replaceChildren(T("section", "env-sec env-vacio", T("h2", "", "Conecta un destino"),
        T("p", "muted", "Envía tareas, notas y archivos a donde ya trabajas. Elige uno para empezar; luego podrás crear presets y recetas automáticas."),
        T("div", "env-grid env-grid3", ...esc(sug.map(t => el("button", {type: "button", className: "env-card card env-tipo-c", onclick: () => formDestino(ctx, t, null, refrescar)}, ico(t), T("strong", "", ctx.cat.tipos[t].nombre), T("small", "env-estado", "Sin conectar"), T("small", "muted", {carpeta: "Archivos en una carpeta de este equipo", correo: "Documentos adjuntos por correo", slack: "Mensajes a un canal"}[t]))))),
        el("button", {type: "button", className: "env-otro", onclick: () => catalogo(ctx, refrescar)}, "+ Otro destino"),
        T("div", "env-ej", T("h3", "", "Recetas de ejemplo"), ...[["Resumen semanal al equipo", "Cada lunes a las 09:00 · Resumen → Correo"], ["Tareas nuevas a tu gestor", "Al terminar un documento · Tareas → Jira / Planner"]].map(([n, d]) =>
          T("div", "env-card card", ico("receta"), T("div", "", T("strong", "", n), T("small", "muted", d)), T("span", "grow"), T("span", "env-etq", "Ejemplo"))))));
      return;
    }
    const TABS = [["destinos", "Destinos", sDest, ctx.cat.destinos.length], ["presets", "Presets", sPre, ctx.presets.length], ["recetas", "Recetas", sRec, ctx.recetas.length], ["historial", "Historial", sHis, 0]];
    if (!TABS.some(t => t[0] === tabEnv)) tabEnv = "destinos";
    const tl = T("div", "env-tabs"); tl.setAttribute("role", "tablist"); tl.setAttribute("aria-label", "Enviar");
    TABS.forEach(([k, t, , n]) => tl.append(el("button", {type: "button", role: "tab", id: "env-t-" + k, className: "env-tab", "aria-selected": k === tabEnv, tabIndex: k === tabEnv ? 0 : -1,
      onclick: () => { tabEnv = k; pintar(); }, onkeydown: e => { const d = {ArrowRight: 1, ArrowLeft: -1}[e.key]; if (d) { tabEnv = TABS[(TABS.findIndex(x => x[0] === tabEnv) + d + 4) % 4][0]; pintar().then(() => document.getElementById("env-t-" + tabEnv)?.focus()); } }},
      t, ...(n ? [T("span", "env-n", String(n))] : []))));
    const sec = TABS.find(t => t[0] === tabEnv)[2]; sec.setAttribute("role", "tabpanel"); sec.setAttribute("aria-labelledby", "env-t-" + tabEnv);
    raiz.replaceChildren(tl, sec);
  };
  await pintar();
}

/* ---------- checklist del plan ---------- */
async function checklist(raiz, {plan, carpeta, onChange} = {}) {
  raiz.classList.add("env-root");
  plan ||= {carpeta, salidas: []}; plan.salidas ||= [];
  let ctx;
  try { ctx = await datos(); } catch (e) { raiz.replaceChildren(T("p", "err", e.message)); return; }
  const S = {};
  const desde = s => ({on: true, sel: s.como === "documento" ? "doc" : s.preset ? "p:" + s.preset : s.destino && ctx.dest[s.destino]?.tipo === "carpeta" && s.formatos ? "local" : s.destino ? "d:" + s.destino : "doc",
    nombre: s.nombre || "", formatos: s.formatos || ["pdf"], destino: s.destino});
  for (const s of plan.salidas) S[s.que] = desde(s);
  let objs = []; try { objs = await api("/api/objetivos"); } catch {}
  const jira = ctx.cat.destinos.find(d => ["jira", "ms_planner"].includes(d.tipo));
  if (jira) objs.splice(objs.findIndex(o => !o.serie) < 0 ? objs.length : objs.findIndex(o => !o.serie), 0,
    {id: "serie:jira", nombre: "Para " + jira.nombre + "…", serie: true, plan: {salidas: [{que: "tareas", como: "destino", destino: jira.id}]}});
  const pre = {sel: null, abierto: false, cambiados: new Set()}, OU = "env.objUlt";
  const pinS = () => new Set(ls(FS, []));
  const fijado = o => o.serie ? pinS().has(o.id) : !!o.fijado;
  const aplicar = o => {
    pre.sel = o.id; pre.abierto = false; localStorage.setItem(OU, JSON.stringify(o.id)); pre.cambiados = new Set([...Object.keys(S).filter(q => S[q].on), ...o.plan.salidas.map(s => s.que)]);
    for (const q of Object.keys(S)) S[q].on = false;
    for (const s of o.plan.salidas) S[s.que] = desde(s);
    if (o.plan.solo_buscable) plan.solo_buscable = true; else delete plan.solo_buscable;
    if (o.plantilla) plan.plantilla = o.plantilla; else delete plan.plantilla;
    emitir(); pintar();
  };
  const planActual = () => ({salidas: plan.salidas.map(({configurar, ...r}) => r), ...(plan.plantilla ? {plantilla: plan.plantilla} : {}), ...(plan.solo_buscable ? {solo_buscable: true} : {})});
  const recargar = async () => { try { objs = await api("/api/objetivos"); } catch {} pintar(); };
  const nombrar = (titulo, ini, fn) => {
    const n = el("input", {id: "env-on", value: ini}), m = T("p", "env-msg", "");
    const ok = btn("Guardar", "pri", async () => { if (!n.value.trim()) return; try { await fn(n.value.trim()); salir(d); recargar(); toast("Preset guardado"); } catch (e) { m.textContent = e.message; m.className = "env-msg err"; } });
    const d = dialogo(titulo, T("div", "env-form", T("div", "env-campo", el("label", {htmlFor: "env-on"}, "Nombre"), n), m), [ok]);
    n.focus(); n.select();
  };
  const planDe = o => ({...o.plan, salidas: o.plan.salidas.map(({configurar, ...r}) => r)});
  const items = o => {
    const dup = () => nombrar("Duplicar para editar", o.nombre + " (copia)", n => send("POST", "/api/objetivos", {nombre: n, plan: planDe(o), plantilla: o.plantilla}));
    const fij = [fijado(o) ? "Quitar fijado" : "Fijar", async () => { if (o.serie) { const s = pinS(); s.has(o.id) ? s.delete(o.id) : s.add(o.id); localStorage.setItem(FS, JSON.stringify([...s])); } else { await send("PATCH", "/api/objetivos/" + o.id, {fijado: !o.fijado}); o.fijado = !o.fijado; } pintar(); }];
    return o.serie ? [fij, ["Duplicar para editar", dup]] : [fij, ["Renombrar", () => nombrar("Renombrar preset", o.nombre, async n => send("PATCH", "/api/objetivos/" + o.id, {nombre: n}))], ["Duplicar", dup],
      ["Eliminar", async () => { await send("DELETE", "/api/objetivos/" + o.id); if (pre.sel === o.id) pre.sel = null; objs = objs.filter(x => x.id !== o.id); pintar(); }]];
  };
  const barra = () => {
    const orden = [...objs].sort((a, b) => fijado(b) - fijado(a)), ult = ls(OU, null);
    const vis = ["serie:reunion", "serie:resumen", "serie:buscable"].map(id => orden.find(o => o.id === id)).filter(Boolean);
    for (const o of orden) if (vis.length < 3 && !vis.includes(o)) vis.push(o);
    const extra = orden.find(o => o.id === pre.sel) || orden.find(o => o.id === ult);
    if (extra && !vis.includes(extra)) vis.splice(2, 1, extra);  // 3 chips máx.: el elegido/último ocupa el 3.º hueco
    const mas = orden.filter(o => !vis.includes(o));
    const ch = o => chip({nombre: o.nombre, fijado: fijado(o), serie: o.serie, activo: pre.sel === o.id, ultimo: o.id === ult, titulo: resumen(o.plan, ctx), onSelect: () => aplicar(o), onMenu: a => menu(a, items(o))});
    const sum = pre.sel && !raiz.closest("dialog")?.querySelector("#an-res") ? resumen(planActual(), ctx) : "";  // en Añadir el pie (#an-res) ya dice lo mismo: un solo resumen
    return T("div", "env-pres", T("div", "env-chips", ...esc(vis.map(ch)),
      T("span", "env-mas", btn("Más ▾", "sec env-sm", e => menu(e.currentTarget, [...mas.map(o => [o.nombre + (fijado(o) ? " ★" : ""), () => aplicar(o)]),
        ["Guardar lo actual como preset…", () => nombrar("Guardar como preset", "", n => send("POST", "/api/objetivos", {nombre: n, plan: planActual(), plantilla: plan.plantilla}))]]), {"aria-haspopup": "menu"}))),
      ...(sum ? [T("small", "env-sum", sum)] : []));
  };
  const rep = {on: !!plan.repetir, cada: "semana", dia_semana: 0, hora: "09:00", ...plan.repetir};
  const carp = () => ctx.cat.destinos.find(d => d.tipo === "carpeta");
  const salida = (q, r) => {
    const o = {que: q};
    if (r.sel === "doc") o.como = "documento";
    else if (r.sel === "local") Object.assign(o, {como: "destino", destino: carp()?.id, formatos: r.formatos});
    else Object.assign(o, {como: "destino"}, r.sel.startsWith("p:") ? {preset: r.sel.slice(2)} : {destino: r.sel.slice(2)});
    if (r.nombre) o.nombre = r.nombre;
    return o;
  };
  const emitir = () => {
    plan.salidas = ORDEN.filter(q => S[q]?.on).map(q => salida(q, S[q]));
    if (rep.on) plan.repetir = {cada: rep.cada, dia_semana: rep.dia_semana, dia_mes: rep.dia_mes || 1, hora: rep.hora}; else delete plan.repetir;
    onChange && onChange(plan);
  };
  const pintar = () => {
    const ORD2 = ORDEN.filter(q => q === "documento" || ctx.cat.que.includes(q));
    const filas = ORD2.map(q => {
      const r = S[q] ||= {on: false, sel: "doc", nombre: "", formatos: ["pdf"]};
      const cb = el("input", {type: "checkbox", id: "env-cl-" + q, checked: r.on, onchange: () => { r.on = cb.checked; pre.sel = null; pre.abierto = true; emitir(); pintar(); }});
      const sel = el("select", {"aria-label": "Destino de " + (QL[q] || q), disabled: !r.on, onchange: () => {
        if (sel.value === "+") { sel.value = r.sel; catalogo(ctx, async () => { ctx = await datos(); pintar(); }); return; }
        r.sel = sel.value; if (r.sel === "local" && !carp()) { r.sel = "doc"; catalogo(ctx, async () => { ctx = await datos(); pintar(); }); }
        emitir(); pintar(); }},
        el("option", {value: "doc", textContent: "Documento en el proyecto"}), el("option", {value: "local", textContent: "Archivo local"}),
        ...ctx.presets.map(p => el("option", {value: "p:" + p.id, textContent: "Preset: " + p.nombre})),
        ...ctx.cat.destinos.map(d => el("option", {value: "d:" + d.id, textContent: d.nombre})),
        el("option", {value: "+", textContent: "+ configurar…"}));
      sel.value = r.sel;
      const nm = el("input", {type: "text", placeholder: "Nombre (opcional)", "aria-label": "Nombre de " + (QL[q] || q), value: r.nombre, disabled: !r.on, oninput: () => { r.nombre = nm.value; emitir(); }});
      const fila = T("div", "env-cl-fila" + (r.on ? " on" : ""), T("label", "env-chk env-cl-q", cb, " " + (QL[q] || q)), sel, nm);
      if (r.on && r.sel === "local") fila.append(T("div", "env-chips", ...FMT_LOCAL.map(f => el("button", {type: "button", className: "env-chip", "aria-pressed": r.formatos.includes(f), textContent: FN[f],
        onclick: () => { r.formatos = r.formatos.includes(f) ? r.formatos.filter(x => x !== f) : [...r.formatos, f]; emitir(); pintar(); }}))));
      return fila;
    });
    const rc = el("input", {type: "checkbox", id: "env-rep", checked: rep.on, onchange: () => { rep.on = rc.checked; emitir(); pintar(); }});
    const cada = el("select", {"aria-label": "Frecuencia", disabled: !rep.on, onchange: () => { rep.cada = cada.value; emitir(); pintar(); }}, ...Object.entries(CADA).map(([k, v]) => el("option", {value: k, textContent: v})));
    cada.value = rep.cada;
    const ds = el("select", {"aria-label": "Día de la semana", disabled: !rep.on, onchange: () => { rep.dia_semana = +ds.value; emitir(); }}, ...DIAS.map((n, i) => el("option", {value: i, textContent: n})));
    ds.value = rep.dia_semana;
    const hr = el("input", {type: "time", "aria-label": "Hora", value: rep.hora, disabled: !rep.on, onchange: () => { rep.hora = hr.value; emitir(); }});
    const fr = T("div", "env-cl-rep", T("label", "env-chk", rc, " Repetir cada"), cada, ...(rep.cada === "semana" ? [ds] : []), T("span", "", "a las"), hr);
    const gr = btn("Guardar como receta", "sec", () => {
      const n = el("input", {id: "env-gr", value: (carpeta || plan.carpeta || "") + " · envío"});
      const cu = editorCuando(rep.on ? {tipo: "programado", ...rep} : {});
      const m = T("p", "env-msg", "");
      const ok = btn("Guardar", "pri", async () => {
        try { await send("POST", "/api/recetas", {nombre: n.value, activa: true, solo_nuevo: true, cuando: {...cu.get(), carpeta: carpeta || plan.carpeta || ""}, plan: {carpeta: carpeta || plan.carpeta, salidas: plan.salidas}}); d.close(); toast("Receta guardada"); }
        catch (e) { m.textContent = e.message; m.className = "env-msg err"; }
      });
      const d = dialogo("Guardar como receta", T("div", "env-form", T("div", "env-campo", el("label", {htmlFor: "env-gr"}, "Nombre"), n), cu.w, m), [ok]);
    });
    const flash = pre.cambiados; pre.cambiados = new Set();
    filas.forEach((f, i) => { if (flash.has(ORD2[i])) f.classList.add("env-flash"); });
    // con preset elegido el resumen ya va bajo los chips: en «Personalizar» solo si el plan es a medida
    const det = el("details", {className: "env-pers", open: pre.abierto, ontoggle: () => { pre.abierto = det.open; }}, el("summary", {}, "Personalizar", ...(plan.salidas.length && !pre.sel ? [T("small", "env-sum", " · " + resumen(planActual(), ctx))] : [])), T("div", "env-checklist", ...filas, fr, T("div", "env-row", gr)));
    raiz.replaceChildren(barra(), det);
  };
  // recuerda el último objetivo y lo preselecciona si el plan viene vacío (no con callbacks vacíos: ajustes por defecto de un proyecto)
  // preset marcado al abrir: el último usado → si el proyecto trae plan, el preset que coincide → «Acta de reunión» (el tipo por defecto)
  const u = ls(OU, null), uo = u && objs.find(x => x.id === u), clave = ss => JSON.stringify(ss.map(s => s.que + "|" + s.como).sort());
  if (onChange && onChange.length && !plan.solo_buscable) {
    if (!plan.salidas.length) { const o = uo || objs.find(x => x.id === "serie:reunion"); if (o) return aplicar(o); }
    else pre.sel = objs.find(x => !x.plan.solo_buscable && clave(x.plan.salidas) === clave(plan.salidas))?.id ?? null;
  }
  pintar();
}

/* ---------- envío rápido (Enviar ▾) ---------- */
function itemsEnvio(ctx) {
  const ult = ls("env.ultimo", null);
  const items = [...ctx.presets.map(p => ({k: "p:" + p.id, t: p.nombre, s: "→ " + (ctx.dest[p.destino]?.nombre || ""), body: {preset: p.id}})),
    ...ctx.cat.destinos.map(d => ({k: "d:" + d.id, t: d.nombre, s: "documento completo", body: {destino: d.id, que: ["documento"]}}))]
    .sort((a, b) => (b.k === ult) - (a.k === ult));
  const pin = new Set(ctx.presets.filter(p => p.fijado).map(p => "p:" + p.id));
  items.sort((a, b) => pin.has(b.k) - pin.has(a.k));
  return {items, pin, ult};
}
async function envia(it, sel) {
  localStorage.setItem("env.ultimo", JSON.stringify(it.k));
  if (sel.docs) {  // varios documentos: un envío por documento
    let ok = 0, err = ""; for (const x of sel.docs) { const r = await send("POST", "/api/enviar", {...it.body, doc: x}); if (r.estado === "ok") ok++; else err ||= r.estado + (r.items?.find(y => y.error)?.error ? " — " + r.items.find(y => y.error).error : ""); }
    toast("Enviados " + ok + " de " + sel.docs.length + " a " + it.t + (sel.omitidos ? " · " + sel.omitidos + " solo buscable(s) sin enviar" : "") + (err ? " · " + err : ""), !!err);
    return;
  }
  const r = await send("POST", "/api/enviar", {...it.body, ...sel});
  toast(r.estado === "ok" ? "Enviado a " + it.t : "Envío: " + r.estado + (r.items?.find(x => x.error)?.error ? " — " + r.items.find(x => x.error).error : ""), r.estado !== "ok");
}
async function enviar(sel) {
  let ctx;
  try { ctx = await datos(); } catch (e) { return fail(e); }
  const {items, pin, ult} = itemsEnvio(ctx);
  const lista = T("ul", "env-menu", ...items.map(it => T("li", "", btn(it.t + " ", "sec env-menu-i", async e => {
    const b = e.currentTarget; b.disabled = true;
    try { await envia(it, sel); salir(d); } catch (x) { fail(x); b.disabled = false; }
  }, {}))));
  items.forEach((it, i) => lista.children[i].firstChild.append(T("small", "", (pin.has(it.k) ? "★ " : "") + it.s + (it.k === ult ? " · último usado" : ""))));
  const d = dialogo("Enviar a…", items.length ? lista : T("p", "muted", "No hay destinos configurados. Ve a Enviar para añadir uno."));
  lista.querySelector("button")?.focus();
}
/* Botón dividido: principal = primer ítem (fijado > último usado; sin ítems abre el diálogo), flecha = menú. sel = {c} | {doc}. */
function split(host, sel, {label = "Enviar", cls = "pri"} = {}) {
  const g = T("span", "env-split"), main = btn(label, cls + " env-sp-m", async () => {
    main.disabled = true;
    try { const {items} = itemsEnvio(await datos()); if (!items.length) return enviar(sel); await envia(items[0], sel); } catch (x) { fail(x); } finally { main.disabled = false; }
  }), arrow = btn("▾", cls + " env-sp-a", async e => {
    try {
      const {items, pin} = itemsEnvio(await datos());
      menu(e.currentTarget, [...items.map(it => [(pin.has(it.k) ? "★ " : "") + it.t + " " + it.s, () => envia(it, sel)]), ["Más opciones…", () => enviar(sel)]]);
    } catch (x) { fail(x); }
  }, {"aria-haspopup": "menu", "aria-label": "Elegir a dónde enviar", title: "Elegir a dónde enviar"});
  main.title = "Enviar al destino fijado o al último usado";
  datos().then(ctx => { const it = itemsEnvio(ctx).items[0]; if (it) main.title = "Enviar a " + it.t; }).catch(() => {});
  g.append(main, arrow); (host || document.body).append(g);
  return g;
}

window.Enviar = {montar, checklist, enviar, split, outlook, chip, menu, cabecera, presetsObjetivo: true};
})();
