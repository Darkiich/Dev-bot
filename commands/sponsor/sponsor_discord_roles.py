# Синхронизация ролей дискорда с новой спонсоркой.

import disnake
from disnake.ext import tasks

from bot_init import bot, ss14_db

from .sponsor_api import SponsorApi, SponsorApiError

SYNC_INTERVAL_HOURS = 1

@tasks.loop(hours=SYNC_INTERVAL_HOURS)
async def sponsor_discord_roles_sync():
    try:
        await _sync()
    except SponsorApiError as error:
        print(f"[sponsor_roles] Игровое API недоступно: {error}")
    except Exception as error:
        print(f"[sponsor_roles] Сбой синхронизации: {error!r}")

async def _sync():
    api = SponsorApi("00000000-0000-0000-0000-000000000000", "sponsor-role-sync")
    data = await api.get_discord_roles()

    managed = {str(role) for role in (data.get("managed") or [])}

    if not managed:
        return

    players = data.get("players") or {}

    discord_by_guid = await ss14_db.get_discord_ids_by_guids(list(players.keys())) if players else {}

    wanted = {}

    for guid, roles in players.items():
        discord_id = discord_by_guid.get(guid)

        if not discord_id:
            continue

        wanted.setdefault(str(discord_id), set()).update(str(role) for role in roles)

    granted = 0
    revoked = 0

    for guild in bot.guilds:
        guild_roles = {}

        for role_id in managed:
            try:
                role = guild.get_role(int(role_id))
            except (TypeError, ValueError):
                print(f"[sponsor_roles] Некорректный ID роли в тире: {role_id!r}")
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
                        await member.add_roles(role, reason="Спонсорка")
                        granted += 1
                    else:
                        await member.remove_roles(role, reason="Спонсорка")
                        revoked += 1
                except disnake.Forbidden:
                    print(f"[sponsor_roles] Нет прав на роль {role.name} в гильдии {guild.name}.")
                    break
                except disnake.HTTPException as error:
                    print(f"[sponsor_roles] Ошибка с ролью {role.name} у {member.id}: {error}")

    if granted or revoked:
        print(f"[sponsor_roles] Выдано: {granted}, снято: {revoked}")

@sponsor_discord_roles_sync.before_loop
async def _before():
    await bot.wait_until_ready()

@bot.listen("on_ready")
async def _start_sponsor_role_sync():
    if not sponsor_discord_roles_sync.is_running():
        sponsor_discord_roles_sync.start()
