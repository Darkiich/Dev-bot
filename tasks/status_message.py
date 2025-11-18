from bot_init import bot
from dataConfig import CHANNEL_STATUS_MESSAGE, ADDRESS_MRP
from disnake import Embed
from template_embed import embed_status

import aiohttp
from disnake.ext import tasks

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
                    for field in embed_status["fields"]:
                        embed.add_field(name=field["name"], value=eval(field["value"]), inline=field["inline"])
                else:
                    embed = Embed(title="Ошибка", description=f"Код {resp.status}", color=0xff0000)
    except Exception as e:
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