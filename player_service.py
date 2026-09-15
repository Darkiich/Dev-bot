"""
Общее для игроцких команд: поиск аккаунта, форматирование часов и дат
"""

import logging
import re

from datetime import date, datetime, timedelta, timezone

import disnake

from bot_init import ss14_db, stats_db
from dataConfig import CHANNEL_AUTH_DISCORD, PLAYER_STATS_SERVER, ROLE_ACCESS_PRIVACY_BYPASS
from player_jobs import OVERALL, is_job, job_name
from vacation_time import TZ, plural

logger = logging.getLogger(__name__)

COLOR_MAIN = 0x3498DB
COLOR_WARN = 0xF0B232
COLOR_BAD = 0xED4245

MENTIONS = disnake.AllowedMentions(everyone=False, roles=False, users=False)

_ID_RE = re.compile(r"^(?:<@!?(\d{15,25})>|(\d{15,25}))$")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

BLOCKS = "▁▂▃▄▅▆▇█"


def link_hint() -> str:
    """Куда идти, если аккаунт ещё не привязан."""
    return (
        "❌ Игровой аккаунт не привязан к Discord.\n"
        f"Привязать можно кнопкой в канале <#{CHANNEL_AUTH_DISCORD}>, "
        "UID берётся из лобби игры."
    )


def discord_id_from(token: str):
    """Discord ID из упоминания или голых цифр, иначе None."""
    match = _ID_RE.match((token or "").strip())
    if not match:
        return None
    return match.group(1) or match.group(2)


def looks_like_uuid(token: str) -> bool:
    return bool(_UUID_RE.match((token or "").strip()))


#  Даты и длительности
def as_utc(value):
    """Наивные даты из БД считаем UTC, как в остальных командах бота."""
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def ts(value, style: str = "f") -> str:
    moment = as_utc(value)
    return f"<t:{int(moment.timestamp())}:{style}>" if moment else "неизвестно"


