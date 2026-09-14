"""
Карточка персонажа. Поле добавляется, только если колонка есть в базе
"""

import logging

import disnake

from bot_init import stats_db
from dataConfig import PLAYER_STATS_SERVER
from player_jobs import job_name, pretty_id, sex_name, species_name, trait_name
from player_service import COLOR_MAIN

logger = logging.getLogger(__name__)

FLAVOR_LIMIT = 900
FIELD_LIMIT = 1024

# В базе приоритет числом: 3 - высокий, 1 - низкий
PRIORITY_TITLES = {3: "🟢 Высокий", 2: "🟡 Средний", 1: "⚪ Низкий"}

GENDERS = {
    "male": "мужской",
    "female": "женский",
    "epicene": "они",
    "neuter": "оно",
}


def name_of(row) -> str:
    return (row["char_name"] or "Без имени").strip()


def _value(row, fields: set, column: str):
    return row[column] if column in fields else None


def _hex(value) -> str | None:
    """Цвет из базы приводим к виду #RRGGBB."""
    text = str(value or "").strip()
    if not text:
        return None
    if not text.startswith("#"):
        text = "#" + text
    return text.upper()[:9]


def _color(row, fields: set) -> int:
    """Цвет эмбеда берём из глаз персонажа, чтобы карточки не были одинаковыми."""
    raw = _hex(_value(row, fields, "eye_color"))
    if not raw:
        return COLOR_MAIN

    try:
        return int(raw.lstrip("#")[:6], 16)
    except ValueError:
        return COLOR_MAIN


def _voice(row, fields: set) -> str:
    """Голос TTS и барк персонажа."""
    parts = []

    voice = _value(row, fields, "voice")
    if voice:
        parts.append(f"TTS: **{pretty_id(str(voice))}**")

    bark = _value(row, fields, "bark_proto")
    if bark:
        pitch = _value(row, fields, "bark_pitch")
        tone = f" (тон {float(pitch):.2f})" if pitch else ""
        parts.append(f"Барк: **{pretty_id(str(bark))}**{tone}")

    return " · ".join(parts)


def _appearance(row, fields: set) -> str:
    """Цвета и причёска. Строка собирается из того, что нашлось."""
    parts = []

    hair = _hex(_value(row, fields, "hair_color"))
    if hair:
        parts.append(f"Волосы: `{hair}`")

    eyes = _hex(_value(row, fields, "eye_color"))
    if eyes:
        parts.append(f"Глаза: `{eyes}`")

    skin = _hex(_value(row, fields, "skin_color"))
    if skin:
        parts.append(f"Кожа: `{skin}`")

    lines = [" · ".join(parts)] if parts else []

    styles = []
    hair_style = pretty_id(_value(row, fields, "hair_name"))
    if hair_style:
        styles.append(f"Причёска: {hair_style}")

    beard = pretty_id(_value(row, fields, "facial_hair_name"))
    if beard:
        styles.append(f"Борода: {beard}")

    if styles:
        lines.append(" · ".join(styles))

    size = []
    height = _value(row, fields, "height")
    width = _value(row, fields, "width")
    if height:
        size.append(f"рост {float(height):.2f}")
    if width:
        size.append(f"ширина {float(width):.2f}")
    if size:
        lines.append("Телосложение: " + ", ".join(size))

    return "\n".join(lines)


def _jobs(extras: dict) -> str:
    """Роли по приоритетам: сначала высокий, потом средний."""
    jobs = extras.get("jobs") or []
    if not jobs:
        return ""

    grouped = {}
    for name, priority in jobs:
        grouped.setdefault(priority, []).append(job_name(name))

    lines = []
    for priority in sorted(grouped, key=lambda value: (value is None, -(value or 0))):
        title = PRIORITY_TITLES.get(priority, "Выбраны")
        lines.append(f"{title}: {', '.join(sorted(grouped[priority]))}")

    return "\n".join(lines)[:FIELD_LIMIT]


def _traits(extras: dict) -> str:
    traits = extras.get("traits") or []
    if not traits:
        return ""
    return ", ".join(trait_name(trait) for trait in traits)[:FIELD_LIMIT]


async def build_card(row, owner: str | None) -> disnake.Embed:
    """Собирает карточку персонажа, дотягивая роли и черты из базы."""
    fields = set(row.keys())

    try:
        extras = await stats_db.character_extras(_value(row, fields, "profile_id"), PLAYER_STATS_SERVER)
    except Exception as e:
        logger.warning("Не удалось получить роли и черты персонажа: %s", e)
        extras = {}

    embed = disnake.Embed(title=f"🪪 {name_of(row)}", color=_color(row, fields))

    if "species" in fields:
        embed.add_field(name="Раса", value=species_name(row["species"]), inline=True)
    if _value(row, fields, "age") is not None:
        embed.add_field(name="Возраст", value=str(row["age"]), inline=True)
    if "sex" in fields:
        embed.add_field(name="Пол", value=sex_name(row["sex"]), inline=True)

    gender = str(_value(row, fields, "gender") or "").strip().lower()
    if gender and gender != str(_value(row, fields, "sex") or "").strip().lower():
        embed.add_field(name="Обращение", value=GENDERS.get(gender, gender), inline=True)

    voice = _voice(row, fields)
    if voice:
        embed.add_field(name="Голос", value=voice, inline=False)

    appearance = _appearance(row, fields)
    if appearance:
        embed.add_field(name="Внешность", value=appearance, inline=False)

    jobs = _jobs(extras)
    if jobs:
        embed.add_field(name="Приоритеты ролей", value=jobs, inline=False)

    traits = _traits(extras)
    if traits:
        embed.add_field(name="Черты", value=traits, inline=False)

    flavor = (row["flavor_text"] or "").strip() if "flavor_text" in fields else ""
    if flavor:
        embed.add_field(
            name="Описание",
            value=flavor[:FLAVOR_LIMIT] + ("..." if len(flavor) > FLAVOR_LIMIT else ""),
            inline=False,
        )

    if owner:
        embed.set_footer(text=f"Персонаж игрока {owner}")
    else:
        embed.set_footer(text="Кто играет за этого персонажа - не показываю")

    return embed
