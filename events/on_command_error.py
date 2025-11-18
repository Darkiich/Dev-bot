from bot_init import bot
from disnake.ext import commands

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Неизвестная команда")
    elif isinstance(error, (commands.MissingAnyRole, commands.MissingPermissions)):
        await ctx.send("❌ Недостаточно прав для выполнения этой команды")