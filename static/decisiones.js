// Vista «decisiones» (F4): línea de tiempo estilo ADR + tabla compacta. FVISTAS.decisiones = (c, e) => [nodos].
// IA primero: las decisiones llegan «propuesto» con cita verificada; el humano revisa, edita (un PATCH = un paso deshacible) y exporta.
// Contrato: /api/reg (tipo=decision), /api/reg/bandeja (relaciones_propuestas), /api/reg/relacion, /api/reg/revisar|fusionar|deshacer, /api/reg/exportar.
(() => {
  const ESTADOS = ["vigente", "sustituida", "revocada"], CHIP = {vigente: "ok", sustituida: "w", revocada: "no"};
  const FORMATOS = [["docx", "Word (.docx)"], ["pdf", "PDF"], ["xlsx", "Excel (.xlsx)"], ["csv", "CSV"], ["md", "Markdown"], ["json", "JSON"]];
  const REVS = [["", "Todas"], ["propuesto", "Propuestas"], ["aprobado", "Aprobadas"], ["descartado", "Descartadas"], ["fusionado", "Fusionadas"]];
  const enc = encodeURIComponent, cam = (it, k) => (it.campos || {})[k] ?? "";
  const estado = it => it.estado || "vigente";
  // la fecha editada se guarda en fecha_alta (y se duplica en campos.fecha, que manda en filas antiguas)
  const fecha = it => cam(it, "fecha") || it.fecha_alta || (it.creado ? new Date(it.creado * 1000).toISOString().slice(0, 10) : "");
  const num = it => parseInt(String(it.codigo || "").replace(/\D/g, ""), 10) || 0;
  const fechaTxt = f => { const d = new Date(f + "T00:00:00"); return isNaN(d) ? (f || "Sin fecha") : d.toLocaleDateString("es", {weekday: "long", day: "numeric", month: "long", year: "numeric"}); };
  const err = e => aviso(e.message || String(e));
  const enCampo = () => { const a = document.activeElement; return a && (/^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) || a.isContentEditable); };
  let ACTIVA = null;
  document.addEventListener("keydown", e => {
    if (ACTIVA && !ACTIVA.isConnected) ACTIVA = null;
    if (ACTIVA && e.ctrlKey && !e.shiftKey && e.key.toLowerCase() === "z" && !enCampo() && !document.activeElement?.closest?.(".reg")) { e.preventDefault(); ACTIVA.deshacer(); }
  });

  function vista(c, e) {
    const S = {items: [], rels: [], prop: [], vista: lsGet("dec-vista", "linea"), asc: lsGet("dec-asc", false), vig: lsGet("dec-vig", false), soloAprob: lsGet("dec-aprob", false),
      f: {estado: "", dueno: "", revision: "", q: ""}, ctx: new Set(), edit: null, drawer: null, fusion: null};
    const fo = typeof fTomaFoco === "function" ? fTomaFoco("decisiones") : null;  // foco desde el informe
    if (fo) { S.ids = fo.ids; S.resaltar = true; S.vig = false; S.vista = "linea"; }
    const raiz = el("div", {className: "dec"}), barra = el("div", {className: "dec-bar"}), banner = el("div"), cuerpo = el("div", {className: "dec-cuerpo"}), cajon = el("aside", {className: "dec-draw", hidden: true, "aria-label": "Detalle de la decisión"});
    raiz.append(barra, banner, cuerpo, cajon); ACTIVA = raiz; raiz.deshacer = deshacer;
    let seq = 0;

    async function cargar() {
      const n = ++seq;
      try {
        const [r, b] = await Promise.all([api("/api/reg?" + new URLSearchParams({c, tipo: "decision", ...(S.f.revision ? {revision: S.f.revision} : {})})), api("/api/reg/bandeja?c=" + enc(c))]);
        if (n !== seq) return;
        S.items = r.items; S.prop = b.relaciones_propuestas || []; S.nFus = r.contadores?.fusionadas ?? 0;
        S.rels = S.items.flatMap(x => x.relaciones || []).filter(r => r.tipo === "sustituye" && !r.propuesta);
        if (S.edit && !S.items.some(x => x.id === S.edit)) S.edit = null;
        pintar();
      } catch (x) { if (n === seq) cuerpo.replaceChildren(el("p", {className: "err", textContent: x.message})); }
    }
    const refrescar = async () => { await cargar(); if (S.drawer) abrirCajon(S.drawer); };
    const porId = id => S.items.find(x => x.id === id);
    // sustPor(b) = a (a es la más nueva); sustA(a) = [b...]
    const sustPor = id => S.rels.find(r => r.b === id)?.a, sustA = id => [...new Set(S.rels.filter(r => r.a === id).map(r => r.b))];

    async function deshacer() { try { const r = await post("/api/reg/deshacer", {c}); aviso(r.revertidas ? "Deshecho (" + r.revertidas + ")" : "Nada que deshacer"); await refrescar(); } catch (x) { err(x); } }
    async function revisar(ids, accion) { try { await post("/api/reg/revisar", {c, ids, accion}); aviso(({aprobar: "Aprobada", restaurar: "Restaurada"}[accion] || "Descartada") + ". Ctrl+Z para deshacer"); await refrescar(); } catch (x) { err(x); } }
    async function patch(it, cambios) { try { await api("/api/reg/" + enc(it.id), {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({c, cambios})}); return true; } catch (x) { err(x); return false; } }
    function fusionar(destino, origen) { S.fusion = null; pintar(); regDialogoFusion(c, [porId(destino), porId(origen)], destino, refrescar); }
    async function nueva() {
      try {
        const x = await post("/api/reg", {c, tipo: "decision", titulo: "Nueva decisión", estado: "vigente"});
        S.edit = x.id; S.vista = "linea"; S.f = {estado: "", dueno: "", revision: "", q: ""}; await cargar();
        document.getElementById("dec-" + x.id)?.scrollIntoView({block: "center"}); document.querySelector("#dec-" + x.id + " input")?.select();
      } catch (x) { err(x); }
    }
    async function proponer(r, aceptar) {
      try {
        if (aceptar) {
          await post("/api/reg/relacion", {c, a: r.a, b: r.b, tipo: "sustituye", aplicar: true});
          aviso("Aceptado: «" + r.b_titulo + "» queda sustituida. Ctrl+Z para deshacer");
        } else { await api("/api/reg/relacion?" + new URLSearchParams({c, a: r.a, b: r.b, tipo: r.tipo || "sustituye"}), {method: "DELETE"}); aviso("Propuesta rechazada"); }
        await refrescar();
      } catch (x) { err(x); }
    }
    function ir(id) {
      const n = document.getElementById("dec-" + id);
      if (!n) { aviso("Esa decisión no está visible con los filtros actuales"); return; }
      n.scrollIntoView({behavior: "smooth", block: "center"}); n.classList.add("flash"); n.focus({preventScroll: true}); setTimeout(() => n.classList.remove("flash"), 1800);
    }
    async function exportar(fmt) {
      try {
        const r = await fetch("/api/reg/exportar?" + new URLSearchParams({c, vista: "decisiones", fmt, borrador: S.soloAprob ? "0" : "1"}));
        if (!r.ok) { let m = r.statusText; try { const j = await r.json(); m = j.detail || j.error || m; } catch {} aviso(r.status === 404 ? "Exportación no disponible: " + m : "No se pudo exportar: " + m); return; }
        const b = await r.blob(), cd = r.headers.get("content-disposition") || "", nombre = /filename\*?=(?:UTF-8'')?"?([^";]+)/i.exec(cd)?.[1];
        const a = el("a", {href: URL.createObjectURL(b), download: nombre ? decodeURIComponent(nombre) : "decisiones." + fmt}); document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
        aviso("Exportado · " + fmt.toUpperCase() + (S.soloAprob ? " (solo aprobados)" : " (borradores marcados)"));
      } catch (x) { err(x); }
    }

    // ---- tarjeta ----
    const campo = (et, ctl) => el("label", {className: "dec-f"}, el("span", {textContent: et}), ctl);
    function citas(it) {
      return (it.citas || []).map(ci => el("blockquote", {className: "dec-cita"}, "«" + (ci.texto || "") + "» ", ci.mid ? fLink({mid: ci.mid, ver: ci.ver, t: ci.t}, "[" + mmss(ci.t || 0) + "]") : "",
        ci.verificada === false ? el("span", {className: "badge w", textContent: "cita sin verificar"}) : ""));
    }
    function editor(it) {
      const t = el("input", {type: "text", value: it.titulo || ""}), d = el("textarea", {rows: 3, value: it.detalle || ""}), al = el("textarea", {rows: 2, value: cam(it, "alternativas")}), co = el("textarea", {rows: 2, value: cam(it, "consecuencias")});
      const de = el("input", {type: "text", value: cam(it, "decisor") || it.dueno || ""}), fe = el("input", {type: "date", value: fecha(it)});
      const es = el("select", {}, ...ESTADOS.map(x => new Option(x, x))); es.value = estado(it);
      const guardar = async () => {
        const cambios = {titulo: t.value.trim() || it.titulo, detalle: d.value, estado: es.value, ...(fe.value ? {fecha_alta: fe.value} : {}), dueno: de.value.trim(), campos: {alternativas: al.value, consecuencias: co.value, decisor: de.value.trim(), fecha: fe.value}};
        if (await patch(it, cambios)) { S.edit = null; aviso("Guardado. Ctrl+Z para deshacer"); await refrescar(); }
      };
      return el("form", {className: "dec-edit", onsubmit: ev => { ev.preventDefault(); guardar(); }, onkeydown: ev => { if (ev.key === "Escape") { S.edit = null; pintar(); } }},
        campo("Título", t), campo("Contexto / motivo", d), campo("Alternativas consideradas", al), campo("Consecuencias", co),
        el("div", {className: "dec-fila"}, campo("Decisor", de), campo("Estado", es), campo("Fecha", fe)),
        el("div", {className: "row"}, el("button", {className: "pri sm", type: "submit", textContent: "Guardar"}), el("button", {className: "sec sm", type: "button", textContent: "Cancelar", onclick: () => { S.edit = null; pintar(); }})));
    }
    function tarjeta(it) {
      const es = estado(it), sp = sustPor(it.id), sa = sustA(it.id), muerta = es !== "vigente", rev = it.revision;
      const btn = (txt, fn, cl = "link") => el("button", {className: cl, type: "button", textContent: txt, onclick: fn});
      const extra = [["Alternativas", cam(it, "alternativas")], ["Consecuencias", cam(it, "consecuencias")]].filter(x => x[1]);
      const art = el("article", {id: "dec-" + it.id, "data-id": it.id, tabIndex: -1, className: "dec-card" + (muerta ? " muerta" : "") + (rev === "propuesto" ? " prop" : "") + (rev === "descartado" ? " desc" : "")},
        el("header", {className: "dec-h"}, el("b", {className: "dec-cod", textContent: it.codigo || "D-?"}), el("h3", {className: "dec-t", textContent: it.titulo}),
          el("span", {className: "badge " + (CHIP[es] || ""), textContent: es}), ...regInsignias(it)),
        el("div", {className: "dec-meta muted", textContent: [cam(it, "decisor") || it.dueno ? "Decisor: " + (cam(it, "decisor") || it.dueno) : "Sin decisor", fecha(it) && fechaTxt(fecha(it))].filter(Boolean).join(" · ")}));
      if (S.edit === it.id) { art.append(editor(it)); return art; }
      if (sp) { const n = porId(sp); art.append(el("div", {className: "dec-flecha"}, "⤷ Sustituida por ", btn((n?.codigo || "otra") + (n ? " · " + n.titulo.slice(0, 70) : ""), () => ir(sp)))); }
      if (sa.length) art.append(el("div", {className: "dec-flecha ok"}, "Sustituye a ", ...sa.flatMap((id, i) => [i ? ", " : "", btn(porId(id)?.codigo || "otra", () => ir(id))])));
      if (it.detalle || extra.length) {
        const det = el("details", {className: "dec-ctx", open: S.ctx.has(it.id), ontoggle: () => { det.open ? S.ctx.add(it.id) : S.ctx.delete(it.id); }}, el("summary", {textContent: "Contexto y consecuencias"}),
          ...(it.detalle ? [el("p", {textContent: it.detalle})] : []), ...extra.map(([k, v]) => el("p", {}, el("b", {textContent: k + ": "}), v)));
        art.append(det);
      }
      art.append(...citas(it), regFusiona(it, c, refrescar));
      const fus = () => { const s = el("select", {ariaLabel: "Fusionar con", onchange: () => s.value && fusionar(s.value, it.id), onkeydown: ev => { if (ev.key === "Escape") { S.fusion = null; pintar(); } }}, new Option("Fusionar con…", ""), ...S.items.filter(x => x.id !== it.id).map(x => new Option((x.codigo || "") + " · " + x.titulo.slice(0, 60), x.id))); setTimeout(() => s.focus()); return s; };
      art.append(el("div", {className: "dec-ops"},
        ...(rev === "propuesto" ? [btn("Aprobar", () => revisar([it.id], "aprobar"), "sec sm"), btn("Descartar", () => revisar([it.id], "descartar"))] : []),
        ...(rev === "descartado" ? [btn("Restaurar", () => revisar([it.id], "restaurar"), "sec sm")] : []),
        btn("Editar", () => { S.edit = it.id; pintar(); document.querySelector("#dec-" + it.id + " input")?.focus(); }), btn("Detalle ADR", () => abrirCajon(it.id)),
        ...regBotonSeparar(it, c, refrescar),
        ...(rev === "fusionado" ? [] : [S.fusion === it.id ? fus() : btn("Fusionar…", () => { S.fusion = it.id; pintar(); })]),
        ...(it.origen === "manual" ? [btn("Quitar", async () => { try { await api("/api/reg/" + enc(it.id) + "?c=" + enc(c), {method: "DELETE"}); await refrescar(); } catch (x) { err(x); } })] : [])));
      return art;
    }

    // ---- cajón ADR + historial ----
    async function abrirCajon(id) {
      const it = porId(id); if (!it) { cerrarCajon(); return; }
      S.drawer = id; cajon.hidden = false;
      const sec = (k, v) => v ? [el("h4", {textContent: k}), el("p", {textContent: v})] : [];
      const sp = sustPor(id), sa = sustA(id), hist = el("div", {className: "muted", textContent: "Cargando historial…"});
      cajon.replaceChildren(el("div", {className: "sec-h"}, el("h3", {textContent: "ADR · " + (it.codigo || "")}), el("button", {className: "sec sm", type: "button", textContent: "Cerrar", onclick: cerrarCajon})),
        el("h2", {className: "dec-adr-t", textContent: it.titulo}),
        el("p", {}, el("span", {className: "badge " + (CHIP[estado(it)] || ""), textContent: estado(it)}), " ", ...regInsignias(it), " ", el("span", {className: "muted", textContent: fecha(it) ? fechaTxt(fecha(it)) : ""})),
        ...sec("Decisor", cam(it, "decisor") || it.dueno), ...sec("Contexto", it.detalle), ...sec("Alternativas consideradas", cam(it, "alternativas")), ...sec("Consecuencias", cam(it, "consecuencias")),
        ...(sp ? [el("h4", {textContent: "Sustituida por"}), el("p", {}, el("button", {className: "link", type: "button", textContent: (porId(sp)?.codigo || "") + " · " + (porId(sp)?.titulo || ""), onclick: () => ir(sp)}))] : []),
        ...(sa.length ? [el("h4", {textContent: "Sustituye a"}), el("p", {textContent: sa.map(x => porId(x)?.codigo || x).join(", ")})] : []),
        ...((it.citas || []).length ? [el("h4", {textContent: "Evidencia"}), ...citas(it)] : []), el("h4", {textContent: "Historial"}), hist);
      try {
        const h = await api("/api/reg/" + enc(id) + "/historial?c=" + enc(c)), txt = v => typeof v === "string" ? v : JSON.stringify(v);
        hist.replaceChildren(...(h.length ? h.map(x => el("div", {className: "reg-h"}, el("b", {textContent: x.accion}), el("small", {textContent: new Date(x.t * (x.t < 1e11 ? 1000 : 1)).toLocaleString("es")}),
          el("div", {textContent: [x.antes && "Antes: " + txt(x.antes), x.despues && "Después: " + txt(x.despues)].filter(Boolean).join("  →  ")}))) : [el("span", {textContent: "Sin cambios registrados."})]));
      } catch (x) { hist.textContent = x.message; }
    }
    function cerrarCajon() { S.drawer = null; cajon.hidden = true; }

    // ---- pintado ----
    function filtradas() {
      const q = S.f.q.toLowerCase();
      return S.items.filter(x => (!S.ids || S.ids.includes(x.id)) && (!S.vig || estado(x) === "vigente") && (!S.f.estado || estado(x) === S.f.estado) && (!S.f.dueno || (cam(x, "decisor") || x.dueno) === S.f.dueno)
        && (!q || [x.titulo, x.detalle, x.codigo, cam(x, "alternativas"), cam(x, "consecuencias"), cam(x, "decisor")].some(v => String(v || "").toLowerCase().includes(q))));
    }
    function pintarBarra() {
      const dec = [...new Set(S.items.map(x => cam(x, "decisor") || x.dueno).filter(Boolean))].sort();
      const q = el("input", {type: "search", value: S.f.q, placeholder: "Buscar decisión…", ariaLabel: "Buscar", oninput: ev => { S.f.q = ev.target.value; pintarCuerpo(); }});
      const se = el("select", {ariaLabel: "Estado", onchange: ev => { S.f.estado = ev.target.value; pintarCuerpo(); }}, new Option("Todos los estados", ""), ...ESTADOS.map(x => new Option(x, x))); se.value = S.f.estado;
      const sd = el("select", {ariaLabel: "Decisor", onchange: ev => { S.f.dueno = ev.target.value; pintarCuerpo(); }}, new Option("Todos los decisores", ""), ...dec.map(x => new Option(x, x))); sd.value = S.f.dueno;
      const sr = el("select", {ariaLabel: "Revisión", onchange: ev => { S.f.revision = ev.target.value; cargar(); }}, ...REVS.map(([k, t]) => new Option(t, k))); sr.value = S.f.revision;
      const fusP = el("button", {className: "f-pill", type: "button", "aria-pressed": S.f.revision === "fusionado", textContent: "Fusionadas (" + (S.nFus ?? 0) + ")", title: "Ver las decisiones fusionadas en otras",
        onclick: () => { S.f.revision = S.f.revision === "fusionado" ? "" : "fusionado"; cargar(); }});
      const vig = el("label", {className: "dec-chk"}, el("input", {type: "checkbox", checked: S.vig, onchange: ev => { S.vig = ev.target.checked; lsSet("dec-vig", S.vig); pintarCuerpo(); }}), " Solo vigentes");
      const seg = (k, t) => el("button", {className: "f-pill", type: "button", "aria-pressed": S.vista === k, textContent: t, onclick: () => { S.vista = k; lsSet("dec-vista", k); pintar(); }});
      const ord = el("button", {className: "sec sm", type: "button", textContent: S.asc ? "Más antiguas primero ↑" : "Más recientes primero ↓", onclick: () => { S.asc = !S.asc; lsSet("dec-asc", S.asc); pintar(); }});
      const apr = el("label", {className: "dec-chk", title: "Desmarcado: se incluyen las no revisadas marcadas como BORRADOR"}, el("input", {type: "checkbox", checked: S.soloAprob, onchange: ev => { S.soloAprob = ev.target.checked; lsSet("dec-aprob", S.soloAprob); }}), " Solo aprobados");
      const exp = el("details", {className: "dec-exp"}, el("summary", {textContent: "Exportar ▾", className: "sec"}),
        el("div", {className: "dec-menu"}, apr, ...FORMATOS.map(([f, t]) => el("button", {className: "link", type: "button", textContent: t, onclick: () => { exp.open = false; exportar(f); }}))));
      barra.replaceChildren(el("div", {className: "reg-bar"}, ...(S.vista === "linea" ? [q, se, sd, sr, fusP, vig] : []), el("span", {className: "grow"}), el("div", {className: "row", role: "group", "aria-label": "Vista"}, seg("linea", "Línea"), seg("tabla", "Tabla"))),
        el("div", {className: "reg-acc"}, el("button", {className: "pri sm", type: "button", textContent: "+ Decisión", onclick: nueva}), el("button", {className: "sec sm", type: "button", textContent: "Deshacer", title: "Ctrl+Z", onclick: deshacer}),
          ...(S.vista === "linea" ? [ord] : []), el("span", {className: "grow"}), exp));
    }
    function pintarBanner() {
      banner.replaceChildren(...(S.prop.length ? [el("section", {className: "card dec-ban"}, el("div", {className: "sec-h"}, el("h3", {textContent: "Sustituciones propuestas · " + S.prop.length})),
        el("p", {className: "muted", textContent: "La IA cree que estas decisiones reemplazan a otras anteriores. Al aceptar, la antigua pasa a «sustituida»."}),
        el("ul", {className: "f-lst"}, ...S.prop.map(r => el("li", {}, el("b", {textContent: "«" + r.a_titulo + "»"}), " sustituye a ", el("b", {textContent: "«" + r.b_titulo + "»"}), " ",
          el("button", {className: "sec sm", type: "button", textContent: "Aceptar", onclick: () => proponer(r, true)}), " ", el("button", {className: "link", type: "button", textContent: "Rechazar", onclick: () => proponer(r, false)})))))] : []));
    }
    function pintarCuerpo() {
      if (S.vista === "tabla") {
        const w = el("div"); cuerpo.replaceChildren(w);
        registroTabla(w, {c, tipo: "decision", onChange: () => { cargar(); }, vacio: "Sin decisiones todavía. Usa «+ Añadir» o espera a que la IA las proponga.",
          columnas: [{k: "codigo", label: "Código", w: 80, editable: false}, {k: "titulo", label: "Decisión", tipo: "area"}, {k: "estado", label: "Estado", tipo: "select", opciones: ESTADOS}, {k: "campos.decisor", label: "Decisor"}, {k: "fecha_alta", label: "Fecha", editable: false}]});
        return;
      }
      const xs = filtradas();
      if (!xs.length) { cuerpo.replaceChildren(el("div", {className: "vacio", textContent: S.items.length ? "Ninguna decisión con estos filtros." : "Aún no hay decisiones. Se extraen de las reuniones o añádelas con «+ Decisión»."})); return; }
      const g = new Map(); for (const x of xs) { const k = fecha(x); (g.get(k) || g.set(k, []).get(k)).push(x); }
      const dir = S.asc ? 1 : -1, claves = [...g.keys()].sort((a, b) => a.localeCompare(b) * dir);
      cuerpo.replaceChildren(el("ol", {className: "dec-linea"}, ...claves.map(k => el("li", {className: "dec-grupo"}, el("h3", {className: "dec-fecha", textContent: k ? fechaTxt(k) : "Sin fecha"}),
        ...g.get(k).sort((a, b) => (num(a) - num(b)) * dir).map(tarjeta)))));
    }
    function pintar() {
      pintarBarra(); pintarBanner(); pintarCuerpo();
      if (S.ids && S.vista === "linea") banner.prepend(fChipFoco(filtradas().length, () => { S.ids = null; pintar(); }, fo?.etiqueta));
      if (S.resaltar) { S.resaltar = false; fResaltaIds(cuerpo, S.ids); }
    }
    cargar();
    return [raiz];
  }
  document.addEventListener("DOMContentLoaded", () => { FVISTAS.decisiones = vista; });
})();
