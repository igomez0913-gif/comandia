/* Conexión y ventas sin conexión de Comandia.

   - Indicador de la barra superior: «BD en línea» / «BD offline» (revisa /api/health cada pocos segundos: si el servidor
     de Comandia o la base de datos MySQL no responden —por ejemplo se cayó el internet—, pasa a offline).
   - Modo ventas offline: el punto de venta sigue funcionando con el catálogo guardado en este equipo (IndexedDB). Cada venta
     se guarda en una cola con un comprobante PROVISIONAL (no es factura fiscal) y, al volver la conexión, se envía sola:
     el servidor emite entonces la factura con el siguiente número del CAI. Reintentar no duplica (id único por venta).
   - Se carga antes que app.js; lo que necesita de app.js (api, $, toast…) lo usa solo en tiempo de ejecución. */
"use strict";

// La pantalla se guarda en el navegador para poder abrirla aunque el servidor no responda (solo en localhost o https).
if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));

/* ───────── almacenamiento local (IndexedDB) ───────── */
const OfflineDB = (() => {
  let opening = null;
  const open = () => opening || (opening = new Promise((ok, bad) => {
    if (!window.indexedDB) return bad(new Error("Este navegador no permite guardar datos sin conexión"));
    const req = indexedDB.open("comandia-offline", 1);
    req.onupgradeneeded = () => { req.result.createObjectStore("kv"); req.result.createObjectStore("queue", { keyPath: "id" }); };
    req.onsuccess = () => ok(req.result);
    req.onerror = () => bad(req.error);
  }));
  const run = (store, mode, fn) => open().then((db) => new Promise((ok, bad) => {
    const r = fn(db.transaction(store, mode).objectStore(store));
    r.onsuccess = () => ok(r.result);
    r.onerror = () => bad(r.error);
  }));
  return {
    get: (key) => run("kv", "readonly", (s) => s.get(key)).catch(() => undefined),
    set: (key, value) => run("kv", "readwrite", (s) => s.put(value, key)),
    queue: () => run("queue", "readonly", (s) => s.getAll()).catch(() => []),
    put: (item) => run("queue", "readwrite", (s) => s.put(item)),
    del: (id) => run("queue", "readwrite", (s) => s.delete(id)),
  };
})();

/* ───────── estado de la conexión ───────── */
const CONN_TEXT = { online: "BD en línea", offline: "BD offline", syncing: "Sincronizando…" };
const CONN_WHY = {
  server: "No hay conexión con el servidor de Comandia (la red falló o el servidor está apagado).",
  db: "El servidor de Comandia funciona, pero la base de datos MySQL no responde (sin internet o servidor de base de datos apagado).",
  network: "Este equipo no tiene conexión de red.",
};

const Conn = {
  state: "online", reason: "", fails: 0, syncing: false, timer: null, started: false,
  /** Pregunta al servidor si vive y si su base de datos contesta. */
  async check() {
    let ok = false, reason = "server";
    if (navigator.onLine === false) reason = "network";
    else {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), 4000);
      try {
        const res = await fetch("/api/health", { cache: "no-store", signal: ctl.signal });
        const data = await res.json();
        ok = res.ok && data.db_ok !== false;
        reason = ok ? "" : res.ok ? "db" : "server";
      } catch (err) { /* sin respuesta: servidor o red caídos */ }
      clearTimeout(timer);
    }
    Conn.apply(ok, reason);
    return ok;
  },
  /** Dos fallos seguidos para pasar a offline (evita parpadeos); un solo acierto para volver. */
  apply(ok, reason) {
    if (ok) { Conn.fails = 0; if (Conn.state === "offline") Conn.set("online", ""); return; }
    Conn.fails += 1;
    if (Conn.state === "online" && Conn.fails >= 2) Conn.set("offline", reason);
    else if (Conn.state === "offline" && reason !== Conn.reason) Conn.set("offline", reason);
  },
  /** Una petición falló por la red: se revisa de inmediato. */
  reportFailure(reason = "") {
    if (reason) { Conn.fails = Math.max(Conn.fails, 1); Conn.apply(false, reason); }
    else { Conn.fails = Math.max(Conn.fails, 1); Conn.check(); }
  },
  forceOffline(reason = "server") { Conn.fails = 2; Conn.set("offline", reason); },
  set(state, reason) {
    const changed = state !== Conn.state;
    Conn.state = state; Conn.reason = reason;
    renderConn();
    if (changed) (state === "offline" ? enteredOffline() : leftOffline()).catch(() => {});
  },
  start() {
    if (Conn.started) return;
    Conn.started = true;
    window.addEventListener("offline", () => Conn.forceOffline("network"));
    window.addEventListener("online", () => Conn.check());
    const loop = async () => { if (user) await Conn.check(); Conn.timer = setTimeout(loop, Conn.state === "offline" ? 3000 : 6000); };
    loop();
  },
};

