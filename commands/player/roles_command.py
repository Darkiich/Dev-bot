"""
&roles - все роли с наигранными часами
"""

import logging

import disnake

from bot_init import bot
from commands.moderation.mod_common import reply
from commands.player.player_common import fail, require_account
from player_jobs import DEPARTMENTS, job_department, job_name
from player_service import COLOR_MAIN, MENTIONS, fmt_hours, played_roles, summary_of

logger = logging.getLogger(__name__)

FIELD_LIMIT = 1024


def _department_lines(roles: list) -> dict:
    """Роли по отделам: {отдел: [строки]}."""
    grouped = {}
    for tracker, delta in roles:
        grouped.setdefault(job_department(tracker), []).append(
            f"**{job_name(tracker)}** - {fmt_hours(delta)}"
        )
    return grouped


def _trim(lines: list) -> str:
    """Поле эмбеда не резиновое, лишнее сворачиваем в счётчик."""
    text = ""
    for index, line in enumerate(lines):
        tail = f"\nи ещё {len(lines) - index}"
        if len(text) + len(line) + len(tail) + 1 > FIELD_LIMIT:
            return text + tail
        text += ("\n" if text else "") + line
    return text


@bot.command(name="roles", aliases=["роли"])
async def roles_command(ctx):
    """Время по всем ролям и список ролей, на которых ещё не играл."""
    guid, ckey = await require_account(ctx)
    if guid is None:
        return

    try:
        data = await summary_of(guid)
    except Exception as e:
        await fail(ctx, e, "roles")
        return

    if not data:
        await reply(ctx, "❌ Этого игрока нет в игровой базе.")
        return

    roles = played_roles(data["times"])
    if not roles:
        await reply(ctx, "Ты ещё не отыграл ни одной роли. Самое время это исправить.")
        return

    embed = disnake.Embed(
        title=f"🧰 Роли · {ckey}",
        description=f"Всего ролей отыграно: **{len(roles)}**",
        color=COLOR_MAIN,
    )

    grouped = _department_lines(roles)
    for key, title in DEPARTMENTS:
        lines = grouped.get(key)
        if lines:
            embed.add_field(name=title, value=_trim(lines), inline=False)

    await ctx.send(embed=embed, allowed_mentions=MENTIONS)
