// Carpeta = expediente (diseño: design/Carpeta.dc.html): Resumen | Pendientes | Línea de tiempo | Preguntar | Comparar | Ajustes.
// Se engancha a app.js por pintarHome() -> carpetaVista(c) y por sondear() -> carpetaTrasCola(); usa los ganchos #f-tabs / #f-panel / #f-nuevo.
const FTABS = [
  ["resumen", "Resumen"],
  ["revision", "Revisión"],
  ["pendientes", "Pendientes"],
  ["requisitos", "Requisitos"],
  ["historias", "Historias"],
  ["interesados", "Interesados"],
  ["decisiones", "Decisiones"],
  ["riesgos", "Riesgos"],
  ["preguntas", "Preguntas"],
  ["hitos", "Hitos"],
  ["informe", "Informe"],
  ["linea", "Línea de tiempo"],
  ["preguntar", "Preguntar"],
  ["comparar", "Comparar"],
  ["ajustes", "Ajustes"],
];
// pestañas del registro (F3/F4): tipo de entidad que muestra cada una. Para sustituir el placeholder de una vista (F4) basta con registrar su función en FVISTAS[clave] = (c, e) => nodos.
const FREG = {
    requisitos: "requisito",
    historias: "historia",
    interesados: "interesado",
    decisiones: "decision",
    riesgos: "riesgo",
    preguntas: "pregunta",
    hitos: "hito",
    ideas: "idea",
    hipotesis: "hipotesis",
    experimentos: "experimento",
    aprendizajes: "insight",
  },
  FVISTAS = {};
const FCTX = new Set(["riesgos", "preguntas", "hitos"]);
const FINNOV = new Set(["ideas", "hipotesis", "experimentos", "aprendizajes"]); // fijas solo en carpetas de tipo «Innovación» // pestañas contextuales: solo se ven mientras están abiertas (se llega desde el informe)
let fReg = { rev: 0, tipos: {}, proyecto: false, tipo: "" }; // contadores del registro de la carpeta abierta (para mostrar/ocultar pestañas)
// las de FCTX (riesgos, preguntas, hitos) solo con contenido o abiertas; el resto de tipos, también en carpetas de tipo «Proyecto»
const fFija = k => (FINNOV.has(k) ? fReg.tipo === "Innovación" : fReg.proyecto && !FCTX.has(k)); // pestaña que se ve aunque esté vacía
const fTabVisible = k => (FREG[k] ? k === ftab || fFija(k) || !!fReg.tipos[FREG[k]] : true);
// ---- navegación con foco: fIr(pestaña, {ids, filtro, etiqueta}) abre la pestaña y la vista destino consume el foco UNA vez (fTomaFoco):
// filtra a esos ids si sabe, hace scroll al primero y lo resalta (~2 s). Sin ids (informes antiguos): solo abre la pestaña.
let fFoco = null;
function fIr(tab, foco) {
  fFoco = foco && foco.ids ? { ...foco, tab } : null;
  ftab = tab;
  lsSet("ftab", tab);
  fsucio = true;
  pintarHome();
}
function fTomaFoco(tab) {
  const f = fFoco && fFoco.tab === tab ? fFoco : null;
  if (f) fFoco = null;
  return f;
}
function fResalta(nodos) {
  const ns = [...nodos].filter(Boolean);
  if (!ns.length) return;
  ns[0].scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  for (const n of ns) {
    n.classList.remove("f-flash");
    void n.offsetWidth;
    n.classList.add("f-flash");
    setTimeout(() => n.classList.remove("f-flash"), 2400);
  }
}
const fResaltaIds = (raiz, ids) => setTimeout(() => fResalta([...raiz.querySelectorAll("[data-id]")].filter(n => ids.includes(n.getAttribute("data-id")))), 60);
const fChipFoco = (n, quitar, etq) =>
  el(
    "div",
    { className: "f-foco", role: "status" },
    el("span", { textContent: "Mostrando " + n + (n === 1 ? " elemento" : " elementos") + " del informe" + (etq ? " · " + etq : "") }),
    el("button", { className: "link", type: "button", textContent: "Quitar filtro", onclick: quitar }),
  );
const fTabTxt = (k, t) => (k === "revision" ? t + " (" + fReg.rev + ")" : t);
async function fCargaReg(c, tipoCarpeta) {
  try {
    const r = await api("/api/reg?" + new URLSearchParams({ c }));
    fReg = {
      rev: r.contadores?.por_revision?.propuesto || 0,
      tipos: r.contadores?.por_tipo || {},
      proyecto: tipoCarpeta === "Proyecto",
      tipo: tipoCarpeta || "",
    };
  } catch {
    fReg = { rev: 0, tipos: {}, proyecto: tipoCarpeta === "Proyecto", tipo: tipoCarpeta || "" };
  }
  pintaTabs();
}
let ftab = lsGet("ftab", "resumen"),
  fuC = null,
  fsucio = true,
  fseq = 0,
  fpen = { estado: "abierto", resp: "", orden: "plazo" },
  fcmp = { a: "", b: "" };
const fFecha = iso => (iso ? new Date(iso + "T12:00").toLocaleDateString("es", { day: "numeric", month: "short", year: "numeric" }) : "");
const carpetaTrasCola = () => {
  fsucio = true;
};
const fEnCola = async (url, body) => {
  await post(url, { ...body, gpu: $("usar-gpu").checked });
  aviso("Añadido a la cola");
  sondear();
};
// abre un documento en su minuto exacto (como las marcas del propio documento)
async function irMinuto(mid, ver, t) {
  await abrir(mid, ver);
  if (cur.video && t) mpSeek(t, cur.videourl, cur.m.label);
}
const fLink = (r, txt) =>
  el("a", {
    href: "#",
    className: "ts",
    textContent: txt || r.doc + " · " + mmss(r.t || 0),
    onclick: e => {
      e.preventDefault();
      fallo(irMinuto)(r.mid, r.ver, r.t);
    },
  });

