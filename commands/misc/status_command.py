import aiohttp
import logging
from datetime import datetime, timezone, timedelta
from bot_init import bot
from template_embed import embed_status
from dataConfig import ADDRESS_MRP, ADDRESS_DEV
from disnake import Embed

logger = logging.getLogger(__name__)

'''Команда для получения информации о сервере МРП/ДЕВа'''
@bot.command(name="status")
async def status_command(ctx, server: str = "mrp"):
    if server.lower() == "mrp":
        address = ADDRESS_MRP
        port = "1212"
    elif server.lower() == "dev":
        address = ADDRESS_DEV
        port = "11212"
    else:
        await ctx.send("Неверный сервер: dev или mrp")
        return

    url = f"http://{address}:{port}/status"

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
                    await ctx.send(embed=embed)
                else:
                    logger.error("status: сервер %s ответил кодом %d", server, resp.status)
                    await ctx.send(f"Ошибка: код {resp.status}")
    except Exception as e:
        logger.exception("Ошибка команды status для %s: %s", server, e)
        await ctx.send(f"Ошибка: {e}")