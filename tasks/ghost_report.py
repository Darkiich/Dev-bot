"""
Аналитика гост-смен: у каждого отдела свой канал и свой закреплённый пост
"""

import logging

from datetime import timedelta

import disnake

from disnake.ext import tasks

from bot_init import bot, ghost_db
from dataConfig import (
    AGHOST_STATS_CHANNEL_ID,
    EGHOST_STATS_CHANNEL_ID,
    GHOST_ADMIN_TEAM_ROLE_ID,
    GHOST_EVENT_TEAM_ROLE_ID,
    GHOST_MAX_SHIFT_HOURS,
    GHOST_REPORT_INTERVAL_MIN,
    GHOST_SILENT_DAYS,
    MOD_GUILD_ID,
)
from ghost_rules import (
    AGHOST,
    COLOR_INFO,
    COLOR_OK,
    COLOR_WARN,
    EGHOST,
    hours_text,
    kind_color,
    kind_name,
    kind_title,
    kind_verb,
)
from ghost_service import review_needed
from vacation_time import as_local, now_local, plural, ts

logger = logging.getLogger(__name__)

SHORT_DAYS = 7
LONG_DAYS = 30

# Никого не пингуем: отчёт перерисовывается сам по расписанию
SILENT = disnake.AllowedMentions.none()

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

TEAM_ROLES = {
    AGHOST: GHOST_ADMIN_TEAM_ROLE_ID,
    EGHOST: GHOST_EVENT_TEAM_ROLE_ID,
}

# У каждого отдела свой канал аналитики. 0 - отдел без фонового отчёта
STATS_CHANNELS = {
    AGHOST: AGHOST_STATS_CHANNEL_ID,
    EGHOST: EGHOST_STATS_CHANNEL_ID,
}


def _percent(part: int, whole: int) -> str:
    return f"{round(part * 100 / whole)}%" if whole else "-"


def _by_user(rows) -> dict:
    return {row["user_id"]: row for row in rows}


#  1 и 3. Часы, смены, средняя длительность
def _summary(kind: str, data: dict) -> disnake.Embed:
    duration = data["duration"] or {}
    shifts = duration.get("shifts") or 0
    avg_hours = float(duration.get("avg_hours") or 0)

    long_rows = data["hours_long"]
    total_hours = sum(float(row["hours"] or 0) for row in long_rows)
    people = len(long_rows)

    embed = disnake.Embed(
        title=f"{kind_title(kind)} · аналитика отдела",
        color=kind_color(kind),
        timestamp=disnake.utils.utcnow(),
    )

    if not shifts:
        embed.description = (
            f"За {LONG_DAYS} дней ни одной закрытой смены. "
            f"Похоже, отдел не {kind_verb(kind)}."
        )
        return embed

    embed.description = (
        f"За **{LONG_DAYS}** дней: **{shifts}** "
        f"{plural(shifts, ('смена', 'смены', 'смен'))}, "
        f"**{hours_text(total_hours)}** суммарно, "
        f"**{people}** {plural(people, ('человек', 'человека', 'человек'))} в строю."
    )

    embed.add_field(name="Средняя смена", value=hours_text(avg_hours), inline=True)
    embed.add_field(
        name="Самая длинная",
        value=hours_text(float(duration.get("max_hours") or 0)),
        inline=True,
    )

    forgotten = data.get("forgotten") or 0
    embed.add_field(
        name="Забытых смен",
        value=(
            f"{forgotten} · дольше {GHOST_MAX_SHIFT_HOURS} ч или без кнопки"
            if forgotten else "нет"
        ),
        inline=True,
    )

    return embed


def _hours(kind: str, data: dict) -> disnake.Embed:
    """Часы на человека: месяц как основа, неделя как срез свежести."""
    long_rows = data["hours_long"]
    short = _by_user(data["hours_short"])

    embed = disnake.Embed(
        title=f"⏱️ Часы {kind_name(kind).lower()}а на человека",
        color=kind_color(kind),
    )

    if not long_rows:
        embed.description = f"За {LONG_DAYS} дней закрытых смен не было."
        return embed

    lines = []
    for place, row in enumerate(long_rows[:15], start=1):
        medal = MEDALS.get(place, f"`{place:>2}.`")
        week = short.get(row["user_id"])
        week_text = hours_text(float(week["hours"])) if week else "-"
        shifts = row["shifts"]

        lines.append(
            f"{medal} <@{row['user_id']}> - **{hours_text(float(row['hours'] or 0))}**\n"
            f"за неделю {week_text} · {shifts} "
            f"{plural(shifts, ('смена', 'смены', 'смен'))}"
        )

    embed.description = "\n".join(lines)[:4000]
    embed.set_footer(text=f"Слева месяц ({LONG_DAYS} дней), внутри неделя ({SHORT_DAYS} дней)")

    return embed


