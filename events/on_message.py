import logging

import disnake

from bot_init import bot
from dataConfig import (
    AGHOST_REPORT_CHANNEL_ID,
    EGHOST_REPORT_CHANNEL_ID,
    TEAM_LOG_CHANNEL_ID,
)
from ghost_rules import AGHOST, EGHOST, kind_name
from ghost_service import channel_id_for, departments_of

logger = logging.getLogger(__name__)

DM_WARNING = (
    "В канале {channel} писать текстом нельзя, туда пишет только бот.\n"
    "{advice}\n"
    "Справка - `{help}`."
)

FALLBACK_WARNING = "{mention}, здесь только команды бота. {advice}"

TEAM_ADVICE = (
    "Кадровые действия оформляются командами: `&hire`, `&fire`, `&promote`, "
    "`&demote`, либо кнопками на панели."
)

GHOST_CHANNELS = {
    AGHOST_REPORT_CHANNEL_ID: AGHOST,
    EGHOST_REPORT_CHANNEL_ID: EGHOST,
}

GHOST_COMMANDS = {AGHOST: "&aghost", EGHOST: "&eghost"}

# Сколько живёт заметка в канале, если личку закрыли
WARNING_LIFETIME = 15

# Сколько символов текста вернуть человеку, чтобы он не потерял написанное
ECHO_LIMIT = 1500


def _prefixes() -> tuple:
    prefix = bot.command_prefix
    return (prefix,) if isinstance(prefix, str) else tuple(prefix)


def _is_command(message) -> bool:
    return message.content.startswith(_prefixes())


def _ghost_advice(author, kind: str) -> str:
    """
    Какой командой человеку сдавать отчёт.

    Отдел смотрим по ролям отдела, а не по доступу к командам: сказать
    ивентёру «жми &aghost» только потому, что канал админский, - это
    отправить его делать чужую работу.
    """
    departments = departments_of(author)

    if kind in departments:
        return f"Отчёт открывается командой `{GHOST_COMMANDS[kind]}`."

    if departments:
        mine = departments[0]
        return (
            f"Это канал отчётов {kind_name(kind).lower()}а, а твой отдел сдаёт "
            f"их командой `{GHOST_COMMANDS[mine]}` в <#{channel_id_for(mine)}>."
        )

    return (
        "Гост-отчёты сдают отдел модерации (`&aghost`) и ивентология (`&eghost`). "
        "Ты не состоишь ни в одном из них - если это ошибка, напиши главе отдела."
    )


def _locked(message) -> tuple[str, str] | None:
    """(объяснение, файл справки) для закрытого канала или None, если открыт."""
    channel_id = message.channel.id

    if TEAM_LOG_CHANNEL_ID and channel_id == TEAM_LOG_CHANNEL_ID:
        return TEAM_ADVICE, "&team_help"

    kind = GHOST_CHANNELS.get(channel_id)
    if kind:
        return _ghost_advice(message.author, kind), "&ghost_help"

    return None


async def _notify(message, advice: str, help_command: str) -> bool:
    """Объясняет в личку. True если дошло."""
    text = DM_WARNING.format(
        channel=message.channel.mention, advice=advice, help=help_command
    )

    if message.content:
        text += "\n\nЧто было написано:\n>>> " + message.content[:ECHO_LIMIT]

    try:
        await message.author.send(text)
        return True
    except (disnake.Forbidden, disnake.HTTPException):
        return False


async def _reject(message, advice: str, help_command: str):
    """Удаляет сообщение и объясняет автору, что здесь можно только командами."""
    try:
        await message.delete()
    except disnake.Forbidden:
        logger.warning(
            "Нет права «Управление сообщениями» в канале %s, сообщение осталось.",
            message.channel.id,
        )
        return
    except (disnake.NotFound, disnake.HTTPException) as e:
        logger.warning("Не удалось удалить сообщение %s: %s", message.id, e)
        return

    logger.info(
        "Удалено текстовое сообщение в закрытом канале %s: автор=%s (%s)",
        message.channel.id, message.author, message.author.id,
    )

    if await _notify(message, advice, help_command):
        return

    # Личка закрыта: другого способа достучаться нет, пишем в канал ненадолго
    try:
        await message.channel.send(
            FALLBACK_WARNING.format(mention=message.author.mention, advice=advice),
            delete_after=WARNING_LIFETIME,
        )
    except (disnake.Forbidden, disnake.HTTPException) as e:
        logger.warning("Не удалось предупредить автора %s: %s", message.author.id, e)


@bot.event
async def on_message(message):
    # Через этот обработчик проходят вообще все сообщения бота, поэтому
    try:
        if not message.author.bot and not _is_command(message):
            locked = _locked(message)
            if locked is not None:
                await _reject(message, *locked)
                return
    except Exception:
        logger.exception("Сторож закрытых каналов упал, пропускаю сообщение")

    await bot.process_commands(message)
