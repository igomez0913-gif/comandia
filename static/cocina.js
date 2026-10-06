/* Comandia · pantalla de cocina y barra (KDS): comandas por estación con sus estados. Se actualiza sola cada pocos segundos. */

const KITCHEN = { station: "", comandas: [], known: null, root: null, stations: ["cocina", "barra", "parrilla", "postres", "otra"] };
const NEXT_KDS = { pendiente: "preparando", preparando: "listo", listo: "servido" };
const NEXT_LABEL = { pendiente: "Empezar", preparando: "Listo", listo: "Entregado" };

async function renderKitchen(root) {
  KITCHEN.root = root; KITCHEN.known = null;
  try { KITCHEN.station = localStorage.getItem("comandia_kds_station") || ""; } catch (e) { KITCHEN.station = ""; }
  await loadKitchen();
  paintKitchen();
  const tick = setInterval(async () => { if (document.hidden || $("#modal").classList.contains("open")) return; try { await loadKitchen(); paintKitchen(); } catch (e) { /* sin conexión: se reintenta */ } }, 4000);
  onLeave(() => clearInterval(tick));
}

async function loadKitchen() {
  const r = await api("/api/kitchen" + (KITCHEN.station ? "?station=" + encodeURIComponent(KITCHEN.station) : ""));
  const ids = new Set(r.comandas.map((c) => c.id));
  if (KITCHEN.known && r.comandas.some((c) => !KITCHEN.known.has(c.id) && c.status === "Pendiente")) beep(784, 260);  // llegó una comanda nueva
  KITCHEN.known = ids;
  KITCHEN.comandas = r.comandas;
}

function ageClass(min) { return min >= 20 ? "late" : min >= 10 ? "warn" : ""; }

function ticketHtml(c) {
  const canKitchen = can("cocina"), canServe = can("mesas");
  const live = c.lines.filter((l) => !l.voided);
  const allReady = live.length && live.every((l) => l.kds_status === "listo");
  return `<article class="kt ${ageClass(c.minutes)}" data-c="${c.id}">
    <header><strong>${esc(c.tables ? "Mesa " + c.tables : c.tab_name || c.tab_number)}</strong><span class="kt-min">${c.minutes} min</span></header>
    <div class="kt-meta">${esc(c.number)} · ${esc(c.waiter)} · <b>${esc(c.station)}</b>${c.print_error ? ` · <span class="bad" title="${esc(c.print_error)}">sin imprimir</span>` : ""}</div>
    <ul>${c.lines.map((l) => `<li class="kl ${l.voided ? "voided" : l.kds_status}">
      <div class="kl-main"><b>${l.qty} ×</b> ${esc(l.description)}${l.descriptives ? `<div class="kl-sub">+ ${esc(l.descriptives)}</div>` : ""}${l.note ? `<div class="kl-sub note">“${esc(l.note)}”</div>` : ""}${l.guest > 1 ? `<small class="muted"> comensal ${l.guest}</small>` : ""}${l.voided ? `<div class="kl-sub">ANULADO: ${esc(l.void_reason)}</div>` : ""}</div>
      ${l.voided ? "" : ((l.kds_status === "listo" ? canServe : canKitchen) && NEXT_KDS[l.kds_status] ? `<button type="button" class="btn sm ${l.kds_status === "preparando" ? "primary" : ""}" data-line="${l.id}" data-to="${NEXT_KDS[l.kds_status]}">${NEXT_LABEL[l.kds_status]}</button>` : `<span class="pill ${l.kds_status === "listo" ? "pagada" : "parcial"}">${KDS_LABEL[l.kds_status]}</span>`)}</li>`).join("")}</ul>
    <footer>${canKitchen && !allReady && live.some((l) => l.kds_status !== "listo") ? `<button type="button" class="btn primary" data-all="${c.id}" data-to="listo">Todo listo</button>` : ""}
      ${canKitchen && c.lines.some((l) => !l.voided && l.kds_status === "pendiente") ? `<button type="button" class="btn" data-all="${c.id}" data-to="preparando">Empezar todo</button>` : ""}
      ${can("mesas") && allReady ? `<button type="button" class="btn primary" data-all="${c.id}" data-to="servido">Entregado a la mesa</button>` : ""}
      ${c.print_error && (can("mesas") || can("cocina")) ? `<button type="button" class="btn ghost sm" data-reprint="${c.id}">Reimprimir</button>` : ""}</footer></article>`;
}

function paintKitchen() {
  const root = KITCHEN.root;
  if (!root || view !== "cocina") return;
  const cols = { Pendiente: [], Preparando: [], Lista: [] };
  KITCHEN.comandas.forEach((c) => (cols[c.status] || cols.Pendiente).push(c));
  const titles = { Pendiente: "Nuevos", Preparando: "En preparación", Lista: "Listos para llevar" };
  root.innerHTML = `<div class="section-head"><h2>Cocina y barra</h2><div class="actions">
      <select id="kds-station" aria-label="Estación"><option value="">Todas las estaciones</option>${KITCHEN.stations.map((s) => `<option value="${s}" ${s === KITCHEN.station ? "selected" : ""}>${s[0].toUpperCase() + s.slice(1)}</option>`).join("")}</select>
      <button class="btn ghost" id="kds-full">Pantalla completa</button></div></div>
    <div class="kds">${Object.keys(cols).map((k) => `<section class="kds-col ${k.toLowerCase()}"><h3>${titles[k]} <i>${cols[k].length}</i></h3><div class="kds-list">${cols[k].map(ticketHtml).join("") || `<p class="muted">Nada por aquí</p>`}</div></section>`).join("")}</div>`;
  $("#kds-station").onchange = (e) => { KITCHEN.station = e.target.value; try { localStorage.setItem("comandia_kds_station", KITCHEN.station); } catch (err) { /* nada */ } KITCHEN.known = null; loadKitchen().then(paintKitchen).catch((er) => toast(er.message, "err")); };
  $("#kds-full").onclick = () => { const el = $("#view"); if (document.fullscreenElement) document.exitFullscreen(); else if (el.requestFullscreen) el.requestFullscreen(); };
  $$("[data-line]", root).forEach((b) => b.onclick = () => kdsAct(() => api(`/api/kitchen/lines/${b.dataset.line}/status`, { method: "PUT", body: { status: b.dataset.to } })));
  $$("[data-all]", root).forEach((b) => b.onclick = () => kdsAct(() => api(`/api/kitchen/comandas/${b.dataset.all}/status`, { method: "POST", body: { status: b.dataset.to } })));
  $$("[data-reprint]", root).forEach((b) => b.onclick = () => kdsAct(() => api(`/api/comandas/${b.dataset.reprint}/reprint`, { method: "POST" }), "Comanda reimpresa"));
}

async function kdsAct(action, ok) {
  try { await action(); if (ok) toast(ok); await loadKitchen(); paintKitchen(); }
  catch (err) { toast(err.message, "err"); await loadKitchen().then(paintKitchen).catch(() => {}); }
}
