"""
Гост-смены: сборка карточек, ветки под отчёт и вся работа с ДС
"""

import logging

from datetime import datetime

import aiohttp
import disnake

from bot_init import bot, ghost_db
from dataConfig import (
    ADDRESS_DEV,
    ADDRESS_MRP,
    AGHOST_REPORT_CHANNEL_ID,
    EGHOST_REPORT_CHANNEL_ID,
    GHOST_MAX_SHIFT_HOURS,
    GHOST_REVIEW_EVENT,
    GHOST_STATUS_SERVER,
    GHOST_STATUS_TIMEOUT,
    MOD_GUILD_ID,
    ROLE_ACCESS_GHOST_ADMIN,
    ROLE_ACCESS_GHOST_EVENT,
    ROLE_ACCESS_GHOST_REVIEW,
)
from ghost_rules import (
    AGHOST,
    COLOR_BAD,
    COLOR_INFO,
    COLOR_LIVE,
    COLOR_OK,
    EGHOST,
    REVIEW_APPROVED,
    REVIEW_NONE,
    REVIEW_PENDING,
    REVIEW_REJECTED,
    clean_preset,
    clock,
    duration_text,
    event_line,
    hours_text,
    kind_color,
    kind_department,
    kind_name,
    kind_title,
    kind_verb,
    preset_line,
    review_mark,
)
from team_departments import department_role_id, get_position, get_positions
from vacation_time import as_local, now_local, ts

logger = logging.getLogger(__name__)

MENTIONS = disnake.AllowedMentions(everyone=False, roles=False, users=True)

# Порты игровых серверов, как в &status
SERVER_PORTS = {"mrp": (ADDRESS_MRP, "1212"), "dev": (ADDRESS_DEV, "11212")}

# Ветка под отчёт живёт сутки без активности, потом сворачивается сама
THREAD_ARCHIVE_MIN = 1440


#  Кто что может
def _role_ids(user) -> set:
    return {role.id for role in getattr(user, "roles", [])}


def can_open(user, kind: str) -> bool:
    """Пускаем в отдел, к которому относится смена."""
    allowed = ROLE_ACCESS_GHOST_ADMIN if kind == AGHOST else ROLE_ACCESS_GHOST_EVENT
    return bool(_role_ids(user) & set(allowed))


def can_review(user) -> bool:
    """Проверка отчётов - обязанность наблюдателей, но выше тоже могут."""
    return bool(_role_ids(user) & set(ROLE_ACCESS_GHOST_REVIEW))


def can_close(user, row) -> bool:
    """Закрывает смену её хозяин. Проверяющие могут закрыть чужую забытую."""
    return user.id == row["user_id"] or can_review(user)



def review_needed(kind: str) -> bool:
    return kind == AGHOST or GHOST_REVIEW_EVENT


def initial_review_state(kind: str) -> str:
    return REVIEW_PENDING if review_needed(kind) else REVIEW_NONE


def _department_role_ids(kind: str) -> set:
    """
    Все роли отдела: и общая, и каждая ступень лестницы.

    Берём из team_departments, а не переписываем ID в конфиг: там они уже
    лежат одним списком, и разъехаться двум спискам гораздо проще, чем
    одному.
    """
    department = kind_department(kind)
    ids = {department_role_id(department)}
    ids |= {position.role_id for position in get_positions(department)}
    return {role_id for role_id in ids if role_id}


def departments_of(user) -> list:
    """
    В каких отделах человек реально состоит.

    Это не то же самое, что can_open. Там вопрос «пустить ли», и на него
    влияют роли руководства: они открывают команды обоих отделов. Здесь
    вопрос «чей он», и ответ должен быть точным, иначе &ghost покажет
    главному ивентеру с ролью «Админ» статистику модерации.
    """
    roles = _role_ids(user)
    return [kind for kind in (AGHOST, EGHOST) if roles & _department_role_ids(kind)]


