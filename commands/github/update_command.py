import aiohttp

from bot_init import bot
from disnake.ext.commands import has_any_role
from dataConfig import ROLE_ACCESS_HEADS, ADDRESS_DEV, ADDRESS_MRP, HEADERS_DEV, HEADERS_MRP, DATA_DEV, DATA_MRP

@has_any_role(*ROLE_ACCESS_HEADS)
@bot.command(name="update")
async def update_command(ctx, server: str = "mrp"):

    if server.lower() == "mrp":
        address = ADDRESS_MRP
        port = 5000
        data = DATA_MRP
        headers = HEADERS_MRP
    elif server.lower() == "dev":
        address = ADDRESS_DEV
        port = 5001
        data = DATA_DEV
        headers = HEADERS_DEV
    else:
        await ctx.send("Неверный сервер: mrp или dev")
        return

    url = f"http://{address}:{port}/instances/{server.upper()}/update"

    await ctx.send(f"Запуск обновления {server.upper()}...")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as resp:
                if resp.status == 200:
                    await ctx.send(f"Код {resp.status}. Обновление на {server.upper()} успешно отправлено.")
                else:
                    await ctx.send(f"Код {resp.status}. Обновление на {server.upper()} сервер не отправлено")
    except Exception as e:
        await ctx.send(f"Ошибка: {e}")