// «Enlaces» de la cabecera: dónde vive el proyecto fuera (servidor de equipo, carpeta de OneDrive) y los destinos con los que trabaja
// (repositorio, proyecto de Jira o Azure…). Sin enlaces no se ve: no ocupa sitio.
function fEnlaces(c) {
  const w = $("f-enl"),
    l = $("f-enl-l");
  const item = (nombre, tipo, extra) =>
    el("a", { role: "menuitem", className: "enl", ...extra }, el("span", { textContent: nombre }), el("span", { className: "muted", textContent: tipo }));
  api("/api/enlaces?c=" + encodeURIComponent(c))
    .catch(() => [])
    .then(xs => {
      if (fuC !== c) return; // el usuario ya está en otro proyecto
      const its = xs.map(x =>
        x.carpeta
          ? item(x.nombre, x.tipo + " · abrir carpeta", {
              href: "#",
              title: x.ruta,
              onclick: e => {
                e.preventDefault();
                w.open = false;
                fallo(post)("/api/compartir/abrir", { c });
              },
            })
          : item(x.nombre, x.tipo + (x.ultimo ? " · último envío" : ""), {
              href: x.url,
              target: "_blank",
              rel: "noopener",
              title: x.url,
              onclick: () => (w.open = false),
            }),
      );
      if (AJ.servidor)
        its.push(
          item("Copiar enlace a este proyecto", "para compartirlo con el equipo", {
            href: "#",
            onclick: e => {
              e.preventDefault();
              w.open = false;
              navigator.clipboard.writeText(location.origin + "/#/p/" + encodeURIComponent(c)).then(() => aviso("Enlace copiado"));
            },
          }),
        );
      l.replaceChildren(...its);
      $("f-enl-n").textContent = xs.length ? String(xs.length) : "";
      w.hidden = !its.length;
    });
}
function carpetaVista(c) {
  const on = typeof c === "string" && c !== "";
  $("f-tabs").hidden = $("f-panel").hidden = $("f-nuevo").hidden = !on;
  for (const id of ["f-plant", "f-estilo", "f-preguntar"]) $(id).hidden = true; // pasan a las pestañas Ajustes y Preguntar
  $("docs-w").hidden = on && ftab !== "documentos";
  $("f-mas").hidden = !on;
  if (on && window.Enviar?.split && $("f-env-s")?.dataset.c !== c) {
    // split «Enviar proyecto ▾» (destino fijado/último + flecha); #f-env queda oculto para la paleta
    $("f-env-s")?.remove();
    const g = Enviar.split(null, { c }, { label: "Enviar proyecto", cls: "sec" });
    g.id = "f-env-s";
    g.dataset.c = c;
    $("f-env").after(g);
  }
  const sinDocs = on && !todas.some(m => (m.carpeta || "") === c); // proyecto vacío: no hay nada que enviar
  $("f-env").hidden = !on || sinDocs || !!$("f-env-s");
  if ($("f-env-s")) $("f-env-s").hidden = !on || sinDocs;
  if (!$("f-env-m"))
    $("f-ren").before(
      el("button", {
        role: "menuitem",
        id: "f-env-m",
        className: "solo-movil",
        textContent: "Enviar proyecto…",
        onclick: () => {
          $("f-mas").open = false;
          $("f-env").click();
        },
      }),
    );
  $("f-env-m").hidden = sinDocs;
  if (!on) {
    fuC = null;
    $("f-sub").replaceChildren();
    $("f-auto").hidden = true;
    $("f-enl").hidden = true;
    return;
  }
  $("f-nuevo").textContent = "+ Añadir";
  pintaTabs();
  if (fuC === c && !fsucio) return;
  if (fuC !== c) fpenFoco = null;
  fEnlaces(c);
  fuC = c;
  fsucio = false;
  pintaTabs();
  fRender();
}
// 5 pestañas: Resumen | Documentos | Extraído (segmentado: Revisión, Tareas, Decisiones…) | Informe | Preguntar; Línea de tiempo, Comparar y Ajustes en «⋯ Más»
const FTOP = [
  ["resumen", "Resumen"],
  ["documentos", "Documentos"],
  ["extraido", "Extraído"],
  ["informe", "Informe"],
  ["preguntar", "Preguntar"],
];
const FEXT = [
  ["pendientes", "Tareas"],
  ["decisiones", "Decisiones"],
  ["requisitos", "Requisitos"],
  ["historias", "Historias"],
  ["interesados", "Interesados"],
  ["riesgos", "Riesgos"],
  ["preguntas", "Preguntas"],
  ["hitos", "Hitos"],
  ["ideas", "Ideas"],
  ["hipotesis", "Hipótesis"],
  ["experimentos", "Experimentos"],
  ["aprendizajes", "Aprendizajes"],
];
const FMAS = { equipo: "Equipo", linea: "Línea de tiempo", comparar: "Comparar", ajustes: "Ajustes del proyecto" };
let fCnt = {},
  fPend = 0,
  fUltExt = lsGet("fext", "pendientes"),
  fScrollA = null;
const fTop = k => (k === "revision" || FEXT.some(([x]) => x === k) ? "extraido" : FMAS[k] ? "" : k);
const fN = k => (k === "pendientes" ? fPend : fReg.tipos[FREG[k]] || 0);
const fImportable = k => ["requisitos", "historias", "interesados", "decisiones"].includes(k); // vista que entiende /api/reg/importar (lo usa regImportar, shell.js)
function pintaTabs() {
  if (fuC === null) return;
  if (ftab === "extraido") ftab = (fUltExt === "revision" || FEXT.some(([k]) => k === fUltExt)) && fTabVisible(fUltExt) ? fUltExt : "pendientes"; // la ruta …/extraido abre la última sub-pestaña
  if (!FORDEN.includes(ftab) || !fTabVisible(ftab)) ftab = "resumen";
  const top = fTop(ftab),
    nDoc = todas.filter(m => (m.carpeta || "") === fuC).length;
  const ir = k => {
      ftab = k;
      lsSet("ftab", k);
      fsucio = true;
      pintarHome();
    },
    c = (t, k) => {
      const id = fuC + "|" + k,
        tic = id in fCnt && fCnt[id] !== t;
      fCnt[id] = t;
      return el("span", { className: "c" + (tic ? " tic" : ""), textContent: t ? " " + t : "" });
    }; // tic: el número cambió
  // «Por revisar» solo como segmento activo: fuera de él ya lo anuncia el aviso «N por revisar · Revisar»
  const segs = [["revision", "Por revisar"], ...FEXT].filter(
    ([k]) => k === ftab || (k !== "revision" && fTabVisible(k) && (fN(k) || k === "pendientes" || fFija(k))),
  );
  const nExt = segs.reduce((a, [k]) => a + (k === "revision" ? 0 : fN(k)), 0);
  $("f-tabs").replaceChildren(
    ...FTOP.map(([k, t]) =>
      el(
        "button",
        { role: "tab", "aria-selected": k === top, onclick: () => ir(k === "extraido" ? (fTabVisible(fUltExt) ? fUltExt : "pendientes") : k) },
        t,
        c(k === "extraido" ? nExt : k === "documentos" ? nDoc : 0, k),
      ),
    ),
  );
  if (top === "extraido") {
    fUltExt = ftab;
    lsSet("fext", ftab);
  }
  $("f-sub").replaceChildren(
    ...(top === "extraido"
      ? [
          ...(fReg.rev && ftab !== "revision"
            ? [
                el(
                  "div",
                  { className: "aviso f-rev", role: "status" },
                  el("span", {}, el("b", { textContent: fReg.rev + " por revisar" }), " · propuestos por la IA, sin aprobar"),
                  el("span", { className: "grow" }),
                  el(
                    "span",
                    { className: "split" },
                    el("button", { className: "sec", textContent: "Revisar", onclick: () => ir("revision") }),
                    el("button", {
                      className: "sec",
                      textContent: "Aprobar todo",
                      title: "Aprueba los " + fReg.rev + " (se puede deshacer)",
                      onclick: fallo(() => fAprobarTodo(fuC)),
                    }),
                  ),
                ),
              ]
            : []),
          el(
            "div",
            { className: "row wrap f-seg" },
            el(
              "div",
              { className: "seg", role: "tablist", ariaLabel: "Qué se ha extraído" },
              ...segs.map(([k, t]) =>
                el("button", { role: "tab", "aria-selected": k === ftab, onclick: () => ir(k) }, t, c(k === "revision" ? fReg.rev : fN(k), k)),
              ),
            ),
            el("span", { className: "grow" }),
          ),
        ] // «Importar Excel/CSV», en el ⋯ de la barra de cada vista (regImportarAcc)
      : FMAS[ftab]
        ? [
            el(
              "div",
              { className: "row f-mas-v" },
              el("button", { className: "link", textContent: "← Resumen", onclick: () => ir("resumen") }),
              el("h2", { textContent: FMAS[ftab] }),
            ),
          ]
        : []),
  );
  for (const w of [$("f-tabs"), $("f-sub").querySelector(".seg")]) {
    const on = w?.querySelector("[aria-selected=true]");
    if (!w) continue;
    if (on && w.scrollWidth > w.clientWidth) {
      const a = on.getBoundingClientRect(),
        b = w.getBoundingClientRect();
      if (a.left < b.left) w.scrollLeft += a.left - b.left - 28;
      else if (a.right > b.right) w.scrollLeft += a.right - b.right + 28;
    } // la activa, a la vista (lo mínimo)
    fBordes(w);
  }
}
// borde difuminado solo del lado por el que queda contenido (clases fl/fr → máscara en app.css)
const fBordes = w => {
  w.classList.add("fb");
  const f = () => {
    w.classList.toggle("fl", w.scrollLeft > 2);
    w.classList.toggle("fr", w.scrollLeft + w.clientWidth < w.scrollWidth - 2);
  };
  w.onscroll = f;
  f();
};
$("f-nuevo").onclick = () => formNuevo();
// «+ Nuevo documento» dentro de la carpeta hereda perfil, estilo (al exportar), glosario y carpeta (en el servidor) e idioma por defecto
const formNuevo0 = formNuevo;
formNuevo = function (m, a) {
  formNuevo0(m, a);
  const c = m ? m.carpeta : typeof fsel === "string" ? fsel : "";
  if (c)
    api("/api/exp?c=" + encodeURIComponent(c))
      .then(e => {
        if (e.ajustes.idioma && !m) {
          $("idioma").value = e.ajustes.idioma;
          $("idioma").onchange();
        }
      })
      .catch(() => {});
};

