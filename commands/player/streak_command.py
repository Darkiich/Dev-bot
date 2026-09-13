"""
&streak - сколько дней подряд заходишь на сервер
"""

import logging

import disnake

from bot_init import bot, stats_db
from commands.moderation.mod_common import reply
from commands.player.player_common import fail, require_account
from dataConfig import PLAYER_STATS_SERVER, VACATION_TIMEZONE
from player_service import COLOR_MAIN, MENTIONS, streak_from_days
from vacation_time import plural

logger = logging.getLogger(__name__)


def _days(number: int) -> str:
    return f"{number} {plural(number, ('день', 'дня', 'дней'))}"


@bot.command(name="streak", aliases=["стрик", "серия"])
async def streak_command(ctx):
    """Текущая и лучшая серия заходов подряд."""
    guid, ckey = await require_account(ctx)
    if guid is None:
        return

    try:
        days = await stats_db.connection_days(guid, VACATION_TIMEZONE, PLAYER_STATS_SERVER)
    except Exception as e:
        await fail(ctx, e, "streak")
        return

    if not days:
        await reply(ctx, "В базе нет ни одного твоего захода за последние три года.")
        return

    current, best, today_visited = streak_from_days(days)

    embed = disnake.Embed(title=f"🔥 Серия заходов · {ckey}", color=COLOR_MAIN)
    embed.add_field(name="Сейчас подряд", value=_days(current), inline=True)
    embed.add_field(name="Лучшая серия", value=_days(best), inline=True)
    embed.add_field(name="Дней с заходом", value=_days(len(days)), inline=True)
    embed.add_field(name="Последний заход", value=days[0].strftime("%d.%m.%Y"), inline=True)

    if today_visited:
        embed.description = "Сегодня уже отметился, серия в безопасности."
    elif current:
        embed.description = "Сегодня тебя ещё не было. Зайди до полуночи, иначе серия оборвётся."
    else:
        embed.description = "Серия оборвалась. Новая начнётся с ближайшего захода."

    embed.set_footer(text="День засчитывается по московскому времени")

    await ctx.send(embed=embed, allowed_mentions=MENTIONS)
