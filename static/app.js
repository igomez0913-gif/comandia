/* Comandia v2.9 · Gestión comercial SAR Honduras · Ing. Israel Gómez / Soluciones Tecnológicas HN */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
let token = localStorage.getItem("comandia_token") || "";
let user = JSON.parse(localStorage.getItem("comandia_user") || "null");
let period = "month";
let view = "inicio";
let pendingQuery = "";
const docFilter = { kind: "", status: "", q: "", store: "" };
let IDLE_MIN = 30; // minutos sin usar el sistema para cerrar la sesión (0 = nunca)
let lastActive = Date.now();
["mousemove", "mousedown", "keydown", "touchstart", "scroll", "wheel"].forEach((ev) => window.addEventListener(ev, () => { lastActive = Date.now(); }, { passive: true }));
setInterval(() => {
  // No se cierra sin conexión (no se podría volver a entrar) ni con ventas a medias en el punto de venta.
  if (!IDLE_MIN || !user || !token || (typeof Conn !== "undefined" && Conn.state === "offline") || (typeof pos !== "undefined" && pos.lines && pos.lines.length)) return;
  if (Date.now() - lastActive > IDLE_MIN * 60000) { logout(); toast(`Sesión cerrada por ${IDLE_MIN} minutos sin actividad`, "err"); }
}, 20000);
let LIC_ACTIVE = {}; // módulos activos según la licencia (se guarda en el equipo para el modo sin conexión)
const modOn = (name) => LIC_ACTIVE[name] !== false;
const MOD_LOCKED = { multi_warehouse: "Multi-bodega", offline: "Modo sin conexión", importar_excel: "Importar desde Excel", reports: "Reportes avanzados",
  advanced_credit: "Crédito avanzado", reabastecimiento: "Reabastecimiento", docs_fiscales: "Notas de débito", etiquetas: "Etiquetas y códigos de barras", backup: "Respaldos automáticos",
  api: "API REST", email: "Correo electrónico", compras: "Compras" };
const lockedPopup = (name) => alertPopup(`El módulo «${MOD_LOCKED[name] || name}» no está activado. Pide tu clave y actívala en Configuración › Licencia.`, "Módulo adicional");
let PLAN = { id: "todo", label: "" }; // paquete de la licencia (Básico, Profesional, Empresarial, Todo) para la barra superior
const NAV_MODULE = { reabastecer: "reabastecimiento", etiquetas: "etiquetas", cxp: "compras" }; // pantallas que son de un módulo
function applyPlanUi() {
  $$("[data-view]").forEach((b) => { const m = NAV_MODULE[b.dataset.view]; if (!m) return; b.classList.toggle("locked", !modOn(m)); b.title = modOn(m) ? "" : `Módulo «${MOD_LOCKED[m]}»: sin activar`; });
  const badge = $("#plan-badge");
  if (badge) { badge.textContent = PLAN.label; badge.className = "plan-badge plan-" + PLAN.id; badge.classList.toggle("hidden", !PLAN.label); }
}
let POS_ON = true; // el punto de venta se puede ocultar en Configuración
let STORES = []; // tiendas (módulo Multi-tienda); con una sola no se muestra nada de tiendas
let priceNames = ["Público", "Mayorista", "Distribuidor", "Especial"]; // se cargan de Configuración al iniciar
const levelName = (n) => priceNames[(+n || 1) - 1] || `Precio ${n}`;
const levelOptions = (selected) => priceNames.map((name, i) => `<option value="${i + 1}" ${i + 1 === +selected ? "selected" : ""}>${i + 1} · ${esc(name)}</option>`).join("");
/** Los 4 precios guardados (0 = no definido) a partir de un producto o presentación de la API. */
const rawPrices = (x) => [x.price, x.price_2, x.price_3, x.price_4].map((v) => num(v));

/* ───────── utilidades ───────── */
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const slug = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-");
const seriesLabel = (s) => `${s.code === s.name ? s.name : `${s.code} · ${s.name}`} · siguiente ${s.current}`;
const pill = (s) => `<span class="pill ${slug(s)}">${esc(s)}</span>`;
const can = (...perms) => !!user && perms.some((p) => (user.permissions || []).includes(p));
const NAV_PERMS = { salon: ["mesas"], cocina: ["cocina", "mesas"], restaurante: ["salones", "catalogo", "config", "inventario", "ver_costos"], bodegas: ["inventario", "catalogo"], catalogo: ["catalogo"], proveedores: ["compras"], bancos: ["bancos"], reportes: ["reportes"], config: ["config", "usuarios"], cxc: ["cobrar", "reportes"], caja: ["cobrar", "reportes"], bitacora: ["bitacora"], cxp: ["compras", "bancos"], conteo: ["inventario"], reabastecer: ["compras"], etiquetas: ["catalogo", "inventario"], };
// Vistas que piden TODOS sus permisos (no solo uno): el punto de venta factura y cobra a la vez.
const NAV_ALL = { pos: ["facturar", "cobrar"] };
const canAll = (...perms) => perms.every((p) => can(p));
const canView = (v) => (NAV_ALL[v] ? canAll(...NAV_ALL[v]) : !NAV_PERMS[v] || can(...NAV_PERMS[v]));
const money = (n) => "L\u00a0" + Number(n || 0).toLocaleString("es-HN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : 0; };
const r2 = (n) => Math.round((n + Number.EPSILON) * 100) / 100;
/** Cliente exonerado: lo gravado se factura exonerado (sin ISV), igual que hace el servidor. */
const effTax = (tax, client) => (client && client.exonerated && (tax === "gravado15" || tax === "gravado18") ? "exonerado" : tax);
const exoBlock = (d) => (d.oce_number || d.exo_registry || d.sag_registry
  ? `Orden de compra exenta: ${esc(d.oce_number || "—")} · Constancia de registro de exonerados: ${esc(d.exo_registry || "—")} · Registro SAG: ${esc(d.sag_registry || "—")}` : "");
/** Importe neto de una línea: cantidad × precio − descuento. */
const lineGross = (l) => r2(l.qty * l.price);
const lineNet = (l) => r2(lineGross(l) - (l.discount || 0));
/** Descuento de la línea según lo escrito: «25» son lempiras y «10%» es porcentaje del importe. */
const applyDiscount = (l, text) => {
  const raw = String(text ?? "").trim().replace(",", ".");
  l.dpct = raw.endsWith("%") ? Math.min(Math.max(num(raw.slice(0, -1)), 0), 100) : null;
  l.dunit = null;
  l.discount = l.dpct !== null ? r2(lineGross(l) * l.dpct / 100) : Math.min(Math.max(r2(num(raw)), 0), lineGross(l));
};
/** Al cambiar cantidad o precio, el descuento en porcentaje (o por unidad, en notas de crédito) se recalcula. */
const redoDiscount = (l) => {
  if (l.dpct != null) l.discount = r2(lineGross(l) * l.dpct / 100);
  else if (l.dunit != null) l.discount = r2(l.dunit * l.qty);
  else l.discount = Math.min(l.discount || 0, lineGross(l));
};
const TAX_LABEL = { gravado15: "ISV 15%", gravado18: "ISV 18%", exento: "Exento", exonerado: "Exonerado" };
const TAX_OPTIONS = Object.entries(TAX_LABEL).map(([value, label]) => ({ value, label }));
const KIND_OPTIONS = [["producto", "Producto (se compra y se vende)"], ["platillo", "Platillo (se vende, con receta)"], ["insumo", "Insumo (ingrediente)"], ["elaborado", "Elaborado (se prepara)"]].map(([value, label]) => ({ value, label }));
const STATION_OPTIONS = [["", "Ninguna"], ["cocina", "Cocina"], ["barra", "Barra"], ["parrilla", "Parrilla"], ["postres", "Postres"], ["otra", "Otra"]].map(([value, label]) => ({ value, label }));
const when = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  const sameDay = (a, b) => a.toDateString() === b.toDateString();
  const hh = d.toLocaleTimeString("es-HN", { hour: "2-digit", minute: "2-digit" });
  const now = new Date();
  if (sameDay(d, now)) return `Hoy, ${hh}`;
  const yest = new Date(now); yest.setDate(now.getDate() - 1);
  if (sameDay(d, yest)) return `Ayer, ${hh}`;
  return d.toLocaleDateString("es-HN");
};
/** Fecha y hora completas para documentos impresos (nunca «Hoy» o «Ayer»). */
const fullDate = (iso) => (iso ? `${new Date(iso).toLocaleDateString("es-HN", { day: "2-digit", month: "2-digit", year: "numeric" })} ${new Date(iso).toLocaleTimeString("es-HN", { hour: "2-digit", minute: "2-digit" })}` : "");
const dateOnly = (iso) => (iso ? new Date(iso + (iso.length === 10 ? "T00:00:00" : "")).toLocaleDateString("es-HN") : "—");

/** Aviso grande y rojo para errores (por ejemplo «Stock insuficiente…»): se ve aunque la ventana esté en primer plano,
    se cierra solo a los 8 segundos (con barra de cuenta regresiva; se detiene al pasar el mouse) o con ✕. */
const POPUP_SECONDS = 8;
function alertPopup(message, title = "") {
  message = String(message || "").trim();
  if (!message) return;
  $$(".alert-pop").forEach((p) => p.remove()); // un solo aviso a la vez: el nuevo reemplaza al anterior
  if (!title) title = /^Stock insuficiente/i.test(message) ? "No hay existencia suficiente" : /^(falta|sobra)/i.test(message) ? "Revisa el cobro" : "No se pudo completar";
  const el = document.createElement("div");
  el.className = "alert-pop";
  el.setAttribute("role", "alert");
  el.innerHTML = `<div class="alert-pop-icon" aria-hidden="true">!</div>
    <div class="alert-pop-body"><strong>${esc(title)}</strong><p>${esc(message)}</p></div>
    <button type="button" class="alert-pop-close" aria-label="Cerrar aviso">✕</button>
    <div class="alert-pop-bar" style="animation-duration:${POPUP_SECONDS}s"></div>`;
  document.body.appendChild(el);
  const close = () => el.remove();
  $(".alert-pop-close", el).onclick = close;
  $(".alert-pop-bar", el).addEventListener("animationend", close);
}

function toast(message, kind = "ok") {
  if (kind === "err") return alertPopup(message);
  const box = $("#toasts");
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = message;
  box.appendChild(el);
  setTimeout(() => el.remove(), kind === "err" ? 6000 : 3200);
}

function errorText(data) {
  if (typeof data.detail === "string") return data.detail.replace(/^(AUTORIZACION|DB_OFFLINE): /, "");
  if (Array.isArray(data.detail)) {
    return "Revisa los datos: " + data.detail.map((e) => `${(e.loc || []).filter((x) => x !== "body").join(" › ")} ${e.msg}`).join("; ");
  }
  return "Error de servidor";
}

async function api(path, opts = {}) {
  let res;
  try {
    res = await fetch(path, {
      ...opts,
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}), ...(opts.headers || {}) },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
  } catch (e) { // sin respuesta del servidor: la red o el servidor de Comandia están caídos
    const err = new Error("Sin conexión con el servidor de Comandia.");
    err.network = true;
    if (typeof Conn !== "undefined" && user) Conn.reportFailure();
    throw err;
  }
  if (res.status === 401 && !path.startsWith("/api/auth/")) { logout(); throw new Error("Tu sesión expiró. Ingresa de nuevo."); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(errorText(data));
    err.dbOffline = res.status === 503 && typeof data.detail === "string" && data.detail.startsWith("DB_OFFLINE");
    if (err.dbOffline && typeof Conn !== "undefined" && user) Conn.reportFailure("db");
    err.needsAuth = res.status === 403 && typeof data.detail === "string" && data.detail.startsWith("AUTORIZACION");
    throw err;
  }
  return data;
}

async function downloadApi(path, fallbackName) {
  const res = await fetch(path, { headers: { Authorization: "Bearer " + token } });
  if (!res.ok) { const data = await res.json().catch(() => ({})); throw new Error(errorText(data)); }
  const name = (res.headers.get("content-disposition") || "").match(/filename="?([^"]+)"?/)?.[1] || fallbackName;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(await res.blob());
  a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
}
const exportCsv = (path, name) => downloadApi(path, name).catch((err) => toast(err.message, "err"));

function logout() {
  token = ""; user = null;
  localStorage.removeItem("comandia_token");
  localStorage.removeItem("comandia_user");
  closeModal();
  $("#shell").classList.add("hidden");
  $("#login").classList.remove("hidden");
}

/* ───────── modales ───────── */
/** Pide el PIN de un supervisor para aprobar un descuento. Devuelve el PIN, o null si se cancela. */
function askAuthPin(amount, reason = "") {
  return new Promise((resolve) => {
    $("#modal-title").textContent = reason ? "Autorización necesaria" : "Autorizar descuento";
    $(".modal").classList.remove("wide");
    modalSnapshot = null; modalOnCancel = () => resolve(null);
    const form = $("#modal-form");
    form.innerHTML = `<div class="full info">${reason ? esc(reason) : `Descuento de <strong>${money(amount)}</strong>. Tu rol necesita que un supervisor lo apruebe con su PIN de autorización.`}</div>
      <label class="full">PIN del supervisor<input id="auth-pin" type="password" inputmode="numeric" autocomplete="one-time-code" maxlength="8" required /></label>
      <div class="full actions"><button class="btn primary" type="submit">Autorizar</button><button type="button" class="btn" id="pin-no">Cancelar</button></div><p id="modal-error" class="form-error full"></p>`;
    form.onsubmit = (e) => { e.preventDefault(); const v = $("#auth-pin").value.trim(); if (!v) return; closeModal(); resolve(v); };
    $("#pin-no").onclick = () => { closeModal(); resolve(null); };
    $("#modal").classList.add("open");
    $("#auth-pin").focus();
  });
}
/** ¿Hay descuentos que el usuario no puede dar por sí mismo? */
const needsDiscountAuth = (lines) => !can("descuentos") && lines.some((l) => (l.discount || 0) > 0.004);

function closeModal() { $("#close-confirm")?.remove(); modalOnCancel = null; $("#modal").classList.remove("open"); $(".modal").classList.remove("wide"); }

/* Cerrar a propósito (Esc, «Cerrar», clic afuera): si hay datos escritos sin guardar o se está guardando, se pregunta antes. */
let modalSnapshot = null;   // estado del formulario al abrirse (null = ventana de solo lectura o de confirmación)
let modalOnCancel = null;   // qué hacer si se cancela con Esc (las preguntas devuelven su respuesta)
const formState = (form) => JSON.stringify([...form.elements].filter((el) => el.name || el.id).map((el) => [el.name || el.id,
  el.type === "checkbox" || el.type === "radio" ? el.checked : el.type === "file" ? [...el.files].map((f) => f.name) : el.value]));
/** Motivo por el que cerrar la ventana perdería algo, o "" si se puede cerrar sin problema. */
function modalPending() {
  if (modalSnapshot === null || !$("#modal").classList.contains("open")) return "";
  const form = $("#modal-form");
  if ($("button[type=submit]", form)?.disabled) return "Se está guardando: si cierras ahora no sabrás si quedó guardado.";
  return formState(form) !== modalSnapshot ? "Hay datos escritos que todavía no se guardan." : "";
}
function requestClose() {
  if ($("#close-confirm")) { $("#close-confirm").remove(); return; } // Esc con la pregunta abierta = seguir editando
  const why = modalPending();
  if (!why) { const cancel = modalOnCancel; closeModal(); if (cancel) cancel(); return; }
  const box = document.createElement("div");
  box.id = "close-confirm"; box.className = "close-confirm"; box.setAttribute("role", "alertdialog");
  box.innerHTML = `<div class="card"><h3>¿Cerrar la ventana?</h3><p>${esc(why)} Si cierras, se pierde lo escrito.</p>
    <div class="actions"><button type="button" class="btn primary" id="dc-no">Seguir editando</button><button type="button" class="btn danger" id="dc-yes">Cerrar sin guardar</button></div>
    <div class="modal-hints"><span>${kbdHtml("N")} o ${kbdHtml("Esc")} Seguir editando</span><span>${kbdHtml("S")} Cerrar sin guardar</span></div></div>`;
  document.body.appendChild(box);
  $("#dc-no").onclick = () => box.remove();
  $("#dc-yes").onclick = () => closeModal();
  $("#dc-no").focus();
}
$("#modal-close").onclick = requestClose;
$("#modal").addEventListener("mousedown", (e) => { if (e.target.id === "modal") requestClose(); });

/* Trabajo sin guardar en pantalla (por ejemplo una factura a medias): se pregunta antes de salir de ella. */
let pendingWork = null; // () => mensaje | null
async function leaveOk() {
  const msg = pendingWork && pendingWork();
  if (!msg) { pendingWork = null; return true; }
  const ok = await askConfirm(msg, "Salir sin guardar", true);
  if (ok) pendingWork = null;
  return ok;
}
window.addEventListener("beforeunload", (e) => { if ((pendingWork && pendingWork()) || modalPending()) { e.preventDefault(); e.returnValue = ""; } });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { if ($("#modal").classList.contains("open")) requestClose(); $("#results").classList.remove("open"); }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k" && user) { e.preventDefault(); $("#global-search").focus(); }
});

/** Modal con HTML propio. onSubmit(formEl) puede ser null para vistas de solo lectura. */
function openForm(title, html, onSubmit, { wide = false, submitLabel = "Guardar", mount, danger = false } = {}) {
  $("#modal-title").textContent = title;
  $(".modal").classList.toggle("wide", wide);
  const form = $("#modal-form");
  form.innerHTML = html + (onSubmit ? `<button class="btn ${danger ? "danger" : "primary"} full" type="submit">${esc(submitLabel)}</button>` : "") + `<p id="modal-error" class="form-error full"></p>`;
  form.onsubmit = async (e) => {
    e.preventDefault();
    if (!onSubmit) return;
    const btn = $("button[type=submit]", form);
    btn.disabled = true;
    try {
      const result = await onSubmit(form);
      if (result === false) { btn.disabled = false; return; }
      closeModal();
      if (result !== "stay") render();
    } catch (err) { $("#modal-error").textContent = err.message; alertPopup(err.message); btn.disabled = false; }
  };
  $("#modal").classList.add("open");
  modalOnCancel = null;
  if (mount) mount(form);
  const first = $("input:not([type=hidden]):not([readonly]), select", form);
  if (first && onSubmit) first.focus();
  modalSnapshot = onSubmit ? formState(form) : null;
}

function fieldHtml(f) {
  const cls = f.full ? "full" : "";
  const req = f.required ? "required" : "";
  const hint = f.hint ? `<small class="muted">${esc(f.hint)}</small>` : "";
  if (f.type === "info") return `<div class="full info">${f.html}</div>`;
  if (f.type === "select") {
    return `<label class="${cls}">${esc(f.label)}<select name="${f.name}" ${req}>${f.options.map((o) => `<option value="${esc(o.value)}" ${String(o.value) === String(f.value ?? "") ? "selected" : ""}>${esc(o.label)}</option>`).join("")}</select>${hint}</label>`;
  }
  if (f.type === "textarea") return `<label class="full">${esc(f.label)}<textarea name="${f.name}" ${req}>${esc(f.value || "")}</textarea>${hint}</label>`;
  const extra = [f.step ? `step="${f.step}"` : "", f.min !== undefined ? `min="${f.min}"` : "", f.max !== undefined ? `max="${f.max}"` : "", f.placeholder ? `placeholder="${esc(f.placeholder)}"` : "", f.autocomplete ? `autocomplete="${f.autocomplete}"` : "", f.readonly ? "readonly" : ""].join(" ");
  return `<label class="${cls}">${esc(f.label)}<input name="${f.name}" type="${f.type || "text"}" value="${esc(f.value ?? "")}" ${req} ${extra} />${hint}</label>`;
}

function openModal(title, fields, onSubmit, opts = {}) {
  openForm(title, fields.map(fieldHtml).join(""), (form) => onSubmit(Object.fromEntries(new FormData(form).entries())), opts);
}

function askConfirm(message, confirmLabel = "Confirmar", danger = false) {
  return new Promise((resolve) => {
    $("#modal-title").textContent = "Confirmar";
    $(".modal").classList.remove("wide");
    modalSnapshot = null; modalOnCancel = () => resolve(false);
    const form = $("#modal-form");
    form.innerHTML = `<p class="full">${esc(message)}</p><div class="full actions"><button type="button" class="btn ${danger ? "danger" : "primary"}" id="cf-yes">${esc(confirmLabel)}</button><button type="button" class="btn" id="cf-no">Cancelar</button></div><p id="modal-error" class="form-error full"></p>`;
    form.onsubmit = (e) => e.preventDefault();
    $("#cf-yes").onclick = () => { closeModal(); resolve(true); };
    $("#cf-no").onclick = () => { closeModal(); resolve(false); };
    $("#modal").classList.add("open");
    $("#cf-no").focus();
  });
}

/** Ejecuta una acción de la interfaz mostrando el error como aviso y refrescando la vista. */
async function run(action, okMessage) {
  try {
    const result = await action();
    if (okMessage) toast(okMessage);
    await render();
    return result;
  } catch (err) { toast(err.message, "err"); }
}

/* ───────── impresión (iframe oculto: no lo bloquea el bloqueador de ventanas) ───────── */
async function printHtml(html) {
  const frame = document.createElement("iframe");
  frame.setAttribute("aria-hidden", "true");
  frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0";
  document.body.appendChild(frame);
  const doc = frame.contentWindow.document;
  doc.open(); doc.write(html); doc.close();
  await Promise.all([...doc.images].map((i) => (i.complete ? 1 : new Promise((ok) => { i.onload = i.onerror = ok; }))));
  frame.contentWindow.focus();
  frame.contentWindow.print();
  setTimeout(() => frame.remove(), 60000);
}

const LEGEND = "La factura es beneficio de todos, ¡Exíjala!";

async function printTicket(id) {
  const { document: d, company: c } = await api("/api/documents/" + id);
  const fiscal = d.kind !== "cotizacion";
  const lines = d.items.map((i) => `<p>${esc(i.description)}<br>${i.qty} x ${money(i.price)}${i.discount ? ` − desc. ${money(i.discount)}` : ""} = ${money(i.total)}</p>`).join("");
  await printHtml(`<!doctype html><html><head><meta charset="utf-8"><title>Ticket ${esc(d.number)}</title><style>body{font-family:monospace;width:280px;padding:8px;font-size:12px}p{margin:6px 0}.logo{display:block;margin:0 auto 6px;max-width:160px;max-height:70px;object-fit:contain}</style></head><body>
    ${c.logo ? `<img class="logo" src="${esc(logoUrl(c))}" alt="Logo" />` : ""}
    <p><strong>${esc(c.name)}</strong><br>${esc(c.address)}<br>RTN ${esc(c.rtn)}</p>
    <p>${esc(d.kind_label)} ${esc(d.number)}<br>${fullDate(d.issued_at)}<br>${esc(d.client)}<br>RTN ${esc(d.rtn || "Consumidor final")}${(d.kind === "nota" || d.kind === "debito") && d.ref_number ? `<br>Modifica factura ${esc(d.ref_number)}` : ""}${d.user ? `<br>Atendió: ${esc(d.user)}` : ""}</p>
    ${lines}
    <p>${d.discount ? `Descuentos y rebajas ${money(d.discount)}<br>` : ""}Gravado 15% ${money(d.gravado_15)}<br>ISV 15% ${money(d.isv_15)}<br>Gravado 18% ${money(d.gravado_18)}<br>ISV 18% ${money(d.isv_18)}<br>Exento ${money(d.exento)}<br>Exonerado ${money(d.exonerado)}<br><strong>Total ${money(d.total)}</strong></p>
    <p>${esc(d.amount_words)}</p>
    ${exoBlock(d) ? `<p>${exoBlock(d).replaceAll(" · ", "<br>")}</p>` : ""}
    ${d.payments.length ? `<p>${d.payments.map((p) => `${esc(p.method)} ${money(p.amount)}${p.note ? `<br>${esc(p.note)}` : ""}`).join("<br>")}</p>` : ""}
    ${fiscal ? `<p>CAI ${esc(d.cai || "N/A")}<br>${esc(d.range_label || "")}<br>Fecha límite de emisión ${dateOnly(d.limit_date)}</p><p>${LEGEND}</p>` : "<p>Cotización sin valor fiscal</p>"}
    </body></html>`);
}

const amt = (n) => Number(n || 0).toLocaleString("es-HN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const TAX_MARK = { gravado18: "18%", exento: "E", exonerado: "EXO" };
/** Encabezado de los reportes impresos en carta (cierre de caja): logo, nombre y datos fiscales del emisor. */
const reportHeader = (c, title, sub = "") => `<div class="rh">${c.logo ? `<img src="${esc(logoUrl(c))}" alt="Logo" />` : ""}<div class="rh-co"><strong>${esc(c.name)}</strong>${c.legal_name ? `<br>${esc(c.legal_name)}` : ""}<br>${esc(c.address || "")}<br>RTN ${esc(c.rtn || "")}${c.phone ? ` · Tel. ${esc(c.phone)}` : ""}</div><div class="rh-title"><h1>${esc(title)}</h1>${sub}</div></div>`;

/** Factura, nota de crédito y cotización en carta, con el mismo orden que el talonario manual autorizado por el SAR. */
async function printDoc(id) {
  const { document: d, company: c } = await api("/api/documents/" + id);
  const fiscal = d.kind !== "cotizacion";
  const issued = d.issued_at ? new Date(d.issued_at) : new Date();
  const two = (n) => String(n).padStart(2, "0");
  const marks = new Set();
  const rows = d.items.map((i) => {
    const mark = TAX_MARK[i.tax_treatment];
    if (mark) marks.add(mark);
    return `<tr><td class="c">${i.qty}<small> ${esc(i.unit)}</small></td><td>${esc(i.description)}${mark ? ` <b class="mk">(${mark})</b>` : ""}</td><td class="r">${amt(i.price)}</td><td class="r">${i.discount ? amt(i.discount) : ""}</td><td class="r">${amt(i.total)}</td></tr>`;
  });
  for (let k = rows.length; k < 12; k++) rows.push(`<tr class="blank"><td></td><td></td><td></td><td></td><td></td></tr>`); // renglones vacíos como en el talonario
  const markText = [...marks].map((m) => ({ "18%": "18% = gravado con ISV 18%", E: "E = exento", EXO: "EXO = exonerado" }[m])).join(" · ");
  const n = d.number || "", cut = n.lastIndexOf("-");
  const prefix = fiscal && cut > 0 ? n.slice(0, cut + 1) : "", corr = fiscal && cut > 0 ? n.slice(cut + 1) : n;
  const extra = [
    d.kind === "nota" || d.kind === "debito" ? `<b>Factura que modifica: ${esc(d.ref_number || "—")}</b>` : "",
    d.kind === "cotizacion" ? `Válida hasta: ${dateOnly(d.validity_date || d.due_date)}` : `Condición: ${esc(d.payment_terms || "Contado")}${d.due_date && d.payment_terms !== "Contado" ? ` · Vence: ${dateOnly(d.due_date)}` : ""}`,
    d.client_ref && d.kind !== "nota" && d.kind !== "debito" ? `Referencia: ${esc(d.client_ref)}` : "",
    d.series ? `Serie: ${esc(d.series)}` : "",
    `Hora: ${issued.toLocaleTimeString("es-HN", { hour: "2-digit", minute: "2-digit" })}`,
    d.user ? `Atendido por: ${esc(d.user)}` : "",
  ].filter(Boolean).join(" · ");
  const tot = (label, v, cls = "") => `<tr class="${cls}"><th>${label}</th><td>${amt(v)}</td></tr>`;
  await printHtml(`<!doctype html><html><head><meta charset="utf-8"><title>${esc(d.number)}</title>
    <style>
      @page { size: letter; margin: 10mm 12mm; }  /* facturas y cotizaciones siempre en tamaño carta */
      * { box-sizing: border-box; }
      body { font-family: Arial, Helvetica, sans-serif; color: #111; margin: 0; font-size: 12px; }
      .hd { display: grid; grid-template-columns: 150px 1fr 150px; align-items: center; gap: 10px; }
      .hd .logo { max-width: 150px; max-height: 90px; object-fit: contain; }
      .issuer { text-align: center; line-height: 1.35; }
      .issuer .co { font-size: 26px; font-weight: 900; letter-spacing: .02em; text-transform: uppercase; line-height: 1.1; }
      .issuer .legal { font-weight: 700; font-size: 13px; }
      .date { border-collapse: collapse; width: 100%; }
      .date th { font-size: 10px; font-weight: 600; border: 1px solid #333; padding: 2px; background: #e6e6e6; }
      .date td { border: 1px solid #333; text-align: center; font-size: 15px; font-weight: 700; padding: 6px 2px; }
      .fields { margin-top: 10px; }
      .fields .row { display: flex; align-items: flex-end; gap: 6px; margin-top: 6px; }
      .fields .lb { white-space: nowrap; }
      .fields .ln { flex: 1; border-bottom: 1px solid #333; padding: 0 4px 1px; font-weight: 700; min-height: 16px; }
      .fields .ln.rtn { flex: 0 0 210px; }
      .fields .extra { font-size: 11px; color: #333; margin-top: 4px; }
      table.items { width: 100%; border-collapse: separate; border-spacing: 0; margin-top: 8px; border: 1.5px solid #333; border-radius: 6px; overflow: hidden; }
      thead { display: table-header-group; }  /* el encabezado de la tabla se repite en cada página */
      tr { page-break-inside: avoid; }
      .items th { background: #d9d9d9; font-size: 11px; padding: 5px 4px; border-bottom: 1.5px solid #333; border-left: 1px solid #333; }
      .items th:first-child, .items td:first-child { border-left: 0; }
      .items th small { display: block; font-size: 8px; line-height: 1; }
      .items td { border-left: 1px solid #333; border-bottom: 1px solid #bbb; padding: 4px 5px; height: 21px; vertical-align: top; }
      .items tbody tr:last-child td { border-bottom: 0; }
      .items td small { color: #555; font-size: 10px; }
      .c { text-align: center; } .r { text-align: right; white-space: nowrap; }
      .mk { font-size: 10px; }
      .marks { font-size: 10px; color: #333; margin: 3px 2px 0; }
      .ft { display: grid; grid-template-columns: 1fr 175px 230px; gap: 10px; margin-top: 8px; page-break-inside: avoid; align-items: start; }
      .exo .t { font-weight: 700; }
      .exo .row { display: flex; gap: 6px; align-items: flex-end; margin-top: 5px; }
      .exo .ln { flex: 1; border-bottom: 1px solid #333; min-height: 15px; padding: 0 3px; font-weight: 700; }
      .legend { text-align: center; font-family: "Times New Roman", serif; font-weight: 700; font-style: italic; font-size: 14px; margin: 8px 0; }
      .words { border-top: 1px solid #333; margin-top: 10px; padding-top: 2px; }
      .words .t { font-weight: 700; font-size: 10px; text-align: right; }
      .words .v { font-weight: 700; }
      .cai { font-size: 17px; font-weight: 700; margin-top: 8px; letter-spacing: .01em; }
      .small { font-size: 11px; line-height: 1.4; }
      .num { text-align: center; padding-top: 70px; }
      .num .k { font-size: 22px; font-weight: 900; text-transform: uppercase; line-height: 1.1; }
      .num .p { font-size: 20px; font-weight: 700; letter-spacing: .03em; }
      .num .n { color: #c0262d; font-size: 22px; font-weight: 700; letter-spacing: .06em; font-family: "Courier New", monospace; }
      .tot { border-collapse: separate; border-spacing: 0; width: 100%; border: 1.5px solid #333; border-radius: 6px; overflow: hidden; }
      .tot th { background: #d9d9d9; text-align: right; font-weight: 600; font-size: 11px; padding: 6px 5px; border-bottom: 1px solid #333; border-right: 1px solid #333; white-space: nowrap; }
      .tot td { text-align: right; padding: 6px 6px; border-bottom: 1px solid #333; font-weight: 600; min-width: 85px; }
      .tot tr:last-child th, .tot tr:last-child td { border-bottom: 0; font-size: 13px; font-weight: 800; }
      .void { color: #b42318; font-size: 28px; font-weight: 700; border: 3px solid #b42318; display: inline-block; padding: 2px 12px; transform: rotate(-6deg); margin: 6px 0 0; }
      .notes { font-size: 11px; margin-top: 6px; }
    </style></head><body>
    <div class="hd">
      <div>${c.logo ? `<img class="logo" src="${esc(logoUrl(c))}" alt="Logo" />` : ""}</div>
      <div class="issuer"><div class="co">${esc(c.name)}</div>${c.legal_name ? `<div class="legal">${esc(c.legal_name)}</div>` : ""}<div>${esc(c.address || "")}</div>
        <div>${[c.email ? `E-mail: ${esc(c.email)}` : "", c.phone ? `Tel. ${esc(c.phone)}` : "", `<b>R.T.N. ${esc(c.rtn || "")}</b>`].filter(Boolean).join(" • ")}</div></div>
      <table class="date"><tr><th>DÍA</th><th>MES</th><th>AÑO</th></tr><tr><td>${two(issued.getDate())}</td><td>${two(issued.getMonth() + 1)}</td><td>${issued.getFullYear()}</td></tr></table>
    </div>
    ${["Anulada", "Cancelada"].includes(d.status) ? `<div class="void">${d.status.toUpperCase()}</div>` : ""}
    <div class="fields">
      <div class="row"><span class="lb">Cliente:</span><span class="ln">${esc(d.client)}</span><span class="lb">R.T.N.</span><span class="ln rtn">${esc(d.rtn || "")}</span></div>
      <div class="row"><span class="lb">Dirección:</span><span class="ln">${esc(d.client_address || "")}</span></div>
      <div class="extra">${extra}</div>
    </div>
    <table class="items"><thead><tr><th style="width:70px">CANT.</th><th>DESCRIPCIÓN</th><th style="width:95px">P. UNIT.</th><th style="width:95px">DESCUENTOS<small>Y REBAJAS</small></th><th style="width:105px">TOTAL</th></tr></thead><tbody>${rows.join("")}</tbody></table>
    ${markText ? `<p class="marks">${markText}</p>` : ""}
    <div class="ft">
      <div>
        ${fiscal ? `<div class="exo"><div class="t">Datos del Adquirente Exonerado:</div>
          <div class="row"><span>Compra Exenta No.</span><span class="ln">${esc(d.oce_number || "")}</span><span>Reg. SAG No.</span><span class="ln">${esc(d.sag_registry || "")}</span></div>
          <div class="row"><span>Constancia Registro de Exonerados:</span><span class="ln">${esc(d.exo_registry || "")}</span></div></div>
        <div class="legend">“La Factura es beneficio de todos, EXÍJALA”</div>` : ""}
        <div class="words"><div class="t">CANTIDAD EN LETRAS</div><div class="v">${esc(d.amount_words)}</div></div>
        ${fiscal ? `<div class="cai">CAI: ${esc(d.cai || "—")}</div>
          <div class="small">Rango Autorizado: ${esc(d.range_label || "—")}<br>${d.cai_received ? `Fecha Recepción: ${dateOnly(d.cai_received)} • ` : ""}Fecha Límite de Emisión: ${dateOnly(d.limit_date)}<br><b>Original: Cliente • Copia: Obligado Tributario Emisor</b></div>`
          : `<p class="small"><b>Cotización sin valor fiscal.</b></p>`}
        ${d.notes ? `<p class="notes">Notas: ${esc(d.notes)}</p>` : ""}
      </div>
      <div class="num"><div class="k">${esc(d.kind_label)}</div>${prefix ? `<div class="p">${esc(prefix)}</div>` : ""}<div class="n">Nº ${esc(corr)}</div></div>
      <table class="tot">
        ${d.discount ? tot("Descuentos y Rebajas L.", d.discount) : ""}${tot("Importe Exonerado L.", d.exonerado)}${tot("Importe Exento L.", d.exento)}${tot("Importe Gravado 15% L.", d.gravado_15)}${tot("Importe Gravado 18% L.", d.gravado_18)}
        ${tot("15% I.S.V. L.", d.isv_15)}${tot("18% I.S.V. L.", d.isv_18)}${tot(d.kind === "nota" || d.kind === "debito" ? "TOTAL NOTA L." : "TOTAL A PAGAR L.", d.total)}
      </table>
    </div>
    </body></html>`);
}
/** URL completa del logo: la impresión ocurre en un marco aparte y así la imagen siempre carga. */
const logoUrl = (c) => (c.logo ? new URL(c.logo, location.origin).href : "");
const safePrint = (fn, id) => fn(id).catch((err) => toast(err.message, "err"));

/* ───────── sesión y navegación ───────── */
$("#login-form").onsubmit = async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  try {
    const data = await api("/api/auth/login", { method: "POST", body: { email: $("#email").value, password: $("#password").value } });
    token = data.token; user = data.user;
    localStorage.setItem("comandia_token", token);
    localStorage.setItem("comandia_user", JSON.stringify(user));
    localStorage.setItem("comandia_last_email", $("#email").value.trim());
    $("#password").value = "";
    boot();
  } catch (err) { $("#login-error").textContent = err.message; }
};
$("#logout").onclick = async () => { if (await leaveOk()) logout(); };

