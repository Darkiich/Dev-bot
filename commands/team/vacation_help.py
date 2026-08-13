"""Справка по командам системы отпусков."""

from disnake import Embed

from bot_init import bot
from template_embed import embed_vacation_help


@bot.command(name="vacation_help", aliases=["vac_help"])
async def vacation_help_command(ctx):
    """Выводит список команд для работы с отпусками."""
    embed = Embed(
        title=embed_vacation_help["title"],
        color=embed_vacation_help["color"],
        description=embed_vacation_help["description"],
    )
    for field in embed_vacation_help["fields"]:
        embed.add_field(name=field["name"], value=field["value"], inline=field["inline"])

    if bot.user and bot.user.avatar:
        embed.set_thumbnail(url=bot.user.avatar.url)

    await ctx.send(embed=embed)