const FORDEN = ["resumen", "documentos", "revision", ...FEXT.map(([k]) => k), "informe", "preguntar", ...Object.keys(FMAS)];
let fPintado = { c: null, tab: null }; // lo último pintado: dirección del eje X entre pestañas
async function fRender() {
  const c = fuC,
    n = ++fseq,
    p = $("f-panel");
  if (fPintado.c !== c)
    p.replaceChildren(el("div", { className: "card", "aria-busy": "true" }, ...sk(3)), el("div", { className: "card", "aria-hidden": "true" }, ...sk(5)));
  if (p.contains($("qpanel"))) {
    $("qpanel").hidden = true;
    document.querySelector("main").append($("qpanel"));
  } // el panel de preguntas se conserva al cambiar de pestaña
  try {
    const e = await api("/api/exp?c=" + encodeURIComponent(c));
    fPend = e.pend || 0;
    await fCargaReg(c, e.tipo);
    if (n !== fseq) return;
    const nodos = await (
      {
        documentos: async () => [],
        resumen: tResumen,
        revision: tRevision,
        requisitos: tVista,
        historias: tVista,
        interesados: tVista,
        decisiones: tVista,
        riesgos: tVista,
        preguntas: tVista,
        hitos: tVista,
        ideas: tVista,
        hipotesis: tVista,
        experimentos: tVista,
        aprendizajes: tVista,
        equipo: tEquipo,
        informe: tVista,
        pendientes: tPendientes,
        linea: tLinea,
        preguntar: tPreguntar,
        comparar: tComparar,
        ajustes: tAjustes,
      }[ftab] || tResumen
    )(c, e, ftab);
    if (n !== fseq) return;
    p.replaceChildren(...nodos);
    const dir = fPintado.c === c && fPintado.tab !== ftab ? Math.sign(FORDEN.indexOf(ftab) - FORDEN.indexOf(fPintado.tab)) : 0;
    fPintado = { c, tab: ftab };
    ejeX(ftab === "documentos" ? $("docs-w") : p, dir);
    const pl_ = PL.find(t => t.id === e.perfil);
    $("fsub").replaceChildren(
      ...[plural(todas.filter(m => (m.carpeta || "") === c).length), e.pend ? e.pend + (e.pend === 1 ? " pendiente" : " pendientes") : ""]
        .filter(Boolean)
        .join(" · "),
      ...[e.tipo, pl_ && "Perfil: " + pl_.nombre, ...e.datos.slice(0, 2).map(d => d.v)]
        .filter(Boolean)
        .map(t => el("span", { className: "fs-x", textContent: " · " + t })),
    );
    $("docs-w").hidden = ftab !== "documentos";
    fAutoLinea(c);
    if (fScrollA) {
      $(fScrollA)?.scrollIntoView({ block: "start" });
      fScrollA = null;
    }
  } catch (err) {
    // estado vacío amable con «Reintentar» (el detalle técnico, en el title)
    if (n === fseq)
      p.replaceChildren(
        el(
          "div",
          { className: "vacio f-fallo", role: "alert", title: err.message },
          el("p", { textContent: "No se ha podido cargar esta sección." }),
          el("button", { className: "sec", textContent: "Reintentar", onclick: fRe }),
        ),
      );
  }
}
const fRe = () => {
  fsucio = true;
  return fRender();
};
const fEspera = n => new Promise(ok => setTimeout(ok, 420 * (parseFloat(getComputedStyle(n).getPropertyValue("--mv")) || 0)));
function fLogro(t, txt, acc, fn) {
  // estado vacío «todo hecho»: check trazado + una acción
  const svg =
    '<svg viewBox="0 0 48 48" width="48" height="48" aria-hidden="true"><circle cx="24" cy="24" r="21" pathLength="1"/><path d="M15 25l6 6 12-13" pathLength="1"/></svg>';
  const w = el("div", { className: "vacio logro", role: "status" });
  w.innerHTML = svg;
  w.append(
    el("b", { textContent: t }),
    el("p", { textContent: txt }),
    ...(acc ? [el("button", { type: "button", className: "sec", textContent: acc, onclick: fn })] : []),
  );
  return w;
}
const H = (t, ...k) => el("div", { className: "sec-h" }, el("h2", { textContent: t }), ...k);

// ---- inicio: pendientes abiertos de todas las carpetas (vencidos y con plazo primero) ----
let hpSeq = 0;
async function homePend() {
  const cs = carpetas.filter(c => RES[c]?.pend),
    n = ++hpSeq;
  const rs = await Promise.all(
    cs.map(c =>
      api("/api/exp/pendientes?" + new URLSearchParams({ c, estado: "abierto", orden: "plazo" }))
        .then(r => r.items.filter(p => p.estado === "abierto").map(p => ({ ...p, c })))
        .catch(() => []),
    ),
  );
  if (n !== hpSeq) return;
  const its = rs.flat().sort((a, b) => !!b.vencido - !!a.vencido || !!b.pronto - !!a.pronto || (a.fecha || "9").localeCompare(b.fecha || "9"));
  $("h-pend").hidden = !its.length;
  $("h-pend-n").textContent = its.length > 5 ? "Ver los " + its.length : "Ver todos";
  $("h-pend-l").replaceChildren(
    ...its.slice(0, 5).map(p => {
      const chk = el("input", {
        type: "checkbox",
        ariaLabel: "Marcar hecho: " + p.texto,
        onchange: fallo(async () => {
          chk.disabled = true;
          try {
            await post("/api/exp/pendientes", { c: p.c, id: p.id, estado: "hecho" });
          } catch (e) {
            chk.disabled = chk.checked = false;
            throw e;
          }
          await cargarLista();
          hechoDeshacer(p.c, p, () => vistaAct === "home" && pintarHome());
        }),
      });
      const f = p.vencido
        ? el("b", { className: "hp-f err", textContent: "Vencido" })
        : el("span", { className: "hp-f" + (p.pronto ? " w" : ""), textContent: p.plazo || (p.fecha ? fFecha(p.fecha) : "Sin fecha") });
      return el(
        "li",
        {},
        chk,
        el(
          "div",
          { className: "hp-t" },
          el("span", { textContent: p.texto }),
          el(
            "small",
            {},
            el("a", {
              href: "#",
              textContent: p.c,
              onclick: e => {
                e.preventDefault();
                fsel = p.c;
                ftab = "pendientes";
                lsSet("ftab", ftab);
                fsucio = true;
                pintarHome();
              },
            }),
            p.resp ? " · " + p.resp : "",
          ),
        ),
        f,
      );
    }),
  );
}

// ---- banner «parece hecho» ----
function bannerSug(c, sug) {
  if (!sug.length) return [];
  const hechos = sug.filter(p => p.sugerido.tipo === "hecho").length,
    n = sug.length;
  return [
    el(
      "div",
      { className: "aviso f-sug" },
      el(
        "div",
        {},
        el("b", {
          textContent:
            n === 1 ? "Un documento nuevo parece cerrar o cambiar 1 pendiente" : "Los documentos nuevos parecen cerrar o cambiar " + n + " pendientes",
        }),
        el("div", {
          className: "muted",
          textContent:
            sug
              .slice(0, 2)
              .map(p => "«" + p.texto + "»")
              .join(" y ") +
            (n > 2 ? "…" : "") +
            " Confirma antes de cerrarlos.",
        }),
      ),
      el(
        "div",
        { className: "row" },
        ...(ftab === "pendientes"
          ? []
          : [
              el("button", {
                className: "sec",
                textContent: "Revisar",
                onclick: () => {
                  ftab = "pendientes";
                  lsSet("ftab", ftab);
                  fsucio = true;
                  pintarHome();
                },
              }),
            ]),
        el("button", {
          className: "pri",
          textContent: hechos === n ? "Cerrar los " + n : "Aceptar los " + n,
          onclick: fallo(async () => {
            await post("/api/exp/sugerencia", { c, todas: true, aceptar: true });
            await fRe();
          }),
        }),
      ),
    ),
  ];
}

