/* Descargar: qué × formato -> archivo o zip. Globales: el. */
(() => {
const QL = {documento: "Documento completo", resumen: "Resumen", transcripcion: "Transcripción", tareas: "Tareas", decisiones: "Decisiones", riesgos: "Riesgos",
  requisitos: "Requisitos", historias: "Historias de usuario", interesados: "Interesados", informe: "Informe de estado"};
const ORDEN = Object.keys(QL);
const BASICOS = {pdf: "PDF", docx: "Word", md: "Markdown", xlsx: "Excel", csv: "CSV"};
const KEY = "desc.sel";
const T = (t, c, ...k) => el(t, {className: c}, ...k);

async function abrir({docs, c, ids} = {}) {
  const alcance = docs?.length ? "documento" : "proyecto";
  let op;
  try { op = await api("/api/descargar/opciones"); } catch (e) { alert(e.message); return; }
  let mem = {}; try { mem = JSON.parse(localStorage.getItem(KEY)) || {}; } catch {}
  const ques = ORDEN.filter(q => op.que[q] && op.que[q][alcance]?.length), extra = ques.length ? [] : Object.keys(op.que);
  const lq = [...ques, ...extra];
  const st = {que: new Set((mem.que || ["documento"]).filter(q => lq.includes(q))), fmt: new Set(mem.fmt || ["pdf"]), apr: !!mem.apr, mas: !!mem.mas};
  if (!st.que.size && lq.length) st.que.add(lq[0]);
  const ok = (q, f) => !!op.que[q]?.[alcance]?.includes(f);
  const valido = f => [...st.que].some(q => ok(q, f));
  const d = el("dialog", {className: "env-dlg desc-dlg", "aria-label": "Descargar"});
  const cuerpo = T("div", "desc-body"), msg = T("div", "desc-msg"); msg.setAttribute("role", "status");
  const go = el("button", {type: "button", className: "btn pri", onclick: bajar});
  const pintar = () => {
    const fm = op.formatos, basicos = Object.keys(BASICOS).filter(f => fm.includes(f)), mas = fm.filter(f => !BASICOS[f]);
    const chip = f => {
      const v = valido(f), on = st.fmt.has(f) && v;
      return el("button", {type: "button", className: "env-chip", "aria-pressed": on, disabled: !v, title: v ? "" : "No disponible para lo marcado",
        textContent: BASICOS[f] || f, onclick: () => { st.fmt.has(f) ? st.fmt.delete(f) : st.fmt.add(f); pintar(); }});
    };
    cuerpo.replaceChildren(
      T("fieldset", "desc-q", T("legend", "", "Qué descargar"),
        ...lq.map(q => T("label", "env-chk", el("input", {type: "checkbox", checked: st.que.has(q), onchange: e => { e.target.checked ? st.que.add(q) : st.que.delete(q); pintar(); }}), " " + (QL[q] || q)))),
      T("fieldset", "desc-f", T("legend", "", "Formato"), T("div", "env-chips", ...basicos.map(chip)),
        ...(mas.length ? [el("button", {type: "button", className: "btn sec env-sm", "aria-expanded": st.mas, textContent: st.mas ? "Menos formatos" : "Más formatos", onclick: () => { st.mas = !st.mas; pintar(); }}),
          ...(st.mas ? [T("div", "env-chips", ...mas.map(chip))] : [])] : [])),
      T("label", "env-chk", el("input", {type: "checkbox", checked: st.apr, onchange: e => st.apr = e.target.checked}), " Solo aprobados"));
    const n = [...st.fmt].filter(valido).length * st.que.size;
    go.disabled = !st.que.size || ![...st.fmt].some(valido);
    go.textContent = "Descargar" + (n > 1 ? " (.zip)" : "");
  };
  async function bajar() {
    const formatos = [...st.fmt].filter(valido), que = [...st.que];
    localStorage.setItem(KEY, JSON.stringify({que, fmt: [...st.fmt], apr: st.apr, mas: st.mas}));
    go.disabled = true; msg.className = "desc-msg"; msg.textContent = "Preparando…";
    try {
      const r = await fetch("/api/descargar", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({docs, c, ids, que, formatos, solo_aprobados: st.apr})});
      if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(typeof j.detail === "string" ? j.detail : r.statusText); }
      const cd = r.headers.get("Content-Disposition") || "", m = /filename\*=UTF-8''([^;]+)/i.exec(cd) || /filename="?([^";]+)/i.exec(cd);
      const nombre = m ? decodeURIComponent(m[1]) : "actas";
      let omit = []; try { omit = JSON.parse(decodeURIComponent(r.headers.get("X-Actas-Omitidos") || "[]")); } catch {}
      const url = URL.createObjectURL(await r.blob()), a = el("a", {href: url, download: nombre});
      document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 10000);
      msg.textContent = "Descargado: " + nombre;
      if (omit.length) msg.append(T("div", "desc-omit", T("b", "", "No incluido:"), el("ul", {}, ...omit.map(x => el("li", {textContent: x})))));
    } catch (e) { msg.className = "desc-msg env-bad"; msg.textContent = e.message; }
    go.disabled = false;
  }
  d.append(T("h2", "", "Descargar"), cuerpo, msg, T("div", "row env-acc", go, el("button", {type: "button", className: "btn sec", textContent: "Cerrar", onclick: () => d.close()})));
  d.addEventListener("close", () => d.remove());
  document.body.append(d); pintar(); d.showModal();
}
window.Descargar = {abrir};
})();
