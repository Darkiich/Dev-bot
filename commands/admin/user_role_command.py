import disnake
from bot_init import bot
from dataConfig import VACATION_ROLE_ID, GENERAL_ACCESS
from disnake.ext.commands import has_any_role

@bot.command(name='user_role')
async def user_role_command(ctx, *, input: str):
    role = None
    if input.startswith('<@&') and input.endswith('>'):
        role_id = int(input[3:-1])
        role = ctx.guild.get_role(role_id)
    else:
        role = disnake.utils.get(ctx.guild.roles, name=input.strip())
    if not role:
        await ctx.send("Роль не найдена.")
        return
    members = [m for m in role.members if not m.bot]
    lines = []
    for m in members:
        suffix = " (в отпуске)" if VACATION_ROLE_ID in [r.id for r in m.roles] else ""
        lines.append(f"{m.display_name}{suffix}")
    text = "\n".join(lines) if lines else "Нет пользователей."
    embed = disnake.Embed(title=f"Пользователи с ролью {role.name}", description=text)
    await ctx.send(embed=embed)

@has_any_role(*GENERAL_ACCESS)
@bot.command(name='user_role_mention')
async def user_role_mention_command(ctx, *, input: str):
    role = None
    if input.startswith('<@&') and input.endswith('>'):
        role_id = int(input[3:-1])
        role = ctx.guild.get_role(role_id)
    else:
        role = disnake.utils.get(ctx.guild.roles, name=input.strip())
    if not role:
        await ctx.send("Роль не найдена.")
        return
    members = [m for m in role.members if not m.bot]
    lines = []
    for m in members:
        suffix = " (в отпуске)" if VACATION_ROLE_ID in [r.id for r in m.roles] else ""
        lines.append(f"{m.mention}{suffix}")
    text = "\n".join(lines) if lines else "Нет пользователей."
    await ctx.send(text)