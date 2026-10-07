/* Comandia · administración del restaurante: diseño del plano, recetas, descriptivos, impresoras de comandas y órdenes de preparación. */

const restState = { tab: "plano", salonId: null };
const REST_TABS = [["plano", "Plano de salones", ["salones"]], ["recetas", "Recetas", ["catalogo", "ver_costos"]], ["descriptivos", "Descriptivos", ["catalogo"]],
  ["impresoras", "Impresoras", ["config"]], ["preparacion", "Preparación", ["inventario"]]];

async function renderRestaurant(root) {
  const tabs = REST_TABS.filter(([, , perms]) => can(...perms));
  if (!tabs.length) { root.innerHTML = `<div class="card"><p>No tienes permiso para esta pantalla.</p></div>`; return; }
  if (!tabs.find((t) => t[0] === restState.tab)) restState.tab = tabs[0][0];
  root.innerHTML = `<div class="section-head"><h2>Restaurante</h2></div>
    <div class="salon-tabs">${tabs.map(([k, label]) => `<button class="tab-chip ${k === restState.tab ? "on" : ""}" data-rt="${k}">${label}</button>`).join("")}</div><div id="rest-body"></div>`;
  $$("[data-rt]", root).forEach((b) => b.onclick = () => { restState.tab = b.dataset.rt; render(); });
  const body = $("#rest-body");
  await ({ plano: renderPlano, recetas: renderRecetas, descriptivos: renderDescriptivos, impresoras: renderImpresoras, preparacion: renderPreparacion }[restState.tab])(body);
}

/* ───────── plano de salones ───────── */
const PL = { salons: [], items: [], sel: null, dirty: false, key: 0, scale: 1 };
const PL_KINDS = [["mesa", "Mesa"], ["mobiliario", "Mobiliario"], ["planta", "Planta"], ["pared", "Pared"], ["piso", "Piso"], ["puerta", "Puerta"]];

