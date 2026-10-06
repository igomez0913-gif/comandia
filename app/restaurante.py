"""Comandia · catálogo del restaurante: recetas (costo por ingredientes), descriptivos y órdenes de preparación.

Se carga al final de app/main.py, cuando ya existen la aplicación, los modelos y los permisos."""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.main import (
    Department, Descriptive, PrepOrder, Product, RecipeLine, User, Warehouse, adjust_stock, app, audit, current_user, effective_cost, get_db, has_perm,
    money, next_seq_number, now_local, recipe_lines, require, SELLABLE_KINDS,
)

RECIPE_OWNERS = ("platillo", "elaborado")  # quienes llevan receta
INGREDIENT_KINDS = ("insumo", "elaborado", "producto")  # lo que puede ser ingrediente (un platillo no)
MAX_RECIPE_LINES = 60


class RecipeLineIn(BaseModel):
    ingredient_id: int
    qty: float = Field(gt=0, le=1_000_000)  # por UNA unidad del platillo, en la unidad base del ingrediente


class RecipeIn(BaseModel):
    lines: list[RecipeLineIn] = Field(default_factory=list, max_length=MAX_RECIPE_LINES)


def _owner(db: Session, pid: int) -> Product:
    p = db.get(Product, pid)
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    return p


def _recipe_out(db: Session, p: Product, costs: bool) -> dict:
    lines = recipe_lines(db, p.id)
    cost = effective_cost(db, p)
    price = money(p.price)
    out = {
        "product_id": p.id, "sku": p.sku, "name": p.name, "kind": p.kind, "base_unit": p.base_unit, "price": price,
        "lines": [{"ingredient_id": ln.ingredient_id, "sku": ln.ingredient.sku, "name": ln.ingredient.name, "unit": ln.ingredient.base_unit,
                   "kind": ln.ingredient.kind, "qty": float(ln.qty),
                   **({"unit_cost": round(effective_cost(db, ln.ingredient), 4), "cost": round(float(ln.qty) * effective_cost(db, ln.ingredient), 4)} if costs else {})}
                  for ln in lines],
    }
    if costs:
        out["cost"] = round(cost, 2)
        out["margin"] = round(price - cost, 2) if price else None
        out["margin_pct"] = round((price - cost) / price * 100, 1) if price else None
    return out


def _reaches(db: Session, start: int, target: int, seen: Optional[set] = None) -> bool:
    """¿La receta de `start` usa, directa o indirectamente, a `target`? (para impedir recetas circulares)"""
    seen = seen if seen is not None else set()
    if start == target:
        return True
    if start in seen:
        return False
    seen.add(start)
    return any(_reaches(db, ln.ingredient_id, target, seen) for ln in recipe_lines(db, start))


@app.get("/api/recipes")
def list_recipes(db: Session = Depends(get_db), user: User = Depends(require("catalogo", "inventario", "ver_costos", "reportes"))):
    """Reporte de recetas: todos los productos que llevan receta, con su costo, precio y margen (el costo solo lo ve quien puede ver costos)."""
    costs = has_perm(user, "ver_costos")
    owners = db.query(Product).filter(Product.id.in_([r.product_id for r in db.query(RecipeLine.product_id).distinct()] or [0])).order_by(Product.name).all()
    return [_recipe_out(db, p, costs) for p in owners]


@app.get("/api/recipes/{pid}")
def get_recipe(pid: int, db: Session = Depends(get_db), user: User = Depends(require("catalogo", "inventario", "ver_costos", "reportes"))):
    return _recipe_out(db, _owner(db, pid), has_perm(user, "ver_costos"))


