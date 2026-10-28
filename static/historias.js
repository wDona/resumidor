// Vista «historias» (F4). FVISTAS.historias = (c, e) => [nodes]  (c = carpeta, e = expediente).
// carpeta.js (que define FVISTAS) se carga DESPUÉS de este fichero: registra dentro de DOMContentLoaded.
// Tablero kanban (drag&drop nativo) | Tabla (registroTabla) + editor de criterios Gherkin con vista previa .feature.
(() => {
  const ESTADOS = ["backlog", "preparada", "en curso", "hecha"], REVS = [["", "Todas"], ["propuesto", "Propuestas"], ["aprobado", "Aprobadas"]];
  const FMT = [["docx", "Word (.docx)"], ["pdf", "PDF"], ["xlsx", "Excel (.xlsx)"], ["csv", "CSV"], ["md", "Markdown"], ["json", "JSON"], ["feature", "Gherkin (.feature)"], ["csv_jira", "Jira (.csv)"], ["csv_azure", "Azure DevOps (.csv)"]];
  const err = x => aviso(x.message || String(x));
  const cm = it => it.campos || {};
  const crits = it => Array.isArray(cm(it).criterios) ? cm(it).criterios : [];
  const derivada = it => it.origen === "derivado";
  const PUNTOS = it => Number(cm(it).puntos) || 0;

  function menuExportar(c, vista, fmts) {  // contrato: GET /api/reg/exportar?c&vista&fmt&borrador
    const solo = el("input", {type: "checkbox"}), nota = el("small", {className: "muted", textContent: "Lo no revisado sale marcado BORRADOR"}), det = el("details", {className: "menu rq-exp"});
    solo.onchange = () => nota.textContent = solo.checked ? "" : "Lo no revisado sale marcado BORRADOR";
    const ir = async fmt => {
      det.open = false;
      try {
        const r = await fetch("/api/reg/exportar?" + new URLSearchParams({c, vista, fmt, borrador: solo.checked ? 0 : 1}));
        if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(r.status === 404 ? "Exportación no disponible todavía (" + fmt + ")" : j.detail || r.statusText); }
        const nombre = decodeURIComponent((/filename\*=UTF-8''(.+)/.exec(r.headers.get("Content-Disposition") || "") || [])[1] || vista + "." + (fmt.startsWith("csv") ? "csv" : fmt));
        const a = el("a", {href: URL.createObjectURL(await r.blob()), download: nombre}); document.body.append(a); a.click(); a.remove(); aviso("Descargado: " + nombre);
      } catch (x) { err(x); }
    };
    det.append(el("summary", {className: "sec sm", textContent: "Exportar ▾"}), el("div", {className: "rq-exp-p"}, el("label", {className: "rq-chk"}, solo, " Solo aprobados"), nota,
      ...fmts.map(([f, t]) => el("button", {className: "link", textContent: t, onclick: () => ir(f)}))));
    return det;
  }

  // texto .feature en español (la 2.ª línea y siguientes de Dado/Cuando/Entonces salen como «Y»)
  function feature(titulo, k, cr) {
    const L = ["# language: es", "Característica: " + (titulo || ""), ...(k.como ? ["  Como " + k.como] : []), ...(k.quiero ? ["  Quiero " + k.quiero] : []), ...(k.para ? ["  Para " + k.para] : [])];
    for (const x of cr) {
      L.push("", "  Escenario: " + (x.escenario || ""));
      for (const [kw, f] of [["Dado", x.dado], ["Cuando", x.cuando], ["Entonces", x.entonces]]) String(f || "").split("\n").filter(s => s.trim()).forEach((s, i) => L.push("    " + (i ? "Y" : kw) + " " + s.trim()));
    }
    return L.join("\n");
  }

  function vista(c) {
    const fo = typeof fTomaFoco === "function" ? fTomaFoco("historias") : null;  // foco desde el informe
    const S = {all: [], f: {epica: "", req: globalThis.histFiltroReq || "", rev: fo ? "" : lsGet("hu-rev", "")}, modo: lsGet("hu-modo", "tablero"), ed: null, tabla: null, ids: fo?.ids || null, resaltar: !!fo};
    globalThis.histFiltroReq = "";
    let seq = 0;
    const raiz = el("div", {className: "hu"}), cab = el("div", {className: "reg-bar"}), filtros = el("div", {className: "reg-bar"}), cuerpo = el("div", {className: "hu-body"}), panel = el("aside", {className: "reg-hist hu-ed", hidden: true});
    raiz.append(cab, filtros, cuerpo, panel);

    async function cargar() {
      const n = ++seq;
      try {
        const r = await api("/api/reg?" + new URLSearchParams({c}));
        if (n !== seq) return;
        S.all = r.items; S.byId = Object.fromEntries(r.items.map(x => [x.id, x]));
        pintar();
      } catch (x) { if (n === seq) cuerpo.replaceChildren(el("p", {className: "err", textContent: x.message})); }
    }
    const hus = () => S.all.filter(x => x.tipo === "historia");
    const reqDe = it => { for (const r of it.relaciones || []) if (r.tipo === "deriva_de") { const o = S.byId[r.a === it.id ? r.b : r.a]; if (o?.tipo === "requisito") return o; } return null; };
    const visibles = () => hus().filter(x => (!S.ids || S.ids.includes(x.id)) && (!S.f.rev || x.revision === S.f.rev) && (!S.f.epica || cm(x).epica === S.f.epica) && (!S.f.req || reqDe(x)?.id === S.f.req));

    // solo claves de campos que cambian: el servidor fusiona sobre los vigentes
    const dif = (prev, cambios) => cambios.campos ? {...cambios, campos: Object.fromEntries(Object.entries(cambios.campos).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(prev.campos[k])))} : cambios;
    async function patch(it, cambios, opt = {}) {
      const prev = {...it, campos: {...cm(it)}};
      Object.assign(it, cambios); it.editado = true;
      if (!opt.sinPintar) pintar();
      try { Object.assign(it, await api("/api/reg/" + encodeURIComponent(it.id), {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({c, cambios: dif(prev, cambios)})})); return true; }
      catch (x) { Object.assign(it, prev); err(x); return false; }
      finally { if (!opt.sinPintar) pintar(); }
    }
    const revisar = async (ids, accion) => { try { await post("/api/reg/revisar", {c, ids, accion}); aviso((accion === "aprobar" ? "Aprobada" : "Descartada") + ". Ctrl+Z para deshacer"); panel.hidden = true; await cargar(); } catch (x) { err(x); } };
    const deshacer = async () => { try { const r = await post("/api/reg/deshacer", {c}); aviso(r.revertidas ? "Deshecho (" + r.revertidas + ")" : "Nada que deshacer"); await cargar(); } catch (x) { err(x); } };
    const aRequisito = () => { ftab = "requisitos"; lsSet("ftab", ftab); fsucio = true; pintarHome(); };

    // ---- tablero ----
    function tarjeta(it) {
      const k = cm(it), rq = reqDe(it), cr = crits(it), pend = cr.filter(x => x.propuesta).length;
      const card = el("article", {className: "hu-card" + (it.revision === "propuesto" ? " prop" : ""), draggable: true, tabIndex: 0, "data-id": it.id, role: "button", ariaLabel: "Abrir " + (it.codigo || "") + " " + it.titulo},
        el("div", {className: "hu-top"}, el("b", {textContent: it.codigo || ""}), ...(k.epica ? [el("span", {className: "hu-ep", textContent: k.epica})] : []), el("span", {className: "grow"}), ...(PUNTOS(it) ? [el("span", {className: "hu-pts", textContent: PUNTOS(it) + " pt", title: "Puntos de historia"})] : [])),
        el("div", {className: "hu-txt"}, ...(k.como || k.quiero || k.para ? [el("span", {}, el("i", {textContent: "Como "}), k.como || "…"), el("span", {}, el("i", {textContent: "quiero "}), k.quiero || "…"), el("span", {}, el("i", {textContent: "para "}), k.para || "…")] : [it.titulo])),
        ...(derivada(it) ? [el("small", {className: "hu-der-c", textContent: "Propuesta, no dicha en la reunión"})] : []),
        el("div", {className: "hu-pie"}, ...regInsignias(it),
          ...(rq ? [el("button", {className: "link", textContent: "↖ " + rq.codigo, title: rq.titulo + " · filtrar por este requisito", onclick: ev => { ev.stopPropagation(); S.f.req = rq.id; pintar(); }})] : []),
          ...(cr.length ? [el("small", {className: "muted", textContent: cr.length + (cr.length === 1 ? " criterio" : " criterios") + (pend ? " (" + pend + " por revisar)" : "")})] : [])));
      const mv = el("select", {className: "hu-mv", ariaLabel: "Mover " + it.codigo + " a", onclick: ev => ev.stopPropagation(), onchange: () => patch(it, {estado: mv.value})}, ...ESTADOS.map(x => new Option(x, x))); mv.value = it.estado;
      card.append(mv);
      card.ondragstart = ev => { ev.dataTransfer.setData("text/plain", it.id); ev.dataTransfer.effectAllowed = "move"; card.classList.add("arr"); };
      card.ondragend = () => card.classList.remove("arr");
      card.onclick = () => editor(it);
      card.onkeydown = ev => { if (ev.target === card && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); editor(it); } };
      return card;
    }
    function tablero(xs) {
      return el("div", {className: "hu-tab"}, ...ESTADOS.map(est => {
        const l = xs.filter(x => (ESTADOS.includes(x.estado) ? x.estado : "backlog") === est), pts = l.reduce((a, x) => a + PUNTOS(x), 0);
        const col = el("section", {className: "hu-col", "data-estado": est, ariaLabel: est},
          el("h3", {}, est, el("span", {className: "badge", textContent: l.length, title: "WIP: historias en esta columna"}), ...(pts ? [el("small", {className: "muted", textContent: pts + " pt"})] : [])),
          el("div", {className: "hu-lst"}, ...(l.length ? l.map(tarjeta) : [el("p", {className: "muted hu-vacio", textContent: "Arrastra aquí"})])));
        col.ondragover = ev => { ev.preventDefault(); col.classList.add("over"); };
        col.ondragleave = ev => { if (!col.contains(ev.relatedTarget)) col.classList.remove("over"); };
        col.ondrop = ev => { ev.preventDefault(); col.classList.remove("over"); const it = S.byId[ev.dataTransfer.getData("text/plain")]; if (it && it.estado !== est) patch(it, {estado: est}); };
        return col;
      }));
    }

    function pintar() {
      const todas = hus(), xs = visibles(), epicas = [...new Set(todas.map(x => cm(x).epica).filter(Boolean))].sort();
      const reqs = [...new Map(todas.map(reqDe).filter(Boolean).map(r => [r.id, r])).values()].sort((a, b) => a.codigo.localeCompare(b.codigo, "es", {numeric: true}));
      const sel = (lab, v, ops, set) => { const s = el("select", {ariaLabel: lab, onchange: () => { set(s.value); pintar(); }}, new Option(lab, ""), ...ops.map(([k, t]) => new Option(t, k))); s.value = v; return s; };
      cab.replaceChildren(el("div", {className: "row", role: "group", ariaLabel: "Modo"}, ...[["tablero", "Tablero"], ["tabla", "Tabla"]].map(([k, t]) => el("button", {className: "f-pill", "aria-pressed": S.modo === k, textContent: t, onclick: () => { S.modo = k; lsSet("hu-modo", k); pintar(); }}))),
        el("span", {className: "grow"}), el("button", {className: "sec", textContent: "Deshacer", title: "Ctrl+Z", onclick: deshacer}),
        el("button", {className: "sec", textContent: "+ Añadir", onclick: async () => { try { await post("/api/reg", {c, tipo: "historia", titulo: "Nueva historia", estado: "backlog"}); await cargar(); } catch (x) { err(x); } }}), menuExportar(c, "historias", FMT));
      filtros.replaceChildren(sel("Todas las épicas", S.f.epica, epicas.map(e => [e, e]), v => S.f.epica = v), sel("Todos los requisitos", S.f.req, reqs.map(r => [r.id, r.codigo + " · " + r.titulo.slice(0, 40)]), v => S.f.req = v),
        ...(S.modo === "tablero" ? [...REVS.map(([k, t]) => el("button", {className: "f-pill", "aria-pressed": S.f.rev === k, textContent: t + " · " + (k ? todas.filter(x => x.revision === k).length : todas.length), onclick: () => { S.f.rev = k; lsSet("hu-rev", k); pintar(); }})),
        el("span", {className: "grow"}), el("small", {className: "muted", textContent: xs.length + " de " + todas.length + " historias · " + xs.reduce((a, x) => a + PUNTOS(x), 0) + " pt"})] : []),
        ...(S.ids && S.modo === "tablero" ? [fChipFoco(xs.length, () => { S.ids = null; pintar(); }, fo?.etiqueta)] : []));
      if (S.resaltar) { S.resaltar = false; fResaltaIds(cuerpo, S.ids); }
      if (S.modo === "tabla") {
        const w = el("div"); cuerpo.replaceChildren(w);
        registroTabla(w, {c, tipo: "historia", onChange: cargar, ...(S.ids ? {foco: {ids: S.ids, etiqueta: fo?.etiqueta}} : {}), filtro: its => its.filter(x => (!S.f.epica || cm(x).epica === S.f.epica) && (!S.f.req || reqDe(x)?.id === S.f.req)), columnas: [{k: "codigo", label: "Código", w: 90}, {k: "titulo", label: "Historia", tipo: "area"}, {k: "estado", label: "Estado", tipo: "select", opciones: ESTADOS},
          {k: "campos.epica", label: "Épica"}, {k: "req", label: "Requisito", render: it => reqDe(it)?.codigo || ""}, {k: "campos.puntos", label: "Puntos", tipo: "num", w: 70}], vacio: "Aún no hay historias. Se derivan de los requisitos (F5) o puedes añadirlas a mano."});
        return;
      }
      cuerpo.replaceChildren(todas.length ? tablero(xs) : el("div", {className: "vacio", textContent: "Aún no hay historias. Se derivan de los requisitos o puedes añadirlas con «+ Añadir»."}));
    }

    // ---- editor: como/quiero/para + épica + puntos + criterios Gherkin con vista previa ----
    function editor(it) {
      const d = {titulo: it.titulo, estado: it.estado, k: {como: "", quiero: "", para: "", epica: "", puntos: "", ...cm(it)}, cr: crits(it).map(x => ({escenario: "", dado: "", cuando: "", entonces: "", ...x}))};
      const rq = reqDe(it), prev = el("pre", {className: "hu-prev", tabIndex: 0, ariaLabel: "Vista previa del .feature"}), lista = el("div", {className: "hu-crs"});
      const refresca = () => { prev.textContent = feature(d.titulo, d.k, d.cr); };
      const fld = (lab, ctl) => el("label", {className: "field"}, el("span", {textContent: lab}), ctl);
      const inp = (obj, key, tag = "input", extra = {}) => { const x = el(tag, {value: obj[key] ?? "", ...(tag === "textarea" ? {rows: 2} : {}), ...extra}); x.oninput = () => { obj[key] = extra.type === "number" ? (x.value === "" ? "" : Number(x.value)) : x.value; refresca(); }; return x; };
      function pintaCr() {
        lista.replaceChildren(...d.cr.map((x, i) => el("fieldset", {className: "hu-cr" + (x.propuesta ? " prop" : "")},
          el("legend", {}, "Escenario " + (i + 1), ...(x.propuesta ? [el("span", {className: "badge acc", textContent: "propuesto por la IA"})] : [])),
          fld("Escenario", inp(x, "escenario")), fld("Dado", inp(x, "dado", "textarea")), fld("Cuando", inp(x, "cuando", "textarea")), fld("Entonces", inp(x, "entonces", "textarea")),
          el("div", {className: "row"}, ...(x.propuesta ? [el("button", {className: "sec sm", textContent: "Aceptar criterio", onclick: () => { x.propuesta = false; pintaCr(); }})] : []), el("span", {className: "grow"}),
            el("button", {className: "link", textContent: "Quitar", onclick: () => { d.cr.splice(i, 1); pintaCr(); refresca(); }})))),
          el("button", {className: "sec sm", textContent: "+ Añadir criterio", onclick: () => { d.cr.push({escenario: "", dado: "", cuando: "", entonces: ""}); pintaCr(); refresca(); }}));
      }
      const est = el("select", {ariaLabel: "Estado"}, ...ESTADOS.map(x => new Option(x, x))); est.value = ESTADOS.includes(it.estado) ? it.estado : "backlog"; est.onchange = () => d.estado = est.value;
      const guardar = async () => {
        const campos = {...cm(it), ...d.k, criterios: d.cr}, ok = await patch(it, {titulo: d.titulo, estado: d.estado, campos}, {sinPintar: true});
        if (ok) { aviso("Guardado. Ctrl+Z para deshacer"); panel.hidden = true; pintar(); } else pintar();
      };
      panel.hidden = false;
      panel.replaceChildren(el("div", {className: "sec-h"}, el("h3", {textContent: (it.codigo || "") + " · historia"}), el("button", {className: "sec sm", textContent: "Cerrar", onclick: () => panel.hidden = true})),
        ...(derivada(it) ? [el("p", {className: "aviso w hu-der", textContent: "Propuesta, no dicha en la reunión"})] : []), el("div", {className: "reg-ins"}, ...regInsignias(it)),
        ...(rq ? [el("p", {}, "Deriva de ", el("b", {textContent: rq.codigo}), " · " + rq.titulo + " ", el("button", {className: "link", textContent: "Ver requisitos", onclick: aRequisito}))] : []),
        fld("Título", inp(d, "titulo")), fld("Estado", est), fld("Como", inp(d.k, "como")), fld("Quiero", inp(d.k, "quiero", "textarea")), fld("Para", inp(d.k, "para", "textarea")),
        el("div", {className: "row"}, fld("Épica", inp(d.k, "epica", "input")), fld("Puntos", inp(d.k, "puntos", "input", {type: "number", min: 0}))),
        el("h4", {textContent: "Criterios de aceptación (Gherkin)"}), lista, el("h4", {textContent: "Vista previa · .feature"}), prev,
        el("div", {className: "row hu-pie2"}, el("button", {className: "pri", textContent: "Guardar", onclick: guardar}), ...(it.revision === "propuesto" ? [el("button", {className: "sec", textContent: "Aprobar historia", onclick: () => revisar([it.id], "aprobar")}), el("button", {className: "link", textContent: "Descartar", onclick: () => revisar([it.id], "descartar")})] : [])));
      pintaCr(); refresca();
    }
    raiz.addEventListener("keydown", ev => {
      const a = document.activeElement, enCampo = a && (/^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) || a.isContentEditable);
      if (ev.key === "Escape" && !panel.hidden) panel.hidden = true;
      else if (ev.ctrlKey && ev.key.toLowerCase() === "z" && !enCampo && S.modo === "tablero") { ev.preventDefault(); deshacer(); }
    });
    cargar();
    return raiz;
  }
  const reg = () => { FVISTAS.historias = (c) => [vista(c)]; };
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", reg) : reg();
})();
