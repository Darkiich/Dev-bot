import logging

from bot_init import bot
from tasks.discord_auth import RegisterButton, discord_auth_update
from tasks.team_list import list_team_task
from tasks.status_message import status_update
from tasks.sponsor_role_sync import sponsor_role_sync
from tasks.db_size_monitor import db_size_monitor
from tasks.vacation_monitor import vacation_monitor
from tasks.team_report import team_report
from tasks.team_sync import team_sync
from tasks.mod_monitor import mod_monitor
from tasks.mod_report import mod_report
from tasks.ghost_report import ghost_report
from commands.team.team_panel_command import TeamPanel
from commands.moderation.mod_panel_command import ModPanel

logger = logging.getLogger(__name__)

BACKGROUND_TASKS = (
    discord_auth_update,
    list_team_task,
    status_update,
    sponsor_role_sync,
    db_size_monitor,
    vacation_monitor,
    team_report,
    team_sync,
    mod_monitor,
    mod_report,
    ghost_report,
)

_startup_done = False


@bot.event
async def on_ready():
    global _startup_done

    logger.info(
        "Подключение к Discord установлено: %s (%s) | серверов: %d",
        bot.user, bot.user.id, len(bot.guilds),
    )

    bot.add_view(RegisterButton())
    bot.add_view(TeamPanel())
    bot.add_view(ModPanel())

    if _startup_done:
        logger.info("on_ready сработал повторно (переподключение), фоновые задачи не трогаю")
        return

    started = []
    for task in BACKGROUND_TASKS:
        if not task.is_running():
            task.start()
            started.append(getattr(getattr(task, "coro", None), "__name__", str(task)))
    logger.info("Запущено фоновых задач: %d (%s)", len(started), ", ".join(started))

    _startup_done = True
    logger.info("Бот полностью готов к работе: %s (%s)", bot.user, bot.user.id)
