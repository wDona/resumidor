const $ = id => document.getElementById(id);
// 409 {msg, faltan}: falta instalar modelos -> se abre Ajustes › Modelos con el aviso
const det = (j, st) => {
  const d = j.detail;
  if (d && d.faltan) {
    abrirModelos(d.msg, d.faltan);
    return d.msg;
  }
  return d || st;
};
const api = (url, opt) =>
  fetch(url, opt).then(async r => {
    if (r.status === 401 && r.headers.get("content-type")?.includes("json")) {
      const j = await r.json().catch(() => ({}));
      if (j.detail === "Inicia sesión") location.replace("/login.html"); // modo servidor: la sesión caducó
      throw new Error(det(j, r.statusText));
    }
    if (!r.ok) throw new Error(det(await r.json().catch(() => ({})), r.statusText));
    return r.json();
  });
const post = (url, body) => api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
const mmss = t => {
  t = Math.floor(t);
  const h = Math.floor(t / 3600),
    m = Math.floor((t % 3600) / 60),
    s = t % 60,
    p = n => String(n).padStart(2, "0");
  return (h ? h + ":" + p(m) : p(m)) + ":" + p(s);
};
const el = (tag, props = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const k in props) k.startsWith("data-") || k.startsWith("aria-") ? e.setAttribute(k, props[k]) : (e[k] = props[k]);
  e.append(...kids);
  return e;
};
const lsGet = (k, d) => {
  try {
    return JSON.parse(localStorage.getItem(k)) ?? d;
  } catch {
    return d;
  }
};
const lsSet = (k, v) => {
  try {
    localStorage.setItem(k, JSON.stringify(v));
  } catch {}
};
let corriendo = false;
const GR = { activa: false, dev: null, est: null, notas: [], cfg: null }; // grabar.js

let PL = [],
  CP = {},
  DEF = {},
  IDI = {},
  SERIE = {},
  CE = {},
  ESTILOS = []; // plantillas (ver plantillas.js)
addEventListener("beforeunload", e => {
  if (corriendo) {
    e.preventDefault();
    e.returnValue = "Hay trabajos en la cola; si cierras, se cancelarán";
  }
});
setInterval(() => fetch("/api/latido", { method: "POST" }).catch(() => {}), 5000);
fetch("/api/latido", { method: "POST" });

// ---- elegir vídeo y transcripción ----
const INFO_TR = "Sustituye a la transcripción automática; con vídeo se alinea sola. Sin vídeo, el documento no lleva capturas ni reproductor.";
let ruta = "",
  rutaTr = "",
  hablaTr = false;
const setRuta = p => {
  ruta = p;
  $("ruta").value = p;
  typeof notasForm === "function" && notasForm(p);
  typeof nubeForm !== "undefined" && nubeForm.estimar();
};
const setTr = async p => {
  rutaTr = "";
  hablaTr = false;
  $("ruta-tr").value = p;
  $("quitar-tr").hidden = !p;
  try {
    if (p) {
      const r = await post("/api/transcripcion", { path: p });
      rutaTr = p;
      hablaTr = r.hablantes.length > 0;
      $("info-tr").textContent =
        r.formato + " · " + r.segmentos + " segmentos · " + (hablaTr ? r.hablantes.length + " hablantes con nombre" : "sin nombres de hablantes");
    }
  } catch (err) {
    $("ruta-tr").value = "";
    $("quitar-tr").hidden = true;
    $("info-tr").textContent = err.message;
  }
  typeof nubeForm !== "undefined" && nubeForm.estimar();
  $("hablantes").disabled = hablaTr;
  if (hablaTr) $("hablantes").checked = false;
  $("hint-hab").hidden = !hablaTr;
};
$("quitar-tr").onclick = () => {
  setTr("");
  $("info-tr").textContent = INFO_TR;
};
const elegir = (btn, tipo, set) =>
  (btn.onclick = async () => {
    btn.disabled = true;
    try {
      const r = (await post("/api/pick", { tipo })).path;
      if (r) set(r);
    } finally {
      btn.disabled = false;
    }
  });
elegir($("elegir"), "video", p => anAdd(p));
elegir($("elegir-tr"), "transcripcion", setTr);
const soltar = (zona, set, msg) => {
  zona.ondragover = e => {
    e.preventDefault();
    zona.classList.add("over");
  };
  zona.ondragleave = () => zona.classList.remove("over");
  zona.ondrop = async e => {
    e.preventDefault();
    zona.classList.remove("over");
    const f = e.dataTransfer.files[0];
    if (!f) return;
    $(msg).textContent = "Copiando " + f.name + "…";
    try {
      set((await api("/api/upload?name=" + encodeURIComponent(f.name), { method: "PUT", body: f })).path);
      $(msg).textContent = "";
    } catch (err) {
      $(msg).textContent = err.message;
    }
  };
};
soltar($("drop-tr"), setTr, "info-tr"); // la hoja Añadir y toda la ventana aceptan archivos: shell.js

// ---- GPU: autodetectada; la elección manual se recuerda ----
api("/api/gpu")
  .then(g => {
    const c = $("usar-gpu"),
      v = lsGet("usar-gpu", null);
    const gb = g.vram_mb ? `, ${Math.round(g.vram_mb / 1024)} GB de VRAM` : g.igpu ? ", gráfica integrada (usa la RAM del sistema)" : "";
    c.disabled = !g.ok;
    c.checked = g.ok && (v === null ? g.default : v === "1" || v === true);
    $("info-gpu").textContent = !g.ok
      ? "GPU no encontrada o no válida"
      : (g.default ? "Se te recomienda usar la GPU" : "No se te recomienda usar la GPU") + ` (${g.name}${gb})`;
    const chat = () => {
      const [gem, why] = g[c.checked && g.ok ? "chat_gpu" : "chat_cpu"];
      return `Chat: ${gem ? "gemma-4-E4B" : g.llm} (${why})`;
    };
    const ram = () =>
      ($("info-ram").textContent =
        `RAM: ${g.ram_gb || "?"} GB` +
        (g.ok && g.vram_mb
          ? ` · VRAM: ${Math.round(g.vram_mb / 1024)} GB (${g.name})`
          : g.ok && g.igpu
            ? ` · ${g.name}: gráfica integrada (usa la RAM del sistema)`
            : "") +
        " · " +
        chat() +
        (g.ram_gb && g.ram_gb < 8 ? ". Poca RAM: el proceso puede ir muy lento o fallar" : ""));
    ram();
    c.onchange = () => {
      ram();
      lsSet("usar-gpu", c.checked ? "1" : "0");
    };
    niveles(g.niveles);
  })
  .catch(() => {});
let NIV = [];
const GB = b => (b / 1e9).toFixed(1).replace(".", ",") + " GB";
const nivelInfo = q => NIV.find(n => n.id === q);
const ESTADO = { ok: "cómodo", aviso: "lento", no: "no cabe" };
// selector de calidad: el <select> oculto guarda el valor; las tarjetas lo muestran (modelo y si cabe); «no cabe» deshabilitado
function niveles(l) {
  NIV = l;
  const c = $("calidad"),
    v = c.value;
  c.innerHTML = "";
  for (const n of l) c.add(new Option(`${n.nombre} (${n.modelo})`, n.id));
  l.forEach((n, i) => (c.options[i].disabled = n.estado === "no"));
  c.value = l.some(n => n.id === v && n.estado !== "no") ? v : "rápida";
  c.onchange();
}
function pintarCal() {
  $("cal-niv").replaceChildren(
    ...NIV.map(n => {
      const b = el(
        "button",
        {
          type: "button",
          role: "radio",
          className: "chip niv" + (n.instalado ? "" : " sin") + (n.estado === "aviso" ? " lento" : ""),
          "aria-checked": n.id === $("calidad").value,
          "aria-disabled": n.estado === "no",
          onclick: () => {
            if (n.estado === "no") return;
            $("calidad").value = n.id;
            $("calidad").onchange();
          },
        },
        el("b", { textContent: n.nombre }),
        el("small", { textContent: n.modelo + " · " + (!n.instalado ? "sin instalar" : ESTADO[n.estado] || "") }),
      );
      return b;
    }),
  );
}
$("calidad").onchange = () => {
  const n = nivelInfo($("calidad").value);
  pintarCal();
  if (!n) return;
  const t = [
    n.tiempo > 1 && `Tarda aprox. ${n.tiempo}× lo que Rápida`,
    n.estado === "no" && `No cabe en este equipo (necesita ~${Math.ceil(n.necesita)} GB de memoria)`,
    n.estado === "aviso" && "No tienes los recursos recomendados para este modelo, puede tardar más de lo normal",
    n.pers && "Modelo no probado con la app: la calidad del documento puede variar",
  ].filter(Boolean);
  $("aviso-alta").textContent = t.join(". ");
  $("aviso-alta").hidden = !t.length;
  $("bajar-nivel").hidden = n.instalado;
  $("bajar-nivel").textContent = `Descargar ${n.modelo} (${GB(n.bytes)})`;
  $("info-alta").hidden = n.id === "rápida";
};
$("bajar-nivel").onclick = async () => {
  await post("/api/modelos", { ids: [nivelInfo($("calidad").value).m] });
  abrirModelos();
};
const NIVELES_D = ["breve", "normal", "detallado"];
function pintarNivel() {
  $("seg-nivel").replaceChildren(
    ...NIVELES_D.map(n =>
      el("button", {
        type: "button",
        role: "radio",
        textContent: cap(n),
        "aria-checked": $("nivel").value === n,
        "aria-selected": $("nivel").value === n,
        onclick: () => {
          $("nivel").value = n;
          pintarNivel();
        },
      }),
    ),
  );
}

