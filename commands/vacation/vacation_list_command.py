"""
Просмотр отпусков.

    &vacations - список активных и запланированных отпусков
    &vacation_info @user - отпуск конкретного участника
"""

import disnake

from disnake.ext import commands
from disnake.ext.commands import has_any_role

from bot_init import bot, vacation_db
from dataConfig import GENERAL_ACCESS
from vacation_service import COLOR_INFO, COLOR_START, describe_row
from vacation_time import fmt, human_delta, now_local

FIELD_VALUE_LIMIT = 1024   # лимит Discord на значение поля
EMBED_TOTAL_LIMIT = 5800   # лимит Discord на эмбед 6000, оставляем запас
MAX_FIELDS = 25            # лимит Discord на количество полей


def _chunk(lines: list[str]) -> list[str]:
    """Режет список строк на куски, влезающие в одно поле эмбеда."""
    chunks, current, size = [], [], 0

    for line in lines:
        line = line[:FIELD_VALUE_LIMIT]
        if size + len(line) + 1 > FIELD_VALUE_LIMIT and current:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1

    if current:
        chunks.append("\n".join(current))

    return chunks or [""]


def _add_group(embed: disnake.Embed, title: str, lines: list[str]) -> bool:
    """False, если упёрлись в лимиты Discord и часть данных не влезла."""
    for index, chunk in enumerate(_chunk(lines)):
        name = title if index == 0 else f"{title} (продолжение)"

        if len(embed.fields) >= MAX_FIELDS or len(embed) + len(name) + len(chunk) > EMBED_TOTAL_LIMIT:
            return False

        embed.add_field(name=name, value=chunk, inline=False)

    return True


@bot.command(name="vacations", aliases=["vacation_list", "otpuska"])
@has_any_role(*GENERAL_ACCESS)
async def vacations_command(ctx):
    """Показывает, кто сейчас в отпуске и у кого отпуск запланирован."""
    rows = await vacation_db.get_all_vacations()

    if rows is None:
        await ctx.send("❌ База отпусков недоступна. Попробуй позже или проверь логи бота.")
        return

    now = now_local()
    active, planned = [], []

    for row in rows or []:
        start = row.get("start_vacation")
        end = row.get("end_vacation")

        if end is not None and end <= now:
            continue  # снимется ближайшей проверкой, показывать незачем
        if start is not None and start > now:
            planned.append(row)
        else:
            active.append(row)

    if not active and not planned:
        await ctx.send("📭 Сейчас в отпуске никого нет.")
        return

    embed = disnake.Embed(title="🌴 Отпуска команды проекта", color=COLOR_START)

    for title, group in (
        (f"В отпуске ({len(active)})", active),
        (f"Запланировано ({len(planned)})", planned),
    ):
        if not group:
            continue
        if not _add_group(embed, title, [describe_row(r, now) for r in group]):
            embed.set_footer(text="Список не поместился целиком")
            break

    await ctx.send(embed=embed)


@bot.command(name="vacation_info", aliases=["vacinfo"])
# @has_any_role(*GENERAL_ACCESS)
async def vacation_info_command(ctx, member: disnake.Member = None):
    """Показывает отпуск участника, без аргумента свой."""
    member = member or ctx.author

    record = await vacation_db.get_vacation(member.id)
    if not record:
        await ctx.send(f"📭 У {member.mention} нет записи об отпуске.")
        return

    now = now_local()
    start = record.get("start_vacation")
    end = record.get("end_vacation")

    if end is not None and end <= now:
        status = "срок вышел, снимется ближайшей проверкой"
    elif start is not None and start > now:
        status = f"запланирован с {fmt(start)}"
    else:
        status = "в отпуске"

    embed = disnake.Embed(
        title="🌴 Отпуск",
        description=f"{member.mention} - {status}",
        color=COLOR_INFO,
    )
    embed.add_field(name="До", value=fmt(end), inline=True)

    if end and end > now:
        embed.add_field(name="Осталось", value=human_delta(end - now), inline=True)

    embed.add_field(name="Причина", value=record.get("reason"), inline=False)
    embed.set_thumbnail(url=member.display_avatar.url)

    await ctx.send(embed=embed)


@vacations_command.error
@vacation_info_command.error
async def vacation_view_error(ctx, error):
    if isinstance(error, commands.MissingAnyRole):
        return

    if isinstance(error, commands.MemberNotFound):
        await ctx.send(f"❌ Участник `{error.argument}` не найден на сервере.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Неверный аргумент: {error}")
    else:
        await ctx.send(f"❗ Ошибка: `{error}`")
