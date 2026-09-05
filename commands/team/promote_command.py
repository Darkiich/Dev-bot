"""
Повышение на следующую ступень отдела.

    &promote @user @Старший разработчик
    &promote @user @Старший разработчик Тянет ревью на себе

Работает только по ролям из карьерной лестницы. Отдельные роли вроде
«Тестировщик» повышением не считаются, для них &hire и &fire.
"""

import disnake

from disnake.ext.commands import has_any_role

from bot_init import bot
from dataConfig import ROLE_ACCESS_HEADS
from team_service import MENTIONS, command_error_text, perform_move

USAGE = (
    "**Использование:** `&promote <@участник> <@должность> [причина]`\n"
    "Должность указывается ролью: упоминанием, ID или названием в кавычках.\n"
    "**Пример:** `&promote @Darkiich @Старший разработчик Тянет ревью на себе`"
)


@bot.command(name="promote", aliases=["povysit"])
@has_any_role(*ROLE_ACCESS_HEADS)
async def promote_command(ctx, member: disnake.Member, role: disnake.Role, *, reason: str = ""):
    """Поднимает участника на указанную ступень его отдела."""
    text = await perform_move(member, role, ctx.author, "promote", reason.strip())
    await ctx.send(text, allowed_mentions=MENTIONS)


@promote_command.error
async def promote_command_error(ctx, error):
    text = command_error_text(error, USAGE)
    if text:
        await ctx.send(text, allowed_mentions=MENTIONS)
