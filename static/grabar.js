// ---- Grabar reunión (sin bot) y notas con el minuto: design/Grabar.dc.html ----
const LEGAL = "Aviso: esta reunión se está grabando para elaborar el acta. Si no estás de acuerdo, dilo ahora o abandona la llamada.";
const MEDIA_RE = /\.(mp4|mkv|webm|mov|m4v|avi|mp3|m4a|wav|ogg|opus|flac|aac)$/i;
const PN = {act: null};  // panel de notas con atajos activos

// Panel de notas reutilizable (grabación en vivo, vídeo de un documento, vídeo aún sin procesar).
// c: {notas, botones(): [{nombre, seccion, atajo}], tiempo(): s, add(nota): Promise<notas>, save(notas): Promise<notas>, seek?(t), dur?()}
function panelNotas(host, c) {
  let notas = c.notas || [];
  const ta = el("textarea", {rows: 3, placeholder: "Escribe una nota… (se guarda con el minuto actual)", ariaLabel: "Escribe una nota"});
  const btns = el("div", {className: "nbtns"}), lista = el("ol", {className: "notas"}), tl = el("div", {className: "ntl", hidden: true});
  const err = e => aviso(e.message);
  const poner = async (n, p) => { try { notas = await p; pinta(); } catch (e) { err(e); } };
  const marca = b => poner(b, c.add({texto: "", boton: b.nombre || "", seccion: b.seccion || null}));
  const botones = c.botones();
  btns.append(el("button", {type: "button", className: "sec", textContent: "Marcar momento", onclick: () => marca({nombre: "", seccion: null})}),
    ...botones.map(b => el("button", {type: "button", className: "sec", title: b.atajo, onclick: () => marca(b)}, "+ " + b.nombre + " ", b.atajo ? el("kbd", {textContent: b.atajo}) : "")));
  const anota = () => { const t = ta.value.trim(); if (!t) return; ta.value = ""; poner(null, c.add({texto: t, boton: "", seccion: null})); };
  ta.onkeydown = e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); anota(); } };
  const fila = (n, i) => {
    const li = el("li"), m = el("button", {type: "button", className: "m", textContent: mmss(n.t), title: c.seek ? "Ir a este momento" : "", onclick: () => c.seek && c.seek(n.t)});
    const ver = () => {
      li.replaceChildren(m, el("span", {className: "x"}, ...(n.boton ? [el("span", {className: "badge", textContent: n.boton})] : []), n.texto || "Momento marcado"),
        el("button", {type: "button", className: "sec sm", textContent: "Editar", onclick: edit}));
    };
    const edit = () => {
      const mi = el("input", {value: mmss(n.t), size: 6, ariaLabel: "Minuto (mm:ss)"}), ti = el("input", {value: n.texto, className: "grow", ariaLabel: "Texto de la nota", placeholder: "Texto (opcional)"});
      const guardar = () => {
        const p = mi.value.split(":").map(Number).reverse(), t = p.reduce((s, v, k) => s + (v || 0) * 60 ** k, 0);
        poner(null, c.save(notas.map((x, k) => k === i ? {...x, t: isFinite(t) ? t : x.t, texto: ti.value.trim()} : x)));
      };
      li.replaceChildren(mi, ti, el("button", {type: "button", className: "pri sm", textContent: "Guardar", onclick: guardar}),
        el("button", {type: "button", className: "sec sm dng", textContent: "Borrar", onclick: () => poner(null, c.save(notas.filter((_, k) => k !== i)))}));
      ti.focus();
    };
    ver(); return li;
  };
  function pinta() {
    lista.replaceChildren(...notas.map(fila).reverse());
    const d = c.dur && c.dur(); tl.hidden = !(d > 0);
    tl.replaceChildren(...(d > 0 ? notas.map(n => el("button", {type: "button", title: mmss(n.t) + " " + (n.texto || n.boton), style: `left:${Math.min(100, n.t / d * 100)}%`, onclick: () => c.seek && c.seek(n.t), ariaLabel: "Nota en " + mmss(n.t)})) : []));
  }
  host.append(tl, btns, ta, el("div", {className: "row", style: "margin-top:8px"}, el("button", {type: "button", className: "pri sm", textContent: "Añadir nota", onclick: anota}), el("small", {textContent: "Ctrl+Intro añade · lo marcado entra siempre en el documento"})), lista);
  pinta();
  const p = {botones, anota, ta, set: n => { notas = n; pinta(); }, repinta: pinta};
  host.addEventListener("focusin", () => PN.act = p);
  PN.act = p;
  return p;
}
// atajos: el que define el perfil («Ctrl+1»…) y, como alternativa (los navegadores se quedan Ctrl+1…9), Alt+1…9 por orden
addEventListener("keydown", e => {
  const p = PN.act; if (!p || !p.ta.isConnected || p.ta.offsetParent === null) return;
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "n") { e.preventDefault(); p.ta.focus(); return; }
  const k = e.key.length === 1 ? e.key.toUpperCase() : e.key;
  const i = p.botones.findIndex((b, j) => { const a = (b.atajo || "").split("+").map(s => s.trim().toLowerCase()); const tecla = a.pop();
    return tecla && tecla === k.toLowerCase() && a.includes("ctrl") === e.ctrlKey && a.includes("alt") === e.altKey && a.includes("shift") === e.shiftKey || e.altKey && !e.ctrlKey && k === String(j + 1); });
  if (i >= 0) { e.preventDefault(); [...p.ta.closest("section,div.card,#p-notas")?.querySelectorAll(".nbtns button") || []][i + 1]?.click(); }
});
const botonesDe = id => (PL.find(p => p.id === (id || "acta")) || PL[0] || {}).notas_rapidas || [];