// ---- vistas ----
let qBuscar = "";
let vistaAct = "home";
const VISTAS = ["home", "grabar", "cola", "res", "preg", "ajustes", "uso", "bib", "pend", "enviar", "buscar"];
// «nuevo» es la hoja Añadir (<dialog>): se abre encima de la vista actual
// movimiento (UI-RONDAS.md): animOk() según Ajustes › Apariencia; anima() reinicia una clase de animación CSS y la quita al acabar
const animOk = () => document.documentElement.dataset.anim !== "no";
const anima = (n, cls, ms = 450) => {
  if (!n || !animOk()) return;
  n.classList.remove(cls);
  void n.offsetWidth;
  n.classList.add(cls);
  clearTimeout(n["t_" + cls]);
  n["t_" + cls] = setTimeout(() => n.classList.remove(cls), ms);
};
const ejeX = (n, dir) => dir && anima(n, dir > 0 ? "ax-d" : "ax-i"); // pestañas: entra desde la derecha (dir > 0) o la izquierda
let vistaT = 0; // al entrar en una vista sus listas se escalonan (una vez, no en cada repintado)
const escalona = (n, siempre) => (siempre || performance.now() - vistaT < 1200) && anima(n, "stg", 800);
const sk = (n = 3) => Array.from({ length: n }, (_, i) => el("span", { className: "sk" + (i % 3 === 2 ? " w6" : "") })); // esqueleto: n líneas
// rutas: fade-through con View Transitions (sin ellas, solo la entrada); el estado cambia ya y el pintado va en la transición:
// lo que necesite la vista ya visible (foco, medidas) espera a vistaLista
let vistaLista = Promise.resolve();
function transicion(f) {
  if (!animOk() || document.hidden) return f();
  if (!document.startViewTransition) {
    f();
    return anima(document.querySelector("main"), "m-ft", 260);
  }
  const h = document.documentElement,
    t = document.startViewTransition(f);
  h.classList.add("vt");
  vistaLista = t.updateCallbackDone.catch(() => {});
  t.finished.finally(() => h.classList.remove("vt"));
}
const vista = v => {
  if (v === "nuevo") {
    if (!$("v-nuevo").open) $("v-nuevo").showModal();
    return;
  }
  if ($("v-nuevo").open) $("v-nuevo").close();
  const cambia = v !== vistaAct;
  vistaAct = v;
  const pinta = () => {
    VISTAS.forEach(n => ($("v-" + n).hidden = n !== vistaAct));
    scrollTo(0, 0);
    typeof ubicar === "function" && ubicar();
  };
  if (cambia) {
    vistaT = performance.now();
    transicion(pinta);
  } else pinta();
  document.title = "Actas";
  if (v !== "res" && v !== "preg") mpCerrar();
  typeof rutaSync === "function" && rutaSync();
};
const ir = v => {
  if (v !== vistaAct) vistaT = performance.now();
  if (v === "home") pintarHome();
  vista(v);
};
// aviso(texto, {txt, fn}?): snackbar abajo (capa superior, también sobre diálogos). Con acción («Deshacer») dura 6 s; el ratón o el foco encima lo pausan
const aviso = (t, acc) => {
  let n = $("toast");
  if (!n) {
    n = document.body.appendChild(el("div", { id: "toast", role: "status", "aria-live": "polite" }));
    if (n.showPopover) n.popover = "manual";
    const pausa = () => clearTimeout(aviso.t),
      sigue = () => {
        if (!n.matches(":hover, :focus-within")) avisoT(n, 2500);
      };
    n.addEventListener("mouseenter", pausa);
    n.addEventListener("focusin", pausa);
    n.addEventListener("mouseleave", sigue);
    n.addEventListener("focusout", () => setTimeout(sigue));
  }
  n.replaceChildren(
    el("span", { textContent: t }),
    ...(acc
      ? [
          el("button", {
            type: "button",
            className: "link",
            textContent: acc.txt,
            onclick: () => {
              avisoFuera(n);
              acc.fn();
            },
          }),
        ]
      : []),
  );
  n.classList.remove("fuera");
  n.hidden = false;
  if (n.popover) {
    if (n.matches(":popover-open")) n.hidePopover();
    n.showPopover();
  }
  avisoT(n, acc ? 6000 : 3500);
};
const avisoT = (n, ms) => {
  clearTimeout(aviso.t);
  aviso.t = setTimeout(() => avisoFuera(n), ms);
};
const avisoFuera = n => {
  clearTimeout(aviso.t);
  n.classList.add("fuera");
  aviso.t = setTimeout(
    () => {
      n.classList.remove("fuera");
      n.popover && n.matches(":popover-open") ? n.hidePopover() : (n.hidden = true);
    },
    animOk() ? 200 : 0,
  );
};
const irInicio = () => {
  fsel = undefined;
  ir("home");
};
$("inicio").onclick = e => {
  e.preventDefault();
  irInicio();
};
$("cola-volver").onclick = e => {
  e.preventDefault();
  ir("home");
};
$("preg-volver").onclick = e => {
  e.preventDefault();
  mpCerrar();
  ir("home");
};
$("b-cola").onclick = () => {
  vista("cola");
  sondear();
};
$("nueva").onclick = () => formNuevo();
$("b-ajustes").onclick = () => abrirAjustes();

// ---- nuevo documento (o otra versión de uno existente: reuse) ----
let reuse = null;
const VACIO_SUB = $("form-sub").textContent,
  NUEVA_C = "\u0001nueva";
function carpetaSel(v) {
  const s = $("n-carpeta");
  s.replaceChildren(new Option(sinC(), ""), ...carpetas.map(c => new Option(c, c)), new Option("+ " + cap(nm("carpeta")) + " nueva…", NUEVA_C));
  s.value = v && carpetas.includes(v) ? v : "";
  $("n-carpeta-nueva").hidden = true;
  $("n-carpeta-nueva").value = "";
}
$("n-carpeta-l").textContent = "Guardar en";
$("n-carpeta").onchange = () => {
  const n = $("n-carpeta").value === NUEVA_C;
  $("n-carpeta-nueva").hidden = !n;
  if (n) $("n-carpeta-nueva").focus();
  const p = CP[$("n-carpeta").value];
  if (p && !reuse && PL.some(t => t.id === p)) {
    $("plantilla").value = p;
    $("plantilla").onchange();
  }
};
function formNuevo(m, a) {
  reuse = m ? { id: m.id, asr: a.asr } : null;
  $("form-t").textContent = m ? "Otra versión de «" + m.label + "»" : "Nuevo " + nm("documento");
  $("form-sub").textContent = m
    ? "Rehace el documento con otra plantilla, nivel o calidad aprovechando la transcripción y las capturas ya hechas. Con el mismo nivel y calidad que una versión existente, la sustituye."
    : VACIO_SUB;
  $("f-fuente-c").hidden = $("f-hab").hidden = !!m;
  $("n-carpeta").closest(".field").hidden = !!m;
  $("form-err").textContent = "";
  $("n-carpeta-l").textContent = "Guardar en";
  $("plantilla-l").textContent = "Tipo";
  carpetaSel(m ? m.carpeta || "" : typeof fsel === "string" ? fsel : "");
  if (m) {
    // propone la primera combinación que aún no existe
    const hay = n => cur.actas.some(x => x.name === n);
    const [n, c] = ["normal", "breve", "detallado"]
      .flatMap(n => NIV.map(q => q.id).map(c => [n, c]))
      .find(([n, c]) => !hay(`acta_${n}_${a.asr}${c === "rápida" ? "" : "_" + c}`)) || [a.nivel, a.calidad];
    $("nivel").value = n;
    $("calidad").value = c;
    $("calidad").onchange();
  }
  pintarNivel();
  plantForm(CP[m ? m.carpeta || "" : typeof fsel === "string" ? fsel : ""] || "acta");
  vista("nuevo");
  formSimple(m);
  genRes();
}
function genRes() {
  const o = s => s.options[s.selectedIndex]?.text || "",
    c = $("n-carpeta").value === NUEVA_C ? $("n-carpeta-nueva").value.trim() || "Proyecto nuevo" : o($("n-carpeta"));
  $("gen-res").textContent = [
    !reuse && c,
    o($("plantilla")),
    cap($("nivel").value),
    nivelInfo($("calidad").value)?.nombre,
    !reuse && o($("habla")),
    $("usar-gpu").checked ? "GPU" : "CPU",
  ]
    .filter(Boolean)
    .join(" · ");
}
$("form").addEventListener("input", genRes);
$("form").addEventListener("change", genRes);
$("form").addEventListener("click", () => setTimeout(genRes));
$("enlace").oninput = () => {
  const v = !!$("enlace").value.trim();
  $("l-solo-audio").hidden = !v;
  if (!v) $("solo-audio").checked = false;
}; // «solo audio» solo con enlace
const params = () => ({
  carpeta: reuse ? "" : $("n-carpeta").value === NUEVA_C ? $("n-carpeta-nueva").value.trim() : $("n-carpeta").value,
  video: reuse ? "" : ruta,
  enlace: reuse || ruta ? "" : $("enlace").value.trim(),
  solo_audio: $("solo-audio").checked,
  navegador: $("navegador").value,
  transcripcion: reuse ? "" : rutaTr,
  nivel: $("nivel").value,
  calidad: $("calidad").value,
  asr: reuse ? reuse.asr : "calidad",
  reuse: reuse?.id,
  hablantes: $("hablantes").checked,
  gpu: $("usar-gpu").checked,
  nombres: $("nombres").value,
  plantilla: $("plantilla").value,
  idioma: $("idioma").value,
  habla: reuse ? "" : $("habla").value,
  ...paramsSimple(),
  nube: nubeParams("f"),
});
$("form").onsubmit = async e => {
  // un trabajo por archivo (y otro por el enlace); el .zip de lote lo desempaqueta el servidor
  e.preventDefault();
  const fs = reuse ? [] : AN.files.map(f => f.path),
    enl = reuse ? "" : $("enlace").value.trim();
  if (!reuse && !fs.length && !rutaTr && !enl) {
    $("form-err").textContent = "Elige archivos, pega un enlace o una captura";
    return;
  }
  try {
    let dest = reuse ? "" : $("n-carpeta").value;
    if (dest === NUEVA_C) {
      dest = $("n-carpeta-nueva").value.trim();
      if (!dest) {
        $("form-err").textContent = "Escribe el nombre de la " + nm("carpeta").toLowerCase() + " nueva";
        return;
      }
      await post("/api/carpeta", { nuevo: dest });
    }
    if (!(await nubeOk("f"))) return;
    const p = { ...params(), ...anParams(dest) };
    if (AJ.servidor) return await subirAlServidor(dest, p);
    const jobs =
      !fs.length && !enl
        ? [{}]
        : [
            ...fs.map(v => ({
              video: v,
              enlace: "",
              transcripcion: fs.length === 1 ? p.transcripcion : "",
              descripcion: AN.files.find(f => f.path === v)?.img ? p.descripcion : "",
            })),
            ...(enl ? [{ video: "", enlace: enl, transcripcion: fs.length ? "" : p.transcripcion }] : []),
          ];
    $("generar").disabled = true;
    let n = 0,
      adj = 0;
    const errs = [];
    for (const j of jobs) {
      try {
        const r = await post("/api/generar", { ...p, ...j });
        n += r.lote || 1;
        adj += r.adjuntos?.length || 0;
        errs.push(...(r.errores || []).map(x => x.fichero + ": " + x.error));
      } catch (x) {
        errs.push(x.message);
      }
    }
    if (!n) throw new Error(errs.join(" · "));
    if (!reuse) anLimpiar();
    $("form-err").textContent = "";
    vista("cola");
    sondear();
    aviso(
      n +
        (n === 1 ? " trabajo en cola" : " trabajos en cola") +
        (adj ? " · +" + adj + " adjuntos en cola" : "") +
        (errs.length ? " · " + errs.length + " con error: " + errs[0] : ""),
    );
  } catch (err) {
    $("form-err").textContent = err.message;
  } finally {
    $("generar").disabled = false;
  }
};

// servidor de equipo: cada archivo va en base64 a /api/subir (documentos; resumir pide un modelo en la nube, si no solo se indexa)
const b64De = f =>
  new Promise((ok, ko) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result).split(",")[1] || "");
    r.onerror = () => ko(r.error);
    r.readAsDataURL(f);
  });
async function subirAlServidor(c, p) {
  // solo sale lo que se pide en «Qué sacar»: sin «documento» ni «resumen» el documento se guarda tal cual y solo se extrae lo pedido
  const sal = p.plan?.salidas || [],
    ia = !p.buscable && !!p.nube,
    resumen = !sal.length || sal.some(s => s.que === "documento" || s.que === "resumen"),
    fs = AN.files.filter(f => f.file),
    errs = [];
  if (!fs.length) throw new Error("Elige archivos");
  $("generar").disabled = true;
  let n = 0;
  for (const f of fs) {
    try {
      const resumir = ia && (resumen || f.img);
      await post("/api/subir", {
        c,
        nombre: f.name,
        base64: await b64De(f.file),
        resumir,
        tal_cual: ia && !resumir,
        perfil: p.plantilla,
        nube: p.nube,
        ...(ia && p.plan ? { plan: p.plan } : {}),
      });
      n++;
    } catch (x) {
      errs.push(f.name + ": " + x.message);
    }
  }
  if (!n) throw new Error(errs.join(" · "));
  anLimpiar();
  $("form-err").textContent = "";
  vista("cola");
  sondear();
  aviso(
    n +
      (n === 1 ? " documento en cola" : " documentos en cola") +
      (ia || p.buscable ? "" : " · sin modelo en la nube: solo se leen y se indexan") +
      (errs.length ? " · " + errs.length + " con error: " + errs[0] : ""),
  );
}

