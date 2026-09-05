"""
Общая логика кадровой системы: какие роли выдать и снять, эмбеды и отправка
в канал действий глав.

Текущее состояние человека берётся из его ролей в Discord, а не из БД.
БД это журнал для аналитики, если она отвалится, роли всё равно встанут верно.
"""

import disnake

from disnake.ext import commands

from bot_init import bot, team_db
from dataConfig import (
    PROJECT_TEAM_ROLE_ID,
    TEAM_LOG_CHANNEL_ID,
)
from team_departments import (
    DEPARTMENTS,
    department_role_id,
    get_position,
    get_positions,
)

COLOR_HIRE = 0x57F287
COLOR_FIRE = 0xED4245
COLOR_PROMOTE = 0x5865F2
COLOR_DEMOTE = 0xF0B232
COLOR_INFO = 0x5865F2

DEFAULT_REASON = "Причина не указана"

# Роли не пингуем, людей можно
MENTIONS = disnake.AllowedMentions(everyone=False, roles=False, users=True)


#  Текущее состояние по ролям
def member_positions(member: disnake.Member) -> list:
    """Должности участника, вычисленные по его ролям."""
    found = (get_position(role.id) for role in member.roles)
    return [p for p in found if p is not None]


def positions_in(positions: list, department: str) -> list:
    return [p for p in positions if p.department == department]


def top_ladder_position(positions: list, department: str):
    """Высшая занимаемая ступень лестницы отдела или None."""
    ladder = [p for p in positions_in(positions, department) if p.on_ladder]
    return max(ladder, key=lambda p: p.grade) if ladder else None


def resolve_position(role: disnake.Role):
    """Должность по роли или None, если роль не из карты отделов."""
    return get_position(role.id)


def resolve_department(role: disnake.Role) -> str | None:
    """Ключ отдела, если передали общую роль отдела."""
    for key, dept in DEPARTMENTS.items():
        if dept["role_id"] == role.id:
            return key
    return None


def department_headcount(guild: disnake.Guild, department: str) -> set:
    """ID всех, кто держит хотя бы одну должность отдела."""
    people = set()
    for position in get_positions(department):
        role = guild.get_role(position.role_id)
        if role:
            people.update(m.id for m in role.members)
    return people


def department_roster(guild: disnake.Guild, department: str) -> list:
    """Состав отдела по ролям в Discord: список (должность, участники)."""
    roster = []
    for position in sorted(
        get_positions(department),
        key=lambda p: (p.grade is None, -(p.grade or 0)),
    ):
        role = guild.get_role(position.role_id)
        members = sorted(role.members, key=lambda m: m.display_name.lower()) if role else []
        roster.append((position, members))
    return roster


def find_team_guild():
    """Сервер, на котором живут кадровые роли."""
    if PROJECT_TEAM_ROLE_ID:
        for guild in bot.guilds:
            if guild.get_role(PROJECT_TEAM_ROLE_ID):
                return guild

    channel = bot.get_channel(TEAM_LOG_CHANNEL_ID)
    return getattr(channel, "guild", None)


def collect_import_rows(guild: disnake.Guild) -> list:
    """Все, кто держит должностные роли: (ds_id, ds_name, должность)."""
    rows = []
    for key in DEPARTMENTS:
        for position, members in department_roster(guild, key):
            rows.extend((m.id, str(m), position) for m in members)
    return rows


def role_gaps(guild: disnake.Guild) -> tuple[int, int]:
    """Сколько людей с должностью сидят без роли отдела и без общей роли."""
    no_department, no_team = set(), set()

    for key in DEPARTMENTS:
        dept_role_id = department_role_id(key)
        for position, members in department_roster(guild, key):
            for member in members:
                held = {role.id for role in member.roles}
                if dept_role_id and dept_role_id not in held:
                    no_department.add(member.id)
                if PROJECT_TEAM_ROLE_ID and PROJECT_TEAM_ROLE_ID not in held:
                    no_team.add(member.id)

    return len(no_department), len(no_team)


#  Работа с ролями
def role_manage_problem(guild: disnake.Guild, role: disnake.Role) -> str | None:
    """Почему бот не сможет тронуть роль. None если препятствий нет."""
    me = guild.me

    if me is None:
        return "бот не найден среди участников сервера"

    if not me.guild_permissions.manage_roles:
        return "у бота нет права «Управление ролями»"

    if role.managed:
        return f"роль «{role.name}» управляется интеграцией, вручную её не выдать"

    if role >= me.top_role:
        return f"роль «{role.name}» не ниже роли бота «{me.top_role.name}», подними бота выше"

    return None