// ---------- vídeo de un documento ----------
async function notasRes() {
  const h = $("p-notas"); if (!cur || h.dataset.id === cur.id + ver) return;
  h.dataset.id = cur.id + ver;
  h.replaceChildren(el("h2", {textContent: "Notas"}), el("p", {className: "muted", textContent: cur.video ? "Marca momentos mientras ves la grabación. Entran en el documento la próxima vez que lo generes (nueva versión)." : "Este documento no tiene vídeo ni audio: no hay minutos que marcar."}));
  if (!cur.video) return;
  const id = cur.id, put = n => api("/api/notas", {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({id, notas: n})});
  let notas = await api("/api/notas?id=" + encodeURIComponent(id)).catch(() => []);
  const p = panelNotas(h, {notas, botones: () => botonesDe(), tiempo: () => VID().currentTime || 0, dur: () => VID().duration, seek: t => mpSeek(t, cur.video, cur.m.label),
    save: async n => notas = await put(n), add: async n => notas = await put([...notas, {...n, t: VID().currentTime || 0}])});
  VID().addEventListener("loadedmetadata", () => p.repinta(), {once: true});
}

// ---------- vídeo aún sin procesar (formulario «Nuevo») ----------
async function notasForm(ruta) {
  const h = $("n-notas"); h.hidden = !ruta || !MEDIA_RE.test(ruta); h.replaceChildren();
  if (h.hidden) return;
  const v = el("video", {className: "rec-prev", controls: true, preload: "metadata", src: "/api/previa?video=" + encodeURIComponent(ruta)});
  const put = n => api("/api/notas", {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({video: ruta, notas: n})});
  let notas = await api("/api/notas?video=" + encodeURIComponent(ruta)).catch(() => []);
  h.append(el("h2", {textContent: "Notas del vídeo (opcional)"}), el("p", {className: "muted", textContent: "Marca momentos viéndolo: lo marcado entra siempre en el documento."}), v);
  const p = panelNotas(h, {notas, botones: () => botonesDe($("plantilla").value), tiempo: () => v.currentTime || 0, dur: () => v.duration, seek: t => { v.currentTime = t; v.play().catch(() => {}); },
    save: async n => notas = await put(n), add: async n => notas = await put([...notas, {...n, t: v.currentTime || 0}])});
  v.addEventListener("loadedmetadata", () => p.repinta(), {once: true});
}

