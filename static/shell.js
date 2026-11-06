// Marco del rediseño (REDISENO.md): raíl, rutas #/…, omnibox, paleta Ctrl+K, Inicio, hoja Añadir, Biblioteca, Pendientes, Enviar, Buscar,
// barra de acciones del Documento (Extraído, Fuente) y extras del Proyecto («Auto: …», ⋯ Más, Automático, importar Excel/CSV, añadir a proyecto).
// Usa los globales de app.js, carpeta.js, ajustes.js y exportar.js. enviar.js y descargar.js son opcionales: window.Enviar?, window.Descargar?.

const enc = encodeURIComponent,
  norm = s => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const KIND_T = { video: "Vídeo", audio: "Audio", pdf: "PDF", texto: "Texto", imagen: "Imagen" };
const TIPO_T = {
  tarea: "Tarea",
  decision: "Decisión",
  requisito: "Requisito",
  historia: "Historia",
  interesado: "Interesado",
  riesgo: "Riesgo",
  pregunta: "Pregunta",
  hito: "Hito",
  idea: "Idea",
  hipotesis: "Hipótesis",
  experimento: "Experimento",
  insight: "Aprendizaje",
};
const TIPO_TAB = {
  tarea: "pendientes",
  decision: "decisiones",
  requisito: "requisitos",
  historia: "historias",
  interesado: "interesados",
  riesgo: "riesgos",
  pregunta: "preguntas",
  hito: "hitos",
  idea: "ideas",
  hipotesis: "hipotesis",
  experimento: "experimentos",
  insight: "aprendizajes",
};
const editable = t => !!t?.closest?.("input, textarea, select, [contenteditable=true]");
const sinEnviar = () => aviso("El módulo de envío no está disponible");
const ICO = {
  inicio: '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/>',
  bib: '<path d="M4 4h6v16H4zM14 4h6v16h-6z"/>',
  pend: '<path d="M9 11l3 3 8-8"/><path d="M20 12v7a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h11"/>',
  env: '<path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4z"/>',
  proy: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  mas: '<path d="M12 5v14M5 12h14"/>',
  aj: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>',
  rec: '<circle cx="12" cy="12" r="6"/>',
  doc: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>',
  subir: '<path d="M12 16V4M6 10l6-6 6 6"/><path d="M4 20h16"/>',
  bajar: '<path d="M12 4v12M6 10l6 6 6-6"/><path d="M4 20h16"/>',
  clip: '<rect x="8" y="3" width="8" height="4" rx="1"/><path d="M16 5h2a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h2"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  ia: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
  vista: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
  preg: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>',
  editar: '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
  cola: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  buscar: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
  modo: '<rect x="2" y="7" width="20" height="10" rx="5"/><circle cx="16" cy="12" r="2.5"/>',
  ojo: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  enlace: '<path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
  plant: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/>',
  sli: '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
  informe: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
};
const ico = k => {
  const s = el("span", { className: "ri", "aria-hidden": "true" });
  s.innerHTML = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICO[k]}</svg>`;
  return s;
};
const badgeT = (t, cls = "") => el("span", { className: "badge " + cls, textContent: t });

// ---------- rutas: #/ · #/biblioteca · #/pendientes · #/enviar · #/cola · #/p/<proyecto>/<pestaña> · #/d/<id>/<versión> · #/buscar/<q> · #/ajustes/<pestaña> ----------
let rutaLista = false,
  rutaRep = false; // rutaLista: hasta aplicar la ruta inicial no se reescribe el hash; rutaRep: al seguir una ruta se reemplaza (no se apila)
function rutaHash() {
  const v = vistaAct;
  if (v === "home") return fsel === undefined ? "#/" : fsel === null ? "#/biblioteca" : "#/p/" + enc(fsel) + (fsel ? "/" + ftab : "");
  if (v === "res") return cur ? "#/d/" + cur.id + (ver ? "/" + enc(ver) : "") : "#/";
  if (v === "ajustes") return "#/ajustes/" + tabAj;
  if (v === "buscar") return "#/buscar/" + enc(BQ.q);
  if (v === "preg") return location.hash;
  return "#/" + ({ bib: "biblioteca", pend: "pendientes", enviar: "enviar", cola: "cola", grabar: "grabar", uso: "uso" }[v] || "");
}
const desdeTxt = h =>
  h.startsWith("#/p/")
    ? decodeURIComponent(h.split("/")[2] || "") || sinC()
    : h.startsWith("#/buscar")
      ? "Resultados"
      : { "#/biblioteca": "Biblioteca", "#/pendientes": "Pendientes", "#/enviar": "Enviar", "#/cola": "Cola" }[h] || "Inicio";
function rutaSync() {
  document.body.classList.toggle("sin-cromo", vistaAct === "uso" && !$("uso-pasos").hidden); // primer arranque: el asistente va solo (sin raíl, buscador ni «+ Añadir»; vistas-shell.css)
  if (vistaAct === "home" && fsel === null) {
    fsel = undefined;
    vista("bib");
    pintarBib();
    return;
  } // «todos los documentos» = Biblioteca
  if (rutaLista) {
    const h = rutaHash();
    if (h !== location.hash && !(h === "#/" && !location.hash)) history[rutaRep ? "replaceState" : "pushState"](null, "", h);
  }
  document.body.classList.remove("rail-open");
  pintarSide();
  omniScope();
}
async function rutaIr() {
  const h = location.hash,
    [, a = "", b = "", c = ""] = h.split("/").map(x => {
      try {
        return decodeURIComponent(x);
      } catch {
        return x;
      }
    });
  if (/^#\/(ajustes|modelos|plantillas)/.test(h)) return; // ajustes.js (ruta_)
  if (rutaLista && h === rutaHash()) return;
  rutaRep = true;
  try {
    if (a === "biblioteca") {
      vista("bib");
      pintarBib();
    } else if (a === "pendientes") {
      vista("pend");
      pintarPendPag();
    } else if (a === "enviar") {
      vista("enviar");
      window.Enviar
        ? Enviar.montar($("env-raiz"))
        : $("env-raiz").replaceChildren(el("p", { className: "muted", textContent: "El módulo de envío no está disponible." }));
    } else if (a === "cola") {
      vista("cola");
      sondear();
    } else if (a === "grabar") grabarAbrir();
    else if (a === "p") {
      fsel = b;
      if (c) {
        ftab = c;
        lsSet("ftab", c);
      }
      fsucio = true;
      ir("home");
    } else if (a === "d" && b) {
      const l = rutaLista;
      rutaLista = false;
      try {
        await abrir(b, c || undefined);
      } catch (x) {
        aviso(x.message);
      } finally {
        rutaLista = l;
        rutaSync();
      }
    } else if (a === "buscar") buscarIr(b);
    else {
      fsel = undefined;
      ir("home");
    }
  } finally {
    rutaRep = false;
  }
}
addEventListener("popstate", () => rutaIr());
const cierraPal = () => document.querySelector("dialog.pal")?.close();
addEventListener("hashchange", cierraPal);
addEventListener("popstate", cierraPal);

// ---------- raíl izquierdo (plegable: iconos + texto → solo iconos; en móvil, panel) ----------
const RAIL_N = {},
  BIB_N = { de: null, n: -1 }; // la Biblioteca cuenta también los solo buscables (todas solo trae los que tienen acta)
function pintarSide() {
  if (BIB_N.de !== todas) {
    BIB_N.de = todas;
    api("/api/meetings")
      .then(ms => {
        BIB_N.n = unicas(ms).length;
        pintarSide();
      })
      .catch(() => {});
  }
  document.body.classList.toggle("en-proy", vistaAct === "home" && !!fsel); // móvil: el FAB del proyecto (solo en proyectos reales, no «Sin proyecto») sustituye a «+ Añadir» de arriba
  const r = vistaAct,
    cnt = c => todas.filter(m => (m.carpeta || "") === c).length,
    sin = todas.some(m => !m.carpeta);
  const pend = Object.values(RES).reduce((s, x) => s + (x?.pend || 0), 0);
  const a = (h, k, t, on, n) => {
    const c = el("span", { className: "c", textContent: n || "" });
    if (RAIL_N[h] !== undefined && RAIL_N[h] !== (n || 0)) {
      c.classList.add("tick");
      c.addEventListener("animationend", () => c.classList.remove("tick"));
    }
    RAIL_N[h] = n || 0;
    return el("a", { href: h, className: "nav", title: t, "aria-current": on ? "page" : "false" }, ico(k), el("span", { className: "rt", textContent: t }), c);
  };
  $("side").replaceChildren(
    a("#/", "inicio", "Inicio", r === "home" && fsel === undefined),
    a("#/biblioteca", "bib", "Biblioteca", r === "bib", BIB_N.n >= 0 ? BIB_N.n : todas.length),
    a("#/pendientes", "pend", "Pendientes", r === "pend", pend),
    a("#/enviar", "env", "Enviar", r === "enviar"),
    el(
      "div",
      { className: "t" },
      el("span", { className: "rt", textContent: cap(pl(nm("carpeta"))) }),
      el(
        "button",
        {
          type: "button",
          className: "gh ic rail-mas",
          title: cap(nm("carpeta")) + " nuevo",
          ariaLabel: cap(nm("carpeta")) + " nuevo",
          onclick: () => {
            if (vistaAct !== "home") irInicio();
            nuevaCarpeta();
          },
        },
        ico("mas"),
      ),
    ),
    ...carpetas.map(c => soltable(a("#/p/" + enc(c), "proy", c, r === "home" && fsel === c, cnt(c)), c)),
    ...(sin ? [soltable(a("#/p/", "proy", sinC(), r === "home" && fsel === "", cnt("")), "")] : []),
    el("span", { className: "grow" }),
    ...(GR.activa
      ? [
          el(
            "button",
            { type: "button", className: "nav rec", title: "Grabando", onclick: () => grabarAbrir() },
            ico("rec"),
            el("span", { className: "rt", textContent: "Grabando…" }),
          ),
        ]
      : []),
    a("#/ajustes/general", "aj", "Ajustes", r === "ajustes"),
  );
}
const railToggle = () => {
  if (matchMedia("(max-width: 860px)").matches) document.body.classList.toggle("rail-open");
  else {
    document.body.classList.toggle("rail-min");
    lsSet("rail-min", document.body.classList.contains("rail-min"));
  }
  $("rail-t").setAttribute(
    "aria-expanded",
    document.body.classList.contains("rail-open") || (!document.body.classList.contains("rail-min") && !matchMedia("(max-width: 860px)").matches),
  );
};
$("rail-t").onclick = railToggle;
document.body.classList.toggle("rail-min", !!lsGet("rail-min", false));
$("b-ajustes").hidden = false;
$("inicio").onclick = null; // enlace normal a #/
{
  const s = $("f-mas").querySelector("summary");
  s.textContent = "⋯";
  s.title = "Más acciones";
} // proyecto: solo «⋯» (el aria-label ya dice «Más acciones del proyecto»; sin «Más» ni repetir la pista con ▾)

// ---------- omnibox: buscar o preguntar (tecla /), alcance todo | proyecto | documento ----------
function omniScope() {
  const s = $("omni-c"),
    v = s.value,
    p = vistaAct === "home" && fsel ? fsel : vistaAct === "res" && cur?.carpeta ? cur.carpeta : "";
  s.replaceChildren(
    new Option("Todo", ""),
    ...(p ? [new Option(p, "p:" + p)] : []),
    ...(vistaAct === "res" && cur ? [new Option("Este documento", "d:" + cur.id)] : []),
  );
  if ([...s.options].some(o => o.value === v)) s.value = v;
  omniChips();
}
// alcance como chips bajo el campo (el select sigue siendo el valor; en escritorio solo se ven con el foco)
function omniChips() {
  const s = $("omni-c"),
    w = $("omni-sc") || $("omni").appendChild(el("div", { id: "omni-sc", className: "omni-sc", role: "group", ariaLabel: "Dónde buscar" }));
  w.replaceChildren(
    ...[...s.options].map(o =>
      el("button", {
        type: "button",
        className: "fchip",
        "aria-pressed": s.value === o.value,
        textContent: o.text,
        onclick: () => {
          s.value = o.value;
          omniChips();
          $("buscar").focus();
        },
      }),
    ),
  );
}
$("omni-b").onclick = () => {
  const on = document.body.classList.toggle("omni-open");
  $("omni-b").setAttribute("aria-expanded", on);
  if (on) $("buscar").focus();
};
$("buscar").addEventListener("keydown", e => {
  if (e.key === "Escape" && document.body.classList.contains("omni-open")) {
    document.body.classList.remove("omni-open");
    $("omni-b").setAttribute("aria-expanded", "false");
    $("omni-b").focus();
  }
});
addEventListener("hashchange", () => document.body.classList.remove("omni-open"));
// «Cola»: oculta sin trabajos; con trabajos, aro de progreso + número y tooltip con el detalle
{
  const pp = pintarPill;
  pintarPill = function () {
    pp();
    const n = cola.n,
      b = $("b-cola");
    let q = b.querySelector(".qn");
    if (!q) b.append((q = el("b", { className: "qn" })));
    if (q.textContent !== String(n || "")) {
      q.textContent = n || "";
      anima(q, "pop", 300);
    }
    b.hidden = !n;
    b.classList.toggle("idle", !n);
    b.title = n ? "Cola de trabajos:" + $("cola-txt").textContent.replace(/^ ·/, "") + " (clic para verla)" : "Cola de trabajos";
  };
}
$("omni").onsubmit = e => {
  e.preventDefault();
  const q = $("buscar").value.trim();
  if (!q) return;
  if (location.hash === "#/buscar/" + enc(q)) buscarIr(q);
  else location.hash = "#/buscar/" + enc(q);
};
addEventListener("keydown", e => {
  if (document.body.classList.contains("sin-cromo")) return; // detrás del asistente de primer arranque no hay atajos globales
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    paleta();
  } else if (e.key === "/" && !editable(e.target) && !document.querySelector("dialog[open]")) {
    e.preventDefault();
    $("buscar").focus();
    $("buscar").select();
  } else if (e.key.toLowerCase() === "n" && !e.ctrlKey && !e.metaKey && !e.altKey && !editable(e.target) && !document.querySelector("dialog[open]")) {
    e.preventDefault();
    formNuevo();
  }
});
// «+ Añadir» se contrae a icono al bajar en vistas largas
let scrT = 0;
addEventListener(
  "scroll",
  () => {
    if (!scrT)
      scrT = requestAnimationFrame(() => {
        scrT = 0;
        document.body.classList.toggle("scr", scrollY > 160);
      });
  },
  { passive: true },
);

// ---------- Buscar (resultado del omnibox): respuesta con citas, fragmentos y elementos ----------
const BQ = { q: "", tipo: "" };
// miniatura: imagen real (vía /api/fuente) o icono del tipo
const BUS_ICO = {
  video: '<rect x="3" y="5" width="13" height="14" rx="2"/><path d="M16 10l5-3v10l-5-3"/>',
  audio: '<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>',
  pdf: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 13h6M9 17h6"/>',
  texto: '<path d="M5 6h14M5 11h14M5 16h9"/>',
  imagen: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/>',
};
const BUS_URL = {};
function miniBus(f) {
  const w = el("span", { className: "bus-th", "aria-hidden": "true" });
  w.innerHTML = `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${BUS_ICO[f.kind] || BUS_ICO.texto}</svg>`;
  if (f.kind === "imagen")
    (BUS_URL[f.doc] ||= api("/api/fuente/" + f.doc)
      .then(r => r.url)
      .catch(() => null)).then(u => {
      if (u) {
        const i = el("img", { src: u, alt: "" });
        i.onload = () => w.replaceChildren(i);
      }
    });
  return w;
}
// chips sin resultados: ocultos (se quedan «Todo» y el activo); un grupo sin chips y el separador también
const busPoda = () => {
  const f = $("bus-f");
  f.querySelectorAll("[role=group]").forEach(g => {
    g.hidden = ![...g.children].some(b => !b.hidden);
  });
  const d = f.querySelector(".fdiv");
  if (d) d.hidden = f.querySelectorAll("[role=group]:not([hidden])").length < 2;
};
const esPregunta = q => /[?¿]/.test(q) || /^(qu[eé]|qui[eé]n|cu[aá]ndo|c[oó]mo|d[oó]nde|por qu[eé]|cu[aá]l|cu[aá]nt)/i.test(q);
async function buscarIr(q) {
  BQ.q = q;
  $("buscar").value = q;
  const sc = $("omni-c").value,
    c = sc.startsWith("p:") ? sc.slice(2) : "",
    d = sc.startsWith("d:") ? sc.slice(2) : "";
  if (vistaAct !== "buscar") vista("buscar");
  else rutaSync();
  document.title = q + " · Buscar · Actas";
  $("bus-t").textContent = "Resultados de «" + q + "»";
  const cn = k => (BQ.cnt?.q === q + "|" + sc && BQ.cnt[k] ? el("i", { textContent: " " + BQ.cnt[k] }) : ""); // contadores de la última búsqueda sin filtro de tipo
  const hay = BQ.cnt?.q === q + "|" + sc; // con los contadores de la última búsqueda sin filtro, los tipos vacíos ni se pintan
  const chip = (v, t) =>
    el(
      "button",
      {
        type: "button",
        className: "fchip",
        hidden: hay && v !== "" && BQ.tipo !== v && !BQ.cnt[v],
        "aria-pressed": BQ.tipo === v,
        onclick: () => {
          BQ.tipo = v;
          buscarIr(q);
        },
      },
      t,
      cn(v || "_"),
    );
  $("bus-f").replaceChildren(
    el(
      "div",
      { className: "row wrap bus-chips" },
      el(
        "div",
        { className: "row wrap", role: "group", ariaLabel: "Tipo de documento" },
        chip("", "Todo"),
        ...Object.entries(KIND_T).map(([k, t]) => chip(k, t)),
      ),
      el("span", { className: "fdiv", role: "separator", "aria-hidden": "true" }),
      el(
        "div",
        { className: "row wrap", role: "group", ariaLabel: "Elementos extraídos" },
        chip("tarea", "Tareas"),
        chip("decision", "Decisiones"),
        chip("requisito", "Requisitos"),
        chip("riesgo", "Riesgos"),
      ),
    ),
    ...(sc ? [el("small", { textContent: "En: " + $("omni-c").selectedOptions[0].text })] : []),
  );
  busPoda();
  const skI = () => el("li", { className: "bus-i", "aria-hidden": "true" }, ...sk(3));
  $("bus-fr").replaceChildren(skI(), skI(), skI());
  $("bus-el").replaceChildren(skI());
  $("bus-fr").setAttribute("aria-busy", "true");
  let r;
  try {
    r = await api("/api/buscar?" + new URLSearchParams({ q, c, tipo: BQ.tipo, limit: 40 }));
  } catch {
    r = {
      fragmentos: todas
        .filter(m => (!c || m.carpeta === c) && norm(m.label + " " + m.carpeta).includes(norm(q)))
        .map(m => ({ doc: m.id, titulo: m.label, c: m.carpeta, kind: m.kind, snippet: "" })),
      elementos: [],
    };
  }
  if (BQ.q !== q) return;
  const fr = r.fragmentos.filter(f => !d || f.doc === d),
    els = r.elementos.filter(x => !d || x.doc === d);
  if (!BQ.tipo) {
    const k = { q: q + "|" + sc, _: fr.length + els.length };
    fr.forEach(f => {
      k[f.kind] = (k[f.kind] || 0) + 1;
    });
    els.forEach(x => {
      k[x.tipo] = (k[x.tipo] || 0) + 1;
    });
    BQ.cnt = k;
    $("bus-f")
      .querySelectorAll(".fchip")
      .forEach(b => {
        const t = b.firstChild.textContent,
          v = [
            ...Object.entries(KIND_T),
            ["tarea", "Tareas"],
            ["decision", "Decisiones"],
            ["requisito", "Requisitos"],
            ["riesgo", "Riesgos"],
            ["", "Todo"],
          ].find(x => x[1] === t)?.[0];
        const n = k[v || "_"];
        if (n && !b.querySelector("i")) b.append(el("i", { textContent: " " + n }));
        else if (!n && v) b.hidden = true;
      });
    busPoda();
  }
  $("bus-el").closest("section").hidden = !els.length;
  $("bus-fr").closest("section").hidden = !fr.length && !!els.length;
  $("bus-fr")
    .closest(".bus-g")
    .classList.toggle("uno", !els.length || !fr.length);
  $("bus-fr").replaceChildren(
    ...(fr.length
      ? fr.map(f => {
          const loc = f.loc || (f.t != null ? mmss(f.t) : ""),
            go = () => fallo(citaDoc)(f.doc, f.t, f.loc);
          const p = el("p", { className: "bus-s" });
          p.innerHTML = f.snippet || ""; // el servidor escapa el HTML y solo añade <mark>
          return el(
            "li",
            { className: "bus-i bus-r" },
            miniBus(f),
            el(
              "div",
              { className: "bus-m" },
              el(
                "div",
                { className: "row wrap" },
                el("button", { type: "button", className: "doc-l", textContent: f.titulo || f.doc, onclick: go }),
                ...(loc ? [el("button", { type: "button", className: "cite", textContent: loc, onclick: go })] : []),
                el("span", { className: "muted", textContent: [KIND_T[f.kind] || f.tipo_fuente, f.c].filter(Boolean).join(" · ") }),
              ),
              p,
            ),
          );
        })
      : [el("li", { className: "muted", textContent: "Sin resultados. Prueba con otra palabra o quita el filtro." })]),
  );
  $("bus-fr").removeAttribute("aria-busy");
  escalona($("bus-fr"), true);
  escalona($("bus-el"), true);
  $("bus-el").replaceChildren(
    ...(els.length
      ? els.map(x =>
          el(
            "li",
            { className: "bus-i" },
            el(
              "div",
              { className: "row wrap" },
              badgeT(TIPO_T[x.tipo] || x.tipo, "acc"),
              el("b", { textContent: (x.codigo ? x.codigo + " · " : "") + x.texto }),
            ),
            el(
              "small",
              {},
              [x.estado, x.c].filter(Boolean).join(" · ") + " · ",
              el("a", {
                href: "#",
                textContent: "Abrir en el proyecto",
                onclick: ev => {
                  ev.preventDefault();
                  irElemento(x.c, x.tipo, x.id);
                },
              }),
            ),
          ),
        )
      : [el("li", { className: "muted", textContent: "Sin elementos." })]),
  );
  // Respuesta: el mismo panel de Preguntar, en el proyecto o documento del alcance (o en el del mejor fragmento)
  const cs = carpetas.length ? carpetas : await api("/api/carpetas").catch(() => []); // carga directa de #/buscar/…: la lista del arranque aún puede no haber llegado y sin proyectos no habría «Preguntar a … →» (R4-12)
  if (BQ.q !== q) return;
  const docs = d ? [] : cs,
    s = el(
      "select",
      { ariaLabel: "Preguntar en" },
      ...(d ? [new Option("Este documento", "d")] : []),
      ...docs.map(x => new Option(x, "c:" + x)),
      ...(!d && todas.some(m => !m.carpeta) ? [new Option(sinC(), "c:")] : []),
    );
  s.value = d ? "d" : "c:" + (c || fr[0]?.c || cs[0] || "");
  const preguntar = () => {
    if (s.value === "d") {
      const a = cur.actas.find(x => x.name === ver) || cur.actas[0];
      setQ(cur.id + "|" + (a?.asr || cur.asr));
    } else setQ(s.value);
    $("pregunta").value = q;
    $("qform").requestSubmit();
  };
  // sin respuesta todavía: una línea «Preguntar a <proyecto> →» (+ dónde, si hay varios); el título «Respuesta» sale con la respuesta
  const ask = el("button", {
    type: "button",
    className: "sec bus-ask",
    onclick: () => {
      $("qpanel").hidden = false;
      $("bus-resp").classList.remove("sin-r");
      preguntar();
    },
  });
  s.onchange = () => {
    ask.textContent = "Preguntar a " + (s.value === "d" ? "este documento" : s.selectedOptions[0]?.text || "") + " →";
  };
  s.onchange();
  $("bus-resp").hidden = !s.options.length;
  $("bus-q").replaceChildren(
    el("div", { className: "row wrap bus-ask-r" }, ask, ...(s.options.length > 1 ? [el("label", { className: "muted" }, "Cambiar: ", s)] : [])),
    $("qpanel"),
  );
  $("qpanel").hidden = true;
  $("bus-resp").classList.add("sin-r");
  if (esPregunta(q) && s.options.length) ask.click();
}
function irElemento(c, tipo, id) {
  fsel = c;
  vista("home");
  fIr(TIPO_TAB[tipo] || "revision", { ids: [id] });
}

// ---------- citas → fuente: [mm:ss] al vídeo; p. 12 / § Título a la pestaña Fuente ----------
let FUENTE = null;
async function citaDoc(id, t, loc) {
  if (!cur || cur.id !== id || vistaAct !== "res") await abrir(id);
  if (!cur || cur.id !== id) return;
  if (t != null) citaIr(t, loc);
}
function citaIr(t, loc) {
  if (cur.video) return mpSeek(t, cur.videourl, cur.m.label);
  tab("p-video");
  const salta = () => {
    const ss = [...$("p-fuente").querySelectorAll(".fu-s")];
    const s = ss.find(x => x.dataset.loc === loc) || ss.filter(x => +x.dataset.t <= t).pop() || ss[0];
    if (s) {
      s.closest("details").open = true;
      fResalta([s]);
    }
  };
  FUENTE?.id === cur.id ? salta() : docFuente().then(salta);
}

// ---------- Documento: barra de acciones, Extraído y Fuente ----------
const DST = { p: null }; // nombres de presets y destinos para «Enviar a X»
async function nombresDst() {
  if (!DST.p)
    DST.p = Promise.all([api("/api/destinos").catch(() => ({ destinos: [] })), api("/api/presets").catch(() => [])]).then(([d, p]) =>
      Object.fromEntries([...d.destinos.map(x => ["d:" + x.id, x.nombre]), ...p.map(x => ["p:" + x.id, x.nombre])]),
    );
  return DST.p;
}
async function envLbl() {
  const u = lsGet("env.ultimo", null),
    n = u && (await nombresDst())[u];
  $("d-env").textContent = n ? "Enviar a " + n : "Enviar…";
  $("d-env").title = n ? "Último destino (1 clic). ▾ para elegir otro." : "Elegir a dónde enviar";
}
async function envUltimo(sel) {
  if (!window.Enviar) return sinEnviar();
  const u = lsGet("env.ultimo", null),
    n = u && (await nombresDst())[u];
  if (!n) return Enviar.enviar(sel);
  const body = { ...(u.startsWith("p:") ? { preset: u.slice(2) } : { destino: u.slice(2), que: ["documento"] }), ...sel },
    r = await post("/api/enviar", body);
  if (r.estado === "ok" && r.items?.length && r.items.every(x => x.accion === "omitido"))
    return aviso("Ya enviado a " + n + ", sin cambios", {
      txt: "Reenviar",
      fn: fallo(async () => aviso((await post("/api/enviar", { ...body, reenviar: true })).estado === "ok" ? "Enviado a " + n : "Envío fallido")),
    });
  aviso(r.estado === "ok" ? "Enviado a " + n : "Envío: " + r.estado + (r.error ? " — " + r.error : ""));
}
const docSel = () => ({ doc: cur.id + "/" + ver });
$("d-preg").onclick = () => tab("p-preg");
$("d-env").onclick = fallo(() => envUltimo(docSel()));
$("d-env-m").onclick = () => (window.Enviar ? Enviar.enviar(docSel()) : sinEnviar());
$("d-aproy").onclick = () => aProyecto([cur.id]);
$("d-anon").onclick = () => abrirAnon(null);
$("d-cond").onclick = () => {
  tab("p-video");
  $("cond").scrollIntoView({ block: "start" });
};
$("d-desc").onclick = () => (window.Descargar ? Descargar.abrir({ docs: [cur.id + (ver ? "/" + ver : "")] }) : sinEnviar());
$("d-dud").onclick = () => {
  if ($("dud-bar").hidden) return aviso("No hay frases dudosas en este documento");
  tab("p-acta");
  $("dud-sig").click();
};
document.addEventListener("click", e => {
  const it = e.target.closest(".menu .pop [role=menuitem]");
  if (it) it.closest("details").open = false;
});
function docTab(p) {
  // lo llama tab() de app.js
  $("d-cond").hidden = !cur.video || !!cur.solo;
  envLbl();
  if (p === "p-ext" && !cur.solo) docExt();
  if (p === "p-video") docFuente();
}
async function docExt() {
  const w = $("p-ext"),
    id = cur.id,
    c = cur.carpeta || "";
  w.replaceChildren(el("p", { className: "muted", textContent: "Cargando…" }));
  const [reg, pen] = await Promise.all([
    api("/api/reg?" + new URLSearchParams({ c })).catch(() => ({ items: [] })),
    api("/api/exp/pendientes?" + new URLSearchParams({ c })).catch(() => ({ items: [] })),
  ]);
  if (cur.id !== id) return;
  const regT = reg.items.some(x => x.tipo === "tarea"); // si el registro ya tiene las tareas, los pendientes serían duplicados
  const its = [
    ...pen.items.filter(p => !regT && p.mid === id).map(p => ({ tipo: "tarea", titulo: p.texto, estado: p.estado, dueno: p.resp, extra: p.plazo, t: p.t })),
    ...reg.items
      .filter(x => x.citas?.some(q => q.mid === id))
      .map(x => ({
        tipo: x.tipo,
        id: x.id,
        codigo: x.codigo,
        titulo: x.titulo,
        estado: x.estado,
        rev: x.revision,
        dueno: x.dueno,
        t: x.citas.find(q => q.mid === id).t,
      })),
  ];
  $("t-ext").textContent = "Extraído" + (its.length ? " (" + its.length + ")" : "");
  const grupos = Object.keys(TIPO_T)
    .map(k => [k, its.filter(x => x.tipo === k)])
    .filter(([, l]) => l.length);
  w.replaceChildren(
    ...(grupos.length
      ? grupos.map(([k, l]) =>
          el(
            "section",
            { className: "card ext-g" },
            H(
              TIPO_T[k] + " · " + l.length,
              ...(c ? [el("button", { className: "link", textContent: "Abrir en el proyecto", onclick: () => irElemento(c, k, l[0].id) })] : []),
            ),
            el(
              "ul",
              { className: "f-lst" },
              ...l.map(x =>
                el(
                  "li",
                  {},
                  ...(x.rev === "propuesto" ? [badgeT("Por revisar", "w"), " "] : []),
                  (x.codigo ? x.codigo + " · " : "") + x.titulo,
                  [x.dueno, x.extra, x.estado]
                    .filter(Boolean)
                    .map(v => " · " + v)
                    .join(""),
                  " ",
                  ...(x.t != null
                    ? [el("button", { type: "button", className: "cite", textContent: FUENTE?.id === id ? locDe(x.t) : mmss(x.t), onclick: () => citaIr(x.t) })]
                    : []),
                ),
              ),
            ),
          ),
        )
      : [
          el("p", {
            className: "vacio",
            textContent: c
              ? "Todavía no se ha extraído nada de este documento."
              : "Mueve el documento a un " + nm("carpeta").toLowerCase() + " para extraer tareas, decisiones y requisitos con su cita.",
          }),
        ]),
  );
}
const locDe = t => (FUENTE?.partes || []).filter(p => p.t <= t).pop()?.loc || mmss(t);
async function docFuente() {
  const w = $("p-fuente"),
    id = cur.id;
  if (FUENTE?.id === id) return;
  w.replaceChildren(el("p", { className: "muted", textContent: "Cargando la fuente…" }));
  let f;
  try {
    f = await api("/api/fuente/" + id);
  } catch (x) {
    w.replaceChildren(el("p", { className: "muted", textContent: x.message }));
    return;
  }
  if (cur.id !== id) return;
  FUENTE = { ...f, id };
  if (cur.solo && cur.m.label === id && f.nombre) {
    cur.m.label = f.nombre;
    $("cab-titulo").textContent = f.nombre;
    document.title = f.nombre + " · Actas";
  } // la lista no incluye los solo buscables
  const media = f.kind === "video" || f.kind === "audio";
  const sec = p =>
    el(
      "section",
      { className: "fu-s", "data-t": p.t ?? 0, "data-loc": p.loc || "" },
      el(
        "h3",
        {},
        media
          ? el("a", {
              href: "#",
              className: "ts",
              textContent: mmss(p.t || 0),
              onclick: e => {
                e.preventDefault();
                mpSeek(p.t || 0, cur.videourl, cur.m.label);
              },
            })
          : p.loc || "",
      ),
      el("p", { textContent: p.texto }),
    );
  const ia = el("button", {
    type: "button",
    className: "sec sm",
    textContent: f.kind === "imagen" ? "Describir con IA" : "Describir capturas con IA",
    onclick: fallo(async () => {
      await post("/api/describir", { id, gpu: $("usar-gpu").checked });
      aviso("Añadido a la cola");
      sondear();
      FUENTE = null;
    }),
  });
  const nodos = [
    el(
      "div",
      { className: "row wrap fu-h" },
      el("b", { textContent: f.nombre || "" }),
      ...(f.paginas ? [el("span", { className: "muted", textContent: f.paginas + " págs." })] : []),
      el("span", { className: "grow" }),
      ...(f.url && !media && f.kind !== "imagen"
        ? [el("a", { className: "btn sec sm", href: f.url, target: "_blank", rel: "noopener", textContent: "Abrir el original" })]
        : []),
      ...(!["audio", "pdf", "texto", "imagen"].includes(f.kind) ? [ia] : []),
    ),
    ...(f.vision === "no_disponible" && (f.kind === "imagen" || f.kind === "video")
      ? [
          el(
            "p",
            { className: "aviso w" },
            "Sin modelo con visión: las imágenes no se describen solas. ",
            el("a", { href: "#/ajustes/modelos", textContent: "Instalar uno recomendado" }),
            " o configúralo en ",
            el("a", { href: "#/ajustes/avanzado", textContent: "Ajustes › Avanzado" }),
            ".",
          ),
        ]
      : []),
  ];
  if (f.kind === "imagen") {
    const du = el("textarea", { rows: 3, value: f.descripcion || "", id: "fu-du" }),
      dia = el("textarea", { rows: 3, value: f.descripcion_ia || "", id: "fu-dia" });
    // acciones como iconos sobre la imagen; la descripción de la IA, plegada a 5 líneas con «Ver más» si es larga
    const icoB = (lab, d, extra) => {
      const b = el(extra.href ? "a" : "button", { className: "fu-ib", ariaLabel: lab, title: lab, ...extra });
      if (!extra.href) b.type = "button";
      b.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
      return b;
    };
    ia.className = "fu-ib";
    ia.ariaLabel = ia.title = "Describir con IA";
    ia.innerHTML =
      '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></svg>';
    const ver = el("button", {
      type: "button",
      className: "link fu-ver",
      hidden: true,
      "aria-controls": "fu-dia",
      "aria-expanded": "false",
      textContent: "Ver más",
      onclick: () => {
        const on = dia.classList.toggle("abierta");
        ver.textContent = on ? "Ver menos" : "Ver más";
        ver.setAttribute("aria-expanded", on);
      },
    });
    nodos.push(
      el(
        "div",
        { className: "fu-img" },
        el(
          "figure",
          { className: "fu-fig" },
          el("img", { src: f.url, alt: f.descripcion || f.descripcion_ia || f.nombre || "Imagen" }),
          el(
            "div",
            { className: "fu-ov" },
            ...(f.url
              ? [
                  icoB("Abrir el original", '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>', {
                    href: f.url,
                    target: "_blank",
                    rel: "noopener",
                  }),
                ]
              : []),
            ia,
          ),
        ),
        el(
          "div",
          {},
          el("div", { className: "field" }, el("label", { htmlFor: "fu-du", textContent: "Tu descripción" }), du),
          el("div", { className: "field" }, el("label", { htmlFor: "fu-dia", textContent: "Descripción de la IA" }), dia, ver),
          el("button", {
            type: "button",
            className: "pri sm",
            textContent: "Guardar descripciones",
            onclick: fallo(async () => {
              await post("/api/imagen/" + id, { descripcion: du.value, descripcion_ia: dia.value });
              aviso("Guardado: ya se puede buscar");
            }),
          }),
        ),
      ),
      ...(f.ocr_texto
        ? [
            el(
              "details",
              { open: false },
              el("summary", { textContent: "Texto reconocido (OCR)" }),
              el("pre", { className: "fu-ocr", textContent: f.ocr_texto }),
            ),
          ]
        : []),
    );
  }
  if (f.partes?.length)
    nodos.push(
      el(
        "details",
        { open: !media && f.kind !== "imagen" },
        el("summary", {
          textContent:
            (media ? "Transcripción · " : "Texto · ") +
            f.partes.length +
            (media ? (f.partes.length === 1 ? " tramo" : " tramos") : f.partes.length === 1 ? " parte" : " partes"),
        }),
        el("div", { className: "fu-p" }, ...f.partes.map(sec)),
      ),
    );
  w.replaceChildren(...nodos);
  const t = $("fu-dia");
  if (t)
    requestAnimationFrame(() => {
      w.querySelector(".fu-ver").hidden = t.scrollHeight <= t.clientHeight + 2;
    });
}

// ---------- Añadir: hoja con archivos, objetivo («¿Qué quieres sacar y dónde?»), proyecto y ajustes de procesado plegados ----------
const AN = { files: [], plan: null, defecto: [], goal: lsGet("an.goal", ""), buscable: false };
const IMG_RE = /\.(png|jpe?g|webp)$/i,
  TXT_RE = /\.(pdf|md|txt|docx|html?)$/i,
  TR_RE = /\.(vtt|srt)$/i;
const GOALS = [
  { id: "acta", t: "Acta de reunión", d: "Tareas y decisiones", p: "acta", q: ["tareas", "decisiones"] },
  { id: "req", t: "Requisitos e historias", d: "Para el equipo de producto", p: "requisitos", q: ["requisitos", "historias"] },
  { id: "res", t: "Resumen y puntos clave", d: "Lo esencial, con citas", p: "video", q: ["resumen"] },
  { id: "seg", t: "Seguimiento / informe", d: "Tareas, decisiones y riesgos", p: "raid", q: ["tareas", "decisiones", "riesgos"] },
  { id: "ent", t: "Entrevista", d: "Respuestas y citas", p: "periodistica", q: ["resumen"] },
  { id: "cla", t: "Apuntes de clase", d: "Conceptos y resumen", p: "clase", q: ["resumen"] },
  { id: "bus", t: "Solo hacerlo buscable", d: "Sin resumir: barato, ideal para PDF grandes", b: true, q: [] },
  { id: "otro", t: "Otro…", d: "Todas las plantillas" },
];
function anGoals() {
  const uso = new Set(AJ.perfil_uso || []),
    gs = [...GOALS].sort((a, b) => (b.p && uso.has(b.p)) - (a.p && uso.has(a.p)));
  $("an-goals").replaceChildren(
    ...gs.map(g =>
      el(
        "button",
        { type: "button", className: "goal", "aria-pressed": AN.goal === g.id, onclick: () => anGoal(g.id, true) },
        el("b", { textContent: g.t }),
        el("small", { textContent: g.d }),
      ),
    ),
  );
}
function anGoal(id, user) {
  const g = GOALS.find(x => x.id === id);
  AN.goal = g ? id : "";
  if (user) lsSet("an.goal", AN.goal);
  AN.buscable = !!g?.b;
  if (g?.p) {
    if (![...$("plantilla").options].some(o => o.value === g.p) && PL.some(t => t.id === g.p)) $("plantilla").append(new Option(plantDe(g.p).nombre, g.p));
    if (PL.some(t => t.id === g.p)) {
      $("plantilla").value = g.p;
      $("plantilla").onchange();
    }
  }
  if (id === "otro" && user) {
    const v = $("plantilla").value;
    $("plantilla").replaceChildren(...PL.map(t => new Option(t.nombre, t.id)));
    $("plantilla").value = v;
    $("plantilla").focus();
  }
  anCheck();
  anGoals();
  anBoton();
}
const anChips = () => !!window.Enviar?.presetsObjetivo; // los objetivos van como chips dentro del checklist (enviar.js): sin la fila de tarjetas
function anCheck() {
  // casillas «qué → dónde»: las del proyecto (sus recetas) + las del objetivo
  const g = GOALS.find(x => x.id === AN.goal),
    q = g?.q || [],
    c = $("n-carpeta").value === NUEVA_C ? "" : $("n-carpeta").value;
  $("an-goals").hidden = anChips();
  if (anChips()) {
    // «Solo hacerlo buscable» llega como plan.solo_buscable → el trabajo va con buscable
    AN.plan = { carpeta: c, salidas: [...AN.defecto] };
    AN.buscable = false;
    return Enviar.checklist($("an-check"), {
      plan: AN.plan,
      carpeta: c,
      onChange: p => {
        AN.plan = { ...p, carpeta: c };
        AN.buscable = !!p.solo_buscable;
        if (p.plantilla && PL.some(t => t.id === p.plantilla)) {
          if (![...$("plantilla").options].some(o => o.value === p.plantilla)) $("plantilla").append(new Option(plantDe(p.plantilla).nombre, p.plantilla));
          $("plantilla").value = p.plantilla;
          $("plantilla").onchange();
        }
        anBoton();
      },
    });
  }
  AN.plan = {
    carpeta: c,
    salidas: g?.b ? [] : [...AN.defecto, ...q.filter(k => !AN.defecto.some(s => s.que === k)).map(k => ({ que: k, como: "documento" }))],
  };
  if (!window.Enviar) {
    $("an-check").replaceChildren(el("p", { className: "muted", textContent: "Se extraerá: " + (q.join(", ") || "solo el documento") + "." }));
    AN.plan = null;
    return;
  }
  $("an-check").replaceChildren(
    ...(g?.b ? [el("p", { className: "muted", textContent: "Se lee y se indexa sin resumir: luego lo encuentras con Buscar y Preguntar." })] : []),
  );
  if (!g?.b)
    Enviar.checklist($("an-check"), {
      plan: AN.plan,
      carpeta: c,
      onChange: p => {
        AN.plan = p;
        anBoton();
      },
    });
}
async function anProyecto() {
  const c = $("n-carpeta").value;
  AN.defecto = [];
  if (c && c !== NUEVA_C && window.Enviar)
    AN.defecto = ((await api("/api/carpetas/" + enc(c) + "/plan_defecto").catch(() => null))?.salidas || []).map(({ receta, ...s }) => s);
  anCheck();
}
function anAdd(path, extra = {}) {
  if (!path || AN.files.some(f => f.path === path)) return;
  if (TR_RE.test(path)) return setTr(path);
  AN.files.push({ path, name: path.split(/[\\/]/).pop(), img: IMG_RE.test(path), ...extra });
  anRuta();
  anPintar();
}
const anRuta = () => {
  if (AJ.servidor) return; // sin ruta del disco (y sin estimar con /api/nube/estimar)
  const p = AN.files.find(f => f.path)?.path || "";
  if (p !== ruta) setRuta(p);
};
const stamp = () => new Date().toISOString().slice(0, 19).replace(/\D/g, "");
async function anSubir(files) {
  if (!$("v-nuevo").open) formNuevo();
  for (const f0 of files) {
    const f = f0.name === "image.png" ? new File([f0], "captura-" + stamp() + ".png", { type: f0.type }) : f0;
    const it = { path: "", name: f.name, img: IMG_RE.test(f.name) || f.type.startsWith("image/"), subiendo: true };
    const srv = !!AJ.servidor; // servidor de equipo: no hay rutas del disco; el archivo se manda al procesar (app.js, /api/subir)
    if (srv || !TR_RE.test(f.name)) {
      AN.files.push(it);
      anPintar();
    }
    try {
      if (srv) [it.file, it.path] = [f, "subir:" + crypto.randomUUID()];
      else {
        const p = (await api("/api/upload?name=" + enc(f.name), { method: "PUT", body: f })).path;
        if (TR_RE.test(f.name)) setTr(p);
        else it.path = p;
      }
    } catch (x) {
      it.err = x.message;
    }
    it.subiendo = false;
    anRuta();
    anPintar();
  }
}
function anPintar() {
  const ok = AN.files.filter(f => f.path);
  $("an-files").replaceChildren(
    ...AN.files.map(f =>
      el(
        "li",
        { className: f.err ? "err" : "" },
        el("span", {
          className: "badge",
          textContent: f.img
            ? "Imagen"
            : /\.zip$/i.test(f.name)
              ? "Zip"
              : /\.(eml|msg)$/i.test(f.name)
                ? "Correo"
                : TXT_RE.test(f.name)
                  ? "Documento"
                  : "Vídeo/audio",
        }),
        el("span", { className: "n", textContent: f.name }),
        el("small", { textContent: f.subiendo ? "Copiando…" : f.err || "" }),
        el("button", {
          type: "button",
          className: "qx",
          textContent: "✕",
          ariaLabel: "Quitar " + f.name,
          onclick: () => {
            AN.files.splice(AN.files.indexOf(f), 1);
            anRuta();
            anPintar();
          },
        }),
      ),
    ),
  );
  $("an-desc-w").hidden = !AN.files.some(f => f.img);
  const enl = $("enlace").value.trim();
  $("an-tc-w").hidden = !!AJ.servidor || !(ok.length ? ok.every(f => TXT_RE.test(f.name)) : /\.(pdf|md|txt|docx|html?)(\?|$)/i.test(enl));
  anBoton();
}
function anBoton() {
  const n = AN.files.filter(f => f.path).length + ($("enlace").value.trim() ? 1 : 0),
    t = plantDe($("plantilla").value);
  $("generar").textContent = reuse
    ? "Generar " + (t?.documento?.singular || "documento")
    : AN.buscable
      ? "Hacer buscable" + (n > 1 ? " " + n + " archivos" : "")
      : n > 1
        ? "Procesar " + n + " archivos"
        : "Procesar";
  $("generar").disabled = AN.files.some(f => f.subiendo);
  const s = AN.plan?.salidas || [];
  $("an-res").textContent = $("an-res").title = reuse
    ? ""
    : AN.buscable
      ? "Solo buscable: sin resumen ni extracción"
      : s.length
        ? s.length + (s.length === 1 ? " salida: " : " salidas: ") + s.map(x => x.que).join(", ")
        : ""; // una línea con «…»; el título lleva el texto entero
}
const anParams = dest => ({
  buscable: !reuse && AN.buscable,
  descripcion: $("an-desc").value.trim(),
  tal_cual: !reuse && !$("an-tc-w").hidden && $("an-tc").checked,
  ...(!reuse && AN.plan
    ? {
        plan: {
          ...AN.plan,
          carpeta: dest,
          plantilla: $("plantilla").value,
          ...($("an-nombre").value.trim() ? { nombre: $("an-nombre").value.trim() } : {}),
          ...(AN.buscable ? { solo_buscable: true } : {}),
        },
      }
    : {}),
});
function anLimpiar() {
  anEnlVer(false);
  AN.files = [];
  setRuta("");
  setTr("");
  $("enlace").value = "";
  $("enlace").oninput();
  $("an-desc").value = "";
  $("an-tc").checked = false;
  $("an-nombre").value = "";
  anPintar();
}
const anEnlVer = on => {
  $("t-enlace").hidden = !on;
  $("an-enl-b").setAttribute("aria-expanded", on);
};
function anEnlace(u) {
  if (!$("v-nuevo").open) formNuevo();
  anEnlVer(true);
  $("enlace").value = u;
  $("enlace").oninput();
}
async function anPegar() {
  try {
    for (const it of await navigator.clipboard.read()) {
      const t = it.types.find(x => x.startsWith("image/"));
      if (t) {
        const b = await it.getType(t);
        await anSubir([new File([b], "captura-" + stamp() + "." + t.split("/")[1], { type: t })]);
        $("an-desc").focus();
        return;
      }
    }
    aviso("No hay ninguna imagen en el portapapeles");
  } catch {
    if (!$("v-nuevo").open) formNuevo();
    aviso("Pulsa Ctrl+V para pegar la captura");
  }
}
// la hoja: abrirla monta el objetivo y el plan del proyecto; «Otra versión» (reuse) solo enseña tipo y ajustes
const formNuevo1 = formNuevo;
formNuevo = function (m, a) {
  formNuevo1(m, a);
  $("an-obj").hidden = $("an-nombre").closest(".field").hidden = !!m;
  $("an-av").open = !!m;
  if (AJ.servidor) {
    // el servidor no lee rutas de su disco, no descarga enlaces ni graba; solo documentos, leídos e indexados o resumidos con la nube
    $("elegir").hidden = $("an-enl-b").hidden = $("n-grabar").hidden = true;
    $("form-sub").textContent = "Documentos: se leen y se indexan en el servidor; con un modelo en la nube, también se resumen.";
    $("an-file").accept = ".pdf,.md,.markdown,.txt,.docx,.html,.htm,.eml,.msg,.png,.jpg,.jpeg,.webp";
    document.querySelector("#an-elegir + small").textContent = "PDF, Word, Markdown, texto, HTML o correos (imágenes, con la nube)";
  }
  $("form-t").textContent = m ? $("form-t").textContent : "Añadir";
  if (!m) {
    anGoals();
    if (AN.goal && !anChips()) anGoal(AN.goal);
    anProyecto();
  }
  anEnlVer(!!$("enlace").value.trim());
  anPintar();
  if ($("v-nuevo").open) ($("an-elegir").offsetParent ? $("an-elegir") : $("generar")).focus(); // foco inicial: «Elegir archivos» (no el «×»)
};
$("n-carpeta").addEventListener("change", anProyecto);
$("an-x").onclick = () => $("v-nuevo").close();
$("an-cancel").onclick = () => {
  anLimpiar();
  $("v-nuevo").close();
};
$("an-elegir").onclick = () => $("an-file").click();
$("an-file").onchange = () => {
  anSubir([...$("an-file").files]);
  $("an-file").value = "";
};
$("an-pegar").onclick = anPegar;
$("an-enl-b").onclick = () => {
  anEnlVer($("t-enlace").hidden);
  if (!$("t-enlace").hidden) $("enlace").focus();
};
$("drop").addEventListener("click", e => {
  if (e.target === $("drop") || e.target.closest(".t, .ico")) $("an-file").click();
}); // toda la zona abre el selector
$("h-enl-b").onclick = () => {
  const f = $("h-enl");
  f.hidden = !f.hidden;
  $("h-enl-b").setAttribute("aria-expanded", !f.hidden);
  if (!f.hidden) $("h-enl-i").focus();
};
$("enlace").addEventListener("input", anPintar);
$("nueva").onclick = () => formNuevo();
// Inicio: zona grande de soltar
$("h-elegir").onclick = () => {
  formNuevo();
  $("an-file").click();
};
$("h-pegar").onclick = anPegar;
$("h-grabar").onclick = () => grabarAbrir();
$("h-enl").onsubmit = e => {
  e.preventDefault();
  const u = $("h-enl-i").value.trim();
  if (u) {
    anEnlace(u);
    $("h-enl-i").value = "";
  }
};
// táctil o móvil: «Suelta archivos» no aplica → título «Añadir», un botón y la franja entera abre la hoja (enlace, captura y grabar van dentro)
const tactil = matchMedia("(max-width: 560px), (pointer: coarse)"),
  hdTactil = () => {
    document.body.classList.toggle("tactil", tactil.matches);
    $("h-drop-t").textContent = tactil.matches ? "Añadir" : "Suelta archivos o pega un enlace";
    $("drop-t").textContent = tactil.matches ? "Archivos, fotos o capturas" : "Suelta aquí tus archivos";
  };
tactil.addEventListener("change", hdTactil);
hdTactil();
$("h-drop").addEventListener("click", e => {
  if (tactil.matches && !e.target.closest("button, a, input, form")) formNuevo();
});
// toda la ventana acepta soltar archivos o enlaces (no los arrastres internos de documentos a proyectos) y pegar capturas o enlaces
const arrastreExt = e => !arrastrando && [...(e.dataTransfer?.types || [])].some(t => t === "Files" || t === "text/uri-list");
addEventListener("dragover", e => {
  if (arrastreExt(e)) {
    e.preventDefault();
    document.body.classList.add("soltando");
  }
});
addEventListener("dragleave", e => {
  if (!e.relatedTarget) document.body.classList.remove("soltando");
});
addEventListener("drop", e => {
  document.body.classList.remove("soltando");
  if (!arrastreExt(e) || e.defaultPrevented) return;
  e.preventDefault();
  const fs = [...e.dataTransfer.files],
    u = (e.dataTransfer.getData("text/uri-list") || "").split("\n")[0].trim();
  if (fs.length) anSubir(fs);
  else if (/^https?:\/\//i.test(u)) anEnlace(u);
});
addEventListener("paste", e => {
  const fs = [...(e.clipboardData?.files || [])];
  if (fs.length) {
    e.preventDefault();
    anSubir(fs);
    return;
  }
  const t = (e.clipboardData?.getData("text") || "").trim();
  if (!editable(e.target) && /^https?:\/\/\S+$/i.test(t)) {
    e.preventDefault();
    anEnlace(t);
  }
});

// ---------- Inicio: tira del flujo, Continúa, Por revisar ----------
const INI = { p: null, t: 0, k: "" };
function iniDatos() {
  const k = carpetas.slice(0, 12).join("|"); // la clave lleva los proyectos: la lista vacía del arranque no se queda cacheada 30 s como «sin registro» (P2-9)
  if (INI.p && INI.k === k && Date.now() - INI.t < 30000) return INI.p;
  INI.t = Date.now();
  INI.k = k;
  return (INI.p = Promise.all([
    Promise.all(
      carpetas.slice(0, 12).map(c =>
        api("/api/reg?" + new URLSearchParams({ c }))
          .then(r => ({ c, r }))
          .catch(() => null),
      ),
    ),
    api("/api/envios?limit=200").catch(() => []),
  ]).then(([regs, env]) => ({ regs: regs.filter(Boolean), env })));
}
const stT = (t, c) => el("span", { className: "st " + c, textContent: t }); // estado: punto de color + texto (no parece botón)
// container transform: la fila de «Continúa» se convierte en la cabecera del documento (View Transitions; sin soporte, abre directo)
async function abrirVT(fila, id) {
  if (!document.startViewTransition || matchMedia("(prefers-reduced-motion: reduce)").matches || document.documentElement.dataset.anim === "no")
    return abrir(id);
  fila.style.viewTransitionName = "doc-vt";
  const orig = document.startViewTransition.bind(document),
    okT = { finished: Promise.resolve(), ready: Promise.resolve(), updateCallbackDone: Promise.resolve() };
  const t = orig(async () => {
    fila.style.viewTransitionName = "";
    document.startViewTransition = f => {
      f();
      return okT;
    }; // la vista() de app.js no debe abrir otra transición encima de esta
    try {
      await abrir(id);
    } finally {
      document.startViewTransition = orig;
    }
    const h = $("cab-titulo")?.closest(".dh-t") || $("v-res");
    h.style.viewTransitionName = "doc-vt";
  });
  t.ready.catch(() => {});
  t.updateCallbackDone.catch(() => {});
  try {
    await t.finished;
  } catch {
  } finally {
    $("cab-titulo")?.closest(".dh-t")?.style.removeProperty("view-transition-name");
  }
}
function pintarInicio() {
  const vacio = !todas.length && !cola.items.length,
    act = cola.items.filter(e => ACT.includes(e.state)),
    run = act.find(e => e.state === "marcha");
  $("h-flujo").hidden = $("h-cont").hidden = vacio;
  const pl0 = lsGet("an.goal", ""),
    g = GOALS.find(x => x.id === pl0);
  $("h-receta").replaceChildren(
    el("span", { className: "muted", textContent: "Al terminar: " }),
    g ? g.t + (g.q?.length ? " (" + g.q.join(", ") + ")" : "") : "el documento y lo que digan las recetas del proyecto",
    " · ",
    el("button", { type: "button", className: "link", textContent: "Cambiar", onclick: () => formNuevo() }),
  );
  // Continúa: lo que se está procesando y lo último
  const nuevas = act
    .filter(e => e.kind === "acta" && !e.mid)
    .map(e =>
      el(
        "div",
        { className: "h-ci" },
        el("span", { className: "n" }, el("b", { textContent: e.video }), el("small", { textContent: "Procesando" })),
        stT(e.state === "marcha" ? "Procesando " + Math.round(e.frac * 100) + " %" : "En cola", "acc"),
      ),
    );
  const recientes = todas.slice(0, 6).map(m => {
    const e = act.find(x => x.mid === m.id),
      r = RES[m.carpeta || ""] || {};
    const st = e ? stT(e.state === "marcha" ? "Procesando" : "En cola", "acc") : r.sug ? stT(r.sug + " por revisar", "w") : null; // «Listo» no se dice: solo lo que pide atención
    const fila = el(
      "button",
      { type: "button", className: "h-ci", "data-mid": m.id, onclick: fallo(() => abrirVT(fila, m.id)) },
      el(
        "span",
        { className: "n" },
        el("b", { textContent: m.label }),
        el("small", {
          textContent: [m.carpeta || sinC(), fechaC(m.mtime), m.dur ? Math.round(m.dur / 60) + " min" : KIND_T[m.kind]].filter(Boolean).join(" · "),
        }),
      ),
      ...(st ? [st] : []),
    );
    return fila;
  });
  $("h-cont-l").replaceChildren(...nuevas, ...recientes);
  escalona($("h-cont-l"));
  // tira del flujo (contadores clicables); los del registro y los envíos llegan después
  const tile = (n, t, v, s, f) =>
    el(
      "button",
      { type: "button", className: "fl", onclick: f },
      el("span", { className: "fl-t", textContent: n + " · " + t }),
      v == null ? el("b", { className: "sk sk-n", "aria-label": "Cargando" }) : el("b", { textContent: v }),
      el("small", { textContent: s }),
    );
  const pinta = (rev, apr, hoy, ult) => {
    const ts = [
      [
        act.length,
        1,
        "En cola",
        run ? "Procesando: " + nombreDe(run) : "Esperando turno",
        () => {
          location.hash = "#/cola";
        },
      ],
      [rev, 2, "Por revisar", "Elementos extraídos sin aprobar", () => $("rev").scrollIntoView({ block: "start" })],
      [
        apr,
        3,
        "Listo para enviar",
        "Elementos aprobados",
        () => {
          location.hash = "#/enviar";
        },
      ],
      [
        hoy,
        4,
        "Enviado hoy",
        ult || "Historial en Enviar",
        () => {
          location.hash = "#/enviar";
        },
      ],
    ].filter(x => x[0] > 0); // solo las etapas con algo
    $("h-flujo").hidden = vacio || !ts.length;
    $("h-flujo").replaceChildren(...ts.map(([v, n, t, sb, f]) => tile(n, t, v, sb, f)));
  };
  pinta();
  // sugerencias: lo listo de la cola ya; lo del registro cuando llega (mismo hueco: esqueleto si la última vez hubo)
  const listo = cola.items.filter(e => e.kind === "acta" && e.state === "hecho" && e.mid && todas.some(m => m.id === e.mid)).pop();
  sugerencias(
    listo
      ? [{ k: "doc:" + listo.mid, t: "Documento listo: " + nombreDe(listo), s: "Revísalo antes de enviarlo", b: "Abrir", f: fallo(() => abrir(listo.mid)) }]
      : [],
    true,
  );
  iniDatos().then(({ regs, env }) => {
    if (vistaAct !== "home" || fsel !== undefined) return;
    const rev = regs.flatMap(({ c, r }) => r.items.filter(x => x.revision === "propuesto").map(x => ({ ...x, c }))),
      cont = k => regs.reduce((s, { r }) => s + (r.contadores?.por_revision?.[k] || 0), 0),
      nRev = cont("propuesto"),
      apr = cont("aprobado"); // los números son los contadores del backend (los mismos que el proyecto); las filas, los ítems
    const hoy = env.filter(e => e.estado === "ok" && e.t * 1000 >= new Date().setHours(0, 0, 0, 0)),
      u = hoy[0];
    pinta(
      nRev + Object.values(RES).reduce((s, x) => s + (x?.sug || 0), 0),
      apr,
      hoy.length,
      u ? "Última: " + (u.destino || "") + " · " + new Date(u.t * 1000).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" }) : "",
    );
    const porDoc = {};
    rev.forEach(x =>
      new Set((x.citas || []).map(ci => ci.mid)).forEach(id => {
        porDoc[id] = (porDoc[id] || 0) + 1;
      }),
    ); // propuestas del registro por documento (RES.sug solo cuenta pendientes)
    $("h-cont-l")
      .querySelectorAll(".h-ci[data-mid]")
      .forEach(f => {
        const n = porDoc[f.dataset.mid];
        if (n && !f.querySelector(".st")) f.append(stT(n + " por revisar", "w"));
      });
    $("rev-reg").replaceChildren(
      ...rev.slice(0, 6).map(x => {
        const ci = x.citas?.[0],
          d = ci && todas.find(m => m.id === ci.mid);
        return el(
          "div",
          { className: "rv-i" },
          badgeT(TIPO_T[x.tipo] || x.tipo, "acc"),
          el("span", { className: "n", textContent: x.titulo }),
          el("small", { textContent: [x.c, d && d.label + (ci.t != null ? " · " + mmss(ci.t) : "")].filter(Boolean).join(" · ") }),
          el("button", {
            type: "button",
            className: "sec sm",
            textContent: "Revisar",
            onclick: () => {
              fsel = x.c;
              vista("home");
              fIr("revision", { ids: [x.id] });
            },
          }),
        );
      }),
    );
    $("rev-acc").replaceChildren(
      ...(nRev
        ? [
            el("button", {
              type: "button",
              className: "sec sm",
              textContent: "Aprobar todo (" + nRev + ")",
              onclick: fallo(async () => {
                const cs = [...new Set(rev.map(x => x.c))];
                for (const c of cs) await post("/api/reg/revisar", { c, ids: rev.filter(x => x.c === c).map(x => x.id), accion: "aprobar" });
                INI.p = null;
                aviso(rev.length + " aprobados", {
                  txt: "Deshacer",
                  fn: fallo(async () => {
                    for (const c of cs) await post("/api/reg/deshacer", { c });
                    INI.p = null;
                    pintarHome();
                  }),
                });
                pintarHome();
              }),
            }),
          ]
        : []),
    );
    if (nRev) $("rev").hidden = false;
    const n = nRev + Object.values(RES).reduce((s, x) => s + (x?.sug || 0), 0),
      c0 = rev[0]?.c ?? Object.keys(RES).find(c => RES[c]?.sug);
    sugerencias([
      ...(n && c0 != null
        ? [
            {
              k: "rev:" + n,
              t: n + " por revisar",
              s: "Propuestos por la IA, sin aprobar",
              b: "Revisar",
              w: 1,
              f: () => {
                fsel = c0;
                vista("home");
                fIr("revision");
              },
            },
          ]
        : []),
      ...(apr
        ? [
            {
              k: "env:" + apr,
              t: apr + (apr === 1 ? " elemento listo" : " elementos listos") + " para enviar",
              s: "Aprobados y sin enviar",
              b: "Enviar",
              f: () => {
                location.hash = "#/enviar";
              },
            },
          ]
        : []),
      ...(listo
        ? [{ k: "doc:" + listo.mid, t: "Documento listo: " + nombreDe(listo), s: "Revísalo antes de enviarlo", b: "Abrir", f: fallo(() => abrir(listo.mid)) }]
        : []),
    ]);
  });
}
// Inicio › Sugerencias: tarjetas descartables (lo descartado vuelve si cambia: la clave lleva el número o el documento)
function sugerencias(l, prov, anim = !prov) {
  // prov: lista provisional (falta el registro): esqueleto si la última vez hubo sugerencias
  const fuera = lsGet("ini.sug.x", []),
    vis = l.filter(x => !fuera.includes(x.k)),
    esperando = prov && INI.nSug > 0;
  if (!prov) INI.nSug = vis.length;
  $("h-sug").replaceChildren(
    ...vis.slice(0, 1).map(x =>
      el(
        "div",
        { className: "sug-c" + (x.w ? " w" : "") },
        el(
          "span",
          { className: "n" },
          el("small", { className: "eb", textContent: "Siguiente paso" }),
          el("b", { textContent: x.t }),
          el("small", { textContent: x.s }),
        ),
        el("button", { type: "button", className: "sec sm", textContent: x.b, onclick: x.f }),
        el("button", {
          type: "button",
          className: "qx",
          textContent: "✕",
          ariaLabel: "Descartar: " + x.t,
          title: "Descartar",
          onclick: () => {
            lsSet("ini.sug.x", [...fuera, x.k].slice(-40));
            sugerencias(l, false, false);
            $("h-sug").querySelector(".qx")?.focus();
          },
        }),
      ),
    ),
    ...(esperando && !vis.length ? [el("div", { className: "sk-c", "aria-hidden": "true" }, ...sk(2))] : []),
  );
  if (anim) escalona($("h-sug"));
}

// ---------- Biblioteca: una sola lista con chips de tipo, filtros, selección múltiple y vista previa ----------
const BIB = { ms: [], sel: new Set(), tipo: "", c: "*", est: "", dias: 0, q: "", act: null };
async function pintarBib() {
  if (!BIB.ms.length)
    $("bib-tb").replaceChildren(
      ...Array.from({ length: 6 }, () => el("tr", { className: "sk-r", "aria-hidden": "true" }, el("td", { colSpan: 6 }, el("span", { className: "sk" })))),
    );
  BIB.ms = unicas(await api("/api/meetings").catch(() => todas));
  BIB.sel = new Set([...BIB.sel].filter(id => BIB.ms.some(m => m.id === id)));
  pintarBibL();
}
const BIB0 = { tipo: "", c: "*", est: "", dias: 0, q: "" },
  BIB_SERIE = [
    { n: "Esta semana", dias: 7 },
    { n: "Solo buscable", est: "buscable" },
    { n: "En cola", est: "cola" },
  ];
const bibVista = v => {
  Object.assign(BIB, BIB0, v);
  if (BIB.qEl) BIB.qEl.value = BIB.q;
  pintarBibL();
};
// una sola fila de filtros: buscador | Tipo | Proyecto | Estado | Fecha | Rápidos (Esta semana, Solo buscable, En cola + vistas guardadas y «Guardar la vista actual»); el buscador se crea una vez (no pierde el foco)
function bibBarra(ms) {
  const f = $("bib-f");
  if (!f.firstChild) {
    BIB.qEl = el("input", {
      type: "search",
      placeholder: "Filtrar por nombre",
      ariaLabel: "Filtrar por nombre",
      oninput: () => {
        BIB.q = BIB.qEl.value;
        pintarBibL();
      },
    });
    f.append(el("div", { className: "fbar" }, BIB.qEl, el("div", { id: "bib-fp", className: "fp", role: "group", ariaLabel: "Filtros" })));
    document.addEventListener("click", e =>
      document.querySelectorAll("#bib-f details[open]").forEach(d => {
        if (!d.contains(e.target)) d.open = false;
      }),
    );
    f.addEventListener("keydown", e => {
      if (e.key === "Escape")
        f.querySelectorAll("details[open]").forEach(d => {
          d.open = false;
          d.querySelector("summary").focus();
        });
    });
  }
  if (BIB.qEl.value !== BIB.q) BIB.qEl.value = BIB.q;
  const abierto = $("bib-fp").querySelector("details[open]")?.dataset.k; // repintar no cierra el menú abierto
  const caja = (k, lab, on, ...hijos) => {
    const d = el(
      "details",
      { className: "fpop" + (on ? " on" : ""), "data-k": k, open: abierto === k },
      el("summary", { className: "fchip", textContent: lab }),
      el("div", { className: "fpop-l", role: "group", ariaLabel: k }, ...hijos),
    );
    return d;
  };
  const pop = (lab, v, ops, def, fn) => {
    const c = ops.find(o => String(o[0]) === String(v)),
      act = String(v) !== String(def);
    return caja(
      lab,
      act ? lab + ": " + c[1] : lab,
      act,
      ...ops.map(([k, t]) =>
        el("button", {
          type: "button",
          className: "fpop-o",
          "aria-pressed": String(k) === String(v),
          textContent: t,
          onclick: () => {
            fn(k);
            $("bib-fp").querySelector("details[open]")?.removeAttribute("open");
            pintarBibL();
          },
        }),
      ),
    );
  };
  const guardar = () => {
    const v = { tipo: BIB.tipo, c: BIB.c, est: BIB.est, dias: BIB.dias, q: BIB.q },
      n = [
        KIND_T[v.tipo],
        v.c !== "*" && (v.c || sinC()),
        { listo: "Listo", buscable: "Solo buscable", cola: "En cola" }[v.est],
        v.dias && "Últimos " + v.dias + " d",
        v.q && "«" + v.q + "»",
      ]
        .filter(Boolean)
        .join(" · ");
    if (!n) return aviso("Elige algún filtro antes de guardar la vista");
    lsSet("bib.vistas", [...lsGet("bib.vistas", []).filter(x => x.n !== n), { n, ...v }].slice(-8));
    aviso("Vista guardada: " + n);
    pintarBibL();
  };
  const vistas = lsGet("bib.vistas", []),
    filtrado = BIB.tipo || BIB.c !== "*" || BIB.est || BIB.dias || BIB.q,
    vb = v =>
      el("button", {
        type: "button",
        className: "fpop-o",
        textContent: v.n,
        onclick: () => {
          $("bib-fp").querySelector("details[open]")?.removeAttribute("open");
          bibVista(v);
        },
      });
  const tipos = Object.entries(KIND_T)
    .map(([k, t]) => [k, t + " · " + ms.filter(m => m.kind === k).length, ms.some(m => m.kind === k)])
    .filter(x => x[2]);
  $("bib-fp").replaceChildren(
    pop("Tipo", BIB.tipo, [["", "Todo · " + ms.length], ...tipos], "", v => (BIB.tipo = v)),
    ...(carpetas.length || ms.some(m => !m.carpeta)
      ? [pop(cap(nm("carpeta")), BIB.c, [["*", "Todos"], ...carpetas.map(c => [c, c]), ["", sinC()]], "*", v => (BIB.c = v))]
      : []),
    pop(
      "Estado",
      BIB.est,
      [
        ["", "Cualquiera"],
        ["listo", "Listo"],
        ["buscable", "Solo buscable"],
        ["cola", "En cola"],
      ],
      "",
      v => (BIB.est = v),
    ),
    pop(
      "Fecha",
      BIB.dias,
      [
        [0, "Cualquiera"],
        [1, "Hoy"],
        [7, "Últimos 7 días"],
        [30, "Últimos 30 días"],
      ],
      0,
      v => (BIB.dias = +v),
    ),
    caja(
      "Rápidos",
      "Rápidos",
      false,
      ...BIB_SERIE.map(vb),
      ...(vistas.length
        ? [
            el("p", { className: "ovl fpop-h", textContent: "Guardadas" }),
            ...vistas.map(v =>
              el(
                "span",
                { className: "fchip-x" },
                vb(v),
                el("button", {
                  type: "button",
                  className: "qx",
                  textContent: "✕",
                  ariaLabel: "Quitar la vista " + v.n,
                  onclick: () => {
                    lsSet(
                      "bib.vistas",
                      lsGet("bib.vistas", []).filter(x => x.n !== v.n),
                    );
                    pintarBibL();
                    $("bib-fp").querySelector("[data-k=Rápidos] summary")?.focus();
                  },
                }),
              ),
            ),
          ]
        : []),
      el("button", {
        type: "button",
        className: "fpop-o fpop-g",
        textContent: "Guardar la vista actual",
        disabled: !filtrado,
        title: filtrado ? "Guarda los filtros de ahora como una vista" : "Elige algún filtro antes",
        onclick: guardar,
      }),
    ),
    ...(filtrado ? [el("button", { type: "button", className: "link fp-x", textContent: "Quitar filtros", onclick: () => bibVista({}) })] : []),
  );
}
const bibEst = m => (cola.items.some(e => ACT.includes(e.state) && e.mid === m.id) ? "cola" : m.actas ? "listo" : "buscable");
function pintarBibL() {
  const ms = BIB.ms,
    ok = m =>
      (!BIB.tipo || m.kind === BIB.tipo) &&
      (BIB.c === "*" || (m.carpeta || "") === BIB.c) &&
      (!BIB.est || bibEst(m) === BIB.est) &&
      (!BIB.dias || m.mtime * 1000 > Date.now() - BIB.dias * 864e5) &&
      (!BIB.q || norm(m.label + " " + m.carpeta).includes(norm(BIB.q)));
  const vis = ms.filter(ok);
  $("bib-n").textContent = vis.length === ms.length ? plural(ms.length) : vis.length + " de " + ms.length;
  if (BIB_N.n !== ms.length) {
    BIB_N.n = ms.length;
    pintarSide();
  }
  bibBarra(ms);
  const ESTT = { listo: ["Listo", "ok"], buscable: ["Solo buscable", ""], cola: ["En cola", "acc"] };
  $("bib-tb").replaceChildren(
    ...vis.map(m => {
      const ck = el("input", {
        type: "checkbox",
        checked: BIB.sel.has(m.id),
        ariaLabel: "Seleccionar " + m.label,
        onchange: () => {
          ck.checked ? BIB.sel.add(m.id) : BIB.sel.delete(m.id);
          bibBulk();
        },
      });
      const tr = el(
        "tr",
        {
          className: "f" + (BIB.act === m.id ? " on" : ""),
          draggable: true,
          ondragstart: ev => {
            arrastrando = m;
            ev.dataTransfer.effectAllowed = "move";
            ev.dataTransfer.setData("text/plain", m.id);
          },
          ondragend: () => {
            arrastrando = null;
          },
        },
        el("td", {}, ck),
        el(
          "td",
          {},
          el("button", { type: "button", className: "doc-l", textContent: m.label, onclick: () => bibVer(m), ondblclick: fallo(() => abrir(m.id)) }),
        ),
        el("td", { textContent: KIND_T[m.kind] || m.kind || "" }),
        el("td", { textContent: m.carpeta || "" }),
        el("td", { textContent: fechaC(m.mtime) }),
        el("td", {}, ...(bibEst(m) === "listo" ? [] : [badgeT(...ESTT[bibEst(m)])])),
      ); // «Listo» es lo normal: solo se marca lo que no lo está
      return tr;
    }),
  );
  escalona($("bib-tb"));
  $("bib-tb")
    .closest(".bib-l")
    .classList.toggle("sin-est", !vis.some(m => bibEst(m) !== "listo")); // sin columna ESTADO cuando ninguna fila tiene estado (N3)
  $("bib-v").hidden = !!vis.length;
  $("v-bib").classList.toggle("sin-docs", !ms.length);
  $("bib-v").replaceChildren(
    ...(ms.length
      ? [
          el("p", { textContent: "Nada coincide con los filtros." }),
          el("button", { type: "button", className: "sec sm", textContent: "Quitar filtros", onclick: () => bibVista({}) }),
        ]
      : [
          el("span", { className: "vi", "aria-hidden": "true" }, "▤"),
          el("b", { textContent: "Tu biblioteca está vacía" }),
          el("p", { className: "muted", textContent: "Suelta archivos en cualquier parte de la ventana, pega un enlace o una captura." }),
          el("button", { type: "button", className: "sec", textContent: "Añadir " + nm("documento"), onclick: () => formNuevo() }),
        ]),
  );
  $("bib-all").checked = vis.length > 0 && vis.every(m => BIB.sel.has(m.id));
  $("bib-all").onchange = () => {
    vis.forEach(m => ($("bib-all").checked ? BIB.sel.add(m.id) : BIB.sel.delete(m.id)));
    pintarBibL();
  };
  bibBulk();
}
function bibEnviar(ids) {
  // un envío por documento; los solo buscables no tienen acta que enviar
  const con = ids.filter(id => BIB.ms.find(m => m.id === id)?.actas);
  if (!con.length) return aviso("Los documentos solo buscables no se envían: usa «Resumir y extraer» antes");
  Enviar.enviar({ docs: con, omitidos: ids.length - con.length });
}
function bibBulk() {
  const ids = [...BIB.sel],
    n = ids.length;
  $("bib-bulk").hidden = !n;
  $("bib-h").classList.toggle("sel", !!n); // la barra contextual sustituye al título (Esc la quita)
  $("bib-bulk").replaceChildren(
    el("button", {
      type: "button",
      className: "gh ic",
      textContent: "✕",
      ariaLabel: "Quitar selección",
      title: "Quitar selección (Esc)",
      onclick: () => {
        BIB.sel.clear();
        pintarBibL();
        $("bib-all").focus();
      },
    }),
    el("b", { textContent: n + (n === 1 ? " seleccionado" : " seleccionados") }),
    el("span", { className: "grow" }),
    el("button", {
      type: "button",
      className: "sec sm",
      textContent: "Descargar",
      onclick: () => (window.Descargar ? Descargar.abrir({ docs: ids }) : sinEnviar()),
    }),
    el("button", {
      type: "button",
      className: "sec sm",
      textContent: "Enviar",
      onclick: () => (!window.Enviar ? sinEnviar() : n === 1 ? Enviar.enviar({ doc: ids[0] }) : bibEnviar(ids)),
    }),
    el("button", { type: "button", className: "sec sm", textContent: "Mover…", onclick: () => bibMover(ids) }),
  );
}
// mover varios a otro proyecto (o a «Sin proyecto») sin reprocesar; con «Deshacer». «Copiar o enviar a la vez» = el flujo de «Añadir a proyecto» (aProyecto)
function bibMover(ids) {
  const { d, b, f } = dialogo(
    "Mover " + ids.length + " " + (ids.length === 1 ? nm("documento") : pl(nm("documento"))),
    "Cambia el " + nm("carpeta").toLowerCase() + " sin reprocesar nada.",
  );
  const s = el("select", { id: "mv-c" }, ...carpetas.map(c => new Option(c, c)), new Option(sinC(), ""));
  b.append(
    el("div", { className: "field" }, el("label", { htmlFor: "mv-c", textContent: cap(nm("carpeta")) }), s),
    ...(carpetas.length
      ? [
          el("button", {
            type: "button",
            className: "link",
            textContent: "Copiar en vez de mover, o enviar a la vez…",
            onclick: () => {
              d.close();
              aProyecto(ids);
            },
          }),
        ]
      : []),
  );
  const ok = el("button", {
    type: "button",
    className: "pri",
    textContent: "Mover",
    onclick: fallo(async () => {
      const antes = ids.map(id => [id, BIB.ms.find(m => m.id === id)?.carpeta || ""]),
        c = s.value;
      ok.disabled = true;
      try {
        for (const id of ids) await post("/api/meta", { id, carpeta: c });
      } finally {
        d.close();
      }
      BIB.sel.clear();
      await cargarLista();
      pintarBib();
      aviso("Movido a «" + (c || sinC()) + "»", {
        txt: "Deshacer",
        fn: fallo(async () => {
          for (const [id, c0] of antes) await post("/api/meta", { id, carpeta: c0 });
          await cargarLista();
          pintarBib();
        }),
      });
    }),
  });
  f.append(
    el("span"),
    el("div", { className: "row" }, el("button", { type: "button", className: "sec", textContent: "Cancelar", onclick: () => d.close() }), ok),
  );
}
$("v-bib").addEventListener("keydown", e => {
  if (e.key === "Escape" && BIB.sel.size && (e.target.type === "checkbox" || !editable(e.target))) {
    BIB.sel.clear();
    pintarBibL();
    $("bib-all").focus();
  }
});
async function bibVer(m) {
  BIB.act = m.id;
  pintarBibL();
  const p = $("bib-p");
  p.hidden = false;
  $("bib-g").classList.add("con-p");
  const acc = el(
    "div",
    { className: "row wrap" },
    ...(m.actas ? [el("button", { type: "button", className: "pri sm", textContent: "Abrir", onclick: fallo(() => abrir(m.id)) })] : []),
    el("button", { type: "button", className: "sec sm", textContent: "Enviar", onclick: () => (window.Enviar ? Enviar.enviar({ doc: m.id }) : sinEnviar()) }),
    el("button", { type: "button", className: "sec sm", textContent: "Añadir a " + nm("carpeta").toLowerCase(), onclick: () => aProyecto([m.id]) }),
    el("button", {
      type: "button",
      className: "sec sm",
      textContent: "Descargar",
      onclick: () => (window.Descargar ? Descargar.abrir({ docs: [m.id] }) : sinEnviar()),
    }),
    el("button", { type: "button", className: "sec sm", textContent: "Renombrar", onclick: () => renombrar(m, p) }),
    el("button", { type: "button", className: "sec sm", textContent: "Mover", onclick: () => mover(m, p) }),
  );
  p.replaceChildren(
    el("button", {
      type: "button",
      className: "gh ic bib-x",
      textContent: "✕",
      ariaLabel: "Cerrar la vista previa",
      title: "Cerrar",
      onclick: () => {
        BIB.act = null;
        p.hidden = true;
        $("bib-g").classList.remove("con-p");
        pintarBibL();
      },
    }),
    el("h2", { textContent: m.label }),
    el("p", {
      className: "muted",
      textContent: [
        KIND_T[m.kind],
        m.carpeta || sinC(),
        fechaC(m.mtime),
        m.dur ? Math.round(m.dur / 60) + " min" : "",
        m.actas > 1 ? m.actas + " versiones" : "",
      ]
        .filter(Boolean)
        .join(" · "),
    }),
    acc,
    m.actas
      ? el("div", { className: "bib-res", "aria-busy": "true" }, ...sk(4))
      : el("p", { className: "muted", textContent: "Solo buscable: se encuentra con Buscar y Preguntar." }),
  );
  if (!m.actas) return;
  try {
    const d = await api("/api/meeting/" + m.id),
      a = d.actas.reduce((x, y) => (y.mtime > x.mtime ? y : x)),
      doc = (await api(`/api/doc/${m.id}/${a.name}`)).datos;
    if (BIB.act !== m.id) return;
    p.lastChild.replaceWith(
      el(
        "div",
        { className: "bib-res" },
        el("h3", { textContent: "Resumen" }),
        el("p", { textContent: doc.resumen || "—" }),
        ...((doc.puntos || []).length
          ? [el("h3", { textContent: "Puntos clave" }), el("ul", {}, ...doc.puntos.slice(0, 6).map(x => el("li", { textContent: x.texto || x })))]
          : []),
      ),
    );
  } catch (x) {
    p.lastChild.textContent = x.message;
  }
}

// ---------- Pendientes de todos los proyectos ----------
// marcar hecho (o descartar) no pide confirmación: snackbar con «Deshacer» que lo reabre
const hechoDeshacer = (c, p, luego, txt = "Hecho") =>
  aviso(txt + ": «" + (p.texto.length > 48 ? p.texto.slice(0, 47) + "…" : p.texto) + "»", {
    txt: "Deshacer",
    fn: fallo(async () => {
      await post("/api/exp/pendientes", { c, id: p.id, estado: "abierto" });
      await cargarLista();
      fsucio = true;
      await luego();
    }),
  });
// «Asignado a mí» (Ajustes › Tú): el responsable es tu nombre, tu nombre de pila o tu nombre completo empieza por él
const esMio = r => {
  const n = (AJ.yo?.nombre || "").trim().toLowerCase();
  r = (r || "").trim().toLowerCase();
  return !!n && !!r && (r === n || n.startsWith(r + " ") || r.startsWith(n + " "));
};
const PEND = { c: "*", resp: "", g: "" },
  PEND_G = [
    ["venc", "Vencidas"],
    ["sem", "Esta semana"],
    ["desp", "Después"],
    ["sin", "Sin fecha"],
  ];
const pendG = p => (p.vencido ? "venc" : p.pronto ? "sem" : p.fecha ? "desp" : "sin");
async function pintarPendPag() {
  const w = $("pend-l");
  if (!w.querySelector("table, .vacio")) w.replaceChildren(el("div", { "aria-busy": "true" }, ...sk(5)));
  // el contador del raíl sale de RES; en una carga directa (#/pendientes) aún puede estar vacío: se pide fresco
  const R = Object.keys(RES).length ? RES : await api("/api/carpetas/resumen").catch(() => ({})),
    cs = Object.keys(R).filter(c => R[c]?.pend);
  const todos = (
    await Promise.all(
      cs.map(c =>
        api("/api/exp/pendientes?" + new URLSearchParams({ c, estado: "abierto", orden: "plazo" }))
          .then(r => r.items.filter(p => p.estado === "abierto").map(p => ({ ...p, c })))
          .catch(() => []),
      ),
    )
  )
    .flat()
    .sort((a, b) => !!b.vencido - !!a.vencido || !!b.pronto - !!a.pronto || (a.fecha || "9").localeCompare(b.fecha || "9"));
  $("pend-f").textContent = todos.length ? todos.length + " abiertos" : "";
  if (!todos.length)
    return w.replaceChildren(
      el(
        "div",
        { className: "vacio vacio-e" },
        el("span", { className: "vi", "aria-hidden": "true" }, "✓"),
        el("b", { textContent: "Todo al día" }),
        el("p", {
          className: "muted",
          textContent: "Aquí aparecen las tareas que salen de tus " + pl(nm("documento")) + " y las que añadas a mano, con su plazo y responsable.",
        }),
        el(
          "div",
          { className: "row wrap" },
          el("button", { type: "button", className: "sec", textContent: "Añadir " + nm("documento"), onclick: () => formNuevo() }),
          el("a", { href: "#/biblioteca", className: "btn sec", textContent: "Ver la biblioteca" }),
        ),
      ),
    );
  const resps = [...new Set(todos.map(p => p.resp).filter(Boolean))].sort((a, b) => a.localeCompare(b)),
    projs = [...new Set(todos.map(p => p.c))];
  if (PEND.c !== "*" && !projs.includes(PEND.c)) PEND.c = "*";
  if (PEND.resp && PEND.resp !== ":yo:" && !resps.includes(PEND.resp)) PEND.resp = "";
  const base = todos.filter(p => (PEND.c === "*" || p.c === PEND.c) && (!PEND.resp || (PEND.resp === ":yo:" ? esMio(p.resp) : p.resp === PEND.resp))),
    its = base.filter(p => !PEND.g || pendG(p) === PEND.g);
  const chip = (v, t, n) =>
    el(
      "button",
      {
        type: "button",
        className: "fchip",
        "aria-pressed": PEND.g === v,
        onclick: () => {
          PEND.g = v;
          pintarPendPag();
        },
      },
      t,
      el("i", { textContent: " " + n }),
    );
  const sel = (lab, v, ops, f) => {
    const s = el(
      "select",
      {
        ariaLabel: lab,
        onchange: () => {
          f(s.value);
          pintarPendPag();
        },
      },
      ...ops.map(([k, t]) => new Option(t, k)),
    );
    s.value = v;
    return s;
  };
  const bar = el(
    "div",
    { className: "fbar" },
    el(
      "div",
      { className: "row wrap", role: "group", ariaLabel: "Plazo" },
      chip("", "Todos", base.length),
      ...PEND_G.map(([k, t]) => [k, t, base.filter(p => pendG(p) === k).length])
        .filter(x => x[2])
        .map(x => chip(...x)),
    ),
    ...(projs.length > 1
      ? [sel(cap(nm("carpeta")), PEND.c, [["*", "Todos los " + pl(nm("carpeta").toLowerCase())], ...projs.map(c => [c, c || sinC()])], v => (PEND.c = v))]
      : []),
    ...(resps.length
      ? [
          sel(
            "Responsable",
            PEND.resp,
            [["", "Cualquier responsable"], ...(AJ.yo?.nombre ? [[":yo:", "Asignado a mí"]] : []), ...resps.map(r => [r, r])],
            v => (PEND.resp = v),
          ),
        ]
      : []),
  );
  const fila = p => {
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
        pintarPendPag();
        hechoDeshacer(p.c, p, pintarPendPag);
      }),
    });
    return el(
      "tr",
      { className: "f" },
      el("td", {}, chk),
      el("td", { className: "pt" }, p.texto, " ", ...(p.mid ? [fLink(p)] : [])),
      el("td", { className: "pc" }, el("a", { href: "#/p/" + enc(p.c) + "/pendientes", textContent: p.c || sinC() })),
      el("td", { className: "pr", textContent: p.resp || "" }),
      el("td", { className: "pp" }, p.vencido ? el("b", { className: "err", textContent: "Vencido" }) : p.plazo || (p.fecha ? fFecha(p.fecha) : "Sin fecha")),
    );
  };
  const grupos = PEND_G.map(([k, t]) => [t, its.filter(p => pendG(p) === k)]).filter(g => g[1].length);
  w.replaceChildren(
    bar,
    ...(its.length
      ? [
          el(
            "div",
            { className: "tabla pend-t" },
            el(
              "table",
              {},
              el(
                "thead",
                {},
                el("tr", {}, ...["Hecho", "Pendiente", cap(nm("carpeta")), "Responsable", "Plazo"].map(t => el("th", { scope: "col", textContent: t }))),
              ),
              ...grupos.map(([t, l]) =>
                el("tbody", {}, el("tr", { className: "grp" }, el("th", { colSpan: 5, scope: "colgroup", textContent: t + " · " + l.length })), ...l.map(fila)),
              ),
            ),
          ),
        ]
      : [el("p", { className: "vacio", textContent: "Nada coincide con los filtros." })]),
  );
  escalona(w);
}

// ---------- Proyecto: «Auto: …», Automático, ⋯ Más, aprobar todo, importar Excel/CSV, .zip, añadir a proyecto ----------
const QUE_T = {
  documento: "documento",
  resumen: "resumen",
  tareas: "tareas",
  decisiones: "decisiones",
  requisitos: "requisitos",
  historias: "historias",
  riesgos: "riesgos",
  interesados: "interesados",
  informe: "informe",
};
const DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"];
async function recetasTxt(c) {
  const [rs, ns] = await Promise.all([api("/api/recetas?c=" + enc(c)).catch(() => []), nombresDst()]);
  const sal = r =>
    (r.plan?.salidas || (r.presets || []).map(p => ({ preset: p })))
      .map(
        s => (s.que ? QUE_T[s.que] || s.que : "") + " → " + (s.como === "documento" ? "documento" : ns["p:" + s.preset] || ns["d:" + s.destino] || "destino"),
      )
      .join(" · ");
  return rs.map(r => ({
    r,
    txt:
      (r.cuando?.tipo === "al_asignar"
        ? "al asignar: "
        : r.cuando?.tipo === "programado"
          ? "cada " +
            ({ dia: "día", semana: DIAS[r.cuando.dia_semana || 0], mes: "mes" }[r.cuando.cada] || "") +
            (r.cuando.hora ? " " + r.cuando.hora : "") +
            ": "
          : "") + (sal(r) || r.nombre),
  }));
}
async function fAutoLinea(c) {
  const l = (await recetasTxt(c)).filter(x => x.r.activa);
  if (fuC !== c) return;
  $("f-auto").hidden = !l.length;
  $("f-auto").textContent = "Auto: " + l.map(x => x.txt).join(" · ");
  $("f-auto").onclick = () => {
    fScrollA = "f-auto-card";
    fIr("ajustes");
  };
}
function fAuto(c) {
  // Proyecto › Ajustes › Automático: sus recetas (al terminar y programadas) + el plan por defecto de Añadir
  const lista = el("ul", { className: "list" }),
    plan = el("div");
  const carga = async () => {
    const l = await recetasTxt(c);
    lista.replaceChildren(
      ...(l.length
        ? l.map(({ r, txt }) => {
            const sw = el("input", {
              type: "checkbox",
              checked: !!r.activa,
              ariaLabel: "Activa: " + (r.nombre || txt),
              onchange: fallo(async () => {
                await api("/api/recetas/" + r.id, {
                  method: "PATCH",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ activa: sw.checked }),
                });
                fAutoLinea(c);
              }),
            });
            return el(
              "li",
              {},
              el(
                "label",
                { className: "check" },
                sw,
                el(
                  "span",
                  {},
                  el("b", { textContent: r.nombre || "Receta" }),
                  el("small", {
                    textContent: txt + (r.proximo_iso ? " · próximo: " + r.proximo_iso.replace("T", " ") : "") + (r.atrasado ? " · atrasado" : ""),
                  }),
                ),
              ),
              el("span", { className: "grow" }),
              el("button", {
                className: "sec sm",
                textContent: "Enviar ahora",
                onclick: fallo(async () => {
                  await post("/api/recetas/" + r.id + "/ahora");
                  aviso("Enviado");
                }),
              }),
              el("button", {
                className: "sec sm dng",
                textContent: "Quitar",
                onclick: fallo(async () => {
                  await api("/api/recetas/" + r.id, { method: "DELETE" });
                  carga();
                  fAutoLinea(c);
                  aviso("Receta «" + (r.nombre || txt) + "» quitada", {
                    txt: "Deshacer",
                    fn: fallo(async () => {
                      const { id, ...x } = r;
                      await post("/api/recetas", x);
                      carga();
                      fAutoLinea(c);
                    }),
                  });
                }),
              }),
            );
          })
        : [el("li", { className: "muted", textContent: "Sin recetas: nada se envía solo desde este " + nm("carpeta").toLowerCase() + "." })]),
    );
  };
  carga();
  if (window.Enviar)
    api("/api/carpetas/" + enc(c) + "/plan_defecto")
      .then(p => Enviar.checklist(plan, { plan: p, carpeta: c, onChange: () => {} }))
      .catch(() => {});
  return el(
    "div",
    { className: "card", id: "f-auto-card" },
    H(
      "Automático",
      el("button", {
        className: "link",
        textContent: "Recargar",
        onclick: () => {
          carga();
          fAutoLinea(c);
        },
      }),
    ),
    el("p", {
      className: "muted",
      textContent:
        "Lo que se envía solo al terminar cada documento de este " +
        nm("carpeta").toLowerCase() +
        " o de forma programada. Al añadir aquí, estas casillas ya vienen marcadas.",
    }),
    lista,
    ...(window.Enviar
      ? [el("h3", { textContent: "Nueva receta" }), plan]
      : [el("p", { className: "muted", textContent: "El módulo de envío no está disponible." })]),
  );
}
async function fAprobarTodo(c) {
  const ids = (await api("/api/reg?" + new URLSearchParams({ c, revision: "propuesto" }))).items.map(x => x.id);
  if (!ids.length) return aviso("No hay nada por revisar");
  await post("/api/reg/revisar", { c, ids, accion: "aprobar" });
  INI.p = null;
  aviso(ids.length + " aprobados", {
    txt: "Deshacer",
    fn: fallo(async () => {
      await post("/api/reg/deshacer", { c });
      fsucio = true;
      pintarHome();
    }),
  });
  fsucio = true;
  pintarHome();
}
async function deshacerPasada(c) {
  const u = (await Promise.all(["poblar", "derivar"].map(k => api("/api/reg/" + k + "/estado?c=" + enc(c)).catch(() => ({})))))
    .map(x => x.ultimo)
    .filter(x => x && x.lote)
    .sort((x, y) => y.t - x.t)[0];
  if (!u) return aviso("No hay ninguna pasada de IA que deshacer");
  if (!confirm("¿Deshacer la última pasada de IA (" + new Date(u.t * 1000).toLocaleString("es") + ")? Se quitan los elementos que propuso y no has tocado."))
    return;
  const r = await post("/api/reg/deshacer-pasada", { c, lote: u.lote });
  aviso("Pasada deshecha (" + (r.revertidas ?? r.revertida ?? 0) + ")");
  fsucio = true;
  pintarHome();
}
function regImportar(c, vista) {
  const inp = el("input", { type: "file", accept: ".xlsx,.csv", hidden: true });
  document.body.append(inp);
  inp.onchange = fallo(async () => {
    const f = inp.files[0];
    inp.remove();
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    fd.append("c", c);
    if (fImportable(vista)) fd.append("vista", vista);
    importarPrevia(c, await api("/api/reg/importar/previa", { method: "POST", body: fd }));
  });
  inp.click();
}
function importarPrevia(c, r) {
  const { d, b, f } = dialogo(
    "Importar " + (r.vista || "") + " desde Excel/CSV",
    "Vista previa: nada cambia hasta que pulses Aplicar. Nunca se borra nada y se puede deshacer.",
  );
  const sel = new Set([...r.nuevos.map(x => String(x.fila)), ...r.modificados.map(x => String(x.id))]);
  const chk = k => el("input", { type: "checkbox", checked: true, onchange: e => (e.target.checked ? sel.add(k) : sel.delete(k)) });
  b.append(
    el("p", {
      className: "muted",
      textContent:
        "Columnas reconocidas: " +
        (r.columnas_reconocidas || []).join(", ") +
        ((r.columnas_ignoradas || []).length ? " · ignoradas: " + r.columnas_ignoradas.join(", ") : "") +
        " · sin cambios: " +
        (r.iguales ?? 0),
    }),
    ...(r.nuevos.length
      ? [
          el("h3", { textContent: "Nuevos · " + r.nuevos.length }),
          el(
            "ul",
            { className: "imp-l" },
            ...r.nuevos.map(x =>
              el(
                "li",
                {},
                el(
                  "label",
                  { className: "check" },
                  chk(String(x.fila)),
                  el("span", {}, el("b", { textContent: x.titulo }), el("small", { textContent: "Fila " + x.fila })),
                ),
              ),
            ),
          ),
        ]
      : []),
    ...(r.modificados.length
      ? [
          el("h3", { textContent: "Modificados · " + r.modificados.length }),
          el(
            "ul",
            { className: "imp-l" },
            ...r.modificados.map(x =>
              el(
                "li",
                {},
                el(
                  "label",
                  { className: "check" },
                  chk(String(x.id)),
                  el(
                    "span",
                    {},
                    el("b", { textContent: (x.codigo || x.id) + " · fila " + x.fila }),
                    ...Object.entries(x.cambios).map(([k, [a, z]]) => el("small", {}, k + ": ", el("s", { textContent: a ?? "—" }), " → " + (z ?? "—"))),
                  ),
                ),
              ),
            ),
          ),
        ]
      : []),
    ...(r.desconocidas.length
      ? [
          el("h3", { textContent: "Filas que no se importan · " + r.desconocidas.length }),
          el("ul", { className: "imp-l" }, ...r.desconocidas.map(x => el("li", { textContent: "Fila " + x.fila + ": " + x.motivo }))),
        ]
      : []),
    ...(!r.nuevos.length && !r.modificados.length ? [el("p", { className: "aviso", textContent: "No hay nada nuevo ni cambiado que importar." })] : []),
  );
  const ap = el("button", {
    type: "button",
    className: "pri",
    textContent: "Aplicar",
    disabled: !r.nuevos.length && !r.modificados.length,
    onclick: fallo(async () => {
      ap.disabled = true;
      let x;
      try {
        x = await post("/api/reg/importar/aplicar", { token: r.token, seleccion: [...sel] });
      } catch (e) {
        ap.disabled = false;
        throw e;
      }
      d.close();
      aviso(x.creadas + " nuevos · " + x.modificadas + " modificados", {
        txt: "Deshacer",
        fn: fallo(async () => {
          await post("/api/reg/deshacer", { c });
          fsucio = true;
          pintarHome();
        }),
      });
      fsucio = true;
      pintarHome();
    }),
  });
  f.append(
    el("span"),
    el("div", { className: "row" }, el("button", { type: "button", className: "sec", textContent: "Cancelar", onclick: () => d.close() }), ap),
  );
}
async function importarZip(c) {
  const p = (await post("/api/pick", { tipo: "zip" })).path;
  if (!p) return;
  const m = await post("/api/importar", { path: p, ...(c ? { carpeta: c } : {}) });
  await cargarLista();
  aviso("Documento importado");
  abrir(m.id);
}
function aProyecto(mids) {
  const { d, b, f } = dialogo(
    "Llevar a " + nm("carpeta").toLowerCase(),
    "Sin reprocesar: sus tareas entran tal cual y queda buscable en el " + nm("carpeta").toLowerCase() + ". Marca qué más quieres sacar.",
  );
  if (!carpetas.length) {
    b.append(el("p", { textContent: "Aún no hay ningún " + nm("carpeta").toLowerCase() + ". Créalo desde el menú lateral («Nuevo»)." }));
    return;
  }
  const s = el("select", { id: "ap-c" }, ...carpetas.map(c => new Option(c, c))),
    mv = el("input", { type: "radio", name: "ap-m", checked: true }),
    cp = el("input", { type: "radio", name: "ap-m" }),
    env = el("input", { type: "checkbox" });
  if (carpetas.includes(fsel)) s.value = fsel;
  const suya = mids.length === 1 && (todas.find(m => m.id === mids[0]) || BIB.ms.find(m => m.id === mids[0]))?.carpeta;
  if (suya && carpetas.includes(suya)) s.value = suya; // ya está en un proyecto: por defecto, sacar a ese mismo
  // «Qué sacar»: la IA lee la reunión y propone solo eso (queda en «Por revisar»); nada marcado = como siempre
  const QS = {
    tareas: "Tareas",
    decisiones: "Decisiones",
    riesgos: "Riesgos",
    requisitos: "Requisitos",
    preguntas: "Preguntas abiertas",
    interesados: "Interesados",
    ideas: "Ideas",
    hipotesis: "Hipótesis",
    insights: "Aprendizajes",
  };
  const qs = Object.entries(QS).map(([v, t]) => [v, el("input", { type: "checkbox", value: v })]);
  const nl = el("div"),
    nh = el("div");
  nubeEnlace(nl, nh, "ap", null);
  b.append(
    el("div", { className: "field" }, el("label", { htmlFor: "ap-c", textContent: cap(nm("carpeta")) }), s),
    el(
      "fieldset",
      {},
      el("legend", { textContent: "Cómo" }),
      el("label", { className: "check" }, mv, el("span", { textContent: "Mover" })),
      el("label", { className: "check" }, cp, el("span", { textContent: "Copiar (sigue también donde está)" })),
    ),
    el(
      "fieldset",
      {},
      el("legend", { textContent: "Qué sacar al " + nm("carpeta").toLowerCase() }),
      ...qs.map(([v, i]) => el("label", { className: "check" }, i, el("span", { textContent: QS[v] }))),
      el("small", { className: "muted", textContent: "Con IA: en este equipo puede tardar; en la nube va más rápido." }),
      nl,
      nh,
    ),
    el("label", { className: "check" }, env, el("span", { textContent: "Enviar también según las recetas del " + nm("carpeta").toLowerCase() })),
  );
  const ok = el("button", {
    type: "button",
    className: "pri",
    textContent: "Llevar",
    onclick: fallo(async () => {
      const antes = mids.map(id => [id, (todas.find(m => m.id === id) || BIB.ms.find(m => m.id === id))?.carpeta || ""]);
      const vistas = qs.filter(([, i]) => i.checked).map(([v]) => v);
      const nube = vistas.length ? nubeParams("ap") : null;
      if (nube && !(await nubeOk("ap"))) return;
      ok.disabled = true;
      let r;
      try {
        r = await post("/api/doc/a-proyecto", {
          mids,
          c: s.value,
          modo: cp.checked ? "copiar" : "mover",
          enviar: env.checked,
          ...(vistas.length ? { vistas } : {}),
          ...(nube ? { nube } : {}),
        });
      } catch (e) {
        ok.disabled = false;
        throw e;
      }
      d.close();
      BIB.sel.clear();
      await cargarLista();
      sondear();
      if (vistaAct === "bib") pintarBib();
      const txt = "Añadido a " + s.value + (r.poblando?.length ? " · extrayendo sus elementos" : "");
      // deshacer = devolver cada documento a su carpeta (lo ya incorporado al proyecto se revisa allí); las copias no se deshacen desde aquí
      if (cp.checked) aviso(txt);
      else
        aviso(txt, {
          txt: "Deshacer",
          fn: fallo(async () => {
            for (const [id, c] of antes) await post("/api/meta", { id, carpeta: c });
            await cargarLista();
            if (vistaAct === "bib") pintarBib();
            else if (vistaAct === "home") pintarHome();
          }),
        });
    }),
  });
  f.append(
    el("span"),
    el("div", { className: "row" }, el("button", { type: "button", className: "sec", textContent: "Cancelar", onclick: () => d.close() }), ok),
  );
}
const proyAcc = () => [
  ["Línea de tiempo", () => fIr("linea")],
  ["Comparar documentos", () => fIr("comparar")],
  [
    "Glosario",
    () => {
      fScrollA = "f-glos";
      fIr("ajustes");
    },
  ],
  ["Regenerar con IA", () => fEnCola("/api/reg/poblar", { c: fuC })],
  ["Derivar historias de requisitos", () => fEnCola("/api/reg/derivar", { c: fuC })],
  ["Deshacer la última pasada IA", () => deshacerPasada(fuC)],
  ["Importar desde Excel/CSV", () => regImportar(fuC, ftab)],
  ["Importar .zip de Actas", () => importarZip(fuC)],
  ["Descargar…", () => (window.Descargar ? Descargar.abrir({ c: fuC }) : sinEnviar())],
  [
    "Automático (envíos)",
    () => {
      fScrollA = "f-auto-card";
      fIr("ajustes");
    },
  ],
  ["Ajustes del " + nm("carpeta").toLowerCase(), () => fIr("ajustes")],
];
$("f-mas-l").prepend(
  ...proyAcc().map(([t, f]) => el("button", { type: "button", role: "menuitem", textContent: t, onclick: fallo(async () => f()) })),
  el("div", { className: "sep", role: "separator" }),
);
$("f-env").onclick = () => (window.Enviar ? Enviar.enviar({ c: fuC }) : sinEnviar());

// ---------- paleta Ctrl+K: navegación + todas las acciones (también las escondidas) + búsqueda ----------
function palCmds() {
  const C = (g, t, f, i) => ({ g, t, f, i }),
    go = h => () => {
      location.hash = h;
    },
    clk = id => () => $(id).click(),
    vis = id => !$(id).hidden;
  const L = [];
  if (vistaAct === "res" && cur?.solo)
    L.push(
      C("Documento", "Resumir y extraer", clk("d-resumir")),
      C("Documento", "Ver la fuente", () => tab("p-video")),
      C("Documento", "Preguntar", () => tab("p-preg")),
      C("Documento", "Descargar…", clk("d-desc")),
      C("Documento", "Renombrar", clk("m-ren")),
      C("Documento", "Mover", clk("m-mover")),
      C("Documento", "Añadir a " + nm("carpeta").toLowerCase() + "…", clk("d-aproy")),
    );
  else if (vistaAct === "res" && cur) {
    const a = cur.actas.find(x => x.name === ver);
    L.push(
      C("Documento", "Preguntar", () => tab("p-preg")),
      C("Documento", "Ver resumen", () => tab("p-acta")),
      C("Documento", "Ver lo extraído", () => tab("p-ext")),
      C("Documento", "Ver la fuente", () => tab("p-video")),
      C("Documento", $("d-env").textContent, clk("d-env")),
      C("Documento", "Enviar a…", clk("d-env-m")),
      ...FMT.map(([f, t]) => C("Exportar", t, () => exportar(f))),
      C("Documento", "Descargar…", clk("d-desc")),
      C("Documento", "Editar el texto", clk("d-editar")),
      C("Documento", "Renombrar", clk("m-ren")),
      C("Documento", "Mover", clk("m-mover")),
      C("Documento", "Añadir a " + nm("carpeta").toLowerCase() + "…", clk("d-aproy")),
      C("Documento", "Anonimizar…", clk("d-anon")),
      C("Documento", "Borrador de correo", clk("d-correo")),
      ...(cur.video ? [C("Documento", (cur.audio ? "Audio" : "Vídeo") + " condensado", clk("d-cond"))] : []),
      ...(vis("fondo") ? [C("Documento", $("fondo").textContent, clk("fondo"))] : []),
      ...(vis("dl-zip") ? [C("Documento", "Descargar (.zip)", clk("dl-zip"))] : []),
      ...(vis("dl-vid") ? [C("Documento", $("dl-vid").textContent, clk("dl-vid"))] : []),
      C("Documento", "Otra versión…", clk("d-otra")),
      C("Documento", "Renombrar versión", clk("d-vren")),
      C("Documento", "Dudas: siguiente frase dudosa", clk("d-dud")),
      ...(vis("d-rest") ? [C("Documento", "Restaurar original", clk("d-rest"))] : []),
      ...(a?.sin ? [] : []),
    );
  }
  if (vistaAct === "home" && fsel) {
    L.push(
      ...FTOP.filter(([k]) => k !== "extraido").map(([k, t]) => C(fsel, t, () => fIr(k))),
      C(fsel, "Por revisar", () => fIr("revision")),
      ...FEXT.map(([k, t]) => C(fsel, "Extraído · " + t, () => fIr(k))),
      C(fsel, "Aprobar todo lo pendiente de revisar", () => fAprobarTodo(fsel)),
      ...proyAcc().map(([t, f]) => C(fsel, t, f)),
      C(fsel, "Enviar " + nm("carpeta").toLowerCase(), clk("f-env")),
      C(fsel, "Añadir documento aquí", () => formNuevo()),
      C(fsel, "Renombrar " + nm("carpeta").toLowerCase(), clk("f-ren")),
      C(fsel, "Quitar " + nm("carpeta").toLowerCase(), clk("f-quitar")),
    );
  }
  L.push(
    C("Acción", "Añadir archivos, enlace o captura", () => formNuevo()),
    C("Acción", "Buscar o preguntar", () => {
      if ($("omni-b").offsetParent) $("omni-b").click();
      else $("buscar").focus();
    }),
    C("Acción", "Elegir archivos…", () => {
      formNuevo();
      $("an-file").click();
    }),
    C("Acción", "Pegar captura", anPegar),
    C("Acción", "Grabar reunión", () => grabarAbrir()),
    C("Acción", "Importar documento exportado (.zip)", () => $("b-importar").click()),
    C("Acción", "Nuevo " + nm("carpeta").toLowerCase(), () => {
      irInicio();
      nuevaCarpeta();
    }),
    C("Acción", "Asistente: ¿para qué usas la app?", () => abrirUso(false)),
    C("Vista", simple() ? "Cambiar a modo avanzado" : "Cambiar a modo simple", () => guardarAj({ modo: simple() ? "avanzado" : "simple" })),
    C("Vista", "Contraer o mostrar el menú lateral", railToggle),
    C("Ajustes", "Carpetas vigiladas", () => ajIr("general", "aj-vig"), "ojo"),
    C("Ajustes", "Conectar con otras herramientas de IA (MCP)", () => ajIr("avanzado", "aj-mcp"), "enlace"),
    C("Ir a", "Inicio", go("#/")),
    C("Ir a", "Biblioteca", go("#/biblioteca")),
    C("Ir a", "Pendientes", go("#/pendientes")),
    C("Ir a", "Enviar: destinos, recetas e historial", go("#/enviar")),
    C("Ir a", "Cola de trabajos", go("#/cola")),
    ...[
      ["general", "General", "aj"],
      ["modelos", "Modelos", "cpu"],
      ["plantillas", "Plantillas", "plant"],
      ["enviar", "Enviar", "env"],
      ["avanzado", "Avanzado y perfiles de uso", "sli"],
    ].map(([k, t, i]) => C("Ajustes", t, () => abrirAjustes(k), i)),
    ...carpetas.map(c => ({ ...C(cap(pl(nm("carpeta"))), c, go("#/p/" + enc(c))), i: "proy" })),
    ...todas.slice(0, 60).map(m => ({ ...C("Documentos", m.label, () => abrir(m.id)), i: "doc" })),
  );
  return L;
}
// icono por tipo de acción (no por grupo): el primero que encaje; los documentos y proyectos de la lista llevan el suyo
const PAL_I = [
  [/^Añadir archivos/, "mas"],
  [/^Elegir archivos/, "subir"],
  [/^Pegar/, "clip"],
  [/^Grabar|condensado/, "mic"],
  [/Importar|Descargar|^Exportar|\(\.zip\)/, "bajar"],
  [/^Asistente|Resumir|^Dudas/, "ia"],
  [/modo (simple|avanzado)/, "modo"],
  [/menú lateral/, "vista"],
  [/^Enviar|Borrador de correo/, "env"],
  [/^Preguntar/, "preg"],
  [/^Editar|^Renombrar|Anonimizar/, "editar"],
  [/^Mover|^Añadir a |^Quitar |^Nuevo /, "proy"],
  [/^Cola/, "cola"],
  [/^Buscar/, "buscar"],
  [/^Pendientes|Aprobar|revisar/i, "pend"],
  [/^Biblioteca/, "bib"],
  [/^Inicio/, "inicio"],
  [/^Resumen|^Ver resumen/, "cola"],
  [/^Informe/, "informe"],
  [/fuente/, "ojo"],
  [/extraído/i, "plant"],
  [/^Ver /, "doc"],
];
const palIco = c => c.i || (c.g === "Ajustes" ? "aj" : c.g === "Exportar" ? "bajar" : PAL_I.find(([r]) => r.test(c.t))?.[1] || "doc");
function paleta() {
  if (document.querySelector("dialog.pal")) return;
  const cmds = palCmds(),
    d = el("dialog", { className: "pal", ariaLabel: "Paleta de comandos" }),
    ul = el("ul", { id: "pal-l", role: "listbox", ariaLabel: "Resultados" });
  const q = el("input", {
    type: "search",
    id: "pal-q",
    placeholder: "Acción, " + nm("carpeta").toLowerCase() + ", documento o búsqueda…",
    ariaLabel: "Comando",
    role: "combobox",
    "aria-controls": "pal-l",
    "aria-expanded": "true",
    "aria-autocomplete": "list",
  });
  let sel = 0,
    vis = [];
  const key = c => c.g + "|" + c.t,
    SC = { "Añadir archivos, enlace o captura": "N", "Pegar captura": "Ctrl V", "Buscar o preguntar": "/" },
    MAX = 4,
    mas = new Set(); // sin texto: 4 por grupo + «Ver más»
  const run = c => {
    if (c.mas) {
      mas.add(c.mas);
      sel = vis.indexOf(c);
      pint(true);
      return;
    }
    if (c.g !== "Buscar") lsSet("pal.rec", [key(c), ...lsGet("pal.rec", []).filter(k => k !== key(c))].slice(0, 5));
    d.close();
    setTimeout(() => fallo(async () => c.f())(), 0);
  };
  const pint = sc => {
    // sc: solo con teclado se desplaza hasta la fila elegida (con el ratón la lista no salta)
    const t = norm(q.value).trim(),
      w = t.split(/\s+/),
      gs = new Map();
    const add = (g, c) => {
      if (!gs.has(g)) gs.set(g, []);
      gs.get(g).push(c);
    };
    if (!t) {
      // «Recientes» primero: lo último usado en la paleta; la primera vez, los últimos documentos
      const h = lsGet("pal.rec", [])
        .map(k => cmds.find(c => key(c) === k))
        .filter(Boolean);
      (h.length ? h : cmds.filter(c => c.i === "doc").slice(0, 3)).forEach(c => add("Recientes", c));
    }
    const rec = new Set(gs.get("Recientes") || []);
    for (const c of cmds) if ((!t || w.every(x => norm(c.g + " " + c.t).includes(x))) && !rec.has(c)) add(c.g, c);
    if (q.value.trim())
      add("Buscar", {
        g: "Buscar",
        t: "Buscar «" + q.value.trim() + "»",
        f: () => {
          $("buscar").value = q.value.trim();
          $("omni").requestSubmit();
        },
        i: "buscar",
      });
    vis = [];
    const rows = [];
    for (const [g, l] of gs) {
      const tope = t ? 12 : g === "Recientes" ? 5 : MAX,
        ver = mas.has(g) ? l : l.slice(0, tope);
      rows.push(el("li", { role: "presentation", className: "pal-h", textContent: g }));
      for (const c of ver) {
        rows.push(c);
        vis.push(c);
      }
      if (ver.length < l.length) {
        const c = { g, t: "Ver " + (l.length - ver.length) + " más", mas: g };
        rows.push(c);
        vis.push(c);
      }
    }
    sel = Math.max(0, Math.min(sel, vis.length - 1));
    let i = 0;
    ul.replaceChildren(
      ...rows.map(c => {
        if (c instanceof Node) return c;
        const n = i++;
        return el(
          "li",
          {
            role: "option",
            id: "pal-" + n,
            className: c.mas ? "pal-mas" : "",
            "aria-selected": n === sel,
            onclick: () => run(c),
            onmousemove: () => {
              if (sel !== n) {
                sel = n;
                pint();
              }
            },
          },
          c.mas ? el("span", { className: "ri", "aria-hidden": "true" }) : ico(palIco(c)),
          el("span", { className: "pal-t", textContent: c.t }),
          ...(SC[c.t] ? [el("kbd", { className: "kbd", textContent: SC[c.t] })] : []),
        );
      }),
    );
    if (!vis.length) ul.replaceChildren(el("li", { className: "muted pal-0", role: "presentation", textContent: "Nada coincide. Prueba con otra palabra." }));
    ul.style.maxHeight = ""; // la lista acaba en el borde de una fila (+14 px de fundido): nunca una fila a medias bajo la barra de atajos
    if (ul.scrollHeight > ul.clientHeight) {
      const y = li => li.offsetTop - ul.offsetTop + li.offsetHeight,
        f = [...ul.children].filter(li => y(li) <= ul.clientHeight - 14 && !li.matches(".pal-h")).pop();
      if (f) ul.style.maxHeight = y(f) + 14 + "px";
    } // offset* y no getBoundingClientRect (la animación de entrada del diálogo lo escala); sin cabecera de grupo huérfana al final
    q.setAttribute("aria-activedescendant", vis.length ? "pal-" + sel : "");
    if (sc) $("pal-" + sel)?.scrollIntoView({ block: "nearest" });
  };
  q.oninput = () => {
    sel = 0;
    pint(true);
  };
  q.onkeydown = e => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      sel = (sel + (e.key === "ArrowDown" ? 1 : -1) + vis.length) % Math.max(vis.length, 1);
      pint(true);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (vis[sel]) run(vis[sel]);
    }
  };
  d.append(
    q,
    ul,
    el(
      "p",
      { className: "pal-n muted" },
      el("kbd", { className: "kbd", textContent: "↑↓" }),
      " elegir · ",
      el("kbd", { className: "kbd", textContent: "Intro" }),
      " ejecutar · ",
      el("kbd", { className: "kbd", textContent: "Esc" }),
      " cerrar · escribe para ver todo",
    ),
  );
  d.onclose = () => d.remove();
  document.body.append(d);
  d.showModal();
  pint();
}

// ---------- Ajustes › General: carpetas vigiladas · Ajustes › Avanzado: MCP ----------
const jsonH = { "Content-Type": "application/json" };
function ajVigiladas() {
  const lista = el("ul", { className: "list" }),
    hace = t => {
      const s = Math.round(Date.now() / 1000 - t);
      return s < 90 ? "hace " + s + " s" : s < 5400 ? "hace " + Math.round(s / 60) + " min" : new Date(t * 1000).toLocaleString("es");
    };
  const carga = async () => {
    const l = await api("/api/vigiladas").catch(() => []);
    lista.replaceChildren(
      ...(l.length
        ? l.map(v => {
            const e = v.estado || {},
              sw = el("input", {
                type: "checkbox",
                checked: !!v.activa,
                ariaLabel: "Activa: " + v.ruta,
                onchange: fallo(async () => {
                  await api("/api/vigiladas/" + v.id, { method: "PATCH", headers: jsonH, body: JSON.stringify({ activa: sw.checked }) });
                  carga();
                }),
              });
            return el(
              "li",
              {},
              el(
                "label",
                { className: "check" },
                sw,
                el(
                  "span",
                  {},
                  el("b", { textContent: v.ruta }),
                  el("small", {
                    className: e.error ? "err" : "",
                    textContent: [
                      "→ " + (v.carpeta || sinC()),
                      v.recursivo && "con subcarpetas",
                      v.mover && "mueve a Procesados/",
                      e.error || (e.ultima ? "Última revisión " + hace(e.ultima) : "Sin revisar aún"),
                      e.encoladas ? e.encoladas + " en cola" : "",
                    ]
                      .filter(Boolean)
                      .join(" · "),
                  }),
                ),
              ),
              el("span", { className: "grow" }),
              el("button", {
                className: "sec sm",
                textContent: "Revisar ahora",
                onclick: fallo(async () => {
                  await post("/api/vigiladas/" + v.id + "/revisar");
                  carga();
                  sondear();
                }),
              }),
              el("button", {
                className: "sec sm dng",
                textContent: "Quitar",
                onclick: fallo(async () => {
                  await api("/api/vigiladas/" + v.id, { method: "DELETE" });
                  carga();
                  aviso("Ya no se vigila " + v.ruta + " (no se borra nada)", {
                    txt: "Deshacer",
                    fn: fallo(async () => {
                      await post("/api/vigiladas", {
                        ruta: v.ruta,
                        carpeta: v.carpeta || "",
                        recursivo: !!v.recursivo,
                        mover: !!v.mover,
                        activa: !!v.activa,
                        ...(v.plan ? { plan: v.plan } : {}),
                      });
                      carga();
                    }),
                  });
                }),
              }),
            );
          })
        : [el("li", { className: "muted", textContent: "Ninguna todavía." })]),
    );
  };
  const rt = el("input", { id: "vg-r", required: true, placeholder: "C:\\Users\\…\\OneDrive\\Grabaciones" }),
    c = el("select", { id: "vg-c" }, new Option(sinC(), ""), ...carpetas.map(x => new Option(x, x)));
  const rec = el("input", { type: "checkbox" }),
    mov = el("input", { type: "checkbox" }),
    chk = el("div");
  let plan = null;
  c.onchange = () => {
    plan = null;
    if (window.Enviar && c.value)
      Enviar.checklist(chk, {
        plan: { carpeta: c.value, salidas: [] },
        carpeta: c.value,
        onChange: p => {
          plan = p;
        },
      });
    else chk.replaceChildren();
  };
  const f = el(
    "form",
    { className: "vg-add" },
    el("h3", { textContent: "Vigilar una carpeta" }),
    el(
      "div",
      { className: "cols" },
      el("div", { className: "field" }, el("label", { htmlFor: "vg-r", textContent: "Ruta de la carpeta" }), rt),
      el("div", { className: "field" }, el("label", { htmlFor: "vg-c", textContent: "Añadir a" }), c),
    ),
    el("label", { className: "check" }, rec, el("span", { textContent: "Incluir subcarpetas" })),
    el("label", { className: "check" }, mov, el("span", { textContent: "Mover lo procesado a «Procesados/»" })),
    chk,
    el("button", { className: "pri", textContent: "Vigilar esta carpeta" }),
  );
  f.onsubmit = fallo(async e => {
    e.preventDefault();
    await post("/api/vigiladas", {
      ruta: rt.value.trim(),
      carpeta: c.value,
      recursivo: rec.checked,
      mover: mov.checked,
      activa: true,
      ...(plan?.salidas?.length ? { plan } : {}),
    });
    rt.value = "";
    carga();
    aviso("Carpeta vigilada");
  });
  carga();
  return el(
    "section",
    { className: "card", id: "aj-vig" },
    el("h2", { textContent: "Carpetas vigiladas" }),
    el("p", {
      className: "muted",
      textContent: "Lo que caiga en estas carpetas entra solo en la cola. Ideal para la carpeta de OneDrive donde caen las grabaciones de Teams.",
    }),
    lista,
    f,
  );
}
function ajMcp() {
  const cuerpo = el("div");
  const pinta = async () => {
    const [a, cf] = await Promise.all([api("/api/mcp/ajustes"), api("/api/mcp/config")]),
      set = async b => {
        await post("/api/mcp/ajustes", b);
        await pinta();
      };
    const copia = (t, txt) =>
      el(
        "div",
        { className: "field" },
        el(
          "div",
          { className: "row" },
          el("b", { textContent: t }),
          el("span", { className: "grow" }),
          el("button", {
            type: "button",
            className: "sec sm",
            textContent: "Copiar",
            onclick: fallo(async () => {
              await navigator.clipboard.writeText(txt);
              aviso("Copiado");
            }),
          }),
        ),
        el("pre", { className: "fu-ocr", textContent: txt }),
      );
    const h = Object.entries(cf.http?.headers || {})
      .map(([k, v]) => k + ": " + v)
      .join("\n");
    cuerpo.replaceChildren(
      chk2("Activar el servidor MCP", !!a.activo, v => set({ activo: v })),
      chk2("Pedir token (recomendado)", !!a.token_requerido, v => set({ token_requerido: v })),
      chk2("Permitir que añadan trabajos a la cola", !!a.permitir_encolar, v => set({ permitir_encolar: v }), "Pueden encolar archivos; nunca borrar."),
      ...(a.activo
        ? [
            copia("Claude Desktop (claude_desktop_config.json)", cf.claude_desktop),
            copia("Claude Code", cf.claude_code),
            copia("HTTP (otras herramientas)", cf.http.url + (h ? "\n" + h : "")),
            ...(a.token_requerido
              ? [el("button", { type: "button", className: "sec sm", textContent: "Regenerar token", onclick: fallo(() => set({ regenerar_token: true })) })]
              : []),
          ]
        : []),
    );
  };
  pinta().catch(x => cuerpo.replaceChildren(el("p", { className: "muted", textContent: x.message })));
  return el(
    "section",
    { className: "card", id: "aj-mcp" },
    el("h2", { textContent: "Conectar con otras herramientas de IA (MCP)" }),
    el("p", {
      className: "aviso w",
      textContent:
        "Las herramientas conectadas (Claude Desktop, Copilot, Cursor…) pueden enviar a la nube lo que reciben. Con «Anonimizar por defecto» activo, Actas no les entrega contenido.",
    }),
    cuerpo,
  );
}
const ajIr = (t, id) => {
  abrirAjustes(t);
  setTimeout(() => $(id)?.scrollIntoView({ block: "start" }), 300);
};

// ---------- arranque: la ruta del enlace (#/…) ----------
rutaIr().finally(() => {
  rutaLista = true;
});
