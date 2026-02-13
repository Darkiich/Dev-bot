from bot_init import bot
import importlib
import pkgutil
from pathlib import Path
from dataConfig import DISCORD_KEY

def load_modules(folder: str):
    package = importlib.import_module(folder)
    if not package.__file__:
        return
    dir_path = Path(package.__file__).parent
    for _, mod_name, _ in pkgutil.iter_modules([str(dir_path)]):
        importlib.import_module(f"{folder}.{mod_name}")

load_modules('commands.admin')
load_modules('commands.github')
load_modules('commands.misc')
load_modules('commands.team')
load_modules('commands.discord')
load_modules('commands.holiday')
load_modules('tasks')
load_modules('events')

bot.run(DISCORD_KEY)