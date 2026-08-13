"""
Утилиты работы со временем для системы отпусков.
"""

import re

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from dataConfig import VACATION_TIMEZONE

try:
    TZ = ZoneInfo(VACATION_TIMEZONE)
except Exception:
    print(
        f"[vacation] Часовой пояс {VACATION_TIMEZONE} недоступен, использую UTC+3. "
        f"Поставь базу часовых поясов: pip install tzdata"
    )
    TZ = timezone(timedelta(hours=3), "MSK")

_DATE_FORMATS = (
    "%Y-%m-%d", # 2026-09-01
    "%d.%m.%Y", # 01.09.2026
    "%d.%m.%y", # 01.09.26
    "%d-%m-%Y", # 01-09-2026
    "%d/%m/%Y", # 01/09/2026
    "%Y.%m.%d", # 2026.09.01
)

_TIME_FORMATS = (
    "%H:%M", # 18:30
    "%H:%M:%S", # 18:30:00
)

# Если время не указано, отпуск заканчивается в конце указанных суток
DEFAULT_END_TIME = time(23, 59, 59)



#  Базовые преобразования
def now_local() -> datetime:
    return datetime.now(TZ)


def as_local(value) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, str):
        value = _parse_db_string(value)
        if value is None:
            return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=TZ)
        return value.astimezone(TZ)

    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=TZ)

    return None


def as_local_end(value) -> datetime | None:
    """Дата без времени считается концом суток, иначе отпуск истёк бы в полночь."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return combine(value)
    return as_local(value)


def to_naive_local(value: datetime) -> datetime:
    local = as_local(value)
    return local.replace(tzinfo=None) if local else None


def _parse_db_string(value: str) -> datetime | None:
    """Разбирает дату/время, пришедшие из текстовой колонки."""
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", *_DATE_FORMATS):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None



#  Разбор пользовательского ввода
def parse_date_token(token: str) -> date | None:
    """
    Пробует прочитать аргумент как дату. Поддерживает 2026-09-01, 01.09.2026,
    01.09.26, а также 01.09 - год подставляется ближайший в будущем.
    Возвращает None, если аргумент датой не является.
    """
    token = (token or "").strip()
    if not token:
        return None

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue

    # Короткая запись без года: 01.09 / 01-09 / 01/09
    match = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})", token)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        today = now_local().date()
        for year in (today.year, today.year + 1):
            try:
                candidate = date(year, month, day)
            except ValueError:
                return None
            if candidate >= today:
                return candidate
        return None

    return None


def parse_time_token(token: str) -> time | None:
    """
    Пробует прочитать аргумент как время суток: 18:30 или 18:30:00.
    Возвращает None, если аргумент временем не является.
    """
    token = (token or "").strip()
    if not token:
        return None

    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(token, fmt).time()
        except ValueError:
            continue

    return None


def combine(day: date, moment: time | None = None) -> datetime:
    """
    Собирает дату и время в момент по поясу проекта.
    Без времени берётся конец суток - дата отпуска включительно.
    """
    return datetime.combine(day, moment or DEFAULT_END_TIME, tzinfo=TZ)



#  Форматирование
def plural(number: int, forms: tuple[str, str, str]) -> str:
    """Русская форма слова: plural(5, ('день', 'дня', 'дней')) -> 'дней'."""
    number = abs(number) % 100
    if 11 <= number <= 14:
        return forms[2]
    number %= 10
    if number == 1:
        return forms[0]
    if 2 <= number <= 4:
        return forms[1]
    return forms[2]


def fmt(moment: datetime | None) -> str:
    """Человекочитаемая дата: 01.09.2026 09:00 (МСК)."""
    local = as_local(moment)
    if local is None:
        return "не указано"
    return local.strftime("%d.%m.%Y %H:%M")


def ts(moment: datetime | None, style: str = "f") -> str:
    """Динамическая метка времени Discord: <t:unix:style>."""
    local = as_local(moment)
    if local is None:
        return "-"
    return f"<t:{int(local.timestamp())}:{style}>"


def human_delta(delta: timedelta) -> str:
    """Длительность словами: '14 дней 3 часа'."""
    total = int(delta.total_seconds())
    if total <= 0:
        return "0 часов"

    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60

    parts = []
    if days:
        parts.append(f"{days} {plural(days, ('день', 'дня', 'дней'))}")
    if hours:
        parts.append(f"{hours} {plural(hours, ('час', 'часа', 'часов'))}")
    if not days and not hours and minutes:
        parts.append(f"{minutes} {plural(minutes, ('минута', 'минуты', 'минут'))}")

    return " ".join(parts) or "меньше минуты"