// ---- Resumen ----
// proyecto sin documentos: la zona de soltar viva (toda la ventana acepta archivos, shell.js) en vez de «Ninguna/Ninguno» y acciones sobre nada
function fSoltar() {
  const tactil = matchMedia("(max-width: 560px), (pointer: coarse)").matches,
    vi = el("span", { className: "vi", ariaHidden: "true" });
  vi.innerHTML =
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4M6 10l6-6 6 6"/><path d="M4 20h16"/></svg>';
  return el(
    "div",
    { className: "vacio vacio-e f-drop" },
    vi,
    el("b", { textContent: tactil ? "Añade el primer documento" : "Suelta aquí el primer documento" }),
    el("p", {
      className: "muted",
      textContent: "Vídeo, audio, PDF, Word, imágenes o correos. Lo que se extraiga (tareas, decisiones, requisitos…) aparecerá aquí.",
    }),
    el("button", {
      type: "button",
      className: "sec",
      textContent: "Elegir archivos",
      onclick: () => {
        formNuevo();
        $("an-file").click();
      },
    }),
  );
}
async function tResumen(c, e) {
  if (!todas.some(m => (m.carpeta || "") === c)) return [...(e.aviso ? [el("p", { className: "aviso w", textContent: e.aviso })] : []), fSoltar()];
  const [est, pen] = await Promise.all([api("/api/exp/estado?c=" + encodeURIComponent(c)), api("/api/exp/pendientes?c=" + encodeURIComponent(c))]);
  const nodos = [...bannerSug(c, pen.sugeridos)];
  // datos de la carpeta (clave/valor libres con sugerencias por tipo)
  let datos = e.datos.map(d => ({ ...d })),
    tipo = e.tipo,
    abierto = false;
  const abrirD = t =>
    el("button", {
      className: "link",
      textContent: t,
      onclick: () => {
        abierto = true;
        pintD();
        caja.querySelector("input, button")?.focus();
      },
    });
  const caja = el("div"),
    pintD = () => {
      caja.className = abierto ? "card" : "";
      if (!abierto) {
        // solo los datos rellenos, como chips; el editor se abre con «+ Añadir datos» / «Editar datos»
        const llenos = e.datos.filter(d => d.k && d.v);
        if (!llenos.length && !e.aviso) return caja.replaceChildren();
        return caja.replaceChildren(
          ...(e.aviso ? [el("p", { className: "aviso w", textContent: e.aviso })] : []),
          el(
            "div",
            { className: "f-datos" },
            ...llenos.map(d => el("span", { className: "dchip" }, el("b", { textContent: d.k }), d.v)),
            ...(llenos.length ? [abrirD("Editar datos")] : []),
          ),
        );
      }
      const rows = datos.map((d, i) =>
        el(
          "div",
          { className: "row f-dato" },
          el("input", { value: d.k, ariaLabel: "Dato", placeholder: "Dato", oninput: ev => (d.k = ev.target.value), style: "flex:0 1 200px" }),
          el("input", { value: d.v, ariaLabel: "Valor de " + d.k, placeholder: "Valor", oninput: ev => (d.v = ev.target.value) }),
          el("button", {
            className: "sec sm",
            textContent: "×",
            ariaLabel: "Quitar " + d.k,
            onclick: () => {
              datos.splice(i, 1);
              pintD();
            },
          }),
        ),
      );
      const sug = e.sugerencias.filter(k => !datos.some(d => d.k === k));
      caja.replaceChildren(
        H("Datos" + (tipo ? " · " + tipo : "")),
        ...(e.aviso ? [el("p", { className: "aviso w", textContent: e.aviso })] : []),
        ...rows,
        el(
          "div",
          { className: "row wrap", style: "margin-top:8px" },
          ...sug.map(k =>
            el("button", {
              className: "sec sm",
              textContent: "+ " + k,
              onclick: () => {
                datos.push({ k, v: "" });
                pintD();
              },
            }),
          ),
          el("button", {
            className: "sec sm",
            textContent: "+ Otro dato",
            onclick: () => {
              datos.push({ k: "", v: "" });
              pintD();
            },
          }),
          el("span", { className: "grow" }),
          el("button", {
            className: "sec sm",
            textContent: "Cancelar",
            onclick: () => {
              datos = e.datos.map(d => ({ ...d }));
              abierto = false;
              pintD();
            },
          }),
          el("button", {
            className: "pri sm",
            textContent: "Guardar datos",
            onclick: fallo(async () => {
              await post("/api/exp/datos", { c, datos });
              aviso("Datos guardados");
              await fRe();
            }),
          }),
        ),
      );
    };
  pintD();
  nodos.push(caja);
  const hayDatos = e.datos.some(d => d.k && d.v);
  // estado actual
  const dv = est.decisiones,
    red = est.redaccion;
  // cabecera en 2 filas por debajo de 700 px (.f-est-h, app.css): el título entero arriba; «+ Añadir datos» y «Generar resumen» debajo
  nodos.push(
    el(
      "div",
      { className: "card" },
      Object.assign(
        H(
          "Estado actual",
          ...(hayDatos ? [] : [abrirD("+ Añadir datos")]),
          el("button", {
            className: "sec sm",
            textContent: red ? "Regenerar resumen" : "Generar resumen",
            onclick: fallo(() => fEnCola("/api/exp/estado", { c })),
          }),
        ),
        { className: "sec-h f-est-h" },
      ),
      ...(red
        ? [
            el("ul", { className: "f-red" }, ...red.frases.map(f => el("li", {}, f.texto + " ", ...f.refs.flatMap(r => [fLink(r), " "])))),
            ...(est.obsoleta ? [el("p", { className: "muted", textContent: "Hay documentos nuevos desde que se generó: regenéralo para incluirlos." })] : []),
          ]
        : [el("p", { className: "muted", textContent: "Aún no hay resumen redactado; abajo, los datos con su fuente." })]),
      el("h3", { textContent: "Decisiones vigentes · " + dv.vigentes.length }),
      ...(dv.vigentes.length
        ? [el("ul", { className: "f-lst" }, ...dv.vigentes.map(x => el("li", {}, x.texto + " ", fLink(x))))]
        : [el("p", { className: "muted", textContent: "Ninguna." })]),
      ...(dv.superadas.length
        ? [
            el(
              "details",
              {},
              el("summary", { textContent: "Sustituidas por una decisión posterior · " + dv.superadas.length }),
              el(
                "ul",
                { className: "f-lst" },
                ...dv.superadas.map(x => el("li", {}, el("s", { textContent: x.texto }), " ", fLink(x), " → ahora: " + x.por.texto + " ", fLink(x.por))),
              ),
            ),
          ]
        : []),
      el("h3", { textContent: "Pendientes abiertos · " + est.pendientes.length }),
      ...(est.pendientes.length
        ? [el("ul", { className: "f-lst" }, ...est.pendientes.slice(0, 3).map(p => el("li", { textContent: p.texto })))]
        : [el("p", { className: "muted", textContent: "Ninguno." })]),
      el("a", {
        href: "#",
        textContent: est.pendientes.length > 3 ? "Ver los " + est.pendientes.length : "Ver todos",
        onclick: ev => {
          ev.preventDefault();
          ftab = "pendientes";
          lsSet("ftab", ftab);
          fsucio = true;
          pintarHome();
        },
      }),
      ...(est.cambios ? [el("h3", { textContent: "Desde el documento anterior" }), cambiosResumen(est.cambios, c)] : []),
    ),
  );
  return nodos;
}
function cambiosResumen(cm, c) {
  const n = (k, t) => cm[k][t].length;
  return el(
    "div",
    { className: "f-camb" },
    ...[
      ["decisiones", "Decisiones"],
      ["tareas", "Tareas"],
      ["puntos", "Puntos"],
    ].map(([k, t]) =>
      el(
        "span",
        { className: "fchip", title: n(k, "nuevo") + " nuevas · " + n(k, "cambiado") + " cambiadas · " + n(k, "ya_no") + " ya no aparecen" },
        t + " ",
        el("b", { className: n(k, "nuevo") ? "n-nuevo" : "", textContent: "+" + n(k, "nuevo") }),
        " ~" + n(k, "cambiado") + " −" + n(k, "ya_no"),
      ),
    ),
    el("a", {
      href: "#",
      textContent: "Comparar",
      onclick: e => {
        e.preventDefault();
        fcmp = { a: cm.a.mid, b: cm.b.mid };
        ftab = "comparar";
        lsSet("ftab", ftab);
        fsucio = true;
        pintarHome();
      },
    }),
  );
}

