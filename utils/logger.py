import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.getenv("LOG_DIR", "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", 5 * 1024 * 1024))  # 5 MB per file
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", 5))

_configured = False


def setup_logging() -> None:
    """
    Ek hi jagah se poori app ke liye logging configure karo — sab modules
    `logging.getLogger(__name__)` use karke isi central file (LOG_FILE) me
    likhenge, taaki production me kuch fail ho to ek hi log file check karni pade.

    Idempotent hai — dobara call karne pe kuch nahi hota (root logger pe
    duplicate handlers add nahi honge).
    """
    global _configured
    if _configured:
        return
    _configured = True

    os.makedirs(LOG_DIR, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVEL)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Uvicorn/SQLAlchemy access-style loggers are noisy at INFO — keep them quieter
    # so the shared log file stays focused on this app's own events.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
