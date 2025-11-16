from bot_init import bot
from tasks.discord_auth import RegisterButton, discord_auth_update
from tasks.team_list import list_team_task


@bot.event
async def on_ready():
    bot.add_view(RegisterButton())
    discord_auth_update.start()
    list_team_task.start()