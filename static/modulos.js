/* Módulos adicionales de la v3.1: reabastecimiento y órdenes de compra. */

const replState = { days: 30, lead: 7, cover: 30, warehouse_id: "", onlyNeeded: true, qty: {}, sup: {}, cost: {}, picked: {} };
const LEVEL_PILL = { agotado: ["Agotado", "vencida"], critico: ["Crítico", "vencida"], bajo: ["Bajo", "pendiente"], ok: ["Bien", "activo"] };

async function printPurchaseOrder(p) {
  const co = (await Offline.company().catch(() => ({}))) || {};
  const name = co.name || ($("#co-name") || {}).textContent || "";
  const rows = p.items.map((i) => `<tr><td>${esc(i.description)}</td><td class="r">${i.qty}</td><td>${esc(i.unit)}</td><td class="r">${money(i.unit_cost)}</td><td class="r">${money(i.total)}</td></tr>`).join("");
  await printHtml(`<!doctype html><html><head><meta charset="utf-8"><title>Orden de compra ${esc(p.number)}</title><style>
    @page { size: letter; margin: 14mm; } body { font-family: Arial, Helvetica, sans-serif; font-size: 12px; color: #111; }
    h1 { font-size: 20px; margin: 0 0 2px; } .muted { color: #555; } table { width: 100%; border-collapse: collapse; margin-top: 14px; }
    th { background: #eee; text-align: left; } th, td { border: 1px solid #999; padding: 5px 7px; } .r { text-align: right; } .tot { margin-top: 10px; text-align: right; font-size: 14px; }
    .sig { display: flex; gap: 40px; margin-top: 60px; } .sig div { flex: 1; border-top: 1px solid #333; padding-top: 4px; text-align: center; }
  </style></head><body><h1>ORDEN DE COMPRA ${esc(p.number)}</h1><div class="muted">${esc(name)}</div>
    <p><b>Proveedor:</b> ${esc(p.supplier)}<br><b>Fecha:</b> ${when(p.issued_at)} · <b>Entregar en:</b> ${esc(p.warehouse)}<br><b>Condición:</b> ${esc(p.payment_terms)}</p>
    <table><thead><tr><th>Descripción</th><th class="r">Cantidad</th><th>Unidad</th><th class="r">Costo</th><th class="r">Importe</th></tr></thead><tbody>${rows}</tbody></table>
    <div class="tot">Subtotal L ${money(p.gravado + p.exento)} · ISV L ${money(p.isv)} · <b>Total L ${money(p.total)}</b></div>
    ${p.notes ? `<p class="muted">${esc(p.notes)}</p>` : ""}<div class="sig"><div>Elaboró</div><div>Aprobó</div><div>Recibe el proveedor</div></div></body></html>`);
}

