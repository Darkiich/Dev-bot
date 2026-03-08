from bot_init import bot
from template_embed import embed_sponsor_help
from disnake import Embed

@bot.command(name="sponsor_help")
async def sponsor_help_command(ctx):
    embed = Embed(title=embed_sponsor_help["title"], color=embed_sponsor_help["color"])
    for field in embed_sponsor_help["fields"]:
        embed.add_field(name=field["name"], value=field["value"], inline=field["inline"])
    await ctx.send(embed=embed)