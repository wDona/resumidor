// Embudo de ideas (docs/plan-equipos.md, B3): tablero por fases, puntuación ICE (o RICE, en el propio tablero) y un voto por persona.
// Sustituye a la tabla genérica de la pestaña «Ideas» (FVISTAS de carpeta.js); «Ver como tabla» vuelve a ella.
const EMB_FASES = [
  ["nueva", "Ideas"],
  ["en evaluación", "En evaluación"],
  ["en experimento", "En experimento"],
  ["escalada", "Escaladas"],
  ["descartada", "Descartadas"],
];
const EMB_EJES = {
  ice: [
    ["impacto", "Impacto"],
    ["confianza", "Confianza"],
    ["facilidad", "Facilidad"],
  ],
  rice: [
    ["alcance", "Alcance"],
    ["impacto", "Impacto"],
    ["confianza", "Confianza"],
    ["esfuerzo", "Esfuerzo"],
  ],
};
// misma fórmula que export_registro.puntuacion
function embPunt(k, modo) {
  const n = x => {
    const v = parseFloat(String(k[x] ?? "").replace(",", "."));
    return isNaN(v) ? null : Math.max(0, v);
  };
  const [al, im, co, fa, es] = ["alcance", "impacto", "confianza", "facilidad", "esfuerzo"].map(n);
  if (modo === "rice") return al == null || im == null || co == null || !es ? null : Math.round((al * im * co * 10) / es) / 10;
  return im == null || co == null || fa == null ? null : Math.round(im * co * fa * 10) / 10;
}
const embVotos = k => Object.keys(k).filter(x => x.startsWith("voto:") && k[x]);
// B4: lo parecido en todos los proyectos (embeddings de serie, sin LLM) -> «parecida a X (proyecto Y, descartada el …: porque)»
const embParecidas = async id =>
  (await api("/api/reg/parecidas?" + regQ({ id }))).map(
    p => `${p.codigo} «${p.titulo}» (${p.carpeta}, ${p.estado || "sin estado"}${p.fecha ? " el " + p.fecha : ""})${p.porque ? ": " + p.porque : ""}`,
  );
const embPatch = (c, id, cambios) =>
  api("/api/reg/" + encodeURIComponent(id), { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ c, cambios }) });

