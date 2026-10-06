"""Cocina y barra: impresoras térmicas de red (ESC/POS por IP), comandas, pantalla de cocina y aviso de platillos listos."""
import socket
import socketserver
import threading
import time

import pytest

from test_api import make_user
from test_r2_salon import add, open_tab, pay_all, rest  # noqa: F401


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        data = b""
        while True:
            chunk = self.request.recv(4096)
            if not chunk:
                break
            data += chunk
        self.server.received.append(data)


class FakePrinter:
    """Una impresora de red de mentira: recibe los bytes por TCP, igual que una térmica en el puerto 9100."""

    def __init__(self):
        self.srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
        self.srv.received, self.srv.daemon_threads = [], True
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def jobs(self, n=1, wait=3.0):
        end = time.time() + wait
        while len(self.srv.received) < n and time.time() < end:
            time.sleep(0.02)
        return list(self.srv.received)

    def text(self, i=0):
        return self.jobs(i + 1)[i].decode("cp858", errors="replace")

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture()
def printers():
    made = []

    def make():
        p = FakePrinter()
        made.append(p)
        return p
    yield make
    for p in made:
        p.stop()


def setup_printer(client, auth, station, printer, **extra):
    r = client.put("/api/printers", json={"station": station, "host": "127.0.0.1", "port": printer.port, **extra}, headers=auth)
    assert r.status_code == 200, r.text


def dead_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def order(client, auth, rest, mesa="1"):  # noqa: F811
    t = open_tab(client, auth, rest, mesa)
    add(client, auth, t, rest["burger"], 2, descriptive_ids=[rest["queso"]["id"], rest["sinceb"]["id"]], note="bien cocida", guest=2)
    add(client, auth, t, rest["cola"], 3)
    return t


# ───────────────────────── configuración de impresoras ─────────────────────────
def test_configurar_impresoras_solo_en_la_red_local(client, auth, login, rest):  # noqa: F811
    assert [p["station"] for p in client.get("/api/printers", headers=auth).json()] == ["cocina", "barra", "parrilla", "postres", "otra"]
    put = lambda **b: client.put("/api/printers", json={"station": "cocina", **b}, headers=auth)
    assert put(host="192.168.1.50").json() == {"station": "cocina", "host": "192.168.1.50", "port": 9100, "copies": 1, "active": True}
    assert put(host="10.0.0.7", port=9101, copies=2).status_code == 200
    assert put(host="8.8.8.8").status_code == 400  # no es de la red local
    assert put(host="impresora.miempresa.com").status_code == 400  # solo direcciones IP: el servidor no resuelve nombres
    assert put(host="169.254.1.2").status_code == 200 and put(host="127.0.0.1").status_code == 200
    assert put(host="192.168.1.50", port=0).status_code == 422 and put(host="192.168.1.50", copies=9).status_code == 422
    assert client.put("/api/printers", json={"station": "azotea", "host": "192.168.1.50"}, headers=auth).status_code == 400
    assert put(host="").json()["host"] == ""  # vacío = sin impresora
    mesero = make_user(client, auth, login, "Mesero")
    assert client.get("/api/printers", headers=mesero).status_code == 403 and client.put("/api/printers", json={"station": "cocina"}, headers=mesero).status_code == 403


def test_imprimir_una_prueba(client, auth, printers):
    p = printers()
    assert client.post("/api/printers/cocina/test", headers=auth).status_code == 400  # sin impresora configurada
    setup_printer(client, auth, "cocina", p)
    assert client.post("/api/printers/cocina/test", headers=auth).json() == {"ok": True}
    assert "PRUEBA DE IMPRESORA" in p.text()
    setup_printer(client, auth, "barra", p, active=False)
    assert client.post("/api/printers/barra/test", headers=auth).status_code == 400  # apagada


