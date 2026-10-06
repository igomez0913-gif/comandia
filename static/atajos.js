/* Atajos de teclado de Comandia.
   - Una sola tabla (ATAJOS) dice qué tecla hace qué en cada pantalla; de ahí salen las acciones, las
     etiquetas que se ven en los botones, la barra de pistas de cada pantalla, las pistas de las ventanas
     emergentes y la ayuda completa (F1 o ?).
   - Las letras sueltas (/, ?, S, N) solo funcionan fuera de un campo de texto; F1…F9 y Ctrl/Alt funcionan siempre.
   - Se carga después de app.js y usa sus funciones (goto, newDocument, can, openForm…). */
"use strict";

const IS_MAC = /Mac|iPhone|iPad/i.test(navigator.platform || "");
const KEY_NAMES = { Enter: "↵", Escape: "Esc", Left: "←", Right: "→", Ctrl: IS_MAC ? "⌘" : "Ctrl" };

/** «Ctrl+Enter» → <span class="kbd">Ctrl+↵</span>; varias opciones separadas por «|» ("F1|?"). */
const kbdHtml = (keys) => keys.split("|").map((k) => `<span class="kbd">${k.split("+").map((p) => esc(KEY_NAMES[p] || p)).join("+")}</span>`).join(" o ");

/* Cada atajo: scope (dónde vale), keys, label, y una acción: btn (hace clic), focus (enfoca un campo) o run.
   when: condición extra · display: solo se muestra (lo maneja otro código) · help: en la ayuda pero sin etiqueta en el botón. */
const ATAJOS = [
  // ── En todo el sistema ──
  { scope: "global", keys: "Ctrl+K", label: "Buscar en todo el sistema", display: true },
  { scope: "global", keys: "F1|?", label: "Ver todos los atajos", run: () => showShortcuts() },
  { scope: "global", keys: "Alt+I", label: "Ir al inicio", run: () => goto("inicio") },
  { scope: "global", keys: "Alt+V", label: "Punto de venta", when: () => POS_ON && can("facturar") && can("cobrar") && !editing(), run: () => goto("pos") },
  { scope: "global", keys: "Alt+N", label: "Nueva factura", when: () => can("facturar") && !editing(), btn: "#new-inv, #new-sale, [data-go=factura]", run: () => newDocument("factura") },
  { scope: "global", keys: "Alt+C", label: "Nueva cotización", when: () => can("cotizar") && !editing(), btn: "#new-quote, [data-go=cotizacion]", run: () => newDocument("cotizacion") },
  { scope: "global", keys: "Esc", label: "Cerrar la ventana o cancelar", display: true },

  // ── Listas (ventas, cuentas por cobrar, inventario, clientes, bitácora…) ──
  { scope: "lista", keys: "/", label: "Buscar en la lista", focus: "#f-q, #q, #a-q", when: () => !editing() },
  { scope: "lista", keys: "Alt+N", label: "Añadir (producto, cliente, bodega…)", btn: "#add", when: () => !editing() },

  // ── Punto de venta ──
  { scope: "pos", keys: "F2", label: "Buscar o escanear producto", focus: "#pos-q" },
  { scope: "pos", keys: "F3", label: "Elegir cliente", focus: "#pos-client" },
  { scope: "pos", keys: "F4", label: "Cambiar forma de pago", run: () => posNextMode() },
  { scope: "pos", keys: "F6", label: "Efectivo recibido", focus: "#pos-received" },
  { scope: "pos", keys: "F7", label: "Descuento a la última línea", run: () => { const b = [...$$("[data-pdisc]")].pop(); if (b) b.click(); }, when: () => !!$("[data-pdisc]") },
  { scope: "pos", keys: "F9", label: "Cobrar", btn: "#pos-pay", run: () => posCheckout() },
  { scope: "pos", keys: "Esc", label: "Limpiar la búsqueda", display: true, bar: true },

  // ── Editor de factura, cotización o nota ──
  { scope: "editor", keys: "F2", label: "Buscar producto", focus: "#sale-q" },
  { scope: "editor", keys: "Ctrl+Enter", label: "Guardar e imprimir", btn: "#d-save" },
  { scope: "editor", keys: "F9", label: "Guardar y cobrar (ya guardada: cobrar)", btn: "#d-savepay, #d-pay" },
  { scope: "editor", keys: "Ctrl+P", label: "Imprimir (carta)", btn: "#d-print" },
  { scope: "editor", keys: "↑ ↓", label: "Moverse entre los productos encontrados (Enter agrega)", display: true, bar: true },

  // ── Cierre de caja ──
  { scope: "caja-turno", keys: "Ctrl+Enter", label: "Abrir o cerrar el turno", btn: "#sh-go, #sh-close" },
  { scope: "caja-turno", keys: "Alt+1", label: "Ingreso de efectivo", btn: "[data-move=Ingreso]" },
  { scope: "caja-turno", keys: "Alt+2", label: "Gasto pagado de caja", btn: "[data-move=Gasto]" },
  { scope: "caja-turno", keys: "Alt+3", label: "Retiro a caja fuerte", btn: "[data-move=Retiro]" },
  { scope: "caja-dia", keys: "Ctrl+P", label: "Imprimir el reporte", btn: "#cash-print" },
  { scope: "caja-dia", keys: "Ctrl+Enter", label: "Registrar el cierre en la bitácora", btn: "#cash-record" },

  // ── Ventanas emergentes ──
  { scope: "modal", keys: "Esc", label: "Cerrar o cancelar", display: true },
  { scope: "modal", keys: "Enter", label: "Guardar o confirmar", display: true },
  { scope: "modal", keys: "Ctrl+Enter", label: "Guardar desde cualquier campo", run: () => submitModal(), when: () => !!modalSubmit() },
  { scope: "modal", keys: "S", label: "Sí (confirmar, o cerrar sin guardar)", btn: "#dc-yes, #cf-yes" },
  { scope: "modal", keys: "N", label: "No (cancelar, o seguir editando)", btn: "#dc-no, #cf-no" },
  { scope: "modal", keys: "Esc", label: "Si hay datos sin guardar, pregunta antes de cerrar", display: true },
];

