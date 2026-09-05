"""Справка по кадровым командам и карта отделов."""

import disnake

from disnake.ext.commands import has_any_role

from bot_init import bot
from dataConfig import GENERAL_ACCESS
from team_departments import DEPARTMENTS, get_positions
from team_service import COLOR_INFO, MENTIONS

COMMANDS = (
    "`&hire <@участник> <@должность> [причина]` - принять в отдел\n"
    "`&fire <@участник> <@должность> [причина]` - снять с должности\n"
    "`&promote <@участник> <@должность> [причина]` - повысить\n"
    "`&demote <@участник> <@должность> [причина]` - понизить\n"
    "`&team` - численность по отделам\n"
    "`&team <@отдел>` - состав отдела\n"
    "`&team <@участник>` - должности участника"
)

NOTES = (
    "Должность указывается ролью: упоминанием, ID или названием в кавычках.\n"
    "При найме выдаётся должность, роль отдела и общая роль команды проекта.\n"
    "При увольнении роль отдела снимается, только если в отделе больше "
    "ничего не осталось.\n"
    "`&promote` и `&demote` работают по ступеням лестницы. Отдельные роли "
    "ступеней не имеют, их выдают через `&hire`."
)


def _departments_embed() -> disnake.Embed:
    embed = disnake.Embed(
        title="Отделы и должности",
        description="Ступени идут сверху вниз, от высшей к низшей.",
        color=COLOR_INFO,
    )

    for key, dept in DEPARTMENTS.items():
        positions = sorted(
            get_positions(key),
            key=lambda p: (p.grade is None, -(p.grade or 0)),
        )

        lines = []
        for position in positions:
            prefix = f"{position.grade}." if position.on_ladder else "•"
            lines.append(f"{prefix} <@&{position.role_id}>")

        embed.add_field(
            name=f"{dept['name']}  <@&{dept['role_id']}>",
            value="\n".join(lines),
            inline=False,
        )

    return embed


@bot.command(name="team_help", aliases=["hire_help"])
@has_any_role(*GENERAL_ACCESS)
async def team_help(ctx):
    """Показывает команды кадровой системы и карту отделов."""
    main = disnake.Embed(title="Кадровая система", description=COMMANDS, color=COLOR_INFO)
    main.add_field(name="Как это работает", value=NOTES, inline=False)

    await ctx.send(embeds=[main, _departments_embed()], allowed_mentions=MENTIONS)
