// QA headless: carga rutas de la app, recoge errores JS/consola y hace capturas.
// uso: node cdp.mjs <baseURL> <outDir> <wsDebuggerURL> [rutas separadas por coma] [ancho] [oscuro]
import { writeFileSync } from "node:fs";

const [base, out, wsUrl, rutasArg, anchoArg, oscuro] = process.argv.slice(2);
const rutas = (rutasArg || "#/").split(",");
const ancho = +(anchoArg || 1440);
const ws = new WebSocket(wsUrl);
let id = 0;
const pend = new Map(), errores = [];
const send = (method, params = {}, sessionId) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params, sessionId })); });
ws.onmessage = e => {
  const m = JSON.parse(e.data);
  if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result ?? { error: m.error }); pend.delete(m.id); }
  if (m.method === "Runtime.exceptionThrown") errores.push("EXC " + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text).split("\n").slice(0, 2).join(" | "));
  if (m.method === "Runtime.consoleAPICalled" && ["error", "warning"].includes(m.params.type)) errores.push("CON " + m.params.args.map(a => a.value ?? a.description).join(" ").slice(0, 200));
  if (m.method === "Network.responseReceived" && m.params.response.status >= 400) errores.push(`HTTP ${m.params.response.status} ${m.params.response.url.replace(base, "")}`);
};
await new Promise(r => ws.onopen = r);
const { targetId } = await send("Target.createTarget", { url: "about:blank" });
const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
const s = (m, p) => send(m, p, sessionId);
await s("Runtime.enable"); await s("Network.enable"); await s("Network.setCacheDisabled",{cacheDisabled:true}); await s("Page.enable");
await s("Emulation.setDeviceMetricsOverride", { width: ancho, height: 900, deviceScaleFactor: 1, mobile: ancho < 600 });
await s("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: oscuro ? "dark" : "light" }] });
const espera = ms => new Promise(r => setTimeout(r, ms));
const informe = [];
for (const r of rutas) {
  errores.length = 0;
  const [ruta, accion] = r.split("|");
  await s("Page.navigate", { url: "about:blank" }); await espera(200);
  await s("Page.navigate", { url: base + "/" + ruta });
  await espera(2500);
  if (accion) { await s("Runtime.evaluate", { expression: accion, awaitPromise: true }); await espera(1500); }
  const info = await s("Runtime.evaluate", { expression: globalThis.process.env.EV ? process.env.EV : `JSON.stringify({h: location.hash, vis: [...document.querySelectorAll("main section, .view, [id^=v-]")].filter(e => e.offsetParent).map(e => e.id).slice(0,6), txt: document.body.innerText.length, ovf: document.documentElement.scrollWidth > innerWidth})`, returnByValue: true });
  const shot = await s("Page.captureScreenshot", { format: "png" });
  const nombre = (ruta + (accion ? "_" + accion.slice(0, 12) : "")).replace(/[^a-z0-9]+/gi, "_").replace(/^_|_$/g, "") || "inicio";
  writeFileSync(`${out}/${nombre}-${ancho}${oscuro ? "-dark" : ""}.png`, Buffer.from(shot.data, "base64"));
  informe.push(`${r.slice(0, 60)} → ${info.result?.value} ${errores.length ? "\n   " + [...new Set(errores)].join("\n   ") : ""}`);
}
console.log(informe.join("\n"));
await send("Target.closeTarget", { targetId });
ws.close();
