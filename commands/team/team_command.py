"""
Просмотр состава.

    &team                  - численность по всем отделам
    &team @Разработка      - состав отдела по ступеням
    &team @user            - должности участника

Считается по ролям в Discord, а не по базе, поэтому показывает то,
что есть на сервере прямо сейчас.
"""

from typing import Union

import disnake

from disnake.ext.commands import has_any_role

from bot_init import bot
from dataConfig import GENERAL_ACCESS
from team_departments import DEPARTMENTS, department_name
from team_service import (
    COLOR_INFO,
    MENTIONS,
    command_error_text,
    department_headcount,
    department_roster,
    member_positions,
    resolve_department,
    resolve_position,
)

USAGE = (
    "**Использование:** `&team [@отдел или @участник]`\n"
    "Без аргумента - численность по всем отделам."
)

FIELD_LIMIT = 1024


def _join(members: list) -> str:
    """Список упоминаний, обрезанный под лимит поля эмбеда."""
    if not members:
        return "пусто"

    shown = []
    length = 0

    for member in members:
        piece = member.mention
        if length + len(piece) + 2 > FIELD_LIMIT - 20:
            shown.append(f"и ещё {len(members) - len(shown)}")
            break
        shown.append(piece)
        length += len(piece) + 2

    return ", ".join(shown)


def _summary(guild) -> disnake.Embed:
    embed = disnake.Embed(title="👥 Команда проекта", color=COLOR_INFO)
    everyone = set()

    for key in DEPARTMENTS:
        people = department_headcount(guild, key)
        everyone |= people
        embed.add_field(name=department_name(key), value=f"{len(people)} чел.", inline=True)

    embed.description = f"Всего в отделах: **{len(everyone)}** чел."
    return embed


def _roster(guild, department: str) -> disnake.Embed:
    embed = disnake.Embed(title=f"👥 {department_name(department)}", color=COLOR_INFO)
    total = 0

    for position, members in department_roster(guild, department):
        total += len(members)
        embed.add_field(
            name=f"{position.name} ({len(members)})",
            value=_join(members),
            inline=False,
        )

    embed.description = f"Всего: **{len(department_headcount(guild, department))}** чел."
    return embed


def _member_card(member: disnake.Member) -> disnake.Embed:
    positions = member_positions(member)

    embed = disnake.Embed(
        title=f"👤 {member.display_name}",
        color=COLOR_INFO,
        description=member.mention if positions else f"{member.mention} не занимает должностей.",
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    grouped = {}
    for position in positions:
        grouped.setdefault(position.department_name, []).append(position)

    for name, items in grouped.items():
        items.sort(key=lambda p: (p.grade is None, -(p.grade or 0)))
        embed.add_field(
            name=name,
            value="\n".join(f"• {p.name}" for p in items),
            inline=False,
        )

    return embed


@bot.command(name="team", aliases=["sostav"])
@has_any_role(*GENERAL_ACCESS)
async def team_command(ctx, target: Union[disnake.Member, disnake.Role] = None):
    """Показывает численность отделов, состав одного отдела или должности участника."""
    if target is None:
        await ctx.send(embed=_summary(ctx.guild), allowed_mentions=MENTIONS)
        return

    if isinstance(target, disnake.Member):
        await ctx.send(embed=_member_card(target), allowed_mentions=MENTIONS)
        return

    department = resolve_department(target)
    if department is None:
        position = resolve_position(target)
        if position is None:
            await ctx.send(
                f"❌ Роль {target.mention} не относится к отделам.\n\n{USAGE}",
                allowed_mentions=MENTIONS,
            )
            return
        department = position.department

    await ctx.send(embed=_roster(ctx.guild, department), allowed_mentions=MENTIONS)


@team_command.error
async def team_command_error(ctx, error):
    text = command_error_text(error, USAGE)
    if text:
        await ctx.send(text, allowed_mentions=MENTIONS)
