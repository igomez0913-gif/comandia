"""Comandia · salón: salones y plano de mesas, cuentas, pedidos, cambio y unión de mesas, división de cuentas y cobro.

Se carga al final de app/main.py, cuando ya existen la aplicación, los modelos y los permisos."""
from datetime import datetime
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func, or_, select
from sqlalchemy.orm import Session, relationship

from app.main import (
    PAY_METHODS, Base, Client, Descriptive, PosPaymentIn, PosSaleIn, ItemIn, Presentation, Product, SELLABLE_KINDS, User, Warehouse, _pos_sale, app, audit,
    authorize_with_pin, current_user, get_db, has_perm, money, next_seq_number, now_local, require, resolve_line, price_for_level,
)

FLOOR_KINDS = ("mesa", "mobiliario", "planta", "pared", "piso", "puerta")
# Formas: cuadrada, redonda, rectangular y ovalada (mesas con sillas alrededor), cabina (sofás enfrentados), barra (mostrador con bancos), alta (mesa de coctel con bancos) y sofá.
SHAPES = ("cuadrada", "redonda", "rectangular", "ovalada", "cabina", "barra", "alta", "sofa")
ACTIVE_LINE = ("nueva", "enviada")  # lo que todavía se debe cobrar


# ───────────────────────── Modelos ─────────────────────────
class Salon(Base):
    __tablename__ = "salons"
    id = Column(Integer, primary_key=True)
    name = Column(String(60), unique=True, nullable=False)
    sort_order = Column(Integer, default=0)
    active = Column(Integer, default=1)
    items = relationship("FloorItem", cascade="all, delete-orphan", order_by="FloorItem.id")


class FloorItem(Base):
    """Un elemento del plano: mesa, mobiliario, planta, pared o piso. Solo las mesas reciben cuentas."""
    __tablename__ = "floor_items"
    id = Column(Integer, primary_key=True)
    salon_id = Column(Integer, ForeignKey("salons.id"), nullable=False)
    kind = Column(String(12), default="mesa")
    name = Column(String(40), default="")
    shape = Column(String(12), default="cuadrada")
    x = Column(Integer, default=0)
    y = Column(Integer, default=0)
    w = Column(Integer, default=80)
    h = Column(Integer, default=80)
    rotation = Column(Integer, default=0)
    seats = Column(Integer, default=4)
    active = Column(Integer, default=1)


class Tab(Base):
    """Cuenta: la consumición de una mesa (o de varias unidas). Se cobra completa o por partes y se cierra cuando no queda nada por cobrar."""
    __tablename__ = "tabs"
    id = Column(Integer, primary_key=True)
    number = Column(String(16), unique=True, nullable=False)
    name = Column(String(120), default="")  # a nombre de quién (opcional)
    guests = Column(Integer, default=1)
    status = Column(String(10), default="Abierta")  # Abierta, Cerrada, Unida (se unió a otra cuenta)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)  # de qué bodega sale lo que se vende
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    waiter_id = Column(Integer, nullable=True)
    waiter_name = Column(String(120), default="")
    notes = Column(String(255), default="")
    opened_at = Column(DateTime, default=now_local)
    closed_at = Column(DateTime, nullable=True)
    merged_into_id = Column(Integer, nullable=True)
    lines = relationship("TabLine", cascade="all, delete-orphan", order_by="TabLine.id")
    tables = relationship("TabTable", cascade="all, delete-orphan")
    client = relationship("Client")


class TabTable(Base):
    """Mesas que ocupa una cuenta. Una cuenta abierta puede ocupar varias mesas (mesas unidas)."""
    __tablename__ = "tab_tables"
    id = Column(Integer, primary_key=True)
    tab_id = Column(Integer, ForeignKey("tabs.id"), nullable=False)
    table_id = Column(Integer, ForeignKey("floor_items.id"), nullable=False)
    table = relationship("FloorItem")