// ---------- grabar en vivo ----------
const grabarEl = $("v-grabar");
const copiarTxt = async t => { try { await navigator.clipboard.writeText(t); aviso("Texto copiado"); } catch { aviso("No se pudo copiar: selecciona el texto"); } };
const legal = () => el("div", {className: "legal"}, el("b", {textContent: "Informa a los participantes de que se está grabando. "}), "En muchos casos necesitas su consentimiento.",
  el("br"), el("em", {textContent: LEGAL}), el("br"), el("button", {type: "button", className: "sec sm", textContent: "Copiar texto para el chat de la llamada", onclick: () => copiarTxt(LEGAL)}));
const medidor = (nombre, disp, id) => el("div", {}, el("div", {className: "meter-l"}, el("span", {textContent: nombre}), el("span", {id: id + "-d", textContent: disp})),
  el("div", {className: "meter", role: "meter", "aria-label": "Nivel " + nombre, "aria-valuenow": "0", "aria-valuemin": "0", "aria-valuemax": "100", id: id}, el("i")));
const opts = (sel, l, v) => { sel.replaceChildren(...l); if (v !== undefined) sel.value = v; return sel; };

async function grabarAbrir() {
  vista("grabar"); grabarEl.replaceChildren(el("p", {className: "muted", textContent: "Cargando…"}));
  try {
    GR.dev = await api("/api/grabar/dispositivos"); const e = await api("/api/grabar/estado");
    if (!PL.length) await cargarPlant();
    GR.activa = !!e.activa; GR.est = e.activa; GR.notas = e.notas; GR.cfg = e.cfg;
    GR.activa ? grabando() : preparar(e.recuperables);
  } catch (err) { grabarEl.replaceChildren(el("p", {className: "err", textContent: err.message})); }
}