/** Logo y nombre de la empresa en la pantalla de ingreso y en el icono de la pestaña (no requiere sesión). */
async function loadBranding() {
  try {
    const res = await fetch("/api/public/branding");
    if (!res.ok) return;
    const b = await res.json();
    if (b.name) { $("#login-sub").textContent = b.name; document.title = `${b.name} · Comandia`; }
    if (b.logo) {
      $("#login-logo").src = b.logo;
      $("#login-company").classList.remove("hidden");
      $("#login-brand").classList.add("hidden");
      $("#login-powered").classList.remove("hidden");
      const icon = document.querySelector("link[rel=icon]"); if (icon) icon.href = b.logo;
    } else {
      $("#login-company").classList.add("hidden");
      $("#login-brand").classList.remove("hidden");
      $("#login-powered").classList.add("hidden");
    }
  } catch (err) { /* sin conexión: se queda la marca de Comandia */ }
}
loadBranding();
try { const last = localStorage.getItem("comandia_last_email"); if (last) $("#email").value = last; } catch (err) { /* nada */ }
/* Tema claro (por defecto) u oscuro: se recuerda en este navegador. */
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem("comandia_theme", theme); } catch (e) { /* sin almacenamiento: solo esta sesión */ }
  $("#theme").textContent = theme === "dark" ? "Claro" : "Oscuro";
  $("#theme").title = theme === "dark" ? "Cambiar a tema claro" : "Cambiar a tema oscuro";
}
applyTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
$("#theme").onclick = () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
$("#mypin").onclick = () => openModal(user.has_pin ? "Cambiar mi PIN de autorización" : "Crear mi PIN de autorización", [
  { name: "info", type: "info", full: true, html: "Con este PIN apruebas en la caja lo que cajeros y vendedores no pueden hacer solos: descuentos y ventas al crédito a clientes con mora o sin crédito disponible. Es personal: la bitácora registra quién autorizó cada cosa." },
  { name: "password", label: "Tu clave de ingreso", type: "password", full: true, required: true, autocomplete: "current-password" },
  { name: "pin", label: "PIN nuevo (4 a 8 números; vacío para quitarlo)", type: "password", full: true, autocomplete: "off", inputmode: "numeric", maxlength: 8 },
  { name: "again", label: "Repite el PIN", type: "password", full: true, autocomplete: "off", inputmode: "numeric", maxlength: 8 },
], async (b) => {
  if (b.pin !== b.again) throw new Error("Los PIN no coinciden");
  const r = await api("/api/me/pin", { method: "POST", body: { password: b.password, pin: b.pin } });
  user.has_pin = r.has_pin;
  toast(r.has_pin ? "PIN de autorización guardado" : "PIN de autorización quitado");
  return "stay";
});
$("#chpass").onclick = () => openModal("Cambiar mi clave", [
  { name: "current", label: "Clave actual", type: "password", full: true, required: true, autocomplete: "current-password" },
  { name: "new", label: "Clave nueva (mínimo 8 caracteres)", type: "password", full: true, required: true, autocomplete: "new-password" },
  { name: "again", label: "Repite la clave nueva", type: "password", full: true, required: true, autocomplete: "new-password" },
], async (b) => {
  if (b.new !== b.again) throw new Error("Las claves nuevas no coinciden");
  const res = await api("/api/me/password", { method: "POST", body: { current: b.current, new: b.new } });
  if (res.token) { token = res.token; localStorage.setItem("comandia_token", token); } // la sesión de este equipo sigue; las demás se cierran
  toast("Clave actualizada");
});

async function goto(name, query = "") {
  if (typeof Conn !== "undefined" && Conn.state === "offline" && name !== "pos") {
    alertPopup("Sin conexión con la base de datos: solo el punto de venta funciona. Las ventas se guardan en este equipo y se facturan al reconectar.", "Modo ventas offline");
    return;
  }
  if (!(await leaveOk())) return;
  view = name;
  pendingQuery = query;
  $$(".nav-btn").forEach((n) => n.classList.toggle("active", n.dataset.view === name));
  return render();
}
$$(".nav-btn").forEach((b) => b.onclick = () => {
  if (b.dataset.view === "ventas") Object.assign(docFilter, { kind: "", status: "", q: "" }); // al entrar desde el menú se ven todos los documentos
  if (b.dataset.view === "conteo") openCountId = null; // desde el menú se ve la lista de conteos
  goto(b.dataset.view);
});

async function boot() {
  try {
    $("#login").classList.add("hidden");
    $("#shell").classList.remove("hidden");
    let settings, offlineStart = false;
    try {
      user = await api("/api/me"); // permisos al día aunque el rol haya cambiado desde el último ingreso
      localStorage.setItem("comandia_user", JSON.stringify(user));
      settings = await api("/api/settings");
      const licInfo = await api("/api/license").catch(() => ({ active: {} }));
      settings.modules = licInfo.active || {}; settings.plan = licInfo.plan || ""; settings.plan_label = licInfo.plan_label || "";
      if (typeof Offline !== "undefined") Offline.saveCompany({ name: settings.name, legal_name: settings.legal_name, rtn: settings.rtn, address: settings.address, phone: settings.phone, email: settings.email, logo: settings.logo, price_names: settings.price_names, modules: settings.modules, plan: settings.plan, plan_label: settings.plan_label });
    } catch (err) {
      // Se abrió el sistema sin conexión: se usa la sesión y los datos guardados en este equipo (solo punto de venta)
      if (!(err.network || err.dbOffline) || !user) throw err;
      settings = { ...(await Offline.company()) }; settings.name = settings.name || "Comandia"; settings.rtn = settings.rtn || "";
      offlineStart = true;
    }
    if (typeof offlineInit === "function") offlineInit();
    if (offlineStart) { Conn.forceOffline("server"); view = can("facturar") && can("cobrar") ? "pos" : view; }
    $("#uname").textContent = user.name;
    $("#mypin").classList.toggle("hidden", !can("descuentos") && !can("credito"));
    $("#urole").textContent = user.role;
    $("#avatar").textContent = user.initials;
    $$("[data-perm]").forEach((el) => el.classList.toggle("hidden", !can(...el.dataset.perm.split(" "))));
    $$("[data-perm-all]").forEach((el) => el.classList.toggle("hidden", !canAll(...el.dataset.permAll.split(" "))));
    LIC_ACTIVE = settings.modules || {};
    PLAN = { id: settings.plan || "todo", label: settings.plan_label || "" };
    applyPlanUi();
    IDLE_MIN = settings.idle_minutes ?? 30;
    POS_ON = settings.pos_enabled !== false || offlineStart;  // sin punto de venta se factura desde Ventas (en modo sin conexión sí hace falta)
    $$('[data-view="pos"]').forEach((el) => el.classList.toggle("hidden", !POS_ON || !canAll("facturar", "cobrar")));
    if (Array.isArray(settings.price_names) && settings.price_names.length === 4) priceNames = settings.price_names;
    $("#co-name").textContent = settings.name;
    $("#co-rif").textContent = "RTN " + settings.rtn;
    const logo = $("#co-logo");
    if (settings.logo) { logo.src = settings.logo; logo.classList.remove("hidden"); } else logo.classList.add("hidden");
    if (!canView(view)) view = "inicio";
    const home = typeof homeViewFor === "function" ? homeViewFor(user) : null;
    if (home && view === "inicio") view = home;  // el mesero entra al salón y la cocina a su pantalla
    $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
    await render();
  } catch (err) { /* si la sesión expiró api() ya volvió al login */ }
}

async function render() {
  const root = $("#view");
  (window.viewCleanup || []).splice(0).forEach((stop) => { try { stop(); } catch (e) { /* nada */ } });  // detiene los temporizadores de la pantalla anterior
  root.innerHTML = `<p class="muted">Cargando...</p>`;
  const q = pendingQuery; pendingQuery = "";
  try {
    if (!canView(view)) view = "inicio";
    const views = {
      inicio: renderHome, ventas: (r) => renderDocs(r, ""), cxc: (r) => renderDocs(r, "cxc"), inventario: (r) => renderProducts(r, q),
      bodegas: renderWarehouses, catalogo: renderCatalog, clientes: (r) => renderClients(r, q), proveedores: renderSuppliers,
      bancos: renderBanks, reportes: renderReports, config: renderSettings, caja: renderCashClose, bitacora: renderAudit, pos: renderPos, cxp: renderPayables, conteo: renderCounts, etiquetas: renderLabels, reabastecer: renderReplenish, salon: renderSalon, cocina: renderKitchen, restaurante: renderRestaurant,
    };
    await (views[view] || renderHome)(root);
  } catch (err) { root.innerHTML = `<div class="card"><p>${esc(err.message)}</p></div>`; }
}

function table(headers, rows, empty = "Sin registros") {
  return `<div class="tbl-wrap"><table><thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.join("") || `<tr><td colspan="${headers.length}" class="muted">${esc(empty)}</td></tr>`}</tbody></table></div>`;
}

/* ───────── inicio ───────── */
function chart(months) {
  const max = Math.max(...months.flatMap((m) => [m.ingresos, m.egresos]), 1);
  const w = 640, gap = w / months.length;
  const bars = months.map((m, i) => {
    const hi = (Math.max(m.ingresos, 0) / max) * 150, he = (m.egresos / max) * 150, x = 30 + i * gap;
    return `<rect x="${x}" y="${170 - hi}" width="16" height="${hi}" rx="4" class="bar-in"><title>${m.label} · ventas ${money(m.ingresos)}</title></rect>
            <rect x="${x + 20}" y="${170 - he}" width="16" height="${he}" rx="4" class="bar-out"><title>${m.label} · compras ${money(m.egresos)}</title></rect>
            <text x="${x + 18}" y="196" font-size="12" text-anchor="middle">${m.label}</text>`;
  }).join("");
  return `<svg class="chart" viewBox="0 0 ${w} 210" role="img" aria-label="Ventas y compras de los últimos 6 meses">${bars}</svg>`;
}

/** Gráfica de barras simple en SVG (sin librerías: funciona sin internet). */
function barChart(points, { height = 150, every = 1, label = "" } = {}) {
  const max = Math.max(...points.map((p) => p.value), 1);
  const w = 640, slot = (w - 20) / points.length, bw = Math.max(Math.min(slot * 0.68, 28), 3);
  const bars = points.map((p, i) => {
    const h = (Math.max(p.value, 0) / max) * height, x = 10 + i * slot + (slot - bw) / 2;
    return `<rect x="${x.toFixed(1)}" y="${(height + 8 - h).toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" rx="3" class="${p.hi ? "bar-in" : "bar-soft"}"><title>${esc(p.title)}</title></rect>`
      + (i % every === 0 || p.hi ? `<text x="${(x + bw / 2).toFixed(1)}" y="${height + 26}" font-size="11" text-anchor="middle">${esc(p.label)}</text>` : "");
  }).join("");
  return `<svg class="chart" viewBox="0 0 ${w} ${height + 34}" role="img" aria-label="${esc(label)}">${bars}</svg>`;
}

function kpi(label, value, delta, note = "") {
  if (value === null || value === undefined) return "";
  let line = `<div class="delta muted">Sin período anterior para comparar</div>`;
  if (delta !== null && delta !== undefined) {
    const up = delta >= 0;
    line = `<div class="delta ${up ? "up" : "down"}">${up ? "↑" : "↓"} ${Math.abs(delta)}% vs. período anterior</div>`;
  }
  if (note) line = `<div class="delta muted">${note}</div>`;
  return `<div class="card kpi"><small>${label}</small><strong>${money(value)}</strong>${line}</div>`;
}

function docTable(rows) {
  return table(["DOCUMENTO", "CLIENTE", "TIPO", "TOTAL", "ESTADO", "FECHA", ""], rows.map((r) => `<tr><td class="nowrap">${esc(r.number)}</td><td><div class="who"><div class="mini" style="background:${esc(r.color)}">${esc(r.initials)}</div>${esc(r.client)}</div></td><td>${esc(r.kind_label)}</td><td class="nowrap num">${money(r.total)}</td><td>${pill(r.status)}</td><td class="nowrap">${when(r.issued_at)}</td><td><button class="btn ghost sm" data-view-doc="${r.id}">Ver</button></td></tr>`), "Sin movimientos");
}

function bindDocButtons(root) {
  $$("[data-view-doc]", root).forEach((b) => b.onclick = () => showDoc(b.dataset.viewDoc));
  $$("[data-print]", root).forEach((b) => b.onclick = () => safePrint(printDoc, b.dataset.print));
  $$("[data-ticket]", root).forEach((b) => b.onclick = () => safePrint(printTicket, b.dataset.ticket));
  $$("[data-pay]", root).forEach((b) => b.onclick = () => payDoc(b.dataset.pay));
  $$("[data-quote-invoice]", root).forEach((b) => b.onclick = () => invoiceQuote(b.dataset.quoteInvoice));
}

async function renderHome(root) {
  const [d, settings, ins] = await Promise.all([api("/api/dashboard?period=" + period), api("/api/settings"), api("/api/dashboard/insights?period=" + period)]);
  $("#badge-sales").textContent = d.counts.sales;
  $("#badge-cxc").textContent = d.counts.receivables;
  const hour = new Date().getHours();
  const greet = hour < 12 ? "Buenos días" : hour < 19 ? "Buenas tardes" : "Buenas noches";
  const caiText = !d.cai ? "Sin CAI vigente: no se puede facturar." : `CAI vigente: quedan ${d.cai.left} correlativos y ${d.cai.days_left} días (hasta ${dateOnly(d.cai.limit)}).`;
  root.innerHTML = `
    <div class="hello">
      <div class="hello-brand">${settings.logo ? `<img class="dash-logo" src="${esc(settings.logo)}" alt="Logo" />` : ""}<div><div class="muted">${new Date().toLocaleDateString("es-HN", { weekday: "long", day: "numeric", month: "long" })}</div>
      <h2>${greet}, ${esc(user.name.split(" ")[0])}</h2><p>${esc(settings.name)}. Facturación con CAI del SAR.</p></div></div>
      <div class="actions">
        ${can("reportes") ? `<button class="btn" id="export">Exportar libro de ventas</button>` : ""}
        <select id="period" aria-label="Período"><option value="month">Este mes</option><option value="quarter">Trimestre</option><option value="year">Año</option><option value="all">Todo</option></select>
        ${can("facturar") ? `<button class="btn primary" id="new-sale">+ Nueva venta</button>` : ""}
      </div>
    </div>
    <div class="grid-4">
      ${kpi("Ventas netas", d.sales, d.sales_delta)}
      ${kpi("Cuentas por cobrar", d.receivables, null, d.counts.overdue ? `<span class="down">${d.counts.overdue} factura(s) vencida(s)</span>` : `${d.counts.receivables} factura(s) abiertas`)}
      ${kpi("Compras", d.purchases, d.purchases_delta)}
      ${kpi("Utilidad estimada", d.utility, d.utility_delta)}
    </div>
    <div class="grid-2">
      <div class="card"><div class="section-head"><div><h3>Resumen de ventas</h3><div class="muted"><span class="dot g"></span>Ventas netas <span class="dot m"></span>Compras · últimos 6 meses</div></div></div>${chart(d.months)}</div>
      <div class="card">
        <h3>Accesos rápidos</h3>
        <div class="quick">
          ${can("facturar") ? `<button class="qbtn" data-go="factura">Nueva factura <span>›</span></button>` : ""}
          ${can("cotizar") ? `<button class="qbtn" data-go="cotizacion">Cotización <span>›</span></button>` : ""}
          ${can("clientes") ? `<button class="qbtn" data-go="cliente">Nuevo cliente <span>›</span></button>` : ""}
          ${can("catalogo") ? `<button class="qbtn" data-go="producto">Añadir producto <span>›</span></button>` : `<button class="qbtn" data-go="inventario">Ver inventario <span>›</span></button>`}
        </div>
        <h3 style="margin-top:16px">Alertas</h3>
        ${ins.alerts.length ? ins.alerts.map((a, i) => `<div class="alert lvl-${a.level}"><div><strong>${esc(a.title)}</strong><div class="muted">${esc(a.text)}</div></div><button class="btn warn" data-alert="${i}">Ver</button></div>`).join("")
          : `<div class="alert ok"><div><strong>Todo en orden</strong><div class="muted">${caiText} Bodegas activas: ${d.warehouses}.</div></div></div>`}
      </div>
    </div>
    <div class="grid-2" style="margin-top:12px">
      <div class="card today-card"><div class="section-head"><div><h3>Hoy</h3><div class="muted">${new Date().toLocaleDateString("es-HN", { weekday: "long", day: "numeric", month: "long" })}</div></div>
          ${ins.today.delta === null ? "" : `<span class="delta ${ins.today.delta >= 0 ? "up" : "down"}">${ins.today.delta >= 0 ? "↑" : "↓"} ${Math.abs(ins.today.delta)}% vs. ayer</span>`}</div>
        <div class="today-kpis"><div><small>Vendido</small><strong>${money(ins.today.sales)}</strong></div><div><small>Facturas</small><strong>${ins.today.tickets}</strong></div><div><small>Ticket promedio</small><strong>${money(ins.today.average)}</strong></div><div><small>Ayer</small><strong>${money(ins.today.yesterday)}</strong></div></div>
        <div class="muted small">Ventas por hora</div>
        ${(() => {
          const now = new Date().getHours(), sold = ins.hours.map((v, h) => (v ? h : -1)).filter((h) => h >= 0);
          const from = Math.min(6, ...sold), to = Math.min(23, Math.max(20, now, ...sold)); // 6h a 20h, y más si hubo ventas o ya es de noche
          return barChart(ins.hours.map((v, h) => ({ value: v, label: `${h}h`, title: `${h}:00 a ${h}:59 · ${money(v)}`, hi: h === now })).slice(from, to + 1), { height: 110, every: to - from > 14 ? 3 : 2, label: "Ventas por hora de hoy" });
        })()}</div>
      <div class="card"><h3>Ventas de los últimos 30 días</h3><div class="muted small">Ventas netas por día (las notas de crédito restan)</div>
        ${barChart(ins.daily.map((x, i) => { const dt = new Date(x.date + "T00:00:00"); return { value: x.total, label: `${dt.getDate()}/${dt.getMonth() + 1}`, title: `${dt.toLocaleDateString("es-HN", { weekday: "short", day: "numeric", month: "short" })} · ${money(x.total)}`, hi: i === ins.daily.length - 1 }; }), { height: 150, every: 5, label: "Ventas por día" })}</div>
    </div>
    <div class="grid-2" style="margin-top:12px">
      <div class="card"><h3>Más vendidos</h3><div class="muted small">${{ month: "Este mes", quarter: "Este trimestre", year: "Este año", all: "Desde el inicio" }[period] || ""} · importe sin ISV</div>
        ${ins.top_products.length ? `<div class="toplist">${ins.top_products.map((p, i) => { const pct = (p.amount / Math.max(ins.top_products[0].amount, 1)) * 100; return `<div class="toprow"><span class="rank">${i + 1}</span><div class="topinfo"><div class="topname">${esc(p.name)} <span class="muted small">${esc(p.sku)}</span></div><div class="rankbar"><span style="width:${pct.toFixed(1)}%"></span></div><div class="muted small">${Number(p.qty.toFixed(2))} ${esc(p.unit)}${p.cost !== undefined && p.amount ? ` · margen ${Math.round(((p.amount - p.cost) / p.amount) * 100)}%` : ""}</div></div><strong class="nowrap">${money(p.amount)}</strong></div>`; }).join("")}</div>` : `<p class="muted">Todavía no hay ventas en este período.</p>`}</div>
      <div class="card"><h3>Mejores clientes</h3>
        ${table(["CLIENTE", "FACTURAS", "COMPRADO"], ins.top_clients.map((c) => `<tr><td>${esc(c.name)}</td><td>${c.docs}</td><td class="nowrap"><strong>${money(c.total)}</strong></td></tr>`), "Sin ventas en este período")}
        ${ins.margin ? `<div class="margin-box"><div><small>Vendido (sin ISV)</small><strong>${money(ins.margin.sales)}</strong></div><div><small>Costo</small><strong>${money(ins.margin.cost)}</strong></div><div><small>Utilidad bruta</small><strong class="${ins.margin.profit >= 0 ? "up" : "down"}">${money(ins.margin.profit)}${ins.margin.pct !== null ? ` · ${ins.margin.pct}%` : ""}</strong></div></div>` : ""}</div>
    </div>
    <div class="card" style="margin-top:12px"><h3>Actividad reciente</h3>${docTable(d.recent)}</div>`;
  $("#period").value = period;
  $("#period").onchange = (e) => { period = e.target.value; render(); };
  if ($("#new-sale")) $("#new-sale").onclick = () => newDocument("factura");
  if ($("#export")) $("#export").onclick = () => exportCsv(`/api/reports/libro-ventas.csv?period=${period}`, "libro-de-ventas.csv");
  $$(".qbtn", root).forEach((b) => b.onclick = () => quick(b.dataset.go));
  $$("[data-alert]", root).forEach((b) => b.onclick = () => { const a = ins.alerts[+b.dataset.alert]; if (a.go === "caja") cashTab = "historial"; goto(a.go); });
  bindDocButtons(root);
}

function quick(kind) {
  if (kind === "factura" || kind === "cotizacion") return newDocument(kind);
  if (kind === "cliente") return goto("clientes").then(() => $("#add") && $("#add").click());
  if (kind === "producto") return goto("inventario").then(() => $("#add") && $("#add").click());
  return goto(kind);
}

/* ───────── ventas y cuentas por cobrar ───────── */
const OPEN_STATES = ["Pendiente", "Parcial", "Vencida"];

function docRowActions(r, compact = false) {
  const open = r.kind === "factura" && OPEN_STATES.includes(r.status);
  const quoteOpen = r.kind === "cotizacion" && !["Facturada", "Cancelada"].includes(r.stored_status);
  return `<button class="btn ghost sm" data-view-doc="${r.id}">Ver</button>` +
    (open && can("cobrar") ? `<button class="btn sm" data-pay="${r.id}">Cobrar</button>` : "") +
    (quoteOpen && can("facturar") ? `<button class="btn sm" data-quote-invoice="${r.id}">Facturar</button>` : "") +
    (compact ? "" : `<button class="btn ghost sm" data-print="${r.id}">Imprimir</button>`);
}

async function renderDocs(root, mode) {
  const cxc = mode === "cxc";
  const [rows, stores] = await Promise.all([api("/api/documents" + (cxc ? "?kind=factura" : "")), Promise.resolve([])]);
  const mainStore = (stores.find((x) => x.main) || {}).id;
  const list = rows.filter((r) => {
    if (cxc) return OPEN_STATES.includes(r.status);
    if (docFilter.store && (r.store_id || mainStore) !== +docFilter.store) return false;
    if (docFilter.kind && r.kind !== docFilter.kind) return false;
    if (docFilter.status && r.status !== docFilter.status) return false;
    const q = docFilter.q.trim().toLowerCase();
    return !q || `${r.number} ${r.client} ${r.rtn} ${r.client_ref}`.toLowerCase().includes(q);
  });
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const late = (r) => (r.due_date ? Math.max(Math.floor((today - new Date(r.due_date + "T00:00:00")) / 86400000), 0) : 0);
  const balance = list.reduce((s, r) => s + r.balance, 0);
  const headers = cxc ? ["FACTURA", "CLIENTE", "VENCE", "ATRASO", "TOTAL", "ABONADO", "SALDO", "ESTADO", ""] : ["DOCUMENTO", "CLIENTE", "FECHA", "TIPO", "TOTAL", "ESTADO", ""];
  const clientCell = (r) => `<td class="client-cell">${esc(r.client)}<div class="muted small">RTN ${esc(r.rtn || "Consumidor final")}</div></td>`;
  const body = list.map((r) => cxc
    ? `<tr><td class="nowrap">${esc(r.number)}</td>${clientCell(r)}<td class="nowrap">${dateOnly(r.due_date)}</td><td>${late(r) ? `<span class="down">${late(r)} días</span>` : "—"}</td><td class="nowrap num">${money(r.total)}</td><td>${money(r.paid)}</td><td><strong>${money(r.balance)}</strong></td><td>${pill(r.status)}</td><td class="row-actions">${docRowActions(r, true)}</td></tr>`
    : `<tr><td class="nowrap">${esc(r.number)}</td>${clientCell(r)}<td class="nowrap">${when(r.issued_at)}</td><td>${esc(r.kind_label)}</td><td class="nowrap num">${money(r.total)}</td><td>${pill(r.status)}</td><td class="row-actions">${docRowActions(r)}</td></tr>`);
  const statuses = [...new Set(rows.map((r) => r.status))];
  root.innerHTML = `<div class="section-head"><h2>${cxc ? "Cuentas por cobrar" : "Ventas"}</h2>
    <div class="actions">${cxc ? `<button class="btn" id="cxc-csv">Exportar CSV</button>` : `${can("cotizar") ? `<button class="btn" id="new-quote">Cotización</button>` : ""}${can("anular") ? `<button class="btn" id="new-note">Nota de crédito</button>` : ""}`}${can("facturar") ? `<button class="btn primary" id="new-inv">Nueva factura</button>` : ""}</div></div>
    ${cxc ? `<div class="card kpi inline"><small>Saldo por cobrar</small><strong>${money(balance)}</strong><span class="muted">${list.length} factura(s) abiertas</span></div>` : `<div class="toolbar">
      <input id="f-q" placeholder="Buscar por número, cliente o RTN" value="${esc(docFilter.q)}" />
      <select id="f-kind"><option value="">Todos los tipos</option><option value="factura">Facturas</option><option value="cotizacion">Cotizaciones</option><option value="nota">Notas de crédito</option><option value="debito">Notas de débito</option></select>
      <select id="f-status"><option value="">Todos los estados</option>${statuses.map((s) => `<option>${esc(s)}</option>`).join("")}</select>
      ${stores.length > 1 ? `<select id="f-store"><option value="">Todas las tiendas</option>${stores.map((x) => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select>` : ""}</div>`}
    <div class="card">${table(headers, body, cxc ? "No hay facturas pendientes de cobro" : "No hay documentos con ese filtro")}</div>`;
  if ($("#new-inv")) $("#new-inv").onclick = () => newDocument("factura");
  if (cxc) $("#cxc-csv").onclick = () => exportCsv("/api/reports/cxc.csv", "cuentas-por-cobrar.csv");
  else {
    if ($("#new-quote")) $("#new-quote").onclick = () => newDocument("cotizacion");
    if ($("#new-note")) $("#new-note").onclick = () => pickInvoiceForNote(rows);
    $("#f-kind").value = docFilter.kind; $("#f-status").value = docFilter.status;
    $("#f-kind").onchange = (e) => { docFilter.kind = e.target.value; render(); };
    $("#f-status").onchange = (e) => { docFilter.status = e.target.value; render(); };
    if ($("#f-store")) { $("#f-store").value = docFilter.store; $("#f-store").onchange = (e) => { docFilter.store = e.target.value; render(); }; }
    let t; $("#f-q").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { docFilter.q = e.target.value; render().then(() => { const i = $("#f-q"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }); }, 300); };
  }
  bindDocButtons(root);
}

async function showDoc(id) {
  const { document: d } = await api("/api/documents/" + id);
  const open = d.kind === "factura" && OPEN_STATES.includes(d.status);
  const quoteOpen = d.kind === "cotizacion" && !["Facturada", "Cancelada"].includes(d.stored_status);
  const activeNotes = [...(d.credit_notes || []), ...(d.debit_notes || [])].filter((n) => n.status !== "Anulada");
  const canDebit = can("anular") && d.kind === "factura" && d.stored_status !== "Anulada" && modOn("docs_fiscales");
  const canVoid = can("anular") && !["Anulada", "Cancelada", "Facturada"].includes(d.stored_status) && !(d.kind === "factura" && (d.paid > 0 || activeNotes.length));
  const canCredit = can("anular") && d.kind === "factura" && d.stored_status !== "Anulada" && d.creditable_amount > 0.005 && Object.keys(d.creditable || {}).length > 0;
  const items = table(["DESCRIPCIÓN", "CANT.", "UdM", "PRECIO", "DESCUENTO", "ISV", "IMPORTE"], d.items.map((i) => `<tr><td>${esc(i.description)}</td><td>${i.qty}</td><td>${esc(i.unit)}</td><td>${money(i.price)}</td><td>${i.discount ? money(i.discount) : "—"}</td><td>${TAX_LABEL[i.tax_treatment] || ""}</td><td>${money(i.total)}</td></tr>`));
  const pays = d.payments.length ? table(["FECHA", "FORMA", "NOTA", "COBRÓ", "MONTO"], d.payments.map((p) => `<tr><td>${when(p.created_at)}</td><td>${esc(p.method)}</td><td>${esc(p.note)}</td><td>${esc(p.user || "—")}</td><td>${money(p.amount)}</td></tr>`)) : "";
  const notes = (d.credit_notes || []).length ? table(["NOTA DE CRÉDITO", "FECHA", "ESTADO", "MONTO", ""], d.credit_notes.map((n) => `<tr><td>${esc(n.number)}</td><td>${when(n.issued_at)}</td><td>${pill(n.status)}</td><td>${money(n.total)}</td><td><button type="button" class="btn ghost sm" data-open-doc="${n.id}">Ver</button></td></tr>`)) : "";
  openForm(`${d.kind_label} ${d.number}`, `<div class="full docview">
      <div class="docmeta"><div><small class="muted">Cliente</small><br><strong>${esc(d.client)}</strong><br>RTN ${esc(d.rtn || "Consumidor final")}</div>
      <div><small class="muted">Emisión / vence</small><br>${when(d.issued_at)}<br>${dateOnly(d.due_date || d.validity_date)}</div>
      <div><small class="muted">Estado</small><br>${pill(d.status)}<br><span class="muted">${esc(d.warehouse)} · Serie ${esc(d.series || "—")}${d.kind !== "nota" && d.kind !== "debito" ? ` · Precio ${esc(levelName(d.price_level))}` : ""}</span></div>
      <div><small class="muted">${d.kind === "nota" || d.kind === "debito" ? "Factura que modifica" : "Emitido por"}</small><br>${d.kind === "nota" || d.kind === "debito" ? (d.ref_document_id ? `<button type="button" class="btn ghost sm" data-open-doc="${d.ref_document_id}">${esc(d.ref_number)}</button>` : esc(d.ref_number || "—")) : ""}${d.kind === "nota" || d.kind === "debito" ? `<br><span class="muted">${esc(d.user || "")}</span>` : esc(d.user || "—")}</div></div>
      ${items}
      <div class="docsum"><div>Gravado 15% ${money(d.gravado_15)} · ISV ${money(d.isv_15)}</div><div>Gravado 18% ${money(d.gravado_18)} · ISV ${money(d.isv_18)}</div><div>Exento ${money(d.exento)} · Exonerado ${money(d.exonerado)}</div>
      <div><strong>Total ${money(d.total)}</strong>${d.kind === "factura" ? ` · Abonado ${money(d.paid)}${d.debited ? ` · Cargos (notas de débito) ${money(d.debited)}` : ""}${d.credited ? ` · Acreditado ${money(d.credited)}` : ""} · <strong>Saldo ${money(d.balance)}</strong>` : ""}</div></div>
      <p class="muted">${esc(d.amount_words)}${d.cai ? `<br>CAI ${esc(d.cai)} · ${esc(d.range_label)} · límite ${dateOnly(d.limit_date)}` : ""}${exoBlock(d) ? `<br>${exoBlock(d)}` : ""}${d.discount ? `<br>Descuentos y rebajas: ${money(d.discount)}${d.discount_auth ? ` · autorizado por ${esc(d.discount_auth)}` : ""}` : ""}${d.notes ? `<br>Notas: ${esc(d.notes)}` : ""}</p>
      ${pays ? `<h4>Cobros</h4>${pays}` : ""}
      ${notes ? `<h4>Notas de crédito</h4>${notes}` : ""}
      ${(d.debit_notes || []).length ? `<h4>Notas de débito</h4>${table(["NOTA DE DÉBITO", "FECHA", "ESTADO", "MONTO", ""], d.debit_notes.map((n) => `<tr><td>${esc(n.number)}</td><td>${when(n.issued_at)}</td><td>${pill(n.status)}</td><td>${money(n.total)}</td><td><button type="button" class="btn ghost sm" data-open-doc="${n.id}">Ver</button></td></tr>`))}` : ""}
      <div class="actions" style="margin-top:12px">
        <button type="button" class="btn" data-a="print">Imprimir</button><button type="button" class="btn" data-a="ticket">Ticket</button>
        <button type="button" class="btn" data-a="pdf">PDF</button>${can("cotizar", "facturar", "cobrar") ? `<button type="button" class="btn" data-a="email">Enviar por correo</button>` : ""}
        ${open && can("cobrar") ? `<button type="button" class="btn primary" data-a="pay">Cobrar</button>` : ""}
        ${quoteOpen && can("facturar") ? `<button type="button" class="btn primary" data-a="invoice">Convertir en factura</button>` : ""}
        ${quoteOpen && can("cotizar") ? `<select id="quote-state" aria-label="Estado de la cotización">${["Pendiente", "Cotización enviada", "Orden de venta"].map((s) => `<option ${s === d.stored_status ? "selected" : ""}>${s}</option>`).join("")}</select>` : ""}
        ${canCredit ? `<button type="button" class="btn" data-a="credit">Nota de crédito</button>` : ""}
        ${canDebit ? `<button type="button" class="btn" data-a="debit">Nota de débito</button>` : ""}
        ${canVoid ? `<button type="button" class="btn danger" data-a="void">${d.kind === "cotizacion" ? "Cancelar" : "Anular"}</button>` : ""}
      </div></div>`, null, {
    wide: true,
    mount: (form) => {
      const on = (a, fn) => { const b = $(`[data-a=${a}]`, form); if (b) b.onclick = fn; };
      on("print", () => safePrint(printDoc, d.id));
      on("ticket", () => safePrint(printTicket, d.id));
      on("pdf", () => downloadApi(`/api/documents/${d.id}/pdf`, `${d.number}.pdf`).catch((err) => toast(err.message, "err")));
      on("email", () => emailDoc(d));
      on("pay", () => payDoc(d.id));
      on("invoice", () => invoiceQuote(d.id));
      on("credit", () => { closeModal(); newDocument("nota", { from: d }); });
      on("debit", () => { closeModal(); debitNoteForm(d); });
      $$("[data-open-doc]", form).forEach((b) => b.onclick = () => showDoc(b.dataset.openDoc));
      on("void", async () => {
        const msg = d.kind === "cotizacion" ? "¿Cancelar esta cotización?" : `¿Anular ${d.number}? El número fiscal queda registrado como anulado y las existencias regresan al inventario.`;
        if (await askConfirm(msg, "Sí, anular", true)) run(() => api(`/api/documents/${d.id}/void`, { method: "POST" }), "Documento anulado");
      });
      if ($("#quote-state")) $("#quote-state").onchange = (e) => { closeModal(); run(() => api(`/api/documents/${d.id}/status?status=${encodeURIComponent(e.target.value)}`, { method: "POST" }), "Estado actualizado"); };
    },
  });
}