async function renderReplenish(root) {
  const st = replState;
  const [whs, suppliers] = await Promise.all([api("/api/warehouses"), api("/api/suppliers")]);
  const q = `days=${st.days}&lead=${st.lead}&cover=${st.cover}` + (st.warehouse_id ? `&warehouse_id=${st.warehouse_id}` : "");
  let data;
  try { data = await api("/api/replenishment?" + q); }
  catch (err) { root.innerHTML = `<div class="section-head"><h2>Reabastecimiento</h2></div><div class="card"><p class="muted">${esc(err.message)}</p></div>`; return; }
  const rows = data.rows.filter((r) => !st.onlyNeeded || r.suggested > 0);
  const qtyOf = (r) => (st.qty[r.product_id] !== undefined ? +st.qty[r.product_id] : r.suggested);
  const supOf = (r) => (st.sup[r.product_id] !== undefined ? st.sup[r.product_id] : r.supplier_id || "");
  const costOf = (r) => (st.cost[r.product_id] !== undefined ? +st.cost[r.product_id] : r.unit_cost);
  const supOpts = (sel) => `<option value="">— elegir —</option>` + suppliers.map((s) => `<option value="${s.id}" ${+sel === s.id ? "selected" : ""}>${esc(s.name)}</option>`).join("");
  root.innerHTML = `<div class="section-head"><h2>Reabastecimiento</h2><div class="actions"><button class="btn" id="rp-all">Marcar todo lo sugerido</button><button class="btn" id="rp-none">Desmarcar</button><button class="btn primary" id="rp-go">Crear órdenes de compra (<span id="rp-n">0</span>)</button></div></div>
    <p class="muted">Sugiere qué pedir según lo que vendes y lo que hay. Pide cuando lo disponible (existencia + lo que ya viene en órdenes pendientes) baja del punto de pedido —el mayor entre el stock mínimo y las ventas de los días de entrega— y repone hasta cubrir los días elegidos. Crea una orden pendiente por proveedor; la mercadería entra al inventario cuando la recibes.</p>
    <div class="toolbar">
      <label class="check">Ventas de los últimos <input type="number" id="rp-days" min="7" max="365" class="qty-in" value="${st.days}" /> días</label>
      <label class="check">Entrega del proveedor <input type="number" id="rp-lead" min="0" max="90" class="qty-in" value="${st.lead}" /> días</label>
      <label class="check">Cubrir <input type="number" id="rp-cover" min="1" max="365" class="qty-in" value="${st.cover}" /> días</label>
      <select id="rp-wh"><option value="">Todas las bodegas</option>${whs.map((w) => `<option value="${w.id}" ${+st.warehouse_id === w.id ? "selected" : ""}>${esc(w.name)}</option>`).join("")}</select>
      <label class="check"><input type="checkbox" id="rp-only" ${st.onlyNeeded ? "checked" : ""} /> Solo lo que hay que pedir</label></div>
    <div class="grid-4"><div class="card kpi"><small>Productos a pedir</small><strong>${data.summary.needed}</strong><span class="muted">de ${data.summary.products}</span></div>
      <div class="card kpi"><small>Inversión estimada</small><strong>${money(data.summary.estimated)}</strong><span class="muted">sin ISV</span></div>
      <div class="card kpi"><small>Sin proveedor</small><strong>${data.summary.no_supplier}</strong><span class="muted">elige uno para pedirlos</span></div></div>
    <div class="card repl" style="margin-top:12px">${table(["", "PRODUCTO", "EXISTENCIA", "EN CAMINO", "VENDIDO", "DÍAS DE STOCK", "ESTADO", "PEDIR", "PROVEEDOR", "COSTO", "IMPORTE"], rows.map((r) => {
      const [label, cls] = LEVEL_PILL[r.level];
      return `<tr><td><input type="checkbox" data-pick="${r.product_id}" ${st.picked[r.product_id] ? "checked" : ""} aria-label="Incluir ${esc(r.name)}" /></td><td>${esc(r.name)}<div class="muted small">${esc(r.sku)} · mín. ${r.min_stock} ${esc(r.unit)}</div></td>
        <td>${r.stock} ${esc(r.unit)}</td><td>${r.incoming || "—"}</td><td>${r.sold}<div class="muted small">${r.daily}/día</div></td><td>${r.days_left === null ? "—" : r.days_left}</td><td><span class="pill ${cls}">${label}</span></td>
        <td><input type="number" min="0" step="1" class="qty-in" data-qty="${r.product_id}" value="${qtyOf(r)}" /></td>
        <td><select data-sup="${r.product_id}">${supOpts(supOf(r))}</select></td><td><input type="number" min="0" step="0.01" class="qty-in" data-cost="${r.product_id}" value="${costOf(r)}" /></td>
        <td class="nowrap" data-line="${r.product_id}">${money(qtyOf(r) * costOf(r))}</td></tr>`; }), "Nada que pedir con estos criterios: el inventario cubre las ventas")}</div>`;
  const byId = new Map(rows.map((r) => [r.product_id, r]));
  const chosen = () => rows.filter((r) => st.picked[r.product_id] && qtyOf(r) > 0);
  const refresh = () => { $("#rp-n").textContent = chosen().length; };
  refresh();
  const reload = () => render();
  ["days", "lead", "cover"].forEach((k) => { $("#rp-" + k).onchange = (e) => { st[k] = Math.max(+e.target.value || 0, k === "days" ? 7 : k === "cover" ? 1 : 0); reload(); }; });
  $("#rp-wh").onchange = (e) => { st.warehouse_id = e.target.value; reload(); };
  $("#rp-only").onchange = (e) => { st.onlyNeeded = e.target.checked; reload(); };
  $("#rp-all").onclick = () => { rows.filter((r) => r.suggested > 0).forEach((r) => { st.picked[r.product_id] = true; }); reload(); };
  $("#rp-none").onclick = () => { st.picked = {}; reload(); };
  $$("[data-pick]").forEach((i) => i.onchange = () => { st.picked[i.dataset.pick] = i.checked; refresh(); });
  $$("[data-qty]").forEach((i) => i.oninput = () => { st.qty[i.dataset.qty] = i.value; const r = byId.get(+i.dataset.qty); $(`[data-line="${r.product_id}"]`).textContent = money(qtyOf(r) * costOf(r)); });
  $$("[data-cost]").forEach((i) => i.oninput = () => { st.cost[i.dataset.cost] = i.value; const r = byId.get(+i.dataset.cost); $(`[data-line="${r.product_id}"]`).textContent = money(qtyOf(r) * costOf(r)); });
  $$("[data-sup]").forEach((i) => i.onchange = () => { st.sup[i.dataset.sup] = i.value; });
  $("#rp-go").onclick = () => run(async () => {
    const lines = chosen();
    if (!lines.length) throw new Error("Marca al menos un producto con cantidad mayor que cero");
    if (lines.some((r) => !supOf(r))) throw new Error("Elige el proveedor de todos los productos marcados");
    const wh = st.warehouse_id || (whs[0] || {}).id;
    const res = await api("/api/replenishment/orders", { method: "POST", body: { warehouse_id: +wh, lines: lines.map((r) => ({ product_id: r.product_id, qty: qtyOf(r), supplier_id: +supOf(r), unit_cost: costOf(r) })) } });
    st.picked = {}; st.qty = {};
    toast(`Órdenes creadas: ${res.orders.map((o) => o.number).join(", ")}. Recíbelas desde Proveedores cuando llegue la mercadería.`);
  });
}

