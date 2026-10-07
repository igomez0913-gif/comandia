"""Prueba de humo de la interfaz en un navegador real: arranca el servidor con un restaurante de demostración y recorre un servicio completo
(abrir cuenta, pedir con descriptivos, enviar a cocina, marcar listo, servir y cobrar) más el diseño del plano y los roles.
Se omite sola si no hay Playwright o Chromium instalados."""
import glob
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import pytest

sync_api = pytest.importorskip("playwright.sync_api")


def _chromium():
    for pattern in ("/opt/pw-browsers/chromium-*/chrome-linux/chrome", os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux/chrome")):
        found = sorted(glob.glob(pattern))
        if found:
            return found[-1]
    return None


pytestmark = pytest.mark.skipif(_chromium() is None, reason="no hay Chromium instalado")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def server():
    tmp = tempfile.mkdtemp(prefix="comandia-ui-")
    port = _free_port()
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp}/ui.db", "COMANDIA_SECRET": "ui-secret", "COMANDIA_BACKUP_SCHEDULER": "0", "COMANDIA_LOGS": f"{tmp}/logs",
           "COMANDIA_MARCA": f"{tmp}/marca", "COMANDIA_DEMO": "restaurante"}
    env.pop("TEST_DATABASE_URL", None)
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            urllib.request.urlopen(base + "/api/health", timeout=1)
            break
        except OSError:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("el servidor de la prueba no arrancó")
    yield base
    proc.terminate()
    proc.wait(timeout=10)


def _api(base, path, body=None, token=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    return json.loads(urllib.request.urlopen(req).read() or b"{}")


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch(executable_path=_chromium())
        yield b
        b.close()


def _page(browser, w=1400, h=950):
    pg = browser.new_context(viewport={"width": w, "height": h}).new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)[:300]))
    pg.on("console", lambda m: pg.errors.append(m.text[:300]) if m.type == "error" and "status of 4" not in m.text else None)  # los 4xx esperados (PIN malo…) no cuentan
    return pg


def _login(pg, base, email="luis@miempresa.hn", password="comandia123"):
    pg.goto(base)
    pg.fill("#email", email)
    pg.fill("#password", password)
    pg.click("#login-form button[type=submit]")
    pg.wait_for_selector("#shell:not(.hidden)")
    pg.wait_for_timeout(900)  # que termine de cargar la pantalla inicial antes de navegar


def test_un_servicio_completo_desde_la_pantalla(server, browser):
    pg = _page(browser)
    _login(pg, server)
    pg.click('[data-view="salon"]')
    pg.wait_for_selector(".fi.mesa")
    pg.click('.fi.mesa[data-table]:has(strong:text-is("2"))')
    pg.wait_for_selector("#modal.open")
    pg.fill("input[name=guests]", "2")
    pg.click("#modal-form button[type=submit]")
    pg.wait_for_selector(".tab-head")
    # el menú se mantiene abierto al agregar productos
    pg.click('.menu-deps [data-dep]:has-text("Hamburguesas")')
    pg.click('.menu-item:has-text("Hamburguesa clásica")')
    pg.wait_for_selector("#modal.open .dsc")
    pg.click('.dsc:has-text("Extra queso")')
    pg.click("#aq-p")
    pg.fill("input[name=note]", "bien cocida")
    pg.select_option("select[name=guest]", "2")
    pg.click("#modal-form button[type=submit]")
    pg.wait_for_selector(".tline")
    pg.click('.menu-deps [data-dep]:has-text("Bebidas")')
    pg.click('.menu-item:has-text("Refresco")')
    pg.wait_for_selector("#modal.open")
    pg.click("#modal-form button[type=submit]")
    pg.wait_for_selector(".tline >> nth=1")
    assert pg.inner_text(".tab-total strong").replace(" ", " ") == "L 335.00"  # 2 × (135 + 15 de extra queso) + 35
    pg.click("#t-send")
    pg.wait_for_selector(".pill:has-text('Esperando')")
    # la cocina ve la comanda con sus detalles y la marca lista
    pg.click('[data-view="cocina"]')
    pg.wait_for_selector(".kt")
    assert pg.locator(".kt").count() == 2
    assert "bien cocida" in pg.inner_text('.kt:has-text("Hamburguesa")') and "Extra queso" in pg.inner_text('.kt:has-text("Hamburguesa")')
    pg.click('.kt:has-text("Hamburguesa") [data-all][data-to=listo]')
    pg.wait_for_timeout(600)
    # el salón avisa que está listo; se sirve y se cobra
    pg.click('[data-view="salon"]')
    pg.wait_for_selector(".ready-bar")
    assert "Hamburguesa clásica" in pg.inner_text(".ready-bar")
    pg.click(".ready-chip")
    pg.wait_for_timeout(600)
    pg.click(".fi.mesa.ocupada")
    pg.click("#t-pay")
    pg.wait_for_selector("#pay-methods .pm-row")
    assert pg.inner_text("#pay-total").replace(" ", " ") == "L 335.00" and pg.input_value("#tip") == "33.50"
    pg.fill("#recv", "500")
    pg.wait_for_timeout(100)
    assert "165.00" in pg.inner_text("#pay-change")
    pg.click("#modal-form button[type=submit]")
    pg.wait_for_timeout(1500)
    assert pg.locator(".fi.mesa.ocupada").count() == 0  # la mesa quedó libre
    assert pg.errors == []