/** Envía el documento en PDF por correo (al correo del cliente si lo tiene). */
function emailDoc(d) {
  if (!modOn("email")) return lockedPopup("email");
  openModal(`Enviar ${d.kind_label.toLowerCase()} ${d.number}`, [
    { type: "info", html: `Se envía el PDF de la ${esc(d.kind_label.toLowerCase())} a nombre de <strong>${esc(d.client)}</strong>. Varios correos se separan con coma.` },
    { name: "to", label: "Para", value: d.client_email || "", required: true, full: true, placeholder: "cliente@empresa.hn" },
    { name: "cc", label: "Copia (opcional)", full: true },
    { name: "message", label: "Mensaje (opcional)", type: "textarea", full: true },
  ], async (b) => {
    await api(`/api/documents/${d.id}/email`, { method: "POST", body: { to: b.to, cc: b.cc, message: b.message } });
    toast(`${d.kind_label} ${d.number} enviada a ${b.to}`);
    return "stay";
  }, { submitLabel: "Enviar" });
}

/** La nota de crédito siempre se emite contra una factura: primero se elige cuál. */
function pickInvoiceForNote(rows) {
  const invoices = rows.filter((r) => r.kind === "factura" && r.stored_status !== "Anulada" && r.stored_status !== "Acreditada");
  if (!invoices.length) return toast("No hay facturas vigentes para acreditar", "err");
  openModal("Nota de crédito", [
    { type: "info", html: "Elige la factura que se acredita. La nota devuelve las existencias y rebaja el saldo de esa factura." },
    { name: "invoice", label: "Factura", type: "select", full: true, options: invoices.map((r) => ({ value: r.id, label: `${r.number} · ${r.client} · ${money(r.total)} · ${r.status}` })) },
  ], async (b) => {
    const { document: d } = await api("/api/documents/" + b.invoice);
    if (!(d.creditable_amount > 0.005) || !Object.keys(d.creditable || {}).length) throw new Error(`La factura ${d.number} ya está acreditada por completo`);
    newDocument("nota", { from: d });
    return "stay"; // el editor reemplaza la vista: no hay que volver a dibujar Ventas
  }, { submitLabel: "Continuar" });
}

async function payDoc(id) {
  const [{ document: d }, banks] = await Promise.all([api("/api/documents/" + id), api("/api/banks/accounts")]);
  openModal(`Cobrar ${d.number}`, [
    { type: "info", html: `<strong>${esc(d.client)}</strong> · Total ${money(d.total)} · Abonado ${money(d.paid)} · <strong>Saldo ${money(d.balance)}</strong>` },
    { name: "amount", label: "Monto a cobrar", type: "number", step: "0.01", min: "0.01", max: d.balance, value: d.balance.toFixed(2), required: true },
    { name: "method", label: "Forma de pago", type: "select", options: ["Efectivo", "Transferencia", "Tarjeta", "Cheque", "Depósito", "Retención ISV"].map((m) => ({ value: m, label: m === "Retención ISV" ? "Retención de ISV (comprobante del cliente)" : m })), hint: "Retención: el cliente es agente de retención; escribe el número de comprobante en la nota y no elijas cuenta." },
    { name: "bank_id", label: "Ingresa a la cuenta", type: "select", options: [{ value: "", label: "Sin registrar en bancos" }, ...banks.map((b) => ({ value: b.id, label: b.name }))] },
    { name: "note", label: "Nota (referencia, # de cheque, # de comprobante de retención…)" },
  ], async (b) => {
    await api(`/api/documents/${d.id}/payments`, { method: "POST", body: { amount: num(b.amount), method: b.method, bank_id: b.bank_id ? +b.bank_id : null, note: b.note } });
    toast("Cobro registrado");
  }, { submitLabel: "Registrar cobro" });
}

async function invoiceQuote(id) {
  const [series, { document: q }] = await Promise.all([api("/api/series"), api("/api/documents/" + id)]);
  openModal("Convertir cotización en factura", [
    { type: "info", html: "Se genera la factura con el siguiente correlativo del CAI y se descuentan las existencias de la bodega de la cotización." },
    { name: "series_id", label: "Serie", type: "select", options: series.map((s) => ({ value: s.id, label: seriesLabel(s) })), full: true },
    ...(q.client_exonerated ? [{ name: "oce_number", label: "Orden de Compra Exenta (el cliente es exonerado)", required: true, full: true, value: q.oce_number }] : []),
  ], async (b) => {
    const url = `/api/documents/${id}/invoice?series_id=${b.series_id}${b.oce_number ? "&oce_number=" + encodeURIComponent(b.oce_number.trim()) : ""}${b.auth_pin ? "&auth_pin=" + encodeURIComponent(b.auth_pin.trim()) : ""}`;
    let doc;
    try { doc = await api(url, { method: "POST" }); } catch (e) {
      if (e.needsAuth && !$("#modal-form [name=auth_pin]")) {
        $("#modal-form button[type=submit]").insertAdjacentHTML("beforebegin", `<label class="full">PIN del supervisor<input name="auth_pin" type="password" inputmode="numeric" autocomplete="one-time-code" maxlength="8" required /></label>`);
        $("#modal-form [name=auth_pin]").focus();
      }
      throw e;
    }
    toast(`Factura ${doc.number} creada`);
    safePrint(printDoc, doc.id);
  }, { submitLabel: "Facturar" });
}

/** Aviso de crédito del cliente en la factura: saldo, vencido y disponible (solo si vende al crédito o hay algo que advertir). */
function creditNote(c, terms, total) {
  if (!c || !c.id) return "";
  const credit = terms && terms !== "Contado";
  const parts = [];
  if (c.balance) parts.push(`debe ${money(c.balance)}`);
  if (c.overdue) parts.push(`<strong>vencido ${money(c.overdue)}</strong> (${c.overdue_count} factura${c.overdue_count === 1 ? "" : "s"})`);
  if (c.credit_limit) parts.push(`límite ${money(c.credit_limit)} · disponible ${money(c.available)}`);
  if (!parts.length || (!credit && !c.overdue)) return "";
  const blocked = credit && ((c.overdue && c.block_overdue) || (c.credit_limit && c.balance + total > c.credit_limit + 0.004));
  const extra = blocked ? (can("credito") ? " · Puedes venderle al crédito: quedará en la bitácora." : " · Para venderle al crédito se pedirá el PIN de un supervisor, o cobra de contado.") : "";
  return `<p class="${blocked ? "warn-note" : "info"}">Crédito de ${esc(c.name)}: ${parts.join(" · ")}${extra}</p>`;
}

/* ───────── editor de factura / cotización / nota ───────── */
async function newDocument(kind, opts = {}) {
  const from = kind === "nota" ? opts.from || null : null; // factura que se acredita
  const [clients, products, warehouses, series] = await Promise.all([api("/api/clients"), api("/api/products"), api("/api/warehouses"), kind === "factura" ? api("/api/series") : Promise.resolve([])]);
  const titles = { factura: "Nueva factura", cotizacion: "Nueva cotización", nota: "Nueva nota de crédito" };
  const offers = [];
  products.forEach((p) => p.presentations.forEach((pr) => offers.push({
    product_id: p.id, presentation_id: pr.id, sku: p.sku, name: p.name, present: pr.name,
    unit: pr.unit, factor: pr.factor, price: pr.price, prices: pr.prices || [pr.price, pr.price, pr.price, pr.price], raw: rawPrices(pr),
    tax: p.tax_treatment, stocks: p.stocks, base_unit: p.base_unit,
  })));
  const lines = [];
  view = "ventas";
  $$(".nav-btn").forEach((n) => n.classList.toggle("active", n.dataset.view === "ventas"));
  let saved = null;
  const what = { factura: "factura", cotizacion: "cotización", nota: "nota de crédito" }[kind];
  pendingWork = () => (!saved && lines.length ? `La ${what} tiene ${lines.length} producto(s) y no está guardada. Si sales, se pierde.` : null);
  let hits = [], hitIndex = 0, refocus = false;
  let tab = "lines";
  const state = { client_id: clients[0]?.id, warehouse_id: warehouses[0]?.id, series_id: series[0]?.id, terms: kind === "cotizacion" ? "15 días" : "Contado", due: "", ref: "", notes: "", level: clients[0]?.price_level || 1 };
  const curClient = () => clients.find((c) => c.id === +state.client_id) || {};
  const clientLevel = () => curClient().price_level || 1;
  const priceAt = (l) => l.prices[(+state.level || 1) - 1] ?? l.price;
  /** Al cambiar de cliente o de nivel, todas las líneas toman el precio del nivel elegido. */
  const reprice = () => lines.forEach((l) => { l.price = priceAt(l); });
  /** Opciones de precio para quien no puede escribir uno libre: solo los niveles con precio definido (más el precio 1). */
  const priceChoices = (l) => { const seen = new Set(); return l.prices.map((v, i) => ({ v, i })).filter(({ v, i }) => (i === 0 || l.raw[i] > 0) && !seen.has(v) && seen.add(v)); };
  const dueFromTerms = (t) => { const days = parseInt((t.match(/\d+/) || [0])[0], 10); const d = new Date(); d.setDate(d.getDate() + days); return d.toISOString().slice(0, 10); };
  state.due = dueFromTerms(state.terms);
  if (from) {
    Object.assign(state, { client_id: from.client_id, warehouse_id: from.warehouse_id, ref: from.number, terms: "Contado", level: from.price_level || 1 });
    // Precarga las líneas de la factura con lo que aún se puede acreditar (en unidades base, por producto).
    const left = { ...(from.creditable || {}) };
    from.items.forEach((it) => {
      const offer = offers.find((o) => o.presentation_id === it.presentation_id);
      const base = left[it.product_id] || 0;
      if (!offer || base <= 0) return;
      const qty = Math.min(it.qty, Math.floor((base / offer.factor) * 100) / 100);
      if (qty <= 0) return;
      left[it.product_id] = base - qty * offer.factor;
      const dunit = it.discount && it.qty ? it.discount / it.qty : 0; // la nota repite el descuento de la factura, por unidad
      lines.push({ ...offer, qty, price: it.price, tax: it.tax_treatment || offer.tax, dunit: dunit || null, discount: r2(dunit * qty) });
    });
  }
  const root = $("#view");
  const available = (l) => (l.stocks.find((s) => s.warehouse_id === +state.warehouse_id) || { qty: 0 }).qty;

  const totals = () => {
    const b = { exento: 0, exonerado: 0, gravado15: 0, gravado18: 0 };
    lines.forEach(redoDiscount); // un cambio de precio o de nivel no deja descuentos mayores que el importe
    lines.forEach((l) => { b[effTax(l.tax, curClient())] += lineNet(l); });
    const isv15 = r2(b.gravado15 * 0.15), isv18 = r2(b.gravado18 * 0.18);
    const sub = r2(b.exento + b.exonerado + b.gravado15 + b.gravado18);
    const disc = r2(lines.reduce((x, l) => x + (l.discount || 0), 0));
    return { ...b, isv15, isv18, sub, disc, total: r2(sub + isv15 + isv18) };
  };

  const overMsg = (l) => (kind === "factura" && l.qty * l.factor > available(l) ? `Solo hay ${available(l)} ${esc(l.base_unit)} en esta bodega (${l.qty * l.factor} requeridos)` : "");
  const totalsHtml = (t) => `${t.disc ? `<div><span>Descuentos y rebajas</span><span>− ${money(t.disc)}</span></div>` : ""}<div><span>Importe gravado 15%</span><span>${money(t.gravado15)}</span></div><div><span>ISV 15%</span><span>${money(t.isv15)}</span></div>
    ${t.gravado18 ? `<div><span>Importe gravado 18%</span><span>${money(t.gravado18)}</span></div><div><span>ISV 18%</span><span>${money(t.isv18)}</span></div>` : ""}
    ${t.exento ? `<div><span>Exento</span><span>${money(t.exento)}</span></div>` : ""}${t.exonerado ? `<div><span>Exonerado</span><span>${money(t.exonerado)}</span></div>` : ""}
    <div><strong>Total</strong><strong>${money(t.total)}</strong></div>`;
  /** Actualiza importes y avisos sin redibujar: así no se pierde el foco ni el clic en "Guardar". */
  const refresh = () => {
    const t = totals();
    lines.forEach((l, i) => {
      redoDiscount(l);
      if ($("#lt-" + i)) $("#lt-" + i).textContent = money(lineNet(l));
      const di = $(`[data-disc="${i}"]`);
      if (di && document.activeElement !== di) di.value = l.dpct != null ? `${l.dpct}%` : l.discount ? l.discount.toFixed(2) : "";
      if ($("#ld-" + i)) $("#ld-" + i).textContent = l.dpct != null && l.discount ? `= ${money(l.discount)}` : ""; if ($("#lw-" + i)) $("#lw-" + i).textContent = overMsg(l); });
    $("#totals-box").innerHTML = totalsHtml(t);
    $("#stock-warn").textContent = lines.some((l) => overMsg(l)) ? "Hay líneas que superan la existencia de la bodega elegida." : "";
  };

  const paint = () => {
    const t = totals();
    const lock = saved ? "disabled" : "";
    const canDiscount = !from; // la nota de crédito repite el descuento de la factura; sin permiso se pide el PIN de un supervisor
    const stockWarn = lines.some((l) => overMsg(l));
    root.innerHTML = `<div class="odoo">
      <div class="odoo-top">
        <div><div class="muted">Ventas / ${titles[kind]}</div><h2>${saved ? esc(saved.number) : "Nuevo"}</h2></div>
        <div class="odoo-actions">
          ${saved ? `<button class="btn primary" id="d-print">Imprimir</button><button class="btn" id="d-ticket">Ticket</button><button class="btn" id="d-email">Correo</button>${kind === "factura" && can("cobrar") ? `<button class="btn" id="d-pay">Cobrar</button>` : ""}<button class="btn" id="d-new">Crear otro</button>`
            : `<button class="btn primary" id="d-save">${kind === "factura" ? "Guardar e imprimir factura" : kind === "nota" ? "Guardar e imprimir nota" : "Guardar e imprimir cotización"}</button>${kind === "factura" && can("cobrar") ? `<button class="btn" id="d-savepay">Guardar y cobrar</button>` : ""}`}
          <button class="btn" id="d-back">Volver</button>
        </div>
        <div class="statusbar"><span class="${saved ? "" : "on"}">Borrador</span><span class="${saved ? "on" : ""}">${saved ? (kind === "cotizacion" ? "Guardada" : "Emitida") : (kind === "cotizacion" ? "Guardada" : "Emitida")}</span></div>
      </div>
      <div class="odoo-grid">
        <label>Cliente<span class="inline-field"><select id="f-client" ${lock || (from ? "disabled" : "")}>${clients.map((c) => `<option value="${c.id}" ${c.id === +state.client_id ? "selected" : ""}>${esc(c.name)}${c.rtn ? "" : " (sin RTN)"}</option>`).join("")}</select>${saved || from || !can("clientes") ? "" : `<button type="button" class="btn sm" id="f-newclient">+ Nuevo</button>`}</span></label>
        <label>Bodega<select id="f-wh" ${lock}>${warehouses.map((w) => `<option value="${w.id}" ${w.id === +state.warehouse_id ? "selected" : ""}>${esc(w.name)}</option>`).join("")}</select></label>
        <label>${kind === "cotizacion" ? "Válida hasta" : "Fecha de vencimiento"}<input id="f-due" type="date" value="${state.due}" ${lock} /></label>
        <label>Términos de pago<select id="f-terms" ${lock}>${["Contado", "15 días", "30 días", "45 días", "60 días"].map((o) => `<option ${o === state.terms ? "selected" : ""}>${o}</option>`).join("")}</select></label>
        ${from ? "" : `<label>Precio<select id="f-level" ${lock}>${levelOptions(state.level)}</select></label>`}
        ${!curClient().rtn && !from ? `<label>Nombre en la factura (opcional)<input id="f-bname" value="${esc(state.bname || "")}" maxlength="180" ${lock} placeholder="Si el comprador pide factura a su nombre" /></label>
          <label>RTN en la factura (opcional)<input id="f-brtn" value="${esc(state.brtn || "")}" maxlength="20" ${lock} placeholder="14 dígitos" /></label>` : ""}
        ${curClient().exonerated && kind !== "nota" ? `<label>Orden de Compra Exenta${kind === "factura" ? " (obligatoria)" : ""}<input id="f-oce" value="${esc(state.oce || "")}" maxlength="40" ${lock} placeholder="No. de OCE del cliente" /></label>` : ""}
        ${kind === "factura" ? `<label>Serie<select id="f-series" ${lock}>${series.map((s) => `<option value="${s.id}" ${s.id === +state.series_id ? "selected" : ""}>${esc(seriesLabel(s))}</option>`).join("")}</select></label>` : ""}
        <label>${kind === "nota" ? "Factura que se acredita" : "Referencia del cliente (orden de compra)"}<input id="f-ref" value="${esc(state.ref)}" ${lock || (from ? "readonly" : "")} /></label>
      </div>
      ${from && !saved ? `<p class="muted">Se acredita la factura <strong>${esc(from.number)}</strong>: quita las líneas que no regresan o baja las cantidades. Queda por acreditar hasta ${money(from.creditable_amount)}.</p>` : ""}
      ${kind === "factura" && !saved ? creditNote(curClient(), state.terms, t.total) : ""}
      ${curClient().exonerated ? `<p class="info">Cliente exonerado (constancia ${esc(curClient().exo_registry)}): las líneas gravadas se facturan exoneradas, sin ISV.</p>` : ""}
      <div class="tabs"><button class="${tab === "lines" ? "on" : ""}" data-tab="lines">Líneas</button><button class="${tab === "notes" ? "on" : ""}" data-tab="notes">Notas</button></div>
      ${tab === "lines" ? `<div class="tbl-wrap"><table><thead><tr><th>Código</th><th>Descripción</th><th>Cantidad</th><th>UdM</th><th>Precio unitario</th><th>Descuento${!from && !can("descuentos") ? ` <span class="muted small" title="Al guardar, un supervisor lo aprueba con su PIN">· con PIN</span>` : ""}</th><th>ISV</th><th>Importe</th><th></th></tr></thead><tbody>
        ${lines.map((l, i) => { return `<tr><td>${esc(l.sku)}</td><td>${esc(l.name)} · ${esc(l.present)}<div class="down small" id="lw-${i}">${overMsg(l)}</div></td><td><input data-qty="${i}" type="number" step="0.01" min="0.01" value="${l.qty}" ${lock} /></td><td>${esc(l.unit)}</td><td>${can("precios") || from ? `<input data-price="${i}" type="number" step="0.01" min="0" value="${l.price}" ${lock} ${can("precios") ? "" : "readonly"} />`
          : `<select data-pricesel="${i}" ${lock} title="Tu rol elige entre los precios del catálogo">${priceChoices(l).map(({ v, i: n }) => `<option value="${v}" ${Math.abs(v - l.price) < 0.005 ? "selected" : ""}>${esc(levelName(n + 1))} · ${money(v)}</option>`).join("")}</select>`}</td><td>${canDiscount ? `<input data-disc="${i}" class="disc-input" inputmode="decimal" placeholder="L o %" value="${l.dpct != null ? `${l.dpct}%` : l.discount ? l.discount.toFixed(2) : ""}" ${lock} title="Lempiras, o porcentaje con %" /><div class="muted small" id="ld-${i}">${l.dpct != null && l.discount ? `= ${money(l.discount)}` : ""}</div>` : l.discount ? money(l.discount) : "—"}</td><td>${TAX_LABEL[effTax(l.tax, curClient())]}</td><td id="lt-${i}">${money(lineNet(l))}</td><td>${saved ? "" : `<button class="btn ghost sm" data-del="${i}" type="button" aria-label="Quitar línea">✕</button>`}</td></tr>`; }).join("") || `<tr><td colspan="9" class="muted">Busca un producto para agregarlo</td></tr>`}
        </tbody></table></div>
        ${saved ? "" : `<div class="sale-search"><input id="sale-q" placeholder="Escribe el SKU o la descripción (Enter agrega · ↑↓ navega)" autocomplete="off" /><div id="sale-hits" class="sale-hits"></div></div>`}`
        : `<label class="full">Notas del documento<textarea id="f-notes" rows="4" ${lock}>${esc(state.notes)}</textarea></label>`}
      <p class="form-error" id="stock-warn">${stockWarn ? "Hay líneas que superan la existencia de la bodega elegida." : ""}</p>
      <div class="odoo-foot"><div class="odoo-totals" id="totals-box">${totalsHtml(t)}</div></div>
      <p id="doc-error" class="form-error"></p>
    </div>`;
    bind();
  };

  const sync = () => {
    if ($("#f-client")) state.client_id = +$("#f-client").value;
    if ($("#f-wh")) state.warehouse_id = +$("#f-wh").value;
    if ($("#f-due")) state.due = $("#f-due").value;
    if ($("#f-terms")) state.terms = $("#f-terms").value;
    if ($("#f-series")) state.series_id = +$("#f-series").value;
    if ($("#f-level")) state.level = +$("#f-level").value;
    if ($("#f-oce")) state.oce = $("#f-oce").value;
    if ($("#f-bname")) state.bname = $("#f-bname").value;
    if ($("#f-brtn")) state.brtn = $("#f-brtn").value;
    if ($("#f-ref")) state.ref = $("#f-ref").value;
    if ($("#f-notes")) state.notes = $("#f-notes").value;
  };

  const addOffer = (offer) => {
    sync();
    const found = lines.find((l) => l.presentation_id === offer.presentation_id);
    if (found) found.qty += 1; else { const l = { ...offer, qty: 1 }; l.price = priceAt(l); lines.push(l); }
    refocus = true;
    paint();
  };
  const searchHits = (showAll) => {
    const input = $("#sale-q"); if (!input) return;
    const q = input.value.trim().toLowerCase();
    const box = $("#sale-hits");
    hits = showAll || !q ? offers.slice() : offers.filter((o) => `${o.sku} ${o.name} ${o.present}`.toLowerCase().includes(q));
    hitIndex = 0;
    if (!showAll && !q) { box.classList.remove("open"); return; }
    box.innerHTML = hits.map((o, i) => {
      const st = (o.stocks.find((s) => s.warehouse_id === +state.warehouse_id) || { qty: 0 }).qty;
      return `<button type="button" data-hit="${i}" class="${i === 0 ? "active" : ""}">${esc(o.sku)} · ${esc(o.name)} · ${esc(o.present)} · ${money(o.price)} · stock ${st}</button>`;
    }).join("") || `<button type="button">Sin productos</button>`;
    box.classList.add("open");
    $$("[data-hit]", box).forEach((b) => b.onmousedown = (e) => { e.preventDefault(); addOffer(hits[+b.dataset.hit]); });
  };

  const payload = () => {
    sync();
    return {
      kind, client_id: +state.client_id, warehouse_id: +state.warehouse_id, series_id: kind === "factura" ? state.series_id || null : null,
      due_date: state.due || null, validity_date: kind === "cotizacion" ? state.due || null : null, payment_terms: state.terms, client_ref: state.ref, notes: state.notes,
      ref_document_id: from ? from.id : null, price_level: from ? null : +state.level || 1, oce_number: (state.oce || "").trim(),
      buyer_name: curClient().rtn || from ? "" : (state.bname || "").trim(), buyer_rtn: curClient().rtn || from ? "" : (state.brtn || "").trim(),
      items: lines.map((l) => ({ product_id: l.product_id, presentation_id: l.presentation_id, description: `${l.sku} ${l.name} ${l.present}`, qty: l.qty, price: l.price, discount: r2(l.discount || 0), tax_treatment: l.tax })),
    };
  };
  const save = async (thenPay) => {
    const err = $("#doc-error");
    try {
      if (!lines.length) throw new Error("Agrega al menos un producto");
      if (lines.some((l) => !(l.qty > 0))) throw new Error("Hay líneas con cantidad cero");
      const body = payload();
      if (needsDiscountAuth(lines)) {
        const pin = await askAuthPin(totals().disc);
        if (!pin) return;
        body.auth_pin = pin;
      }
      $("#d-save")?.setAttribute("disabled", ""); $("#d-savepay")?.setAttribute("disabled", "");
      try {
        saved = await api("/api/documents", { method: "POST", body });
      } catch (e) {
        if (!e.needsAuth || body.auth_pin) throw e;
        const pin = await askAuthPin(0, e.message); // por ejemplo, venta al crédito a un cliente con mora o sin crédito disponible
        if (!pin) throw e;
        saved = await api("/api/documents", { method: "POST", body: { ...body, auth_pin: pin } });
      }
      toast(`${saved.kind_label} ${saved.number} guardada`);
      paint();
      await safePrint(printDoc, saved.id); // la factura siempre sale en carta, también al guardar y cobrar
      if (thenPay) payDoc(saved.id);
    } catch (e) { err.textContent = e.message; alertPopup(e.message); $("#d-save")?.removeAttribute("disabled"); $("#d-savepay")?.removeAttribute("disabled"); }
  };

  function bind() {
    $$("[data-tab]").forEach((b) => b.onclick = () => { sync(); tab = b.dataset.tab; paint(); });
    $$("[data-qty]").forEach((el) => {
      el.oninput = () => { lines[el.dataset.qty].qty = num(el.value) > 0 ? num(el.value) : 0; refresh(); };
      el.onchange = () => { if (!(num(el.value) > 0)) { el.value = 1; lines[el.dataset.qty].qty = 1; } refresh(); };
    });
    $$("[data-price]").forEach((el) => {
      el.oninput = () => { lines[el.dataset.price].price = Math.max(num(el.value), 0); refresh(); };
      el.onchange = () => { if (num(el.value) < 0) el.value = 0; refresh(); };
    });
    $$("[data-pricesel]").forEach((el) => el.onchange = () => { lines[el.dataset.pricesel].price = num(el.value); refresh(); });
    $$("[data-disc]").forEach((el) => {
      el.oninput = () => { applyDiscount(lines[el.dataset.disc], el.value); refresh(); };
      el.onchange = () => { applyDiscount(lines[el.dataset.disc], el.value); el.blur(); refresh(); };
    });
    $$("[data-del]").forEach((el) => el.onclick = () => { sync(); lines.splice(+el.dataset.del, 1); paint(); });
    ["f-wh", "f-series"].forEach((id) => { if ($("#" + id)) $("#" + id).onchange = () => { sync(); paint(); }; });
    if ($("#f-client")) $("#f-client").onchange = () => { sync(); state.level = clientLevel(); reprice(); paint(); };
    if ($("#f-level")) $("#f-level").onchange = () => { sync(); reprice(); paint(); };
    ["f-due", "f-ref", "f-notes", "f-oce", "f-bname", "f-brtn"].forEach((id) => { if ($("#" + id)) $("#" + id).oninput = sync; });
    if ($("#f-terms")) $("#f-terms").onchange = () => { sync(); state.due = dueFromTerms(state.terms); paint(); };
    if ($("#f-newclient")) $("#f-newclient").onclick = () => { sync(); clientForm(null, async (id) => { const fresh = await api("/api/clients"); clients.splice(0, clients.length, ...fresh); state.client_id = id; state.level = clientLevel(); reprice(); paint(); }); };
    if ($("#sale-q")) {
      const input = $("#sale-q");
      input.onclick = () => searchHits(true);
      input.oninput = () => searchHits(false);
      input.onblur = () => setTimeout(() => $("#sale-hits")?.classList.remove("open"), 120);
      input.onkeydown = (e) => {
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          if (!$("#sale-hits").classList.contains("open")) searchHits(false);
          hitIndex = Math.max(0, Math.min(hits.length - 1, hitIndex + (e.key === "ArrowDown" ? 1 : -1)));
          $$("[data-hit]").forEach((b, i) => b.classList.toggle("active", i === hitIndex));
          $$("[data-hit]")[hitIndex]?.scrollIntoView({ block: "nearest" });
        }
        if (e.key === "Enter") {
          e.preventDefault();
          const q = input.value.trim().toLowerCase();
          const pick = offers.find((o) => o.sku.toLowerCase() === q) || hits[hitIndex] || hits[0];
          if (pick) addOffer(pick);
        }
        if (e.key === "Escape") $("#sale-hits").classList.remove("open");
      };
      if (refocus) { input.focus(); refocus = false; }
    }
    if ($("#d-save")) $("#d-save").onclick = () => save(false);
    if ($("#d-savepay")) $("#d-savepay").onclick = () => save(true);
    if ($("#d-print")) $("#d-print").onclick = () => safePrint(printDoc, saved.id);
    if ($("#d-ticket")) $("#d-ticket").onclick = () => safePrint(printTicket, saved.id);
    if ($("#d-email")) $("#d-email").onclick = () => emailDoc(saved);
    if ($("#d-pay")) $("#d-pay").onclick = () => payDoc(saved.id);
    if ($("#d-new")) $("#d-new").onclick = () => (from ? goto("ventas") : newDocument(kind));
    $("#d-back").onclick = () => goto(kind === "factura" || kind === "cotizacion" || kind === "nota" ? "ventas" : "inicio");
  }
  paint();
}

/* ───────── inventario ───────── */
let lowOnly = false;

