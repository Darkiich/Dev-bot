"""
Понижение на ступень ниже внутри отдела.

    &demote @user @Разработчик
    &demote @user @Разработчик Не справляется с нагрузкой

Работает только по ролям из карьерной лестницы.
"""

import disnake

from disnake.ext.commands import has_any_role

from bot_init import bot
from dataConfig import ROLE_ACCESS_HEADS
from team_service import MENTIONS, command_error_text, perform_move

USAGE = (
    "**Использование:** `&demote <@участник> <@должность> [причина]`\n"
    "Должность указывается ролью: упоминанием, ID или названием в кавычках.\n"
    "**Пример:** `&demote @Darkiich @Разработчик Не справляется с нагрузкой`"
)


@bot.command(name="demote", aliases=["ponizit"])
@has_any_role(*ROLE_ACCESS_HEADS)
async def demote_command(ctx, member: disnake.Member, role: disnake.Role, *, reason: str = ""):
    """Опускает участника на указанную ступень его отдела."""
    text = await perform_move(member, role, ctx.author, "demote", reason.strip())
    await ctx.send(text, allowed_mentions=MENTIONS)


@demote_command.error
async def demote_command_error(ctx, error):
    text = command_error_text(error, USAGE)
    if text:
        await ctx.send(text, allowed_mentions=MENTIONS)
