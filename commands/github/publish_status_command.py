import aiohttp

from bot_init import bot
from disnake.ext.commands import has_any_role
from disnake import Embed
from template_embed import embed_publish_status
from dataConfig import ROLE_ACCESS_MAINTAINER, USER_KEY_GITHUB

@has_any_role(*ROLE_ACCESS_MAINTAINER)
@bot.command(name="publish_status")
async def publish_status_command(ctx):
    url = "https://api.github.com/repos/AdventureTimeSS14/space_station_ADT/actions/workflows/publish-public.yml/runs"

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {USER_KEY_GITHUB}"
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                await ctx.send(f"Ошибка {resp.status}")
                return

            data = await resp.json()
            runs = data.get("workflow_runs", [])

            if not runs:
                await ctx.send("Нет запусков")
                return

            last_run = runs[0]
            run_status = last_run["status"]
            conclusion = last_run.get("conclusion")
            branch = last_run["head_branch"]
            user = last_run["actor"]["login"]

    status_map = {
        "in_progress": ("В процессе", 0xffa500),
    }

    if run_status == "completed":
        if conclusion == "success":
            translated_status, color = ("Завершено", 0x00ff00)
        else:
            translated_status, color = ("Не завершено", 0xff0000)
    else:
        translated_status, color = status_map.get(run_status, ("Неизвестно", 0x808080))

    embed = Embed(title=embed_publish_status["title"], color=color)

    for field in embed_publish_status["fields"]:
        value = eval(field["value"], {"translated_status": translated_status, "branch": branch, "user": user})
        embed.add_field(name=field["name"], value=value, inline=field["inline"])

    await ctx.send(embed=embed)