// ---- cola de trabajos ----
const ACT = ["pendiente", "marcha"],
  KIND = {
    acta: "Generar documento",
    fondo: "Búsqueda a fondo",
    condensar: "Vídeo condensado",
    describir: "Describir con IA",
    seguimiento: "Seguimiento de pendientes",
    estado: "Resumen del estado",
    comparar: "Resumen de diferencias",
  };
let cola = { n: 0, items: [] },
  vistos = new Set(),
  colaKey = null; // null: la cola aún no se ha pintado (también vacía)
const nombreDe = e => (e.mid && todas.find(m => m.id === e.mid)?.label) || e.video;
const minutos = s => (s > 90 ? "unos " + Math.round(s / 60) + " min" : "unos " + s + " s");
const lleva = e => (e?.t0 ? Math.max(0, Math.round(Date.now() / 1000 - e.t0)) : null); // en el portátil lento: se ve que avanza aunque aún no haya ETA
const durac = s => (s >= 3600 ? Math.floor(s / 3600) + " h " + Math.round((s % 3600) / 60) + " min" : s >= 60 ? Math.round(s / 60) + " min" : s + " s");
const titCola = e => (e.kind === "acta" ? "Generar " + (e.doc || "documento") : KIND[e.kind]) + " · " + nombreDe(e);
async function sondear() {
  const c = await api("/api/cola").catch(() => null);
  if (!c) return;
  const act = new Set(c.items.filter(e => ACT.includes(e.state)).map(e => e.id));
  const fin = c.items.filter(e => vistos.has(e.id) && !act.has(e.id));
  vistos = act;
  cola = c;
  corriendo = c.n > 0;
  const k = c.items.map(e => e.id + e.state).join();
  if (fin.length) {
    // algo terminó: refrescar lista y, si es la reunión abierta, su página
    carpetaTrasCola(fin);
    await cargarLista();
    if (vistaAct === "res" && fin.some(e => e.state === "hecho" && e.mid === cur.id)) await abrir(cur.id, ver, true);
  } else if (k !== colaKey && vistaAct === "home") pintarHome();
  pintarCola(k);
  pintarPill();
}
function pintarPill() {
  const r = cola.items.find(e => e.state === "marcha"),
    n = cola.n;
  $("b-cola").style.setProperty("--p", r ? r.frac : 0);
  $("b-cola").classList.toggle("on", n > 0); // anillo de progreso
  $("cola-txt").textContent = n ? " · " + (r ? "1 de " + n : n + " en espera") + (r && r.eta != null ? " · " + minutos(r.eta) : "") : "";
  $("b-cola").setAttribute("aria-label", "Cola de trabajos" + (n ? ", " + n : ""));
  $("b-cola").title = r ? (r.msg || "En marcha") + (lleva(r) != null ? " · lleva " + durac(lleva(r)) : "") : "Cola de trabajos";
  if (vistaAct === "home") {
    const c = document.querySelector("#side [data-cola]");
    if (c) c.textContent = n || "";
  }
}
function pintarCola(k) {
  if (k !== colaKey) {
    colaKey = k;
    const it = cola.items,
      pend = it.filter(e => e.state === "pendiente");
    const bt = (e, txt, url, extra, lbl) => {
      const x = el("button", { className: "sec sm", textContent: txt, ariaLabel: lbl || txt });
      x.onclick = fallo(async () => {
        x.disabled = true;
        await post(url, { id: e.id, ...extra });
        await sondear();
      });
      return x;
    };
    const ab = e => {
      const o = el("button", { className: "sec ab", textContent: "Abrir" });
      o.onclick = fallo(() => abrir(e.result.id, e.result.acta));
      return o;
    };
    const sec = (t, kids, cls = "", lado) =>
      el(
        "section",
        { className: "qs " + cls },
        el("div", { className: "sec-h" }, el("h2", { textContent: t }), ...(lado ? [lado] : [])),
        el("div", { className: "qbox" }, ...kids),
      );
    const kind = e => (e.kind === "acta" ? "Generar " + (e.doc || "documento") : KIND[e.kind]);
    const xb = e => {
      const x = el("button", { className: "qx", textContent: "✕", ariaLabel: "Quitar de la cola", title: "Quitar" });
      x.onclick = fallo(async () => {
        x.disabled = true;
        await post("/api/cola/cancelar", { id: e.id });
        await sondear();
      });
      return x;
    };
    const run = it
      .filter(e => e.state === "marcha")
      .map(e =>
        el(
          "section",
          { className: "qcurso" },
          el(
            "div",
            { className: "q-it" },
            el(
              "div",
              { className: "n" },
              el("div", { className: "k", textContent: "En curso" }),
              el("h3", { textContent: nombreDe(e) }),
              el("div", { className: "d", textContent: kind(e) }),
            ),
            el("div", { className: "acc" }, ...(e.kind === "acta" || true ? [bt(e, "Cancelar", "/api/cola/cancelar")] : [])),
          ),
          e.kind === "acta"
            ? el("ol", { className: "fases", id: "q-fases", ariaLabel: "Fases" })
            : el("div", { className: "bar", role: "progressbar", ariaLabel: "Progreso" }, el("div", { id: "q-bar" })),
          el("div", { className: "q-pie" }, el("span", { id: "q-eta" }), el("span", { id: "q-msg" })),
        ),
      );
    run.forEach(r => r.querySelector(".acc button").classList.add("dng"));
    const esp = pend.map((e, i) =>
      el(
        "div",
        { className: "q-it" },
        el("span", { className: "num", textContent: i + 2 - (it.some(x => x.state === "marcha") ? 0 : 1) }),
        el(
          "div",
          { className: "n" },
          el("b", { textContent: nombreDe(e) }),
          el("div", { className: "d", textContent: kind(e) + " · en espera (" + (i + 1) + " de " + pend.length + ")" }),
        ),
        el(
          "div",
          { className: "acc" },
          bt(e, "↑", "/api/cola/mover", { d: -1 }, "Subir en la cola"),
          bt(e, "↓", "/api/cola/mover", { d: 1 }, "Bajar en la cola"),
          xb(e),
        ),
      ),
    );
    esp.forEach((r, i) => {
      const b = r.querySelectorAll(".acc button");
      b[0].disabled = i === 0;
      b[1].disabled = i === esp.length - 1;
      b[0].classList.add("qi");
      b[1].classList.add("qi");
    });
    const mal = it
      .filter(e => e.state === "error" || e.state === "interrumpido")
      .map(e =>
        el(
          "div",
          { className: "q-it" },
          el(
            "div",
            { className: "n" },
            el("b", { textContent: nombreDe(e) + " · " + (e.state === "interrumpido" ? "interrumpido" : "ha fallado") }),
            el("div", { className: "d", textContent: e.error || kind(e) }),
          ),
          el("div", { className: "acc" }, bt(e, "Reintentar", "/api/cola/reintentar"), bt(e, "Quitar", "/api/cola/quitar")),
        ),
      );
    const hec = it
      .filter(e => e.state === "hecho" || e.state === "cancelado")
      .reverse()
      .map(e =>
        el(
          "div",
          { className: "q-it" },
          el(
            "div",
            { className: "n" },
            el("b", { textContent: nombreDe(e) }),
            el("div", { className: "d", textContent: kind(e) + " · " + (e.state === "hecho" ? "terminado" : "cancelado") }),
          ),
          el("div", { className: "acc" }, ...(e.state === "hecho" && e.result?.id ? [ab(e)] : []), xb2(e)),
        ),
      );
    function xb2(e) {
      const x = xb(e);
      x.onclick = fallo(async () => {
        x.disabled = true;
        await post("/api/cola/quitar", { id: e.id });
        await sondear();
      });
      return x;
    }
    const lim = el("button", {
      className: "link",
      textContent: "Limpiar",
      onclick: fallo(async () => {
        for (const e of it.filter(e => !ACT.includes(e.state) && e.state !== "error" && e.state !== "interrumpido"))
          await post("/api/cola/quitar", { id: e.id });
        await sondear();
      }),
    });
    const mas = el(
      "div",
      { className: "qdrop" },
      "Para añadir más al final, crea otro documento · ",
      el("a", {
        href: "#",
        textContent: "Nuevo documento",
        onclick: e => {
          e.preventDefault();
          formNuevo();
        },
      }),
    );
    $("q-lista").replaceChildren(
      ...run,
      ...(pend.length ? [sec("En espera · " + pend.length, esp, "", el("span", { className: "d", textContent: "Se procesan en este orden" })), mas] : []),
      ...(mal.length ? [sec("Necesita tu ayuda · " + mal.length, mal, "ayuda")] : []),
      ...(hec.length ? [sec("Terminados · " + hec.length, hec, "", lim)] : []),
      ...(!it.length ? [el("div", { className: "qbox vacio", textContent: "No hay trabajos. Crea un documento con «" + nm("nuevo_boton") + "»." })] : []),
    );
    $("q-sub").textContent =
      pend.length || it.some(e => e.state === "marcha")
        ? (it.some(e => e.state === "marcha") ? "1 en curso" : "") +
          (pend.length ? (it.some(e => e.state === "marcha") ? " · " : "") + pend.length + " en espera" : "") +
          ". Puedes cerrar esta ventana de trabajo y seguir usando la aplicación."
        : "Se procesa un trabajo a la vez; el resto espera su turno.";
  }
  const r = cola.items.find(e => e.state === "marcha");
  if (r && $("q-eta")) {
    $("q-msg").textContent = r.msg;
    if ($("q-bar")) $("q-bar").style.width = Math.round(r.frac * 100) + "%";
    pintarFases(r);
    $("q-eta").textContent =
      (r.eta != null ? "Quedan " + minutos(r.eta) : "En marcha") +
      " · " +
      Math.round(r.frac * 100) +
      " %" +
      (lleva(r) != null ? " · lleva " + durac(lleva(r)) : "");
  }
  const ep = $("en-proc-bar");
  if (r && ep) {
    ep.style.width = Math.round(r.frac * 100) + "%";
    $("en-proc-eta").textContent = r.msg + (r.eta != null ? " · quedan " + minutos(r.eta) : "");
  }
}

// fases de «Generar documento»: tramos fijos de la barra de pipeline.run (asr 0–45 %, hablantes y capturas 45–60 %, resumen 60–92 %, redacción y repasos 92–100 %);
// con enlace, antes va la descarga (su propia barra 0–100 %, mensaje «Descargando…»)
const FASES = [
  ["Transcripción", 0, 0.45],
  ["Capturas y OCR", 0.45, 0.6],
  ["Resumen", 0.6, 0.92],
  ["Redacción", 0.92, 1],
];
function pintarFases(r) {
  const ol = $("q-fases");
  if (!ol) return;
  const baja = /^Descargando/.test(r.msg || ""),
    fs = [...(/^https?:/i.test(r.video || "") ? [["Descarga", -1, 0]] : []), ...FASES];
  ol.replaceChildren(
    ...fs.map(([t, lo, hi]) => {
      const f = lo < 0 ? (baja ? r.frac : 1) : baja ? 0 : Math.max(0, Math.min(1, (r.frac - lo) / (hi - lo))),
        on = lo < 0 ? baja : !baja && r.frac >= lo && r.frac < hi,
        i = el("i");
      i.style.width = Math.round(f * 100) + "%";
      return el(
        "li",
        on ? { className: "on", "aria-current": "step" } : { className: f >= 1 ? "ok" : "" },
        el("div", { className: "bar" }, i),
        el("span", { textContent: t + (on ? " · " + Math.round(f * 100) + " %" : f >= 1 ? " ✓" : "") }),
      );
    }),
  );
}

