"""Comandia · cocina y barra: comandas, impresión en impresoras térmicas de red (ESC/POS por IP) y pantalla de cocina (KDS).

Se carga al final de app/main.py, cuando ya existen la aplicación, los modelos y los permisos."""
import ipaddress
import socket
import textwrap
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Session, relationship

from app.logger import get_logger
from app.main import STATIONS, Base, User, app, audit, get_db, has_perm, now_local, next_seq_number, require
from app.salon import Tab, TabLine

log = get_logger("comandia.cocina")

WIDTH = 42  # caracteres por línea en papel de 80 mm
KDS_STATUSES = ("pendiente", "preparando", "listo", "servido")
KITCHEN_SET = ("pendiente", "preparando", "listo")  # los marca la cocina; «servido» lo marca quien atiende el salón
PRINT_TIMEOUT = 2.0


# ───────────────────────── Modelos ─────────────────────────
class PrinterConfig(Base):
    """Impresora térmica de red de una estación (cocina, barra...)."""
    __tablename__ = "printers"
    station = Column(String(20), primary_key=True)
    host = Column(String(64), default="")
    port = Column(Integer, default=9100)
    copies = Column(Integer, default=1)
    active = Column(Integer, default=1)


class Comanda(Base):
    """Lo que se envía a una estación en un mismo momento: una por estación cada vez que se manda un pedido."""
    __tablename__ = "comandas"
    id = Column(Integer, primary_key=True)
    number = Column(String(16), unique=True, nullable=False)
    tab_id = Column(Integer, ForeignKey("tabs.id"), nullable=False)
    station = Column(String(20), default="cocina")
    created_at = Column(DateTime, default=now_local)
    printed_at = Column(DateTime, nullable=True)
    print_error = Column(String(200), default="")
    tab = relationship("Tab")
    lines = relationship("TabLine", primaryjoin="Comanda.id == TabLine.comanda_id", order_by="TabLine.id")


# ───────────────────────── Impresión ESC/POS ─────────────────────────
def check_host(host: str) -> str:
    """Solo direcciones IP de la red local o de la propia máquina: una impresora de comandas nunca está en internet, y así el servidor no se puede usar para llegar a otros destinos."""
    host = (host or "").strip()
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise HTTPException(400, "Escribe la dirección IP de la impresora (por ejemplo 192.168.1.50)")
    if not (ip.is_private or ip.is_loopback or ip.is_link_local):
        raise HTTPException(400, "La impresora debe estar en tu red local (una dirección 192.168.x.x, 10.x.x.x o 172.16-31.x.x)")
    return str(ip)


def send_to_printer(host: str, port: int, data: bytes, timeout: float = PRINT_TIMEOUT):
    """Manda los bytes a la impresora por el puerto de impresión directa (normalmente 9100). Se separa para poder simularla en las pruebas."""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(data)


def _text(s: str) -> bytes:
    return s.encode("cp858", errors="replace")  # página de códigos con acentos y ñ (ESC t 19)


def _lines(text: str, indent: int = 0) -> list:
    return textwrap.wrap(text, WIDTH - indent) or [""]


