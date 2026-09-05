"""
Ядро модерации Discord: проверки, действие, кейс в базе, карточка в лог-канал
и письмо нарушителю.

Команды с префиксом, слэш-команды, кнопки панели и фоновая задача зовут одни
и те же perform_*. Логика ровно одна, поэтому мут из панели ничем не отличается
от мута из команды: тот же номер кейса, та же запись в истории, то же письмо.

Каждое действие получает номер кейса.
"""

import logging

from datetime import timedelta

import disnake

from disnake.ext import commands

from bot_init import bot, mod_db
from dataConfig import (
    MOD_DM_NOTIFY,
    MOD_GUILD_ID,
    MOD_IMMUNE_ROLES,
    MOD_LOG_CHANNEL_ID,
    MOD_WARN_EXPIRE_DAYS,
    MUTED_ROLE_ID,
    ROLE_ACCESS_MODERATOR,
    ROLE_ACCESS_MODERATOR_SENIOR,
)
from mod_rules import (
    COLOR_BAD,
    COLOR_INFO,
    COLOR_OK,
    DEFAULT_REASON,
    action_color,
    action_name,
    action_notifies,
    action_title,
    escalation_for,
    term_text,
    parse_duration,
)
from vacation_time import human_delta, plural, ts

logger = logging.getLogger(__name__)

# Роли не пингуем, людей можно
MENTIONS = disnake.AllowedMentions(everyone=False, roles=False, users=True)

# Действия, которые остаются висеть и которые можно снять
LASTING = ("warn", "mute", "ban")


#  Доступ
def _role_ids(user) -> set:
    return {role.id for role in getattr(user, "roles", [])}


def is_moderator(user) -> bool:
    return bool(_role_ids(user) & set(ROLE_ACCESS_MODERATOR))


def is_senior(user) -> bool:
    """Старший состав: чужие кейсы, закрытие сервера, настройка роли мута."""
    return bool(_role_ids(user) & set(ROLE_ACCESS_MODERATOR_SENIOR))


def moderation_guild():
    """Сервер, на котором работает модерация."""
    if MOD_GUILD_ID:
        guild = bot.get_guild(MOD_GUILD_ID)
        if guild is not None:
            return guild

    channel = bot.get_channel(MOD_LOG_CHANNEL_ID)
    if channel is not None:
        return channel.guild

    return bot.guilds[0] if bot.guilds else None


async def resolve_member(guild, user_id):
    """Участник сервера или None, если он вышел."""
    if guild is None:
        return None

    member = guild.get_member(int(user_id))
    if member is not None:
        return member

    try:
        return await guild.fetch_member(int(user_id))
    except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException):
        return None


async def resolve_user(user_id):
    """Пользователь Discord даже вне сервера: нужен для банов по ID."""
    user = bot.get_user(int(user_id))
    if user is not None:
        return user

    try:
        return await bot.fetch_user(int(user_id))
    except (disnake.NotFound, disnake.HTTPException):
        return None


def muted_role(guild):
    return guild.get_role(MUTED_ROLE_ID) if guild and MUTED_ROLE_ID else None


#  Проверки перед действием
def target_problem(actor, target, action: str) -> str | None:
    """
    Кого этому модератору трогать нельзя. None - можно.

    Право на саму команду даёт роль, а это про цель: себя не наказываем,
    ботов не трогаем, выше себя не лезем. Старшинство считается по порядку
    ролей на сервере - так же, как это делает сам Discord.
    """
    if getattr(target, "bot", False):
        return "Ботов модерировать нельзя."

    if target.id == getattr(bot.user, "id", 0):
        return "Меня наказывать нельзя."

    if actor.id == target.id:
        return "Себя наказывать нельзя."

    guild = getattr(target, "guild", None) or moderation_guild()
    if guild is None:
        return None

    if guild.owner_id == target.id:
        return "Владельца сервера трогать нельзя."

    # Участника вне сервера проверять по ролям нечем: у него их просто нет
    if not isinstance(target, disnake.Member):
        return None

    if _role_ids(target) & set(MOD_IMMUNE_ROLES):
        return f"У {target.mention} иммунитет к модерации."

    if actor.id == guild.owner_id:
        return None

    author = guild.get_member(actor.id) or actor
    top = getattr(author, "top_role", None)
    if top is None:
        return None

    if target.top_role >= top:
        return f"У {target.mention} роль «{target.top_role.name}» не ниже твоей."

    return None


def bot_problem(guild, action: str) -> str | None:
    """Чего не хватает самому боту. None - всё на месте."""
    me = guild.me if guild else None
    if me is None:
        return "бот не найден среди участников сервера"

    rights = me.guild_permissions
    need = {
        "mute": (rights.manage_roles, "«Управление ролями»"),
        "unmute": (rights.manage_roles, "«Управление ролями»"),
        "kick": (rights.kick_members, "«Выгонять участников»"),
        "ban": (rights.ban_members, "«Банить участников»"),
        "unban": (rights.ban_members, "«Банить участников»"),
        "softban": (rights.ban_members, "«Банить участников»"),
    }

    if action in need:
        ok, name = need[action]
        if not ok:
            return f"у бота нет права {name}"

    if action in ("mute", "unmute"):
        guild_role = muted_role(guild)
        if guild_role is None:
            return (
                f"роль мута с ID {MUTED_ROLE_ID} не найдена на сервере, "
                "проверь MUTED_ROLE_ID в конфиге"
            )
        if guild_role >= me.top_role:
            return (
                f"роль «{guild_role.name}» не ниже роли бота «{me.top_role.name}», "
                "подними бота выше в списке ролей"
            )

    return None


