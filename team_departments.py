"""
Карта отделов, должностей и карьерных лестниц.

Грейд руками не вписывается: должности в ladder идут снизу вверх, номер
ступени это место в списке начиная с 1. Роли из extra стоят вне лестницы,
грейда у них нет и повышением их выдача не считается.
"""

DEPARTMENTS = {
    "leadership": {
        "name": "Руководство проекта",
        "role_id": 1054908932868538449,
        "ladder": [
            ("Куратор проекта", 1060264704838209586),
            ("Зам. лидера проекта", 1127152229439246468),
            ("Лидер проекта", 1116612861993689251),
        ],
        "extra": [
            ("Хост", 1233048689996726378),
            ("Админ", 1054827766211694593),
        ],
    },
    "discord_mod": {
        "name": "Дискорд модерация",
        "role_id": 1350908719608762388,
        "ladder": [
            ("Дискорд модератор", 1116562622976897085),
            ("Старший дискорд модератор", 1123894677712679015),
        ],
        "extra": [],
    },
    "moderation": {
        "name": "Модерация",
        "role_id": 1248667383334178902,
        "ladder": [
            ("Ментор", 1248665294944342016),
            ("Младший Модератор", 1248665288283525272),
            ("Модератор", 1248665281748795392),
            ("Наблюдатель Модерации", 1248666127949893747),
            ("Инструктор Модерации", 1248665270051143721),
            ("Заместитель Главного Модератора", 1223228123370229770),
            ("Главный Модератор", 1254021066796302366),
        ],
        "extra": [],
    },
    "dev": {
        "name": "Разработка",
        "role_id": 1060191651538145420,
        "ladder": [
            ("Младший разработчик", 1173709090694889513),
            ("Разработчик", 1054583841060306944),
            ("Старший разработчик", 1364533120799608903),
            ("Заместитель Главы Разработки", 1477251178411851787),
            ("Глава разработки", 1054583381024854106),
        ],
        "extra": [
            ("Руководство отдела разработки", 1266161300036390913),
            ("Тестировщик", 1266164443327234110),
            ("Менеджер разработки", 1266164436100452443),
            ("Maintainer", 1338486326328164352),
            ("Кодинг", 1321350645998944256),
            ("Прототипинг", 1321351353347604550),
        ],
    },
    "mapping": {
        "name": "Мапперский отдел",
        "role_id": 1084143714110275614,
        "ladder": [
            ("Маппер стажёр", 1062451564058521610),
            ("Маппер", 1062660322386784307),
            ("Старший маппер", 1258007009673089086),
            ("Зам главного маппера", 1160695278429556796),
            ("Главный маппер", 1148669166128205926),
        ],
        "extra": [],
    },
    "sprite": {
        "name": "Спрайтинг",
        "role_id": 1155055955214614558,
        "ladder": [
            ("Полу-спрайтер", 1173683325098012762),
            ("Младший спрайтер", 1154869038720225402),
            ("Спрайтер", 1084170638811484221),
            ("Спрайтер наставник", 1257007633936814090),
            ("Зам ведущего спрайтера", 1150155484893040720),
            ("Ведущий спрайтер", 1089903271902183516),
        ],
        "extra": [],
    },
    "wiki": {
        "name": "Комитет вики",
        "role_id": 1084840645790814310,
        "ladder": [
            ("Редактор вики", 1084840686303580191),
            ("Лоровед вики", 1270498576740647032),
            ("Главный лоровед вики", 1428057252874551337),
            ("Бюрократ вики", 1084832292893118546),
        ],
        "extra": [
            ("Тех ассистент вики", 1290374832676012135),
        ],
    },
    "event": {
        "name": "Ивентология",
        "role_id": 1395296010573582437,
        "ladder": [
            ("Младший ивентер", 1409878581546451066),
            ("Ивентер", 1395295618879979621),
            ("Ивентер-инструктор", 1420404970192240791),
            ("Старший ивентер", 1409881051450445935),
            ("Главный ивентер", 1395298067309133834),
        ],
        "extra": [],
    },
}


class Position:
    """Должность: к какому отделу относится, какая роль, какая ступень."""

    __slots__ = ("key", "department", "department_name", "name", "role_id", "grade")

    def __init__(self, key, department_name, name, role_id, grade):
        self.department = key
        self.department_name = department_name
        self.name = name
        self.role_id = role_id
        self.grade = grade

    @property
    def on_ladder(self) -> bool:
        return self.grade is not None

    def __repr__(self):
        return f"<Position {self.name} {self.department}:{self.grade}>"


def _build():
    """Разворачивает карту в плоские индексы. Заодно ловит дубли ID."""
    by_role = {}
    by_department = {}

    for key, dept in DEPARTMENTS.items():
        positions = []

        for grade, (name, role_id) in enumerate(dept["ladder"], start=1):
            positions.append(Position(key, dept["name"], name, role_id, grade))

        for name, role_id in dept["extra"]:
            positions.append(Position(key, dept["name"], name, role_id, None))

        for position in positions:
            if position.role_id in by_role:
                other = by_role[position.role_id]
                raise ValueError(
                    f"Роль {position.role_id} указана дважды: "
                    f"{other.department}/{other.name} и {key}/{position.name}"
                )
            by_role[position.role_id] = position

        by_department[key] = positions

    return by_role, by_department


POSITION_BY_ROLE, POSITIONS_BY_DEPARTMENT = _build()

DEPARTMENT_ROLE_IDS = {dept["role_id"] for dept in DEPARTMENTS.values()}
POSITION_ROLE_IDS = set(POSITION_BY_ROLE)


def get_position(role_id) -> Position | None:
    """Должность по ID роли или None, если роль не наша."""
    try:
        return POSITION_BY_ROLE.get(int(role_id))
    except (TypeError, ValueError):
        return None


def get_positions(department: str) -> list:
    """Все должности отдела: сначала лестница снизу вверх, потом отдельные роли."""
    return POSITIONS_BY_DEPARTMENT.get(department, [])


def get_ladder(department: str) -> list:
    """Только ступени лестницы отдела, снизу вверх."""
    return [p for p in get_positions(department) if p.on_ladder]


def department_name(department: str) -> str:
    dept = DEPARTMENTS.get(department)
    return dept["name"] if dept else department


def department_role_id(department: str):
    dept = DEPARTMENTS.get(department)
    return dept["role_id"] if dept else None