def render_comanda(c: Comanda, void_line: Optional[TabLine] = None, test: bool = False) -> bytes:
    out = bytearray(b"\x1b@\x1bt\x13")  # iniciar + página cp858
    center, left = b"\x1ba\x01", b"\x1ba\x00"
    bold_on, bold_off, big, normal = b"\x1bE\x01", b"\x1bE\x00", b"\x1d!\x11", b"\x1d!\x00"
    if test:
        out += center + bold_on + _text("PRUEBA DE IMPRESORA\n") + bold_off + _text(f"{c.station.upper()}\n{now_local():%d/%m/%Y %H:%M}\n") + left
    else:
        t = c.tab
        mesas = ", ".join(x.table.name for x in t.tables if x.table) or (t.name or "sin mesa")
        title = "*** ANULADO ***" if void_line is not None else c.station.upper()
        out += center + bold_on + big + _text(title + "\n") + normal + bold_off + left
        out += bold_on + _text(f"Mesa: {mesas}\n") + bold_off
        out += _text(f"Cuenta {t.number}  ·  {t.waiter_name}\n{(c.created_at or now_local()):%d/%m/%Y %H:%M}   {c.number}\n")
        out += _text("-" * WIDTH + "\n")
        for ln in ([void_line] if void_line is not None else c.lines):
            if ln.status == "anulada" and void_line is None:
                continue
            qty = f"{float(ln.qty):g}"
            for i, piece in enumerate(_lines(f"{qty} x {ln.description}", 0)):
                out += (bold_on + big if i == 0 else b"") + _text(piece + "\n") + (normal + bold_off if i == 0 else b"")
            if ln.descriptives:
                for piece in _lines("+ " + ln.descriptives, 3):
                    out += _text("   " + piece + "\n")
            if ln.note:
                for piece in _lines("NOTA: " + ln.note, 3):
                    out += bold_on + _text("   " + piece + "\n") + bold_off
            if ln.guest and ln.guest > 1:
                out += _text(f"   (comensal {ln.guest})\n")
        out += _text("-" * WIDTH + "\n")
    out += b"\n\n\n\x1dV\x41\x03"  # avanzar y cortar
    return bytes(out)


def _printer(db: Session, station: str) -> Optional[PrinterConfig]:
    p = db.get(PrinterConfig, station)
    return p if p and p.active and (p.host or "").strip() else None


def _dispatch(jobs: list) -> dict:
    """Envía los trabajos [(clave, host, puerto, copias, bytes)] en paralelo; devuelve {clave: error o ''}."""
    def run(job):
        key, host, port, copies, data = job
        try:
            for _ in range(max(copies, 1)):
                send_to_printer(host, port, data)
            return key, ""
        except OSError as exc:
            log.warning("No se pudo imprimir en %s:%s: %s", host, port, exc)
            return key, f"No se pudo imprimir en {host}: {exc}"[:200]
    if not jobs:
        return {}
    with ThreadPoolExecutor(max_workers=min(len(jobs), 8)) as pool:
        return dict(pool.map(run, jobs))


def create_comandas(db: Session, tab: Tab, lines: list, now: datetime) -> list:
    """Una comanda por estación con las líneas recién enviadas."""
    made, by_station = [], {}
    for ln in lines:
        by_station.setdefault(ln.station or "cocina", []).append(ln)
    for station, group in by_station.items():
        c = Comanda(number=next_seq_number(db, Comanda, Comanda.number, "CM-", 6), tab_id=tab.id, station=station, created_at=now)
        db.add(c)
        db.flush()
        for ln in group:
            ln.comanda_id, ln.kds_status = c.id, "pendiente"
        made.append(c)
    return made


def print_comandas(db: Session, comandas: list):
    """Imprime cada comanda en la impresora de su estación (si la tiene) y deja constancia de si salió. Un fallo de impresión no frena el pedido:
    la comanda ya está en la pantalla de cocina y se puede reimprimir."""
    jobs = []
    for c in comandas:
        p = _printer(db, c.station)
        if p:
            jobs.append((c.id, p.host, p.port, p.copies, render_comanda(c)))
    result = _dispatch(jobs)
    for c in comandas:
        if c.id in result:
            c.printed_at, c.print_error = (None, result[c.id]) if result[c.id] else (now_local(), "")
    db.commit()


def notify_void(db: Session, tab: Tab, line: TabLine):
    """Avisa a la estación que un producto ya enviado se anuló (papel «ANULADO»); si no hay impresora, queda tachado en la pantalla de cocina."""
    c = db.get(Comanda, line.comanda_id) if line.comanda_id else None
    p = _printer(db, c.station) if c else None
    if c and p:
        _dispatch([(c.id, p.host, p.port, 1, render_comanda(c, void_line=line))])


# ───────────────────────── Impresoras (configuración) ─────────────────────────
class PrinterIn(BaseModel):
    station: str
    host: str = Field(default="", max_length=64)
    port: int = Field(default=9100, ge=1, le=65535)
    copies: int = Field(default=1, ge=1, le=3)
    active: bool = True


