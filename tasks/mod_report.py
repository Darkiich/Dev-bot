"""
Аналитика модерации
"""

import logging

from datetime import timedelta

import disnake

from disnake.ext import tasks

from bot_init import bot, mod_db
from dataConfig import (
    MOD_GUILD_ID,
    MOD_REPORT_CHANNEL_ID,
    MOD_REPORT_INTERVAL_MIN,
    MOD_TEAM_ROLE_ID,
    VACATION_TIMEZONE,
)
from mod_rules import COLOR_INFO, action_title
from vacation_time import now_local, plural

logger = logging.getLogger(__name__)

SHORT_DAYS = 7
LONG_DAYS = 30
CHART_DAYS = 14

PUNISH = ("warn", "mute", "kick", "ban", "softban")

# Никого не пингуем: отчёт перерисовывается каждый час
SILENT = disnake.AllowedMentions.none()


def _totals(rows) -> dict:
    return {row["action"]: row["n"] for row in rows}


def _sum(totals: dict) -> int:
    return sum(totals.get(action, 0) for action in PUNISH)


def _line(totals: dict) -> str:
    parts = [
        f"{action_title(action)}: **{totals[action]}**"
        for action in PUNISH
        if totals.get(action)
    ]
    return " · ".join(parts) or "ничего не было"


def _trend(now: int, before: int) -> str:
    """Насколько неделя отличается от предыдущей."""
    if not before:
        return "неделей раньше было тихо" if now else "тихо, как и неделей раньше"

    change = round((now - before) * 100 / before)
    if change > 0:
        return f"на **{change}%** больше, чем неделей раньше ({before})"
    if change < 0:
        return f"на **{abs(change)}%** меньше, чем неделей раньше ({before})"
    return f"столько же, сколько неделей раньше ({before})"


def _chart(rows) -> str:
    """Столбики по дням. Дни без наказаний тоже показываем, это тоже данные."""
    counts = {row["day"]: row["n"] for row in rows}
    today = now_local().date()
    days = [today - timedelta(days=offset) for offset in range(CHART_DAYS - 1, -1, -1)]

    peak = max((counts.get(day, 0) for day in days), default=0)
    if not peak:
        return "За две недели наказаний не было."

    lines = []
    for day in days:
        value = counts.get(day, 0)
        bar = "█" * max(1, round(value * 14 / peak)) if value else "·"
        lines.append(f"{day.strftime('%d.%m')} {bar:<14} {value or ''}".rstrip())

    return "```\n" + "\n".join(lines) + "\n```"


def _hours(rows) -> str:
    """Три часа, в которые чаще всего приходится наказывать."""
    top = sorted(rows, key=lambda r: r["n"], reverse=True)[:3]
    if not top:
        return "данных нет"

    return "\n".join(
        f"{row['hour']:02d}:00-{(row['hour'] + 1) % 24:02d}:00 - {row['n']}"
        for row in top
    )


def _department(guild, actors) -> tuple[int, int, str]:
    """
    Состав отдела модерации: сколько работало, сколько всего и кто молчал.

    Считаем по роли отдела, а не по доступу к командам: команды открыты и
    руководству, но в статистике модераторов ему делать нечего.
    """
    if guild is None or not MOD_TEAM_ROLE_ID:
        return 0, 0, ""

    role = guild.get_role(MOD_TEAM_ROLE_ID)
    if role is None:
        return 0, 0, ""

    members = [member for member in role.members if not member.bot]
    worked_ids = {row["actor_id"] for row in actors}

    idle = sorted(
        (member for member in members if member.id not in worked_ids),
        key=lambda m: m.display_name.lower(),
    )

    names = ", ".join(member.mention for member in idle[:12])
    if len(idle) > 12:
        names += f" и ещё {len(idle) - 12}"

    return len(members) - len(idle), len(members), names


def _summary(data: dict) -> disnake.Embed:
    short = _totals(data["short"])
    long = _totals(data["long"])
    active = data["active"] or {}

    total_short = _sum(short)

    embed = disnake.Embed(
        title="📊 Модерация Discord",
        description=(
            f"**За {SHORT_DAYS} дней: {total_short}** "
            f"{plural(total_short, ('наказание', 'наказания', 'наказаний'))}\n"
            f"{_line(short)}\n"
            f"{_trend(total_short, data.get('previous') or 0)}"
        ),
        color=COLOR_INFO,
        timestamp=disnake.utils.utcnow(),
    )

    embed.add_field(
        name=f"За {LONG_DAYS} дней",
        value=f"{_sum(long)} всего\n{_line(long)}",
        inline=False,
    )

    embed.add_field(
        name="Действует сейчас",
        value=(
            f"🔇 мутов: **{active.get('mutes', 0)}**\n"
            f"🔨 банов: **{active.get('bans', 0)}**\n"
            f"⚠️ людей с активными варнами: **{active.get('warned', 0)}**"
        ),
        inline=True,
    )

    repeat = data.get("repeat") or 0
    embed.add_field(
        name="Повторные",
        value=(
            f"**{repeat}** {plural(repeat, ('человек', 'человека', 'человек'))} "
            f"получили больше одного наказания за {LONG_DAYS} дней"
        ),
        inline=True,
    )

    return embed


