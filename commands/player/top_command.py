"""
&top - рейтинги по часам, раундам и ролям
"""

import logging

import disnake

from bot_init import bot, stats_db
from commands.moderation.mod_common import reply
from commands.player.player_common import fail
from dataConfig import PLAYER_STATS_SERVER, PLAYER_TOP_LIMIT
from player_jobs import OVERALL, find_tracker, job_name
from player_service import COLOR_MAIN, MENTIONS, fmt_hours

logger = logging.getLogger(__name__)

HOURS_WORDS = ("", "часы", "час", "часов", "hours", "overall", "общее")
ROUNDS_WORDS = ("раунды", "раунд", "раундов", "rounds")
MONTH_WORDS = ("месяц", "month", "за месяц")
MONTH_DAYS = 30

MEDALS = ("🥇", "🥈", "🥉")


def _place(index: int) -> str:
    return MEDALS[index] if index < len(MEDALS) else f"`{index + 1}.`"


def _lines(rows: list, value_key, formatter) -> str:
    return "\n".join(
        f"{_place(index)} **{row['ckey']}** - {formatter(row[value_key])}"
        for index, row in enumerate(rows)
    ) or "Пока пусто."


@bot.command(name="top", aliases=["топ"])
async def top_command(ctx, *, query: str = ""):
    """`&top`, `&top месяц`, `&top капитан`."""
    query = (query or "").strip().lower()

    try:
        if query in HOURS_WORDS:
            rows = await stats_db.top_by_tracker(OVERALL, PLAYER_TOP_LIMIT, PLAYER_STATS_SERVER)
            embed = disnake.Embed(
                title="🏆 Топ по времени в игре",
                description=_lines(rows, "time", fmt_hours),
                color=COLOR_MAIN,
            )
            embed.set_footer(text="Раунды: &top раунды · своё место: &rank · роль: &top капитан")
            await ctx.send(embed=embed, allowed_mentions=MENTIONS)
            return

        if query in ROUNDS_WORDS:
            rows = await stats_db.top_by_rounds(None, PLAYER_TOP_LIMIT, PLAYER_STATS_SERVER)
            embed = disnake.Embed(
                title="🏆 Топ по раундам",
                description=_lines(rows, "rounds", lambda n: f"{n} раундов"),
                color=COLOR_MAIN,
            )
            embed.set_footer(text="Часы: &top часы · за месяц: &top месяц · своё место: &rank")
            await ctx.send(embed=embed, allowed_mentions=MENTIONS)
            return

        if query in MONTH_WORDS:
            rows = await stats_db.top_by_rounds(MONTH_DAYS, PLAYER_TOP_LIMIT, PLAYER_STATS_SERVER)
            embed = disnake.Embed(
                title=f"🏆 Топ по раундам за {MONTH_DAYS} дней",
                description=_lines(rows, "rounds", lambda n: f"{n} раундов"),
                color=COLOR_MAIN,
            )
            embed.set_footer(text="Своё место смотри в &rank")
            await ctx.send(embed=embed, allowed_mentions=MENTIONS)
            return

        trackers = await stats_db.trackers(PLAYER_STATS_SERVER)
        matches = find_tracker(query, trackers)

        if not matches:
            await reply(
                ctx,
                f"❌ Роль `{query}` не найдена.\n"
                "Попробуй `&top` (часы), `&top месяц` или название роли: `&top капитан`.",
            )
            return

        if len(matches) > 1:
            names = ", ".join(f"`{job_name(t)}`" for t in matches[:10])
            await reply(ctx, f"Уточни роль. Подходят: {names}")
            return

        tracker = matches[0]
        rows = await stats_db.top_by_tracker(tracker, PLAYER_TOP_LIMIT, PLAYER_STATS_SERVER)

        embed = disnake.Embed(
            title=f"🏆 Топ по роли: {job_name(tracker)}",
            description=_lines(rows, "time", fmt_hours),
            color=COLOR_MAIN,
        )
        embed.set_footer(text="Своё место смотри в &rank")
        await ctx.send(embed=embed, allowed_mentions=MENTIONS)

    except Exception as e:
        await fail(ctx, e, "top")
