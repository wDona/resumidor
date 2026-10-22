// Anonimizar, borrador de correo y marcas de dudas del documento. Usa los globales de app.js (cur, ver, el, $, api, post, aviso, fallo, descargar, FMT) y AJ (ajustes.js).
let anonSel = null;  // casilla «Anonimizar» del menú Exportar (null = lo que diga el ajuste)
const anonOn = () => anonSel ?? !!AJ.anonimizar_defecto;
const TIPOS = {persona: "Nombre de persona", email: "Email", telefono: "Teléfono", dni: "DNI / NIE", iban: "IBAN", tarjeta: "Tarjeta", matricula: "Matrícula", otro: "Añadido a mano"};

function dialogo(titulo, sub, cls = "") {
  const d = el("dialog", {className: "gr " + cls}), b = el("div", {className: "dg-b"}), f = el("div", {className: "dg-f"});
  d.append(el("div", {className: "dg-h"}, el("div", {}, el("h2", {textContent: titulo}), el("div", {className: "muted", textContent: sub})),
    el("button", {type: "button", className: "sec qi", ariaLabel: "Cerrar", textContent: "×", onclick: () => d.close()})), b, f);
  d.onclose = () => d.remove(); document.body.append(d); d.showModal();
  return {d, b, f};
}
// espera con aviso: si el modelo local está ocupado con otro trabajo, lo dice (/api/aux) en vez de parecer colgado
function esperando(msg) {
  const t = el("span", {textContent: msg}), box = el("div", {className: "esp", role: "status"}, el("i", {className: "spin"}), t);
  const iv = setInterval(async () => { const a = await api("/api/aux").catch(() => null); if (a) t.textContent = a.estado === "esperando" ? "En cola: hay un trabajo en marcha; esto empezará cuando termine." : msg; }, 1500);
  box.stop = () => clearInterval(iv); return box;
}

// ---- exportar (con o sin anonimizar) ----
async function exportar(fmt, extra = "") {
  const dud = $("ex-dud")?.checked ? "&dudas=1" : "";
  if (!anonOn()) return descargar(fmt, extra + dud + "&anon=0");
  const e = await api(`/api/anonimizar/${cur.id}/${ver}`);
  if (e.existe && !e.obsoleta) return descargar(fmt, extra + dud + "&anon=1");
  abrirAnon({fmt, extra: extra + dud, obsoleta: e.existe});
}
function zipAnon() {  // una exportación anonimizada nunca lleva vídeo ni audio (ni el zip del original)
  const on = anonOn();
  for (const a of [$("dl-zip"), $("dl-vid")]) {
    a.setAttribute("aria-disabled", on); a.classList.toggle("off", on);
    a.title = on ? "No disponible con «Anonimizar»: no incluye vídeo, audio ni el documento original" : a.id === "dl-vid" ? "Documento y vídeo en un zip: las marcas de tiempo saltan al momento sin internet" : "";
    a.onclick = on ? e => e.preventDefault() : null;
  }
}

