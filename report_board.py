"""
Одно сообщение-отчёт в канале
"""

import logging

import disnake

from bot_init import bot

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 50


def _is_own(message, match) -> bool:
    if bot.user is None or message.author.id != bot.user.id:
        return False
    return match(message) if match else True


async def _candidates(channel, match) -> list:
    """Свои отчёты в канале: закреплённые плюс свежая история."""
    found = {}

    try:
        async for message in channel.pins():
            if _is_own(message, match):
                found[message.id] = message
    except (disnake.Forbidden, disnake.HTTPException) as e:
        logger.warning("Не удалось прочитать закреплённые в %s: %s", channel.id, e)

    try:
        async for message in channel.history(limit=HISTORY_LIMIT):
            if _is_own(message, match):
                found[message.id] = message
    except (disnake.Forbidden, disnake.HTTPException) as e:
        logger.warning("Не удалось прочитать историю %s: %s", channel.id, e)

    return sorted(found.values(), key=lambda message: message.created_at)


async def _pin(message, label: str):
    try:
        await message.pin()
        logger.info("%s закреплён в %s", label, message.channel.id)
    except (disnake.Forbidden, disnake.HTTPException) as e:
        logger.warning("%s не закрепился: %s", label, e)


async def _drop(message, label: str):
    try:
        await message.delete()
        logger.info("Лишний %s удалён из %s", label, message.channel.id)
    except (disnake.Forbidden, disnake.HTTPException) as e:
        logger.warning("Лишний %s не удалился: %s", label, e)


async def refresh_board(channel, embeds: list, match=None, label: str = "отчёт", mentions=None):
    """Обновляет отчёт в канале и возвращает сообщение или None при ошибке."""
    messages = await _candidates(channel, match)

    try:
        if not messages:
            message = await channel.send(embeds=embeds, allowed_mentions=mentions)
            await _pin(message, label)
            return message

        board = next((message for message in messages if message.pinned), messages[0])
        await board.edit(embeds=embeds, allowed_mentions=mentions)
    except (disnake.Forbidden, disnake.HTTPException) as e:
        logger.error("Не удалось обновить %s в %s: %s", label, channel.id, e)
        return None

    for extra in messages:
        if extra.id != board.id:
            await _drop(extra, label)

    if not board.pinned:
        await _pin(board, label)

    return board