def test_cobro_mixto_con_cuenta_de_banco_desde_la_pantalla(server, browser):
    pg = _page(browser)
    _login(pg, server)
    pg.click('[data-view="salon"]')
    pg.wait_for_selector(".fi.mesa")
    pg.click('.fi.mesa[data-table]:has(strong:text-is("1"))')
    pg.wait_for_selector("#modal.open")
    pg.click("#modal-form button[type=submit]")
    pg.wait_for_selector(".tab-head")
    pg.click('.menu-deps [data-dep]:has-text("Hamburguesas")')
    pg.click('.menu-item:has-text("Hamburguesa clásica")')
    pg.wait_for_selector("#modal.open")
    pg.click("#modal-form button[type=submit]")
    pg.wait_for_selector(".tline")
    pg.click("#t-send")
    pg.wait_for_selector(".pill:has-text('Esperando')")
    pg.click("#t-pay")
    pg.wait_for_selector("#pay-methods .pm-row")
    assert pg.locator(".pm-row .pm-extra:not(.hidden)").count() == 0  # el efectivo no pide cuenta ni referencia
    pg.click("#pay-split")  # segunda forma de pago: tarjeta
    pg.fill(".pm-row:nth-child(1) input[type=number]", "35")
    pg.fill(".pm-row:nth-child(2) input[type=number]", "100")
    assert pg.locator(".pm-row:nth-child(2) .pm-extra:not(.hidden)").count() == 1  # la tarjeta sí
    pg.select_option(".pm-row:nth-child(2) .pm-bank", label="Banco (tarjetas y transferencias)")
    pg.fill(".pm-row:nth-child(2) .pm-ref", "Aut 4471")
    pg.wait_for_timeout(150)
    assert "Falta" not in pg.inner_text("#pay-change") and "Sobra" not in pg.inner_text("#pay-change")  # 35 + 100 = 135
    pg.click("#modal-form button[type=submit]")
    pg.wait_for_timeout(1500)
    token = _api(server, "/api/auth/login", {"email": "luis@miempresa.hn", "password": "comandia123"})["token"]
    bancos = {b["name"]: b["balance"] for b in _api(server, "/api/banks", token=token)["banks"]}
    assert bancos["Banco (tarjetas y transferencias)"] == 100.0 and bancos["Caja general"] == 0.0  # solo lo electrónico entra al banco
    assert pg.errors == []


def _abrir_cuenta(pg, mesa, comensales):
    pg.click(f'.fi.mesa[data-table]:has(strong:text-is("{mesa}"))')
    pg.wait_for_selector("#modal.open")
    pg.fill("input[name=guests]", str(comensales))
    pg.click("#modal-form button[type=submit]")
    pg.wait_for_selector(".tab-head")


def _agregar(pg, familia, producto):
    pg.click(f'.menu-deps [data-dep]:has-text("{familia}")')
    pg.click(f'.menu-item:has-text("{producto}")')
    pg.wait_for_selector("#modal.open")
    pg.click("#modal-form button[type=submit]")  # sin descriptivos: se agrega tal cual
    pg.wait_for_selector(f'.tline:has-text("{producto}")')


