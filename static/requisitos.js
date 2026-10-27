// Vista «requisitos» (F4). FVISTAS.requisitos = (c, e) => [nodes]  (c = carpeta, e = expediente).
// carpeta.js (que define FVISTAS) se carga DESPUÉS de este fichero: registra dentro de DOMContentLoaded.
// Tabla propia (no registroTabla) porque necesita agrupar, filtrar por MoSCoW, columna de trazabilidad y cajón de detalle;
// usa los mismos endpoints /api/reg/* y las mismas clases .reg-* para el aspecto.
(() => {
  const PRIO = ["Must", "Should", "Could", "Won't"], ESTADOS = ["borrador", "validado", "aprobado", "rechazado", "implementado"], TIPOS = ["funcional", "no funcional", "restricción"];
  const px = p => "rq-p-" + String(p || "ninguna").toLowerCase().replace(/[^a-z]/g, ""), ex = s => "rq-e-" + String(s || "").replace(/\s/g, "");
  const COLS = [
    {k: "codigo", label: "Código", ro: true}, {k: "titulo", label: "Requisito", tipo: "area"},
    {k: "campos.tipo_req", label: "Tipo", tipo: "select", ops: TIPOS}, {k: "prioridad", label: "Prioridad", tipo: "select", ops: PRIO, chip: px},
    {k: "campos.solicitante", label: "Solicitante", lista: "rq-dl-sol"}, {k: "estado", label: "Estado", tipo: "select", ops: ESTADOS, chip: ex},
    {k: "campos.criterios", label: "Criterios de aceptación", tipo: "area"}, {k: "campos.version", label: "Versión"}];
  const GRUPOS = [["", "Sin agrupar"], ["campos.solicitante", "Solicitante"], ["campos.tipo_req", "Tipo"], ["prioridad", "Prioridad"], ["estado", "Estado"]];
  const REVS = [["", "Todos"], ["propuesto", "Propuestos"], ["aprobado", "Aprobados"], ["descartado", "Descartados"]];
  const val = (it, k) => k.startsWith("campos.") ? (it.campos || {})[k.slice(7)] ?? "" : it[k] ?? "";
  const num = it => parseInt(String(it.codigo || "").replace(/\D/g, "")) || 0;
  const err = x => aviso(x.message || String(x));

  // Exportar ▾ (contrato: GET /api/reg/exportar?c&vista&fmt&borrador)
  function menuExportar(c, vista, fmts) {
    const solo = el("input", {type: "checkbox", id: "ex-solo-" + vista}), det = el("details", {className: "menu rq-exp"});
    const ir = async fmt => {
      det.open = false;
      try {
        const r = await fetch("/api/reg/exportar?" + new URLSearchParams({c, vista, fmt, borrador: solo.checked ? 0 : 1}));
        if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(r.status === 404 ? "Exportación no disponible todavía (" + fmt + ")" : j.detail || r.statusText); }
        const nombre = decodeURIComponent((/filename\*=UTF-8''(.+)/.exec(r.headers.get("Content-Disposition") || "") || [])[1] || vista + "." + fmt.replace(/^csv_.*/, "csv").replace("feature", "feature"));
        const a = el("a", {href: URL.createObjectURL(await r.blob()), download: nombre}); document.body.append(a); a.click(); a.remove(); aviso("Descargado: " + nombre);
      } catch (x) { err(x); }
    };
    det.append(el("summary", {className: "sec sm", textContent: "Exportar ▾"}), el("div", {className: "rq-exp-p"},
      el("label", {className: "rq-chk"}, solo, " Solo aprobados"), el("small", {className: "muted", textContent: solo.checked ? "" : "Lo no revisado sale marcado BORRADOR"}),
      ...fmts.map(([f, t]) => el("button", {className: "link", textContent: t, onclick: () => ir(f)}))));
    solo.onchange = () => det.querySelector("small").textContent = solo.checked ? "" : "Lo no revisado sale marcado BORRADOR";
    return det;
  }
  const FMT = [["docx", "Word (.docx)"], ["pdf", "PDF"], ["xlsx", "Excel (.xlsx)"], ["csv", "CSV"], ["md", "Markdown"], ["json", "JSON"], ["csv_jira", "Jira (.csv)"], ["csv_azure", "Azure DevOps (.csv)"]];

  function vista(c) {
    const S = {all: [], f: {q: "", estado: "", prio: "", rev: lsGet("rq-rev", "")}, grupo: lsGet("rq-grupo", ""), cerrados: new Set(), sel: new Set(), hu: {}, pr: {}, drawer: null};
    let seq = 0;
    const raiz = el("div", {className: "reg rq", tabIndex: -1}), cab = el("div", {className: "reg-bar"}), resumen = el("div", {className: "rq-sum"}), chips = el("div", {className: "reg-chips"}),
      acc = el("div", {className: "reg-acc"}), cuerpo = el("div", {className: "reg-wrap"}), dr = el("aside", {className: "reg-hist rq-dr", hidden: true}),
      dl = el("datalist", {id: "rq-dl-sol"});
    raiz.append(cab, resumen, chips, acc, cuerpo, dr, dl);

    async function cargar() {
      const n = ++seq;
      try {
        const [r, d] = await Promise.all([api("/api/reg?" + new URLSearchParams({c})), S.f.rev === "descartado" ? api("/api/reg?" + new URLSearchParams({c, tipo: "requisito", revision: "descartado"})) : null]);
        if (n !== seq) return;
        S.all = r.items; S.desc = d ? d.items : []; S.cont = r.contadores;
        const byId = Object.fromEntries(r.items.map(x => [x.id, x]));
        S.hu = {}; S.pr = {};
        for (const it of r.items) if (it.tipo === "requisito") for (const rel of it.relaciones || []) {
          const o = byId[rel.a === it.id ? rel.b : rel.a];
          if (!o) continue;
          if (rel.tipo === "deriva_de" && o.tipo === "historia") (S.hu[it.id] ||= []).push(o);
          else if (o.tipo === "pregunta" && !["hecho", "descartado"].includes(o.estado)) S.pr[it.id] = (S.pr[it.id] || 0) + 1;
        }
        dl.replaceChildren(...[...new Set(r.items.filter(x => x.tipo === "interesado").map(x => x.titulo))].map(v => el("option", {value: v})));
        S.sel = new Set([...S.sel].filter(id => byId[id]));
        pintar();
      } catch (x) { if (n === seq) cuerpo.replaceChildren(el("p", {className: "err", textContent: x.message})); }
    }
    const reqs = () => S.f.rev === "descartado" ? S.desc : S.all.filter(x => x.tipo === "requisito" && (!S.f.rev || x.revision === S.f.rev));
    const visibles = () => {
      const q = S.f.q.toLowerCase();
      return reqs().filter(x => (!S.f.estado || x.estado === S.f.estado) && (!S.f.prio || x.prioridad === S.f.prio) &&
        (!q || [x.codigo, x.titulo, x.detalle, val(x, "campos.solicitante"), val(x, "campos.criterios")].some(v => String(v || "").toLowerCase().includes(q)))).sort((a, b) => num(a) - num(b));
    };

    async function patch(it, k, v) {
      const antes = val(it, k);
      if (String(antes) === String(v)) return;
      const camp = k.startsWith("campos."), cambios = camp ? {campos: {[k.slice(7)]: v}} : {[k]: v};
      if (camp) (it.campos ||= {})[k.slice(7)] = v; else it[k] = v;
      it.editado = true;
      try { Object.assign(it, await api("/api/reg/" + encodeURIComponent(it.id), {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({c, cambios})})); }
      catch (x) { if (camp) it.campos[k.slice(7)] = antes; else it[k] = antes; err(x); }
      pintar();
    }
    const revisar = async (ids, accion) => {
      if (!ids.length) return;
      try { await post("/api/reg/revisar", {c, ids, accion}); aviso(({aprobar: "Aprobado", restaurar: "Restaurado"}[accion] || "Descartado") + " · " + ids.length + ". Ctrl+Z para deshacer"); S.sel.clear(); await cargar(); } catch (x) { err(x); }
    };
    const fusionar = async (destino, origenes) => { try { await post("/api/reg/fusionar", {c, destino, origenes}); aviso("Fusionado. Ctrl+Z para deshacer"); S.sel.clear(); await cargar(); } catch (x) { err(x); } };
    const deshacer = async () => { try { const r = await post("/api/reg/deshacer", {c}); aviso(r.revertidas ? "Deshecho (" + r.revertidas + ")" : "Nada que deshacer"); await cargar(); } catch (x) { err(x); } };
    const duplicar = async it => {
      try {
        const n = await post("/api/reg", {c, tipo: "requisito", titulo: it.titulo + " (copia)", detalle: it.detalle || "", estado: "borrador", prioridad: it.prioridad || "", campos: {...(it.campos || {}), huerfano: undefined}});
        aviso("Duplicado como " + (n.codigo || "nuevo")); await cargar();
      } catch (x) { err(x); }
    };
    const aHistorias = it => { globalThis.histFiltroReq = it.id; ftab = "historias"; lsSet("ftab", ftab); fsucio = true; pintarHome(); };

    function celda(it, col) {
      const v = val(it, col.k), t = col.tipo || "texto", f = {ariaLabel: col.label + " de " + (it.codigo || it.titulo)};
      if (col.ro || it.revision === "fusionado") return el("b", {textContent: v});
      let ctl;
      if (t === "select") {
        const ops = col.ops; ctl = el("select", {...f, className: col.chip ? "rq-chip " + col.chip(v) : ""}, new Option("—", ""), ...(v && !ops.includes(v) ? [v, ...ops] : ops).map(x => new Option(x, x))); ctl.value = v;
        ctl.onchange = () => { if (col.chip) ctl.className = "rq-chip " + col.chip(ctl.value); patch(it, col.k, ctl.value); };
      } else {
        ctl = t === "area" ? el("textarea", {...f, rows: 2, value: v}) : el("input", {...f, type: "text", value: v});
        if (col.lista) ctl.setAttribute("list", col.lista);
        ctl.onchange = () => patch(it, col.k, ctl.value);
        if (t === "area") ctl.onkeydown = ev => { if (ev.key === "Escape") ctl.blur(); };
      }
      return ctl;
    }
    function traza(it) {
      const hs = S.hu[it.id] || [], np = S.pr[it.id] || 0;
      return el("span", {className: "rq-tz"}, el("button", {className: "link", textContent: hs.length + (hs.length === 1 ? " historia" : " historias"), title: hs.length ? hs.map(h => h.codigo).join(", ") + " · ver en Historias" : "Sin historias derivadas", disabled: !hs.length, onclick: () => aHistorias(it)}),
        ...(np ? [el("span", {className: "badge w", textContent: np + (np === 1 ? " pregunta abierta" : " preguntas abiertas"), title: "Preguntas abiertas relacionadas"})] : []));
    }
    function fila(it) {
      const chk = el("input", {type: "checkbox", checked: S.sel.has(it.id), ariaLabel: "Seleccionar " + it.codigo, onchange: () => { chk.checked ? S.sel.add(it.id) : S.sel.delete(it.id); pintarAcc(); }});
      const cit = (it.citas || [])[0], or = el("span", {className: "reg-or"}, cit?.mid ? fLink({mid: cit.mid, ver: cit.ver, t: cit.t}, "[" + mmss(cit.t || 0) + "]") : el("span", {className: "muted", textContent: it.origen === "manual" ? "—" : "sin cita"}));
      return el("tr", {className: "reg-r" + (it.revision === "propuesto" ? " prop" : "") + (it.revision === "descartado" || it.revision === "fusionado" ? " cerr" : ""), tabIndex: 0, "data-id": it.id},
        el("td", {className: "c"}, chk), ...COLS.map(col => el("td", {}, celda(it, col))), el("td", {}, traza(it)), el("td", {}, or), el("td", {className: "reg-ins"}, ...regInsignias(it)),
        el("td", {className: "reg-ops"},
          ...(it.revision === "descartado" ? [el("button", {className: "sec sm", textContent: "Restaurar", onclick: () => revisar([it.id], "restaurar")})] : []),
          ...(it.revision === "propuesto" ? [el("button", {className: "sec sm", textContent: "Aprobar", onclick: () => revisar([it.id], "aprobar")}), el("button", {className: "link", textContent: "Descartar", onclick: () => revisar([it.id], "descartar")})] : []),
          el("button", {className: "link", textContent: "Detalle", onclick: () => detalle(it)}), el("button", {className: "link", textContent: "Duplicar", onclick: () => duplicar(it)})));
    }
    function pintarAcc() {
      const n = S.sel.size, ids = [...S.sel];
      const dest = el("select", {ariaLabel: "Fusionar con", hidden: true}, new Option("Fusionar con…", ""), ...reqs().filter(x => !S.sel.has(x.id)).map(x => new Option(x.codigo + " · " + x.titulo.slice(0, 60), x.id)));
      dest.onchange = () => dest.value && fusionar(dest.value, ids);
      acc.replaceChildren(el("button", {className: "sec", textContent: "Deshacer", title: "Ctrl+Z", onclick: deshacer}), el("span", {className: "grow"}),
        ...(n ? [el("span", {className: "muted", textContent: n + (n === 1 ? " seleccionado" : " seleccionados")}), el("button", {className: "pri sm", textContent: "Aprobar", onclick: () => revisar(ids, "aprobar")}),
          el("button", {className: "sec sm", textContent: "Descartar", onclick: () => revisar(ids, "descartar")}), el("button", {className: "sec sm", textContent: "Fusionar con…", onclick: () => { dest.hidden = false; dest.focus(); }}), dest] : []));
    }
    function barra(base) {  // resumen MoSCoW apilado; clic = filtrar
      const cnt = Object.fromEntries(PRIO.map(p => [p, 0])); let sin = 0;
      for (const x of base) x.prioridad in cnt ? cnt[x.prioridad]++ : sin++;
      const tot = base.length || 1, seg = (p, n) => el("button", {className: "rq-seg " + px(p), style: "flex:" + n + " 1 0", "aria-pressed": S.f.prio === p, textContent: n + " " + p, title: "Filtrar por " + p, onclick: () => { S.f.prio = S.f.prio === p ? "" : p; pintar(); }});
      return [el("div", {className: "rq-bar", role: "group", "aria-label": "Resumen MoSCoW"}, ...PRIO.filter(p => cnt[p]).map(p => seg(p, cnt[p])), ...(sin ? [el("span", {className: "rq-seg " + px(""), style: "flex:" + sin + " 1 0", textContent: sin + " sin prioridad"})] : []),
        ...(base.length ? [] : [el("span", {className: "muted", textContent: "Sin requisitos"})])), el("small", {className: "muted", textContent: base.length + " requisitos" + (S.f.prio ? " · filtrando " + S.f.prio : "")})];
    }
    // «Derivar historias» (F5): encola /api/reg/derivar con los seleccionados o, sin selección, los que aún no tienen historias; al terminar,
    // carpetaTrasCola recarga la pestaña (mismo patrón que «Regenerar con IA» de carpeta.js)
    const dinfo = el("small", {className: "muted"});
    const dEstado = () => api("/api/reg/derivar/estado?c=" + encodeURIComponent(c)).then(r => {
      const u = r.ultimo, cr = u?.creadas || {};
      dinfo.textContent = r.en_cola ? "Derivando… (en cola)" : u ? "Última derivación: " + (cr.historia || 0) + " historias · " + (cr.pregunta || 0) + " preguntas · " + u.llamadas + " llamadas" + (u.coste ? " · US$" + u.coste.toFixed(3) : "") : "";
    }).catch(() => {});
    function derivarBtn() {
      const vivos = () => S.all.filter(x => x.tipo === "requisito" && !["descartado", "fusionado"].includes(x.revision)), nb = () => { try { return nubeParams("q") || nubeParams("f"); } catch { return null; } };
      const b = el("button", {className: "sec sm", textContent: "Derivar historias", disabled: !vivos().length,
        title: vivos().length ? "La IA propone historias, criterios Gherkin y preguntas abiertas de los requisitos seleccionados o, sin selección, de los que aún no tienen historias" : "No hay requisitos",
        onclick: async () => {
          const ids = [...S.sel].filter(id => vivos().some(x => x.id === id));
          if (!ids.length && !vivos().some(x => !(S.hu[x.id] || []).length)) return aviso("Todos los requisitos tienen historias: selecciona los que quieras volver a derivar");
          b.disabled = true;
          try { await fEnCola("/api/reg/derivar", {c, ...(ids.length ? {ids} : {}), ...(nb() ? {nube: nb()} : {})}); dEstado(); } catch (x) { err(x); } finally { b.disabled = false; }
        }});
      return b;
    }
    dEstado();
    function pintar() {
      const base = reqs(), xs = visibles(), co = S.cont?.por_revision || {};
      cab.replaceChildren(el("input", {type: "search", value: S.f.q, placeholder: "Buscar…", ariaLabel: "Buscar", oninput: ev => { S.f.q = ev.target.value; clearTimeout(pintar.t); pintar.t = setTimeout(() => { const p = ev.target.selectionStart; pintar(); const i = cab.querySelector("input"); i.focus(); i.setSelectionRange(p, p); }, 250); }}),
        (() => { const s = el("select", {ariaLabel: "Estado", onchange: ev => { S.f.estado = ev.target.value; pintar(); }}, new Option("Todos los estados", ""), ...ESTADOS.map(x => new Option(x, x))); s.value = S.f.estado; return s; })(),
        (() => { const s = el("select", {ariaLabel: "Agrupar por", onchange: ev => { S.grupo = ev.target.value; lsSet("rq-grupo", S.grupo); pintar(); }}, ...GRUPOS.map(([k, t]) => new Option(k ? "Agrupar: " + t : t, k))); s.value = S.grupo; return s; })(),
        el("span", {className: "grow"}),
        derivarBtn(), dinfo,
        el("button", {className: "sec", textContent: "+ Añadir", onclick: async () => { try { await post("/api/reg", {c, tipo: "requisito", titulo: "Nuevo requisito", estado: "borrador"}); await cargar(); } catch (x) { err(x); } }}),
        menuExportar(c, "requisitos", FMT));
      resumen.replaceChildren(...barra(base));
      chips.replaceChildren(...REVS.map(([k, t]) => el("button", {className: "f-pill", "aria-pressed": S.f.rev === k, textContent: t + " · " + (k ? co[k] ?? 0 : (co.propuesto ?? 0) + (co.aprobado ?? 0)), onclick: () => { S.f.rev = k; lsSet("rq-rev", k); cargar(); }})));
      pintarAcc();
      const todos = el("input", {type: "checkbox", ariaLabel: "Seleccionar todo", checked: xs.length > 0 && xs.every(x => S.sel.has(x.id)), onchange: ev => { S.sel = ev.target.checked ? new Set(xs.map(i => i.id)) : new Set(); pintar(); }});
      if (!xs.length) { cuerpo.replaceChildren(el("div", {className: "vacio", textContent: "No hay requisitos con estos filtros. La IA los propone al poblar el proyecto; también puedes usar «+ Añadir»."})); return; }
      const tb = [];
      if (!S.grupo) tb.push(el("tbody", {}, ...xs.map(fila)));
      else {
        const g = new Map();
        for (const x of xs) { const k = val(x, S.grupo) || "(sin " + GRUPOS.find(a => a[0] === S.grupo)[1].toLowerCase() + ")"; (g.get(k) || g.set(k, []).get(k)).push(x); }
        const ord = S.grupo === "prioridad" ? k => PRIO.indexOf(k) < 0 ? 9 : PRIO.indexOf(k) : S.grupo === "estado" ? k => ESTADOS.indexOf(k) < 0 ? 9 : ESTADOS.indexOf(k) : () => 0;
        for (const [k, l] of [...g].sort((a, b) => ord(a[0]) - ord(b[0]) || a[0].localeCompare(b[0], "es"))) {
          const cerr = S.cerrados.has(k);
          tb.push(el("tbody", {className: "rq-g"}, el("tr", {className: "rq-gh"}, el("td", {colSpan: COLS.length + 5}, el("button", {className: "link", "aria-expanded": !cerr, textContent: (cerr ? "▸ " : "▾ ") + k + " · " + l.length, onclick: () => { cerr ? S.cerrados.delete(k) : S.cerrados.add(k); pintar(); }}))),
            ...(cerr ? [] : l.map(fila))));
        }
      }
      cuerpo.replaceChildren(el("table", {className: "reg-t"}, el("thead", {}, el("tr", {}, el("th", {className: "c"}, todos), ...COLS.map(col => el("th", {scope: "col", textContent: col.label})), el("th", {textContent: "Trazabilidad"}), el("th", {textContent: "Origen"}), el("th", {textContent: "Revisión"}), el("th"))), ...tb));
    }
    // cajón de detalle: todos los campos + citas + historial
    async function detalle(it) {
      S.drawer = it.id; dr.hidden = false;
      const campo = (col, extra) => el("div", {className: "field"}, el("label", {textContent: col.label}), celda(it, col), ...(extra ? [extra] : []));
      const hist = el("div", {className: "rq-hist"}, el("p", {className: "muted", textContent: "Cargando historial…"}));
      dr.replaceChildren(el("div", {className: "sec-h"}, el("h3", {textContent: it.codigo + " · detalle"}), el("button", {className: "sec sm", textContent: "Cerrar", onclick: () => { dr.hidden = true; S.drawer = null; }})),
        el("div", {className: "reg-ins"}, ...regInsignias(it)), ...COLS.filter(x => !x.ro).map(col => campo(col)), campo({k: "detalle", label: "Detalle", tipo: "area"}),
        el("h4", {textContent: "Trazabilidad"}), el("div", {}, traza(it)), el("ul", {className: "f-lst"}, ...(S.hu[it.id] || []).map(h => el("li", {textContent: h.codigo + " · " + h.titulo}))),
        el("h4", {textContent: "Citas"}), ...((it.citas || []).length ? it.citas.map(ci => el("blockquote", {}, "«" + (ci.texto || "") + "» ", ci.mid ? fLink({mid: ci.mid, ver: ci.ver, t: ci.t}, "[" + mmss(ci.t || 0) + "]") : "", ci.verificada === false ? el("span", {className: "badge w", textContent: "cita sin verificar"}) : "")) : [el("p", {className: "muted", textContent: "Sin cita."})]),
        el("h4", {textContent: "Historial"}), hist);
      try {
        const h = await api("/api/reg/" + encodeURIComponent(it.id) + "/historial?c=" + encodeURIComponent(c));
        hist.replaceChildren(...(h.length ? h.map(x => el("div", {className: "reg-h"}, el("b", {textContent: x.accion}), el("small", {className: "muted", textContent: " " + new Date(x.t * (x.t < 1e11 ? 1000 : 1)).toLocaleString("es")}),
          el("div", {textContent: [x.antes && "Antes: " + (typeof x.antes === "string" ? x.antes : JSON.stringify(x.antes)), x.despues && "Después: " + (typeof x.despues === "string" ? x.despues : JSON.stringify(x.despues))].filter(Boolean).join("  →  ")}))) : [el("p", {className: "muted", textContent: "Sin cambios registrados."})]));
      } catch (x) { hist.replaceChildren(el("p", {className: "err", textContent: x.message})); }
    }
    raiz.addEventListener("keydown", ev => {
      const a = document.activeElement, enCampo = a && (/^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) || a.isContentEditable);
      if (ev.key === "Escape" && !dr.hidden && !enCampo) { dr.hidden = true; return; }
      if (ev.ctrlKey && ev.key.toLowerCase() === "z" && !enCampo) { ev.preventDefault(); deshacer(); }
    });
    cargar();
    return raiz;
  }
  const reg = () => { FVISTAS.requisitos = (c) => [vista(c)]; if (typeof KIND === "object") KIND.derivar = "Derivar historias de requisitos"; };
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", reg) : reg();
})();
