#&sponsor_panel

import disnake
from disnake.ext.commands import has_any_role

from bot_init import bot, ss14_db
from dataConfig import ROLE_ACCESS_SPONSOR

from .sponsor_api import SponsorApi, SponsorApiError
from .sponsor_embeds import (
    BENEFIT_FLAGS,
    error_embed,
    main_embed,
    ok_embed,
    player_embed,
    tier_embed,
    tier_list_embed,
)

VIEW_TIMEOUT = 600


async def build_api(user: disnake.abc.User) -> SponsorApi:
    guid = await ss14_db.get_player_guid_by_discord_id(str(user.id))

    if not guid:
        raise SponsorApiError(
            "Привяжите аккаунт SS14 к дискорду."
        )

    name = await ss14_db.get_admin_name(guid) or str(user)
    return SponsorApi(guid, name)


class BaseView(disnake.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.owner_id = owner_id

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.author.id == self.owner_id:
            return True

        await inter.response.send_message("Это не ваша панель.", ephemeral=True)
        return False

    async def fail(self, inter: disnake.MessageInteraction, error: Exception):
        embed = error_embed(str(error))

        if inter.response.is_done():
            await inter.followup.send(embed=embed, ephemeral=True)
        else:
            await inter.response.send_message(embed=embed, ephemeral=True)

class MainView(BaseView):
    @disnake.ui.button(label="Игрок", emoji="🔍", style=disnake.ButtonStyle.primary)
    async def player_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(PlayerSearchModal(self.owner_id))

    @disnake.ui.button(label="Тиры", emoji="📦", style=disnake.ButtonStyle.secondary)
    async def tiers_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        try:
            api = await build_api(inter.author)
            tiers = await api.get_tiers()
        except SponsorApiError as error:
            await self.fail(inter, error)
            return

        await inter.response.edit_message(
            embed=tier_list_embed(tiers),
            view=TierListView(self.owner_id, tiers),
        )


class PlayerSearchModal(disnake.ui.Modal):
    def __init__(self, owner_id: int):
        self.owner_id = owner_id

        super().__init__(
            title="Поиск игрока",
            custom_id="sponsor_player_search",
            components=[
                disnake.ui.TextInput(
                    label="Ник или GUID",
                    custom_id="query",
                    style=disnake.TextInputStyle.short,
                    max_length=64,
                ),
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        query = inter.text_values["query"].strip()

        await inter.response.defer()

        try:
            api = await build_api(inter.author)
            data = await api.get_player(query)
            tiers = await api.get_tiers()
        except SponsorApiError as error:
            await inter.followup.send(embed=error_embed(str(error)), ephemeral=True)
            return

        await inter.edit_original_response(
            embed=player_embed(query, data),
            view=PlayerView(self.owner_id, query, data, tiers),
        )

class PlayerView(BaseView):
    def __init__(self, owner_id: int, query: str, data: dict, tiers: list):
        super().__init__(owner_id)

        self.query = query
        self.data = data
        self.tiers = tiers

        self.add_item(GrantTierSelect(self))

        active = [g for g in (data.get("grants") or []) if not g.get("revoked")]

        if active:
            self.add_item(RevokeSelect(self, active))

    async def refresh(self, inter: disnake.Interaction):
        api = await build_api(inter.author)
        data = await api.get_player(self.query)
        tiers = await api.get_tiers()

        await inter.edit_original_response(
            embed=player_embed(self.query, data),
            view=PlayerView(self.owner_id, self.query, data, tiers),
        )

    @disnake.ui.button(label="Обновить", emoji="🔄", style=disnake.ButtonStyle.secondary, row=2)
    async def refresh_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.defer()

        try:
            await self.refresh(inter)
        except SponsorApiError as error:
            await self.fail(inter, error)

    @disnake.ui.button(label="Назад", emoji="◀", style=disnake.ButtonStyle.secondary, row=2)
    async def back_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.edit_message(embed=main_embed(), view=MainView(self.owner_id))


class GrantTierSelect(disnake.ui.StringSelect):
    def __init__(self, parent: PlayerView):
        self.parent = parent

        options = [
            disnake.SelectOption(
                label="Без тира (только именные бонусы)",
                value="-",
                emoji="⭐",
            ),
        ]

        for tier in parent.tiers[:24]:
            options.append(
                disnake.SelectOption(
                    label=tier.get("displayName") or tier["name"],
                    value=tier["name"],
                    description=f"приоритет {tier.get('priority', 0)}",
                )
            )

        super().__init__(placeholder="Выдать спонсорку...", options=options, row=0)

    async def callback(self, inter: disnake.MessageInteraction):
        tier = None if self.values[0] == "-" else self.values[0]
        await inter.response.send_modal(GrantModal(self.parent, tier))


class GrantModal(disnake.ui.Modal):
    def __init__(self, parent: PlayerView, tier: str | None):
        self.parent = parent
        self.tier = tier

        super().__init__(
            title="Новая выдача",
            custom_id="sponsor_grant",
            components=[
                disnake.ui.TextInput(
                    label="Дней (пусто = бессрочно)",
                    custom_id="days",
                    style=disnake.TextInputStyle.short,
                    required=False,
                    placeholder="30",
                    max_length=5,
                ),
                disnake.ui.TextInput(
                    label="Комментарий",
                    custom_id="comment",
                    style=disnake.TextInputStyle.short,
                    required=False,
                    placeholder="Плейсхолдер",
                    max_length=200,
                ),
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        raw_days = inter.text_values["days"].strip()

        body = {
            "userId" if _looks_like_guid(self.parent.query) else "userName": self.parent.query,
            "comment": inter.text_values["comment"].strip(),
        }

        if self.tier is not None:
            body["tier"] = self.tier
        else:
            body["overrides"] = {}

        if raw_days:
            if not raw_days.isdigit() or int(raw_days) <= 0:
                await inter.response.send_message(
                    embed=error_embed("Количество дней должно быть положительным числом."),
                    ephemeral=True,
                )
                return

            body["expiresInDays"] = int(raw_days)
        else:
            body["permanent"] = True

        await inter.response.defer()

        try:
            api = await build_api(inter.author)
            await api.create_grant(body)
            await self.parent.refresh(inter)
        except SponsorApiError as error:
            await inter.followup.send(embed=error_embed(str(error)), ephemeral=True)
            return

        await inter.followup.send(embed=ok_embed("Выдача создана."), ephemeral=True)


class RevokeSelect(disnake.ui.StringSelect):
    def __init__(self, parent: PlayerView, grants: list):
        self.parent = parent

        options = []

        for grant in grants[:25]:
            options.append(
                disnake.SelectOption(
                    label=f"#{grant['id']} · {grant.get('tierName') or 'без тира'}",
                    value=str(grant["id"]),
                    description=(grant.get("comment") or "")[:90] or None,
                )
            )

        super().__init__(placeholder="Отозвать выдачу...", options=options, row=1)

    async def callback(self, inter: disnake.MessageInteraction):
        grant_id = int(self.values[0])

        await inter.response.defer()

        try:
            api = await build_api(inter.author)
            await api.revoke_grant(grant_id)
            await self.parent.refresh(inter)
        except SponsorApiError as error:
            await inter.followup.send(embed=error_embed(str(error)), ephemeral=True)
            return

        await inter.followup.send(embed=ok_embed(f"Выдача #{grant_id} отозвана."), ephemeral=True)

class TierListView(BaseView):
    def __init__(self, owner_id: int, tiers: list):
        super().__init__(owner_id)

        self.tiers = tiers

        if tiers:
            self.add_item(TierSelect(self))

    @disnake.ui.button(label="Создать тир", emoji="➕", style=disnake.ButtonStyle.success, row=1)
    async def create_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(TierCreateModal(self.owner_id))

    @disnake.ui.button(label="Назад", emoji="◀", style=disnake.ButtonStyle.secondary, row=1)
    async def back_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.edit_message(embed=main_embed(), view=MainView(self.owner_id))


class TierSelect(disnake.ui.StringSelect):
    def __init__(self, parent: TierListView):
        self.parent = parent

        options = [
            disnake.SelectOption(
                label=tier.get("displayName") or tier["name"],
                value=tier["name"],
                description=f"`{tier['name']}` · приоритет {tier.get('priority', 0)}"[:100],
            )
            for tier in parent.tiers[:25]
        ]

        super().__init__(placeholder="Открыть тир...", options=options, row=0)

    async def callback(self, inter: disnake.MessageInteraction):
        tier = next((t for t in self.parent.tiers if t["name"] == self.values[0]), None)

        if tier is None:
            await inter.response.send_message(embed=error_embed("Обновите список."), ephemeral=True)
            return

        await inter.response.edit_message(
            embed=tier_embed(tier),
            view=TierDetailView(self.parent.owner_id, tier),
        )


class TierDetailView(BaseView):
    def __init__(self, owner_id: int, tier: dict):
        super().__init__(owner_id)
        self.tier = tier

    async def reload(self, inter: disnake.Interaction):
        api = await build_api(inter.author)
        tiers = await api.get_tiers()
        fresh = next((t for t in tiers if t["name"] == self.tier["name"]), None)

        if fresh is None:
            await inter.edit_original_response(embed=tier_list_embed(tiers), view=TierListView(self.owner_id, tiers))
            return

        self.tier = fresh
        await inter.edit_original_response(embed=tier_embed(fresh), view=TierDetailView(self.owner_id, fresh))

    @disnake.ui.button(label="Основное", emoji="✏", style=disnake.ButtonStyle.primary, row=0)
    async def main_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(TierMainModal(self))

    @disnake.ui.button(label="Флаги", emoji="🎚", style=disnake.ButtonStyle.primary, row=0)
    async def flags_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.edit_message(
            embed=tier_embed(self.tier),
            view=TierFlagsView(self.owner_id, self.tier),
        )

    @disnake.ui.button(label="Роли", emoji="🧑‍🚀", style=disnake.ButtonStyle.primary, row=0)
    async def roles_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(TierRolesModal(self))

    @disnake.ui.button(label="Кастомизация", emoji="🎨", style=disnake.ButtonStyle.primary, row=1)
    async def custom_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(TierCustomizationModal(self))

    @disnake.ui.button(label="Удалить", emoji="🗑", style=disnake.ButtonStyle.danger, row=1)
    async def delete_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.edit_message(
            embed=disnake.Embed(
                title=f"Удалить тир {self.tier['name']}?",
                description=(
                    "Выдачи на него **не удалятся**, но потеряют ссылку и останутся "
                    "работать только своей персональной надстройкой."
                ),
                color=0xED4245,
            ),
            view=TierDeleteConfirmView(self.owner_id, self.tier),
        )

    @disnake.ui.button(label="Назад", emoji="◀", style=disnake.ButtonStyle.secondary, row=1)
    async def back_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        try:
            api = await build_api(inter.author)
            tiers = await api.get_tiers()
        except SponsorApiError as error:
            await self.fail(inter, error)
            return

        await inter.response.edit_message(embed=tier_list_embed(tiers), view=TierListView(self.owner_id, tiers))


class TierDeleteConfirmView(BaseView):
    def __init__(self, owner_id: int, tier: dict):
        super().__init__(owner_id)
        self.tier = tier

    @disnake.ui.button(label="Удалить", style=disnake.ButtonStyle.danger)
    async def confirm(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.defer()

        try:
            api = await build_api(inter.author)
            await api.delete_tier(self.tier["name"])
            tiers = await api.get_tiers()
        except SponsorApiError as error:
            await self.fail(inter, error)
            return

        await inter.edit_original_response(embed=tier_list_embed(tiers), view=TierListView(self.owner_id, tiers))
        await inter.followup.send(embed=ok_embed(f"Тир {self.tier['name']} удалён."), ephemeral=True)

    @disnake.ui.button(label="Отмена", style=disnake.ButtonStyle.secondary)
    async def cancel(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.edit_message(embed=tier_embed(self.tier), view=TierDetailView(self.owner_id, self.tier))


class TierFlagsView(BaseView):
    def __init__(self, owner_id: int, tier: dict):
        super().__init__(owner_id)
        self.tier = tier

        for index, (label, key) in enumerate(BENEFIT_FLAGS):
            self.add_item(FlagButton(self, label, key, index // 3))

        self.add_item(FlagsBackButton(self))


class FlagButton(disnake.ui.Button):
    def __init__(self, parent: TierFlagsView, label: str, key: str, row: int):
        self.parent = parent
        self.key = key

        enabled = bool((parent.tier.get("benefits") or {}).get(key))

        super().__init__(
            label=label,
            emoji="✅" if enabled else "❌",
            style=disnake.ButtonStyle.success if enabled else disnake.ButtonStyle.secondary,
            row=row,
        )

    async def callback(self, inter: disnake.MessageInteraction):
        await inter.response.defer()

        benefits = dict(self.parent.tier.get("benefits") or {})
        benefits[self.key] = not benefits.get(self.key)

        try:
            api = await build_api(inter.author)
            await api.update_tier({"name": self.parent.tier["name"], "benefits": benefits})
            tiers = await api.get_tiers()
        except SponsorApiError as error:
            await self.parent.fail(inter, error)
            return

        fresh = next((t for t in tiers if t["name"] == self.parent.tier["name"]), self.parent.tier)

        await inter.edit_original_response(
            embed=tier_embed(fresh),
            view=TierFlagsView(self.parent.owner_id, fresh),
        )


class FlagsBackButton(disnake.ui.Button):
    def __init__(self, parent: TierFlagsView):
        self.parent = parent
        super().__init__(label="Назад", emoji="◀", style=disnake.ButtonStyle.secondary, row=2)

    async def callback(self, inter: disnake.MessageInteraction):
        await inter.response.edit_message(
            embed=tier_embed(self.parent.tier),
            view=TierDetailView(self.parent.owner_id, self.parent.tier),
        )

class TierCreateModal(disnake.ui.Modal):
    def __init__(self, owner_id: int):
        self.owner_id = owner_id

        super().__init__(
            title="Новый тир",
            custom_id="sponsor_tier_create",
            components=[
                disnake.ui.TextInput(label="ID", custom_id="name", placeholder="tier2", max_length=32),
                disnake.ui.TextInput(label="Название для игрока", custom_id="display", placeholder="Тир 2", max_length=64),
                disnake.ui.TextInput(
                    label="Приоритет",
                    custom_id="priority",
                    placeholder="20",
                    required=False,
                    max_length=5,
                ),
                disnake.ui.TextInput(
                    label="Описание",
                    custom_id="description",
                    style=disnake.TextInputStyle.paragraph,
                    required=False,
                    max_length=300,
                ),
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer()

        body = {
            "name": inter.text_values["name"].strip(),
            "displayName": inter.text_values["display"].strip(),
            "description": inter.text_values["description"].strip(),
            "priority": _parse_int(inter.text_values["priority"]),
        }

        try:
            api = await build_api(inter.author)
            await api.create_tier(body)
            tiers = await api.get_tiers()
        except SponsorApiError as error:
            await inter.followup.send(embed=error_embed(str(error)), ephemeral=True)
            return

        await inter.edit_original_response(embed=tier_list_embed(tiers), view=TierListView(self.owner_id, tiers))
        await inter.followup.send(embed=ok_embed(f"Тир {body['name']} создан."), ephemeral=True)


class TierMainModal(disnake.ui.Modal):
    def __init__(self, parent: TierDetailView):
        self.parent = parent
        tier = parent.tier

        super().__init__(
            title=f"Тир {tier['name']}",
            custom_id="sponsor_tier_main",
            components=[
                disnake.ui.TextInput(
                    label="Название для игрока",
                    custom_id="display",
                    value=tier.get("displayName") or "",
                    max_length=64,
                ),
                disnake.ui.TextInput(
                    label="Приоритет",
                    custom_id="priority",
                    value=str(tier.get("priority", 0)),
                    max_length=5,
                ),
                disnake.ui.TextInput(
                    label="Включён (да/нет)",
                    custom_id="enabled",
                    value="да" if tier.get("enabled", True) else "нет",
                    max_length=5,
                ),
                disnake.ui.TextInput(
                    label="Цвет ника hex (пусто = нет)",
                    custom_id="ooc",
                    value=(tier.get("benefits") or {}).get("oocColor") or "",
                    required=False,
                    max_length=9,
                ),
                disnake.ui.TextInput(
                    label="Доп. слотов персонажей",
                    custom_id="slots",
                    value=str((tier.get("benefits") or {}).get("extraCharacterSlots", 0)),
                    required=False,
                    max_length=3,
                ),
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer()

        benefits = dict(self.parent.tier.get("benefits") or {})
        ooc = inter.text_values["ooc"].strip()

        benefits["oocColor"] = ooc or None
        benefits["extraCharacterSlots"] = _parse_int(inter.text_values["slots"])

        body = {
            "name": self.parent.tier["name"],
            "displayName": inter.text_values["display"].strip(),
            "priority": _parse_int(inter.text_values["priority"]),
            "enabled": inter.text_values["enabled"].strip().lower() in ("да", "yes", "true", "1", "+"),
            "benefits": benefits,
        }

        await _apply_tier(self.parent, inter, body)


class TierRolesModal(disnake.ui.Modal):
    def __init__(self, parent: TierDetailView):
        self.parent = parent
        benefits = parent.tier.get("benefits") or {}
        bypass = benefits.get("roleBypass") or "None"

        super().__init__(
            title=f"Роли: {parent.tier['name']}",
            custom_id="sponsor_tier_roles",
            components=[
                disnake.ui.TextInput(
                    label="Обход: none / jobs / antags / jobs,antags",
                    custom_id="bypass",
                    value=bypass,
                    max_length=20,
                ),
                disnake.ui.TextInput(
                    label="Кроме департаментов (через запятую)",
                    custom_id="departments",
                    value=", ".join(benefits.get("excludedDepartments") or []),
                    required=False,
                    style=disnake.TextInputStyle.paragraph,
                    max_length=500,
                ),
                disnake.ui.TextInput(
                    label="Кроме работ (через запятую)",
                    custom_id="jobs",
                    value=", ".join(benefits.get("excludedJobs") or []),
                    required=False,
                    style=disnake.TextInputStyle.paragraph,
                    max_length=500,
                ),
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer()

        benefits = dict(self.parent.tier.get("benefits") or {})
        benefits["roleBypass"] = inter.text_values["bypass"].strip() or "None"
        benefits["excludedDepartments"] = _split(inter.text_values["departments"])
        benefits["excludedJobs"] = _split(inter.text_values["jobs"])

        await _apply_tier(self.parent, inter, {"name": self.parent.tier["name"], "benefits": benefits})


class TierCustomizationModal(disnake.ui.Modal):
    def __init__(self, parent: TierDetailView):
        self.parent = parent
        benefits = parent.tier.get("benefits") or {}

        super().__init__(
            title=f"Кастомизация: {parent.tier['name']}",
            custom_id="sponsor_tier_custom",
            components=[
                disnake.ui.TextInput(
                    label="Лодауты",
                    custom_id="loadouts",
                    value=", ".join(benefits.get("loadouts") or []),
                    required=False,
                    style=disnake.TextInputStyle.paragraph,
                    max_length=1000,
                ),
                disnake.ui.TextInput(
                    label="Маркинги",
                    custom_id="markings",
                    value=", ".join(benefits.get("markings") or []),
                    required=False,
                    style=disnake.TextInputStyle.paragraph,
                    max_length=1000,
                ),
                disnake.ui.TextInput(
                    label="Виды",
                    custom_id="species",
                    value=", ".join(benefits.get("species") or []),
                    required=False,
                    style=disnake.TextInputStyle.paragraph,
                    max_length=500,
                ),
                disnake.ui.TextInput(
                    label="Трейты",
                    custom_id="traits",
                    value=", ".join(benefits.get("traits") or []),
                    required=False,
                    style=disnake.TextInputStyle.paragraph,
                    max_length=500,
                ),
                disnake.ui.TextInput(
                    label="Цвета призрака hex (через запятую)",
                    custom_id="ghost",
                    value=", ".join(benefits.get("ghostColors") or []),
                    required=False,
                    max_length=300,
                ),
            ],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer()

        benefits = dict(self.parent.tier.get("benefits") or {})
        benefits["loadouts"] = _split(inter.text_values["loadouts"])
        benefits["markings"] = _split(inter.text_values["markings"])
        benefits["species"] = _split(inter.text_values["species"])
        benefits["traits"] = _split(inter.text_values["traits"])
        benefits["ghostColors"] = _split(inter.text_values["ghost"])

        await _apply_tier(self.parent, inter, {"name": self.parent.tier["name"], "benefits": benefits})


async def _apply_tier(parent: TierDetailView, inter: disnake.ModalInteraction, body: dict):
    try:
        api = await build_api(inter.author)
        await api.update_tier(body)
        await parent.reload(inter)
    except SponsorApiError as error:
        await inter.followup.send(embed=error_embed(str(error)), ephemeral=True)
        return

    await inter.followup.send(embed=ok_embed("Тир сохранён."), ephemeral=True)

def _split(raw: str) -> list:
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


def _parse_int(raw: str) -> int:
    try:
        return int((raw or "0").strip())
    except ValueError:
        return 0


def _looks_like_guid(value: str) -> bool:
    return len(value) == 36 and value.count("-") == 4


@has_any_role(*ROLE_ACCESS_SPONSOR)
@bot.command(name="sponsor_panel", aliases=["sp"])
async def sponsor_panel_command(ctx):
    await ctx.send(embed=main_embed(), view=MainView(ctx.author.id))
