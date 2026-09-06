"""
Кнопки под карточкой гост-отчёта.

    ghost:<вид>:finish:<отчёт> - завершить смену, спросив время окончания
    ghost:<вид>:act:<отчёт> - оповестить о действии, только у игоста
    ghost:<вид>:approve:<отчёт> - подтвердить отчёт, заметка по желанию
    ghost:<вид>:reject:<отчёт> - не подтверждать, причина обязательна
    ghost:<вид>:log:<отчёт> - хронология действий смены
"""

import logging

import disnake

from bot_init import bot, ghost_db
from ghost_rules import (
    AGHOST,
    EGHOST,
    REVIEW_APPROVED,
    REVIEW_REJECTED,
    kind_name,
    parse_end,
)
from ghost_service import (
    MENTIONS,
    add_action,
    build_actions_embed,
    can_open,
    can_review,
    close_shift,
    review_shift,
)
from vacation_time import as_local

logger = logging.getLogger(__name__)

REVIEW_ACTIONS = ("approve", "reject")


def _allowed(user, kind: str | None, action: str) -> str | None:
    """Текст отказа или None, если кнопка этому человеку доступна."""
    if action in REVIEW_ACTIONS:
        if can_review(user, kind):
            return None
        return (
            "Отчёты модерации проверяют наблюдатели и выше, "
            "отчёты ивентологии - ивентер-инструктор и выше."
        )

    # Карточка из старого формата custom_id: вида смены в ней нет, поэтому
    # пускаем любого из отделов, а хозяина смены проверит уже сам вызов
    if kind is None:
        staff = can_open(user, AGHOST) or can_open(user, EGHOST) or can_review(user)
        return None if staff else "Это кнопки для отделов."

    if can_open(user, kind) or can_review(user, kind):
        return None

    return f"{kind_name(kind)} ведёт свой отдел, чужие смены не трогаем."


