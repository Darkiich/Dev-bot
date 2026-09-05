import logging

import aiohttp

from bot_init import bot
from dataConfig import ADDRESS_MRP, ADDRESS_DEV, DATA_MRP, DATA_DEV, HEADERS_MRP, HEADERS_DEV, ROLE_ACCESS_HEADS
from disnake.ext.commands import has_any_role

logger = logging.getLogger(__name__)

'''Команда для рестарта сервера MRP/DEV'''
@has_any_role(*ROLE_ACCESS_HEADS)
@bot.command(name="restart")
async def restart_command(ctx, server: str = "mrp"):
    if server.lower() == "mrp":
        address = ADDRESS_MRP
        instance = "MRP"
        port = 5000
        data = DATA_MRP
        headers = HEADERS_MRP
    elif server.lower() == "dev":
        address = ADDRESS_DEV
        instance = "DEV"
        port = 5001
        data = DATA_DEV
        headers = HEADERS_DEV
    else:
        await ctx.send("Неверный сервер: dev или mrp")
        return

    url = f"http://{address}:{port}/instances/{instance}/restart"

    logger.warning("Рестарт сервера %s запрошен пользователем %s (%s)", instance, ctx.author, ctx.author.id)
    await ctx.send(f"Запущен рестарт {server.upper()} сервера...")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, headers=headers) as resp:
                if resp.status == 200:
                    logger.info("Рестарт сервера %s выполнен успешно", instance)
                    await ctx.send(f"✅ Рестарт {server.upper()} выполнен.")
                else:
                    logger.error("Рестарт сервера %s: код %d", instance, resp.status)
                    await ctx.send(f"Ошибка: код {resp.status}")
    except Exception as e:
        logger.exception("Ошибка при рестарте сервера %s: %s", instance, e)
        await ctx.send(f"Ошибка: {e}")