async function renderProducts(root, query = "") {
  const rows = await api("/api/products");
  const costs = can("ver_costos"), canAdjust = can("inventario"), canEdit = can("catalogo");
  const apply = () => {
    const q = ($("#q")?.value || "").trim().toLowerCase();
    const list = rows.filter((p) => (!lowOnly || p.low) && (!q || `${p.sku} ${p.name} ${p.department} ${p.category}`.toLowerCase().includes(q)));
    $("#plist").innerHTML = table(["SKU", "PRODUCTO", "PRESENTACIONES Y PRECIOS", "ISV", costs ? "COSTO" : "PRECIO", "EXISTENCIA", ""], list.map((p) => `<tr>
      <td class="nowrap"><strong>${esc(p.sku)}</strong></td><td class="prod-cell">${esc(p.name)}<div class="muted small">${esc(p.department)} · ${esc(p.category)}</div><div class="muted small">Unidad base: ${esc(p.base_unit)}</div></td>
      <td class="pres-cell">${p.presentations.map((x) => `<div class="pres-line"><span>${esc(x.name)} <span class="muted small">× ${x.factor} ${esc(p.base_unit)}</span></span> <strong class="nowrap">${money(x.price)}</strong></div>${x.prices.slice(1).some((v, i) => rawPrices(x)[i + 1] > 0) ? `<div class="muted small">${x.prices.slice(1).map((v, i) => rawPrices(x)[i + 1] > 0 ? `${esc(levelName(i + 2))} ${money(v)}` : "").filter(Boolean).join(" · ")}</div>` : ""}`).join("")}</td><td class="nowrap">${TAX_LABEL[p.tax_treatment]}</td>
      <td class="nowrap">${costs ? `${money(p.cost)}<div class="muted small">precio ${money(p.price)}</div>` : money(p.price)}</td>
      <td class="nowrap">${p.low ? `<span class="pill vencida">${p.stock} ${esc(p.base_unit)} · bajo</span>` : `<strong>${p.stock} ${esc(p.base_unit)}</strong>`}${p.stocks.map((s) => `<div class="muted small">${esc(s.warehouse)}: ${s.qty}</div>`).join("")}</td>
      <td class="row-actions"><button class="btn ghost sm" data-kardex="${p.id}">Kardex</button>${canAdjust ? `<button class="btn sm" data-adjust="${p.id}">Ajustar</button>` : ""}${canEdit ? `<button class="btn sm" data-edit="${p.id}">Editar</button><button class="btn danger sm" data-del="${p.id}">Eliminar</button>` : ""}</td></tr>`), "No hay productos con ese filtro");
    $$("[data-kardex]").forEach((b) => b.onclick = () => showKardex(+b.dataset.kardex));
    $$("[data-adjust]").forEach((b) => b.onclick = () => adjustForm(rows.find((p) => p.id === +b.dataset.adjust)));
    $$("[data-edit]").forEach((b) => b.onclick = () => productForm(rows.find((p) => p.id === +b.dataset.edit)));
    $$("[data-del]").forEach((b) => b.onclick = async () => {
      const p = rows.find((x) => x.id === +b.dataset.del);
      if (await askConfirm(`¿Eliminar «${p.name}»? Solo se puede si nunca se vendió ni se compró.`, "Eliminar", true)) run(() => api("/api/products/" + p.id, { method: "DELETE" }), "Producto eliminado");
    });
  };
  root.innerHTML = `<div class="section-head"><h2>Inventario</h2><div class="actions">
      <button class="btn" id="moves">Movimientos</button>${can("inventario") ? `<button class="btn" id="go-count">Conteo físico</button>` : ""}${can("reportes") ? `<button class="btn" id="inv-csv">Exportar valorizado</button>` : ""}${canEdit ? `<button class="btn" id="xls">Excel: importar / exportar</button><button class="btn primary" id="add">Añadir producto</button>` : ""}</div></div>
    <div class="toolbar"><input id="q" placeholder="Buscar por SKU, nombre o categoría" value="${esc(query)}" /><label class="check"><input type="checkbox" id="low" ${lowOnly ? "checked" : ""} /> Solo stock bajo</label></div>
    <div class="card" id="plist"></div>`;
  apply();
  $("#q").oninput = apply;
  $("#low").onchange = (e) => { lowOnly = e.target.checked; apply(); };
  $("#moves").onclick = () => showKardex(null);
  if ($("#go-count")) $("#go-count").onclick = () => { openCountId = null; goto("conteo"); };
  if ($("#add")) $("#add").onclick = () => productForm(null);
  if ($("#xls")) $("#xls").onclick = () => (modOn("importar_excel") ? importProducts() : lockedPopup("importar_excel"));
  if ($("#inv-csv")) $("#inv-csv").onclick = () => exportCsv("/api/reports/inventario.csv", "inventario-valorizado.csv");
}

/** Importar productos desde Excel o CSV: primero se revisa el archivo y luego se importa todo junto. */
async function importProducts() {
  const warehouses = await api("/api/warehouses");
  let reviewed = null;
  const ACTION = { nuevo: "Nuevo", actualizado: "Actualiza", "sin cambios": "Sin cambios", omitido: "Omitido", error: "Error" };
  const html = `<div class="full info">1) Descarga la <button type="button" class="link-btn" id="imp-tpl">plantilla de Excel</button> o <button type="button" class="link-btn" id="imp-exp">exporta tu catálogo actual</button> (sirve para cambiar precios en Excel y volver a importarlo).
      2) Llénala: una fila por producto, precios sin ISV. 3) Súbela aquí, revisa el resultado e importa. Si una fila tiene error no se importa nada hasta corregirla.</div>
    <label class="full">Archivo (.xlsx o .csv)<input type="file" id="imp-file" accept=".xlsx,.csv" /></label>
    <label>Bodega para la existencia inicial<select id="imp-wh"><option value="">— Sin existencia inicial —</option>${warehouses.filter((w) => w.active !== false).map((w) => `<option value="${w.id}">${esc(w.name)}</option>`).join("")}</select></label>
    <label class="check"><input type="checkbox" id="imp-upd" /> Actualizar productos que ya existen (nombre, precios, costo, ISV…)</label>
    <div class="full" id="imp-result"></div>`;
  const send = async (apply) => {
    const file = $("#imp-file").files[0];
    if (!file) throw new Error("Elige el archivo de Excel o CSV");
    const body = new FormData(); body.append("file", file);
    const q = new URLSearchParams({ update: $("#imp-upd").checked, apply });
    if ($("#imp-wh").value) q.set("warehouse_id", $("#imp-wh").value);
    const res = await fetch("/api/products/import?" + q, { method: "POST", headers: { Authorization: "Bearer " + token }, body });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(errorText(data));
    return data;
  };
  const show = (r) => {
    const c = r.counts;
    $("#imp-result").innerHTML = `<p><strong>${c.nuevos}</strong> nuevos · <strong>${c.actualizados}</strong> se actualizan · ${c.sin_cambios} sin cambios · <strong class="${c.errores ? "down" : ""}">${c.errores} con error</strong></p>
      ${table(["FILA", "CÓDIGO", "NOMBRE", "RESULTADO", "DETALLE"], r.rows.map((x) => `<tr class="${x.action === "error" ? "row-bad" : ""}"><td>${x.row}</td><td>${esc(x.sku)}</td><td>${esc(x.name)}</td><td>${x.action === "error" ? `<span class="pill vencida">Error</span>` : esc(ACTION[x.action] || x.action)}</td><td class="small">${esc(x.notes.join(" · "))}</td></tr>`))}`;
  };
  openForm("Importar productos desde Excel", html, async () => {
    if (!reviewed) {
      reviewed = await send(false);
      show(reviewed);
      const btn = $("#modal-form button[type=submit]");
      if (reviewed.counts.errores) { reviewed = null; btn.textContent = "Revisar de nuevo"; return false; }
      if (!reviewed.counts.nuevos && !reviewed.counts.actualizados) { reviewed = null; btn.textContent = "Revisar de nuevo"; $("#imp-result").insertAdjacentHTML("afterbegin", `<p class="muted">No hay nada que importar.</p>`); return false; }
      btn.textContent = `Importar ${reviewed.counts.nuevos + reviewed.counts.actualizados} productos`;
      return false;
    }
    const done = await send(true);
    if (!done.applied) { reviewed = null; show(done); throw new Error("El archivo cambió o tiene errores: revisa de nuevo"); }
    toast(`Importación lista: ${done.counts.nuevos} nuevos, ${done.counts.actualizados} actualizados`);
  }, { wide: true, submitLabel: "Revisar archivo", mount: () => {
    const reset = () => { reviewed = null; $("#modal-form button[type=submit]").textContent = "Revisar archivo"; $("#imp-result").innerHTML = ""; };
    ["imp-file", "imp-wh", "imp-upd"].forEach((id) => $("#" + id).onchange = reset);
    $("#imp-tpl").onclick = () => exportCsv("/api/products/import/template", "plantilla-productos.xlsx");
    $("#imp-exp").onclick = () => exportCsv("/api/products/export.xlsx", "catalogo.xlsx");
  } });
}

async function showKardex(productId) {
  const rows = await api("/api/stock/moves?limit=200" + (productId ? "&product_id=" + productId : ""));
  openForm(productId ? `Kardex · ${rows[0]?.product || "producto"}` : "Últimos movimientos de inventario",
    `<div class="full">${table(["FECHA", "PRODUCTO", "BODEGA", "MOVIMIENTO", "CONCEPTO"], rows.map((r) => `<tr><td>${when(r.created_at)}</td><td>${esc(r.sku)} ${esc(r.product)}</td><td>${esc(r.warehouse)}</td><td class="${r.qty < 0 ? "down" : "up"}">${r.qty > 0 ? "+" : ""}${r.qty}</td><td>${esc(r.concept)}</td></tr>`), "Todavía no hay movimientos")}</div>`, null, { wide: true });
}

function adjustForm(p) {
  openModal(`Ajustar existencias · ${p.name}`, [
    { type: "info", html: `Existencia actual: ${p.stocks.map((s) => `${esc(s.warehouse)} <strong>${s.qty}</strong>`).join(" · ")} (${esc(p.base_unit)})` },
    { name: "warehouse_id", label: "Bodega", type: "select", options: p.stocks.map((s) => ({ value: s.warehouse_id, label: s.warehouse })), full: true },
    { name: "qty", label: `Cantidad en ${p.base_unit} (positiva entra, negativa sale)`, type: "number", step: "0.01", required: true, full: true },
    { name: "concept", label: "Motivo (conteo físico, merma, entrada inicial…)", required: true, full: true },
  ], async (b) => {
    if (!num(b.qty)) throw new Error("La cantidad no puede ser cero");
    await api("/api/stock/adjust", { method: "POST", body: { product_id: p.id, warehouse_id: +b.warehouse_id, qty: num(b.qty), concept: b.concept } });
    toast("Ajuste registrado en el kardex");
  });
}

