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
function toast(msg, err) {
  live ||= document.body.appendChild(el("div", {className: "env-toast", role: "status", "aria-live": "polite"}));
  live.textContent = msg; live.classList.toggle("env-bad", !!err); live.hidden = false;
  clearTimeout(live._t); live._t = setTimeout(() => live.hidden = true, 5000);
}
const fail = e => toast(e.message || String(e), true);

function dialogo(titulo, cuerpo, acciones = []) {
  const d = el("dialog", {className: "env-dlg", "aria-label": titulo});
  const cerrar = btn("Cerrar", "sec", () => d.close());
  d.append(T("h2", "", titulo), cuerpo, T("div", "row env-acc", ...acciones, cerrar));
  d.addEventListener("close", () => d.remove());
  document.body.append(d); d.showModal();
  return d;
}

async function datos() {
  const [cat, presets, recetas] = await Promise.all([api("/api/destinos"), api("/api/presets"), api("/api/recetas")]);
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
      dc.length ? T("div", "env-grid", ...dc) : T("p", "muted", "Aún no hay destinos. Añade uno para enviar tareas, notas o archivos."));
    const sPre = T("section", "env-sec", T("div", "env-row", T("h2", "", "Presets"), T("span", "grow"), btn("+ Preset", "sec", () => formPreset(ctx, null, refrescar))),
      ctx.presets.length ? T("ul", "env-ul", ...ctx.presets.map(p => T("li", "env-row", T("span", "", T("strong", "", p.nombre), " → " + (ctx.dest[p.destino]?.nombre || "?") + " · " + (p.que || []).map(q => QL[q] || q).join(", ")), T("span", "grow"),
        btn("Editar", "sec env-sm", () => formPreset(ctx, p, refrescar)),
        btn("Eliminar", "sec dng env-sm", async () => { try { await send("DELETE", "/api/presets/" + p.id); refrescar(); } catch (e) { fail(e); } })))) : T("p", "muted", "Un preset guarda destino + qué enviar + formatos."));
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
    try {
      const h = await api("/api/envios?limit=30");
      sHis.append(h.length ? T("ul", "env-ul", ...h.map(e => {
        const links = [...(e.enlaces || []), ...(e.items || []).map(i => i.url).filter(Boolean)];
        const errs = (e.items || []).map(i => i.error).filter(Boolean);
        return T("li", "env-hist", T("div", "env-row", T("span", "pill " + (e.estado === "ok" ? "env-ok" : "env-bad"), e.estado), T("strong", "", e.nombre || ctx.dest[e.destino]?.nombre || e.destino || "Envío"),
          T("span", "muted", e.fecha || e.ts ? new Date((e.ts || Date.parse(e.fecha) / 1000) * (e.ts ? 1000 : 1000)).toLocaleString("es") : ""), T("span", "grow"),
          ...(e.reintentable ? [btn("Reintentar", "sec env-sm", async b => { b.target.disabled = true; try { await send("POST", `/api/envios/${e.id}/reintentar`); toast("Reintentado"); refrescar(); } catch (x) { fail(x); b.target.disabled = false; } })] : [])),
          ...[...new Set(links)].map(u => el("a", {href: u, target: "_blank", rel: "noopener", textContent: u.length > 60 ? u.slice(0, 57) + "…" : u, className: "env-link"})),
          ...errs.map(x => T("small", "env-bad", x)), e.error ? T("small", "env-bad", e.error) : "");
      })) : T("p", "muted", "Todavía no se ha enviado nada."));
    } catch (e) { sHis.append(T("p", "err", e.message)); }
    raiz.replaceChildren(sDest, sPre, sRec, sHis);
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
  for (const s of plan.salidas) S[s.que] = {on: true, sel: s.como === "documento" ? "doc" : s.preset ? "p:" + s.preset : s.destino && ctx.dest[s.destino]?.tipo === "carpeta" && s.formatos ? "local" : s.destino ? "d:" + s.destino : "doc",
    nombre: s.nombre || "", formatos: s.formatos || ["pdf"], destino: s.destino};
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
    const filas = ORDEN.filter(q => q === "documento" || ctx.cat.que.includes(q)).map(q => {
      const r = S[q] ||= {on: false, sel: "doc", nombre: "", formatos: ["pdf"]};
      const cb = el("input", {type: "checkbox", id: "env-cl-" + q, checked: r.on, onchange: () => { r.on = cb.checked; emitir(); pintar(); }});
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
    raiz.replaceChildren(T("div", "env-checklist", ...filas, fr, T("div", "env-row", gr)));
  };
  pintar();
}

/* ---------- envío rápido (Enviar ▾) ---------- */
async function enviar(sel) {
  let ctx;
  try { ctx = await datos(); } catch (e) { return fail(e); }
  const ult = ls("env.ultimo", null);
  const items = [...ctx.presets.map(p => ({k: "p:" + p.id, t: p.nombre, s: "→ " + (ctx.dest[p.destino]?.nombre || ""), body: {preset: p.id}})),
    ...ctx.cat.destinos.map(d => ({k: "d:" + d.id, t: d.nombre, s: "documento completo", body: {destino: d.id, que: ["documento"]}}))]
    .sort((a, b) => (b.k === ult) - (a.k === ult));
  const lista = T("ul", "env-menu", ...items.map((it, i) => T("li", "", btn(it.t + " ", "sec env-menu-i", async e => {
    e.currentTarget.disabled = true; localStorage.setItem("env.ultimo", JSON.stringify(it.k));
    try { const r = await send("POST", "/api/enviar", {...it.body, ...sel}); d.close(); toast(r.estado === "ok" ? "Enviado a " + it.t : "Envío: " + r.estado + (r.items?.find(x => x.error)?.error ? " — " + r.items.find(x => x.error).error : ""), r.estado !== "ok"); }
    catch (x) { fail(x); e.currentTarget && (e.currentTarget.disabled = false); }
  }, {}), ...(it.s ? [] : []))));
  items.forEach((it, i) => lista.children[i].firstChild.append(T("small", "", it.s + (it.k === ult ? " · último usado" : ""))));
  const d = dialogo("Enviar a…", items.length ? lista : T("p", "muted", "No hay destinos configurados. Ve a Enviar para añadir uno."));
  lista.querySelector("button")?.focus();
}

window.Enviar = {montar, checklist, enviar, outlook};
})();
