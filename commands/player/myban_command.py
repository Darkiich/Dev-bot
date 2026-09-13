"""
&myban - свои баны и джоббаны
"""

import logging

from datetime import datetime, timezone

import disnake

from bot_init import bot, stats_db
from commands.player.player_common import fail, require_account
from dataConfig import PLAYER_STATS_SERVER
from player_service import COLOR_BAD, COLOR_MAIN, MENTIONS, as_utc, ts

logger = logging.getLogger(__name__)

SHOWN = 10


def _is_active(ban) -> bool:
    if ban["unban_time"] is not None:
        return False
    expires = as_utc(ban["expiration_time"])
    return expires is None or expires > datetime.now(timezone.utc)


def _kind(ban) -> str:
    """Бан сервера или джоббан. Тип 0 в базе это обычный бан."""
    if ban["ban_type"] in (None, 0):
        return "Бан сервера"
    role = ban["role"]
    return f"Джоббан · {role}" if role else "Джоббан"


def _line(ban) -> str:
    reason = (ban["reason"] or "без причины").strip()
    if len(reason) > 300:
        reason = reason[:297] + "..."

    if ban["unban_time"] is not None:
        term = f"снят {ts(ban['unban_time'], 'd')}"
    elif ban["expiration_time"] is None:
        term = "навсегда"
    elif _is_active(ban):
        term = f"до {ts(ban['expiration_time'], 'f')}"
    else:
        term = f"истёк {ts(ban['expiration_time'], 'd')}"

    return (
        f"**#{ban['ban_id']} · {_kind(ban)}**\n"
        f"Выдан {ts(ban['ban_time'], 'd')} · {term}\n"
        f"Причина: {reason}"
    )


@bot.command(name="myban", aliases=["мойбан", "мои_баны", "mybans"])
async def myban_command(ctx):
    """Свои наказания на игровом сервере."""
    guid, ckey = await require_account(ctx)
    if guid is None:
        return

    try:
        bans = await stats_db.bans(guid, PLAYER_STATS_SERVER)
    except Exception as e:
        await fail(ctx, e, "myban")
        return

    active = [ban for ban in bans if _is_active(ban)]
    past = [ban for ban in bans if not _is_active(ban)]

    if not bans:
        embed = disnake.Embed(
            title=f"✅ Наказания · {ckey}",
            description="За тобой ничего не числится. Так держать.",
            color=COLOR_MAIN,
        )
    else:
        embed = disnake.Embed(
            title=f"📋 Наказания · {ckey}",
            description=f"Активных: **{len(active)}** · всего записей: **{len(bans)}**",
            color=COLOR_BAD if active else COLOR_MAIN,
        )

        for ban in active[:SHOWN]:
            embed.add_field(name="🔴 Активно", value=_line(ban), inline=False)

        for ban in past[:SHOWN - len(active[:SHOWN])]:
            embed.add_field(name="⚪ В прошлом", value=_line(ban), inline=False)

        if len(bans) > SHOWN:
            embed.set_footer(text=f"Показаны {SHOWN} последних записей из {len(bans)}")

    await ctx.send(embed=embed, allowed_mentions=MENTIONS)