def position_name(member, kind: str) -> str | None:
    """Должность человека в его отделе на момент отчёта: старшая из ролей."""
    department = kind_department(kind)
    best = None

    for role in getattr(member, "roles", []):
        position = get_position(role.id)
        if position is None or position.department != department:
            continue
        if best is None or (position.grade or 0) > (best.grade or 0):
            best = position

    return best.name if best else None


#  Где что лежит
def ghost_guild():
    """Сервер, на котором ведутся отчёты."""
    if MOD_GUILD_ID:
        guild = bot.get_guild(MOD_GUILD_ID)
        if guild is not None:
            return guild

    return bot.guilds[0] if bot.guilds else None


def channel_id_for(kind: str) -> int:
    return AGHOST_REPORT_CHANNEL_ID if kind == AGHOST else EGHOST_REPORT_CHANNEL_ID


async def report_channel(kind: str):
    channel_id = channel_id_for(kind)
    if not channel_id:
        return None

    channel = bot.get_channel(channel_id)
    if channel is not None:
        return channel

    try:
        return await bot.fetch_channel(channel_id)
    except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException) as e:
        logger.error("Канал отчётов %s (%s) недоступен: %s", kind, channel_id, e)
        return None


async def shift_thread(row):
    """Ветка под отчёт. None, если её удалили или бота туда не пускают."""
    thread_id = row["thread_id"]
    if not thread_id:
        return None

    thread = bot.get_channel(thread_id)
    if thread is not None:
        return thread

    try:
        return await bot.fetch_channel(thread_id)
    except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException):
        return None


#  Данные с игрового сервера
async def fetch_status(server: str = None) -> dict:
    """
    Раунд, онлайн и режим с игрового сервера.

    Пустой словарь означает, что сервер не ответил: отчёт от этого не
    отменяется, человек просто впишет цифры руками. Таймаут короткий не
    случайно - Discord даёт три секунды на первый ответ, и лучше отдать
    пустую форму, чем протухшее взаимодействие.
    """
    name = (server or GHOST_STATUS_SERVER or "mrp").lower()
    address, port = SERVER_PORTS.get(name, SERVER_PORTS["mrp"])
    url = f"http://{address}:{port}/status"

    timeout = aiohttp.ClientTimeout(total=GHOST_STATUS_TIMEOUT)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning("Статус сервера %s: код %d", name, resp.status)
                    return {}
                data = await resp.json()
    except Exception as e:
        logger.warning("Не удалось получить статус сервера %s: %s", name, e)
        return {}

    # Пустые значения не возвращаем: в лобби пресета ещё нет, и лучше
    # честно спросить его у человека, чем записать в отчёт пустую строку
    status = {
        "round_id": data.get("round_id"),
        "players": data.get("players"),
        "preset": clean_preset(str(data.get("preset") or "")),
    }

    return {key: value for key, value in status.items() if value not in (None, "")}


def status_complete(status: dict) -> bool:
    """Есть ли в ответе сервера всё, что иначе пришлось бы спрашивать."""
    return all(key in (status or {}) for key in ("round_id", "players", "preset"))


#  Карточка отчёта
def _state_line(row) -> tuple[str, int]:
    """Строка статуса и цвет карточки: они всегда меняются вместе."""
    if row["ended_at"] is None:
        return f"🟢 Смена идёт с {clock(as_local(row['started_at']))}", COLOR_LIVE

    state = row["review_state"] or REVIEW_PENDING

    if state == REVIEW_APPROVED:
        return f"{review_mark(state)} · <@{row['review_by']}>", COLOR_OK
    if state == REVIEW_REJECTED:
        return f"{review_mark(state)} · <@{row['review_by']}>", COLOR_BAD
    if state == REVIEW_NONE:
        return "⏹️ Смена завершена", COLOR_INFO

    return "⏹️ Смена завершена, ждёт проверки", kind_color(row["kind"])


