from bot_init import bot
from tasks.discord_auth import RegisterButton, discord_auth_update
from tasks.team_list import list_team_task
from tasks.status_message import status_update
from tasks.sponsor_role_sync import sponsor_role_sync
from tasks.db_size_monitor import db_size_monitor
from tasks.vacation_monitor import vacation_monitor

BACKGROUND_TASKS = (
    discord_auth_update,
    list_team_task,
    status_update,
    sponsor_role_sync,
    db_size_monitor,
    vacation_monitor,
)


@bot.event
async def on_ready():
    bot.add_view(RegisterButton())

    for task in BACKGROUND_TASKS:
        if not task.is_running():
            task.start()

    print(f"[bot] Готов: {bot.user} ({bot.user.id})")
