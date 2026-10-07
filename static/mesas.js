/* Comandia · dibujo de mesas con sillas. Cada mesa se dibuja en SVG según su forma y su número de lugares: sirve para el salón, el diseñador y el catálogo. */

/** Catálogo de mesas y adornos del diseñador. Los tamaños ya incluyen el espacio de las sillas. */
const TABLE_PRESETS = [
  { id: "mesa2", label: "Mesa 2 personas", kind: "mesa", shape: "cuadrada", seats: 2, w: 96, h: 110, info: "Cuadrada para parejas; se junta con otra para grupos." },
  { id: "mesa4", label: "Mesa 4 personas", kind: "mesa", shape: "cuadrada", seats: 4, w: 120, h: 120, info: "La más usada en cualquier restaurante." },
  { id: "redonda4", label: "Redonda 4", kind: "mesa", shape: "redonda", seats: 4, w: 120, h: 120, info: "Redonda pequeña: más cómoda para conversar." },
  { id: "redonda6", label: "Redonda 6", kind: "mesa", shape: "redonda", seats: 6, w: 150, h: 150, info: "Familias y grupos; muy común en restaurantes de comida compartida." },
  { id: "redonda8", label: "Redonda 8", kind: "mesa", shape: "redonda", seats: 8, w: 180, h: 180, info: "Banquetes y celebraciones." },
  { id: "rect6", label: "Rectangular 6", kind: "mesa", shape: "rectangular", seats: 6, w: 190, h: 120, info: "Grupos medianos; se alarga uniendo mesas." },
  { id: "rect8", label: "Rectangular 8", kind: "mesa", shape: "rectangular", seats: 8, w: 250, h: 120, info: "Grupos grandes y reuniones de trabajo." },
  { id: "oval8", label: "Ovalada 8", kind: "mesa", shape: "ovalada", seats: 8, w: 230, h: 140, info: "Banquetes y salas privadas." },
  { id: "cabina4", label: "Cabina 4", kind: "mesa", shape: "cabina", seats: 4, w: 190, h: 120, info: "Sofás enfrentados contra la pared: cafeterías, diners y comida rápida." },
  { id: "cabina6", label: "Cabina 6", kind: "mesa", shape: "cabina", seats: 6, w: 250, h: 120, info: "Cabina larga para grupos." },
  { id: "alta2", label: "Mesa alta 2", kind: "mesa", shape: "alta", seats: 2, w: 90, h: 90, info: "Mesa de coctel con bancos altos: bares, terrazas y esperas." },
  { id: "alta4", label: "Mesa alta 4", kind: "mesa", shape: "alta", seats: 4, w: 110, h: 110, info: "Mesa alta para cuatro." },
  { id: "barra6", label: "Barra 6 bancos", kind: "mesa", shape: "barra", seats: 6, w: 320, h: 90, info: "Cuentas de barra: bares, cafés y cocina a la vista." },
  { id: "barra4", label: "Barra 4 bancos", kind: "mesa", shape: "barra", seats: 4, w: 220, h: 90, info: "Barra corta." },
  { id: "planta", label: "Planta", kind: "planta", shape: "redonda", seats: 0, w: 64, h: 64, info: "Adorno." },
  { id: "puerta", label: "Puerta", kind: "puerta", shape: "rectangular", seats: 0, w: 90, h: 90, info: "Entrada o salida." },
  { id: "sofa", label: "Sofá", kind: "mobiliario", shape: "sofa", seats: 0, w: 190, h: 80, info: "Zona de espera o lounge (sin cuenta)." },
  { id: "mueble", label: "Mueble / estante", kind: "mobiliario", shape: "rectangular", seats: 0, w: 200, h: 50, info: "Mostrador, estante, caja o estación de servicio." },
  { id: "pared", label: "Pared", kind: "pared", shape: "rectangular", seats: 0, w: 300, h: 12, info: "Divisiones y muros." },
  { id: "piso", label: "Piso / alfombra", kind: "piso", shape: "rectangular", seats: 0, w: 220, h: 220, info: "Zona con otro piso (terraza, tarima)." },
];
const SHAPE_LABEL = { cuadrada: "Cuadrada", redonda: "Redonda", rectangular: "Rectangular", ovalada: "Ovalada", cabina: "Cabina", barra: "Barra", alta: "Mesa alta", sofa: "Sofá" };

const _r = (n) => Math.round(n * 10) / 10;
const _clamp = (v, a, b) => Math.max(a, Math.min(b, v));

