import importlib
import logging
import pkgutil
from pathlib import Path

from logger_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

from bot_init import bot
from dataConfig import DISCORD_KEY

MODULE_GROUPS = (
    'commands.admin',
    'commands.github',
    'commands.misc',
    'commands.team',
    'commands.discord',
    'commands.sponsor',
    'commands.holiday',
    'tasks',
    'events',
)


def load_modules(folder: str):
    package = importlib.import_module(folder)
    if not package.__file__:
        return
    dir_path = Path(package.__file__).parent
    loaded = 0
    for _, mod_name, _ in pkgutil.iter_modules([str(dir_path)]):
        try:
            importlib.import_module(f"{folder}.{mod_name}")
            loaded += 1
        except Exception:
            logger.exception("Не удалось загрузить модуль %s.%s", folder, mod_name)
    logger.info("Загружен пакет '%s': %d модулей", folder, loaded)


logger.info("Запуск бота: загрузка модулей...")
for group in MODULE_GROUPS:
    load_modules(group)
logger.info("Все модули загружены, подключаюсь к Discord...")

bot.run(DISCORD_KEY)