// ---- reuniones y carpetas ----
// fsel: undefined = inicio, null = todos los documentos, "" = sin carpeta, otro = esa carpeta
let cur,
  ver,
  tabAct = "p-acta",
  todas = [],
  carpetas = [],
  fsel,
  desde,
  RES = {},
  docDesde = "#/"; // docDesde: ruta a la que vuelve «←» del documento
const fallo =
  f =>
  (...a) =>
    f(...a).catch(err => alert(err.message));
const refrescarTodo = async () => {
  await cargarLista();
  if (vistaAct === "res") await abrir(cur.id, ver, true);
};
// formulario en la propia página (sin prompt/confirm): campo opcional + botón + Cancelar; Esc cancela
function enLinea(donde, { valor, lista, texto, boton = "Guardar" }, hecho) {
  document.querySelector("form.inline-f")?.remove();
  const f = el("form", { className: "inline-f row wrap" }),
    c = el("button", { type: "button", className: "sec", textContent: "Cancelar" });
  const i = valor != null ? el("input", { value: valor, ariaLabel: texto, className: "il-i" }) : null;
  if (i && lista?.length) {
    i.setAttribute("list", "dl-carpetas");
    f.append(el("datalist", { id: "dl-carpetas" }, ...lista.map(v => el("option", { value: v }))));
  }
  f.append(el("span", { textContent: texto, className: "il-t" }), ...(i ? [i] : []), el("button", { className: "pri", textContent: boton }), c);
  c.onclick = () => f.remove();
  f.onkeydown = e => {
    if (e.key === "Escape") f.remove();
  };
  f.onsubmit = e => {
    e.preventDefault();
    fallo(async () => {
      await hecho(i ? i.value.trim() : "");
      f.remove();
    })();
  };
  donde.append(f);
  (i || c).focus();
  i?.select();
}
const renombrar = (m, donde) =>
  enLinea(donde, { valor: m.nombre || m.label, texto: "Nombre (vacío = el original)" }, async n => {
    await post("/api/meta", { id: m.id, nombre: n });
    await refrescarTodo();
  });
const mover = (m, donde) =>
  enLinea(
    donde,
    {
      valor: m.carpeta || "",
      lista: carpetas,
      texto: cap(nm("carpeta").toLowerCase()) + " (nueva o existente; vacío = " + sinC().toLowerCase() + ")",
      boton: "Mover",
    },
    async c => {
      const antes = m.carpeta || "";
      if (c === antes) return;
      await post("/api/meta", { id: m.id, carpeta: c });
      await refrescarTodo();
      aviso("Movido a «" + (c || sinC()) + "»", {
        txt: "Deshacer",
        fn: fallo(async () => {
          await post("/api/meta", { id: m.id, carpeta: antes });
          await refrescarTodo();
          typeof BIB !== "undefined" && vistaAct === "bib" && pintarBib();
        }),
      });
    },
  );
const carpetaOp = (nombre, borrar, donde) =>
  enLinea(
    donde,
    borrar
      ? { texto: "Se quita «" + nombre + "»: los " + pl(nm("documento")) + " pasan a «" + sinC() + "» y no se borran.", boton: "Quitar" }
      : { valor: nombre, texto: "Nuevo nombre" },
    async nuevo => {
      if (!borrar && (!nuevo || nuevo === nombre)) return;
      await post("/api/carpeta", { nombre, nuevo });
      if (fsel === nombre) fsel = borrar ? null : nuevo;
      await refrescarTodo();
    },
  );
const unicas = ms => {
  const v = new Set();
  return ms.filter(m => !v.has(m.id) && v.add(m.id));
};
async function cargarLista() {
  [todas, carpetas, CP, CE, ESTILOS, RES] = await Promise.all([
    api("/api/meetings").then(ms => unicas(ms).filter(m => m.actas)),
    api("/api/carpetas"),
    api("/api/carpetas/plantillas"),
    api("/api/carpetas/estilos").catch(() => ({})),
    api("/api/estilos").catch(() => []),
    api("/api/carpetas/resumen").catch(() => ({})),
    PL.length ? null : cargarPlant(),
  ]);
  if (fsel && !carpetas.includes(fsel)) fsel = undefined;
  pintarHome();
  typeof homePend === "function" && homePend();
  if (vistaAct === "pend" && typeof pintarPendPag === "function") pintarPendPag(); // abierta por enlace antes de tener RES: se repinta con los datos
}
const plural = n => n + " " + (n === 1 ? nm("documento") : pl(nm("documento")));
const fechaC = t => new Date(t * 1000).toLocaleDateString("es", { day: "numeric", month: "short" });
let arrastrando = null;
const soltable = (n, c) => {
  n.addEventListener("dragover", e => {
    if (arrastrando) {
      e.preventDefault();
      n.classList.add("drop");
    }
  });
  n.addEventListener("dragleave", () => n.classList.remove("drop"));
  n.addEventListener(
    "drop",
    fallo(async e => {
      e.preventDefault();
      n.classList.remove("drop");
      const m = arrastrando;
      arrastrando = null;
      if (!m || (m.carpeta || "") === c) return;
      await (c ? post("/api/doc/a-proyecto", { mids: [m.id], c, modo: "mover" }) : post("/api/meta", { id: m.id, carpeta: c }));
      await refrescarTodo();
      aviso("Movido a " + (c || sinC()));
    }),
  );
  return n;
};
// pintarSide (raíl izquierdo): shell.js
const nuevaCarpeta = () =>
  enLinea($("ed-home"), { valor: "", texto: "Nombre de la " + nm("carpeta").toLowerCase() + " nueva", boton: "Crear" }, async n => {
    if (!n) return;
    await post("/api/carpeta", { nuevo: n });
    fsel = n;
    await cargarLista();
  });
