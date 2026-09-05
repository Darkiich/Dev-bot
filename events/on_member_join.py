"""
Возврат мута тем, кто пытался от него сбежать.
"""

import logging

import disnake

from bot_init import bot, mod_db
from mod_rules import COLOR_WARN
from mod_service import announce_embed, duration_line, muted_role

logger = logging.getLogger(__name__)


@bot.listen("on_member_join")
async def restore_mute_on_join(member: disnake.Member):
    if member.bot:
        return

    case = await mod_db.active_case(member.id, "mute", member.guild.id)
    if case is None:
        return

    role = muted_role(member.guild)
    if role is None:
        logger.warning("Роль мута не найдена, вернуть мут %s не могу", member)
        return

    try:
        await member.add_roles(role, reason=f"Возврат мута при входе, кейс #{case['id']}")
    except (disnake.Forbidden, disnake.HTTPException) as e:
        logger.error("Не удалось вернуть мут %s (%s): %s", member, member.id, e)
        return

    logger.info(
        "Мут возвращён при входе: %s (%s), кейс #%s", member, member.id, case["id"],
    )

    embed = disnake.Embed(
        title="🔇 Мут возвращён при входе",
        description=f"{member.mention} перезашёл на сервер, роль мута надета обратно.",
        color=COLOR_WARN,
        timestamp=disnake.utils.utcnow(),
    )
    embed.add_field(name="Кейс", value=f"#{case['id']}", inline=True)
    embed.add_field(name="Осталось", value=duration_line(case["expires_at"]), inline=True)
    embed.add_field(name="Причина мута", value=(case["reason"] or "")[:500], inline=False)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"ID участника: {member.id}")

    await announce_embed(embed)
