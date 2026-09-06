"""
Открытие смены: &aghost у модерации и &eghost у ивентологии
"""

import logging

import disnake

from disnake.ext.commands import has_any_role

from bot_init import bot
from commands.moderation.mod_common import error_text, reply
from dataConfig import (
    MOD_SLASH_GUILD_IDS,
    ROLE_ACCESS_GHOST_ADMIN,
    ROLE_ACCESS_GHOST_EVENT,
)
from ghost_rules import (
    AGHOST,
    EGHOST,
    clock,
    kind_color,
    kind_name,
    kind_title,
    parse_number,
    parse_start,
    split_preset,
)
from ghost_service import MENTIONS, can_open, fetch_status, open_shift, status_complete
from vacation_time import now_local

logger = logging.getLogger(__name__)

PANEL_TIMEOUT = 300

GUILDS = MOD_SLASH_GUILD_IDS or None

EVENT_PLACEHOLDER = "Ссылка на ивент или описание. Пусто - ивента на раунд нет"


def _time_input(kind: str) -> disnake.ui.TextInput:
    return disnake.ui.TextInput(
        label=f"Время начала {kind_name(kind).lower()}а"[:45],
        custom_id="started",
        style=disnake.TextInputStyle.short,
        required=True,
        max_length=10,
        value="сейчас",
        placeholder="21:16 или «сейчас»",
    )


def _event_input() -> disnake.ui.TextInput:
    return disnake.ui.TextInput(
        label="Ивент на раунд",
        custom_id="event",
        style=disnake.TextInputStyle.paragraph,
        required=False,
        max_length=900,
        placeholder=EVENT_PLACEHOLDER,
    )


