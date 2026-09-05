"""
Общая логика системы отпусков разбора аргументов, роль отпуска, оформление эмбедов и отправка сообщений в канал отпусков.
"""

import logging

import disnake

from datetime import datetime

from bot_init import bot
from dataConfig import (
    VACATION_CHANNEL_ID,
    VACATION_MAX_DAYS,
    VACATION_ROLE_ID,
)
from vacation_time import (
    as_local,
    combine,
    fmt,
    now_local,
    parse_date_token,
    parse_time_token,
    ts,
)

COLOR_START = 0xF0B232 # уход в отпуск
COLOR_END = 0x57F287 # возвращение
COLOR_CANCEL = 0xED4245 # досрочное снятие
COLOR_INFO = 0x5865F2 # справочные эмбеды

DEFAULT_REASON = "Причина не указана"

#  Разбор аргументов команды
logger = logging.getLogger(__name__)


def parse_vacation_args(date_arg: str, rest: str = "") -> tuple[datetime | None, datetime | None, str, str | None]:
    """
    Разбирает `<дата> [время] [причина]`, возвращает (start, end, reason, error).
    Отпуск всегда начинается в момент выдачи команды.
    """
    rest = (rest or "").strip()
    now = now_local()

    day = parse_date_token(date_arg)
    if day is None:
        return None, None, "", (
            f"Не понял дату `{date_arg}`.\n"
            "Ожидаю конкретную дату окончания отпуска: "
            "`01.09.2026`, `2026-09-01` или `01.09`."
        )

    # Первое слово после даты может оказаться временем, тогда причина идёт следом
    head, _, tail = rest.partition(" ")
    moment = parse_time_token(head) if head else None

    if moment is not None:
        end = combine(day, moment)
        reason = tail.strip() or DEFAULT_REASON
    else:
        end = combine(day)
        reason = rest or DEFAULT_REASON

    return now, end, reason, None


def validate_period(start: datetime, end: datetime) -> str | None:
    """Проверяет корректность периода. Возвращает текст ошибки или None."""
    now = now_local()

    if end <= start:
        return "Дата окончания отпуска должна быть позже даты начала."

    if end <= now:
        return f"Отпуск заканчивается в прошлом ({fmt(end)}). Проверь дату и время."

    if (end - start).days > VACATION_MAX_DAYS:
        return f"Слишком длинный отпуск: максимум {VACATION_MAX_DAYS} дней."

    return None



#  Гильдия, участники и роль отпуска
def find_vacation_guild() -> disnake.Guild | None:
    """Находит гильдию, в которой существует роль отпуска."""
    if VACATION_ROLE_ID:
        for guild in bot.guilds:
            if guild.get_role(VACATION_ROLE_ID):
                return guild

    channel = bot.get_channel(VACATION_CHANNEL_ID)
    return getattr(channel, "guild", None)


def get_vacation_role(guild: disnake.Guild) -> disnake.Role | None:
    """Роль отпуска на сервере или None."""
    if not VACATION_ROLE_ID or guild is None:
        return None
    return guild.get_role(VACATION_ROLE_ID)


async def resolve_member(guild: disnake.Guild, ds_id) -> disnake.Member | None:
    """Ищет участника по Discord ID: сначала в кэше, потом запросом к API."""
    if guild is None:
        return None
    try:
        member_id = int(ds_id)
    except (TypeError, ValueError):
        return None

    member = guild.get_member(member_id)
    if member is not None:
        return member

    try:
        return await guild.fetch_member(member_id)
    except (disnake.NotFound, disnake.HTTPException):
        return None


def role_manage_problem(member: disnake.Member, role: disnake.Role) -> str | None:
    """Почему бот не сможет тронуть роль. None если препятствий нет."""
    me = member.guild.me

    if me is None:
        return "бот не найден среди участников сервера"

    if not me.guild_permissions.manage_roles:
        return "у бота нет права «Управление ролями»"

    if role.managed:
        return f"роль «{role.name}» управляется интеграцией, вручную её не выдать"

    if role >= me.top_role:
        return f"роль «{role.name}» не ниже роли бота «{me.top_role.name}», подними бота выше"


    return None


