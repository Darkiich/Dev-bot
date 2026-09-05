"""
Каналы: замок и медленный режим.

    &lock - закрыть этот канал до ручного открытия
    &lock 30m Рейд - закрыть на полчаса, откроется само
    &lock #флудилка 2h Остыть
    &unlock [#канал]
    &slowmode 10s [#канал] - медленный режим
    &slowmode off
    &lockdown on Рейд - закрыть все текстовые каналы разом
    &lockdown off

Срок блокировки живёт в базе, а не в памяти бота: перезапуск во время рейда
не оставит сервер закрытым навсегда, канал всё равно откроется по времени.
"""

import asyncio
import logging

import disnake

from disnake.ext import commands
from disnake.ext.commands import has_any_role

from bot_init import bot, mod_db
from commands.moderation.mod_common import error_text, reply
from dataConfig import MOD_LOCK_MAX_MIN, ROLE_ACCESS_MODERATOR, ROLE_ACCESS_MODERATOR_SENIOR
from mod_rules import COLOR_INFO, COLOR_OK, COLOR_WARN, DEFAULT_REASON, action_title, looks_like_duration, parse_duration
from mod_service import announce_embed, audit_reason, revoke_case, set_channel_lock
from vacation_time import human_delta, ts

logger = logging.getLogger(__name__)

LOCK_USAGE = (
    "**Использование:** `&lock [#канал] [срок] [причина]`\n"
    "Без срока канал останется закрытым до `&unlock`.\n"
    "**Пример:** `&lock 30m Ждём, пока рейд закончится`"
)

SLOWMODE_USAGE = (
    "**Использование:** `&slowmode <срок или off> [#канал]`\n"
    "**Пример:** `&slowmode 10s` - одно сообщение в 10 секунд"
)

# Больше шести часов Discord в медленном режиме не разрешает
SLOWMODE_MAX = 21600


async def _split_channel(ctx, tokens: list):
    """Отделяет канал от остальных аргументов: он либо первый, либо текущий."""
    if tokens:
        first = tokens[0]
        if first.startswith("<#") or (first.isdigit() and len(first) >= 15):
            try:
                channel = await commands.TextChannelConverter().convert(ctx, first)
                return channel, tokens[1:]
            except commands.ChannelNotFound:
                pass

    return ctx.channel, tokens


