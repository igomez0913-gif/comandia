"""Registro (logs) de Comandia: archivos que rotan solos, sin repetir cada línea en varios archivos.

- `logs/comandia.log`: todo lo importante (arranque, avisos, errores) · rota a los 10 MB y guarda 5.
- `logs/error.log`: solo errores, con el detalle técnico para quien da soporte · rota a los 5 MB y guarda 3.
Los errores no previstos se anotan con su traza completa. La carpeta se puede cambiar con la variable COMANDIA_LOGS.
"""
import logging
import logging.handlers
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.environ.get("COMANDIA_LOGS") or os.path.join(BASE_DIR, "logs")
FILE_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_MARK = "_comandia_handler"


def setup_logging(level: int = logging.INFO) -> bool:
    """Prepara los archivos de registro una sola vez. Si la carpeta no se puede escribir, el sistema sigue sin registro en archivo."""
    root = logging.getLogger()
    if any(getattr(h, _MARK, False) for h in root.handlers):
        return True
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        main = logging.handlers.RotatingFileHandler(os.path.join(LOGS_DIR, "comandia.log"), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
        errors = logging.handlers.RotatingFileHandler(os.path.join(LOGS_DIR, "error.log"), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    except OSError:
        return False
    main.setLevel(level)
    errors.setLevel(logging.ERROR)
    for handler in (main, errors):
        handler.setFormatter(logging.Formatter(FILE_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
        setattr(handler, _MARK, True)
        root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    for noisy in ("urllib3", "sqlalchemy.engine", "multipart", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)  # el acceso de cada petición no se guarda: solo avisos y errores
    return True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
