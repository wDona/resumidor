/* Descargar: qué × formato -> archivo o zip. Globales: el. */
(() => {
  const QL = {
    documento: "Documento completo",
    resumen: "Resumen",
    transcripcion: "Transcripción",
    tareas: "Tareas",
    decisiones: "Decisiones",
    riesgos: "Riesgos",
    requisitos: "Requisitos",
    historias: "Historias de usuario",
    interesados: "Interesados",
    informe: "Informe de estado",
  };
  const ORDEN = Object.keys(QL);
  const BASICOS = { pdf: "PDF", docx: "Word", md: "Markdown", xlsx: "Excel", csv: "CSV" };
  const KEY = "desc.sel";
  const PK = "desc.presets",
    PU = "desc.ultimo";
  const SERIE = [
    { id: "s:acta", nombre: "Acta en PDF", que: ["documento"], fmt: ["pdf"] },
    { id: "s:comite", nombre: "Pack comité", que: ["decisiones", "riesgos"], fmt: ["docx", "pdf"] },
    { id: "s:tareas", nombre: "Tareas a Excel", que: ["tareas"], fmt: ["xlsx"] },
    { id: "s:md", nombre: "Todo en Markdown", que: ["documento", "resumen", "tareas", "decisiones", "transcripcion"], fmt: ["md"] },
  ];
  const ls = (k, d) => {
    try {
      return JSON.parse(localStorage.getItem(k)) ?? d;
    } catch {
      return d;
    }
  };
  const T = (t, c, ...k) => el(t, { className: c }, ...k);

  async function abrir({ docs, c, ids } = {}) {
    const alcance = docs?.length ? "documento" : "proyecto";
    let op;
    try {
      op = await api("/api/descargar/opciones");
    } catch (e) {
      alert(e.message);
      return;
    }
    let mem = {};
    try {
      mem = JSON.parse(localStorage.getItem(KEY)) || {};
    } catch {}
    const ques = ORDEN.filter(q => op.que[q] && op.que[q][alcance]?.length),
      extra = ques.length ? [] : Object.keys(op.que);
    const lq = [...ques, ...extra];
    const st = {
      que: new Set((mem.que || ["documento"]).filter(q => lq.includes(q))),
      fmt: new Set(mem.fmt || ["pdf"]),
      apr: !!mem.apr,
      mas: !!mem.mas,
      sel: null,
    };
    if (!st.que.size && lq.length) st.que.add(lq[0]);
    const ajustaFmt = () => {
      const v = Object.keys(BASICOS).filter(f => op.formatos.includes(f) && [...st.que].some(q => op.que[q]?.[alcance]?.includes(f)));
      if (v.length && !v.some(f => st.fmt.has(f))) st.fmt = new Set([v[0]]);
    };
    ajustaFmt();
    {
      // preselecciona el último preset usado si coincide con lo recordado
      const u = ls(PU, null) || "s:acta",
        p = [...SERIE, ...ls(PK, [])].find(x => x.id === u),
        mismo = (A, B) => A.size === B.length && B.every(x => A.has(x));
      if (p && mismo(st.que, p.que) && mismo(st.fmt, p.fmt)) st.sel = p.id;
    }
    const ok = (q, f) => !!op.que[q]?.[alcance]?.includes(f);
    const valido = f => [...st.que].some(q => ok(q, f));
    const d = el("dialog", { className: "env-dlg desc-dlg", "aria-label": "Descargar" });
    let propios = ls(PK, []),
      flash = false;
    const salir = () => (matchMedia("(prefers-reduced-motion: reduce)").matches ? d.close() : (d.classList.add("saliendo"), setTimeout(() => d.close(), 160)));
    const aplicar = p => {
      st.que = new Set(p.que.filter(q => lq.includes(q)));
      st.fmt = new Set(p.fmt);
      st.sel = p.id;
      flash = true;
      if (p.fmt.some(f => !BASICOS[f])) st.mas = true;
      pintar();
    };
    const guardar = () => {
      const n = prompt("Nombre del preset");
      if (!n?.trim()) return;
      propios = [...propios, { id: "u:" + Date.now(), nombre: n.trim(), que: [...st.que], fmt: [...st.fmt].filter(valido) }];
      localStorage.setItem(PK, JSON.stringify(propios));
      st.sel = propios.at(-1).id;
      pintar();
    };
    const filaPre = () => {
      const ult = ls(PU, null);
      const chip = (p, own) =>
        Enviar.chip({
          nombre: p.nombre,
          serie: !own,
          activo: st.sel === p.id,
          ultimo: p.id === ult,
          onSelect: () => aplicar(p),
          titulo: p.que.map(q => QL[q] || q).join(", ") + " · " + p.fmt.map(f => BASICOS[f] || f).join(", "),
          onMenu: own
            ? a =>
                Enviar.menu(a, [
                  [
                    "Eliminar",
                    () => {
                      const x = p;
                      propios = propios.filter(y => y.id !== x.id);
                      localStorage.setItem(PK, JSON.stringify(propios));
                      pintar();
                      aviso("Preset eliminado", {
                        txt: "Deshacer",
                        fn: () => {
                          propios = [...propios, x];
                          localStorage.setItem(PK, JSON.stringify(propios));
                          pintar();
                        },
                      });
                    },
                  ],
                ])
            : undefined,
        });
      return T("div", "env-chips desc-pre", ...[...SERIE.map(p => chip(p)), ...propios.map(p => chip(p, true))]);
    };
    const movil = matchMedia("(max-width:560px)"),
      cuerpo = T("div", "desc-body"),
      msg = T("div", "desc-msg");
    msg.setAttribute("role", "status");
    const go = el("button", { type: "button", className: "btn pri", onclick: bajar });
    const pintar = () => {
      const fm = op.formatos,
        basicos = Object.keys(BASICOS).filter(f => fm.includes(f)),
        mas = fm.filter(f => !BASICOS[f]);
      const chip = f => {
        const v = valido(f),
          on = st.fmt.has(f) && v,
          no = [...st.que].filter(q => !ok(q, f)).map(q => QL[q] || q);
        return el("button", {
          type: "button",
          className: "env-chip",
          "aria-pressed": on,
          "aria-disabled": !v,
          title: v ? "" : "No disponible para " + no.join(", "),
          textContent: BASICOS[f] || f,
          onclick: () => {
            if (!v) return;
            st.fmt.has(f) ? st.fmt.delete(f) : st.fmt.add(f);
            st.sel = null;
            pintar();
          },
        });
      };
      const mov = flash;
      flash = false;
      const fQue = T(
        "fieldset",
        "desc-q",
        T("legend", "", "Qué descargar"),
        ...lq.map(q =>
          T(
            "label",
            "env-chk",
            el("input", {
              type: "checkbox",
              checked: st.que.has(q),
              onchange: e => {
                e.target.checked ? st.que.add(q) : st.que.delete(q);
                ajustaFmt();
                st.sel = null;
                pintar();
              },
            }),
            " " + (QL[q] || q),
          ),
        ),
      );
      const fFmt = T(
        "fieldset",
        "desc-f",
        T("legend", "", "Formato"),
        T("div", "env-seg env-fmt", ...basicos.map(chip), ...(st.mas ? mas.map(chip) : [])),
        ...(basicos.some(f => !valido(f)) ? [T("small", "muted desc-nota", "Los formatos en gris no están disponibles para lo elegido.")] : []),
      );
      cuerpo.replaceChildren(
        T("div", "desc-p", T("div", "desc-l", "Preajustes"), filaPre()),
        T("div", "desc-cols", ...(movil.matches ? [fFmt, fQue] : [fQue, fFmt])), // una columna: Formato (corto) antes de la lista larga; el orden del DOM = el visual
        el(
          "details",
          { className: "env-pers desc-opc", open: st.opc || st.mas || st.apr, ontoggle: e => (st.opc = e.target.open) },
          el("summary", {}, "Opciones"),
          T(
            "div",
            "env-opc",
            ...(mas.length
              ? [
                  el("button", {
                    type: "button",
                    className: "btn sec env-sm",
                    "aria-expanded": st.mas,
                    textContent: st.mas ? "Menos formatos" : "Más formatos",
                    onclick: () => {
                      st.mas = !st.mas;
                      pintar();
                    },
                  }),
                ]
              : []),
            T("label", "env-chk", el("input", { type: "checkbox", checked: st.apr, onchange: e => (st.apr = e.target.checked) }), " Solo aprobados"),
            el("button", { type: "button", className: "btn sec env-sm", textContent: "Guardar esta selección", onclick: guardar }),
          ),
        ),
      );
      const n = [...st.fmt].filter(valido).length * st.que.size;
      go.disabled = !st.que.size || ![...st.fmt].some(valido);
      go.textContent = "Descargar" + (n > 1 ? " (.zip)" : "");
      if (mov) cuerpo.querySelectorAll("input:checked,.env-chip[aria-pressed=true]").forEach(x => (x.closest("label") || x).classList.add("env-flash"));
    };
    async function bajar() {
      const formatos = [...st.fmt].filter(valido),
        que = [...st.que];
      if (st.sel) localStorage.setItem(PU, JSON.stringify(st.sel));
      localStorage.setItem(KEY, JSON.stringify({ que, fmt: [...st.fmt], apr: st.apr, mas: st.mas }));
      go.disabled = true;
      msg.className = "desc-msg";
      msg.textContent = "Preparando…";
      try {
        const r = await fetch("/api/descargar", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ docs, c, ids, que, formatos, solo_aprobados: st.apr }),
        });
        if (!r.ok) {
          const j = await r.json().catch(() => ({}));
          throw new Error(typeof j.detail === "string" ? j.detail : r.statusText);
        }
        const cd = r.headers.get("Content-Disposition") || "",
          m = /filename\*=UTF-8''([^;]+)/i.exec(cd) || /filename="?([^";]+)/i.exec(cd);
        const nombre = m ? decodeURIComponent(m[1]) : "actas";
        let omit = [];
        try {
          omit = JSON.parse(decodeURIComponent(r.headers.get("X-Actas-Omitidos") || "[]"));
        } catch {}
        const url = URL.createObjectURL(await r.blob()),
          a = el("a", { href: url, download: nombre });
        document.body.append(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
        msg.textContent = "Descargado: " + nombre;
        if (omit.length) msg.append(T("div", "desc-omit", T("b", "", "No incluido:"), el("ul", {}, ...omit.map(x => el("li", { textContent: x })))));
      } catch (e) {
        msg.className = "desc-msg env-bad";
        msg.textContent = e.message;
      }
      go.disabled = false;
    }
    d.append(
      Enviar.cabecera("Descargar", salir),
      cuerpo,
      msg,
      T("div", "row env-acc", el("button", { type: "button", className: "btn sec", textContent: "Cerrar", onclick: salir }), go),
    ); // cabecera común (título + «×») y secundario · primario, como Añadir
    d.addEventListener("close", () => {
      movil.onchange = null;
      d.remove();
    });
    movil.onchange = () => pintar();
    document.body.append(d);
    pintar();
    d.showModal();
    go.focus();
  }
  window.Descargar = { abrir };
})();
