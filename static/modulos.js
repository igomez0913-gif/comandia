/* Módulos adicionales de la v3.1: reabastecimiento y órdenes de compra, guías de remisión. */

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

/* ───────── nota de débito (módulo Notas de débito y guías de remisión) ───────── */
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

/* ───────── guías de remisión ───────── */
const REMISSION_REASONS = ["Venta", "Traslado entre bodegas o tiendas", "Devolución", "Consignación", "Otro"];

async function printRemission(id) {
  const r = await api("/api/remissions/" + id);
  const c = r.company || {};
  const fd = (v) => (v ? dateOnly(v) : "—");
  const rows = r.items.map((i) => `<tr><td>${esc(i.description)}</td><td class="r">${i.qty}</td><td>${esc(i.unit)}</td></tr>`).join("");
  await printHtml(`<!doctype html><html><head><meta charset="utf-8"><title>Guía de remisión ${esc(r.number)}</title><style>
    @page { size: letter; margin: 12mm; } body { font-family: Arial, Helvetica, sans-serif; font-size: 12px; color: #111; }
    .top { display: flex; justify-content: space-between; gap: 16px; } h1 { font-size: 20px; margin: 0; } .box { border: 1.5px solid #333; border-radius: 6px; padding: 8px 10px; }
    .num { text-align: center; min-width: 210px; } .num b { font-size: 16px; } .muted { color: #555; } .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; }
    table { width: 100%; border-collapse: collapse; margin-top: 12px; } th { background: #eee; text-align: left; } th, td { border: 1px solid #888; padding: 5px 7px; } .r { text-align: right; }
    .sig { display: flex; gap: 36px; margin-top: 56px; } .sig div { flex: 1; border-top: 1px solid #333; padding-top: 4px; text-align: center; }
    .void { color: #b42318; font-size: 26px; font-weight: 700; border: 3px solid #b42318; display: inline-block; padding: 2px 12px; transform: rotate(-6deg); margin-top: 8px; }
    .legend { text-align: center; font-style: italic; margin-top: 14px; font-size: 11px; }
  </style></head><body>
    <div class="top"><div>${c.logo ? `<img src="${esc(c.logo)}" alt="" style="max-height:60px;max-width:180px"><br>` : ""}<h1>${esc(c.name || "")}</h1><div class="muted">${esc(c.legal_name || "")}<br>RTN ${esc(c.rtn || "")}<br>${esc(c.address || "")}${c.phone ? `<br>Tel. ${esc(c.phone)}` : ""}</div></div>
      <div class="box num"><div class="muted">GUÍA DE REMISIÓN</div><b>${esc(r.number)}</b><div class="muted" style="margin-top:6px">CAI ${esc(r.cai)}<br>Rango ${esc(r.range_label)}<br>Fecha límite de emisión ${fd(r.limit_date)}${r.cai_received ? `<br>Recepción ${fd(r.cai_received)}` : ""}</div></div></div>
    ${r.status === "Anulada" ? `<div class="void">ANULADA</div>` : ""}
    <div class="grid"><div class="box"><b>Remitente</b><br>${esc(c.name || "")}<br>RTN ${esc(c.rtn || "")}<br><span class="muted">Punto de partida:</span> ${esc(r.origin || "—")}</div>
      <div class="box"><b>Destinatario</b><br>${esc(r.recipient_name)}<br>RTN ${esc(r.recipient_rtn || "—")}<br><span class="muted">Punto de llegada:</span> ${esc(r.destination)}</div></div>
    <div class="grid"><div class="box"><b>Traslado</b><br>Motivo: ${esc(r.reason)}<br>Fecha de inicio: ${fd(r.transfer_date)}${r.ref_number ? `<br>Factura: ${esc(r.ref_number)}` : ""}</div>
      <div class="box"><b>Transporte</b><br>${esc(r.carrier_name || "—")}${r.carrier_rtn ? ` · RTN ${esc(r.carrier_rtn)}` : ""}<br>Vehículo: ${esc(r.vehicle || "—")} · Placa ${esc(r.plate || "—")}<br>Conductor: ${esc(r.driver_name || "—")}${r.driver_id ? ` · ${esc(r.driver_id)}` : ""}</div></div>
    <table><thead><tr><th>Descripción de la mercadería</th><th class="r">Cantidad</th><th>Unidad</th></tr></thead><tbody>${rows}</tbody></table>
    ${r.notes ? `<p class="muted">${esc(r.notes)}</p>` : ""}
    <div class="sig"><div>Entregó (remitente)</div><div>Transportista / conductor</div><div>Recibí conforme</div></div>
    <div class="legend">${esc(LEGEND)}</div></body></html>`);
}

