"""
Справочник гост-отчётов: виды смен, статусы, разбор времени и чисел.
"""

import re

from datetime import datetime, timedelta

from vacation_time import TZ, now_local, plural

#  Виды смен
AGHOST = "aghost"
EGHOST = "eghost"

KINDS = {
    AGHOST: {
        "name": "Агост",
        "title": "🛡️ Агост",
        "emoji": "🛡️",
        "verb": "агостить",
        "department": "moderation",
        "color": 0x5865F2,
    },
    EGHOST: {
        "name": "Игост",
        "title": "🎭 Игост",
        "emoji": "🎭",
        "verb": "игостить",
        "department": "event",
        "color": 0x9B59B6,
    },
}

COLOR_INFO = 0x5865F2
COLOR_OK = 0x57F287
COLOR_WARN = 0xF0B232
COLOR_BAD = 0xED4245
COLOR_LIVE = 0x3BA55D

#  Состояния проверки
REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
REVIEW_REJECTED = "rejected"
REVIEW_NONE = "none"

REVIEW_LABELS = {
    REVIEW_PENDING: ("🕓", "Ждёт проверки", COLOR_WARN),
    REVIEW_APPROVED: ("✅", "Подтверждён", COLOR_OK),
    REVIEW_REJECTED: ("❌", "Не подтверждён", COLOR_BAD),
    REVIEW_NONE: ("➖", "Проверка не требуется", COLOR_INFO),
}


def kind_name(kind: str) -> str:
    return KINDS.get(kind, {}).get("name", kind)


def kind_title(kind: str) -> str:
    return KINDS.get(kind, {}).get("title", kind)


def kind_emoji(kind: str) -> str:
    return KINDS.get(kind, {}).get("emoji", "•")


def kind_verb(kind: str) -> str:
    return KINDS.get(kind, {}).get("verb", "работать")


def kind_color(kind: str) -> int:
    return KINDS.get(kind, {}).get("color", COLOR_INFO)


def kind_department(kind: str) -> str:
    return KINDS.get(kind, {}).get("department", "")


def review_mark(state: str) -> str:
    emoji, label, _ = REVIEW_LABELS.get(state, REVIEW_LABELS[REVIEW_PENDING])
    return f"{emoji} {label}"


def review_color(state: str) -> int:
    return REVIEW_LABELS.get(state, REVIEW_LABELS[REVIEW_PENDING])[2]


#  Режим раунда
# Название режима бот берёт из /status
def clean_preset(text: str) -> str:
    """Приводит режим к одной строке: лишние пробелы и переносы ни к чему."""
    return re.sub(r"\s+", " ", (text or "").strip())[:150]


def split_preset(text: str) -> tuple[str, str]:
    text = clean_preset(text)

    match = re.search(r"^(.*?)\s*\(([^()]*)\)\s*$", text)
    if match and match.group(1).strip():
        return match.group(1).strip(), match.group(2).strip()

    return text, ""


def preset_line(preset: str, note: str = "") -> str:
    preset = clean_preset(preset) or "не указан"
    note = clean_preset(note)
    return f"{preset} ({note})" if note else preset


#  Ивент на раунд
# Пусто - значит ивента не планируется, отдельной галочки не нужно
_URL = re.compile(r"https?://\S+")


def has_event(text: str) -> bool:
    return bool((text or "").strip())


def event_line(text: str) -> str:
    """Ивент для карточки. Пустое поле это тоже ответ, а не пропуск."""
    text = (text or "").strip()
    if not text:
        return "➖ Не планируется"

    mark = "🔗" if _URL.search(text) else "✨"
    return f"{mark} {text}"[:1000]


#  Время начала и окончания смены
_NOW_WORDS = {"сейчас", "now", "-", "\u2014", ""}

_CLOCK = re.compile(r"^(\d{1,2})[:.\- ](\d{2})$")


def parse_start(token: str, reference: datetime = None) -> tuple[datetime | None, str | None]:
    """
    Читает время начала: "21:16", "21.16", "2116" или "сейчас".

    Возвращает (момент, ошибка)
    """
    reference = reference or now_local()
    text = (token or "").strip().lower()

    if text in _NOW_WORDS:
        return reference, None

    match = _CLOCK.match(text)
    if match is None and text.isdigit() and len(text) == 4:
        match = _CLOCK.match(f"{text[:2]}:{text[2:]}")

    if match is None:
        return None, "Время не понял. Пиши `21:16` или `сейчас`."

    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None, "Таких часов не бывает. Пиши `21:16` или `сейчас`."

    moment = reference.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # Начало в будущем это всегда вчерашняя смена
    if moment > reference + timedelta(minutes=5):
        moment -= timedelta(days=1)

    if reference - moment > timedelta(hours=24):
        return None, "Начало старше суток. Открывай смену в тот же день."

    return moment, None


def parse_end(token: str, started_at: datetime,
              reference: datetime = None) -> tuple[datetime | None, str | None]:
    """
    Время окончания смены. Читается так же, как начало, но отсчитывается
    от начала: смена, начатая в 23:40 и закрытая в 00:20, длится 40 минут,
    а не минус двадцать три часа.
    """
    reference = reference or now_local()
    text = (token or "").strip().lower()

    if text in _NOW_WORDS:
        return reference, None

    moment, problem = parse_start(text, reference)
    if problem:
        return None, problem

    if moment < started_at:
        shifted = moment + timedelta(days=1)
        if shifted <= reference + timedelta(minutes=5):
            moment = shifted

    if moment < started_at:
        return None, "Окончание раньше начала смены."

    return moment, None


def parse_number(token: str, name: str, limit: int = 1_000_000) -> tuple[int | None, str | None]:
    """Целое число из поля формы. Пусто это None, а не ноль."""
    text = (token or "").strip()
    if not text:
        return None, None

    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return None, f"{name}: нужно число, а пришло «{text[:40]}»."

    value = int(digits)
    if value > limit:
        return None, f"{name}: {value} это слишком много."

    return value, None


#  Длительность
def duration_text(started_at: datetime, ended_at: datetime = None) -> str:
    """Длительность смены словами. Незакрытая считается до текущего момента."""
    if started_at is None:
        return "неизвестно"

    end = ended_at or now_local()
    total = int((end - started_at).total_seconds())

    if total < 60:
        return "меньше минуты"

    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60

    parts = []
    if hours:
        parts.append(f"{hours} {plural(hours, ('час', 'часа', 'часов'))}")
    if minutes:
        parts.append(f"{minutes} {plural(minutes, ('минута', 'минуты', 'минут'))}")

    return " ".join(parts)


def hours_text(hours: float) -> str:
    """Часы словами для аналитики: 12.5 -> "12 ч 30 мин"."""
    total = int(round((hours or 0) * 60))
    if total <= 0:
        return "0 мин"

    whole, minutes = divmod(total, 60)
    if not whole:
        return f"{minutes} мин"
    if not minutes:
        return f"{whole} ч"

    return f"{whole} ч {minutes:02d} мин"


def clock(moment: datetime | None) -> str:
    """Время суток по поясу проекта: 21:16."""
    if moment is None:
        return "-"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=TZ)
    return moment.astimezone(TZ).strftime("%H:%M")
