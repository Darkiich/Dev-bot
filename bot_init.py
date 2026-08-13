from disnake import Intents
from disnake.ext.commands import Bot
from AHelperManager.database_ss14 import DatabaseManagerSS14
from AHelperManager.database_vacation import DatabaseManagerVacation

intent = Intents.all()
intent.message_content = True
intent.members = True
intent.guilds = True
intent.guild_messages = True
intent.guild_reactions = True

bot = Bot(
    help_command=None,
    command_prefix="&",
    intents=intent
)

ss14_db = DatabaseManagerSS14()
vacation_db = DatabaseManagerVacation()