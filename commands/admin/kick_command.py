import aiohttp
import json
import logging
from bot_init import bot
from disnake.ext.commands import has_any_role
from bot_init import ss14_db
from dataConfig import ADDRESS_MRP, ADMIN_API, ROLE_ACCESS_ADMIN

logger = logging.getLogger(__name__)

'''Команда для кика игрока с сервера MRP'''
@has_any_role(*ROLE_ACCESS_ADMIN)
@bot.command(name="kick")
async def kick_command(ctx, nickname: str, reason: str):
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

    url = f"http://{ADDRESS_MRP}:1212/admin/actions/kick"

    post_data = {"Guid": str(player_guid), "Reason": reason}

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
                    logger.info("Кик игрока %s выполнен админом %s (%s), причина: %r", nickname, ctx.author, ctx.author.id, reason)
                    await ctx.send("✅ Кик выполнен.")
                else:
                    logger.error("Не удалось кикнуть %s: код %d", nickname, resp.status)
                    await ctx.send(f"Ошибка: код {resp.status}")
    except Exception as e:
        logger.exception("Ошибка при кике игрока %s: %s", nickname, e)
        await ctx.send(f"Ошибка: {e}")