async function renderPlano(root) {
  PL.salons = await api("/api/salons");
  if (!PL.salons.find((s) => s.id === restState.salonId)) restState.salonId = PL.salons.length ? PL.salons[0].id : null;
  loadPlano(); paintPlano(root);
}
function loadPlano() {
  const s = PL.salons.find((x) => x.id === restState.salonId);
  PL.items = s ? s.items.map((i) => ({ ...i, _k: ++PL.key })) : []; PL.sel = null; PL.dirty = false;
}
function paintPlano(root) {
  const s = PL.salons.find((x) => x.id === restState.salonId);
  const b = floorBounds(PL.items);
  root.innerHTML = `<div class="card"><div class="section-head"><h3>Diseña tus salones</h3><div class="actions">
      <button class="btn" id="pl-new">Nuevo salón</button>${s ? `<button class="btn" id="pl-ren">Renombrar</button><button class="btn danger" id="pl-del">Eliminar salón</button>` : ""}</div></div>
    <div class="salon-tabs">${PL.salons.map((x) => `<button class="tab-chip ${x.id === restState.salonId ? "on" : ""}" data-ps="${x.id}">${esc(x.name)}</button>`).join("") || `<span class="muted">Crea tu primer salón (por ejemplo «Salón principal» o «Terraza»).</span>`}</div>
    ${s ? `<div class="plano-layout"><div><div class="floor edit" id="pl-floor"><div class="floor-size" id="pl-size" style="width:${b.w}px;height:${b.h}px" data-w="${b.w}" data-h="${b.h}">${PL.items.map(planoItem).join("")}</div></div>
        <p class="muted small">Arrastra los elementos para moverlos. Toca uno para editar su nombre, tamaño y giro. Las mesas necesitan un nombre o número distinto.</p></div>
      <aside class="plano-side"><div class="palette"><strong>Agregar al plano</strong><p class="muted small">Toca un modelo para ponerlo en el salón. Pasa el cursor para ver para qué sirve.</p>
          <div class="preset-grid">${TABLE_PRESETS.map((p) => `<button type="button" class="preset" data-preset="${p.id}" title="${esc(p.info)}"><span class="pv pv-${p.kind}">${p.kind === "mesa" || p.shape === "sofa" ? tableSvg(p.shape, p.w, p.h, p.seats) : decorSvg(p.kind, p.shape, p.w, p.h)}</span><small>${esc(p.label)}</small></button>`).join("")}</div></div>
        <div id="pl-props">${propsHtml()}</div>
        <button class="btn primary full" id="pl-save" ${PL.dirty ? "" : "disabled"}>Guardar plano</button></aside></div>` : ""}</div>`;
  fitPlano(); bindPlano(root);
}
function planoItem(i) {
  const cls = `fi ${i.kind} ${i.shape} edit ${PL.sel === i._k ? "sel" : ""}`;
  const attrs = `data-k="${i._k}" style="${floorItemStyle(i)}" tabindex="0" role="button" aria-label="${esc(i.kind)} ${esc(i.name)}"`;
  if (i.kind === "mesa") return `<div class="${cls} libre" ${attrs}>${tableSvg(i.shape, i.w, i.h, i.seats)}<div class="fi-label" style="transform:rotate(${-(i.rotation || 0)}deg)"><strong>${esc(i.name || "?")}</strong><small>${i.seats} lugares</small></div>${i.tab ? `<i class="lock" title="Tiene una cuenta abierta">●</i>` : ""}</div>`;
  return `<div class="${cls}" ${attrs}>${decorSvg(i.kind, i.shape, i.w, i.h)}${i.kind === "mobiliario" || i.kind === "planta" ? `<span class="fi-text">${esc(i.name)}</span>` : ""}</div>`;
}
function fitPlano() {
  const box = $("#pl-floor"), size = $("#pl-size"); if (!box || !size) return;
  const s = Math.min(1.2, box.clientWidth / +size.dataset.w); PL.scale = s;
  size.style.transform = `scale(${s})`; size.style.transformOrigin = "top left"; box.style.height = Math.ceil(+size.dataset.h * s) + "px";
}
function propsHtml() {
  const i = PL.items.find((x) => x._k === PL.sel);
  if (!i) return `<p class="muted">Selecciona un elemento del plano para editarlo.</p>`;
  const num = (k, label, min, max) => `<label>${label}<input type="number" data-p="${k}" value="${i[k]}" min="${min}" max="${max}" step="${k === "x" || k === "y" ? 10 : 1}" /></label>`;
  return `<div class="props form"><h4 class="full">${PL_KINDS.find((k) => k[0] === i.kind)[1]}</h4>
    <label class="full">${i.kind === "mesa" ? "Nombre o número" : "Texto (opcional)"}<input data-p="name" value="${esc(i.name)}" maxlength="40" autocomplete="off" /></label>
    <label>Forma<select data-p="shape">${Object.entries(SHAPE_LABEL).map(([v, l]) => `<option value="${v}" ${i.shape === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
    ${i.kind === "mesa" ? num("seats", "Lugares", 0, 50) : ""}${num("w", "Ancho", 10, 2000)}${num("h", "Alto", 10, 2000)}${num("x", "Izquierda", 0, 5000)}${num("y", "Arriba", 0, 5000)}${num("rotation", "Giro (°)", 0, 359)}
    <div class="full actions"><button type="button" class="btn sm" id="pl-dup">Duplicar</button><button type="button" class="btn danger sm" id="pl-rm">Quitar</button></div></div>`;
}
function bindPlano(root) {
  $$("[data-ps]", root).forEach((b) => b.onclick = async () => { if (PL.dirty && !(await askConfirm("Hay cambios sin guardar en este salón. ¿Descartarlos?", "Descartar", true))) return; restState.salonId = +b.dataset.ps; loadPlano(); paintPlano(root); });
  $("#pl-new").onclick = () => openModal("Nuevo salón", [{ name: "name", label: "Nombre", required: true, full: true, placeholder: "Salón principal, Terraza, Barra…" }], async (b) => { const s = await api("/api/salons", { method: "POST", body: { name: b.name } }); restState.salonId = s.id; });
  if (!$("#pl-size")) return;
  $("#pl-ren").onclick = () => { const s = PL.salons.find((x) => x.id === restState.salonId); openModal("Renombrar salón", [{ name: "name", label: "Nombre", value: s.name, required: true, full: true }], (b) => api("/api/salons/" + s.id, { method: "PUT", body: { name: b.name } })); };
  $("#pl-del").onclick = async () => { if (await askConfirm("¿Eliminar este salón y su plano? Las mesas con cuentas abiertas lo impiden.", "Eliminar", true)) { try { await api("/api/salons/" + restState.salonId, { method: "DELETE" }); restState.salonId = null; render(); } catch (err) { toast(err.message, "err"); } } };
  $$("[data-preset]", root).forEach((b) => b.onclick = () => addPlanoItem(b.dataset.preset));
  $("#pl-save").onclick = () => savePlano();
  $$(".fi.edit", root).forEach((el) => bindDrag(el, root));
  bindProps(root);
}
function bindProps(root) {
  $$("[data-p]", root).forEach((inp) => inp.oninput = inp.onchange = () => {
    const i = PL.items.find((x) => x._k === PL.sel); if (!i) return;
    const k = inp.dataset.p; i[k] = ["name", "shape"].includes(k) ? inp.value : Math.max(0, +inp.value || 0);
    PL.dirty = true; repaintItem(i); if (k === "w" || k === "h" || k === "x" || k === "y") refreshBounds(); markDirty();
  });
  if ($("#pl-rm")) $("#pl-rm").onclick = () => { PL.items = PL.items.filter((x) => x._k !== PL.sel); PL.sel = null; PL.dirty = true; paintPlano($("#rest-body")); };
  if ($("#pl-dup")) $("#pl-dup").onclick = () => { const i = PL.items.find((x) => x._k === PL.sel); const c = { ...i, id: undefined, tab: null, _k: ++PL.key, x: i.x + 20, y: i.y + 20, name: i.kind === "mesa" ? "" : i.name }; PL.items.push(c); PL.sel = c._k; PL.dirty = true; paintPlano($("#rest-body")); };
}
function markDirty() { const b = $("#pl-save"); if (b) b.disabled = !PL.dirty; }
function repaintItem(i) { const el = $(`.fi.edit[data-k="${i._k}"]`); if (!el) return; el.outerHTML = planoItem(i); const n = $(`.fi.edit[data-k="${i._k}"]`); bindDrag(n, $("#rest-body")); }
function refreshBounds() { const b = floorBounds(PL.items), size = $("#pl-size"); size.style.width = b.w + "px"; size.style.height = b.h + "px"; size.dataset.w = b.w; size.dataset.h = b.h; fitPlano(); }
function addPlanoItem(presetId) {
  const p = TABLE_PRESETS.find((x) => x.id === presetId);
  const used = new Set(PL.items.map((i) => i.name));
  let name = "";
  if (p.kind === "mesa") { let k = PL.items.filter((i) => i.kind === "mesa").length + 1; while (used.has(String(k))) k++; name = p.shape === "barra" ? `B${PL.items.filter((i) => i.shape === "barra").length + 1}` : String(k); }
  else if (p.kind === "mobiliario") name = p.shape === "sofa" ? "Sofá" : "Mueble";
  const i = { _k: ++PL.key, kind: p.kind, name, shape: p.shape, x: 40, y: 40, w: p.w, h: p.h, rotation: 0, seats: p.seats };
  PL.items.push(i); PL.sel = i._k; PL.dirty = true; paintPlano($("#rest-body"));
}
function bindDrag(el, root) {
  el.onpointerdown = (e) => {
    if (e.button !== undefined && e.button > 0) return;
    const i = PL.items.find((x) => x._k === +el.dataset.k); if (!i) return;
    const changedSel = PL.sel !== i._k; PL.sel = i._k;
    $$(".fi.edit", root).forEach((x) => x.classList.toggle("sel", x === el));
    if (changedSel) { $("#pl-props").innerHTML = propsHtml(); bindProps(root); }
    const sx = e.clientX, sy = e.clientY, ox = i.x, oy = i.y; let moved = false;
    // Se escucha en la ventana (no con captura del puntero): sigue funcionando aunque el elemento se repinte, con ratón o con el dedo.
    const move = (m) => {
      const dx = (m.clientX - sx) / PL.scale, dy = (m.clientY - sy) / PL.scale;
      if (!moved && Math.hypot(dx, dy) < 4) return; moved = true;
      i.x = Math.max(0, Math.round((ox + dx) / 10) * 10); i.y = Math.max(0, Math.round((oy + dy) / 10) * 10);
      const cur = $(`.fi.edit[data-k="${i._k}"]`); if (cur) { cur.style.left = i.x + "px"; cur.style.top = i.y + "px"; }
    };
    const up = () => {
      window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); window.removeEventListener("pointercancel", up);
      if (moved) { PL.dirty = true; markDirty(); refreshBounds(); const x = $('[data-p="x"]'), y = $('[data-p="y"]'); if (x) x.value = i.x; if (y) y.value = i.y; }
    };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up); window.addEventListener("pointercancel", up);
    e.preventDefault();
  };
}
async function savePlano() {
  const items = PL.items.map((i) => ({ ...(i.id ? { id: i.id } : {}), kind: i.kind, name: i.name, shape: i.shape, x: i.x, y: i.y, w: i.w, h: i.h, rotation: i.rotation || 0, seats: i.seats || 0 }));
  try {
    const s = await api(`/api/salons/${restState.salonId}/layout`, { method: "PUT", body: { items } });
    toast("Plano guardado"); PL.salons = await api("/api/salons"); loadPlano(); paintPlano($("#rest-body")); return s;
  } catch (err) { toast(err.message, "err"); }
}

/* ───────── recetas ───────── */
async function renderRecetas(root) {
  const [products, recipes] = await Promise.all([api("/api/products"), api("/api/recipes")]);
  const byId = Object.fromEntries(recipes.map((r) => [r.product_id, r]));
  const owners = products.filter((p) => ["platillo", "elaborado"].includes(p.kind));
  const costs = can("ver_costos");
  root.innerHTML = `<div class="card"><div class="section-head"><h3>Recetas y costo por ingredientes</h3></div>
    <p class="muted">Cada platillo o elaborado lleva su receta: al venderlo, el sistema descuenta los ingredientes del inventario en proporción y el costo sale de lo que cuestan. Los productos se crean en <strong>Inventario</strong> con el tipo <em>platillo</em>, <em>insumo</em> o <em>elaborado</em>.</p>
    ${table(["CÓDIGO", "PRODUCTO", "TIPO", "INGREDIENTES", ...(costs ? ["COSTO", "PRECIO", "MARGEN"] : []), ""], owners.map((p) => {
      const r = byId[p.id], cost = r ? r.cost : null;
      return `<tr><td class="mono">${esc(p.sku)}</td><td>${esc(p.name)}</td><td>${pill(p.kind === "platillo" ? "Platillo" : "Elaborado")}</td><td>${r ? r.lines.length : `<span class="muted">sin receta</span>`}</td>
        ${costs ? `<td>${cost !== null ? money(cost) : "—"}</td><td>${p.kind === "platillo" ? money(p.price) : "—"}</td><td>${r && r.margin_pct !== null && p.kind === "platillo" ? `<span class="${r.margin_pct < 50 ? "bad" : ""}">${r.margin_pct}%</span>` : "—"}</td>` : ""}
        <td class="row-actions"><button class="btn sm" data-recipe="${p.id}">${r ? "Editar receta" : "Armar receta"}</button></td></tr>`;
    }), "Todavía no hay platillos ni elaborados: créalos en Inventario con ese tipo.")}</div>`;
  $$("[data-recipe]", root).forEach((b) => b.onclick = () => recipeModal(products, +b.dataset.recipe, byId[+b.dataset.recipe]));
}

function recipeModal(products, pid, current) {
  const p = products.find((x) => x.id === pid);
  const ingredients = products.filter((x) => ["insumo", "elaborado", "producto"].includes(x.kind) && x.id !== pid).sort((a, b) => a.name.localeCompare(b.name));
  const costs = can("ver_costos");
  const opt = (sel) => ingredients.map((x) => `<option value="${x.id}" data-cost="${x.cost ?? 0}" data-unit="${esc(x.base_unit)}" ${x.id === sel ? "selected" : ""}>${esc(x.name)} (${esc(x.base_unit)})</option>`).join("");
  openForm(`Receta · ${p.name}`, `<p class="full muted small">Cantidades por <strong>una</strong> unidad de «${esc(p.name)}», en la unidad de cada ingrediente.</p>
    <div class="full" id="rc-rows"></div><div class="full"><button type="button" class="btn sm" id="rc-add">+ Agregar ingrediente</button></div>
    ${costs ? `<div class="full rc-total"><span>Costo por unidad</span><strong id="rc-cost">${money(0)}</strong>${p.kind === "platillo" && p.price ? `<span id="rc-margin" class="muted"></span>` : ""}</div>` : ""}`,
  async (form) => {
    const lines = $$(".rc-row", form).map((r) => ({ ingredient_id: +$("select", r).value, qty: +$("input", r).value })).filter((l) => l.ingredient_id && l.qty > 0);
    await api("/api/recipes/" + pid, { method: "PUT", body: { lines } }); toast("Receta guardada"); await render(); return "stay";
  }, { wide: true, submitLabel: "Guardar receta", mount: (form) => {
    const rows = $("#rc-rows", form);
    const recalc = () => {
      if (!costs) return;
      const c = $$(".rc-row", form).reduce((s, r) => { const o = $("select", r).selectedOptions[0]; const v = (+$("input", r).value || 0) * (+(o?.dataset.cost) || 0); $(".rc-line", r).textContent = money(v); return s + v; }, 0);
      $("#rc-cost", form).textContent = money(c);
      const m = $("#rc-margin", form); if (m) m.textContent = p.price ? `Precio ${money(p.price)} · margen ${Math.round((p.price - c) / p.price * 1000) / 10}%` : "";
    };
    const add = (sel, qty) => {
      const d = document.createElement("div"); d.className = "rc-row";
      d.innerHTML = `<select aria-label="Ingrediente">${opt(sel)}</select><input type="number" min="0" step="0.0001" value="${qty}" aria-label="Cantidad" /><span class="rc-unit"></span>${costs ? `<span class="rc-line"></span>` : ""}<button type="button" class="btn ghost sm" aria-label="Quitar">✕</button>`;
      rows.appendChild(d);
      const unit = () => { $(".rc-unit", d).textContent = $("select", d).selectedOptions[0]?.dataset.unit || ""; recalc(); };
      $("select", d).onchange = unit; $("input", d).oninput = recalc; $("button", d).onclick = () => { d.remove(); recalc(); }; unit();
    };
    (current ? current.lines : []).forEach((l) => add(l.ingredient_id, l.qty));
    if (!current) add(ingredients[0]?.id, 1);
    $("#rc-add", form).onclick = () => add(ingredients[0]?.id, 1);
  } });
}

/* ───────── descriptivos ───────── */
async function renderDescriptivos(root) {
  const [rows, deps] = await Promise.all([api("/api/descriptives?all=true"), api("/api/departments")]);
  root.innerHTML = `<div class="card"><div class="section-head"><h3>Descriptivos del pedido</h3><div class="actions"><button class="btn primary" id="d-new">Nuevo descriptivo</button></div></div>
    <p class="muted">Lo que el mesero marca al tomar un pedido: «sin cebolla», «término medio», «con hielo»… Cada uno aplica a una familia del menú o a todas, y puede llevar un recargo (por ejemplo «extra queso»).</p>
    ${table(["DESCRIPTIVO", "FAMILIA", "RECARGO", "ESTADO", ""], rows.map((d) => `<tr><td>${esc(d.name)}</td><td>${d.department ? esc(d.department) : `<span class="muted">Todas</span>`}</td><td>${d.extra_price ? money(d.extra_price) : "—"}</td><td>${pill(d.active ? "Activo" : "Inactivo")}</td>
      <td class="row-actions"><button class="btn sm" data-de="${d.id}">Editar</button><button class="btn danger sm" data-dd="${d.id}">Borrar</button></td></tr>`), "Sin descriptivos todavía")}</div>`;
  const form = (d) => openModal(d ? "Editar descriptivo" : "Nuevo descriptivo", [
    { name: "name", label: "Nombre", value: d?.name, required: true, full: true, placeholder: "Sin cebolla" },
    { name: "department_id", label: "Familia", type: "select", value: d?.department_id || "", options: [{ value: "", label: "Todas las familias" }, ...deps.departments.map((x) => ({ value: x.id, label: x.name }))] },
    { name: "extra_price", label: "Recargo (L)", type: "number", step: "0.01", min: 0, value: d ? d.extra_price : 0 },
    { name: "active", label: "Estado", type: "select", value: d ? (d.active ? "1" : "0") : "1", options: [{ value: "1", label: "Activo" }, { value: "0", label: "Inactivo" }] },
  ], (b) => api(d ? "/api/descriptives/" + d.id : "/api/descriptives", { method: d ? "PUT" : "POST", body: { name: b.name, department_id: b.department_id ? +b.department_id : null, extra_price: +b.extra_price || 0, active: b.active === "1" } }));
  $("#d-new").onclick = () => form(null);
  $$("[data-de]", root).forEach((b) => b.onclick = () => form(rows.find((d) => d.id === +b.dataset.de)));
  $$("[data-dd]", root).forEach((b) => b.onclick = async () => { if (await askConfirm("¿Borrar este descriptivo? Los pedidos ya tomados no cambian.", "Borrar", true)) run(() => api("/api/descriptives/" + b.dataset.dd, { method: "DELETE" }), "Descriptivo borrado"); });
}

/* ───────── impresoras ───────── */
async function renderImpresoras(root) {
  const rows = await api("/api/printers");
  root.innerHTML = `<div class="card"><div class="section-head"><h3>Impresoras de comandas</h3></div>
    <p class="muted">Cada estación (cocina, barra…) puede tener una <strong>impresora térmica de red</strong> con su dirección IP, por ejemplo <span class="mono">192.168.1.50</span> y el puerto <span class="mono">9100</span>. Solo se aceptan direcciones de tu red local. Sin impresora, la comanda igual aparece en la pantalla de cocina.</p>
    ${table(["ESTACIÓN", "DIRECCIÓN IP", "PUERTO", "COPIAS", "ACTIVA", ""], rows.map((p) => `<tr data-st="${p.station}"><td><strong>${esc(p.station[0].toUpperCase() + p.station.slice(1))}</strong></td>
      <td><input class="pr-host" value="${esc(p.host)}" placeholder="192.168.1.50" inputmode="decimal" autocomplete="off" /></td><td><input class="pr-port" type="number" value="${p.port}" min="1" max="65535" /></td>
      <td><input class="pr-copies" type="number" value="${p.copies}" min="1" max="3" /></td><td><input class="pr-active" type="checkbox" ${p.active || !p.host ? "checked" : ""} /></td>
      <td class="row-actions"><button class="btn sm primary" data-psave="${p.station}">Guardar</button><button class="btn sm" data-ptest="${p.station}">Imprimir prueba</button></td></tr>`))}</div>`;
  const read = (st) => { const r = $(`tr[data-st="${st}"]`, root); return { station: st, host: $(".pr-host", r).value.trim(), port: +$(".pr-port", r).value || 9100, copies: +$(".pr-copies", r).value || 1, active: $(".pr-active", r).checked }; };
  $$("[data-psave]", root).forEach((b) => b.onclick = async () => { try { await api("/api/printers", { method: "PUT", body: read(b.dataset.psave) }); toast("Impresora guardada"); } catch (err) { toast(err.message, "err"); } });
  $$("[data-ptest]", root).forEach((b) => b.onclick = async () => { try { await api("/api/printers", { method: "PUT", body: read(b.dataset.ptest) }); await api(`/api/printers/${b.dataset.ptest}/test`, { method: "POST" }); toast("Prueba enviada: revisa que salga el papel"); } catch (err) { toast(err.message, "err"); } });
}

/* ───────── órdenes de preparación ───────── */
async function renderPreparacion(root) {
  const [orders, products, whs] = await Promise.all([api("/api/preparations"), api("/api/products"), api("/api/warehouses")]);
  const elaborated = products.filter((p) => p.kind === "elaborado");
  root.innerHTML = `<div class="card"><div class="section-head"><h3>Órdenes de preparación</h3><div class="actions"><button class="btn primary" id="po-new" ${elaborated.length ? "" : "disabled"}>Nueva orden</button></div></div>
    <p class="muted">Producen un <strong>elaborado</strong> (una salsa, una masa…) gastando sus ingredientes según su receta. Lo producido queda en el inventario para usarlo en los platillos.</p>
    ${table(["ORDEN", "FECHA", "PRODUCTO", "CANTIDAD", ...(can("ver_costos") ? ["COSTO"] : []), "HECHA POR"], orders.map((o) => `<tr><td class="mono">${esc(o.number)}</td><td>${o.created_at ? new Date(o.created_at).toLocaleString("es-HN") : ""}</td><td>${esc(o.product)}</td><td>${o.qty} ${esc(o.unit)}</td>${can("ver_costos") ? `<td>${money(o.cost)}</td>` : ""}<td>${esc(o.user)}</td></tr>`), "Todavía no hay órdenes")}</div>`;
  if ($("#po-new")) $("#po-new").onclick = () => openModal("Nueva orden de preparación", [
    { name: "product_id", label: "Elaborado", type: "select", full: true, options: elaborated.map((p) => ({ value: p.id, label: `${p.name} (${p.base_unit})` })) },
    { name: "warehouse_id", label: "Bodega", type: "select", options: whs.map((w) => ({ value: w.id, label: w.name })) },
    { name: "qty", label: "Cantidad a producir", type: "number", step: "0.01", min: 0.01, value: 1, required: true },
    { name: "notes", label: "Notas", full: true, value: "" },
  ], (b) => api("/api/preparations", { method: "POST", body: { product_id: +b.product_id, warehouse_id: +b.warehouse_id, qty: +b.qty, notes: b.notes } }).then(() => toast("Orden registrada")), { submitLabel: "Preparar" });
}
