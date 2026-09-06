"""
Ручная модерация через интерфейс Discord попадает в тот же журнал, что и
команды бота
"""

import logging

import disnake

from bot_init import bot, mod_db
from dataConfig import (
    MOD_AUDIT_ACTIONS,
    MOD_AUDIT_ENABLED,
    MOD_GUILD_ID,
    MUTED_ROLE_ID,
)
from mod_service import announce_case, open_case
from mod_rules import action_name

logger = logging.getLogger(__name__)

A = disnake.AuditLogAction

# Действия, у которых цель - сам участник, и разбирать нечего
SIMPLE = {
    A.ban: "ban",
    A.unban: "unban",
    A.kick: "kick",
}

# Ручное снятие наказания закрывает кейс, который бот считает действующим.
# Тайм-аута тут нет намеренно: им целиком распоряжается Discord, снимает
# по сроку сам и о снятии не сообщает. Мы такие кейсы держим записями,
# а не действующими наказаниями, закрывать нечего
CLOSES = {"unban": "ban", "unmute": "mute"}

class _Subject:
    """
    Цель действия, когда это не участник, а канал или сервер
    """

    __slots__ = ("id", "mention", "display_avatar", "_label")

    def __init__(self, obj, label: str):
        self.id = getattr(obj, "id", 0) or 0
        self.mention = getattr(obj, "mention", label)
        self.display_avatar = type("_Avatar", (), {"url": None})()
        self._label = label

    def __str__(self):
        return self._label


def _roles(diff) -> list:
    return [role for role in (getattr(diff, "roles", None) or [])]


def _member_update(entry):
    """
    Одно нажатие в интерфейсе меняет одно поле, но событие приходит общее.
    Смотрим, что именно поменялось, и выдаём столько записей, сколько
    полей тронули.
    """
    before, after = entry.before, entry.after

    if hasattr(after, "timeout"):
        if after.timeout is not None:
            yield "timeout", "", after.timeout
        else:
            yield "untimeout", "", None

    if hasattr(after, "nick"):
        was = getattr(before, "nick", None) or "без ника"
        now = after.nick or "без ника"
        yield "nick", f"{was} -> {now}", None

    if hasattr(after, "mute"):
        yield ("voice_mute" if after.mute else "voice_unmute"), "", None

    if hasattr(after, "deaf"):
        yield ("voice_deaf" if after.deaf else "voice_undeaf"), "", None


def _role_update(entry):
    """Из ролей смотрим только роль мута, остальные к модерации не относятся."""
    if not MUTED_ROLE_ID:
        return

    if any(role.id == MUTED_ROLE_ID for role in _roles(entry.after)):
        yield "mute", "роль мута выдана вручную", None

    if any(role.id == MUTED_ROLE_ID for role in _roles(entry.before)):
        yield "unmute", "роль мута снята вручную", None


def decode(entry):
    """
    Запись аудит-лога -> список (действие, пояснение, срок).
    """
    action = entry.action
    extra = entry.extra

    if action in SIMPLE:
        yield SIMPLE[action], "", None
        return

    if action is A.member_update:
        yield from _member_update(entry)
        return

    if action is A.member_role_update:
        yield from _role_update(entry)
        return

    if action is A.member_prune:
        days = getattr(extra, "delete_member_days", "?")
        removed = getattr(extra, "members_removed", "?")
        yield "prune", f"удалено {removed}, неактивных дольше {days} дн", None
        return

    if action is A.message_delete:
        channel = getattr(extra, "channel", None)
        count = getattr(extra, "count", "?")
        where = getattr(channel, "mention", "канал неизвестен")
        yield "purge", f"{count} сообщений в {where}", None
        return

    if action is A.message_bulk_delete:
        yield "purge", f"{getattr(extra, 'count', '?')} сообщений", None
        return

    if action is A.member_disconnect:
        yield "voice_kick", f"{getattr(extra, 'count', '?')} участников", None
        return

    if action is A.member_move:
        channel = getattr(extra, "channel", None)
        where = getattr(channel, "mention", "канал неизвестен")
        yield "voice_move", f"{getattr(extra, 'count', '?')} участников в {where}", None


def subject(entry, action: str):
    """
    Кого касается запись.
    """
    target = entry.target

    if action == "prune" or target is None:
        return _Subject(entry.guild, str(entry.guild) if entry.guild else "сервер")

    if action == "purge" and not isinstance(target, (disnake.Member, disnake.User)):
        return _Subject(target, f"#{getattr(target, 'name', 'канал')}")

    return target


def build_reason(entry, note: str) -> str:
    """Причина из Discord плюс то, что бот разобрал сам."""
    parts = [part for part in ((entry.reason or "").strip(), note.strip()) if part]
    return " · ".join(parts) or "Причина не указана"


async def close_matching(entry, action: str, actor):
    """
    Ручное снятие закрывает кейс, который бот считает действующим
    """
    parent = CLOSES.get(action)
    if not parent:
        return None

    target = entry.target
    if target is None:
        return None

    row = await mod_db.active_case(target.id, parent, entry.guild.id if entry.guild else None)
    if row is None:
        return None

    closed = await mod_db.close_case(
        row["id"], kind="revoked", actor_id=actor.id, actor_name=str(actor),
        reason="Снято вручную через Discord",
    )

    if closed is not None:
        logger.info(
            "Кейс #%s закрыт: %s снят вручную модератором %s (%s)",
            row["id"], action_name(parent), actor, actor.id,
        )

    return closed


async def record(entry, action: str, note: str, expires_at):
    actor = entry.user
    target = subject(entry, action)

    await close_matching(entry, action, actor)

    case = await open_case(
        guild=entry.guild,
        action=action,
        target=target,
        actor=actor,
        reason=build_reason(entry, note),
        expires_at=expires_at,
        source="discord",
    )

    await announce_case(case)

    logger.info(
        "Ручное действие из Discord: %s над %s модератором %s (%s), кейс %s",
        action, target, actor, actor.id, case.get("id"),
    )


@bot.listen("on_audit_log_entry_create")
async def audit_router(entry: disnake.AuditLogEntry):
    """Ловит записи аудит-лога Discord и превращает их в кейсы."""
    if not MOD_AUDIT_ENABLED:
        return

    guild = entry.guild
    if guild is None or (MOD_GUILD_ID and guild.id != MOD_GUILD_ID):
        return

    actor = entry.user

    # Боты сюда не попадают
    if actor is None or actor.bot:
        return

    try:
        for action, note, expires_at in decode(entry):
            if action in MOD_AUDIT_ACTIONS:
                await record(entry, action, note, expires_at)
    except Exception:
        logger.exception("Не удалось разобрать запись аудит-лога %s", entry.action)