function pintarHome() {
  typeof pintarSide === "function" && pintarSide();
  const ini = fsel === undefined,
    act = cola.items.filter(e => ACT.includes(e.state)),
    est = e => (e.state === "marcha" ? "Generando" : "En cola (" + (act.indexOf(e) + 1) + "/" + act.length + ")");
  $("h-inicio").hidden = !ini;
  $("f-cab").hidden = ini;
  if (ini) {
    $("h-tit").textContent = "Inicio";
    $("h-sub").textContent = todas.length
      ? ""
      : "Todavía no hay nada. Pulsa «" + nm("nuevo_boton") + "» para crear tu primer " + nm("documento") + " o «Importar» para abrir uno exportado.";
    $("proys-t").textContent = cap(pl(nm("carpeta")));
    const ult = c => todas.filter(m => (m.carpeta || "") === c).reduce((a, m) => Math.max(a, m.mtime), 0);
    const card = c => {
      const n = todas.filter(m => (m.carpeta || "") === c).length,
        r = RES[c] || {},
        u = Math.max(ult(c), r.ultima || 0);
      return soltable(
        el(
          "button",
          {
            className: "proy",
            onclick: () => {
              fsel = c;
              pintarHome();
            },
          },
          el(
            "div",
            { className: "pt" },
            el("b", { textContent: c || sinC() }),
            el("small", { textContent: (CP[c] && PL.length ? plantDe(CP[c]).nombre + " · " : "") + plural(n) }),
          ),
          el(
            "div",
            { className: "pf" },
            ...(r.pend ? [el("b", { textContent: r.pend + (r.pend === 1 ? " pendiente" : " pendientes") })] : [el("span", { textContent: "Sin pendientes" })]),
            ...(r.sug ? [el("span", { textContent: r.sug + " por revisar" })] : []),
            ...(u ? [el("span", { textContent: "Último: " + fechaC(u) })] : []),
          ),
        ),
        c,
      );
    };
    const nueva = el("button", { className: "proy nueva", textContent: "+ " + cap(nm("carpeta")) + " nuevo", onclick: nuevaCarpeta });
    $("proys").replaceChildren(...carpetas.map(card), ...(todas.some(m => !m.carpeta) && carpetas.length ? [card("")] : []), nueva);
    const r = act.find(e => e.state === "marcha");
    $("en-proc").replaceChildren(
      ...(act.length
        ? [
            el(
              "div",
              { className: "en-proc" },
              el(
                "div",
                { className: "r" },
                el("strong", { textContent: r ? "Generando · " + nombreDe(r) : "En cola" }),
                el("span", { className: "muted", textContent: act.length > 1 ? act.length - (r ? 1 : 0) + " más en espera" : "" }),
              ),
              ...(r ? [el("div", { className: "bar", role: "progressbar", ariaLabel: "Progreso" }, el("div", { id: "en-proc-bar" }))] : []),
              el(
                "div",
                { className: "d muted" },
                el("span", { id: "en-proc-eta" }),
                r ? " · " : "",
                el("a", {
                  href: "#",
                  textContent: "Ver cola",
                  onclick: e => {
                    e.preventDefault();
                    vista("cola");
                    sondear();
                  },
                }),
              ),
            ),
          ]
        : []),
    );
    const rv = [...carpetas, ""]
      .filter(c => (RES[c] || {}).sug || (RES[c] || {}).pend)
      .map(c => {
        const q = RES[c];
        return el(
          "button",
          {
            className: "rev-i" + (q.sug ? " w" : ""),
            onclick: () => {
              fsel = c;
              pintarHome();
            },
          },
          el("b", {
            textContent: q.sug
              ? q.sug + (q.sug === 1 ? " sugerencia por revisar" : " sugerencias por revisar")
              : q.pend + (q.pend === 1 ? " pendiente abierto" : " pendientes abiertos"),
          }),
          el("small", { textContent: c || sinC() }),
        );
      });
    $("rev-l").replaceChildren(...rv);
    $("rev").hidden = !act.length && !rv.length;
    pintarCola(colaKey);
  } else {
    const c = fsel;
    $("ftit").textContent = c === null ? cap(pl(nm("documento"))) : c === "" ? sinC() : c;
    $("fsub").textContent = plural(todas.filter(m => c === null || (m.carpeta || "") === c).length);
    for (const id of ["f-preguntar", "f-ren", "f-quitar", "f-plant"]) $(id).hidden = !c;
    $("f-estilo").hidden = !c || !ESTILOS.length;
    if (c && ESTILOS.length) {
      $("f-estilo").replaceChildren(new Option("Estilo por defecto: ninguno", ""), ...ESTILOS.map(e => new Option("Estilo: " + e.nombre, e.id)));
      $("f-estilo").value = CE[c] || "";
    }
    $("f-plant-l").hidden = !c;
    if (c) {
      $("f-plant").replaceChildren(...PL.map(t => new Option("Tipo por defecto: " + t.nombre, t.id)));
      $("f-plant").value = CP[c] || "acta";
    }
  }
  carpetaVista(!ini && fsel ? fsel : null);
  const bus = qBuscar.trim().toLowerCase(),
    ms = todas
      .filter(m => (ini || fsel === null || (m.carpeta || "") === fsel) && (!bus || (m.label + " " + (m.carpeta || "")).toLowerCase().includes(bus)))
      .slice(0, ini && !bus ? 8 : 1e9);
  $("docs-t").textContent = bus ? "Resultados" : ini ? "Documentos recientes" : fsel === null ? "Todos" : "Documentos";
  $("docs-todos").hidden = !ini || !!bus;
  const enP = !ini && fsel !== null; // dentro de un proyecto (o «Sin proyecto»): la columna «Proyecto» sobra y, en la pestaña Documentos, el título repite el nombre de la pestaña
  $("docs-t").parentElement.hidden = !!fsel && !bus;
  const nuevas = bus ? [] : ini || fsel === null || fsel === "" ? act.filter(e => e.kind === "acta" && !e.mid) : [];
  const fila = m => {
    const e = act.find(e => e.mid === m.id),
      f = fechaC(m.mtime);
    const tr = el(
      "tr",
      {
        className: "f",
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
      el("td", {}, el("button", { className: "doc-l", textContent: m.label, onclick: fallo(() => abrir(m.id)) })),
      el("td", { textContent: m.carpeta || "", hidden: enP }),
      el("td", { textContent: f }),
      el(
        "td",
        {},
        el(
          "div",
          { className: "est-c" },
          ...(e ? [el("span", { className: "badge acc", textContent: est(e) })] : []),
          ...(m.actas > 1 && !e ? [el("span", { className: "badge", textContent: m.actas + " versiones" })] : []), // «Mover» a la derecha de la celda (misma x en todas las filas); con ratón, al pasar o enfocar la fila
          el("button", { className: "sec sm fila-mv", textContent: "Mover", ariaLabel: "Mover " + m.label, onclick: () => mover(m, tr.lastChild) }),
        ),
      ),
    );
    return tr;
  };
  $("lista").replaceChildren(
    ...nuevas.map(e =>
      el(
        "tr",
        {},
        el("td", { textContent: e.video }),
        el("td", { hidden: enP }),
        el("td"),
        el("td", {}, el("span", { className: "badge acc", textContent: est(e) })),
      ),
    ),
    ...ms.map(fila),
  );
  $("vacio").hidden = !!(ms.length || nuevas.length);
  $("tabla").firstChild.hidden = !$("vacio").hidden;
  $("vacio").textContent = "Aún no hay " + pl(nm("documento")) + (fsel ? " en «" + fsel + "»" : "") + ".";
  const ths = document.querySelectorAll("#tabla th");
  ths[1].hidden = enP;
  ths[3].replaceChildren(
    nuevas.length || ms.some(m => m.actas > 1 || act.some(e => e.mid === m.id)) ? "Estado" : el("span", { className: "sr", textContent: "Acciones" }),
  ); // sin estado en ninguna fila, la columna solo lleva «Mover»: cabecera solo para lectores de pantalla
  if (ini) $("docs-w").hidden = true; // Inicio: «Continúa» en vez de la tabla (shell.js)
  if (typeof rutaSync === "function") {
    if (ini) pintarInicio();
    if (vistaAct === "home") rutaSync();
  }
}
$("f-ren").onclick = () => carpetaOp(fsel, false, $("ed-carpeta"));
$("f-quitar").onclick = () => carpetaOp(fsel, true, $("ed-carpeta"));
$("f-preguntar").onclick = () => {
  $("preg-tit").textContent = "Preguntar · " + fsel;
  $("p-fcarpeta").append($("qpanel"));
  setQ("c:" + fsel);
  vista("preg");
};
$("f-estilo").onchange = fallo(async () => {
  await post("/api/carpeta", { nombre: fsel, estilo: $("f-estilo").value });
  CE = await api("/api/carpetas/estilos");
  aviso("Estilo guardado");
});
$("f-plant").onchange = fallo(async () => {
  await post("/api/carpeta", { nombre: fsel, plantilla: $("f-plant").value === "acta" ? "" : $("f-plant").value });
  CP = await api("/api/carpetas/plantillas");
  aviso("Tipo por defecto guardado");
});

// ---- página de un documento ----
const cap = s => s[0].toUpperCase() + s.slice(1);
const defecto = a =>
  [
    a.plantilla,
    a.idioma && "en " + (IDI[a.idioma] || a.idioma),
    cap(a.nivel),
    (nivelInfo(a.calidad)?.nombre || "Rápida") + (nivelInfo(a.calidad)?.pers ? " · " + nivelInfo(a.calidad).modelo : ""),
    a.fondo && "a fondo",
    a.nube && "☁ " + a.nube,
    a.name
      .split("_")
      .slice(3)
      .filter(x => !(x in { alta: 1, alta9: 1, muyalta: 1, maxima: 1 } || /^p[0-9a-f]{6}$/.test(x) || /^[pi]-/.test(x) || /^nube-/.test(x)))
      .join(" "),
  ]
    .filter(Boolean)
    .join(" · ");
const etiqueta = a => cur.versiones[a.name] || defecto(a);
async function abrir(id, acta, quedar) {
  cur = await api("/api/meeting/" + id);
  cur.solo = !cur.actas.length; // «solo buscable»: sin acta; se abre en Fuente
  cur.m = todas.find(m => m.id === id) || { id, label: cur.nombre || id, nombre: cur.nombre, carpeta: cur.carpeta };
  if (!cur.solo && simple()) {
    const u = cur.actas.reduce((x, y) => (y.mtime > x.mtime ? y : x));
    if (!acta || !cur.actas.some(a => a.name === acta)) acta = u.name;
  }
  ver = cur.solo ? "" : (cur.actas.find(a => a.name === acta) || cur.actas.find(a => a.name === ver && quedar) || cur.actas[0]).name;
  if (!quedar) {
    desde = fsel;
    if (vistaAct !== "res") docDesde = rutaHash();
  }
  $("cab-carpeta").textContent = desdeTxt(docDesde);
  $("cab-titulo").textContent = cur.m.label;
  const au = cur.audio;
  $("t-video").hidden = false;
  $("vslot").hidden = !cur.video;
  $("t-acta").hidden = $("t-ext").hidden = cur.solo;
  $("cond").hidden = !cur.video; // imagen, PDF o texto: sin «Vídeo condensado»
  $("cond-t").textContent = au ? "Audio condensado" : "Vídeo condensado";
  $("condensar").textContent = au ? "Generar audio condensado" : "Generar vídeo condensado";
  if (cur.video) mpCargar(cur.videourl, cur.m.label, !!au);
  else mpCerrar();
  vista("res");
  document.title = cur.m.label + " · Actas";
  soloUI(cur.solo);
  if (cur.solo) {
    $("acta-acciones").replaceChildren();
    $("vers").replaceChildren();
    $("cab-meta").replaceChildren(...[KIND_T[cur.kind], cur.carpeta, "solo buscable"].filter(Boolean).map(t => el("span", { textContent: t })));
    $("imp-info").hidden = true;
    pintarConds();
    tab(quedar && tabAct !== "p-acta" && tabAct !== "p-ext" ? tabAct : "p-video");
    return;
  }
  pintarVers();
  cambiarActa();
  pintarConds();
  tab(quedar && !(tabAct === "p-video" && !cur.video) ? tabAct : cur.kind === "imagen" ? "p-video" : "p-acta"); // una imagen se abre en Fuente: ahí está la imagen (en Resumen no se vería)
}
// documento «solo buscable»: oculta lo que necesita un acta y ofrece «Resumir y extraer» (otra versión con la misma fuente, sin buscable)
const SOLO_OCULTOS = [
  "d-env-w",
  "d-editar",
  "d-correo",
  "d-anon",
  "d-otra",
  "d-vren",
  "d-dud",
  "d-rest",
  "fondo",
  "dl-zip",
  "dl-vid",
  "d-cond",
  "d-exp",
  "d-det",
];
function soloUI(on) {
  SOLO_OCULTOS.forEach(i => {
    if (on || !["d-rest", "fondo", "dl-zip", "dl-vid", "d-cond"].includes(i)) $(i).hidden = on;
  });
  $("d-resumir").hidden = !on;
  $("d-mas").open = false;
}
$("d-resumir").onclick = $("solo-resumir").onclick = () => formNuevo(cur.m, { asr: cur.asr, nivel: "normal", calidad: "rápida" });
const tab = (p, dir = 0) => {
  // dir: eje X al cambiar de pestaña a mano (−1 izquierda, 1 derecha)
  tabAct = p;
  document.querySelectorAll("#mtabs button").forEach(b => {
    b.setAttribute("aria-selected", b.dataset.p === p);
    $(b.dataset.p).hidden = b.dataset.p !== p;
  });
  const vacio = cur.solo && (p === "p-acta" || p === "p-ext");
  $("solo-vacio").hidden = !vacio;
  if (vacio) $(p).hidden = true;
  ubicar();
  docAlto();
  if (p === "p-video" && typeof notasRes === "function") notasRes();
  docTab(p); // Extraído y Fuente: shell.js
  ejeX($(p), dir);
  if (p === "p-preg") {
    $("p-preg-m").append($("qpanel"));
    $("qbox").hidden = !cur.video;
    const a = cur.actas.find(a => a.name === ver) || { asr: cur.asr };
    setQ(cur.id + "|" + a.asr);
    $("preguntar-b").disabled = $("pregunta").disabled = !!a.sin;
    $("pregunta").placeholder = a.sin ? "Documento importado sin transcripción: no se puede preguntar" : "Escribe tu pregunta…";
    ubicar();
  }
};
document
  .querySelectorAll("#mtabs button")
  .forEach((b, i, bs) => (b.onclick = () => tab(b.dataset.p, Math.sign(i - [...bs].findIndex(x => x.dataset.p === tabAct)))));
function pintarVers() {
  const a = cur.actas.find(a => a.name === ver),
    ren = el("button", { className: "sec sm", textContent: "Renombrar versión", title: "Renombrar esta versión" }),
    otra = el("button", { className: "sec sm", textContent: "+ Otra versión" });
  ren.onclick = () =>
    enLinea($("ed-res"), { valor: etiqueta(a), texto: "Nombre de la versión (vacío = el original)" }, async n => {
      await post("/api/meta", { id: cur.id, version: ver, vnombre: n === defecto(a) ? "" : n });
      cur.versiones = (await api("/api/meeting/" + cur.id)).versiones;
      pintarVers();
    });
  otra.onclick = () => formNuevo(cur.m, a);
  const txt = x => etiqueta(x) + (x.editado ? " · editado" : ""),
    pon = n => {
      ver = n;
      pintarVers();
      cambiarActa();
    };
  const sel =
    cur.actas.length <= 3
      ? el(
          "div",
          { className: "seg vseg", role: "tablist", ariaLabel: "Versiones" },
          ...cur.actas.map(x => el("button", { role: "tab", textContent: txt(x), "aria-selected": x.name === ver, onclick: () => pon(x.name) })),
        )
      : el(
          "label",
          { className: "vsel" },
          el("span", { textContent: "Versión" }),
          el("select", { onchange: e => pon(e.target.value) }, ...cur.actas.map(x => Object.assign(new Option(txt(x), x.name), { selected: x.name === ver }))),
        );
  $("d-vren").onclick = ren.onclick;
  $("d-otra").onclick = otra.onclick; // en el menú ⋯
  $("vers").replaceChildren(...(cur.actas.length > 1 || !simple() ? [sel] : []));
}
function cambiarActa() {
  const a = cur.actas.find(a => a.name === ver),
    nd = a.doc || "acta";
  editando = false;
  pintarAcciones(a);
  $("dl-zip").textContent = "Descargar (.zip)";
  $("fondo").hidden = !!a.plantilla;
  const imp = cur.importadas[a.asr],
    proc = [cap(nd), a.nube ? "☁ " + a.nube : nivelInfo(a.calidad)?.nombre || "Rápida"].join(" · ");
  $("cab-meta").replaceChildren(
    ...[!imp?.tipo && cur.m.dur ? Math.round(cur.m.dur / 60) + " min" : "", a.editado && "editado"].filter(Boolean).map(t => el("span", { textContent: t })),
    el(
      "span",
      { className: "pchip", title: "Procesado: " + etiqueta(a) },
      "Procesado: " + proc,
      el("button", {
        type: "button",
        className: "link",
        textContent: "Reprocesar",
        title: "Otra versión con otras opciones",
        onclick: () => formNuevo(cur.m, a),
      }),
    ),
    ...(cur.carpeta ? [el("a", { href: "#/p/" + encodeURIComponent(cur.carpeta), textContent: cur.carpeta })] : []),
  );
  // desde los datos: lleva data-p (marcas de dudas) y lo editado
  $("acta-frame").src = `/api/vista/${cur.id}/${a.name}?v=` + Date.now();
  $("fondo").disabled = a.fondo;
  $("fondo").textContent = a.fondo ? "Búsqueda a fondo hecha" : "Buscar todas a fondo";
  $("dl-zip").hidden = !a.zip;
  if (a.zip) {
    $("dl-zip").href = a.zip;
    $("dl-zip").download = cur.nombre ? cur.nombre + ".zip" : "";
  }
  $("dl-vid").hidden = !cur.video;
  $("dl-vid").href = "/api/zipvideo/" + cur.id + "/" + a.name;
  $("dl-vid").textContent = "Descargar con " + (cur.audio ? "audio" : "vídeo") + " (" + cur.videomb + " MB)";
  $("imp-info").textContent = imp
    ? (imp.tipo ? "Documento: " : "Transcripción importada: ") +
      imp.fuente +
      " (" +
      imp.formato +
      ", " +
      imp.segmentos +
      " segmentos, " +
      imp.hablantes.length +
      " hablantes)" +
      (cur.video
        ? imp.aviso
          ? ""
          : " · desfase aplicado " + (imp.desfase >= 0 ? "+" : "") + Math.round(imp.desfase) + " s"
        : cur.audio
          ? " · solo audio: sin capturas"
          : " · sin vídeo: sin capturas ni reproductor") +
      (imp.aviso ? ". " + imp.aviso : "")
    : "";
  $("imp-info").className = imp && imp.aviso ? "err" : "muted det";
  $("imp-info").hidden = !imp?.aviso;
  $("d-det").hidden = !imp;
  $("cond").hidden = !cur.video; // sin aviso: en ⋯ › Detalles
  zipAnon();
  const rec = cur.recomendado[a.asr];
  if (rec) {
    $("pct").value = rec;
    $("pct-o").textContent = rec;
    $("rec").textContent = "Recomendado para esta reunión: " + rec + " %. Primero los silencios largos, después lo menos importante.";
  }
}
$("fondo").onclick = async () => {
  const a = cur.actas.find(a => a.name === ver);
  try {
    await post("/api/fondo", { id: cur.id, nivel: a.nivel, asr: a.asr, calidad: a.calidad, gpu: $("usar-gpu").checked });
    aviso("Añadido a la cola");
    sondear();
  } catch (err) {
    alert(err.message);
  }
};
$("condensar").onclick = async () => {
  try {
    await post("/api/condensar", { id: cur.id, asr: cur.actas.find(a => a.name === ver).asr, pct: +$("pct").value });
    aviso("Añadido a la cola");
    sondear();
  } catch (err) {
    alert(err.message);
  }
};
$("m-ren").onclick = () => renombrar(cur.m, $("ed-res"));
$("d-det").onclick = () => {
  tab("p-acta");
  $("imp-info").hidden = !$("imp-info").hidden;
};
$("m-mover").onclick = () => mover(cur.m, $("ed-res"));
$("pct").oninput = () => ($("pct-o").textContent = $("pct").value);
$("volver").onclick = e => {
  e.preventDefault();
  $("acta-frame").src = "about:blank";
  mpCerrar();
  $("cvideo").pause();
  location.hash = docDesde || "#/";
};
function pintarConds() {
  $("cvideo").hidden = true;
  $("cvideo").removeAttribute("src");
  $("conds").replaceChildren(
    ...cur.condensados.map(c => {
      const vb = el("button", { className: "sec sm", textContent: "Ver" });
      vb.onclick = () => {
        $("cvideo").src = c.url;
        $("cvideo").hidden = false;
        $("cvideo").play();
      };
      return el(
        "li",
        {},
        el("span", { className: "n", textContent: c.name }),
        vb,
        el("a", { className: "btn sec sm", href: c.url, download: c.name, textContent: "Descargar" }),
      );
    }),
  );
}

// ---- preguntar (panel único #qpanel: se monta en la pestaña del documento o en la vista de carpeta) ----
let qsel = "";
function setQ(sel) {
  // sel: "id|asr" o "c:carpeta"
  if (sel !== qsel) $("respuestas").replaceChildren();
  qsel = sel;
  $("qpanel").hidden = false;
}
// v: undefined = vídeo del selector; en carpetas, la url del vídeo de esa reunión (null = reunión sin vídeo); n: nombre de la reunión
const ts = (t, v, n) =>
  el("a", {
    className: "ts",
    href: "#",
    textContent: mmss(t) + (n ? " · " + n : ""),
    onclick: e => {
      e.preventDefault();
      if (v !== null) mpSeek(t, v, n);
    },
  });
$("qform").onsubmit = async e => {
  e.preventDefault();
  const q = $("pregunta").value.trim();
  if (!q || !qsel) return;
  $("preguntar-b").disabled = true;
  const box = el("div", { className: "card resp" }, el("h3", { textContent: q })),
    cuerpo = el("div"),
    frag = el("details", { open: true }, el("summary", { textContent: "Fragmentos recuperados" }));
  box.append(cuerpo, frag);
  $("respuestas").prepend(box);
  const estado = el("p", { textContent: "Buscando en la reunión…" });
  cuerpo.append(estado);
  try {
    if (!(await nubeOk("q"))) throw new Error("Cancelado: no se ha enviado nada");
    const r = await fetch("/api/preguntar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sel: qsel, q, gpu: $("usar-gpu").checked, nube: nubeParams("q") }),
    });
    if (!r.ok) throw new Error(det(await r.json().catch(() => ({})), r.statusText));
    const rd = r.body.getReader(),
      dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await rd.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop();
      for (const l of lines.filter(Boolean)) evento(JSON.parse(l), cuerpo, frag, estado);
    }
  } catch (err) {
    cuerpo.append(el("p", { className: "err", textContent: err.message }));
  }
  estado.remove();
  frag.open = false;
  $("preguntar-b").disabled = false;
  $("pregunta").value = "";
};
function evento(ev, cuerpo, frag, estado) {
  if (ev.k === "marca") cuerpo.insertBefore(el("p", {}, el("small", { textContent: "☁ " + ev.text })), estado);
  else if (ev.k === "arranque") estado.textContent = "Arrancando el modelo de lenguaje…";
  else if (ev.k === "candidatos") {
    estado.textContent = "Buscando en la reunión…";
    frag.append(el("ol", {}, ...ev.items.map(i => el("li", {}, ts(i.t, i.v, i.n), " " + i.text))));
  } else if (ev.k === "frase") {
    const quote = el("blockquote");
    ev.cita.forEach((c, n) => quote.append(...(n ? [el("br")] : []), el("span", { className: c.main ? "" : "o" }, ts(c.t, c.v, c.n), " " + c.text)));
    cuerpo.insertBefore(
      el(
        "p",
        ev.kind === "deduce" ? { className: "ded" } : {},
        ...(ev.n ? [el("b", { textContent: ev.n + ": " })] : []),
        ev.ok ? ev.text : "Se dijo: «" + ev.text + "» ",
        ev.ok ? "" : el("small", { textContent: "(texto literal: la frase del modelo no se pudo verificar)" }),
        " ",
        ts(ev.t, ev.v, ev.n),
        ...(ev.mas || []).flatMap(m => [" ", ts(m.t, m.v, m.n)]),
        el("details", {}, el("summary", { textContent: "cita literal" }), quote),
      ),
      estado,
    );
  } else if (ev.k === "pendientes") {
    // pregunta sobre pendientes: lista determinista de los datos de la carpeta, con enlaces al minuto
    const T = {
      es: ["Pendientes abiertos", "Pendiente de", "No hay pendientes abiertos", "plazo"],
      en: ["Open items", "Pending for", "No open items", "due"],
      fr: ["Points ouverts", "En attente pour", "Aucun point ouvert", "échéance"],
      de: ["Offene Punkte", "Offen für", "Keine offenen Punkte", "Frist"],
      pt: ["Pendentes abertos", "Pendente de", "Nenhum pendente aberto", "prazo"],
      it: ["Aperti", "In sospeso per", "Nessuna attività aperta", "scadenza"],
    }[ev.en] || ["Open items", "Pending for", "No open items", "due"];
    cuerpo.insertBefore(
      el(
        "div",
        {},
        el("p", {}, el("b", { textContent: ev.items.length ? (ev.resp ? T[1] + " " + ev.resp : T[0]) + " · " + ev.items.length : T[2] })),
        el(
          "ul",
          { className: "f-lst" },
          ...ev.items.map(p =>
            el("li", {}, p.texto + (ev.resp ? "" : p.resp ? " — " + p.resp : "") + (p.plazo ? " · " + T[3] + ": " + p.plazo : "") + " ", p.mid ? fLink(p) : ""),
          ),
        ),
      ),
      estado,
    );
  } else if (ev.k === "lista") {
    // pregunta de lista sobre el registro del proyecto: entidades con código, responsable y citas al minuto
    cuerpo.insertBefore(
      el(
        "div",
        {},
        el("p", {}, el("b", { textContent: ev.titulo + " · " + ev.n })),
        el(
          "ul",
          { className: "f-lst" },
          ...ev.items.map(p =>
            el(
              "li",
              {},
              (p.codigo ? p.codigo + " · " : "") +
                p.texto +
                (p.respuesta ? " → " + p.respuesta : "") +
                (p.resp ? " — " + p.resp : "") +
                (p.estado ? " · " + p.estado : "") +
                (p.sin_revisar ? " · sin revisar" : "") +
                " ",
              ...p.citas.flatMap(r => [fLink(r), " "]),
            ),
          ),
        ),
        ...(ev.n > ev.items.length ? [el("small", { textContent: "Se muestran " + ev.items.length + " de " + ev.n })] : []),
      ),
      estado,
    );
  } else if (ev.k === "aviso") cuerpo.insertBefore(el("p", {}, el("small", { textContent: ev.text })), estado);
  else if (ev.k === "nada") cuerpo.insertBefore(el("p", {}, el("b", { textContent: ev.text })), estado);
  else if (ev.k === "error") cuerpo.append(el("p", { className: "err", textContent: ev.text }));
}

