"""
Панель модератора и досье участника.

    &mod @user - карточка участника с кнопками быстрых действий
    &modpanel - выложить постоянную панель с кнопками

Досье собирает всё, что стоит знать до решения: возраст аккаунта, когда
зашёл, роли, активные варны, текущее наказание и подсветку рисков. Кнопки
под ним делают ровно то же, что команды, поэтому история не расходится.
"""

import logging

import disnake

from disnake.ext.commands import has_any_role

from bot_init import bot
from commands.moderation.mod_common import error_text, reply
from dataConfig import MOD_DEFAULT_MUTE, ROLE_ACCESS_MODERATOR
from mod_rules import COLOR_INFO, action_title, split_duration
from mod_service import (
    MENTIONS,
    build_dossier,
    find_target,
    is_moderator,
    is_senior,
    perform_ban,
    perform_kick,
    perform_mute,
    perform_note,
    perform_warn,
)

logger = logging.getLogger(__name__)

STEP_TIMEOUT = 180

ACTIONS = ("warn", "mute", "kick", "ban", "note")

# Какие действия требуют старшего состава. Бан сюда не входит:
# банят все модераторы, старшинство нужно только для чужих кейсов,
# закрытия сервера и настройки роли мута
SENIOR_ONLY = ()

REASON_PLACEHOLDER = "За что наказание. Например: реклама в общем чате"


def _allowed(user, action: str) -> str | None:
    """Текст отказа или None, если действие этому модератору доступно."""
    if not is_moderator(user):
        return "Модерация доступна только персоналу сервера."

    if action in SENIOR_ONLY and not is_senior(user):
        return "Баны выдаёт старший состав."

    return None


async def run_action(action: str, target, actor, reason: str, duration_text: str = "") -> str:
    """Единая точка: и кнопка, и слэш-команда зовут отсюда те же perform_*."""
    if action == "warn":
        return await perform_warn(target, actor, reason, source="panel")

    if action == "mute":
        duration, extra, _ = split_duration(duration_text or MOD_DEFAULT_MUTE, MOD_DEFAULT_MUTE)
        return await perform_mute(target, actor, duration, reason or extra, source="panel")

    if action == "kick":
        return await perform_kick(target, actor, reason, source="panel")

    if action == "ban":
        duration, extra, _ = split_duration(duration_text)
        return await perform_ban(target, actor, duration, reason or extra, source="panel")

    if action == "note":
        return await perform_note(target, actor, reason)

    return f"❌ Неизвестное действие «{action}»."


#  Шаг с причиной
class ActionModal(disnake.ui.Modal):
    """Причина, а для мута и бана ещё и срок."""

    def __init__(self, action: str, target, root=None):
        self.action, self.target, self.root = action, target, root

        components = [
            disnake.ui.TextInput(
                label="Причина",
                custom_id="reason",
                style=disnake.TextInputStyle.paragraph,
                required=False,
                max_length=500,
                placeholder=REASON_PLACEHOLDER,
            )
        ]

        if action in ("mute", "ban"):
            components.append(
                disnake.ui.TextInput(
                    label="Срок",
                    custom_id="duration",
                    style=disnake.TextInputStyle.short,
                    required=False,
                    max_length=20,
                    value=MOD_DEFAULT_MUTE if action == "mute" else "",
                    placeholder="10m, 2h, 3d, 1w или «перм»",
                )
            )

        super().__init__(
            title=f"{action_title(action)}"[:45],
            custom_id=f"mod_modal:{action}:{target.id}",
            components=components,
        )

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)

        reason = (inter.text_values.get("reason") or "").strip()
        duration = (inter.text_values.get("duration") or "").strip()

        text = await run_action(self.action, self.target, inter.author, reason, duration)
        await inter.followup.send(text, ephemeral=True, allowed_mentions=MENTIONS)

        if self.root is not None:
            try:
                await self.root.edit_original_response(content="Готово.", embed=None, view=None)
            except disnake.HTTPException:
                pass


