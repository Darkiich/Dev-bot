import aiohttp
from bot_init import bot
from template_embed import embed_status
from dataConfig import ADDRESS_MRP, ADDRESS_DEV
from disnake import Embed

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
                    for field in embed_status["fields"]:
                        embed.add_field(name=field["name"], value=eval(field["value"]), inline=field["inline"])
                    await ctx.send(embed=embed)
                else:
                    await ctx.send(f"Ошибка: код {resp.status}")
    except Exception as e:
        await ctx.send(f"Ошибка: {e}")