def fmt_hours(delta: timedelta | None) -> str:
    """`312 ч 40 мин (13 дней)`: в больших числах одни часы не читаются."""
    if delta is None:
        return "нет данных"

    total = int(delta.total_seconds())
    if total <= 0:
        return "0 ч"

    hours, minutes = divmod(total // 60, 60)

    if not hours:
        return f"{minutes} мин"

    text = f"{hours} ч" if not minutes else f"{hours} ч {minutes} мин"

    days = hours // 24
    if days:
        text += f" ({days} {plural(days, ('день', 'дня', 'дней'))})"

    return text


def fmt_minutes(minutes: int | None) -> str:
    return fmt_hours(timedelta(minutes=minutes)) if minutes is not None else "нет данных"


def age_text(moment) -> str:
    """Сколько прошло с даты: `3 года 4 месяца`."""
    start = as_utc(moment)
    if start is None:
        return ""

    days = (datetime.now(timezone.utc) - start).days
    if days < 31:
        return f"{days} {plural(days, ('день', 'дня', 'дней'))}"

    years, months = divmod(days // 30, 12)
    parts = []
    if years:
        parts.append(f"{years} {plural(years, ('год', 'года', 'лет'))}")
    if months:
        parts.append(f"{months} {plural(months, ('месяц', 'месяца', 'месяцев'))}")
    return " ".join(parts) or "меньше месяца"


def since_text(first_seen) -> str:
    """`12.05.2023 · 3 года 4 месяца`."""
    if not isinstance(first_seen, datetime):
        return "неизвестно"
    return f"{ts(first_seen, 'D')} · {age_text(first_seen)}"


def can_see_private(user) -> bool:
    """Админский состав видит персонажей даже у скрывшихся."""
    roles = {role.id for role in getattr(user, "roles", [])}
    return bool(roles & set(ROLE_ACCESS_PRIVACY_BYPASS))


def place_text(place: int, total: int) -> str:
    return f"**{place}**-е место из {total}"


def bar(values: list) -> str:
    """Полоска из блоков под ряд чисел."""
    if not values:
        return ""

    top = max(values)
    if top <= 0:
        return BLOCKS[0] * len(values)

    return "".join(BLOCKS[min(len(BLOCKS) - 1, int(value / top * (len(BLOCKS) - 1)))] for value in values)


#  Роли
def played_roles(times: dict) -> list:
    """
    Роли с наигранным временем: (название, время, трекеры), от большего.

    Одна роль может лежать в базе под несколькими трекерами сразу, поэтому
    собираем их по названию и складываем время.
    """
    grouped = {}

    for tracker, delta in (times or {}).items():
        if not is_job(tracker) or not delta:
            continue

        name = job_name(tracker)
        total, trackers = grouped.get(name, (timedelta(), []))
        grouped[name] = (total + delta, trackers + [tracker])

    roles = [(name, total, trackers) for name, (total, trackers) in grouped.items()]
    return sorted(roles, key=lambda role: role[1], reverse=True)


def top_roles_text(times: dict, limit: int = 3) -> str:
    roles = played_roles(times)[:limit]
    if not roles:
        return "ещё не играл"
    return "\n".join(f"**{name}** - {fmt_hours(delta)}" for name, delta, _ in roles)


#  Стрик
def streak_from_days(days: list) -> tuple:
    """Считает (текущий стрик, лучший, был ли заход сегодня)."""
    unique = sorted({day for day in days if isinstance(day, date)}, reverse=True)
    if not unique:
        return 0, 0, False

    today = datetime.now(TZ).date()
    today_visited = unique[0] == today

    current = 0
    expected = today if today_visited else today - timedelta(days=1)
    for day in unique:
        if day == expected:
            current += 1
            expected -= timedelta(days=1)
        elif day < expected:
            break

    best = 1
    run = 1
    for previous, day in zip(unique, unique[1:]):
        if previous - day == timedelta(days=1):
            run += 1
            best = max(best, run)
        else:
            run = 1

    return current, max(best, current), today_visited


#  Аккаунты
async def guid_by_discord(discord_id) -> str | None:
    return await ss14_db.get_player_guid_by_discord_id(str(discord_id), PLAYER_STATS_SERVER)


async def own_account(ctx):
    """Аккаунт автора команды: (guid, ckey, текст отказа)."""
    guid = await guid_by_discord(ctx.author.id)
    if not guid:
        return None, None, link_hint()

    ckey = await ss14_db.get_player_name(guid, PLAYER_STATS_SERVER)
    if not ckey:
        return None, None, "❌ Аккаунт привязан, но игрока с таким UID в базе нет."

    return guid, ckey, None


async def account_by_token(token: str):
    """Аккаунт по упоминанию, Discord ID, UID или нику: (guid, ckey, ошибка)."""
    token = (token or "").strip()
    if not token:
        return None, None, "Не указан игрок."

    discord_id = discord_id_from(token)
    if discord_id:
        guid = await guid_by_discord(discord_id)
        if not guid:
            return None, None, f"У <@{discord_id}> не привязан игровой аккаунт."
        ckey = await ss14_db.get_player_name(guid, PLAYER_STATS_SERVER)
        return guid, ckey, None

    if looks_like_uuid(token):
        ckey = await ss14_db.get_player_name(token, PLAYER_STATS_SERVER)
        if not ckey:
            return None, None, f"Игрок с UID `{token}` не найден."
        return token, ckey, None

    guid = await ss14_db.get_player_guid(token, PLAYER_STATS_SERVER)
    if not guid:
        return None, None, f"Игрок `{token}` не найден в игровой базе."
    return guid, token, None


async def summary_of(guid) -> dict:
    return await stats_db.summary(guid, PLAYER_STATS_SERVER)


def overall_of(summary: dict) -> timedelta:
    return (summary or {}).get("times", {}).get(OVERALL, timedelta())