def build_shift_embed(row, member=None) -> disnake.Embed:
    """Карточка отчёта. Одна и та же и при открытии, и после проверки."""
    kind = row["kind"]
    started = as_local(row["started_at"])
    ended = as_local(row["ended_at"])

    state_text, color = _state_line(row)

    round_id = row["round_id"]
    title = f"{kind_title(kind)} · раунд {round_id}" if round_id else kind_title(kind)

    embed = disnake.Embed(title=title, color=color, timestamp=disnake.utils.utcnow())

    who = member.mention if member is not None else f"<@{row['user_id']}>"
    embed.add_field(
        name="Кто",
        value=f"{who}\n`{row['user_name'] or row['user_id']}`",
        inline=True,
    )
    embed.add_field(name="Раунд", value=str(round_id) if round_id else "не указан", inline=True)
    embed.add_field(
        name="Игроков",
        value=str(row["players"]) if row["players"] is not None else "не указано",
        inline=True,
    )

    embed.add_field(
        name="Режим",
        value=preset_line(row["preset"], row["preset_note"]),
        inline=False,
    )

    embed.add_field(name="Начало", value=f"{clock(started)}\n{ts(started, 't')}", inline=True)
    embed.add_field(
        name="Окончание",
        value=f"{clock(ended)}\n{ts(ended, 't')}" if ended else "-",
        inline=True,
    )
    embed.add_field(
        name="Длительность",
        value=duration_text(started, ended) + ("" if ended else " (идёт)"),
        inline=True,
    )

    if kind == EGHOST:
        embed.add_field(name="Отмечено действий", value=str(row["actions"] or 0), inline=True)
        embed.add_field(name="Ивент", value=event_line(row["event_text"]), inline=False)

    embed.add_field(name="Статус", value=state_text, inline=False)

    if row["review_state"] in (REVIEW_APPROVED, REVIEW_REJECTED):
        note = (row["review_note"] or "").strip()
        label = "Заметка наблюдателя" if row["review_state"] == REVIEW_APPROVED else "Причина отказа"
        embed.add_field(name=label, value=note[:1000] if note else "-", inline=False)

    if member is not None:
        embed.set_thumbnail(url=member.display_avatar.url)

    footer = f"Отчёт #{row['id']}"
    if row["position"]:
        footer += f" · {row['position']}"
    footer += f" · ID: {row['user_id']}"
    embed.set_footer(text=footer)

    return embed


def shift_buttons(row) -> list:
    """
    Кнопки под карточкой. Вся суть в custom_id: перезапуск бота им не страшен.

    Пока смена идёт - завершить и, у игоста, отметить действие.
    После - проверка отчёта, если она для этого вида смен нужна.
    """
    shift_id = row["id"]
    if not shift_id:
        return []

    # Вид смены едет прямо в custom_id: роутеру нужно знать, чья это
    # карточка, ещё до похода в базу - форму Discord принимает только
    # первым ответом на нажатие
    tag = f"ghost:{row['kind']}"
    buttons = []

    if row["ended_at"] is None:
        if row["kind"] == EGHOST:
            buttons.append(
                disnake.ui.Button(
                    label="Оповестить о действии",
                    emoji="📢",
                    style=disnake.ButtonStyle.primary,
                    custom_id=f"{tag}:act:{shift_id}",
                )
            )

        buttons.append(
            disnake.ui.Button(
                label=f"Завершить {kind_name(row['kind']).lower()}",
                emoji="⏹️",
                style=disnake.ButtonStyle.danger,
                custom_id=f"{tag}:finish:{shift_id}",
            )
        )
    elif row["review_state"] == REVIEW_PENDING:
        buttons.append(
            disnake.ui.Button(
                label="Подтвердить",
                emoji="✅",
                style=disnake.ButtonStyle.success,
                custom_id=f"{tag}:approve:{shift_id}",
            )
        )
        buttons.append(
            disnake.ui.Button(
                label="Не подтверждать",
                emoji="❌",
                style=disnake.ButtonStyle.danger,
                custom_id=f"{tag}:reject:{shift_id}",
            )
        )

    if row["kind"] == EGHOST and (row["actions"] or 0):
        buttons.append(
            disnake.ui.Button(
                label="Хронология",
                emoji="🗒️",
                style=disnake.ButtonStyle.secondary,
                custom_id=f"{tag}:log:{shift_id}",
            )
        )

    return buttons


