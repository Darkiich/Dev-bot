"""
Ежедневный снимок часов: из разницы снимков считается &hours
"""

import logging

from disnake.ext import tasks

from bot_init import bot, player_db, stats_db
from dataConfig import (
    PLAYER_SNAPSHOT_ACTIVE_DAYS,
    PLAYER_SNAPSHOT_HOUR,
    PLAYER_SNAPSHOT_KEEP_DAYS,
    PLAYER_STATS_SERVER,
)
from vacation_time import now_local

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MIN = 30

_last_day = None


async def take_snapshot(force: bool = False) -> int:
    """Снимает часы за сегодня. Повторный вызов за те же сутки ничего не делает."""
    global _last_day

    today = now_local().date()

    if _last_day is None:
        _last_day = await player_db.last_snapshot_day()

    if not force and _last_day == today:
        return 0

    rows = await stats_db.overall_minutes(PLAYER_SNAPSHOT_ACTIVE_DAYS, PLAYER_STATS_SERVER)
    if not rows:
        logger.warning("Снимок часов: игровая база вернула пусто, попробую позже")
        return 0

    saved = await player_db.save_snapshot(today, rows)
    _last_day = today

    removed = await player_db.prune_snapshots(PLAYER_SNAPSHOT_KEEP_DAYS)
    logger.info("Снимок часов за %s: записей %d, удалено старых %d", today, saved, removed)

    return saved


@tasks.loop(minutes=CHECK_INTERVAL_MIN)
async def playtime_snapshot():
    if now_local().hour < PLAYER_SNAPSHOT_HOUR:
        return

    try:
        await take_snapshot()
    except Exception as e:
        logger.exception("Не удалось снять часы: %s", e)


@playtime_snapshot.before_loop
async def before_playtime_snapshot():
    await bot.wait_until_ready()