function preparar(rec) {
  const d = GR.dev, n = (t, ...k) => el("div", {className: "field"}, el("label", {textContent: t}), ...k);
  const mic = opts(el("select", {ariaLabel: "Micrófono"}), d.mics.map(m => new Option(m.name, m.id)), d.mic);
  const sis = opts(el("select", {ariaLabel: "Audio del sistema"}), [new Option("Ninguno (solo micrófono)", ""), ...d.sistemas.map(m => new Option(m.name, m.id))], d.sistema);
  const pan = el("input", {type: "checkbox", disabled: !d.pantalla[0]}), yo = el("input", {value: "Yo"}), otros = el("input", {value: "Otros"}), nom = el("input", {placeholder: "Se llamará «Reunión» y la fecha"});
  const perfil = opts(el("select"), PL.map(p => new Option(p.nombre, p.id)), "acta"), carp = opts(el("select"), [new Option(sinC(), ""), ...carpetas.map(c => new Option(c, c))], typeof fsel === "string" ? fsel : "");
  const cal = opts(el("select"), [...$("calidad").options].map(o => { const x = new Option(o.text, o.value); x.disabled = o.disabled; return x; }), $("calidad").value);
  const ir = el("button", {type: "button", className: "pri", textContent: "● Empezar a grabar", onclick: async () => {
    ir.disabled = true;
    try {
      GR.est = await post("/api/grabar/iniciar", {mic_id: mic.value, sistema_id: sis.value, pantalla: pan.checked, carpeta: carp.value, perfil: perfil.value, calidad: cal.value, nombre: nom.value.trim(),
        nombres: `Hablante 1=${yo.value.trim() || "Yo"}, Hablante 2=${otros.value.trim() || "Otros"}`, gpu: $("usar-gpu").checked});
      GR.activa = true; GR.notas = []; GR.cfg = (await api("/api/grabar/estado")).cfg; pintarSide(); grabando();
    } catch (e) { aviso(e.message); ir.disabled = false; }
  }});
  grabarEl.replaceChildren(el("a", {className: "back", href: "#", textContent: "← Inicio", onclick: e => { e.preventDefault(); irInicio(); }}),
    el("div", {className: "head"}, el("h1", {textContent: "Grabar reunión"}), el("p", {className: "muted", textContent: "Sin bots: se graba tu micrófono («Yo») y el audio del sistema («Otros») por separado, así se sabe quién habla. Todo se queda en este equipo."})),
    ...(d.error ? [el("p", {className: "err", textContent: d.error})] : []),
    el("section", {className: "card"}, el("h2", {textContent: "Fuentes"}), n("Yo · micrófono", mic), n("Otros · audio del sistema", sis),
      ...(d.aviso ? [el("small", {textContent: d.aviso})] : []),
      el("label", {className: "check"}, pan, el("span", {}, "Grabar también la pantalla", ...(d.pantalla[1] ? [el("small", {textContent: d.pantalla[1]})] : []))),
      el("label", {className: "check"}, el("input", {type: "checkbox", disabled: true}), el("span", {}, "Transcribir mientras graba", el("small", {textContent: "Próximamente: de momento se transcribe al parar."}))),
      el("small", {textContent: "Se guarda por tramos de unos minutos: si algo falla no se pierde lo grabado."})),
    el("section", {className: "card"}, el("h2", {textContent: "Documento"}), n("Perfil", perfil), n(cap(nm("carpeta")), carp), n("Calidad", cal), n("Nombre", nom),
      el("div", {className: "row wrap", style: "align-items:flex-start"}, el("div", {className: "field grow"}, el("label", {textContent: "Nombre de tu voz"}), yo), el("div", {className: "field grow"}, el("label", {textContent: "Nombre de los demás"}), otros))),
    legal(), el("div", {className: "row", style: "margin:16px 0"}, ir),
    ...(rec.length ? [el("section", {className: "card"}, el("h2", {textContent: "Recuperar grabación"}), el("p", {className: "muted", textContent: "Grabaciones que no se cerraron (la aplicación se cerró o falló). Lo grabado hasta entonces está a salvo."}),
      el("ul", {className: "list"}, ...rec.map(r => el("li", {}, el("span", {className: "n", textContent: new Date(r.inicio * 1000).toLocaleString("es") + " · " + mmss(r.dur) + (r.notas ? " · " + r.notas + " notas" : "")}),
        el("button", {type: "button", className: "pri sm", textContent: "Recuperar y generar", onclick: async e => { e.target.disabled = true; try { await post("/api/grabar/recuperar", {id: r.id}); vista("cola"); sondear(); } catch (x) { aviso(x.message); e.target.disabled = false; } }}),
        el("button", {type: "button", className: "sec sm dng", textContent: "Descartar", onclick: async () => { if (confirm("¿Descartar esta grabación?")) { await post("/api/grabar/recuperar", {id: r.id, descartar: true}); grabarAbrir(); } }})))))] : []));
}

