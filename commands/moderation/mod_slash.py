"""
Слэш-команды модерации
"""

import logging

import disnake

from disnake.ext import commands

from bot_init import bot, mod_db
from commands.moderation.mod_panel_command import ModPanel, QuickActions
from dataConfig import MOD_DEFAULT_MUTE, MOD_SLASH_GUILD_IDS
from mod_rules import COLOR_INFO, split_duration
from mod_service import (
    build_case_detail,
    build_dossier,
    build_history_embed,
    is_moderator,
    is_senior,
    perform_ban,
    perform_kick,
    perform_mute,
    perform_note,
    perform_unban,
    perform_unmute,
    perform_warn,
    resolve_user,
    revoke_case,
)

logger = logging.getLogger(__name__)

GUILDS = MOD_SLASH_GUILD_IDS or None

# Discord прячет команды от тех, у кого нет права модерировать. Это только
# витрина: настоящая проверка идёт по ролям проекта внутри каждой команды
PERMISSIONS = disnake.Permissions(moderate_members=True)


async def guard(inter, senior: bool = False) -> bool:
    """Пускает только персонал. Отказ уходит скрытым сообщением."""
    if not is_moderator(inter.author):
        await inter.response.send_message(
            "❌ Модерация доступна только персоналу сервера.", ephemeral=True
        )
        return False

    if senior and not is_senior(inter.author):
        await inter.response.send_message(
            "❌ Это действие выполняет старший состав.", ephemeral=True
        )
        return False

    return True


@bot.slash_command(
    name="mod",
    description="Модерация Discord",
    guild_ids=GUILDS,
    default_member_permissions=PERMISSIONS,
    contexts=disnake.InteractionContextTypes(guild=True),
)
async def mod_slash(inter):
    """Группа команд, сама по себе не вызывается."""


@mod_slash.sub_command(name="warn", description="Выдать предупреждение")
async def slash_warn(
    inter,
    member: disnake.Member = commands.Param(description="Кого предупреждаем"),
    reason: str = commands.Param("", description="За что наказание"),
):
    if not await guard(inter):
        return

    await inter.response.defer(ephemeral=True)
    await inter.followup.send(
        await perform_warn(member, inter.author, reason, source="slash"), ephemeral=True
    )


@mod_slash.sub_command(name="mute", description="Выдать мут")
async def slash_mute(
    inter,
    member: disnake.Member = commands.Param(description="Кого мутим"),
    duration: str = commands.Param(MOD_DEFAULT_MUTE, description="Срок: 30, 10m, 2h, 3d, перм"),
    reason: str = commands.Param("", description="За что наказание"),
):
    if not await guard(inter):
        return

    await inter.response.defer(ephemeral=True)
    delta, extra, _ = split_duration(duration, MOD_DEFAULT_MUTE)

    await inter.followup.send(
        await perform_mute(member, inter.author, delta, reason or extra, source="slash"),
        ephemeral=True,
    )


@mod_slash.sub_command(name="unmute", description="Снять мут")
async def slash_unmute(
    inter,
    member: disnake.Member = commands.Param(description="С кого снимаем"),
    reason: str = commands.Param("", description="Комментарий"),
):
    if not await guard(inter):
        return

    await inter.response.defer(ephemeral=True)
    await inter.followup.send(await perform_unmute(member, inter.author, reason), ephemeral=True)


@mod_slash.sub_command(name="kick", description="Выгнать с сервера")
async def slash_kick(
    inter,
    member: disnake.Member = commands.Param(description="Кого выгоняем"),
    reason: str = commands.Param("", description="За что наказание"),
):
    if not await guard(inter):
        return

    await inter.response.defer(ephemeral=True)
    await inter.followup.send(
        await perform_kick(member, inter.author, reason, source="slash"), ephemeral=True
    )


@mod_slash.sub_command(name="ban", description="Забанить на сервере Discord")
async def slash_ban(
    inter,
    user: disnake.User = commands.Param(description="Кого баним, можно по ID"),
    duration: str = commands.Param("", description="Срок: 7d, 30d, перм. Пусто - навсегда"),
    reason: str = commands.Param("", description="За что наказание"),
    clean: int = commands.Param(0, description="Удалить его сообщения за N дней", ge=0, le=7),
):
    if not await guard(inter):
        return

    await inter.response.defer(ephemeral=True)

    target = inter.guild.get_member(user.id) or user
    delta, extra, _ = split_duration(duration)

    await inter.followup.send(
        await perform_ban(
            target, inter.author, delta, reason or extra,
            delete_seconds=clean * 86400, source="slash",
        ),
        ephemeral=True,
    )


@mod_slash.sub_command(name="unban", description="Снять бан по ID")
async def slash_unban(
    inter,
    user_id: str = commands.Param(description="ID пользователя"),
    reason: str = commands.Param("", description="Комментарий"),
):
    if not await guard(inter):
        return

    digits = "".join(ch for ch in user_id if ch.isdigit())
    if not digits:
        await inter.response.send_message("❌ Нужен числовой ID.", ephemeral=True)
        return

    await inter.response.defer(ephemeral=True)
    await inter.followup.send(await perform_unban(int(digits), inter.author, reason), ephemeral=True)