// ---- Pendientes ----
let fpenFoco = null; // {ids, etiqueta} desde el informe: filtra la tabla hasta «Quitar filtro»
async function tPendientes(c, e) {
  const fo = fTomaFoco("pendientes");
  if (fo) {
    fpenFoco = fo;
    fpen.estado = fo.filtro || "abierto";
    fpen.resp = "";
  }
  if (fpen.estado !== "cerrados") fpen.estado = "abierto"; // «Vigentes» ya no está aquí: las decisiones en vigor, en Decisiones (Filtros › «Solo vigentes»)
  const q = new URLSearchParams({ c, estado: fpen.estado === "cerrados" ? "todos" : fpen.estado, resp: fpen.resp, orden: fpen.orden });
  const r = await api("/api/exp/pendientes?" + q);
  const pill = (k, t, n) =>
    el(
      "button",
      {
        className: "fchip",
        "aria-pressed": fpen.estado === k,
        onclick: () => {
          fpen.estado = k;
          fRe();
        },
      },
      t,
      el("span", { className: "n", textContent: n }),
    );
  const sel = el(
    "select",
    {
      onchange: ev => {
        fpen.resp = ev.target.value;
        fRe();
      },
    },
    new Option("Todos", ""),
    ...(AJ.yo?.nombre ? [new Option("Asignado a mí", AJ.yo.nombre.trim().split(/\s+/)[0])] : []), // el servidor filtra por «contiene»
    ...r.responsables.map(x => new Option(x, x)),
  );
  sel.value = fpen.resp;
  const ord = el(
    "select",
    {
      onchange: ev => {
        fpen.orden = ev.target.value;
        fRe();
      },
    },
    new Option("Fecha límite", "plazo"),
    new Option("Documento", "doc"),
  );
  ord.value = fpen.orden;
  const cerr = r.n.hecho + r.n.descartado;
  // «Filtros» = el menú común de Extraído (masFiltros, registro.js); la insignia cuenta los que se apartan del valor por defecto
  const barra = el(
    "div",
    { className: "toolbar f-barra" },
    el("div", { className: "row f-est", role: "group", ariaLabel: "Estado" }, pill("abierto", "Abiertos", r.n.abierto), pill("cerrados", "Cerrados", cerr)),
    el("span", { className: "grow" }),
    masFiltros([regCampo("Responsable", sel), regCampo("Ordenar por", ord)], +!!fpen.resp + +(fpen.orden !== "plazo")),
  );
  let items = fpen.estado === "cerrados" ? r.items.filter(p => p.estado !== "abierto") : r.items;
  const foco = fpenFoco;
  if (foco) items = items.filter(p => foco.ids.includes(p.eid || p.id));
  const lista = el(
    "div",
    { className: "f-tabla" },
    el(
      "div",
      { className: "pr h" },
      el("span"),
      el("span", { textContent: "Pendiente" }),
      el("span", { textContent: "Responsable" }),
      el("span", { textContent: "Fecha límite" }),
      el("span", { textContent: "Origen" }),
    ),
    ...(items.length
      ? items.map(p => filaPend(c, p))
      : [
          fpen.estado === "abierto"
            ? fLogro("Todo al día", "No quedan pendientes abiertos en este proyecto.", "Añadir un pendiente", () => $("pm-t").focus())
            : el("div", { className: "vacio", textContent: "Nada cerrado todavía." }),
        ]),
  );
  const add = el(
    "form",
    { className: "row wrap f-add" },
    el("input", { id: "pm-t", placeholder: "Añadir un pendiente a mano…", ariaLabel: "Pendiente" }),
    respNuevo(c),
    el("input", { id: "pm-p", placeholder: "Plazo (viernes…)", ariaLabel: "Plazo" }),
    el("button", { className: "sec", textContent: "Añadir" }),
  ); // tamaños en app.css (.f-add)
  add.onsubmit = fallo(async ev => {
    ev.preventDefault();
    await post("/api/exp/pendientes", { c, texto: $("pm-t").value, resp: $("pm-r").value, plazo: $("pm-p").value });
    await fRe();
  });
  if (foco && fo) fResaltaIds(lista, foco.ids);
  return [
    ...bannerSug(c, r.sugeridos),
    barra,
    ...(foco
      ? [
          fChipFoco(
            items.length,
            () => {
              fpenFoco = null;
              fRe();
            },
            foco.etiqueta,
          ),
        ]
      : []),
    lista,
    add,
    el("p", {
      className: "muted",
      textContent:
        "Cada pendiente enlaza al minuto exacto del documento donde se acordó. Marcar o desmarcar es siempre a mano: el seguimiento automático solo propone.",
    }),
  ];
}
// Responsable editable con sugerencias de los miembros del proyecto (datalist #reg-miembros de registro.js); se puede escribir otro
function respEditable(c, p) {
  regMiembros(c);
  const i = el("input", { value: p.resp || "", placeholder: "—", ariaLabel: "Responsable de " + p.texto, className: "pw-in" });
  i.setAttribute("list", "reg-miembros");
  i.onchange = fallo(async () => {
    await api("/api/reg/" + encodeURIComponent(p.eid), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ c, cambios: { dueno: i.value.trim() } }),
    });
    await fRe();
  });
  return i;
}
function respNuevo(c) {
  regMiembros(c);
  const i = el("input", { id: "pm-r", placeholder: "Responsable", ariaLabel: "Responsable" });
  i.setAttribute("list", "reg-miembros");
  return i;
}
function filaPend(c, p) {
  const chk = el("input", {
    type: "checkbox",
    checked: p.estado !== "abierto",
    ariaLabel: p.estado === "abierto" ? "Marcar hecho: " + p.texto : "Reabrir: " + p.texto,
  });
  chk.onchange = fallo(async () => {
    const h = chk.checked,
      fila = chk.closest(".pr");
    if (h) fila.classList.add("tachando"); // el trazo cruza el texto mientras se guarda
    try {
      await Promise.all([post("/api/exp/pendientes", { c, id: p.id, estado: h ? "hecho" : "abierto" }), h && fEspera(fila)]);
    } catch (e) {
      fila.classList.remove("tachando");
      chk.checked = !h;
      throw e;
    }
    await fRe();
    if (h) hechoDeshacer(c, p, fRe);
  });
  const sg = p.sugerido && p.estado === "abierto" ? p.sugerido : null;
  const ft = p.plazo || (p.fecha ? fFecha(p.fecha) : "Sin fecha"),
    punto = (k, t) => el("span", { className: "dot " + k, role: "img", ariaLabel: t, title: t });
  const plazo = p.vencido
    ? [punto("err", "Vencido"), el("b", { className: "err", textContent: "Vencido" }), " · " + ft]
    : p.pronto
      ? [punto("w", "Vence pronto"), ft]
      : [ft];
  const acc = [];
  if (p.estado === "abierto")
    acc.push(
      el("button", {
        className: "gh",
        textContent: "Descartar",
        ariaLabel: "Descartar: " + p.texto,
        onclick: fallo(async () => {
          await post("/api/exp/pendientes", { c, id: p.id, estado: "descartado" });
          await fRe();
          hechoDeshacer(c, p, fRe, "Descartado");
        }),
      }),
    );
  if (p.manual)
    acc.push(
      el("button", {
        className: "gh",
        textContent: "Quitar",
        ariaLabel: "Quitar: " + p.texto,
        onclick: fallo(async () => {
          await post("/api/exp/pendientes", { c, id: p.id, borrar: true });
          await fRe();
        }),
      }),
    );
  return el(
    "div",
    { className: "pr" + (sg ? " sug" : "") + (p.estado !== "abierto" ? " cerr" : ""), "data-id": p.eid || p.id },
    el("span", { className: "pc" }, chk),
    el(
      "span",
      { className: "pt" },
      el("span", { className: p.estado === "abierto" ? "" : "tach", textContent: p.texto }),
      " ",
      ...(/^tareas?$/i.test(p.tipo || "") ? [] : [el("small", { className: "tipo", textContent: p.tipo })]),
      ...(p.estado === "descartado" ? [el("span", { className: "badge", textContent: "descartado" })] : []),
      ...(sg ? [el("b", { className: "q", textContent: { hecho: " ¿cerrado?", respondida: " ¿respondida?" }[sg.tipo] || " ¿actualizado?" })] : []),
      ...(p.nota ? [el("small", { textContent: p.nota })] : []),
      ...(sg
        ? [
            el(
              "div",
              { className: "ev" },
              sg.respuesta && sg.respuesta !== sg.cita ? "Respuesta: " + sg.respuesta + " · " : "",
              "«" + sg.cita + "» ",
              fLink({ mid: sg.mid, ver: sg.ver, t: sg.t }, sg.doc + " · " + mmss(sg.t)),
              " ",
              el("button", {
                className: "sec sm",
                textContent: { hecho: "Sí, cerrar", respondida: "Sí, guardar respuesta" }[sg.tipo] || "Sí, anotar",
                onclick: fallo(async () => {
                  await post("/api/exp/sugerencia", { c, id: p.id, aceptar: true });
                  await fRe();
                }),
              }),
              el("button", {
                className: "link",
                textContent: "No",
                onclick: fallo(async () => {
                  await post("/api/exp/sugerencia", { c, id: p.id, aceptar: false });
                  await fRe();
                }),
              }),
            ),
          ]
        : []),
      ...(acc.length ? [el("div", { className: "ac" }, ...acc)] : []),
    ),
    el("span", { className: "pw" }, p.eid && p.estado === "abierto" ? respEditable(c, p) : p.resp || "—"),
    el("span", { className: "pf" + (p.pronto && !p.vencido ? " w" : ""), title: p.pronto && !p.vencido ? "Vence pronto" : "" }, ...plazo),
    el("span", { className: "po" }, p.manual ? "Manual" : p.mid ? fLink(p) : p.doc || "—"),
  );
}