async def grant_vacation_role(member: disnake.Member, reason: str) -> tuple[bool, str]:
    """Выдаёт роль отпуска. Возвращает (успех, текст статуса)."""
    if not VACATION_ROLE_ID:
        return False, "⚠️ Роль не выдана: в конфиге не задан VACATION_ROLE_ID."

    role = get_vacation_role(member.guild)
    if role is None:
        return False, f"⚠️ Роль не выдана: роль с ID {VACATION_ROLE_ID} не найдена на сервере."

    if role in member.roles:
        return True, f"ℹ️ Роль **{role.name}** уже была выдана."

    problem = role_manage_problem(member, role)
    if problem:
        return False, f"⚠️ Роль не выдана: {problem}."

    try:
        await member.add_roles(role, reason=reason)
        logger.info("Выдана роль отпуска: %s (%s), причина: %r", member, member.id, reason)
        return True, f"✅ Роль **{role.name}** выдана."
    except disnake.Forbidden:
        logger.warning("Не удалось выдать роль отпуска %s: нет прав", member.id)
        return False, f"⚠️ Роль не выдана: {role_manage_problem(member, role) or 'Discord отказал (403)'}."
    except disnake.HTTPException as e:
        logger.error("Не удалось выдать роль отпуска %s: %s", member.id, e)
        return False, f"⚠️ Роль не выдана: ошибка Discord ({e})."


async def revoke_vacation_role(member: disnake.Member, reason: str) -> tuple[bool, str]:
    """Снимает роль отпуска. Возвращает (успех, текст статуса)."""
    if not VACATION_ROLE_ID:
        return False, "⚠️ Роль не снята: в конфиге не задан VACATION_ROLE_ID."

    role = get_vacation_role(member.guild)
    if role is None:
        return False, f"⚠️ Роль не снята: роль с ID {VACATION_ROLE_ID} не найдена на сервере."

    if role not in member.roles:
        return True, "ℹ️ Роли отпуска у участника не было."

    problem = role_manage_problem(member, role)
    if problem:
        return False, f"⚠️ Роль не снята: {problem}."

    try:
        await member.remove_roles(role, reason=reason)
        logger.info("Снята роль отпуска: %s (%s), причина: %r", member, member.id, reason)
        return True, f"✅ Роль **{role.name}** снята."
    except disnake.Forbidden:
        logger.warning("Не удалось снять роль отпуска %s: нет прав", member.id)
        return False, f"⚠️ Роль не снята: {role_manage_problem(member, role) or 'Discord отказал (403)'}."
    except disnake.HTTPException as e:
        logger.error("Не удалось снять роль отпуска %s: %s", member.id, e)
        return False, f"⚠️ Роль не снята: ошибка Discord ({e})."



#  Эмбеды
def _apply_avatar(embed: disnake.Embed, member: disnake.Member | None):
    if member is not None:
        embed.set_thumbnail(url=member.display_avatar.url)
    return embed


def build_start_embed(ds_id, member, end, reason, scheduled=False) -> disnake.Embed:
    """scheduled - отпуск подхвачен ежечасной проверкой, а не командой."""
    embed = disnake.Embed(
        title="🌴 Отпуск активен" if scheduled else "🌴 Уход в отпуск",
        description=f"<@{ds_id}> в отпуске до {ts(end, 'f')} ({ts(end, 'R')})",
        color=COLOR_START,
    )
    embed.add_field(name="Причина", value=reason or DEFAULT_REASON, inline=False)
    return _apply_avatar(embed, member)


def build_end_embed(ds_id, member) -> disnake.Embed:
    embed = disnake.Embed(
        title="✅ Отпуск окончен",
        description=f"<@{ds_id}> вернулся из отпуска. С возвращением!",
        color=COLOR_END,
    )
    return _apply_avatar(embed, member)


def build_cancel_embed(ds_id, member, comment=None) -> disnake.Embed:
    embed = disnake.Embed(
        title="⛔ Отпуск снят досрочно",
        description=f"<@{ds_id}> вышел из отпуска раньше срока.",
        color=COLOR_CANCEL,
    )
    if comment:
        embed.add_field(name="Комментарий", value=comment, inline=False)
    return _apply_avatar(embed, member)



#  Отправка в канал отпусков
async def announce(embed: disnake.Embed) -> bool:
    """Отправляет эмбед в канал отпусков. Возвращает True при успехе."""
    if not VACATION_CHANNEL_ID:
        logger.warning("VACATION_CHANNEL_ID не задан в конфиге.")
        return False

    channel = bot.get_channel(VACATION_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(VACATION_CHANNEL_ID)
        except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException) as e:
            logger.error("Канал отпусков %s недоступен: %s", VACATION_CHANNEL_ID, e)
            return False

    try:
        await channel.send(embed=embed)
        return True
    except (disnake.Forbidden, disnake.HTTPException) as e:
        logger.error("Не удалось отправить сообщение в канал отпусков: %s", e)
        return False


def describe_row(row: dict, now: datetime | None = None) -> str:
    """Одна строка для списка отпусков."""
    now = now or now_local()
    start = as_local(row.get("start_vacation"))
    end = as_local(row.get("end_vacation"))

    if end is None:
        return f"<@{row['ds_id']}> бессрочно"
    if start and start > now:
        return f"<@{row['ds_id']}> с {ts(start, 'd')} до {ts(end, 'd')}"
    return f"<@{row['ds_id']}> до {ts(end, 'd')} ({ts(end, 'R')})"
