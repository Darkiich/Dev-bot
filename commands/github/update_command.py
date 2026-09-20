"""
Обновление игрового сервера через вотчдог
"""

import logging

from disnake.ext.commands import has_any_role

import watchdog

from bot_init import bot
from dataConfig import ROLE_ACCESS_HEADS

logger = logging.getLogger(__name__)


@has_any_role(*ROLE_ACCESS_HEADS)
@bot.command(name="update")
async def update_command(ctx, server: str = "mrp"):
    """Отправляет вотчдогу запрос на обновление сервера."""
    if not watchdog.known(server):
        await ctx.send(f"❌ Неверный сервер. Доступны: {watchdog.SERVERS_TEXT}")
        return

    logger.warning(
        "Обновление сервера %s запрошено пользователем %s (%s)",
        server.upper(), ctx.author, ctx.author.id,
    )
    await ctx.send(f"Запуск обновления {server.upper()}...")

    _, text = await watchdog.request(server, "update")
    await ctx.send(text)