FVISTAS.ideas = async (c, e) => {
  if (lsGet("emb-vista", "embudo") === "tabla") {
    const w = el("div");
    registroTabla(w, { c, tipo: "idea", onChange: () => fCargaReg(c, e.tipo), foco: fTomaFoco("ideas") });
    return [
      el(
        "div",
        { className: "row" },
        el("button", { className: "link", textContent: "Ver como embudo", onclick: () => (lsSet("emb-vista", "embudo"), fRe()) }),
      ),
      w,
    ];
  }
  const modo = e.ajustes?.puntuacion === "rice" ? "rice" : "ice";
  const xs = (await api("/api/reg?" + regQ({ c, tipo: "idea" }))).items.filter(x => !["descartado", "fusionado"].includes(x.revision));
  const yo = (AJ.yo?.nombre || "").trim();
  const recarga = async () => {
    await fCargaReg(c, e.tipo);
    fRe();
  };
  const tarjeta = x => {
    const k = x.campos || {},
      p = embPunt(k, modo),
      vs = embVotos(k),
      mio = !!yo && !!k["voto:" + yo];
    const fase = el(
      "select",
      { ariaLabel: "Fase de " + x.titulo, onchange: fallo(async () => (await embPatch(c, x.id, { estado: fase.value }), recarga())) },
      ...EMB_FASES.map(([v, t]) => new Option(t, v)),
    );
    fase.value = EMB_FASES.some(([v]) => v === x.estado) ? x.estado : "nueva";
    const ejes = EMB_EJES[modo].map(([a, t]) => {
      const i = el("input", { type: "number", min: 1, max: 10, step: 1, value: k[a] ?? "", ariaLabel: t + " (1-10) de " + x.titulo });
      i.onchange = fallo(async () => {
        const v = i.value === "" ? null : Math.min(10, Math.max(1, Math.round(+i.value)));
        await embPatch(c, x.id, { campos: { [a]: v } });
        recarga();
      });
      return el("label", { className: "emb-eje" }, el("span", { textContent: t }), i);
    });
    const voto = el("button", {
      className: "sec sm" + (mio ? " on" : ""),
      "aria-pressed": mio,
      title: vs.length ? "Votos: " + vs.map(v => v.slice(5)).join(", ") : "Sin votos",
      textContent: "▲ " + vs.length,
      onclick: fallo(async () => {
        if (!yo) throw new Error("Pon tu nombre en Ajustes › Tú para votar");
        await embPatch(c, x.id, { campos: { ["voto:" + yo]: mio ? null : 1 } });
        recarga();
      }),
    });
    const par = el("ul", { className: "emb-par" });
    const bpar = el("button", {
      className: "link",
      textContent: "¿Ya probamos algo parecido?",
      onclick: fallo(async () => {
        const r = await embParecidas(x.id);
        par.replaceChildren(...(r.length ? r : ["Nada parecido en ningún proyecto."]).map(s => el("li", { textContent: s })));
      }),
    });
    const t = el(
      "article",
      { className: "emb-card", draggable: true, "data-id": x.id },
      el(
        "div",
        { className: "row" },
        el("small", { className: "muted", textContent: x.codigo }),
        el("span", { className: "grow" }),
        el("b", { className: "emb-p", title: modo.toUpperCase(), textContent: p == null ? "—" : String(p) }),
      ),
      el("p", { textContent: x.titulo }),
      ...(k.problema ? [el("small", { className: "muted", textContent: k.problema })] : []),
      el(
        "details",
        {},
        el("summary", { textContent: "Puntuar (" + modo.toUpperCase() + ") y parecidas" }),
        el("div", { className: "emb-ejes" }, ...ejes),
        bpar,
        par,
      ),
      el("div", { className: "row" }, voto, fase),
    );
    t.ondragstart = ev => ev.dataTransfer.setData("text/plain", x.id);
    return t;
  };
  const col = ([v, t]) => {
    const its = xs
      .filter(x => (EMB_FASES.some(([f]) => f === x.estado) ? x.estado : "nueva") === v)
      .sort(
        (a, b) =>
          (embPunt(b.campos || {}, modo) ?? -1) - (embPunt(a.campos || {}, modo) ?? -1) || embVotos(b.campos || {}).length - embVotos(a.campos || {}).length,
      );
    const z = el(
      "section",
      { className: "emb-col", ariaLabel: t },
      el("h3", {}, t, el("span", { className: "muted", textContent: " " + its.length })),
      ...its.map(tarjeta),
    );
    z.ondragover = ev => (ev.preventDefault(), z.classList.add("sobre"));
    z.ondragleave = () => z.classList.remove("sobre");
    z.ondrop = fallo(async ev => {
      ev.preventDefault();
      z.classList.remove("sobre");
      const id = ev.dataTransfer.getData("text/plain");
      if (id && xs.find(x => x.id === id)?.estado !== v) {
        await embPatch(c, id, { estado: v });
        recarga();
      }
    });
    return z;
  };
  const punt = el(
    "select",
    {
      ariaLabel: "Puntuación",
      onchange: fallo(async () => {
        e = await post("/api/exp/ajustes", { c, puntuacion: punt.value });
        fRe();
      }),
    },
    new Option("ICE: impacto × confianza × facilidad", "ice"),
    new Option("RICE: alcance × impacto × confianza ÷ esfuerzo", "rice"),
  );
  punt.value = modo;
  const nueva = fallo(async () => {
    const t = prompt("Nueva idea:");
    if (!t?.trim()) return;
    const x = await post("/api/reg", { c, tipo: "idea", titulo: t.trim(), estado: "nueva", campos: yo ? { autor: yo } : {} });
    await recarga();
    const r = await embParecidas(x.id).catch(() => []);
    if (r.length) aviso("Parecida a " + r[0] + (r.length > 1 ? ` (y ${r.length - 1} más)` : ""));
  });
  return [
    el(
      "div",
      { className: "row wrap emb-barra" },
      el("button", { className: "pri", textContent: "+ Idea", onclick: nueva }),
      regCampo("Puntuación", punt),
      el("span", { className: "grow" }),
      regExportar(c, "ideas", [
        ["xlsx", "Excel (ordenado por puntuación)"],
        ["csv", "CSV"],
        ["md", "Markdown"],
      ]),
      el(
        "a",
        {
          className: "btn sec sm",
          href: "/api/portafolio?fmt=pptx",
          download: "",
          title: "Ideas, experimentos, decisiones y aprendizajes de todos los proyectos",
        },
        "Portafolio (PPTX)",
      ),
      el("a", { className: "link", href: "/api/portafolio?fmt=md", download: "" }, "MD"),
      el("button", { className: "link", textContent: "Ver como tabla", onclick: () => (lsSet("emb-vista", "tabla"), fRe()) }),
    ),
    el("div", { className: "emb" }, ...EMB_FASES.map(col)),
    el("p", { className: "muted", textContent: "Arrastra una idea a otra columna o cambia su fase. Puntúa de 1 a 10; cada persona tiene un voto por idea." }),
  ];
};
