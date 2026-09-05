import aiohttp
import logging

from bot_init import bot
from dataConfig import USER_KEY_GITHUB, ROLE_ACCESS_HEADS
from disnake.ext.commands import has_any_role

logger = logging.getLogger(__name__)


@has_any_role(*ROLE_ACCESS_HEADS)
@bot.command(name="add_maint")
async def add_maint_command(ctx, github_login: str):
    url = f"https://api.github.com/orgs/AdventureTimeSS14/teams/adt_maintainer/memberships/{github_login}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {USER_KEY_GITHUB}",
    }
    data = {"role": "maintainer"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.put(url, headers=headers, json=data) as resp:
                if resp.status == 200:
                    logger.info("GitHub: %s добавлен в adt_maintainer (выполнил %s)", github_login, ctx.author)
                    await ctx.send(f"Участник {github_login} добавлен в команду adt_maintainer.")
                else:
                    logger.error("add_maint: GitHub API ответил %d для %s", resp.status, github_login)
                    await ctx.send(f"Ошибка {resp.status}: {await resp.text()}")
    except Exception as e:
        logger.exception("Ошибка add_maint для %s: %s", github_login, e)
        await ctx.send(f"Ошибка: {e}")