/* ───────── ayudas ───────── */
const editing = () => !!$("#d-save"); // editor con un documento sin guardar: no se cambia de pantalla por accidente
const modalOpen = () => $("#modal").classList.contains("open");
const modalSubmit = () => $("#modal-form button[type=submit]:not([disabled])");

function posNextMode() {
  const modes = $$("[data-mode]");
  if (!modes.length) return;
  const at = modes.findIndex((b) => b.classList.contains("primary"));
  modes[(at + 1) % modes.length].click();
}
function submitModal() { const b = modalSubmit(); if (b) b.click(); }

/** Pantallas activas ahora: el orden importa (la ventana emergente tapa todo lo demás). */
function currentScopes() {
  if (modalOpen()) return ["modal"];
  const s = [];
  if ($(".odoo")) s.push("editor");
  else if (view === "pos") s.push("pos");
  else if (view === "caja") s.push(cashTab === "turno" ? "caja-turno" : cashTab === "dia" ? "caja-dia" : "caja-historial");
  else if ($("#f-q, #q, #a-q") || $("#add")) s.push("lista");
  s.push("global");
  return s;
}

const firstEl = (selector) => [...$$(selector)].find((el) => el.offsetParent !== null && !el.disabled);

/** ¿Este atajo se puede usar ahora mismo? */
function isActive(a) {
  if (a.when && !a.when()) return false;
  if (a.btn && !a.run && !firstEl(a.btn)) return false;
  if (a.focus && !firstEl(a.focus)) return false;
  return true;
}

/** Una tecla del evento contra una opción como «Ctrl+Enter», «Alt+N», «F9», «/» o «?». */
function keyMatches(e, option) {
  const parts = option.split("+");
  const key = parts.pop();
  const ctrl = e.ctrlKey || e.metaKey;
  if (parts.includes("Ctrl") !== ctrl || parts.includes("Alt") !== e.altKey) return false;
  if (key === "?") return e.key === "?";
  if (key === "Esc") return e.key === "Escape";
  if (/^\d$/.test(key)) return e.code === "Digit" + key || e.code === "Numpad" + key;
  if (/^[A-Za-z]$/.test(key)) {
    if (e.shiftKey) return false;
    // Con Alt el carácter cambia según el teclado: se compara la tecla física.
    return parts.includes("Alt") ? e.code === "Key" + key.toUpperCase() : e.key.toLowerCase() === key.toLowerCase();
  }
  return e.key === key;
}

const isBare = (option) => !/(Ctrl|Alt)\+/.test(option) && !/^F\d+$/.test(option) && option !== "Enter" && option !== "Esc";

document.addEventListener("keydown", (e) => {
  if (!user || e.isComposing || !$("#login").classList.contains("hidden")) return;
  if (e.key === "F1") { e.preventDefault(); if (!e.repeat && !modalOpen()) showShortcuts(); return; }
  if (e.repeat) return;
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
  const scopes = currentScopes();
  for (const scope of scopes) {
    for (const a of ATAJOS) {
      if (a.scope !== scope || a.display) continue;
      const option = a.keys.split("|").find((o) => keyMatches(e, o));
      if (!option || (typing && isBare(option)) || !isActive(a)) continue;
      e.preventDefault();
      if (a.run) a.run();
      else if (a.focus) { const el = firstEl(a.focus); el.focus(); if (el.select) el.select(); }
      else if (a.btn) firstEl(a.btn).click();
      return;
    }
  }
  // Esc en la búsqueda del punto de venta: la limpia (la ventana emergente la cierra app.js)
  if (e.key === "Escape" && view === "pos" && !modalOpen() && document.activeElement?.id === "pos-q") {
    $("#pos-q").value = ""; $("#pos-hits")?.classList.remove("open");
  }
});

/* ───────── lo que se ve: etiquetas en botones, barra de pistas y pistas de ventanas ───────── */
const SCOPE_TITLES = { global: "En todo el sistema", lista: "En listas", pos: "Punto de venta", editor: "Factura, cotización y nota", "caja-turno": "Mi turno de caja", "caja-dia": "Corte del día", modal: "En ventanas emergentes" };