async def refresh_card(row) -> bool:
    """Перерисовывает карточку в канале под то, что лежит в базе."""
    if not row["channel_id"] or not row["message_id"]:
        return False

    channel = bot.get_channel(row["channel_id"])
    if channel is None:
        try:
            channel = await bot.fetch_channel(row["channel_id"])
        except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException):
            return False

    try:
        message = await channel.fetch_message(row["message_id"])
    except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException) as e:
        logger.warning("Карточка отчёта #%s недоступна: %s", row["id"], e)
        return False

    guild = getattr(channel, "guild", None) or ghost_guild()
    member = guild.get_member(row["user_id"]) if guild else None

    try:
        await message.edit(
            embed=build_shift_embed(row, member),
            components=shift_buttons(row),
            allowed_mentions=MENTIONS,
        )
        return True
    except disnake.HTTPException as e:
        logger.warning("Не удалось обновить карточку отчёта #%s: %s", row["id"], e)
        return False


#  Открытие смены
def thread_name(row, member=None) -> str:
    """Имя ветки: раунд и ник, чтобы отчёт находился поиском."""
    who = getattr(member, "display_name", None) or row["user_name"] or str(row["user_id"])
    head = f"Раунд {row['round_id']}" if row["round_id"] else kind_name(row["kind"])
    return f"{head} · {who}"[:100]


async def announce_shift(row, member=None) -> tuple[object, str | None]:
    """
    Кладёт карточку в канал отдела, заводит под ней ветку и запоминает и то,
    и другое. Возвращает (обновлённая строка, текст проблемы).

    Если ветку завести не вышло, отчёт всё равно остаётся: без ветки жить
    можно, без отчёта нельзя.
    """
    channel = await report_channel(row["kind"])
    if channel is None:
        return row, "Канал отчётов не настроен или недоступен боту."

    try:
        message = await channel.send(
            embed=build_shift_embed(row, member),
            components=shift_buttons(row),
            allowed_mentions=MENTIONS,
        )
    except (disnake.Forbidden, disnake.HTTPException) as e:
        logger.error("Не удалось отправить карточку отчёта #%s: %s", row["id"], e)
        return row, "Не смог написать в канал отчётов, проверь права бота."

    thread = None
    try:
        thread = await message.create_thread(
            name=thread_name(row, member),
            auto_archive_duration=THREAD_ARCHIVE_MIN,
        )
    except (disnake.Forbidden, disnake.HTTPException) as e:
        logger.warning("Ветку под отчёт #%s завести не вышло: %s", row["id"], e)

    updated = await ghost_db.set_message(
        row["id"], channel.id, message.id,
        thread.id if thread is not None else None,
        message.jump_url,
    )

    return updated or row, None


async def open_shift(member, kind: str, round_id, players, preset, preset_note,
                     started_at: datetime, event_text=None):
    """
    Заводит смену и публикует отчёт. Возвращает (строка, текст для человека).

    Строка None означает, что база не ответила: отчёт в канал в этом случае
    не уходит, иначе в отделе повиснет карточка без кнопок и без номера.
    """
    existing = await ghost_db.open_shift_of(member.id, kind)
    if existing is not None:
        where = existing["message_url"] or "в канале отдела"
        return None, (
            f"❌ У тебя уже открыт {kind_name(kind).lower()} с "
            f"{clock(as_local(existing['started_at']))}: {where}\n"
            f"Сначала заверши его кнопкой под карточкой."
        )

    row = await ghost_db.open_shift(
        kind=kind,
        guild_id=member.guild.id,
        user_id=member.id,
        user_name=str(member),
        started_at=started_at,
        department=kind_department(kind),
        position=position_name(member, kind),
        round_id=round_id,
        players=players,
        preset=preset,
        preset_note=preset_note,
        event_text=event_text,
        review_state=initial_review_state(kind),
    )

    if row is None:
        return None, "⚠️ База недоступна, отчёт не завёлся. Попробуй ещё раз через минуту."

    row, problem = await announce_shift(row, member)

    logger.info(
        "Открыт %s #%s: %s (%s), раунд %s",
        kind, row["id"], member, member.id, round_id,
    )

    lines = [f"{kind_title(kind)} открыт, отчёт **#{row['id']}**."]
    if row["message_url"]:
        lines.append(f"Карточка: {row['message_url']}")
    if row["thread_id"]:
        lines.append(f"Ветка под отчёт: <#{row['thread_id']}>")
    if problem:
        lines.append(f"⚠️ {problem}")

    return row, "\n".join(lines)