/* ───────── nota de débito (módulo Notas de débito) ───────── */
function debitNoteForm(d) {
  openModal(`Nota de débito sobre la factura ${d.number}`, [
    { type: "info", html: `Un cargo adicional a <strong>${esc(d.client)}</strong>: intereses por mora, flete, ajuste de precio... Aumenta lo que debe esta factura (saldo actual ${money(d.balance)}) y no mueve el inventario.` },
    { name: "concept", label: "Concepto del cargo", required: true, full: true, placeholder: "Intereses por mora, flete, ajuste de precio..." },
    { name: "amount", label: "Monto (sin ISV)", type: "number", step: "0.01", min: "0.01", required: true },
    { name: "tax", label: "Impuesto", type: "select", value: "exento", options: [{ value: "exento", label: "Exento" }, { value: "gravado15", label: "Gravado 15%" }, { value: "gravado18", label: "Gravado 18%" }] },
    { name: "notes", label: "Notas", full: true },
  ], async (b) => {
    const saved = await api("/api/documents", { method: "POST", body: { kind: "debito", client_id: d.client_id, warehouse_id: d.warehouse_id, ref_document_id: d.id, notes: b.notes || "",
      items: [{ description: b.concept, qty: 1, price: num(b.amount), tax_treatment: b.tax }] } });
    toast(`${saved.kind_label} ${saved.number} emitida`);
    safePrint(printDoc, saved.id);
  });
}
