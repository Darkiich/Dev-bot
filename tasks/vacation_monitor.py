"""
Ежечасная проверка отпусков: снимает истёкшие, возвращает роль тем,
у кого она слетела, и убирает роль у тех, кого нет в базе.
"""

from disnake.ext import tasks

from bot_init import bot, vacation_db
from dataConfig import (
    VACATION_CHECK_INTERVAL_MIN,
    VACATION_ROLE_ID,
    VACATION_ROLE_STRICT_SYNC,
)
from vacation_service import (
    announce,
    build_end_embed,
    build_start_embed,
    find_vacation_guild,
    get_vacation_role,
    grant_vacation_role,
    resolve_member,
    revoke_vacation_role,
)
from vacation_time import fmt, now_local


# Про кого уже писали в лог, чтобы не повторять одно и то же каждый час
_REPORTED = set()


def _report_once(who, status: str):
    """Часть причин неустранима, например владельца сервера не тронуть никак."""
    key = (str(getattr(who, "id", who)), status)
    if key in _REPORTED:
        return
    _REPORTED.add(key)
    print(f"[vacation_monitor] {who}: {status.lstrip('✅ℹ️⚠️ ').replace('**', '')}")


async def _finish_vacation(guild, row) -> bool:
    """Снимает истёкший отпуск. Возвращает True, если запись обработана."""
    ds_id = row["ds_id"]

    ok, info = await vacation_db.delete_vacation(ds_id)
    if not ok and info != "not_found":
        print(f"[vacation_monitor] Не удалось удалить запись {ds_id}: {info}")
        return False

    member = await resolve_member(guild, ds_id)

    if member is not None:
        ok_role, status = await revoke_vacation_role(member, reason="Срок отпуска истёк")
        if not ok_role:
            _report_once(member, status)

    await announce(build_end_embed(ds_id, member))

    print(f"[vacation_monitor] Отпуск окончен: {ds_id} (до {fmt(row.get('end_vacation'))})")
    return True


async def _begin_vacation(guild, row) -> bool:
    """Выдаёт роль тому, у кого отпуск идёт, а роли нет."""
    ds_id = row["ds_id"]

    member = await resolve_member(guild, ds_id)
    role = get_vacation_role(guild)

    if member is None or role is None or role in member.roles:
        return False

    ok_role, status = await grant_vacation_role(member, reason="Начало отпуска")
    if not ok_role:
        _report_once(member, status)
        return False

    await announce(build_start_embed(
        ds_id, member, row.get("end_vacation"), row.get("reason"), scheduled=True
    ))

    print(f"[vacation_monitor] Отпуск начался: {ds_id} (до {fmt(row.get('end_vacation'))})")
    return True


async def _strict_sync(guild, active_ids: set) -> int:
    """Снимает роль отпуска у тех, кого нет среди активных отпусков."""
    role = get_vacation_role(guild)
    if role is None:
        return 0

    revoked = 0
    for member in list(role.members):
        if str(member.id) in active_ids:
            continue

        ok, status = await revoke_vacation_role(
            member, reason="Синхронизация отпусков: записи в БД нет"
        )
        if ok:
            revoked += 1
        else:
            _report_once(member, status)

    return revoked


@tasks.loop(minutes=VACATION_CHECK_INTERVAL_MIN)
async def vacation_monitor():
    """Раз в час сверяет базу отпусков с реальностью."""
    if not VACATION_ROLE_ID:
        print("[vacation_monitor] VACATION_ROLE_ID не задан в конфиге.")
        return

    guild = find_vacation_guild()
    if guild is None:
        print("[vacation_monitor] Гильдия с ролью отпуска не найдена.")
        return

    if get_vacation_role(guild) is None:
        print(f"[vacation_monitor] Роль {VACATION_ROLE_ID} не найдена на сервере {guild.name}.")
        return

    try:
        rows = await vacation_db.get_all_vacations()
    except Exception as e:
        print(f"[vacation_monitor] Ошибка чтения БД: {e}")
        return

    # None это недоступная БД. Продолжать нельзя: строгая синхронизация примет
    # "нет данных" за "отпусков нет" и снимет роль у всех
    if rows is None:
        print("[vacation_monitor] База отпусков недоступна, проверка пропущена.")
        return

    now = now_local()
    finished = started = 0
    active_ids = set()

    for row in rows:
        start = row.get("start_vacation")
        end = row.get("end_vacation")

        if end is not None and end <= now:
            if await _finish_vacation(guild, row):
                finished += 1
            continue

        if start is not None and start > now:
            continue

        active_ids.add(str(row["ds_id"]))

        if await _begin_vacation(guild, row):
            started += 1

    revoked = await _strict_sync(guild, active_ids) if VACATION_ROLE_STRICT_SYNC else 0

    if finished or started or revoked:
        print(
            f"[vacation_monitor] Начато: {started}, окончено: {finished}, "
            f"снято лишних ролей: {revoked}"
        )


@vacation_monitor.before_loop
async def before_vacation_monitor():
    await bot.wait_until_ready()