#  Завершение смены
class FinishModal(disnake.ui.Modal):
    """
    Время окончания. По умолчанию «сейчас», но кнопку часто жмут не сразу
    после раунда, поэтому руками поправить можно.
    """

    def __init__(self, shift_id: int):
        self.shift_id = shift_id

        super().__init__(
            title=f"Завершить смену, отчёт #{shift_id}"[:45],
            custom_id=f"ghost_finish_modal:{shift_id}",
            components=[
                disnake.ui.TextInput(
                    label="Время окончания",
                    custom_id="ended",
                    style=disnake.TextInputStyle.short,
                    required=True,
                    max_length=10,
                    value="сейчас",
                    placeholder="23:04 или «сейчас»",
                )
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)

        row = await ghost_db.get_shift(self.shift_id)
        if row is None:
            await inter.followup.send(f"❌ Отчёт #{self.shift_id} не найден.", ephemeral=True)
            return

        # Разбирать окончание можно только зная начало: смена, открытая в
        # 23:40 и закрытая в 00:20, идёт сорок минут, а не минус сутки
        ended_at, problem = parse_end(
            inter.text_values.get("ended"), as_local(row["started_at"])
        )
        if problem:
            await inter.followup.send(f"❌ {problem}", ephemeral=True)
            return

        text = await close_shift(self.shift_id, inter.author, ended_at)
        await inter.followup.send(text, ephemeral=True, allowed_mentions=MENTIONS)


#  Действие по ходу раунда
class ActionModal(disnake.ui.Modal):
    """
    Что произошло. Одно поле и никаких типов: посреди ивента лишний выбор
    из списка стоит дороже, чем строка свободного текста.
    """

    def __init__(self, shift_id: int):
        self.shift_id = shift_id

        super().__init__(
            title=f"Действие в раунде, отчёт #{shift_id}"[:45],
            custom_id=f"ghost_action_modal:{shift_id}",
            components=[
                disnake.ui.TextInput(
                    label="Что произошло",
                    custom_id="body",
                    style=disnake.TextInputStyle.paragraph,
                    required=True,
                    max_length=900,
                    placeholder="Спавн синдиката у грузового, три бойца, идут к мостику",
                )
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)

        text = await add_action(self.shift_id, inter.author, inter.text_values.get("body", ""))
        await inter.followup.send(text, ephemeral=True, allowed_mentions=MENTIONS)


#  Проверка отчёта
class ApproveModal(disnake.ui.Modal):
    """Заметка по желанию: пустая - значит подтвердили молча."""

    def __init__(self, shift_id: int):
        self.shift_id = shift_id

        super().__init__(
            title=f"Подтвердить отчёт #{shift_id}"[:45],
            custom_id=f"ghost_approve_modal:{shift_id}",
            components=[
                disnake.ui.TextInput(
                    label="Заметка (необязательно)",
                    custom_id="note",
                    style=disnake.TextInputStyle.paragraph,
                    required=False,
                    max_length=900,
                    placeholder="Можно оставить пустым - отчёт подтвердится без комментария",
                )
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)

        text = await review_shift(
            self.shift_id, REVIEW_APPROVED, inter.author, inter.text_values.get("note", "")
        )
        await inter.followup.send(text, ephemeral=True, allowed_mentions=MENTIONS)


class RejectModal(disnake.ui.Modal):
    """Отказ без причины бесполезен: человеку нечего исправлять."""

    def __init__(self, shift_id: int):
        self.shift_id = shift_id

        super().__init__(
            title=f"Не подтверждать отчёт #{shift_id}"[:45],
            custom_id=f"ghost_reject_modal:{shift_id}",
            components=[
                disnake.ui.TextInput(
                    label="Причина",
                    custom_id="note",
                    style=disnake.TextInputStyle.paragraph,
                    required=True,
                    max_length=900,
                    placeholder="Что не так с отчётом и что переделать",
                )
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)

        text = await review_shift(
            self.shift_id, REVIEW_REJECTED, inter.author, inter.text_values.get("note", "")
        )
        await inter.followup.send(text, ephemeral=True, allowed_mentions=MENTIONS)


#  Роутер
async def _handle(inter, kind: str | None, action: str, shift_id: int):
    problem = _allowed(inter.author, kind, action)
    if problem:
        await inter.response.send_message(f"❌ {problem}", ephemeral=True)
        return

    if action in ("finish", "act"):
        modal = FinishModal(shift_id) if action == "finish" else ActionModal(shift_id)
        await inter.response.send_modal(modal)
        return

    if action in REVIEW_ACTIONS:
        modal = ApproveModal(shift_id) if action == "approve" else RejectModal(shift_id)
        await inter.response.send_modal(modal)
        return

    if action == "log":
        await inter.response.defer(ephemeral=True)

        row = await ghost_db.get_shift(shift_id)
        if row is None:
            await inter.followup.send(f"❌ Отчёт #{shift_id} не найден.", ephemeral=True)
            return

        actions = await ghost_db.list_actions(shift_id)
        await inter.followup.send(embed=build_actions_embed(row, actions), ephemeral=True)
        return


@bot.listen("on_button_click")
async def ghost_component_router(inter: disnake.MessageInteraction):
    """Ловит нажатия по префиксу custom_id, остальные кнопки не трогает."""
    custom_id = inter.component.custom_id or ""

    if not custom_id.startswith("ghost:"):
        return

    try:
        parts = custom_id.split(":")

        # ghost:<вид>:<действие>:<отчёт>, но карточки самых первых прогонов
        # ещё без вида - их кнопки должны продолжать работать
        if len(parts) == 4:
            _, kind, action, shift_id = parts
        elif len(parts) == 3:
            _, action, shift_id = parts
            kind = None
        else:
            return

        await _handle(inter, kind, action, int(shift_id))
    except Exception:
        logger.exception("Ошибка обработки кнопки гост-отчёта: %s", custom_id)

        if not inter.response.is_done():
            try:
                await inter.response.send_message(
                    "❗ Что-то пошло не так, ошибка записана в лог.", ephemeral=True
                )
            except disnake.HTTPException:
                pass
