import logging

from bot_init import bot, ss14_db
from datetime import datetime, timezone
from dataConfig import ROLE_ACCESS_ADMIN
from disnake.ext.commands import has_any_role

import disnake
import aiohttp

logger = logging.getLogger(__name__)

async def get_creation_date(uuid: str):
    url = f"https://auth.spacestation14.com/api/query/userid?userid={uuid}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    player_date = data.get('createdTime', None)
                    if player_date:
                        date_obj = datetime.fromisoformat(player_date)
                        unix = int(date_obj.timestamp())
                        return f'<t:{unix}:f>'
                    return "Дата не найдена"
                else:
                    logger.warning("check_nick: сайт учёток ответил кодом %d", resp.status)
                    return f"Ошибка: код {resp.status}"
    except Exception as e:
        logger.error("check_nick: не удалось получить дату создания аккаунта %s: %s", uuid, e)
        return f"Ошибка: {e}"


def time_since(dt):
    now = datetime.now(timezone.utc)
    delta = now - dt
    minutes = int(delta.total_seconds() // 60)
    return f'{minutes} минут назад'

'''Команда для проверки мультиаккаунта'''
@has_any_role(*ROLE_ACCESS_ADMIN)
@bot.command(name="check_nick")
async def check_nick_command(ctx, nickname: str):
    logger.info("check_nick по '%s' запросил %s (%s)", nickname, ctx.author, ctx.author.id)
    # Получаем поля данных из БД 
    data, related_accounts = await ss14_db.get_all_player_info(nickname)

    if not data:
        await ctx.send("Игрок не найден.")
        return
    
    # Присваиваем поля данныъ в переменные для дальнейшей работы с ними
    player_id, GUID, first_seen_time, last_seen_user_name, last_seen_time, last_seen_address, last_seen_hwid = data

    # Форматируем данные для того, чтобы бы было приятно читать без доп.инфы
    first_seen_formatted = first_seen_time.strftime("%Y-%m-%d %H:%M:%S") if isinstance(first_seen_time, datetime) else 'Неизвестно'
    last_seen_time_formatted = last_seen_time.strftime("%Y-%m-%d %H:%M:%S") if isinstance(last_seen_time, datetime) else 'Неизвестно'

    # Привеодим HWID к 16-теричному виду
    hwid_message = last_seen_hwid.hex() if last_seen_hwid else 'Нет'

    # Получение даты создания акка
    creation_date = await get_creation_date(GUID)

    # Получаем инфу о ds id, никнейму
    discord_id = await ss14_db.get_discord_info_by_guid(GUID)
    if discord_id:
        try:
            discord_member = await ctx.guild.fetch_member(int(discord_id))
            discord_name = discord_member.name
        except Exception as e:
            logger.debug("check_nick: не удалось получить участника Discord %s: %s", discord_id, e)
            discord_name = "Неизвестно"
        discord_message = f"Привязан Discord: <@{discord_id}> ({discord_name}, ID: {discord_id})"
    else:
        discord_message = "Discord не привязан."

    # Сохраняем инфу по совпадениям
    related_accounts_str = 'Совпадение по аккаунтам:\n'
    if related_accounts:

        for acc in related_accounts:
            related_user_name, related_address, related_hwid, related_last_seen_time = acc
            if related_user_name == last_seen_user_name:
                continue

            related_last_seen_time_str = related_last_seen_time.strftime("%Y-%m-%d %H:%M:%S") if isinstance(related_last_seen_time, datetime) else "Неизвестно"

            if related_address == last_seen_address and related_hwid != last_seen_hwid:
                related_accounts_str += f"{related_user_name} [IP] | Последний заход: {related_last_seen_time_str}\n"
            elif related_hwid == last_seen_hwid and related_address != last_seen_address:
                related_accounts_str += f"{related_user_name} [HWID] | Последний заход: {related_last_seen_time_str}\n"
            elif related_hwid == last_seen_hwid and related_address == last_seen_address:
                related_accounts_str += f"{related_user_name} [IP, HWID] | Последний заход: {related_last_seen_time_str}\n"

        if related_accounts_str == 'Совпадение по аккаунтам:\n':
            related_accounts_str += 'Не найдены'

    description = (f"Первый заход: {first_seen_formatted}\n"
                   f"Последний заход: {last_seen_time_formatted}\n"
                   f"Дата создания: {creation_date}\n\n"
                   f"HWID: {hwid_message}\n"
                   f"GUID: {GUID}\n\n"
                   f"{discord_message}\n\n"
                   f"{related_accounts_str}")

    embed = disnake.Embed(title=f"{last_seen_user_name} | ID {player_id}", description=description, color=0xFF0000)
    await ctx.send(embed=embed)