@app.put("/api/recipes/{pid}")
def put_recipe(pid: int, body: RecipeIn, db: Session = Depends(get_db), user: User = Depends(require("catalogo"))):
    """Reemplaza la receta. Una lista vacía la borra. El costo del producto pasa a ser el de sus ingredientes."""
    p = _owner(db, pid)
    if p.kind not in RECIPE_OWNERS:
        raise HTTPException(400, "Solo los platillos y los elaborados llevan receta: cambia el tipo del producto primero")
    seen_ids = set()
    for ln in body.lines:
        if ln.ingredient_id in seen_ids:
            raise HTTPException(400, "Un ingrediente no puede repetirse en la misma receta")
        seen_ids.add(ln.ingredient_id)
        ing = db.get(Product, ln.ingredient_id)
        if not ing:
            raise HTTPException(400, "Ingrediente no encontrado")
        if ing.id == p.id:
            raise HTTPException(400, "Un producto no puede ser ingrediente de sí mismo")
        if ing.kind not in INGREDIENT_KINDS:
            raise HTTPException(400, f"«{ing.name}» es un platillo: solo los insumos, elaborados y productos pueden ser ingredientes")
        if _reaches(db, ing.id, p.id):
            raise HTTPException(400, f"«{ing.name}» ya usa a «{p.name}» en su receta: la receta quedaría circular")
    db.query(RecipeLine).filter(RecipeLine.product_id == p.id).delete(synchronize_session=False)
    for ln in body.lines:
        db.add(RecipeLine(product_id=p.id, ingredient_id=ln.ingredient_id, qty=Decimal(str(ln.qty))))
    db.flush()
    p.cost = Decimal(str(round(effective_cost(db, p), 2))) if body.lines else p.cost  # costo por ingredientes
    audit(db, user, "Editó receta" if body.lines else "Borró receta", f"{p.sku} {p.name} · {len(body.lines)} ingrediente(s)", "producto", p.id)
    db.commit()
    return _recipe_out(db, p, has_perm(user, "ver_costos"))


# ───────────────────────── Descriptivos ─────────────────────────
class DescriptiveIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    department_id: Optional[int] = None  # vacío = para todas las familias
    extra_price: float = Field(default=0, ge=0, le=1_000_000)
    active: bool = True


def _descriptive_out(d: Descriptive) -> dict:
    return {"id": d.id, "name": d.name, "department_id": d.department_id, "department": d.department.name if d.department else "",
            "extra_price": money(d.extra_price), "active": bool(d.active)}


def _check_department(db: Session, department_id: Optional[int]):
    if department_id and not db.get(Department, department_id):
        raise HTTPException(400, "Familia no válida")