// ---- importar un documento exportado (.zip) ----
$("b-importar").onclick = async () => {
  $("b-importar").disabled = true;
  try {
    const r = (await post("/api/pick", { tipo: "zip" })).path;
    if (r) {
      const m = await post("/api/importar", { path: r });
      await cargarLista();
      aviso("Documento importado");
      abrir(m.id);
    }
  } catch (e) {
    aviso(e.message);
  } finally {
    $("b-importar").disabled = false;
  }
};

// ---- selector de plantilla («Tipo») y de idioma del formulario ----
async function cargarPlant() {
  const r = await api("/api/plantillas");
  PL = r.plantillas;
  DEF = r.escala;
  IDI = r.idiomas;
  SERIE = r.serie;
  idiomasForm();
}
const plantDe = id => PL.find(t => t.id === id) || PL[0];
const docDe = id => plantDe(id)?.documento?.singular || "documento";
function idiomasForm() {
  const v = $("idioma").value;
  $("idioma").replaceChildren(
    new Option("Según la plantilla", ""),
    ...Object.entries(IDI)
      .filter(([k]) => k !== "reunión")
      .map(([k, n]) => new Option(cap(n), k)),
  );
  $("idioma").value = v;
}
function plantForm(id) {
  // selector «Tipo»: en modo simple, solo los perfiles de uso elegidos (+ el de la carpeta); en avanzado, todos
  const ok = simple() ? new Set([...AJ.perfil_uso, id]) : null,
    l = PL.filter(t => !ok || ok.has(t.id));
  $("plantilla").replaceChildren(...l.map(t => new Option(t.nombre, t.id)));
  $("plantilla").value = plantDe(id)?.id || "acta";
  $("plantilla").onchange();
}
$("plantilla").onchange = () => {
  const t = plantDe($("plantilla").value);
  if (!t) return;
  anBoton();
  $("info-plant").textContent =
    t.descripcion + (t.nube_permitida ? "" : " Solo en este equipo (datos especialmente protegidos: RGPD art. 9 y secreto profesional).");
  if (typeof nubePlantilla === "function") nubePlantilla(t);
  $("idioma").options[0].textContent = "Según la plantilla (" + (IDI[t.idioma_acta] || t.idioma_acta) + ")";
  $("idioma").onchange();
};
$("idioma").onchange = () => {
  // aviso: fuera de es/en conviene un modelo mayor
  const t = plantDe($("plantilla").value),
    i = $("idioma").value || t?.idioma_acta || "reunión";
  $("hint-idioma").textContent =
    i === "eu"
      ? "Para euskera se recomienda la calidad Muy alta."
      : ["reunión", "es", "en"].includes(i)
        ? ""
        : "Para este idioma se recomienda Alta+ o superior.";
  $("hint-idioma").hidden = !$("hint-idioma").textContent;
};

