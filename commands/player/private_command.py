"""
&private - скрыть своих персонажей от чужих глаз
"""

import logging

import disnake

from bot_init import bot, player_db
from commands.player.player_common import fail, require_account
from player_service import COLOR_MAIN, MENTIONS

logger = logging.getLogger(__name__)

PANEL_TIMEOUT = 120

OPEN_TEXT = (
    "Сейчас твоих персонажей **видно всем**: их найдут по имени, по твоему "
    "упоминанию и по UID."
)
HIDDEN_TEXT = (
    "Сейчас твои персонажи **скрыты**: чужие не найдут их ни поиском по имени, "
    "ни по упоминанию. Сам ты видишь их как обычно, администрация проекта тоже."
)


def _embed(hidden: bool) -> disnake.Embed:
    embed = disnake.Embed(
        title="🔒 Приватность персонажей" if hidden else "🔓 Приватность персонажей",
        description=HIDDEN_TEXT if hidden else OPEN_TEXT,
        color=COLOR_MAIN,
    )
    embed.set_footer(text="Настройка привязана к игровому аккаунту")
    return embed


class PrivacyPanel(disnake.ui.View):
    """Переключатель. Работает только для того, кто вызвал команду."""

    def __init__(self, author_id: int, guid, hidden: bool):
        super().__init__(timeout=PANEL_TIMEOUT)
        self.author_id = author_id
        self.guid = guid
        self.hidden = hidden
        self.message = None
        self._sync()

    def _sync(self):
        self.toggle.label = "Открыть персонажей" if self.hidden else "Скрыть персонажей"
        self.toggle.style = disnake.ButtonStyle.success if self.hidden else disnake.ButtonStyle.danger
        self.toggle.emoji = "🔓" if self.hidden else "🔒"

    async def interaction_check(self, inter) -> bool:
        if inter.author.id != self.author_id:
            await inter.response.send_message(
                "Это чужая настройка. Открой свою: `&private`.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except disnake.HTTPException:
                pass

    @disnake.ui.button(label="Скрыть персонажей", style=disnake.ButtonStyle.danger)
    async def toggle(self, button, inter):
        saved = await player_db.hide_characters(self.guid, not self.hidden)
        if not saved:
            await inter.response.send_message(
                "❗ Не получилось сохранить настройку, ошибка в логе.", ephemeral=True
            )
            return

        self.hidden = not self.hidden
        self._sync()
        await inter.response.edit_message(embed=_embed(self.hidden), view=self)


@bot.command(name="private", aliases=["приват", "скрыть", "privacy"])
async def private_command(ctx):
    """Показывает и переключает видимость своих персонажей."""
    guid, ckey = await require_account(ctx)
    if guid is None:
        return

    try:
        hidden = await player_db.characters_hidden(guid)
    except Exception as e:
        await fail(ctx, e, "private")
        return

    panel = PrivacyPanel(ctx.author.id, guid, hidden)
    panel.message = await ctx.send(embed=_embed(hidden), view=panel, allowed_mentions=MENTIONS)
