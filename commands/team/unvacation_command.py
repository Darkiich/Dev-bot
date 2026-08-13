"""
Команда досрочного снятия отпуска.

    &unvacation @user - снять отпуск
    &unvacation @user Вышел раньше - снять с комментарием
"""

import disnake

from disnake.ext import commands
from disnake.ext.commands import has_any_role

from bot_init import bot, vacation_db
from dataConfig import ROLE_ACCESS_HEADS
from vacation_service import announce, build_cancel_embed, revoke_vacation_role

USAGE = (
    "**Использование:** `&unvacation <@участник> [комментарий]`\n"
    "**Пример:** `&unvacation @Darkiich Вышел раньше срока`"
)


@bot.command(name="unvacation", aliases=["unvac", "vacation_off"])
# @has_any_role(*ROLE_ACCESS_HEADS)
async def unvacation_command(ctx, member: disnake.Member, *, comment: str = ""):
    """Снимает отпуск досрочно: чистит БД, снимает роль и оповещает канал."""
    ok, info = await vacation_db.delete_vacation(member.id)

    if not ok and info == "not_found":
        # Записи нет, но роль могла остаться
        _, role_status = await revoke_vacation_role(member, reason=f"Снятие отпуска, {ctx.author}")
        await ctx.send(f"ℹ️ У {member.mention} нет активного отпуска в БД.\n{role_status}")
        return

    if not ok:
        await ctx.send(f"❌ Не удалось удалить отпуск из БД:\n```{info}```")
        return

    ok_role, role_status = await revoke_vacation_role(
        member, reason=f"Досрочное снятие отпуска, {ctx.author}"
    )

    sent = await announce(
        build_cancel_embed(member.id, member, comment=comment.strip() or None)
    )

    lines = [f"✅ Отпуск для {member.mention} снят"]

    if not ok_role:
        lines.append(role_status)

    if not sent:
        lines.append("⚠️ Не удалось отправить сообщение в канал отпусков, проверь права бота.")

    await ctx.send("\n".join(lines))


@unvacation_command.error
async def unvacation_command_error(ctx, error):
    if isinstance(error, commands.MissingAnyRole):
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Не хватает аргументов.\n\n{USAGE}")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send(f"❌ Участник `{error.argument}` не найден на сервере.\n\n{USAGE}")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Неверный аргумент: {error}\n\n{USAGE}")
    else:
        await ctx.send(f"❗ Ошибка при снятии отпуска: `{error}`")