function abrirAnon(p) {
  const {d, b, f} = dialogo("Revisar antes de exportar anonimizado", "Se crea una copia. El documento original no cambia.", "anon");
  const url = `/api/anonimizar/${cur.id}/${ver}`;
  let its = [], res = null;
  const cancel = el("button", {type: "button", className: "sec", textContent: "Cancelar", onclick: () => d.close()}), ok = el("button", {type: "button", className: "pri", disabled: true});
  ok.textContent = !p ? "Aplicar anonimización" : p.obsoleta ? "Volver a anonimizar y exportar" : "Exportar " + fmtNombre(p.fmt) + " anonimizado";
  f.append(p ? el("button", {type: "button", className: "link dng", textContent: "Exportar sin anonimizar", onclick: fallo(async () => { d.close(); await descargar(p.fmt, p.extra + "&anon=0"); })}) : el("span"), el("div", {className: "row"}, cancel, ok));
  const esp = esperando("Buscando datos personales en el documento…"); b.append(...(p?.obsoleta ? [el("div", {className: "aviso w", textContent: "La copia anonimizada está obsoleta: el documento cambió después de crearla. Vuelve a anonimizarla."})] : []), esp);
  post(url + "/detectar", {}).then(r => {
    esp.stop(); esp.remove(); if (!d.open) return;
    its = r.items.map(i => ({...i, incluir: true}));  // privacidad: mejor ocultar de más (la IA marcada) que olvidar a una persona
    const tabla = el("div", {className: "tbl"}), cnt = el("div", {className: "b"}), lado = el("div", {className: "dg-s"});
    const pintar = () => {
      const gr = [...new Set(its.map(i => i.tipo))];  // agrupados por tipo, con su columna (design/Anonimizar.dc.html)
      tabla.replaceChildren(el("table", {}, el("thead", {}, el("tr", {}, el("th", {className: "w-chk"}, el("span", {className: "sr", textContent: "Ocultar"})), el("th", {textContent: "Encontrado"}), el("th", {textContent: "Tipo"}), el("th", {textContent: "Se sustituye por"}))),
        el("tbody", {}, ...gr.flatMap(t => its.filter(i => i.tipo === t)).map(i => el("tr", {className: i.ia ? "ia" : ""},
          el("td", {}, el("input", {type: "checkbox", checked: i.incluir, ariaLabel: "Ocultar", onchange: e => { i.incluir = e.target.checked; cuenta(); }})),
          el("td", {}, i.manual ? el("input", {type: "text", value: i.valor, placeholder: "Texto exacto a ocultar", ariaLabel: "Texto a ocultar", oninput: e => { i.valor = e.target.value; }}) : el("span", {}, el("b", {textContent: i.valor}),
            el("span", {className: "muted", textContent: ` · ${i.n} ${i.n === 1 ? "vez" : "veces"}`}), ...(i.ejemplos?.[0] ? [el("small", {textContent: "…" + i.ejemplos[0] + "…"})] : []))),
          el("td", {className: "tipo", textContent: i.ia ? "Posible nombre (IA)" : TIPOS[i.tipo] || i.tipo}),
          el("td", {}, el("input", {type: "text", value: i.sugerido, ariaLabel: "Seudónimo", oninput: e => { i.sugerido = e.target.value; }})))))));
      if (!its.length) tabla.replaceChildren(el("p", {className: "vacio", textContent: "No se encontró nada que ocultar. Añade a mano lo que falte."}));
      cuenta();
    };
    const cuenta = () => { const n = its.filter(i => i.incluir).length; cnt.textContent = `Se va a ocultar · ${n} ${n === 1 ? "elemento" : "elementos"}`; ok.disabled = false; };
    lado.append(el("div", {className: "b", textContent: "Capturas"}), el("div", {className: "nota", textContent: r.capturas_sin_cajas.length
      ? `${r.capturas_sin_cajas.length} captura(s) sin cajas del OCR (transcripción anterior): si contienen datos marcados se omitirán de la copia.` : "Las capturas con datos marcados se difuminan por zonas; si no se pueden localizar, se omiten."}),
      el("div", {className: "nota"}, el("div", {textContent: "Sin vídeo ni audio: una exportación anonimizada nunca los incluye."}), el("div", {textContent: "La detección no es perfecta. Revisa la lista antes de compartir."})));
    b.append(...(r.sin_modelo ? [el("div", {className: "aviso w", textContent: "No hay modelo instalado para buscar nombres: solo se detectan datos con formato (DNI, IBAN…) y los nombres del propio documento. Añade a mano los demás."})] : []),
      el("div", {className: "dg-g"}, el("div", {className: "dg-m"}, el("div", {className: "row wrap entre"}, cnt,
        el("button", {type: "button", className: "sec sm", textContent: "+ Añadir texto", onclick: () => { its.push({tipo: "otro", valor: "", n: 0, ejemplos: [], sugerido: "[OCULTO]", incluir: true, manual: true}); pintar(); tabla.querySelector("tr:last-child input[type=text]")?.focus(); }})), tabla), lado));
    pintar();
  }).catch(err => { esp.stop(); esp.remove(); b.append(el("p", {className: "err", textContent: err.message})); });
  ok.onclick = fallo(async () => {
    ok.disabled = cancel.disabled = true; ok.textContent = "Anonimizando…";
    try {
      res = await post(url + "/aplicar", {items: its.filter(i => i.valor.trim()).map(({tipo, valor, sugerido, incluir}) => ({tipo, valor, sugerido, incluir}))});
    } catch (err) { ok.disabled = cancel.disabled = false; ok.textContent = "Reintentar"; throw err; }
    if (!d.open) return;
    if (p && !res.omitidas.length) { d.close(); aviso(`Anonimizado: ${res.reemplazos} cambios, ${res.difuminadas} zonas difuminadas`); await descargar(p.fmt, p.extra + "&anon=1"); return; }
    b.replaceChildren(el("p", {}, el("b", {textContent: "Copia anonimizada creada. "}), `${res.reemplazos} textos cambiados, ${res.difuminadas} zonas difuminadas.`),
      ...(res.omitidas.length ? [el("div", {className: "aviso w"}, el("b", {textContent: `${res.omitidas.length} captura(s) omitida(s) de la copia:`}), el("ul", {}, ...res.omitidas.map(o => el("li", {textContent: `${o.img}: ${o.motivo}`})))) ] : []));
    f.replaceChildren(el("span"), el("div", {className: "row"}, el("button", {type: "button", className: "sec", textContent: p ? "Cancelar" : "Cerrar", onclick: () => d.close()}),
      ...(p ? [el("button", {type: "button", className: "pri", textContent: "Exportar " + fmtNombre(p.fmt) + " anonimizado", onclick: fallo(async () => { d.close(); await descargar(p.fmt, p.extra + "&anon=1"); })})] : [])));
  });
}
const fmtNombre = f => FMT.find(x => x[0] === f)?.[1] || f;

