"""
Команда выдачи отпуска участнику команды проекта.

    &vacation @user 01.09.2026 - до конца 1 сентября (23:59)
    &vacation @user 01.09.2026 18:30 - до 1 сентября 18:30
    &vacation @user 01.09.2026 18:30 Учёба - то же самое, с причиной
    &vacation @user 01.09.2026 Учёба - до конца дня, с причиной

Отпуск всегда начинается в момент выдачи команды.
"""

import disnake

from disnake.ext import commands
from disnake.ext.commands import has_any_role

from bot_init import bot, vacation_db
from dataConfig import ROLE_ACCESS_HEADS
from vacation_service import (
    announce,
    build_start_embed,
    grant_vacation_role,
    parse_vacation_args,
    validate_period,
)
from vacation_time import fmt

USAGE = (
    "**Использование:** `&vacation <@участник> <дата окончания> [время] [причина]`\n"
    "Дата - `01.09.2026`, `2026-09-01` или `01.09`. "
    "Время - `18:30` или `18:30:00`, без него отпуск идёт до конца суток.\n"
    "**Примеры:**\n"
    "`&vacation @Darkiich 01.09.2026 Сессия в универе`\n"
    "`&vacation @Darkiich 01.09.2026 18:30 Вернусь к вечернему созвону`\n"
    "`&vacation @Darkiich 01.09`"
)


@bot.command(name="vacation", aliases=["vac", "otpusk"])
# @has_any_role(*ROLE_ACCESS_HEADS)
async def vacation_command(ctx, member: disnake.Member, date: str, *, rest: str = ""):
    """Выдаёт участнику отпуск до указанной даты, пишет его в БД и оповещает канал."""
    if member.bot:
        await ctx.send("❌ Ботам отпуск не положен.")
        return

    start, end, reason, error = parse_vacation_args(date, rest)
    if error:
        await ctx.send(f"❌ {error}\n\n{USAGE}")
        return

    error = validate_period(start, end)
    if error:
        await ctx.send(f"❌ {error}")
        return

    ok, info = await vacation_db.set_vacation(member.id, start, end, reason)
    if not ok:
        await ctx.send(f"❌ Не удалось записать отпуск в БД:\n```{info}```")
        return

    ok_role, role_status = await grant_vacation_role(
        member, reason=f"Отпуск до {fmt(end)}, оформил {ctx.author}"
    )

    sent = await announce(build_start_embed(member.id, member, end, reason))

    action = "обновлён" if info == "updated" else "оформлен"
    lines = [f"✅ Отпуск для {member.mention} {action} до {fmt(end)}"]

    if not ok_role:
        lines.append(role_status)

    if not sent:
        lines.append("⚠️ Не удалось отправить сообщение в канал отпусков, проверь права бота.")

    await ctx.send("\n".join(lines))


@vacation_command.error
async def vacation_command_error(ctx, error):
    if isinstance(error, commands.MissingAnyRole):
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Не хватает аргументов.\n\n{USAGE}")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send(f"❌ Участник `{error.argument}` не найден на сервере.\n\n{USAGE}")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Неверный аргумент: {error}\n\n{USAGE}")
    else:
        await ctx.send(f"❗ Ошибка при выдаче отпуска: `{error}`")
