"""
Часовой модерации: снимает всё, у чего вышел срок.
"""

import logging

from disnake.ext import tasks

from bot_init import bot, mod_db
from dataConfig import MOD_CHECK_INTERVAL_MIN
from mod_service import expire_case

logger = logging.getLogger(__name__)

# За один проход разбираем ограниченную пачку, чтобы не упереться в лимиты
# Discord: остальное дождётся следующего круга через несколько минут
BATCH = 25


@tasks.loop(minutes=MOD_CHECK_INTERVAL_MIN)
async def mod_monitor():
    """Снимает истёкшие наказания и гасит просроченные варны."""
    try:
        rows = await mod_db.due_cases(("mute", "ban", "lock"))
    except Exception as e:
        logger.error("Не удалось прочитать истёкшие кейсы: %s", e)
        return

    handled = 0
    for row in rows[:BATCH]:
        try:
            if await expire_case(row):
                handled += 1
        except Exception:
            logger.exception("Ошибка при снятии кейса #%s", row["id"])

    expired_warns = await mod_db.expire_warns()

    if handled or expired_warns:
        logger.info(
            "Проверка модерации: снято наказаний %d, сгорело варнов %d",
            handled, expired_warns,
        )


@mod_monitor.before_loop
async def before_mod_monitor():
    await bot.wait_until_ready()
