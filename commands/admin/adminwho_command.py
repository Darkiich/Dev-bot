from bot_init import bot
from dataConfig import ADDRESS_MRP, POST_ADMIN_HEADERS, ROLE_ACCESS_ADMIN
from template_embed import embed_adminwho
from disnake.ext.commands import has_any_role

import aiohttp
from disnake import Embed


def add_chunked_fields(embed, name, value, max_length=1024, inline=False):
    """Разбивает длинное значение на несколько полей."""
    if len(value) <= max_length:
        embed.add_field(name=name, value=value, inline=inline)
        return

    chunks, chunk = [], ""
    lines = value.split("\n")
    for line in lines:
        if len(chunk) + len(line) + 1 > max_length:
            chunks.append(chunk.strip())
            chunk = line
        else:
            chunk += f"\n{line}" if chunk else line
    if chunk:
        chunks.append(chunk.strip())

    for i, chunk in enumerate(chunks):
        field_name = name if i == 0 else f"{name} (часть {i+1})"
        embed.add_field(name=field_name, value=chunk, inline=inline)


'''Команда awho - показывает текущих онлайн-админов сервера MRP'''
@has_any_role(*ROLE_ACCESS_ADMIN)
@bot.command(name="awho")
async def adminwho_command(ctx):
    url = f"http://{ADDRESS_MRP}:1212/admin/info"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=POST_ADMIN_HEADERS) as resp:
                if resp.status != 200:
                    await ctx.send(f"Ошибка: код {resp.status}")
                    return

                data = await resp.json()
                players = data.get("Players", [])

                online_admins = [p for p in players if p.get("IsAdmin") and not p.get("IsDeadminned")]
                deadminned_admins = [p for p in players if p.get("IsAdmin") and p.get("IsDeadminned")]

                embed = Embed(
                    title=embed_adminwho["title"],
                    color=embed_adminwho["color"],
                )

                if online_admins:
                    value = "\n".join(
                        f"**{p.get('Name', '?')}** — {p.get('AdminTitle', 'Админ')} "
                        f"({p.get('PingUser', '?')} ms)"
                        for p in online_admins
                    )
                    add_chunked_fields(embed, "🟢 Онлайн", value, inline=False)
                else:
                    embed.add_field(name="🟢 Онлайн", value="Нет админов на сервере", inline=False)

                if deadminned_admins:
                    value = "\n".join(
                        f"**{p.get('Name', '?')}** — {p.get('AdminTitle', 'Админ')} "
                        f"({p.get('PingUser', '?')} ms)"
                        for p in deadminned_admins
                    )
                    add_chunked_fields(embed, "⚪ Деадмин (не отвечают на тикеты)", value, inline=False)

                total = len(online_admins) + len(deadminned_admins)
                embed.set_footer(text=f"Всего админов на сервере: {total} | Раунд ID: {data.get('RoundId', '?')}")

                await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"Ошибка: {e}")