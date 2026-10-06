"""PDF de facturas, cotizaciones y notas de crédito (para enviar por correo o descargar).

Recibe el mismo diccionario que la API devuelve (doc_out) para que el PDF y la impresión del navegador muestren lo mismo.
Usa las fuentes base de PDF (Helvetica), que cubren el español; los pocos símbolos fuera de latin-1 se reemplazan.
"""
import os
from datetime import date, datetime

from fpdf import FPDF

LEGEND = "La factura es beneficio de todos, ¡Exíjala!"
TAX_LABEL = {"gravado15": "ISV 15%", "gravado18": "ISV 18%", "exento": "Exento", "exonerado": "Exonerado"}
GREEN = (19, 96, 58)
MUTED = (100, 112, 107)
LINE = (214, 222, 218)
_REPLACE = {"—": "-", "–": "-", "“": '"', "”": '"', "‘": "'", "’": "'", "…": "...", "•": "·", " ": " "}


def t(value) -> str:
    """Texto seguro para las fuentes base del PDF (latin-1)."""
    text = "" if value is None else str(value)
    for bad, good in _REPLACE.items():
        text = text.replace(bad, good)
    return text.encode("latin-1", "replace").decode("latin-1")


def money(value) -> str:
    return f"L {float(value or 0):,.2f}"


def fecha(value) -> str:
    if not value:
        return "-"
    try:
        if len(value) == 10:
            return date.fromisoformat(value).strftime("%d/%m/%Y")
        return datetime.fromisoformat(value).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return str(value)


class DocPDF(FPDF):
    def footer(self):
        self.set_y(-12)
        self.set_font("helvetica", "", 7)
        self.set_text_color(*MUTED)
        self.cell(0, 5, t(f"Página {self.page_no()}/{{nb}}"), align="R")


GRAY = (217, 217, 217)
INK = (17, 17, 17)
RED = (192, 38, 45)
TAX_MARK = {"gravado18": "18%", "exento": "E", "exonerado": "EXO"}
MARK_TEXT = {"18%": "18% = gravado con ISV 18%", "E": "E = exento", "EXO": "EXO = exonerado"}


def amt(value) -> str:
    return f"{float(value or 0):,.2f}"


def _logo(pdf, logo_file, x, y, max_w, max_h):
    """Dibuja el logo respetando su proporción. Devuelve el ancho usado (0 si no hay logo o está dañado)."""
    if not logo_file or not os.path.exists(logo_file):
        return 0
    try:
        from PIL import Image  # abre PNG, JPG y WEBP
        img = Image.open(logo_file)
        img.load()
        if img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGBA")
        h = max_h
        w = h * img.width / max(img.height, 1)
        if w > max_w:
            w, h = max_w, max_w * img.height / max(img.width, 1)
        pdf.image(img, x=x, y=y + (max_h - h) / 2, w=w, h=h)
        return w
    except Exception:  # noqa: BLE001 - un logo dañado no impide el PDF
        return 0


def _line_field(pdf, label, value, width, bold=True):
    """«Etiqueta: ____valor____» como en el talonario manual."""
    pdf.set_font("helvetica", "", 9)
    lw = pdf.get_string_width(t(label)) + 2
    pdf.cell(lw, 6, t(label))
    pdf.set_font("helvetica", "B" if bold else "", 9.5)
    x, y = pdf.get_x(), pdf.get_y()
    pdf.cell(width - lw, 6, t(value))
    pdf.line(x, y + 6, x + width - lw, y + 6)


