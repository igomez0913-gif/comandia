"""Datos de demostración de Comandia: un restaurante pequeño con menú, recetas, descriptivos y dos salones.

Se carga solo al iniciar una base vacía (COMANDIA_DEMO=comercio carga la demostración antigua de ferretería, que usan las pruebas)."""
from datetime import timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.main import (
    Bank, CaiRange, Category, Client, Company, Department, Descriptive, InvoiceSeries, Presentation, Product, RecipeLine, Stock, Supplier, User, Warehouse,
    hash_password, initials, now_local, today_local,
)
from app.salon import FloorItem, Salon

# (sku, nombre, familia, subfamilia, unidad, costo, precio, mínimo, tipo, estación)
INSUMOS = [
    ("INS-CARNE", "Carne molida de res", "Insumos", "Carnes", "lb", 62, 0, 10, "insumo", ""),
    ("INS-RES", "Corte de res (churrasco)", "Insumos", "Carnes", "lb", 120, 0, 8, "insumo", ""),
    ("INS-POLLO", "Pechuga de pollo", "Insumos", "Carnes", "lb", 45, 0, 10, "insumo", ""),
    ("INS-ALITAS", "Alitas de pollo", "Insumos", "Carnes", "lb", 48, 0, 10, "insumo", ""),
    ("INS-PAN", "Pan de hamburguesa", "Insumos", "Panadería", "und", 4, 0, 30, "insumo", ""),
    ("INS-TORT", "Tortilla de harina", "Insumos", "Panadería", "und", 2.5, 0, 30, "insumo", ""),
    ("INS-QUESO", "Queso cheddar", "Insumos", "Lácteos", "lb", 85, 0, 6, "insumo", ""),
    ("INS-LECHE", "Leche", "Insumos", "Lácteos", "lt", 28, 0, 8, "insumo", ""),
    ("INS-HUEVO", "Huevos", "Insumos", "Lácteos", "und", 3.5, 0, 30, "insumo", ""),
    ("INS-LECH", "Lechuga", "Insumos", "Verduras", "lb", 20, 0, 5, "insumo", ""),
    ("INS-TOM", "Tomate", "Insumos", "Verduras", "lb", 15, 0, 8, "insumo", ""),
    ("INS-PAPAS", "Papas", "Insumos", "Verduras", "lb", 18, 0, 15, "insumo", ""),
    ("INS-FRUTA", "Fruta para jugos", "Insumos", "Verduras", "lb", 25, 0, 8, "insumo", ""),
    ("INS-FRIJ", "Frijoles fritos", "Insumos", "Abarrotes", "lb", 25, 0, 6, "insumo", ""),
    ("INS-PASTA", "Pasta seca", "Insumos", "Abarrotes", "lb", 30, 0, 6, "insumo", ""),
    ("INS-CAFE", "Café molido", "Insumos", "Abarrotes", "lb", 90, 0, 3, "insumo", ""),
    ("INS-AZ", "Azúcar", "Insumos", "Abarrotes", "lb", 12, 0, 6, "insumo", ""),
]
ELABORADOS = [("EL-BBQ", "Salsa BBQ de la casa", "Insumos", "Salsas", "lb", 0, 0, 3, "elaborado", "cocina")]
REVENTA = [  # se compran y se venden tal cual
    ("BEB-COLA", "Refresco", "Bebidas", "Refrescos", "und", 14, 35, 24, "producto", "barra"),
    ("BEB-CERV", "Cerveza nacional", "Bebidas", "Cervezas", "und", 30, 55, 24, "producto", "barra"),
]
PLATILLOS = [
    ("PL-NACHOS", "Nachos con queso", "Entradas", "Calientes", "und", 0, 110, 0, "platillo", "cocina"),
    ("PL-ALITAS", "Alitas BBQ", "Entradas", "Calientes", "und", 0, 165, 0, "platillo", "cocina"),
    ("PL-ENSALADA", "Ensalada césar", "Entradas", "Frías", "und", 0, 120, 0, "platillo", "cocina"),
    ("PL-HAMB", "Hamburguesa clásica", "Hamburguesas", "Clásicas", "und", 0, 135, 0, "platillo", "cocina"),
    ("PL-HAMB2", "Hamburguesa doble", "Hamburguesas", "Clásicas", "und", 0, 185, 0, "platillo", "cocina"),
    ("PL-CHURR", "Churrasco", "Platos fuertes", "Carnes", "und", 0, 285, 0, "platillo", "cocina"),
    ("PL-POLLO", "Pollo a la plancha", "Platos fuertes", "Pollo", "und", 0, 195, 0, "platillo", "cocina"),
    ("PL-PASTA", "Pasta al pomodoro", "Platos fuertes", "Pastas", "und", 0, 150, 0, "platillo", "cocina"),
    ("PL-BALEADA", "Baleada especial", "Platos fuertes", "Pollo", "und", 0, 65, 0, "platillo", "cocina"),
    ("PL-FLAN", "Flan de vainilla", "Postres", "Dulces", "und", 0, 70, 0, "platillo", "postres"),
    ("BEB-CAFE", "Café americano", "Bebidas", "Café y jugos", "und", 0, 40, 0, "platillo", "barra"),
    ("BEB-JUGO", "Jugo natural", "Bebidas", "Café y jugos", "und", 0, 55, 0, "platillo", "barra"),
]
# receta por UNA unidad: (ingrediente, cantidad en la unidad base del ingrediente)
RECETAS = {
    "EL-BBQ": [("INS-TOM", 0.8), ("INS-AZ", 0.15)],
    "PL-NACHOS": [("INS-QUESO", 0.15), ("INS-TORT", 2), ("INS-FRIJ", 0.1)],
    "PL-ALITAS": [("INS-ALITAS", 0.6), ("EL-BBQ", 0.1)],
    "PL-ENSALADA": [("INS-LECH", 0.25), ("INS-POLLO", 0.2), ("INS-QUESO", 0.04)],
    "PL-HAMB": [("INS-CARNE", 0.25), ("INS-PAN", 1), ("INS-QUESO", 0.04), ("INS-LECH", 0.03), ("INS-TOM", 0.05)],
    "PL-HAMB2": [("INS-CARNE", 0.5), ("INS-PAN", 1), ("INS-QUESO", 0.08), ("INS-LECH", 0.03), ("INS-TOM", 0.05)],
    "PL-CHURR": [("INS-RES", 0.5), ("INS-PAPAS", 0.4)],
    "PL-POLLO": [("INS-POLLO", 0.5), ("INS-PAPAS", 0.3), ("INS-LECH", 0.05)],
    "PL-PASTA": [("INS-PASTA", 0.3), ("INS-TOM", 0.3), ("INS-QUESO", 0.03)],
    "PL-BALEADA": [("INS-TORT", 1), ("INS-FRIJ", 0.1), ("INS-HUEVO", 1), ("INS-QUESO", 0.03)],
    "PL-FLAN": [("INS-HUEVO", 1), ("INS-LECHE", 0.2), ("INS-AZ", 0.05)],
    "BEB-CAFE": [("INS-CAFE", 0.03), ("INS-AZ", 0.02)],
    "BEB-JUGO": [("INS-FRUTA", 0.5), ("INS-AZ", 0.03)],
}
STOCK = {"INS-CARNE": 40, "INS-RES": 25, "INS-POLLO": 35, "INS-ALITAS": 30, "INS-PAN": 120, "INS-TORT": 150, "INS-QUESO": 20, "INS-LECHE": 25, "INS-HUEVO": 150,
         "INS-LECH": 15, "INS-TOM": 30, "INS-PAPAS": 50, "INS-FRUTA": 30, "INS-FRIJ": 20, "INS-PASTA": 20, "INS-CAFE": 8, "INS-AZ": 25, "EL-BBQ": 6,
         "BEB-COLA": 96, "BEB-CERV": 120}
