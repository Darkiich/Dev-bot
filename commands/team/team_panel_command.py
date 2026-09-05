"""
Интерактивное меню кадровых действий.

    &team_panel - выложить панель с кнопками

Панель живёт вечно, кнопки переживают перезапуск бота. Всё остальное
происходит в скрытых сообщениях, видных только тому, кто нажал.

Шаги подстроены под действие: при найме спрашиваем отдел, при остальных
действиях он и так известен из ролей человека. В списках показываем
только то, что реально можно выбрать, поэтому промахнуться нечем.

Кнопки и команды зовут одни и те же perform_* из team_service.
"""

import logging

import disnake

from disnake.ext.commands import has_any_role

from bot_init import bot
from dataConfig import ROLE_ACCESS_HEADS
from team_departments import DEPARTMENTS, department_name, get_positions
from team_service import (
    COLOR_INFO,
    MENTIONS,
    actor_problem,
    member_positions,
    perform_fire,
    perform_hire,
    perform_move,
    positions_in,
    top_ladder_position,
)

STEP_TIMEOUT = 180

logger = logging.getLogger(__name__)

TITLES = {
    "hire": "Найм",
    "fire": "Увольнение",
    "promote": "Повышение",
    "demote": "Понижение",
}


def _allowed(user) -> bool:
    roles = getattr(user, "roles", None)
    if roles is None:
        return False
    return any(role.id in ROLE_ACCESS_HEADS for role in roles)


def _options_for(member: disnake.Member, action: str) -> tuple[list, str]:
    """
    Должности, которые имеет смысл предложить. Возвращает (варианты, причина пустоты).
    Пустой список это не ошибка, а повод объяснить человеку, почему выбирать нечего.
    """
    held = member_positions(member)

    if action == "fire":
        if not held:
            return [], f"{member.mention} не занимает ни одной должности."
        return held, ""

    options = []
    for key in DEPARTMENTS:
        current = top_ladder_position(held, key)
        if current is None:
            continue
        for position in get_positions(key):
            if not position.on_ladder:
                continue
            if action == "promote" and position.grade > current.grade:
                options.append(position)
            if action == "demote" and position.grade < current.grade:
                options.append(position)

    if not options:
        if not held:
            return [], f"{member.mention} не занимает ни одной должности, нужен найм."
        if action == "promote":
            return [], f"{member.mention} уже на верхней ступени своего отдела."
        return [], f"{member.mention} уже на нижней ступени своего отдела."

    return options, ""


def _label(position) -> str:
    return f"{position.name} - {position.department_name}"[:100]


