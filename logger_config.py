"""
Единая настройка логирования бота.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from os import getenv

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "bot.log"

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 5 файлов по 5 МБ - на VPS с ограниченным диском этого достаточно, а истории
# хватает на несколько дней активной работы бота
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5

_configured = False


def setup_logging() -> None:
    """Настраивает корневой логгер. Повторные вызовы ничего не делают."""
    global _configured
    if _configured:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    level_name = getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, level_name, logging.INFO)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    disnake_level_name = getenv("DISNAKE_LOG_LEVEL", "WARNING").upper()
    disnake_level = getattr(logging, disnake_level_name, logging.WARNING)
    logging.getLogger("disnake").setLevel(disnake_level)

    def _log_unhandled_exception(exc_type, exc_value, exc_traceback):
        """Всё, что раньше падало в консоль без следа, теперь попадёт в лог."""
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        root_logger.critical(
            "Необработанное исключение вне обработчиков discord",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    sys.excepthook = _log_unhandled_exception

    _configured = True
    root_logger.info(
        "Логирование настроено: уровень=%s, файл=%s, уровень disnake=%s",
        level_name, LOG_FILE, disnake_level_name,
    )
