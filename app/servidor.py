"""Modo servidor de Comandia: varias computadoras de la red local entran por el navegador a un solo equipo.

- Atiende por HTTPS (el navegador solo deja funcionar las ventas sin conexión y la instalación como app con HTTPS).
- Crea solo los certificados: una «autoridad» propia de Comandia (la misma de por vida) y el certificado del servidor,
  que vale para el nombre y las IP del equipo. Cada computadora instala UNA vez la autoridad y no vuelve a ver avisos.
- Un segundo puerto HTTP (80) solo reparte la página de instalación y el certificado público; todo lo demás lo manda a HTTPS.

Uso:
    python comandia_cmd.py servidor              inicia el servidor (lo que ejecuta el servicio de Windows)
    python comandia_cmd.py servidor certs        crea o renueva los certificados con los nombres de servidor.conf
    python comandia_cmd.py servidor info         muestra la configuración y las direcciones para los clientes

La configuración está en `servidor.conf` (junto a database.url): nombres, puerto_https, puerto_http, escuchar.
"""
import datetime
import ipaddress
import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import urlsplit

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF_FILE = os.path.join(BASE_DIR, "servidor.conf")
CERT_DIR = os.path.join(BASE_DIR, "certs")
CA_DAYS = 3650
SERVER_DAYS = 825
RENEW_BEFORE_DAYS = 60

DEFAULTS = {"nombres": "", "puerto_https": "443", "puerto_http": "80", "escuchar": "0.0.0.0"}


# ───────── configuración ─────────
def read_conf(path: str = CONF_FILE) -> dict:
    conf = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8-sig") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith(("#", ";")) or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                conf[key.strip().lower()] = value.strip()
    except OSError:
        pass
    return conf


def write_conf(conf: dict, path: str = CONF_FILE):
    lines = ["# Configuración del servidor de Comandia. Después de cambiar los nombres, ejecuta servidor\\renovar-certificado.bat",
             f"nombres={conf.get('nombres', '')}", f"puerto_https={conf.get('puerto_https', '443')}", f"puerto_http={conf.get('puerto_http', '80')}",
             f"escuchar={conf.get('escuchar', '0.0.0.0')}"]
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")