@app.get("/api/descriptives")
def list_descriptives(department_id: Optional[int] = None, all: bool = False, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Con `department_id` trae los de esa familia más los generales (los que usa un mesero al tomar el pedido). `all` incluye los inactivos."""
    q = db.query(Descriptive)
    if not all:
        q = q.filter(Descriptive.active == 1)
    if department_id:
        q = q.filter((Descriptive.department_id == department_id) | (Descriptive.department_id.is_(None)))
    return [_descriptive_out(d) for d in q.order_by(Descriptive.name).all()]


@app.post("/api/descriptives")
def create_descriptive(body: DescriptiveIn, db: Session = Depends(get_db), user: User = Depends(require("catalogo"))):
    _check_department(db, body.department_id)
    name = body.name.strip()
    if db.query(Descriptive).filter(Descriptive.name == name, Descriptive.department_id == body.department_id).first():
        raise HTTPException(400, "Ya existe ese descriptivo en esa familia")
    d = Descriptive(name=name, department_id=body.department_id, extra_price=Decimal(str(body.extra_price)), active=1 if body.active else 0)
    db.add(d)
    db.flush()
    audit(db, user, "Creó descriptivo", name, "descriptivo", d.id)
    db.commit()
    return _descriptive_out(d)


@app.put("/api/descriptives/{did}")
def update_descriptive(did: int, body: DescriptiveIn, db: Session = Depends(get_db), user: User = Depends(require("catalogo"))):
    d = db.get(Descriptive, did)
    if not d:
        raise HTTPException(404, "Descriptivo no encontrado")
    _check_department(db, body.department_id)
    name = body.name.strip()
    if db.query(Descriptive).filter(Descriptive.name == name, Descriptive.department_id == body.department_id, Descriptive.id != did).first():
        raise HTTPException(400, "Ya existe ese descriptivo en esa familia")
    d.name, d.department_id, d.extra_price, d.active = name, body.department_id, Decimal(str(body.extra_price)), 1 if body.active else 0
    audit(db, user, "Editó descriptivo", name, "descriptivo", d.id)
    db.commit()
    return _descriptive_out(d)


@app.delete("/api/descriptives/{did}")
def delete_descriptive(did: int, db: Session = Depends(get_db), user: User = Depends(require("catalogo"))):
    d = db.get(Descriptive, did)
    if not d:
        raise HTTPException(404, "Descriptivo no encontrado")
    audit(db, user, "Borró descriptivo", d.name, "descriptivo", d.id)
    db.delete(d)
    db.commit()
    return {"ok": True}


# ───────────────────────── Órdenes de preparación ─────────────────────────
class PrepIn(BaseModel):
    product_id: int
    warehouse_id: int
    qty: float = Field(gt=0, le=1_000_000)  # cuántas unidades del elaborado se producen
    notes: str = Field(default="", max_length=255)


def _prep_out(o: PrepOrder) -> dict:
    return {"id": o.id, "number": o.number, "product_id": o.product_id, "product": o.product.name if o.product else "", "unit": o.product.base_unit if o.product else "",
            "warehouse_id": o.warehouse_id, "qty": float(o.qty), "cost": money(o.cost), "notes": o.notes or "",
            "created_at": o.created_at.isoformat() if o.created_at else None, "user": o.user_name or ""}


@app.get("/api/preparations")
def list_preparations(db: Session = Depends(get_db), user: User = Depends(require("inventario"))):
    return [_prep_out(o) for o in db.query(PrepOrder).order_by(PrepOrder.id.desc()).limit(300).all()]


@app.post("/api/preparations")
def create_preparation(body: PrepIn, db: Session = Depends(get_db), user: User = Depends(require("inventario"))):
    """Produce un elaborado: gasta sus ingredientes (según su receta) y suma lo producido a la bodega, todo en una sola operación."""
    p = db.get(Product, body.product_id)
    if not p or p.kind != "elaborado":
        raise HTTPException(400, "Solo se preparan los productos de tipo «elaborado»")
    lines = recipe_lines(db, p.id)
    if not lines:
        raise HTTPException(400, f"«{p.name}» no tiene receta: arma su receta antes de prepararlo")
    wh = db.get(Warehouse, body.warehouse_id)
    if not wh or not wh.active:
        raise HTTPException(400, "Bodega no válida")
    number = next_seq_number(db, PrepOrder, PrepOrder.number, "OP-", 6)
    cost = 0.0
    for ln in sorted(lines, key=lambda x: x.ingredient_id):  # siempre en el mismo orden: evita bloqueos cruzados
        used = body.qty * float(ln.qty)
        cost += used * effective_cost(db, ln.ingredient)
        adjust_stock(db, ln.ingredient_id, wh.id, -used, f"Preparación {number}")
    adjust_stock(db, p.id, wh.id, body.qty, f"Preparación {number}")
    o = PrepOrder(number=number, product_id=p.id, warehouse_id=wh.id, qty=Decimal(str(body.qty)), cost=Decimal(str(round(cost, 4))), notes=body.notes.strip(),
                  created_at=now_local(), user_id=user.id, user_name=user.name)
    db.add(o)
    db.flush()
    audit(db, user, "Orden de preparación", f"{number} · {p.name} × {body.qty:g} {p.base_unit}", "preparacion", o.id)
    db.commit()
    return _prep_out(o)
