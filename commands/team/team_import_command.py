"""
Разовый импорт текущего состава в базу.

    &team_import

Сначала показывает, что будет записано, и ждёт подтверждения кнопкой.
Тех, кто уже есть в базе, пропускает, так что повторный запуск безопасен.
У импортированных дата найма пустая: они считаются в численности,
но не попадают в наймы за период, иначе аналитика покажет всплеск.
"""

import disnake

from disnake.ext.commands import has_any_role

from bot_init import bot, team_db
from dataConfig import ROLE_ACCESS_HEADS
from team_departments import DEPARTMENTS, department_name
from team_service import (
    COLOR_INFO,
    MENTIONS,
    collect_import_rows,
    command_error_text,
    department_headcount,
    role_gaps,
)

USAGE = "**Использование:** `&team_import` - показывает предпросмотр и просит подтвердить."

TIMEOUT = 120


def _preview(guild, rows) -> disnake.Embed:
    people = {ds_id for ds_id, _, _ in rows}

    embed = disnake.Embed(
        title="Импорт текущего состава",
        description=(
            f"Найдено **{len(people)}** чел. и **{len(rows)}** должностей.\n"
            "Записываются только те, кого ещё нет в базе."
        ),
        color=COLOR_INFO,
    )

    for key in DEPARTMENTS:
        count = len(department_headcount(guild, key))
        if count:
            embed.add_field(name=department_name(key), value=f"{count} чел.", inline=True)

    no_department, no_team = role_gaps(guild)
    if no_department or no_team:
        embed.add_field(
            name="Стоит поправить руками",
            value=(
                f"без роли отдела: {no_department} чел.\n"
                f"без роли команды проекта: {no_team} чел."
            ),
            inline=False,
        )
    return embed


class ConfirmImport(disnake.ui.View):
    def __init__(self, author_id: int, rows: list):
        super().__init__(timeout=TIMEOUT)
        self.author_id = author_id
        self.rows = rows
        self.message = None

    async def interaction_check(self, inter) -> bool:
        if inter.author.id != self.author_id:
            await inter.response.send_message("Импорт запускал не ты.", ephemeral=True)
            return False
        return True

    def _lock(self):
        for child in self.children:
            child.disabled = True

    async def on_timeout(self):
        self._lock()
        if self.message:
            try:
                await self.message.edit(content="⌛ Время вышло, импорт не запущен.", view=self)
            except disnake.HTTPException:
                pass

    @disnake.ui.button(label="Импортировать", style=disnake.ButtonStyle.success)
    async def confirm(self, button, inter):
        self._lock()
        await inter.response.edit_message(content="⏳ Пишу в базу...", view=self)

        ok, info = await team_db.import_members(self.rows)
        self.stop()

        if not ok:
            await inter.followup.send(f"❌ Импорт не прошёл: `{info}`")
            return

        skipped = len(self.rows) - info
        text = f"✅ Импортировано должностей: **{info}**."
        if skipped:
            text += f" Уже были в базе: {skipped}."

        await inter.followup.send(text)

    @disnake.ui.button(label="Отмена", style=disnake.ButtonStyle.secondary)
    async def cancel(self, button, inter):
        self._lock()
        self.stop()
        await inter.response.edit_message(content="Импорт отменён.", view=self)


@bot.command(name="team_import")
@has_any_role(*ROLE_ACCESS_HEADS)
async def team_import_command(ctx):
    """Переносит текущий состав с ролей Discord в базу."""
    rows = collect_import_rows(ctx.guild)

    if not rows:
        await ctx.send("Не нашёл никого с должностными ролями. Проверь ID ролей в `team_departments.py`.")
        return

    view = ConfirmImport(ctx.author.id, rows)
    view.message = await ctx.send(
        embed=_preview(ctx.guild, rows), view=view, allowed_mentions=MENTIONS
    )


@team_import_command.error
async def team_import_command_error(ctx, error):
    text = command_error_text(error, USAGE)
    if text:
        await ctx.send(text, allowed_mentions=MENTIONS)
