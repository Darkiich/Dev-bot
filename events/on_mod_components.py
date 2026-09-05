"""
Кнопки под карточкой кейса в лог-канале.
    mod_case:revoke:<кейс> - снять наказание
    mod_case:reason:<кейс> - поправить формулировку
    mod_case:card:<кейс> - досье нарушителя
"""

import logging

import disnake

from bot_init import bot, mod_db
from mod_service import (
    MENTIONS,
    build_case_detail,
    build_dossier,
    is_moderator,
    moderation_guild,
    resolve_member,
    resolve_user,
    revoke_case,
)

logger = logging.getLogger(__name__)


class RevokeModal(disnake.ui.Modal):
    """Комментарий к снятию: почему наказание больше не в силе."""

    def __init__(self, case_id: int):
        self.case_id = case_id
        super().__init__(
            title=f"Снять наказание, кейс #{case_id}"[:45],
            custom_id=f"mod_revoke_modal:{case_id}",
            components=[
                disnake.ui.TextInput(
                    label="Комментарий",
                    custom_id="reason",
                    style=disnake.TextInputStyle.paragraph,
                    required=False,
                    max_length=500,
                    placeholder="Почему снимаем. Можно оставить пустым",
                )
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        text = await revoke_case(self.case_id, inter.author, inter.text_values.get("reason", ""))
        await inter.followup.send(text, ephemeral=True, allowed_mentions=MENTIONS)


class ReasonModal(disnake.ui.Modal):
    """Правка причины уже выданного наказания."""

    def __init__(self, case_id: int, current: str = ""):
        self.case_id = case_id
        super().__init__(
            title=f"Причина кейса #{case_id}"[:45],
            custom_id=f"mod_reason_modal:{case_id}",
            components=[
                disnake.ui.TextInput(
                    label="Новая формулировка",
                    custom_id="reason",
                    style=disnake.TextInputStyle.paragraph,
                    required=True,
                    max_length=500,
                    value=current[:500],
                )
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)

        row = await mod_db.update_reason(self.case_id, inter.text_values["reason"].strip())
        if row is None:
            await inter.followup.send("⚠️ База недоступна, причина не изменилась.", ephemeral=True)
            return

        logger.info("Причина кейса #%s изменена модератором %s", self.case_id, inter.author)

        # Карточка в канале должна показывать то же, что база
        try:
            embed = inter.message.embeds[0]
            for index, field in enumerate(embed.fields):
                if field.name == "Причина":
                    embed.set_field_at(index, name="Причина", value=row["reason"][:1000], inline=False)
                    break
            await inter.message.edit(embed=embed)
        except (IndexError, disnake.HTTPException):
            pass

        await inter.followup.send(f"✏️ Причина кейса #{self.case_id} обновлена.", ephemeral=True)


def _reason_from_card(message) -> str:
    """
    Текущая причина берётся из самой карточки, а не из базы.

    Модалку Discord принимает только первым ответом на нажатие, отложить её
    нельзя - а запрос в базу до ответа съедает те самые три секунды.
    """
    if not message or not message.embeds:
        return ""

    for field in message.embeds[0].fields:
        if field.name == "Причина":
            return field.value or ""

    return ""


async def _handle_case_button(inter, action: str, case_id: int):
    if not is_moderator(inter.author):
        await inter.response.send_message("❌ Это кнопки для персонала.", ephemeral=True)
        return

    # Модалки открываем сразу: существование кейса проверят их обработчики
    if action == "revoke":
        await inter.response.send_modal(RevokeModal(case_id))
        return

    if action == "reason":
        await inter.response.send_modal(ReasonModal(case_id, _reason_from_card(inter.message)))
        return

    if action == "card":
        await inter.response.defer(ephemeral=True)

        row = await mod_db.get_case(case_id)
        if row is None:
            await inter.followup.send(f"❌ Кейс #{case_id} не найден.", ephemeral=True)
            return

        guild = inter.guild or moderation_guild()
        target = await resolve_member(guild, row["target_id"]) or await resolve_user(row["target_id"])

        if target is None:
            await inter.followup.send(embed=build_case_detail(row), ephemeral=True)
            return

        await inter.followup.send(embed=await build_dossier(target, guild), ephemeral=True)


@bot.listen("on_button_click")
async def mod_component_router(inter: disnake.MessageInteraction):
    """Ловит нажатия по префиксу custom_id, остальные кнопки не трогает."""
    custom_id = inter.component.custom_id or ""

    if not custom_id.startswith("mod_case:"):
        return

    try:
        _, action, case_id = custom_id.split(":", 2)
        await _handle_case_button(inter, action, int(case_id))
    except Exception:
        logger.exception("Ошибка обработки кнопки модерации: %s", custom_id)

        if not inter.response.is_done():
            try:
                await inter.response.send_message(
                    "❗ Что-то пошло не так, ошибка записана в лог.", ephemeral=True
                )
            except disnake.HTTPException:
                pass