def _activity(data: dict) -> disnake.Embed:
    embed = disnake.Embed(title="Когда наказывают", color=COLOR_INFO)
    embed.add_field(name=f"По дням, за {CHART_DAYS} дней", value=_chart(data["daily"]), inline=False)
    embed.add_field(name=f"Часы пик, за {LONG_DAYS} дней", value=_hours(data["hourly"]), inline=True)
    return embed


def _moderators(data: dict, guild) -> disnake.Embed:
    actors = data["actors"]

    embed = disnake.Embed(title=f"Модераторы за {LONG_DAYS} дней", color=COLOR_INFO)

    if actors:
        lines = []
        for place, row in enumerate(actors[:10], start=1):
            mark = {1: "🥇", 2: "🥈", 3: "🥉"}.get(place, f"`{place}.`")
            lines.append(
                f"{mark} <@{row['actor_id']}> - **{row['total']}**  "
                f"(⚠️ {row['warns']} · 🔇 {row['mutes']} · 👢 {row['kicks']} · 🔨 {row['bans']})"
            )
        embed.add_field(name="Кто сколько выдал", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Кто сколько выдал", value="Никто ничего не выдавал", inline=False)

    if data["revokers"]:
        embed.add_field(
            name="Кто снимал наказания",
            value="\n".join(f"<@{row['actor_id']}> - {row['n']}" for row in data["revokers"]),
            inline=True,
        )

    worked, total, idle = _department(guild, actors)

    if total:
        embed.add_field(
            name="Отдел модерации",
            value=f"работали **{worked}** из **{total}**",
            inline=True,
        )

    if idle:
        embed.add_field(name="Без единого действия", value=idle, inline=False)

    return embed


def _offenders(data: dict) -> disnake.Embed:
    embed = disnake.Embed(title=f"Нарушители за {LONG_DAYS} дней", color=COLOR_INFO)

    if data["targets"]:
        embed.description = "\n".join(
            f"<@{row['target_id']}> - {row['n']} "
            f"{plural(row['n'], ('наказание', 'наказания', 'наказаний'))}"
            for row in data["targets"]
        )
    else:
        embed.description = "Никого не наказывали."

    embed.set_footer(text="Обновляется автоматически · подробнее: &history и &modstats")
    return embed


def build_report(data: dict, guild) -> list:
    return [_summary(data), _activity(data), _moderators(data, guild), _offenders(data)]


async def _find_report_message(channel):
    """Свой закреплённый отчёт в канале или None."""
    try:
        async for message in channel.pins():
            if message.author.id == bot.user.id:
                return message
    except (disnake.Forbidden, disnake.HTTPException) as e:
        logger.error("Не удалось прочитать закреплённые сообщения: %s", e)
    return None


async def refresh_report() -> str:
    """Перерисовывает отчёт. Возвращает текст для того, кто позвал вручную."""
    if not MOD_REPORT_CHANNEL_ID:
        return "❌ Канал отчёта не задан в конфиге."

    channel = bot.get_channel(MOD_REPORT_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(MOD_REPORT_CHANNEL_ID)
        except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException) as e:
            logger.error("Канал отчёта %s недоступен: %s", MOD_REPORT_CHANNEL_ID, e)
            return f"❌ Канал отчёта недоступен: {e}"

    guild = bot.get_guild(MOD_GUILD_ID) or channel.guild

    data = await mod_db.get_report_data(
        guild_id=guild.id if guild else None,
        short_days=SHORT_DAYS,
        long_days=LONG_DAYS,
        chart_days=CHART_DAYS,
        tz=VACATION_TIMEZONE,
    )

    if data is None:
        logger.warning("База не ответила, отчёт модерации оставлен как был")
        return "⚠️ База не ответила, отчёт оставлен как был."

    embeds = build_report(data, guild)
    message = await _find_report_message(channel)

    try:
        if message:
            await message.edit(embeds=embeds, allowed_mentions=SILENT)
            logger.debug("Отчёт модерации обновлён")
        else:
            message = await channel.send(embeds=embeds, allowed_mentions=SILENT)
            await message.pin()
            logger.info("Отчёт модерации создан и закреплён")
    except (disnake.Forbidden, disnake.HTTPException) as e:
        logger.error("Не удалось обновить отчёт модерации: %s", e)
        return f"❌ Не удалось обновить отчёт: {e}"

    return f"📊 Отчёт обновлён: {channel.mention}"


@tasks.loop(minutes=MOD_REPORT_INTERVAL_MIN or 60)
async def mod_report():
    await refresh_report()


@mod_report.before_loop
async def before_mod_report():
    await bot.wait_until_ready()