// ---- arranque (lo llama el último script, cuando ya está todo definido) ----
function arranque() {
  cargarLista()
    .then(() => {
      sondear();
      plantForm("acta");
      const m = cur && vistaAct === "res" && todas.find(x => x.id === cur.id);
      if (m) {
        cur.m = m;
        $("cab-titulo").textContent = m.label;
        document.title = m.label + " · Actas";
      } // abierto por enlace antes de cargar la lista
    })
    .catch(() => {});
  setInterval(sondear, 2000);
}

// ---- reproductor flotante (único <video>: no se recrea al cambiar de pestaña, así no se corta) ----
const MP = () => $("mp"),
  VID = () => $("vvideo"),
  esAudio = u => /\.(mp3|m4a|wav|ogg|opus|flac|aac)$/i.test(u || "");
function mpCargar(url, titulo, audio) {
  const v = VID(),
    m = MP();
  if (!v.src.endsWith(url)) v.src = url;
  m.classList.toggle("audio", audio);
  $("vslot").classList.toggle("audio", audio);
  $("mp-t").textContent = titulo || "";
  $("mp-pip").hidden = audio || !document.pictureInPictureEnabled;
  m.hidden = false;
  m.classList.remove("min");
  ubicar();
}
function mpCerrar() {
  VID().pause();
  MP().hidden = true;
  if (document.pictureInPictureElement) document.exitPictureInPicture().catch(() => {});
}
function mpSeek(t, url, nombre) {
  const v = VID(),
    go = () => {
      v.currentTime = Math.floor(t);
      v.play().catch(() => {});
    };
  if (url && !v.src.endsWith(url)) {
    mpCargar(url, nombre, esAudio(url));
    v.addEventListener("loadedmetadata", go, { once: true });
    v.src = url;
  } else {
    MP().hidden = false;
    MP().classList.remove("min");
    ubicar();
    go();
  }
}
function ubicar() {
  // en las pestañas Vídeo/Audio y Preguntar el reproductor se coloca sobre su hueco; en las demás flota abajo a la derecha
  const m = MP(),
    slot =
      vistaAct !== "res"
        ? null
        : tabAct === "p-video" && !$("p-video").hidden
          ? $("vslot")
          : tabAct === "p-preg" && !$("p-preg").hidden && !$("qbox").hidden
            ? $("qslot")
            : null;
  m.classList.toggle("full", !!slot);
  for (const s of [$("vslot"), $("qslot")]) if (s !== slot) s.style.height = "";
  if (slot) {
    const r = slot.getBoundingClientRect();
    Object.assign(m.style, { left: r.left + scrollX + "px", top: r.top + scrollY + "px", width: r.width + "px" });
    slot.style.height = m.offsetHeight + "px";
  } else if (!m.dataset.arrastrado) Object.assign(m.style, { left: "", top: "", width: "" });
}
addEventListener("resize", ubicar);
// Fuente de una imagen: las descripciones se guardan solas al dejar de escribir («Guardado ✓»; el botón queda de respaldo)
let fuT;
$("p-fuente").addEventListener("input", e => {
  const w = e.target.closest(".fu-img");
  if (!w || e.target.tagName !== "TEXTAREA") return;
  const id = cur.id,
    [du, dia] = w.querySelectorAll("textarea"),
    ok = w.querySelector(".fu-ok") || w.querySelector(".pri").after(el("span", { className: "fu-ok muted", role: "status" })) || w.querySelector(".fu-ok");
  const ver = w.querySelector(".fu-ver");
  if (ver && e.target === dia && !dia.classList.contains("abierta")) ver.hidden = dia.scrollHeight <= dia.clientHeight + 2; // «Ver más» solo si la descripción de la IA desborda las 5 líneas
  ok.textContent = "Guardando…";
  clearTimeout(fuT);
  fuT = setTimeout(
    () =>
      post("/api/imagen/" + id, { descripcion: du.value, descripcion_ia: dia.value }).then(
        () => (ok.textContent = "Guardado ✓"),
        x => (ok.textContent = "No se pudo guardar: " + x.message),
      ),
    800,
  );
});
new ResizeObserver(() => !MP().hidden && ubicar()).observe(MP()); // el vídeo cambia de alto al cargar: el hueco lo sigue
$("mp-x").onclick = mpCerrar;
$("mp-min").onclick = () => {
  MP().classList.toggle("min");
  $("mp-min").setAttribute("aria-label", MP().classList.contains("min") ? "Restaurar" : "Minimizar");
};
$("mp-pip").onclick = () =>
  (document.pictureInPictureElement ? document.exitPictureInPicture() : VID().requestPictureInPicture()).catch(e =>
    aviso("No se pudo abrir imagen en imagen: " + e.message),
  );
$("mp-bar").onpointerdown = e => {
  // arrastrar (opcional) desde la barra
  const m = MP();
  if (m.classList.contains("full") || e.target.closest("button")) return;
  const r = m.getBoundingClientRect(),
    dx = e.clientX - r.left,
    dy = e.clientY - r.top;
  $("mp-bar").setPointerCapture(e.pointerId);
  const mv = ev => {
    m.dataset.arrastrado = 1;
    Object.assign(m.style, {
      right: "auto",
      bottom: "auto",
      left: Math.max(0, Math.min(innerWidth - 60, ev.clientX - dx)) + "px",
      top: Math.max(0, Math.min(innerHeight - 40, ev.clientY - dy)) + "px",
    });
  };
  const up = () => {
    $("mp-bar").removeEventListener("pointermove", mv);
    $("mp-bar").removeEventListener("pointerup", up);
  };
  $("mp-bar").addEventListener("pointermove", mv);
  $("mp-bar").addEventListener("pointerup", up);
};
// dentro de la app el documento se lee como en design/DocResumen.dc.html (solo la vista: exportar no cambia)
const DOC_CSS =
  "#side{display:none!important}main{padding-bottom:32px!important;display:block!important;max-width:960px!important}" +
  ":root{--bg2:#f8f9fb}@media(prefers-color-scheme:dark){:root{--bg2:#1a1f26}}body{max-width:none;padding:28px 36px}@media(max-width:700px){body{padding:20px 16px}}" +
  "h2{scroll-margin-top:var(--sm,16px)}h1{font-size:26px;line-height:1.25}h2{font-size:20px}h3{font-size:17px}h1,h2,h3,h4,b,strong,th{font-weight:600}.meta+h2{font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);margin-top:28px}.meta+h2+p{font-size:17px;line-height:1.6}" +
  "h2+ul{list-style:none;padding:0;display:flex;flex-direction:column;gap:10px}h2+ul>li{background:var(--bg2);border-radius:10px;padding:12px 16px}" +
  "table{border:1px solid var(--line2);border-radius:10px;border-collapse:separate;border-spacing:0;overflow:hidden}th{background:var(--bg2);padding:10px}td{padding:12px 10px}" +
  "details{border:1px solid var(--line2);border-radius:10px;padding:12px 16px;margin:8px 0}summary{cursor:pointer;font-weight:600;min-height:28px}" +
  ".ts.cita{border-radius:999px;padding:0 7px;font-size:12px;font-weight:600;white-space:nowrap;cursor:help}";
