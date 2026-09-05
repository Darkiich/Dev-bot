"""
Приём в отдел.

    &hire @user @Разработчик
    &hire @user @Разработчик Прошёл стажировку

Вместе с должностью выдаётся роль отдела и общая роль команды проекта.
"""

import disnake

from disnake.ext.commands import has_any_role

from bot_init import bot
from dataConfig import ROLE_ACCESS_HEADS
from team_service import MENTIONS, command_error_text, perform_hire

USAGE = (
    "**Использование:** `&hire <@участник> <@должность> [причина]`\n"
    "Должность указывается ролью: упоминанием, ID или названием в кавычках.\n"
    "**Пример:** `&hire @Darkiich @Младший разработчик Прошёл стажировку`"
)


@bot.command(name="hire", aliases=["nanyat"])
@has_any_role(*ROLE_ACCESS_HEADS)
async def hire_command(ctx, member: disnake.Member, role: disnake.Role, *, reason: str = ""):
    """Принимает участника в отдел на указанную должность."""
    text = await perform_hire(member, role, ctx.author, reason.strip())
    await ctx.send(text, allowed_mentions=MENTIONS)


@hire_command.error
async def hire_command_error(ctx, error):
    text = command_error_text(error, USAGE)
    if text:
        await ctx.send(text, allowed_mentions=MENTIONS)
