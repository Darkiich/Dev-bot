"""
Аналитика по кадрам. Один закреплённый пост в канале отчётов, который
перерисовывается раз в TEAM_REPORT_INTERVAL_MIN минут.

Периоды разные не случайно: движение и активность глав смотрим за месяц,
текучку за квартал (за месяц она скачет от пары увольнений), удержание
по когортам от 30 дней и старше, застой от полугода.

Если база не ответила, отчёт остаётся как был. Затирать его цифрами
из ниоткуда хуже, чем показать вчерашние.
"""

from datetime import datetime, timedelta, timezone

import disnake

from disnake.ext import tasks

from bot_init import bot, team_db
from dataConfig import TEAM_REPORT_CHANNEL_ID, TEAM_REPORT_INTERVAL_MIN
from team_departments import DEPARTMENTS, department_name, get_ladder
from team_service import COLOR_INFO

MOVEMENT_DAYS = 30
TURNOVER_DAYS = 90
STAGNATION_DAYS = 180

ACTION_LABELS = {"hire": "найм", "fire": "увольнения", "promote": "повышения", "demote": "понижения"}

COHORT_LABELS = {
    90: "пришли 1-3 месяца назад",
    180: "пришли 3-6 месяцев назад",
    999: "пришли больше полугода назад",
}


def _percent(part: int, whole: int) -> str:
    return f"{round(part * 100 / whole)}%" if whole else "-"


def _top_grade(department: str):
    ladder = get_ladder(department)
    return max((p.grade for p in ladder), default=None)


def _composition(members: list, movement: list) -> disnake.Embed:
    """Численность отделов и чистое изменение за месяц."""
    by_department = {}
    for row in members:
        by_department.setdefault(row["department"], set()).add(row["ds_id"])

    net = {}
    for row in movement:
        delta = 1 if row["action"] == "hire" else -1 if row["action"] == "fire" else 0
        net[row["department"]] = net.get(row["department"], 0) + delta * row["n"]

    people = {row["ds_id"] for row in members}

    embed = disnake.Embed(
        title="Состав команды",
        description=f"Всего **{len(people)}** чел. на **{len(members)}** должностях",
        color=COLOR_INFO,
    )

    for key in DEPARTMENTS:
        count = len(by_department.get(key, ()))
        change = net.get(key, 0)
        mark = f"  ({change:+d})" if change else ""
        embed.add_field(name=department_name(key), value=f"{count} чел.{mark}", inline=True)

    return embed


def _movement(movement: list) -> disnake.Embed:
    """Кто пришёл, ушёл и подвинулся за месяц."""
    by_department = {}
    totals = {}

    for row in movement:
        by_department.setdefault(row["department"], {})[row["action"]] = row["n"]
        totals[row["action"]] = totals.get(row["action"], 0) + row["n"]

    summary = ", ".join(
        f"{ACTION_LABELS[a]} {totals[a]}" for a in ACTION_LABELS if totals.get(a)
    )

    embed = disnake.Embed(
        title=f"Движение за {MOVEMENT_DAYS} дней",
        description=summary or "Действий не было",
        color=COLOR_INFO,
    )

    for key in DEPARTMENTS:
        counts = by_department.get(key)
        if not counts:
            continue
        embed.add_field(
            name=department_name(key),
            value="\n".join(
                f"{ACTION_LABELS[a]}: {counts[a]}" for a in ACTION_LABELS if counts.get(a)
            ),
            inline=True,
        )

    return embed


