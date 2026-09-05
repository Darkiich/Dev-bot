import logging

import aiohttp

from bot_init import bot
from dataConfig import POST_ADMIN_HEADERS, ROLE_ACCESS_DOWN_ADMIN, ADDRESS_MRP
from disnake.ext.commands import has_any_role

logger = logging.getLogger(__name__)


@has_any_role(*ROLE_ACCESS_DOWN_ADMIN)
@bot.command(name="bunker")
async def bunker_command(ctx, switch: str):
    if switch.lower() not in ["on", "off"]:
        await ctx.send("Используйте 'on' или 'off'.")
        return

    bunker_bool = switch.lower() == "on"
    status = "включен" if bunker_bool else "выключен"

    url = f"http://{ADDRESS_MRP}:1212/admin/actions/panic_bunker"
    data = {"game.panic_bunker.enabled": bunker_bool}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=POST_ADMIN_HEADERS, json=data) as resp:
                if resp.status == 200:
                    logger.info("Паник-бункер %s пользователем %s (%s)", status, ctx.author, ctx.author.id)
                    await ctx.send(f"Паник-бункер {status}.")
                else:
                    logger.error("Не удалось переключить паник-бункер: код %d", resp.status)
                    await ctx.send(f"Ошибка {resp.status}: {await resp.text()}")
    except Exception as e:
        logger.exception("Ошибка переключения паник-бункера: %s", e)
        await ctx.send(f"Ошибка: {e}")