def document_pdf(d: dict, company: dict, logo_file: str = "") -> bytes:
    """Factura, nota de crédito o cotización en carta, con el orden del talonario manual autorizado por el SAR."""
    fiscal = d.get("kind") != "cotizacion"
    pdf = DocPDF(format="Letter")
    pdf.set_margins(12, 10, 12)
    pdf.set_auto_page_break(True, 14)
    pdf.alias_nb_pages()
    pdf.add_page()
    L = pdf.l_margin
    width = pdf.w - pdf.l_margin - pdf.r_margin
    pdf.set_draw_color(51, 51, 51)
    pdf.set_text_color(*INK)

    # Encabezado: logo, emisor centrado y casilla DÍA / MES / AÑO.
    top = pdf.get_y()
    _logo(pdf, logo_file, L, top, 42, 24)
    date_w, mid_x = 42, L + 46
    mid_w = width - 46 - date_w - 4
    pdf.set_xy(mid_x, top)
    pdf.set_font("helvetica", "B", 18 if len(company.get("name") or "") <= 30 else 14)
    pdf.cell(mid_w, 8, t((company.get("name") or "").upper()), align="C", new_x="LEFT", new_y="NEXT")
    rows = []
    if company.get("legal_name"):
        rows.append(("B", company["legal_name"]))
    if company.get("address"):
        rows.append(("", company["address"]))
    contact = " • ".join(x for x in (f"E-mail: {company['email']}" if company.get("email") else "", f"Tel. {company['phone']}" if company.get("phone") else "") if x)
    if contact:
        rows.append(("", contact))
    rows.append(("B", f"R.T.N. {company.get('rtn', '')}"))
    for style, text in rows:
        pdf.set_font("helvetica", style, 8.5)
        pdf.set_x(mid_x)
        pdf.multi_cell(mid_w, 4, t(text), align="C", new_x="LEFT", new_y="NEXT")
    head_bottom = max(pdf.get_y(), top + 25)

    issued = None
    try:
        issued = datetime.fromisoformat(d["issued_at"]) if d.get("issued_at") else None
    except ValueError:
        issued = None
    dx = L + width - date_w
    pdf.set_xy(dx, top + 2)
    pdf.set_fill_color(*GRAY)
    pdf.set_font("helvetica", "B", 7)
    for label in ("DÍA", "MES", "AÑO"):
        pdf.cell(date_w / 3, 5, t(label), border=1, align="C", fill=True)
    pdf.set_xy(dx, top + 7)
    pdf.set_font("helvetica", "B", 11)
    for value in ((f"{issued.day:02d}", f"{issued.month:02d}", str(issued.year)) if issued else ("", "", "")):
        pdf.cell(date_w / 3, 8, value, border=1, align="C")
    pdf.set_y(head_bottom + 2)

    if d.get("status") in ("Anulada", "Cancelada"):
        pdf.set_font("helvetica", "B", 16)
        pdf.set_text_color(168, 37, 26)
        pdf.cell(0, 8, t(d["status"].upper()), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*INK)

    # Cliente, RTN y dirección sobre líneas, como en el talonario.
    y = pdf.get_y()
    _line_field(pdf, "Cliente:", d.get("client", ""), width - 62)
    pdf.set_xy(L + width - 60, y)
    _line_field(pdf, "R.T.N.", d.get("rtn") or "", 60)
    pdf.set_xy(L, y + 7)
    _line_field(pdf, "Dirección:", d.get("client_address") or "", width)
    pdf.set_xy(L, y + 14)
    extra = []
    if d.get("kind") in ("nota", "debito"):
        extra.append(f"Factura que modifica: {d.get('ref_number') or '-'}")
    elif d.get("kind") == "cotizacion":
        extra.append(f"Válida hasta: {fecha(d.get('validity_date') or d.get('due_date'))}")
    else:
        terms = d.get("payment_terms") or "Contado"
        extra.append(f"Condición: {terms}" + (f" · Vence: {fecha(d.get('due_date'))}" if d.get("due_date") and terms != "Contado" else ""))
    if d.get("client_ref") and d.get("kind") not in ("nota", "debito"):
        extra.append(f"Referencia: {d['client_ref']}")
    if d.get("series"):
        extra.append(f"Serie: {d['series']}")
    if issued:
        extra.append(f"Hora: {issued.strftime('%H:%M')}")
    if d.get("user"):
        extra.append(f"Atendido por: {d['user']}")
    pdf.set_font("helvetica", "", 8)
    pdf.multi_cell(width, 4.2, t(" · ".join(extra)), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)

    # Detalle: CANT. | DESCRIPCIÓN | P. UNIT. | DESCUENTOS Y REBAJAS | TOTAL
    cols = [("CANT.", 20, "C"), ("DESCRIPCIÓN", width - 106, "L"), ("P. UNIT.", 26, "R"), ("DESCUENTOS\nY REBAJAS", 28, "R"), ("TOTAL", 32, "R")]

    def table_head():
        pdf.set_font("helvetica", "B", 8)
        pdf.set_fill_color(*GRAY)
        x0, y0 = pdf.l_margin, pdf.get_y()
        for label, w, _align in cols:
            pdf.set_xy(x0, y0)
            if "\n" in label:
                pdf.set_font("helvetica", "B", 6.5)
                pdf.multi_cell(w, 3.5, t(label), border=1, align="C", fill=True)
                pdf.set_font("helvetica", "B", 8)
            else:
                pdf.cell(w, 7, t(label), border=1, align="C", fill=True)
            x0 += w
        pdf.set_xy(pdf.l_margin, y0 + 7)

    def row_cells(values, h, marks_line=False):
        x = pdf.l_margin
        y0 = pdf.get_y()
        for (label, w, align), value in zip(cols, values):
            pdf.set_xy(x, y0)
            if label == "DESCRIPCIÓN":
                pdf.multi_cell(w, 4.4, t(value), border=0, padding=(1, 1, 0.8, 1))
                pdf.rect(x, y0, w, h)
            else:
                pdf.cell(w, h, t(value), border=1, align=align)
            x += w
        pdf.set_xy(pdf.l_margin, y0 + h)

    table_head()
    pdf.set_font("helvetica", "", 8.5)
    marks = []
    items = d.get("items", [])
    for item in items:
        mark = TAX_MARK.get(item.get("tax_treatment"))
        if mark and mark not in marks:
            marks.append(mark)
        desc = (item.get("description") or "") + (f" ({mark})" if mark else "")
        lines = pdf.multi_cell(cols[1][1], 4.4, t(desc), dry_run=True, output="LINES", padding=(1, 1, 0.8, 1))
        h = max(6.0, 4.4 * max(1, len(lines)) + 1.8)
        if pdf.get_y() + h > pdf.page_break_trigger:
            pdf.add_page()
            table_head()
            pdf.set_font("helvetica", "", 8.5)
        qty = f"{float(item.get('qty') or 0):g} {item.get('unit') or ''}".strip()
        row_cells([qty, desc, amt(item.get("price")), amt(item.get("discount")) if item.get("discount") else "", amt(item.get("total"))], h)
    # Renglones vacíos como en el talonario, sin pasarse a otra hoja.
    footer_h = 74
    blanks = max(0, 12 - len(items))
    while blanks and pdf.get_y() + 6 + footer_h < pdf.page_break_trigger:
        row_cells(["", "", "", "", ""], 6)
        blanks -= 1
    if marks:
        pdf.set_font("helvetica", "", 7.5)
        pdf.cell(width, 4.5, t(" · ".join(MARK_TEXT[m] for m in marks)), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # Pie: adquirente exonerado, CAI y rango a la izquierda; tipo y número al centro; totales a la derecha.
    if pdf.get_y() + footer_h > pdf.page_break_trigger:
        pdf.add_page()
    fy = pdf.get_y()
    tot_w, num_w = 66, 46
    left_w = width - tot_w - num_w - 6
    tx = L + width - tot_w
    totals = [("Descuentos y Rebajas L.", d.get("discount"))] if d.get("discount") else []
    totals += [("Importe Exonerado L.", d.get("exonerado")), ("Importe Exento L.", d.get("exento")), ("Importe Gravado 15% L.", d.get("gravado_15")),
              ("Importe Gravado 18% L.", d.get("gravado_18")), ("15% I.S.V. L.", d.get("isv_15")), ("18% I.S.V. L.", d.get("isv_18")),
              ("TOTAL NOTA L." if d.get("kind") in ("nota", "debito") else "TOTAL A PAGAR L.", d.get("total"))]
    pdf.set_fill_color(*GRAY)
    for i, (label, value) in enumerate(totals):
        last = i == len(totals) - 1
        pdf.set_xy(tx, fy + i * 7)
        pdf.set_font("helvetica", "B" if last else "", 8.5 if last else 7.5)
        pdf.cell(38, 7, t(label), border=1, align="R", fill=True)
        pdf.set_font("helvetica", "B", 9.5 if last else 8.5)
        pdf.cell(tot_w - 38, 7, amt(value), border=1, align="R")

    pdf.set_xy(L + left_w + 3, fy + 18)
    pdf.set_font("helvetica", "B", 15 if len(d.get("kind_label", "")) <= 10 else 11)
    pdf.cell(num_w, 7, t((d.get("kind_label") or "").upper()), align="C", new_x="LEFT", new_y="NEXT")
    number = d.get("number") or ""
    cut = number.rfind("-")
    if fiscal and cut > 0:
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(num_w, 6, t(number[:cut + 1]), align="C", new_x="LEFT", new_y="NEXT")
        number = number[cut + 1:]
    pdf.set_text_color(*RED)
    pdf.set_font("courier", "B", 14)
    pdf.cell(num_w, 7, t(f"No. {number}"), align="C", new_x="LEFT", new_y="NEXT")
    pdf.set_text_color(*INK)

    pdf.set_xy(L, fy)
    if fiscal:
        pdf.set_font("helvetica", "B", 9)
        pdf.cell(left_w, 5, t("Datos del Adquirente Exonerado:"), align="L", new_x="LMARGIN", new_y="NEXT")
        y = pdf.get_y()
        _line_field(pdf, "Compra Exenta No.", d.get("oce_number") or "", left_w * 0.55)
        pdf.set_xy(L + left_w * 0.57, y)
        _line_field(pdf, "Reg. SAG No.", d.get("sag_registry") or "", left_w * 0.43)
        pdf.set_xy(L, y + 7)
        _line_field(pdf, "Constancia Registro de Exonerados:", d.get("exo_registry") or "", left_w)
        pdf.set_xy(L, y + 15)
        pdf.set_font("times", "BI", 10)
        pdf.cell(left_w, 6, t("\"La Factura es beneficio de todos, EXÍJALA\""), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    y = pdf.get_y()
    pdf.line(L, y, L + left_w, y)
    pdf.set_font("helvetica", "B", 6.5)
    pdf.cell(left_w, 3.5, "CANTIDAD EN LETRAS", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "B", 8.5)
    pdf.multi_cell(left_w, 4.2, t(d.get("amount_words")), align="L", new_x="LMARGIN", new_y="NEXT")
    if fiscal:
        pdf.ln(1)
        pdf.set_font("helvetica", "B", 9.5)
        pdf.multi_cell(left_w, 5, t(f"CAI: {d.get('cai') or '-'}"), align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 8)
        pdf.multi_cell(left_w, 4, t(f"Rango Autorizado: {d.get('range_label') or '-'}"), align="L", new_x="LMARGIN", new_y="NEXT")
        received = f"Fecha Recepción: {fecha(d.get('cai_received'))} • " if d.get("cai_received") else ""
        pdf.multi_cell(left_w, 4, t(f"{received}Fecha Límite de Emisión: {fecha(d.get('limit_date'))}"), align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "B", 8)
        pdf.multi_cell(left_w, 4, t("Original: Cliente • Copia: Obligado Tributario Emisor"), align="L", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("helvetica", "B", 8.5)
        pdf.multi_cell(left_w, 4.5, t("Cotización sin valor fiscal."), align="L", new_x="LMARGIN", new_y="NEXT")
    if d.get("notes"):
        pdf.set_font("helvetica", "", 8)
        pdf.multi_cell(left_w, 4, t(f"Notas: {d['notes']}"), align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(max(pdf.get_y(), fy + len(totals) * 7) + 2)
    return bytes(pdf.output())