async function remissionForm() {
  const [invoices, whs] = await Promise.all([api("/api/documents?kind=factura"), api("/api/warehouses")]);
  const open = invoices.filter((x) => x.status !== "Anulada").slice(0, 100);
  const lines = [{ description: "", unit: "und", qty: 1 }];
  const html = `<label class="full">Factura que se entrega (opcional: llena los datos y la mercadería)<select name="ref_document_id"><option value="">Sin factura</option>${open.map((x) => `<option value="${x.id}">${esc(x.number)} · ${esc(x.client)} · ${money(x.total)}</option>`).join("")}</select></label>
    ${fieldHtml({ name: "recipient_name", label: "Destinatario", required: true })}${fieldHtml({ name: "recipient_rtn", label: "RTN del destinatario" })}
    <label>Motivo del traslado<select name="reason">${REMISSION_REASONS.map((m) => `<option>${esc(m)}</option>`).join("")}</select></label>
    <label>Bodega de origen<select name="warehouse_id">${whs.map((w) => `<option value="${w.id}">${esc(w.name)}</option>`).join("")}</select></label>
    ${fieldHtml({ name: "origin", label: "Punto de partida (vacío = dirección de la bodega)", full: true })}
    ${fieldHtml({ name: "destination", label: "Punto de llegada", required: true, full: true })}
    ${fieldHtml({ name: "transfer_date", label: "Fecha de inicio del traslado", type: "date", value: new Date().toISOString().slice(0, 10) })}
    ${fieldHtml({ name: "carrier_name", label: "Transportista" })}${fieldHtml({ name: "carrier_rtn", label: "RTN del transportista" })}
    ${fieldHtml({ name: "vehicle", label: "Vehículo" })}${fieldHtml({ name: "plate", label: "Placa" })}
    ${fieldHtml({ name: "driver_name", label: "Conductor" })}${fieldHtml({ name: "driver_id", label: "Identidad o licencia del conductor" })}
    <div class="full"><h4>Mercadería</h4><div id="rm-lines"></div><button type="button" class="btn sm" id="rm-add">+ Agregar línea</button></div>
    ${fieldHtml({ name: "notes", label: "Notas", type: "textarea", full: true })}`;
  openForm("Nueva guía de remisión", html, async (form) => {
    const f = Object.fromEntries(new FormData(form).entries());
    const items = lines.filter((l) => l.description.trim()).map((l) => ({ description: l.description.trim(), unit: l.unit || "und", qty: num(l.qty) || 1 }));
    if (!items.length) throw new Error("Agrega al menos una línea de mercadería");
    const saved = await api("/api/remissions", { method: "POST", body: { ...f, ref_document_id: f.ref_document_id ? +f.ref_document_id : null, warehouse_id: +f.warehouse_id, transfer_date: f.transfer_date || null, items } });
    toast(`Guía ${saved.number} emitida`);
    safePrint(printRemission, saved.id);
  }, { wide: true, submitLabel: "Emitir e imprimir guía", mount: (form) => {
    const paint = () => {
      $("#rm-lines", form).innerHTML = lines.map((l, i) => `<div class="line-row" style="display:grid;grid-template-columns:1fr 90px 90px 32px;gap:6px;margin-bottom:6px">
        <input data-l="${i}" data-k="description" placeholder="Descripción" value="${esc(l.description)}" /><input data-l="${i}" data-k="qty" type="number" min="0.01" step="0.01" value="${l.qty}" aria-label="Cantidad" />
        <input data-l="${i}" data-k="unit" value="${esc(l.unit)}" aria-label="Unidad" /><button type="button" class="btn ghost sm" data-rm="${i}" aria-label="Quitar">✕</button></div>`).join("");
      $$("[data-l]", form).forEach((el) => el.oninput = () => { lines[+el.dataset.l][el.dataset.k] = el.value; });
      $$("[data-rm]", form).forEach((el) => el.onclick = () => { if (lines.length > 1) { lines.splice(+el.dataset.rm, 1); paint(); } });
    };
    paint();
    $("#rm-add", form).onclick = () => { lines.push({ description: "", unit: "und", qty: 1 }); paint(); };
    $("[name=ref_document_id]", form).onchange = async (e) => {
      if (!e.target.value) return;
      const { document: d } = await api("/api/documents/" + e.target.value);
      $("[name=recipient_name]", form).value = d.client; $("[name=recipient_rtn]", form).value = d.rtn || ""; $("[name=destination]", form).value = d.client_address || $("[name=destination]", form).value;
      lines.splice(0, lines.length, ...d.items.map((i) => ({ description: i.description, unit: i.unit, qty: i.qty })));
      paint();
    };
  } });
}