#  Завершение смены
async def close_shift(shift_id: int, actor, ended_at: datetime = None) -> str:
    row = await ghost_db.get_shift(shift_id)
    if row is None:
        return f"❌ Отчёт #{shift_id} не найден."

    if row["ended_at"] is not None:
        return f"⚠️ Отчёт #{shift_id} уже завершён в {clock(as_local(row['ended_at']))}."

    if not can_close(actor, row):
        return "❌ Завершить смену может только её хозяин или проверяющий."

    closed = await ghost_db.close_shift(shift_id, ended_at or now_local())
    if closed is None:
        return "⚠️ База недоступна, смена не закрылась. Попробуй ещё раз."

    await refresh_card(closed)

    started = as_local(closed["started_at"])
    ended = as_local(closed["ended_at"])
    length = duration_text(started, ended)

    thread = await shift_thread(closed)
    if thread is not None:
        try:
            await thread.send(
                f"⏹️ {kind_title(closed['kind'])} завершён в **{clock(ended)}**. "
                f"Длительность: **{length}**.",
                allowed_mentions=MENTIONS,
            )
        except disnake.HTTPException:
            pass

    logger.info("Закрыт %s #%s пользователем %s", closed["kind"], shift_id, actor)

    lines = [
        f"⏹️ {kind_title(closed['kind'])} **#{shift_id}** завершён.",
        f"С {clock(started)} до {clock(ended)}, всего **{length}**.",
    ]

    if closed["review_state"] == REVIEW_PENDING:
        lines.append("Отчёт ушёл наблюдателям на проверку.")

    if (ended - started).total_seconds() > GHOST_MAX_SHIFT_HOURS * 3600:
        lines.append(
            f"⚠️ Смена длиннее {GHOST_MAX_SHIFT_HOURS} ч, в среднюю длительность "
            f"она не пойдёт. Похоже, кнопку нажали не сразу."
        )

    return "\n".join(lines)


#  Действия по ходу раунда
async def add_action(shift_id: int, actor, body: str) -> str:
    row = await ghost_db.get_shift(shift_id)
    if row is None:
        return f"❌ Отчёт #{shift_id} не найден."

    if row["ended_at"] is not None:
        return f"⚠️ Отчёт #{shift_id} уже завершён, действия к нему не добавить."

    if actor.id != row["user_id"] and not can_review(actor):
        return "❌ Отмечать действия может только тот, кто ведёт смену."

    body = (body or "").strip()
    if not body:
        return "❌ Пустое действие записывать незачем."

    action, total = await ghost_db.add_action(shift_id, actor.id, str(actor), body)
    if action is None:
        return "⚠️ База недоступна, действие не записалось."

    row = await ghost_db.get_shift(shift_id) or row
    await refresh_card(row)

    thread = await shift_thread(row)
    if thread is not None:
        embed = disnake.Embed(
            title=f"📢 Действие {total}",
            description=body[:2000],
            color=COLOR_INFO,
            timestamp=disnake.utils.utcnow(),
        )
        embed.set_footer(text=f"Отчёт #{shift_id} · {actor}")
        try:
            await thread.send(embed=embed, allowed_mentions=MENTIONS)
        except disnake.HTTPException:
            pass

    logger.info("Действие в %s #%s от %s: %s", row["kind"], shift_id, actor, body[:80])

    return f"📢 Записал. Всего действий за смену: **{total}**."


