"""
Снятие с должности.

    &fire @user @Разработчик
    &fire @user @Разработчик Ушёл по своему желанию

Роль отдела снимается, если в отделе у человека ничего не осталось,
общая роль команды проекта - если не осталось должностей вообще.
"""

import disnake

from disnake.ext.commands import has_any_role

from bot_init import bot
from dataConfig import ROLE_ACCESS_HEADS
from team_service import MENTIONS, command_error_text, perform_fire

USAGE = (
    "**Использование:** `&fire <@участник> <@должность> [причина]`\n"
    "Должность указывается ролью: упоминанием, ID или названием в кавычках.\n"
    "**Пример:** `&fire @Darkiich @Младший разработчик Пропал на два месяца`"
)


@bot.command(name="fire", aliases=["uvolit"])
@has_any_role(*ROLE_ACCESS_HEADS)
async def fire_command(ctx, member: disnake.Member, role: disnake.Role, *, reason: str = ""):
    """Снимает с участника должность и, если нужно, роль отдела."""
    text = await perform_fire(member, role, ctx.author, reason.strip())
    await ctx.send(text, allowed_mentions=MENTIONS)


@fire_command.error
async def fire_command_error(ctx, error):
    text = command_error_text(error, USAGE)
    if text:
        await ctx.send(text, allowed_mentions=MENTIONS)
