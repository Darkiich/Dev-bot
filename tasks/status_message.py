import logging

from bot_init import bot
from datetime import datetime, timezone, timedelta
from dataConfig import CHANNEL_STATUS_MESSAGE, ADDRESS_MRP
from disnake import Embed
from template_embed import embed_status

import aiohttp
from disnake.ext import tasks

logger = logging.getLogger(__name__)


@tasks.loop(minutes=2)
async def status_update():
    channel = bot.get_channel(CHANNEL_STATUS_MESSAGE)
    if not channel:
        return

    url = f"http://{ADDRESS_MRP}:1212/status"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    embed = Embed(title=embed_status["title"], color=embed_status["color"])

                    time_str = "Неизвестно"
                    if data.get('round_start_time'):
                        try:
                            dt = datetime.fromisoformat(data['round_start_time'].replace('Z', '+00:00'))
                            now = datetime.now(timezone.utc)
                            delta = now - dt
                            hours, remainder = divmod(int(delta.total_seconds()), 3600)
                            minutes, _ = divmod(remainder, 60)
                            time_str = f"{hours} часов и {minutes:02d} минуты"
                        except:
                            pass

                    for field in embed_status["fields"]:
                        if field["name"] == "Время раунда":
                            value = time_str
                        else:
                            value = eval(field["value"])
                        embed.add_field(name=field["name"], value=value, inline=field["inline"])
                else:
                    logger.warning("Сервер статуса ответил кодом %d", resp.status)
                    embed = Embed(title="Ошибка", description=f"Код {resp.status}", color=0xff0000)
    except Exception as e:
        logger.error("Не удалось получить статус сервера: %s", e)
        embed = Embed(title="Ошибка", description=str(e), color=0xff0000)

    pinned = []
    async for msg in channel.pins():
        pinned.append(msg)

    old_message = next((m for m in pinned if m.author == channel.guild.me), None)

    if old_message:
        await old_message.edit(embed=embed)
    else:
        new_message = await channel.send(embed=embed)
        await new_message.pin()