def _heads(actors: list, turnover: list) -> disnake.Embed:
    """Активность глав и текучка по отделам."""
    embed = disnake.Embed(title="Главы и текучка", color=COLOR_INFO)

    if actors:
        embed.add_field(
            name=f"Кто оформлял, за {MOVEMENT_DAYS} дней",
            value="\n".join(f"<@{r['actor_id']}> - {r['n']}" for r in actors),
            inline=False,
        )
    else:
        embed.add_field(
            name=f"Кто оформлял, за {MOVEMENT_DAYS} дней",
            value="Никто ничего не оформлял",
            inline=False,
        )

    lines = []
    for row in sorted(turnover, key=lambda r: r["fires"], reverse=True):
        if not row["hires"] and not row["fires"]:
            continue
        lines.append(
            f"{department_name(row['department'])}: "
            f"пришло {row['hires']}, ушло {row['fires']}"
        )

    embed.add_field(
        name=f"Текучка за {TURNOVER_DAYS} дней",
        value="\n".join(lines) or "Движения не было",
        inline=False,
    )

    return embed


def _retention(cohorts: list, members: list) -> disnake.Embed:
    """Сколько новичков осело и кто давно сидит на одной ступени."""
    embed = disnake.Embed(title="Удержание и застой", color=COLOR_INFO)

    lines = []
    for row in sorted(cohorts, key=lambda r: r["bucket"]):
        label = COHORT_LABELS.get(row["bucket"], str(row["bucket"]))
        lines.append(
            f"{label}: осталось **{row['alive']}** из {row['total']} "
            f"({_percent(row['alive'], row['total'])})"
        )

    embed.add_field(
        name="Прижились",
        value="\n".join(lines) or "Пока не по чем считать, нужны наймы старше месяца",
        inline=False,
    )

    edge = datetime.now(timezone.utc) - timedelta(days=STAGNATION_DAYS)
    stuck = {}

    for row in members:
        since = row.get("position_since")
        grade = row.get("grade")
        top = _top_grade(row["department"])

        if since is None or grade is None or top is None:
            continue
        if grade >= top or since > edge:
            continue

        stuck.setdefault(row["department"], []).append(row)

    lines = [
        f"{department_name(key)}: {len(rows)} чел."
        for key, rows in sorted(stuck.items(), key=lambda kv: len(kv[1]), reverse=True)
    ]

    embed.add_field(
        name=f"Без повышения дольше {STAGNATION_DAYS} дней",
        value="\n".join(lines) or "Таких нет",
        inline=False,
    )

    embed.set_footer(text="Импортированные считаются в составе, но не в наймах и удержании")
    return embed


def build_report(data: dict) -> list:
    members = data["members"]
    return [
        _composition(members, data["movement"]),
        _movement(data["movement"]),
        _heads(data["actors"], data["turnover"]),
        _retention(data["cohorts"], members),
    ]


async def _find_report_message(channel):
    """Свой закреплённый отчёт в канале или None."""
    try:
        async for message in channel.pins():
            if message.author.id == bot.user.id:
                return message
    except (disnake.Forbidden, disnake.HTTPException) as e:
        print(f"[team_report] Не удалось прочитать закреплённые: {e}")
    return None


@tasks.loop(minutes=TEAM_REPORT_INTERVAL_MIN or 120)
async def team_report():
    if not TEAM_REPORT_CHANNEL_ID:
        return

    channel = bot.get_channel(TEAM_REPORT_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(TEAM_REPORT_CHANNEL_ID)
        except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException) as e:
            print(f"[team_report] Канал {TEAM_REPORT_CHANNEL_ID} недоступен: {e}")
            return

    data = await team_db.get_report_data(MOVEMENT_DAYS, TURNOVER_DAYS)
    if data is None:
        print("[team_report] База не ответила, отчёт оставлен как был")
        return

    embeds = build_report(data)
    message = await _find_report_message(channel)

    try:
        if message:
            await message.edit(embeds=embeds)
        else:
            message = await channel.send(embeds=embeds)
            await message.pin()
            print("[team_report] Отчёт создан и закреплён")
    except (disnake.Forbidden, disnake.HTTPException) as e:
        print(f"[team_report] Не удалось обновить отчёт: {e}")


@team_report.before_loop
async def before_team_report():
    await bot.wait_until_ready()
