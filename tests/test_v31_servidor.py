"""Modo servidor: certificados propios, HTTPS real, página de instalación por HTTP y redirección."""
import datetime
import os
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request

import pytest

from app import servidor


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_certificados_propios_validos_para_los_nombres_del_servidor(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives.asymmetric import ec
    folder = str(tmp_path / "certs")
    certs = servidor.ensure_certs(["comandia", "192.168.1.50"], folder)
    assert certs["renewed"] and certs["list"] == ["comandia", "192.168.1.50", "localhost", "127.0.0.1"]
    ca = x509.load_pem_x509_certificate(open(certs["ca_crt"], "rb").read())
    leaf = x509.load_pem_x509_certificate(open(certs["crt"], "rb").read())
    san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "comandia" in san.get_values_for_type(x509.DNSName) and "192.168.1.50" in [str(i) for i in san.get_values_for_type(x509.IPAddress)]
    assert leaf.issuer == ca.subject and ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    ca.public_key().verify(leaf.signature, leaf.tbs_certificate_bytes, ec.ECDSA(leaf.signature_hash_algorithm))  # firmado por la autoridad de Comandia
    # sin cambios no se vuelve a crear (los clientes siguen confiando); con otro nombre se renueva el servidor pero NO la autoridad
    ca_before = open(certs["ca_crt"], "rb").read()
    assert servidor.ensure_certs(["comandia", "192.168.1.50"], folder)["renewed"] is False
    again = servidor.ensure_certs(["comandia", "192.168.1.77"], folder)
    assert again["renewed"] and open(again["ca_crt"], "rb").read() == ca_before
    if os.name == "posix":
        assert oct(os.stat(certs["ca_key"]).st_mode)[-3:] == "600"


def test_servidor_https_y_pagina_de_instalacion(tmp_path):
    import uvicorn
    https_port, http_port = free_port(), free_port()
    conf = {**servidor.DEFAULTS, "escuchar": "127.0.0.1", "puerto_https": str(https_port), "puerto_http": str(http_port), "nombres": "localhost"}
    certs = servidor.ensure_certs(["localhost"], str(tmp_path / "certs"))
    httpd = servidor.start_http(conf, certs["list"], certs["ca_crt"])
    server = uvicorn.Server(servidor.build_config(conf, certs))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started
        trusted = ssl.create_default_context(cafile=certs["ca_crt"])
        with urllib.request.urlopen(f"https://localhost:{https_port}/api/health", context=trusted, timeout=5) as r:  # HTTPS verificado con la autoridad de Comandia
            assert r.status == 200
        with pytest.raises(urllib.error.URLError):  # sin instalar la autoridad, el navegador no confiaría: es lo que la página de instalación resuelve
            urllib.request.urlopen(f"https://localhost:{https_port}/api/health", context=ssl.create_default_context(), timeout=5)
        base = f"http://localhost:{http_port}"
        with urllib.request.urlopen(base + "/", timeout=5) as r:
            page = r.read().decode()
        assert "Comandia" in page and "instalar-certificado.bat" in page and f"https://localhost:{https_port}" in page
        with urllib.request.urlopen(base + "/ca.crt", timeout=5) as r:
            assert r.read() == open(certs["ca_crt"], "rb").read() and b"PRIVATE" not in open(certs["ca_crt"], "rb").read()
        with urllib.request.urlopen(base + "/instalar-certificado.bat", timeout=5) as r:
            bat = r.read().decode()
        assert "certutil -addstore -f \"Root\"" in bat and f"{base}/ca.crt" in bat and "\r\n" in bat
        for secret in ("/ca.key", "/servidor.key", "/certs/ca.key", "/../certs/ca.key"):  # la llave privada jamás se reparte
            try:
                body = urllib.request.urlopen(base + secret, timeout=5, context=trusted).read()
            except urllib.error.URLError:
                body = b""  # redirige a HTTPS y el sistema responde 404
            assert b"PRIVATE KEY" not in body
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        with pytest.raises(urllib.error.HTTPError) as err:
            opener.open(base + "/api/health", timeout=5)
        assert err.value.code == 301 and err.value.headers["Location"] == f"https://localhost:{https_port}/api/health"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if httpd:
            httpd.shutdown()


def test_configuracion_y_nombres(tmp_path):
    path = str(tmp_path / "servidor.conf")
    servidor.write_conf({"nombres": "Comandia, 192.168.1.5;caja1", "puerto_https": "8443", "puerto_http": "8080", "escuchar": "0.0.0.0"}, path)
    conf = servidor.read_conf(path)
    assert conf["puerto_https"] == "8443" and servidor.split_names(conf["nombres"]) == ["comandia", "192.168.1.5", "caja1"]
    assert servidor.read_conf(str(tmp_path / "no-existe.conf"))["puerto_https"] == "443"
    assert servidor.detect_names()  # al menos el nombre del equipo


def test_setup_mysql_enter_usa_el_valor_por_defecto(monkeypatch):
    """Pulsar Enter en Usuario/Servidor/Base debe tomar el valor entre corchetes (antes quedaba vacío y MySQL usaba el usuario de Windows)."""
    from app import setup_mysql
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    assert setup_mysql.ask("Usuario", "root") == "root"
    assert setup_mysql.ask("Base", "comandia") == "comandia"
    monkeypatch.setattr("builtins.input", lambda prompt="": "  otra ")
    assert setup_mysql.ask("Usuario", "root") == "otra"
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "")
    assert setup_mysql.ask("Clave", "", secret=True) == ""