let grabarT = 0;
function grabando() {
  const c = GR.cfg || {}, dev = n => (GR.dev[n + "s"] || []).find(x => x.id === c[n + "_id"]);
  const t = el("span", {className: "t", id: "rec-t", textContent: "00:00"}), st = el("span", {className: "muted", id: "rec-s"}), dot = el("span", {className: "dot", id: "rec-dot", "aria-hidden": "true"});
  const pausa = el("button", {type: "button", className: "sec", id: "rec-p", textContent: "Pausar", onclick: async () => { GR.est = await post("/api/grabar/pausa", {pausa: GR.est.estado !== "pausada"}); pinta(); }});
  const parar = el("button", {type: "button", className: "pri dng", id: "rec-x", textContent: "Parar y generar", onclick: async () => {
    if (!confirm("¿Parar la grabación y generar el documento?")) return;
    parar.disabled = pausa.disabled = true; parar.textContent = "Cerrando la grabación…";
    try { await post("/api/grabar/parar", {}); GR.activa = false; clearInterval(grabarT); pintarSide(); vista("cola"); sondear(); }
    catch (e) { aviso(e.message); parar.disabled = pausa.disabled = false; parar.textContent = "Parar y generar"; }
  }});
  const notas = el("section", {className: "card"});
  notas.append(el("div", {className: "row wrap"}, el("h2", {textContent: "Notas", style: "margin:0"}), el("span", {className: "grow"}), el("small", {textContent: "Ctrl+N nota nueva · lo marcado entra siempre en el documento"})));
  const pn = panelNotas(notas, {notas: GR.notas, botones: () => botonesDe(c.perfil), tiempo: () => GR.est.elapsed,
    add: n => api("/api/grabar/nota", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(n)}),
    save: n => api("/api/grabar/notas", {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({notas: n})})});
  const pc = el("input", {type: "checkbox", disabled: true, checked: false});
  grabarEl.replaceChildren(el("div", {className: "rec-h"}, el("div", {className: "row"}, dot, t, st), el("div", {className: "row"}, pausa, parar)),
    el("div", {className: "rec-g"}, el("aside", {}, el("section", {className: "card"}, el("h2", {textContent: "Fuentes"}),
      medidor("Yo · micrófono", (dev("mic") || {}).name || "", "m-mic"), el("div", {style: "height:14px"}), medidor("Otros · audio del sistema", (dev("sistema") || {}).name || "ninguno", "m-sis"),
      el("p", {id: "rec-i", className: "muted", style: "margin:14px 0 0"}), el("p", {id: "rec-e", className: "err"}),
      el("small", {textContent: "Se guarda por tramos: si algo falla no se pierde lo grabado."})), legal()), notas));
  function pinta() {
    const e = GR.est, p = e.estado === "pausada", seg = e.elapsed + (p ? 0 : (Date.now() - e.recibido) / 1000);
    t.textContent = new Date(seg * 1000).toISOString().slice(seg >= 3600 ? 11 : 14, 19); dot.classList.toggle("p", p);
    st.textContent = (p ? "En pausa" : "Grabando") + (c.carpeta ? " · [" + c.carpeta + "]" : "") + (c.nombre ? " · " + c.nombre : ""); pausa.textContent = p ? "Reanudar" : "Pausar";
    for (const [k, id] of [["mic", "m-mic"], ["sistema", "m-sis"]]) { const m = $(id); if (m) { m.setAttribute("aria-valuenow", p ? 0 : e.nivel[k]); m.firstChild.style.width = (p ? 0 : e.nivel[k]) + "%"; } }
    $("rec-i").textContent = (e.size / 1e6).toFixed(1).replace(".", ",") + " MB" + (e.pantalla ? " · con pantalla" : "");
    $("rec-e").textContent = Object.entries(e.err || {}).map(([k, v]) => (k === "mic" ? "Micrófono: " : "Audio del sistema: ") + v).join(" · ");
  }
  GR.est.recibido = Date.now(); pinta(); clearInterval(grabarT);
  grabarT = setInterval(async () => {
    if (vistaAct !== "grabar") return;
    try { const e = await api("/api/grabar/estado"); if (!e.activa) { clearInterval(grabarT); GR.activa = false; return; } GR.est = {...e.activa, recibido: Date.now()}; pinta(); } catch {}
  }, 500);
}
// la página se abre con una grabación en marcha (se cerró la pestaña) o con grabaciones sin cerrar
api("/api/grabar/estado").then(e => { GR.activa = !!e.activa; if (e.activa) grabarAbrir(); else if (e.recuperables.length) aviso("Hay una grabación sin cerrar: Grabar reunión › Recuperar grabación"); }).catch(() => {});
{ const h = $("n-grabar"); h.hidden = false; h.append(el("button", {type: "button", className: "sec grab", onclick: () => grabarAbrir()}, el("span", {className: "ring", ariaHidden: "true"}, el("i")), el("b", {textContent: "Grabar ahora"}), el("small", {textContent: "Micro + audio del sistema"}))); }