# ───────────────────────── comandas impresas ─────────────────────────
def test_cada_estacion_imprime_su_comanda_con_los_detalles(client, auth, printers, rest):  # noqa: F811
    cocina, barra = printers(), printers()
    setup_printer(client, auth, "cocina", cocina)
    setup_printer(client, auth, "barra", barra)
    t = order(client, auth, rest)
    r = client.post(f"/api/tabs/{t['id']}/send", headers=auth).json()
    by = {c["station"]: c for c in r["comandas"]}
    assert set(by) == {"cocina", "barra"} and all(c["printed"] and c["print_error"] == "" for c in by.values())
    assert by["cocina"]["number"] == "CM-000001" and by["barra"]["number"] == "CM-000002"
    k = cocina.text()
    assert "COCINA" in k and "Mesa: 1" in k and "2 x Hamburguesa" in k and "+ Extra queso, Sin cebolla" in k and "NOTA: bien cocida" in k and "(comensal 2)" in k
    assert "Refresco" not in k  # lo de la barra no sale en la cocina
    b = barra.text()
    assert "BARRA" in b and "3 x Refresco" in b and "Hamburguesa" not in b
    raw = cocina.jobs()[0]
    assert raw.startswith(b"\x1b@") and raw.endswith(b"\x1dV\x41\x03")  # inicia la impresora y termina con corte


def test_acentos_y_ene_salen_en_la_pagina_de_codigos_correcta(client, auth, printers, rest):  # noqa: F811
    p = printers()
    setup_printer(client, auth, "cocina", p)
    t = open_tab(client, auth, rest)
    add(client, auth, t, rest["burger"], 1, note="sin sal, que esté bien crudo, añadir piña")
    client.post(f"/api/tabs/{t['id']}/send", headers=auth)
    assert "piña".encode("cp858") in p.jobs()[0] and "esté".encode("cp858") in p.jobs()[0]


def test_copias_por_comanda(client, auth, printers, rest):  # noqa: F811
    p = printers()
    setup_printer(client, auth, "cocina", p, copies=2)
    t = open_tab(client, auth, rest)
    add(client, auth, t, rest["burger"], 1)
    client.post(f"/api/tabs/{t['id']}/send", headers=auth)
    assert len(p.jobs(2)) == 2


def test_estacion_sin_impresora_no_falla_y_se_ve_en_la_pantalla(client, auth, rest):  # noqa: F811
    t = order(client, auth, rest)
    r = client.post(f"/api/tabs/{t['id']}/send", headers=auth)
    assert r.status_code == 200 and all(c["printed"] is False and c["print_error"] == "" for c in r.json()["comandas"])
    assert len(client.get("/api/kitchen", headers=auth).json()["comandas"]) == 2


def test_impresora_apagada_no_frena_el_pedido_y_se_puede_reimprimir(client, auth, printers, rest):  # noqa: F811
    p = printers()
    client.put("/api/printers", json={"station": "cocina", "host": "127.0.0.1", "port": dead_port()}, headers=auth)
    t = order(client, auth, rest)
    r = client.post(f"/api/tabs/{t['id']}/send", headers=auth)
    assert r.status_code == 200, r.text  # el pedido salió aunque la impresora no responde
    cm = next(c for c in r.json()["comandas"] if c["station"] == "cocina")
    assert cm["printed"] is False and "No se pudo imprimir" in cm["print_error"]
    assert all(ln["status"] == "enviada" for ln in r.json()["tab"]["lines"])
    assert client.post(f"/api/comandas/{cm['id']}/reprint", headers=auth).status_code == 502  # sigue apagada
    setup_printer(client, auth, "cocina", p)  # se arregla la impresora
    again = client.post(f"/api/comandas/{cm['id']}/reprint", headers=auth)
    assert again.status_code == 200 and again.json()["printed"] is True and again.json()["print_error"] == ""
    assert "2 x Hamburguesa" in p.text()
    barra = next(c for c in r.json()["comandas"] if c["station"] == "barra")
    assert client.post(f"/api/comandas/{barra['id']}/reprint", headers=auth).status_code == 400  # la barra no tiene impresora
    assert client.post("/api/comandas/99999/reprint", headers=auth).status_code == 404