async function productForm(p) {
  const cat = await api("/api/departments");
  if (!cat.departments.length) { toast("Primero crea un departamento y una categoría", "err"); return; }
  const presents = p ? p.presentations.map((x) => ({ ...x })) : [{ name: "Unidad", unit: "und", factor: 1, price: 0, price_2: 0, price_3: 0, price_4: 0 }];
  const deptId = p ? p.department_id : cat.departments[0].id;
  const catOptions = (dep, selected) => cat.categories.filter((c) => c.department_id === +dep).map((c) => `<option value="${c.id}" ${c.id === selected ? "selected" : ""}>${esc(c.name)}</option>`).join("");
  const html = `${fieldHtml({ name: "sku", label: "SKU", value: p?.sku, required: true })}${fieldHtml({ name: "name", label: "Nombre", value: p?.name, required: true })}
    <label>Departamento<select name="department_id">${cat.departments.map((d) => `<option value="${d.id}" ${d.id === deptId ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select></label>
    <label>Categoría<select name="category_id">${catOptions(deptId, p?.category_id)}</select></label>
    ${fieldHtml({ name: "base_unit", label: "Unidad base", value: p?.base_unit || "und", required: true })}
    ${fieldHtml({ name: "tax_treatment", label: "ISV", type: "select", options: TAX_OPTIONS, value: p?.tax_treatment || "gravado15" })}
    ${fieldHtml({ name: "kind", label: "Tipo", type: "select", options: KIND_OPTIONS, value: p?.kind || "producto", hint: "Platillo: se vende y su receta descuenta insumos. Insumo: ingrediente que se compra. Elaborado: se prepara con una orden de preparación." })}
    ${fieldHtml({ name: "station", label: "Estación de preparación", type: "select", options: STATION_OPTIONS, value: p?.station || "" })}
    ${fieldHtml({ name: "cost", label: "Costo (por unidad base)", type: "number", step: "0.01", min: 0, value: p?.cost ?? 0 })}
    <div class="full price-grid"><h4>Precios por unidad base</h4><p class="muted">Deja en 0 un precio que no uses: se cobra el precio ${esc(priceNames[0])}.</p>
      <div class="price-row">${priceNames.map((name, i) => `<label>${i + 1} · ${esc(name)}<input name="${i ? "price_" + (i + 1) : "price"}" type="number" step="0.01" min="0" value="${p ? (i ? p["price_" + (i + 1)] : p.price) : 0}" /></label>`).join("")}</div></div>
    ${fieldHtml({ name: "min_stock", label: "Existencia mínima", type: "number", step: "0.01", min: 0, value: p?.min_stock ?? 5 })}
    <div class="full"><h4>Presentaciones</h4><p class="muted">El factor dice cuántas unidades base contiene (ej. caja de 100 → 100). Al facturar se descuenta cantidad × factor.</p><div id="pres"></div><button type="button" class="btn sm" id="pres-add">+ Presentación</button></div>`;
  openForm(p ? `Editar ${p.name}` : "Nuevo producto", html, async (form) => {
    const f = Object.fromEntries(new FormData(form).entries());
    const presentations = presents.map((x) => ({ id: x.id ?? null, name: x.name, unit: x.unit, factor: num(x.factor), price: num(x.price), price_2: num(x.price_2), price_3: num(x.price_3), price_4: num(x.price_4), barcode: x.barcode || "" }));
    if (presentations.some((x) => !x.name || !x.unit || x.factor <= 0)) throw new Error("Cada presentación necesita nombre, unidad y un factor mayor a cero");
    const body = { sku: f.sku, name: f.name, department_id: +f.department_id, category_id: +f.category_id, base_unit: f.base_unit, cost: num(f.cost), price: num(f.price), price_2: num(f.price_2), price_3: num(f.price_3), price_4: num(f.price_4), min_stock: num(f.min_stock), tax_treatment: f.tax_treatment, kind: f.kind || "producto", station: f.station || "", presentations };
    await api(p ? "/api/products/" + p.id : "/api/products", { method: p ? "PUT" : "POST", body });
    toast(p ? "Producto actualizado" : "Producto creado");
  }, {
    wide: true,
    mount: (form) => {
      const paintPres = () => {
        const keys = ["price", "price_2", "price_3", "price_4"];
        $("#pres").innerHTML = `<div class="pres-row price4 pres-head"><small>Nombre</small><small>Unidad</small><small>Factor (unidades base)</small>${priceNames.map((n, i) => `<small>${i + 1} · ${esc(n)}</small>`).join("")}<span></span></div>` + presents.map((x, i) => `<div class="pres-row price4"><input data-pf="name" data-i="${i}" placeholder="Nombre (Caja 100)" value="${esc(x.name)}" /><input data-pf="unit" data-i="${i}" placeholder="Unidad" value="${esc(x.unit)}" /><input data-pf="factor" data-i="${i}" type="number" step="0.0001" min="0.0001" title="Factor" value="${x.factor}" />${keys.map((k, j) => `<input data-pf="${k}" data-i="${i}" type="number" step="0.01" min="0" title="${esc(priceNames[j])}" aria-label="${esc(x.name || "Presentación")} · ${esc(priceNames[j])}" value="${x[k] ?? 0}" />`).join("")}<button type="button" class="btn danger sm" data-pdel="${i}" aria-label="Quitar presentación">✕</button></div>`).join("");
        $$("[data-pf]", form).forEach((el) => el.oninput = () => { presents[+el.dataset.i][el.dataset.pf] = el.value; });
        $$("[data-pdel]", form).forEach((el) => el.onclick = async () => {
          const i = +el.dataset.pdel;
          if (presents.length <= 1) return toast("Debe quedar al menos una presentación", "err");
          if (presents[i].id) {
            try { await api(`/api/products/${p.id}/presentations/${presents[i].id}`, { method: "DELETE" }); } catch (err) { return toast(err.message, "err"); }
          }
          presents.splice(i, 1); paintPres();
        });
      };
      paintPres();
      $("#pres-add").onclick = () => { presents.push({ name: "", unit: form.elements.base_unit.value || "und", factor: 1, price: num(form.elements.price.value), price_2: num(form.elements.price_2.value), price_3: num(form.elements.price_3.value), price_4: num(form.elements.price_4.value) }); paintPres(); };
      form.elements.department_id.onchange = (e) => { form.elements.category_id.innerHTML = catOptions(e.target.value); };
    },
  });
}

/* ───────── bodegas ───────── */
async function renderWarehouses(root) {
  const [rows, products, lic, stores] = await Promise.all([api("/api/warehouses"), api("/api/products"), api("/api/license").catch(() => null), Promise.resolve([])]);
  const allowed = lic ? lic.warehouses_allowed : null;
  const whPill = allowed === null || allowed === undefined ? "" : ` <span class="pill ${rows.length >= allowed ? "pendiente" : "activo"}" title="Para más bodegas activa el módulo Multi-bodega en Configuración › Licencia">${rows.length} de ${allowed}${rows.length >= allowed ? " · límite" : ""}</span>`;
  root.innerHTML = `<div class="section-head"><h2>Bodegas${whPill}</h2><div class="actions">${can("inventario") ? `<button class="btn" id="move">Trasladar entre bodegas</button>` : ""}${can("catalogo") ? `<button class="btn primary" id="add">Nueva bodega</button>` : ""}</div></div>
    <div class="grid-4">${rows.map((w) => `<div class="card kpi"><small>${esc(w.code)}${stores.length > 1 ? " · " + esc(w.store || "") : ""}</small><strong>${esc(w.name)}</strong><div class="muted">${esc(w.address)}<br>${w.lines} productos con existencia</div>
      <div class="actions" style="margin-top:10px"><button class="btn sm" data-stock="${w.id}">Existencias</button>${can("catalogo") ? `<button class="btn sm" data-edit="${w.id}">Editar</button><button class="btn danger sm" data-off="${w.id}">Desactivar</button>` : ""}</div></div>`).join("")}</div>`;
  const whForm = (w) => openModal(w ? "Editar bodega" : "Nueva bodega", [{ name: "code", label: "Código", value: w?.code, required: true }, { name: "name", label: "Nombre", value: w?.name, required: true }, { name: "address", label: "Dirección", value: w?.address, full: true },
    ...(stores.length > 1 ? [{ name: "store_id", label: "Tienda", type: "select", value: w?.store_id || (stores.find((x) => x.main) || {}).id, options: stores.map((x) => ({ value: x.id, label: `${x.code} · ${x.name}` })) }] : [])],
    (b) => api(w ? "/api/warehouses/" + w.id : "/api/warehouses", { method: w ? "PUT" : "POST", body: { ...b, store_id: b.store_id ? +b.store_id : null } }));
  if ($("#add")) $("#add").onclick = () => whForm(null);
  $$("[data-edit]").forEach((b) => b.onclick = () => whForm(rows.find((w) => w.id === +b.dataset.edit)));
  $$("[data-off]").forEach((b) => b.onclick = async () => { if (await askConfirm("¿Desactivar esta bodega? Debe estar sin existencias.", "Desactivar", true)) run(() => api("/api/warehouses/" + b.dataset.off, { method: "DELETE" }), "Bodega desactivada"); });
  $$("[data-stock]").forEach((b) => b.onclick = async () => {
    const w = rows.find((x) => x.id === +b.dataset.stock);
    const stock = (await api(`/api/warehouses/${w.id}/stock`)).filter((s) => s.qty > 0).sort((a, c) => a.name.localeCompare(c.name));
    openForm(`Existencias · ${w.name}`, `<div class="full">${table(["SKU", "PRODUCTO", "EXISTENCIA"], stock.map((s) => `<tr><td>${esc(s.sku)}</td><td>${esc(s.name)}</td><td>${s.qty} ${esc(s.unit)}</td></tr>`), "Bodega sin existencias")}</div>`, null, { wide: true });
  });
  if ($("#move")) $("#move").onclick = () => !modOn("multi_warehouse") ? lockedPopup("multi_warehouse") : openModal("Traslado entre bodegas", [
    { name: "product_id", label: "Producto", type: "select", options: products.map((p) => ({ value: p.id, label: `${p.sku} · ${p.name} (${p.stock} ${p.base_unit})` })), full: true },
    { name: "from_warehouse_id", label: "Desde", type: "select", options: rows.map((w) => ({ value: w.id, label: w.name })) },
    { name: "to_warehouse_id", label: "Hacia", type: "select", options: rows.map((w, i) => ({ value: w.id, label: w.name })), value: rows[1]?.id },
    { name: "qty", label: "Cantidad (unidad base)", type: "number", step: "0.01", min: "0.01", required: true, full: true },
  ], async (b) => { await api("/api/stock/transfer", { method: "POST", body: { product_id: +b.product_id, from_warehouse_id: +b.from_warehouse_id, to_warehouse_id: +b.to_warehouse_id, qty: num(b.qty) } }); toast("Traslado realizado"); });
}

/* ───────── departamentos y categorías ───────── */
async function renderCatalog(root) {
  const data = await api("/api/departments");
  root.innerHTML = `<div class="section-head"><h2>Departamentos y categorías</h2><div class="actions"><button class="btn" id="addc">Nueva categoría</button><button class="btn primary" id="addd">Nuevo departamento</button></div></div>
    <div class="card">${table(["DEPARTAMENTO", "CATEGORÍAS", ""], data.departments.map((d) => `<tr><td><strong>${esc(d.name)}</strong></td>
      <td>${d.categories.map((c) => `<span class="chip">${esc(c.name)}<button class="chip-btn" data-ecat="${c.id}" aria-label="Editar ${esc(c.name)}">✎</button><button class="chip-btn" data-dcat="${c.id}" aria-label="Eliminar ${esc(c.name)}">✕</button></span>`).join("") || `<span class="muted">Sin categorías</span>`}</td>
      <td class="row-actions"><button class="btn sm" data-edept="${d.id}">Renombrar</button><button class="btn danger sm" data-ddept="${d.id}">Eliminar</button></td></tr>`))}</div>`;
  const deptForm = (d) => openModal(d ? "Renombrar departamento" : "Departamento", [{ name: "name", label: "Nombre", value: d?.name, full: true, required: true }], (b) => api(d ? "/api/departments/" + d.id : "/api/departments", { method: d ? "PUT" : "POST", body: b }));
  const catForm = (c) => openModal(c ? "Editar categoría" : "Categoría", [{ name: "department_id", label: "Departamento", type: "select", value: c?.department_id, options: data.departments.map((d) => ({ value: d.id, label: d.name })) }, { name: "name", label: "Nombre", value: c?.name, required: true }],
    (b) => api(c ? "/api/categories/" + c.id : "/api/categories", { method: c ? "PUT" : "POST", body: { name: b.name, department_id: +b.department_id } }));
  $("#addd").onclick = () => deptForm(null);
  $("#addc").onclick = () => catForm(null);
  $$("[data-edept]").forEach((b) => b.onclick = () => deptForm(data.departments.find((d) => d.id === +b.dataset.edept)));
  $$("[data-ecat]").forEach((b) => b.onclick = () => catForm(data.categories.find((c) => c.id === +b.dataset.ecat)));
  $$("[data-ddept]").forEach((b) => b.onclick = async () => { if (await askConfirm("¿Eliminar este departamento?", "Eliminar", true)) run(() => api("/api/departments/" + b.dataset.ddept, { method: "DELETE" }), "Departamento eliminado"); });
  $$("[data-dcat]").forEach((b) => b.onclick = async () => { if (await askConfirm("¿Eliminar esta categoría?", "Eliminar", true)) run(() => api("/api/categories/" + b.dataset.dcat, { method: "DELETE" }), "Categoría eliminada"); });
}

/* ───────── clientes ───────── */
function clientForm(c, onDone) {
  openModal(c ? "Editar cliente" : "Nuevo cliente", [
    { name: "name", label: "Nombre", value: c?.name, full: true, required: true },
    { name: "rtn", label: "RTN (14 dígitos)", value: c?.rtn, hint: "Opcional: vacío = consumidor final", placeholder: "08019999123456" },
    { name: "phone", label: "Teléfono", value: c?.phone }, { name: "email", label: "Correo", value: c?.email, type: "email" },
    { name: "address", label: "Dirección", value: c?.address, full: true },
    { name: "price_level", label: "Precio que se le aplica", type: "select", value: c?.price_level || 1, options: priceNames.map((n, i) => ({ value: i + 1, label: `${i + 1} · ${n}` })), hint: "Las facturas y cotizaciones de este cliente toman este precio solas" },
    { name: "exonerated", label: "Exoneración del ISV", type: "select", value: c?.exonerated ? "1" : "0", options: [{ value: "0", label: "No exonerado" }, { value: "1", label: "Cliente exonerado (sus ventas gravadas van sin ISV)" }] },
    { name: "exo_registry", label: "No. constancia del Registro de Exonerados", value: c?.exo_registry, hint: "Obligatorio si es exonerado" },
    { name: "sag_registry", label: "No. registro SAG (si aplica)", value: c?.sag_registry },
    ...(can("credito") && !modOn("advanced_credit") ? [{ type: "info", html: `<span class="muted">Límite de crédito y bloqueo por facturas vencidas: módulo «Crédito avanzado» (plan Empresarial).</span>` }] : []),
    ...(can("credito") && modOn("advanced_credit") ? [
      { name: "credit_limit", label: "Límite de crédito (0 = sin límite)", type: "number", step: "0.01", min: 0, value: c?.credit_limit ?? 0, hint: "Lo máximo que puede deber entre todas sus facturas" },
      { name: "block_overdue", label: "Si tiene facturas vencidas", type: "select", value: c && !c.block_overdue ? "0" : "1", options: [{ value: "1", label: "No venderle al crédito sin autorización" }, { value: "0", label: "Venderle al crédito igual" }] },
    ] : []),
  ], async (b) => {
    const credit = can("credito") ? { credit_limit: num(b.credit_limit), block_overdue: b.block_overdue !== "0" } : { credit_limit: null, block_overdue: null };
    const res = await api(c ? "/api/clients/" + c.id : "/api/clients", { method: c ? "PUT" : "POST", body: { ...b, price_level: +b.price_level || 1, exonerated: b.exonerated === "1", ...credit } });
    toast(c ? "Cliente actualizado" : "Cliente creado");
    if (onDone) { await onDone(c ? c.id : res.id); return "stay"; }
  });
}

async function renderClients(root, query = "") {
  const rows = await api("/api/clients");
  const apply = () => {
    const q = ($("#q")?.value || "").trim().toLowerCase();
    const list = rows.filter((c) => !q || `${c.name} ${c.rtn} ${c.email} ${c.phone}`.toLowerCase().includes(q));
    $("#clist").innerHTML = table(["NOMBRE", "RTN", "CORREO", "TELÉFONO", "PRECIO", "CRÉDITO", ""], list.map((c) => `<tr><td>${esc(c.name)}</td><td>${esc(c.rtn || "Consumidor final")}</td><td>${esc(c.email)}</td><td>${esc(c.phone)}</td><td>${c.price_level > 1 ? pill(levelName(c.price_level)) : esc(levelName(1))}${c.exonerated ? ` ${pill("Exonerado")}` : ""}</td>
      <td class="nowrap">${c.balance ? `Debe ${money(c.balance)}` : `<span class="muted">Sin saldo</span>`}${c.overdue ? `<div><span class="pill vencida">Vencido ${money(c.overdue)}</span></div>` : ""}${c.credit_limit ? `<div class="muted small">Límite ${money(c.credit_limit)} · disponible ${money(c.available)}</div>` : ""}</td>
      <td class="row-actions"><button class="btn ghost sm" data-statement="${c.id}">Estado de cuenta</button>${can("clientes") ? `<button class="btn sm" data-edit="${c.id}">Editar</button>` : ""}${can("borrar_clientes") ? `<button class="btn danger sm" data-del="${c.id}">Eliminar</button>` : ""}</td></tr>`), "No hay clientes con ese filtro");
    $$("[data-edit]").forEach((b) => b.onclick = () => clientForm(rows.find((c) => c.id === +b.dataset.edit)));
    $$("[data-del]").forEach((b) => b.onclick = async () => { if (await askConfirm("¿Eliminar este cliente? Solo se puede si no tiene documentos.", "Eliminar", true)) run(() => api("/api/clients/" + b.dataset.del, { method: "DELETE" }), "Cliente eliminado"); });
    $$("[data-statement]").forEach((b) => b.onclick = () => showStatement(+b.dataset.statement));
  };
  root.innerHTML = `<div class="section-head"><h2>Clientes</h2>${can("clientes") ? `<button class="btn primary" id="add">Nuevo cliente</button>` : ""}</div>
    <div class="toolbar"><input id="q" placeholder="Buscar por nombre, RTN, correo o teléfono" value="${esc(query)}" /></div><div class="card" id="clist"></div>`;
  apply();
  $("#q").oninput = apply;
  if ($("#add")) $("#add").onclick = () => clientForm(null);
}

async function showStatement(id) {
  const s = await api(`/api/clients/${id}/statement`);
  openForm(`Estado de cuenta · ${s.client.name}`, `<div class="full"><div class="docmeta"><div><small class="muted">Facturado</small><br><strong>${money(s.billed)}</strong></div><div><small class="muted">Saldo pendiente</small><br><strong class="${s.balance ? "down" : "up"}">${money(s.balance)}</strong></div><div><small class="muted">RTN</small><br>${esc(s.client.rtn || "Consumidor final")}</div></div>
    ${table(["FACTURA", "FECHA", "VENCE", "TOTAL", "SALDO", "ESTADO", ""], s.invoices.map((i) => `<tr><td>${esc(i.number)}</td><td>${when(i.issued_at)}</td><td>${dateOnly(i.due_date)}</td><td>${money(i.total)}</td><td>${money(i.balance)}</td><td>${pill(i.status)}</td><td>${OPEN_STATES.includes(i.status) && can("cobrar") ? `<button type="button" class="btn sm" data-pay="${i.id}">Cobrar</button>` : ""}</td></tr>`), "Este cliente aún no tiene facturas")}</div>`, null, {
    wide: true, mount: (form) => $$("[data-pay]", form).forEach((b) => b.onclick = () => payDoc(b.dataset.pay)),
  });
}

/* ───────── proveedores y compras ───────── */
async function renderSuppliers(root) {
  const [suppliers, purchases] = await Promise.all([api("/api/suppliers"), api("/api/purchases")]);
  root.innerHTML = `<div class="section-head"><h2>Proveedores y compras</h2><div class="actions"><button class="btn" id="buy">Registrar compra</button><button class="btn primary" id="add">Nuevo proveedor</button></div></div>
    <div class="card"><h3>Proveedores</h3>${table(["PROVEEDOR", "RTN", "CATEGORÍA", "TELÉFONO", ""], suppliers.map((s) => `<tr><td>${esc(s.name)}</td><td>${esc(s.rtn)}</td><td>${esc(s.category)}</td><td>${esc(s.phone)}</td><td class="row-actions"><button class="btn sm" data-edit="${s.id}">Editar</button><button class="btn danger sm" data-del="${s.id}">Eliminar</button></td></tr>`), "Sin proveedores")}</div>
    <div class="card" style="margin-top:12px"><h3>Compras</h3>${table(["ORDEN", "FECHA", "PROVEEDOR", "BODEGA", "TOTAL", "RECEPCIÓN", "PAGO", ""], purchases.map((p) => `<tr><td class="nowrap">${esc(p.number)}${p.supplier_invoice ? `<div class="muted small">Fact. ${esc(p.supplier_invoice)}</div>` : ""}</td><td class="nowrap">${when(p.issued_at)}</td><td>${esc(p.supplier)}</td><td>${esc(p.warehouse)}</td><td class="nowrap">${money(p.total)}${p.balance > 0 ? `<div class="muted small">saldo ${money(p.balance)}</div>` : ""}</td><td>${pill(p.status)}</td><td>${p.status === "Anulada" ? "" : pill(p.credit ? p.pay_status : "Contado")}</td>
      <td class="row-actions"><button class="btn ghost sm" data-pview="${p.id}">Ver</button>${p.balance > 0 && can("compras", "bancos") && modOn("compras") ? `<button class="btn sm" data-ppay="${p.id}">Pagar</button>` : ""}${p.status === "Pendiente" && modOn("compras") ? `<button class="btn sm" data-receive="${p.id}">Recibir</button>` : ""}${p.status !== "Anulada" && !(p.credit && p.paid > 0) && !p.returned ? `<button class="btn danger sm" data-pvoid="${p.id}">Anular</button>` : ""}</td></tr>`), "Sin compras registradas")}</div>`;
  const supForm = (s) => openModal(s ? "Editar proveedor" : "Proveedor", [{ name: "name", label: "Nombre", value: s?.name, full: true, required: true }, { name: "rtn", label: "RTN (14 dígitos)", value: s?.rtn }, { name: "category", label: "Categoría", value: s?.category || "Insumos" }, { name: "phone", label: "Teléfono", value: s?.phone }, { name: "email", label: "Correo", value: s?.email }],
    (b) => api(s ? "/api/suppliers/" + s.id : "/api/suppliers", { method: s ? "PUT" : "POST", body: b }));
  $("#add").onclick = () => supForm(null);
  $("#buy").onclick = () => purchaseForm(suppliers);
  $$("[data-edit]").forEach((b) => b.onclick = () => supForm(suppliers.find((s) => s.id === +b.dataset.edit)));
  $$("[data-del]").forEach((b) => b.onclick = async () => { if (await askConfirm("¿Eliminar este proveedor?", "Eliminar", true)) run(() => api("/api/suppliers/" + b.dataset.del, { method: "DELETE" }), "Proveedor eliminado"); });
  $$("[data-receive]").forEach((b) => b.onclick = async () => { if (await askConfirm("¿Recibir esta orden? Las existencias entran a la bodega indicada.", "Recibir")) run(() => api(`/api/purchases/${b.dataset.receive}/receive`, { method: "POST" }), "Compra recibida"); });
  $$("[data-pvoid]").forEach((b) => b.onclick = async () => { if (await askConfirm("¿Anular esta compra? Si ya se recibió, se descuentan las existencias.", "Anular", true)) run(() => api(`/api/purchases/${b.dataset.pvoid}/void`, { method: "POST" }), "Compra anulada"); });
  $$("[data-ppay]").forEach((b) => b.onclick = () => payPurchase(+b.dataset.ppay));
  $$("[data-pview]").forEach((b) => b.onclick = async () => {
    const p = await api("/api/purchases/" + b.dataset.pview);
    openForm(`Compra ${p.number}`, `<div class="full"><p>${esc(p.supplier)} · ${esc(p.warehouse)} · ${pill(p.status)}${p.cai_supplier ? ` · CAI ${esc(p.cai_supplier)}` : ""}</p>
      ${p.items.length ? table(["DESCRIPCIÓN", "CANT.", "UdM", "COSTO", "ISV", "IMPORTE"], p.items.map((i) => `<tr><td>${esc(i.description)}</td><td>${i.qty}</td><td>${esc(i.unit)}</td><td>${money(i.unit_cost)}</td><td>${TAX_LABEL[i.tax_treatment] || ""}</td><td>${money(i.total)}</td></tr>`)) : `<p class="muted">Compra capturada solo con totales (sin detalle de productos).</p>`}
      <p>Gravado ${money(p.gravado)} · Exento ${money(p.exento)} · ISV ${money(p.isv)} · <strong>Total ${money(p.total)}</strong></p>
      <p>${p.credit ? `Crédito ${esc(p.payment_terms)} · vence ${dateOnly(p.due_date)} · pagado ${money(p.paid)} · <strong>saldo ${money(p.balance)}</strong> ${pill(p.pay_status)}` : "Compra de contado"}${p.supplier_invoice ? ` · Factura del proveedor ${esc(p.supplier_invoice)}` : ""}</p>
      ${p.returns.length ? `<h4>Devoluciones al proveedor</h4>${table(["NÚMERO", "FECHA", "NOTA DE CRÉDITO", "PRODUCTOS", "MONTO"], p.returns.map((r) => `<tr><td>${esc(r.number)}</td><td>${when(r.created_at)}</td><td>${esc(r.credit_note || "—")}</td><td>${r.items.map((i) => `${i.qty} × ${esc(i.description)}`).join("<br>")}</td><td>${money(r.total)}</td></tr>`))}` : ""}
      ${p.status === "Recibida" && p.items.length && can("compras") && modOn("compras") && Object.values(p.returnable || {}).some((v) => v > 0) ? `<div class="actions" style="margin-top:10px"><button type="button" class="btn" data-a="return">Devolver al proveedor</button></div>` : ""}
      ${p.items.length ? `<div class="actions" style="margin-top:10px"><button type="button" class="btn" data-a="print-order">Imprimir orden de compra</button></div>` : ""}
      ${p.payments.length ? `<h4>Pagos al proveedor</h4>${table(["FECHA", "FORMA", "NOTA", "REGISTRÓ", "MONTO"], p.payments.map((x) => `<tr><td>${when(x.created_at)}</td><td>${esc(x.method)}</td><td>${esc(x.note)}</td><td>${esc(x.user || "—")}</td><td>${money(x.amount)}</td></tr>`))}` : ""}
      ${p.notes ? `<p class="muted">${esc(p.notes)}</p>` : ""}</div>`, null, { wide: true, mount: (form) => { const b = $("[data-a=return]", form); if (b) b.onclick = () => returnToSupplier(p); const o = $("[data-a=print-order]", form); if (o) o.onclick = () => printPurchaseOrder(p).catch((err) => toast(err.message, "err")); } });
  });
}

async function purchaseForm(suppliers) {
  const [products, whs, banks] = await Promise.all([api("/api/products"), api("/api/warehouses"), can("bancos", "cobrar") ? api("/api/banks/accounts") : []]);
  if (!suppliers.length) { toast("Primero registra un proveedor", "err"); return; }
  const lines = [{ product_id: products[0]?.id, presentation_id: products[0]?.presentations[0]?.id, qty: 1, unit_cost: 0 }];
  const prod = (id) => products.find((p) => p.id === +id);
  const defaultCost = (l) => { const p = prod(l.product_id), pr = p?.presentations.find((x) => x.id === +l.presentation_id); return r2((p?.cost || 0) * (pr?.factor || 1)); };
  lines[0].unit_cost = defaultCost(lines[0]);
  const html = `<label class="full">Proveedor<select name="supplier_id">${suppliers.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}</select></label>
    <label>Bodega de destino<select name="warehouse_id">${whs.map((w) => `<option value="${w.id}">${esc(w.name)}</option>`).join("")}</select></label>
    <label>Estado<select name="status"><option value="Recibida">Recibida (ingresa al inventario)</option>${modOn("compras") ? `<option value="Pendiente">Orden pendiente (aún no llega)</option>` : ""}</select>${modOn("compras") ? "" : `<small class="muted">Órdenes pendientes: módulo Compras</small>`}</label>
    ${fieldHtml({ name: "supplier_invoice", label: "No. de factura del proveedor", placeholder: "000-001-01-00001234" })}
    ${fieldHtml({ name: "cai_supplier", label: "CAI de la factura del proveedor" })}
    <label>Condición de pago<select name="payment_terms">${(modOn("compras") ? ["Contado", "15 días", "30 días", "45 días", "60 días"] : ["Contado"]).map((t) => `<option>${t}</option>`).join("")}</select>${modOn("compras") ? "" : `<small class="muted">Compras a crédito: módulo Compras</small>`}</label>
    <label id="pay-bank-wrap">Pagar ahora desde (contado)<select name="pay_bank_id"><option value="">No registrar en bancos</option>${banks.map((b) => `<option value="${b.id}">${esc(b.name)}</option>`).join("")}</select></label>
    <div class="full"><h4>Productos</h4><div id="plines"></div><button type="button" class="btn sm" id="pl-add">+ Agregar producto</button><div class="odoo-totals" id="ptotals" style="margin:10px 0 0 auto"></div></div>
    ${fieldHtml({ name: "notes", label: "Notas", type: "textarea" })}`;
  openForm("Registrar compra", html, async (form) => {
    const f = Object.fromEntries(new FormData(form).entries());
    await api("/api/purchases", { method: "POST", body: { supplier_id: +f.supplier_id, warehouse_id: +f.warehouse_id, status: f.status, cai_supplier: f.cai_supplier, notes: f.notes,
      supplier_invoice: f.supplier_invoice, payment_terms: f.payment_terms, pay_bank_id: f.payment_terms === "Contado" && f.pay_bank_id ? +f.pay_bank_id : null, items: lines.map((l) => ({ product_id: +l.product_id, presentation_id: +l.presentation_id, qty: num(l.qty), unit_cost: num(l.unit_cost) })) } });
    toast("Compra registrada");
  }, {
    wide: true, submitLabel: "Guardar compra",
    mount: (form) => {
      const totals = () => {
        let gravado = 0, exento = 0, isv = 0;
        lines.forEach((l) => { const p = prod(l.product_id); const v = r2(num(l.qty) * num(l.unit_cost)); if (p.tax_treatment === "gravado15") { gravado += v; isv += v * 0.15; } else if (p.tax_treatment === "gravado18") { gravado += v; isv += v * 0.18; } else exento += v; });
        $("#ptotals").innerHTML = `<div><span>Gravado</span><span>${money(gravado)}</span></div><div><span>Exento</span><span>${money(exento)}</span></div><div><span>ISV</span><span>${money(r2(isv))}</span></div><div><strong>Total</strong><strong>${money(r2(gravado + exento + isv))}</strong></div>`;
      };
      const paint = () => {
        $("#plines").innerHTML = `<div class="pres-row buy-row pres-head"><small>Producto</small><small>Presentación</small><small>Cantidad</small><small>Costo por presentación</small><span></span></div>` + lines.map((l, i) => {
          const p = prod(l.product_id);
          return `<div class="pres-row buy-row"><select data-lf="product_id" data-i="${i}">${products.map((x) => `<option value="${x.id}" ${x.id === +l.product_id ? "selected" : ""}>${esc(x.sku)} · ${esc(x.name)}</option>`).join("")}</select>
            <select data-lf="presentation_id" data-i="${i}">${p.presentations.map((x) => `<option value="${x.id}" ${x.id === +l.presentation_id ? "selected" : ""}>${esc(x.name)} (×${x.factor})</option>`).join("")}</select>
            <input data-lf="qty" data-i="${i}" type="number" step="0.01" min="0.01" title="Cantidad" value="${l.qty}" /><input data-lf="unit_cost" data-i="${i}" type="number" step="0.01" min="0" title="Costo por presentación" value="${l.unit_cost}" />
            <button type="button" class="btn danger sm" data-ldel="${i}" aria-label="Quitar línea">✕</button></div>`;
        }).join("");
        $$("[data-lf]", form).forEach((el) => {
          const i = +el.dataset.i, f = el.dataset.lf;
          el.oninput = () => { lines[i][f] = el.value; if (f === "qty" || f === "unit_cost") totals(); };
          if (f === "product_id") el.onchange = () => { lines[i].product_id = +el.value; lines[i].presentation_id = prod(el.value).presentations[0].id; lines[i].unit_cost = defaultCost(lines[i]); paint(); };
          if (f === "presentation_id") el.onchange = () => { lines[i].presentation_id = +el.value; lines[i].unit_cost = defaultCost(lines[i]); paint(); };
        });
        $$("[data-ldel]", form).forEach((el) => el.onclick = () => { if (lines.length > 1) { lines.splice(+el.dataset.ldel, 1); paint(); } });
        totals();
      };
      paint();
      form.elements.payment_terms.onchange = (e) => { $("#pay-bank-wrap").classList.toggle("hidden", e.target.value !== "Contado"); };
      $("#pl-add").onclick = () => { const p = products[0]; const l = { product_id: p.id, presentation_id: p.presentations[0].id, qty: 1, unit_cost: 0 }; l.unit_cost = defaultCost(l); lines.push(l); paint(); };
    },
  });
}

/* ───────── devolución a proveedor ───────── */
async function returnToSupplier(p) {
  const banks = !p.credit && can("bancos", "cobrar") ? await api("/api/banks/accounts") : [];
  const rows = p.items.filter((i) => (p.returnable[String(i.id)] || 0) > 0);
  openForm(`Devolver mercadería de ${p.number}`, `<div class="full info">Las cantidades salen del inventario de ${esc(p.warehouse)}. ${p.credit ? "En una compra a crédito la devolución baja lo que se le debe al proveedor." : "Es una compra de contado: puedes registrar el reembolso en una cuenta."}</div>
    <div class="full">${table(["PRODUCTO", "COMPRADO", "SE PUEDE DEVOLVER", "COSTO", "DEVOLVER"], rows.map((i) => `<tr><td>${esc(i.description)}</td><td>${i.qty} ${esc(i.unit)}</td><td>${p.returnable[String(i.id)]}</td><td>${money(i.unit_cost)}</td>
      <td><input type="number" min="0" step="0.01" max="${p.returnable[String(i.id)]}" data-ret="${i.id}" value="0" style="width:100px" /></td></tr>`))}</div>
    ${fieldHtml({ name: "credit_note", label: "No. de nota de crédito del proveedor" })}
    ${banks.length ? fieldHtml({ name: "refund_bank_id", label: "Reembolso entra a", type: "select", options: [{ value: "", label: "Sin reembolso a banco" }, ...banks.map((b) => ({ value: b.id, label: b.name }))] }) : ""}
    ${fieldHtml({ name: "notes", label: "Motivo", full: true, placeholder: "Producto dañado, vencido, equivocado…" })}`, async (form) => {
    const items = $$("[data-ret]", form).map((el) => ({ purchase_item_id: +el.dataset.ret, qty: num(el.value) })).filter((x) => x.qty > 0);
    if (!items.length) throw new Error("Escribe la cantidad a devolver de al menos un producto");
    const f = Object.fromEntries(new FormData(form).entries());
    const r = await api(`/api/purchases/${p.id}/returns`, { method: "POST", body: { items, credit_note: f.credit_note || "", notes: f.notes || "", refund_bank_id: f.refund_bank_id ? +f.refund_bank_id : null } });
    toast(`Devolución registrada por ${money(r.returns[r.returns.length - 1].total)}`);
  }, { wide: true, submitLabel: "Registrar devolución" });
}

/* ───────── conteo físico ───────── */
let openCountId = null;

async function renderCounts(root) {
  if (openCountId) return renderCount(root, openCountId);
  const [counts, whs, cat] = await Promise.all([api("/api/counts"), api("/api/warehouses"), api("/api/departments")]);
  const costs = can("ver_costos");
  root.innerHTML = `<div class="section-head"><h2>Conteo físico de inventario</h2><button class="btn primary" id="new-count">Nuevo conteo</button></div>
    <p class="muted">Cuenta lo que hay en una bodega, escribe las cantidades y al aplicar el sistema ajusta las existencias a lo contado (queda en el kardex). Lo ideal es contar sin mover esa bodega; si se vende mientras cuentas, la diferencia se calcula con la existencia del momento de aplicar.</p>
    <div class="card">${table(["CONTEO", "BODEGA", "ABIERTO", "PRODUCTOS", "CONTADOS", ...(costs ? ["FALTANTE", "SOBRANTE"] : []), "ESTADO", ""], counts.map((c) => `<tr><td>${esc(c.number)}</td><td>${esc(c.warehouse)}</td><td class="nowrap">${when(c.created_at)}<div class="muted small">${esc(c.user)}</div></td><td>${c.products}</td><td>${c.counted}</td>
      ${costs ? `<td class="nowrap down">${c.shortage ? money(c.shortage) : "—"}</td><td class="nowrap">${c.surplus ? money(c.surplus) : "—"}</td>` : ""}<td>${pill(c.status)}</td>
      <td class="row-actions"><button class="btn sm" data-count="${c.id}">${c.status === "Abierto" ? "Continuar" : "Ver"}</button></td></tr>`), "Todavía no hay conteos")}</div>`;
  $("#new-count").onclick = () => openModal("Nuevo conteo físico", [
    { name: "warehouse_id", label: "Bodega", type: "select", options: whs.map((w) => ({ value: w.id, label: w.name })), full: true },
    { name: "department_id", label: "Departamento (opcional)", type: "select", options: [{ value: "", label: "Todos" }, ...cat.departments.map((d) => ({ value: d.id, label: d.name }))] },
    { name: "category_id", label: "Categoría (opcional)", type: "select", options: [{ value: "", label: "Todas" }, ...cat.categories.map((c) => ({ value: c.id, label: c.name }))] },
    { name: "notes", label: "Notas", full: true },
  ], async (b) => {
    const c = await api("/api/counts", { method: "POST", body: { warehouse_id: +b.warehouse_id, department_id: b.department_id ? +b.department_id : null, category_id: b.category_id ? +b.category_id : null, notes: b.notes } });
    openCountId = c.id;
  }, { submitLabel: "Abrir conteo" });
  $$("[data-count]").forEach((b) => b.onclick = () => { openCountId = +b.dataset.count; render(); });
}

async function renderCount(root, id) {
  const c = await api("/api/counts/" + id);
  const costs = can("ver_costos"), open = c.status === "Abierto";
  const diffOf = (l, v) => (v === "" || v === null || v === undefined || l.current === null ? null : r2(num(v) - l.current));
  root.innerHTML = `<div class="section-head"><div><h2>Conteo ${esc(c.number)} · ${esc(c.warehouse)}</h2><span class="muted">${pill(c.status)} Abierto ${when(c.created_at)} por ${esc(c.user)}${c.applied_at ? ` · aplicado ${when(c.applied_at)} por ${esc(c.applied_by)}` : ""}</span></div>
    <div class="actions"><button class="btn" id="cnt-back">Volver</button><button class="btn" id="cnt-print">Imprimir hoja</button><button class="btn" id="cnt-csv">CSV</button>
    ${open ? `<button class="btn" id="cnt-save">Guardar avance</button><button class="btn danger" id="cnt-cancel">Cancelar conteo</button><button class="btn primary" id="cnt-apply">Aplicar ajustes</button>` : ""}</div></div>
    ${open ? `<div class="toolbar"><input id="cnt-q" placeholder="Buscar producto o SKU" /><span class="muted" id="cnt-progress">${c.counted} de ${c.products} contados</span></div>` : ""}
    <div class="card">${table(["SKU", "PRODUCTO", "SISTEMA", open ? "AHORA" : "", "CONTADO", "DIFERENCIA", ...(costs ? ["VALOR"] : [])].filter(Boolean), c.lines.map((l) => {
      const d = open ? diffOf(l, l.counted) : l.diff;
      return `<tr data-row="${l.id}" data-text="${esc(`${l.sku} ${l.name}`.toLowerCase())}"><td class="nowrap">${esc(l.sku)}</td><td>${esc(l.name)}</td><td class="nowrap">${l.expected} ${esc(l.unit)}</td>${open ? `<td class="nowrap">${l.current}</td>` : ""}
        <td>${open ? `<input class="cnt-input" type="number" min="0" step="0.01" data-line="${l.id}" value="${l.counted ?? ""}" />` : (l.counted ?? "—")}</td>
        <td class="nowrap ${d < 0 ? "down" : d > 0 ? "up" : ""}" data-diff="${l.id}">${d === null ? "—" : (d > 0 ? "+" : "") + d}</td>
        ${costs ? `<td class="nowrap" data-val="${l.id}">${d === null || !l.cost ? "—" : money(r2(d * l.cost))}</td>` : ""}</tr>`;
    }))}</div>`;
  const lines = Object.fromEntries(c.lines.map((l) => [l.id, l]));
  const collect = () => $$("[data-line]").map((el) => ({ line_id: +el.dataset.line, counted: el.value === "" ? null : num(el.value) }));
  $("#cnt-back").onclick = () => { openCountId = null; render(); };
  $("#cnt-csv").onclick = () => exportCsv(`/api/counts/${c.id}/csv`, `conteo-${c.number}.csv`);
  $("#cnt-print").onclick = () => printHtml(`<html><head><meta charset="utf-8"><title>Hoja de conteo ${esc(c.number)}</title><style>body{font-family:"Segoe UI",sans-serif;margin:24px;font-size:12px}table{width:100%;border-collapse:collapse}th,td{border:1px solid #ccd;padding:6px}th{background:#eef5f1;text-align:left}td.box{width:110px}</style></head><body>
    <h2>Hoja de conteo ${esc(c.number)} · ${esc(c.warehouse)}</h2><p>${new Date().toLocaleString("es-HN")} · Contó: ____________________ · Revisó: ____________________</p>
    <table><thead><tr><th>SKU</th><th>Producto</th><th>Unidad</th><th>Contado</th><th>Observaciones</th></tr></thead><tbody>${c.lines.map((l) => `<tr><td>${esc(l.sku)}</td><td>${esc(l.name)}</td><td>${esc(l.unit)}</td><td class="box"></td><td></td></tr>`).join("")}</tbody></table></body></html>`).catch((err) => toast(err.message, "err"));
  if (!open) return;
  $$("[data-line]").forEach((el, idx, all) => {
    el.oninput = () => {
      const l = lines[el.dataset.line], d = diffOf(l, el.value);
      const cell = $(`[data-diff="${l.id}"]`); cell.textContent = d === null ? "—" : (d > 0 ? "+" : "") + d; cell.className = `nowrap ${d < 0 ? "down" : d > 0 ? "up" : ""}`;
      if (costs) $(`[data-val="${l.id}"]`).textContent = d === null || !l.cost ? "—" : money(r2(d * l.cost));
      $("#cnt-progress").textContent = `${collect().filter((x) => x.counted !== null).length} de ${c.products} contados`;
    };
    el.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); const next = all.slice(idx + 1).find((x) => !x.closest("tr").classList.contains("hidden")); if (next) next.focus(); } };
  });
  $("#cnt-q").oninput = (e) => { const q = e.target.value.trim().toLowerCase(); $$("[data-row]").forEach((tr) => tr.classList.toggle("hidden", !!q && !tr.dataset.text.includes(q))); };
  const save = () => api(`/api/counts/${c.id}/lines`, { method: "PUT", body: { lines: collect() } });
  $("#cnt-save").onclick = () => run(save, "Avance guardado");
  $("#cnt-cancel").onclick = async () => { if (await askConfirm("¿Cancelar este conteo? No se ajusta nada.", "Sí, cancelar", true)) { await run(() => api(`/api/counts/${c.id}/cancel`, { method: "POST" }), "Conteo cancelado"); } };
  $("#cnt-apply").onclick = async () => {
    const done = collect().filter((x) => x.counted !== null).length;
    if (!done) return toast("Escribe al menos una cantidad contada", "err");
    if (await askConfirm(`¿Aplicar el conteo? Se ajustan ${done} producto(s) a lo contado; los que no contaste no cambian.`, "Aplicar ajustes")) {
      try { await save(); const r = await api(`/api/counts/${c.id}/apply`, { method: "POST" }); toast(`Conteo aplicado${r.shortage !== null ? ` · faltante ${money(r.shortage)} · sobrante ${money(r.surplus)}` : ""}`); render(); }
      catch (err) { toast(err.message, "err"); }
    }
  };
}

/* ───────── cuentas por pagar ───────── */
async function payPurchase(id) {
  const [p, banks] = await Promise.all([api("/api/purchases/" + id), api("/api/banks/accounts")]);
  openModal(`Pagar ${p.number} a ${p.supplier}`, [
    { type: "info", html: `Total ${money(p.total)} · Pagado ${money(p.paid)} · <strong>Saldo ${money(p.balance)}</strong>${p.due_date ? ` · vence ${dateOnly(p.due_date)}` : ""}${p.supplier_invoice ? ` · Factura ${esc(p.supplier_invoice)}` : ""}` },
    { name: "amount", label: "Monto a pagar", type: "number", step: "0.01", min: "0.01", max: p.balance, value: p.balance.toFixed(2), required: true },
    { name: "method", label: "Forma de pago", type: "select", options: ["Transferencia", "Cheque", "Efectivo", "Depósito", "Tarjeta"].map((m) => ({ value: m, label: m })) },
    { name: "bank_id", label: "Sale de la cuenta", type: "select", options: [{ value: "", label: "No registrar en bancos" }, ...banks.map((b) => ({ value: b.id, label: b.name }))] },
    { name: "note", label: "Referencia (No. de cheque, transferencia…)" },
  ], async (b) => {
    await api(`/api/purchases/${p.id}/payments`, { method: "POST", body: { amount: num(b.amount), method: b.method, bank_id: b.bank_id ? +b.bank_id : null, note: b.note } });
    toast(`Pago a ${p.supplier} registrado`);
  }, { submitLabel: "Registrar pago" });
}

async function renderPayables(root) {
  if (!modOn("compras")) { root.innerHTML = `<div class="section-head"><h2>Cuentas por pagar</h2></div><div class="card"><p class="muted">Las cuentas por pagar (compras a crédito, pagos y devoluciones a proveedores) son parte del módulo <strong>Compras</strong> del plan Empresarial. Pide tu clave y actívala en Configuración › Licencia. Mientras tanto puedes registrar compras de contado en Proveedores.</p></div>`; return; }
  const d = await api("/api/payables");
  const today = new Date(); today.setHours(0, 0, 0, 0);
  root.innerHTML = `<div class="section-head"><h2>Cuentas por pagar</h2><button class="btn" id="cxp-csv">Exportar CSV</button></div>
    <div class="grid-4">
      <div class="card kpi"><small>Saldo por pagar</small><strong>${money(d.total)}</strong><span class="muted">${d.rows.length} compra(s) abiertas</span></div>
      <div class="card kpi"><small>Vencido</small><strong class="${d.overdue ? "down" : ""}">${money(d.overdue)}</strong><span class="muted">${d.rows.filter((r) => r.pay_status === "Vencida").length} compra(s)</span></div>
      <div class="card kpi"><small>Vence en 7 días</small><strong>${money(d.due_week)}</strong><span class="muted">programa los pagos</span></div>
      <div class="card kpi"><small>Proveedores con saldo</small><strong>${d.by_supplier.length}</strong><span class="muted">${esc(d.by_supplier[0]?.supplier || "—")}</span></div>
    </div>
    <div class="grid-2">
      <div class="card">${table(["COMPRA", "PROVEEDOR", "VENCE", "ATRASO", "TOTAL", "PAGADO", "SALDO", "ESTADO", ""], d.rows.map((r) => `<tr><td class="nowrap">${esc(r.number)}${r.supplier_invoice ? `<div class="muted small">Fact. ${esc(r.supplier_invoice)}</div>` : ""}</td><td>${esc(r.supplier)}</td><td class="nowrap">${dateOnly(r.due_date)}</td>
        <td>${r.days_late ? `<span class="down">${r.days_late} días</span>` : "—"}</td><td class="nowrap">${money(r.total)}</td><td class="nowrap">${money(r.paid)}</td><td class="nowrap"><strong>${money(r.balance)}</strong></td><td>${pill(r.pay_status)}</td>
        <td class="row-actions"><button class="btn sm" data-ppay="${r.id}">Pagar</button></td></tr>`), "No hay compras pendientes de pago")}</div>
      <div class="card"><h3>Por proveedor</h3>${table(["PROVEEDOR", "SALDO"], d.by_supplier.map((x) => `<tr><td>${esc(x.supplier)}</td><td class="nowrap">${money(x.balance)}</td></tr>`), "Sin saldos")}</div>
    </div>`;
  $("#cxp-csv").onclick = () => exportCsv("/api/reports/cxp.csv", "cuentas-por-pagar.csv");
  $$("[data-ppay]").forEach((b) => b.onclick = () => payPurchase(+b.dataset.ppay));
}

/* ───────── bancos ───────── */
let bankFilter = null;
async function renderBanks(root) {
  const data = await api("/api/banks" + (bankFilter ? "?bank_id=" + bankFilter : ""));
  root.innerHTML = `<div class="section-head"><h2>Bancos y caja</h2><strong>${money(data.total)}</strong></div>
    <div class="grid-4">${data.banks.map((b) => `<div class="card kpi clickable ${bankFilter === b.id ? "sel" : ""}" data-bank="${b.id}"><small>${esc(b.name)}</small><strong>${money(b.balance)}</strong><div class="muted">${esc(b.account)}</div><button class="btn ghost sm" data-ebank="${b.id}">Editar</button></div>`).join("")}</div>
    <div class="actions" style="margin:12px 0"><button class="btn primary" id="move">Registrar movimiento</button><button class="btn" id="addbank">Nueva cuenta</button>${bankFilter ? `<button class="btn" id="unfilter">Ver todas las cuentas</button>` : ""}</div>
    <div class="card">${table(["FECHA", "CUENTA", "TIPO", "CONCEPTO", "MONTO"], data.moves.map((m) => `<tr><td>${when(m.created_at)}</td><td>${esc(m.bank)}</td><td>${pill(m.kind === "ingreso" ? "Ingreso" : "Egreso")}</td><td>${esc(m.concept)}</td><td class="${m.kind === "ingreso" ? "up" : "down"}">${m.kind === "ingreso" ? "+" : "−"}${money(m.amount)}</td></tr>`), "Sin movimientos")}</div>`;
  $$("[data-bank]").forEach((c) => c.onclick = (e) => { if (e.target.closest("[data-ebank]")) return; bankFilter = bankFilter === +c.dataset.bank ? null : +c.dataset.bank; render(); });
  if ($("#unfilter")) $("#unfilter").onclick = () => { bankFilter = null; render(); };
  const bankForm = (b) => openModal(b ? "Editar cuenta" : "Nueva cuenta", [{ name: "name", label: "Banco o caja", value: b?.name, full: true, required: true }, { name: "account", label: "Número de cuenta", value: b?.account }, { name: "currency", label: "Moneda", value: b?.currency || "HNL" }, ...(b ? [] : [{ name: "balance", label: "Saldo inicial", type: "number", step: "0.01", value: 0 }])],
    (f) => api(b ? "/api/banks/" + b.id : "/api/banks", { method: b ? "PUT" : "POST", body: { ...f, balance: num(f.balance) } }));
  $("#addbank").onclick = () => bankForm(null);
  $$("[data-ebank]").forEach((el) => el.onclick = () => bankForm(data.banks.find((b) => b.id === +el.dataset.ebank)));
  $("#move").onclick = () => openModal("Movimiento bancario", [
    { name: "bank_id", label: "Cuenta", type: "select", options: data.banks.map((b) => ({ value: b.id, label: `${b.name} · ${money(b.balance)}` })), value: bankFilter },
    { name: "kind", label: "Tipo", type: "select", options: [{ value: "ingreso", label: "Ingreso" }, { value: "egreso", label: "Egreso" }] },
    { name: "concept", label: "Concepto", full: true, required: true }, { name: "amount", label: "Monto", type: "number", step: "0.01", min: "0.01", required: true },
  ], async (f) => { await api("/api/banks/moves", { method: "POST", body: { bank_id: +f.bank_id, kind: f.kind, concept: f.concept, amount: num(f.amount) } }); toast("Movimiento registrado"); });
}

/* ───────── reportes ───────── */
let seriesFilter = "all";
let reportStore = "";
let profitTab = "by_product";
function profitHtml(pr) {
  const costs = pr.cost !== null;
  const tabs = [["by_product", "Productos"], ["by_category", "Categorías"], ["by_seller", "Vendedores"], ["top_qty", "Más vendidos"]];
  const rows = pr[profitTab] || [];
  const maxSales = Math.max(...rows.map((r) => Math.abs(r.sales)), 1);
  const head = [profitTab === "by_seller" ? "VENDEDOR" : profitTab === "by_category" ? "DEPARTAMENTO / CATEGORÍA" : "PRODUCTO",
    ...(profitTab === "by_product" || profitTab === "top_qty" ? ["CANTIDAD"] : ["DOCUMENTOS"]), "VENTAS SIN ISV", ...(costs ? ["COSTO", "MARGEN", "MARGEN %"] : [])];
  return `<div class="card" style="margin-top:12px" id="profit-card"><div class="section-head"><h3>Rentabilidad</h3><button class="btn" id="profit-csv">Exportar CSV</button></div>
    ${costs ? `<div class="profit-kpis"><div><small class="muted">Ventas sin ISV</small><strong>${money(pr.sales)}</strong></div><div><small class="muted">Costo de lo vendido</small><strong>${money(pr.cost)}</strong></div>
      <div><small class="muted">Margen bruto</small><strong class="${pr.margin < 0 ? "down" : "up"}">${money(pr.margin)}</strong></div><div><small class="muted">Margen %</small><strong>${pr.margin_pct ?? "—"}${pr.margin_pct !== null ? "%" : ""}</strong></div></div>` : ""}
    ${pr.estimated_lines ? `<p class="muted small">${pr.estimated_lines} línea(s) son ventas anteriores a la v2.9: su costo se estima con el costo actual del producto. Desde ahora cada venta guarda su costo.</p>` : ""}
    <div class="tabs">${tabs.map(([k, l]) => `<button type="button" class="${k === profitTab ? "on" : ""}" data-ptab="${k}">${l}</button>`).join("")}</div>
    ${table(head, rows.map((r) => `<tr><td>${esc(r.name)}<div class="share"><i style="width:${Math.max(2, Math.abs(r.sales) / maxSales * 100).toFixed(1)}%"></i></div></td>
      <td class="nowrap">${profitTab === "by_product" || profitTab === "top_qty" ? `${r.qty} ${esc(r.unit || "")}` : r.documents}</td><td class="nowrap">${money(r.sales)}</td>
      ${costs ? `<td class="nowrap">${money(r.cost)}</td><td class="nowrap ${r.margin < 0 ? "down" : ""}">${money(r.margin)}</td><td>${r.margin_pct ?? "—"}${r.margin_pct !== null ? "%" : ""}</td>` : ""}</tr>`), "Sin ventas en el período")}</div>`;
}

async function renderReports(root) {
  const sq = reportStore ? `&store_id=${reportStore}` : "";
  const [data, profit, stores] = await Promise.all([api(`/api/reports?period=${period}&series=${seriesFilter}${sq}`), api(`/api/reports/profit?period=${period}`).catch(() => null), Promise.resolve([])]);
  const v = data.libro_ventas, c = data.libro_compras;
  root.innerHTML = `<div class="section-head"><h2>Reportes SAR</h2><div class="actions"><select id="period" aria-label="Período"><option value="month">Este mes</option><option value="quarter">Trimestre</option><option value="year">Año</option><option value="all">Todo</option></select>${stores.length > 1 ? `<select id="rstore" aria-label="Tienda"><option value="">Todas las tiendas</option>${stores.map((x) => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select>` : ""}<select id="series" aria-label="Serie"><option value="all">Todas las series</option><option value="normal">Normal</option><option value="E">Serie E</option></select></div></div>
    <div class="grid-2"><div class="card"><h3>Ventas netas por cliente</h3>${table(["CLIENTE", "TOTAL"], data.by_client.map((r) => `<tr><td>${esc(r.name)}</td><td class="nowrap num">${money(r.total)}</td></tr>`), "Sin datos en el período")}</div>
    <div class="card"><h3>Libro de ventas <small class="muted">(facturas menos notas de crédito)</small></h3><p>Gravado 15% ${money(v.gravado_15)} · ISV ${money(v.isv_15)}</p><p>Gravado 18% ${money(v.gravado_18)} · ISV ${money(v.isv_18)}</p><p>Exento ${money(v.exento)} · Exonerado ${money(v.exonerado)}</p><p><strong>Total ${money(v.total)}</strong></p>
    <h3>Libro de compras</h3><p>Gravado ${money(c.gravado)} · ISV ${money(c.isv)} · <strong>Total ${money(c.total)}</strong></p>
    <h3>Inventario</h3><p>Valor al costo ${money(data.inventory_value)} · ${data.low_stock.length} producto(s) con stock bajo</p></div></div>
    <div class="card" style="margin-top:12px"><h3>Descargas (CSV para Excel)</h3><div class="actions">
      <button class="btn" data-csv="libro-ventas">Libro de ventas detallado</button><button class="btn" data-csv="libro-compras">Libro de compras detallado</button>
      <button class="btn" data-csv="inventario">Inventario valorizado</button><button class="btn" data-csv="cxc">Cuentas por cobrar</button><button class="btn" data-csv="retenciones">Retenciones de ISV</button></div>
      <p class="muted">El libro de ventas detallado incluye cada factura y nota de crédito; las anuladas aparecen con monto cero para conservar la secuencia fiscal.</p></div>
    <div class="card" style="margin-top:12px" id="ld-card"><h3>Libro de ventas diario <small class="muted">(resumen por día y serie, para el SAR)</small></h3>
      <p class="muted">Por cada día: el número con que empezó y con el que terminó cada serie, cuántos documentos hubo (y cuáles se anularon) y los importes por tasa de impuesto. Las notas de crédito restan. Avisa si falta algún número en la secuencia.</p>
      <form id="ld-form" class="form inline-form"><label>Mes<input type="month" id="ld-month" required /></label>
        <label>Serie<select id="ld-series"><option value="all">Todas las series</option></select></label>
        ${stores.length > 1 ? `<label>Tienda<select id="ld-store"><option value="">Todas</option>${stores.map((x) => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select></label>` : ""}
        <button class="btn primary" type="submit">Ver</button><button class="btn" type="button" id="ld-print">Imprimir</button><button class="btn" type="button" id="ld-csv">CSV</button><button class="btn" type="button" id="ld-xlsx">Excel</button></form>
      <div id="ld-result"></div></div>
    <div class="card" style="margin-top:12px"><h3>Ventas por rango de fechas</h3>
      ${modOn("reports") ? "" : `<p class="warn-note">Los reportes avanzados (ventas por rango y rentabilidad) son del plan Profesional. Los libros del SAR de arriba siguen disponibles.</p>`}
      <p class="muted">Una línea por factura, nota de crédito o nota de débito, con exento, gravado, ISV, descuentos y total (las anuladas salen en cero para conservar la secuencia).</p>
      <form id="vd-form" class="form inline-form" ${modOn("reports") ? "" : 'style="display:none"'}><label>Desde<input type="date" id="vd-start" required /></label><label>Hasta<input type="date" id="vd-end" required /></label>
        <button class="btn primary" type="submit">Ver</button><button class="btn" type="button" id="vd-csv">Descargar CSV</button></form>
      <div id="vd-result"></div></div>
    ${profit ? profitHtml(profit) : `<div class="card" style="margin-top:12px"><h3>Rentabilidad</h3><p class="muted">Módulo adicional sin activar. Actívalo con tu clave en Configuración › Licencia.</p></div>`}
    ${data.low_stock.length ? `<div class="card" style="margin-top:12px"><h3>Productos con stock bajo</h3>${table(["SKU", "PRODUCTO", "EXISTENCIA"], data.low_stock.map((p) => `<tr><td>${esc(p.sku)}</td><td>${esc(p.name)}</td><td>${p.stock}</td></tr>`))}</div>` : ""}`;
  $("#period").value = period; $("#series").value = seriesFilter;
  $("#period").onchange = (e) => { period = e.target.value; render(); };
  $("#series").onchange = (e) => { seriesFilter = e.target.value; render(); };
  if ($("#rstore")) { $("#rstore").value = reportStore; $("#rstore").onchange = (e) => { reportStore = e.target.value; render(); }; }
  const files = { "libro-ventas": [`/api/reports/libro-ventas.csv?period=${period}&series=${seriesFilter}${sq}`, "libro-de-ventas.csv"], "libro-compras": [`/api/reports/libro-compras.csv?period=${period}`, "libro-de-compras.csv"], inventario: ["/api/reports/inventario.csv", "inventario-valorizado.csv"], cxc: ["/api/reports/cxc.csv", "cuentas-por-cobrar.csv"], retenciones: [`/api/reports/retenciones.csv?period=${period}`, "retenciones-isv.csv"] };
  $$("[data-csv]").forEach((b) => b.onclick = () => exportCsv(...files[b.dataset.csv]));
  if (profit) renderReportsBindProfit(profit);
  const nowD = new Date(), pad2 = (n) => String(n).padStart(2, "0");
  $("#ld-month").value = `${nowD.getFullYear()}-${pad2(nowD.getMonth() + 1)}`;
  const ldQuery = () => `month=${$("#ld-month").value}&series=${encodeURIComponent($("#ld-series").value)}${$("#ld-store") && $("#ld-store").value ? `&store_id=${$("#ld-store").value}` : ""}`;
  let ldBook = null;
  const ldPaint = (book) => {
    ldBook = book;
    const sel = $("#ld-series"), keep = sel.value;
    sel.innerHTML = `<option value="all">Todas las series</option>` + book.series_disponibles.map((x) => `<option value="${esc(x)}">Serie ${esc(x)}</option>`).join("");
    sel.value = [...sel.options].some((o) => o.value === keep) ? keep : "all";
    const t = book.totales, row = (label, x, strong) => `<tr class="${strong ? "total-row" : ""}"><td colspan="5"><strong>${label}</strong></td><td class="num">${x.documentos}</td><td class="num">${x.anuladas}</td>
      <td class="num">${money(x.exento)}</td><td class="num">${money(x.exonerado)}</td><td class="num">${money(x.gravado_15)}</td><td class="num">${money(x.isv_15)}</td><td class="num">${money(x.gravado_18)}</td><td class="num">${money(x.isv_18)}</td><td class="num">${money(x.descuento)}</td><td class="num"><strong>${money(x.total)}</strong></td></tr>`;
    const body = book.dias.map((r) => `<tr><td class="nowrap">${esc(r.fecha)}</td><td>${esc(r.tipo)}</td><td>${esc(r.serie)}</td><td class="nowrap mono">${esc(r.desde)}</td><td class="nowrap mono">${esc(r.hasta)}</td>
      <td class="num">${r.documentos}</td><td class="num" ${r.anuladas.length ? `title="${esc(r.anuladas.join(", "))}"` : ""}>${r.anuladas.length || "—"}</td>
      <td class="num">${money(r.exento)}</td><td class="num">${money(r.exonerado)}</td><td class="num">${money(r.gravado_15)}</td><td class="num">${money(r.isv_15)}</td><td class="num">${money(r.gravado_18)}</td><td class="num">${money(r.isv_18)}</td><td class="num">${money(r.descuento)}</td>
      <td class="num"><strong>${money(r.total)}</strong>${r.saltos_total ? ` <span class="pill vencida" title="Faltan los números: ${esc(r.saltos.join(", "))}${r.saltos_total > r.saltos.length ? "…" : ""}">Faltan ${r.saltos_total}</span>` : ""}</td></tr>`);
    $("#ld-result").innerHTML = `<p><strong>${book.dias_con_ventas} día(s) con ventas</strong> · del ${esc(book.desde)} al ${esc(book.hasta)} · Serie: ${esc(book.serie)}${book.con_saltos ? ` · <span class="down">${book.con_saltos} renglón(es) con números faltantes</span>` : ""}</p>
      ${book.cai.map((c) => `<div class="muted small">CAI ${esc(c.cai)} · ${esc(c.documento)} · rango ${esc(c.rango)} · fecha límite ${c.limite ? dateOnly(c.limite) : "—"}</div>`).join("")}
      ${table(["FECHA", "DOCUMENTO", "SERIE", "NÚMERO INICIAL", "NÚMERO FINAL", "DOCS", "ANUL.", "EXENTO", "EXONERADO", "GRAV. 15%", "ISV 15%", "GRAV. 18%", "ISV 18%", "DESCUENTOS", "TOTAL"],
        [...body, row("TOTAL FACTURAS", t.facturas), row("TOTAL NOTAS DE DÉBITO", t.debitos), row("TOTAL NOTAS DE CRÉDITO", t.creditos), row("VENTAS NETAS", t.netas, true)], "No hay ventas en ese mes")}`;
  };
  const ldLoad = async () => { try { ldPaint(await api("/api/reports/libro-ventas-diario?" + ldQuery())); } catch (err) { toast(err.message, "err"); alertPopup(err.message); } };
  $("#ld-form").onsubmit = (e) => { e.preventDefault(); ldLoad(); };
  $("#ld-print").onclick = async () => { if (!ldBook) await ldLoad(); if (ldBook) printDailyBook(ldBook).catch((err) => toast(err.message, "err")); };
  $("#ld-csv").onclick = () => exportCsv("/api/reports/libro-ventas-diario.csv?" + ldQuery(), "libro-de-ventas-diario.csv");
  $("#ld-xlsx").onclick = () => exportCsv("/api/reports/libro-ventas-diario.xlsx?" + ldQuery(), "libro-de-ventas-diario.xlsx");
  ldLoad();
  const today = new Date(), pad = (n) => String(n).padStart(2, "0"), ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  $("#vd-start").value = ymd(new Date(today.getFullYear(), today.getMonth(), 1)); $("#vd-end").value = ymd(today);
  const vdQuery = () => `start=${$("#vd-start").value}&end=${$("#vd-end").value}${reportStore ? `&store_id=${reportStore}` : ""}`;
  $("#vd-form").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const r = await api("/api/reports/ventas-detallado?" + vdQuery()), t = r.totales;
      $("#vd-result").innerHTML = `<p><strong>${t.documentos} documento(s)</strong> · Exento ${money(t.exento)} · Gravado ${money(t.gravado)} · ISV ${money(t.isv)} · Descuentos ${money(t.descuento)} · <strong>Total ${money(t.total)}</strong></p>
        ${table(["FECHA", "TIPO", "NÚMERO", "CLIENTE", "EXENTO", "GRAVADO", "ISV", "TOTAL", "ESTADO"], r.ventas.map((v) => `<tr><td class="nowrap">${esc(v.fecha)}</td><td>${esc(v.tipo)}</td><td class="nowrap">${esc(v.numero)}</td><td>${esc(v.cliente)}</td>
          <td class="num">${money(v.exento)}</td><td class="num">${money(v.gravado)}</td><td class="num">${money(v.isv)}</td><td class="num"><strong>${money(v.total)}</strong></td><td>${pill(v.estado)}</td></tr>`), "No hay ventas en ese rango")}`;
    } catch (err) { toast(err.message, "err"); alertPopup(err.message); }
  };
  $("#vd-csv").onclick = () => { if ($("#vd-start").value && $("#vd-end").value) exportCsv("/api/reports/ventas-detallado.csv?" + vdQuery(), "ventas-por-rango.csv"); };
}

function renderReportsBindProfit(profit) {
  $("#profit-csv").onclick = () => exportCsv(`/api/reports/rentabilidad.csv?period=${period}`, "rentabilidad-por-producto.csv");
  $$("[data-ptab]").forEach((b) => b.onclick = () => { profitTab = b.dataset.ptab; $("#profit-card").outerHTML = profitHtml(profit); renderReportsBindProfit(profit); });
}

/* ───────── punto de venta ───────── */
const pos = { lines: [], client_id: null, warehouse_id: null, mode: "Efectivo", received: "", card: "", data: null };
try { pos.warehouse_id = +localStorage.getItem("comandia_pos_wh") || null; } catch (e) { /* sin almacenamiento */ }
pos.print = "carta"; // la factura del punto de venta sale en carta, como la cotización; el ticket es opcional
try { pos.print = localStorage.getItem("comandia_pos_print") || "carta"; } catch (e) { /* sin almacenamiento */ }

function docTotals(lines, client = null) {
  const b = { exento: 0, exonerado: 0, gravado15: 0, gravado18: 0 };
  lines.forEach(redoDiscount);
  lines.forEach((l) => { b[effTax(l.tax, client)] += lineNet(l); });
  const isv15 = r2(b.gravado15 * 0.15), isv18 = r2(b.gravado18 * 0.18);
  const sub = r2(b.exento + b.exonerado + b.gravado15 + b.gravado18);
  const disc = r2(lines.reduce((x, l) => x + (l.discount || 0), 0));
  return { ...b, isv15, isv18, sub, disc, tax: r2(isv15 + isv18), total: r2(sub + isv15 + isv18) };
}

async function renderPos(root) {
  const { products, clients, warehouses, series, shiftInfo } = await loadPosData(); // sin conexión, del catálogo guardado en este equipo
  pos.shift = shiftInfo.shift || null;
  const offers = [];
  products.forEach((p) => p.presentations.forEach((pr) => offers.push({
    product_id: p.id, presentation_id: pr.id, sku: p.sku, name: p.name, present: pr.name, unit: pr.unit, factor: pr.factor,
    barcode: (pr.barcode || "").trim(), prices: pr.prices || [pr.price, pr.price, pr.price, pr.price], tax: p.tax_treatment, stocks: p.stocks,
  })));
  pos.data = { offers, clients, warehouses, series, products };
  if (!clients.some((c) => c.id === pos.client_id)) pos.client_id = (clients.find((c) => !c.rtn && /consumidor/i.test(c.name)) || clients[0] || {}).id;
  if (!warehouses.some((w) => w.id === pos.warehouse_id)) pos.warehouse_id = warehouses[0]?.id;
  paintPos(root);
}

function posClient() { return pos.data.clients.find((c) => c.id === pos.client_id) || {}; }
function posLevel() { return posClient().price_level || 1; }
function posAvailable(l) { return (l.stocks.find((s) => s.warehouse_id === pos.warehouse_id) || { qty: 0 }).qty; }
function posReprice() { pos.lines.forEach((l) => { l.price = l.prices[posLevel() - 1] ?? l.prices[0]; }); }

function posAdd(offer, qty = 1) {
  const found = pos.lines.find((l) => l.presentation_id === offer.presentation_id);
  if (found) found.qty = r2(found.qty + qty);
  else pos.lines.push({ ...offer, qty, price: offer.prices[posLevel() - 1] ?? offer.prices[0] });
  pos.received = "";
}

/** Busca por código de barras o SKU exacto; si no, por nombre. Acepta "3*código" para la cantidad. */
function posFind(text) {
  let qty = 1, q = text.trim();
  const m = q.match(/^(\d+(?:[.,]\d+)?)\s*[*xX]\s*(.+)$/);
  if (m) { qty = num(m[1].replace(",", ".")); q = m[2].trim(); }
  const lower = q.toLowerCase();
  const exact = pos.data.offers.find((o) => o.barcode && o.barcode.toLowerCase() === lower)
    || pos.data.offers.filter((o) => o.sku.toLowerCase() === lower).sort((a, b) => a.factor - b.factor)[0];
  const hits = exact ? [exact] : pos.data.offers.filter((o) => `${o.sku} ${o.name} ${o.present} ${o.barcode}`.toLowerCase().includes(lower)).slice(0, 30);
  return { qty: qty > 0 ? qty : 1, exact, hits };
}

function posPayments(t) {
  if (pos.mode === "Mixto") {
    const card = Math.min(num(pos.card), t.total), cash = r2(t.total - card);
    return [...(cash > 0 ? [{ method: "Efectivo", amount: cash }] : []), ...(card > 0 ? [{ method: "Tarjeta", amount: r2(card) }] : [])];
  }
  return [{ method: pos.mode, amount: t.total }];
}

function paintPos(root = $("#view")) {
  const { clients, warehouses } = pos.data;
  const t = docTotals(pos.lines, posClient());
  const cashDue = posPayments(t).filter((p) => p.method === "Efectivo").reduce((s, p) => s + p.amount, 0);
  const received = pos.received === "" ? null : num(pos.received);
  const change = received === null ? null : r2(received - cashDue);
  root.innerHTML = `<div class="pos">
    <div class="card pos-left">
      <div class="section-head"><h2>Punto de venta</h2><span class="muted small">${Conn.state === "offline" ? `<span class="pill vencida">Sin conexión · las ventas se guardan en este equipo</span>` : ""} ${pos.shift ? `<span class="pill pagada">${esc(pos.shift.register)} · turno desde ${hhmm(pos.shift.opened_at)}</span>` : (Conn.state === "offline" ? "" : `<button class="btn sm" id="pos-shift" type="button">Sin turno abierto · Abrir turno</button>`)}</span></div>
      <div class="sale-search pos-search"><input id="pos-q" placeholder="Escanea el código de barras o escribe SKU / nombre  (3*código = 3 unidades)" autocomplete="off" /><div id="pos-hits" class="sale-hits"></div></div>
      <div class="tbl-wrap pos-lines">${table(["PRODUCTO", "CANTIDAD", "PRECIO", "IMPORTE", ""], pos.lines.map((l, i) => {
        const over = l.qty * l.factor > posAvailable(l);
        return `<tr><td><strong>${esc(l.name)}</strong> <span class="muted">${esc(l.present)}</span><div class="muted small">${esc(l.sku)}${over ? ` · <span class="down">solo hay ${posAvailable(l)} en esta bodega</span>` : ""}</div></td>
          <td class="nowrap"><button class="btn sm" data-minus="${i}" aria-label="Menos">−</button><input class="pos-qty" data-pqty="${i}" type="number" min="0.01" step="0.01" value="${l.qty}" /><button class="btn sm" data-plus="${i}" aria-label="Más">+</button></td>
          <td class="nowrap">${money(l.price)}</td><td class="nowrap"><strong>${money(lineNet(l))}</strong>${l.discount ? `<div class="muted small">desc. ${l.dpct != null ? `${l.dpct}% · ` : ""}${money(l.discount)}</div>` : ""}</td><td class="nowrap"><button class="btn ghost sm" data-pdisc="${i}" title="Descuento de la línea${can("descuentos") ? "" : " (con PIN de supervisor)"}">%</button><button class="btn ghost sm" data-pdel="${i}" aria-label="Quitar">✕</button></td></tr>`;
      }), "Escanea un producto para empezar")}</div>
    </div>
    <div class="card pos-right">
      <label class="pos-field">Cliente<span class="inline-field"><select id="pos-client">${clients.map((c) => `<option value="${c.id}" ${c.id === pos.client_id ? "selected" : ""}>${esc(c.name)}${c.rtn ? ` · ${esc(c.rtn)}` : ""}</option>`).join("")}</select>${can("clientes") ? `<button class="btn sm" id="pos-newclient" type="button">+ Nuevo</button>` : ""}</span></label>
      <div class="pos-meta"><label class="pos-field">Bodega<select id="pos-wh">${warehouses.map((w) => `<option value="${w.id}" ${w.id === pos.warehouse_id ? "selected" : ""}>${esc(w.name)}</option>`).join("")}</select></label>
        <div class="pos-field"><span>Precio</span><strong>${esc(levelName(posLevel()))}</strong></div></div>
      ${!posClient().rtn ? `<details class="pos-buyer" ${pos.bname || pos.brtn ? "open" : ""}><summary>¿Pide factura con su nombre y RTN?</summary>
        <label class="pos-field">Nombre en la factura<input id="pos-bname" value="${esc(pos.bname || "")}" maxlength="180" /></label>
        <label class="pos-field">RTN<input id="pos-brtn" value="${esc(pos.brtn || "")}" maxlength="20" placeholder="14 dígitos" /></label></details>` : ""}
      ${posClient().exonerated ? `<label class="pos-field">Orden de Compra Exenta (cliente exonerado)<input id="pos-oce" value="${esc(pos.oce || "")}" maxlength="40" /></label>` : ""}
      <div class="pos-total"><div><span>Subtotal</span><span>${money(r2(t.sub + t.disc))}</span></div>${t.disc ? `<div><span>Descuentos</span><span>− ${money(t.disc)}</span></div>` : ""}<div><span>ISV</span><span>${money(t.tax)}</span></div>
        <div class="pos-big"><span>Total</span><span>${money(t.total)}</span></div></div>
      <div class="pos-modes">${["Efectivo", "Tarjeta", "Transferencia", "Mixto"].map((m) => `<button type="button" class="btn ${pos.mode === m ? "primary" : ""}" data-mode="${m}">${m === "Mixto" ? "Efectivo + tarjeta" : m}</button>`).join("")}</div>
      ${pos.mode === "Mixto" ? `<label class="pos-field">Monto con tarjeta<input id="pos-card" type="number" min="0" step="0.01" value="${esc(pos.card)}" /></label><p class="muted small">En efectivo: ${money(cashDue)}</p>` : ""}
      ${cashDue > 0 ? `<label class="pos-field">Efectivo recibido<input id="pos-received" type="number" min="0" step="0.01" value="${esc(pos.received)}" placeholder="${cashDue.toFixed(2)}" /></label>
        <div class="pos-quick">${[["Exacto", cashDue], ...[100, 200, 500, 1000].filter((v) => v > cashDue).slice(0, 3).map((v) => [money(v), v])].map(([label, v]) => `<button type="button" class="btn sm" data-cash="${v}">${label}</button>`).join("")}</div>
        <div class="pos-change ${change !== null && change < 0 ? "bad" : ""}"><span>${change !== null && change < 0 ? "Falta" : "Cambio"}</span><strong>${change === null ? "—" : money(Math.abs(change))}</strong></div>` : ""}
      <button class="btn primary pos-pay" id="pos-pay" ${!pos.lines.length ? "disabled" : ""}>Cobrar ${money(t.total)} <span class="kbd">F9</span></button>
      <label class="pos-field pos-print">Imprimir al cobrar<select id="pos-print">${[["carta", "Factura tamaño carta"], ["ticket", "Ticket 80 mm"], ["no", "No imprimir"]].map(([v, l]) => `<option value="${v}" ${pos.print === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <button class="btn ghost" id="pos-clear" type="button" ${pos.lines.length ? "" : "disabled"}>Cancelar venta</button>
      <p id="pos-error" class="form-error"></p>
    </div></div>`;
  bindPos();
}

function bindPos() {
  const input = $("#pos-q"), box = $("#pos-hits");
  let hits = [], idx = 0;
  const showHits = () => {
    const q = input.value.trim();
    if (!q) { box.classList.remove("open"); return; }
    hits = posFind(q).hits; idx = 0;
    box.innerHTML = hits.map((o, i) => `<button type="button" data-hit="${i}" class="${i === 0 ? "active" : ""}">${esc(o.sku)} · ${esc(o.name)} · ${esc(o.present)} · ${money(o.prices[posLevel() - 1])} · existencia ${posAvailable(o)}</button>`).join("") || `<button type="button">Sin productos con «${esc(q)}»</button>`;
    box.classList.add("open");
    $$("[data-hit]", box).forEach((b) => b.onmousedown = (e) => { e.preventDefault(); posAdd(hits[+b.dataset.hit], posFind(input.value).qty); paintPos(); $("#pos-q").focus(); });
  };
  input.oninput = showHits;
  input.onblur = () => setTimeout(() => box.classList.remove("open"), 120);
  input.onkeydown = (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault(); idx = Math.max(0, Math.min(hits.length - 1, idx + (e.key === "ArrowDown" ? 1 : -1)));
      $$("[data-hit]", box).forEach((b, i) => b.classList.toggle("active", i === idx));
    }
    if (e.key === "Enter") {
      e.preventDefault();
      const found = posFind(input.value);
      const pick = found.exact || (box.classList.contains("open") ? hits[idx] : null) || (found.hits.length === 1 ? found.hits[0] : null);
      if (pick) { posAdd(pick, found.qty); paintPos(); $("#pos-q").focus(); }
      else if (input.value.trim()) { showHits(); if (!found.hits.length) toast(`No encontré «${input.value.trim()}»`, "err"); }
    }
  };
  $$("[data-plus]").forEach((b) => b.onclick = () => { pos.lines[+b.dataset.plus].qty = r2(pos.lines[+b.dataset.plus].qty + 1); paintPos(); });
  $$("[data-minus]").forEach((b) => b.onclick = () => { const l = pos.lines[+b.dataset.minus]; if (l.qty > 1) l.qty = r2(l.qty - 1); else pos.lines.splice(+b.dataset.minus, 1); paintPos(); });
  // «change» llega también al perder el foco: el redibujo se deja para después para no chocar con ese evento.
  $$("[data-pqty]").forEach((el) => el.onchange = () => { const v = num(el.value); if (v > 0) pos.lines[+el.dataset.pqty].qty = v; setTimeout(() => paintPos()); });
  $$("[data-pdel]").forEach((b) => b.onclick = () => { pos.lines.splice(+b.dataset.pdel, 1); paintPos(); });
  $("#pos-print").onchange = (e) => { pos.print = e.target.value; try { localStorage.setItem("comandia_pos_print", pos.print); } catch (err) { /* nada */ } };
  if ($("#pos-shift")) $("#pos-shift").onclick = () => { cashTab = "turno"; goto("caja"); };
  $$("[data-pdisc]").forEach((b) => b.onclick = () => {
    const l = pos.lines[+b.dataset.pdisc];
    openModal(`Descuento · ${l.name}`, [
      { name: "info", type: "info", full: true, html: `Importe de la línea: ${money(lineGross(l))}. Escribe lempiras (25) o porcentaje (10%).${can("descuentos") ? "" : " Al cobrar, un supervisor lo aprueba con su PIN."}` },
      { name: "disc", label: "Descuento", full: true, value: l.dpct != null ? `${l.dpct}%` : l.discount ? l.discount.toFixed(2) : "", placeholder: "0.00 o 10%" },
    ], (v) => { applyDiscount(l, v.disc); paintPos(); return "stay"; });
  });
  $("#pos-client").onchange = (e) => { pos.client_id = +e.target.value; pos.oce = ""; pos.bname = ""; pos.brtn = ""; posReprice(); paintPos(); };
  if ($("#pos-oce")) $("#pos-oce").oninput = (e) => { pos.oce = e.target.value; };
  if ($("#pos-bname")) $("#pos-bname").oninput = (e) => { pos.bname = e.target.value; };
  if ($("#pos-brtn")) $("#pos-brtn").oninput = (e) => { pos.brtn = e.target.value; };
  $("#pos-wh").onchange = (e) => { pos.warehouse_id = +e.target.value; try { localStorage.setItem("comandia_pos_wh", pos.warehouse_id); } catch (err) { /* nada */ } paintPos(); };
  if ($("#pos-newclient")) $("#pos-newclient").onclick = () => clientForm(null, async (id) => { pos.data.clients = await api("/api/clients"); pos.client_id = id; posReprice(); paintPos(); });
  $$("[data-mode]").forEach((b) => b.onclick = () => { pos.mode = b.dataset.mode; pos.received = ""; paintPos(); });
  if ($("#pos-card")) $("#pos-card").onchange = (e) => { pos.card = e.target.value; setTimeout(() => paintPos()); };
  if ($("#pos-received")) {
    $("#pos-received").oninput = (e) => { pos.received = e.target.value; const t = docTotals(pos.lines, posClient()); const due = posPayments(t).filter((p) => p.method === "Efectivo").reduce((s, p) => s + p.amount, 0); const ch = r2(num(pos.received) - due); const box2 = $(".pos-change"); box2.classList.toggle("bad", pos.received !== "" && ch < 0); box2.querySelector("span").textContent = ch < 0 ? "Falta" : "Cambio"; box2.querySelector("strong").textContent = pos.received === "" ? "—" : money(Math.abs(ch)); };
    $("#pos-received").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); posCheckout(); } };
  }
  $$("[data-cash]").forEach((b) => b.onclick = () => { pos.received = String(r2(num(b.dataset.cash))); paintPos(); $("#pos-pay").focus(); });
  $("#pos-pay").onclick = posCheckout;
  $("#pos-clear").onclick = async () => { if (await askConfirm("¿Cancelar esta venta? Se quitan todos los productos.", "Sí, cancelar", true)) { pos.lines = []; pos.received = ""; pos.card = ""; paintPos(); } };
  input.focus();
}

