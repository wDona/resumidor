// Vista «interesados» (F4): matriz poder/interés con chips arrastrables + tabla editable + ficha + fusión + exportación.
// IA primero: los interesados llegan «propuesto» (nombre, rol, organización + citas); poder/interés NUNCA se infieren -> «Sin clasificar».
// Registra FVISTAS.interesados = (c, e) => [nodos]  (carpeta.js se carga después: se registra en DOMContentLoaded).
(() => {
  const ACTS = ["a favor", "neutral", "en contra", "desconocida"];  // campo informativo de tabla/ficha: no afecta a la matriz
  const QS = {
    gc: {t: "Gestionar de cerca", s: "Alto poder, alto interés: implicar y consultar de forma activa"},
    ms: {t: "Mantener satisfecho", s: "Alto poder, bajo interés: informar de lo esencial y evitar sorpresas"},
    mi: {t: "Mantener informado", s: "Bajo poder, alto interés: comunicación regular, escuchar sus aportes"},
    mon: {t: "Monitorizar", s: "Bajo poder, bajo interés: seguimiento mínimo"},
    lim: {t: "En el límite / entre zonas", s: "Poder o interés exactamente en el centro de su eje: está sobre la línea divisoria entre dos zonas y no se asigna a ningún cuadrante"},
    sin: {t: "Sin clasificar", s: "Falta poder o interés (la IA no los infiere)"},
  };
  // huecos por eje (filas = poder, columnas = interés): escala del proyecto en el servidor (GET/POST /api/reg/matriz, 3..10 cada uno);
  // el resto del aspecto, en localStorage por carpeta
  const NMAX = 10, NDEF = 6, MXDEF = {h: 420, gap: 6, len: 0, tam: "M", grid: true, etq: true, reesc: true, cuad: false};
  let NP = NDEF, NI = NDEF;  // niveles de la vista abierta (una a la vez)
  // valores en pasos de 0,5: entero = centro de una casilla; x,5 = la línea entre la casilla x y la x+1
  const num = (v, n) => (v === "" || v == null || isNaN(Number(v)) ? null : Math.min(n, Math.max(1, Math.round(Number(v) * 2) / 2)));
  const pw = v => num(v, NP), iw = v => num(v, NI), fmt = v => String(v).replace(".", ",");
  // Regla simétrica por eje: la cruz está en el centro exacto (N+1)/2. Por encima = alto, por debajo = bajo, igual = sobre la línea
  // divisoria («entre zonas», sin cuadrante). Los 4 cuadrantes miden lo mismo.
  const REGLA = "La cruz está en el centro exacto de cada eje. Por encima del centro = alto; por debajo = bajo. Valores intermedios (x,5) = en la línea entre dos casillas. Poder o interés exactamente en el centro = entre dos zonas (sin cuadrante).";
  const lado = (v, n) => { const m = (n + 1) / 2; return v > m ? 1 : v < m ? -1 : 0; };
  const quad = (p, i) => { p = pw(p); i = iw(i); if (p == null || i == null) return "sin"; const a = lado(p, NP), b = lado(i, NI); return !a || !b ? "lim" : a > 0 ? (b > 0 ? "gc" : "ms") : (b > 0 ? "mi" : "mon"); };
  const posTxt = (p, i) => "Poder " + fmt(p) + " · Interés " + fmt(i) + " (" + (quad(p, i) === "lim" ? "entre zonas" : QS[quad(p, i)].t) + ")";
  // imán: a menos de un 30 % de casilla de una línea, se pega a la línea (x,5); si no, al centro de la casilla
  const snap = (v, n) => { const u = v - .5, c = Math.floor(u), t = u - c; return Math.min(n, Math.max(1, t < .3 ? c + .5 : t > .7 ? c + 1.5 : c + 1)); };
  const qOf = it => quad(it.campos?.poder, it.campos?.interes);
  const toks = s => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9 ]+/g, " ").trim().split(/\s+/).filter(Boolean);
  // «Ana» ~ «Ana G.» ~ «Ana García»: todas las palabras del nombre corto están (o son inicial) en el largo
  const parecidos = (a, b) => {
    let s = toks(a), l = toks(b); if (!s.length || !l.length) return false;
    if (s.length > l.length) [s, l] = [l, s];
    const ok = (t, u) => t === u || (t.length === 1 && u.startsWith(t)) || (u.length === 1 && t.startsWith(u));
    return s.every(t => l.some(u => ok(t, u))) && s.some(t => t.length > 1 && l.includes(t));
  };
  const igual = (a, b) => toks(a).join(" ") === toks(b).join(" ");
  const sugerida = it => ["gc", "ms", "mi", "mon"].includes(qOf(it)) ? QS[qOf(it)].s : "";
  const tip = it => [it.titulo, [it.campos?.rol, it.campos?.organizacion].filter(Boolean).join(" · "),
    qOf(it) === "sin" ? "Sin clasificar" : posTxt(pw(it.campos.poder), iw(it.campos.interes)), it.revision === "propuesto" ? "Propuesto por la IA: pendiente de revisar" : ""].filter(Boolean).join("\n");
  const COLS = [["titulo", "Nombre", "t"], ["campos.rol", "Rol", "t"], ["campos.organizacion", "Organización", "t"], ["campos.poder", "Poder", "n"], ["campos.interes", "Interés", "n"],
    ["campos.actitud", "Actitud", "s"], ["campos.estrategia", "Estrategia", "t"], ["campos.canal", "Canal", "t"], ["detalle", "Notas", "a"]];
  const val = (it, k) => k.startsWith("campos.") ? (it.campos || {})[k.slice(7)] ?? "" : it[k] ?? "";

  async function vista(c, e) {
    const S = {all: [], ints: [], sel: new Set(), f: {cuad: "", rev: ""}, sort: {k: "", d: 1}, open: null, hist: null, soloAprob: false, foco: null, ign: new Set(lsGet("int-ign-" + c, [])), cfg: {...MXDEF, ...lsGet("int-mx-" + c, {})}};
    const okN = n => Math.min(NMAX, Math.max(3, Number(n) || NDEF));
    const leeN = async () => { try { const r = await api("/api/reg/matriz?c=" + encodeURIComponent(c)); NP = okN(r.niveles_poder ?? r.niveles); NI = okN(r.niveles_interes ?? r.niveles); } catch { NP = NI = NDEF; } };
    await leeN();
    let seq = 0;
    const raiz = el("div", {className: "int"});
    const zHead = el("div", {className: "int-head"}), zBan = el("div"), zBar = el("div", {className: "int-bar"}), zAcc = el("div", {className: "reg-acc"});
    const zMx = el("section", {className: "int-col int-mx-w"}), zTb = el("section", {className: "int-col int-tb-w"}), zFi = el("aside", {className: "int-ficha", hidden: true});
    const zMxH = el("div", {className: "sec-h"}), zMxB = el("div");
    zMx.append(zMxH, el("p", {className: "muted int-leg", textContent: "Borde discontinuo = propuesto por la IA, pendiente de revisar"}), zMxB);
    raiz.append(zHead, zBan, zBar, zAcc, el("div", {className: "int-main"}, zMx, zTb), zFi);
    const cambio = () => { typeof fCargaReg === "function" && fCargaReg(c, e && e.tipo); };
    const aviso_ = m => aviso(m);
    const err = x => aviso_(x.message || String(x));
    const PATCH = (id, cambios) => api("/api/reg/" + encodeURIComponent(id), {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({c, cambios})});

    async function cargar() {
      const n = ++seq;
      try {
        const r = await api("/api/reg?" + new URLSearchParams({c}));
        let ints = r.items.filter(i => i.tipo === "interesado");
        if (S.f.rev === "descartado" || S.f.rev === "fusionado") ints = (await api("/api/reg?" + new URLSearchParams({c, tipo: "interesado", revision: S.f.rev}))).items;
        else if (S.f.rev) ints = ints.filter(i => i.revision === S.f.rev);
        if (n !== seq) return;
        S.all = r.items; S.ints = ints; S.sel = new Set([...S.sel].filter(id => ints.some(i => i.id === id)));
        if (S.open && !ints.some(i => i.id === S.open)) S.open = null;
        pintar();
      } catch (x) { if (n === seq) raiz.replaceChildren(el("p", {className: "err", textContent: x.message})); }
    }
    const byId = id => S.ints.find(i => i.id === id) || S.all.find(i => i.id === id);
    const visibles = () => S.ints;

    // ---- guardar (optimista, deshacible con Ctrl+Z) ----
    async function guardar(it, cambios, src, msg) {
      const nuevo = {...cambios}; if (cambios.campos) nuevo.campos = {...(it.campos || {}), ...cambios.campos};
      const antes = {titulo: it.titulo, detalle: it.detalle, campos: {...(it.campos || {})}, editado: it.editado};
      Object.assign(it, nuevo); it.editado = true; refrescar(src);
      try { Object.assign(it, await PATCH(it.id, cambios)); cambio(); if (msg) aviso_(msg + " Ctrl+Z para deshacer"); }
      catch (x) { Object.assign(it, antes); err(x); }
      refrescar(src);
    }
    const guarda = (it, k, v, src) => {
      if (String(val(it, k)) === String(v)) return;
      if (k === "campos.poder" || k === "campos.interes") v = v === "" ? "" : Number(v);
      return guardar(it, k.startsWith("campos.") ? {campos: {[k.slice(7)]: v}} : {[k]: v}, src);
    };
    const mover = (id, p, i) => { const it = byId(id); if (it && (pw(it.campos?.poder) !== p || iw(it.campos?.interes) !== i)) { S.foco = id; return guardar(it, {campos: {poder: p ?? "", interes: i ?? ""}}, "", p == null ? "Sacado de la matriz." : "Movido a " + posTxt(p, i) + "."); } };
    const revisar = async (ids, accion) => {
      if (!ids.length) return;
      try { await post("/api/reg/revisar", {c, ids, accion}); aviso_(({aprobar: "Aprobado", restaurar: "Restaurado"}[accion] || "Descartado") + " · " + ids.length + ". Ctrl+Z para deshacer"); S.sel.clear(); cambio(); await cargar(); } catch (x) { err(x); }
    };
    const fusionar = (destino, origenes) => { if (destino && origenes.length) regDialogoFusion(c, [destino, ...origenes].map(byId), destino, async () => { S.sel.clear(); cambio(); await cargar(); }); };
    const trasSeparar = async () => { cambio(); await cargar(); };
    async function deshacer() { try { const r = await post("/api/reg/deshacer", {c}); aviso_(r.revertidas ? "Deshecho (" + r.revertidas + ")" : "Nada que deshacer"); cambio(); await leeN(); pintaAjustes(); await cargar(); } catch (x) { err(x); } }

    // ---- exportación ----
    async function exportar(fmt) {
      const u = "/api/reg/exportar?" + new URLSearchParams({c, vista: "interesados", fmt, borrador: S.soloAprob ? "0" : "1"});
      try {
        const r = await fetch(u);
        if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(typeof det === "function" ? det(d, r.statusText) : d.detail || r.statusText); }
        const b = await r.blob(), m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(r.headers.get("Content-Disposition") || "");
        const a = el("a", {href: URL.createObjectURL(b), download: m ? decodeURIComponent(m[1]) : "interesados." + fmt}); document.body.append(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      } catch (x) { aviso_("No se pudo exportar: " + (x.message || x)); }
    }

    // ---- controles de campo (compartidos por tabla y ficha) ----
    function ctl(it, k, tipo, label, src) {
      const v = val(it, k), f = {"aria-label": label + " de " + it.titulo}, ed = it.revision !== "fusionado";
      if (!ed) return el("span", {textContent: v});
      let x;
      if (tipo === "s" || tipo === "n") {
        const ops = tipo === "n" ? Array.from({length: 2 * (k === "campos.poder" ? NP : NI) - 1}, (_, j) => String(1 + j / 2)) : ACTS;
        x = el("select", f, new Option("—", ""), ...(v !== "" && !ops.includes(String(v)) ? [String(v), ...ops] : ops).map(o => new Option(fmt(o), o))); x.value = String(v);
        x.onchange = () => guarda(it, k, x.value, src);
      } else {
        x = tipo === "a" ? el("textarea", {...f, rows: 2, value: v}) : el("input", {...f, type: "text", value: v});
        if (k === "campos.estrategia" && sugerida(it)) x.placeholder = "Sugerida: " + sugerida(it);
        x.onchange = () => guarda(it, k, x.value, src);
        if (tipo === "a") x.onkeydown = ev => { if (ev.key === "Escape") x.blur(); };
      }
      return x;
    }

    // ---- cabecera: exportar + añadir ----
    function pintaHead() {
      const nom = el("input", {type: "text", placeholder: "Nombre del interesado", "aria-label": "Nombre del nuevo interesado"});
      const add = async () => {
        const t = nom.value.trim(); if (!t) return nom.focus();
        try { const n = await post("/api/reg", {c, tipo: "interesado", titulo: t}); nom.value = ""; cambio(); S.open = n.id; await cargar(); } catch (x) { err(x); }
      };
      nom.onkeydown = ev => { if (ev.key === "Enter") add(); };
      const menu = el("details", {className: "int-menu"}, el("summary", {className: "int-sum", textContent: "Exportar ▾"}),
        el("div", {className: "int-pop"},
          el("label", {className: "check"}, el("input", {type: "checkbox", checked: S.soloAprob, onchange: ev => { S.soloAprob = ev.target.checked; }}), "Solo aprobados"),
          el("small", {textContent: "Sin marcar, incluye lo no revisado marcado BORRADOR."}),
          el("div", {className: "int-fmts"}, ...["docx", "pdf", "xlsx", "csv", "md", "json"].map(f => el("button", {className: "sec sm", textContent: f.toUpperCase(), onclick: () => { menu.open = false; exportar(f); }})))));
      zHead.replaceChildren(H("Interesados · " + S.ints.length), el("span", {className: "grow"}), nom, el("button", {className: "sec", textContent: "+ Añadir", onclick: add}), menu);
    }

    // ---- aviso de posibles duplicados ----
    function pintaBan() {
      const vivos = S.ints.filter(i => i.revision !== "descartado" && i.revision !== "fusionado"), ps = [];
      for (let a = 0; a < vivos.length; a++) for (let b = a + 1; b < vivos.length; b++) {
        const k = [vivos[a].id, vivos[b].id].sort().join("|");
        if (!S.ign.has(k) && parecidos(vivos[a].titulo, vivos[b].titulo)) ps.push([vivos[a], vivos[b], k]);
      }
      zBan.replaceChildren(...ps.slice(0, 3).map(([a, b, k]) => {
        const [d, o] = b.titulo.length > a.titulo.length ? [b, a] : [a, b];
        return el("div", {className: "aviso w int-dup"}, el("span", {}, el("b", {textContent: "¿Fusionar? "}), "«" + a.titulo + "» y «" + b.titulo + "» podrían ser la misma persona."), el("span", {className: "grow"}),
          el("button", {className: "pri sm", textContent: "Fusionar en «" + d.titulo + "»", onclick: () => fusionar(d.id, [o.id])}),
          el("button", {className: "link", textContent: "No son iguales", onclick: () => { S.ign.add(k); lsSet("int-ign-" + c, [...S.ign]); pintaBan(); }}));
      }), ...(ps.length > 3 ? [el("p", {className: "muted", textContent: "…y " + (ps.length - 3) + " posibles duplicados más."})] : []));
    }

    // ---- filtros y recuentos por cuadrante ----
    function pintaBar() {
      const vs = visibles(), cnt = {gc: 0, ms: 0, mi: 0, mon: 0, lim: 0, sin: 0}; vs.forEach(i => cnt[qOf(i)]++);
      const pill = (k, t, n) => el("button", {className: "f-pill", "aria-pressed": S.f.cuad === k, textContent: t + " · " + n, title: k && QS[k].s, onclick: () => { S.f.cuad = k; pintaBar(); pintaTabla(); }});
      const sr = el("select", {"aria-label": "Revisión", onchange: ev => { S.f.rev = ev.target.value; cargar(); }}, new Option("Revisión: visibles", ""), new Option("Propuestos (IA)", "propuesto"), new Option("Aprobados", "aprobado"), new Option("Descartados", "descartado"), new Option("Fusionados (" + regNumFusionadas(S.all.filter(i => i.tipo === "interesado")) + ")", "fusionado")); sr.value = S.f.rev;
      zBar.replaceChildren(pill("", "Todos", vs.length), ...["gc", "ms", "mi", "mon", "lim", "sin"].map(k => pill(k, QS[k].t, cnt[k])), el("span", {className: "grow"}), sr);
    }

    function pintaAcc() {
      const ids = [...S.sel], n = ids.length, prop = S.ints.filter(i => i.revision === "propuesto");
      const dest = el("select", {"aria-label": "Fusionar en"}, ...ids.map(id => new Option(byId(id)?.titulo || id, id)));
      {
        zAcc.replaceChildren(el("button", {className: "sec", textContent: "Deshacer", title: "Ctrl+Z", onclick: deshacer}), el("span", {className: "grow"}),
          ...(prop.length && !n ? [el("button", {className: "pri sm", textContent: "Aprobar propuestos (" + prop.length + ")", onclick: () => revisar(prop.map(i => i.id), "aprobar")})] : []),
          ...(n ? [el("span", {className: "muted", textContent: n + (n === 1 ? " seleccionado" : " seleccionados")}),
            el("button", {className: "pri sm", textContent: "Aprobar", onclick: () => revisar(ids, "aprobar")}), el("button", {className: "sec sm", textContent: "Descartar", onclick: () => revisar(ids, "descartar")}),
            ...(n >= 2 ? [el("span", {className: "muted", textContent: "Fusionar en:"}), dest, el("button", {className: "sec sm", textContent: "Fusionar", onclick: () => fusionar(dest.value, ids.filter(i => i !== dest.value))})] : [])] : []));
      }
    }

    // ---- matriz filas×columnas (cruz en el centro exacto; ver REGLA) + bandeja «sin clasificar» ----
    function chip(it) {
      const p = pw(it.campos?.poder), i = iw(it.campos?.interes), L = Number(S.cfg.len) || 0;
      const nm = L && it.titulo.length > L ? it.titulo.slice(0, L).trimEnd() + "…" : it.titulo;
      const b = el("button", {type: "button", className: "int-chip" + (it.revision === "propuesto" ? " prop" : "") + (it.revision === "descartado" ? " cerr" : ""), draggable: true, title: tip(it), "data-id": it.id, "data-ini": toks(it.titulo).filter(w => w.length > 2 || /\d/.test(w)).slice(0, 2).map(w => /\d/.test(w) ? w : w[0].toUpperCase()).join("") || it.titulo.slice(0, 2)},
        el("span", {className: "int-nm", textContent: nm}));
      b.setAttribute("aria-label", tip(it).replace(/\n/g, ". ") + ". Flechas: mover medio paso (Mayús: un paso); Intro: abrir ficha");
      b.onclick = () => { S.open = it.id; pintaFicha(); };
      b.ondragstart = ev => { ev.dataTransfer.setData("text/plain", it.id); ev.dataTransfer.effectAllowed = "move"; b.classList.add("arrastrando"); };
      b.ondragend = () => b.classList.remove("arrastrando");
      b.onkeydown = ev => {  // alternativa accesible al arrastre
        const d = {ArrowUp: [1, 0], ArrowDown: [-1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1]}[ev.key]; if (!d) return;
        ev.preventDefault(); const s = ev.shiftKey ? 1 : .5;
        p == null || i == null ? mover(it.id, Math.ceil(NP / 2), Math.ceil(NI / 2)) : mover(it.id, Math.min(NP, Math.max(1, p + d[0] * s)), Math.min(NI, Math.max(1, i + d[1] * s)));
      };
      return b;
    }
    const zona = (n, fn) => { n.ondragover = ev => { ev.preventDefault(); n.classList.add("over"); }; n.ondragleave = () => n.classList.remove("over"); n.ondrop = ev => { ev.preventDefault(); n.classList.remove("over"); fn(ev.dataTransfer.getData("text/plain")); }; return n; };
    // cabecera de la matriz + «Ajustar matriz» (vista previa en vivo; se guarda por carpeta). Se pinta aparte para no cerrar el panel al repintar.
    function pintaAjustes(abierto) {
      const K = S.cfg, fija = (k, v) => { S.cfg = {...S.cfg, [k]: v}; lsSet("int-mx-" + c, S.cfg); refrescar(); };
      const niveles = async (np_, ni_) => {  // null = ese eje no cambia
        try {
          const r = await post("/api/reg/matriz", {c, ...(np_ ? {niveles_poder: np_} : {}), ...(ni_ ? {niveles_interes: ni_} : {}), reescalar: !!S.cfg.reesc});
          NP = okN(r.niveles_poder ?? np_ ?? NP); NI = okN(r.niveles_interes ?? ni_ ?? NI);
          aviso_("Matriz de " + NP + " filas × " + NI + " columnas" + (r.recortados ? " · " + r.recortados + " valores recortados al máximo" : "") + ". Ctrl+Z deshace el reescalado"); cambio(); await cargar();
        } catch (x) { err(x); }
        pintaAjustes(true);
      };
      const fila = (t, ctl, extra) => el("label", {className: "int-aj-f"}, el("span", {textContent: t}), ctl, ...(extra ? [extra] : []));
      const rango = (k, min, max, paso, ud) => { const o = el("output", {textContent: K[k] + ud}); return fila({h: "Alto de la matriz", gap: "Separación entre chips"}[k], el("input", {type: "range", min, max, step: paso, value: K[k], oninput: ev => { o.textContent = ev.target.value + ud; fija(k, Number(ev.target.value)); }}), o); };
      const sel = (k, ops, f = x => x) => { const s = el("select", {onchange: ev => fija(k, f(ev.target.value))}, ...ops.map(([v, t]) => new Option(t, v))); s.value = String(K[k]); return s; };
      const chk = (k, t) => el("label", {className: "check"}, el("input", {type: "checkbox", checked: !!K[k], onchange: ev => fija(k, ev.target.checked)}), t);
      const sN = (v, f) => { const s = el("select", {onchange: ev => f(Number(ev.target.value))}, ...Array.from({length: NMAX - 2}, (_, j) => new Option((j + 3) + (j + 3 === NDEF ? " (por defecto)" : ""), j + 3))); s.value = String(v); return s; };
      const m = el("details", {className: "int-menu", open: !!abierto}, el("summary", {className: "int-sum", textContent: "Ajustar matriz ▾"}),
        el("div", {className: "int-pop int-aj"},
          el("div", {className: "int-aj-2"}, fila("Filas (poder)", sN(NP, n => niveles(n, null))), fila("Columnas (interés)", sN(NI, n => niveles(null, n)))),
          el("div", {className: "int-aj-h2"}, el("small", {className: "muted", textContent: "Huecos de cada eje, para todo el proyecto."}),
            el("button", {className: "link", textContent: "Igualar columnas a filas", disabled: NP === NI, onclick: () => niveles(null, NP)})),
          el("label", {className: "check"}, el("input", {type: "checkbox", checked: !!K.reesc, onchange: ev => { S.cfg = {...S.cfg, reesc: ev.target.checked}; lsSet("int-mx-" + c, S.cfg); }}), "Reescalar los valores existentes"),
          el("small", {className: "muted int-aj-h", textContent: "Activado: cada poder/interés se convierte en proporción a la nueva escala (un 4 de 5 pasa a 8 de 10). Desactivado: se conservan los números tal cual y los que superen el nuevo máximo se recortan a él. Se deshace con Ctrl+Z."}),
          rango("h", 240, 900, 20, " px"), rango("gap", 0, 16, 1, " px"),
          fila("Longitud máxima del nombre", el("input", {type: "number", min: 0, max: 60, value: K.len, oninput: ev => fija("len", Math.max(0, Number(ev.target.value) || 0))}), el("small", {className: "muted", textContent: "0 = nombre completo (salta de línea)"})),
          fila("Tamaño de chip", sel("tam", [["S", "Pequeño"], ["M", "Mediano"], ["L", "Grande"]])),
          chk("cuad", "Celdas cuadradas (el alto sale del ancho)"), chk("grid", "Mostrar cuadrícula"), chk("etq", "Mostrar etiquetas de cuadrante"),
          el("button", {className: "sec sm", textContent: "Restablecer", title: "Restablece el aspecto (no cambia los niveles)", onclick: () => { S.cfg = {...MXDEF}; lsSet("int-mx-" + c, S.cfg); refrescar(); pintaAjustes(true); }})));
      zMxH.replaceChildren(el("h3", {textContent: "Matriz poder / interés", title: REGLA}), el("span", {className: "grow"}), m);
    }
    function pintaMatriz() {
      // Capas: cuadrícula CSS de casillas idénticas (solo dibujo; el contenido nunca cambia su tamaño) + capa de «huecos» absolutos.
      // Un hueco por posición (poder, interés) en pasos de 0,5: entero = centro de casilla, x,5 = sobre la línea. Sus chips van en fila
      // centrada y saltan de línea solo si no caben; si no caben en alto, el hueco hace scroll.
      const vs = visibles(), K = S.cfg, ticks = [], mp = (NP + 1) / 2, mi = (NI + 1) / 2;
      const px = v => (v - .5) / NI * 100 + "%", py = v => (NP + .5 - v) / NP * 100 + "%";
      for (let v = 1; v <= NP; v += .5) ticks.push(el("span", {className: "int-tk y" + (v % 1 ? " m" : ""), "aria-hidden": "true", style: "top:" + py(v), textContent: v % 1 ? "" : v}));
      for (let v = 1; v <= NI; v += .5) ticks.push(el("span", {className: "int-tk x" + (v % 1 ? " m" : ""), "aria-hidden": "true", style: "left:" + px(v), textContent: v % 1 ? "" : v}));
      const pos = new Map();
      for (const it of vs) { const p = pw(it.campos?.poder), i = iw(it.campos?.interes); if (p == null || i == null) continue; const k = p + "|" + i; pos.has(k) ? pos.get(k).push(it) : pos.set(k, [it]); }
      const ks = [...pos.keys()].map(k => k.split("|").map(Number));
      const huecos = ks.map(([p, i]) => {
        let w = 1, h = 1;  // en casillas; un vecino a medio paso lo estrecha (en su eje dominante) para que nunca se solapen
        for (const [p2, i2] of ks) { const dp = Math.abs(p2 - p), di = Math.abs(i2 - i); if ((dp || di) && dp < 1 && di < 1) di >= dp ? (w = Math.min(w, di)) : (h = Math.min(h, dp)); }
        const k = p + "|" + i, its = pos.get(k), ab = S.slA === k && its.length > 2;
        return el("div", {className: "int-sl" + (its.length > 2 ? " mucho" : "") + (ab ? " ab" : ""), role: "group", "aria-label": posTxt(p, i), style: `left:${px(i)};top:${py(p)};width:${w / NI * 100}%;max-height:${h / NP * 100}%` + (ab ? `;transform:translate(${i > mi ? "calc(-100% + 12px)" : "-12px"},-50%)` : "")},
          ...(its.length > 2 ? [el("button", {type: "button", className: "int-cnt", textContent: ab ? "×" : its.length, "aria-expanded": ab, "aria-label": (ab ? "Cerrar la lista de " : "Ver los ") + its.length + " de " + posTxt(p, i),
            title: (ab ? "Cerrar" : its.length + " aquí (clic para verlos todos)") + ": " + its.map(x => x.titulo).join(", "), onclick: () => { S.slA = ab ? null : k; pintaMatriz(); }})] : []),
          el("div", {className: "int-slr"}, ...its.map(chip)));
      });
      const cnt = q => vs.filter(x => qOf(x) === q).length, lab = q => el("span", {className: "int-ql", title: QS[q].s, textContent: QS[q].t + " · " + cnt(q)});
      const gt = el("span", {className: "int-gh-t"}), gh = el("div", {className: "int-gh", hidden: true, "aria-hidden": "true"}, gt);
      const grid = el("div", {className: "int-grid", "aria-hidden": "true", style: `grid-template-columns:repeat(${NI},minmax(0,1fr));grid-template-rows:repeat(${NP},minmax(0,1fr))`}, ...Array.from({length: NP * NI}, () => el("div", {className: "int-cell"})));
      const plot = el("div", {className: "int-plot t-" + K.tam + (K.grid ? " rej" : ""), role: "group", "aria-label": "Matriz de " + NP + " filas (poder) por " + NI + " columnas (interés)", title: REGLA,
        style: K.cuad ? `height:auto;aspect-ratio:${NI}/${NP}` : `height:max(${K.h}px,${NP * 48}px)`},
        ...["ms", "gc", "mon", "mi"].map(q => el("div", {className: "int-qb q-" + q, "aria-hidden": "true"})), grid, el("div", {className: "int-cx v", "aria-hidden": "true"}), el("div", {className: "int-cx h", "aria-hidden": "true"}), ...ticks, ...huecos, gh);
      const donde = ev => { const r = plot.getBoundingClientRect(); return [snap((r.bottom - ev.clientY) / r.height * NP + .5, NP), snap((ev.clientX - r.left) / r.width * NI + .5, NI)]; };
      plot.ondragover = ev => { ev.preventDefault(); ev.dataTransfer.dropEffect = "move"; const [p, i] = donde(ev); gh.hidden = false; gh.style.left = px(i); gh.style.top = py(p); gh.classList.toggle("ab", p > NP - 1); gt.textContent = posTxt(p, i); };
      plot.ondragleave = ev => { if (!plot.contains(ev.relatedTarget)) gh.hidden = true; };
      plot.ondrop = ev => { ev.preventDefault(); gh.hidden = true; const [p, i] = donde(ev); mover(ev.dataTransfer.getData("text/plain"), p, i); };
      const sin = vs.filter(it => qOf(it) === "sin"), tray = zona(el("div", {className: "int-tray"}, ...sin.map(chip),
        ...(sin.length ? [] : [el("span", {className: "muted", textContent: "Todos clasificados. Arrastra aquí para quitar de la matriz."})])), id => mover(id, null, null));
      zMx.style.cssText = `--mx-h:${K.h}px;--chip-gap:${K.gap}px`;
      zMxB.replaceChildren(
        el("div", {className: "int-mxw"}, el("div", {className: "int-ax int-ay", textContent: "Poder ↑ (más poder arriba)"}),
          el("div", {className: "int-mxc"}, ...(K.etq ? [el("div", {className: "int-qh"}, lab("ms"), lab("gc"))] : []), plot,
            ...(K.etq ? [el("div", {className: "int-qh"}, lab("mon"), lab("mi"))] : []), el("div", {className: "int-ax int-axx", textContent: "Interés → (más interés a la derecha)"}))),
        el("p", {className: "muted int-nota", title: REGLA, textContent: QS.lim.t + " · " + cnt("lim") + " — Valores intermedios (x,5) = en la línea entre dos casillas. Poder o interés exactamente en el centro (poder " + fmt(mp) + ", interés " + fmt(mi) + ") = entre dos zonas: no se asigna a ningún cuadrante."}),
        el("h4", {textContent: "Sin clasificar · " + sin.length}), el("p", {className: "muted", textContent: "Arrastra a la matriz (o usa las flechas con el chip enfocado) para fijar poder e interés. La IA no los infiere."}), tray);
    }

    // ---- tabla ----
    function pintaTabla() {
      let xs = visibles().filter(i => !S.f.cuad || qOf(i) === S.f.cuad);
      const {k, d} = S.sort;
      if (k) xs = [...xs].sort((a, b) => { const x = val(a, k), y = val(b, k), nx = x === "" , ny = y === ""; return nx || ny ? (nx - ny) : (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "es")) * d; });
      const todos = el("input", {type: "checkbox", "aria-label": "Seleccionar todo", checked: xs.length > 0 && xs.every(i => S.sel.has(i.id)), onchange: ev => { xs.forEach(i => ev.target.checked ? S.sel.add(i.id) : S.sel.delete(i.id)); pintaTabla(); pintaAcc(); }});
      const th = ([kk, t]) => el("th", {scope: "col", "aria-sort": S.sort.k === kk ? (S.sort.d > 0 ? "ascending" : "descending") : "none"},
        el("button", {className: "link int-so", textContent: t + (S.sort.k === kk ? (S.sort.d > 0 ? " ↑" : " ↓") : ""), onclick: () => { S.sort = S.sort.k === kk ? {k: kk, d: -S.sort.d} : {k: kk, d: 1}; pintaTabla(); }}));
      const fila = it => {
        const chk = el("input", {type: "checkbox", checked: S.sel.has(it.id), "aria-label": "Seleccionar " + it.titulo, onchange: () => { chk.checked ? S.sel.add(it.id) : S.sel.delete(it.id); pintaAcc(); }});
        const q = qOf(it), ins = typeof regInsignias === "function" ? regInsignias(it) : [];
        return el("tr", {className: "reg-r" + (it.revision === "propuesto" ? " prop" : "") + (it.revision === "descartado" || it.revision === "fusionado" ? " cerr" : ""), "data-id": it.id},
          el("td", {className: "c"}, chk), ...COLS.map(([kk, t, tp]) => el("td", {className: tp === "n" ? "int-n" : ""}, ctl(it, kk, tp, t, "tabla"))),
          el("td", {}, el("span", {className: "badge" + (q === "sin" ? " w" : ""), textContent: QS[q].t})), el("td", {className: "reg-ins"}, ...ins, regFusiona(it, c, trasSeparar)),
          el("td", {className: "reg-ops"},
            ...(it.revision === "descartado" ? [el("button", {className: "sec sm", textContent: "Restaurar", onclick: () => revisar([it.id], "restaurar")})] : []),
            ...(it.revision === "propuesto" ? [el("button", {className: "sec sm", textContent: "Aprobar", onclick: () => revisar([it.id], "aprobar")}), el("button", {className: "link", textContent: "Descartar", onclick: () => revisar([it.id], "descartar")})] : []),
            ...regBotonSeparar(it, c, trasSeparar), el("button", {className: "link", textContent: "Ficha", onclick: () => { S.open = it.id; pintaFicha(); }})));
      };
      zTb.replaceChildren(el("div", {className: "sec-h"}, el("h3", {textContent: "Tabla · " + xs.length})),
        xs.length ? el("div", {className: "int-scroll"}, el("table", {className: "reg-t int-t"}, el("thead", {}, el("tr", {}, el("th", {className: "c"}, todos), ...COLS.map(th), el("th", {textContent: "Cuadrante"}), el("th", {textContent: "Revisión"}), el("th"))),
          el("tbody", {}, ...xs.map(fila)))) : el("div", {className: "vacio", textContent: S.ints.length ? "Nada con estos filtros." : "Aún no hay interesados. La IA los propone al procesar documentos, o añádelos con «+ Añadir»."}));
    }

    // ---- ficha lateral ----
    async function historial(it, host) {
      host.replaceChildren(el("p", {className: "muted", textContent: "Cargando…"}));
      try {
        const h = await api("/api/reg/" + encodeURIComponent(it.id) + "/historial?c=" + encodeURIComponent(c)), j = x => typeof x === "string" ? x : JSON.stringify(x);
        host.replaceChildren(...(h.length ? h.map(x => el("div", {className: "reg-h"}, el("b", {textContent: x.accion}), el("small", {className: "muted", textContent: " " + new Date(x.t * (x.t < 1e11 ? 1000 : 1)).toLocaleString("es")}),
          el("div", {textContent: [x.antes && "Antes: " + j(x.antes), x.despues && "Después: " + j(x.despues)].filter(Boolean).join("  →  ")}))) : [el("p", {className: "muted", textContent: "Sin cambios registrados."})]));
      } catch (x) { host.replaceChildren(el("p", {className: "err", textContent: x.message})); }
    }
    function pintaFicha() {
      const it = S.open && byId(S.open);
      zFi.hidden = !it; raiz.classList.toggle("con-ficha", !!it);
      if (!it) return zFi.replaceChildren();
      const campo = (t, k, tp) => el("label", {className: "int-f"}, el("span", {textContent: t}), ctl(it, k, tp, t, "ficha"));
      const cs = it.citas || [], sol = (it.relaciones || []).filter(r => r.tipo === "solicita").map(r => ({r, x: byId(r.a === it.id ? r.b : r.a)})).filter(o => o.x);
      const due = S.all.filter(x => x.tipo !== "interesado" && x.dueno && igual(x.dueno, it.titulo));
      const li = x => el("li", {}, el("b", {textContent: (x.codigo ? x.codigo + " · " : "")}), x.titulo + " ", el("span", {className: "badge", textContent: (typeof REG_TIPOS === "object" && REG_TIPOS[x.tipo] || x.tipo) + (x.estado ? " · " + x.estado : "")}));
      const hh = el("div", {className: "int-hist", hidden: true}), q = qOf(it), sg = sugerida(it);
      const estr = it.campos?.estrategia;
      zFi.replaceChildren(
        el("div", {className: "sec-h"}, el("h3", {textContent: it.titulo}), el("button", {className: "sec sm", textContent: "Cerrar", onclick: () => { S.open = null; pintaFicha(); }})),
        el("div", {className: "row wrap"}, ...(typeof regInsignias === "function" ? regInsignias(it) : []), el("span", {className: "badge" + (q === "sin" ? " w" : ""), textContent: QS[q].t})),
        el("div", {className: "int-fs"}, campo("Nombre", "titulo", "t"), campo("Rol", "campos.rol", "t"), campo("Organización", "campos.organizacion", "t"), campo("Poder (1-" + NP + ")", "campos.poder", "n"), campo("Interés (1-" + NI + ")", "campos.interes", "n"),
          campo("Actitud", "campos.actitud", "s"), campo("Canal", "campos.canal", "t")),
        campo("Estrategia", "campos.estrategia", "a"),
        ...(sg && !estr ? [el("button", {className: "sec sm", textContent: "Usar la sugerida: " + sg, onclick: () => guarda(it, "campos.estrategia", sg)})] : []),
        campo("Notas", "detalle", "a"),
        el("div", {className: "row wrap", style: "margin-top:8px"},
          ...(it.revision === "propuesto" ? [el("button", {className: "pri sm", textContent: "Aprobar", onclick: () => revisar([it.id], "aprobar")}), el("button", {className: "sec sm", textContent: "Descartar", onclick: () => revisar([it.id], "descartar")})] : []),
          ...(it.revision === "descartado" ? [el("button", {className: "sec sm", textContent: "Restaurar", onclick: () => revisar([it.id], "restaurar")})] : []),
          ...(it.origen === "manual" ? [el("button", {className: "link", textContent: "Quitar", onclick: async () => { try { await api("/api/reg/" + encodeURIComponent(it.id) + "?c=" + encodeURIComponent(c), {method: "DELETE"}); S.open = null; cambio(); await cargar(); } catch (x) { err(x); } }})] : [])),
        el("h4", {textContent: "Menciones · " + cs.length}),
        ...(cs.length ? cs.map(ci => el("blockquote", {}, "«" + (ci.texto || "") + "» ", ci.mid ? fLink({mid: ci.mid, ver: ci.ver, t: ci.t}, "[" + mmss(ci.t || 0) + "]") : "", ci.verificada === false ? el("span", {className: "badge w", textContent: "cita sin verificar"}) : "")) : [el("p", {className: "muted", textContent: it.origen === "manual" ? "Añadido a mano: sin menciones." : "Sin menciones."})]),
        el("h4", {textContent: "Requisitos que solicitó · " + sol.length}),
        ...(sol.length ? [el("ul", {className: "f-lst"}, ...sol.map(o => el("li", {}, el("b", {textContent: (o.x.codigo ? o.x.codigo + " · " : "")}), o.x.titulo, o.r.propuesta ? el("span", {className: "badge acc", textContent: " IA · propuesta"}) : "")))] : [el("p", {className: "muted", textContent: "Ninguno vinculado."})]),
        el("h4", {textContent: "Tareas y decisiones a su cargo · " + due.length}),
        ...(due.length ? [el("ul", {className: "f-lst"}, ...due.map(li))] : [el("p", {className: "muted", textContent: "Ninguna con este responsable."})]),
        el("h4", {textContent: "Historial"}), el("button", {className: "link", textContent: "Ver historial", onclick: ev => { hh.hidden = false; ev.target.hidden = true; historial(it, hh); }}), hh);
    }

    function pintar() { pintaHead(); pintaBan(); pintaBar(); pintaAcc(); pintaMatriz(); pintaTabla(); pintaFicha(); restauraFoco(); }
    function restauraFoco() { if (!S.foco) return; const id = S.foco; S.foco = null; [...raiz.querySelectorAll(".int-chip")].find(x => x.getAttribute("data-id") === id)?.focus(); }
    function refrescar(src) { pintaHead(); pintaBan(); pintaBar(); pintaMatriz(); if (src !== "tabla") pintaTabla(); if (src !== "ficha") pintaFicha(); restauraFoco(); }

    document.addEventListener("keydown", ev => { if (ev.key === "Escape" && S.open && raiz.isConnected && !ev.defaultPrevented) { S.open = null; pintaFicha(); } });
    // Ctrl+Z global (registro.js) también deshace aquí
    if (typeof REG_ACTIVA !== "undefined") REG_ACTIVA = {recargar: cargar, vivo: () => raiz.isConnected, tecla: ev => { if (ev.ctrlKey && ev.key.toLowerCase() === "z" && !(typeof regEnCampo === "function" && regEnCampo())) { ev.preventDefault(); deshacer(); return true; } return false; }};
    pintaAjustes();
    await cargar();
    return [raiz];
  }
  document.addEventListener("DOMContentLoaded", () => { FVISTAS.interesados = vista; });
  if (typeof module !== "undefined") module.exports = {quad, parecidos, vista};  // solo para pruebas en node
})();