def _printer_out(station: str, p: Optional[PrinterConfig]) -> dict:
    return {"station": station, "host": p.host if p else "", "port": p.port if p else 9100, "copies": p.copies if p else 1, "active": bool(p.active) if p else False}


@app.get("/api/printers")
def list_printers(db: Session = Depends(get_db), user: User = Depends(require("config"))):
    have = {p.station: p for p in db.query(PrinterConfig).all()}
    return [_printer_out(s, have.get(s)) for s in STATIONS if s]


@app.put("/api/printers")
def put_printer(body: PrinterIn, db: Session = Depends(get_db), user: User = Depends(require("config"))):
    station = body.station.strip().lower()
    if station not in STATIONS or not station:
        raise HTTPException(400, "Estación no válida: " + ", ".join(s for s in STATIONS if s))
    host = check_host(body.host) if body.host.strip() else ""
    p = db.get(PrinterConfig, station) or PrinterConfig(station=station)
    p.host, p.port, p.copies, p.active = host, body.port, body.copies, 1 if body.active else 0
    db.add(p)
    audit(db, user, "Configuró impresora de comandas", f"{station} · {host or 'sin impresora'}:{body.port}", "impresora", None)
    db.commit()
    return _printer_out(station, p)


@app.post("/api/printers/{station}/test")
def test_printer(station: str, db: Session = Depends(get_db), user: User = Depends(require("config"))):
    p = _printer(db, station)
    if not p:
        raise HTTPException(400, "Esa estación no tiene impresora configurada")
    fake = Comanda(station=station, created_at=now_local())
    err = _dispatch([(station, p.host, p.port, 1, render_comanda(fake, test=True))]).get(station, "")
    if err:
        raise HTTPException(502, err)
    return {"ok": True}


