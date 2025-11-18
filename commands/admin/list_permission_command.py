from bot_init import bot, ss14_db
from dataConfig import ROLE_ACCESS_HEADS
from disnake import Embed
from template_embed import embed_list_permission
from disnake.ext.commands import has_any_role


@bot.command(name="list_permission")
@has_any_role(*ROLE_ACCESS_HEADS)
async def list_permission_command(ctx, dbname: str = 'mrp'):
    list_permissions = await ss14_db.get_list_permission(dbname)

    embed = Embed(title=embed_list_permission["title"], color=embed_list_permission["color"])
    for row in list_permissions:
        embed.add_field(name="", value=f"`{row['name']}`", inline=False)
    await ctx.send(embed=embed)