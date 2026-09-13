"""
&character - карточка персонажа: свои, чужие по Discord или поиск по имени
"""

import logging

import disnake

from bot_init import bot, stats_db
from commands.moderation.mod_common import reply
from commands.player.character_card import build_card, name_of
from commands.player.player_common import fail
from dataConfig import PLAYER_CHARACTERS_BY_DISCORD, PLAYER_STATS_SERVER
from player_jobs import species_name
from player_service import (
    COLOR_MAIN,
    MENTIONS,
    discord_id_from,
    guid_by_discord,
    link_hint,
    looks_like_uuid,
)

logger = logging.getLogger(__name__)

PANEL_TIMEOUT = 180
OPTIONS_LIMIT = 25


class CharacterSelect(disnake.ui.StringSelect):
    """Выбор персонажа из списка."""

    def __init__(self, rows: list, owner: str | None):
        self.rows = rows[:OPTIONS_LIMIT]
        self.owner = owner

        options = []
        for index, row in enumerate(self.rows):
            description = species_name(row["species"]) if "species" in set(row.keys()) else None
            options.append(
                disnake.SelectOption(
                    label=name_of(row)[:100],
                    value=str(index),
                    description=(description or None),
                )
            )

        super().__init__(placeholder="Выбери персонажа", options=options)

    async def callback(self, inter: disnake.MessageInteraction):
        row = self.rows[int(self.values[0])]
        await inter.response.defer(ephemeral=True)
        await inter.followup.send(embed=await build_card(row, self.owner), ephemeral=True)


class CharacterPanel(disnake.ui.View):
    """Список персонажей с выбором. Работает только для того, кто вызвал."""

    def __init__(self, author_id: int, rows: list, owner: str | None):
        super().__init__(timeout=PANEL_TIMEOUT)
        self.author_id = author_id
        self.message = None
        self.add_item(CharacterSelect(rows, owner))

    async def interaction_check(self, inter) -> bool:
        if inter.author.id != self.author_id:
            await inter.response.send_message(
                "Это чужой список. Открой свой: `&character`.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except disnake.HTTPException:
                pass


async def _resolve(ctx, query: str):
    """Чьих персонажей показывать: (строки, подпись владельца, ошибка)."""
    query = (query or "").strip()

    if not query:
        guid = await guid_by_discord(ctx.author.id)
        if not guid:
            return None, None, link_hint()
        rows = await stats_db.characters_of(guid, PLAYER_STATS_SERVER)
        return rows, "ты", None

    discord_id = discord_id_from(query)
    if discord_id:
        if not PLAYER_CHARACTERS_BY_DISCORD:
            return None, None, "❌ Смотреть чужих персонажей по Discord на сервере запрещено."

        guid = await guid_by_discord(discord_id)
        if not guid:
            return None, None, f"❌ У <@{discord_id}> не привязан игровой аккаунт."
        rows = await stats_db.characters_of(guid, PLAYER_STATS_SERVER)
        return rows, f"<@{discord_id}>", None

    if looks_like_uuid(query):
        if not PLAYER_CHARACTERS_BY_DISCORD:
            return None, None, "❌ Смотреть чужих персонажей по UID на сервере запрещено."

        rows = await stats_db.characters_of(query, PLAYER_STATS_SERVER)
        return rows, f"UID `{query}`", None

    if len(query) < 3:
        return None, None, "❌ Для поиска нужно хотя бы три буквы имени."

    rows = await stats_db.characters_by_name(query, PLAYER_STATS_SERVER)
    return rows, None, None


@bot.command(name="character", aliases=["перс", "char", "персонаж"])
async def character_command(ctx, *, query: str = ""):
    """`&character`, `&character @участник`, `&character Джон Смит`."""
    try:
        rows, owner, problem = await _resolve(ctx, query)
    except Exception as e:
        await fail(ctx, e, "character")
        return

    if problem:
        await reply(ctx, problem)
        return

    if not rows:
        if owner == "ты":
            await reply(ctx, "У тебя в игре ещё нет ни одного персонажа.")
        elif owner:
            await reply(ctx, f"У {owner} нет персонажей в базе.")
        else:
            await reply(ctx, f"❌ Персонаж `{query}` не найден.")
        return

    if len(rows) == 1:
        await ctx.send(embed=await build_card(rows[0], owner), allowed_mentions=MENTIONS)
        return

    title = "🪪 Мои персонажи" if owner == "ты" else (
        f"🪪 Персонажи {owner}" if owner else f"🪪 Найдено персонажей: {len(rows)}"
    )

    embed = disnake.Embed(
        title=title,
        description="\n".join(f"**{name_of(row)}**" for row in rows[:OPTIONS_LIMIT]),
        color=COLOR_MAIN,
    )
    embed.set_footer(text="Выбери персонажа в списке ниже, карточка придёт скрытым сообщением")

    panel = CharacterPanel(ctx.author.id, rows, owner)
    panel.message = await ctx.send(embed=embed, view=panel, allowed_mentions=MENTIONS)
