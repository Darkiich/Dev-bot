import disnake

from bot_init import bot, ss14_db
from disnake.ext import tasks

from dataConfig import SPONSOR_ROLE_ID


def _find_sponsor_guild():
    """Находит гильдию, в которой существует роль спонсора."""
    for guild in bot.guilds:
        if guild.get_role(SPONSOR_ROLE_ID):
            return guild
    return None


@tasks.loop(hours=1)
async def sponsor_role_sync():
    """
    Раз в час синхронизирует роль спонсора с БД
      - выдаёт роль активным спонсорам, у которых её нет;
      - снимает роль у тех, чья спонсорка истекла или удалена из БД.
    """
    if not SPONSOR_ROLE_ID:
        print("[sponsor_role_sync] SPONSOR_ROLE_ID не задан в конфиге.")
        return

    guild = _find_sponsor_guild()
    if guild is None:
        print("[sponsor_role_sync] Гильдия с ролью спонсора не найдена.")
        return

    role = guild.get_role(SPONSOR_ROLE_ID)

    guids = await ss14_db.get_active_sponsor_guids()

    discord_map = await ss14_db.get_discord_ids_by_guids(guids) if guids else {}

    active_ids = {str(did) for did in discord_map.values() if did}

    granted = 0
    revoked = 0

    # Выдаём роль активным спонсорам, у которых её нет
    for discord_id in active_ids:
        try:
            member = guild.get_member(int(discord_id))
        except (ValueError, TypeError):
            continue

        if member is None:
            continue

        if role in member.roles:
            continue

        try:
            await member.add_roles(role, reason="Авто-синхронизация спонсорки (раз в час)")
            granted += 1
        except (disnake.Forbidden, disnake.HTTPException) as e:
            print(f"[sponsor_role_sync] Не удалось выдать роль {discord_id}: {e}")

    # Снимаем роль у тех, кто её имеет, но активным спонсором не является
    for member in list(role.members):
        if str(member.id) in active_ids:
            continue

        try:
            await member.remove_roles(role, reason="Авто-синхронизация спонсорки: подписка истекла")
            revoked += 1
        except (disnake.Forbidden, disnake.HTTPException) as e:
            print(f"[sponsor_role_sync] Не удалось снять роль {member.id}: {e}")

    if granted or revoked:
        print(f"[sponsor_role_sync] Выдано: {granted}, снято: {revoked}")


@sponsor_role_sync.before_loop
async def before_sponsor_role_sync():
    await bot.wait_until_ready()
