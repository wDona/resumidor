// Vista «informe» (F6): informe de estado / comité. FVISTAS.informe = (c, e) => [nodos].
// Contrato: GET/POST /api/reg/informes, GET/PATCH /api/reg/informes/{id}, POST …/{id}/recalcular | …/{id}/redactar (cola, op «informe»), GET …/{id}/exportar, DELETE /api/reg/informes/{id}?c= (una versión).
// Los gráficos (SVG) vienen hechos del servidor (informe.graficos): los mismos que salen en el PDF; heredan color con currentColor.
// Todo se guarda al salir del campo (blur) en la versión actual; «Recalcular» y «Redactar con IA» crean una versión nueva.
(() => {
  const enc = encodeURIComponent, err = x => aviso(x.message || String(x));
  const COL = ["verde", "ambar", "rojo", "gris"], NOM = {verde: "Verde", ambar: "Ámbar", rojo: "Rojo", gris: "Sin datos"}, FORMA = {verde: "●", ambar: "▲", rojo: "■", gris: "○"};
  const SEC = [["logros", "Logros del periodo"], ["proximos", "Próximos pasos"], ["riesgos", "Riesgos principales"], ["comite", "Decisiones requeridas al comité"]];
  const FMT = [["docx", "Word (.docx)"], ["pdf", "PDF (apaisado, con gráficos)"], ["pptx", "PowerPoint (.pptx)"], ["md", "Markdown"], ["json", "JSON"], ["xlsx", "Excel (.xlsx)"]];
  const fmtF = iso => iso ? new Date(iso + "T12:00").toLocaleDateString("es", {day: "numeric", month: "short", year: "numeric"}) : "";

  function vista(c) {
    const raiz = el("div", {className: "inf"}), S = {lista: [], x: null, def: null};
    const url = (id, s = "") => "/api/reg/informes/" + id + s;
    const patch = async cambios => {
      try { S.x = await api(url(S.x.id), {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({c, cambios})}); return true; } catch (x) { err(x); return false; }
    };
    async function cargar(id) {
      try {
        const r = await api("/api/reg/informes?c=" + enc(c)); S.lista = r.items; S.def = r.periodo;
        const serie = lsGet("inf-serie-" + c, null), it = S.lista.find(x => x.id === id) || S.lista.find(x => x.serie === serie) || S.lista[0];
        S.x = id ? await api(url(id) + "?c=" + enc(c)) : it ? await api(url(it.id) + "?c=" + enc(c)) : null;
        pintar();
      } catch (x) { raiz.replaceChildren(el("p", {className: "err", textContent: x.message})); }
    }
    const nuevo = (desde, hasta) => async () => {
      try { S.x = await post("/api/reg/informes", {c, ...(desde ? {desde, hasta} : {})}); lsSet("inf-serie-" + c, S.x.serie); aviso("Informe creado"); await cargar(S.x.id); } catch (x) { err(x); }
    };
    function pintar() {
      if (!S.x) {
        const d = el("input", {type: "date", value: S.def?.[0] || "", ariaLabel: "Desde"}), h = el("input", {type: "date", value: S.def?.[1] || "", ariaLabel: "Hasta"});
        raiz.replaceChildren(el("div", {className: "card"}, el("h3", {textContent: "Informe de estado / comité"}),
          el("p", {className: "muted", textContent: "Indicadores, semáforos y narrativa del periodo a partir del registro del proyecto. Funciona sin IA; la IA solo propone la redacción."}),
          el("div", {className: "inf-fila"}, el("label", {}, "Desde ", d), el("label", {}, "Hasta ", h), el("button", {className: "pri", type: "button", textContent: "Nuevo informe", onclick: () => nuevo(d.value, h.value)()}))));
        return;
      }
      raiz.replaceChildren(barra(), cabecera(), semaforos(), kpis(), graficos(), narrativa(), notas());
    }
    function barra() {
      const x = S.x;
      const sel = el("select", {ariaLabel: "Informe", onchange: ev => { const it = S.lista.find(i => String(i.id) === ev.target.value); lsSet("inf-serie-" + c, it.serie); cargar(it.id); }},
        ...S.lista.map(i => new Option(i.titulo + (i.estado === "final" ? " · final" : ""), i.id)));
      sel.value = S.lista.find(i => i.serie === x.serie)?.id ?? "";
      const ver = el("select", {ariaLabel: "Versión", onchange: ev => cargar(+ev.target.value)}, ...x.versiones.map(v => new Option("v" + v.version + " · " + new Date(v.modificado * 1000).toLocaleString("es", {dateStyle: "short", timeStyle: "short"}), v.id)));
      ver.value = x.id;
      const est = el("select", {ariaLabel: "Estado del informe", onchange: async ev => { if (await patch({estado: ev.target.value})) { aviso(ev.target.value === "final" ? "Marcado como final" : "Vuelve a borrador"); pintar(); } }},
        new Option("Borrador", "borrador"), new Option("Final", "final"));
      est.value = x.estado;
      const nb = () => { try { return nubeParams("q") || nubeParams("f"); } catch { return null; } };
      const red = el("button", {className: "sec sm", type: "button", textContent: x.en_cola ? "En cola…" : "Redactar con IA", disabled: x.en_cola,
        title: "La IA redacta logros, próximos pasos, riesgos y decisiones para el comité citando las fuentes [n]; crea una versión nueva",
        onclick: fallo(async () => { red.disabled = true; try { await fEnCola(url(x.id, "/redactar"), {c, ...(nb() ? {nube: nb()} : {})}); red.textContent = "En cola…"; } catch (e) { red.disabled = false; throw e; } })});
      const rec = el("button", {className: "sec sm", type: "button", textContent: "Recalcular", title: "Vuelve a calcular los indicadores y semáforos sugeridos (versión nueva; los semáforos elegidos a mano se quedan)",
        onclick: async () => { try { S.x = await post(url(x.id, "/recalcular"), {c}); aviso("Recalculado (v" + S.x.version + ")"); await cargar(S.x.id); } catch (e) { err(e); } }});
      const del = el("button", {className: "sec sm", type: "button", textContent: "Eliminar versión", title: "Borra solo esta versión del informe (si es la única, desaparece el informe)",
        onclick: async () => { if (!confirm("¿Eliminar la versión v" + x.version + " de «" + x.titulo + "»? No se puede deshacer.")) return;
          try { const r = await api(url(x.id) + "?c=" + enc(c), {method: "DELETE"}); aviso("Versión eliminada"); await cargar(r.id || undefined); } catch (e) { err(e); } }});
      const apr = el("input", {type: "checkbox", checked: lsGet("inf-aprob", false), onchange: ev => lsSet("inf-aprob", ev.target.checked)});
      const exp = el("details", {className: "inf-exp"}, el("summary", {className: "sec", textContent: "Exportar ▾"}),
        el("div", {className: "inf-menu"}, el("label", {className: "inf-chk", title: "Desmarcado: incluye lo no revisado con la marca BORRADOR"}, apr, " Solo aprobados"),
          ...FMT.map(([f, t]) => el("a", {className: "link", textContent: t, href: "#", onclick: ev => { ev.preventDefault(); exp.open = false;
            location.href = url(x.id, "/exportar?") + new URLSearchParams({c, fmt: f, borrador: apr.checked ? 0 : 1}); }}))));
      return el("div", {className: "inf-bar"}, sel, ver, est, el("button", {className: "sec sm", type: "button", textContent: "+ Nuevo informe", onclick: nuevo()}), rec, red, del, el("span", {className: "grow"}), exp);
    }
    function cabecera() {
      const x = S.x, k = x.contenido.kpis;
      const tit = el("input", {className: "inf-tit", value: x.titulo, ariaLabel: "Título del informe", onchange: ev => patch({titulo: ev.target.value})});
      const fecha = (campo, lab) => el("label", {}, lab + " ", el("input", {type: "date", value: x[campo], onchange: async ev => { if (await patch({[campo]: ev.target.value})) { aviso("Periodo cambiado: pulsa «Recalcular» para actualizar los indicadores"); pintar(); } }}));
      const datos = (x.proyecto?.datos || []).filter(d => d.k);
      const borr = k.revision.propuesto ? el("p", {className: "inf-borr", role: "note"}, el("b", {textContent: "BORRADOR · "}), k.revision.propuesto + " elementos propuestos sin revisar entran en los indicadores (marcados «incl. sin revisar»).") : "";
      return el("div", {className: "card inf-cab"}, tit, el("div", {className: "inf-fila"}, fecha("desde", "Desde"), fecha("hasta", "Hasta"),
        el("span", {className: "muted", textContent: "Indicadores calculados para " + fmtF(k.periodo.desde) + " – " + fmtF(k.periodo.hasta)}), el("span", {className: "badge " + (x.estado === "final" ? "ok" : "w"), textContent: x.estado === "final" ? "Final" : "Borrador"})),
        datos.length ? el("dl", {className: "inf-datos"}, ...datos.flatMap(d => [el("dt", {textContent: d.k}), el("dd", {textContent: d.v})])) : "", borr);
    }
    function semaforos() {
      const it = S.x.semaforos.items;
      const card = d => {
        const s = it[d];
        const b = el("button", {type: "button", className: "inf-luz " + s.color, "aria-label": d + ": " + NOM[s.color] + ". Pulsa para cambiar", title: "Pulsa para cambiar el color",
          onclick: async () => { if (await patch({semaforos: {[d]: {color: COL[(COL.indexOf(s.color) + 1) % 4]}}})) pintar(); }}, el("span", {className: "inf-forma", ariaHidden: "true", textContent: FORMA[s.color]}), " " + NOM[s.color]);
        const ta = el("textarea", {rows: 3, value: s.justificacion, ariaLabel: "Justificación de " + d, onblur: ev => ev.target.value !== s.justificacion && patch({semaforos: {[d]: {justificacion: ev.target.value}}})});
        const sug = el("small", {className: "muted"}, "Sugerido: " + FORMA[s.sugerido] + " " + NOM[s.sugerido],
          ...(s.manual ? [" · ", el("a", {href: "#", textContent: "volver al sugerido", onclick: async ev => { ev.preventDefault(); if (await patch({semaforos: {[d]: {manual: false}}})) pintar(); }})] : []));
        return el("div", {className: "inf-sem"}, el("h4", {textContent: d}), b, ta, sug);
      };
      return el("section", {className: "card"}, el("h3", {textContent: "Semáforos"}), el("div", {className: "inf-sems"}, ...["Global", "Alcance", "Plazo", "Coste", "Riesgos"].map(card)));
    }
    function kpis() {
      const k = S.x.contenido.kpis, t = k.tareas, r = k.riesgos, p = k.preguntas, IDS = k.ids || {};
      // cada tarjeta lleva a su pestaña con foco en esos elementos (fIr de carpeta.js); sin ids (informes antiguos) solo abre la pestaña; 0 = no navegable
      const ir = (tab, clave, lab, filtro) => () => typeof fIr === "function" && fIr(tab, IDS[clave] ? {ids: IDS[clave].map(x => typeof x === "object" ? x.id : x), filtro, etiqueta: lab} : null);
      const tarjeta = (n, lab, b, alerta, nav, cuenta = n) => {
        const ok = nav && Number(cuenta) > 0;
        return el(ok ? "button" : "div", {className: "inf-kpi" + (alerta ? " alerta" : "") + (ok ? " inf-go" : ""), ...(ok ? {type: "button", onclick: nav, title: "Ver en su pestaña"} : {"aria-disabled": "true"})},
          el("b", {textContent: n}), el("span", {textContent: lab}), b && b.propuestos ? el("small", {className: "inf-np", textContent: "incl. " + b.propuestos + " sin revisar"}) : "");
      };
      // bandas de severidad = UMBRALES de informe.py (sev_ambar 6, sev_rojo 12)
      const banda = s => s == null ? ["sin valorar", ""] : s >= 12 ? ["alto", "no"] : s >= 6 ? ["medio", "w"] : ["bajo", "ok"];
      const aRiesgo = x => typeof fIr === "function" && fIr("riesgos", {ids: [x.id], etiqueta: x.codigo || x.titulo});
      return el("section", {className: "card"}, el("h3", {textContent: "Indicadores"}), el("div", {className: "inf-kpis"},
        tarjeta(t.abiertas, "Tareas abiertas", t, false, ir("pendientes", "tareas_abiertas", "Tareas abiertas", "abierto")), tarjeta(t.vencidas, "Tareas vencidas", null, t.vencidas > 0, ir("pendientes", "tareas_vencidas", "Tareas vencidas", "abierto")),
        tarjeta(t.cerradas, "Cerradas en el periodo", null, false, ir("pendientes", "tareas_cerradas", "Cerradas en el periodo", "cerrados")),
        tarjeta(r.total, "Riesgos abiertos", r, false, ir("riesgos", "riesgos_abiertos", "Riesgos abiertos")), tarjeta(r.por_severidad.alta, "Riesgos de severidad alta", null, r.por_severidad.alta > 0, ir("riesgos", "riesgos_altos", "Severidad alta")),
        tarjeta(r.por_severidad.sin_valorar, "Riesgos sin valorar", null, false, ir("riesgos", "riesgos_sin_valorar", "Riesgos sin valorar")),
        tarjeta(k.decisiones.n, "Decisiones del periodo", k.decisiones, false, ir("decisiones", "decisiones", "Decisiones del periodo")), tarjeta(p.abiertas, "Preguntas abiertas", p, false, ir("preguntas", "preguntas_abiertas", "Preguntas abiertas")),
        tarjeta(p.escalados, "Escalados", null, p.escalados > 0, ir("preguntas", "escalados", "Escalados")),
        tarjeta(k.requisitos.total, "Requisitos", k.requisitos, false, ir("requisitos", "requisitos", "Requisitos")), tarjeta(k.historias.total, "Historias", k.historias, false, ir("historias", "historias", "Historias")),
        tarjeta(k.hitos.vencidos + "/" + k.hitos.lista.length, "Hitos vencidos", k.hitos, k.hitos.vencidos > 0, ir("hitos", "hitos_vencidos", "Hitos vencidos"), k.hitos.vencidos)),
        el("p", {className: "muted", textContent: "Revisión: " + k.revision.aprobado + " aprobados · " + k.revision.propuesto + " propuestos. Pulsa un indicador para ver sus elementos."}),
        r.top.length ? el("div", {className: "inf-top-w"}, el("table", {className: "inf-top"}, el("caption", {textContent: "Riesgos principales"}),
          el("thead", {}, el("tr", {}, ...[["Código"], ["Riesgo"], ["Probabilidad", "n"], ["Impacto", "n"], ["Severidad", "n"], ["Responsable"]].map(([h, cl]) => el("th", {scope: "col", className: cl || "", textContent: h})))),
          el("tbody", {}, ...r.top.map(x => {
            const [bt, bc] = banda(x.sev);
            const tr = el("tr", {className: x.id ? "inf-go" : "", ...(x.id ? {tabIndex: 0, title: "Abrir el riesgo", onclick: () => aRiesgo(x), onkeydown: ev => { if (ev.key === "Enter") aRiesgo(x); }} : {})},
              el("td", {className: "cod", textContent: x.codigo || "—"}), el("td", {}, x.titulo, x.revision === "propuesto" ? el("span", {className: "badge w", textContent: "BORRADOR"}) : ""),
              ...[x.p, x.i].map(v => el("td", {className: "n", textContent: v ?? "—"})),
              el("td", {className: "n"}, el("span", {className: "badge " + bc, textContent: bt + (x.sev != null ? " · " + x.sev : "")})), el("td", {textContent: x.dueno || "—"}));
            return tr;
          })))) : "");
    }
    function graficos() {
      const g = S.x.graficos, fig = (k, t) => {
        if (!g[k]) return ""; const f = el("figure", {className: "inf-fig"}); f.innerHTML = g[k]; f.append(el("figcaption", {textContent: t}));
        // si el servidor marca celdas/filas con data-id (riesgos), se abren en su pestaña
        for (const n of f.querySelectorAll("[data-id]")) { n.style.cursor = "pointer"; n.setAttribute("tabindex", "0"); n.setAttribute("role", "link");
          const go = () => typeof fIr === "function" && fIr("riesgos", {ids: n.getAttribute("data-id").split(/[\s,]+/).filter(Boolean)}); n.addEventListener("click", go); n.addEventListener("keydown", ev => { if (ev.key === "Enter") go(); }); }
        return f;
      };
      return el("section", {className: "card"}, el("h3", {textContent: "Gráficos"}), el("div", {className: "inf-graf"},
        fig("estados", "Requisitos e historias por estado"), fig("calor", "Riesgos: probabilidad × impacto (pasa el ratón por una celda)"), fig("linea", "Tareas abiertas tras cada reunión")));
    }
    // [n] numeradas en toda la narrativa por orden de aparición (como en la exportación)
    function numeros() {
      const n = new Map();
      for (const [s] of SEC) for (const f of S.x.contenido.narrativa[s] || []) for (const r of f.refs || []) if (!n.has(r.id)) n.set(r.id, n.size + 1);
      return n;
    }
    function narrativa() {
      const N = numeros(), nar = S.x.contenido.narrativa;
      const guardar = s => patch({narrativa: {[s]: nar[s]}});
      const refLink = r => {
        const txt = "[" + N.get(r.id) + "]", tit = (r.codigo || "") + " " + (r.titulo || "") + (r.revision === "propuesto" ? " (BORRADOR)" : "");
        const a = r.cita && r.cita.mid ? fLink(r.cita, txt) : el("span", {className: "ts", textContent: txt});
        a.title = tit; return a;
      };
      const seccion = ([s, nom]) => {
        nar[s] = nar[s] || [];
        const lista = el("ol", {className: "inf-frases"}, ...nar[s].map((f, j) => el("li", {},
          el("textarea", {rows: 2, value: f.texto, ariaLabel: nom + ", frase " + (j + 1), onblur: ev => { if (ev.target.value !== f.texto) { f.texto = ev.target.value; guardar(s); } }}),
          el("span", {className: "inf-refs"}, ...(f.refs || []).map(refLink), (f.refs || []).some(r => r.revision === "propuesto") ? el("span", {className: "badge w", textContent: "BORRADOR"}) : ""),
          el("button", {type: "button", className: "link", textContent: "Quitar", ariaLabel: "Quitar frase " + (j + 1), onclick: async () => { nar[s].splice(j, 1); if (await guardar(s)) pintar(); }}))));
        return el("div", {className: "inf-sec"}, el("h4", {textContent: nom}), nar[s].length ? lista : el("p", {className: "muted", textContent: "Sin texto: escríbelo o pulsa «Redactar con IA»."}),
          el("button", {type: "button", className: "sec sm", textContent: "+ Añadir", onclick: async () => { nar[s].push({texto: "", refs: []}); if (await guardar(s)) { pintar(); raiz.querySelector(`[aria-label="${nom}, frase ${nar[s].length}"]`)?.focus(); } }}));
      };
      const fu = [...N.entries()].map(([id, n]) => { for (const [s] of SEC) for (const f of nar[s] || []) for (const r of f.refs || []) if (r.id === id) return [n, r]; });
      return el("section", {className: "card"}, el("h3", {textContent: "Narrativa"}), ...SEC.map(seccion),
        fu.length ? el("details", {className: "inf-fuentes"}, el("summary", {textContent: "Fuentes (" + fu.length + ")"}),
          el("ol", {}, ...fu.map(([n, r]) => el("li", {value: n}, refLink(r), " " + (r.codigo || "") + " " + (r.titulo || ""), r.cita?.texto ? el("q", {textContent: r.cita.texto}) : "")))) : "");
    }
    function notas() {
      const v = S.x.contenido.notas || "";
      return el("section", {className: "card"}, el("h3", {textContent: "Notas"}),
        el("textarea", {rows: 3, className: "inf-notas", value: v, ariaLabel: "Notas del informe", placeholder: "Notas para el comité…", onblur: ev => ev.target.value !== v && patch({notas: ev.target.value})}));
    }
    cargar();
    return [raiz];
  }
  document.addEventListener("DOMContentLoaded", () => { FVISTAS.informe = vista; KIND.informe = "Redactar informe de estado"; });
})();
