"""
Правила модерации Discord: сроки наказаний и меры наказания за варны.

Здесь только правила и справочники, никакой работы с Discord и БД
"""

import re

from datetime import timedelta

from dataConfig import MOD_WARN_MEASURES
from vacation_time import human_delta

#  Действия модерации
ACTIONS = {
    "warn": ("⚠️", "Предупреждение", 0xF0B232, True),
    "mute": ("🔇", "Мут", 0xE67E22, True),
    "unmute": ("🔊", "Мут снят", 0x57F287, True),
    "kick": ("👢", "Кик", 0xE74C3C, True),
    "ban": ("🔨", "Бан", 0xED4245, True),
    "unban": ("🕊️", "Разбан", 0x57F287, False),
    "softban": ("🧹", "Софт-бан", 0xE67E22, True),
    "unwarn": ("✅", "Варн снят", 0x57F287, True),
    "note": ("📝", "Заметка", 0x5865F2, False),
    "lock": ("🔒", "Канал закрыт", 0xE67E22, False),
    "unlock": ("🔓", "Канал открыт", 0x57F287, False),

    # Действия, сделанные руками через интерфейс Discord
    "timeout": ("⏳", "Тайм-аут Discord", 0xE67E22, False),
    "untimeout": ("⌛", "Тайм-аут снят", 0x57F287, False),
    "nick": ("🏷️", "Ник изменён", 0x5865F2, False),
    "purge": ("🗑️", "Сообщения удалены", 0x5865F2, False),
    "prune": ("🧽", "Чистка неактивных", 0xE67E22, False),
    "voice_kick": ("🔌", "Отключён из голосового", 0xE67E22, False),
    "voice_move": ("↔️", "Перемещён в голосовом", 0x5865F2, False),
    "voice_mute": ("🎙️", "Заглушен в голосовом", 0xE67E22, False),
    "voice_unmute": ("🔈", "Голос возвращён", 0x57F287, False),
    "voice_deaf": ("🎧", "Оглушён в голосовом", 0xE67E22, False),
    "voice_undeaf": ("👂", "Слух возвращён", 0x57F287, False),
}

# Наказания, которые можно отменить кнопкой в карточке кейса
REVOCABLE = ("warn", "mute", "ban")

# Наказания, которые истекают сами и которые снимает фоновая задача
TIMED = ("mute", "ban")

COLOR_INFO = 0x5865F2
COLOR_OK = 0x57F287
COLOR_WARN = 0xF0B232
COLOR_BAD = 0xED4245

DEFAULT_REASON = "Причина не указана"

# Дольше этого срока наказание считаем вечным, чтобы не ловить переполнение дат
MAX_DURATION = timedelta(days=3650)


def action_emoji(action: str) -> str:
    return ACTIONS.get(action, ("•",))[0]


def action_name(action: str) -> str:
    data = ACTIONS.get(action)
    return data[1] if data else action


def action_color(action: str) -> int:
    data = ACTIONS.get(action)
    return data[2] if data else COLOR_INFO


def action_notifies(action: str) -> bool:
    data = ACTIONS.get(action)
    return data[3] if data else False


def action_title(action: str) -> str:
    return f"{action_emoji(action)} {action_name(action)}"


#  Длительности
#  Пишутся как 10m, 2h, 3d, 1w или 10м, 2ч, 3д
_UNITS = {
    "s": 1, "sec": 1, "с": 1, "сек": 1,
    "m": 60, "min": 60, "м": 60, "мин": 60,
    "h": 3600, "hour": 3600, "ч": 3600, "час": 3600,
    "d": 86400, "day": 86400, "д": 86400, "дн": 86400, "день": 86400,
    "w": 604800, "week": 604800, "н": 604800, "нед": 604800,
    "mo": 2592000, "mon": 2592000, "мес": 2592000,
    "y": 31536000, "г": 31536000, "год": 31536000,
}

_FOREVER = {"перм", "навсегда", "вечно", "forever", "perm", "permanent", "inf", "∞"}

_TOKEN = re.compile(r"(\d+)\s*([a-zA-Zа-яё]*)", re.IGNORECASE)


def is_forever(token: str) -> bool:
    """Просили ли наказание без срока."""
    return (token or "").strip().lower() in _FOREVER


def parse_duration(token: str) -> timedelta | None:
    """
    Читает срок наказания. None означает это не срок, а не навсегда:
    вечность проверяется отдельно через is_forever, иначе опечатку в причине
    легко принять за пожизненный бан.
    """
    text = (token or "").strip().lower().replace(" ", "")
    if not text:
        return None

    total = 0
    position = 0

    for match in _TOKEN.finditer(text):
        # Между числами не должно быть ничего лишнего, иначе это не срок,
        # а обычное слово из причины
        if match.start() != position:
            return None

        value, unit = int(match.group(1)), match.group(2)
        seconds = 60 if unit == "" else _UNITS.get(unit)
        if seconds is None:
            return None

        total += value * seconds
        position = match.end()

    if position != len(text) or total <= 0:
        return None

    return min(timedelta(seconds=total), MAX_DURATION)


def looks_like_duration(token: str) -> bool:
    """Аргумент похож на срок, а не на начало причины."""
    return is_forever(token) or parse_duration(token) is not None


def split_duration(text: str, default: str = "") -> tuple[timedelta | None, str, bool]:
    """
    Отделяет срок от причины: «2h флуд в чате» -> (2 часа, 'флуд в чате', True).

    Возвращает (срок, причина, был_ли_срок_указан). Срок None это «навсегда»:
    для бана вечный, для варна без срока давности.
    """
    text = (text or "").strip()
    if not text:
        return parse_duration(default) if default else None, "", False

    head, _, tail = text.partition(" ")

    if is_forever(head):
        return None, tail.strip(), True

    duration = parse_duration(head)
    if duration is not None:
        return duration, tail.strip(), True

    return (parse_duration(default) if default else None), text, False


#  Меры наказания за варны
def term_text(duration: str) -> str:
    """Срок словами: '1h' -> 'на 1 час', пусто -> 'навсегда'."""
    if not duration:
        return "навсегда"

    delta = parse_duration(duration)
    return f"на {human_delta(delta)}" if delta else f"на {duration}"


def escalation_for(warn_count: int) -> tuple[str, str] | None:
    """
    Что выдать за N-й активный варн: ('mute', '1h') или None.
    Ступени берутся из MOD_WARN_MEASURES, срабатывает точное совпадение,
    а сверх последней ступени - её же действие.
    """
    if not MOD_WARN_MEASURES:
        return None

    steps = sorted(MOD_WARN_MEASURES)

    if warn_count in MOD_WARN_MEASURES:
        return MOD_WARN_MEASURES[warn_count]

    top = steps[-1]
    if warn_count > top:
        return MOD_WARN_MEASURES[top]

    return None


def measures_text() -> str:
    """Меры наказания словами, для справки и карточки участника."""
    if not MOD_WARN_MEASURES:
        return "Автоматическая эскалация выключена."

    lines = []
    for count in sorted(MOD_WARN_MEASURES):
        action, duration = MOD_WARN_MEASURES[count]
        lines.append(f"**{count}-й варн** → {action_name(action).lower()} {term_text(duration)}")

    return "\n".join(lines)
