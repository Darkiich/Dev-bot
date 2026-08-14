import re

from datetime import datetime, timezone

import disnake

from bot_init import bot, ss14_db, vacation_db
from dataConfig import ROLE_ACCESS_ADMIN
from disnake.ext import commands
from disnake.ext.commands import has_any_role

USAGE = (
    "**Использование:** `&whois <ckey | @участник | discord id> [mrp/dev]`\n"
    "Без аргументов покажет вас."
)

_ID_RE = re.compile(r"^<@!?(\d{15,25})>$|^(\d{15,25})$")


def _discord_id(token: str):
    """Discord ID из упоминания или голых цифр, иначе None."""
    match = _ID_RE.match(token.strip())
    if not match:
        return None
    return match.group(1) or match.group(2)


def _ts(value, style: str = "f") -> str:
    """Дата в виде метки Discord."""
    if not isinstance(value, datetime):
        return "неизвестно"
    return f"<t:{int(value.timestamp())}:{style}>"


def _aware(value):
    """Наивные даты из БД считаем UTC, чтобы можно было сравнивать."""
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _active_ban(bans):
    """Первый неснятый и неистёкший бан или None."""
    now = datetime.now(timezone.utc)
    for ban in bans or []:
        if ban["unban_time"] is not None:
            continue
        expires = _aware(ban["expiration_time"])
        if expires is None or expires > now:
            return ban
    return None


def _multiaccounts(data, related) -> list:
    """Аккаунты, совпадающие по IP или HWID."""
    found = []
    for acc in related or []:
        if acc["last_seen_user_name"] == data["last_seen_user_name"]:
            continue

        marks = []
        if acc["last_seen_address"] == data["last_seen_address"]:
            marks.append("IP")
        if acc["last_seen_hwid"] == data["last_seen_hwid"]:
            marks.append("HWID")

        if marks:
            found.append(f"{acc['last_seen_user_name']} [{', '.join(marks)}]")
    return found


'''Команда для сбора всей информации об игроке в одну карточку'''
# @has_any_role(*ROLE_ACCESS_ADMIN)
@bot.command(name="whois")
async def whois_command(ctx, username_or_ckey: str = None, server: str = "mrp"):
    if server not in ("mrp", "dev"):
        await ctx.send("Некорректный сервер. Допустимые значения: 'mrp' или 'dev'")
        return

    token = username_or_ckey or str(ctx.author.id)
    discord_id = _discord_id(token)
    ckey = None

    if discord_id:
        guid = await ss14_db.get_player_guid_by_discord_id(discord_id, server)
        if not guid:
            await ctx.send(f"У <@{discord_id}> не привязан аккаунт SS14.")
            return
        ckey = await ss14_db.get_player_name(guid, server)
    else:
        ckey = token

    data, related = await ss14_db.get_all_player_info(ckey, server)
    if not data:
        await ctx.send(f"Игрок `{ckey}` не найден в БД {server.upper()}.")
        return

    guid = data["user_id"]
    ckey = data["last_seen_user_name"]

    if not discord_id:
        discord_id = await ss14_db.get_discord_info_by_guid(guid, server)

    permission = await ss14_db.get_admin_permission(ckey, server)
    bans = await ss14_db.search_ban_player_by_guid(guid, server)
    notes = await ss14_db.search_notes_player(ckey, server)
    sponsor = await ss14_db.get_sponsor(guid)
    vacation = await vacation_db.get_vacation(discord_id) if discord_id else None

    banned = _active_ban(bans)
    multi = _multiaccounts(data, related)

    if banned:
        color = 0xED4245
    elif vacation:
        color = 0xF0B232
    else:
        color = 0x57F287

    embed = disnake.Embed(
        title=f"{ckey}",
        description=(
            f"GUID: `{guid}`\n"
            f"Discord: {f'<@{discord_id}>' if discord_id else 'не привязан'}"
        ),
        color=color,
    )

    embed.add_field(name="Первый заход", value=_ts(data["first_seen_time"], "d"), inline=True)
    embed.add_field(name="Последний заход", value=_ts(data["last_seen_time"], "R"), inline=True)

    embed.add_field(
        name="Титул",
        value=f"{permission['title']}" if permission else "нет",
        inline=True,
    )

    if bans is None:
        bans_value = "не удалось получить"
    elif banned:
        bans_value = f"{len(bans)}, есть активный"
    else:
        bans_value = f"{len(bans)}, активных нет"

    embed.add_field(name="Баны", value=bans_value, inline=True)
    embed.add_field(
        name="Заметки",
        value="не удалось получить" if notes is None else str(len(notes)),
        inline=True,
    )

    if sponsor:
        expires = sponsor["expire_date"]
        sponsor_value = f"тир {sponsor['tier']}"
        if expires:
            sponsor_value += f", до {_ts(expires, 'd')}"
    else:
        sponsor_value = "нет"
    embed.add_field(name="Спонсор", value=sponsor_value, inline=True)

    if vacation:
        embed.add_field(
            name="Отпуск",
            value=f"до {_ts(vacation['end_vacation'], 'd')}\n{vacation['reason']}",
            inline=False,
        )

    if banned:
        until = _ts(banned["expiration_time"]) if banned["expiration_time"] else "навсегда"
        embed.add_field(
            name="Активный бан",
            value=f"#{banned['ban_id']} от {banned['admin_nickname']}, {until}\n{banned['reason']}"[:1024],
            inline=False,
        )

    if multi:
        shown = "\n".join(multi[:5])
        if len(multi) > 5:
            shown += f"\nи ещё {len(multi) - 5}, смотри `&check_nick {ckey}`"
        embed.add_field(name=f"Совпадения по IP и HWID ({len(multi)})", value=shown[:1024], inline=False)

    embed.set_footer(text=f"БД {server.upper()}")
    await ctx.send(embed=embed)


@whois_command.error
async def whois_command_error(ctx, error):
    if isinstance(error, commands.MissingAnyRole):
        return

    if isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Неверный аргумент: {error}\n\n{USAGE}")
    else:
        await ctx.send(f"❗ Ошибка: `{error}`")
