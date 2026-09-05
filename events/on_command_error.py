import logging

from bot_init import bot
from disnake.ext import commands

logger = logging.getLogger(__name__)


def _ctx_info(ctx) -> str:
    guild = f"{ctx.guild.name} ({ctx.guild.id})" if ctx.guild else "ЛС"
    channel = getattr(ctx.channel, "name", "ЛС")
    return (
        f"сообщение='{ctx.message.content}' автор={ctx.author} ({ctx.author.id}) "
        f"сервер={guild} канал={channel}"
    )


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        logger.info("Неизвестная команда: %s", _ctx_info(ctx))
        await ctx.send("❌ Неизвестная команда")
    elif isinstance(error, (commands.MissingAnyRole, commands.MissingPermissions)):
        logger.warning("Отказано в доступе (%s): %s", error, _ctx_info(ctx))
        await ctx.send("❌ Недостаточно прав для выполнения этой команды")
    elif isinstance(error, commands.CommandOnCooldown):
        logger.info("Команда на кулдауне (%s): %s", error, _ctx_info(ctx))
    elif isinstance(error, (commands.UserInputError, commands.BadArgument, commands.MissingRequiredArgument)):
        logger.info("Некорректные аргументы команды (%s): %s", error, _ctx_info(ctx))
    else:
        original = getattr(error, "original", error)
        logger.error("Необработанная ошибка команды | %s", _ctx_info(ctx), exc_info=original)