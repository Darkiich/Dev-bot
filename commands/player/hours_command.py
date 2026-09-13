"""
&hours - часы за неделю и месяц с динамикой по дням
"""

import logging

from datetime import datetime, timedelta

import disnake

from bot_init import bot, player_db
from commands.moderation.mod_common import reply
from commands.player.player_common import fail, require_account
from player_service import COLOR_MAIN, MENTIONS, bar, fmt_minutes, summary_of
from vacation_time import TZ

logger = logging.getLogger(__name__)

CHART_DAYS = 14


def _fmt_day(day) -> str:
    return day.strftime("%d.%m") if day else "неизвестно"


def _period(now_minutes: int, snapshot) -> str:
    """Прирост часов от ближайшего снимка, дата снимка идёт рядом."""
    if snapshot is None:
        return "нет данных"

    grown = max(0, now_minutes - int(snapshot["minutes"]))
    return f"{fmt_minutes(grown)} (с {_fmt_day(snapshot['taken_on'])})"


def _chart(rows: list, now_minutes: int) -> str:
    """Прирост по дням между снимками, последним столбцом идёт сегодня."""
    if len(rows) < 2:
        return ""

    values = []
    labels = []
    for previous, current in zip(rows, rows[1:]):
        values.append(max(0, int(current["minutes"]) - int(previous["minutes"])))
        labels.append(current["taken_on"])

    values.append(max(0, now_minutes - int(rows[-1]["minutes"])))
    labels.append(datetime.now(TZ).date())

    values = values[-CHART_DAYS:]
    labels = labels[-CHART_DAYS:]

    total = sum(values)
    return (
        f"`{bar(values)}`\n"
        f"{_fmt_day(labels[0])} - {_fmt_day(labels[-1])} · всего {fmt_minutes(total)}"
    )


@bot.command(name="hours", aliases=["часы"])
async def hours_command(ctx):
    """Сколько наиграно за неделю и месяц."""
    guid, ckey = await require_account(ctx)
    if guid is None:
        return

    try:
        data = await summary_of(guid)
        if not data:
            await reply(ctx, "❌ Этого игрока нет в игровой базе.")
            return

        now_minutes = int(data["overall"].total_seconds() // 60)
        today = datetime.now(TZ).date()

        week = await player_db.snapshot_before(guid, today - timedelta(days=7))
        month = await player_db.snapshot_before(guid, today - timedelta(days=30))
        series = await player_db.snapshot_series(guid, CHART_DAYS + 1)
        first_day = await player_db.first_snapshot_day(guid)
    except Exception as e:
        await fail(ctx, e, "hours")
        return

    embed = disnake.Embed(title=f"⏱️ Часы · {ckey}", color=COLOR_MAIN)
    embed.add_field(name="Всего", value=fmt_minutes(now_minutes), inline=True)
    embed.add_field(name="За 7 дней", value=_period(now_minutes, week), inline=True)
    embed.add_field(name="За 30 дней", value=_period(now_minutes, month), inline=True)

    chart = _chart(series, now_minutes)
    if chart:
        embed.add_field(name="По дням", value=chart, inline=False)

    if first_day is None:
        embed.set_footer(text="Бот ещё не сделал ни одного снимка часов, динамика появится завтра")
    else:
        embed.set_footer(text=f"Динамика считается со снимка от {_fmt_day(first_day)}")

    await ctx.send(embed=embed, allowed_mentions=MENTIONS)
