"""
Ручное обновление аналитики.

    &modreport

Отчёт и так перерисовывается сам раз в час, команда нужна, когда хочется
посмотреть на свежие цифры прямо сейчас.
"""

from disnake.ext.commands import has_any_role

from bot_init import bot
from commands.moderation.mod_common import reply
from dataConfig import ROLE_ACCESS_MODERATOR
from tasks.mod_report import refresh_report


@bot.command(name="modreport", aliases=["отчёт_модерации"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def modreport_command(ctx):
    """Перерисовывает закреплённый отчёт в канале аналитики."""
    await reply(ctx, await refresh_report())