DESCRIPTIVOS = [  # (nombre, familia o None = todas, recargo)
    ("Sin cebolla", None, 0), ("Sin picante", None, 0), ("Para compartir", None, 0),
    ("Término medio", "Platos fuertes", 0), ("Tres cuartos", "Platos fuertes", 0), ("Bien cocido", "Platos fuertes", 0),
    ("Término medio", "Hamburguesas", 0), ("Bien cocida", "Hamburguesas", 0), ("Extra queso", "Hamburguesas", 15), ("Extra tocino", "Hamburguesas", 20),
    ("Sin pepinillos", "Hamburguesas", 0), ("Con hielo", "Bebidas", 0), ("Sin hielo", "Bebidas", 0), ("Con limón", "Bebidas", 0), ("Con leche", "Bebidas", 5),
]
SALONES = {
    "Salón principal": [
        *[("mesa", str(n), "cuadrada" if n % 3 else "redonda", 40 + (n - 1) % 4 * 150, 70 + (n - 1) // 4 * 150, 4 if n % 3 else 2) for n in range(1, 9)],
        ("mobiliario", "Barra", "rectangular", 40, 400, 0), ("planta", "Planta", "redonda", 700, 60, 0), ("pared", "", "rectangular", 0, 0, 0),
    ],
    "Terraza": [*[("mesa", f"T{n}", "cuadrada", 40 + (n - 1) * 150, 90, 4) for n in range(1, 5)], ("planta", "Planta", "redonda", 660, 300, 0)],
}
SIZES = {"mesa": (90, 90), "mobiliario": (420, 60), "planta": (60, 60), "pared": (880, 12), "piso": (200, 200)}


def seed_restaurante(db: Session):
    """Una base vacía queda lista para vender: usuario Master, empresa con precios que incluyen ISV, menú con recetas, descriptivos, salones y CAI de demostración."""
    if db.query(User).first():
        return
    db.add(User(name="Luis Mendoza", email="luis@miempresa.hn", password_hash=hash_password("comandia123"), role="Master", initials="LM"))
    db.add(Company(name="Restaurante Demo", legal_name="Restaurante Demo, S. de R.L.", address="Tegucigalpa, Honduras", prices_include_tax=1))
    wh = Warehouse(code="BOD", name="Bodega y cocina", address="Tegucigalpa")
    db.add(wh)
    db.flush()

    deps, cats = {}, {}
    for row in INSUMOS + ELABORADOS + REVENTA + PLATILLOS:
        dep, cat = row[2], row[3]
        if dep not in deps:
            deps[dep] = Department(name=dep)
            db.add(deps[dep])
            db.flush()
        if (dep, cat) not in cats:
            cats[(dep, cat)] = Category(name=cat, department_id=deps[dep].id)
            db.add(cats[(dep, cat)])
            db.flush()
    products = {}
    for n, (sku, name, dep, cat, unit, cost, price, min_stock, kind, station) in enumerate(INSUMOS + ELABORADOS + REVENTA + PLATILLOS, start=1):
        p = Product(sku=sku, name=name, department_id=deps[dep].id, category_id=cats[(dep, cat)].id, base_unit=unit, cost=cost, price=price, min_stock=min_stock,
                    tax_treatment="gravado15", kind=kind, station=station)
        p.presentations.append(Presentation(name=f"Unidad {unit}", unit=unit, factor=1, price=price, barcode=f"74020{n:03d}00"))
        db.add(p)
        products[sku] = p
    db.flush()
    for sku, lines in RECETAS.items():
        for ing, qty in lines:
            db.add(RecipeLine(product_id=products[sku].id, ingredient_id=products[ing].id, qty=Decimal(str(qty))))
    db.flush()
    from app.main import effective_cost  # el costo de cada platillo sale de sus ingredientes
    for sku in RECETAS:
        products[sku].cost = Decimal(str(round(effective_cost(db, products[sku]), 2)))
    for sku, qty in STOCK.items():
        db.add(Stock(product_id=products[sku].id, warehouse_id=wh.id, qty=qty))
    for name, dep, extra in DESCRIPTIVOS:
        db.add(Descriptive(name=name, department_id=deps[dep].id if dep else None, extra_price=extra))

    for order, (salon_name, items) in enumerate(SALONES.items()):
        salon = Salon(name=salon_name, sort_order=order)
        db.add(salon)
        db.flush()
        for kind, name, shape, x, y, seats in items:
            w, h = SIZES[kind]
            db.add(FloorItem(salon_id=salon.id, kind=kind, name=name, shape=shape, x=x, y=y, w=w, h=h, seats=seats))

    for name, rtn in (("Consumidor final", ""), ("Cliente frecuente", "08019988001122")):
        db.add(Client(name=name, rtn=rtn, email="mostrador@miempresa.hn" if not rtn else "", phone="", initials=initials(name), color="#1f6f4a", price_level=1))
    db.add(Supplier(name="Distribuidora de Alimentos", rtn="08019000111223", category="Insumos", email="ventas@proveedor.hn", phone="2222-4000"))
    db.add(Supplier(name="Bebidas y Licores del Norte", rtn="05019000111224", category="Bebidas", email="pedidos@proveedor.hn", phone="2222-4001"))
    db.add_all([Bank(name="Caja general", account="EFECTIVO", balance=0), Bank(name="Banco (tarjetas y transferencias)", account="0101-0000000000", balance=0)])
    limit = today_local() + timedelta(days=300)
    cai_f = CaiRange(cai="A1B2C3-D4E5F6-778899-AABBCC-DDEE001", doc_type="01", establishment="001", emission_point="001", range_from=1, range_to=999999, current=1, limit_date=limit)
    cai_n = CaiRange(cai="B2C3D4-E5F6A7-889900-BBCCDD-EEFF002", doc_type="06", establishment="001", emission_point="001", range_from=1, range_to=200, current=1, limit_date=limit)
    db.add_all([cai_f, cai_n])
    db.flush()
    db.add(InvoiceSeries(code="", name="Normal", cai_id=cai_f.id, current=1, range_to=999999))
    db.commit()
