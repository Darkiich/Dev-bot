from datetime import datetime, timezone

import disnake

COLOR_MAIN = 0x66CCFF
COLOR_OK = 0x57F287
COLOR_WARN = 0xFEE75C
COLOR_ERROR = 0xED4245

BENEFIT_FLAGS = [
    ("Все спонсорские лодауты", "allLoadouts"),
    ("Все спонсорские маркинги", "allMarkings"),
    ("Приоритетный вход", "priorityJoin"),
    ("Свой цвет ника", "allowCustomOocColor"),
    ("Любой цвет призрака", "allowCustomGhostColor"),
]

BENEFIT_LISTS = [
    ("Кроме департаментов", "excludedDepartments"),
    ("Кроме работ", "excludedJobs"),
    ("Лодауты", "loadouts"),
    ("Маркинги", "markings"),
    ("Виды", "species"),
    ("Трейты", "traits"),
]

def main_embed() -> disnake.Embed:
    embed = disnake.Embed(
        title="Спонсорка",
        description=(
            "Управление спонсорскими тирами и выдачами.\n\n"
            "**Игрок** - посмотреть и изменить выдачи конкретного человека.\n"
            "**Тиры** - шаблоны наборов бонусов."
        ),
        color=COLOR_MAIN,
    )
    return embed


def error_embed(message: str) -> disnake.Embed:
    return disnake.Embed(title="Ошибка", description=message, color=COLOR_ERROR)


def ok_embed(message: str) -> disnake.Embed:
    return disnake.Embed(description=f"✅ {message}", color=COLOR_OK)


def player_embed(query: str, data: dict) -> disnake.Embed:
    grants = data.get("grants") or []
    resolved = data.get("resolved")

    embed = disnake.Embed(
        title=f"Спонсорка: {query}",
        color=COLOR_MAIN,
    )

    embed.add_field(name="GUID", value=f"`{data.get('userId')}`", inline=False)

    if not grants:
        embed.add_field(name="Выдачи", value="Их нет.", inline=False)
    else:
        lines = []

        for grant in grants[:15]:
            lines.append(_describe_grant(grant))

        if len(grants) > 15:
            lines.append(f"...и ещё {len(grants) - 15}")

        embed.add_field(name=f"Выдачи ({len(grants)})", value="\n".join(lines), inline=False)

    if resolved is None:
        embed.add_field(
            name="Итоговые бонусы",
            value="Игрок не на сервере.",
            inline=False,
        )
    else:
        embed.add_field(name="Итоговые бонусы", value=_describe_benefits(resolved), inline=False)

    return embed


def tier_list_embed(tiers: list) -> disnake.Embed:
    embed = disnake.Embed(title="Спонсорские тиры", color=COLOR_MAIN)

    if not tiers:
        embed.description = "Тиров нет."
        return embed

    lines = []

    for tier in tiers:
        state = "" if tier.get("enabled", True) else " · **выключен**"
        lines.append(
            f"`{tier['name']}` - {tier.get('displayName') or tier['name']} "
            f"(приоритет {tier.get('priority', 0)}){state}"
        )

    embed.description = "\n".join(lines)
    return embed


def tier_embed(tier: dict) -> disnake.Embed:
    embed = disnake.Embed(
        title=f"Тир: {tier.get('displayName') or tier['name']}",
        description=tier.get("description") or "*без описания*",
        color=COLOR_MAIN if tier.get("enabled", True) else COLOR_WARN,
    )

    embed.add_field(name="ID", value=f"`{tier['name']}`", inline=True)
    embed.add_field(name="Приоритет", value=str(tier.get("priority", 0)), inline=True)
    embed.add_field(name="Состояние", value="включён" if tier.get("enabled", True) else "выключен", inline=True)
    embed.add_field(name="Бонусы", value=_describe_benefits(tier.get("benefits") or {}), inline=False)

    return embed


def _describe_grant(grant: dict) -> str:
    tier = grant.get("tierName") or "без тира"
    expires = grant.get("expiresAt")

    if grant.get("revoked"):
        state = "🚫 отозвана"
    elif _expired(expires):
        state = "⌛ истекла"
    else:
        state = "✅ активна"

    when = "бессрочно" if not expires else f"до {_format_date(expires)}"
    extra = " ⭐" if grant.get("overrides") else ""
    comment = grant.get("comment") or ""

    line = f"`#{grant['id']}` **{tier}**{extra} · {when} · {state}"

    if comment:
        line += f"\n> {comment}"

    return line

def _describe_benefits(benefits: dict) -> str:
    lines = []

    bypass = benefits.get("roleBypass") or "None"

    if bypass != "None":
        lines.append(f"обход ролей: **{bypass}**")

    for label, key in BENEFIT_LISTS:
        values = benefits.get(key) or []

        if not values:
            continue

        shown = ", ".join(values[:8])

        if len(values) > 8:
            shown += f" ...(+{len(values) - 8})"

        lines.append(f"{label}: {shown}")

    for label, key in BENEFIT_FLAGS:
        if benefits.get(key):
            lines.append(f"✅ {label}")

    if benefits.get("oocColor"):
        lines.append(f"цвет ника: `{benefits['oocColor']}`")

    ghost = benefits.get("ghostColors") or []

    if ghost:
        lines.append(f"цвета призрака: {', '.join(f'`{c}`' for c in ghost)}")

    if benefits.get("extraCharacterSlots"):
        lines.append(f"доп. слотов: **{benefits['extraCharacterSlots']}**")

    if not lines:
        return "*пусто*"

    text = "\n".join(lines)

    if len(text) > 1000:
        text = text[:1000] + "\n..."

    return text


def _parse_date(raw):
    if not raw:
        return None

    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_date(raw) -> str:
    if not raw:
        return "бессрочно"

    parsed = _parse_date(raw)
    return parsed.strftime("%d.%m.%Y") if parsed else str(raw)


def _expired(raw) -> bool:
    parsed = _parse_date(raw)

    if parsed is None:
        return False

    now = datetime.now(parsed.tzinfo or timezone.utc)
    return parsed <= now