def hierarchy_problem(guild, target) -> str | None:
    """Дотянется ли бот до участника. У Discord тут своя иерархия ролей."""
    if not isinstance(target, disnake.Member):
        return None

    me = guild.me
    if me is None:
        return None

    if target.top_role >= me.top_role:
        return (
            f"роль «{target.top_role.name}» не ниже роли бота, "
            "Discord не даст мне его тронуть"
        )

    return None


def audit_reason(actor, action: str, reason: str, case_id=None) -> str:
    """Строка для журнала аудита Discord, у него лимит 512 символов."""
    head = action_name(action)
    if case_id:
        head += f" #{case_id}"

    text = f"{head}, оформил {actor}"
    if reason and reason != DEFAULT_REASON:
        text += f". {reason}"

    return text[:500]


#  Кейс
def warn_expiry():
    """Когда сгорит выданный сейчас варн. None - варны вечные."""
    if not MOD_WARN_EXPIRE_DAYS:
        return None
    return disnake.utils.utcnow() + timedelta(days=MOD_WARN_EXPIRE_DAYS)


async def open_case(guild, action, target, actor, reason="", expires_at=None,
                    parent_id=None, source="command", message_url=None,
                    channel_id=None) -> dict:
    """
    Заводит кейс в базе и возвращает его словарём.

    Словарь, а не строка из базы, специально: если Postgres лежит, наказание
    всё равно выдаётся и попадает в лог-канал, просто без номера. Модерация
    не должна останавливаться из-за базы.
    """
    reason = (reason or "").strip() or DEFAULT_REASON
    active = action in LASTING

    row = await mod_db.add_case(
        guild_id=guild.id if guild else 0,
        action=action,
        target_id=target.id,
        target_name=str(target),
        actor_id=actor.id,
        actor_name=str(actor),
        reason=reason,
        expires_at=expires_at,
        channel_id=channel_id,
        message_url=message_url,
        parent_id=parent_id,
        source=source,
        active=active,
    )

    return {
        "id": row["id"] if row else None,
        "action": action,
        "target": target,
        "target_id": target.id,
        "target_name": str(target),
        "actor": actor,
        "actor_id": actor.id,
        "actor_name": str(actor),
        "reason": reason,
        "expires_at": expires_at,
        "parent_id": parent_id,
        "source": source,
        "message_url": message_url,
        "guild": guild,
        "db_ok": row is not None,
    }


def case_label(case: dict) -> str:
    return f"#{case['id']}" if case.get("id") else "без номера"


def duration_line(expires_at) -> str:
    if expires_at is None:
        return "**Навсегда**"

    left = expires_at - disnake.utils.utcnow()
    if left.total_seconds() <= 0:
        return "истекло"

    # Округляем до минуты: иначе выданный только что мут на два часа
    # показывается как «1 час», потому что пара секунд уже прошла
    rounded = timedelta(seconds=round(left.total_seconds() / 60) * 60) or left

    return f"{human_delta(rounded)}, до {ts(expires_at, 'f')} ({ts(expires_at, 'R')})"


def build_case_embed(case: dict, warns: int = None) -> disnake.Embed:
    """Карточка кейса для лог-канала."""
    action = case["action"]
    target = case.get("target")

    embed = disnake.Embed(
        title=f"{action_title(action)} · кейс {case_label(case)}",
        color=action_color(action),
        timestamp=disnake.utils.utcnow(),
    )

    who = target.mention if target is not None else f"<@{case['target_id']}>"
    embed.add_field(name="Кто", value=f"{who}\n`{case['target_name']}`", inline=True)
    embed.add_field(
        name="Модератор",
        value=f"<@{case['actor_id']}>\n`{case['actor_name']}`",
        inline=True,
    )

    if action in ("mute", "ban", "warn"):
        embed.add_field(name="Срок", value=duration_line(case.get("expires_at")), inline=True)

    embed.add_field(name="Причина", value=case["reason"][:1000], inline=False)

    if case.get("message_url"):
        embed.add_field(name="Где", value=f"[сообщение]({case['message_url']})", inline=True)

    if warns:
        embed.add_field(
            name="Активных варнов",
            value=f"{warns} {plural(warns, ('штука', 'штуки', 'штук'))}",
            inline=True,
        )

    if case.get("parent_id"):
        embed.add_field(name="Из кейса", value=f"#{case['parent_id']}", inline=True)

    if target is not None:
        embed.set_thumbnail(url=target.display_avatar.url)

    footer = f"ID участника: {case['target_id']}"
    if case.get("source") == "auto":
        footer += " · выдано автоматически"
    embed.set_footer(text=footer)

    return embed