// ---- Equipo: carga por persona (tareas abiertas y vencidas, decisiones recientes, preguntas que se le dirigen) ----
async function tEquipo(c) {
  const ps = await api("/api/reg/equipo?c=" + encodeURIComponent(c));
  if (!ps.length)
    return [
      el("p", { className: "vacio", textContent: "Aún no hay tareas, decisiones ni preguntas con responsable en este " + nm("carpeta").toLowerCase() + "." }),
    ];
  const n = (v, t, cls = "") =>
    el("td", { className: "num" + (v && cls ? " " + cls : "") }, v ? String(v) : "—", el("span", { className: "sr", textContent: " " + t }));
  return [
    el(
      "div",
      { className: "tabla" },
      el(
        "table",
        { className: "f-equipo" },
        el(
          "thead",
          {},
          el(
            "tr",
            {},
            ...["Persona", "Tareas abiertas", "Vencidas", "Decisiones (30 días)", "Preguntas abiertas"].map(t => el("th", { scope: "col", textContent: t })),
          ),
        ),
        el(
          "tbody",
          {},
          ...ps.map(p =>
            el(
              "tr",
              {},
              el(
                "td",
                {},
                el("button", {
                  className: "link",
                  textContent: p.nombre + (esMio(p.nombre) ? " (tú)" : ""),
                  title: "Ver sus tareas",
                  onclick: () => {
                    fpen.resp = p.nombre;
                    fpen.estado = "abierto";
                    fIr("pendientes");
                  },
                }),
              ),
              n(p.abiertas, "tareas abiertas"),
              n(p.vencidas, "vencidas", "err"),
              n(p.decisiones, "decisiones"),
              n(p.preguntas, "preguntas"),
            ),
          ),
        ),
      ),
    ),
    el("p", { className: "muted", textContent: "Pulsa un nombre para ver sus tareas. El responsable se cambia en Tareas." }),
  ];
}

// ---- Línea de tiempo ----
async function tLinea(c) {
  const ev = await api("/api/exp/linea?c=" + encodeURIComponent(c));
  const f = el(
    "form",
    { className: "row wrap f-add" },
    el("input", { type: "date", id: "nt-f", ariaLabel: "Fecha de la nota", value: new Date().toISOString().slice(0, 10), style: "flex:0 0 160px" }),
    el("input", { id: "nt-t", placeholder: "Nota (una llamada, un acuerdo verbal…)", ariaLabel: "Nota", style: "flex:3 1 260px" }),
    el("button", { className: "pri", textContent: "Añadir nota" }),
  );
  f.onsubmit = fallo(async ev2 => {
    ev2.preventDefault();
    await post("/api/exp/notas", { c, texto: $("nt-t").value, fecha: $("nt-f").value });
    await fRe();
  });
  const T = { estado: { hecho: "marcó como hecho", descartado: "descartó", abierto: "reabrió", actualizado: "anotó una actualización de" } };
  const fila = x => {
    let tag, cuerpo;
    if (x.tipo === "doc") {
      tag = "";
      cuerpo = [
        el("b", {}, fLink({ mid: x.mid, ver: x.ver, t: 0 }, x.titulo)),
        el("div", { className: "muted", textContent: (x.resumen || "") + (x.n_pend ? " · " + x.n_pend + " pendientes" : "") }),
      ];
    } // el documento ya se ve por su enlace: sin chip «Documento» en cada fila
    else if (x.tipo === "nota") {
      tag = "Nota";
      cuerpo = [
        x.texto + " ",
        el("button", {
          className: "link",
          textContent: "Quitar",
          ariaLabel: "Quitar nota",
          onclick: fallo(async () => {
            await post("/api/exp/notas", { c, id: x.id, borrar: true });
            await fRe();
          }),
        }),
      ];
    } else if (x.tipo === "pendiente") {
      tag = "Pendiente";
      cuerpo = [(T.estado[x.a] || x.a) + " «" + x.texto + "»" + (x.cita ? " · «" + x.cita + "»" : "")];
    } else if (x.tipo === "sugerido") {
      tag = "Seguimiento";
      cuerpo = [
        "Parece " + ({ hecho: "hecho", respondida: "respondida" }[x.a] || "actualizado") + ": «" + x.texto + "» · «" + x.cita + "» ",
        fLink({ mid: x.mid, ver: "", t: x.t_doc }, x.doc + " · " + mmss(x.t_doc)),
      ];
    } else {
      tag = "Pendiente";
      cuerpo = ["Añadido a mano: «" + x.texto + "»"];
    }
    return el(
      "li",
      {},
      el("span", { className: "d", textContent: fFecha(x.fecha) }),
      el("span", { className: "n tl-c" }, ...(tag ? [el("span", { className: "badge", textContent: tag }), " "] : []), ...cuerpo),
    );
  };
  return [
    f,
    el(
      "ul",
      { className: "list card f-tl" },
      ...(ev.length ? ev.map(fila) : [el("li", { className: "vacio", textContent: "Todavía no hay nada en la línea de tiempo." })]),
    ),
  ];
}

// ---- Preguntar (el mismo panel #qpanel de siempre, montado aquí) ----
// preguntas de ejemplo (solo mientras no se ha preguntado nada): la primera pulsación pregunta
const FEJ = ["¿Qué se ha decidido hasta ahora?", "¿Qué tareas siguen abiertas y quién las lleva?", "¿Qué riesgos o problemas se han mencionado?"];
async function tPreguntar(c) {
  const w = el("div", { id: "f-preg" });
  setQ("c:" + c);
  const ej = $("respuestas").childElementCount
    ? null
    : el(
        "div",
        { className: "row wrap f-ej", role: "group", ariaLabel: "Preguntas de ejemplo" },
        el("span", { className: "muted", textContent: "Prueba con:" }),
        ...FEJ.map(t =>
          el("button", {
            type: "button",
            className: "fchip",
            textContent: t,
            onclick: () => {
              $("pregunta").value = t;
              $("qform").requestSubmit();
            },
          }),
        ),
      );
  if (ej) $("qform").addEventListener("submit", () => ej.remove(), { once: true });
  w.append(...(ej ? [ej] : []), $("qpanel"));
  return [w];
}

