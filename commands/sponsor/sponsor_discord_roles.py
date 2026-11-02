# Единая синхронизация ролей дискорда для старой и новой спонсорки.

import asyncio
import logging

import disnake
from disnake.ext import tasks

from bot_init import bot, ss14_db
from dataConfig import SPONSOR_ROLE_ID

from .sponsor_api import SponsorApi, SponsorApiError

logger = logging.getLogger(__name__)

SYNC_INTERVAL_HOURS = 1

_sync_lock = asyncio.Lock()


async def _collect_wanted():
    api = SponsorApi("00000000-0000-0000-0000-000000000000", "sponsor-role-sync")
    data = await api.get_discord_roles()

    managed = {str(role) for role in (data.get("managed") or [])}
    players = data.get("players") or {}

    old_role = str(SPONSOR_ROLE_ID) if SPONSOR_ROLE_ID else None
    if old_role:
        managed.add(old_role)

    old_guids = [str(g) for g in await ss14_db.get_active_sponsor_guids()] if old_role else []

    all_guids = list(set(players.keys()) | set(old_guids))
    discord_by_guid = await ss14_db.get_discord_ids_by_guids(all_guids) if all_guids else {}

    wanted = {}

    # Новая спонсорка: роли из тиров
    for guid, roles in players.items():
        discord_id = discord_by_guid.get(guid)
        if not discord_id:
            continue
        wanted.setdefault(str(discord_id), set()).update(str(role) for role in roles)

    # Старая спонсорка: общая роль спонсора
    if old_role:
        for guid in old_guids:
            discord_id = discord_by_guid.get(guid)
            if not discord_id:
                continue
            wanted.setdefault(str(discord_id), set()).add(old_role)

    return managed, wanted


async def sync_sponsor_roles(reason: str = "Спонсорка") -> tuple[int, int]:
    async with _sync_lock:
        managed, wanted = await _collect_wanted()

        if not managed:
            return 0, 0

        granted = 0
        revoked = 0

        for guild in bot.guilds:
            guild_roles = {}

            for role_id in managed:
                try:
                    role = guild.get_role(int(role_id))
                except (TypeError, ValueError):
                    logger.warning("Некорректный ID роли спонсора: %r", role_id)
                    continue

                if role is not None:
                    guild_roles[role_id] = role

            if not guild_roles:
                continue

            for member in guild.members:
                member_wanted = wanted.get(str(member.id), set())
                member_roles = {role.id for role in member.roles}

                for role_id, role in guild_roles.items():
                    should_have = role_id in member_wanted
                    has = role.id in member_roles

                    if should_have == has:
                        continue

                    try:
                        if should_have:
                            await member.add_roles(role, reason=reason)
                            granted += 1
                        else:
                            await member.remove_roles(role, reason=reason)
                            revoked += 1
                    except disnake.Forbidden:
                        logger.error("Нет прав на роль %s в гильдии %s", role.name, guild.name)
                        break
                    except disnake.HTTPException as error:
                        logger.error("Ошибка с ролью %s у %s: %s", role.name, member.id, error)

        if granted or revoked:
            logger.info("Синхронизация ролей спонсоров: выдано %d, снято %d", granted, revoked)

        return granted, revoked


@tasks.loop(hours=SYNC_INTERVAL_HOURS)
async def sponsor_discord_roles_sync():
    try:
        await sync_sponsor_roles("Авто-синхронизация спонсорки")
    except SponsorApiError as error:
        logger.error("Игровое API недоступно, синхронизация ролей пропущена: %s", error)
    except Exception:
        logger.exception("Сбой синхронизации ролей спонсоров")


@sponsor_discord_roles_sync.before_loop
async def _before():
    await bot.wait_until_ready()


@bot.listen("on_ready")
async def _start_sponsor_role_sync():
    if not sponsor_discord_roles_sync.is_running():
        sponsor_discord_roles_sync.start()