def case_buttons(case: dict) -> list:
    """Кнопки под карточкой. Переживают перезапуск: вся суть в custom_id."""
    case_id = case.get("id")
    if not case_id:
        return []

    buttons = []

    if case["action"] in LASTING:
        buttons.append(
            disnake.ui.Button(
                label="Снять",
                emoji="↩️",
                style=disnake.ButtonStyle.danger,
                custom_id=f"mod_case:revoke:{case_id}",
            )
        )

    buttons.append(
        disnake.ui.Button(
            label="Причина",
            emoji="✏️",
            style=disnake.ButtonStyle.secondary,
            custom_id=f"mod_case:reason:{case_id}",
        )
    )
    buttons.append(
        disnake.ui.Button(
            label="Досье",
            emoji="🗂️",
            style=disnake.ButtonStyle.secondary,
            custom_id=f"mod_case:card:{case_id}",
        )
    )

    return buttons


async def log_channel():
    if not MOD_LOG_CHANNEL_ID:
        return None

    channel = bot.get_channel(MOD_LOG_CHANNEL_ID)
    if channel is not None:
        return channel

    try:
        return await bot.fetch_channel(MOD_LOG_CHANNEL_ID)
    except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException) as e:
        logger.error("Лог-канал модерации %s недоступен: %s", MOD_LOG_CHANNEL_ID, e)
        return None


async def announce_case(case: dict, warns: int = None) -> bool:
    """Кладёт карточку в лог-канал и запоминает её, чтобы потом обновить."""
    channel = await log_channel()
    if channel is None:
        return False

    try:
        message = await channel.send(
            embed=build_case_embed(case, warns),
            components=case_buttons(case),
            allowed_mentions=MENTIONS,
        )
    except (disnake.Forbidden, disnake.HTTPException) as e:
        logger.error("Не удалось отправить карточку кейса: %s", e)
        return False

    if case.get("id"):
        await mod_db.set_log_message(case["id"], message.id)

    return True


async def announce_embed(embed: disnake.Embed) -> bool:
    """Простое сообщение в лог-канал: чистки, блокировки, автоснятия."""
    channel = await log_channel()
    if channel is None:
        return False

    try:
        await channel.send(embed=embed, allowed_mentions=MENTIONS)
        return True
    except (disnake.Forbidden, disnake.HTTPException) as e:
        logger.error("Не удалось написать в лог-канал модерации: %s", e)
        return False


async def refresh_card(row) -> None:
    """Перерисовывает карточку закрытого кейса: снято, кем и почему."""
    if not row or not row["log_message_id"]:
        return

    channel = await log_channel()
    if channel is None:
        return

    try:
        message = await channel.fetch_message(row["log_message_id"])
    except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException):
        return

    if not message.embeds:
        return

    embed = message.embeds[0]
    embed.color = 0x4E5058

    closed_by = f"<@{row['closed_by']}>" if row["closed_by"] else "автоматически"
    embed.add_field(
        name="Снято",
        value=f"{closed_by}\n{row['close_reason'] or 'без комментария'}",
        inline=False,
    )

    try:
        await message.edit(embed=embed, components=[])
    except (disnake.Forbidden, disnake.HTTPException):
        pass


#  Письмо нарушителю
def build_dm_embed(case: dict, guild) -> disnake.Embed:
    action = case["action"]

    embed = disnake.Embed(
        title=action_title(action),
        description=f"Сервер **{guild.name}**",
        color=action_color(action),
        timestamp=disnake.utils.utcnow(),
    )
    embed.add_field(name="Причина", value=case["reason"][:1000], inline=False)

    if action in ("mute", "ban", "warn"):
        embed.add_field(name="Срок", value=duration_line(case.get("expires_at")), inline=False)

    if case.get("id"):
        embed.set_footer(text=f"Кейс #{case['id']}")

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    return embed


async def notify_target(case: dict, guild) -> bool:
    """
    Пишет нарушителю в личку: что выдали, за что и на сколько. Делать это
    надо до кика и бана - после них общих серверов не остаётся и Discord
    личку уже не пропустит.

    Выключается целиком через MOD_DM_NOTIFY в конфиге.
    """
    if not MOD_DM_NOTIFY or not action_notifies(case["action"]):
        return False

    target = case.get("target")
    if target is None or getattr(target, "bot", False):
        return False

    try:
        await target.send(embed=build_dm_embed(case, guild))
        return True
    except (disnake.Forbidden, disnake.HTTPException):
        return False


#  Сборка ответа модератору
def result_lines(head: str, case: dict, notes=(), announced=True) -> str:
    """
    Ответ модератору: одна строка результата плюс только то, что сломалось.

    Закрытая личка нарушителя не сломанное, поэтому о ней не пишем: модератор
    ничего с этим не сделает, а лишняя строка каждый раз мозолит глаза.
    """
    lines = [head]

    for note in dict.fromkeys(n for n in notes if n):
        lines.append(f"⚠️ {note}")

    if case is not None and not case.get("db_ok"):
        lines.append("⚠️ Кейс не записан в базу.")

    if not announced:
        lines.append("⚠️ Карточка не ушла в лог-канал.")

    return "\n".join(lines)


