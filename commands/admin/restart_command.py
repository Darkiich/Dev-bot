"""
Рестарт игрового сервера через вотчдог
"""

import logging

from disnake.ext.commands import has_any_role

import watchdog

from bot_init import bot
from dataConfig import ROLE_ACCESS_HEADS

logger = logging.getLogger(__name__)


@has_any_role(*ROLE_ACCESS_HEADS)
@bot.command(name="restart")
async def restart_command(ctx, server: str = "mrp"):
    """Отправляет вотчдогу запрос на рестарт сервера."""
    if not watchdog.known(server):
        await ctx.send(f"❌ Неверный сервер. Доступны: {watchdog.SERVERS_TEXT}")
        return

    logger.warning(
        "Рестарт сервера %s запрошен пользователем %s (%s)",
        server.upper(), ctx.author, ctx.author.id,
    )
    await ctx.send(f"Запущен рестарт {server.upper()} сервера...")

    _, text = await watchdog.request(server, "restart")
    await ctx.send(text)
