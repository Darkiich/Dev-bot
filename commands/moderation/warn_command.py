"""
Предупреждения.

    &warn @user Флуд в общем чате
    &warn (ответом на сообщение нарушителя) Оскорбления
    &unwarn 128 Разобрались, снимаю
    &warns @user
"""

import disnake

from disnake.ext.commands import has_any_role

from bot_init import bot, mod_db
from commands.moderation.mod_common import error_text, evidence_url, reply
from dataConfig import ROLE_ACCESS_MODERATOR
from mod_rules import COLOR_INFO, DEFAULT_REASON, measures_text
from mod_service import next_step_hint, perform_warn, revoke_case
from vacation_time import ts

USAGE = (
    "**Использование:** `&warn <@участник> <причина>`\n"
    "Можно ответить на сообщение нарушителя - ссылка на него попадёт в кейс.\n"
    "**Пример:** `&warn @Darkiich Реклама в общем чате`"
)

UNWARN_USAGE = (
    "**Использование:** `&unwarn <номер кейса> [комментарий]`\n"
    "**Пример:** `&unwarn 128 Разобрались, вина не подтвердилась`"
)


@bot.command(name="warn", aliases=["варн", "предупреждение"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def warn_command(ctx, member: disnake.Member, *, reason: str = ""):
    """Выдаёт предупреждение и, если варнов накопилось, применяет меры наказания."""
    text = await perform_warn(
        member, ctx.author, reason, message_url=evidence_url(ctx)
    )
    await reply(ctx, text)


@warn_command.error
async def warn_command_error(ctx, error):
    text = error_text(error, USAGE)
    if text:
        await reply(ctx, text)


@bot.command(name="unwarn", aliases=["снять_варн"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def unwarn_command(ctx, case_id: int, *, reason: str = ""):
    """Снимает варн по номеру кейса."""
    await reply(ctx, await revoke_case(case_id, ctx.author, reason))


@unwarn_command.error
async def unwarn_command_error(ctx, error):
    text = error_text(error, UNWARN_USAGE)
    if text:
        await reply(ctx, text)


@bot.command(name="warns", aliases=["варны"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def warns_command(ctx, member: disnake.Member = None):
    """Активные варны участника и что будет за следующий."""
    member = member or ctx.author
    rows = await mod_db.active_warns(member.id, ctx.guild.id)

    embed = disnake.Embed(
        title=f"⚠️ Активные варны · {member}",
        color=COLOR_INFO,
        timestamp=disnake.utils.utcnow(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    if not rows:
        embed.description = "Активных варнов нет."
    else:
        for row in rows[:10]:
            reason = (row["reason"] or DEFAULT_REASON)[:200]
            expires = f"\nсгорит {ts(row['expires_at'], 'R')}" if row["expires_at"] else ""
            embed.add_field(
                name=f"Кейс #{row['id']} · {ts(row['created_at'], 'd')}",
                value=f"{reason}\nвыдал <@{row['actor_id']}>{expires}",
                inline=False,
            )

    hint = next_step_hint(len(rows))
    if hint:
        embed.add_field(name="Дальше", value=hint, inline=False)

    embed.add_field(name="Меры наказания", value=measures_text(), inline=False)
    embed.set_footer(text="Снять варн: &unwarn <номер кейса>")

    await reply(ctx, "", embed)