// «En este documento»: los apartados (h2) del documento con cuántos elementos tienen; se marca el que se está leyendo
function docIndice(d) {
  const hs = [...d.querySelectorAll("h2")],
    nav = $("doc-i");
  nav.hidden = hs.length < 3;
  const its = hs.map((h, i) => {
    h.id ||= "s" + i;
    const nx = h.nextElementSibling,
      n = !nx ? 0 : /^(UL|OL)$/.test(nx.tagName) ? nx.children.length : nx.tagName === "TABLE" ? nx.querySelectorAll("tr").length - 1 : 0;
    return el(
      "a",
      {
        href: "#" + h.id,
        onclick: e => {
          e.preventDefault();
          h.scrollIntoView({ behavior: "smooth", block: "start" });
        },
      },
      el("span", { textContent: h.textContent }),
      el("span", { className: "c", textContent: n > 0 ? n : "" }),
    );
  });
  nav.replaceChildren(
    el("div", { className: "t", textContent: "En este documento" }),
    ...its,
    ...(cur?.video
      ? [
          el(
            "p",
            { className: "doc-n" },
            "Cada ",
            el("span", { className: "ts", textContent: "mm:ss" }),
            " salta a ese momento del " + (cur.audio ? "audio" : "vídeo") + ".",
          ),
        ]
      : []),
  );
  // bajo 1100 px el índice es un desplegable encima del documento
  const sel =
    $("doc-isel") ||
    document.querySelector("#p-acta .dbar").appendChild(el("select", { id: "doc-isel", className: "doc-isel", ariaLabel: "Ir a un apartado" }));
  sel.hidden = hs.length < 3;
  sel.replaceChildren(...hs.map((h, i) => new Option(h.textContent, i)));
  sel.onchange = () => hs[sel.value]?.scrollIntoView({ behavior: "smooth", block: "start" });
  const f = $("acta-frame"); // con data-pag el iframe no scrollea (lo hace la página): la posición de cada apartado es la del iframe + la suya, bajo la cabecera fija
  const spy = () => {
    const o = f.hasAttribute("data-pag") ? f.getBoundingClientRect().top - document.querySelector(".top").offsetHeight : 0;
    let k = 0;
    hs.forEach((h, i) => {
      if (h.getBoundingClientRect().top + o < 90) k = i;
    });
    its.forEach((a, i) => a.setAttribute("aria-current", i === k ? "true" : "false"));
    sel.value = k;
  };
  d.defaultView.addEventListener("scroll", spy, { passive: true });
  docSpy = spy;
  spy();
}
// citas de documentos: «[§ Comité · Proyecto · 28 de octubre]» → chip «§1» (cada apartado, su número; la etiqueta entera en el title); «[p. 12]» → «p. 12».
// En documentos de texto la «Duración» de la cabecera no significa nada: fuera
function citasCortas(d) {
  const n = new Map();
  for (const t of d.querySelectorAll(".ts")) {
    const m = /^\[(§ .+|p\. ?\d.*)\]$/.exec(t.textContent.trim());
    if (!m) continue;
    t.dataset.full = t.textContent.trim();
    t.title = m[1];
    t.classList.add("cita");
    t.textContent = m[1][0] === "§" ? "§" + (n.get(m[1]) || n.set(m[1], n.size + 1).get(m[1])) : m[1];
  }
  const a = cur?.actas.find(x => x.name === ver),
    me = d.querySelector(".meta");
  if (me?.firstChild && cur.importadas[a?.asr]?.tipo) me.firstChild.textContent = me.firstChild.textContent.replace(/^Duración [\d:]+ · /, "");
}
// un solo scroll, nunca doble barra. Si bajo la cabecera, las pestañas y los avisos quedan ≥ DOC_MIN px, el documento mide lo que queda de ventana y scrollea él;
// si no (ventana baja o móvil ≤700 px) el iframe crece hasta su contenido (data-pag) y scrollea la página. offsetTop y no getBoundingClientRect: la animación
// de entrada de la vista aplica transform y falsearía la medida.
const DOC_MIN = 420;
function docAlto() {
  const f = $("acta-frame");
  if (!f.offsetParent) return;
  const pos = n => {
      let t = 0;
      for (; n; n = n.offsetParent) t += n.offsetTop;
      return t;
    },
    pg = f.closest(".page"),
    movil = matchMedia("(max-width:700px)").matches;
  const debajo = pg ? pos(pg) + pg.offsetHeight - pos(f) - f.offsetHeight : 16; // lo que queda bajo el iframe (relleno de la página), medido: no se supone
  const hay = innerHeight - pos(f) - debajo;
  let d;
  try {
    d = f.contentDocument;
  } catch {}
  const pag = (movil || hay < DOC_MIN) && d?.body && d.location.href !== "about:blank"; // sin documento cargado aún, vale el alto de ventana / el CSS
  f.toggleAttribute("data-pag", !!pag);
  if (d?.body) d.documentElement.style.setProperty("--sm", (pag ? document.querySelector(".top").offsetHeight + 16 : 16) + "px"); // el apartado al que se salta queda bajo la cabecera fija
  f.style.height = pag
    ? Math.ceil(d.documentElement.getBoundingClientRect().height) + f.offsetHeight - f.clientHeight + "px"
    : movil
      ? ""
      : Math.max(0, hay) + "px";
}
const docRO = new ResizeObserver(() => requestAnimationFrame(docAlto)); // el contenido del documento (imágenes, <details>, ancho) cambia su alto
addEventListener("resize", docAlto);
new ResizeObserver(() => requestAnimationFrame(docAlto)).observe(document.body); // lo que hay encima crece o se encoge (aviso de dudosos, versiones…); en el siguiente cuadro para no encadenar avisos del observador
let docSpy;
addEventListener("scroll", () => docSpy?.(), { passive: true }); // con data-pag scrollea la página, no el iframe
// el documento (iframe, mismo origen): su propio reproductor se oculta y sus marcas [mm:ss] mueven el de la app
$("acta-frame").onload = () => {
  docAlto();
  let d;
  try {
    d = $("acta-frame").contentDocument;
  } catch {
    return;
  }
  if (!d || !d.body || d.location.href === "about:blank") return;
  d.head.append(Object.assign(d.createElement("style"), { textContent: DOC_CSS }));
  docIndice(d);
  citasCortas(d);
  docRO.disconnect();
  docRO.observe(d.documentElement); // avisa al observar: mide con el CSS ya puesto
  d.addEventListener(
    "click",
    e => {
      const a = e.target.closest("[data-t]");
      if (!a) return;
      if (!cur?.video) {
        e.preventDefault();
        e.stopImmediatePropagation();
        citaIr(+a.dataset.t, (a.dataset.full || a.textContent).trim());
        return;
      } // PDF, texto: a la pestaña Fuente
      e.preventDefault();
      e.stopImmediatePropagation();
      if (d.getElementById("big")) d.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); // cierra el visor de capturas
      mpSeek(+a.dataset.t, cur.videourl, cur.m.label);
    },
    true,
  );
};

// ---- editar y exportar el documento (#acta-acciones es el gancho de la barra) ----
let editando = false;
const FMT = [
  ["docx", "Word (.docx)"],
  ["pdf", "PDF"],
  ["md", "Markdown"],
  ["obsidian", "Obsidian (.zip)"],
  ["notion", "Notion (.zip)"],
  ["ics", "Calendario (.ics)"],
  ["csv_todoist", "Tareas · Todoist (.csv)"],
  ["csv_jira", "Tareas · Jira (.csv)"],
  ["csv_azure", "Tareas · Azure DevOps (.csv)"],
  ["csv_planner", "Tareas · Planner (.csv)"],
  ["srt", "Subtítulos (.srt)"],
  ["vtt", "Subtítulos (.vtt)"],
];
async function descargar(fmt, extra = "") {
  const est = $("ex-est")?.value,
    q = "fmt=" + fmt + (est && est !== "auto" ? "&estilo=" + encodeURIComponent(est === "none" ? "" : est) : "") + extra;
  const r = await fetch(`/api/exportar/${cur.id}/${ver}?${q}`);
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    if (r.status === 409 && fmt === "pdf") {
      window.open(`/api/vista/${cur.id}/${ver}?print=1` + (/anon=1/.test(extra) ? "&anon=1" : "") + (/dudas=1/.test(extra) ? "&dudas=1" : ""));
      aviso(j.detail || "Usa Imprimir → Guardar como PDF");
      return;
    }
    throw new Error(j.detail || r.statusText);
  }
  const nombre = decodeURIComponent((/filename\*=UTF-8''(.+)/.exec(r.headers.get("Content-Disposition") || "") || [])[1] || "documento." + fmt);
  const a = el("a", { href: URL.createObjectURL(await r.blob()), download: nombre });
  document.body.append(a);
  a.click();
  a.remove();
  aviso("Descargado: " + nombre);
}
function pintarAcciones(a) {
  const box = $("acta-acciones");
  box.hidden = false;
  if (editando) {
    box.replaceChildren(
      el(
        "span",
        { className: "ed-bar" },
        "Editando: haz clic en cualquier texto del documento.",
        el("button", {
          className: "pri sm",
          textContent: "Guardar",
          onclick: fallo(async () => {
            const c = $("acta-frame").contentWindow.cambios();
            if (!Object.keys(c).length) {
              aviso("No hay cambios");
              return;
            }
            await api(`/api/doc/${cur.id}/${ver}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ cambios: c }) });
            editando = false;
            await abrir(cur.id, ver, true);
            aviso("Cambios guardados");
          }),
        }),
        el("button", {
          className: "sec sm",
          textContent: "Descartar",
          onclick: () => {
            editando = false;
            cambiarActa();
          },
        }),
      ),
    );
    return;
  }
  // menú Exportar (design/Documento.dc.html): formatos de documento | tareas, notas y subtítulos | opciones
  const sep = () => el("div", { className: "sep", role: "separator" }),
    mas = el("div", { className: "pop-g", hidden: simple() }),
    ex = el("div", { role: "group", ariaLabel: "Exportar" });
  const cierra = () => {
    $("d-exp").open = $("d-mas").open = false;
  };
  const item = (f, t, extra) =>
    el("button", {
      type: "button",
      role: "menuitem",
      textContent: t,
      onclick: fallo(async () => {
        cierra();
        await exportar(f, extra());
      }),
    });
  const hab = el("input", { type: "checkbox", id: "ex-hab" }),
    evt = el("input", { type: "checkbox", id: "ex-evt" });
  mas.append(
    sep(),
    ...["ics", "csv_todoist", "csv_jira", "csv_azure", "csv_planner", "obsidian", "notion", "srt", "vtt"]
      .map(f => FMT.find(x => x[0] === f))
      .map(([f, t]) => item(f, t, () => (f === "srt" || f === "vtt" ? (hab.checked ? "&hablantes=1" : "") : f === "ics" && evt.checked ? "&evento=1" : ""))),
    el("label", { className: "check" }, evt, "Calendario: como un solo evento"),
    el("label", { className: "check" }, hab, "Subtítulos: con quien habla"),
  );
  ex.append(
    ...(ESTILOS.length
      ? [
          el("div", { className: "t", textContent: "Estilo" }),
          (s => {
            s.append(new Option("El de la carpeta", "auto"), new Option("Sin estilo", "none"), ...ESTILOS.map(e => new Option(e.nombre, e.id)));
            return s;
          })(el("select", { id: "ex-est", ariaLabel: "Estilo de organización" })),
          sep(),
        ]
      : []),
    ...FMT.slice(0, 3).map(([f, t]) => item(f, t, () => "")),
    ...(simple()
      ? [
          el("button", {
            type: "button",
            className: "link mas",
            textContent: "Más formatos…",
            onclick: e => {
              mas.hidden = false;
              e.currentTarget.remove();
            },
          }),
        ]
      : []),
    mas,
    sep(),
    el(
      "label",
      { className: "check" },
      el("input", {
        type: "checkbox",
        id: "ex-anon",
        checked: anonOn(),
        onchange: e => {
          anonSel = e.target.checked;
          zipAnon();
        },
      }),
      "Anonimizar",
    ),
    el("label", { className: "check" }, el("input", { type: "checkbox", id: "ex-dud" }), "Incluir marcas de confianza"),
    ...(window.Descargar
      ? [
          sep(),
          el("button", {
            type: "button",
            role: "menuitem",
            textContent: "Descargar varias cosas…",
            onclick: () => {
              cierra();
              Descargar.abrir({ docs: [cur.id + "/" + ver] });
            },
          }),
        ]
      : []),
  );
  // Editar, Correo y Restaurar viven en el menú ⋯ de la cabecera (index.html)
  $("d-editar").onclick = () => {
    tab("p-acta");
    editando = true;
    $("acta-frame").src = `/api/vista/${cur.id}/${ver}?editar=1`;
    pintarAcciones(a);
  };
  $("d-correo").onclick = abrirCorreo;
  $("d-rest").hidden = !a.editado;
  $("d-rest").onclick = fallo(async () => {
    if (!confirm("¿Volver al texto original? Se pierden tus ediciones de esta versión.")) return;
    await post(`/api/doc/${cur.id}/${ver}/restaurar`);
    await abrir(cur.id, ver, true);
    aviso("Original restaurado");
  });
  box.replaceChildren();
  box.hidden = true;
  $("d-exp-l").replaceChildren(ex); // Exportar vive en ⋯ (submenú plegable)
}
document.addEventListener("click", e =>
  document.querySelectorAll("details.menu[open]").forEach(d => {
    if (!d.contains(e.target)) d.open = false;
  }),
);

// ---- inicio: buscar y preguntar ----