# ───────────────────────── Comandas y pantalla de cocina ─────────────────────────
def _comanda_out(c: Comanda) -> dict:
    now = now_local()
    t = c.tab
    live = [ln for ln in c.lines if ln.status != "anulada"]
    states = {ln.kds_status for ln in live}
    status = "Servida" if live and states == {"servido"} else "Lista" if live and states <= {"listo", "servido"} else "Preparando" if "preparando" in states or "listo" in states else "Pendiente"
    return {"id": c.id, "number": c.number, "station": c.station, "tab_id": t.id, "tab_number": t.number, "tables": ", ".join(x.table.name for x in t.tables if x.table),
            "tab_name": t.name, "waiter": t.waiter_name, "created_at": c.created_at.isoformat() if c.created_at else None,
            "minutes": int((now - c.created_at).total_seconds() // 60) if c.created_at else 0, "status": status,
            "printed": c.printed_at is not None, "print_error": c.print_error or "",
            "lines": [{"id": ln.id, "description": ln.description, "qty": float(ln.qty), "descriptives": ln.descriptives, "note": ln.note, "guest": ln.guest,
                       "kds_status": ln.kds_status, "voided": ln.status == "anulada", "void_reason": ln.void_reason} for ln in c.lines]}


@app.get("/api/kitchen")
def kitchen(station: str = "", db: Session = Depends(get_db), user: User = Depends(require("cocina", "mesas"))):
    """Pantalla de cocina o barra: las comandas con algo por preparar o por llevar a la mesa, las más viejas primero.
    Los productos anulados salen tachados para que la cocina sepa que ya no se hacen."""
    q = db.query(Comanda).join(Tab, Tab.id == Comanda.tab_id).filter(Tab.status.in_(("Abierta", "Cerrada")))
    if station:
        q = q.filter(Comanda.station == station.strip().lower())
    out = []
    for c in q.order_by(Comanda.id).limit(300).all():
        live = [ln for ln in c.lines if ln.status != "anulada"]
        if live and all(ln.kds_status == "servido" for ln in live):
            continue
        if not live:
            continue  # todo anulado: no hay nada que hacer
        out.append(_comanda_out(c))
    return {"station": station, "comandas": out}


class LineStatusIn(BaseModel):
    status: str


def _check_status_permission(user: User, status: str):
    if status not in KDS_STATUSES:
        raise HTTPException(400, "Estado no válido: " + ", ".join(KDS_STATUSES))
    needed = "cocina" if status in KITCHEN_SET else "mesas"
    if not has_perm(user, needed):
        raise HTTPException(403, f"Tu rol ({user.role}) no puede marcar «{status}»")


def _apply(ln: TabLine, status: str):
    ln.kds_status = status
    now = now_local()
    if status in ("listo", "servido") and ln.ready_at is None:
        ln.ready_at = now
    if status == "servido":
        ln.served_at = now
    if status in ("pendiente", "preparando"):
        ln.ready_at = ln.served_at = None


@app.put("/api/kitchen/lines/{lid}/status")
def set_line_status(lid: int, body: LineStatusIn, db: Session = Depends(get_db), user: User = Depends(require("cocina", "mesas"))):
    _check_status_permission(user, body.status)
    ln = db.query(TabLine).filter(TabLine.id == lid).with_for_update().first()
    if not ln or not ln.comanda_id:
        raise HTTPException(404, "Esa línea no está en ninguna comanda")
    if ln.status == "anulada":
        raise HTTPException(400, "Ese producto está anulado")
    _apply(ln, body.status)
    db.commit()
    return _comanda_out(db.get(Comanda, ln.comanda_id))


@app.post("/api/kitchen/comandas/{cid}/status")
def set_comanda_status(cid: int, body: LineStatusIn, db: Session = Depends(get_db), user: User = Depends(require("cocina", "mesas"))):
    """Marca toda la comanda de una vez (por ejemplo «lista» cuando sale el pedido completo)."""
    _check_status_permission(user, body.status)
    c = db.get(Comanda, cid)
    if not c:
        raise HTTPException(404, "Comanda no encontrada")
    for ln in c.lines:
        if ln.status != "anulada":
            _apply(ln, body.status)
    db.commit()
    return _comanda_out(c)


@app.get("/api/kitchen/ready")
def ready_for_pickup(db: Session = Depends(get_db), user: User = Depends(require("mesas"))):
    """Lo que ya está listo para llevar a la mesa. Un mesero ve solo lo de sus cuentas; quien administra el salón, todo."""
    q = (db.query(TabLine, Comanda, Tab).join(Comanda, Comanda.id == TabLine.comanda_id).join(Tab, Tab.id == TabLine.tab_id)
         .filter(TabLine.kds_status == "listo", TabLine.status == "enviada", Tab.status == "Abierta"))
    if user.role == "Mesero":
        q = q.filter(Tab.waiter_id == user.id)
    return [{"line_id": ln.id, "description": ln.description, "qty": float(ln.qty), "station": c.station, "tab_id": t.id, "tab_number": t.number,
             "tables": ", ".join(x.table.name for x in t.tables if x.table), "ready_at": ln.ready_at.isoformat() if ln.ready_at else None}
            for ln, c, t in q.order_by(TabLine.ready_at).limit(200).all()]


@app.get("/api/comandas")
def list_comandas(tab_id: Optional[int] = Query(default=None), db: Session = Depends(get_db), user: User = Depends(require("cocina", "mesas"))):
    q = db.query(Comanda)
    if tab_id:
        q = q.filter(Comanda.tab_id == tab_id)
    return [_comanda_out(c) for c in q.order_by(Comanda.id.desc()).limit(200).all()]


@app.post("/api/comandas/{cid}/reprint")
def reprint_comanda(cid: int, db: Session = Depends(get_db), user: User = Depends(require("cocina", "mesas"))):
    c = db.get(Comanda, cid)
    if not c:
        raise HTTPException(404, "Comanda no encontrada")
    p = _printer(db, c.station)
    if not p:
        raise HTTPException(400, f"La estación «{c.station}» no tiene impresora configurada")
    err = _dispatch([(c.id, p.host, p.port, p.copies, render_comanda(c))]).get(c.id, "")
    c.printed_at, c.print_error = (None, err) if err else (now_local(), "")
    audit(db, user, "Reimprimió comanda", f"{c.number} · {c.station}", "comanda", c.id)
    db.commit()
    if err:
        raise HTTPException(502, err)
    return _comanda_out(c)