// ---- borrador de correo ----
function abrirCorreo() {
  const {d, b, f} = dialogo("Borrador de correo", "Resumen y tareas listos para pegar en tu programa de correo. No se envía nada.", "correo");
  const sel = (id, ops, v) => { const s = el("select", {id}); for (const [k, t] of ops) s.append(new Option(t, k)); s.value = v; return s; };
  const modo = sel("co-modo", [["todos", "Un correo para todos"], ["responsable", "Uno por responsable"]], "todos"), tono = sel("co-tono", [["formal", "Formal"], ["cercano", "Cercano"], ["breve", "Breve"]], "formal"),
    idi = sel("co-idi", [["es", "Español"], ["en", "English"]], "es"), pdf = el("input", {type: "checkbox"}), an = el("input", {type: "checkbox", checked: anonOn()}), out = el("div", {className: "co-out"});
  const go = el("button", {type: "button", className: "pri", textContent: "Generar borrador"}), fl = (t, c) => el("div", {className: "field"}, el("label", {htmlFor: c.id, textContent: t}), c);
  b.append(el("div", {className: "cols"}, fl("Destinatarios", modo), fl("Tono", tono)), el("div", {className: "cols"}, fl("Idioma", idi), el("div", {}, el("label", {className: "check"}, pdf, "Adjuntar el documento en PDF"),
    el("label", {className: "check"}, an, "Anonimizar (usa la copia anonimizada)"))), out);
  f.append(el("span"), el("div", {className: "row"}, el("button", {type: "button", className: "sec", textContent: "Cerrar", onclick: () => d.close()}), go));
  go.onclick = fallo(async () => {
    go.disabled = true; const esp = esperando("Redactando el borrador…"); out.replaceChildren(esp);
    try {
      if (an.checked) { const e = await api(`/api/anonimizar/${cur.id}/${ver}`); if (!e.existe || e.obsoleta) { esp.stop(); out.replaceChildren(el("div", {className: "aviso w"}, e.existe ? "La copia anonimizada está obsoleta. " : "Aún no hay copia anonimizada. ",
        el("button", {type: "button", className: "link", textContent: e.existe ? "Volver a anonimizar" : "Anonimizar ahora", onclick: () => { d.close(); abrirAnon(null); }}))); return; } }
      const r = await post(`/api/correo/${cur.id}/${ver}`, {modo: modo.value, tono: tono.value, idioma: idi.value, adjuntar_pdf: pdf.checked, anon: an.checked});
      esp.stop(); if (!d.open) return;
      out.replaceChildren(...(r.aviso ? [el("div", {className: "aviso w", textContent: r.aviso})] : []), ...(r.llm ? [] : [el("small", {textContent: "Apertura y cierre de plantilla (sin modelo local)."})]), ...r.correos.map(c => el("div", {className: "co"},
        el("div", {className: "row wrap entre"}, el("div", {}, el("b", {textContent: "Para: " + c.para}), el("div", {className: "muted", textContent: c.asunto})), el("div", {className: "row"},
          el("button", {type: "button", className: "sec sm", textContent: "Copiar", onclick: fallo(async function () { await copiar(c); this.textContent = "Copiado"; setTimeout(() => this.textContent = "Copiar", 1800); })}),
          el("a", {className: "btn sec sm", href: c.eml_url, download: "", textContent: "Descargar .eml"}))), el("pre", {textContent: c.texto}))));
    } catch (err) { esp.stop(); out.replaceChildren(el("p", {className: "err", textContent: err.message})); } finally { go.disabled = false; }
  });
}
async function copiar(c) {  // texto + HTML: al pegar en un cliente de correo conserva títulos y listas
  const blob = (t, m) => new Blob([t], {type: m});
  if (navigator.clipboard?.write && window.ClipboardItem) await navigator.clipboard.write([new ClipboardItem({"text/plain": blob(c.texto, "text/plain"), "text/html": blob(c.html, "text/html")})]);
  else await navigator.clipboard.writeText(c.texto);
}