#  2. Проверка отчётов
def _review(kind: str, data: dict) -> disnake.Embed:
    counts = {row["review_state"]: row["n"] for row in data["review"]}

    approved = counts.get("approved", 0)
    rejected = counts.get("rejected", 0)
    pending = counts.get("pending", 0)
    decided = approved + rejected
    total = decided + pending

    color = COLOR_OK if decided and approved >= rejected else COLOR_WARN
    embed = disnake.Embed(title="🔎 Проверка отчётов", color=color if total else COLOR_INFO)

    if not total:
        embed.description = f"За {LONG_DAYS} дней проверять было нечего."
        return embed

    embed.description = (
        f"Из **{total}** завершённых отчётов проверено **{decided}** "
        f"({_percent(decided, total)})."
    )

    embed.add_field(
        name="✅ Подтверждено",
        value=f"**{approved}** · {_percent(approved, decided)} от проверенных",
        inline=True,
    )
    embed.add_field(
        name="❌ Не подтверждено",
        value=f"**{rejected}** · {_percent(rejected, decided)} от проверенных",
        inline=True,
    )
    embed.add_field(
        name="🕓 Ждут наблюдателя",
        value=f"**{pending}** · {_percent(pending, total)} от всех",
        inline=True,
    )

    return embed


#  4. Молчуны отдела
def _silent(kind: str, data: dict, guild) -> disnake.Embed:
    """
    Кто давно не выходил на смену.

    Считаем по роли отдела, а не по доступу к командам: команды открыты и
    руководству, но в выработке отдела ему делать нечего.
    """
    days = data.get("silent_days") or GHOST_SILENT_DAYS

    embed = disnake.Embed(
        title=f"🤐 Не выходили на {kind_name(kind).lower()}",
        color=COLOR_WARN,
    )

    role_id = TEAM_ROLES.get(kind)
    role = guild.get_role(role_id) if (guild and role_id) else None

    if role is None:
        embed.description = "Роль отдела не найдена, считать не по кому."
        return embed

    members = [member for member in role.members if not member.bot]
    if not members:
        embed.description = "В отделе никого нет."
        return embed

    last_seen = {row["user_id"]: as_local(row["last_at"]) for row in data["last_seen"]}
    edge = now_local() - timedelta(days=days)

    silent = [
        member for member in members
        if last_seen.get(member.id) is None or last_seen[member.id] < edge
    ]

    if not silent:
        embed.color = COLOR_OK
        embed.description = (
            f"Все **{len(members)}** из отдела выходили на смену за последние "
            f"{days} {plural(days, ('день', 'дня', 'дней'))}. Так держать."
        )
        return embed

    silent.sort(key=lambda m: (last_seen.get(m.id) is not None, last_seen.get(m.id) or edge))

    lines = []
    for member in silent[:15]:
        last = last_seen.get(member.id)
        lines.append(
            f"{member.mention} - {ts(last, 'R')}" if last
            else f"{member.mention} - **ни одной смены**"
        )

    if len(silent) > 15:
        lines.append(f"…и ещё {len(silent) - 15}")

    embed.description = (
        f"**{len(silent)}** из **{len(members)}** не выходили дольше "
        f"{days} {plural(days, ('дня', 'дней', 'дней'))}:\n\n" + "\n".join(lines)
    )[:4000]

    return embed