class OpenModal(disnake.ui.Modal):
    """Форма отчёта: только те поля, на которые у бота нет ответа."""

    def __init__(self, panel):
        self.panel = panel
        status = panel.status

        # Хватает только полного ответа: в лобби пресета ещё нет, и отчёт
        # с пустым режимом никому не нужен
        self.manual = not status_complete(status)

        components = []

        if self.manual:
            components += [
                disnake.ui.TextInput(
                    label="Раунд",
                    custom_id="round",
                    style=disnake.TextInputStyle.short,
                    required=True,
                    max_length=10,
                    value=str(status.get("round_id") or ""),
                    placeholder="17797",
                ),
                disnake.ui.TextInput(
                    label="Игроков",
                    custom_id="players",
                    style=disnake.TextInputStyle.short,
                    required=True,
                    max_length=6,
                    value=str(status.get("players") if status.get("players") is not None else ""),
                    placeholder="82",
                ),
                disnake.ui.TextInput(
                    label="Режим раунда",
                    custom_id="preset",
                    style=disnake.TextInputStyle.short,
                    required=True,
                    max_length=150,
                    value=status.get("preset") or "",
                    placeholder="Секрет (тройня)",
                ),
                _time_input(panel.kind),
            ]
        else:
            components.append(_time_input(panel.kind))

        if panel.kind == EGHOST:
            components.append(_event_input())

        super().__init__(
            title=f"Открыть {kind_name(panel.kind).lower()}"[:45],
            custom_id=f"ghost_open:{panel.kind}:{panel.author_id}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)

        values = inter.text_values
        status = self.panel.status
        problems = []

        started_at, problem = parse_start(values.get("started"))
        if problem:
            problems.append(problem)

        if self.manual:
            round_id, problem = parse_number(values.get("round"), "Раунд", limit=10_000_000)
            if problem:
                problems.append(problem)

            players, problem = parse_number(values.get("players"), "Игроков", limit=1000)
            if problem:
                problems.append(problem)

            # Руками режим пишут одной строкой, «Секрет (тройня)». Разводим
            # его по тем же двум колонкам, что и подставленный с сервера
            preset, note = split_preset(values.get("preset"))
            note = note or None

            if not preset:
                problems.append("Режим раунда пустой. Впиши, чем шёл раунд.")
        else:
            round_id = status.get("round_id")
            players = status.get("players")
            preset = status.get("preset")
            note = None

        if problems:
            await inter.followup.send(
                "❌ " + "\n❌ ".join(problems), ephemeral=True, allowed_mentions=MENTIONS
            )
            return

        member = inter.guild.get_member(inter.author.id) if inter.guild else None
        if member is None:
            await inter.followup.send(
                "❌ Смены открываются только на сервере проекта.", ephemeral=True
            )
            return

        # Кнопка роль уже проверяла, но форма живёт минутами: за это время
        # человека могли снять с должности
        if not can_open(member, self.panel.kind):
            await inter.followup.send(
                f"❌ {kind_name(self.panel.kind)} сдаёт свой отдел.", ephemeral=True
            )
            return

        row, text = await open_shift(
            member=member,
            kind=self.panel.kind,
            round_id=round_id,
            players=players,
            preset=preset,
            preset_note=note,
            started_at=started_at,
            event_text=(values.get("event") or "").strip() or None,
        )

        await inter.followup.send(text, ephemeral=True, allowed_mentions=MENTIONS)

        if row is not None:
            await self.panel.cleanup(
                f"{kind_title(self.panel.kind)} открыт, отчёт #{row['id']}."
            )


class OpenPanel(disnake.ui.View):
    """Что бот вытянул с сервера и кнопка, открывающая форму."""

    def __init__(self, kind: str, author_id: int, status: dict):
        super().__init__(timeout=PANEL_TIMEOUT)

        self.kind = kind
        self.author_id = author_id
        self.status = dict(status or {})

        self.message = None # панель, вызванная префикс-командой
        self.inter = None # панель, вызванная слэш-командой

        self.open_button.label = f"Открыть {kind_name(kind).lower()}"[:80]

    async def interaction_check(self, inter) -> bool:
        if inter.author.id != self.author_id:
            await inter.response.send_message(
                f"Это чужая панель. Открой свою: `&{self.kind}`.", ephemeral=True
            )
            return False
        return True

    def build_embed(self) -> disnake.Embed:
        embed = disnake.Embed(
            title=f"{kind_title(self.kind)} · открытие смены",
            color=kind_color(self.kind),
        )

        if status_complete(self.status):
            players = self.status.get("players")
            embed.description = (
                f"Раунд **{self.status['round_id']}** · "
                f"игроков **{players}** · "
                f"режим **{self.status['preset']}**"
            )
        elif self.status:
            embed.description = "Сервер ответил не полностью, остальное впишешь в форме."
        else:
            embed.description = "Сервер не ответил, всё впишешь в форме."

        embed.set_footer(text=f"Сейчас {clock(now_local())}")

        return embed

    async def cleanup(self, text: str = "Готово."):
        self.stop()

        try:
            if self.inter is not None:
                await self.inter.edit_original_response(content=text, embed=None, view=None)
            elif self.message is not None:
                await self.message.edit(content=text, embed=None, view=None)
        except disnake.HTTPException:
            pass

    async def on_timeout(self):
        await self.cleanup("Панель закрылась, смена не открыта.")

    @disnake.ui.button(label="Открыть", emoji="▶️", style=disnake.ButtonStyle.success)
    async def open_button(self, button, inter):
        if not can_open(inter.author, self.kind):
            await inter.response.send_message(
                f"❌ {kind_name(self.kind)} сдаёт свой отдел.", ephemeral=True
            )
            return

        await inter.response.send_modal(OpenModal(self))


#  Точка входа, одна на префикс- и слэш-команды
async def send_panel(kind: str, author, ctx=None, inter=None):
    """Тянет статус сервера и выкладывает панель."""
    if not can_open(author, kind):
        text = f"❌ {kind_name(kind)} сдаёт свой отдел, тебе он не положен."
        if inter is not None:
            await inter.edit_original_response(content=text)
        else:
            await reply(ctx, text)
        return

    status = await fetch_status()
    panel = OpenPanel(kind, author.id, status)
    embed = panel.build_embed()

    if inter is not None:
        panel.inter = inter
        await inter.edit_original_response(embed=embed, view=panel)
        return

    panel.message = await ctx.send(embed=embed, view=panel, allowed_mentions=MENTIONS)


@bot.command(name="aghost", aliases=["агост", "ahost"])
@has_any_role(*ROLE_ACCESS_GHOST_ADMIN)
async def aghost_command(ctx):
    """Панель открытия агоста."""
    await send_panel(AGHOST, ctx.author, ctx=ctx)


@aghost_command.error
async def aghost_command_error(ctx, error):
    text = error_text(error, "**Использование:** `&aghost`")
    if text:
        await reply(ctx, text)


@bot.command(name="eghost", aliases=["игост", "ehost"])
@has_any_role(*ROLE_ACCESS_GHOST_EVENT)
async def eghost_command(ctx):
    """Панель открытия игоста."""
    await send_panel(EGHOST, ctx.author, ctx=ctx)


@eghost_command.error
async def eghost_command_error(ctx, error):
    text = error_text(error, "**Использование:** `&eghost`")
    if text:
        await reply(ctx, text)


#  Слэш-команды: то же самое, но ответ виден только автору
@bot.slash_command(
    name="aghost",
    description="Открыть агост и сдать отчёт",
    guild_ids=GUILDS,
)
async def aghost_slash(inter: disnake.ApplicationCommandInteraction):
    await inter.response.defer(ephemeral=True)
    await send_panel(AGHOST, inter.author, inter=inter)


@bot.slash_command(
    name="eghost",
    description="Открыть игост и сдать отчёт",
    guild_ids=GUILDS,
)
async def eghost_slash(inter: disnake.ApplicationCommandInteraction):
    await inter.response.defer(ephemeral=True)
    await send_panel(EGHOST, inter.author, inter=inter)