// ---- Comparar ----
async function tComparar(c) {
  const ev = await api("/api/exp/linea?c=" + encodeURIComponent(c)),
    ds = ev.filter(x => x.tipo === "doc").reverse();
  if (ds.length < 2) return [el("p", { className: "vacio", textContent: "Hacen falta al menos dos documentos para compararlos." })];
  if (!ds.some(d => d.mid === fcmp.a) || !ds.some(d => d.mid === fcmp.b) || fcmp.a === fcmp.b) fcmp = { a: ds[ds.length - 2].mid, b: ds[ds.length - 1].mid };
  // etiqueta encima y select a todo el ancho de su columna (a 390 px se apilan sin salirse)
  const mk = (k, t) => {
    const s = el(
      "select",
      {
        onchange: () => {
          fcmp[k] = s.value;
          fRe();
        },
      },
      ...ds.map(d => new Option(d.titulo + " · " + fFecha(d.fecha), d.mid)),
    );
    s.value = fcmp[k];
    return el("label", { className: "f-cmp" }, el("span", { className: "ovl", textContent: t }), s);
  };
  const barra = el("div", { className: "toolbar" }, mk("a", "Antes"), mk("b", "Después"));
  const cm = await api("/api/exp/comparar?" + new URLSearchParams({ c, a: fcmp.a, b: fcmp.b }));
  const it = (x, extra) => el("li", {}, x.texto + (x.extra ? " (" + x.extra + ")" : "") + " ", fLink(x), ...(extra || []));
  const bloque = (k, t) => {
    const r = cm[k],
      v = r.nuevo.length + r.cambiado.length + r.ya_no.length;
    return el(
      "div",
      { className: "card" },
      H(t, el("span", { className: "muted", textContent: r.igual + " sin cambios" })),
      ...(v ? [] : [el("p", { className: "muted", textContent: "Sin diferencias." })]),
      ...(r.nuevo.length ? [el("h4", { textContent: "Nuevo · " + r.nuevo.length }), el("ul", { className: "f-lst" }, ...r.nuevo.map(x => it(x)))] : []),
      ...(r.cambiado.length
        ? [
            el("h4", { textContent: "Cambiado · " + r.cambiado.length }),
            el(
              "ul",
              { className: "f-lst" },
              ...r.cambiado.map(x =>
                el(
                  "li",
                  {},
                  el("s", { textContent: x.antes.texto + (x.antes.extra ? " (" + x.antes.extra + ")" : "") }),
                  " ",
                  fLink(x.antes),
                  " → " + x.ahora.texto + (x.ahora.extra ? " (" + x.ahora.extra + ")" : "") + " ",
                  fLink(x.ahora),
                ),
              ),
            ),
          ]
        : []),
      ...(r.ya_no.length ? [el("h4", { textContent: "Ya no aparece · " + r.ya_no.length }), el("ul", { className: "f-lst" }, ...r.ya_no.map(x => it(x)))] : []),
    );
  };
  const red = cm.redaccion;
  return [
    barra,
    el(
      "div",
      { className: "card" },
      H(
        "Resumen de las diferencias",
        el("button", {
          className: "sec sm",
          textContent: red ? "Regenerar" : "Redactar",
          onclick: fallo(() => fEnCola("/api/exp/comparar", { c, a: fcmp.a, b: fcmp.b })),
        }),
      ),
      ...(red
        ? [el("ul", { className: "f-red" }, ...red.frases.map(f => el("li", {}, f.texto + " ", ...f.refs.flatMap(r => [fLink(r), " "]))))]
        : [
            el("p", {
              className: "muted",
              textContent: "La comparación de abajo es automática (por parecido de significado); redactarla con el modelo es opcional.",
            }),
          ]),
    ),
    bloque("decisiones", "Decisiones"),
    bloque("tareas", "Tareas"),
    bloque("puntos", "Puntos clave"),
  ];
}