def test_dividir_un_plato_reasignar_comensal_y_cobrar_uno_por_uno(server, browser):
    pg = _page(browser)
    _login(pg, server)
    pg.click('[data-view="salon"]')
    pg.wait_for_selector(".fi.mesa")
    _abrir_cuenta(pg, "4", 3)
    _agregar(pg, "Entradas", "Alitas BBQ")  # L 165
    _agregar(pg, "Bebidas", "Refresco")  # L 35
    pg.click("#t-send")
    pg.wait_for_selector(".pill:has-text('Esperando')")
    # el plato se comparte entre los tres comensales aunque ya está en cocina
    pg.click('.tline:has-text("Alitas BBQ") [data-split]')
    pg.wait_for_selector("#modal.open .split-row")
    assert "55.00" in pg.inner_text("#modal .split-row >> nth=0")  # 165 entre 3, con el reparto a la vista antes de confirmar
    pg.click("#modal-form button[type=submit]")
    pg.wait_for_selector(".tl-sub.part")
    assert pg.locator(".tl-sub.part").count() == 3 and "1/3" in pg.inner_text(".tl-sub.part >> nth=0")
    # el refresco pasa al comensal 2 aunque ya se envió
    pg.select_option('.tline:has-text("Refresco") .guest-sel', "2")
    pg.wait_for_selector('.guest-head:has-text("Comensal 2"):has-text("90.00")')  # 55 de su parte de las alitas + 35 del refresco
    # se cobra comensal por comensal y el sistema ofrece seguir con el siguiente
    pg.click("#t-pay")
    pg.wait_for_selector("#pay-methods .pm-row")
    pg.click("input[name=scope][value=guest]")
    pg.select_option("select[name=guest]", "1")
    pg.wait_for_timeout(150)
    assert pg.inner_text("#pay-total").replace("\u00a0", " ") == "L 55.00"
    pg.click("#modal-form button[type=submit]")
    for guest, total in ((2, "L 90.00"), (3, "L 55.00")):
        pg.wait_for_selector("#cf-yes")
        assert f"comensal {guest}" in pg.inner_text("#modal-form").lower()
        pg.click("#cf-yes")
        pg.wait_for_selector("#pay-methods .pm-row")
        if guest == 2:  # con dos comensales por cobrar ya viene seleccionado el que sigue; cuando solo queda uno, «toda la cuenta» es ese comensal
            assert pg.is_checked("input[name=scope][value=guest]") and pg.input_value("select[name=guest]") == str(guest)
        pg.wait_for_timeout(150)
        assert pg.inner_text("#pay-total").replace("\u00a0", " ") == total
        pg.click("#modal-form button[type=submit]")
    pg.wait_for_timeout(1200)
    assert pg.locator('.fi.mesa.ocupada:has(strong:text-is("4"))').count() == 0  # cuenta cerrada y mesa libre
    assert pg.errors == []


def test_dividir_toda_la_cuenta_y_repartir_el_pago_entre_dos(server, browser):
    pg = _page(browser)
    _login(pg, server)
    pg.click('[data-view="salon"]')
    pg.wait_for_selector(".fi.mesa")
    _abrir_cuenta(pg, "5", 2)
    pg.click('.menu-deps [data-dep]:has-text("Hamburguesas")')
    pg.click('.menu-item:has-text("Hamburguesa clásica")')
    pg.wait_for_selector("#modal.open")
    pg.click("#modal-form button[type=submit]")
    pg.wait_for_selector('.tline:has-text("Hamburguesa clásica")')
    _agregar(pg, "Bebidas", "Refresco")
    pg.click("#t-send")
    pg.wait_for_selector(".pill:has-text('Esperando')")
    pg.click(".more > summary")
    pg.click('[data-more="equal"]')
    pg.wait_for_selector("#modal.open input[name=parts]")
    pg.fill("input[name=parts]", "2")
    pg.click("#modal-form button[type=submit]")
    pg.wait_for_selector(".guest-head >> nth=1")
    heads = pg.locator(".guest-head").all_inner_texts()
    assert len(heads) == 2 and all("85.00" in h for h in heads)  # L 170 entre dos: L 85 cada uno
    # un solo comprobante pagado entre dos personas: el pago se reparte en dos filas iguales
    pg.click("#t-pay")
    pg.wait_for_selector("#pay-methods .pm-row")
    pg.fill("#pay-n", "2")
    pg.click("#pay-eq")
    pg.wait_for_timeout(150)
    assert pg.locator(".pm-row").count() == 2 and [pg.input_value(f".pm-row:nth-child({i}) input[type=number]") for i in (1, 2)] == ["85.00", "85.00"]
    pg.click("#modal-form button[type=submit]")
    pg.wait_for_timeout(1200)
    assert pg.locator('.fi.mesa.ocupada:has(strong:text-is("5"))').count() == 0
    assert pg.errors == []