async function renderRemissions(root) {
  let rows;
  try { rows = await api("/api/remissions"); }
  catch (err) { root.innerHTML = `<div class="section-head"><h2>Guías de remisión</h2></div><div class="card"><p class="muted">${esc(err.message)}</p></div>`; return; }
  root.innerHTML = `<div class="section-head"><h2>Guías de remisión</h2><div class="actions"><button class="btn primary" id="rm-new">Nueva guía de remisión</button></div></div>
    <p class="muted">Documento que acompaña la mercadería durante el traslado (ventas con entrega, traslados entre bodegas o tiendas). Usa su propio CAI y numeración: cárgalo en Configuración › CAI con el documento «Guía de remisión». No mueve el inventario.</p>
    <div class="card">${table(["GUÍA", "FECHA", "DESTINATARIO", "DESTINO", "MOTIVO", "FACTURA", "ESTADO", ""], rows.map((r) => `<tr><td class="nowrap">${esc(r.number)}</td><td class="nowrap">${when(r.issued_at)}</td><td>${esc(r.recipient_name)}</td><td>${esc(r.destination)}</td>
      <td>${esc(r.reason)}</td><td>${esc(r.ref_number || "—")}</td><td>${pill(r.status === "Emitida" ? "Activo" : "Anulada")}</td>
      <td class="row-actions"><button class="btn sm" data-rprint="${r.id}">Imprimir</button>${can("anular") && r.status === "Emitida" ? `<button class="btn danger sm" data-rvoid="${r.id}">Anular</button>` : ""}</td></tr>`), "Aún no hay guías de remisión")}</div>`;
  $("#rm-new").onclick = () => remissionForm();
  $$("[data-rprint]").forEach((b) => b.onclick = () => safePrint(printRemission, +b.dataset.rprint));
  $$("[data-rvoid]").forEach((b) => b.onclick = async () => { if (await askConfirm("¿Anular esta guía? El número queda registrado como anulado.", "Anular", true)) run(() => api(`/api/remissions/${b.dataset.rvoid}/void`, { method: "POST" }), "Guía anulada"); });
}