// ---- Ajustes de la carpeta ----
async function tAjustes(c, e) {
  const g = await api("/api/exp/glosario?c=" + encodeURIComponent(c));
  const fld = (t, ctl, ayuda) =>
    el("div", { className: "field" }, el("label", { textContent: t }), ctl, ...(ayuda ? [el("small", { textContent: ayuda })] : []));
  const perf = el(
    "select",
    {
      ariaLabel: "Perfil por defecto",
      onchange: fallo(async ev => {
        await post("/api/carpeta", { nombre: c, plantilla: ev.target.value === "acta" ? "" : ev.target.value });
        CP = await api("/api/carpetas/plantillas");
        aviso("Perfil guardado");
        fsucio = true;
        fRender();
      }),
    },
    ...PL.map(t => new Option(t.nombre, t.id)),
  );
  perf.value = e.perfil;
  const est = el(
    "select",
    {
      ariaLabel: "Estilo por defecto",
      onchange: fallo(async ev => {
        await post("/api/carpeta", { nombre: c, estilo: ev.target.value });
        CE = await api("/api/carpetas/estilos");
        aviso("Estilo guardado");
      }),
    },
    new Option("Ninguno", ""),
    ...ESTILOS.map(s => new Option(s.nombre, s.id)),
  );
  est.value = e.estilo;
  const tipo = el("input", { value: e.tipo, ariaLabel: "Tipo", list: "dl-tipos" }),
    idi = el(
      "select",
      { ariaLabel: "Idioma del documento" },
      new Option("El de la reunión", ""),
      ...Object.entries(IDI)
        .filter(([k]) => k !== "reunión")
        .map(([k, n]) => new Option(cap(n), k)),
    );
  idi.value = e.ajustes.idioma;
  const anon = el(
    "select",
    { ariaLabel: "Anonimizar por defecto" },
    new Option("Como en los ajustes generales (" + (AJ.anonimizar_defecto ? "sí" : "no") + ")", ""),
    new Option("Sí, siempre", "1"),
    new Option("No", "0"),
  );
  anon.value = e.ajustes.anon === null ? "" : e.ajustes.anon ? "1" : "0";
  const guardar = el("button", {
    className: "pri",
    textContent: "Guardar",
    onclick: fallo(async () => {
      await post("/api/exp/datos", { c, tipo: tipo.value, datos: e.datos });
      await post("/api/exp/ajustes", { c, anon: anon.value === "" ? null : anon.value === "1", idioma: idi.value });
      aviso("Ajustes guardados");
      await fRe();
    }),
  });
  // glosario
  let gl = g.glosario.map(x => ({ ...x })),
    ign = [];
  const caja = el("div", { className: "card" }),
    sugs = el("div", { className: "row wrap" }),
    pintG = () => {
      caja.replaceChildren(
        H("Glosario"),
        el("p", {
          className: "muted",
          textContent:
            "Nombres y términos propios. Ayudan a transcribir y redactar los documentos nuevos y corrigen la ortografía en las respuestas de Preguntar.",
        }),
        ...(gl.length
          ? [
              el(
                "div",
                { className: "pr h gl" },
                el("span", { textContent: "Término" }),
                el("span", { textContent: "Ortografía correcta (opcional)" }),
                el("span", { textContent: "Definición breve (opcional)" }),
                el("span"),
              ),
            ]
          : []),
        ...gl.map((x, i) =>
          el(
            "div",
            { className: "pr gl" },
            el("input", { value: x.t, ariaLabel: "Término", oninput: ev => (x.t = ev.target.value) }),
            el("input", { value: x.orto, ariaLabel: "Ortografía correcta de " + x.t, oninput: ev => (x.orto = ev.target.value) }),
            el("input", { value: x.def, ariaLabel: "Definición de " + x.t, oninput: ev => (x.def = ev.target.value) }),
            el("button", {
              className: "sec sm",
              textContent: "×",
              ariaLabel: "Quitar " + x.t,
              onclick: () => {
                gl.splice(i, 1);
                pintG();
              },
            }),
          ),
        ),
        el(
          "div",
          { className: "row wrap", style: "margin-top:8px" },
          el("button", {
            className: "sec sm",
            textContent: "+ Término",
            onclick: () => {
              gl.push({ t: "", orto: "", def: "" });
              pintG();
            },
          }),
          el("button", {
            className: "sec sm",
            textContent: "Sugerir desde los documentos",
            onclick: fallo(async () => {
              const r = await api("/api/exp/glosario?c=" + encodeURIComponent(c) + "&sugerir=1");
              pintS(r.sugeridos);
            }),
          }),
          el("span", { className: "grow" }),
          el("button", {
            className: "pri sm",
            textContent: "Guardar glosario",
            onclick: fallo(async () => {
              await post("/api/exp/glosario", { c, glosario: gl.filter(x => x.t.trim()), ignorar: ign });
              aviso("Glosario guardado");
              await fRe();
            }),
          }),
        ),
        sugs,
      );
    },
    pintS = l =>
      sugs.replaceChildren(
        ...(l.length
          ? [el("span", { className: "muted", textContent: "Nombres frecuentes (pulsa para añadir; × para no volver a sugerirlo):" })]
          : [el("span", { className: "muted", textContent: "No hay nombres frecuentes nuevos." })]),
        ...l.map(s =>
          el(
            "span",
            { className: "f-chip" },
            el("button", {
              className: "sec sm",
              textContent: s.t + " · " + s.n,
              onclick: () => {
                gl.push({ t: s.t, orto: "", def: "" });
                pintG();
                pintS(l.filter(y => y !== s));
              },
            }),
            el("button", {
              className: "link",
              textContent: "×",
              ariaLabel: "No sugerir " + s.t,
              onclick: () => {
                ign.push(s.t);
                pintS(l.filter(y => y !== s));
              },
            }),
          ),
        ),
      );
  pintG();
  return [
    el(
      "div",
      { className: "card" },
      H("Valores por defecto"),
      el(
        "datalist",
        { id: "dl-tipos" },
        ...["Proyecto", "Innovación", "Comunidad", "Cliente", "Paciente", "Asignatura", "Obra", "Estudio", "Serie", "Candidato"].map(v =>
          el("option", { value: v }),
        ),
      ),
      el(
        "div",
        { className: "cols" },
        fld("Perfil por defecto", perf, "El tipo de documento que propone «+ Añadir»."),
        fld("Estilo por defecto", est, "Cómo se organiza al exportar."),
        fld("Tipo", tipo, "Cambia el nombre del tipo y las sugerencias de datos."),
        fld("Idioma de los documentos nuevos", idi),
        fld("Anonimizar por defecto", anon, "Al exportar y descargar desde aquí."),
      ),
      el("div", { className: "row" }, guardar),
    ),
    fCompartir(c),
    fAuto(c),
    Object.assign(caja, { id: "f-glos" }),
  ];
}
// A2: compartir el proyecto por una carpeta de OneDrive o SharePoint sincronizada (compartir.py)
function fCompartir(c) {
  const w = el("div", { className: "card" });
  const pinta = s => {
    const ruta = el("input", { readOnly: true, value: s.ruta || "", ariaLabel: "Carpeta compartida" });
    const tr = el("input", {
      type: "checkbox",
      checked: !!s.transcripciones,
      onchange: fallo(async () => {
        if (
          tr.checked &&
          !confirm("Las transcripciones recogen todo lo que se dijo, palabra por palabra. Cualquiera con acceso a la carpeta podrá leerlas. ¿Compartirlas?")
        )
          return (tr.checked = false);
        pinta(await post("/api/compartir", { c, transcripciones: tr.checked }));
      }),
    });
    const elegir = fallo(async () => {
      const r = await post("/api/pick", { tipo: "carpeta" });
      if (!r.path) return;
      pinta(await post("/api/compartir", { c, ruta: r.path, transcripciones: tr.checked }));
      aviso("Proyecto compartido en " + r.path);
    });
    const alServidor = fallo(async () => {
      pinta(await post("/api/servidor/enviar", { c, transcripciones: tr.checked }));
      aviso("Proyecto enviado al servidor de equipo");
    });
    const srv = s.servidor || s.servidor_url;
    w.replaceChildren(
      H("Compartir con el equipo"),
      s.servidor
        ? el("p", {
            className: "muted",
            textContent:
              "Se envía al servidor de equipo " +
              s.servidor +
              ": tareas, decisiones y demás elementos, y las actas (sin vídeo; las anonimizadas no). Lo que el equipo cambie en la web vuelve aquí.",
          })
        : el("p", {
            className: "muted",
            textContent:
              "Elige una carpeta de OneDrive o SharePoint que tu equipo tenga sincronizada. Se comparten las tareas, decisiones y demás elementos, y los documentos en .md. Los vídeos nunca. Los demás usan Ajustes › Equipo › «Unirse a un proyecto compartido».",
          }),
      s.servidor
        ? ""
        : el(
            "div",
            { className: "row wrap" },
            ruta,
            el("button", { className: "sec", textContent: s.compartido ? "Cambiar carpeta…" : "Compartir en carpeta…", onclick: elegir }),
            ...(!s.compartido && srv ? [el("button", { textContent: "Enviar al servidor de equipo", onclick: alServidor })] : []),
          ),
      !s.compartido && !srv ? el("p", { className: "muted", textContent: "¿Tenéis servidor de equipo? Conéctalo en Ajustes › Equipo." }) : "",
      el("label", { className: "check" }, tr, el("span", { textContent: "Compartir también las transcripciones" })),
      ...(s.compartido
        ? [
            el("p", {
              className: s.error ? "err" : "muted",
              textContent:
                s.error ||
                (s.ultima ? "Última sincronización: " + new Date(s.ultima * 1000).toLocaleString("es") : "Sin sincronizar todavía") +
                  (s.servidor ? " · se envía sola cada minuto" : " · se sincroniza sola cada minuto") +
                  (s.miembros.length ? " · " + s.miembros.length + (s.miembros.length === 1 ? " equipo más" : " equipos más") : ""),
            }),
            el(
              "div",
              { className: "row wrap" },
              el("button", {
                className: "sec",
                textContent: s.servidor ? "Enviar ahora" : "Sincronizar ahora",
                onclick: fallo(async () => {
                  pinta(await post("/api/compartir", { c }));
                  aviso("Sincronizado");
                  fsucio = true;
                }),
              }),
              el("button", {
                className: "gh",
                textContent: s.servidor ? "Dejar de enviar" : "Dejar de compartir",
                onclick: fallo(async () => {
                  if (
                    !confirm(
                      s.servidor
                        ? "Este equipo deja de enviar el proyecto. Lo que ya está en el servidor se queda allí."
                        : "Este equipo deja de sincronizar el proyecto. Lo que ya está en la carpeta compartida se queda allí.",
                    )
                  )
                    return;
                  pinta(await post("/api/compartir", { c, dejar: true }));
                }),
              }),
            ),
          ]
        : []),
    );
  };
  api("/api/compartir?c=" + encodeURIComponent(c))
    .then(pinta)
    .catch(() => w.remove());
  return w;
}

// ---- Registro: Revisión (bandeja) y vistas por tipo ----
// «Regenerar con IA» (F3b): encola /api/reg/poblar (todas las vistas o solo la de la pestaña); al terminar, carpetaTrasCola recarga la pestaña
KIND.poblar = "Poblar el proyecto con IA";
const FPOBLAR = { requisitos: "requisitos", interesados: "interesados", decisiones: "decisiones" }; // pestaña -> vista de poblar.py
function fRegenerar(c, vistas) {
  const nb = () => {
    try {
      return nubeParams("q") || nubeParams("f");
    } catch {
      return null;
    }
  };
  const b = el("button", {
    className: "sec sm",
    textContent: "Regenerar con IA",
    title: "La IA vuelve a leer las reuniones y propone solo lo nuevo (respeta lo editado, aprobado y descartado)",
    onclick: fallo(async () => {
      b.disabled = true;
      try {
        await fEnCola("/api/reg/poblar", { c, ...(vistas ? { vistas } : {}), ...(nb() ? { nube: nb() } : {}) });
      } finally {
        b.disabled = false;
      }
    }),
  });
  const info = el("small", { className: "muted" });
  api("/api/reg/poblar/estado?c=" + encodeURIComponent(c))
    .then(r => {
      const u = r.ultimo,
        n = u ? Object.values(u.creadas || {}).reduce((a, x) => a + x, 0) : 0;
      info.textContent = r.en_cola
        ? "En cola…"
        : u
          ? "Última pasada: " +
            new Date(u.t * 1000).toLocaleString("es") +
            " · " +
            n +
            (n === 1 ? " nueva" : " nuevas") +
            " · " +
            u.llamadas +
            " llamadas" +
            (u.coste ? " · US$" + u.coste.toFixed(3) : "")
          : "";
    })
    .catch(() => {});
  return el("div", { className: "row wrap", style: "margin-bottom:8px" }, b, info);
}
async function tRevision(c) {
  const w = el("div");
  registroBandeja(w, c, () => fCargaReg(c, fReg.tipo));
  return [fRegenerar(c), w];
}
// placeholder genérico: tabla editable del tipo; cada vista de F4 lo sustituye con FVISTAS[clave]
async function tVista(c, e, k) {
  if (FVISTAS[k]) return FVISTAS[k](c, e);
  if (k === "informe") return [el("p", { className: "vacio", textContent: "Próximamente (F6)." })];
  const w = el("div");
  registroTabla(w, { c, tipo: FREG[k], onChange: () => fCargaReg(c, e.tipo), foco: fTomaFoco(k) });
  return FPOBLAR[k] ? [fRegenerar(c, [FPOBLAR[k]]), w] : [w];
}
