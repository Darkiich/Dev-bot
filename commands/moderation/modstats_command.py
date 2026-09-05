"""
Статистика модерации.

    &modstats - за 30 дней
    &modstats 7 - за неделю

Показывает, кто сколько выдал, чего было больше и кто чаще всех попадал под раздачу
"""

import disnake

from disnake.ext.commands import has_any_role

from bot_init import bot, mod_db
from commands.moderation.mod_common import error_text, reply
from dataConfig import ROLE_ACCESS_MODERATOR
from mod_rules import COLOR_INFO, action_title
from vacation_time import plural


@bot.command(name="modstats", aliases=["модстат"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def modstats_command(ctx, days: int = 30):
    """Кто сколько намодерировал за период."""
    days = max(1, min(days, 365))

    actors = await mod_db.actor_stats(days, ctx.guild.id)
    totals = await mod_db.period_totals(days, ctx.guild.id)
    targets = await mod_db.top_targets(days, 5, ctx.guild.id)

    embed = disnake.Embed(
        title=f"📊 Модерация за {days} {plural(days, ('день', 'дня', 'дней'))}",
        color=COLOR_INFO,
        timestamp=disnake.utils.utcnow(),
    )

    summary = " · ".join(
        f"{action_title(action)}: **{count}**"
        for action, count in sorted(totals.items(), key=lambda p: -p[1])
        if action in ("warn", "mute", "kick", "ban", "softban", "note")
    )
    embed.description = summary or "За период ничего не происходило."

    if actors:
        lines = []
        for place, row in enumerate(actors[:10], start=1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(place, f"`{place}.`")
            lines.append(
                f"{medal} <@{row['actor_id']}> - **{row['total']}**\n"
                f"⚠️ {row['warns']} · 🔇 {row['mutes']} · 👢 {row['kicks']} · 🔨 {row['bans']}"
            )
        embed.add_field(name="Модераторы", value="\n".join(lines), inline=False)

    if targets:
        embed.add_field(
            name="Чаще всех получали",
            value="\n".join(
                f"<@{row['target_id']}> - {row['total']}" for row in targets
            ),
            inline=False,
        )

    embed.set_footer(text="Период меняется числом: &modstats 7")
    await reply(ctx, "", embed)


@modstats_command.error
async def modstats_command_error(ctx, error):
    text = error_text(error, "**Использование:** `&modstats [дней]`")
    if text:
        await reply(ctx, text)
