"""
Мелочи, общие для всех команд модерации: где нарушился человек и как объяснить кривые аргументы.
"""

import disnake

from disnake.ext import commands


def evidence_url(ctx) -> str | None:
    """
    Ссылка на сообщение, из-за которого выдали наказание.

    Если команду написали ответом на сообщение нарушителя, ссылка ведёт на
    него - это самый быстрый способ приложить доказательство: ответил и
    написал `&warn`. Иначе ссылка ведёт на саму команду.
    """
    if ctx.guild is None:
        return None

    reference = getattr(ctx.message, "reference", None)
    if reference is not None and reference.message_id:
        return (
            f"https://discord.com/channels/{ctx.guild.id}/"
            f"{ctx.channel.id}/{reference.message_id}"
        )

    return ctx.message.jump_url


def error_text(error, usage: str) -> str | None:
    """Ответ на кривые аргументы. None - промолчать, уже ответил общий обработчик."""
    if isinstance(error, (commands.MissingAnyRole, commands.MissingPermissions)):
        return None

    if isinstance(error, commands.MissingRequiredArgument):
        return f"❌ Не хватает аргументов.\n\n{usage}"

    if isinstance(error, commands.MemberNotFound):
        return f"❌ Участник `{error.argument}` не найден на сервере.\n\n{usage}"

    if isinstance(error, commands.UserNotFound):
        return f"❌ Пользователь `{error.argument}` не найден.\n\n{usage}"

    if isinstance(error, commands.ChannelNotFound):
        return f"❌ Канал `{error.argument}` не найден.\n\n{usage}"

    if isinstance(error, commands.BadArgument):
        return f"❌ Неверный аргумент: {error}\n\n{usage}"

    return f"❗ Ошибка: `{error}`"


async def reply(ctx, text: str, embed: disnake.Embed = None):
    """Ответ модератору. Длинный текст режем, чтобы Discord не отбил сообщение."""
    mentions = disnake.AllowedMentions(everyone=False, roles=False, users=True)
    await ctx.send(text[:1990] if text else None, embed=embed, allowed_mentions=mentions)