/* ───────── libro de ventas diario: impresión (carta horizontal) ───────── */
async function printDailyBook(book) {
  const e = book.empresa, t = book.totales, n = (v) => money(v);
  const rows = book.dias.map((r) => `<tr><td>${esc(r.fecha)}</td><td>${esc(r.tipo)}</td><td>${esc(r.serie)}</td><td class="m">${esc(r.desde)}</td><td class="m">${esc(r.hasta)}</td><td class="r">${r.documentos}</td>
    <td class="r">${r.anuladas.length || "—"}</td><td class="r">${n(r.exento)}</td><td class="r">${n(r.exonerado)}</td><td class="r">${n(r.gravado_15)}</td><td class="r">${n(r.isv_15)}</td><td class="r">${n(r.gravado_18)}</td><td class="r">${n(r.isv_18)}</td><td class="r">${n(r.descuento)}</td><td class="r"><b>${n(r.total)}</b></td></tr>
    ${r.anuladas.length ? `<tr class="sub"><td></td><td colspan="14">Anuladas: ${esc(r.anuladas.join(", "))}</td></tr>` : ""}${r.saltos_total ? `<tr class="sub warn"><td></td><td colspan="14">Faltan en la secuencia: ${esc(r.saltos.join(", "))}${r.saltos_total > r.saltos.length ? "…" : ""}</td></tr>` : ""}`).join("");
  const tot = (label, x, strong) => `<tr class="${strong ? "grand" : "tot"}"><td colspan="5">${label}</td><td class="r">${x.documentos}</td><td class="r">${x.anuladas}</td><td class="r">${n(x.exento)}</td><td class="r">${n(x.exonerado)}</td><td class="r">${n(x.gravado_15)}</td><td class="r">${n(x.isv_15)}</td><td class="r">${n(x.gravado_18)}</td><td class="r">${n(x.isv_18)}</td><td class="r">${n(x.descuento)}</td><td class="r">${n(x.total)}</td></tr>`;
  await printHtml(`<!doctype html><html><head><meta charset="utf-8"><title>Libro de ventas ${esc(book.desde)} al ${esc(book.hasta)}</title><style>
    @page { size: letter landscape; margin: 10mm; } body { font-family: Arial, Helvetica, sans-serif; font-size: 9.5px; color: #111; }
    h1 { font-size: 15px; margin: 0; } h2 { font-size: 12px; margin: 2px 0 6px; } .muted { color: #444; } table { width: 100%; border-collapse: collapse; margin-top: 8px; }
    th { background: #e8efe9; text-align: center; font-size: 8.5px; } th, td { border: 1px solid #888; padding: 2px 4px; } .r { text-align: right; white-space: nowrap; } .m { font-family: monospace; white-space: nowrap; }
    tr.sub td { border-top: 0; font-size: 8.5px; color: #333; } tr.warn td { color: #b42318; font-weight: 700; } tr.tot td { background: #f3f3f3; font-weight: 700; } tr.grand td { background: #dfeadf; font-weight: 800; font-size: 10.5px; }
    thead { display: table-header-group; } tr { page-break-inside: avoid; } .sig { display: flex; gap: 60px; margin-top: 36px; } .sig div { flex: 1; border-top: 1px solid #333; padding-top: 3px; text-align: center; }
  </style></head><body>
    <h1>${esc(e.nombre)}</h1><div class="muted">${esc(e.razon_social || "")} · RTN ${esc(e.rtn || "")} · ${esc(e.direccion || "")}</div>
    <h2>LIBRO DE VENTAS · RESUMEN DIARIO — del ${dateOnly(book.desde)} al ${dateOnly(book.hasta)} · Serie: ${esc(book.serie)}</h2>
    ${book.cai.map((c) => `<div class="muted">CAI ${esc(c.cai)} · ${esc(c.documento)} · rango autorizado ${esc(c.rango)} · fecha límite de emisión ${c.limite ? dateOnly(c.limite) : "—"}</div>`).join("")}
    <table><thead><tr><th>Fecha</th><th>Documento</th><th>Serie</th><th>Número inicial</th><th>Número final</th><th>Docs.</th><th>Anul.</th><th>Importe exento</th><th>Importe exonerado</th><th>Gravado 15%</th><th>ISV 15%</th><th>Gravado 18%</th><th>ISV 18%</th><th>Descuentos y rebajas</th><th>Total</th></tr></thead>
    <tbody>${rows}${tot("TOTAL FACTURAS", t.facturas)}${tot("TOTAL NOTAS DE DÉBITO", t.debitos)}${tot("TOTAL NOTAS DE CRÉDITO", t.creditos)}${tot("VENTAS NETAS", t.netas, true)}</tbody></table>
    <p class="muted">Importes en lempiras. Las notas de crédito restan; los documentos anulados se cuentan en la secuencia pero no suman importes.</p>
    <div class="sig"><div>Elaborado por</div><div>Revisado por</div><div>Contador / Representante legal</div></div></body></html>`);
}
