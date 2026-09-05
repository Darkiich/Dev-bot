"""
Умная чистка канала.

    &purge 50 - последние 50 сообщений
    &purge 50 @user - только его сообщения
    &purge 100 ссылки - только сообщения со ссылками
    &purge 100 инвайты - приглашения на другие серверы
    &purge 50 боты - сообщения ботов
    &purge 50 файлы / картинки
    &purge 200 текст казино - всё, где встречается слово
"""

import asyncio
import io
import logging
import re

from datetime import timedelta

import disnake

from disnake.ext.commands import has_any_role

from bot_init import bot
from commands.moderation.mod_common import error_text, reply
from dataConfig import MOD_PURGE_CONFIRM_FROM, MOD_PURGE_LIMIT, MOD_PURGE_OLD_LIMIT, ROLE_ACCESS_MODERATOR
from mod_service import MENTIONS, announce_embed, find_target
from mod_rules import COLOR_INFO

logger = logging.getLogger(__name__)

USAGE = (
    "**Использование:** `&purge <сколько> [фильтр]`\n"
    "Фильтры: `@участник`, `ссылки`, `инвайты`, `картинки`, `файлы`, `боты`, "
    "`эмбеды`, `текст <слово>`.\n"
    f"За раз не больше {MOD_PURGE_LIMIT} сообщений, старше 14 дней Discord удалять не даёт.\n"
    "**Пример:** `&purge 100 текст казино`"
)

_LINK = re.compile(r"https?://", re.IGNORECASE)
_INVITE = re.compile(r"(discord\.(gg|io|me|li)|discord(app)?\.com/invite)/", re.IGNORECASE)

FILTERS = {
    "ссылки": ("сообщения со ссылками", lambda m, a: bool(_LINK.search(m.content))),
    "links": ("сообщения со ссылками", lambda m, a: bool(_LINK.search(m.content))),
    "инвайты": ("приглашения на серверы", lambda m, a: bool(_INVITE.search(m.content))),
    "invites": ("приглашения на серверы", lambda m, a: bool(_INVITE.search(m.content))),
    "картинки": ("картинки", lambda m, a: any(
        (att.content_type or "").startswith("image") for att in m.attachments
    )),
    "images": ("картинки", lambda m, a: any(
        (att.content_type or "").startswith("image") for att in m.attachments
    )),
    "файлы": ("вложения", lambda m, a: bool(m.attachments)),
    "files": ("вложения", lambda m, a: bool(m.attachments)),
    "боты": ("сообщения ботов", lambda m, a: m.author.bot),
    "bots": ("сообщения ботов", lambda m, a: m.author.bot),
    "эмбеды": ("эмбеды", lambda m, a: bool(m.embeds)),
    "embeds": ("эмбеды", lambda m, a: bool(m.embeds)),
    "текст": ("сообщения с текстом", lambda m, a: a.lower() in m.content.lower()),
    "text": ("сообщения с текстом", lambda m, a: a.lower() in m.content.lower()),
}


class Confirm(disnake.ui.View):
    """Подтверждение большой чистки. Жать может только тот, кто её затеял."""

    def __init__(self, author_id: int):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.value = None

    async def interaction_check(self, inter) -> bool:
        if inter.author.id != self.author_id:
            await inter.response.send_message("Это не твоя чистка.", ephemeral=True)
            return False
        return True

    @disnake.ui.button(label="Удалить", emoji="🧽", style=disnake.ButtonStyle.danger)
    async def confirm(self, button, inter):
        self.value = True
        self.stop()
        await inter.response.defer()

    @disnake.ui.button(label="Отмена", style=disnake.ButtonStyle.secondary)
    async def cancel(self, button, inter):
        self.value = False
        self.stop()
        await inter.response.edit_message(content="Отменено.", view=None)


def _archive(messages) -> disnake.File:
    """Текстовый слепок удалённого, чтобы чистку можно было объяснить."""
    lines = []
    for message in reversed(messages):
        stamp = message.created_at.strftime("%d.%m.%Y %H:%M")
        content = message.content or ""
        for attachment in message.attachments:
            content += f"\n[вложение] {attachment.filename} {attachment.url}"
        lines.append(f"[{stamp}] {message.author} ({message.author.id}): {content}")

    data = io.BytesIO("\n".join(lines).encode("utf-8"))
    return disnake.File(data, filename="purge.txt")