def test_anular_lo_enviado_imprime_el_aviso_en_la_estacion(client, auth, printers, rest):  # noqa: F811
    p = printers()
    setup_printer(client, auth, "cocina", p)
    t = open_tab(client, auth, rest)
    add(client, auth, t, rest["burger"], 1)
    sent = client.post(f"/api/tabs/{t['id']}/send", headers=auth).json()["tab"]
    client.post(f"/api/tabs/{t['id']}/lines/{sent['lines'][0]['id']}/void", json={"reason": "El cliente se fue"}, headers=auth)
    jobs = p.jobs(2)
    assert len(jobs) == 2 and "ANULADO" in jobs[1].decode("cp858") and "Hamburguesa" in jobs[1].decode("cp858")


# ───────────────────────── pantalla de cocina ─────────────────────────
def test_la_cocina_ve_sus_comandas_y_las_va_marcando(client, auth, login, rest):  # noqa: F811
    cocina = make_user(client, auth, login, "Cocina")
    mesero = make_user(client, auth, login, "Mesero")
    t = client.post("/api/tabs", json={"table_ids": [rest["mesas"]["1"]]}, headers=mesero).json()
    add(client, mesero, t, rest["burger"], 2, note="sin sal")
    add(client, mesero, t, rest["cola"], 1)
    client.post(f"/api/tabs/{t['id']}/send", headers=mesero)
    k = client.get("/api/kitchen?station=cocina", headers=cocina).json()["comandas"]
    assert len(k) == 1 and k[0]["tables"] == "1" and k[0]["status"] == "Pendiente" and k[0]["lines"][0]["note"] == "sin sal"
    assert [c["station"] for c in client.get("/api/kitchen", headers=cocina).json()["comandas"]] == ["cocina", "barra"]
    lid = k[0]["lines"][0]["id"]
    assert client.put(f"/api/kitchen/lines/{lid}/status", json={"status": "preparando"}, headers=cocina).json()["status"] == "Preparando"
    assert client.get("/api/kitchen/ready", headers=mesero).json() == []  # todavía no está listo
    assert client.put(f"/api/kitchen/lines/{lid}/status", json={"status": "listo"}, headers=cocina).json()["status"] == "Lista"
    ready = client.get("/api/kitchen/ready", headers=mesero).json()
    assert len(ready) == 1 and ready[0]["description"] == "Hamburguesa" and ready[0]["tables"] == "1" and ready[0]["tab_number"] == t["number"]
    # el mesero lo lleva a la mesa y lo marca servido; entonces sale de la pantalla
    assert client.put(f"/api/kitchen/lines/{lid}/status", json={"status": "servido"}, headers=mesero).status_code == 200
    assert client.get("/api/kitchen/ready", headers=mesero).json() == []
    assert client.get("/api/kitchen?station=cocina", headers=cocina).json()["comandas"] == []
    assert len(client.get("/api/kitchen?station=barra", headers=cocina).json()["comandas"]) == 1  # la barra sigue pendiente


def test_cada_rol_marca_solo_lo_suyo(client, auth, login, rest):  # noqa: F811
    cocina = make_user(client, auth, login, "Cocina")
    mesero = make_user(client, auth, login, "Mesero")
    cajero = make_user(client, auth, login, "Cajero")
    t = open_tab(client, auth, rest)
    add(client, auth, t, rest["burger"], 1)
    client.post(f"/api/tabs/{t['id']}/send", headers=auth)
    lid = client.get("/api/kitchen", headers=auth).json()["comandas"][0]["lines"][0]["id"]
    st = lambda who, s: client.put(f"/api/kitchen/lines/{lid}/status", json={"status": s}, headers=who).status_code
    assert st(mesero, "listo") == 403 and st(cajero, "preparando") == 403  # solo la cocina prepara
    assert st(cocina, "servido") == 403  # y solo el salón sirve
    assert st(cocina, "inventado") == 400 and st(auth, "preparando") == 200
    assert client.get("/api/kitchen", headers=cajero).status_code == 200  # el cajero ve el estado de los pedidos
    assert client.put("/api/kitchen/lines/99999/status", json={"status": "listo"}, headers=cocina).status_code == 404


