"""
Мут ролью.

    &mute @user 2h Флуд
    &mute @user Оскорбления - срок по умолчанию из конфига
    &mute @user перм Обход бана
    &unmute @user Разобрались
    &muted - кто сейчас в муте
    &mute_setup - расставить права роли мута по каналам

Срок пишется первым словом после участника: 30 (минуты), 10m, 2h, 3d, 1w
или по-русски 10м, 2ч, 3д. Слово «перм» - мут без срока.
"""

import asyncio
import logging

import disnake

from disnake.ext.commands import has_any_role

from bot_init import bot, mod_db
from commands.moderation.mod_common import error_text, evidence_url, reply
from dataConfig import MOD_DEFAULT_MUTE, MUTED_ROLE_ID, ROLE_ACCESS_MODERATOR, ROLE_ACCESS_MODERATOR_SENIOR
from mod_rules import COLOR_INFO, COLOR_OK, DEFAULT_REASON, split_duration
from mod_service import duration_line, muted_role, perform_mute, perform_unmute

logger = logging.getLogger(__name__)

USAGE = (
    "**Использование:** `&mute <@участник> [срок] [причина]`\n"
    "Срок: `30` (минуты), `10m`, `2h`, `3d`, `1w`, `перм`. "
    f"Без срока берётся `{MOD_DEFAULT_MUTE}`.\n"
    "**Пример:** `&mute @Darkiich 2h Флуд в общем чате`"
)

UNMUTE_USAGE = "**Использование:** `&unmute <@участник> [комментарий]`"

# Права, которые роль мута отбирает в каждом канале
DENY = {
    "send_messages": False,
    "send_messages_in_threads": False,
    "create_public_threads": False,
    "create_private_threads": False,
    "add_reactions": False,
    "speak": False,
    "request_to_speak": False,
}


@bot.command(name="mute", aliases=["мут", "молчать"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def mute_command(ctx, member: disnake.Member, *, rest: str = ""):
    """Выдаёт роль мута на срок."""
    duration, reason, _ = split_duration(rest, MOD_DEFAULT_MUTE)

    text = await perform_mute(
        member, ctx.author, duration, reason, message_url=evidence_url(ctx)
    )
    await reply(ctx, text)


@mute_command.error
async def mute_command_error(ctx, error):
    text = error_text(error, USAGE)
    if text:
        await reply(ctx, text)


@bot.command(name="unmute", aliases=["размут"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def unmute_command(ctx, member: disnake.Member, *, reason: str = ""):
    """Снимает мут досрочно."""
    await reply(ctx, await perform_unmute(member, ctx.author, reason))


@unmute_command.error
async def unmute_command_error(ctx, error):
    text = error_text(error, UNMUTE_USAGE)
    if text:
        await reply(ctx, text)


@bot.command(name="muted", aliases=["муты"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def muted_command(ctx):
    """Кто сейчас в муте и сколько ему осталось."""
    role = muted_role(ctx.guild)
    embed = disnake.Embed(
        title="🔇 Сейчас в муте",
        color=COLOR_INFO,
        timestamp=disnake.utils.utcnow(),
    )

    members = list(role.members) if role else []
    if not members:
        embed.description = "Никого."
        await reply(ctx, "", embed)
        return

    lines = []
    for member in members[:25]:
        case = await mod_db.active_case(member.id, "mute", ctx.guild.id)
        if case:
            reason = (case["reason"] or DEFAULT_REASON)[:80]
            lines.append(
                f"{member.mention} · кейс #{case['id']}\n"
                f"{duration_line(case['expires_at'])}\n{reason}"
            )
        else:
            # Роль есть, кейса нет: выдали руками мимо бота
            lines.append(f"{member.mention}\n⚠️ роль выдана мимо бота, кейса нет")

    embed.description = "\n\n".join(lines)

    if len(members) > 25:
        embed.set_footer(text=f"Показаны 25 из {len(members)}")

    await reply(ctx, "", embed)


@bot.command(name="mute_setup")
@has_any_role(*ROLE_ACCESS_MODERATOR_SENIOR)
async def mute_setup_command(ctx):
    """
    Расставляет права роли мута по всем каналам.

    Без этого роль мута не значит ничего: Discord сам по себе не запрещает
    писать её обладателям. Команду достаточно прогнать один раз, а потом
    после создания новых каналов.
    """
    role = muted_role(ctx.guild)
    if role is None:
        await reply(
            ctx,
            f"❌ Роль с ID `{MUTED_ROLE_ID}` не найдена на сервере. "
            "Поправь `MUTED_ROLE_ID` в конфиге.",
        )
        return

    me = ctx.guild.me
    if not me.guild_permissions.manage_channels:
        await reply(ctx, "❌ У бота нет права «Управление каналами».")
        return

    if role >= me.top_role:
        await reply(
            ctx,
            f"❌ Роль «{role.name}» не ниже роли бота «{me.top_role.name}». "
            "Подними бота выше в списке ролей, иначе он не сможет её выдавать.",
        )
        return

    channels = ctx.guild.channels
    status = await ctx.send(f"⏳ Настраиваю права в {len(channels)} каналах...")

    done = skipped = failed = 0

    for index, channel in enumerate(channels, start=1):
        overwrite = channel.overwrites_for(role)
        need = {
            name: value for name, value in DENY.items()
            if hasattr(overwrite, name) and getattr(overwrite, name) is not value
        }

        if not need:
            skipped += 1
            continue

        for name, value in need.items():
            setattr(overwrite, name, value)

        try:
            await channel.set_permissions(role, overwrite=overwrite, reason="Настройка роли мута")
            done += 1
        except (disnake.Forbidden, disnake.HTTPException) as e:
            logger.warning("Не удалось настроить канал %s: %s", channel, e)
            failed += 1

        # Discord не любит шквал правок прав, идём с паузой
        await asyncio.sleep(0.4)

        if index % 15 == 0:
            try:
                await status.edit(content=f"⏳ Обработано {index} из {len(channels)}...")
            except disnake.HTTPException:
                pass

    embed = disnake.Embed(
        title="🔇 Роль мута настроена",
        description=f"{role.mention} больше не может писать, реагировать и говорить.",
        color=COLOR_OK,
    )
    embed.add_field(name="Настроено", value=str(done), inline=True)
    embed.add_field(name="Уже было", value=str(skipped), inline=True)
    embed.add_field(name="Не вышло", value=str(failed), inline=True)
    embed.set_footer(text="Прогоняй команду после создания новых каналов")

    logger.info(
        "Настройка роли мута на %s: настроено %d, пропущено %d, ошибок %d",
        ctx.guild.name, done, skipped, failed,
    )

    try:
        await status.edit(content=None, embed=embed)
    except disnake.HTTPException:
        await reply(ctx, "", embed)