def build_actions_embed(row, actions) -> disnake.Embed:
    """Хронология действий смены одним сообщением."""
    embed = disnake.Embed(
        title=f"🗒️ Хронология отчёта #{row['id']}",
        color=kind_color(row["kind"]),
    )

    if not actions:
        embed.description = "За смену действий не отмечали."
        return embed

    lines = []
    for action in actions:
        moment = clock(as_local(action["created_at"]))
        lines.append(f"`{moment}` {action['body']}")

    text = "\n".join(lines)
    embed.description = text[:4000] if len(text) <= 4000 else text[:3980] + "\n…"
    embed.set_footer(text=f"Действий: {len(actions)}")

    return embed


#  Проверка отчёта
async def review_shift(shift_id: int, state: str, actor, note: str = "") -> str:
    row = await ghost_db.get_shift(shift_id)
    if row is None:
        return f"❌ Отчёт #{shift_id} не найден."

    if not can_review(actor):
        return "❌ Отчёты проверяют наблюдатели и выше."

    if row["ended_at"] is None:
        return "⚠️ Смена ещё идёт. Проверять можно только завершённый отчёт."

    if row["review_state"] == REVIEW_NONE:
        return "⚠️ Этот отчёт проверять не нужно."

    if state == REVIEW_REJECTED and not (note or "").strip():
        return "❌ Для отказа нужна причина."

    updated = await ghost_db.review_shift(
        shift_id, state, actor.id, str(actor), (note or "").strip() or None
    )
    if updated is None:
        return "⚠️ База недоступна, проверка не записалась."

    await refresh_card(updated)

    thread = await shift_thread(updated)
    if thread is not None:
        text = f"{review_mark(state)} - {actor.mention}"
        if (note or "").strip():
            label = "Заметка" if state == REVIEW_APPROVED else "Причина"
            text += f"\n**{label}:** {note.strip()[:1500]}"
        try:
            await thread.send(text, allowed_mentions=MENTIONS)
        except disnake.HTTPException:
            pass

    logger.info(
        "Отчёт #%s проверен: %s наблюдателем %s (%s)",
        shift_id, state, actor, actor.id,
    )

    head = "✅ Отчёт подтверждён." if state == REVIEW_APPROVED else "❌ Отчёт не подтверждён."
    tail = f"\nЧеловеку видно в карточке: {updated['message_url']}" if updated["message_url"] else ""

    return head + tail


#  Сводка для человека
def build_user_embed(member, kind, summary, days: int) -> disnake.Embed:
    """Что человек наработал за период. Показывается ему же и главам."""
    embed = disnake.Embed(
        title=f"{kind_title(kind)} · {member.display_name}",
        color=kind_color(kind),
    )

    if summary is None:
        embed.description = "База не ответила, цифры показать не могу."
        return embed

    shifts = summary["shifts"] or 0
    if not shifts:
        embed.description = f"За {days} дней ни одной смены. Пора {kind_verb(kind)}."
        return embed

    embed.add_field(name="Смен", value=str(shifts), inline=True)
    embed.add_field(name="Часов", value=hours_text(summary["hours"] or 0), inline=True)
    embed.add_field(
        name="Средняя смена",
        value=hours_text((summary["hours"] or 0) / shifts),
        inline=True,
    )

    if review_needed(kind):
        embed.add_field(name="✅ Подтверждено", value=str(summary["approved"] or 0), inline=True)
        embed.add_field(name="❌ Отклонено", value=str(summary["rejected"] or 0), inline=True)
        embed.add_field(name="🕓 Ждёт проверки", value=str(summary["pending"] or 0), inline=True)

    last = as_local(summary["last_at"])
    if last is not None:
        embed.add_field(name="Последняя смена", value=ts(last, "R"), inline=False)

    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"За последние {days} дней")

    return embed