/* ───────── cola de ventas sin conexión ───────── */
const Offline = {
  items: [],
  async load() { Offline.items = (await OfflineDB.queue()).sort((a, b) => a.created_at.localeCompare(b.created_at)); renderConn(); },
  count() { return Offline.items.length; },
  device() {
    let id = "";
    try { id = localStorage.getItem("comandia_device") || ""; if (!id) { id = Math.random().toString(36).slice(2, 6).toUpperCase(); localStorage.setItem("comandia_device", id); } } catch (err) { id = "PC"; }
    return id;
  },
  /** Referencia única de la venta: equipo + fecha y hora. Sirve también para no duplicarla si se reintenta. */
  newId() {
    const d = new Date(), p = (n) => String(n).padStart(2, "0");
    return `OFF-${Offline.device()}-${String(d.getFullYear()).slice(2)}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
  },
  async saveCatalog(data) { try { await OfflineDB.set("catalog", { ...data, saved_at: new Date().toISOString() }); } catch (err) { /* sin almacenamiento: el modo sin conexión no estará disponible */ } },
  async catalog() { return OfflineDB.get("catalog"); },
  async saveCompany(c) { try { await OfflineDB.set("company", c); } catch (err) { /* nada */ } },
  async company() { return (await OfflineDB.get("company")) || {}; },

  async enqueue(item) { await OfflineDB.put(item); await Offline.load(); },
  async discard(id) { await OfflineDB.del(id); await Offline.load(); },

  /** Envía las ventas pendientes en orden. Sin conexión, sin sesión o con error de red se detiene y las conserva. */
  async sync() {
    if (Conn.syncing || Conn.state !== "online" || !token || !Offline.items.length) return;
    Conn.syncing = true; renderConn();
    const done = [], failed = [];
    try {
      for (const item of [...Offline.items]) {
        let res, data = {};
        try {
          res = await fetch("/api/pos/sale", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
            body: JSON.stringify({ ...item.payload, offline: true, offline_id: item.id, offline_at: item.created_at, offline_user: item.user_name }) });
          data = await res.json().catch(() => ({}));
        } catch (err) { Conn.reportFailure(); break; } // se perdió la conexión a medio camino
        if (res.status === 401) { alertPopup("Tu sesión expiró. Vuelve a entrar para sincronizar las ventas sin conexión (siguen guardadas en este equipo)."); break; }
        if (res.status === 503) { Conn.reportFailure("db"); break; }
        if (res.ok) { done.push({ item, number: data.number, duplicate: !!data.duplicate }); await OfflineDB.del(item.id); continue; }
        const msg = errorText(data);
        failed.push({ item, msg });
        await OfflineDB.put({ ...item, error: msg, failed_at: new Date().toISOString() });
      }
    } finally { Conn.syncing = false; await Offline.load(); }
    if (done.length) toast(`${done.length} venta(s) sin conexión sincronizadas: ya están facturadas en Ventas (${done.map((d) => d.number).join(", ")})`);
    if (failed.length) alertPopup(`${failed.length} venta(s) sin conexión no se pudieron facturar: ${failed[0].msg}. Revísalas en el indicador «BD» de la barra superior.`, "Ventas sin sincronizar");
    if (done.length && view === "pos" && !pos.lines.length) renderPos($("#view")).catch(() => {});
  },
};

/** El punto de venta lee del servidor y guarda una copia; sin conexión usa la copia. */
async function loadPosData() {
  const fetchAll = () => Promise.all([api("/api/products"), api("/api/clients"), api("/api/warehouses"), api("/api/series"),
    can("cobrar") ? api("/api/shifts/current").catch((e) => { if (e.network) throw e; return {}; }) : Promise.resolve({})]);
  if (Conn.state !== "offline") {
    try {
      const [products, clients, warehouses, series, shiftInfo] = await fetchAll();
      Offline.saveCatalog({ products, clients, warehouses, series });
      return { products, clients, warehouses, series, shiftInfo, offline: false };
    } catch (err) { if (!err.network && !err.dbOffline) throw err; Conn.forceOffline(err.dbOffline ? "db" : "server"); }
  }
  const cat = await Offline.catalog();
  if (!cat) throw new Error("Sin conexión y todavía no hay datos guardados en este equipo. Abre el punto de venta una vez con conexión para preparar el modo sin conexión.");
  return { products: cat.products, clients: cat.clients, warehouses: cat.warehouses, series: cat.series, shiftInfo: {}, offline: true, saved_at: cat.saved_at };
}

/* ───────── lo que se ve: indicador, aviso y panel de pendientes ───────── */
function renderConn() {
  const el = $("#conn");
  if (!el) return;
  const state = Conn.syncing ? "syncing" : Conn.state;
  el.className = `conn ${state}`;
  $("#conn-text").textContent = CONN_TEXT[state];
  const n = Offline.count();
  const badge = $("#conn-pending");
  badge.textContent = n ? `${n} por sincronizar` : "";
  badge.classList.toggle("hidden", !n);
  el.title = (Conn.state === "offline" ? `${CONN_WHY[Conn.reason] || CONN_WHY.server}\nSolo el punto de venta funciona: las ventas se guardan en este equipo y se facturan al reconectar.`
    : "La base de datos responde con normalidad.") + (n ? `\n${n} venta(s) sin conexión pendientes: clic para verlas.` : "");
  const banner = $("#offline-banner");
  if (!banner) return;
  banner.classList.toggle("hidden", Conn.state !== "offline");
  if (Conn.state === "offline") {
    banner.innerHTML = `<strong>Sin conexión con la base de datos · modo ventas offline.</strong> ${esc(CONN_WHY[Conn.reason] || CONN_WHY.server)}
      El punto de venta sigue funcionando: las ventas se guardan en este equipo con un comprobante provisional y se facturan solas al reconectar. Las demás pantallas necesitan conexión.
      ${view !== "pos" && can("facturar") ? `<button type="button" class="btn sm" id="off-go-pos">Ir al punto de venta</button>` : ""}`;
    const go = $("#off-go-pos"); if (go) go.onclick = () => goto("pos");
  }
}

async function enteredOffline() {
  renderConn();
  if (view === "pos" && typeof pos !== "undefined" && pos.data) paintPos($("#view")); // el encabezado del punto de venta avisa que no hay conexión
  alertPopup("Se perdió la conexión con la base de datos. Entraste al modo ventas offline: puedes seguir vendiendo en el punto de venta y las ventas se facturan solas al reconectar.", "Modo ventas offline");
  if (can("facturar") && can("cobrar") && view !== "pos" && !(typeof pendingWork === "function" && pendingWork())) goto("pos");
}

async function leftOffline() {
  renderConn();
  if (view === "pos" && typeof pos !== "undefined" && pos.data) paintPos($("#view"));
  if (Offline.count()) { toast("Conexión restablecida: sincronizando las ventas sin conexión…"); await Offline.sync(); }
  else toast("Conexión restablecida: la base de datos está en línea");
}

function showOfflineQueue() {
  const rows = () => Offline.items.map((it) => `<tr><td class="nowrap">${fullDate(it.created_at)}</td><td class="mono small">${esc(it.id)}</td><td>${esc(it.client_name || "")}</td><td class="nowrap">${money(it.total)}</td>
    <td>${it.error ? `<span class="pill vencida">Error</span><div class="small down">${esc(it.error)}</div>` : `<span class="pill pendiente">Pendiente</span>`}</td>
    <td class="row-actions"><button class="btn ghost sm" data-off-print="${esc(it.id)}">Comprobante</button><button class="btn danger sm" data-off-del="${esc(it.id)}">Descartar</button></td></tr>`);
  const paint = () => {
    $("#off-box").innerHTML = `<p>${Conn.state === "online" ? `<span class="pill activo">BD en línea</span>` : `<span class="pill vencida">BD offline</span>`}
      ${Offline.count() ? `<strong>${Offline.count()}</strong> venta(s) sin sincronizar (<strong>${money(Offline.items.reduce((s, i) => s + i.total, 0))}</strong>)` : "No hay ventas pendientes."}</p>
      ${table(["HORA", "REFERENCIA", "CLIENTE", "TOTAL", "ESTADO", ""], rows(), "No hay ventas sin conexión pendientes")}
      <div class="actions" style="margin-top:12px"><button class="btn primary" id="off-sync" ${Conn.state !== "online" || !Offline.count() ? "disabled" : ""}>Sincronizar ahora</button></div>
      <p class="muted small">Estas ventas ya se cobraron; el cliente se llevó un comprobante provisional. Al sincronizar, el sistema emite la factura con el siguiente número del CAI (no se duplican si se reintenta). «Descartar» solo si la venta no se hizo o ya la facturaste a mano.</p>`;
    $("#off-sync")?.addEventListener("click", async () => { await Offline.sync(); paint(); });
    $$("[data-off-print]").forEach((b) => b.onclick = () => printOfflineTicket(Offline.items.find((i) => i.id === b.dataset.offPrint)));
    $$("[data-off-del]").forEach((b) => b.onclick = async () => { if (await askConfirm("¿Descartar esta venta sin conexión? No se facturará ni se descontará del inventario.", "Descartar", true)) { await Offline.discard(b.dataset.offDel); showOfflineQueue(); } });
  };
  openForm("Ventas sin conexión", `<div class="full" id="off-box"></div>`, null, { wide: true, mount: paint });
}

/** Comprobante provisional del cliente: NO es factura fiscal. */
async function printOfflineTicket(item) {
  const c = await Offline.company();
  await printHtml(`<!doctype html><html><head><meta charset="utf-8"><title>${esc(item.id)}</title><style>body{font-family:monospace;width:280px;padding:8px;font-size:12px}p{margin:6px 0}.box{border:2px solid #000;padding:6px;text-align:center;font-weight:bold}.logo{display:block;margin:0 auto 6px;max-width:160px;max-height:70px;object-fit:contain}</style></head><body>
    ${c.logo ? `<img class="logo" src="${esc(logoUrl(c))}" alt="Logo" />` : ""}
    <p><strong>${esc(c.name || "")}</strong><br>${esc(c.address || "")}<br>RTN ${esc(c.rtn || "")}</p>
    <div class="box">COMPROBANTE PROVISIONAL<br>NO ES FACTURA FISCAL</div>
    <p>Ref. ${esc(item.id)}<br>${fullDate(item.created_at)}<br>${esc(item.client_name || "")}${item.user_name ? `<br>Atendió: ${esc(item.user_name)}` : ""}</p>
    ${item.lines.map((l) => `<p>${esc(l.name)}<br>${l.qty} x ${money(l.price)}${l.discount ? ` − desc. ${money(l.discount)}` : ""} = ${money(l.total)}</p>`).join("")}
    <p>Gravado 15% ${money(item.totals.gravado15)}<br>ISV 15% ${money(item.totals.isv15)}<br>Gravado 18% ${money(item.totals.gravado18)}<br>ISV 18% ${money(item.totals.isv18)}<br>Exento ${money(item.totals.exento)}<br>Exonerado ${money(item.totals.exonerado)}<br><strong>Total ${money(item.total)}</strong></p>
    <p>${item.payments.map((p) => `${esc(p.method)} ${money(p.amount)}`).join("<br>")}${item.change > 0 ? `<br>Cambio ${money(item.change)}` : ""}</p>
    <div class="box">La factura fiscal se emite al reconectar el sistema. Conserve este comprobante.</div></body></html>`);
}

/** Cobra una venta del punto de venta sin conexión: guarda la venta en la cola, descuenta del inventario local e imprime el comprobante. */
async function offlineCheckout(body, t, payments, change) {
  if (!can("descuentos") && pos.lines.some((l) => (l.discount || 0) > 0.004)) throw new Error("Sin conexión no se puede pedir la autorización de un supervisor: quita los descuentos de la venta o espera a que vuelva la conexión.");
  const client = posClient();
  const item = {
    id: body.offline_id, created_at: new Date().toISOString(), user_name: user?.name || "", user_id: user?.id, total: t.total, change: change || 0, client_name: client.name || "",
    payload: body, totals: t, payments,
    lines: pos.lines.map((l) => ({ name: `${l.name} ${l.present}`, qty: l.qty, price: l.price, discount: l.discount || 0, total: lineNet(l) })),
  };
  await Offline.enqueue(item);
  // existencia local al día para no vender de más mientras no hay conexión
  pos.lines.forEach((l) => { const row = (l.stocks || []).find((s) => s.warehouse_id === pos.warehouse_id); if (row) row.qty = r2(row.qty - l.qty * l.factor); });
  if (pos.data?.products) Offline.saveCatalog({ products: pos.data.products, clients: pos.data.clients, warehouses: pos.data.warehouses, series: pos.data.series });
  return item;
}

function offlineInit() {
  // Pide que el navegador NO borre estas ventas pendientes por falta de espacio, y avisa antes de cerrar la pestaña con ventas sin sincronizar.
  try { if (navigator.storage && navigator.storage.persist) navigator.storage.persist(); } catch (err) { /* no disponible */ }
  if (!window.__offlineGuard) {
    window.__offlineGuard = true;
    window.addEventListener("beforeunload", (e) => { if (Offline.count()) { e.preventDefault(); e.returnValue = ""; } });
  }
  const el = $("#conn");
  if (el && !el.dataset.bound) { el.dataset.bound = "1"; el.onclick = showOfflineQueue; }
  Offline.load();
  Conn.start();
}
