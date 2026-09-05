"""
Фоновая сверка состава в базе с ролями Discord.

Нужна для случаев, когда роли раздают руками мимо бота: без сверки такие
люди не попадут в аналитику, а у снятых вручную останутся мёртвые строки.

Сверка идёт в обе стороны: кого нет в базе - заводит, чья роль пропала -
убирает. События помечаются source='sync', поэтому в наймы и текучку за
период не попадают: это не решение главы, а следствие ручной правки.

Роли задача не трогает вообще. Discord тут источник правды, база догоняет.
"""

import asyncio
import logging

import disnake

from disnake.ext import tasks

from bot_init import bot, team_db
from dataConfig import TEAM_SYNC_INTERVAL_MIN, LOG_CHANNEL_ID
from team_service import COLOR_INFO, announce, collect_import_rows, find_team_guild

logger = logging.getLogger(__name__)


async def _load_members(guild) -> bool:
    """Догружает список участников, если он ещё не в кэше."""
    if guild.chunked:
        return True

    try:
        await guild.chunk()
        return True
    except (disnake.HTTPException, asyncio.TimeoutError) as e:
        logger.error("Не удалось загрузить участников гильдии: %s", e)
        return False


async def _report(added: int, removed: int):
    embed = disnake.Embed(
        title="🔄 Сверка состава",
        description="Роли меняли мимо бота, база подтянута.",
        color=COLOR_INFO,
    )

    if added:
        embed.add_field(name="Добавлено должностей", value=str(added), inline=True)
    if removed:
        embed.add_field(name="Убрано должностей", value=str(removed), inline=True)

    await announce(embed)

    if not LOG_CHANNEL_ID:
        logger.warning("LOG_CHANNEL_ID не задан в конфиге.")
        return False

    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(LOG_CHANNEL_ID)
        except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException) as e:
            logger.error("Канал кадровых действий %s недоступен: %s", LOG_CHANNEL_ID, e)
            return False

    try:
        await channel.send(embed=embed)
        return True
    except (disnake.Forbidden, disnake.HTTPException) as e:
        logger.error("Не удалось отправить сообщение в канал кадровых действий: %s", e)
        return False


@tasks.loop(minutes=TEAM_SYNC_INTERVAL_MIN or 30)
async def team_sync():
    guild = find_team_guild()
    if guild is None:
        logger.warning("Сервер с кадровыми ролями не найден")
        return

    if not await _load_members(guild):
        return

    rows = collect_import_rows(guild)

    # Пустой список почти наверняка значит недогруженный кэш, а не опустевшую
    # команду. Сверка в этом случае вычистила бы базу целиком.
    if not rows:
        logger.warning("Ни одной должностной роли не найдено, сверка пропущена")
        return

    ok, result = await team_db.sync_members(rows)
    if not ok:
        logger.error("Сверка состава с БД не удалась")
        return

    added, removed = result
    if not added and not removed:
        return

    logger.info("Сверка состава: добавлено %d, убрано %d", added, removed)
    await _report(added, removed)


@team_sync.before_loop
async def before_team_sync():
    await bot.wait_until_ready()
