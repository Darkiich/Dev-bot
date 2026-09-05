import aiohttp
import logging

from bot_init import bot
from dataConfig import USER_KEY_GITHUB, ROLE_ACCESS_HEADS
from disnake import Embed
from disnake.ext.commands import has_any_role
from template_embed import embed_git_invite

logger = logging.getLogger(__name__)

@has_any_role(*ROLE_ACCESS_HEADS)
@bot.command(name="git_invite")
async def git_invite_command(ctx, username: str):
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {USER_KEY_GITHUB}"}
    user_url = f"https://api.github.com/users/{username}"
    
    try:
        async with aiohttp.ClientSession() as session:
            # Получаем ID пользователя
            async with session.get(user_url, headers=headers) as user_resp:
                if user_resp.status != 200:
                    logger.warning("git_invite: пользователь GitHub %s не найден", username)
                    result = f"Не удалось отправить приглашение: Пользователь {username} не найден"
                    embed_color = 0xff0000
                else:
                    user_data = await user_resp.json()
                    user_id = user_data["id"]
                    invite_url = "https://api.github.com/orgs/AdventureTimeSS14/invitations"
                    data = {"invitee_id": user_id, "role": "direct_member"}
                    
                    # Отправляем приглашение
                    async with session.post(invite_url, headers=headers, json=data) as invite_resp:
                        if invite_resp.status == 201:
                            logger.info("GitHub: приглашение отправлено %s (инициатор %s)", username, ctx.author)
                            result = "Приглашение успешно отправлено"
                            embed_color = 0x00ff00
                        else:
                            logger.error("git_invite: GitHub API ответил %d для %s", invite_resp.status, username)
                            result = f"Не удалось отправить приглашение: {await invite_resp.text()}"
                            embed_color = 0xff0000

        embed = Embed(title=embed_git_invite["title"], color=embed_color)
        for field in embed_git_invite["fields"]:
            embed.add_field(name=field["name"], value=eval(field["value"], {"result": result, "username": username}), inline=field["inline"])
        
        await ctx.send(embed=embed)
    except Exception as e:
        logger.exception("Ошибка git_invite для %s: %s", username, e)
        embed = Embed(title=embed_git_invite["title"], color=0xff0000)
        embed.add_field(name="Пользователь", value=username, inline=False)
        embed.add_field(name="Статус", value=f"Не удалось отправить приглашение: {e}", inline=False)
        await ctx.send(embed=embed)