@bot.command(name="purge", aliases=["clear", "чистка"])
@has_any_role(*ROLE_ACCESS_MODERATOR)
async def purge_command(ctx, count: int, *, rest: str = ""):
    """Удаляет сообщения в канале с фильтром и подтверждением."""
    if not ctx.guild:
        await reply(ctx, "❌ Чистить можно только каналы сервера.")
        return

    if not ctx.channel.permissions_for(ctx.guild.me).manage_messages:
        await reply(ctx, "❌ У бота нет права «Управление сообщениями» в этом канале.")
        return

    if count < 1:
        await reply(ctx, "❌ Сколько сообщений чистить?\n\n" + USAGE)
        return

    count = min(count, MOD_PURGE_LIMIT)
    rest = rest.strip()
    label = "последние сообщения"
    check = None

    if rest:
        keyword, _, argument = rest.partition(" ")
        entry = FILTERS.get(keyword.lower())

        if entry:
            title, predicate = entry
            if keyword.lower() in ("текст", "text") and not argument.strip():
                await reply(ctx, "❌ Укажи слово: `&purge 100 текст казино`")
                return
            label = f"{title} {argument}".strip()
            check = lambda m: predicate(m, argument.strip())
        else:
            target, problem = await find_target(ctx, rest)
            if problem:
                await reply(ctx, f"❌ Не понял фильтр `{rest}`.\n\n{USAGE}")
                return
            label = f"сообщения {target}"
            check = lambda m: m.author.id == target.id

    # Сначала считаем, потом удаляем: модератор видит объём до того, как
    # что-то исчезнет, а не после
    matched = []
    async for message in ctx.channel.history(limit=count, before=ctx.message):
        if message.pinned:
            continue
        if check is None or check(message):
            matched.append(message)

    if not matched:
        await ctx.send("ℹ️ Под фильтр ничего не попало.", delete_after=15)
        return

    # Пачкой Discord удаляет только сообщения моложе двух недель. Всё, что
    # старше, идёт по одному и упирается в лимит запросов, поэтому старое
    # считаем отдельно и берём ограниченной горстью
    edge = disnake.utils.utcnow() - timedelta(days=13, hours=23)
    fresh = [m for m in matched if m.created_at > edge]
    old = [m for m in matched if m.created_at <= edge][:MOD_PURGE_OLD_LIMIT]
    skipped = len([m for m in matched if m.created_at <= edge]) - len(old)

    planned = len(fresh) + len(old)

    if planned >= MOD_PURGE_CONFIRM_FROM or old:
        question_text = f"🧽 Под удаление попадает **{planned}** сообщений ({label})."
        if old:
            question_text += (
                f"\nИз них {len(old)} старше двух недель - их Discord удаляет по одному, "
                f"это займёт около {len(old)} секунд."
            )
        if skipped:
            question_text += f"\nЕщё {skipped} старых пропущу, чтобы не ловить лимит запросов."
        question_text += "\nУдаляем?"

        view = Confirm(ctx.author.id)
        question = await ctx.send(question_text, view=view)
        await view.wait()

        if not view.value:
            if view.value is None:
                try:
                    await question.edit(content="⏳ Время вышло, ничего не удалено.", view=None)
                except disnake.HTTPException:
                    pass
            return

        try:
            await question.delete()
        except disnake.HTTPException:
            pass

    # Свежее уходит пачками по сотне: столько разрешает Discord за запрос
    removed = 0
    for start in range(0, len(fresh), 100):
        chunk = fresh[start:start + 100]
        try:
            await ctx.channel.delete_messages(chunk)
            removed += len(chunk)
        except (disnake.Forbidden, disnake.HTTPException) as e:
            logger.warning("Пачка не удалилась (%s), добиваю по одному", e)
            for message in chunk:
                try:
                    await message.delete()
                    removed += 1
                except disnake.HTTPException:
                    continue
                await asyncio.sleep(1)

    # Старое - по одному, с паузой: без неё Discord начинает придерживать
    # запросы и лог заваливается предупреждениями о лимите
    for message in old:
        try:
            await message.delete()
            removed += 1
        except disnake.HTTPException:
            continue
        await asyncio.sleep(1)

    logger.info(
        "Чистка: %d сообщений в #%s модератором %s (%s), фильтр: %s",
        removed, ctx.channel, ctx.author, ctx.author.id, label,
    )

    result = f"🧽 Удалено: {removed} ({label})"
    if skipped:
        result += f" · пропущено старых: {skipped}"

    await ctx.send(result, delete_after=15)

    embed = disnake.Embed(
        title="🧽 Чистка канала",
        color=COLOR_INFO,
        timestamp=disnake.utils.utcnow(),
    )
    embed.add_field(name="Канал", value=ctx.channel.mention, inline=True)
    embed.add_field(name="Модератор", value=ctx.author.mention, inline=True)
    embed.add_field(name="Удалено", value=str(removed), inline=True)
    embed.add_field(name="Фильтр", value=label, inline=False)
    if skipped:
        embed.add_field(
            name="Пропущено",
            value=f"{skipped} сообщений старше двух недель",
            inline=True,
        )

    await announce_embed(embed)

    if not await _send_archive(fresh + old):
        logger.warning("Архив чистки отправить не удалось")


async def _send_archive(messages) -> bool:
    """Кладёт слепок удалённого в лог-канал отдельным файлом."""
    from mod_service import log_channel

    channel = await log_channel()
    if channel is None:
        return False

    try:
        await channel.send(file=_archive(messages), allowed_mentions=MENTIONS)
        return True
    except (disnake.Forbidden, disnake.HTTPException) as e:
        logger.error("Не удалось приложить архив чистки: %s", e)
        return False


@purge_command.error
async def purge_command_error(ctx, error):
    text = error_text(error, USAGE)
    if text:
        await reply(ctx, text)