def audit_reason(actor, action: str, reason: str = "") -> str:
    """Строка для журнала аудита Discord, у него лимит в 512 символов."""
    text = f"{action}, оформил {actor}"
    if reason and reason != DEFAULT_REASON:
        text += f". {reason}"
    return text[:500]


async def apply_roles(member: disnake.Member, add_ids, remove_ids, reason: str) -> list:
    """
    Выдаёт и снимает роли. Возвращает список замечаний, пустой список - всё чисто.
    Роли, которые уже в нужном состоянии, пропускаются молча.
    """
    guild = member.guild
    current = {role.id for role in member.roles}
    notes = []

    def prepare(ids, needed: bool):
        picked = []
        for role_id in ids:
            if not role_id:
                continue
            role_id = int(role_id)
            if (role_id in current) == needed:
                continue

            role = guild.get_role(role_id)
            if role is None:
                notes.append(f"роль с ID {role_id} не найдена на сервере")
                continue

            problem = role_manage_problem(guild, role)
            if problem:
                notes.append(problem)
                continue

            picked.append(role)
        return picked

    to_add = prepare(add_ids, needed=True)
    to_remove = prepare(remove_ids, needed=False)

    if to_add:
        try:
            await member.add_roles(*to_add, reason=reason)
        except disnake.Forbidden:
            notes.append(f"Discord не дал выдать роли: {role_names(to_add)}")
        except disnake.HTTPException as e:
            notes.append(f"ошибка Discord при выдаче ролей: {e}")

    if to_remove:
        try:
            await member.remove_roles(*to_remove, reason=reason)
        except disnake.Forbidden:
            notes.append(f"Discord не дал снять роли: {role_names(to_remove)}")
        except disnake.HTTPException as e:
            notes.append(f"ошибка Discord при снятии ролей: {e}")

    return notes


def role_names(roles: list) -> str:
    return ", ".join(f"«{role.name}»" for role in roles)


#  Кадровые действия
async def do_hire(member: disnake.Member, position, actor, reason: str = "") -> list:
    """Выдаёт должность, роль отдела и общую роль команды."""
    return await apply_roles(
        member,
        add_ids=[position.role_id, department_role_id(position.department), PROJECT_TEAM_ROLE_ID],
        remove_ids=[],
        reason=audit_reason(actor, f"Найм: {position.name}", reason),
    )


async def do_fire(member: disnake.Member, position, actor, reason: str = "") -> tuple[list, bool, bool]:
    """
    Снимает должность. Роль отдела снимается, только если в отделе больше
    ничего не осталось, общая роль команды - если не осталось должностей вообще.
    Возвращает (замечания, ушёл_из_отдела, ушёл_из_команды).
    """
    left = [p for p in member_positions(member) if p.role_id != position.role_id]
    remove = [position.role_id]

    left_department = not positions_in(left, position.department)
    if left_department:
        remove.append(department_role_id(position.department))

    # Общая роль держится ровно на должностях. Пока есть хоть одна в любом
    # отделе - человек в команде, не осталось ни одной - снимаем вместе с остальным.
    left_team = not left
    if left_team:
        remove.append(PROJECT_TEAM_ROLE_ID)

    notes = await apply_roles(
        member,
        add_ids=[],
        remove_ids=remove,
        reason=audit_reason(actor, f"Увольнение: {position.name}", reason),
    )
    return notes, left_department, left_team


async def do_move(member: disnake.Member, old, new, actor, action: str, reason: str = "") -> list:
    """Меняет должность внутри отдела. Роль отдела и общая роль остаются."""
    label = "Повышение" if action == "promote" else "Понижение"
    return await apply_roles(
        member,
        add_ids=[new.role_id, department_role_id(new.department), PROJECT_TEAM_ROLE_ID],
        remove_ids=[old.role_id],
        reason=audit_reason(actor, f"{label}: {old.name} -> {new.name}", reason),
    )


def check_move(member: disnake.Member, target, action: str) -> tuple:
    """
    Проверяет, можно ли двигать участника на должность target.
    Возвращает (текущая должность, текст ошибки).
    """
    if not target.on_ladder:
        return None, (
            f"«{target.name}» стоит вне карьерной лестницы, "
            "повышением её выдача не считается. Используй `&hire` и `&fire`."
        )

    positions = member_positions(member)
    current = top_ladder_position(positions, target.department)

    if current is None:
        return None, (
            f"{member.mention} не занимает должность в отделе «{target.department_name}». "
            "Сначала найм через `&hire`."
        )

    if current.role_id == target.role_id:
        return None, f"{member.mention} уже на должности «{target.name}»."

    if action == "promote" and target.grade < current.grade:
        return None, (
            f"«{target.name}» ниже, чем «{current.name}». Это понижение, используй `&demote`."
        )

    if action == "demote" and target.grade > current.grade:
        return None, (
            f"«{target.name}» выше, чем «{current.name}». Это повышение, используй `&promote`."
        )

    return current, None


