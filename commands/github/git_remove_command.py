import aiohttp
import logging

from bot_init import bot
from dataConfig import USER_KEY_GITHUB, ROLE_ACCESS_HEADS
from disnake import Embed
from disnake.ext.commands import has_any_role
from template_embed import embed_git_remove

logger = logging.getLogger(__name__)

@has_any_role(*ROLE_ACCESS_HEADS)
@bot.command(name="git_remove")
async def git_remove_command(ctx, username: str):
    url = f"https://api.github.com/orgs/AdventureTimeSS14/memberships/{username}"
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {USER_KEY_GITHUB}"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers) as resp:
                if resp.status == 204:
                    logger.info("GitHub: %s удалён из организации (инициатор %s)", username, ctx.author)
                    result = "Пользователь успешно удалён"
                    embed_color = 0x00ff00
                else:
                    logger.error("git_remove: GitHub API ответил %d для %s", resp.status, username)
                    result = f"Не удалось удалить пользователя: {await resp.text()}"
                    embed_color = 0xff0000

        embed = Embed(title=embed_git_remove["title"], color=embed_color)
        for field in embed_git_remove["fields"]:
            embed.add_field(name=field["name"], value=eval(field["value"], {"result": result, "username": username}), inline=field["inline"])
        
        await ctx.send(embed=embed)
    except Exception as e:
        logger.exception("Ошибка git_remove для %s: %s", username, e)
        embed = Embed(title=embed_git_remove["title"], color=0xff0000)
        embed.add_field(name="Пользователь", value=username, inline=False)
        embed.add_field(name="Статус", value=f"Не удалось удалить пользователя: {e}", inline=False)
        await ctx.send(embed=embed)