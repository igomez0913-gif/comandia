/* Comandia · salón: plano de mesas, cuenta, pedido con descriptivos, envío a cocina, cambio/unión/transferencia y cobro (toda la cuenta, por comensal o por líneas). */

const SALON = { salons: [], salonId: null, tabs: [], tab: null, products: [], deps: [], descriptives: [], clients: [], depId: "", q: "", ready: [], includesTax: true, root: null };
const LINE_STATE = { nueva: ["Sin enviar", "pendiente"], enviada: ["En cocina", "parcial"], cobrada: ["Cobrada", "pagada"], anulada: ["Anulada", "anulada"] };
const KDS_LABEL = { pendiente: "Esperando", preparando: "Preparando", listo: "¡Listo!", servido: "Servido" };

/** Al terminar una vista se detienen sus temporizadores (app.js llama a todo lo que se registre aquí al cambiar de pantalla). */
window.viewCleanup = window.viewCleanup || [];
const onLeave = (fn) => window.viewCleanup.push(fn);

/** Pantalla inicial según el rol: el mesero entra al salón y la cocina a su pantalla. */
function homeViewFor(u) {
  const perms = (u && u.permissions) || [];
  const has = (p) => perms.includes(p);
  if (has("cocina") && !has("mesas") && !has("reportes") && !has("facturar")) return "cocina";
  if (has("mesas") && !has("reportes") && !has("facturar")) return "salon";
  return null;
}

function beep(freq = 880, ms = 160) {
  try {
    const ctx = beep.ctx || (beep.ctx = new (window.AudioContext || window.webkitAudioContext)());
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.frequency.value = freq; g.gain.value = 0.08; o.connect(g); g.connect(ctx.destination); o.start(); o.stop(ctx.currentTime + ms / 1000);
  } catch (e) { /* sin audio */ }
}

