"""Los atajos de teclado viven en static/atajos.js: debe existir, cargarse desde la página y ofrecerse sin sesión."""


def test_atajos_se_cargan_con_la_pagina(client):
    page = client.get("/").text
    assert "/static/atajos.js" in page and 'id="help-keys"' in page
    js = client.get("/static/atajos.js")
    assert js.status_code == 200 and "ATAJOS" in js.text and "showShortcuts" in js.text