async function posCheckout() {
  const btn = $("#pos-pay");
  if (!btn || btn.disabled) return;
  const t = docTotals(pos.lines, posClient());
  const payments = posPayments(t);
  let authPin = "";
  if (needsDiscountAuth(pos.lines)) {
    authPin = await askAuthPin(t.disc);
    if (!authPin) return;
  }
  const cashDue = payments.filter((p) => p.method === "Efectivo").reduce((s, p) => s + p.amount, 0);
  const received = pos.received === "" ? (cashDue > 0 ? cashDue : null) : num(pos.received);
  if (received !== null && cashDue > 0 && received + 0.005 < cashDue) { alertPopup(`Falta efectivo: recibido ${money(received)} de ${money(cashDue)}`); $("#pos-error").textContent = `Falta efectivo: recibido ${money(received)} de ${money(cashDue)}`; return; }
  btn.disabled = true; btn.textContent = "Cobrando…";
  const sale = {
    client_id: pos.client_id, warehouse_id: pos.warehouse_id, series_id: pos.data.series[0]?.id || null, price_level: posLevel(),
    items: pos.lines.map((l) => ({ product_id: l.product_id, presentation_id: l.presentation_id, qty: l.qty, price: l.price, discount: r2(l.discount || 0), tax_treatment: l.tax })), auth_pin: authPin,
    payments, received: cashDue > 0 ? received : null, oce_number: (pos.oce || "").trim(),
    buyer_name: posClient().rtn ? "" : (pos.bname || "").trim(), buyer_rtn: posClient().rtn ? "" : (pos.brtn || "").trim(),
    offline_id: Offline.newId(), // id único: si se cae la conexión justo al cobrar y se reintenta, no se factura dos veces
  };
  const change = cashDue > 0 && received !== null ? r2(received - cashDue) : 0;
  const saveOffline = async () => {
    if (!modOn("offline")) { lockedPopup("offline"); return; }
    const item = await offlineCheckout(sale, t, payments, change);
    toast(`Venta guardada SIN CONEXIÓN (${item.id}${change > 0 ? ` · Cambio ${money(change)}` : ""}). Se factura al reconectar.`);
    pos.lines = []; pos.received = ""; pos.card = ""; pos.mode = "Efectivo"; pos.oce = ""; pos.bname = ""; pos.brtn = "";
    if (pos.print !== "no") printOfflineTicket(item).catch((err) => toast(err.message, "err"));
    await renderPos($("#view"));
  };
  try {
    if (Conn.state === "offline") return await saveOffline();
    let d;
    try { d = await api("/api/pos/sale", { method: "POST", body: sale }); }
    catch (err) { if (err.network || err.dbOffline) return await saveOffline(); throw err; }
    toast(`Factura ${d.number} cobrada${d.change > 0 ? ` · Cambio ${money(d.change)}` : ""}`);
    pos.lines = []; pos.received = ""; pos.card = ""; pos.mode = "Efectivo"; pos.oce = ""; pos.bname = ""; pos.brtn = "";
    if (pos.print === "carta") safePrint(printDoc, d.id); else if (pos.print === "ticket") safePrint(printTicket, d.id);
    await renderPos($("#view")); // existencias al día para la siguiente venta
  } catch (err) { $("#pos-error").textContent = err.message; alertPopup(err.message); btn.disabled = false; btn.textContent = `Cobrar ${money(t.total)}`; }
}

/* ───────── cierre de caja ───────── */
const cashFilter = { day: "", user_id: "", store_id: "" };
// Sin día elegido, el servidor usa la fecha de Honduras (no la del navegador, que puede tener otra zona horaria).
const cashQuery = () => "?" + [cashFilter.day ? "day=" + cashFilter.day : "", cashFilter.user_id ? "user_id=" + cashFilter.user_id : "", cashFilter.store_id ? "store_id=" + cashFilter.store_id : ""].filter(Boolean).join("&");

const CASH_ORDER = ["Efectivo", "Tarjeta", "Transferencia", "Cheque", "Depósito"];
const COUNT_HELP = { Efectivo: "billetes y monedas en la gaveta", Tarjeta: "total del cierre del datáfono (POS)", Transferencia: "lo acreditado en el banco", Cheque: "cheques recibidos", "Depósito": "depósitos confirmados" };
const diffLabel = (d) => (d === null ? "—" : Math.abs(d) < 0.005 ? "Cuadra" : d > 0 ? `Sobran ${money(d)}` : `Faltan ${money(-d)}`);
const diffClass = (d) => (d === null ? "muted" : Math.abs(d) < 0.005 ? "up" : "down");

/* ───────── turnos de caja ───────── */
let cashTab = "turno";
const REPORT_CSS = `@page { size: letter; margin: 12mm 14mm; }
  body { font-family: Arial, Helvetica, sans-serif; color: #111; font-size: 12px; margin: 0; }
  .rh { display: flex; align-items: center; gap: 14px; border-bottom: 2px solid #333; padding-bottom: 8px; }
  .rh img { max-width: 140px; max-height: 80px; object-fit: contain; }
  .rh-co { flex: 1; line-height: 1.4; } .rh-co strong { font-size: 17px; text-transform: uppercase; }
  .rh-title { text-align: right; } .rh-title h1 { margin: 0 0 4px; font-size: 20px; }
  h2 { font-size: 13px; margin: 14px 0 4px; text-transform: uppercase; letter-spacing: .03em; }
  table { width: calc(100% - 1px); border-collapse: collapse; } th, td { border: 1px solid #999; padding: 5px 6px; text-align: left; }
  th { background: #e6e6e6; font-size: 11px; } td.r, th.r { text-align: right; } tfoot td { font-weight: 700; background: #f3f3f3; }
  .res { margin-top: 10px; font-size: 16px; font-weight: 800; padding: 8px 10px; border: 2px solid #111; display: inline-block; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .sig { display: grid; grid-template-columns: 1fr 1fr; gap: 50px; margin-top: 55px; } .sig div { border-top: 1px solid #111; padding-top: 4px; text-align: center; }
  tr { page-break-inside: avoid; }`;
const hhmm = (iso) => (iso ? new Date(iso).toLocaleTimeString("es-HN", { hour: "2-digit", minute: "2-digit" }) : "");
const resultText = (d) => (d === null || d === undefined ? "Sin contar" : Math.abs(d) < 0.005 ? "CAJA CUADRADA" : d > 0 ? `SOBRANTE: ${money(d)}` : `FALTANTE: ${money(-d)}`);

async function renderCashClose(root) {
  const tabs = [["turno", "Mi turno"], ["dia", "Corte del día"], ...(can("reportes") ? [["historial", "Turnos del día"]] : [])];
  if (!tabs.some(([k]) => k === cashTab)) cashTab = "turno";
  if (!can("cobrar") && cashTab === "turno") cashTab = "dia";
  root.innerHTML = `<div class="tabs page-tabs">${tabs.filter(([k]) => k !== "turno" || can("cobrar")).map(([k, l]) => `<button class="${cashTab === k ? "on" : ""}" data-ctab="${k}">${l}</button>`).join("")}</div><div id="cash-body"></div>`;
  $$("[data-ctab]").forEach((b) => b.onclick = () => { cashTab = b.dataset.ctab; render(); });
  const body = $("#cash-body");
  if (cashTab === "turno") return renderShift(body);
  if (cashTab === "historial") return renderShiftHistory(body);
  return renderDayClose(body);
}

