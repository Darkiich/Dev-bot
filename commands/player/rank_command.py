"""
&rank - какие места занимаешь в рейтингах
"""

import logging

import disnake

from bot_init import bot, stats_db
from commands.moderation.mod_common import reply
from commands.player.player_common import fail, require_account
from dataConfig import PLAYER_STATS_SERVER
from player_jobs import OVERALL, job_name
from player_service import COLOR_MAIN, MENTIONS, fmt_hours, place_text, played_roles, summary_of

logger = logging.getLogger(__name__)

ROLES_SHOWN = 3
MONTH_DAYS = 30


@bot.command(name="rank", aliases=["место", "ранг"])
async def rank_command(ctx):
    """Места по общему времени, по любимым ролям и по раундам за месяц."""
    guid, ckey = await require_account(ctx)
    if guid is None:
        return

    try:
        data = await summary_of(guid)
        if not data:
            await reply(ctx, "❌ Этого игрока нет в игровой базе.")
            return

        top_roles = [tracker for tracker, _ in played_roles(data["times"])[:ROLES_SHOWN]]
        places = await stats_db.rank_by_tracker(guid, [OVERALL] + top_roles, PLAYER_STATS_SERVER)
        month = await stats_db.rank_by_rounds(guid, MONTH_DAYS, PLAYER_STATS_SERVER)
        overall_rounds = await stats_db.rank_by_rounds(guid, None, PLAYER_STATS_SERVER)
    except Exception as e:
        await fail(ctx, e, "rank")
        return

    embed = disnake.Embed(title=f"📍 Места · {ckey}", color=COLOR_MAIN)

    overall = places.get(OVERALL)
    if overall:
        place, total, time_spent = overall
        embed.add_field(
            name="Время в игре",
            value=f"{place_text(place, total)} · {fmt_hours(time_spent)}",
            inline=False,
        )

    if overall_rounds:
        place, total, rounds = overall_rounds
        embed.add_field(
            name="Раунды за всё время",
            value=f"{place_text(place, total)} · {rounds} раундов",
            inline=False,
        )

    if month:
        place, total, rounds = month
        embed.add_field(
            name=f"Раунды за {MONTH_DAYS} дней",
            value=f"{place_text(place, total)} · {rounds} раундов",
            inline=False,
        )

    role_lines = []
    for tracker in top_roles:
        found = places.get(tracker)
        if not found:
            continue
        place, total, time_spent = found
        role_lines.append(f"**{job_name(tracker)}** - {place_text(place, total)} · {fmt_hours(time_spent)}")

    if role_lines:
        embed.add_field(name="Любимые роли", value="\n".join(role_lines), inline=False)

    if not embed.fields:
        embed.description = "Пока не за что зацепиться: сыграй хотя бы один раунд."

    embed.set_footer(text="Сами рейтинги - в &top")

    await ctx.send(embed=embed, allowed_mentions=MENTIONS)
