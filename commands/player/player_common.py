"""
Мелочи, общие для игроцких команд: отказы, личка и единый ответ об ошибке.
"""

import logging

import disnake

from AHelperManager.database_stats import SchemaError
from commands.moderation.mod_common import reply
from player_service import own_account

logger = logging.getLogger(__name__)


async def require_account(ctx):
    """Аккаунт автора или None. Отказ бот отправляет сам."""
    guid, ckey, problem = await own_account(ctx)
    if problem:
        await reply(ctx, problem)
        return None, None

    return guid, ckey


async def fail(ctx, error: Exception, what: str):
    """Ошибку игроку показываем одной строкой, подробности уходят в лог."""
    if isinstance(error, SchemaError):
        logger.error("Структура игровой базы не подходит (%s): %s", what, error)
        await reply(ctx, f"❌ Не удалось прочитать игровую базу: {error}")
        return

    logger.exception("Ошибка команды %s: %s: %s", what, type(error).__name__, error)
    await reply(ctx, "❗ Не получилось получить данные, ошибка записана в лог.")


async def send_private(ctx, embed: disnake.Embed = None, content: str = None) -> bool:
    """Ответ в личку. False, если она закрыта."""
    try:
        await ctx.author.send(content=content, embed=embed)
        return True
    except disnake.Forbidden:
        await reply(ctx, "❌ Не могу написать в личку. Открой личные сообщения от участников сервера.")
        return False
    except disnake.HTTPException as e:
        logger.warning("Не удалось отправить личку %s: %s", ctx.author, e)
        await reply(ctx, "❗ Не получилось отправить сообщение в личку.")
        return False
