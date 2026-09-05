"""
История и кейсы.

    &case 128 - карточка кейса
    &case 128 причина Новая формулировка
    &revoke 128 Комментарий - снять любое наказание по номеру
    &history @user - вся история участника
    &note @user Текст - скрытая заметка, нарушителю не приходит
"""

import disnake

from disnake.ext.commands import has_any_role

from bot_init import bot, mod_db
from commands.moderation.mod_common import error_text, reply
from dataConfig import ROLE_ACCESS_MODERATOR
from mod_service import (
    build_case_detail,
    build_history_embed,
    find_target,
    is_senior,
    perform_note,
    revoke_case,
)

PAGE = 10

CASE_USAGE = (
    "**Использование:**\n"
    "`&case <номер>` - показать кейс\n"
    "`&case <номер> причина <новый текст>` - поправить формулировку\n"
    "`&revoke <номер> [комментарий]` - снять наказание"
)


@bot.command(name="case", aliases=["кейс"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def case_command(ctx, case_id: int, action: str = "", *, value: str = ""):
    """Показывает кейс или правит его причину."""
    row = await mod_db.get_case(case_id)
    if row is None:
        await reply(ctx, f"❌ Кейс #{case_id} не найден.")
        return

    if action.lower() in ("причина", "reason"):
        if not value.strip():
            await reply(ctx, "❌ Новая причина пустая.\n\n" + CASE_USAGE)
            return

        if row["actor_id"] != ctx.author.id and not is_senior(ctx.author):
            await reply(ctx, "❌ Чужие кейсы правит старший состав.")
            return

        updated = await mod_db.update_reason(case_id, value.strip())
        if updated is None:
            await reply(ctx, "⚠️ База недоступна, причина не изменилась.")
            return

        await reply(ctx, f"✏️ Причина кейса #{case_id} обновлена.", build_case_detail(updated))
        return

    await reply(ctx, "", build_case_detail(row))


@case_command.error
async def case_command_error(ctx, error):
    text = error_text(error, CASE_USAGE)
    if text:
        await reply(ctx, text)


@bot.command(name="revoke", aliases=["снять"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def revoke_command(ctx, case_id: int, *, reason: str = ""):
    """Снимает наказание по номеру кейса: варн, мут или бан."""
    await reply(ctx, await revoke_case(case_id, ctx.author, reason))


@revoke_command.error
async def revoke_command_error(ctx, error):
    text = error_text(error, "**Использование:** `&revoke <номер кейса> [комментарий]`")
    if text:
        await reply(ctx, text)


@bot.command(name="history", aliases=["modlogs", "история"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def history_command(ctx, target: str = None, page: int = 1):
    """История наказаний участника, свежие сверху."""
    if target is None:
        user = ctx.author
    else:
        user, problem = await find_target(ctx, target)
        if problem:
            await reply(ctx, f"❌ {problem}")
            return

    page = max(1, page)
    counts = await mod_db.count_cases(user.id)
    total = sum(counts.values())
    rows = await mod_db.list_cases(user.id, limit=PAGE, offset=(page - 1) * PAGE)

    if not rows and page > 1:
        await reply(ctx, f"ℹ️ На странице {page} пусто. Всего кейсов: {total}.")
        return

    embed = build_history_embed(user, rows, page, total, counts)
    if not rows:
        embed.description = "За участником ничего не числится."

    await reply(ctx, "", embed)


@history_command.error
async def history_command_error(ctx, error):
    text = error_text(error, "**Использование:** `&history <@участник или ID> [страница]`")
    if text:
        await reply(ctx, text)


@bot.command(name="note", aliases=["заметка"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def note_command(ctx, target: str, *, text: str = ""):
    """
    Скрытая заметка об участнике. В личку не уходит, наказанием не считается,
    но всплывёт в досье у следующего модератора.
    """
    if not text.strip():
        await reply(ctx, "❌ Пустую заметку сохранять незачем.\n\n"
                         "**Пример:** `&note @Darkiich Просил не пинговать, работает по ночам`")
        return

    user, problem = await find_target(ctx, target)
    if problem:
        await reply(ctx, f"❌ {problem}")
        return

    await reply(ctx, await perform_note(user, ctx.author, text.strip()))


@note_command.error
async def note_command_error(ctx, error):
    text = error_text(error, "**Использование:** `&note <@участник> <текст>`")
    if text:
        await reply(ctx, text)