function visibleShortcuts(scopes) {
  return ATAJOS.filter((a) => scopes.includes(a.scope) && (a.display || isActive(a)));
}

let deco = null, decoQueued = false;
function decorate() {
  decoQueued = false;
  const view$ = $("#view");
  if (!view$ || !user) return;
  deco.disconnect();
  // 1) etiquetas en los botones que tienen atajo
  for (const a of ATAJOS) {
    if (!a.btn || a.display || a.scope === "modal" || !currentScopes().includes(a.scope)) continue;
    if (a.when && !a.when()) continue;
    for (const b of $$(a.btn, view$)) {
      if (b.querySelector(".kbd") || b.dataset.kbd) continue;
      b.dataset.kbd = a.keys;
      b.insertAdjacentHTML("beforeend", ` ${kbdHtml(a.keys.split("|")[0])}`);
    }
  }
  // 2) barra de pistas arriba de la pantalla
  const scopes = currentScopes();
  const own = visibleShortcuts(scopes.filter((s) => s !== "global")).filter((a) => !a.display || a.bar);
  let bar = $("#hintbar");
  if (!own.length) { if (bar) bar.remove(); } else {
    const html = own.map((a) => `<span>${kbdHtml(a.keys.split("|")[0])} ${esc(a.label)}</span>`).join("") + `<span>${kbdHtml("F1")} Todos los atajos</span>`;
    if (!bar) { bar = document.createElement("div"); bar.id = "hintbar"; bar.className = "hintbar"; view$.prepend(bar); }
    if (bar.dataset.html !== html) { bar.innerHTML = html; bar.dataset.html = html; }
    if (view$.firstElementChild !== bar) view$.prepend(bar);
  }
  deco.observe(view$, { childList: true, subtree: true });
}
function queueDecorate() { if (!decoQueued) { decoQueued = true; requestAnimationFrame(decorate); } }

/** Pistas al pie de cada ventana emergente. */
function decorateModal() {
  const modal = $(".modal");
  if (!modal) return;
  let hints = $("#modal-hints");
  if (!hints) { hints = document.createElement("div"); hints.id = "modal-hints"; hints.className = "modal-hints"; modal.appendChild(hints); }
  if (!modalOpen()) { hints.innerHTML = ""; return; }
  const confirm = !!$("#cf-yes"), submit = !!modalSubmit();
  const parts = [];
  if (confirm) parts.push(`${kbdHtml("S")} Sí`, `${kbdHtml("N")} No`, `${kbdHtml("Esc")} Cancelar`);
  else if (submit) parts.push(`${kbdHtml("Enter")} Guardar`, `${kbdHtml("Ctrl+Enter")} Guardar desde cualquier campo`, `${kbdHtml("Esc")} Cerrar (pregunta si hay datos sin guardar)`);
  else parts.push(`${kbdHtml("Esc")} Cerrar`);
  const html = parts.map((p) => `<span>${p}</span>`).join("");
  if (hints.dataset.html !== html) { hints.innerHTML = html; hints.dataset.html = html; }
}

/** Ayuda completa: F1 o ?. */
function showShortcuts() {
  const scopes = currentScopes().filter((s) => s !== "modal");
  const ordered = [...scopes.filter((s) => s !== "global"), "global", "modal"];
  const groups = ordered.map((scope) => {
    const rows = ATAJOS.filter((a) => a.scope === scope && (scope === "modal" || !a.when || a.when()));
    const seen = new Set();
    const unique = rows.filter((a) => { const k = a.keys + a.label; return seen.has(k) ? false : (seen.add(k), true); });
    return unique.length ? `<h4>${esc(SCOPE_TITLES[scope] || scope)}</h4>${table(["TECLA", "QUÉ HACE"], unique.map((a) => `<tr><td class="nowrap">${kbdHtml(a.keys)}</td><td>${esc(a.label)}</td></tr>`))}` : "";
  }).join("");
  openForm("Atajos de teclado", `<div class="full">${groups}
    <p class="muted small">${IS_MAC ? "En Mac, Ctrl se cambia por ⌘. " : ""}Las letras sueltas (/, ?, S, N) solo funcionan cuando no estás escribiendo en un campo; las teclas F y las combinaciones con Ctrl o Alt funcionan siempre. En el punto de venta, escanear un código y presionar Enter agrega el producto; <strong>3*código</strong> agrega 3 unidades.</p></div>`, null, { wide: true });
}

/* ───────── arranque ───────── */
deco = new MutationObserver(queueDecorate);
(() => {
  const root = $("#view");
  if (root) deco.observe(root, { childList: true, subtree: true });
  const modal = $("#modal");
  new MutationObserver(decorateModal).observe(modal, { attributes: true, attributeFilter: ["class"], subtree: false });
  new MutationObserver(decorateModal).observe($("#modal-form"), { childList: true });
  const help = $("#help-keys");
  if (help) help.onclick = () => (modalOpen() ? null : showShortcuts());
  queueDecorate();
})();
