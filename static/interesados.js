// Vista «interesados» (F4): matriz poder/interés con chips arrastrables + tabla editable + ficha + fusión + exportación.
// IA primero: los interesados llegan «propuesto» (nombre, rol, organización + citas); poder/interés NUNCA se infieren -> «Sin clasificar».
// Registra FVISTAS.interesados = (c, e) => [nodos]  (carpeta.js se carga después: se registra en DOMContentLoaded).
(() => {
  const ACT = {"a favor": ["▲", "int-fav"], neutral: ["●", "int-neu"], "en contra": ["▼", "int-con"], desconocida: ["?", "int-des"]};  // icono + color: no depende solo del color
  const ACTS = Object.keys(ACT);
  const QS = {
    gc: {t: "Gestionar de cerca", s: "Alto poder, alto interés: implicar y consultar de forma activa"},
    ms: {t: "Mantener satisfecho", s: "Alto poder, bajo interés: informar de lo esencial y evitar sorpresas"},
    mi: {t: "Mantener informado", s: "Bajo poder, alto interés: comunicación regular, escuchar sus aportes"},
    mon: {t: "Monitorizar", s: "Bajo poder, bajo interés: seguimiento mínimo"},
    sin: {t: "Sin clasificar", s: "Falta poder o interés (la IA no los infiere)"},
  };
  const num = v => (v === "" || v == null || isNaN(Number(v)) ? null : Math.min(5, Math.max(1, Math.round(Number(v)))));
  // alto = valor >= 3 (la celda central 3 cuenta como alto; la rejilla 5x5 lo dibuja así)
  const quad = (p, i) => { p = num(p); i = num(i); return p == null || i == null ? "sin" : p >= 3 ? (i >= 3 ? "gc" : "ms") : (i >= 3 ? "mi" : "mon"); };
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
  const sugerida = it => QS[qOf(it)] && qOf(it) !== "sin" ? QS[qOf(it)].s : "";
  const tip = it => [it.titulo, [it.campos?.rol, it.campos?.organizacion].filter(Boolean).join(" · "), "Actitud: " + (it.campos?.actitud || "desconocida"),
    qOf(it) === "sin" ? "Sin clasificar" : "Poder " + it.campos.poder + " · Interés " + it.campos.interes].filter(Boolean).join("\n");
  const COLS = [["titulo", "Nombre", "t"], ["campos.rol", "Rol", "t"], ["campos.organizacion", "Organización", "t"], ["campos.poder", "Poder", "n"], ["campos.interes", "Interés", "n"],
    ["campos.actitud", "Actitud", "s"], ["campos.estrategia", "Estrategia", "t"], ["campos.canal", "Canal", "t"], ["detalle", "Notas", "a"]];
  const val = (it, k) => k.startsWith("campos.") ? (it.campos || {})[k.slice(7)] ?? "" : it[k] ?? "";

  async function vista(c, e) {
    const S = {all: [], ints: [], sel: new Set(), f: {cuad: "", act: "", rev: ""}, sort: {k: "", d: 1}, open: null, hist: null, soloAprob: false, foco: null, ign: new Set(lsGet("int-ign-" + c, []))};
    let seq = 0;
    const raiz = el("div", {className: "int"});
    const zHead = el("div", {className: "int-head"}), zBan = el("div"), zBar = el("div", {className: "int-bar"}), zAcc = el("div", {className: "reg-acc"});
    const zMx = el("section", {className: "int-col int-mx-w"}), zTb = el("section", {className: "int-col int-tb-w"}), zFi = el("aside", {className: "int-ficha", hidden: true});
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
        if (S.f.rev === "descartado") ints = (await api("/api/reg?" + new URLSearchParams({c, tipo: "interesado", revision: "descartado"}))).items;
        else if (S.f.rev) ints = ints.filter(i => i.revision === S.f.rev);
        if (n !== seq) return;
        S.all = r.items; S.ints = ints; S.sel = new Set([...S.sel].filter(id => ints.some(i => i.id === id)));
        if (S.open && !ints.some(i => i.id === S.open)) S.open = null;
        pintar();
      } catch (x) { if (n === seq) raiz.replaceChildren(el("p", {className: "err", textContent: x.message})); }
    }
    const byId = id => S.ints.find(i => i.id === id) || S.all.find(i => i.id === id);
    const visibles = () => S.ints.filter(i => !S.f.act || (i.campos?.actitud || "desconocida") === S.f.act);

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
    const mover = (id, p, i) => { const it = byId(id); if (it && (num(it.campos?.poder) !== p || num(it.campos?.interes) !== i)) { S.foco = id; return guardar(it, {campos: {poder: p ?? "", interes: i ?? ""}}, "", p == null ? "Sacado de la matriz." : "Clasificado: " + QS[quad(p, i)].t + "."); } };
    const revisar = async (ids, accion) => {
      if (!ids.length) return;
      try { await post("/api/reg/revisar", {c, ids, accion}); aviso_(({aprobar: "Aprobado", restaurar: "Restaurado"}[accion] || "Descartado") + " · " + ids.length + ". Ctrl+Z para deshacer"); S.sel.clear(); cambio(); await cargar(); } catch (x) { err(x); }
    };
    const fusionar = async (destino, origenes) => {
      if (!destino || !origenes.length) return;
      try { await post("/api/reg/fusionar", {c, destino, origenes}); aviso_("Fusionado. Ctrl+Z para deshacer"); S.sel.clear(); cambio(); await cargar(); } catch (x) { err(x); }
    };
    async function deshacer() { try { const r = await post("/api/reg/deshacer", {c}); aviso_(r.revertidas ? "Deshecho (" + r.revertidas + ")" : "Nada que deshacer"); cambio(); await cargar(); } catch (x) { err(x); } }

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
        const ops = tipo === "n" ? ["1", "2", "3", "4", "5"] : ACTS;
        x = el("select", f, new Option("—", ""), ...(v !== "" && !ops.includes(String(v)) ? [String(v), ...ops] : ops).map(o => new Option(o, o))); x.value = String(v);
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
      const vs = visibles(), cnt = {gc: 0, ms: 0, mi: 0, mon: 0, sin: 0}; vs.forEach(i => cnt[qOf(i)]++);
      const pill = (k, t, n) => el("button", {className: "f-pill", "aria-pressed": S.f.cuad === k, textContent: t + " · " + n, title: k && QS[k].s, onclick: () => { S.f.cuad = k; pintaBar(); pintaTabla(); }});
      const sa = el("select", {"aria-label": "Actitud", onchange: ev => { S.f.act = ev.target.value; pintar(); }}, new Option("Todas las actitudes", ""), ...ACTS.map(a => new Option(a, a))); sa.value = S.f.act;
      const sr = el("select", {"aria-label": "Revisión", onchange: ev => { S.f.rev = ev.target.value; cargar(); }}, new Option("Revisión: visibles", ""), new Option("Propuestos (IA)", "propuesto"), new Option("Aprobados", "aprobado"), new Option("Descartados", "descartado")); sr.value = S.f.rev;
      zBar.replaceChildren(pill("", "Todos", vs.length), ...["gc", "ms", "mi", "mon", "sin"].map(k => pill(k, QS[k].t, cnt[k])), el("span", {className: "grow"}), sa, sr);
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

    // ---- matriz 5x5 (alto = 3..5) + bandeja «sin clasificar» ----
    function chip(it) {
      const a = ACT[it.campos?.actitud] || ACT.desconocida, p = num(it.campos?.poder), i = num(it.campos?.interes);
      const b = el("button", {type: "button", className: "int-chip " + a[1] + (it.revision === "propuesto" ? " prop" : "") + (it.revision === "descartado" ? " cerr" : ""), draggable: true, title: tip(it), "data-id": it.id},
        el("span", {className: "int-ic", "aria-hidden": "true", textContent: a[0]}), el("span", {className: "int-nm", textContent: it.titulo}));
      b.setAttribute("aria-label", tip(it).replace(/\n/g, ". ") + ". Flechas: mover; Intro: abrir ficha");
      b.onclick = () => { S.open = it.id; pintaFicha(); };
      b.ondragstart = ev => { ev.dataTransfer.setData("text/plain", it.id); ev.dataTransfer.effectAllowed = "move"; b.classList.add("arrastrando"); };
      b.ondragend = () => b.classList.remove("arrastrando");
      b.onkeydown = ev => {  // alternativa accesible al arrastre
        const d = {ArrowUp: [1, 0], ArrowDown: [-1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1]}[ev.key]; if (!d) return;
        ev.preventDefault(); const np = Math.min(5, Math.max(1, (p ?? 3) + d[0])), ni = Math.min(5, Math.max(1, (i ?? 3) + d[1]));
        p == null || i == null ? mover(it.id, 3, 3) : mover(it.id, np, ni);
      };
      return b;
    }
    const zona = (n, fn) => { n.ondragover = ev => { ev.preventDefault(); n.classList.add("over"); }; n.ondragleave = () => n.classList.remove("over"); n.ondrop = ev => { ev.preventDefault(); n.classList.remove("over"); fn(ev.dataTransfer.getData("text/plain")); }; return n; };
    function pintaMatriz() {
      const vs = visibles(), cells = [];
      for (let p = 5; p >= 1; p--) for (let i = 1; i <= 5; i++) {
        const q = quad(p, i), cell = el("div", {className: "int-cell q-" + q + (p === 3 ? " dv-b" : "") + (i === 3 ? " dv-l" : ""), "data-p": p, "data-i": i, role: "group", "aria-label": "Poder " + p + ", interés " + i + " · " + QS[q].t},
          ...vs.filter(it => num(it.campos?.poder) === p && num(it.campos?.interes) === i).map(chip));
        cells.push(zona(cell, id => mover(id, p, i)));
      }
      const lab = (q, cl) => el("span", {className: "int-ql " + cl, "aria-hidden": "true", textContent: QS[q].t + " (" + vs.filter(x => qOf(x) === q).length + ")"});
      const sin = vs.filter(it => qOf(it) === "sin"), tray = zona(el("div", {className: "int-tray"}, ...sin.map(chip),
        ...(sin.length ? [] : [el("span", {className: "muted", textContent: "Todos clasificados. Arrastra aquí para quitar de la matriz."})])), id => mover(id, null, null));
      zMx.replaceChildren(el("div", {className: "sec-h"}, el("h3", {textContent: "Matriz poder / interés"})),
        el("div", {className: "int-leg"}, ...ACTS.map(a => el("span", {className: "int-lg " + ACT[a][1]}, el("span", {className: "int-ic", "aria-hidden": "true", textContent: ACT[a][0]}), " " + a)),
          el("span", {className: "int-lg"}, el("span", {className: "int-ic prop-s", "aria-hidden": "true", textContent: "▢"}), " borde discontinuo = propuesto por la IA")),
        el("div", {className: "int-mx-in"}, el("span", {className: "int-ax int-ay", textContent: "Poder →"}),
          el("div", {className: "int-mx"}, el("div", {className: "int-grid"}, ...cells), lab("ms", "tl"), lab("gc", "tr"), lab("mon", "bl"), lab("mi", "br")),
          el("span", {className: "int-ax int-axx", textContent: "Interés →"})),
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
          el("td", {}, el("span", {className: "badge" + (q === "sin" ? " w" : ""), textContent: QS[q].t})), el("td", {className: "reg-ins"}, ...ins),
          el("td", {className: "reg-ops"},
            ...(it.revision === "descartado" ? [el("button", {className: "sec sm", textContent: "Restaurar", onclick: () => revisar([it.id], "restaurar")})] : []),
            ...(it.revision === "propuesto" ? [el("button", {className: "sec sm", textContent: "Aprobar", onclick: () => revisar([it.id], "aprobar")}), el("button", {className: "link", textContent: "Descartar", onclick: () => revisar([it.id], "descartar")})] : []),
            el("button", {className: "link", textContent: "Ficha", onclick: () => { S.open = it.id; pintaFicha(); }})));
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
        el("div", {className: "int-fs"}, campo("Nombre", "titulo", "t"), campo("Rol", "campos.rol", "t"), campo("Organización", "campos.organizacion", "t"), campo("Poder (1-5)", "campos.poder", "n"), campo("Interés (1-5)", "campos.interes", "n"),
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
    await cargar();
    return [raiz];
  }
  document.addEventListener("DOMContentLoaded", () => { FVISTAS.interesados = vista; });
  if (typeof module !== "undefined") module.exports = {quad, parecidos, vista};  // solo para pruebas en node
})();
