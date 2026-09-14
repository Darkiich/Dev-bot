"""
&me - карточка своего игрового аккаунта
"""

import logging

from datetime import datetime, timezone

import disnake

from bot_init import bot, ss14_db
from commands.moderation.mod_common import reply
from commands.player.player_common import fail, require_account
from dataConfig import PLAYER_STATS_SERVER
from player_service import (
    COLOR_MAIN,
    as_utc,
    MENTIONS,
    fmt_hours,
    since_text,
    summary_of,
    top_roles_text,
    ts,
)

logger = logging.getLogger(__name__)

HINT = "Подробнее: `&roles` · `&hours` · `&streak` · `&rank`"


@bot.command(name="me", aliases=["я", "профиль", "стата"])
async def me_command(ctx):
    """Часы, роли, раунды и дата первого захода."""
    guid, ckey = await require_account(ctx)
    if guid is None:
        return

    try:
        data = await summary_of(guid)
    except Exception as e:
        await fail(ctx, e, "me")
        return

    if not data:
        await reply(ctx, "❌ Этого игрока нет в игровой базе.")
        return

    player = data["player"]

    embed = disnake.Embed(title=f"👤 {ckey}", color=COLOR_MAIN)
    embed.add_field(name="Время в игре", value=fmt_hours(data["overall"]), inline=True)
    embed.add_field(name="Раундов", value=str(data["rounds"] or "нет данных"), inline=True)
    embed.add_field(name="Последний заход", value=ts(player["last_seen_time"], "R"), inline=True)
    embed.add_field(name="На станции с", value=since_text(player["first_seen_time"]), inline=False)
    embed.add_field(name="Любимые роли", value=top_roles_text(data["times"]), inline=False)

    try:
        sponsor = await ss14_db.get_sponsor(guid)
    except Exception as e:
        logger.warning("Не удалось прочитать спонсорку для %s: %s", ckey, e)
        sponsor = None

    # Истёкшие подписки из базы не удаляются, поэтому смотрим на дату окончания
    if sponsor:
        expires = as_utc(sponsor["expire_date"])
        if expires is None or expires > datetime.now(timezone.utc):
            value = f"уровень {sponsor['tier']}"
            if expires:
                value += f" · до {ts(expires, 'd')}"
            embed.add_field(name="Спонсор", value=value, inline=True)

    embed.set_footer(text=f"Сервер {PLAYER_STATS_SERVER.upper()}")

    if ctx.author.display_avatar:
        embed.set_thumbnail(url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed, content=HINT, allowed_mentions=MENTIONS)