def actor_problem(actor, member: disnake.Member, action: str) -> str | None:
    """
    Кого этому главе трогать нельзя. None если можно.

    Разрешение на саму команду даёт ROLE_ACCESS_HEADS, а это про цель:
    над собой действий не проводим, и выше себя не лезем. Старшинство
    считается по порядку ролей на сервере, как и вся модерация в Discord.
    """
    if getattr(member, "bot", False):
        return "Ботов кадровая система не касается."

    if actor.id == member.id:
        label = {"hire": "нанять", "fire": "уволить"}.get(action, "двигать")
        return f"Себя {label} нельзя, попроси другого главу."

    guild = member.guild

    if guild.owner_id == member.id:
        return "Владельца сервера трогать нельзя."

    # Владельцу можно всё, у него роли могут быть какие угодно
    if actor.id == guild.owner_id:
        return None

    author = guild.get_member(actor.id) or actor
    top = getattr(author, "top_role", None)

    if top is None:
        return None

    if member.top_role >= top:
        return (
            f"У {member.mention} роль «{member.top_role.name}» не ниже твоей "
            f"«{top.name}». Это должен делать кто-то выше."
        )

    return None


def check_hire(member: disnake.Member, position) -> str | None:
    """Текст ошибки, если найм на эту должность не имеет смысла."""
    if position.role_id in {role.id for role in member.roles}:
        return f"{member.mention} уже на должности «{position.name}»."

    if position.on_ladder:
        current = top_ladder_position(member_positions(member), position.department)
        if current is not None:
            return (
                f"{member.mention} уже в отделе «{position.department_name}» "
                f"на должности «{current.name}». Для смены ступени используй "
                "`&promote` или `&demote`."
            )

    return None


def check_fire(member: disnake.Member, position) -> str | None:
    """Текст ошибки, если снимать нечего."""
    if position.role_id not in {role.id for role in member.roles}:
        return f"У {member.mention} нет должности «{position.name}»."
    return None


#  Эмбеды
def _base(title: str, description: str, color: int, member, position, actor, reason: str):
    embed = disnake.Embed(title=title, description=description, color=color)
    embed.add_field(name="Отдел", value=position.department_name, inline=True)
    embed.add_field(name="Кто оформил", value=actor.mention, inline=True)
    embed.add_field(name="Причина", value=reason or DEFAULT_REASON, inline=False)

    if member is not None:
        embed.set_thumbnail(url=member.display_avatar.url)

    return embed


def build_hire_embed(member, position, actor, reason="") -> disnake.Embed:
    return _base(
        "📥 Найм",
        f"{member.mention} принят на должность **{position.name}**",
        COLOR_HIRE, member, position, actor, reason,
    )


def build_fire_embed(member, position, actor, reason="", left_department=False) -> disnake.Embed:
    description = f"{member.mention} снят с должности **{position.name}**"
    if left_department:
        description += f"\nОтдел «{position.department_name}» покинут"

    return _base("📤 Увольнение", description, COLOR_FIRE, member, position, actor, reason)


def build_move_embed(member, old, new, actor, action: str, reason="") -> disnake.Embed:
    up = action == "promote"
    return _base(
        "📈 Повышение" if up else "📉 Понижение",
        f"{member.mention}\n**{old.name}** → **{new.name}**",
        COLOR_PROMOTE if up else COLOR_DEMOTE,
        member, new, actor, reason,
    )


#  Отправка в канал действий глав
async def announce(embed: disnake.Embed) -> bool:
    """Пишет эмбед в канал кадровых действий. True при успехе."""
    if not TEAM_LOG_CHANNEL_ID:
        print("[team] TEAM_LOG_CHANNEL_ID не задан в конфиге.")
        return False

    channel = bot.get_channel(TEAM_LOG_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(TEAM_LOG_CHANNEL_ID)
        except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException) as e:
            print(f"[team] Канал {TEAM_LOG_CHANNEL_ID} недоступен: {e}")
            return False

    try:
        await channel.send(embed=embed)
        return True
    except (disnake.Forbidden, disnake.HTTPException) as e:
        print(f"[team] Не удалось отправить сообщение в канал: {e}")
        return False