def test_marcar_toda_la_comanda_y_volver_atras(client, auth, login, rest):  # noqa: F811
    cocina = make_user(client, auth, login, "Cocina")
    t = order(client, auth, rest)
    client.post(f"/api/tabs/{t['id']}/send", headers=auth)
    cm = next(c for c in client.get("/api/kitchen", headers=cocina).json()["comandas"] if c["station"] == "cocina")
    assert client.post(f"/api/kitchen/comandas/{cm['id']}/status", json={"status": "listo"}, headers=cocina).json()["status"] == "Lista"
    assert client.post(f"/api/kitchen/comandas/{cm['id']}/status", json={"status": "preparando"}, headers=cocina).json()["status"] == "Preparando"  # se equivocó: vuelve
    assert client.post("/api/kitchen/comandas/99999/status", json={"status": "listo"}, headers=cocina).status_code == 404


def test_un_producto_anulado_sale_tachado_y_una_comanda_toda_anulada_desaparece(client, auth, rest):  # noqa: F811
    t = open_tab(client, auth, rest)
    add(client, auth, t, rest["burger"], 1)
    add(client, auth, t, rest["burger"], 2, note="otra")
    sent = client.post(f"/api/tabs/{t['id']}/send", headers=auth).json()["tab"]
    a, b = sent["lines"][0]["id"], sent["lines"][1]["id"]
    client.post(f"/api/tabs/{t['id']}/lines/{a}/void", json={"reason": "Se equivocó el mesero"}, headers=auth)
    lines = client.get("/api/kitchen?station=cocina", headers=auth).json()["comandas"][0]["lines"]
    assert [(ln["voided"], ln["void_reason"]) for ln in lines] == [(True, "Se equivocó el mesero"), (False, "")]
    assert client.put(f"/api/kitchen/lines/{a}/status", json={"status": "listo"}, headers=auth).status_code == 400  # ya anulado
    client.post(f"/api/tabs/{t['id']}/lines/{b}/void", json={"reason": "Se fue el cliente"}, headers=auth)
    assert client.get("/api/kitchen?station=cocina", headers=auth).json()["comandas"] == []


def test_el_mesero_solo_ve_lo_listo_de_sus_cuentas(client, auth, login, rest):  # noqa: F811
    mesero = make_user(client, auth, login, "Mesero")
    t = open_tab(client, auth, rest, "1")  # cuenta de otra persona (Master)
    add(client, auth, t, rest["cola"], 1)
    client.post(f"/api/tabs/{t['id']}/send", headers=auth)
    lid = client.get("/api/kitchen", headers=auth).json()["comandas"][0]["lines"][0]["id"]
    client.put(f"/api/kitchen/lines/{lid}/status", json={"status": "listo"}, headers=auth)
    assert client.get("/api/kitchen/ready", headers=mesero).json() == []  # no es su cuenta
    assert len(client.get("/api/kitchen/ready", headers=auth).json()) == 1


def test_lista_de_comandas_de_una_cuenta(client, auth, rest):  # noqa: F811
    t = order(client, auth, rest)
    client.post(f"/api/tabs/{t['id']}/send", headers=auth)
    add(client, auth, t, rest["cola"], 1)
    client.post(f"/api/tabs/{t['id']}/send", headers=auth)  # segundo envío: otra comanda
    nums = sorted(c["number"] for c in client.get(f"/api/comandas?tab_id={t['id']}", headers=auth).json())
    assert nums == ["CM-000001", "CM-000002", "CM-000003"]


def test_cobrar_no_depende_de_que_la_cocina_haya_servido(client, auth, rest):  # noqa: F811
    t = open_tab(client, auth, rest)
    add(client, auth, t, rest["cola"], 1)
    client.post(f"/api/tabs/{t['id']}/send", headers=auth)
    assert client.post(f"/api/tabs/{t['id']}/pay", json={"payments": pay_all(30)}, headers=auth).json()["closed"] is True
    assert client.get("/api/kitchen", headers=auth).json()["comandas"][0]["status"] == "Pendiente"  # la cocina la ve hasta que se sirva