const fmtMin = (m) => (m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`);

/* ───────── carga ───────── */
async function renderSalon(root) {
  SALON.root = root;
  const [salons, products, deps, descs, settings] = await Promise.all([api("/api/salons"), api("/api/products"), api("/api/departments"), api("/api/descriptives?all=true"), api("/api/settings")]);
  SALON.salons = salons;
  SALON.products = products.filter((p) => p.sellable);
  SALON.deps = deps.departments.filter((d) => SALON.products.some((p) => p.department_id === d.id));
  SALON.descriptives = descs.filter((d) => d.active);
  SALON.includesTax = settings.prices_include_tax !== false;
  SALON.clients = can("cobrar") ? await api("/api/clients").catch(() => []) : [];
  if (!salons.find((s) => s.id === SALON.salonId)) SALON.salonId = salons.length ? salons[0].id : null;
  await reloadTabs();
  if (SALON.tab) SALON.tab = await api("/api/tabs/" + SALON.tab.id).catch(() => null);
  await reloadReady();
  paintSalon();
  const tick = setInterval(async () => {
    if ($("#modal").classList.contains("open") || document.hidden) return; // no se refresca con una ventana abierta (se perdería lo escrito)
    try { await refreshSalon(); } catch (e) { /* sin conexión: se reintenta */ }
  }, 8000);
  let wasPhone = isPhone();
  const onResize = () => { if (isPhone() !== wasPhone) { wasPhone = isPhone(); paintSalon(); } else fitFloor(); };
  window.addEventListener("resize", onResize);
  onLeave(() => { clearInterval(tick); window.removeEventListener("resize", onResize); });
}

async function reloadTabs() { SALON.tabs = await api("/api/tabs"); }
async function reloadReady() {
  if (!can("mesas")) { SALON.ready = []; return; }
  const next = await api("/api/kitchen/ready").catch(() => []);
  if (next.some((r) => !SALON.ready.find((o) => o.line_id === r.line_id)) && SALON.ready.length !== undefined && SALON.readyKnown) beep(988, 220);
  SALON.ready = next; SALON.readyKnown = true;
}
async function refreshSalon(keepScroll = true) {
  SALON.salons = await api("/api/salons");
  await reloadTabs();
  if (SALON.tab) SALON.tab = await api("/api/tabs/" + SALON.tab.id).catch(() => null);
  if (SALON.tab && SALON.tab.status !== "Abierta" && !SALON.keepClosed) SALON.tab = null;
  await reloadReady();
  paintSalon();
}
/** Ejecuta una acción sobre la cuenta, muestra el error si lo hay y repinta (sin recargar toda la pantalla). */
async function salonAct(action, okMessage) {
  try { const r = await action(); if (okMessage) toast(okMessage); await refreshSalon(); return r; }
  catch (err) { toast(err.message, "err"); await refreshSalon().catch(() => {}); }
}

/* ───────── pintado ───────── */
function currentSalon() { return SALON.salons.find((s) => s.id === SALON.salonId); }

function paintSalon() {
  const root = SALON.root;
  if (!root || view !== "salon") return;
  const salon = currentSalon();
  if (!salon) {
    root.innerHTML = `<div class="section-head"><h2>Salón</h2></div><div class="card"><p>Todavía no hay salones. ${can("salones") ? `Diséñalos en <strong>Restaurante › Plano</strong>.` : "Pídele a la gerencia que los cree."}</p>${can("salones") ? `<button class="btn primary" id="go-plano">Ir al plano</button>` : ""}</div>`;
    if ($("#go-plano")) $("#go-plano").onclick = () => { restState.tab = "plano"; view = "restaurante"; $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === "restaurante")); render(); };
    return;
  }
  const scrollTop = $(".tab-body")?.scrollTop || 0;
  const open = SALON.tabs.filter((t) => t.status === "Abierta");
  const noTable = open.filter((t) => !t.tables.length);
  root.innerHTML = `
    <div class="section-head"><h2>Salón</h2><div class="actions">
      ${can("mesas") ? `<button class="btn" id="tab-bar">Cuenta sin mesa</button>` : ""}
      <button class="btn ghost" id="salon-refresh" title="Actualizar">Actualizar</button></div></div>
    ${SALON.includesTax ? "" : `<div class="warn-note">Los precios del menú no incluyen ISV. Activa «Los precios incluyen ISV» en Configuración para que lo que ve el cliente sea lo que paga.</div>`}
    ${SALON.ready.length ? `<div class="ready-bar" role="status"><strong>Listo para llevar:</strong> ${SALON.ready.map((r) => `<button class="ready-chip" data-served="${r.line_id}" title="Marcar como servido">Mesa ${esc(r.tables || r.tab_number)} · ${r.qty > 1 ? r.qty + " × " : ""}${esc(r.description)} ✓</button>`).join("")}</div>` : ""}
    <div class="salon-tabs">${SALON.salons.map((s) => `<button class="tab-chip ${s.id === SALON.salonId ? "on" : ""}" data-salon="${s.id}">${esc(s.name)}</button>`).join("")}
      ${noTable.map((t) => `<button class="tab-chip alt ${SALON.tab && SALON.tab.id === t.id ? "on" : ""}" data-tab="${t.id}">${esc(t.number)}${t.name ? " · " + esc(t.name) : ""} · ${money(t.total)}</button>`).join("")}</div>
    <div class="salon-layout">
      <div class="card floor-card"><div class="floor ${isPhone() ? "as-grid" : ""}" id="floor"><div class="floor-inner" id="floor-inner">${floorHtml(salon)}</div></div>
        <div class="floor-legend"><span class="lg libre"></span>Libre <span class="lg ocupada"></span>Ocupada <span class="lg lista"></span>Pedido listo</div></div>
      <div class="card tab-panel" id="tab-panel">${tabPanelHtml()}</div>
    </div>`;
  fitFloor();
  const body = $(".tab-body"); if (body) body.scrollTop = scrollTop;
  bindSalon();
}

function floorBounds(items) {
  return { w: Math.max(900, ...items.map((i) => i.x + i.w + 24)), h: Math.max(520, ...items.map((i) => i.y + i.h + 24)) };
}
const KIND_Z = { piso: 0, pared: 1, mobiliario: 2, puerta: 2, planta: 3, mesa: 4 };
function floorItemStyle(i) { return `left:${i.x}px;top:${i.y}px;width:${i.w}px;height:${i.h}px;transform:rotate(${i.rotation || 0}deg);z-index:${KIND_Z[i.kind] ?? 2}`; }

const isPhone = () => window.innerWidth < 640;

/** En un teléfono el plano a escala queda minúsculo: se muestran las mesas como botones grandes en cuadrícula. */
function tableGridHtml(salon) {
  const readyTabs = new Set(SALON.ready.map((r) => r.tab_id));
  const mesas = salon.items.filter((i) => i.kind === "mesa").sort((a, b) => a.name.localeCompare(b.name, "es", { numeric: true }));
  return `<div class="table-grid">` + mesas.map((i) => {
    const t = i.tab, sel = SALON.tab && t && SALON.tab.id === t.id;
    return `<button type="button" class="tg ${t ? "ocupada" : "libre"} ${t && readyTabs.has(t.id) ? "lista" : ""} ${sel ? "sel" : ""}" data-table="${i.id}"><strong>${esc(i.name)}</strong>${t ? `<span>${money(t.total)}</span><small>${fmtMin(t.minutes || 0)}${t.pending ? ` · ${t.pending} sin enviar` : ""}</small>` : `<small>${i.seats} lugares</small>`}</button>`;
  }).join("") + `</div>`;
}

function floorHtml(salon) {
  if (isPhone()) return tableGridHtml(salon);
  const b = floorBounds(salon.items);
  const readyTabs = new Set(SALON.ready.map((r) => r.tab_id));
  return `<div class="floor-size" style="width:${b.w}px;height:${b.h}px" data-w="${b.w}" data-h="${b.h}">` + [...salon.items].sort((a, c) => (KIND_Z[a.kind] ?? 2) - (KIND_Z[c.kind] ?? 2)).map((i) => {
    if (i.kind !== "mesa") return `<div class="fi ${i.kind} ${i.shape}" style="${floorItemStyle(i)}" aria-hidden="true">${decorSvg(i.kind, i.shape, i.w, i.h)}${["mobiliario", "planta"].includes(i.kind) && i.shape !== "sofa" ? `<span class="fi-text">${esc(i.name)}</span>` : i.kind === "mobiliario" ? `<span class="fi-text">${esc(i.name)}</span>` : ""}</div>`;
    const t = i.tab, sel = SALON.tab && t && SALON.tab.id === t.id;
    return `<button type="button" class="fi mesa ${i.shape} ${t ? "ocupada" : "libre"} ${t && readyTabs.has(t.id) ? "lista" : ""} ${sel ? "sel" : ""}" style="${floorItemStyle(i)}" data-table="${i.id}" aria-label="Mesa ${esc(i.name)} ${t ? "ocupada" : "libre"}">
      ${tableSvg(i.shape, i.w, i.h, i.seats)}<div class="fi-label" style="transform:rotate(${-(i.rotation || 0)}deg)"><strong>${esc(i.name)}</strong>${t ? `<span>${money(t.total)}</span><small>${fmtMin(t.minutes || 0)}</small>` : `<small>${i.seats} lugares</small>`}</div>${t && t.pending ? `<i class="dot-pend" title="Productos sin enviar">${t.pending}</i>` : ""}</button>`;
  }).join("") + `</div>`;
}

function fitFloor() {
  const box = $("#floor"), size = $(".floor-size");
  if (!box || !size) return;
  const w = +size.dataset.w, h = +size.dataset.h, s = Math.min(1.25, box.clientWidth / w);
  size.style.transform = `scale(${s})`; size.style.transformOrigin = "top left";
  box.style.height = Math.ceil(h * s) + "px";
}

function lineRow(t, ln) {
  const [label, cls] = LINE_STATE[ln.status] || [ln.status, ""];
  const fresh = ln.status === "nueva", sent = ln.status === "enviada";
  return `<li class="tline ${ln.status}">
    <div class="tl-main"><div class="tl-name">${fresh ? `<span class="stepper"><button type="button" data-q="${ln.id}" data-d="-1" aria-label="Menos">−</button><b>${ln.qty}</b><button type="button" data-q="${ln.id}" data-d="1" aria-label="Más">+</button></span>` : `<b>${ln.qty} ×</b>`} ${esc(ln.description)}</div>
      ${ln.descriptives ? `<div class="tl-sub">+ ${esc(ln.descriptives)}</div>` : ""}${ln.note ? `<div class="tl-sub note">“${esc(ln.note)}”</div>` : ""}
      ${ln.status === "anulada" ? `<div class="tl-sub">Anulada: ${esc(ln.void_reason)}</div>` : ""}</div>
    <div class="tl-side"><span class="tl-price">${money(ln.total)}</span>
      <span class="pill ${cls}">${sent && ln.kds ? esc(KDS_LABEL[ln.kds] || label) : label}</span>
      <span class="tl-actions">${fresh ? `<button type="button" class="btn ghost sm" data-note="${ln.id}">Nota</button><button type="button" class="btn ghost sm" data-del="${ln.id}">Quitar</button>` : ""}${sent ? `<button type="button" class="btn ghost sm" data-void="${ln.id}">Anular</button>` : ""}</span></div></li>`;
}

function tabPanelHtml() {
  const t = SALON.tab;
  if (!t) {
    return `<div class="tab-empty"><h3>Elige una mesa</h3><p class="muted">Toca una mesa libre para abrir su cuenta, o una ocupada para ver lo que lleva.</p></div>`;
  }
  const mesas = t.tables.map((x) => x.name).join(" + ") || "sin mesa";
  const guests = Math.max(t.guests, 1);
  const groups = {};
  t.lines.forEach((ln) => { (groups[ln.guest] = groups[ln.guest] || []).push(ln); });
  const showGroups = guests > 1;
  const body = t.lines.length
    ? Object.keys(groups).sort((a, b) => a - b).map((g) => `${showGroups ? `<div class="guest-head">Comensal ${g}<span>${money(t.guests_totals[g] || 0)}</span></div>` : ""}<ul class="tlines">${groups[g].map((ln) => lineRow(t, ln)).join("")}</ul>`).join("")
    : `<p class="muted tab-none">Aún no hay productos. Elígelos del menú.</p>`;
  const ready = !!t.pending;
  return `<div class="tab-head"><div><h3>${esc(t.number)} · Mesa ${esc(mesas)}</h3><small class="muted">${esc(t.waiter)} · ${guests} comensal${guests > 1 ? "es" : ""}${t.name ? " · " + esc(t.name) : ""}</small></div>
      <div class="tab-total"><small>Total</small><strong>${money(t.total)}</strong></div></div>
    <div class="tab-body">${body}
      <details class="menu-box" ${SALON.menuOpen === false ? "" : "open"}><summary>Agregar productos</summary>${menuHtml()}</details></div>
    <div class="tab-foot">
      <button class="btn primary big" id="t-send" ${ready ? "" : "disabled"}>Enviar a cocina${ready ? ` (${t.pending})` : ""}</button>
      ${can("cobrar") ? `<button class="btn big" id="t-pay" ${t.lines_count ? "" : "disabled"}>Cobrar</button>` : ""}
      <details class="more"><summary class="btn ghost">Más</summary><div class="more-menu">
        <button type="button" data-more="move">Cambiar de mesa</button><button type="button" data-more="merge">Unir con otra cuenta</button>
        <button type="button" data-more="transfer" ${t.lines_count ? "" : "disabled"}>Pasar consumos a otra mesa</button>
        <button type="button" data-more="guests">Comensales y nombre</button>
        <button type="button" data-more="empty" ${t.lines.some((l) => ["nueva", "enviada", "cobrada"].includes(l.status)) ? "disabled" : ""}>Cerrar cuenta vacía</button></div></details></div>`;
}

function menuHtml() {
  const q = (SALON.q || "").toLowerCase().trim();
  const list = SALON.products.filter((p) => (!SALON.depId || String(p.department_id) === String(SALON.depId)) && (!q || (p.name + " " + p.sku).toLowerCase().includes(q)));
  return `<div class="menu"><input id="menu-q" placeholder="Buscar platillo o bebida…" value="${esc(SALON.q)}" autocomplete="off" />
    <div class="menu-deps"><button type="button" class="tab-chip ${SALON.depId ? "" : "on"}" data-dep="">Todo</button>${SALON.deps.map((d) => `<button type="button" class="tab-chip ${String(SALON.depId) === String(d.id) ? "on" : ""}" data-dep="${d.id}">${esc(d.name)}</button>`).join("")}</div>
    <div class="menu-grid">${list.map((p) => `<button type="button" class="menu-item" data-add="${p.id}"><span>${esc(p.name)}</span><b>${money(p.price)}</b></button>`).join("") || `<p class="muted">Sin resultados</p>`}</div></div>`;
}

/* ───────── eventos ───────── */
function bindSalon() {
  const root = SALON.root;
  $$("[data-salon]", root).forEach((b) => b.onclick = () => { SALON.salonId = +b.dataset.salon; paintSalon(); });
  $$("[data-tab]", root).forEach((b) => b.onclick = () => selectTab(+b.dataset.tab));
  $$("[data-table]", root).forEach((b) => b.onclick = () => tapTable(+b.dataset.table));
  $$("[data-served]", root).forEach((b) => b.onclick = () => salonAct(() => api(`/api/kitchen/lines/${b.dataset.served}/status`, { method: "PUT", body: { status: "servido" } }), "Marcado como servido"));
  if ($("#salon-refresh")) $("#salon-refresh").onclick = () => refreshSalon().catch((e) => toast(e.message, "err"));
  if ($("#tab-bar")) $("#tab-bar").onclick = () => openTabModal(null);
  if (!SALON.tab) return;
  const t = SALON.tab;
  if ($(".menu-box")) $(".menu-box").ontoggle = (e) => { SALON.menuOpen = e.target.open; };  // el menú recuerda si estaba abierto al repintar la cuenta
  $$("[data-dep]", root).forEach((b) => b.onclick = () => { SALON.depId = b.dataset.dep; keepMenuOpen(); });
  if ($("#menu-q")) { $("#menu-q").oninput = (e) => { SALON.q = e.target.value; const g = $(".menu-grid"); const keep = e.target.selectionStart; keepMenuOpen(true); const i = $("#menu-q"); if (i) { i.focus(); i.setSelectionRange(keep, keep); } }; }
  $$("[data-add]", root).forEach((b) => b.onclick = () => addProduct(+b.dataset.add));
  $$("[data-q]", root).forEach((b) => b.onclick = () => { const ln = t.lines.find((l) => l.id === +b.dataset.q); const qty = Math.max(0, ln.qty + +b.dataset.d); salonAct(() => qty === 0 ? api(`/api/tabs/${t.id}/lines/${ln.id}/void`, { method: "POST", body: {} }) : api(`/api/tabs/${t.id}/lines/${ln.id}`, { method: "PUT", body: { qty } })); });
  $$("[data-del]", root).forEach((b) => b.onclick = () => salonAct(() => api(`/api/tabs/${t.id}/lines/${b.dataset.del}/void`, { method: "POST", body: {} })));
  $$("[data-note]", root).forEach((b) => b.onclick = () => noteModal(t.lines.find((l) => l.id === +b.dataset.note)));
  $$("[data-void]", root).forEach((b) => b.onclick = () => voidModal(t.lines.find((l) => l.id === +b.dataset.void)));
  if ($("#t-send")) $("#t-send").onclick = sendOrder;
  if ($("#t-pay")) $("#t-pay").onclick = payModal;
  $$("[data-more]", root).forEach((b) => b.onclick = () => { $(".more")?.removeAttribute("open"); moreAction(b.dataset.more); });
}
function keepMenuOpen(onlyGrid = false) {
  const box = $(".menu-box"); const wasOpen = box ? box.open : true;
  const wrap = $(".menu-box .menu"); if (!wrap) return;
  const holder = wrap.parentElement; holder.innerHTML = `<summary>Agregar productos</summary>${menuHtml()}`; holder.open = wasOpen;
  bindSalon();
}

async function tapTable(id) {
  const salon = currentSalon(); const item = salon.items.find((i) => i.id === id);
  if (item.tab) return selectTab(item.tab.id);
  if (!can("mesas")) return toast("Esa mesa está libre", "ok");
  openTabModal(item);
}
async function selectTab(id) {
  try { SALON.tab = await api("/api/tabs/" + id); paintSalon(); } catch (err) { toast(err.message, "err"); }
}

function openTabModal(table) {
  openModal(table ? `Abrir cuenta · Mesa ${table.name}` : "Cuenta sin mesa (barra o mostrador)", [
    { name: "guests", label: "Comensales", type: "number", value: table ? Math.min(table.seats || 2, 4) || 2 : 1, min: 1, max: 100, required: true },
    { name: "name", label: "A nombre de (opcional)", value: "", placeholder: "Ej. Sra. Gómez" },
  ], async (b) => {
    const t = await api("/api/tabs", { method: "POST", body: { table_ids: table ? [table.id] : [], guests: +b.guests || 1, name: b.name } });
    SALON.tab = t; await refreshSalon(); return "stay";
  }, { submitLabel: "Abrir cuenta" });
}

function addProduct(pid) {
  const t = SALON.tab, p = SALON.products.find((x) => x.id === pid);
  const descs = SALON.descriptives.filter((d) => !d.department_id || d.department_id === p.department_id);
  const guests = Math.max(t.guests, 1);
  if (!descs.length && guests === 1) return salonAct(() => api(`/api/tabs/${t.id}/lines`, { method: "POST", body: { product_id: pid, qty: 1 } }));
  openForm(`${p.name} · ${money(p.price)}`, `
    <div class="full add-qty"><span>Cantidad</span><span class="stepper big"><button type="button" id="aq-m" aria-label="Menos">−</button><input id="aq" name="qty" type="number" min="1" max="100" step="1" value="1" /><button type="button" id="aq-p" aria-label="Más">+</button></span></div>
    ${descs.length ? `<div class="full"><div class="muted small">Descriptivos</div><div class="dsc-list">${descs.map((d) => `<label class="dsc"><input type="checkbox" name="d" value="${d.id}" /><span>${esc(d.name)}${d.extra_price ? ` <em>+${money(d.extra_price)}</em>` : ""}</span></label>`).join("")}</div></div>` : ""}
    ${guests > 1 ? `<label class="full">Comensal<select name="guest">${Array.from({ length: guests }, (_, i) => `<option value="${i + 1}">Comensal ${i + 1}</option>`).join("")}</select></label>` : ""}
    <label class="full">Nota para la cocina<input name="note" maxlength="200" placeholder="Ej. bien cocida, sin sal…" autocomplete="off" /></label>`,
  async (form) => {
    const f = Object.fromEntries(new FormData(form).entries());
    await api(`/api/tabs/${t.id}/lines`, { method: "POST", body: { product_id: pid, qty: Math.max(1, +f.qty || 1), descriptive_ids: $$("[name=d]:checked", form).map((x) => +x.value), note: f.note || "", guest: +f.guest || 1 } });
    await refreshSalon(); return "stay";
  }, { submitLabel: "Agregar al pedido", mount: (form) => {
    const q = $("#aq", form); $("#aq-m", form).onclick = () => { q.value = Math.max(1, (+q.value || 1) - 1); }; $("#aq-p", form).onclick = () => { q.value = (+q.value || 1) + 1; };
  } });
}

function noteModal(ln) {
  openModal("Nota para la cocina", [{ name: "note", label: ln.description, value: ln.note, full: true, placeholder: "Ej. bien cocida, sin sal…" }],
    async (b) => { await api(`/api/tabs/${SALON.tab.id}/lines/${ln.id}`, { method: "PUT", body: { note: b.note } }); await refreshSalon(); return "stay"; });
}

function voidModal(ln) {
  const needPin = !can("anular");
  openModal(`Anular ${ln.description}`, [
    { type: "info", html: `Ya se envió a cocina. La anulación queda registrada y se avisa a la estación${needPin ? "; necesitas el PIN de un supervisor" : ""}.` },
    { name: "reason", label: "Motivo", required: true, full: true, placeholder: "Ej. el cliente se fue, error de pedido…" },
    ...(needPin ? [{ name: "auth_pin", label: "PIN del supervisor", type: "password", full: true, required: true, autocomplete: "off" }] : []),
  ], async (b) => { await api(`/api/tabs/${SALON.tab.id}/lines/${ln.id}/void`, { method: "POST", body: { reason: b.reason, auth_pin: b.auth_pin || "" } }); await refreshSalon(); return "stay"; }, { submitLabel: "Anular producto", danger: true });
}

async function sendOrder() {
  const t = SALON.tab;
  try {
    const r = await api(`/api/tabs/${t.id}/send`, { method: "POST" });
    const failed = r.comandas.filter((c) => c.print_error);
    toast(`Enviado a ${r.comandas.map((c) => c.station).join(" y ")}`);
    if (failed.length) alertPopup(`La comanda de ${failed.map((c) => c.station.toUpperCase()).join(" y ")} no salió impresa (${failed[0].print_error}). Ya está en la pantalla de cocina; avisa a gerencia.`, "Impresora sin respuesta");
    SALON.tab = r.tab; await refreshSalon();
  } catch (err) { toast(err.message, "err"); }
}

/* ───────── más acciones ───────── */
async function moreAction(kind) {
  const t = SALON.tab;
  if (kind === "empty") { if (await askConfirm("¿Cerrar esta cuenta vacía y liberar la mesa?", "Cerrar cuenta")) { await salonAct(() => api(`/api/tabs/${t.id}/close-empty`, { method: "POST" }), "Cuenta cerrada"); SALON.tab = null; paintSalon(); } return; }
  if (kind === "guests") return openModal("Comensales y nombre", [{ name: "guests", label: "Comensales", type: "number", value: t.guests, min: 1, max: 100, required: true }, { name: "name", label: "A nombre de", value: t.name }], async (b) => {
    await api(`/api/tabs/${t.id}/guests`, { method: "PUT", body: { guests: +b.guests, name: b.name } }); await refreshSalon(); return "stay"; });
  const salon = currentSalon();
  const free = salon.items.filter((i) => i.kind === "mesa" && (!i.tab || i.tab.id === t.id));
  if (kind === "move") return openModal("Cambiar de mesa", [{ type: "info", html: "Elige la mesa (o varias, separadas) a la que pasa la cuenta. La anterior queda libre." },
    { name: "tables", label: "Mesas", type: "select", full: true, value: "", options: [{ value: "", label: "Elige…" }, ...salon.items.filter((i) => i.kind === "mesa" && !i.tab).map((i) => ({ value: i.id, label: `Mesa ${i.name} · ${i.seats} lugares` }))] }],
    async (b) => { if (!b.tables) throw new Error("Elige una mesa"); await api(`/api/tabs/${t.id}/move`, { method: "POST", body: { table_ids: [+b.tables] } }); await refreshSalon(); return "stay"; }, { submitLabel: "Cambiar" });
  if (kind === "merge") {
    const others = SALON.tabs.filter((x) => x.status === "Abierta" && x.id !== t.id);
    if (!others.length) return toast("No hay otra cuenta abierta para unir", "err");
    return openModal("Unir cuentas", [{ type: "info", html: "Los consumos y las mesas de la otra cuenta pasan a esta. Sus comensales se numeran a continuación." },
      { name: "from", label: "Unir esta cuenta con", type: "select", full: true, options: others.map((x) => ({ value: x.id, label: `${x.number} · ${x.tables.map((m) => "Mesa " + m.name).join(", ") || x.name || "sin mesa"} · ${money(x.total)}` })) }],
      async (b) => { await api(`/api/tabs/${t.id}/merge`, { method: "POST", body: { from_tab_id: +b.from } }); await refreshSalon(); return "stay"; }, { submitLabel: "Unir cuentas" });
  }
  if (kind === "transfer") {
    const targets = salon.items.filter((i) => i.kind === "mesa" && (!i.tab || i.tab.id !== t.id));
    return openForm("Pasar consumos a otra mesa", `
      <div class="full"><div class="muted small">Consumos a pasar</div>${t.lines.filter((l) => ["nueva", "enviada"].includes(l.status)).map((l) => `<label class="check-row"><input type="checkbox" name="l" value="${l.id}" /> ${l.qty} × ${esc(l.description)} <span>${money(l.total)}</span></label>`).join("")}</div>
      <label class="full">A la mesa<select name="to">${targets.map((i) => `<option value="${i.id}">Mesa ${esc(i.name)}${i.tab ? ` · ${esc(i.tab.number)} (ocupada)` : " · libre"}</option>`).join("")}</select></label>`,
    async (form) => { const ids = $$("[name=l]:checked", form).map((x) => +x.value); if (!ids.length) throw new Error("Marca al menos un consumo"); await api(`/api/tabs/${t.id}/transfer`, { method: "POST", body: { line_ids: ids, to_table_id: +$("[name=to]", form).value } }); await refreshSalon(); return "stay"; }, { submitLabel: "Pasar consumos" });
  }
}

/* ───────── cobro ───────── */
function payModal() {
  const t = SALON.tab;
  const pending = t.lines.filter((l) => ["nueva", "enviada"].includes(l.status));
  if (pending.some((l) => l.status === "nueva")) return toast("Hay productos sin enviar a cocina: envíalos o quítalos antes de cobrar", "err");
  const guestNums = [...new Set(pending.map((l) => l.guest))].sort((a, b) => a - b);
  const pref = (() => { try { return localStorage.getItem("comandia_pos_print") || "ticket"; } catch (e) { return "ticket"; } })();
  const tipPct = (() => { try { return +localStorage.getItem("comandia_tip_pct") || 10; } catch (e) { return 10; } })();
  const clients = SALON.clients;
  openForm(`Cobrar ${t.number} · Mesa ${t.tables.map((x) => x.name).join(" + ") || "—"}`, `
    <div class="full pay-scope"><label><input type="radio" name="scope" value="all" checked /> Toda la cuenta</label>
      ${guestNums.length > 1 ? `<label><input type="radio" name="scope" value="guest" /> Un comensal <select name="guest">${guestNums.map((g) => `<option value="${g}">Comensal ${g}</option>`).join("")}</select></label>` : ""}
      <label><input type="radio" name="scope" value="lines" /> Elegir consumos</label></div>
    <div class="full pay-lines" id="pay-lines">${pending.map((l) => `<label class="check-row"><input type="checkbox" name="l" value="${l.id}" data-g="${l.guest}" data-t="${l.total}" checked /> ${l.qty} × ${esc(l.description)}${l.descriptives ? ` <small class="muted">+ ${esc(l.descriptives)}</small>` : ""} <span>${money(l.total)}</span></label>`).join("")}</div>
    <div class="full pay-total"><span>A cobrar</span><strong id="pay-total">${money(0)}</strong></div>
    <div class="full pay-tip"><span>Propina</span>${[0, 10, 15, 20].map((p) => `<button type="button" class="tab-chip ${p === tipPct ? "on" : ""}" data-tip="${p}">${p === 0 ? "Sin" : p + "%"}</button>`).join("")}<input id="tip" name="tip" type="number" min="0" step="0.01" value="0" aria-label="Propina en lempiras" /><select name="tip_method">${["Efectivo", "Tarjeta", "Transferencia"].map((m) => `<option>${m}</option>`).join("")}</select></div>
    <div class="full pay-methods" id="pay-methods"></div>
    <div class="full"><button type="button" class="btn ghost sm" id="pay-split">Dividir el pago en otra forma</button></div>
    <label class="full cash-recv">Efectivo recibido<input id="recv" name="received" type="number" min="0" step="0.01" placeholder="Opcional: para calcular el cambio" /></label>
    <div class="full pay-change" id="pay-change"></div>
    <details class="full"><summary>Factura a nombre de…</summary><div class="form" style="margin-top:8px">
      <label class="full">Cliente<select name="client_id"><option value="">Consumidor final</option>${clients.filter((c) => c.rtn).map((c) => `<option value="${c.id}">${esc(c.name)} · ${esc(c.rtn)}</option>`).join("")}</select></label>
      <label>Nombre en la factura<input name="buyer_name" maxlength="180" autocomplete="off" /></label><label>RTN<input name="buyer_rtn" maxlength="20" autocomplete="off" placeholder="14 dígitos" /></label>
      <small class="muted full">Si el cliente no está registrado, escribe su nombre y RTN solo para esta factura.</small></div></details>`,
  async (form) => {
    const f = Object.fromEntries(new FormData(form).entries());
    const scope = f.scope;
    const body = { payments: methodRows(form), received: f.received ? +f.received : null, tip: +f.tip || 0, tip_method: f.tip_method, buyer_name: f.buyer_name || "", buyer_rtn: f.buyer_rtn || "", client_id: f.client_id ? +f.client_id : null };
    if (scope === "guest") body.guest = +f.guest; else if (scope === "lines") body.line_ids = $$("[name=l]:checked", form).map((x) => +x.value);
    const r = await api(`/api/tabs/${t.id}/pay`, { method: "POST", body });
    try { localStorage.setItem("comandia_tip_pct", $(".pay-tip .on")?.dataset.tip || "0"); } catch (e) { /* nada */ }
    toast(r.closed ? `Cuenta cobrada · ${r.document.number}${r.document.change ? ` · cambio ${money(r.document.change)}` : ""}` : `Cobro parcial · ${r.document.number}`);
    if (pref === "carta") safePrint(printDoc, r.document.id); else if (pref === "ticket") safePrint(printTicket, r.document.id);
    SALON.tab = r.closed ? null : r.tab; await refreshSalon(); return "stay";
  }, { wide: true, submitLabel: "Cobrar", mount: (form) => payMount(form, t, tipPct) });
}

function methodRows(form) {
  return $$(".pm-row", form).map((r) => ({ method: $("select", r).value, amount: +$("input", r).value || 0 })).filter((p) => p.amount > 0);
}
function payMount(form, t, tipPct) {
  const rows = $("#pay-methods", form);
  const addRow = (method, amount) => {
    const d = document.createElement("div"); d.className = "pm-row";
    d.innerHTML = `<select aria-label="Forma de pago">${["Efectivo", "Tarjeta", "Transferencia"].map((m) => `<option ${m === method ? "selected" : ""}>${m}</option>`).join("")}</select><input type="number" min="0" step="0.01" value="${amount}" aria-label="Monto" />${rows.children.length ? `<button type="button" class="btn ghost sm" aria-label="Quitar">✕</button>` : ""}`;
    rows.appendChild(d);
    $("input", d).oninput = recalcChange; $("select", d).onchange = recalcChange;
    const x = $("button", d); if (x) x.onclick = () => { d.remove(); recalcTotal(); };
  };
  const chosen = () => $$("[name=l]", form).filter((c) => c.checked);
  const total = () => chosen().reduce((s, c) => s + +c.dataset.t, 0);
  function applyScope() {
    const scope = $("[name=scope]:checked", form).value, g = $("[name=guest]", form) ? +$("[name=guest]", form).value : null;
    $$("[name=l]", form).forEach((c) => { c.disabled = scope !== "lines"; if (scope === "all") c.checked = true; if (scope === "guest") c.checked = +c.dataset.g === g; });
    $("#pay-lines", form).classList.toggle("dim", scope !== "lines");
    recalcTotal();
  }
  function recalcTotal() {
    const tot = r2(total());
    $("#pay-total", form).textContent = money(tot);
    const first = $(".pm-row input", form);
    if (rows.children.length === 1 && first) first.value = tot.toFixed(2);
    const pct = +($(".pay-tip .on")?.dataset.tip ?? 0); $("#tip", form).value = r2(tot * pct / 100).toFixed(2);
    recalcChange();
  }
  function recalcChange() {
    const tot = r2(total()), paid = r2($$(".pm-row input", form).reduce((s, i) => s + (+i.value || 0), 0)), cash = r2($$(".pm-row", form).filter((r) => $("select", r).value === "Efectivo").reduce((s, r) => s + (+$("input", r).value || 0), 0));
    const recv = +$("#recv", form).value || 0, el = $("#pay-change", form);
    const diff = r2(tot - paid);
    el.innerHTML = Math.abs(diff) > 0.004 ? `<span class="bad">${diff > 0 ? "Falta" : "Sobra"} ${money(Math.abs(diff))} para cuadrar el total</span>` : recv && cash ? (recv + 0.004 >= cash ? `Cambio: <strong>${money(r2(recv - cash))}</strong>` : `<span class="bad">El efectivo recibido no alcanza (${money(cash)})</span>`) : "";
    $(".cash-recv", form).classList.toggle("hidden", cash <= 0);
  }
  addRow("Efectivo", 0);
  $$("[name=scope], [name=guest], [name=l]", form).forEach((c) => c.onchange = applyScope);
  $("#recv", form).oninput = recalcChange;
  $$("[data-tip]", form).forEach((b) => b.onclick = () => { $$("[data-tip]", form).forEach((x) => x.classList.toggle("on", x === b)); recalcTotal(); });
  $("#tip", form).oninput = () => { $$("[data-tip]", form).forEach((x) => x.classList.remove("on")); };
  $("#pay-split", form).onclick = () => { if (rows.children.length < 4) { addRow("Tarjeta", 0); recalcChange(); } };
  applyScope();
}