#  Шаг 3: причина
class ReasonModal(disnake.ui.Modal):
    def __init__(self, action: str, member: disnake.Member, position, root):
        self.action, self.member, self.position, self.root = action, member, position, root

        super().__init__(
            title=f"{TITLES[action]}: {position.name}"[:45],
            custom_id=f"team_reason:{action}:{member.id}:{position.role_id}",
            components=[
                disnake.ui.TextInput(
                    label="Причина",
                    custom_id="reason",
                    style=disnake.TextInputStyle.paragraph,
                    required=False,
                    max_length=500,
                    placeholder="Можно оставить пустым",
                )
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)

        role = inter.guild.get_role(self.position.role_id)
        if role is None:
            await inter.followup.send(
                f"❌ Роль «{self.position.name}» не найдена на сервере.", ephemeral=True
            )
            return

        reason = (inter.text_values.get("reason") or "").strip()

        if self.action == "hire":
            text = await perform_hire(self.member, role, inter.author, reason)
        elif self.action == "fire":
            text = await perform_fire(self.member, role, inter.author, reason)
        else:
            text = await perform_move(self.member, role, inter.author, self.action, reason)

        await inter.followup.send(text, ephemeral=True, allowed_mentions=MENTIONS)

        try:
            await self.root.edit_original_response(content="Готово.", embed=None, view=None)
        except disnake.HTTPException:
            pass


#  Шаг 2: должность
class PositionStep(disnake.ui.View):
    def __init__(self, action: str, member: disnake.Member, positions: list, root):
        super().__init__(timeout=STEP_TIMEOUT)
        self.action, self.member, self.root = action, member, root
        self.positions = {str(p.role_id): p for p in positions[:25]}

        self.picker.options = [
            disnake.SelectOption(label=_label(p), value=str(p.role_id))
            for p in self.positions.values()
        ]

    @disnake.ui.string_select(placeholder="Должность", min_values=1, max_values=1)
    async def picker(self, select, inter):
        position = self.positions[select.values[0]]
        self.stop()
        await inter.response.send_modal(ReasonModal(self.action, self.member, position, self.root))


#  Шаг 2 для найма: сначала отдел
class DepartmentStep(disnake.ui.View):
    def __init__(self, action: str, member: disnake.Member, root):
        super().__init__(timeout=STEP_TIMEOUT)
        self.action, self.member, self.root = action, member, root

        self.picker.options = [
            disnake.SelectOption(label=dept["name"], value=key)
            for key, dept in DEPARTMENTS.items()
        ]

    @disnake.ui.string_select(placeholder="Отдел", min_values=1, max_values=1)
    async def picker(self, select, inter):
        key = select.values[0]
        held = positions_in(member_positions(self.member), key)
        taken = {p.role_id for p in held}

        options = [p for p in get_positions(key) if p.role_id not in taken]
        if not options:
            await inter.response.edit_message(
                content=f"{self.member.mention} уже занимает все должности отдела «{department_name(key)}».",
                embed=None, view=None,
            )
            self.stop()
            return

        self.stop()
        await inter.response.edit_message(
            content=f"**Найм** {self.member.mention}, отдел «{department_name(key)}». Выбери должность:",
            embed=None,
            view=PositionStep(self.action, self.member, options, self.root),
        )


#  Шаг 1: участник
class MemberStep(disnake.ui.View):
    def __init__(self, action: str, root):
        super().__init__(timeout=STEP_TIMEOUT)
        self.action, self.root = action, root

    @disnake.ui.user_select(placeholder="Кого", min_values=1, max_values=1)
    async def picker(self, select, inter):
        member = select.values[0]

        if isinstance(member, disnake.User):
            member = inter.guild.get_member(member.id)
        if member is None:
            await inter.response.edit_message(content="❌ Участник не найден на сервере.", view=None)
            self.stop()
            return

        # Ту же проверку сделают perform_*, но лучше сказать сразу,
        # чем после выбора должности и набранной причины
        problem = actor_problem(inter.author, member, self.action)
        if problem:
            await inter.response.edit_message(content=f"❌ {problem}", view=None)
            self.stop()
            return

        self.stop()

        if self.action == "hire":
            await inter.response.edit_message(
                content=f"**Найм** {member.mention}. Выбери отдел:",
                view=DepartmentStep(self.action, member, self.root),
            )
            return

        options, problem = _options_for(member, self.action)
        if problem:
            await inter.response.edit_message(content=f"❌ {problem}", view=None)
            return

        await inter.response.edit_message(
            content=f"**{TITLES[self.action]}** {member.mention}. Выбери должность:",
            view=PositionStep(self.action, member, options, self.root),
        )


#  Сама панель
class TeamPanel(disnake.ui.View):
    """Живёт вечно, поэтому у кнопок постоянные custom_id и timeout=None."""

    def __init__(self):
        super().__init__(timeout=None)

    async def _start(self, inter, action: str):
        if not _allowed(inter.author):
            logger.warning("Отказано в доступе к панели кадров (%s): %s (%s)", action, inter.author, inter.author.id)
            await inter.response.send_message(
                "Кадровые действия доступны только главам.", ephemeral=True
            )
            return

        logger.info("Панель кадров: %s начал '%s'", inter.author, action)
        await inter.response.send_message(
            content=f"**{TITLES[action]}**. Выбери участника:",
            view=MemberStep(action, inter),
            ephemeral=True,
        )

    @disnake.ui.button(label="Найм", emoji="📥", style=disnake.ButtonStyle.success,
                       custom_id="team_panel:hire")
    async def hire(self, button, inter):
        await self._start(inter, "hire")

    @disnake.ui.button(label="Увольнение", emoji="📤", style=disnake.ButtonStyle.danger,
                       custom_id="team_panel:fire")
    async def fire(self, button, inter):
        await self._start(inter, "fire")

    @disnake.ui.button(label="Повышение", emoji="📈", style=disnake.ButtonStyle.primary,
                       custom_id="team_panel:promote")
    async def promote(self, button, inter):
        await self._start(inter, "promote")

    @disnake.ui.button(label="Понижение", emoji="📉", style=disnake.ButtonStyle.secondary,
                       custom_id="team_panel:demote")
    async def demote(self, button, inter):
        await self._start(inter, "demote")


@bot.command(name="team_panel")
@has_any_role(*ROLE_ACCESS_HEADS)
async def team_panel_command(ctx):
    """Выкладывает панель кадровых действий."""
    embed = disnake.Embed(
        title="Кадровые действия",
        description=(
            "Нажми кнопку и следуй шагам. Всё видно только тебе.\n"
            "То же самое делают команды `&hire`, `&fire`, `&promote`, `&demote`."
        ),
        color=COLOR_INFO,
    )

    await ctx.send(embed=embed, view=TeamPanel(), allowed_mentions=MENTIONS)