/** Una silla centrada en (x, y) mirando hacia +y local; `rot` la gira. El respaldo es la franja oscura. */
function _chair(x, y, rot, cs, cd) {
  return `<g transform="translate(${_r(x)} ${_r(y)}) rotate(${_r(rot)})"><rect class="t-chair" x="${_r(-cs / 2)}" y="${_r(-cd / 2)}" width="${_r(cs)}" height="${_r(cd)}" rx="${_r(cs * 0.28)}"/>`
    + `<rect class="t-back" x="${_r(-cs / 2 + 1)}" y="${_r(-cd / 2)}" width="${_r(cs - 2)}" height="${_r(cd * 0.3)}" rx="2"/></g>`;
}
function _stool(x, y, r) { return `<circle class="t-chair" cx="${_r(x)}" cy="${_r(y)}" r="${_r(r)}"/><circle class="t-back" cx="${_r(x)}" cy="${_r(y)}" r="${_r(r * 0.45)}"/>`; }

/** Cuántas sillas van en cada lado de una mesa cuadrada o rectangular. */
function _sideCounts(shape, seats, w, h) {
  const out = { top: 0, bottom: 0, left: 0, right: 0 };
  if (shape === "cuadrada") {
    const base = Math.floor(seats / 4), rem = seats % 4;
    ["top", "bottom", "left", "right"].forEach((k, i) => { out[k] = base + (i < rem ? 1 : 0); });
    return out;
  }
  const horizontal = w >= h;
  const [a, b, e1, e2] = horizontal ? ["top", "bottom", "left", "right"] : ["left", "right", "top", "bottom"];
  const ends = seats >= 6 ? 1 : 0, rest = seats - 2 * ends;
  out[e1] = ends; out[e2] = ends; out[a] = Math.ceil(rest / 2); out[b] = Math.floor(rest / 2);
  return out;
}