def split_names(text: str) -> list:
    seen, out = set(), []
    for item in (text or "").replace(";", ",").replace(" ", ",").split(","):
        item = item.strip().lower()
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def detect_names() -> list:
    """Nombre del equipo y sus direcciones IPv4 de red (la que sale hacia la red local primero)."""
    names = []
    host = socket.gethostname().lower()
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("10.255.255.255", 1))  # no envía nada: solo averigua por qué tarjeta saldría
        names.append(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    names.append(host)
    try:
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in names:
                names.append(ip)
    except OSError:
        pass
    return [n for n in names if n and n != "0.0.0.0"]


# ───────── certificados ─────────
def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def _write_key(path: str, key):
    from cryptography.hazmat.primitives import serialization
    with open(path, "wb") as handle:
        handle.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _write_cert(path: str, cert):
    from cryptography.hazmat.primitives import serialization
    with open(path, "wb") as handle:
        handle.write(cert.public_bytes(serialization.Encoding.PEM))


def ensure_certs(names: list, folder: str = CERT_DIR) -> dict:
    """Crea (o renueva si cambiaron los nombres o falta poco para que venza) los certificados. Devuelve las rutas."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    names = split_names(",".join(names)) or detect_names()
    names = split_names(",".join(names + ["localhost", "127.0.0.1"]))
    os.makedirs(folder, exist_ok=True)
    paths = {"ca_key": os.path.join(folder, "ca.key"), "ca_crt": os.path.join(folder, "ca.crt"),
             "key": os.path.join(folder, "servidor.key"), "crt": os.path.join(folder, "servidor.crt"), "names": os.path.join(folder, "nombres.txt")}

    if not (os.path.exists(paths["ca_key"]) and os.path.exists(paths["ca_crt"])):  # la autoridad se crea una sola vez
        ca_key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Comandia"), x509.NameAttribute(NameOID.COMMON_NAME, f"Comandia · autoridad de {socket.gethostname()}")])
        ca = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(_now() - datetime.timedelta(days=1)).not_valid_after(_now() + datetime.timedelta(days=CA_DAYS))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False, key_encipherment=False, data_encipherment=False,
                                           key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
              .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
              .sign(ca_key, hashes.SHA256()))
        _write_key(paths["ca_key"], ca_key)
        _write_cert(paths["ca_crt"], ca)

    previous = ""
    try:
        with open(paths["names"], encoding="utf-8") as handle:
            previous = handle.read().strip()
    except OSError:
        pass
    wanted = ",".join(names)
    renew = previous != wanted or not (os.path.exists(paths["key"]) and os.path.exists(paths["crt"]))
    if not renew:
        with open(paths["crt"], "rb") as handle:
            current = x509.load_pem_x509_certificate(handle.read())
        renew = current.not_valid_after_utc - _now() < datetime.timedelta(days=RENEW_BEFORE_DAYS)
    if renew:
        with open(paths["ca_key"], "rb") as handle:
            ca_key = serialization.load_pem_private_key(handle.read(), None)
        with open(paths["ca_crt"], "rb") as handle:
            ca = x509.load_pem_x509_certificate(handle.read())
        alt = []
        for name in names:
            try:
                alt.append(x509.IPAddress(ipaddress.ip_address(name)))
            except ValueError:
                alt.append(x509.DNSName(name))
        key = ec.generate_private_key(ec.SECP256R1())
        cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])])).issuer_name(ca.subject).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(_now() - datetime.timedelta(days=1)).not_valid_after(_now() + datetime.timedelta(days=SERVER_DAYS))
                .add_extension(x509.SubjectAlternativeName(alt), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False, content_commitment=False, data_encipherment=False, key_agreement=True, key_cert_sign=False,
                                             crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
                .sign(ca_key, hashes.SHA256()))
        _write_key(paths["key"], key)
        _write_cert(paths["crt"], cert)
        with open(paths["names"], "w", encoding="utf-8") as handle:
            handle.write(wanted + "\n")
    paths["renewed"] = renew
    paths["list"] = names
    return paths


# ───────── puerto HTTP: página de instalación del certificado ─────────
def _public_name(host_header: str, names: list) -> str:
    host = (host_header or "").split(":")[0].strip().lower().strip("[]")
    return host if host in names else (names[0] if names else host or "localhost")


def install_page(host: str, https_url: str, http_base: str) -> str:
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Comandia · conectar este equipo</title><style>
body{{font-family:Arial,Helvetica,sans-serif;max-width:720px;margin:32px auto;padding:0 16px;color:#16241e;line-height:1.5}}
h1{{color:#1f6f4a}} .box{{border:1px solid #cfe0d6;border-radius:10px;padding:16px 18px;margin:14px 0;background:#f6faf7}}
a.btn{{display:inline-block;background:#1f6f4a;color:#fff;padding:10px 16px;border-radius:8px;text-decoration:none;margin:4px 6px 4px 0}} code{{background:#eef3ef;padding:1px 5px;border-radius:4px}}
</style></head><body><h1>Comandia</h1><p>Esta es la computadora servidor de <strong>{host}</strong>. Para usar el sistema desde este equipo hay que hacer <strong>una sola vez</strong> estos dos pasos.</p>
<div class="box"><h3>1. Confiar en el certificado de Comandia</h3>
<p><strong>Windows (Chrome o Edge):</strong> descarga y ejecuta el instalador, acepta el aviso de administrador.</p>
<a class="btn" href="{http_base}/instalar-certificado.bat">Instalar certificado (Windows)</a><a class="btn" href="{http_base}/ca.crt">Solo descargar el certificado</a>
<p class="small">Si no puedes ejecutar el .bat: abre <code>ca.crt</code>, «Instalar certificado», «Equipo local», «Colocar todos los certificados en el siguiente almacén» → <em>Entidades de certificación raíz de confianza</em>.
<br><strong>Firefox:</strong> Ajustes → Privacidad y seguridad → Certificados → Ver certificados → Autoridades → Importar <code>ca.crt</code> y marca «Confiar en esta CA para identificar sitios web».</p></div>
<div class="box"><h3>2. Abrir el sistema</h3><a class="btn" href="{https_url}">Abrir Comandia</a>
<p>Guarda esa dirección como favorito o crea un acceso directo en el escritorio: <code>{https_url}</code></p></div>
</body></html>"""


def install_bat(host: str, http_base: str) -> str:
    lines = [
        "@echo off", "title Comandia - instalar certificado", "net session >nul 2>&1",
        "if errorlevel 1 (", "  echo Se necesitan permisos de administrador. Acepta el aviso que aparece.",
        "  powershell -NoProfile -Command \"Start-Process -FilePath '%~f0' -Verb RunAs\"", "  exit /b", ")",
        f"powershell -NoProfile -Command \"[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -UseBasicParsing -Uri '{http_base}/ca.crt' -OutFile ($env:TEMP + '\\comandia-ca.crt')\"",
        "if errorlevel 1 ( echo No se pudo descargar el certificado. Revisa que el servidor este encendido. & pause & exit /b 1 )",
        "certutil -addstore -f \"Root\" \"%TEMP%\\comandia-ca.crt\"",
        "if errorlevel 1 ( echo No se pudo instalar el certificado. & pause & exit /b 1 )",
        f"echo.", f"echo Listo. Cierra y vuelve a abrir el navegador y entra a https://{host}", "pause",
    ]
    return "\r\n".join(lines) + "\r\n"


def make_http_handler(conf: dict, names: list, ca_path: str):
    https_port = int(conf.get("puerto_https", 443))

    class Handler(BaseHTTPRequestHandler):
        server_version = "Comandia"

        def log_message(self, *args):  # sin ruido en el registro
            pass

        def _send(self, code: int, body: bytes, ctype: str, extra: Optional[dict] = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _urls(self):
            host = _public_name(self.headers.get("Host", ""), names)
            http_port = self.server.server_address[1]
            http_base = f"http://{host}" + ("" if http_port == 80 else f":{http_port}")
            https_url = f"https://{host}" + ("" if https_port == 443 else f":{https_port}")
            return host, http_base, https_url

        def do_GET(self):
            path = urlsplit(self.path).path
            host, http_base, https_url = self._urls()
            if path == "/ca.crt":
                with open(ca_path, "rb") as handle:
                    self._send(200, handle.read(), "application/x-x509-ca-cert", {"Content-Disposition": 'attachment; filename="comandia-ca.crt"'})
            elif path == "/instalar-certificado.bat":
                self._send(200, install_bat(host, http_base).encode("utf-8"), "application/octet-stream", {"Content-Disposition": 'attachment; filename="instalar-certificado.bat"'})
            elif path in ("/", "/index.html", "/conectar"):
                self._send(200, install_page(host, https_url, http_base).encode("utf-8"), "text/html; charset=utf-8")
            else:  # cualquier otra cosa: al sistema, por HTTPS
                self._send(301, b"", "text/plain", {"Location": https_url + self.path})

        do_HEAD = do_GET

    return Handler


def start_http(conf: dict, names: list, ca_path: str):
    """Inicia el puerto de instalación (HTTP) en un hilo. Devuelve el servidor, o None si el puerto está ocupado."""
    try:
        httpd = ThreadingHTTPServer((conf.get("escuchar", "0.0.0.0"), int(conf.get("puerto_http", 80))), make_http_handler(conf, names, ca_path))
    except OSError as exc:
        print(f"AVISO: no se pudo abrir el puerto HTTP {conf.get('puerto_http')} ({exc}). El sistema funciona igual; solo falta la página de instalación.")
        return None
    threading.Thread(target=httpd.serve_forever, name="pagina-instalacion", daemon=True).start()
    return httpd


# ───────── arranque ─────────
def build_config(conf: dict, certs: dict):
    import uvicorn
    return uvicorn.Config("app.main:app", host=conf.get("escuchar", "0.0.0.0"), port=int(conf.get("puerto_https", 443)),
                          ssl_keyfile=certs["key"], ssl_certfile=certs["crt"], log_level="info", proxy_headers=False, timeout_keep_alive=30)


def main(argv: Optional[list] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    conf = read_conf()
    command = argv[0] if argv else "servir"
    names = split_names(conf.get("nombres", "")) or detect_names()
    if command == "certs":
        certs = ensure_certs(names)
        print(("Certificados creados o renovados para: " if certs["renewed"] else "Los certificados ya estaban al día para: ") + ", ".join(certs["list"]))
        return 0
    if command == "info":
        print(f"Nombres: {', '.join(names)}\nHTTPS: puerto {conf['puerto_https']} · HTTP (instalación): puerto {conf['puerto_http']} · escucha en {conf['escuchar']}")
        port = "" if conf["puerto_https"] == "443" else f":{conf['puerto_https']}"
        for name in names:
            print(f"  https://{name}{port}")
        return 0
    if command != "servir":
        print(__doc__)
        return 2
    import uvicorn
    certs = ensure_certs(names)
    start_http(conf, certs["list"], certs["ca_crt"])
    print(f"Comandia (servidor) en https://{certs['list'][0]} · puerto {conf['puerto_https']}")
    uvicorn.Server(build_config(conf, certs)).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