class TabLine(Base):
    __tablename__ = "tab_lines"
    id = Column(Integer, primary_key=True)
    tab_id = Column(Integer, ForeignKey("tabs.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    description = Column(String(200), default="")  # nombre del platillo con sus descriptivos
    qty = Column(Numeric(12, 2), default=1)
    unit_price = Column(Numeric(12, 2), default=0)  # ya incluye los recargos de los descriptivos
    station = Column(String(20), default="")
    guest = Column(Integer, default=1)  # a qué comensal pertenece (para dividir la cuenta)
    descriptives = Column(String(255), default="")
    note = Column(String(200), default="")
    status = Column(String(10), default="nueva")  # nueva (sin enviar), enviada, cobrada, anulada
    created_at = Column(DateTime, default=now_local)
    created_by = Column(String(120), default="")
    sent_at = Column(DateTime, nullable=True)
    voided_at = Column(DateTime, nullable=True)
    voided_by = Column(String(120), default="")
    void_reason = Column(String(200), default="")
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)  # la factura con la que se cobró
    share = Column(Numeric(12, 8), nullable=True)  # fracción del plato que cubre esta línea (vacío = todo): así se reparte un plato compartido entre comensales
    group_id = Column(Integer, nullable=True)  # las partes de un mismo plato comparten este número (el de la línea original)
    orig_guest = Column(Integer, nullable=True)  # a quién pertenecía el plato antes de dividirlo: al juntar las partes vuelve con esa persona
    comanda_id = Column(Integer, ForeignKey("comandas.id"), nullable=True)  # la comanda con la que se envió a cocina o barra
    kds_status = Column(String(12), default="pendiente")  # en la pantalla de cocina: pendiente, preparando, listo, servido
    ready_at = Column(DateTime, nullable=True)
    served_at = Column(DateTime, nullable=True)
    product = relationship("Product")


class TabSettlement(Base):
    """Un cobro de una cuenta (completo o parcial): la factura que generó y la propina."""
    __tablename__ = "tab_settlements"
    id = Column(Integer, primary_key=True)
    tab_id = Column(Integer, ForeignKey("tabs.id"), nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    tip = Column(Numeric(12, 2), default=0)
    tip_method = Column(String(20), default="Efectivo")
    lines = Column(Integer, default=0)
    created_at = Column(DateTime, default=now_local)
    user_id = Column(Integer, nullable=True)
    user_name = Column(String(120), default="")


# ───────────────────────── Salones y plano ─────────────────────────
class SalonIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    sort_order: int = Field(default=0, ge=0, le=999)


class FloorItemIn(BaseModel):
    id: Optional[int] = None
    kind: str = "mesa"
    name: str = Field(default="", max_length=40)
    shape: str = "cuadrada"
    x: int = Field(default=0, ge=0, le=5000)
    y: int = Field(default=0, ge=0, le=5000)
    w: int = Field(default=80, ge=10, le=2000)
    h: int = Field(default=80, ge=10, le=2000)
    rotation: int = Field(default=0, ge=0, le=359)
    seats: int = Field(default=4, ge=0, le=50)


class LayoutIn(BaseModel):
    items: list[FloorItemIn] = Field(default_factory=list, max_length=400)


def open_tab_of_table(db: Session, table_id: int) -> Optional[Tab]:
    return (db.query(Tab).join(TabTable, TabTable.tab_id == Tab.id)
            .filter(TabTable.table_id == table_id, Tab.status == "Abierta").first())


def _minutes(since) -> int:
    """Minutos transcurridos, calculados aquí: las fechas del sistema son de Honduras y el navegador de quien mira podría estar en otra zona."""
    return max(0, int((now_local() - since).total_seconds() // 60)) if since else 0


Q8 = Decimal("0.00000001")


def eff_qty(ln: "TabLine") -> float:
    """Cantidad que realmente cubre la línea: la del plato por la fracción que le toca (un plato compartido se factura en partes).
    Se redondea a 8 decimales, los mismos que guarda la factura: así lo que se muestra, lo que se factura y lo que se acredita es siempre lo mismo."""
    if ln.share is None:
        return float(ln.qty)
    return float((Decimal(str(ln.qty)) * Decimal(str(ln.share))).quantize(Q8, rounding=ROUND_HALF_EVEN))


def line_amount(ln: "TabLine") -> float:
    return round(eff_qty(ln) * float(ln.unit_price), 2)


def split_cents(total: int, weights: list) -> list:
    """Reparte `total` centavos según los pesos sin perder ni sobrar ninguno (método del mayor residuo): las partes siempre suman el total."""
    w = [Fraction(str(x)) for x in weights]
    exact = [Fraction(total) * x / sum(w) for x in w]
    base = [int(e) for e in exact]  # parte entera de cada una
    extra = total - sum(base)
    order = sorted(range(len(w)), key=lambda i: (-(exact[i] - base[i]), i))  # primero a quien más le faltó
    for i in order[:extra]:
        base[i] += 1
    return base


def _cents(ln: "TabLine") -> int:
    """Importe de la línea en centavos, calculado igual que la factura y el total de la cuenta: dividir un consumo nunca cambia lo que se debe."""
    return int((Decimal(str(line_amount(ln))) * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _portion_label(share) -> str:
    """«1/3», «2/5»… o un porcentaje cuando no es una fracción sencilla."""
    if share is None:
        return ""
    f = Fraction(float(share)).limit_denominator(12)
    if abs(float(f) - float(share)) < 5e-4 and f.denominator > 1:  # la parte que lleva el centavo sobrante vale 0.3334, no exactamente 1/3
        return f"{f.numerator}/{f.denominator}"
    return f"{float(share) * 100:.1f}%".replace(".0%", "%")


def _is_part(ln: "TabLine") -> bool:
    """Las partes de un plato dividido, salvo la original, no existen para la cocina (solo se factura su fracción)."""
    return ln.group_id is not None and ln.group_id != ln.id


def tab_total(t: Tab) -> float:
    return round(sum(line_amount(ln) for ln in t.lines if ln.status in ACTIVE_LINE), 2)


def _item_out(db: Session, it: FloorItem) -> dict:
    out = {"id": it.id, "kind": it.kind, "name": it.name, "shape": it.shape, "x": it.x, "y": it.y, "w": it.w, "h": it.h, "rotation": it.rotation, "seats": it.seats}
    if it.kind == "mesa":
        t = open_tab_of_table(db, it.id)
        out["tab"] = {"id": t.id, "number": t.number, "total": tab_total(t), "waiter": t.waiter_name, "guests": t.guests, "opened_at": t.opened_at.isoformat(), "minutes": _minutes(t.opened_at),
                      "pending": sum(1 for ln in t.lines if ln.status == "nueva"), "tables": [x.table_id for x in t.tables]} if t else None
    return out


def _salon_out(db: Session, s: Salon) -> dict:
    return {"id": s.id, "name": s.name, "sort_order": s.sort_order, "items": [_item_out(db, i) for i in s.items if i.active]}


@app.get("/api/salons")
def list_salons(db: Session = Depends(get_db), user: User = Depends(require("mesas", "salones", "cocina"))):
    """Los salones con su plano y el estado de cada mesa (libre u ocupada, con el total de su cuenta)."""
    return [_salon_out(db, s) for s in db.query(Salon).filter(Salon.active == 1).order_by(Salon.sort_order, Salon.id).all()]


@app.post("/api/salons")
def create_salon(body: SalonIn, db: Session = Depends(get_db), user: User = Depends(require("salones"))):
    name = body.name.strip()
    if db.query(Salon).filter(func.lower(Salon.name) == name.lower()).first():
        raise HTTPException(400, "Ya existe un salón con ese nombre")
    s = Salon(name=name, sort_order=body.sort_order)
    db.add(s)
    db.flush()
    audit(db, user, "Creó salón", name, "salon", s.id)
    db.commit()
    return _salon_out(db, s)


@app.put("/api/salons/{sid}")
def update_salon(sid: int, body: SalonIn, db: Session = Depends(get_db), user: User = Depends(require("salones"))):
    s = db.get(Salon, sid)
    if not s or not s.active:
        raise HTTPException(404, "Salón no encontrado")
    name = body.name.strip()
    if db.query(Salon).filter(func.lower(Salon.name) == name.lower(), Salon.id != sid).first():
        raise HTTPException(400, "Ya existe un salón con ese nombre")
    s.name, s.sort_order = name, body.sort_order
    audit(db, user, "Editó salón", name, "salon", s.id)
    db.commit()
    return _salon_out(db, s)


@app.delete("/api/salons/{sid}")
def delete_salon(sid: int, db: Session = Depends(get_db), user: User = Depends(require("salones"))):
    s = db.get(Salon, sid)
    if not s or not s.active:
        raise HTTPException(404, "Salón no encontrado")
    if any(open_tab_of_table(db, i.id) for i in s.items if i.active and i.kind == "mesa"):
        raise HTTPException(400, "Este salón tiene cuentas abiertas: cóbralas o pásalas a otra mesa primero")
    s.active = 0  # se conserva: las cuentas viejas apuntan a sus mesas
    for i in s.items:
        i.active = 0
    audit(db, user, "Quitó salón", s.name, "salon", s.id)
    db.commit()
    return {"ok": True}


@app.put("/api/salons/{sid}/layout")
def save_layout(sid: int, body: LayoutIn, db: Session = Depends(get_db), user: User = Depends(require("salones"))):
    """Guarda el plano completo. Los elementos con `id` se actualizan, los nuevos se crean y los que ya no vienen se quitan
    (una mesa con cuenta abierta no se puede quitar; una con historial solo se desactiva)."""
    s = db.get(Salon, sid)
    if not s or not s.active:
        raise HTTPException(404, "Salón no encontrado")
    mesas = [i.name.strip().lower() for i in body.items if i.kind == "mesa"]
    if any(not n for n in mesas):
        raise HTTPException(400, "Cada mesa necesita un nombre o número")
    if len(set(mesas)) != len(mesas):
        raise HTTPException(400, "Hay dos mesas con el mismo nombre en este salón")
    for i in body.items:
        if i.kind not in FLOOR_KINDS:
            raise HTTPException(400, "Elemento no válido: " + ", ".join(FLOOR_KINDS))
        if i.shape not in SHAPES:
            raise HTTPException(400, "Forma no válida: " + ", ".join(SHAPES))
    current = {i.id: i for i in s.items if i.active}
    keep = set()
    for i in body.items:
        row = current.get(i.id) if i.id else None
        if i.id and not row:
            raise HTTPException(400, "Un elemento del plano no pertenece a este salón")
        if row is None:
            row = FloorItem(salon_id=s.id)
            db.add(row)
        elif row.kind == "mesa" and i.kind != "mesa" and open_tab_of_table(db, row.id):
            raise HTTPException(400, f"La mesa {row.name} tiene una cuenta abierta: no se puede convertir en otra cosa")
        row.kind, row.name, row.shape, row.x, row.y, row.w, row.h, row.rotation, row.seats = i.kind, i.name.strip(), i.shape, i.x, i.y, i.w, i.h, i.rotation, i.seats
        db.flush()
        keep.add(row.id)
    for rid, row in current.items():
        if rid in keep:
            continue
        if row.kind == "mesa" and open_tab_of_table(db, rid):
            raise HTTPException(400, f"La mesa {row.name} tiene una cuenta abierta: no se puede quitar")
        used = db.query(TabTable).filter(TabTable.table_id == rid).first()
        if used:
            row.active = 0
        else:
            db.delete(row)
    audit(db, user, "Guardó el plano del salón", f"{s.name} · {len(body.items)} elemento(s)", "salon", s.id)
    db.commit()
    db.refresh(s)
    return _salon_out(db, s)


# ───────────────────────── Cuentas ─────────────────────────
def _line_out(ln: TabLine, paid_groups=frozenset()) -> dict:
    return {"id": ln.id, "product_id": ln.product_id, "sku": ln.product.sku if ln.product else "", "description": ln.description, "qty": float(ln.qty),
            "unit_price": money(ln.unit_price), "total": line_amount(ln), "station": ln.station, "guest": ln.guest,
            "share": float(ln.share) if ln.share is not None else None, "portion": _portion_label(ln.share), "group_id": ln.group_id, "is_part": _is_part(ln), "group_paid": ln.group_id in paid_groups,
            "descriptives": ln.descriptives, "note": ln.note, "status": ln.status, "kds": ln.kds_status if ln.status == "enviada" and ln.comanda_id else None, "created_by": ln.created_by,
            "sent_at": ln.sent_at.isoformat() if ln.sent_at else None, "void_reason": ln.void_reason, "document_id": ln.document_id}


def _tab_out(db: Session, t: Tab, detail: bool = True) -> dict:
    out = {"id": t.id, "number": t.number, "name": t.name, "guests": t.guests, "status": t.status, "waiter": t.waiter_name, "waiter_id": t.waiter_id,
           "opened_at": t.opened_at.isoformat() if t.opened_at else None, "minutes": _minutes(t.opened_at), "closed_at": t.closed_at.isoformat() if t.closed_at else None,
           "tables": [{"id": x.table_id, "name": x.table.name if x.table else "", "salon_id": x.table.salon_id if x.table else None} for x in t.tables],
           "total": tab_total(t), "lines_count": sum(1 for ln in t.lines if ln.status in ACTIVE_LINE), "pending": sum(1 for ln in t.lines if ln.status == "nueva"),
           "client_id": t.client_id, "warehouse_id": t.warehouse_id, "notes": t.notes or ""}
    if detail:
        paid_groups = {x.group_id for x in t.lines if x.group_id is not None and x.status == "cobrada"}  # platos compartidos de los que ya se cobró alguna parte
        out["lines"] = [_line_out(ln, paid_groups) for ln in t.lines]
        out["guests_totals"] = {}
        for ln in t.lines:
            if ln.status in ACTIVE_LINE:
                out["guests_totals"][str(ln.guest)] = round(out["guests_totals"].get(str(ln.guest), 0) + line_amount(ln), 2)
        out["settlements"] = [{"id": x.id, "document_id": x.document_id, "tip": money(x.tip), "tip_method": x.tip_method, "lines": x.lines,
                               "created_at": x.created_at.isoformat() if x.created_at else None, "user": x.user_name}
                              for x in db.query(TabSettlement).filter(TabSettlement.tab_id == t.id).order_by(TabSettlement.id).all()]
    return out


def _get_tab(db: Session, tid: int, lock: bool = False) -> Tab:
    q = db.query(Tab).filter(Tab.id == tid)
    t = (q.with_for_update() if lock else q).first()
    if not t:
        raise HTTPException(404, "Cuenta no encontrada")
    return t


def _need_open(t: Tab):
    if t.status != "Abierta":
        raise HTTPException(400, f"La cuenta {t.number} ya está {t.status.lower()}")


def _close_if_settled(db: Session, user: User, t: Tab) -> bool:
    """Si ya se cobró algo y no queda nada pendiente (lo último se anuló o pasó a otra cuenta), la cuenta se cierra y la mesa queda libre.
    Sin esto la cuenta quedaría abierta para siempre: no hay nada que cobrar y tampoco se puede cerrar «vacía» porque tiene cobros."""
    if t.status == "Abierta" and any(ln.status == "cobrada" for ln in t.lines) and not any(ln.status in ACTIVE_LINE for ln in t.lines):
        t.status, t.closed_at = "Cerrada", now_local()
        audit(db, user, "Cerró cuenta", f"{t.number} · ya no quedaba nada por cobrar", "cuenta", t.id)
        return True
    return False


def _claim_tables(db: Session, table_ids: list, tab: Optional[Tab] = None) -> list:
    """Valida y bloquea las mesas pedidas: existen, son mesas del plano y no tienen otra cuenta abierta."""
    if len(set(table_ids)) != len(table_ids):
        raise HTTPException(400, "Una mesa está repetida")
    rows = db.query(FloorItem).filter(FloorItem.id.in_(table_ids or [0])).order_by(FloorItem.id).with_for_update().all()
    if len(rows) != len(table_ids):
        raise HTTPException(400, "Mesa no encontrada")
    for r in rows:
        if r.kind != "mesa" or not r.active:
            raise HTTPException(400, f"«{r.name or r.id}» no es una mesa")
        other = open_tab_of_table(db, r.id)
        if other and (tab is None or other.id != tab.id):
            raise HTTPException(400, f"La mesa {r.name} ya tiene la cuenta abierta {other.number}")
    return rows


class TabIn(BaseModel):
    table_ids: list[int] = Field(default_factory=list, max_length=12)  # vacío = cuenta sin mesa (de barra o de mostrador)
    name: str = Field(default="", max_length=120)
    guests: int = Field(default=1, ge=1, le=100)
    client_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    notes: str = Field(default="", max_length=255)


def _default_warehouse(db: Session, warehouse_id: Optional[int]) -> int:
    wh = db.get(Warehouse, warehouse_id) if warehouse_id else db.query(Warehouse).filter(Warehouse.active == 1).order_by(Warehouse.id).first()
    if not wh or not wh.active:
        raise HTTPException(400, "Bodega no válida")
    return wh.id


@app.get("/api/tabs")
def list_tabs(status: str = "Abierta", db: Session = Depends(get_db), user: User = Depends(require("mesas", "cobrar"))):
    q = db.query(Tab)
    if status:
        q = q.filter(Tab.status == status)
    return [_tab_out(db, t, detail=False) for t in q.order_by(Tab.id.desc()).limit(300).all()]


@app.post("/api/tabs")
def open_tab(body: TabIn, db: Session = Depends(get_db), user: User = Depends(require("mesas"))):
    if body.client_id and not db.get(Client, body.client_id):
        raise HTTPException(400, "Cliente no válido")
    _claim_tables(db, body.table_ids)
    t = Tab(number=next_seq_number(db, Tab, Tab.number, "CU-", 6), name=body.name.strip(), guests=body.guests, client_id=body.client_id,
            warehouse_id=_default_warehouse(db, body.warehouse_id), waiter_id=user.id, waiter_name=user.name, notes=body.notes.strip(), opened_at=now_local())
    for tid in body.table_ids:
        t.tables.append(TabTable(table_id=tid))
    db.add(t)
    db.flush()
    audit(db, user, "Abrió cuenta", f"{t.number}" + (f" · mesa(s) {', '.join(str(x.table.name) for x in t.tables if x.table)}" if t.tables else ""), "cuenta", t.id)
    db.commit()
    return _tab_out(db, t)


@app.get("/api/tabs/{tid}")
def get_tab(tid: int, db: Session = Depends(get_db), user: User = Depends(require("mesas", "cobrar"))):
    return _tab_out(db, _get_tab(db, tid))


class LineIn(BaseModel):
    product_id: int
    qty: float = Field(default=1, gt=0, le=1000)
    descriptive_ids: list[int] = Field(default_factory=list, max_length=20)
    note: str = Field(default="", max_length=200)
    guest: int = Field(default=1, ge=1, le=100)


@app.post("/api/tabs/{tid}/lines")
def add_line(tid: int, body: LineIn, db: Session = Depends(get_db), user: User = Depends(require("mesas"))):
    t = _get_tab(db, tid, lock=True)
    _need_open(t)
    prod = db.get(Product, body.product_id)
    if not prod:
        raise HTTPException(400, "Producto no encontrado")
    if (prod.kind or "producto") not in SELLABLE_KINDS:
        raise HTTPException(400, f"«{prod.name}» es un {prod.kind}: no se vende, solo se usa en recetas")
    if body.guest > max(t.guests, 1):
        raise HTTPException(400, f"La cuenta tiene {t.guests} comensal(es): el comensal {body.guest} no existe")
    names, extra = [], Decimal("0")
    for did in dict.fromkeys(body.descriptive_ids):
        d = db.get(Descriptive, did)
        if not d or not d.active:
            raise HTTPException(400, "Descriptivo no válido")
        if d.department_id and d.department_id != prod.department_id:
            raise HTTPException(400, f"«{d.name}» no aplica a «{prod.name}»")
        names.append(d.name)
        extra += Decimal(str(d.extra_price or 0))
    _p, pres, _f, _u = resolve_line(db, prod.id, None)
    base = Decimal(str(price_for_level(pres or prod, 1)))
    ln = TabLine(tab_id=t.id, product_id=prod.id, description=prod.name, qty=Decimal(str(body.qty)), unit_price=base + extra, station=prod.station or "",
                 guest=body.guest, descriptives=", ".join(names), note=body.note.strip(), status="nueva", created_at=now_local(), created_by=user.name)
    t.lines.append(ln)
    db.flush()
    db.commit()
    return _tab_out(db, t)


class LineUpdate(BaseModel):
    qty: Optional[float] = Field(default=None, gt=0, le=1000)
    note: Optional[str] = Field(default=None, max_length=200)
    guest: Optional[int] = Field(default=None, ge=1, le=100)


def _group_of(t: Tab, ln: TabLine) -> list:
    """Todas las partes del plato al que pertenece la línea (ella sola si no está dividido)."""
    return [x for x in t.lines if x.group_id == ln.group_id] if ln.group_id is not None else [ln]


def _get_line(db: Session, t: Tab, lid: int) -> TabLine:
    ln = next((x for x in t.lines if x.id == lid), None)
    if not ln:
        raise HTTPException(404, "Esa línea no está en la cuenta")
    return ln


@app.put("/api/tabs/{tid}/lines/{lid}")
def update_line(tid: int, lid: int, body: LineUpdate, db: Session = Depends(get_db), user: User = Depends(require("mesas"))):
    t = _get_tab(db, tid, lock=True)
    _need_open(t)
    ln = _get_line(db, t, lid)
    if ln.status != "nueva":
        raise HTTPException(400, "Esa línea ya se envió a cocina: agrega otra o anúlala con autorización")
    if body.qty is not None:
        if ln.group_id is not None:
            raise HTTPException(400, "Este plato está dividido entre comensales: junta las partes para cambiar la cantidad")
        ln.qty = Decimal(str(body.qty))
    if body.note is not None:
        for p in _group_of(t, ln):  # la cocina recibe el plato una sola vez (con la línea original): la nota es del plato, no de un comensal
            p.note = body.note.strip()
    if body.guest is not None:
        if body.guest > max(t.guests, 1):
            raise HTTPException(400, f"La cuenta tiene {t.guests} comensal(es)")
        ln.guest = body.guest
    db.commit()
    return _tab_out(db, t)


class VoidIn(BaseModel):
    reason: str = Field(default="", max_length=200)
    auth_pin: str = Field(default="", max_length=20)


@app.post("/api/tabs/{tid}/lines/{lid}/void")
def void_line(tid: int, lid: int, body: VoidIn, db: Session = Depends(get_db), user: User = Depends(require("mesas"))):
    """Una línea sin enviar simplemente se quita. Una ya enviada a cocina se anula con motivo y queda en el reporte de productos anulados;
    quien no tiene el permiso de anular necesita el PIN de un supervisor.
    Un plato dividido entre comensales se anula completo; si ya se cobró alguna parte, se anula lo que falta y lo cobrado se conserva."""
    t = _get_tab(db, tid, lock=True)
    _need_open(t)
    ln = _get_line(db, t, lid)
    parts = _group_of(t, ln)
    live = [p for p in parts if p.status in ACTIVE_LINE]  # lo que todavía se debe del plato
    if ln.status == "nueva":
        for p in live:
            t.lines.remove(p)
        _close_if_settled(db, user, t)
        db.commit()
        return _tab_out(db, t)
    if ln.status != "enviada":
        raise HTTPException(400, f"Esa línea ya está {ln.status}")
    reason = body.reason.strip()
    if len(reason) < 3:
        raise HTTPException(400, "Escribe el motivo de la anulación")
    who = user
    if not has_perm(user, "anular"):
        who = authorize_with_pin(db, user, body.auth_pin, "anular", "Anular un producto ya enviado a cocina necesita el PIN de un supervisor")
    when = now_local()
    for p in live:
        p.status, p.voided_at, p.voided_by, p.void_reason = "anulada", when, who.name, reason
    paid = sum(1 for p in parts if p.status == "cobrada")
    audit(db, user, "Anuló producto de la cuenta", f"{t.number} · {float(ln.qty):g} × {ln.description} · {reason}" + (f" · dividido en {len(parts)} partes" if len(parts) > 1 else "")
          + (f" · {paid} parte(s) ya cobrada(s) se conservan" if paid else "") + (f" · autorizó {who.name}" if who.id != user.id else ""), "cuenta", t.id)
    _close_if_settled(db, user, t)
    db.commit()
    from app import cocina
    for p in live:
        if p.comanda_id:
            cocina.notify_void(db, t, p)  # avisa a la estación para que no lo prepare (o lo deje de preparar)
    return _tab_out(db, t)


@app.post("/api/tabs/{tid}/send")
def send_to_kitchen(tid: int, db: Session = Depends(get_db), user: User = Depends(require("mesas"))):
    """Envía a cocina y barra lo que está sin enviar. Devuelve las comandas agrupadas por estación (a dónde se imprime cada una)."""
    t = _get_tab(db, tid, lock=True)
    _need_open(t)
    fresh = [ln for ln in t.lines if ln.status == "nueva" and not _is_part(ln)]
    if not fresh:
        raise HTTPException(400, "No hay productos nuevos que enviar")
    now = now_local()
    for ln in t.lines:  # las partes de un plato dividido salen con su plato: la cocina lo recibe una sola vez
        if ln.status == "nueva" and _is_part(ln):
            ln.status, ln.sent_at = "enviada", now
    grouped: dict = {}
    for ln in fresh:
        ln.status, ln.sent_at = "enviada", now
        grouped.setdefault(ln.station or "cocina", []).append(_line_out(ln))
    from app import cocina  # se carga después que el salón
    made = cocina.create_comandas(db, t, fresh, now)
    audit(db, user, "Envió pedido a cocina", f"{t.number} · {len(fresh)} línea(s) · " + ", ".join(c.number for c in made), "cuenta", t.id)
    db.commit()
    cocina.print_comandas(db, made)  # un fallo de impresión no frena el pedido: queda en la pantalla de cocina y se puede reimprimir
    mesas = ", ".join(x.table.name for x in t.tables if x.table)
    return {"tab": _tab_out(db, t), "comandas": [{**cocina._comanda_out(c), "sent_at": now.isoformat(), "lines": grouped[c.station]} for c in made]}


class GuestsIn(BaseModel):
    guests: int = Field(ge=1, le=100)
    name: str = Field(default="", max_length=120)


@app.put("/api/tabs/{tid}/guests")
def update_guests(tid: int, body: GuestsIn, db: Session = Depends(get_db), user: User = Depends(require("mesas"))):
    """Cambia cuántos comensales hay y a nombre de quién va la cuenta. No se pueden quitar comensales que ya tienen consumos."""
    t = _get_tab(db, tid, lock=True)
    _need_open(t)
    used = max([ln.guest for ln in t.lines if ln.status in ACTIVE_LINE + ("cobrada",)] or [1])
    if body.guests < used:
        raise HTTPException(400, f"El comensal {used} ya tiene consumos: pásalos a otro antes de bajar a {body.guests}")
    t.guests, t.name = body.guests, body.name.strip()
    db.commit()
    return _tab_out(db, t)


# ───────────────────────── Dividir la cuenta: reasignar, partir un plato, partes iguales ─────────────────────────
class GuestAssignIn(BaseModel):
    line_ids: list[int] = Field(min_length=1, max_length=200)
    guest: int = Field(ge=1, le=100)


@app.post("/api/tabs/{tid}/guest")
def reassign_guest(tid: int, body: GuestAssignIn, db: Session = Depends(get_db), user: User = Depends(require("mesas"))):
    """Pasa consumos a otro comensal, incluso después de enviarlos a cocina (no cambia el total de la cuenta, solo quién paga qué). Queda en la bitácora."""
    t = _get_tab(db, tid, lock=True)
    _need_open(t)
    if body.guest > max(t.guests, 1):
        raise HTTPException(400, f"La cuenta tiene {t.guests} comensal(es): el comensal {body.guest} no existe")
    wanted = set(body.line_ids)
    lines = [ln for ln in t.lines if ln.id in wanted]
    if len(lines) != len(wanted):
        raise HTTPException(400, "Alguna línea no está en esta cuenta")
    if any(ln.status not in ACTIVE_LINE for ln in lines):
        raise HTTPException(400, "Solo se reasignan consumos pendientes de cobro")
    moved = ", ".join(f"{ln.description} (C{ln.guest}→C{body.guest})" for ln in lines if ln.guest != body.guest)
    for ln in lines:
        ln.guest = body.guest
    audit(db, user, "Reasignó consumos a un comensal", f"{t.number} · {len(lines)} línea(s) → comensal {body.guest}" + (f" · {moved}" if moved else ""), "cuenta", t.id)
    db.commit()
    return _tab_out(db, t)


class SplitPart(BaseModel):
    guest: int = Field(ge=1, le=100)
    weight: float = Field(default=1, gt=0, le=1000)  # porciones: con 1 y 2, el segundo paga el doble


class SplitIn(BaseModel):
    parts: list[SplitPart] = Field(min_length=2, max_length=20)


def _plan_parts(ln: TabLine, cents: list) -> list:
    """Fracción exacta de cada parte. Comprueba que facturar «cantidad × fracción × precio» da justo los centavos repartidos (con importes enormes los 8 decimales
    de la fracción no alcanzan y se perdería un centavo): si no cuadra, no se divide."""
    total = sum(cents)
    shares = [(Decimal(c) / Decimal(total)).quantize(Q8, rounding=ROUND_HALF_EVEN) for c in cents]
    for c, sh in zip(cents, shares):
        got = round(float((Decimal(str(ln.qty)) * sh).quantize(Q8, rounding=ROUND_HALF_EVEN)) * float(ln.unit_price), 2)
        if int(round(got * 100)) != c:
            raise HTTPException(400, f"«{ln.description}» es un importe demasiado grande para dividirlo con exactitud (L {total / 100:,.2f}): divide la cantidad en consumos más pequeños")
    return shares


def _make_parts(t: Tab, ln: TabLine, shares: list, guests: list):
    """Convierte `ln` en la primera parte y crea las demás con el mismo plato. Cada parte lleva la fracción exacta que le toca."""
    owner = ln.guest
    ln.group_id = ln.id
    for i, (sh, g) in enumerate(zip(shares, guests)):
        if i == 0:
            part = ln
        else:
            part = TabLine(tab_id=t.id, product_id=ln.product_id, description=ln.description, qty=ln.qty, unit_price=ln.unit_price, station=ln.station, descriptives=ln.descriptives,
                           note=ln.note, status=ln.status, created_at=ln.created_at, created_by=ln.created_by, sent_at=ln.sent_at, group_id=ln.id)
            t.lines.append(part)
        part.share, part.guest, part.orig_guest = sh, g, owner


@app.post("/api/tabs/{tid}/lines/{lid}/split")
def split_line(tid: int, lid: int, body: SplitIn, db: Session = Depends(get_db), user: User = Depends(require("mesas"))):
    """Parte un plato compartido entre comensales (por ejemplo una entrada para tres). Cada uno paga su parte en su propia factura y el inventario se descuenta en proporción;
    la cocina sigue recibiendo el plato una sola vez. Los centavos se reparten sin perder ninguno."""
    t = _get_tab(db, tid, lock=True)
    _need_open(t)
    ln = _get_line(db, t, lid)
    if ln.status not in ACTIVE_LINE:
        raise HTTPException(400, f"Ese consumo ya está {ln.status}: solo se dividen los pendientes de cobro")
    if ln.group_id is not None:
        raise HTTPException(400, "Ese plato ya está dividido: junta sus partes antes de dividirlo de nuevo")
    for p in body.parts:
        if p.guest > max(t.guests, 1):
            raise HTTPException(400, f"La cuenta tiene {t.guests} comensal(es): el comensal {p.guest} no existe")
    total = _cents(ln)
    if total < len(body.parts):
        raise HTTPException(400, "El importe es demasiado pequeño para dividirlo en tantas partes")
    cents = split_cents(total, [p.weight for p in body.parts])
    if min(cents) < 1:
        raise HTTPException(400, "Con esas porciones una parte quedaría en cero: ajusta las porciones")
    shares = _plan_parts(ln, cents)
    detail = ", ".join(f"C{p.guest} L {c / 100:,.2f}" for p, c in zip(body.parts, cents))
    _make_parts(t, ln, shares, [p.guest for p in body.parts])
    db.flush()
    audit(db, user, "Dividió un plato entre comensales", f"{t.number} · {ln.description} · L {total / 100:,.2f} · {detail}", "cuenta", t.id)
    db.commit()
    return _tab_out(db, t)


class SplitEqualIn(BaseModel):
    parts: int = Field(ge=2, le=20)


@app.post("/api/tabs/{tid}/split-equal")
def split_equal(tid: int, body: SplitEqualIn, db: Session = Depends(get_db), user: User = Depends(require("mesas"))):
    """Divide toda la cuenta en partes iguales: cada comensal queda con la misma fracción de cada consumo y se cobra con su propia factura.
    Los centavos sobrantes se reparten de forma rotativa entre los comensales, así nadie paga de más de forma sistemática."""
    t = _get_tab(db, tid, lock=True)
    _need_open(t)
    active = [ln for ln in t.lines if ln.status in ACTIVE_LINE]
    if not active:
        raise HTTPException(400, "No hay consumos que dividir")
    if any(ln.group_id is not None for ln in active):
        raise HTTPException(400, "Ya hay platos divididos: junta las partes antes de dividir toda la cuenta")
    n = body.parts
    plan, carry = [], 0  # carry: cuántos centavos sobrantes se han repartido ya, para que el siguiente consumo siga con el comensal que toca
    for i, ln in enumerate(sorted(active, key=lambda x: x.id)):
        total = _cents(ln)
        count = min(n, total)  # un consumo de pocos centavos se reparte entre menos comensales
        if count < 2:
            plan.append((ln, None, [(i % n) + 1]))
            continue
        base, rem = divmod(total, count)
        cents = [base + (1 if ((g - carry) % count) < rem else 0) for g in range(count)]
        carry = (carry + rem) % count
        plan.append((ln, _plan_parts(ln, cents), list(range(1, count + 1))))  # se valida todo antes de tocar nada
    t.guests = max(t.guests, n)
    for ln, shares, guests in plan:
        if shares is None:
            ln.guest = guests[0]
        else:
            _make_parts(t, ln, shares, guests)
    db.flush()
    audit(db, user, "Dividió la cuenta en partes iguales", f"{t.number} · {n} partes · {len(plan)} consumo(s) · L {tab_total(t):,.2f}", "cuenta", t.id)
    db.commit()
    return _tab_out(db, t)


class UnsplitIn(BaseModel):
    line_id: Optional[int] = None  # vacío = juntar todos los platos divididos de la cuenta


@app.post("/api/tabs/{tid}/unsplit")
def unsplit(tid: int, body: UnsplitIn, db: Session = Depends(get_db), user: User = Depends(require("mesas"))):
    """Junta las partes de un plato dividido (o de todos) de nuevo en una sola línea. No se puede si ya se cobró alguna parte."""
    t = _get_tab(db, tid, lock=True)
    _need_open(t)
    if body.line_id is not None:
        target = _get_line(db, t, body.line_id)
        if target.group_id is None:
            raise HTTPException(400, "Ese consumo no está dividido")
        group_ids = {target.group_id}
    else:
        group_ids = {ln.group_id for ln in t.lines if ln.group_id is not None and ln.status in ACTIVE_LINE}
    done, names = 0, []
    for gid in sorted(group_ids):
        parts = [ln for ln in t.lines if ln.group_id == gid]
        if any(p.status == "cobrada" for p in parts):
            if body.line_id is not None:
                raise HTTPException(400, f"Ya se cobraron partes de «{parts[0].description}»: no se pueden juntar")
            continue  # al juntar todo se respetan los platos que ya tienen partes cobradas
        if any(p.status == "anulada" for p in parts):
            continue
        head = next((p for p in parts if p.id == gid), parts[0])
        for p in parts:
            if p is not head:
                t.lines.remove(p)
        if head.orig_guest:
            head.guest = head.orig_guest  # el plato vuelve con quien lo pidió, no con el comensal de su primera parte
        head.share, head.group_id, head.orig_guest = None, None, None
        names.append(head.description)
        done += 1
    if not done:
        raise HTTPException(400, "No hay platos divididos que se puedan juntar")
    db.flush()
    audit(db, user, "Juntó las partes de un plato", f"{t.number} · {done} plato(s) · " + ", ".join(names), "cuenta", t.id)
    db.commit()
    return _tab_out(db, t)


class MoveIn(BaseModel):
    table_ids: list[int] = Field(min_length=1, max_length=12)


@app.post("/api/tabs/{tid}/move")
def move_tab(tid: int, body: MoveIn, db: Session = Depends(get_db), user: User = Depends(require("mesas"))):
    """El cliente se cambia de mesa (o se pasa a varias): la cuenta deja las mesas anteriores y ocupa las nuevas."""
    t = _get_tab(db, tid, lock=True)
    _need_open(t)
    _claim_tables(db, body.table_ids, t)
    before = ", ".join(x.table.name for x in t.tables if x.table) or "sin mesa"
    t.tables.clear()
    db.flush()
    for tbl in body.table_ids:
        t.tables.append(TabTable(table_id=tbl))
    db.flush()
    after = ", ".join(x.table.name for x in t.tables if x.table)
    audit(db, user, "Cambió la cuenta de mesa", f"{t.number} · {before} → {after}", "cuenta", t.id)
    db.commit()
    return _tab_out(db, t)


class MergeIn(BaseModel):
    from_tab_id: int


@app.post("/api/tabs/{tid}/merge")
def merge_tabs(tid: int, body: MergeIn, db: Session = Depends(get_db), user: User = Depends(require("mesas"))):
    """Une otra cuenta a esta: sus consumos y sus mesas pasan a esta cuenta y la otra queda como «Unida»."""
    if body.from_tab_id == tid:
        raise HTTPException(400, "Elige otra cuenta para unir")
    first, second = sorted((tid, body.from_tab_id))
    locked = {x.id: x for x in db.query(Tab).filter(Tab.id.in_([first, second])).order_by(Tab.id).with_for_update().all()}  # siempre en el mismo orden
    t, src = locked.get(tid), locked.get(body.from_tab_id)
    if not t or not src:
        raise HTTPException(404, "Cuenta no encontrada")
    _need_open(t)
    _need_open(src)
    for tt in list(src.tables):
        t.tables.append(TabTable(table_id=tt.table_id))
    offset = max(t.guests, 1)  # los comensales de la otra cuenta siguen siendo otros: se numeran a continuación
    for ln in list(src.lines):
        src.lines.remove(ln)
        ln.guest += offset
        t.lines.append(ln)
    t.guests = offset + max(src.guests, 1)
    src.tables.clear()
    src.status, src.merged_into_id, src.closed_at = "Unida", t.id, now_local()
    from app.cocina import Comanda  # se carga después que el salón
    db.query(Comanda).filter(Comanda.tab_id == src.id).update({Comanda.tab_id: t.id}, synchronize_session=False)  # las comandas ya enviadas siguen a sus consumos: la cocina las sigue viendo
    db.flush()
    audit(db, user, "Unió cuentas", f"{src.number} → {t.number}", "cuenta", t.id)
    db.commit()
    return _tab_out(db, t)


class TransferIn(BaseModel):
    line_ids: list[int] = Field(min_length=1, max_length=200)
    to_tab_id: Optional[int] = None
    to_table_id: Optional[int] = None  # si esa mesa no tiene cuenta, se le abre una


@app.post("/api/tabs/{tid}/transfer")
def transfer_lines(tid: int, body: TransferIn, db: Session = Depends(get_db), user: User = Depends(require("mesas"))):
    """Pasa consumos a otra cuenta o a otra mesa (se le abre cuenta si estaba libre)."""
    if bool(body.to_tab_id) == bool(body.to_table_id):
        raise HTTPException(400, "Indica la cuenta o la mesa de destino (una sola)")
    dest_id = body.to_tab_id
    if body.to_table_id:
        found = open_tab_of_table(db, body.to_table_id)
        dest_id = found.id if found else None
    locked = {x.id: x for x in db.query(Tab).filter(Tab.id.in_({tid, dest_id} - {None})).order_by(Tab.id).with_for_update().all()}  # origen y destino, siempre en el mismo orden
    t = locked.get(tid)
    if not t:
        raise HTTPException(404, "Cuenta no encontrada")
    _need_open(t)
    lines = [ln for ln in t.lines if ln.id in set(body.line_ids)]
    if len(lines) != len(set(body.line_ids)):
        raise HTTPException(400, "Alguna línea no está en esta cuenta")
    if any(ln.status not in ACTIVE_LINE for ln in lines):
        raise HTTPException(400, "Solo se transfieren consumos pendientes de cobro")
    chosen_ids = {ln.id for ln in lines}
    for ln in lines:
        if ln.group_id is not None and any(p.id not in chosen_ids for p in _group_of(t, ln)):
            raise HTTPException(400, f"«{ln.description}» está dividido entre comensales: pasa todas sus partes juntas o júntalas primero (si ya se cobró una parte, ya no se puede pasar)")
    if dest_id:
        dest = locked.get(dest_id)
        if not dest:
            raise HTTPException(404, "Cuenta no encontrada")
    else:
        _claim_tables(db, [body.to_table_id])  # valida que sea una mesa y la bloquea
        dest = Tab(number=next_seq_number(db, Tab, Tab.number, "CU-", 6), guests=1, warehouse_id=t.warehouse_id, waiter_id=user.id, waiter_name=user.name, opened_at=now_local())
        dest.tables.append(TabTable(table_id=body.to_table_id))
        db.add(dest)
        db.flush()
    if dest.id == t.id:
        raise HTTPException(400, "Elige una cuenta distinta")
    _need_open(dest)
    _follow_comandas(db, lines, dest)
    for ln in lines:
        t.lines.remove(ln)
        ln.guest = min(ln.guest, max(dest.guests, 1))
        dest.lines.append(ln)
    db.flush()
    audit(db, user, "Transfirió consumos", f"{t.number} → {dest.number} · {len(lines)} línea(s) · " + ", ".join(ln.description for ln in lines)[:300], "cuenta", t.id)
    _close_if_settled(db, user, t)
    db.commit()
    return {"from": _tab_out(db, t), "to": _tab_out(db, dest)}


def _follow_comandas(db: Session, lines: list, dest: Tab):
    """Las comandas ya enviadas siguen a sus consumos: así la cocina y el mesero que lleva el plato ven la mesa nueva. Si la comanda lleva más platos que se quedan,
    los que se van pasan a una comanda nueva (sin imprimir: el papel ya salió)."""
    from app.cocina import Comanda  # se carga después que el salón
    by_comanda: dict = {}
    for ln in lines:
        if ln.comanda_id:
            by_comanda.setdefault(ln.comanda_id, []).append(ln)
    for cid, moved in by_comanda.items():
        c = db.get(Comanda, cid)
        staying = [x for x in c.lines if x not in moved]
        if not staying:
            c.tab_id = dest.id
            continue
        new = Comanda(number=next_seq_number(db, Comanda, Comanda.number, "CM-", 6), tab_id=dest.id, station=c.station, created_at=c.created_at, printed_at=c.printed_at)
        db.add(new)
        db.flush()
        for ln in moved:
            ln.comanda_id = new.id


@app.post("/api/tabs/{tid}/close-empty")
def close_empty(tid: int, db: Session = Depends(get_db), user: User = Depends(require("mesas"))):
    """Cierra una cuenta vacía (se abrió por error o el cliente se fue sin pedir) y libera su mesa."""
    t = _get_tab(db, tid, lock=True)
    _need_open(t)
    if any(ln.status in ACTIVE_LINE + ("cobrada",) for ln in t.lines):
        raise HTTPException(400, "La cuenta tiene consumos: cóbrala o transfiérelos")
    t.status, t.closed_at = "Cerrada", now_local()
    audit(db, user, "Cerró cuenta vacía", t.number, "cuenta", t.id)
    db.commit()
    return _tab_out(db, t)


class PayIn(BaseModel):
    line_ids: list[int] = Field(default_factory=list, max_length=200)  # vacío = todo lo pendiente (o el comensal indicado)
    guest: Optional[int] = Field(default=None, ge=1, le=100)  # cobrar solo lo de este comensal
    client_id: Optional[int] = None
    buyer_name: str = Field(default="", max_length=180)
    buyer_rtn: str = Field(default="", max_length=20)
    oce_number: str = Field(default="", max_length=40)
    series_id: Optional[int] = None
    payments: list[PosPaymentIn] = Field(default_factory=list)
    received: Optional[float] = Field(default=None, ge=0)
    tip: float = Field(default=0, ge=0, le=1_000_000)
    tip_method: str = "Efectivo"


@app.post("/api/tabs/{tid}/pay")
def pay_tab(tid: int, body: PayIn, db: Session = Depends(get_db), user: User = Depends(require("mesas", "cobrar"))):
    """Cobra la cuenta (toda, lo de un comensal o las líneas elegidas): emite la factura, registra el pago, descuenta el inventario y,
    si ya no queda nada por cobrar, cierra la cuenta y libera la mesa. Todo en una sola operación."""
    if not has_perm(user, "cobrar") or not has_perm(user, "facturar"):
        raise HTTPException(403, f"Tu rol ({user.role}) no puede cobrar: pide a Caja que cobre la cuenta")
    if body.tip_method not in PAY_METHODS:
        raise HTTPException(400, "Forma de pago de la propina no válida")
    t = _get_tab(db, tid, lock=True)
    _need_open(t)
    pending = [ln for ln in t.lines if ln.status in ACTIVE_LINE]
    if body.line_ids:
        chosen = [ln for ln in pending if ln.id in set(body.line_ids)]
        if len(chosen) != len(set(body.line_ids)):
            raise HTTPException(400, "Alguna línea no está pendiente en esta cuenta")
    elif body.guest:
        chosen = [ln for ln in pending if ln.guest == body.guest]
    else:
        chosen = pending
    if not chosen:
        raise HTTPException(400, "No hay consumos que cobrar")
    if any(ln.status == "nueva" for ln in chosen):
        raise HTTPException(400, "Hay productos sin enviar a cocina: envíalos o quítalos antes de cobrar")
    client_id = body.client_id or t.client_id
    if not client_id:
        final = db.query(Client).filter(Client.rtn == "").order_by(Client.id).first()
        if not final:
            raise HTTPException(400, "Elige el cliente de la factura")
        client_id = final.id
    sale = PosSaleIn(client_id=client_id, warehouse_id=t.warehouse_id or _default_warehouse(db, None), series_id=body.series_id, oce_number=body.oce_number,
                     buyer_name=body.buyer_name, buyer_rtn=body.buyer_rtn, payments=body.payments, received=body.received,
                     items=[ItemIn(product_id=ln.product_id, qty=eff_qty(ln), price=float(ln.unit_price)) for ln in chosen])
    doc = _pos_sale(sale, db, user, commit=False, trusted_prices=True)
    for ln in chosen:
        ln.status, ln.document_id = "cobrada", doc["id"]
    db.add(TabSettlement(tab_id=t.id, document_id=doc["id"], tip=Decimal(str(round(body.tip, 2))), tip_method=body.tip_method, lines=len(chosen),
                         created_at=now_local(), user_id=user.id, user_name=user.name))
    db.flush()
    closed = not any(ln.status in ACTIVE_LINE for ln in t.lines)
    if closed:
        t.status, t.closed_at = "Cerrada", now_local()
    audit(db, user, "Cobró cuenta" if closed else "Cobró parte de la cuenta", f"{t.number} · {doc['number']} · L {doc['total']:,.2f}" + (f" · propina L {body.tip:,.2f}" if body.tip else ""), "cuenta", t.id)
    db.commit()
    return {"document": doc, "tab": _tab_out(db, t), "closed": closed, "tip": round(body.tip, 2)}


# ───────────────────────── Reporte de productos anulados ─────────────────────────
@app.get("/api/reports/voided-lines")
def voided_lines(start: Optional[str] = Query(default=None), end: Optional[str] = Query(default=None), db: Session = Depends(get_db),
                 user: User = Depends(require("reportes"))):
    """Productos anulados de las cuentas: qué, cuándo, de quién era la cuenta, quién lo anuló (y autorizó) y por qué."""
    q = db.query(TabLine).filter(TabLine.status == "anulada")
    try:
        if start:
            q = q.filter(TabLine.voided_at >= datetime.fromisoformat(start))
        if end:
            q = q.filter(TabLine.voided_at < datetime.fromisoformat(end).replace(hour=23, minute=59, second=59))
    except ValueError:
        raise HTTPException(400, "Fecha no válida (AAAA-MM-DD)")
    # un plato dividido sale una sola vez (con la primera de sus partes anuladas): se filtra en la consulta, antes del límite, para que las partes no desplacen anulaciones
    first_voided = select(func.min(TabLine.id)).where(TabLine.status == "anulada", TabLine.group_id.isnot(None)).group_by(TabLine.group_id)
    rows = q.filter(or_(TabLine.group_id.is_(None), TabLine.id.in_(first_voided))).order_by(TabLine.voided_at.desc(), TabLine.id.desc()).limit(1000).all()
    tabs = {t.id: t for t in db.query(Tab).filter(Tab.id.in_([r.tab_id for r in rows] or [0])).all()}
    amount = lambda r: round(sum(line_amount(p) for p in tabs[r.tab_id].lines if p.group_id == r.group_id and p.status == "anulada"), 2) if r.group_id is not None else line_amount(r)
    out = [{"id": r.id, "tab": tabs[r.tab_id].number, "waiter": tabs[r.tab_id].waiter_name, "description": r.description, "qty": float(r.qty),
            "amount": amount(r), "voided_at": r.voided_at.isoformat() if r.voided_at else None, "voided_by": r.voided_by, "reason": r.void_reason} for r in rows]
    return {"rows": out, "total": round(sum(x["amount"] for x in out), 2)}