#  Действия модерации
#  Каждое возвращает готовый текст ответа: его печатает и команда, и кнопка.
async def perform_warn(target, actor, reason="", source="command", message_url=None) -> str:
    """Варн. Если он оказался N-м по счёту, следом применяются меры наказания."""
    guild = target.guild

    problem = target_problem(actor, target, "warn")
    if problem:
        return f"❌ {problem}"

    case = await open_case(
        guild, "warn", target, actor, reason,
        expires_at=warn_expiry(), source=source, message_url=message_url,
    )

    await notify_target(case, guild)
    warns = len(await mod_db.active_warns(target.id, guild.id))
    announced = await announce_case(case, warns)

    logger.info(
        "Варн: %s (%s) от %s (%s), причина: %r, активных варнов: %d",
        target, target.id, actor, actor.id, case["reason"], warns,
    )

    head = f"⚠️ {target.mention} - предупреждение · кейс {case_label(case)} · варнов: {warns}"
    text = result_lines(head, case, [], announced)

    step = escalation_for(warns) if warns else None
    if step:
        text += "\n" + await _escalate(target, actor, step, warns, case)

    return text


async def _escalate(target, actor, step, warns: int, parent: dict) -> str:
    """Автоматическое наказание за набранные варны."""
    action, duration_text = step
    duration = parse_duration(duration_text) if duration_text else None

    reason = f"Меры наказания: {warns}-й активный варн"
    if parent.get("id"):
        reason += f" (кейс #{parent['id']})"

    logger.info(
        "Эскалация: %s (%s) -> %s за %d варнов", target, target.id, action, warns,
    )

    if action == "mute":
        return await perform_mute(
            target, actor, duration, reason, source="auto", parent_id=parent.get("id")
        )

    if action == "ban":
        return await perform_ban(
            target, actor, duration, reason, source="auto", parent_id=parent.get("id")
        )

    if action == "kick":
        return await perform_kick(
            target, actor, reason, source="auto", parent_id=parent.get("id")
        )

    return f"⚠️ В мерах наказания указано неизвестное действие «{action}»."


async def perform_mute(target, actor, duration=None, reason="", source="command",
                       parent_id=None, message_url=None) -> str:
    """Выдаёт роль мута. duration=None - мут без срока."""
    guild = target.guild

    problem = (
        target_problem(actor, target, "mute")
        or bot_problem(guild, "mute")
        or hierarchy_problem(guild, target)
    )
    if problem:
        return f"❌ {problem[0].upper() + problem[1:]}"

    role = muted_role(guild)
    notes = []

    # Старый мут закрываем, иначе фоновая задача снимет роль по его сроку
    previous = await mod_db.active_case(target.id, "mute", guild.id)
    if previous:
        await mod_db.close_case(
            previous["id"], kind="replaced", actor_id=actor.id,
            actor_name=str(actor), reason="Выдан новый мут",
        )
        notes.append(f"Прошлый мут #{previous['id']} заменён.")

    expires_at = disnake.utils.utcnow() + duration if duration else None

    case = await open_case(
        guild, "mute", target, actor, reason, expires_at=expires_at,
        parent_id=parent_id, source=source, message_url=message_url,
    )

    await notify_target(case, guild)

    try:
        await target.add_roles(role, reason=audit_reason(actor, "mute", case["reason"], case["id"]))
    except (disnake.Forbidden, disnake.HTTPException) as e:
        if case.get("id"):
            await mod_db.close_case(
                case["id"], kind="revoked", actor_id=actor.id,
                actor_name=str(actor), reason="Роль выдать не удалось",
            )
        logger.error("Не удалось выдать роль мута %s: %s", target, e)
        return f"❌ Discord не дал выдать роль мута: {e}"

    announced = await announce_case(case)

    logger.info(
        "Мут: %s (%s) от %s (%s) на %s, причина: %r",
        target, target.id, actor, actor.id,
        human_delta(duration) if duration else "навсегда", case["reason"],
    )

    term = f"на {human_delta(duration)}" if duration else "без срока"
    head = f"🔇 {target.mention} - мут {term} · кейс {case_label(case)}"
    if expires_at:
        head += f" · до {ts(expires_at, 'f')}"

    return result_lines(head, case, notes, announced)


async def perform_unmute(target, actor, reason="") -> str:
    """Снимает роль мута и закрывает активный кейс."""
    guild = target.guild

    problem = bot_problem(guild, "unmute")
    if problem:
        return f"❌ {problem[0].upper() + problem[1:]}"

    role = muted_role(guild)
    active = await mod_db.active_case(target.id, "mute", guild.id)

    if role not in target.roles and not active:
        return f"ℹ️ {target.mention} и так не в муте."

    notes = []
    if role in target.roles:
        try:
            await target.remove_roles(role, reason=audit_reason(actor, "unmute", reason))
        except (disnake.Forbidden, disnake.HTTPException) as e:
            return f"❌ Discord не дал снять роль мута: {e}"

    if active:
        closed = await mod_db.close_case(
            active["id"], kind="revoked", actor_id=actor.id,
            actor_name=str(actor), reason=reason or "Снято вручную",
        )
        await refresh_card(closed)
    else:
        notes.append("Активного кейса не было, сняли только роль.")

    case = await open_case(
        guild, "unmute", target, actor, reason,
        parent_id=active["id"] if active else None,
    )
    await notify_target(case, guild)
    announced = await announce_case(case)

    logger.info("Мут снят: %s (%s) модератором %s (%s)", target, target.id, actor, actor.id)

    return result_lines(f"🔊 {target.mention} - мут снят", case, notes, announced)


