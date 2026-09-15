"""
&vs - сравнение двух игроков
"""

import logging

import disnake

from bot_init import bot, stats_db
from commands.moderation.mod_common import error_text, reply
from commands.player.player_common import fail, require_account
from dataConfig import PLAYER_STATS_SERVER
from player_service import (
    COLOR_MAIN,
    MENTIONS,
    account_by_token,
    as_utc,
    fmt_hours,
    played_roles,
    summary_of,
    ts,
)

logger = logging.getLogger(__name__)

USAGE = "**Использование:** `&vs <@участник | ник в игре>`"


def _versus(mine: str, theirs: str, mine_wins: bool | None) -> str:
    """Строка сравнения: медаль достаётся тому, кто впереди."""
    left = f"🏆 {mine}" if mine_wins is True else mine
    right = f"🏆 {theirs}" if mine_wins is False else theirs
    return f"{left} · {right}"


def _winner(mine, theirs) -> bool | None:
    if mine == theirs:
        return None
    return mine > theirs


def _favourite(data: dict) -> str:
    roles = played_roles(data["times"])
    if not roles:
        return "нет"
    name, delta, _ = roles[0]
    return f"{name} ({fmt_hours(delta)})"


@bot.command(name="vs", aliases=["сравнить", "против"])
async def vs_command(ctx, *, target: str):
    """Сравнивает тебя с другим игроком."""
    guid, ckey = await require_account(ctx)
    if guid is None:
        return

    try:
        other_guid, other_ckey, problem = await account_by_token(target)
        if problem:
            await reply(ctx, f"❌ {problem}")
            return

        if str(other_guid) == str(guid):
            await reply(ctx, "Сравнивать себя с собой скучно. Укажи кого-нибудь другого.")
            return

        mine = await summary_of(guid)
        theirs = await summary_of(other_guid)
        if not mine or not theirs:
            await reply(ctx, "❌ Одного из игроков нет в игровой базе.")
            return

        together = await stats_db.common_rounds(guid, other_guid, PLAYER_STATS_SERVER)
    except Exception as e:
        await fail(ctx, e, "vs")
        return

    mine_first = as_utc(mine["player"]["first_seen_time"])
    their_first = as_utc(theirs["player"]["first_seen_time"])

    embed = disnake.Embed(
        title=f"⚔️ {ckey} против {other_ckey}",
        color=COLOR_MAIN,
    )
    embed.add_field(
        name="Время в игре",
        value=_versus(
            fmt_hours(mine["overall"]),
            fmt_hours(theirs["overall"]),
            _winner(mine["overall"], theirs["overall"]),
        ),
        inline=False,
    )
    embed.add_field(
        name="Раундов",
        value=_versus(str(mine["rounds"]), str(theirs["rounds"]), _winner(mine["rounds"], theirs["rounds"])),
        inline=False,
    )
    embed.add_field(name="Любимая роль", value=f"{_favourite(mine)} · {_favourite(theirs)}", inline=False)

    if mine_first and their_first:
        older = "ты" if mine_first < their_first else other_ckey
        embed.add_field(
            name="На станции с",
            value=f"{ts(mine_first, 'D')} · {ts(their_first, 'D')}\nРаньше пришёл: **{older}**",
            inline=False,
        )

    embed.add_field(name="Вместе в раундах", value=f"**{together}**", inline=False)
    embed.set_footer(text="Слева ты, справа соперник")

    await ctx.send(embed=embed, allowed_mentions=MENTIONS)


@vs_command.error
async def vs_command_error(ctx, error):
    text = error_text(error, USAGE)
    if text:
        await reply(ctx, text)