def test_enter_en_repartir_no_cobra_y_un_plato_con_partes_cobradas_no_ofrece_lo_que_falla(server, browser):
    pg = _page(browser)
    _login(pg, server)
    pg.click('[data-view="salon"]')
    pg.wait_for_selector(".fi.mesa")
    _abrir_cuenta(pg, "6", 3)
    _agregar(pg, "Entradas", "Alitas BBQ")
    pg.click("#t-send")
    pg.wait_for_selector(".pill:has-text('Esperando')")
    pg.click('.tline:has-text("Alitas BBQ") [data-split]')
    pg.wait_for_selector("#modal.open .split-row")
    pg.click("#modal-form button[type=submit]")
    pg.wait_for_selector(".tl-sub.part")
    # Enter en «repartir el pago entre N personas» reparte; no debe cobrar ni cerrar la cuenta
    pg.click("#t-pay")
    pg.wait_for_selector("#pay-methods .pm-row")
    pg.fill("#pay-n", "3")
    pg.press("#pay-n", "Enter")
    pg.wait_for_timeout(700)
    assert pg.locator("#modal.open").count() == 1 and pg.locator(".pm-row").count() == 3
    assert pg.locator('.fi.mesa.ocupada:has(strong:text-is("6"))').count() == 1  # la cuenta sigue abierta
    pg.keyboard.press("Escape")
    pg.click("#dc-yes")  # «cerrar sin guardar»: se escribió en el formulario
    pg.wait_for_selector("#modal:not(.open)", state="attached")
    # se cobra el comensal 1: del plato compartido ya no se puede juntar ni pasar a otra mesa, y anular quita lo que falta
    pg.click("#t-pay")
    pg.wait_for_selector("#pay-methods .pm-row")
    pg.click("input[name=scope][value=guest]")
    pg.select_option("select[name=guest]", "1")
    pg.wait_for_timeout(150)
    pg.click("#modal-form button[type=submit]")
    pg.wait_for_selector("#cf-no")
    pg.click("#cf-no")
    pg.wait_for_selector('.tline.enviada:has-text("Alitas BBQ")')
    assert pg.locator("[data-join]").count() == 0
    pg.click(".more > summary")
    assert pg.locator('[data-more="unsplit"]').count() == 0 and pg.is_disabled('[data-more="equal"]')
    pg.click(".more > summary")
    pg.click('.tline.enviada:has-text("Alitas BBQ") >> nth=0 >> [data-void]')
    pg.wait_for_selector("#modal.open input[name=reason]")
    assert "plato compartido" in pg.inner_text("#modal-form").lower()
    pg.fill("input[name=reason]", "Se fueron sin pagar")
    pg.click("#modal-form button[type=submit]")
    pg.wait_for_timeout(1200)
    assert pg.locator('.fi.mesa.ocupada:has(strong:text-is("6"))').count() == 0  # ya no quedaba nada por cobrar: la cuenta se cerró y la mesa quedó libre
    assert pg.errors == []