#  Кнопки под досье
class QuickActions(disnake.ui.View):
    """Быстрые действия под карточкой участника. Жмёт только тот, кто позвал."""

    def __init__(self, target, author_id: int):
        super().__init__(timeout=STEP_TIMEOUT)
        self.target = target
        self.author_id = author_id

    async def interaction_check(self, inter) -> bool:
        if inter.author.id != self.author_id:
            await inter.response.send_message("Открой своё досье: `&mod @участник`.", ephemeral=True)
            return False
        return True

    async def _start(self, inter, action: str):
        problem = _allowed(inter.author, action)
        if problem:
            await inter.response.send_message(f"❌ {problem}", ephemeral=True)
            return

        await inter.response.send_modal(ActionModal(action, self.target))

    @disnake.ui.button(label="Варн", emoji="⚠️", style=disnake.ButtonStyle.secondary)
    async def warn(self, button, inter):
        await self._start(inter, "warn")

    @disnake.ui.button(label="Мут", emoji="🔇", style=disnake.ButtonStyle.primary)
    async def mute(self, button, inter):
        await self._start(inter, "mute")

    @disnake.ui.button(label="Кик", emoji="👢", style=disnake.ButtonStyle.danger)
    async def kick(self, button, inter):
        await self._start(inter, "kick")

    @disnake.ui.button(label="Бан", emoji="🔨", style=disnake.ButtonStyle.danger)
    async def ban(self, button, inter):
        await self._start(inter, "ban")

    @disnake.ui.button(label="Заметка", emoji="📝", style=disnake.ButtonStyle.secondary)
    async def note(self, button, inter):
        await self._start(inter, "note")

    @disnake.ui.button(label="Обновить", emoji="🔄", style=disnake.ButtonStyle.secondary, row=1)
    async def refresh(self, button, inter):
        # Досье собирается запросами в базу, а на первый ответ Discord даёт
        # три секунды. Пока Postgres отвечает, взаимодействие успевает
        # протухнуть, поэтому сначала откладываем ответ и правим уже потом
        await inter.response.defer()

        embed = await build_dossier(self.target, inter.guild)
        await inter.edit_original_response(embed=embed, view=self)


#  Шаг выбора участника для панели
class MemberStep(disnake.ui.View):
    def __init__(self, action: str, root):
        super().__init__(timeout=STEP_TIMEOUT)
        self.action, self.root = action, root

    @disnake.ui.user_select(placeholder="Кого", min_values=1, max_values=1)
    async def picker(self, select, inter):
        target = select.values[0]

        if isinstance(target, disnake.User):
            target = inter.guild.get_member(target.id) or target

        self.stop()
        await inter.response.send_modal(ActionModal(self.action, target, self.root))


class ModPanel(disnake.ui.View):
    """Постоянная панель. Кнопки переживают перезапуск бота."""

    def __init__(self):
        super().__init__(timeout=None)

    async def _start(self, inter, action: str):
        problem = _allowed(inter.author, action)
        if problem:
            logger.warning(
                "Отказано в доступе к панели модерации (%s): %s (%s)",
                action, inter.author, inter.author.id,
            )
            await inter.response.send_message(f"❌ {problem}", ephemeral=True)
            return

        await inter.response.send_message(
            content=f"**{action_title(action)}**. Выбери участника:",
            view=MemberStep(action, inter),
            ephemeral=True,
        )

    @disnake.ui.button(label="Варн", emoji="⚠️", style=disnake.ButtonStyle.secondary,
                       custom_id="mod_panel:warn")
    async def warn(self, button, inter):
        await self._start(inter, "warn")

    @disnake.ui.button(label="Мут", emoji="🔇", style=disnake.ButtonStyle.primary,
                       custom_id="mod_panel:mute")
    async def mute(self, button, inter):
        await self._start(inter, "mute")

    @disnake.ui.button(label="Кик", emoji="👢", style=disnake.ButtonStyle.danger,
                       custom_id="mod_panel:kick")
    async def kick(self, button, inter):
        await self._start(inter, "kick")

    @disnake.ui.button(label="Бан", emoji="🔨", style=disnake.ButtonStyle.danger,
                       custom_id="mod_panel:ban")
    async def ban(self, button, inter):
        await self._start(inter, "ban")

    @disnake.ui.button(label="Заметка", emoji="📝", style=disnake.ButtonStyle.secondary,
                       custom_id="mod_panel:note")
    async def note(self, button, inter):
        await self._start(inter, "note")


@bot.command(name="mod", aliases=["досье", "modcard"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def mod_command(ctx, *, target: str = ""):
    """Досье участника с кнопками быстрых действий."""
    if not target.strip():
        await reply(ctx, "**Использование:** `&mod <@участник или ID>`")
        return

    user, problem = await find_target(ctx, target)
    if problem:
        await reply(ctx, f"❌ {problem}")
        return

    embed = await build_dossier(user, ctx.guild)
    await ctx.send(embed=embed, view=QuickActions(user, ctx.author.id), allowed_mentions=MENTIONS)


@mod_command.error
async def mod_command_error(ctx, error):
    text = error_text(error, "**Использование:** `&mod <@участник или ID>`")
    if text:
        await reply(ctx, text)


@bot.command(name="modpanel", aliases=["панель_модерации"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def modpanel_command(ctx):
    """Выкладывает постоянную панель модерации."""
    embed = disnake.Embed(
        title="🛡️ Панель модерации",
        description="Выберите действие:",
        color=COLOR_INFO,
    )
    embed.set_footer(text="Досье участника: &mod @участник · справка: &mod_help")

    await ctx.send(embed=embed, view=ModPanel(), allowed_mentions=MENTIONS)
