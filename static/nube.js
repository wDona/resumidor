// Modelos en la nube (opcional, apagado por defecto): enlace discreto en «Nuevo» y en «Preguntar» que despliega este panel. Ver nube.py.
// Abierto = se usa en esa acción; cerrado = todo en este equipo. La clave va al llavero del sistema: aquí solo se ve enmascarada.
const NB = {info: null, sel: {proveedor: "", modelo: "", url: "", anonimizar: false}, paneles: {}};
const nubeCarga = () => api("/api/nube").then(i => { NB.info = i; if (!NB.sel.anonimizar && !NB.visto) { NB.sel.anonimizar = !!i.anonimizar_defecto; NB.visto = true; } return i; });
const nubeProv = id => id.startsWith("cli:") ? NB.info.clis.find(c => c.id === id) : NB.info.proveedores.find(p => p.id === id);

function nubePanel(host, clave, pedirEstimacion) {
  const P = {abierto: false, host, clave};
  NB.paneles[clave] = P;
  P.pintar = async () => {
    host.replaceChildren(); if (!P.abierto) return;
    const i = NB.info || await nubeCarga(), s = NB.sel;
    if (!s.proveedor || (s.proveedor.startsWith("cli:") && !i.clis.some(c => c.id === s.proveedor))) s.proveedor = i.clis.length ? i.clis[0].id : "openai";
    const cli = s.proveedor.startsWith("cli:"), p = nubeProv(s.proveedor) || {}, sinURL = !cli && !["propio", "azure"].includes(s.proveedor);
    const sel = el("select", {onchange: () => { s.proveedor = sel.value; s.modelo = nubeProv(s.proveedor)?.modelo || ""; s.url = ""; P.pintar(); }});
    if (i.clis.length) { const g2 = el("optgroup", {label: "Suscripción (CLI instalada)"}); i.clis.forEach(x => g2.append(new Option(x.nombre, x.id))); sel.append(g2); }
    const g1 = el("optgroup", {label: "API con clave"}); sel.append(g1); i.proveedores.forEach(x => g1.append(new Option(x.nombre, x.id)));
    sel.value = s.proveedor;
    const kids = [
      el("p", {style: "margin:0 0 4px"}, el("b", {textContent: "☁ " + i.envia})),
      el("p", {style: "margin:0 0 12px"}, el("b", {textContent: "🔒 " + i.nunca})),
      el("div", {className: "field"}, el("label", {textContent: "Proveedor"}), sel)];
    const redet = el("button", {type: "button", className: "link", textContent: i.clis.length ? "Volver a detectar" : "Detectar de nuevo", onclick: async () => { await nubeCarga().catch(() => {}); P.pintar(); }});
    if (!i.clis.length) kids.push(el("small", {textContent: "¿Tienes suscripción de Claude o ChatGPT? Instala el programa (claude o codex), inicia sesión en él y pulsa «Detectar de nuevo». Actas no detecta ninguno ahora mismo en su PATH."}), redet);
    if (cli) {
      kids.push(el("small", {textContent: "Usa tu suscripción: se aprovecha tu sesión ya iniciada en el programa instalado. Sin clave de API ni modelo; el consumo va a tu plan."}), el("small", {className: "warn", textContent: i.cli_aviso}), redet);
    } else {
      if (!sinURL) {
        const u = el("input", {value: s.url || p.url || "", placeholder: s.proveedor === "azure" ? "https://TU-RECURSO.openai.azure.com/openai/v1" : "http://localhost:11434/v1", oninput: () => { s.url = u.value.trim(); }});
        u.onchange = () => post("/api/nube/url", {proveedor: s.proveedor, url: u.value}).catch(() => {});
        kids.push(el("div", {className: "field"}, el("label", {textContent: "Dirección del servidor"}), u));
      }
      const k = el("input", {type: "password", autocomplete: "off", placeholder: s.proveedor === "propio" ? "Clave (si la pide)" : "Pega tu clave de API"});
      const gk = el("button", {type: "button", className: "sec sm", textContent: "Guardar clave", onclick: async () => {
        try { NB.info = await post("/api/nube/clave", {proveedor: s.proveedor, clave: k.value}); k.value = ""; P.pintar(); } catch (e) { aviso(e.message); } }});
      kids.push(el("div", {className: "field"}, el("label", {textContent: "Clave de API"}),
        p.clave ? el("div", {className: "row"}, el("span", {textContent: "Guardada en el llavero del sistema: " + p.clave}),
          el("button", {type: "button", className: "link", textContent: "Quitar", onclick: async () => { NB.info = await post("/api/nube/clave", {proveedor: s.proveedor, clave: ""}); P.pintar(); }}))
          : el("div", {className: "row"}, k, gk),
        el("small", {textContent: "Solo se guarda en el llavero de tu sistema operativo; nunca en ficheros ni en el registro."})));
      const m = el("input", {value: s.modelo, placeholder: "Nombre del modelo", oninput: () => { s.modelo = m.value.trim(); P.estimar(); }}), dl = el("datalist", {id: "nb-m-" + clave});
      m.setAttribute("list", dl.id);
      const cm = el("button", {type: "button", className: "sec sm", textContent: "Cargar lista", onclick: async () => {
        cm.disabled = true; const r = await post("/api/nube/modelos", {proveedor: s.proveedor, url: s.url}).catch(() => ({modelos: []}));
        dl.replaceChildren(...r.modelos.map(x => new Option(x))); cm.disabled = false; aviso(r.modelos.length ? r.modelos.length + " modelos" : "El proveedor no da la lista: escribe el nombre del modelo"); }});
      kids.push(el("div", {className: "field"}, el("label", {textContent: "Modelo"}), el("div", {className: "row"}, m, dl, cm)));
    }
    const an = el("input", {type: "checkbox", checked: s.anonimizar, onchange: () => { s.anonimizar = an.checked; }});
    kids.push(el("label", {className: "check"}, an, el("span", {textContent: " Anonimizar antes de enviar"})),
      el("small", {textContent: "Se sustituyen: nombres conocidos" + (NB.info?.anon_modelo ? ", nombres detectados por el modelo local" : "") + ", DNI, teléfonos, emails, IBAN, tarjetas, matrículas. Revisa: nombres que no conozca la app pueden pasar. Se devuelven en claro al recibir la respuesta."}));
    P.est = el("small", {style: "margin-top:10px"}); P.precio = el("small");
    kids.push(P.est, P.precio, el("small", {textContent: "Con la nube no se usa el selector de calidad. Cada petición sale de este equipo hacia el proveedor elegido."}));
    host.append(el("div", {className: "card", style: "margin-top:16px"}, el("h3", {textContent: "Modelo en la nube", style: "margin-top:0"}), ...kids));
    P.estimar();
  };
  P.estimar = async () => {
    if (!P.est || !pedirEstimacion) return;
    const s = NB.sel, d = pedirEstimacion(); P.est.textContent = ""; P.precio.replaceChildren();
    if (!d) { P.est.textContent = "El coste estimado aparece al elegir el vídeo o la transcripción."; return; }
    try {
      const e = await post("/api/nube/estimar", {...d, modelo: s.modelo});
      P.est.textContent = "Estimación: ~" + e.entrada.toLocaleString("es") + " tokens enviados y ~" + e.salida.toLocaleString("es") + " recibidos" + (e.coste != null ? " · ≈ " + e.coste.toLocaleString("es") + " USD" : " · sin precio configurado") + ".";
      if (s.modelo && !s.proveedor.startsWith("cli:")) {
        const pr = NB.info.precios[s.modelo] || ["", ""], a = el("input", {type: "number", step: "any", min: 0, value: pr[0], style: "width:6em"}), b = el("input", {type: "number", step: "any", min: 0, value: pr[1], style: "width:6em"});
        const g = el("button", {type: "button", className: "link", textContent: "Guardar precio", onclick: async () => { NB.info = await post("/api/nube/precios", {modelo: s.modelo, entrada: a.value, salida: b.value}); P.estimar(); }});
        P.precio.append("Precio de ", el("b", {textContent: s.modelo}), " (USD por millón de tokens): entrada ", a, " salida ", b, " ", g);
      }
    } catch (err) { P.est.textContent = err.message; }
  };
  return P;
}