@bot.command(name="lock", aliases=["замок", "закрыть"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def lock_command(ctx, *, rest: str = ""):
    """Закрывает канал для @everyone, при желании на срок."""
    channel, tokens = await _split_channel(ctx, rest.split())

    duration = None
    if tokens and looks_like_duration(tokens[0]):
        duration = parse_duration(tokens[0])
        tokens = tokens[1:]

    if duration is not None:
        limit = MOD_LOCK_MAX_MIN * 60
        if duration.total_seconds() > limit:
            await reply(
                ctx,
                f"❌ Максимальный срок автооткрытия - {MOD_LOCK_MAX_MIN} минут. "
                "Для более долгой блокировки закрой канал без срока.",
            )
            return

    reason = " ".join(tokens).strip() or DEFAULT_REASON

    active = await mod_db.active_case(channel.id, "lock", ctx.guild.id)
    if active:
        await reply(
            ctx,
            f"ℹ️ {channel.mention} уже закрыт, кейс #{active['id']}. "
            f"Открыть: `&unlock {channel.mention}`.",
        )
        return

    problem = await set_channel_lock(
        channel, True, reason=audit_reason(ctx.author, "lock", reason)
    )
    if problem:
        await reply(ctx, f"❌ {problem[0].upper() + problem[1:]}")
        return

    expires_at = disnake.utils.utcnow() + duration if duration else None

    row = await mod_db.add_case(
        guild_id=ctx.guild.id, action="lock",
        target_id=channel.id, target_name=f"#{channel.name}",
        actor_id=ctx.author.id, actor_name=str(ctx.author),
        reason=reason, expires_at=expires_at,
        channel_id=channel.id, source="command", active=True,
    )

    case_id = row["id"] if row else None

    embed = disnake.Embed(
        title=action_title("lock"),
        description=f"{channel.mention} закрыт для участников.",
        color=COLOR_WARN,
        timestamp=disnake.utils.utcnow(),
    )
    embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
    embed.add_field(
        name="Срок",
        value=f"{human_delta(duration)}, до {ts(expires_at, 'f')}" if duration else "до ручного открытия",
        inline=True,
    )
    embed.add_field(name="Причина", value=reason, inline=False)
    if case_id:
        embed.set_footer(text=f"Кейс #{case_id} · открыть: &unlock")

    await announce_embed(embed)

    logger.info(
        "Канал закрыт: #%s модератором %s (%s) на %s",
        channel, ctx.author, ctx.author.id,
        human_delta(duration) if duration else "неопределённый срок",
    )

    text = f"🔒 {channel.mention} закрыт"
    if duration:
        text += f" · до {ts(expires_at, 'f')}"
    if case_id:
        text += f" · кейс #{case_id}"

    await reply(ctx, text)


@lock_command.error
async def lock_command_error(ctx, error):
    text = error_text(error, LOCK_USAGE)
    if text:
        await reply(ctx, text)


@bot.command(name="unlock", aliases=["открыть"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def unlock_command(ctx, *, rest: str = ""):
    """Открывает канал обратно."""
    channel, tokens = await _split_channel(ctx, rest.split())
    reason = " ".join(tokens).strip()

    active = await mod_db.active_case(channel.id, "lock", ctx.guild.id)

    if active:
        # Через кейс: он же закроется в базе и перестанет ждать автооткрытия
        await reply(ctx, await revoke_case(active["id"], ctx.author, reason))
        return

    problem = await set_channel_lock(
        channel, False, reason=audit_reason(ctx.author, "unlock", reason)
    )
    if problem:
        await reply(ctx, f"❌ {problem[0].upper() + problem[1:]}")
        return

    await reply(ctx, f"🔓 {channel.mention} открыт")


@bot.command(name="slowmode", aliases=["slow", "медленно"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def slowmode_command(ctx, *, rest: str = ""):
    """Ставит или снимает медленный режим в канале."""
    tokens = rest.split()

    if not tokens:
        current = ctx.channel.slowmode_delay
        await reply(
            ctx,
            f"ℹ️ Сейчас в канале {'нет медленного режима' if not current else f'{current} сек между сообщениями'}.\n\n"
            + SLOWMODE_USAGE,
        )
        return

    value, rest_tokens = tokens[0], tokens[1:]
    channel, _ = await _split_channel(ctx, rest_tokens)

    if value.lower() in ("off", "выкл", "0", "нет"):
        seconds = 0
    else:
        duration = parse_duration(value)
        if duration is None:
            await reply(ctx, f"❌ Не понял срок `{value}`.\n\n{SLOWMODE_USAGE}")
            return
        seconds = int(duration.total_seconds())

        if seconds > SLOWMODE_MAX:
            await reply(ctx, "❌ Больше шести часов Discord не разрешает.")
            return

    try:
        await channel.edit(
            slowmode_delay=seconds,
            reason=audit_reason(ctx.author, "slowmode", f"{seconds} сек"),
        )
    except (disnake.Forbidden, disnake.HTTPException) as e:
        await reply(ctx, f"❌ Discord не дал поменять медленный режим: {e}")
        return

    logger.info("Медленный режим в #%s: %d сек, модератор %s", channel, seconds, ctx.author)

    if seconds:
        text = f"🐌 {channel.mention} - медленный режим, {seconds} сек"
    else:
        text = f"🚀 {channel.mention} - медленный режим снят"

    embed = disnake.Embed(
        title="🐌 Медленный режим",
        description=text,
        color=COLOR_INFO,
        timestamp=disnake.utils.utcnow(),
    )
    embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
    await announce_embed(embed)

    await reply(ctx, text)


class LockdownConfirm(disnake.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.value = None

    async def interaction_check(self, inter) -> bool:
        if inter.author.id != self.author_id:
            await inter.response.send_message("Это не твоя команда.", ephemeral=True)
            return False
        return True

    @disnake.ui.button(label="Закрыть сервер", emoji="🚨", style=disnake.ButtonStyle.danger)
    async def confirm(self, button, inter):
        self.value = True
        self.stop()
        await inter.response.defer()

    @disnake.ui.button(label="Отмена", style=disnake.ButtonStyle.secondary)
    async def cancel(self, button, inter):
        self.value = False
        self.stop()
        await inter.response.edit_message(content="Отменено.", view=None)


@bot.command(name="lockdown", aliases=["бункер_дс"])
@has_any_role(*ROLE_ACCESS_MODERATOR_SENIOR)
async def lockdown_command(ctx, mode: str = "", *, reason: str = ""):
    """
    Закрывает или открывает все текстовые каналы разом. Для рейда.
    Каждый канал получает свой кейс, поэтому `&lockdown off` вернёт всё
    ровно в то состояние, в котором оно было.
    """
    mode = mode.lower()

    if mode not in ("on", "off", "вкл", "выкл"):
        await reply(ctx, "**Использование:** `&lockdown on [причина]` / `&lockdown off`")
        return

    reason = reason.strip() or DEFAULT_REASON

    if mode in ("off", "выкл"):
        rows = await mod_db.active_locks(ctx.guild.id, source="lockdown")
        if not rows:
            await reply(ctx, "ℹ️ Сервер не в режиме блокировки.")
            return

        opened = 0
        for row in rows:
            channel = ctx.guild.get_channel(row["target_id"])
            if channel is not None:
                problem = await set_channel_lock(
                    channel, False, reason=audit_reason(ctx.author, "unlock", reason)
                )
                if problem is None:
                    opened += 1

            await mod_db.close_case(
                row["id"], kind="revoked", actor_id=ctx.author.id,
                actor_name=str(ctx.author), reason=reason,
            )
            await asyncio.sleep(0.3)

        embed = disnake.Embed(
            title="🚨 Блокировка сервера снята",
            description=f"Открыто каналов: **{opened}**",
            color=COLOR_OK,
            timestamp=disnake.utils.utcnow(),
        )
        embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
        await announce_embed(embed)

        logger.warning("Блокировка сервера снята модератором %s, открыто %d каналов", ctx.author, opened)
        await reply(ctx, f"🔓 Сервер открыт · каналов: {opened}")
        return

    targets = [
        channel for channel in ctx.guild.text_channels
        if channel.permissions_for(ctx.guild.me).manage_channels
    ]

    view = LockdownConfirm(ctx.author.id)
    question = await ctx.send(
        f"🚨 Закрыть **{len(targets)}** текстовых каналов? Писать сможет только персонал.",
        view=view,
    )
    await view.wait()

    if not view.value:
        if view.value is None:
            try:
                await question.edit(content="⏳ Время вышло, ничего не тронул.", view=None)
            except disnake.HTTPException:
                pass
        return

    try:
        await question.edit(content="⏳ Закрываю каналы...", view=None)
    except disnake.HTTPException:
        pass

    locked = 0
    for channel in targets:
        if await mod_db.active_case(channel.id, "lock", ctx.guild.id):
            continue

        problem = await set_channel_lock(
            channel, True, reason=audit_reason(ctx.author, "lock", reason)
        )
        if problem:
            continue

        await mod_db.add_case(
            guild_id=ctx.guild.id, action="lock",
            target_id=channel.id, target_name=f"#{channel.name}",
            actor_id=ctx.author.id, actor_name=str(ctx.author),
            reason=reason, channel_id=channel.id, source="lockdown", active=True,
        )
        locked += 1
        await asyncio.sleep(0.3)

    embed = disnake.Embed(
        title="🚨 Сервер закрыт",
        description=f"Закрыто каналов: **{locked}**\nВернуть всё: `&lockdown off`",
        color=0xED4245,
        timestamp=disnake.utils.utcnow(),
    )
    embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
    embed.add_field(name="Причина", value=reason, inline=False)
    await announce_embed(embed)

    logger.warning(
        "Блокировка сервера: %d каналов закрыто модератором %s (%s), причина: %r",
        locked, ctx.author, ctx.author.id, reason,
    )

    await reply(ctx, f"🚨 Сервер закрыт · каналов: {locked} · снять: `&lockdown off`")