@mod_slash.sub_command(name="note", description="Скрытая заметка об участнике")
async def slash_note(
    inter,
    member: disnake.User = commands.Param(description="О ком заметка"),
    text: str = commands.Param(description="Текст заметки"),
):
    if not await guard(inter):
        return

    await inter.response.defer(ephemeral=True)
    target = inter.guild.get_member(member.id) or member
    await inter.followup.send(await perform_note(target, inter.author, text), ephemeral=True)


@mod_slash.sub_command(name="card", description="Досье участника с кнопками действий")
async def slash_card(
    inter,
    member: disnake.User = commands.Param(description="Чьё досье"),
):
    if not await guard(inter):
        return

    await inter.response.defer(ephemeral=True)

    target = inter.guild.get_member(member.id) or member
    embed = await build_dossier(target, inter.guild)

    await inter.followup.send(
        embed=embed, view=QuickActions(target, inter.author.id), ephemeral=True
    )


@mod_slash.sub_command(name="history", description="История наказаний участника")
async def slash_history(
    inter,
    member: disnake.User = commands.Param(description="Чья история"),
    page: int = commands.Param(1, description="Страница", ge=1),
):
    if not await guard(inter):
        return

    await inter.response.defer(ephemeral=True)

    counts = await mod_db.count_cases(member.id)
    total = sum(counts.values())
    rows = await mod_db.list_cases(member.id, limit=10, offset=(page - 1) * 10)

    embed = build_history_embed(member, rows, page, total, counts)
    if not rows:
        embed.description = "За участником ничего не числится."

    await inter.followup.send(embed=embed, ephemeral=True)


@mod_slash.sub_command(name="case", description="Показать кейс по номеру")
async def slash_case(
    inter,
    case_id: int = commands.Param(description="Номер кейса", ge=1),
):
    if not await guard(inter):
        return

    await inter.response.defer(ephemeral=True)

    row = await mod_db.get_case(case_id)
    if row is None:
        await inter.followup.send(f"❌ Кейс #{case_id} не найден.", ephemeral=True)
        return

    await inter.followup.send(embed=build_case_detail(row), ephemeral=True)


@mod_slash.sub_command(name="revoke", description="Снять наказание по номеру кейса")
async def slash_revoke(
    inter,
    case_id: int = commands.Param(description="Номер кейса", ge=1),
    reason: str = commands.Param("", description="Комментарий"),
):
    if not await guard(inter):
        return

    await inter.response.defer(ephemeral=True)
    await inter.followup.send(await revoke_case(case_id, inter.author, reason), ephemeral=True)


@mod_slash.sub_command(name="stats", description="Статистика модерации за период")
async def slash_stats(
    inter,
    days: int = commands.Param(30, description="За сколько дней", ge=1, le=365),
):
    if not await guard(inter):
        return

    await inter.response.defer(ephemeral=True)

    actors = await mod_db.actor_stats(days, inter.guild.id)
    totals = await mod_db.period_totals(days, inter.guild.id)

    embed = disnake.Embed(title=f"📊 Модерация за {days} дн.", color=COLOR_INFO)
    embed.description = " · ".join(
        f"**{action}**: {count}" for action, count in sorted(totals.items(), key=lambda p: -p[1])
    ) or "За период ничего не происходило."

    if actors:
        embed.add_field(
            name="Модераторы",
            value="\n".join(
                f"<@{row['actor_id']}> - {row['total']}" for row in actors[:10]
            ),
            inline=False,
        )

    await inter.followup.send(embed=embed, ephemeral=True)


@mod_slash.sub_command(name="panel", description="Выложить панель модерации в канал")
async def slash_panel(inter):
    if not await guard(inter):
        return

    embed = disnake.Embed(
        title="🛡️ Панель модерации",
        description="Кнопка → участник → причина. Ответ видит только нажавший.",
        color=COLOR_INFO,
    )

    # Сначала отвечаем Discord, потом кладём панель: на первый ответ
    # даётся три секунды, и тратить их на отправку сообщения незачем
    await inter.response.send_message("✅ Панель выложена.", ephemeral=True)
    await inter.channel.send(embed=embed, view=ModPanel())


@mod_slash.sub_command(name="purge", description="Почистить сообщения в канале")
async def slash_purge(
    inter,
    count: int = commands.Param(description="Сколько последних сообщений просмотреть", ge=1, le=500),
    member: disnake.User = commands.Param(None, description="Только сообщения этого участника"),
):
    if not await guard(inter):
        return

    if not inter.channel.permissions_for(inter.guild.me).manage_messages:
        await inter.response.send_message(
            "❌ У бота нет права «Управление сообщениями» в этом канале.", ephemeral=True
        )
        return

    await inter.response.defer(ephemeral=True)

    def check(message):
        if message.pinned:
            return False
        return member is None or message.author.id == member.id

    deleted = await inter.channel.purge(limit=count, check=check)

    logger.info(
        "Чистка через слэш: %d сообщений в #%s модератором %s (%s)",
        len(deleted), inter.channel, inter.author, inter.author.id,
    )

    await inter.followup.send(f"🧽 Удалено сообщений: **{len(deleted)}**.", ephemeral=True)
