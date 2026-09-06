import logging

from bot_init import bot, ss14_db
from disnake.ext import tasks

logger = logging.getLogger(__name__)

from dataConfig import (
    DB_SIZE_LIMIT_GB,
    DB_SIZE_CHECK_INTERVAL_MIN,
    DB_SIZE_ALERT_CHANNEL_ID,
    MY_DS_ID,
)

GB = 1024 ** 3


def fmt_size(num_bytes: float) -> str:
    """Человекочитаемый размер (Б/КБ/МБ/ГБ/ТБ)."""
    value = float(num_bytes)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if abs(value) < 1024.0:
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} ПБ"


def admin_log_size(database) -> int:
    """Размер таблицы admin_log в одной базе."""
    for t in (database.get('tables') or []):
        if t['name'] == 'admin_log' and t['size'] is not None:
            return t['size']
    return 0


async def send_alert(body: str):
    """Отправляет алерт в канал, при неудаче в ЛС."""
    channel = bot.get_channel(DB_SIZE_ALERT_CHANNEL_ID)
    if channel is not None:
        await channel.send(f"<@{MY_DS_ID}> {body}")
        return

    try:
        user = bot.get_user(MY_DS_ID) or await bot.fetch_user(MY_DS_ID)
        await user.send(body)
    except Exception as e:
        logger.error("Канал алертов не найден, и в ЛС отправить не удалось: %s", e)


@tasks.loop(minutes=DB_SIZE_CHECK_INTERVAL_MIN)
async def db_size_monitor():
    databases = await ss14_db.get_databases_size()
    if databases is None:
        logger.warning("Не удалось получить размеры БД, проверка пропущена")
        return

    limit_bytes = DB_SIZE_LIMIT_GB * GB

    for d in databases:
        datname = d['datname']
        log_size = admin_log_size(d)

        if log_size < limit_bytes:
            continue

        lines = [f"• {datname}: {fmt_size(d['size'])}"]
        for t in (d.get('tables') or []):
            tsize = fmt_size(t['size']) if t['size'] is not None else "-"
            lines.append(f"   └ {t['name']}: {tsize}")
        breakdown = "\n".join(lines)

        body = (
            f"⚠️ **admin_log переполнен в `{datname}`!**\n"
            f"Размер admin_log: **{fmt_size(log_size)}** (порог {DB_SIZE_LIMIT_GB} ГБ).\n"
            f"{breakdown}"
        )

        logger.warning("admin_log в базе %s превысил порог: %s", datname, fmt_size(log_size))
        await send_alert(body)


@db_size_monitor.before_loop
async def before_db_size_monitor():
    await bot.wait_until_ready()
