/* Etiquetas y códigos de barras (módulo adicional): arma e imprime hojas de etiquetas con código Code 128. */

// Code 128: cada símbolo son 11 módulos (1 = barra, 0 = espacio); el 106 es la parada. Se usa el juego B (ASCII 32–126).
const CODE128 = ["11011001100", "11001101100", "11001100110", "10010011000", "10010001100", "10001001100", "10011001000", "10011000100", "10001100100", "11001001000", "11001000100", "11000100100", "10110011100", "10011011100", "10011001110", "10111001100", "10011101100", "10011100110", "11001110010", "11001011100", "11001001110", "11011100100", "11001110100", "11101101110", "11101001100", "11100101100", "11100100110", "11101100100", "11100110100", "11100110010", "11011011000", "11011000110", "11000110110", "10100011000", "10001011000", "10001000110", "10110001000", "10001101000", "10001100010", "11010001000", "11000101000", "11000100010", "10110111000", "10110001110", "10001101110", "10111011000", "10111000110", "10001110110", "11101110110", "11010001110", "11000101110", "11011101000", "11011100010", "11011101110", "11101011000", "11101000110", "11100010110", "11101101000", "11101100010", "11100011010", "11101111010", "11001000010", "11110001010", "10100110000", "10100001100", "10010110000", "10010000110", "10000101100", "10000100110", "10110010000", "10110000100", "10011010000", "10011000010", "10000110100", "10000110010", "11000010010", "11001010000", "11110111010", "11000010100", "10001111010", "10100111100", "10010111100", "10010011110", "10111100100", "10011110100", "10011110010", "11110100100", "11110010100", "11110010010", "11011011110", "11011110110", "11110110110", "10101111000", "10100011110", "10001011110", "10111101000", "10111100010", "11110101000", "11110100010", "10111011110", "10111101110", "11101011110", "11110101110", "11010000100", "11010010000", "11010011100"];
const CODE128_STOP = "1100011101011";

function code128Svg(text, height = 38) {
  const clean = String(text || "").replace(/[^\x20-\x7e]/g, "?");
  if (!clean) return "";
  const values = [104, ...[...clean].map((ch) => ch.charCodeAt(0) - 32)];
  const check = values.reduce((sum, v, i) => sum + v * (i || 1), 0) % 103;
  const bits = [...values, check].map((v) => CODE128[v]).join("") + CODE128_STOP;
  const quiet = 10;
  let x = quiet, bars = "";
  for (let i = 0; i < bits.length;) {
    let j = i; while (j < bits.length && bits[j] === bits[i]) j++;
    if (bits[i] === "1") bars += `<rect x="${x}" y="0" width="${j - i}" height="${height}"/>`;
    x += j - i; i = j;
  }
  const width = x + quiet;
  return `<svg class="bc" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" shape-rendering="crispEdges" role="img" aria-label="Código de barras ${esc(clean)}"><rect width="${width}" height="${height}" fill="#fff"/><g fill="#000">${bars}</g></svg>`;
}

const LABEL_SIZES = {
  s: { name: "Pequeña 50 × 25 mm", w: 50, h: 25, font: 8, price: 13 },
  m: { name: "Mediana 66 × 38 mm", w: 66, h: 38, font: 10, price: 17 },
  l: { name: "Grande 100 × 50 mm", w: 100, h: 50, font: 13, price: 24 },
};
const labelState = { q: "", copies: {}, size: "s", level: 0, showCompany: false, onlyCoded: false };

function labelOffers(products) {
  const out = [];
  products.forEach((p) => {
    const list = p.presentations.length ? p.presentations : [{ id: 0, name: "", unit: p.base_unit, barcode: "", prices: p.prices }];
    list.forEach((pr) => out.push({
      key: `${p.id}:${pr.id}`, sku: p.sku, name: p.name, present: pr.name || "", unit: pr.unit || p.base_unit, barcode: (pr.barcode || "").trim(),
      prices: pr.prices || p.prices, stock: p.stock, low: p.low,
    }));
  });
  return out;
}

function labelsHtml(offers, st, companyName) {
  const size = LABEL_SIZES[st.size];
  const cells = [];
  offers.forEach((o) => {
    const n = Math.min(Math.max(Math.floor(+st.copies[o.key] || 0), 0), 500);
    const code = o.barcode || o.sku;
    const price = st.level > 0 ? o.prices[st.level - 1] : null;
    for (let i = 0; i < n; i++) cells.push(`<div class="lb">
      ${st.showCompany ? `<div class="co">${esc(companyName)}</div>` : ""}
      <div class="nm">${esc(o.name)}${o.present ? ` <small>${esc(o.present)}</small>` : ""}</div>
      ${price !== null ? `<div class="pr">L ${money(price)}</div>` : ""}
      <div class="bw">${code128Svg(code)}</div><div class="cd">${esc(code)}</div></div>`);
  });
  return `<!doctype html><html><head><meta charset="utf-8"><title>Etiquetas</title><style>
    @page { size: letter; margin: 8mm; }
    body { margin: 0; font-family: Arial, Helvetica, sans-serif; color: #000; }
    .sheet { display: flex; flex-wrap: wrap; gap: 2mm; align-content: flex-start; }
    .lb { width: ${size.w}mm; height: ${size.h}mm; box-sizing: border-box; border: .2mm dashed #bbb; padding: 1.2mm 1.6mm; overflow: hidden; display: flex; flex-direction: column; justify-content: space-between; page-break-inside: avoid; }
    .co { font-size: ${size.font - 2}px; text-transform: uppercase; letter-spacing: .04em; color: #333; }
    .nm { font-size: ${size.font}px; font-weight: 700; line-height: 1.12; max-height: ${size.font * 2.3}px; overflow: hidden; }
    .nm small { font-weight: 400; }
    .pr { font-size: ${size.price}px; font-weight: 800; }
    .bw { flex: 1; min-height: 0; display: flex; }
    .bc { width: 100%; height: 100%; max-height: ${Math.round(size.h * 0.38)}mm; }
    .cd { font-size: ${size.font - 1}px; text-align: center; letter-spacing: .08em; }
    @media print { .lb { border-color: transparent; } }
  </style></head><body><div class="sheet">${cells.join("")}</div></body></html>`;
}

