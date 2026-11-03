"""
&top - рейтинги по часам, раундам и ролям
"""

import logging

import disnake

from bot_init import bot, stats_db
from commands.moderation.mod_common import reply
from commands.player.player_common import fail, player_cooldown
from dataConfig import PLAYER_STATS_SERVER, PLAYER_TOP_LIMIT, PLAYER_TOP_PAGE
from player_jobs import OVERALL, find_tracker, job_name
from player_service import COLOR_MAIN, MENTIONS, fmt_hours

logger = logging.getLogger(__name__)

HOURS_WORDS = ("", "часы", "час", "часов", "hours", "overall", "общее")
ROUNDS_WORDS = ("раунды", "раунд", "раундов", "rounds")
MONTH_WORDS = ("месяц", "month", "за месяц")
MONTH_DAYS = 30

MEDALS = ("🥇", "🥈", "🥉")

PAGES_TIMEOUT = 300
GRANTED_SHOWN = 10


def _place(index: int) -> str:
    return MEDALS[index] if index < len(MEDALS) else f"`{index + 1}.`"


def _lines(rows: list, value_key, formatter, start: int = 0) -> str:
    return "\n".join(
        f"{_place(start + index)} **{row['ckey']}** - {formatter(row[value_key])}"
        for index, row in enumerate(rows)
    ) or "Пока пусто."


def _granted_note(granted: list) -> str:
    if not granted:
        return ""
    names = ", ".join(disnake.utils.escape_markdown(row["ckey"]) for row in granted[:GRANTED_SHOWN])
    if len(granted) > GRANTED_SHOWN:
        names += f" и ещё {len(granted) - GRANTED_SHOWN}"
    return f"Выданное время, вне рейтинга: {names}"


def _pages(title: str, rows: list, value_key, formatter, footer: str, granted: list = ()) -> list:
    """Страницы топа по PLAYER_TOP_PAGE мест."""
    chunks = [rows[i:i + PLAYER_TOP_PAGE] for i in range(0, len(rows), PLAYER_TOP_PAGE)] or [[]]
    note = _granted_note(granted)

    pages = []
    for number, chunk in enumerate(chunks):
        text = _lines(chunk, value_key, formatter, number * PLAYER_TOP_PAGE)
        if note:
            text += f"\n\n{note}"
        embed = disnake.Embed(title=title, description=text, color=COLOR_MAIN)
        embed.set_footer(text=footer)
        pages.append(embed)
    return pages


class TopPages(disnake.ui.View):
    """Листание топа. Листает только тот, кто вызвал."""

    def __init__(self, author_id: int, pages: list):
        super().__init__(timeout=PAGES_TIMEOUT)
        self.author_id = author_id
        self.pages = pages
        self.page = 0
        self.message = None
        self._sync()

    def _sync(self):
        self.back.disabled = self.page == 0
        self.forward.disabled = self.page >= len(self.pages) - 1
        self.counter.label = f"{self.page + 1}/{len(self.pages)}"

    async def interaction_check(self, inter) -> bool:
        if inter.author.id != self.author_id:
            await inter.response.send_message("Это чужой топ. Открой свой: `&top`.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except disnake.HTTPException:
                pass

    async def _show(self, inter, page: int):
        self.page = max(0, min(page, len(self.pages) - 1))
        self._sync()
        await inter.response.edit_message(embed=self.pages[self.page], view=self)

    @disnake.ui.button(emoji="◀️", style=disnake.ButtonStyle.secondary)
    async def back(self, button, inter):
        await self._show(inter, self.page - 1)

    @disnake.ui.button(label="1/1", style=disnake.ButtonStyle.secondary, disabled=True)
    async def counter(self, button, inter):
        pass

    @disnake.ui.button(emoji="▶️", style=disnake.ButtonStyle.secondary)
    async def forward(self, button, inter):
        await self._show(inter, self.page + 1)


async def _send(ctx, pages: list):
    if len(pages) == 1:
        await ctx.send(embed=pages[0], allowed_mentions=MENTIONS)
        return

    view = TopPages(ctx.author.id, pages)
    view.message = await ctx.send(embed=pages[0], view=view, allowed_mentions=MENTIONS)


def _rounds(n) -> str:
    return f"{n} раундов"


@bot.command(name="top", aliases=["топ"])
@player_cooldown
async def top_command(ctx, *, query: str = ""):
    """`&top`, `&top месяц`, `&top капитан`."""
    query = (query or "").strip().lower()

    try:
        if query in HOURS_WORDS:
            top = await stats_db.top_by_trackers([OVERALL], PLAYER_TOP_LIMIT, PLAYER_STATS_SERVER)
            await _send(ctx, _pages(
                "🏆 Топ по времени в игре", top["rows"], "time", fmt_hours,
                "Раунды: &top раунды · своё место: &rank · роль: &top капитан", top["granted"],
            ))
            return

        if query in ROUNDS_WORDS:
            rows = await stats_db.top_by_rounds(None, PLAYER_TOP_LIMIT, PLAYER_STATS_SERVER)
            await _send(ctx, _pages(
                "🏆 Топ по раундам", rows, "rounds", _rounds,
                "Часы: &top часы · за месяц: &top месяц · своё место: &rank",
            ))
            return

        if query in MONTH_WORDS:
            rows = await stats_db.top_by_rounds(MONTH_DAYS, PLAYER_TOP_LIMIT, PLAYER_STATS_SERVER)
            await _send(ctx, _pages(
                f"🏆 Топ по раундам за {MONTH_DAYS} дней", rows, "rounds", _rounds,
                "Своё место смотри в &rank",
            ))
            return

        trackers = await stats_db.trackers(PLAYER_STATS_SERVER)
        matches = find_tracker(query, trackers)

        if not matches:
            await reply(
                ctx,
                f"❌ Роль `{query}` не найдена.\n"
                "Попробуй `&top` (часы), `&top месяц` или название роли: `&top капитан`.",
            )
            return

        # Одна и та же роль лежит в базе под несколькими трекерами, поэтому
        # уточнения просим только когда названия действительно разные
        groups = {}
        for tracker in matches:
            groups.setdefault(job_name(tracker), []).append(tracker)

        if len(groups) > 1:
            names = ", ".join(f"`{name}`" for name in list(groups)[:10])
            await reply(ctx, f"Уточни роль. Подходят: {names}")
            return

        name, group = next(iter(groups.items()))
        top = await stats_db.top_by_trackers(group, PLAYER_TOP_LIMIT, PLAYER_STATS_SERVER)
        await _send(ctx, _pages(
            f"🏆 Топ по роли: {name}", top["rows"], "time", fmt_hours,
            "Своё место смотри в &rank", top["granted"],
        ))

    except Exception as e:
        await fail(ctx, e, "top")