// ---- confianza: partes dudosas resaltadas en el documento ----
let dudIx = -1;
const dudMarcas = () => { try { return [...$("acta-frame").contentDocument.querySelectorAll(".dd")]; } catch { return []; } };
async function pintarDudas() {
  const bar = $("dud-bar"), fr = $("acta-frame"); bar.hidden = true; dudIx = -1;
  let d; try { d = fr.contentDocument; } catch { return; } if (!d?.body || editando || !cur || d.location.href === "about:blank") return;
  const mid = cur.id, v = ver, r = await api(`/api/dudas/${mid}/${v}`).catch(() => null);
  if (!r || mid !== cur.id || v !== ver || fr.contentDocument !== d) return;
  if (!d.getElementById("dd-css")) d.head.append(Object.assign(d.createElement("style"), {id: "dd-css", textContent: ".dd{background:#fde68a;color:inherit;border-radius:3px;cursor:help;padding:0 2px;position:relative}.dd.on{outline:2px solid #d4a514}" +
    ".dd:hover::after,.dd.on::after{content:attr(data-tip);position:absolute;left:0;top:calc(100% + 6px);z-index:5;width:max-content;max-width:min(360px,80vw);background:#1f2933;color:#fff;font:13px/1.4 system-ui,sans-serif;padding:8px 12px;border-radius:8px;white-space:normal;pointer-events:none}" +
    ".dd-off .dd{background:none;padding:0;cursor:auto}.dd-off .dd::after{display:none}"}));
  for (const e of d.querySelectorAll("[data-p]")) { const m = r.dudas[e.dataset.p]; if (m?.length) { e.classList.add("dd"); e.dataset.tip = m.join(". "); } }
  const n = dudMarcas().length; if (!n) return;
  bar.hidden = false; $("dud-n").textContent = `${n} ${n === 1 ? "fragmento dudoso" : "fragmentos dudosos"}`; $("dud-r").textContent = ""; aplicarDudas();
}
function aplicarDudas() {
  const on = $("dud-ver").checked; lsSet("dudas", on);
  try { $("acta-frame").contentDocument.body.classList.toggle("dd-off", !on); } catch {}
  $("dud-ant").disabled = $("dud-sig").disabled = !on;
}
function saltaDuda(k) {
  const m = dudMarcas(); if (!m.length) return; m.forEach(e => e.classList.remove("on"));
  dudIx = (dudIx + k + m.length) % m.length; const e = m[dudIx]; e.classList.add("on"); e.scrollIntoView({block: "center", behavior: "smooth"});
  $("dud-r").textContent = `${dudIx + 1} de ${m.length}: ${e.dataset.tip}`;
}
$("dud-ver").checked = lsGet("dudas", true); $("dud-ver").onchange = aplicarDudas; $("dud-ant").onclick = () => saltaDuda(-1); $("dud-sig").onclick = () => saltaDuda(1);
{ const prev = $("acta-frame").onload; $("acta-frame").onload = function (e) { prev?.call(this, e); pintarDudas(); }; }
