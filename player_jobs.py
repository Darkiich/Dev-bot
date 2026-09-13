"""
Роли SS14: перевод трекеров времени в названия и отделы.

Своя роль сервера дописывается в JOBS, незнакомая покажется как есть.
"""

import re

OVERALL = "Overall"

# Не роли, в списки не попадают
SERVICE_TRACKERS = {"overall", "admin", "admintime", "observer", "ghost"}

DEPARTMENTS = (
    ("command", "🎖️ Командование"),
    ("security", "🚔 Служба безопасности"),
    ("engineering", "🔧 Инженерный отдел"),
    ("medical", "💉 Медицинский отдел"),
    ("science", "🔬 Научный отдел"),
    ("supply", "📦 Снабжение"),
    ("service", "🍸 Сервис"),
    ("silicon", "🤖 Синтетики"),
    ("other", "📁 Прочее"),
)

DEPARTMENT_NAMES = dict(DEPARTMENTS)

# Ключ - трекер без префикса Job и в нижнем регистре
JOBS = {
    # Командование
    "captain": ("Капитан", "command"),
    "headofpersonnel": ("Глава персонала", "command"),
    "headofsecurity": ("Глава службы безопасности", "command"),
    "chiefengineer": ("Старший инженер", "command"),
    "chiefmedicalofficer": ("Главный врач", "command"),
    "researchdirector": ("Научный руководитель", "command"),
    "quartermaster": ("Квартирмейстер", "command"),
    "blueshield": ("Офицер синего щита", "command"),
    "magistrate": ("Магистрат", "command"),

    # Служба безопасности
    "securityofficer": ("Офицер СБ", "security"),
    "securitycadet": ("Кадет СБ", "security"),
    "warden": ("Смотритель", "security"),
    "detective": ("Детектив", "security"),
    "brigmedic": ("Бригмедик", "security"),
    "corpsman": ("Бригмедик", "security"),
    "headofsecurityassistant": ("Помощник ГСБ", "security"),
    "prisoner": ("Заключённый", "security"),

    # Инженерный отдел
    "stationengineer": ("Инженер станции", "engineering"),
    "seniorengineer": ("Ведущий инженер", "engineering"),
    "atmospherictechnician": ("Атмосферный техник", "engineering"),
    "technicalassistant": ("Технический ассистент", "engineering"),

    # Медицинский отдел
    "medicaldoctor": ("Врач", "medical"),
    "seniorphysician": ("Ведущий врач", "medical"),
    "chemist": ("Химик", "medical"),
    "paramedic": ("Парамедик", "medical"),
    "medicalintern": ("Интерн", "medical"),
    "psychologist": ("Психолог", "medical"),

    # Научный отдел
    "scientist": ("Учёный", "science"),
    "seniorresearcher": ("Ведущий учёный", "science"),
    "researchassistant": ("Научный ассистент", "science"),

    # Снабжение
    "cargotechnician": ("Грузчик", "supply"),
    "salvagespecialist": ("Утилизатор", "supply"),

    # Сервис
    "passenger": ("Пассажир", "service"),
    "bartender": ("Бармен", "service"),
    "botanist": ("Ботаник", "service"),
    "chef": ("Шеф-повар", "service"),
    "janitor": ("Уборщик", "service"),
    "chaplain": ("Священник", "service"),
    "librarian": ("Библиотекарь", "service"),
    "lawyer": ("Адвокат", "service"),
    "clown": ("Клоун", "service"),
    "mime": ("Мим", "service"),
    "musician": ("Музыкант", "service"),
    "reporter": ("Репортёр", "service"),
    "serviceworker": ("Работник сервиса", "service"),
    "zookeeper": ("Смотритель зоопарка", "service"),
    "boxer": ("Боксёр", "service"),
    "visitor": ("Гость", "service"),

    # Синтетики
    "stationai": ("ИИ станции", "silicon"),
    "borg": ("Киборг", "silicon"),
    "cyborg": ("Киборг", "silicon"),

    # Прочее
    "centralcommandofficial": ("Офицер ЦК", "other"),
    "ertleader": ("Лидер ОБР", "other"),
    "ertengineer": ("Инженер ОБР", "other"),
    "ertmedical": ("Медик ОБР", "other"),
    "ertsecurity": ("Боец ОБР", "other"),
    "ertjanitor": ("Уборщик ОБР", "other"),
}

# В базе раса и пол лежат id прототипов
SPECIES = {
    "human": "Человек",
    "reptilian": "Унатх",
    "slimeperson": "Слайм",
    "diona": "Диона",
    "arachnid": "Арахнид",
    "dwarf": "Дворф",
    "moth": "Мотылёк",
    "vox": "Вокс",
    "harpy": "Гарпия",
    "felinid": "Фелинид",
    "skeleton": "Скелет",
    "ipc": "ИПЦ",
}

SEX = {
    "male": "мужской",
    "female": "женский",
    "unsexed": "не указан",
}

# Незнакомая черта покажется английским id
TRAITS = {
    "blindness": "Слепота",
    "nearsighted": "Близорукость",
    "narcolepsy": "Нарколепсия",
    "pacifist": "Пацифист",
    "muted": "Немота",
    "snoring": "Храп",
    "lightstep": "Лёгкая поступь",
    "heavyweightdrunk": "Крепкая голова",
    "lightweightdrunk": "Слабая голова",
    "voracious": "Обжора",
    "thieving": "Ловкие пальцы",
    "sluggish": "Медлительность",
    "frontalgyrus": "Повреждение мозга",
    "painnumbness": "Нечувствительность к боли",
    "deafness": "Глухота",
}

_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")


def pretty_id(value: str) -> str:
    """`HumanHairBob` -> `Human Hair Bob`. Для прототипов без перевода."""
    value = (value or "").strip()
    return _CAMEL.sub(" ", value) if value else ""


def trait_name(trait: str) -> str:
    if not trait:
        return ""
    return TRAITS.get(trait.strip().lower(), pretty_id(trait))


def species_name(species: str) -> str:
    if not species:
        return "неизвестно"
    return SPECIES.get(species.strip().lower(), _CAMEL.sub(" ", species.strip()))


def sex_name(sex: str) -> str:
    if not sex:
        return "не указан"
    return SEX.get(sex.strip().lower(), sex.strip())


def normalize(tracker: str) -> str:
    """`JobStationEngineer` -> `stationengineer`."""
    tracker = (tracker or "").strip()
    if tracker.lower().startswith("job"):
        tracker = tracker[3:]
    return tracker.lower()


def is_job(tracker: str) -> bool:
    """Роль это или служебный трекер вроде Overall."""
    return normalize(tracker) not in SERVICE_TRACKERS


def job_name(tracker: str) -> str:
    """Название роли. Незнакомый трекер разбиваем по заглавным буквам."""
    known = JOBS.get(normalize(tracker))
    if known:
        return known[0]

    raw = (tracker or "").strip()
    if raw.lower().startswith("job"):
        raw = raw[3:]
    return _CAMEL.sub(" ", raw) or "Неизвестная роль"


def job_department(tracker: str) -> str:
    known = JOBS.get(normalize(tracker))
    return known[1] if known else "other"


def find_tracker(query: str, trackers) -> list:
    """Ищет роль по названию или id. Пусто - не нашли, больше одного - уточнить."""
    query = (query or "").strip().lower()
    if not query:
        return []

    jobs = [t for t in trackers if is_job(t)]

    exact = [t for t in jobs if normalize(t) == query or job_name(t).lower() == query]
    if exact:
        return exact

    return [t for t in jobs if query in normalize(t) or query in job_name(t).lower()]