def test_una_respuesta_vieja_no_pisa_la_mesa_que_el_mesero_acaba_de_tocar(server, browser):
    pg = _page(browser)
    _login(pg, server)
    pg.click('[data-view="salon"]')
    pg.wait_for_selector(".fi.mesa")
    _abrir_cuenta(pg, "7", 2)
    id_a = pg.evaluate("SALON.tab.id")
    _abrir_cuenta(pg, "8", 2)
    pg.click('.fi.mesa[data-table]:has(strong:text-is("7"))')
    pg.wait_for_selector('.tab-head h3:has-text("Mesa 7")')
    # la red tarda en contestar por la cuenta 7 (el temporizador de refresco ya la había pedido) y mientras tanto el mesero toca la mesa 8
    pg.evaluate("(A) => { const f = window.fetch; window.fetch = (u, o) => (String(u).endsWith('/api/tabs/' + A) && !(o && o.method) ? new Promise((r) => setTimeout(r, 900)).then(() => f(u, o)) : f(u, o)); }", id_a)
    pg.evaluate("() => { window.__refresh = refreshSalon(); }")
    pg.wait_for_timeout(250)
    pg.click('.fi.mesa[data-table]:has(strong:text-is("8"))')
    pg.wait_for_selector('.tab-head h3:has-text("Mesa 8")')
    pg.wait_for_timeout(1600)  # llega la respuesta vieja
    assert "Mesa 8" in pg.inner_text(".tab-head h3")  # antes el panel volvía a la mesa 7
    assert pg.errors == []


def test_disenar_el_plano_arrastrar_y_guardar(server, browser):
    pg = _page(browser)
    _login(pg, server)
    pg.click('[data-view="restaurante"]')
    pg.wait_for_selector("#pl-size")
    pg.click('[data-preset="mesa4"]')
    pg.wait_for_selector("#pl-props .props")
    pg.fill('[data-p="name"]', "VIP1")
    pg.fill('[data-p="seats"]', "6")
    pg.dispatch_event('[data-p="seats"]', "change")
    box = pg.locator("#pl-size .fi.edit.sel").bounding_box()
    pg.mouse.move(box["x"] + 20, box["y"] + 20)
    pg.mouse.down()
    pg.mouse.move(box["x"] + 300, box["y"] + 250, steps=8)
    pg.mouse.up()
    pg.wait_for_timeout(200)
    assert (int(pg.input_value('[data-p="x"]')), int(pg.input_value('[data-p="y"]'))) != (40, 40)  # se movió aunque se editó antes
    pg.click("#pl-save")
    pg.wait_for_timeout(900)
    names = [i["name"] for s in _api(server, "/api/salons", token=_api(server, "/api/auth/login", {"email": "luis@miempresa.hn", "password": "comandia123"})["token"]) for i in s["items"]]
    assert "VIP1" in names
    pg.click('[data-rt="recetas"]')
    pg.click('tr:has-text("Hamburguesa clásica") [data-recipe]')
    pg.wait_for_selector(".rc-row")
    assert pg.locator(".rc-row").count() == 5 and "L" in pg.inner_text("#rc-cost")
    assert pg.errors == []


def test_cada_rol_ve_solo_lo_suyo(server, browser):
    token = _api(server, "/api/auth/login", {"email": "luis@miempresa.hn", "password": "comandia123"})["token"]
    for role, name in (("Mesero", "Marta Mesera"), ("Cocina", "Carlos Cocina")):
        _api(server, "/api/users", {"name": name, "email": f"{role.lower()}@miempresa.hn", "password": "clave12345", "role": role}, token)
    mesero = _page(browser)
    _login(mesero, server, "mesero@miempresa.hn", "clave12345")
    assert mesero.evaluate("view") == "salon"  # el mesero entra directo al salón
    assert mesero.locator("#t-pay").count() == 0
    assert set(mesero.locator(".nav-btn:visible").all_inner_texts()) >= {"Salón", "Cocina y barra"} and "Inventario" not in mesero.locator(".nav-btn:visible").all_inner_texts()
    cocina = _page(browser)
    _login(cocina, server, "cocina@miempresa.hn", "clave12345")
    assert cocina.evaluate("view") == "cocina"
    assert [t.strip() for t in cocina.locator(".nav-btn:visible").all_inner_texts()] == ["Cocina y barra"]
    assert mesero.errors == [] and cocina.errors == []


def test_en_el_telefono_las_mesas_son_botones_grandes(server, browser):
    pg = _page(browser, 390, 844)
    _login(pg, server)
    pg.click('[data-view="salon"]')
    pg.wait_for_selector(".tg")
    assert pg.locator(".tg").count() >= 8 and pg.locator(".fi.mesa").count() == 0
    assert pg.errors == []
