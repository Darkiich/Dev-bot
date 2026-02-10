import aiohttp

from bot_init import bot
from dataConfig import ADDRESS_MRP, ADDRESS_DEV, DATA_MRP, DATA_DEV, HEADERS_MRP, HEADERS_DEV, ROLE_ACCESS_HEADS
from disnake.ext.commands import has_any_role

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

    await ctx.send(f"Запущен рестарт {server.upper()} сервера...")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, headers=headers) as resp:
                if resp.status == 200:
                    await ctx.send(f"✅ Рестарт {server.upper()} выполнен.")
                else:
                    await ctx.send(f"Ошибка: код {resp.status}")
    except Exception as e:
        await ctx.send(f"Ошибка: {e}")