"""
Аналитика гост-смен по запросу.

    &ghost_stats - свой отдел, определяется по ролям
    &ghost_stats агост - аналитика модерации
    &ghost_stats игост - аналитика ивентологии
    &ghost_report - перерисовать закреплённый отчёт руками
    &ghost [@участник] - короткая сводка по человеку
"""

import logging

import disnake

from disnake.ext.commands import has_any_role

from bot_init import bot, ghost_db
from commands.moderation.mod_common import error_text, reply
from dataConfig import (
    GHOST_MAX_SHIFT_HOURS,
    ROLE_ACCESS_GHOST_ADMIN,
    ROLE_ACCESS_GHOST_EVENT,
    ROLE_ACCESS_GHOST_REVIEW,
)
from ghost_rules import AGHOST, EGHOST, kind_name
from ghost_service import build_user_embed, can_review, departments_of
from tasks.ghost_report import build_report, collect, refresh_report

logger = logging.getLogger(__name__)

# Как отдел называют в команде
ALIASES = {
    "агост": AGHOST, "aghost": AGHOST, "a": AGHOST, "а": AGHOST,
    "модерация": AGHOST, "админы": AGHOST, "mod": AGHOST,
    "игост": EGHOST, "eghost": EGHOST, "e": EGHOST, "и": EGHOST,
    "ивенты": EGHOST, "ивентология": EGHOST, "event": EGHOST,
}

GHOST_ANY = sorted(set(ROLE_ACCESS_GHOST_ADMIN) | set(ROLE_ACCESS_GHOST_EVENT)
                   | set(ROLE_ACCESS_GHOST_REVIEW))


def resolve_kind(token: str, user) -> tuple[str | None, str | None]:
    """
    Какой отдел смотрим. Без аргумента - тот, в котором человек состоит.

    Отдел определяется по ролям отдела, а не по доступу к командам: доступ
    есть и у руководства, и у наблюдателей, а статистику надо показать
    чью-то конкретную.
    """
    token = (token or "").strip().lower()

    if token:
        kind = ALIASES.get(token)
        if kind is None:
            return None, f"Не понял отдел «{token[:30]}». Пиши `агост` или `игост`."

        # Чужой отдел смотрят те, кто и так проверяет по нему отчёты
        if kind not in departments_of(user) and not can_review(user):
            return None, (
                f"{kind_name(kind)} ведёт другой отдел. "
                f"Свою статистику смотри так: `&ghost_stats`."
            )

        return kind, None

    found = departments_of(user)
    if found:
        return found[0], None

    # Наблюдатель или глава без роли отдела: показываем модерацию, но
    # пусть знает, что вторая половина открывается словом
    if can_review(user):
        return AGHOST, None

    return None, "Ты не в отделе модерации и не в ивентологии. Уточни: `агост` или `игост`."


@bot.command(name="ghost_stats", aliases=["гост_стат", "гостстат", "ghoststats"])
@has_any_role(*GHOST_ANY)
async def ghost_stats_command(ctx, department: str = ""):
    """Пять метрик по отделу: часы, проверка, длительность, молчуны, ивенты."""
    kind, problem = resolve_kind(department, ctx.author)
    if problem:
        await reply(ctx, f"❌ {problem}")
        return

    async with ctx.typing():
        data = await collect(kind, ctx.guild)

    if data is None:
        await reply(ctx, "⚠️ База не ответила, цифры показать не могу.")
        return

    other = [d for d in departments_of(ctx.author) if d != kind]
    hint = f"Ты и в другом отделе: `&ghost_stats {other[0]}`" if other and not department else None

    await ctx.send(content=hint, embeds=build_report(kind, data, ctx.guild),
                   allowed_mentions=disnake.AllowedMentions.none())


@ghost_stats_command.error
async def ghost_stats_command_error(ctx, error):
    text = error_text(error, "**Использование:** `&ghost_stats [агост/игост]`")
    if text:
        await reply(ctx, text)


@bot.command(name="ghost_report", aliases=["гост_отчёт", "гост_отчет"])
@has_any_role(*ROLE_ACCESS_GHOST_REVIEW)
async def ghost_report_command(ctx, department: str = ""):
    """Перерисовывает закреплённый отчёт, не дожидаясь расписания."""
    kind = ALIASES.get((department or "").strip().lower()) if department else None

    async with ctx.typing():
        text = await refresh_report(kind)

    await reply(ctx, text)


@ghost_report_command.error
async def ghost_report_command_error(ctx, error):
    text = error_text(error, "**Использование:** `&ghost_report [агост/игост]`")
    if text:
        await reply(ctx, text)


@bot.command(name="ghost", aliases=["гост"])
@has_any_role(*GHOST_ANY)
async def ghost_command(ctx, member: disnake.Member = None, days: int = 30):
    """Сводка по человеку: смены, часы, как проходит проверка."""
    member = member or ctx.author
    days = max(1, min(days, 365))

    if member.id != ctx.author.id and not can_review(ctx.author):
        await reply(ctx, "❌ Чужие смены смотрят наблюдатели и выше.")
        return

    kind, _ = resolve_kind("", member)

    summary = await ghost_db.user_summary(
        member.id, kind, days, max_hours=GHOST_MAX_SHIFT_HOURS
    )

    await reply(ctx, "", build_user_embed(member, kind, summary, days))


@ghost_command.error
async def ghost_command_error(ctx, error):
    text = error_text(error, "**Использование:** `&ghost [@участник] [дней]`")
    if text:
        await reply(ctx, text)