#  Полный цикл действия: проверки, роли, запись в БД, сообщение в канал.
#  Сюда же ходит интерактивное меню, чтобы логика была ровно одна.
async def perform_hire(member: disnake.Member, role: disnake.Role, actor, reason: str = ""):
    """Возвращает текст ответа для того, кто вызвал действие."""
    position = resolve_position(role)
    if position is None:
        return unknown_role_text(role)

    error = actor_problem(actor, member, "hire") or check_hire(member, position)
    if error:
        return f"❌ {error}"

    notes = await do_hire(member, position, actor, reason)

    ok_db, info = await team_db.record_hire(
        member.id, str(member), position, actor.id, str(actor), reason or None,
    )
    sent = await announce(build_hire_embed(member, position, actor, reason))

    return result_lines(
        f"✅ {member.mention} принят в «{position.department_name}» на должность «{position.name}».",
        notes, "" if ok_db else info, sent,
    )


async def perform_fire(member: disnake.Member, role: disnake.Role, actor, reason: str = ""):
    position = resolve_position(role)
    if position is None:
        return unknown_role_text(role, member)

    error = actor_problem(actor, member, "fire") or check_fire(member, position)
    if error:
        return f"❌ {error}"

    notes, left_department, left_team = await do_fire(member, position, actor, reason)

    ok_db, info = await team_db.record_fire(
        member.id, str(member), position, actor.id, str(actor), reason or None,
    )
    sent = await announce(
        build_fire_embed(member, position, actor, reason, left_department)
    )

    head = f"✅ {member.mention} снят с должности «{position.name}»."
    if left_department:
        head += f" Роль отдела «{position.department_name}» снята."
    if left_team:
        head += " Роль команды проекта снята."

    return result_lines(head, notes, "" if ok_db else info, sent)


async def perform_move(member: disnake.Member, role: disnake.Role, actor,
                       action: str, reason: str = ""):
    position = resolve_position(role)
    if position is None:
        return unknown_role_text(role)

    error = actor_problem(actor, member, action)
    if error:
        return f"❌ {error}"

    current, error = check_move(member, position, action)
    if error:
        return f"❌ {error}"

    notes = await do_move(member, current, position, actor, action, reason)

    ok_db, info = await team_db.record_move(
        member.id, str(member), current, position,
        actor.id, str(actor), action, reason or None,
    )
    sent = await announce(build_move_embed(member, current, position, actor, action, reason))

    label = "повышен" if action == "promote" else "понижен"
    return result_lines(
        f"✅ {member.mention} {label}: «{current.name}» → «{position.name}».",
        notes, "" if ok_db else info, sent,
    )


def unknown_role_text(role: disnake.Role, member: disnake.Member = None) -> str:
    """Понятный ответ, когда указали роль, которой нет в карте должностей."""
    department = resolve_department(role)

    if department is None:
        return (
            f"❌ Роль {role.mention} не привязана ни к одной должности.\n"
            "Список должностей - `&team_help`."
        )

    text = (
        f"❌ {role.mention} это общая роль отдела, а не должность. "
        "Укажи конкретную должность."
    )

    if member is not None:
        mine = positions_in(member_positions(member), department)
        if mine:
            text += "\nУ участника в этом отделе: " + ", ".join(f"«{p.name}»" for p in mine)

    return text


#  Сборка ответа команде
def result_lines(head: str, notes: list, db_error: str = "", announced: bool = True) -> str:
    """Собирает ответ главе: результат плюс всё, что пошло не так."""
    lines = [head]

    for note in dict.fromkeys(notes):
        lines.append(f"⚠️ {note}")

    if db_error:
        lines.append(f"⚠️ Действие не записано в БД: `{db_error}`")

    if not announced:
        lines.append("⚠️ Не удалось написать в канал кадровых действий.")

    return "\n".join(lines)


def command_error_text(error, usage: str) -> str | None:
    """Ответ на кривые аргументы. None - промолчать."""
    if isinstance(error, commands.MissingAnyRole):
        return None

    if isinstance(error, commands.MissingRequiredArgument):
        return f"❌ Не хватает аргументов.\n\n{usage}"

    if isinstance(error, commands.MemberNotFound):
        return f"❌ Участник `{error.argument}` не найден на сервере.\n\n{usage}"

    if isinstance(error, commands.RoleNotFound):
        return (
            f"❌ Роль `{error.argument}` не найдена. Упомяни роль или укажи её ID, "
            "название из нескольких слов бери в кавычки.\n\n" + usage
        )

    if isinstance(error, commands.BadArgument):
        return f"❌ Неверный аргумент: {error}\n\n{usage}"

    return f"❗ Ошибка: `{error}`"