// enlace discreto + panel; devuelve el panel. `enlace` es el contenedor donde va el <button class="link">
function nubeEnlace(enlace, host, clave, pedirEstimacion) {
  const P = nubePanel(host, clave, pedirEstimacion), b = el("button", {type: "button", className: "link", textContent: "Usar un modelo en la nube…"});
  b.onclick = async () => { P.abierto = !P.abierto; b.textContent = P.abierto ? "Usar solo este equipo" : "Usar un modelo en la nube…"; if (!NB.info) await nubeCarga().catch(() => {}); P.pintar(); };
  P.cerrar = () => { P.abierto = false; b.textContent = "Usar un modelo en la nube…"; host.replaceChildren(); };
  enlace.replaceChildren(b); enlace.hidden = false; P.enlace = enlace;
  return P;
}

// configuración a enviar (null = en este equipo); lanza si falta el modelo
function nubeParams(clave) {
  const P = NB.paneles[clave]; if (!P?.abierto || document.body.classList.contains("sin-nube")) return null;
  const s = NB.sel; if (!s.proveedor.startsWith("cli:") && !s.modelo) throw new Error("Nube: elige el modelo");
  return {proveedor: s.proveedor, modelo: s.modelo, url: s.url, anonimizar: s.anonimizar};
}

// primera vez con este proveedor: confirmación explícita (<dialog>)
async function nubeOk(clave) {
  const c = nubeParams(clave); if (!c) return true;
  const p = nubeProv(c.proveedor); if (p?.confirmado) return true;
  return new Promise(res => {
    const d = el("dialog", {}), cerrar = ok => { d.close(); d.remove(); res(ok); };
    d.append(el("h2", {textContent: "Enviar a " + (p?.nombre || c.proveedor) + "?"}),
      el("p", {textContent: "Es la primera vez que usas este proveedor. Para redactar, su servicio recibirá por internet:"}),
      el("p", {}, el("b", {textContent: "☁ " + NB.info.envia})),
      el("p", {}, el("b", {textContent: "🔒 " + NB.info.nunca})),
      el("small", {textContent: c.proveedor.startsWith("cli:") ? NB.info.cli_aviso : "Revisa las condiciones y la política de datos del proveedor. Con datos personales o confidenciales, comprueba que tu organización lo permite."}),
      el("div", {className: "row"}, el("button", {className: "pri", type: "button", textContent: "Entiendo, enviar", onclick: async () => {
        NB.info = await post("/api/nube/confirmar", {proveedor: c.proveedor, modelo: c.modelo}); cerrar(true); }}),
        el("button", {className: "sec", type: "button", textContent: "Cancelar", onclick: () => cerrar(false)})));
    d.oncancel = () => res(false); document.body.append(d); d.showModal();
  });
}

// ---- puntos de enganche ----
const nubeForm = nubeEnlace($("n-nube"), $("nube-f"), "f", () => {
  if (typeof reuse !== "undefined" && reuse) return {reuse: reuse.id, asr: reuse.asr};
  if (rutaTr) return {transcripcion: rutaTr};
  return ruta ? {video: ruta} : null;
});
const nubeQ = nubeEnlace($("nube-q-l"), $("nube-q"), "q", null);
function nubePlantilla(t) {  // plantilla que no admite la nube (consulta profesional): sin enlace ni panel
  const ok = !t || t.nube_permitida !== false;
  nubeForm.enlace.hidden = !ok; if (!ok) nubeForm.cerrar();
}
