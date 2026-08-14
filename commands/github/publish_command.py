import aiohttp

from bot_init import bot
from disnake.ext.commands import has_any_role
from dataConfig import ROLE_ACCESS_MAINTAINER, USER_KEY_GITHUB

'''Команда для отправки паблиша какой-либо ветки'''
@has_any_role(*ROLE_ACCESS_MAINTAINER)
@bot.command(name="publish")
async def publish_command(ctx, branch: str = "master", server: str = "mrp"):
    if not branch:
        await ctx.send("Не указана ветка для паблиша")
        return

    api = "https://api.github.com/repos/AdventureTimeSS14/space_station_ADT/actions/workflows"

    workflows = {
        "dev": "publish-testing.yml",
        "mrp": "publish-public.yml",
    }

    if server not in workflows:
        await ctx.send("Некорректный сервер. Допустимые значения: 'dev' или 'mrp'")
        return

    url = f"{api}/{workflows[server]}/dispatches"

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {USER_KEY_GITHUB}"
    }
    
    data = {
        "ref": branch,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url=url, headers=headers, json=data) as resp:
                if resp.status == 204:
                    await ctx.send(f"Код {resp.status}. Запрос на паблиш отправлен")
                else:
                    body = (await resp.text())[:500]
                    await ctx.send(f"Код {resp.status}. Запрос на паблиш не отправлен\n```{body}```")
    except Exception as e:
        await ctx.send(f"Ошибка при отправке запроса: {e}")
