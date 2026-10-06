"""Envío de correos por SMTP (Gmail, Outlook/Office 365, el correo del hosting, etc.)."""
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


def parse_addresses(text: str) -> list:
    """«a@x.com, b@y.com; c@z.com» → lista. Lanza ValueError con la dirección que no sirve."""
    out = []
    for part in re.split(r"[,;\s]+", text or ""):
        part = part.strip()
        if not part:
            continue
        if not EMAIL_RE.match(part):
            raise ValueError(f"Correo no válido: {part}")
        if part.lower() not in {x.lower() for x in out}:
            out.append(part)
    return out


def send_mail(cfg: dict, to: list, subject: str, text: str, cc: list = (), reply_to: str = "", attachments: list = ()):
    """cfg: host, port, user, password, from_email, from_name, security (starttls | ssl | none)."""
    if not cfg.get("host") or not cfg.get("from_email"):
        raise ValueError("Falta configurar el correo de salida (Configuración › Correo)")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg.get("from_name") or "", cfg["from_email"]))
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(text)
    for name, data, mime in attachments:
        main, sub = mime.split("/", 1)
        msg.add_attachment(data, maintype=main, subtype=sub, filename=name)
    port = int(cfg.get("port") or (465 if cfg.get("security") == "ssl" else 587))
    context = ssl.create_default_context()
    if cfg.get("security") == "ssl":
        server = smtplib.SMTP_SSL(cfg["host"], port, timeout=30, context=context)
    else:
        server = smtplib.SMTP(cfg["host"], port, timeout=30)
    try:
        server.ehlo()
        if cfg.get("security", "starttls") == "starttls":
            server.starttls(context=context)
            server.ehlo()
        if cfg.get("user"):
            server.login(cfg["user"], cfg.get("password") or "")
        server.send_message(msg, to_addrs=list(to) + list(cc))
    finally:
        try:
            server.quit()
        except Exception:  # noqa: BLE001
            pass


def friendly_error(exc: Exception) -> str:
    """Mensaje entendible para los errores típicos de SMTP."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "El servidor de correo rechazó el usuario o la clave. En Gmail u Outlook usa una «contraseña de aplicación»."
    if isinstance(exc, (smtplib.SMTPConnectError, ConnectionRefusedError, TimeoutError, OSError)) and not isinstance(exc, smtplib.SMTPException):
        return f"No se pudo conectar con el servidor de correo ({exc}). Revisa el servidor, el puerto y la conexión a internet."
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "El servidor de correo rechazó la dirección del destinatario."
    return f"No se pudo enviar el correo: {exc}"
