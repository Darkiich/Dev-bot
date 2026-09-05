from bot_init import bot
from tasks.discord_auth import RegisterButton, discord_auth_update
from tasks.team_list import list_team_task
from tasks.status_message import status_update
from tasks.sponsor_role_sync import sponsor_role_sync
from tasks.db_size_monitor import db_size_monitor
from tasks.vacation_monitor import vacation_monitor
from tasks.team_report import team_report
from tasks.team_sync import team_sync
from commands.team.team_panel_command import TeamPanel

BACKGROUND_TASKS = (
    discord_auth_update,
    list_team_task,
    status_update,
    sponsor_role_sync,
    db_size_monitor,
    vacation_monitor,
    team_report,
    team_sync,
)


@bot.event
async def on_ready():
    bot.add_view(RegisterButton())
    bot.add_view(TeamPanel())

    for task in BACKGROUND_TASKS:
        if not task.is_running():
            task.start()

    print(f"[bot] Готов: {bot.user} ({bot.user.id})")
