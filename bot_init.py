import logging

from disnake import Intents
from disnake.ext.commands import Bot
from AHelperManager.database_ss14 import DatabaseManagerSS14
from AHelperManager.database_vacation import DatabaseManagerVacation
from AHelperManager.database_team import DatabaseManagerTeam
from AHelperManager.database_moderation import DatabaseManagerModeration
from AHelperManager.database_ghost import DatabaseManagerGhost

logger = logging.getLogger(__name__)

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
logger.info("Экземпляр бота создан (prefix='&')")

ss14_db = DatabaseManagerSS14()
vacation_db = DatabaseManagerVacation()
team_db = DatabaseManagerTeam()
mod_db = DatabaseManagerModeration()
ghost_db = DatabaseManagerGhost()
logger.info("Менеджеры БД инициализированы: ss14_db, vacation_db, team_db, mod_db, ghost_db")