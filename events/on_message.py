"""
В канале кадровых действий разрешены только команды бота.
Обычное сообщение удаляется, автору объясняется почему.

Объяснение уходит в личку, а не в канал. Скрытое сообщение Discord умеет
только в ответ на взаимодействие, а тут его нет: человек просто печатал
текст. Если личка закрыта, остаётся короткая заметка в канале, которая
сама исчезнет.

Этот обработчик перекрывает штатный on_message, поэтому обязан сам звать
process_commands. Без этого перестанут работать вообще все команды бота.
"""

import disnake

from bot_init import bot
from dataConfig import TEAM_LOG_CHANNEL_ID

DM_WARNING = (
    "В канале {channel} писать текстом нельзя, туда пишет только бот.\n"
    "Кадровые действия оформляются командами: `&hire`, `&fire`, `&promote`, `&demote`, "
    "либо кнопками на панели.\n"
    "Справка - `&team_help`."
)

FALLBACK_WARNING = (
    "{mention}, здесь только команды бота, справка - `&team_help`. "
    "Подробности в личку не ушли, она закрыта."
)

# Сколько живёт заметка в канале, если личку закрыли
WARNING_LIFETIME = 15

# Сколько символов текста вернуть человеку, чтобы он не потерял написанное
ECHO_LIMIT = 1500


def _prefixes() -> tuple:
    prefix = bot.command_prefix
    return (prefix,) if isinstance(prefix, str) else tuple(prefix)


def _is_command(message) -> bool:
    return message.content.startswith(_prefixes())


def _is_locked_channel(message) -> bool:
    return bool(TEAM_LOG_CHANNEL_ID) and message.channel.id == TEAM_LOG_CHANNEL_ID


async def _notify(message) -> bool:
    """Объясняет в личку. True если дошло."""
    text = DM_WARNING.format(channel=message.channel.mention)

    if message.content:
        text += "\n\nЧто было написано:\n>>> " + message.content[:ECHO_LIMIT]

    try:
        await message.author.send(text)
        return True
    except (disnake.Forbidden, disnake.HTTPException):
        return False


async def _reject(message):
    """Удаляет сообщение и объясняет автору, что здесь можно только командами."""
    try:
        await message.delete()
    except disnake.Forbidden:
        print("[team] Нет права «Управление сообщениями» в канале кадровых действий.")
        return
    except (disnake.NotFound, disnake.HTTPException) as e:
        print(f"[team] Не удалось удалить сообщение: {e}")
        return

    if await _notify(message):
        return

    # Личка закрыта: другого способа достучаться нет, пишем в канал ненадолго
    try:
        await message.channel.send(
            FALLBACK_WARNING.format(mention=message.author.mention),
            delete_after=WARNING_LIFETIME,
        )
    except (disnake.Forbidden, disnake.HTTPException) as e:
        print(f"[team] Не удалось предупредить автора: {e}")


@bot.event
async def on_message(message):
    if not message.author.bot and _is_locked_channel(message) and not _is_command(message):
        await _reject(message)
        return

    await bot.process_commands(message)