async function renderShift(root) {
  const { shift: sh, last_register } = await api("/api/shifts/current");
  if (!sh) {
    let reg = last_register;
    try { reg = localStorage.getItem("comandia_caja") || reg; } catch (err) { /* nada */ }
    const stores = user.store_id ? [] : await Promise.resolve([]);
    root.innerHTML = `<div class="section-head"><h2>Mi turno de caja</h2></div>
      <div class="card shift-open"><h3>Abrir turno</h3>
        <p class="muted">Al empezar a cobrar, abre tu turno con el fondo (el sencillo que te entregan). Durante el turno registra los retiros a la caja fuerte, los gastos que pagues de la gaveta y los ingresos de efectivo. Al terminar, cuenta y cierra: el sistema te dice si sobra o falta.</p>
        <div class="cash-count">${stores.length > 1 ? `<label>Tienda<select id="sh-store">${stores.map((x) => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select></label>` : ""}<label>Caja<input id="sh-caja" maxlength="40" value="${esc(reg)}" /></label><label>Fondo inicial<input id="sh-open" type="number" step="0.01" min="0" placeholder="0.00" /></label>
        <button class="btn primary" id="sh-go">Abrir turno</button></div></div>`;
    $("#sh-go").onclick = () => run(async () => {
      const caja = $("#sh-caja").value.trim() || "Caja 1";
      await api("/api/shifts/open", { method: "POST", body: { caja, opening: num($("#sh-open").value), store_id: $("#sh-store") ? +$("#sh-store").value : null } });
      try { localStorage.setItem("comandia_caja", caja); } catch (err) { /* nada */ }
      toast(`Turno abierto en ${caja}`);
    });
    return;
  }
  const exp = sh.expected;
  const order = ["Efectivo", "Tarjeta", "Transferencia"];
  root.innerHTML = `<div class="section-head"><h2>Mi turno · ${esc(sh.register)}</h2><div class="actions">
      <button class="btn" data-move="Ingreso">Ingreso de efectivo</button><button class="btn" data-move="Gasto">Gasto pagado de caja</button><button class="btn" data-move="Retiro">Retiro a caja fuerte</button></div></div>
    <div class="grid-4">
      <div class="card kpi"><small>Abierto</small><strong>${hhmm(sh.opened_at)}</strong><span class="muted">${dateOnly(sh.opened_at.slice(0, 10))} · fondo ${money(sh.opening)}</span></div>
      <div class="card kpi"><small>Cobrado en el turno</small><strong>${money(sh.collected)}</strong><span class="muted">${sh.payments.length} cobro(s)</span></div>
      <div class="card kpi"><small>Efectivo en gaveta (esperado)</small><strong>${money(exp.Efectivo)}</strong><span class="muted">fondo + efectivo − retiros − gastos + ingresos</span></div>
      <div class="card kpi"><small>Tarjeta · Transferencias</small><strong>${money(exp.Tarjeta + exp.Transferencia)}</strong><span class="muted">Tarjeta ${money(exp.Tarjeta)} · Transf. ${money(exp.Transferencia)}</span></div>
    </div>
    <div class="grid-2" style="margin-top:12px">
      <div class="card"><h3>Cerrar turno</h3><p class="muted">Cuenta la gaveta, revisa el cierre del datáfono y lo acreditado en el banco.</p>
        <div class="table-wrap"><table class="cuadre"><thead><tr><th>FORMA</th><th>ESPERADO</th><th>CONTADO</th><th>DIFERENCIA</th></tr></thead><tbody>
        ${order.map((m) => `<tr><td><strong>${m}</strong><br><span class="muted small">${COUNT_HELP[m]}</span></td><td>${money(exp[m])}</td><td><input type="number" step="0.01" min="0" data-scount="${m}" placeholder="0.00" aria-label="${m} contado" /></td><td data-sdiff="${m}" class="muted">—</td></tr>`).join("")}
        </tbody></table></div>
        <div class="cash-result" id="sh-result"></div>
        <div class="cash-count"><label class="grow">Observaciones<input id="sh-note" maxlength="500" /></label></div>
        <div class="actions" style="margin-top:8px"><button class="btn primary" id="sh-close">Cerrar turno e imprimir</button></div></div>
      <div class="card"><h3>Movimientos de efectivo</h3>${table(["HORA", "TIPO", "CONCEPTO", "MONTO"], sh.moves.map((m) => `<tr><td>${hhmm(m.created_at)}</td><td>${esc(m.kind)}</td><td>${esc(m.concept)}</td><td class="${m.kind === "Ingreso" ? "up" : "down"}">${m.kind === "Ingreso" ? "+" : "−"} ${money(m.amount)}</td></tr>`), "Sin retiros, gastos ni ingresos")}</div>
    </div>
    <div class="card" style="margin-top:12px"><h3>Cobros del turno</h3>${table(["HORA", "DOCUMENTO", "CLIENTE", "FORMA", "MONTO"], sh.payments.map((p) => `<tr><td>${hhmm(p.time)}</td><td><button class="btn ghost sm" data-view-doc="${p.document_id}">${esc(p.number)}</button></td><td>${esc(p.client)}</td><td>${esc(p.method)}</td><td>${money(p.amount)}</td></tr>`), "Todavía no hay cobros en este turno")}</div>`;
  const read = () => {
    const lines = order.map((m) => { const v = $(`[data-scount="${m}"]`).value; const counted = v === "" ? null : r2(num(v)); return { method: m, expected: exp[m], counted, difference: counted === null ? null : r2(counted - exp[m]) }; });
    const done = lines.filter((l) => l.counted !== null);
    return { lines, total: done.length ? r2(done.reduce((x, l) => x + l.difference, 0)) : null };
  };
  const paint = () => {
    const r = read();
    r.lines.forEach((l) => { const c = $(`[data-sdiff="${l.method}"]`); c.textContent = diffLabel(l.difference); c.className = diffClass(l.difference); });
    $("#sh-result").innerHTML = r.total === null ? `<span class="muted">Escribe lo contado para ver si el turno cuadra.</span>` : `<strong class="${diffClass(r.total)}">${resultText(r.total)}</strong>`;
  };
  $$("[data-scount]").forEach((i) => i.oninput = paint);
  paint();
  $$("[data-move]").forEach((b) => b.onclick = () => {
    const kind = b.dataset.move;
    const help = { Retiro: "Efectivo que sacas de la gaveta para guardarlo (caja fuerte, depósito al banco).", Gasto: "Pago hecho con efectivo de la gaveta (flete, agua, compra menor). Guarda el comprobante.", Ingreso: "Efectivo que entra a la gaveta sin ser venta (más sencillo, devolución de un adelanto)." }[kind];
    openModal({ Retiro: "Retiro a caja fuerte", Gasto: "Gasto pagado de caja", Ingreso: "Ingreso de efectivo" }[kind], [
      { type: "info", html: esc(help) },
      { name: "amount", label: "Monto", type: "number", step: "0.01", min: "0.01", required: true, full: true },
      { name: "concept", label: "Concepto", required: true, full: true, placeholder: kind === "Gasto" ? "Ej. flete de entrega, recibo 123" : "" },
    ], async (v) => { await api(`/api/shifts/${sh.id}/moves`, { method: "POST", body: { kind, amount: num(v.amount), concept: v.concept } }); toast(`${kind} registrado`); });
  });
  $("#sh-close").onclick = async () => {
    if (Offline.count()) { alertPopup(`Hay ${Offline.count()} venta(s) sin conexión sin sincronizar. Sincronízalas (indicador «BD» de la barra superior) antes de cerrar el turno para que los cobros cuadren.`, "Ventas sin sincronizar"); return; }
    const r = read();
    if (r.lines[0].counted === null) { toast("Cuenta el efectivo de la gaveta antes de cerrar", "err"); $('[data-scount="Efectivo"]').focus(); return; }
    if (!(await askConfirm(`¿Cerrar el turno de ${sh.register}? ${resultText(r.total)}. Después ya no se puede cambiar.`, "Cerrar turno"))) return;
    try {
      const done = await api(`/api/shifts/${sh.id}/close`, { method: "POST", body: { counted: Object.fromEntries(r.lines.filter((l) => l.counted !== null).map((l) => [l.method, l.counted])), note: $("#sh-note").value } });
      toast(`Turno cerrado · ${resultText(done.difference)}`);
      printShift(done).catch((err) => toast(err.message, "err"));
      render();
    } catch (err) { toast(err.message, "err"); }
  };
  bindDocButtons(root);
}

async function renderShiftHistory(root) {
  const [data, stores] = await Promise.all([api("/api/shifts" + cashQuery()), Promise.resolve([])]);
  root.innerHTML = `<div class="section-head"><h2>Turnos de caja</h2><div class="actions"><input type="date" id="sh-day" value="${esc(data.day)}" aria-label="Día" />${stores.length > 1 ? `<select id="sh-store-f" aria-label="Tienda"><option value="">Todas las tiendas</option>${stores.map((x) => `<option value="${x.id}" ${x.id === +cashFilter.store_id ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select>` : ""}</div></div>
    <p class="muted">Turnos abiertos ese día y los que siguen abiertos. La diferencia es lo que sobró (+) o faltó (−) al cerrar.</p>
    <div class="card">${table(["CAJA", ...(stores.length > 1 ? ["TIENDA"] : []), "CAJERO", "ABIERTO", "CERRADO", "FONDO", "COBRADO", "EFECTIVO ESPERADO", "CONTADO", "DIFERENCIA", ""], data.rows.map((r) => `<tr><td><strong>${esc(r.register)}</strong></td>${stores.length > 1 ? `<td>${esc(r.store)}</td>` : ""}<td>${esc(r.user)}</td><td>${when(r.opened_at)}</td><td>${r.closed_at ? when(r.closed_at) : pill("Abierto")}</td>
      <td>${money(r.opening)}</td><td>${money(r.collected)}</td><td>${money(r.cash_expected)}</td><td>${r.cash_counted === null || r.cash_counted === undefined ? "—" : money(r.cash_counted)}</td>
      <td class="${r.status === "Cerrado" ? diffClass(r.difference) : "muted"}">${r.status === "Cerrado" ? diffLabel(r.difference) : "—"}</td><td><button class="btn sm" data-shift="${r.id}">${r.status === "Cerrado" ? "Imprimir" : "Ver"}</button></td></tr>`), "No hay turnos ese día")}</div>`;
  $("#sh-day").onchange = (e) => { cashFilter.day = e.target.value; render(); };
  if ($("#sh-store-f")) $("#sh-store-f").onchange = (e) => { cashFilter.store_id = e.target.value; render(); };
  $$("[data-shift]").forEach((b) => b.onclick = async () => {
    try {
      const sh = await api("/api/shifts/" + b.dataset.shift);
      if (sh.status === "Cerrado") return printShift(sh);
      openForm(`Turno abierto · ${sh.register} · ${sh.user}`, `<div class="full">${table(["FORMA", "ESPERADO AHORA"], Object.entries(sh.expected).map(([m, v]) => `<tr><td>${esc(m)}</td><td>${money(v)}</td></tr>`))}
        <p class="muted">Abierto ${when(sh.opened_at)} · fondo ${money(sh.opening)} · ${sh.payments.length} cobro(s) · ${sh.moves.length} movimiento(s). Lo cierra el cajero desde «Mi turno».</p></div>`, null);
    } catch (err) { toast(err.message, "err"); }
  });
}

/** Reporte del turno cerrado, en carta y con el logo. */
async function printShift(sh) {
  const lines = sh.lines.length ? sh.lines : Object.entries(sh.expected).map(([method, expected]) => ({ method, expected, counted: null, difference: null }));
  const mt = sh.moves_total;
  await printHtml(`<!doctype html><html><head><meta charset="utf-8"><title>Turno ${esc(sh.register)} ${esc((sh.opened_at || "").slice(0, 10))}</title><style>${REPORT_CSS}</style></head><body>
    ${reportHeader(sh.company, "Cierre de turno", `<div>${esc(sh.register)} · <b>${esc(sh.user)}</b></div><div>Abierto: ${fullDate(sh.opened_at)}</div><div>Cerrado: ${sh.closed_at ? fullDate(sh.closed_at) : "abierto"}</div>`)}
    <h2>Cuadre por forma de pago</h2>
    <table><thead><tr><th>Forma de pago</th><th class="r">Esperado</th><th class="r">Contado</th><th class="r">Diferencia</th></tr></thead><tbody>
      ${lines.map((l) => `<tr><td>${esc(l.method)}</td><td class="r">${money(l.expected)}</td><td class="r">${l.counted === null ? "—" : money(l.counted)}</td><td class="r">${diffLabel(l.difference)}</td></tr>`).join("")}</tbody></table>
    <div class="res">${sh.status === "Cerrado" ? resultText(sh.difference) : "Turno abierto"}</div>
    ${sh.note ? `<p>Observaciones: ${esc(sh.note)}</p>` : ""}
    <div class="two"><div><h2>Efectivo</h2><table>
      <tr><td>Fondo inicial</td><td class="r">${money(sh.opening)}</td></tr>
      <tr><td>Cobrado en efectivo</td><td class="r">${money(sh.by_method.find((m) => m.method === "Efectivo")?.total || 0)}</td></tr>
      <tr><td>Ingresos</td><td class="r">+ ${money(mt.Ingreso)}</td></tr><tr><td>Retiros a caja fuerte</td><td class="r">− ${money(mt.Retiro)}</td></tr><tr><td>Gastos pagados de caja</td><td class="r">− ${money(mt.Gasto)}</td></tr>
      <tr><td><b>Debía haber en gaveta</b></td><td class="r"><b>${money(sh.expected.Efectivo)}</b></td></tr></table></div>
    <div><h2>Cobrado en el turno</h2><table>${sh.by_method.map((m) => `<tr><td>${esc(m.method)}</td><td class="r">${money(m.total)}</td></tr>`).join("")}<tr><td><b>Total</b></td><td class="r"><b>${money(sh.collected)}</b></td></tr></table></div></div>
    ${sh.moves.length ? `<h2>Movimientos de efectivo</h2><table><thead><tr><th>Hora</th><th>Tipo</th><th>Concepto</th><th>Registró</th><th class="r">Monto</th></tr></thead><tbody>${sh.moves.map((m) => `<tr><td>${hhmm(m.created_at)}</td><td>${esc(m.kind)}</td><td>${esc(m.concept)}</td><td>${esc(m.user)}</td><td class="r">${money(m.amount)}</td></tr>`).join("")}</tbody></table>` : ""}
    <h2>Detalle de cobros</h2><table><thead><tr><th>Hora</th><th>Documento</th><th>Cliente</th><th>Forma</th><th class="r">Monto</th></tr></thead><tbody>
      ${sh.payments.map((p) => `<tr><td>${hhmm(p.time)}</td><td>${esc(p.number)}</td><td>${esc(p.client)}</td><td>${esc(p.method)}</td><td class="r">${money(p.amount)}</td></tr>`).join("") || `<tr><td colspan="5">Sin cobros</td></tr>`}</tbody></table>
    <div class="sig"><div>Entregó: ${esc(sh.user)}</div><div>Recibió / revisó${sh.closed_by && sh.closed_by !== sh.user ? `: ${esc(sh.closed_by)}` : ""}</div></div>
  </body></html>`);
}

async function renderDayClose(root) {
  const [c, stores] = await Promise.all([api("/api/cash/close" + cashQuery()), Promise.resolve([])]);
  const who = c.sees_all ? (c.users.find((u) => u.id === +cashFilter.user_id)?.name || "Todos los usuarios") : user.name;
  // Las formas sin movimiento (cheque, depósito) solo se muestran si tienen cobros; efectivo, tarjeta y transferencia siempre.
  const methods = c.by_method.filter((m) => m.method !== "Retención ISV" && (m.total || ["Efectivo", "Tarjeta", "Transferencia"].includes(m.method)))
    .sort((a, b) => ((CASH_ORDER.indexOf(a.method) + 99) % 99) - ((CASH_ORDER.indexOf(b.method) + 99) % 99));
  const key = `comandia_cuadre_${c.day}_${cashFilter.user_id || (c.sees_all ? "todos" : user.id)}`;
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(key) || "{}"); } catch (err) { /* sin almacenamiento */ }
  root.innerHTML = `<div class="section-head"><h2>Corte del día</h2><div class="actions">
      <input type="date" id="cash-day" value="${esc(c.day)}" aria-label="Día" />
      ${c.sees_all ? `<select id="cash-user" aria-label="Usuario"><option value="">Todos los usuarios</option>${c.users.map((u) => `<option value="${u.id}" ${u.id === +cashFilter.user_id ? "selected" : ""}>${esc(u.name)}</option>`).join("")}</select>` : ""}
      ${stores.length > 1 ? `<select id="cash-store" aria-label="Tienda"><option value="">Todas las tiendas</option>${stores.map((x) => `<option value="${x.id}" ${x.id === +cashFilter.store_id ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select>` : ""}
      <button class="btn" id="cash-csv">Exportar CSV</button><button class="btn" id="cash-ticket">Ticket 80 mm</button><button class="btn primary" id="cash-print">Imprimir reporte</button></div></div>
    ${c.sees_all ? "" : `<p class="muted">Ves solo los cobros y facturas que registraste tú.</p>`}
    <div class="grid-4">
      <div class="card kpi"><small>Total cobrado</small><strong>${money(c.collected)}</strong><span class="muted">${c.payments.length} cobro(s)</span></div>
      <div class="card kpi"><small>Efectivo</small><strong>${money(c.cash)}</strong><span class="muted">Cobrado en efectivo</span></div>
      <div class="card kpi"><small>Tarjeta · Transferencias</small><strong>${money((methods.find((m) => m.method === "Tarjeta")?.total || 0) + (methods.find((m) => m.method === "Transferencia")?.total || 0))}</strong><span class="muted">Tarjeta ${money(methods.find((m) => m.method === "Tarjeta")?.total || 0)} · Transf. ${money(methods.find((m) => m.method === "Transferencia")?.total || 0)}</span></div>
      <div class="card kpi"><small>Facturado en el día</small><strong>${money(c.sales.invoiced)}</strong><span class="muted">${c.sales.invoices} factura(s) · al crédito ${money(c.sales.credit)} · ${c.sales.notes} nota(s) ${money(c.sales.credited)}</span></div>
    </div>
    <div class="card" style="margin-top:12px"><h3>Cuadre de caja</h3>
      <p class="muted">Escribe lo que realmente hay: el efectivo contado, el total del cierre del datáfono y lo que llegó al banco. El sistema calcula cuánto sobra o falta en cada forma de pago.</p>
      <div class="cash-count"><label>Fondo de caja inicial (sencillo con que se abrió)<input id="cash-opening" type="number" step="0.01" min="0" value="${esc(saved.opening ?? "")}" placeholder="0.00" /></label></div>
      <div class="table-wrap"><table class="cuadre"><thead><tr><th>FORMA DE PAGO</th><th>SEGÚN SISTEMA</th><th>CONTADO / CONFIRMADO</th><th>DIFERENCIA</th></tr></thead><tbody>
        ${methods.map((m) => `<tr><td><strong>${esc(m.method)}</strong><br><span class="muted small">${COUNT_HELP[m.method] || ""}</span></td><td data-exp="${esc(m.method)}">${money(m.total)}</td>
          <td><input type="number" step="0.01" min="0" data-count="${esc(m.method)}" value="${esc(saved.counted?.[m.method] ?? "")}" placeholder="0.00" aria-label="${esc(m.method)} contado" /></td><td data-diff="${esc(m.method)}" class="muted">—</td></tr>`).join("")}
      </tbody><tfoot><tr><td><strong>Total</strong></td><td id="cash-exp-total"></td><td id="cash-count-total"></td><td id="cash-diff-total"></td></tr></tfoot></table></div>
      <div class="cash-result" id="cash-result"></div>
      <div class="cash-count"><label class="grow">Observaciones<input id="cash-note" maxlength="200" value="${esc(saved.note || "")}" placeholder="Ej. faltante por vuelto mal dado" /></label></div>
      <div class="actions" style="margin-top:8px"><button class="btn primary" id="cash-record">Registrar cierre en la bitácora</button></div>
    </div>
    <div class="grid-2" style="margin-top:12px">
      <div class="card"><h3>Por usuario</h3>${table(["USUARIO", "COBRADO"], c.by_user.map((u) => `<tr><td>${esc(u.user)}</td><td>${money(u.total)}</td></tr>`), "Sin cobros")}</div>
      <div class="card"><h3>Ventas del día</h3>${table(["CONCEPTO", "MONTO"], [
        `<tr><td>Facturas (${c.sales.invoices})</td><td>${money(c.sales.invoiced)}</td></tr>`, `<tr><td>Al crédito (por cobrar)</td><td>${money(c.sales.credit)}</td></tr>`,
        `<tr><td>Notas de crédito (${c.sales.notes})</td><td>${money(c.sales.credited)}</td></tr>`, ...(c.withheld ? [`<tr><td>Retenciones de ISV</td><td>${money(c.withheld)}</td></tr>`] : [])])}
        ${c.sales.voided.length ? `<h4>Anulados en el día</h4><p class="muted">${c.sales.voided.map((v) => `${esc(v.number)} (${money(v.total)})`).join(", ")}</p>` : ""}</div>
    </div>
    <div class="card" style="margin-top:12px"><h3>Cobros del día</h3>${table(["HORA", "FACTURA", "CLIENTE", "FORMA", "CUENTA", "COBRÓ", "NOTA", "MONTO"], c.payments.map((p) => `<tr><td>${p.time ? new Date(p.time).toLocaleTimeString("es-HN", { hour: "2-digit", minute: "2-digit" }) : ""}</td><td><button class="btn ghost sm" data-view-doc="${p.document_id}">${esc(p.number)}</button></td><td>${esc(p.client)}</td><td>${esc(p.method)}</td><td>${esc(p.bank || "—")}</td><td>${esc(p.user || "—")}</td><td>${esc(p.note)}</td><td>${money(p.amount)}</td></tr>`), "No hay cobros en este día")}</div>`;
  $("#cash-day").onchange = (e) => { cashFilter.day = e.target.value; render(); };
  if ($("#cash-store")) $("#cash-store").onchange = (e) => { cashFilter.store_id = e.target.value; render(); };
  if ($("#cash-user")) $("#cash-user").onchange = (e) => { cashFilter.user_id = e.target.value; render(); };
  $("#cash-csv").onclick = () => exportCsv("/api/cash/close.csv" + cashQuery(), `cierre-de-caja-${c.day}.csv`);

  /** Cuadre: lo esperado (el efectivo incluye el fondo inicial), lo contado y la diferencia por forma de pago. */
  const reconcile = () => {
    const opening = num($("#cash-opening").value);
    const lines = methods.map((m) => {
      const raw = $(`[data-count="${m.method}"]`).value;
      const expected = r2(m.total + (m.method === "Efectivo" ? opening : 0));
      const counted = raw === "" ? null : r2(num(raw));
      return { method: m.method, system: m.total, expected, counted, diff: counted === null ? null : r2(counted - expected) };
    });
    const done = lines.filter((l) => l.counted !== null);
    const total = done.length ? r2(done.reduce((s, l) => s + l.diff, 0)) : null;
    return { opening, lines, total, note: $("#cash-note").value.trim() };
  };
  const paint = () => {
    const r = reconcile();
    r.lines.forEach((l) => {
      $(`[data-exp="${l.method}"]`).innerHTML = money(l.expected) + (l.method === "Efectivo" && r.opening ? `<br><span class="muted small">${money(l.system)} cobrado + ${money(r.opening)} fondo</span>` : "");
      const cell = $(`[data-diff="${l.method}"]`); cell.textContent = diffLabel(l.diff); cell.className = diffClass(l.diff);
    });
    $("#cash-exp-total").textContent = money(r.lines.reduce((s, l) => s + l.expected, 0));
    $("#cash-count-total").textContent = money(r.lines.reduce((s, l) => s + (l.counted || 0), 0));
    $("#cash-diff-total").textContent = diffLabel(r.total); $("#cash-diff-total").className = diffClass(r.total);
    $("#cash-result").innerHTML = r.total === null ? `<span class="muted">Escribe lo contado para ver si la caja cuadra.</span>`
      : `<strong class="${diffClass(r.total)}">${Math.abs(r.total) < 0.005 ? "La caja cuadra exacto" : r.total > 0 ? `SOBRANTE de ${money(r.total)}` : `FALTANTE de ${money(-r.total)}`}</strong>`;
    try { localStorage.setItem(key, JSON.stringify({ opening: $("#cash-opening").value, counted: Object.fromEntries(r.lines.filter((l) => l.counted !== null).map((l) => [l.method, l.counted])), note: r.note })); } catch (err) { /* nada */ }
    return r;
  };
  root.querySelectorAll("#cash-opening, [data-count], #cash-note").forEach((i) => i.oninput = paint);
  paint();
  $("#cash-record").onclick = () => run(async () => {
    const r = reconcile();
    const res = await api("/api/cash/close/record", { method: "POST", body: { day: c.day, user_id: cashFilter.user_id ? +cashFilter.user_id : null, opening: r.opening, note: r.note,
      counted: Object.fromEntries(r.lines.filter((l) => l.counted !== null).map((l) => [l.method, l.counted])) } });
    toast(`Cierre registrado: ${res.result}`);
  });

  const company = async () => c.company;
  const signatures = `<div class="sig"><div>Entregó${cashFilter.user_id || !c.sees_all ? `: ${esc(who)}` : ""}</div><div>Recibió / revisó</div></div>`;
  $("#cash-print").onclick = () => (async () => {
    const co = await company(), r = paint();
    await printHtml(`<!doctype html><html><head><meta charset="utf-8"><title>Cierre de caja ${esc(c.day)}</title><style>
      @page { size: letter; margin: 12mm 14mm; }
      body { font-family: Arial, Helvetica, sans-serif; color: #111; font-size: 12px; margin: 0; }
      .rh { display: flex; align-items: center; gap: 14px; border-bottom: 2px solid #333; padding-bottom: 8px; }
      .rh img { max-width: 140px; max-height: 80px; object-fit: contain; }
      .rh-co { flex: 1; line-height: 1.4; } .rh-co strong { font-size: 17px; text-transform: uppercase; }
      .rh-title { text-align: right; } .rh-title h1 { margin: 0 0 4px; font-size: 20px; }
      h2 { font-size: 13px; margin: 14px 0 4px; text-transform: uppercase; letter-spacing: .03em; }
      table { width: calc(100% - 1px); border-collapse: collapse; } th, td { border: 1px solid #999; padding: 5px 6px; text-align: left; }
      th { background: #e6e6e6; font-size: 11px; } td.r, th.r { text-align: right; } tfoot td { font-weight: 700; background: #f3f3f3; }
      .res { margin-top: 10px; font-size: 16px; font-weight: 800; padding: 8px 10px; border: 2px solid #111; display: inline-block; }
      .two { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
      .sig { display: grid; grid-template-columns: 1fr 1fr; gap: 50px; margin-top: 55px; } .sig div { border-top: 1px solid #111; padding-top: 4px; text-align: center; }
      tr { page-break-inside: avoid; }
    </style></head><body>
      ${reportHeader(co, "Cierre de caja", `<div>Fecha: <b>${dateOnly(c.day)}</b></div><div>Usuario: <b>${esc(who)}</b></div><div>Impreso: ${new Date().toLocaleString("es-HN")}</div>`)}
      <h2>Cuadre por forma de pago</h2>
      <table><thead><tr><th>Forma de pago</th><th class="r">Según sistema</th><th class="r">Contado / confirmado</th><th class="r">Diferencia</th></tr></thead><tbody>
        ${r.lines.map((l) => `<tr><td>${esc(l.method)}${l.method === "Efectivo" && r.opening ? ` (incluye fondo ${money(r.opening)})` : ""}</td><td class="r">${money(l.expected)}</td><td class="r">${l.counted === null ? "—" : money(l.counted)}</td><td class="r">${diffLabel(l.diff)}</td></tr>`).join("")}
      </tbody><tfoot><tr><td>Total</td><td class="r">${money(r.lines.reduce((s, l) => s + l.expected, 0))}</td><td class="r">${money(r.lines.reduce((s, l) => s + (l.counted || 0), 0))}</td><td class="r">${diffLabel(r.total)}</td></tr></tfoot></table>
      <div class="res">${r.total === null ? "Sin contar" : Math.abs(r.total) < 0.005 ? "CAJA CUADRADA" : r.total > 0 ? `SOBRANTE: ${money(r.total)}` : `FALTANTE: ${money(-r.total)}`}</div>
      ${r.note ? `<p>Observaciones: ${esc(r.note)}</p>` : ""}
      <div class="two"><div><h2>Ventas del día</h2><table>
        <tr><td>Facturas emitidas (${c.sales.invoices})</td><td class="r">${money(c.sales.invoiced)}</td></tr><tr><td>Al crédito (por cobrar)</td><td class="r">${money(c.sales.credit)}</td></tr>
        <tr><td>Notas de crédito (${c.sales.notes})</td><td class="r">${money(c.sales.credited)}</td></tr><tr><td>Documentos anulados</td><td class="r">${c.sales.voided.length}</td></tr>
        ${c.withheld ? `<tr><td>Retenciones de ISV recibidas</td><td class="r">${money(c.withheld)}</td></tr>` : ""}<tr><td><b>Total cobrado</b></td><td class="r"><b>${money(c.collected)}</b></td></tr></table></div>
      <div><h2>Cobrado por usuario</h2><table>${c.by_user.map((u) => `<tr><td>${esc(u.user)}</td><td class="r">${money(u.total)}</td></tr>`).join("") || "<tr><td>Sin cobros</td><td></td></tr>"}</table></div></div>
      <h2>Detalle de cobros</h2>
      <table><thead><tr><th>Hora</th><th>Documento</th><th>Cliente</th><th>Forma</th><th>Cuenta</th><th>Cobró</th><th class="r">Monto</th></tr></thead><tbody>
        ${c.payments.map((p) => `<tr><td>${p.time ? new Date(p.time).toLocaleTimeString("es-HN", { hour: "2-digit", minute: "2-digit" }) : ""}</td><td>${esc(p.number)}</td><td>${esc(p.client)}</td><td>${esc(p.method)}</td><td>${esc(p.bank || "")}</td><td>${esc(p.user || "")}</td><td class="r">${money(p.amount)}</td></tr>`).join("") || `<tr><td colspan="7">No hay cobros en este día</td></tr>`}
      </tbody></table>
      ${c.sales.voided.length ? `<p>Anulados: ${c.sales.voided.map((v) => `${esc(v.number)} (${money(v.total)})`).join(", ")}</p>` : ""}
      ${signatures}
    </body></html>`);
  })().catch((err) => toast(err.message, "err"));
  $("#cash-ticket").onclick = () => (async () => {
    const co = await company(), r = paint();
    await printHtml(`<!doctype html><html><head><meta charset="utf-8"><title>Cierre de caja ${esc(c.day)}</title><style>body{font-family:monospace;width:280px;padding:8px;font-size:12px}p{margin:6px 0}table{width:100%;border-collapse:collapse}td{padding:2px 0;vertical-align:top}td:last-child{text-align:right}hr{border:0;border-top:1px dashed #000}.logo{display:block;margin:0 auto 6px;max-width:160px;max-height:70px;object-fit:contain}</style></head><body>
      ${co.logo ? `<img class="logo" src="${esc(logoUrl(co))}" alt="Logo" />` : ""}
      <p><strong>${esc(co.name)}</strong><br>RTN ${esc(co.rtn || "")}<br>CIERRE DE CAJA · ${dateOnly(c.day)}<br>${esc(who)}<br>Impreso ${new Date().toLocaleString("es-HN")}</p><hr>
      ${r.lines.map((l) => `<p><strong>${esc(l.method)}</strong><br>Sistema ${money(l.expected)}${l.counted !== null ? `<br>Contado ${money(l.counted)}<br>${diffLabel(l.diff)}` : ""}</p>`).join("")}
      ${r.opening ? `<p>Fondo inicial incluido en efectivo: ${money(r.opening)}</p>` : ""}<hr>
      <p><strong>${r.total === null ? "Sin contar" : Math.abs(r.total) < 0.005 ? "CAJA CUADRADA" : r.total > 0 ? `SOBRANTE ${money(r.total)}` : `FALTANTE ${money(-r.total)}`}</strong>${r.note ? `<br>${esc(r.note)}` : ""}</p><hr>
      <table><tr><td>Total cobrado</td><td>${money(c.collected)}</td></tr><tr><td>Facturas (${c.sales.invoices})</td><td>${money(c.sales.invoiced)}</td></tr><tr><td>Al crédito</td><td>${money(c.sales.credit)}</td></tr><tr><td>Notas de crédito (${c.sales.notes})</td><td>${money(c.sales.credited)}</td></tr><tr><td>Anulados</td><td>${c.sales.voided.length}</td></tr></table><hr>
      ${c.payments.map((p) => `<p>${esc(p.number)} ${esc(p.method)}<br>${esc(p.client)} · ${money(p.amount)}</p>`).join("")}
      <p><br><br>______________________<br>Firma de quien entrega<br><br><br>______________________<br>Firma de quien recibe</p></body></html>`);
  })().catch((err) => toast(err.message, "err"));
  bindDocButtons(root);
}

/* ───────── bitácora ───────── */
const auditFilter = { q: "", user_id: "", date_from: "", date_to: "" };
const auditQuery = () => "?" + Object.entries(auditFilter).filter(([, v]) => v).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");

async function renderAudit(root) {
  const data = await api("/api/audit" + auditQuery());
  root.innerHTML = `<div class="section-head"><h2>Bitácora</h2><button class="btn" id="audit-csv">Exportar CSV</button></div>
    <p class="muted">Registro de quién hizo qué: ingresos, facturas, cobros, anulaciones, cambios de precio, inventario, compras, bancos, CAI y usuarios. No se puede editar ni borrar desde el sistema.</p>
    <div class="toolbar">
      <input id="a-q" placeholder="Buscar acción, documento o detalle" value="${esc(auditFilter.q)}" />
      <select id="a-user" aria-label="Usuario"><option value="">Todos los usuarios</option>${data.users.map((u) => `<option value="${u.id}" ${u.id === +auditFilter.user_id ? "selected" : ""}>${esc(u.name)}</option>`).join("")}</select>
      <label class="inline">Desde <input id="a-from" type="date" value="${esc(auditFilter.date_from)}" /></label>
      <label class="inline">Hasta <input id="a-to" type="date" value="${esc(auditFilter.date_to)}" /></label>
    </div>
    <div class="card">${table(["FECHA", "USUARIO", "ACCIÓN", "DETALLE"], data.rows.map((r) => `<tr><td>${when(r.created_at)}</td><td>${esc(r.user || "—")}</td><td>${r.entity === "documento" && r.entity_id ? `<button class="btn ghost sm" data-view-doc="${r.entity_id}">${esc(r.action)}</button>` : esc(r.action)}</td><td>${esc(r.detail)}</td></tr>`), "Sin registros con ese filtro")}
    ${data.rows.length >= 300 ? `<p class="muted">Se muestran los 300 más recientes. Usa los filtros o exporta el CSV para ver más.</p>` : ""}</div>`;
  let t; $("#a-q").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { auditFilter.q = e.target.value; render().then(() => { const i = $("#a-q"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }); }, 300); };
  $("#a-user").onchange = (e) => { auditFilter.user_id = e.target.value; render(); };
  $("#a-from").onchange = (e) => { auditFilter.date_from = e.target.value; render(); };
  $("#a-to").onchange = (e) => { auditFilter.date_to = e.target.value; render(); };
  $("#audit-csv").onclick = () => exportCsv("/api/audit.csv" + auditQuery(), "bitacora.csv");
  bindDocButtons(root);
}

/* ───────── configuración ───────── */
async function renderSettings(root) {
  const canCfg = can("config"), canUsers = can("usuarios");
  const [s, users, roleInfo, backups, mail, lic, stores, apiInfo] = await Promise.all([api("/api/settings"), canUsers ? api("/api/users") : [], canUsers ? api("/api/roles") : null, canCfg ? api("/api/backups") : null, canCfg ? api("/api/settings/email") : null, canCfg ? api("/api/license") : null, [], canCfg ? api("/api/api-keys").catch(() => null) : null]);
  STORES = stores;
  const cfgHtml = `<div class="card"><h3>Datos del emisor</h3><form id="set" class="form">
    <label>Nombre comercial<input name="name" value="${esc(s.name)}" required /></label>
    <label>Razón social<input name="legal_name" value="${esc(s.legal_name || "")}" /></label>
    <label>RTN del emisor (14 dígitos)<input name="rtn" value="${esc(s.rtn)}" required /></label>
    <label>Teléfono<input name="phone" value="${esc(s.phone)}" /></label>
    <label class="full">Dirección del establecimiento<input name="address" value="${esc(s.address)}" /></label>
    <label>Correo<input name="email" value="${esc(s.email)}" /></label>
    <label>Moneda<input name="currency" value="${esc(s.currency)}" /></label>
    <label>Cerrar la sesión por inactividad (minutos, 0 = nunca)<input name="idle_minutes" type="number" min="0" max="720" value="${s.idle_minutes ?? 30}" /></label>
    <label class="full check"><input type="checkbox" name="prices_include_tax" ${s.prices_include_tax ? "checked" : ""} /> Los precios de venta <strong>incluyen el ISV</strong> (restaurantes): el precio del menú es lo que paga el cliente y el sistema separa el impuesto.</label>
    <label class="full check"><input type="checkbox" name="pos_enabled" ${s.pos_enabled === false ? "" : "checked"} /> Usar el <strong>Punto de venta</strong> (pantalla de mostrador). Si lo desactivas, se factura desde <em>Ventas › Nueva factura</em>. Para vender sin conexión hace falta tenerlo activo.</label>
    <div class="full price-grid"><h4>Nombres de los 4 precios</h4><p class="muted">Cada producto tiene hasta 4 precios y cada cliente usa uno. Sin el permiso de precio libre, el personal solo elige entre estos.</p>
      <div class="price-row">${(s.price_names || priceNames).map((n, i) => `<label>Precio ${i + 1}<input name="price_name_${i + 1}" value="${esc(n)}" required maxlength="40" /></label>`).join("")}</div></div>
    <label class="full">Logo del negocio (PNG, JPG o WEBP · máx. 2 MB)<input id="logo-file" type="file" accept="image/png,image/jpeg,image/webp" /></label>
    ${s.logo ? `<img class="co-logo" src="${esc(s.logo)}" alt="Logo actual" />` : ""}
    <button class="btn primary" type="submit">Guardar</button><p class="muted">Base de datos: ${esc(s.database)}</p><p id="set-error" class="form-error full"></p>
  </form></div>
  <div class="card" style="margin-top:12px"><div class="section-head"><h3>CAI autorizados por el SAR</h3><button class="btn" id="addcai">Nuevo CAI</button></div>
  <p class="muted">Cada CAI tiene su establecimiento, punto de emisión, rango y fecha límite. El sistema no deja facturar con un CAI vencido o agotado y usa el siguiente vigente automáticamente.</p>
  ${table(["TIPO", "CAI", "PREFIJO", "PRÓXIMO", "RANGO", "RECEPCIÓN", "LÍMITE", "ESTADO", ""], s.cai.map((r) => `<tr><td>${esc(r.purpose_label || (r.doc_type === "01" ? "Factura" : "Nota de crédito"))}<div class="muted small">código ${esc(r.doc_type)}</div></td><td class="mono">${esc(r.cai)}</td><td>${esc(r.establishment)}-${esc(r.emission_point)}-${esc(r.doc_type)}</td><td>${r.current}</td><td>${r.range_from} al ${r.range_to}</td><td><button class="btn ghost sm" data-received="${r.id}" data-value="${r.received_date || ""}" title="Fecha de recepción que se imprime en la factura">${r.received_date ? dateOnly(r.received_date) : "Agregar"}</button></td><td>${dateOnly(r.limit_date)}</td>
    <td>${r.expired ? pill("Vencido") : r.active ? pill("Activo") : pill("Inactivo")}</td><td>${r.current > r.range_to ? "" : `<button class="btn sm" data-toggle="${r.id}">${r.active ? "Desactivar" : "Activar"}</button>`}</td></tr>`))}</div>
  <div class="card" style="margin-top:12px"><div class="section-head"><h3>Series de facturación</h3><button class="btn" id="addseries">Nueva serie</button></div>
  <p class="muted">La serie Normal usa el correlativo del CAI. Una serie con letra (por ejemplo E para ventas exoneradas) lleva su propio talonario dentro del mismo CAI.</p>
  ${table(["SERIE", "NOMBRE", "SIGUIENTE (series con letra)"], s.series.map((r) => `<tr><td>${esc(r.code)}</td><td>${esc(r.name)}</td><td>${r.code === "Normal" ? "usa el CAI" : r.current}</td></tr>`))}</div>
  `;
  const manageable = (u) => user.role === "Master" || u.role !== "Master";
  const matrix = !roleInfo ? "" : `<div class="card" style="margin-top:12px"><h3>Qué puede hacer cada rol</h3>
    <div class="tbl-wrap"><table class="matrix"><thead><tr><th>Permiso</th>${roleInfo.roles.map((r) => `<th title="${esc(r.desc)}">${esc(r.name)}</th>`).join("")}</tr></thead><tbody>
    ${Object.entries(roleInfo.permissions).map(([k, label]) => `<tr><td>${esc(label)}</td>${roleInfo.roles.map((r) => `<td class="${r.permissions.includes(k) ? "up" : "muted"}">${r.permissions.includes(k) ? "✓" : "·"}</td>`).join("")}</tr>`).join("")}
    </tbody></table></div>
    <ul class="muted role-desc">${roleInfo.roles.map((r) => `<li><strong>${esc(r.name)}:</strong> ${esc(r.desc)}</li>`).join("")}</ul></div>`;
  const usersHtml = `<div class="card" style="margin-top:12px"><div class="section-head"><h3>Usuarios${lic && lic.users_allowed ? ` <span class="pill ${users.filter((u) => u.active).length >= lic.users_allowed ? "pendiente" : "activo"}">${users.filter((u) => u.active).length} de ${lic.users_allowed} activos</span>` : ""}</h3><button class="btn" id="adduser">Nuevo usuario</button></div>
  <p class="muted">Cada persona entra con su propio correo y clave. Un usuario desactivado conserva su historial pero ya no puede entrar.</p>
  ${table(["NOMBRE", "CORREO", "ROL", ...(STORES.length > 1 ? ["TIENDA"] : []), "ESTADO", ""], users.map((u) => `<tr><td>${esc(u.name)}</td><td>${esc(u.email)}</td><td>${pill(u.role)}</td>${STORES.length > 1 ? `<td>${esc((STORES.find((x) => x.id === u.store_id) || {}).name || "Todas")}</td>` : ""}<td>${u.active ? pill("Activo") : pill("Desactivado")}</td><td class="row-actions">${manageable(u) ? `<button class="btn sm" data-euser="${u.id}">Editar</button>${u.id === user.id ? "" : `<button class="btn danger sm" data-duser="${u.id}">Eliminar</button>`}` : `<span class="muted">Solo un Master</span>`}</td></tr>`))}</div>${matrix}`;
  const isMaster = user.role === "Master";
  const resetHtml = !isMaster ? "" : `<div class="card danger-zone" style="margin-top:12px"><div class="section-head"><h3>Instalar en un cliente nuevo</h3><button class="btn danger" id="reset-db">Limpiar base de datos…</button></div>
    <p class="muted">Borra los datos de demostración o de prueba para entregar el sistema limpio. Solo un Master puede hacerlo, con su clave, y antes se guarda un respaldo automático. No se permite si ya hay facturas emitidas con un CAI real del SAR: esas deben conservarse por ley.</p></div>`;
  root.innerHTML = `<h2>Configuración</h2>${canCfg ? cfgHtml + licenseHtml(lic) + mailHtml(mail) + backupsHtml(backups) + apiHtml(apiInfo) : ""}${canUsers ? usersHtml : ""}${resetHtml}`;
  if (canCfg) { bindConfig(s); bindLicense(); bindMail(mail); bindBackups(backups); bindApi(); }
  if (canUsers) bindUsers(users, roleInfo);
  if (isMaster) $("#reset-db").onclick = resetDatabase;
}

function bindConfig(s) {
  $("#set").onsubmit = async (e) => {
    e.preventDefault();
    $("#set-error").textContent = "";
    try {
      const f = Object.fromEntries(new FormData(e.target).entries());
      const names = [1, 2, 3, 4].map((n) => (f["price_name_" + n] || "").trim());
      [1, 2, 3, 4].forEach((n) => delete f["price_name_" + n]);
      await api("/api/settings", { method: "PUT", body: { ...f, prices_include_tax: !!f.prices_include_tax, pos_enabled: !!f.pos_enabled, idle_minutes: f.idle_minutes === "" || f.idle_minutes === undefined ? null : +f.idle_minutes, price_names: names } });
      const file = $("#logo-file").files[0];
      if (file) {
        const body = new FormData(); body.append("file", file);
        const res = await fetch("/api/settings/logo", { method: "POST", headers: { Authorization: "Bearer " + token }, body });
        if (!res.ok) throw new Error(errorText(await res.json().catch(() => ({}))));
      }
      toast("Configuración guardada");
      loadBranding();
      boot();
    } catch (err) { $("#set-error").textContent = err.message; alertPopup(err.message); }
  };
  $("#addcai").onclick = () => openModal("Nuevo CAI del SAR", [
    { name: "cai", label: "CAI (como aparece en la Oficina Virtual)", full: true, required: true, placeholder: "A1B2C3-D4E5F6-..." },
    { name: "purpose", label: "Documento", type: "select", options: [{ value: "factura", label: "Factura" }, { value: "nota", label: "Nota de crédito" }, { value: "debito", label: "Nota de débito (módulo adicional)" }, { value: "guia", label: "Guía de remisión (módulo adicional)" }] },
    { name: "doc_type", label: "Código del tipo (2 dígitos del número fiscal)", value: "", placeholder: "Vacío = el sugerido", hint: "Como aparece en tu autorización del SAR. Sugeridos: 01 factura, 06 nota de crédito, 04 nota de débito, 05 guía de remisión. Si tu autorización usa otro código, escríbelo aquí." },
    { name: "limit_date", label: "Fecha límite de emisión", type: "date", required: true },
    { name: "received_date", label: "Fecha de recepción (opcional, sale en la factura)", type: "date" },
    { name: "establishment", label: "Establecimiento", value: "001", required: true }, { name: "emission_point", label: "Punto de emisión", value: "001", required: true },
    { name: "range_from", label: "Rango desde", type: "number", value: 1, min: 1, required: true }, { name: "range_to", label: "Rango hasta", type: "number", value: 500, required: true },
  ], async (b) => { await api("/api/cai", { method: "POST", body: { ...b, doc_type: String(b.doc_type).trim(), range_from: +b.range_from, range_to: +b.range_to, received_date: b.received_date || null } }); toast("CAI registrado"); });
  $$("[data-received]").forEach((b) => b.onclick = () => openModal("Fecha de recepción del CAI", [
    { name: "received_date", label: "Fecha de recepción (déjala vacía para no imprimirla)", type: "date", value: b.dataset.value, full: true },
  ], async (v) => { await api(`/api/cai/${b.dataset.received}/received`, { method: "POST", body: { received_date: v.received_date || null } }); toast("Fecha guardada"); }));
  $$("[data-toggle]").forEach((b) => b.onclick = () => run(() => api(`/api/cai/${b.dataset.toggle}/toggle`, { method: "POST" }), "CAI actualizado"));
  $("#addseries").onclick = () => openModal("Nueva serie", [
    { name: "code", label: "Letra o código de la serie", value: "E", required: true },
    { name: "name", label: "Nombre", value: "Talonario adicional", required: true },
    { name: "cai_id", label: "CAI", type: "select", options: s.cai.filter((c) => c.doc_type === "01").map((c) => ({ value: c.id, label: `${c.cai} (${c.active ? "activo" : "inactivo"})` })), full: true },
  ], async (b) => { await api("/api/series", { method: "POST", body: { code: b.code, name: b.name, cai_id: +b.cai_id } }); toast("Serie creada"); });
}

function bindUsers(users, roleInfo) {
  const roleOptions = roleInfo.roles.filter((r) => user.role === "Master" || r.name !== "Master").map((r) => ({ value: r.name, label: r.name }));
  const userForm = (u) => openModal(u ? "Editar usuario" : "Nuevo usuario", [
    { name: "name", label: "Nombre", value: u?.name, required: true }, { name: "email", label: "Correo", value: u?.email, type: "email", required: true },
    { name: "role", label: "Rol", type: "select", value: u?.role || "Vendedor", options: roleOptions, hint: "Mira la tabla «Qué puede hacer cada rol» más abajo" },
    ...(u ? [{ name: "active", label: "Estado", type: "select", value: u.active ? "1" : "0", options: [{ value: "1", label: "Activo" }, { value: "0", label: "Desactivado (no puede entrar)" }] }] : []),
    ...(STORES.length > 1 ? [{ name: "store_id", label: "Tienda", type: "select", value: u?.store_id || "", options: [{ value: "", label: "Todas (sin restricción)" }, ...STORES.map((x) => ({ value: x.id, label: `${x.code} · ${x.name}` }))], hint: "Un usuario de una tienda solo ve y vende desde las bodegas de esa tienda" }] : []),
    { name: "password", label: u ? "Clave nueva (déjala vacía para no cambiarla)" : "Clave (mínimo 8 caracteres)", type: "password", required: !u, autocomplete: "new-password", full: true },
  ], async (b) => { await api(u ? "/api/users/" + u.id : "/api/users", { method: u ? "PUT" : "POST", body: { ...b, active: u ? b.active === "1" : true, store_id: b.store_id ? +b.store_id : null } }); toast("Usuario guardado"); });
  $("#adduser").onclick = () => userForm(null);
  $$("[data-euser]").forEach((b) => b.onclick = () => userForm(users.find((u) => u.id === +b.dataset.euser)));
  $$("[data-duser]").forEach((b) => b.onclick = async () => { if (await askConfirm("¿Eliminar este usuario? Si solo dejó de trabajar, es mejor desactivarlo.", "Eliminar", true)) run(() => api("/api/users/" + b.dataset.duser, { method: "DELETE" }), "Usuario eliminado"); });
}

/* ───────── correo de salida ───────── */
const MAIL_PRESETS = { gmail: { host: "smtp.gmail.com", port: 587, security: "starttls" }, outlook: { host: "smtp.office365.com", port: 587, security: "starttls" } };

function mailHtml(m) {
  return `<div class="card" style="margin-top:12px" id="mail-card"><div class="section-head"><h3>Correo para enviar facturas${m.available === false ? ` <span class="pill inactivo">Módulo sin activar</span>` : ""}</h3><div class="actions">
      <button type="button" class="btn sm" data-preset="gmail" ${m.available === false ? "disabled" : ""}>Usar Gmail</button><button type="button" class="btn sm" data-preset="outlook" ${m.available === false ? "disabled" : ""}>Usar Outlook / Office 365</button></div></div>
    <p class="muted">Con esto los documentos se envían en PDF desde el botón «Enviar por correo». En Gmail y Outlook usa una <strong>contraseña de aplicación</strong> (se crea en la seguridad de la cuenta), no tu clave normal.</p>
    ${m.available === false ? `<p class="warn-note">Enviar documentos por correo es un módulo del plan Empresarial. Pide tu clave y actívala en Licencia y módulos.</p>` : ""}
    <form id="mail-form" class="form"><fieldset ${m.available === false ? "disabled" : ""} class="plain-fieldset">
      <label>Servidor SMTP<input name="host" value="${esc(m.host)}" placeholder="smtp.gmail.com" /></label>
      <label>Puerto<input name="port" type="number" min="1" max="65535" value="${m.port}" /></label>
      <label>Seguridad<select name="security">${[["starttls", "STARTTLS (puerto 587)"], ["ssl", "SSL (puerto 465)"], ["none", "Sin cifrado"]].map(([v, l]) => `<option value="${v}" ${v === m.security ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label>Usuario<input name="user" value="${esc(m.user)}" placeholder="ventas@miempresa.hn" autocomplete="off" /></label>
      <label>Contraseña${m.has_password ? " (ya guardada: déjala vacía para no cambiarla)" : ""}<input name="password" type="password" autocomplete="new-password" /></label>
      <label>Remitente (correo «De»)<input name="from_email" value="${esc(m.from_email)}" placeholder="${esc(m.company_email || "ventas@miempresa.hn")}" /></label>
      <button class="btn primary" type="submit">Guardar correo</button>
      <div class="inline-field"><input id="mail-test-to" placeholder="Enviar prueba a…" value="${esc(m.company_email)}" /><button class="btn" type="button" id="mail-test">Probar</button></div>
      <p id="mail-error" class="form-error full"></p>
    </fieldset></form></div>`;
}

function bindMail() {
  const form = $("#mail-form");
  $$("[data-preset]").forEach((b) => b.onclick = () => { const p = MAIL_PRESETS[b.dataset.preset]; form.elements.host.value = p.host; form.elements.port.value = p.port; form.elements.security.value = p.security; });
  const body = () => { const f = Object.fromEntries(new FormData(form).entries()); return { host: f.host, port: +f.port || 587, security: f.security, user: f.user, from_email: f.from_email, ...(f.password ? { password: f.password } : {}) }; };
  form.onsubmit = async (e) => {
    e.preventDefault(); $("#mail-error").textContent = "";
    try { await api("/api/settings/email", { method: "PUT", body: body() }); toast("Correo guardado"); await render(); } catch (err) { $("#mail-error").textContent = err.message; }
  };
  $("#mail-test").onclick = async () => {
    $("#mail-error").textContent = "";
    const btn = $("#mail-test"); btn.disabled = true; btn.textContent = "Enviando…";
    try {
      await api("/api/settings/email", { method: "PUT", body: body() });
      await api("/api/settings/email/test", { method: "POST", body: { to: $("#mail-test-to").value } });
      toast("Correo de prueba enviado. Revisa la bandeja de entrada.");
    } catch (err) { $("#mail-error").textContent = err.message; }
    btn.disabled = false; btn.textContent = "Probar";
  };
}

/* ───────── licencia (módulos por clave) ───────── */
function licenseHtml(l) {
  const exp = l.expires ? dateOnly(l.expires) : "sin vencimiento";
  const status = !l.configured ? `<span class="pill inactivo">Sin candado</span>`
    : l.valid ? `<span class="pill activo">Plan ${esc(l.plan_label)}</span>`
    : l.trial.active ? `<span class="pill pendiente">Prueba · quedan ${l.trial.days_left} día(s)</span>` : `<span class="pill vencida">Plan Básico</span>`;
  const lim = l.limits || {};
  const limits = l.valid ? [lim.bodegas ? `${lim.bodegas} bodega(s)` : "bodegas sin límite", lim.tiendas ? `${lim.tiendas} tienda(s)` : "", lim.usuarios ? `${lim.usuarios} usuario(s)` : "", lim.cajas ? `${lim.cajas} caja(s)` : ""].filter(Boolean).join(" · ") : "";
  const state = (m) => (m.licensed ? pill("Activo") : m.active ? `<span class="pill pendiente">${l.configured ? "Incluido en la prueba" : "Activo"}</span>` : `<span class="pill inactivo">Sin activar</span>`);
  const group = (tier, title, hint) => {
    const rows = l.module_list.filter((m) => m.enforced && m.plan === tier);
    return rows.length ? `<div class="lic-group">${title} <small>${hint}</small></div>${table(["MÓDULO", "ESTADO"], rows.map((m) => `<tr><td>${esc(m.label)}</td><td>${state(m)}</td></tr>`))}` : "";
  };
  return `<div class="card" style="margin-top:12px" id="lic-card"><div class="section-head"><h3>Licencia y módulos</h3><div class="actions">${status}</div></div>
    ${!l.configured ? `<p class="warn-note">Esta instalación no tiene llave pública, así que no se aplica ningún candado: todos los módulos están activos.</p>` : ""}
    <p class="muted">El plan <strong>Básico</strong> viene incluido y no necesita clave. Los planes <strong>Profesional</strong> y <strong>Empresarial</strong> (o <strong>Todo incluido</strong>, con los módulos de hoy y los futuros) se activan con una clave. La facturación y tus datos <strong>nunca</strong> se bloquean. Para activar, envía tu <strong>código de instalación</strong> a tu proveedor y pega aquí la clave que te dé.</p>
    <div class="lic-install"><span class="muted">Código de instalación</span><strong class="mono" id="lic-install">${esc(l.install_id)}</strong><button type="button" class="btn sm" id="lic-copy">Copiar</button></div>
    ${l.valid ? `<p>Clave <span class="mono">${esc(l.key_id)}</span> · ${l.expires ? `vence el <strong>${esc(exp)}</strong>${l.days_left <= 15 ? ` <span class="down">(${l.days_left} día(s))</span>` : ""}` : "sin vencimiento"}${limits ? ` · ${esc(limits)}` : ""}${l.users_allowed ? ` · usuarios activos máx. ${l.users_allowed}` : ""}</p>` : ""}
    ${l.reason ? `<p class="form-error">${esc(l.reason)}</p>` : ""}
    <div class="lic-group">Básico <small>incluido, sin clave</small></div>
    <p class="muted small">Facturación con CAI/SAR, cotizaciones, punto de venta, clientes, productos e inventario (1 bodega), registro de compras recibidas de contado, usuarios y permisos, turnos y cierre de caja, <strong>reportes SAR (libros de ventas y compras, retenciones)</strong>, cuentas por cobrar y respaldo manual.</p>
    ${group("profesional", "Profesional", "licencia requerida")}${group("empresarial", "Empresarial", "incluye todo lo de Profesional")}
    ${l.configured ? `<form id="lic-form" class="form"><label class="full">Clave de activación<textarea name="key" rows="3" required placeholder="ABCDE-FGHIJ-KLMNO-…" spellcheck="false"></textarea></label>
      <button class="btn primary" type="submit">Activar clave</button><p id="lic-error" class="form-error full"></p></form>` : ""}</div>`;
}

function bindLicense() {
  const copy = $("#lic-copy");
  if (copy) copy.onclick = async () => { try { await navigator.clipboard.writeText($("#lic-install").textContent); toast("Código copiado"); } catch (err) { toast("Selecciona el código y cópialo con Ctrl+C", "err"); } };
  const form = $("#lic-form");
  if (!form) return;
  form.onsubmit = async (e) => {
    e.preventDefault(); $("#lic-error").textContent = "";
    try { await api("/api/license", { method: "POST", body: { key: form.elements.key.value } }); toast("Licencia activada"); setTimeout(() => location.reload(), 700); }  // recarga: la insignia y los candados salen del arranque
    catch (err) { $("#lic-error").textContent = err.message; alertPopup(err.message, "Clave no válida"); }
  };
}

/* ───────── API REST de lectura (módulo API) ───────── */
function apiHtml(a) {
  if (!a) return "";
  const keys = a.keys.map((k) => `<tr><td>${esc(k.name)}</td><td class="mono">${esc(k.prefix)}…</td><td>${when(k.created_at)}</td><td>${k.last_used ? when(k.last_used) : "—"}</td><td>${k.active ? pill("Activo") : `<span class="pill inactivo">Revocada</span>`}</td>
    <td class="row-actions">${k.active ? `<button class="btn danger sm" data-revoke="${k.id}">Revocar</button>` : ""}</td></tr>`);
  return `<div class="card" style="margin-top:12px" id="api-card"><div class="section-head"><h3>API para integraciones${a.available ? "" : ` <span class="pill inactivo">Módulo sin activar</span>`}</h3><div class="actions"><button class="btn primary" id="api-new" ${a.available ? "" : "disabled"}>Nueva llave</button></div></div>
    <p class="muted">Llaves de <strong>solo lectura</strong> para conectar otros sistemas (tienda en línea, hoja de cálculo, contabilidad): productos con sus precios, existencias, clientes y facturas. No incluye costos ni permite cambiar nada. ${a.available ? "" : "Es un módulo del plan Profesional."}</p>
    <p class="muted small mono">curl -H "X-API-Key: vk_…" https://TU-SERVIDOR/api/v1/products · /api/v1/stock · /api/v1/clients · /api/v1/documents?kind=factura&amp;desde=2026-01-01 · límite 120 peticiones por minuto por llave</p>
    ${table(["NOMBRE", "LLAVE", "CREADA", "ÚLTIMO USO", "ESTADO", ""], keys, "Aún no hay llaves")}</div>`;
}

function bindApi() {
  const add = $("#api-new");
  if (add) add.onclick = () => openModal("Nueva llave de API", [{ name: "name", label: "Para qué sistema (nombre)", required: true, full: true, placeholder: "Tienda en línea" }], async (b) => {
    const k = await api("/api/api-keys", { method: "POST", body: { name: b.name } });
    setTimeout(() => openForm(`Llave «${k.name}»`, `<div class="full"><p class="warn-note">Cópiala ahora: <strong>no se vuelve a mostrar</strong>. Si la pierdes, revócala y crea otra.</p>
      <div class="lic-install"><strong class="mono" id="api-raw" style="word-break:break-all">${esc(k.key)}</strong><button type="button" class="btn sm" id="api-copy">Copiar</button></div></div>`, null,
      { mount: () => { $("#api-copy").onclick = async () => { try { await navigator.clipboard.writeText(k.key); toast("Llave copiada"); } catch (err) { toast("Selecciónala y cópiala con Ctrl+C", "err"); } }; } }), 150);
    render();
    return "stay";
  });
  $$("[data-revoke]").forEach((b) => b.onclick = async () => { if (await askConfirm("¿Revocar esta llave? Los sistemas que la usan dejarán de funcionar.", "Revocar", true)) run(() => api("/api/api-keys/" + b.dataset.revoke, { method: "DELETE" }), "Llave revocada"); });
}

/* ───────── respaldos ───────── */
const fileSize = (n) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

function backupsHtml(b) {
  const st = b.settings;
  const lastAuto = b.files.find((f) => f.auto);
  const status = !st.enabled ? `<span class="pill inactivo">Apagado</span>`
    : lastAuto ? `<span class="pill activo">Activo</span> <span class="muted">Último automático: ${when(lastAuto.created)}</span>`
    : `<span class="pill pendiente">Activo · sin respaldos todavía</span>`;
  return `<div class="card" style="margin-top:12px" id="backups-card"><div class="section-head"><h3>Respaldos</h3><div class="actions">${status}<button class="btn primary" id="backup-now">Respaldar ahora</button></div></div>
    <p class="muted">Comandia respalda la base de datos una vez al día, a partir de la hora elegida (si el sistema está apagado a esa hora, lo hace al abrirlo). Usa mysqldump si está instalado; si no, un respaldo propio que se restaura con <span class="mono">python comandia_cmd.py restaurar archivo</span>. Guarda una copia también fuera del equipo (USB o nube).</p>
    ${b.last_error ? `<p class="form-error">Último error: ${esc(b.last_error)}</p>` : ""}
    ${st.available === false ? `<p class="warn-note">Sin el módulo «Respaldos automáticos» (plan Profesional) solo funciona <strong>Respaldar ahora</strong>: hazlo a diario y copia el archivo a una USB o a otra computadora.</p>` : ""}
    <form id="backup-form" class="form backup-form"><fieldset ${st.available === false ? "disabled" : ""} class="plain-fieldset">
      <label>Respaldo automático<select name="enabled"><option value="1" ${st.enabled ? "selected" : ""}>Activo</option><option value="0" ${st.enabled ? "" : "selected"}>Apagado</option></select></label>
      <label>A partir de las<select name="hour">${Array.from({ length: 24 }, (_, h) => `<option value="${h}" ${h === st.hour ? "selected" : ""}>${String(h).padStart(2, "0")}:00</option>`).join("")}</select></label>
      <label>Respaldos automáticos que se guardan<input name="keep" type="number" min="1" max="365" value="${st.keep}" required /></label>
      <label>Carpeta (vacío = la carpeta «respaldos» de Comandia)<input name="folder" value="${esc(st.folder)}" placeholder="D:\\Respaldos\\Comandia" ${st.env_folder ? "disabled" : ""} /></label>
      <label>Copia secundaria (otro disco o unidad de red, recomendado)<input name="copy_folder" value="${esc(st.copy_folder || "")}" placeholder="E:\\CopiaRespaldos  o  \\\\NAS\\respaldos" /></label>
      <p class="muted full">Se guardan en: <span class="mono">${esc(st.effective_folder)}</span></p>
      <button class="btn" type="submit">Guardar configuración de respaldos</button><p id="backup-error" class="form-error"></p>
    </fieldset></form>
    <h4>Respaldos guardados (${b.files.length})</h4>
    ${table(["FECHA", "ARCHIVO", "TIPO", "TAMAÑO", ""], b.files.slice(0, 15).map((f) => `<tr><td class="nowrap">${when(f.created)}</td><td class="mono">${esc(f.name)}</td><td>${f.auto ? "Automático" : "Manual"}</td><td class="nowrap">${fileSize(f.size)}</td>
      <td class="row-actions">${b.can_download ? `<button class="btn ghost sm" data-dl="${esc(f.name)}">Descargar</button>` : ""}</td></tr>`), "Todavía no hay respaldos")}
    ${b.files.length > 15 ? `<p class="muted">Se muestran los 15 más recientes.</p>` : ""}</div>`;
}

function bindBackups() {
  $("#backup-now").onclick = async () => {
    const btn = $("#backup-now"); btn.disabled = true; btn.textContent = "Respaldando…";
    try { const r = await api("/api/backups", { method: "POST" }); toast(`Respaldo listo: ${r.name} (${fileSize(r.size)})`); await render(); }
    catch (err) { toast(err.message, "err"); btn.disabled = false; btn.textContent = "Respaldar ahora"; }
  };
  $("#backup-form").onsubmit = async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target).entries());
    try {
      await api("/api/backups/settings", { method: "PUT", body: { enabled: f.enabled === "1", hour: +f.hour, keep: +f.keep, folder: f.folder ?? "", copy_folder: f.copy_folder ?? "" } });
      toast("Configuración de respaldos guardada"); await render();
    } catch (err) { $("#backup-error").textContent = err.message; }
  };
  $$("[data-dl]").forEach((b) => b.onclick = () => exportCsv("/api/backups/" + encodeURIComponent(b.dataset.dl), b.dataset.dl));
}

/* ───────── limpiar la base (instalación en un cliente nuevo) ───────── */
async function resetDatabase() {
  const check = await api("/api/admin/reset-check").catch((err) => { toast(err.message, "err"); return null; });
  if (!check) return;
  const c = check.counts;
  if (!check.allowed) {
    openForm("Limpiar base de datos", `<div class="full info warn-box">No se puede limpiar: hay ${check.real_cai_documents} documento(s) emitidos con un CAI real del SAR. Por ley deben conservarse.</div>`, null);
    return;
  }
  openModal("Limpiar base de datos", [
    { type: "info", html: `Hoy hay <strong>${c.documentos}</strong> documentos, <strong>${c.compras}</strong> compras, <strong>${c.productos}</strong> productos, <strong>${c.clientes}</strong> clientes, <strong>${c.proveedores}</strong> proveedores y <strong>${c.usuarios}</strong> usuarios.` },
    { name: "mode", label: "Qué borrar", type: "select", full: true, value: "todo", options: [
      { value: "todo", label: "Todo: base en blanco para un cliente nuevo" },
      { value: "movimientos", label: "Solo movimientos: ventas, compras, cobros, bancos e inventario (conserva productos, clientes, proveedores y CAI)" },
    ], hint: "«Todo» deja solo tu usuario, la Bodega principal y el cliente Consumidor final. Los datos del emisor y el logo se conservan para que los edites." },
    { name: "backup", label: "Respaldo", type: "select", full: true, value: "1", options: [{ value: "1", label: "Hacer respaldo automático antes (recomendado)" }, { value: "0", label: "Ya hice un respaldo: continuar sin respaldo automático" }] },
    { name: "password", label: "Tu clave de Master", type: "password", required: true, autocomplete: "current-password" },
    { name: "confirm", label: "Escribe LIMPIAR para confirmar", required: true, placeholder: "LIMPIAR" },
  ], async (b) => {
    if (b.confirm.trim().toUpperCase() !== "LIMPIAR") throw new Error("Escribe LIMPIAR para confirmar");
    const r = await api("/api/admin/reset", { method: "POST", body: { mode: b.mode, password: b.password, confirm: b.confirm, backup: b.backup === "1" } });
    toast(r.backup ? `Base limpia. Respaldo guardado en ${r.backup}` : "Base limpia");
    await boot();
    return "stay";
  }, { submitLabel: "Limpiar base de datos", danger: true });
}

/* ───────── búsqueda global (Ctrl+K) ───────── */
let searchTimer;
$("#global-search").oninput = (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    const q = e.target.value.trim();
    const box = $("#results");
    if (q.length < 2) { box.classList.remove("open"); return; }
    try {
      const data = await api("/api/search?q=" + encodeURIComponent(q));
      const items = [...data.clients, ...data.documents, ...data.products];
      box.innerHTML = items.map((i) => `<button data-type="${i.type}" data-id="${i.id}" data-name="${esc(i.name)}"><small class="muted">${i.type}</small> ${esc(i.name)} ${i.rtn ? `<small class="muted">· ${esc(i.rtn)}</small>` : ""}</button>`).join("") || `<button type="button">Sin resultados</button>`;
      box.classList.add("open");
      $$("button[data-type]", box).forEach((b) => b.onclick = () => {
        box.classList.remove("open"); e.target.value = "";
        if (b.dataset.type === "documento") showDoc(b.dataset.id);
        if (b.dataset.type === "cliente") goto("clientes", b.dataset.name);
        if (b.dataset.type === "producto") goto("inventario", b.dataset.name);
      });
    } catch (err) { /* sesión expirada: api() ya mostró el login */ }
  }, 200);
};
document.addEventListener("click", (e) => { if (!e.target.closest(".search")) $("#results").classList.remove("open"); });

if (token && user) boot();
