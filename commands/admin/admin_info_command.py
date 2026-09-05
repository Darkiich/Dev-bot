import logging

from bot_init import bot
from dataConfig import ADDRESS_MRP, POST_ADMIN_HEADERS, ROLE_ACCESS_ADMIN
from template_embed import embed_admin_info
from disnake.ext.commands import has_any_role

import aiohttp
from disnake import Embed

logger = logging.getLogger(__name__)


def add_chunked_fields(embed, name, value, max_length=1024, inline=False):
    """Разбивает длинное значение на несколько полей."""
    if len(value) <= max_length:
        embed.add_field(name=name, value=value, inline=inline)
        return
    
    chunks, chunk = [], ""
    lines = value.split("\n")
    for line in lines:
        if len(chunk) + len(line) + 1 > max_length:
            chunks.append(chunk.strip())
            chunk = line
        else:
            chunk += f"\n{line}" if chunk else line
    if chunk:
        chunks.append(chunk.strip())
    
    for i, chunk in enumerate(chunks):
        field_name = name if i == 0 else f"{name} (часть {i+1})"
        embed.add_field(name=field_name, value=chunk, inline=inline)

'''Команда для получения подробной статистики сервера MRP'''
@has_any_role(*ROLE_ACCESS_ADMIN)
@bot.command(name="admin_info")
async def admin_info_command(ctx):
    url = f"http://{ADDRESS_MRP}:1212/admin/info"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=POST_ADMIN_HEADERS) as resp:
                if resp.status == 200:
                    data = await resp.json()

                    embed = Embed(title=embed_admin_info["title"], color=embed_admin_info["color"])
                    for field in embed_admin_info["fields"]:
                        try:
                            value = eval(field["value"])
                            if field["name"] in ["Игроки", "Деадмины", "Правила игры"]:  # Разделение длинных строк
                                add_chunked_fields(embed, field["name"], value, inline=field["inline"])
                            else:
                                embed.add_field(name=field["name"], value=value, inline=field["inline"])
                        except Exception as field_error:
                            logger.warning("Не удалось построить поле '%s' в admin_info: %s", field["name"], field_error)
                            embed.add_field(name=field["name"], value="Ошибка", inline=field["inline"])
                    await ctx.send(embed=embed)
                else:
                    logger.error("admin_info: сервер MRP ответил кодом %d", resp.status)
                    await ctx.send(f"Ошибка: код {resp.status}")
    except Exception as e:
        logger.exception("Ошибка команды admin_info: %s", e)
        await ctx.send(f"Ошибка: {e}")