async def perform_kick(target, actor, reason="", source="command",
                       parent_id=None, message_url=None) -> str:
    guild = target.guild

    problem = (
        target_problem(actor, target, "kick")
        or bot_problem(guild, "kick")
        or hierarchy_problem(guild, target)
    )
    if problem:
        return f"❌ {problem[0].upper() + problem[1:]}"

    case = await open_case(
        guild, "kick", target, actor, reason,
        parent_id=parent_id, source=source, message_url=message_url,
    )

    # Личка уходит до кика: после него общих серверов не остаётся
    await notify_target(case, guild)

    try:
        await guild.kick(target, reason=audit_reason(actor, "kick", case["reason"], case["id"]))
    except (disnake.Forbidden, disnake.HTTPException) as e:
        logger.error("Не удалось кикнуть %s: %s", target, e)
        return f"❌ Discord не дал кикнуть: {e}"

    announced = await announce_case(case)
    logger.info("Кик: %s (%s) от %s (%s), причина: %r", target, target.id, actor, actor.id, case["reason"])

    return result_lines(
        f"👢 {target.mention} - кик · кейс {case_label(case)}",
        case, [], announced,
    )


async def _ban_user(guild, user, reason: str, delete_seconds: int = 0):
    """Бан с чисткой сообщений. Имя параметра менялось между версиями disnake."""
    try:
        await guild.ban(user, reason=reason, clean_history_duration=delete_seconds)
    except TypeError:
        await guild.ban(
            user, reason=reason,
            delete_message_days=max(0, min(7, delete_seconds // 86400)),
        )


async def perform_ban(target, actor, duration=None, reason="", delete_seconds=0,
                      source="command", parent_id=None, message_url=None) -> str:
    """
    Бан. target может быть участником сервера или пользователем Discord:
    забанить по ID можно и того, кто на сервер ещё не заходил.
    """
    guild = getattr(target, "guild", None) or moderation_guild()

    problem = (
        target_problem(actor, target, "ban")
        or bot_problem(guild, "ban")
        or hierarchy_problem(guild, target)
    )
    if problem:
        return f"❌ {problem[0].upper() + problem[1:]}"

    notes = []
    previous = await mod_db.active_case(target.id, "ban", guild.id)
    if previous:
        await mod_db.close_case(
            previous["id"], kind="replaced", actor_id=actor.id,
            actor_name=str(actor), reason="Выдан новый бан",
        )
        notes.append(f"Прошлый бан #{previous['id']} заменён.")

    expires_at = disnake.utils.utcnow() + duration if duration else None

    case = await open_case(
        guild, "ban", target, actor, reason, expires_at=expires_at,
        parent_id=parent_id, source=source, message_url=message_url,
    )

    await notify_target(case, guild)

    try:
        await _ban_user(
            guild, target,
            audit_reason(actor, "ban", case["reason"], case["id"]),
            delete_seconds,
        )
    except (disnake.Forbidden, disnake.HTTPException) as e:
        if case.get("id"):
            await mod_db.close_case(
                case["id"], kind="revoked", actor_id=actor.id,
                actor_name=str(actor), reason="Бан не прошёл",
            )
        logger.error("Не удалось забанить %s: %s", target, e)
        return f"❌ Discord не дал забанить: {e}"

    announced = await announce_case(case)

    logger.info(
        "Бан: %s (%s) от %s (%s) на %s, причина: %r",
        target, target.id, actor, actor.id,
        human_delta(duration) if duration else "навсегда", case["reason"],
    )

    term = f"на {human_delta(duration)}" if duration else "навсегда"
    head = f"🔨 {target.mention} - бан {term} · кейс {case_label(case)}"
    if expires_at:
        head += f" · до {ts(expires_at, 'f')}"

    return result_lines(head, case, notes, announced)


async def perform_unban(user_id, actor, reason="") -> str:
    guild = moderation_guild()

    problem = bot_problem(guild, "unban")
    if problem:
        return f"❌ {problem[0].upper() + problem[1:]}"

    user = await resolve_user(user_id)
    if user is None:
        return f"❌ Пользователь с ID `{user_id}` не найден в Discord."

    try:
        await guild.fetch_ban(disnake.Object(id=int(user_id)))
    except disnake.NotFound:
        return f"ℹ️ `{user}` не в бане на сервере."
    except (disnake.Forbidden, disnake.HTTPException) as e:
        return f"❌ Не удалось проверить бан: {e}"

    try:
        await guild.unban(user, reason=audit_reason(actor, "unban", reason))
    except (disnake.Forbidden, disnake.HTTPException) as e:
        return f"❌ Discord не дал разбанить: {e}"

    notes = []
    active = await mod_db.active_case(int(user_id), "ban", guild.id)
    if active:
        closed = await mod_db.close_case(
            active["id"], kind="revoked", actor_id=actor.id,
            actor_name=str(actor), reason=reason or "Разбан вручную",
        )
        await refresh_card(closed)
    else:
        notes.append("Активного кейса бана не было.")

    case = await open_case(
        guild, "unban", user, actor, reason,
        parent_id=active["id"] if active else None,
    )
    announced = await announce_case(case)

    logger.info("Разбан: %s (%s) модератором %s (%s)", user, user_id, actor, actor.id)

    return result_lines(f"🕊️ `{user}` - разбан", case, notes, announced)


async def perform_softban(target, actor, reason="", delete_seconds=86400) -> str:
    """Бан и сразу разбан: человек остаётся, его сообщения за сутки - нет."""
    guild = target.guild

    problem = (
        target_problem(actor, target, "softban")
        or bot_problem(guild, "softban")
        or hierarchy_problem(guild, target)
    )
    if problem:
        return f"❌ {problem[0].upper() + problem[1:]}"

    case = await open_case(guild, "softban", target, actor, reason)
    await notify_target(case, guild)

    try:
        await _ban_user(
            guild, target,
            audit_reason(actor, "softban", case["reason"], case["id"]),
            delete_seconds,
        )
        await guild.unban(target, reason=f"Софт-бан, кейс #{case['id']}")
    except (disnake.Forbidden, disnake.HTTPException) as e:
        logger.error("Софт-бан %s не удался: %s", target, e)
        return f"❌ Discord не дал провести софт-бан: {e}"

    announced = await announce_case(case)
    logger.info("Софт-бан: %s (%s) от %s (%s)", target, target.id, actor, actor.id)

    return result_lines(
        f"🧹 {target.mention} - софт-бан · кейс {case_label(case)}",
        case, [], announced,
    )


async def perform_note(target, actor, text: str) -> str:
    """Скрытая заметка: нарушителю не приходит, в истории остаётся."""
    guild = getattr(target, "guild", None) or moderation_guild()

    case = await open_case(guild, "note", target, actor, text)
    announced = await announce_case(case)

    logger.info("Заметка о %s (%s) от %s: %r", target, target.id, actor, text)

    return result_lines(
        f"📝 {target.mention} - заметка · кейс {case_label(case)}",
        case, [], announced,
    )


#  Снятие кейса
async def revoke_case(case_id: int, actor, reason="") -> str:
    """
    Снимает наказание по номеру кейса: варн, мут или бан.
    Свой кейс может снять любой модератор, чужой - только старший состав.
    """
    row = await mod_db.get_case(case_id)
    if row is None:
        return f"❌ Кейс #{case_id} не найден."

    if not row["active"]:
        closed = row["close_kind"] or "закрыт"
        return f"ℹ️ Кейс #{case_id} уже неактивен ({closed})."

    if row["actor_id"] != actor.id and not is_senior(actor):
        return "❌ Чужие кейсы снимает старший состав."

    guild = bot.get_guild(row["guild_id"]) or moderation_guild()
    action = row["action"]

    if action == "lock":
        channel = guild.get_channel(row["target_id"]) if guild else None

        if channel is None:
            await mod_db.close_case(
                case_id, kind="revoked", actor_id=actor.id,
                actor_name=str(actor), reason=reason or "Снято вручную",
            )
            return f"✅ Кейс #{case_id} закрыт, канала уже нет."

        problem = await set_channel_lock(
            channel, False, reason=audit_reason(actor, "unlock", reason, case_id)
        )
        if problem:
            return f"❌ {problem[0].upper() + problem[1:]}"

        closed = await mod_db.close_case(
            case_id, kind="revoked", actor_id=actor.id,
            actor_name=str(actor), reason=reason or "Снято вручную",
        )
        await refresh_card(closed)

        embed = disnake.Embed(
            title=action_title("unlock"),
            description=f"{channel.mention} открыт.",
            color=COLOR_OK,
            timestamp=disnake.utils.utcnow(),
        )
        embed.add_field(name="Модератор", value=actor.mention, inline=True)
        embed.add_field(name="Из кейса", value=f"#{case_id}", inline=True)
        await announce_embed(embed)

        logger.info("Блокировка снята: канал %s, кейс #%s, модератор %s", channel, case_id, actor)
        return f"🔓 {channel.mention} открыт · кейс #{case_id} закрыт"

    if action == "mute":
        member = await resolve_member(guild, row["target_id"])
        if member is not None:
            return await perform_unmute(member, actor, reason)

        # Человека нет на сервере: роль снимать не с кого, кейс просто закрываем
        closed = await mod_db.close_case(
            case_id, kind="revoked", actor_id=actor.id,
            actor_name=str(actor), reason=reason or "Снято вручную",
        )
        await refresh_card(closed)
        return f"✅ Кейс #{case_id} закрыт · участника нет на сервере"

    if action == "ban":
        return await perform_unban(row["target_id"], actor, reason)

    if action == "warn":
        closed = await mod_db.close_case(
            case_id, kind="revoked", actor_id=actor.id,
            actor_name=str(actor), reason=reason or "Снято вручную",
        )
        await refresh_card(closed)

        target = await resolve_member(guild, row["target_id"]) or await resolve_user(row["target_id"])
        if target is None:
            return f"✅ Кейс #{case_id} снят"

        case = await open_case(guild, "unwarn", target, actor, reason, parent_id=case_id)
        await notify_target(case, guild)
        announced = await announce_case(case)

        left = len(await mod_db.active_warns(row["target_id"], guild.id))
        logger.info("Варн снят: кейс #%s, участник %s, модератор %s", case_id, target, actor)

        return result_lines(
            f"✅ Кейс #{case_id} снят · у {target.mention} варнов: {left}",
            case, [], announced,
        )

    return f"ℹ️ Кейс #{case_id}: {action_name(action).lower()} снимать нечего."


async def expire_case(row) -> bool:
    """
    Снимает наказание, у которого вышел срок. Зовётся фоновой задачей.
    True, если что-то реально сняли.
    """
    guild = bot.get_guild(row["guild_id"]) or moderation_guild()
    if guild is None:
        return False

    action = row["action"]

    if action == "lock":
        channel = guild.get_channel(row["target_id"])
        if channel is not None:
            await set_channel_lock(channel, False, reason=f"Срок блокировки истёк, кейс #{row['id']}")

        closed = await mod_db.close_case(row["id"], kind="expired", reason="Срок истёк")
        await refresh_card(closed)

        embed = disnake.Embed(
            title=action_title("unlock"),
            description=(
                f"{channel.mention if channel else 'Канал'} снова открыт: "
                f"срок блокировки из кейса #{row['id']} истёк."
            ),
            color=COLOR_OK,
            timestamp=disnake.utils.utcnow(),
        )
        await announce_embed(embed)
        logger.info("Блокировка снята автоматически: канал %s, кейс #%s", row["target_id"], row["id"])
        return True

    if action == "mute":
        member = await resolve_member(guild, row["target_id"])
        role = muted_role(guild)

        if member is not None and role is not None and role in member.roles:
            try:
                await member.remove_roles(role, reason=f"Срок мута истёк, кейс #{row['id']}")
            except (disnake.Forbidden, disnake.HTTPException) as e:
                logger.warning("Не удалось снять роль мута с %s: %s", row["target_id"], e)
                return False

    elif action == "ban":
        try:
            await guild.unban(
                disnake.Object(id=row["target_id"]),
                reason=f"Срок бана истёк, кейс #{row['id']}",
            )
        except disnake.NotFound:
            pass
        except (disnake.Forbidden, disnake.HTTPException) as e:
            logger.warning("Не удалось разбанить %s: %s", row["target_id"], e)
            return False

    closed = await mod_db.close_case(row["id"], kind="expired", reason="Срок истёк")
    await refresh_card(closed)

    # Короткая запись в лог: модерация должна видеть, что наказание ушло само,
    # а не гадать, кто его снял
    embed = disnake.Embed(
        title=action_title("unmute" if action == "mute" else "unban"),
        description=f"<@{row['target_id']}> - срок кейса #{row['id']} истёк.",
        color=COLOR_OK,
        timestamp=disnake.utils.utcnow(),
    )
    embed.set_footer(text=f"ID участника: {row['target_id']}")
    await announce_embed(embed)

    target = await resolve_user(row["target_id"])
    if target is not None:
        case = {
            "id": None,
            "action": "unmute" if action == "mute" else "unban",
            "target": target,
            "target_id": row["target_id"],
            "target_name": row["target_name"] or str(target),
            "actor_id": getattr(bot.user, "id", 0),
            "actor_name": str(bot.user),
            "reason": f"Срок истёк, кейс #{row['id']}",
            "expires_at": None,
            "parent_id": row["id"],
            "source": "auto",
            "db_ok": True,
        }
        await notify_target(case, guild)

    logger.info("Срок истёк: кейс #%s (%s) с участника %s", row["id"], action, row["target_id"])
    return True


#  Каналы
async def set_channel_lock(channel, locked: bool, reason: str = "") -> str | None:
    """
    Закрывает или открывает канал для @everyone.

    Открытие возвращает право в наследуемое состояние, а не выставляет «можно»
    насильно: у категорий и приватных каналов свои настройки, и ломать их
    разблокировкой нельзя.
    """
    everyone = channel.guild.default_role
    overwrite = channel.overwrites_for(everyone)

    fields = ("send_messages", "send_messages_in_threads", "create_public_threads",
              "create_private_threads", "add_reactions")

    for name in fields:
        if hasattr(overwrite, name):
            setattr(overwrite, name, False if locked else None)

    try:
        await channel.set_permissions(everyone, overwrite=overwrite, reason=reason[:500])
        return None
    except disnake.Forbidden:
        return "у бота нет прав на изменение доступа к каналу"
    except disnake.HTTPException as e:
        return f"Discord отказал: {e}"


#  Досье и история
def _case_line(row) -> str:
    """Одна строка истории: #12 ⚠️ Предупреждение · вчера · причина."""
    mark = "" if row["active"] else "~~"
    reason = (row["reason"] or DEFAULT_REASON).replace("\n", " ")
    if len(reason) > 70:
        reason = reason[:67] + "..."

    line = (
        f"`#{row['id']}` {action_title(row['action'])} · {ts(row['created_at'], 'R')}\n"
        f"{mark}{reason}{mark} - <@{row['actor_id']}>"
    )

    if row["active"] and row["expires_at"]:
        line += f"\nдо {ts(row['expires_at'], 'f')}"

    return line


def next_step_hint(warns: int) -> str | None:
    """Что будет за следующий варн: полезно знать до его выдачи."""
    step = escalation_for(warns + 1)
    if step is None:
        return None

    action, duration = step
    return f"Следующий варн: {action_name(action).lower()} {term_text(duration)}"


async def build_dossier(user, guild) -> disnake.Embed:
    """Карточка участника: кто он, что за ним числится, на что смотреть."""
    warns_rows = await mod_db.active_warns(user.id, guild.id if guild else None)
    counts = await mod_db.count_cases(user.id)
    recent = await mod_db.list_cases(user.id, limit=5)

    mute = await mod_db.active_case(user.id, "mute", guild.id if guild else None)
    ban = await mod_db.active_case(user.id, "ban", guild.id if guild else None)
    punishment = mute or ban

    warns = len(warns_rows)
    color = COLOR_BAD if punishment else (0xF0B232 if warns else COLOR_OK)

    embed = disnake.Embed(
        title=f"🗂️ Досье · {user}",
        color=color,
        timestamp=disnake.utils.utcnow(),
    )
    embed.set_thumbnail(url=user.display_avatar.url)

    embed.add_field(
        name="Аккаунт создан",
        value=f"{ts(user.created_at, 'D')}\n{ts(user.created_at, 'R')}",
        inline=True,
    )

    joined = getattr(user, "joined_at", None)
    embed.add_field(
        name="На сервере с",
        value=f"{ts(joined, 'D')}\n{ts(joined, 'R')}" if joined else "не на сервере",
        inline=True,
    )

    embed.add_field(name="ID", value=f"`{user.id}`", inline=True)

    totals = " · ".join(
        f"{action_title(action)}: **{counts.get(action, 0)}**"
        for action in ("warn", "mute", "kick", "ban", "note")
        if counts.get(action)
    )
    embed.add_field(
        name="За всё время",
        value=totals or "чисто, наказаний не было",
        inline=False,
    )

    warn_text = f"**{warns}** {plural(warns, ('активный', 'активных', 'активных'))}"
    hint = next_step_hint(warns)
    if hint:
        warn_text += f"\n{hint}"
    embed.add_field(name="Варны", value=warn_text, inline=True)

    if punishment:
        embed.add_field(
            name="Сейчас действует",
            value=(
                f"{action_title(punishment['action'])} · кейс #{punishment['id']}\n"
                f"{duration_line(punishment['expires_at'])}"
            ),
            inline=True,
        )

    if recent:
        embed.add_field(
            name="Последние кейсы",
            value="\n\n".join(_case_line(row) for row in recent[:3]),
            inline=False,
        )

    embed.set_footer(text="Полная история: &history")
    return embed


def build_history_embed(user, rows, page: int, total: int, counts: dict) -> disnake.Embed:
    embed = disnake.Embed(
        title=f"📚 История · {user}",
        color=COLOR_INFO,
        timestamp=disnake.utils.utcnow(),
    )
    embed.set_thumbnail(url=user.display_avatar.url)

    summary = " · ".join(
        f"{action_title(action)}: **{count}**"
        for action, count in sorted(counts.items(), key=lambda p: -p[1])
    )
    embed.description = summary or "Наказаний не было."

    for row in rows:
        embed.add_field(name="​", value=_case_line(row), inline=False)

    pages = max(1, (total + 9) // 10)
    embed.set_footer(text=f"Страница {page} из {pages} · всего кейсов: {total}")
    return embed


def build_case_detail(row) -> disnake.Embed:
    """Полная карточка кейса по номеру."""
    embed = disnake.Embed(
        title=f"{action_title(row['action'])} · кейс #{row['id']}",
        color=action_color(row["action"]) if row["active"] else 0x4E5058,
        timestamp=row["created_at"],
    )

    embed.add_field(
        name="Кто",
        value=f"<@{row['target_id']}>\n`{row['target_name']}`",
        inline=True,
    )
    embed.add_field(
        name="Модератор",
        value=f"<@{row['actor_id']}>\n`{row['actor_name']}`",
        inline=True,
    )
    embed.add_field(
        name="Состояние",
        value="🟢 действует" if row["active"] else f"⚪ {row['close_kind'] or 'закрыт'}",
        inline=True,
    )
    embed.add_field(name="Причина", value=(row["reason"] or DEFAULT_REASON)[:1000], inline=False)

    if row["expires_at"]:
        embed.add_field(name="Срок", value=duration_line(row["expires_at"]), inline=True)

    if row["parent_id"]:
        embed.add_field(name="Связан с", value=f"кейс #{row['parent_id']}", inline=True)

    if row["source"] and row["source"] != "command":
        embed.add_field(name="Источник", value=row["source"], inline=True)

    if row["message_url"]:
        embed.add_field(name="Где", value=f"[сообщение]({row['message_url']})", inline=True)

    if not row["active"]:
        closed_by = f"<@{row['closed_by']}>" if row["closed_by"] else "бот"
        embed.add_field(
            name="Закрыт",
            value=f"{closed_by} · {ts(row['closed_at'], 'f')}\n{row['close_reason'] or ''}",
            inline=False,
        )

    embed.set_footer(text=f"Выдан · ID участника: {row['target_id']}")
    return embed


#  Разбор аргументов, общий для команд и слэш-команд
async def find_target(ctx_or_inter, token: str):
    """
    Находит участника по упоминанию, ID или имени. Возвращает (кого, ошибка).
    Того, кто вышел с сервера, ищем среди пользователей Discord: банить и
    смотреть досье можно и по одному ID.
    """
    token = (token or "").strip()
    if not token:
        return None, "Не указан участник."

    guild = getattr(ctx_or_inter, "guild", None) or moderation_guild()

    try:
        member = await commands.MemberConverter().convert(ctx_or_inter, token)
        return member, None
    except (commands.MemberNotFound, commands.CommandError, AttributeError):
        pass

    digits = "".join(ch for ch in token if ch.isdigit())
    if digits:
        member = await resolve_member(guild, digits)
        if member is not None:
            return member, None

        user = await resolve_user(digits)
        if user is not None:
            return user, None

    return None, f"Участник `{token}` не найден. Упомяни его или укажи ID."
