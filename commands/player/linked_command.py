"""
&linked - привязан ли аккаунт и к какому UID
"""

import logging

import disnake

from bot_init import bot, ss14_db, stats_db
from commands.moderation.mod_common import reply
from commands.player.player_common import fail, send_private
from dataConfig import PLAYER_STATS_SERVER
from player_service import COLOR_MAIN, ts, guid_by_discord, link_hint

logger = logging.getLogger(__name__)


@bot.command(name="linked", aliases=["привязка", "link_status"])
async def linked_command(ctx):
    """Показывает, к какому игровому аккаунту привязан Discord."""
    try:
        guid = await guid_by_discord(ctx.author.id)
        if not guid:
            await reply(ctx, link_hint())
            return

        ckey = await ss14_db.get_player_name(guid, PLAYER_STATS_SERVER)
        row = await stats_db.player_row(guid, PLAYER_STATS_SERVER)
    except Exception as e:
        await fail(ctx, e, "linked")
        return

    embed = disnake.Embed(
        title="🔗 Привязка аккаунта",
        description="Discord привязан к игровому аккаунту.",
        color=COLOR_MAIN,
    )
    embed.add_field(name="Ник в игре", value=ckey or "неизвестно", inline=True)
    embed.add_field(name="UID", value=f"`{guid}`", inline=False)

    if row is not None:
        embed.add_field(name="Первый заход", value=ts(row["first_seen_time"], "D"), inline=True)
        embed.add_field(name="Последний заход", value=ts(row["last_seen_time"], "R"), inline=True)

    embed.set_footer(text="UID никому не показывай: по нему тебя опознают на сервере")

    if await send_private(ctx, embed=embed):
        await reply(ctx, "📬 Отправил в личку.")