#  5. Ивенты
def _events(data: dict) -> disnake.Embed:
    """
    Ивенты без выдуманных типов: поле заполнено - ивент заявлен, пусто -
    не планировался. Отдельно видно, сколько раз вместо описания приложили
    ссылку: это не оценка, а способ понять, как отдел ведёт документацию.
    """
    events = data["events"] or {}
    rounds = data["rounds"] or {}

    planned = events.get("planned") or 0
    linked = events.get("linked") or 0
    shifts = events.get("shifts") or 0

    total_rounds = rounds.get("total") or 0
    with_event = rounds.get("with_event") or 0

    embed = disnake.Embed(title="🎉 Ивенты", color=COLOR_INFO)

    if not planned:
        embed.description = f"За {LONG_DAYS} дней ивентов не заявляли."
        return embed

    embed.description = (
        f"**{planned}** {plural(planned, ('ивент', 'ивента', 'ивентов'))} "
        f"за {LONG_DAYS} дней - это {_percent(planned, shifts)} всех смен игоста."
    )

    embed.add_field(
        name="Раунды с ивентом",
        value=f"**{with_event}** из **{total_rounds}** · {_percent(with_event, total_rounds)}",
        inline=True,
    )
    embed.add_field(
        name="Как оформляли",
        value=(
            f"🔗 ссылкой - {linked}\n"
            f"✨ описанием - {planned - linked}"
        ),
        inline=True,
    )

    return embed


def build_report(kind: str, data: dict, guild) -> list:
    """Готовые эмбеды отчёта. Их же показывает &ghost_stats."""
    embeds = [_summary(kind, data), _hours(kind, data)]

    if review_needed(kind):
        embeds.append(_review(kind, data))

    embeds.append(_silent(kind, data, guild))

    if kind == EGHOST:
        embeds.append(_events(data))

    return embeds


async def collect(kind: str, guild):
    """Данные для отчёта. None означает, что база не ответила."""
    return await ghost_db.get_report_data(
        kind=kind,
        guild_id=guild.id if guild else None,
        short_days=SHORT_DAYS,
        long_days=LONG_DAYS,
        max_hours=GHOST_MAX_SHIFT_HOURS,
        silent_days=GHOST_SILENT_DAYS,
    )


async def _find_report_message(channel, kind: str):
    """Свой закреплённый отчёт по этому виду смен или None."""
    head = kind_title(kind)

    try:
        async for message in channel.pins():
            if message.author.id != bot.user.id or not message.embeds:
                continue
            if (message.embeds[0].title or "").startswith(head):
                return message
    except (disnake.Forbidden, disnake.HTTPException) as e:
        logger.error("Не удалось прочитать закреплённые сообщения: %s", e)

    return None


async def _publish(kind: str) -> str | None:
    """Перерисовывает отчёт одного отдела. None - отдел пропущен."""
    channel_id = STATS_CHANNELS.get(kind)
    if not channel_id:
        return None

    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException) as e:
            logger.error("Канал аналитики %s (%s) недоступен: %s", kind, channel_id, e)
            return None

    guild = bot.get_guild(MOD_GUILD_ID) or channel.guild

    data = await collect(kind, guild)
    if data is None:
        logger.warning("База не ответила, отчёт %s оставлен как был", kind)
        return None

    embeds = build_report(kind, data, guild)
    message = await _find_report_message(channel, kind)

    try:
        if message:
            await message.edit(embeds=embeds, allowed_mentions=SILENT)
        else:
            message = await channel.send(embeds=embeds, allowed_mentions=SILENT)
            await message.pin()
            logger.info("Отчёт %s создан и закреплён в %s", kind, channel_id)
    except (disnake.Forbidden, disnake.HTTPException) as e:
        logger.error("Не удалось обновить отчёт %s: %s", kind, e)
        return None

    return f"{kind_name(kind)}: {channel.mention}"


async def refresh_report(kind: str = None) -> str:
    """Перерисовывает отчёты. Возвращает текст для того, кто позвал вручную."""
    kinds = (kind,) if kind else (AGHOST, EGHOST)

    if not any(STATS_CHANNELS.get(current) for current in kinds):
        return (
            "❌ Канал аналитики не задан: впиши AGHOST_STATS_CHANNEL_ID или "
            "EGHOST_STATS_CHANNEL_ID в dataConfig.py. Пока они нулевые, цифры "
            "смотрим командой `&ghost_stats`."
        )

    done = [line for current in kinds if (line := await _publish(current))]

    if not done:
        return "⚠️ Отчёты обновить не вышло, подробности в логе."

    return "📊 Обновлено - " + " · ".join(done)


@tasks.loop(minutes=GHOST_REPORT_INTERVAL_MIN or 180)
async def ghost_report():
    if not any(STATS_CHANNELS.values()):
        return
    await refresh_report()


@ghost_report.before_loop
async def before_ghost_report():
    await bot.wait_until_ready()
