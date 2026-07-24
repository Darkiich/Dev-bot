from datetime import datetime, timezone, timedelta

from bot_init import bot, ss14_db
from disnake.ext import tasks

from dataConfig import (
    DB_SIZE_LIMIT_GB,
    DB_SIZE_CHECK_INTERVAL_MIN,
    DB_SIZE_ALERT_CHANNEL_ID,
    DB_SIZE_REALERT_HOURS,
    MY_DS_ID,
)

GB = 1024 ** 3

_last_alert_at = None


def fmt_size(num_bytes: float) -> str:
    """Человекочитаемый размер (Б/КБ/МБ/ГБ/ТБ)."""
    value = float(num_bytes)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if abs(value) < 1024.0:
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} ПБ"


def admin_log_size(databases) -> int:
    """Суммарный размер таблиц admin_log по всем базам (ss14 + ss14_dev)."""
    total = 0
    for d in databases:
        for t in (d.get('tables') or []):
            if t['name'] == 'admin_log' and t['size'] is not None:
                total += t['size']
    return total


@tasks.loop(minutes=DB_SIZE_CHECK_INTERVAL_MIN)
async def db_size_monitor():
    global _last_alert_at

    databases = await ss14_db.get_databases_size()
    if databases is None:
        return

    log_size = admin_log_size(databases)
    limit_bytes = DB_SIZE_LIMIT_GB * GB

    if log_size < limit_bytes:
        _last_alert_at = None
        return

    now = datetime.now(timezone.utc)
    if _last_alert_at is not None and (now - _last_alert_at) < timedelta(hours=DB_SIZE_REALERT_HOURS):
        return

    lines = []
    for d in databases:
        lines.append(f"• {d['datname']}: {fmt_size(d['size'])}")
        for t in (d.get('tables') or []):
            tsize = fmt_size(t['size']) if t['size'] is not None else "—"
            lines.append(f"   └ {t['name']}: {tsize}")
    breakdown = "\n".join(lines)

    body = (
        f"⚠️ **admin_log переполнен!**\n"
        f"Размер admin_log: **{fmt_size(log_size)}** (порог {DB_SIZE_LIMIT_GB} ГБ).\n"
        f"{breakdown}"
    )

    channel = bot.get_channel(DB_SIZE_ALERT_CHANNEL_ID)
    if channel is not None:
        await channel.send(f"<@{MY_DS_ID}> {body}")
    else:
        try:
            user = bot.get_user(MY_DS_ID) or await bot.fetch_user(MY_DS_ID)
            await user.send(body)
        except Exception as e:
            print(f"[db_size_monitor] Канал не найден, и в ЛС отправить не удалось: {e}")
            return

    _last_alert_at = now


@db_size_monitor.before_loop
async def before_db_size_monitor():
    await bot.wait_until_ready()