/** SVG de una mesa (con sillas) dentro de un cuadro w × h. */
function tableSvg(shape, w, h, seats) {
  seats = _clamp(+seats || 0, 0, 24);
  const cs = _clamp(Math.min(w, h) * 0.2, 12, 26), cd = cs * 0.8, m = cd + 5;  // tamaño de silla y margen que ocupa
  const open = (inner) => `<svg class="tsvg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" aria-hidden="true">${inner}</svg>`;
  let g = "";
  if (shape === "redonda" || shape === "alta") {
    const R = Math.min(w, h) / 2, stool = shape === "alta", cdd = stool ? cs * 0.5 : cd;
    const rt = Math.max(8, R - (stool ? cs * 0.5 * 2 : cd) - 5), rc = rt + (stool ? cs * 0.5 + 3 : cd / 2 + 2);
    g += `<circle class="t-top" cx="${w / 2}" cy="${h / 2}" r="${_r(rt)}"/>`;
    for (let i = 0; i < seats; i++) {
      const th = -90 + (360 * i) / seats, rad = (th * Math.PI) / 180, x = w / 2 + rc * Math.cos(rad), y = h / 2 + rc * Math.sin(rad);
      g += stool ? _stool(x, y, cs * 0.5) : _chair(x, y, th + 90, cs, cdd);
    }
  } else if (shape === "ovalada") {
    const rx = w / 2 - m, ry = h / 2 - m;
    g += `<ellipse class="t-top" cx="${w / 2}" cy="${h / 2}" rx="${_r(rx)}" ry="${_r(ry)}"/>`;
    for (let i = 0; i < seats; i++) {
      const t = ((-90 + (360 * i) / seats) * Math.PI) / 180, nx = Math.cos(t) / rx, ny = Math.sin(t) / ry, nl = Math.hypot(nx, ny);
      const ux = nx / nl, uy = ny / nl, x = w / 2 + (rx + cd / 2 + 2) * Math.cos(t), y = h / 2 + (ry + cd / 2 + 2) * Math.sin(t);
      g += _chair(x, y, (Math.atan2(uy, ux) * 180) / Math.PI + 90, cs, cd);
    }
  } else if (shape === "cabina") {
    const bh = Math.max(cd * 1.5, 20), top = Math.ceil(seats / 2), bottom = Math.floor(seats / 2), pad = 2;
    g += `<rect class="t-top" x="${pad + 4}" y="${pad + bh + 3}" width="${w - 2 * pad - 8}" height="${Math.max(10, h - 2 * pad - 2 * bh - 6)}" rx="6"/>`;
    const bench = (y0, count, back) => {
      let s = `<rect class="t-chair" x="${pad}" y="${y0}" width="${w - 2 * pad}" height="${bh}" rx="7"/><rect class="t-back" x="${pad + 2}" y="${back ? y0 : y0 + bh * 0.7}" width="${w - 2 * pad - 4}" height="${bh * 0.3}" rx="3"/>`;
      for (let i = 1; i < count; i++) { const x = pad + ((w - 2 * pad) * i) / count; s += `<line class="t-div" x1="${_r(x)}" y1="${y0 + 3}" x2="${_r(x)}" y2="${y0 + bh - 3}"/>`; }
      return s;
    };
    g += bench(pad, top, true) + bench(h - pad - bh, bottom, false);
  } else if (shape === "barra") {
    const ch = Math.max(h * 0.36, 22), r = _clamp(h * 0.17, 8, 14);
    g += `<rect class="t-top" x="2" y="2" width="${w - 4}" height="${_r(ch)}" rx="6"/>`;
    for (let i = 0; i < seats; i++) g += _stool(4 + r + ((w - 8 - 2 * r) * (i + 0.5)) / Math.max(seats, 1), ch + 6 + r, r);  // bancos pegados al mostrador y repartidos a lo largo
  } else if (shape === "sofa") {
    g += `<rect class="t-chair" x="2" y="2" width="${w - 4}" height="${h - 4}" rx="9"/><rect class="t-back" x="6" y="6" width="${w - 12}" height="${_r(h * 0.28)}" rx="6"/>`
      + `<rect class="t-back" x="3" y="${_r(h * 0.2)}" width="${_r(h * 0.2)}" height="${_r(h * 0.7)}" rx="6"/><rect class="t-back" x="${_r(w - 3 - h * 0.2)}" y="${_r(h * 0.2)}" width="${_r(h * 0.2)}" height="${_r(h * 0.7)}" rx="6"/>`;
  } else {  // cuadrada y rectangular
    const c = _sideCounts(shape, seats, w, h), pad = 2;
    const x0 = c.left ? m : pad + 3, y0 = c.top ? m : pad + 3, x1 = w - (c.right ? m : pad + 3), y1 = h - (c.bottom ? m : pad + 3);
    g += `<rect class="t-top" x="${_r(x0)}" y="${_r(y0)}" width="${_r(x1 - x0)}" height="${_r(y1 - y0)}" rx="${shape === "cuadrada" ? 8 : 10}"/>`;
    for (let i = 0; i < c.top; i++) g += _chair(x0 + ((x1 - x0) * (i + 0.5)) / c.top, m - 2 - cd / 2, 0, cs, cd);
    for (let i = 0; i < c.bottom; i++) g += _chair(x0 + ((x1 - x0) * (i + 0.5)) / c.bottom, h - m + 2 + cd / 2, 180, cs, cd);
    for (let i = 0; i < c.left; i++) g += _chair(m - 2 - cd / 2, y0 + ((y1 - y0) * (i + 0.5)) / c.left, 270, cs, cd);
    for (let i = 0; i < c.right; i++) g += _chair(w - m + 2 + cd / 2, y0 + ((y1 - y0) * (i + 0.5)) / c.right, 90, cs, cd);
  }
  return open(g);
}

/** Adornos con dibujo propio (planta con hojas, puerta con su giro); el resto se dibuja con CSS. */
function decorSvg(kind, shape, w, h) {
  if (kind === "planta") {
    const cx = w / 2, cy = h / 2, R = Math.min(w, h) / 2 - 2;
    let leaves = ""; for (let i = 0; i < 8; i++) leaves += `<ellipse class="t-leaf" cx="${_r(cx)}" cy="${_r(cy - R * 0.5)}" rx="${_r(R * 0.22)}" ry="${_r(R * 0.5)}" transform="rotate(${i * 45} ${_r(cx)} ${_r(cy)})"/>`;
    return `<svg class="tsvg" viewBox="0 0 ${w} ${h}" aria-hidden="true">${leaves}<circle class="t-pot" cx="${_r(cx)}" cy="${_r(cy)}" r="${_r(R * 0.18)}"/></svg>`;
  }
  if (kind === "puerta") {
    const s = Math.min(w, h) - 6;
    return `<svg class="tsvg" viewBox="0 0 ${w} ${h}" aria-hidden="true"><line class="t-door" x1="3" y1="3" x2="3" y2="${3 + s}"/><path class="t-swing" d="M3 3 L${3 + s} 3 A${s} ${s} 0 0 1 3 ${3 + s}" /></svg>`;
  }
  if (kind === "mobiliario" && shape === "sofa") return tableSvg("sofa", w, h, 0);
  return "";
}
