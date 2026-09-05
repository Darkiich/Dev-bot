"""
Баны и кики на самом сервере Discord.

    &dban @user 30d Обход мута
    &dban 568092953948454922 перм Рейд - бан по ID, даже если он не заходил
    &dunban 568092953948454922 Отсидел
    &dkick @user Спам в личку участникам
    &softban @user Реклама - кик с чисткой сообщений за сутки

Игровые `&ban` и `&kick` бьют по серверу SS14 и остались как были.
Discord-команды называются иначе специально, чтобы их не путали в спешке.
"""

import disnake

from commands.moderation.mod_common import error_text, evidence_url, reply
from dataConfig import ROLE_ACCESS_MODERATOR
from disnake.ext.commands import has_any_role

from bot_init import bot
from mod_rules import split_duration
from mod_service import (
    find_target,
    perform_ban,
    perform_kick,
    perform_softban,
    perform_unban,
)

BAN_USAGE = (
    "**Использование:** `&dban <@участник или ID> [срок] [причина]`\n"
    "Срок: `7d`, `30d`, `12h`, `перм`. Без срока бан вечный.\n"
    "**Пример:** `&dban @Darkiich 30d Обход мута с второго аккаунта`"
)

KICK_USAGE = (
    "**Использование:** `&dkick <@участник> [причина]`\n"
    "**Пример:** `&dkick @Darkiich Спам в личку участникам`"
)


@bot.command(name="dban", aliases=["ds_ban", "забанить"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def dban_command(ctx, target: str, *, rest: str = ""):
    """Банит участника Discord. Срок необязателен, без него бан вечный."""
    user, problem = await find_target(ctx, target)
    if problem:
        await reply(ctx, f"❌ {problem}\n\n{BAN_USAGE}")
        return

    duration, reason, _ = split_duration(rest)

    text = await perform_ban(
        user, ctx.author, duration, reason, message_url=evidence_url(ctx)
    )
    await reply(ctx, text)


@dban_command.error
async def dban_command_error(ctx, error):
    text = error_text(error, BAN_USAGE)
    if text:
        await reply(ctx, text)


@bot.command(name="dunban", aliases=["ds_unban", "разбанить"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def dunban_command(ctx, user_id: str, *, reason: str = ""):
    """Снимает бан Discord по ID."""
    digits = "".join(ch for ch in user_id if ch.isdigit())
    if not digits:
        await reply(ctx, "❌ Нужен ID пользователя: `&dunban 568092953948454922 причина`")
        return

    await reply(ctx, await perform_unban(int(digits), ctx.author, reason))


@dunban_command.error
async def dunban_command_error(ctx, error):
    text = error_text(error, "**Использование:** `&dunban <ID> [комментарий]`")
    if text:
        await reply(ctx, text)


@bot.command(name="dkick", aliases=["ds_kick", "выгнать"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def dkick_command(ctx, member: disnake.Member, *, reason: str = ""):
    """Выгоняет участника с сервера Discord."""
    text = await perform_kick(member, ctx.author, reason, message_url=evidence_url(ctx))
    await reply(ctx, text)


@dkick_command.error
async def dkick_command_error(ctx, error):
    text = error_text(error, KICK_USAGE)
    if text:
        await reply(ctx, text)


@bot.command(name="softban", aliases=["софтбан"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def softban_command(ctx, member: disnake.Member, *, reason: str = ""):
    """
    Кик с чисткой: бан и сразу разбан. Сообщения нарушителя за сутки
    удаляются, вернуться по приглашению он может сразу.
    """
    text = await perform_softban(member, ctx.author, reason)
    await reply(ctx, text)


@softban_command.error
async def softban_command_error(ctx, error):
    text = error_text(error, "**Использование:** `&softban <@участник> [причина]`")
    if text:
        await reply(ctx, text)