async function renderLabels(root) {
  let products;
  try { products = await api("/api/labels/products"); }
  catch (err) { root.innerHTML = `<div class="section-head"><h2>Etiquetas y códigos de barras</h2></div><div class="card"><p class="muted">${esc(err.message)}</p></div>`; return; }
  const offers = labelOffers(products);
  const company = ($("#co-name") || {}).textContent || "";
  const st = labelState;
  const shown = () => {
    const q = st.q.trim().toLowerCase();
    return offers.filter((o) => (!st.onlyCoded || o.barcode) && (!q || `${o.sku} ${o.name} ${o.present} ${o.barcode}`.toLowerCase().includes(q)));
  };
  const total = () => offers.reduce((s, o) => s + Math.min(Math.max(Math.floor(+st.copies[o.key] || 0), 0), 500), 0);
  root.innerHTML = `<div class="section-head"><h2>Etiquetas y códigos de barras</h2><div class="actions"><button class="btn" id="lb-low">Pedir 1 por producto con stock bajo</button><button class="btn" id="lb-clear">Limpiar</button><button class="btn primary" id="lb-print">Imprimir etiquetas (<span id="lb-total">0</span>)</button></div></div>
    <p class="muted">Escribe cuántas etiquetas quieres de cada producto. Si la presentación tiene código de barras se usa ese; si no, se usa el SKU. Se imprimen en hoja carta (con la impresora de etiquetas, elige el tamaño de papel en el diálogo de impresión).</p>
    <div class="toolbar"><input id="lb-q" placeholder="Buscar por SKU, nombre o código" value="${esc(st.q)}" />
      <select id="lb-size">${Object.entries(LABEL_SIZES).map(([k, v]) => `<option value="${k}">${esc(v.name)}</option>`).join("")}</select>
      <select id="lb-level"><option value="0">Sin precio</option>${[1, 2, 3, 4].map((n) => `<option value="${n}">Con ${esc(priceNames[n - 1] || "Precio " + n)}</option>`).join("")}</select>
      <label class="check"><input type="checkbox" id="lb-co" ${st.showCompany ? "checked" : ""} /> Nombre de la empresa</label>
      <label class="check"><input type="checkbox" id="lb-coded" ${st.onlyCoded ? "checked" : ""} /> Solo con código de barras</label></div>
    <div class="card" id="lb-list"></div>`;
  $("#lb-size").value = st.size; $("#lb-level").value = String(st.level);
  const paint = () => {
    const rows = shown().slice(0, 300);
    $("#lb-list").innerHTML = table(["SKU", "PRODUCTO", "CÓDIGO", "PRECIO", "ETIQUETAS"], rows.map((o) => `<tr><td>${esc(o.sku)}</td><td>${esc(o.name)}${o.present ? ` <span class="muted">· ${esc(o.present)}</span>` : ""}</td>
      <td class="nowrap">${o.barcode ? esc(o.barcode) : `<span class="muted">${esc(o.sku)} (SKU)</span>`}</td><td class="nowrap">${money(o.prices[Math.max(st.level, 1) - 1])}</td>
      <td><input type="number" min="0" max="500" step="1" class="qty-in" data-copies="${esc(o.key)}" value="${st.copies[o.key] || ""}" placeholder="0" /></td></tr>`), "Sin productos con ese filtro") + (shown().length > 300 ? `<p class="muted">Se muestran 300; afina la búsqueda para ver el resto.</p>` : "");
    $$("[data-copies]").forEach((i) => i.oninput = () => { st.copies[i.dataset.copies] = i.value; $("#lb-total").textContent = total(); });
    $("#lb-total").textContent = total();
  };
  paint();
  let t; $("#lb-q").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { st.q = e.target.value; paint(); }, 200); };
  $("#lb-size").onchange = (e) => { st.size = e.target.value; };
  $("#lb-level").onchange = (e) => { st.level = +e.target.value; paint(); };
  $("#lb-co").onchange = (e) => { st.showCompany = e.target.checked; };
  $("#lb-coded").onchange = (e) => { st.onlyCoded = e.target.checked; paint(); };
  $("#lb-clear").onclick = () => { st.copies = {}; paint(); };
  $("#lb-low").onclick = () => { offers.filter((o) => o.low).forEach((o) => { if (!st.copies[o.key]) st.copies[o.key] = "1"; }); paint(); };
  $("#lb-print").onclick = async () => {
    if (!total()) { toast("Escribe cuántas etiquetas quieres de al menos un producto", "err"); return; }
    await printHtml(labelsHtml(offers.filter((o) => +st.copies[o.key] > 0), st, company));
  };
}
