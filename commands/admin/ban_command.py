import aiohttp
import json
from bot_init import bot
from disnake.ext.commands import has_any_role
from bot_init import ss14_db
from dataConfig import ADDRESS_MRP, ADMIN_API, ROLE_ACCESS_ADMIN

'''Команда для бана игрока с сервера MRP'''
@has_any_role(*ROLE_ACCESS_ADMIN)
@bot.command(name="ban")
async def ban_command(ctx, nickname: str, reason: str, time: str):
    discord_id = str(ctx.author.id)

    admin_guid = await ss14_db.get_player_guid_by_discord_id(discord_id)
    if not admin_guid:
        await ctx.send("⚠️ Ваш GUID не найден в БД. Привяжите свой аккакнут в канале #🔗▏привязка-аккаунта - https://discord.com/channels/901772674865455115/1351213738774237184.")
        return

    admin_name = await ss14_db.get_admin_name(admin_guid)
    if not admin_name:
        await ctx.send("⚠️ Ваш аккаунт SS14 не найден в БД.")
        return

    player_guid = await ss14_db.get_player_guid(nickname)
    if not player_guid:
        await ctx.send("❌ Игрок не найден в БД.")
        return
    
    if len(time) == 0:
        await ctx.send("Ошибка. Время не может быть пустым")
        return

    url = f"http://{ADDRESS_MRP}:1212/admin/actions/ban"

    post_data = {"NickName": nickname, "Reason": reason, "Time": time}

    actor_data = {"Guid": str(admin_guid), "Name": admin_name}

    headers = {
        "Authorization": f"SS14Token {ADMIN_API}",
        "Content-Type": "application/json",
        "Actor": json.dumps(actor_data)
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=post_data) as resp:
                if resp.status == 200:
                    await ctx.send(f"✅ Игрок: {nickname} забанен на {time} мин по причине '{reason}'")
                else:
                    await ctx.send(f"Ошибка: код {resp.status}")
    except Exception as e:
        await ctx.send(f"Ошибка: {e}")