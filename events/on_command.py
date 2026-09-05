import logging
from datetime import datetime

from bot_init import bot
from template_embed import embed_log
from disnake import Embed
from dataConfig import LOG_CHANNEL_ID

logger = logging.getLogger(__name__)


@bot.event
async def on_command(ctx):
    guild = f"{ctx.guild.name} ({ctx.guild.id})" if ctx.guild else "ЛС"
    channel = getattr(ctx.channel, "name", "ЛС")
    logger.info(
        "Команда '%s' | автор=%s (%s) | сервер=%s | канал=%s | сообщение: %s",
        ctx.command.qualified_name if ctx.command else "?",
        ctx.author, ctx.author.id, guild, channel, ctx.message.content,
    )

    embed = Embed(title=embed_log["title"], color=embed_log["color"])
    for field in embed_log["fields"]:
        embed.add_field(name=field["name"], value=eval(field["value"]), inline=field["inline"])
        
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(embed=embed)