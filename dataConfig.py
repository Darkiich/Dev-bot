import logging
import os
import json

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

ROLE_ACCESS_HEADS = [
    1054908932868538449, # Руководство проекта
    1266161300036390913, # Руководство отдела разработки
    1054827766211694593 # Админ
]

ROLE_ACCESS_MAINTAINER = [
    1054908932868538449, # Руководство проекта
    1266161300036390913, # Руководство отдела разработки
    1054827766211694593, # Админ
    1338486326328164352 # Maintainer
]

ROLE_ACCESS_ADMIN = [
    1054908932868538449, # Руководство проекта
    1266161300036390913, # Руководство отдела разработки
    1054827766211694593, # Админ
    1248667383334178902, # Администрация
]

GENERAL_ACCESS = [
    1054908932868538449, # Руководство проекта
    1266161300036390913, # Руководство отдела разработки
    1054827766211694593, # Админ
    1428866954403512513, # Команда проекта
]

ROLE_ACCESS_DOWN_ADMIN = [
    1054908932868538449, # Руководство проекта
    1266161300036390913, # Руководство отдела разработки
    1054827766211694593, # Админ
    1248665270051143721, # Инструктор
    1248666127949893747, # Наблюдатель
    1248665281748795392, # Администратор
    1248665288283525272, # Младший администратор
]

ROLE_ACCESS_OBSERVER_ADMIN = [
    1054908932868538449, # Руководство проекта
    1266161300036390913, # Руководство отдела разработки
    1054827766211694593, # Админ
    1248665270051143721, # Инструктор
    1248666127949893747, # Наблюдатель
]

ROLE_ACCESS_DEPARTAMENT_OF_UNBAN_ADMIN = [
    1054908932868538449, # Руководство проекта
    1266161300036390913, # Руководство отдела разработки
    1054827766211694593, # Админ
    1183135960951697478, # Глава департамента обжалований
    1084459980419240016, # Департамент обжалований
]

ROLE_ACCESS_TOP_HEADS = [
    1116612861993689251, # Лидер проекта
    1060264704838209586, # Куратор проекта
]

# Функция для получения значения скрытого ключа
def get_env(key: str):
    env = os.getenv(f"{key}")

    if not env:
        logger.warning("Ключ секрета не найден в .env: %s", key)

    return env

DISCORD_KEY = get_env("DISCORD_KEY")
USER_KEY_GITHUB = get_env("USER_KEY_GITHUB")

ADDRESS_MRP = "193.164.18.155"
ADDRESS_DEV = "193.164.18.155"

POST_PASSWORD_MRP = get_env("POST_PASSWORD_MRP")
POST_PASSWORD_DEV = get_env("POST_PASSWORD_DEV")

POST_AUTHORIZATION_MRP = get_env("POST_AUTHORIZATION_MRP")
POST_AUTHORIZATION_DEV = get_env("POST_AUTHORIZATION_DEV")

POST_USER_AGENT = get_env("POST_USER_AGENT")

CHANNEL_AUTH_DISCORD = 1351213738774237184
CHANNEL_LOG_AUTH_DISCORD = 1372556297773256795
CHANNEL_STATUS_MESSAGE = 1320771026019422329
CHANNEL_VALENTINE = 1471999161376313427

SPONSOR_ROLE_ID = 1047486419960082474

ADMIN_GUID = get_env("ADMIN_GUID")
ADMIN_NAME = get_env("ADMIN_NAME")
ADMIN_API = get_env("ADMIN_API")

DATABASE_MRP = get_env("DATABASE_MRP")
DATABASE_DEV = get_env("DATABASE_DEV")
DATABASE_MRP_SPONSOR = get_env("DATABASE_MRP_SPONSOR")
DATABASE_HOST = get_env("DATABASE_HOST")
DATABASE_PORT = get_env("DATABASE_PORT")
DATABASE_USER = get_env("DATABASE_USER")
DATABASE_PASS = get_env("DATABASE_PASS")

LOG_CHANNEL_ID = 1141810442721833060

MY_DS_ID = 568092953948454922

DB_SIZE_LIMIT_GB = 19
DB_SIZE_CHECK_INTERVAL_MIN = 60
DB_SIZE_ALERT_CHANNEL_ID = LOG_CHANNEL_ID


#  Система отпусков команды проекта
# Роль, которая выдаётся на время отпуска
VACATION_ROLE_ID = 1309454737032216617

# Канал, куда бот пишет о начале и окончании отпусков
VACATION_CHANNEL_ID = 1222475582953099264

# Как часто проверять в минутах
VACATION_CHECK_INTERVAL_MIN = 60

# Максимальная длительность отпуска, дней
VACATION_MAX_DAYS = 365

# Снимать роль отпуска с тех, кого нет в базе отпусков
VACATION_ROLE_STRICT_SYNC = False

# Часовой пояс, в котором считаются даты отпусков
VACATION_TIMEZONE = "Europe/Moscow"

VACATION_DB_HOST = get_env("VACATION_DB_HOST")
VACATION_DB_PORT = get_env("VACATION_DB_PORT")
VACATION_DB_USER = get_env("VACATION_DB_USER")
VACATION_DB_PASS = get_env("VACATION_DB_PASS")
VACATION_DB_NAME = get_env("VACATION_DB_NAME")
VACATION_DB_TABLE = get_env("VACATION_DB_TABLE")

# Кадровая система

# Общая роль команды проекта, выдаётся при найме в любой отдел
PROJECT_TEAM_ROLE_ID = 1428866954403512513

# Канал с действиями глав, писать в него текстом нельзя
TEAM_LOG_CHANNEL_ID = 1222475582953099264

# Канал с закреплённым отчётом
TEAM_REPORT_CHANNEL_ID = 1545818305409847418

# Как часто перерисовывать отчёт, в минутах
TEAM_REPORT_INTERVAL_MIN = 120

# Как часто сверять состав в базе с ролями Discord, в минутах
TEAM_SYNC_INTERVAL_MIN = 30

TEAM_DB_HOST = get_env("TEAM_DB_HOST")
TEAM_DB_PORT = get_env("TEAM_DB_PORT")
TEAM_DB_USER = get_env("TEAM_DB_USER")
TEAM_DB_PASS = get_env("TEAM_DB_PASS")
TEAM_DB_NAME = get_env("TEAM_DB_NAME")
TEAM_DB_SSL = os.getenv("TEAM_DB_SSL", "prefer")

VALENTINE_IMAGE_PATH = "src/valentine_card/image_valentine.png"

DATA_MRP = {
    "Username": "MRP",
    "Password": POST_PASSWORD_MRP
}

HEADERS_MRP = {
    "Authorization": POST_AUTHORIZATION_MRP,
    "Content-Length": str(len(DATA_MRP)),
    "Host": f"{ADDRESS_MRP}:5000",
    "User-Agent": POST_USER_AGENT,
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive"
}

DATA_DEV = {
    "Username": "DEV",
    "Password": POST_PASSWORD_DEV
}

HEADERS_DEV = {
    "Authorization": POST_AUTHORIZATION_DEV,
    "Content-Length": str(len(DATA_DEV)),
    "Host": f"{ADDRESS_DEV}:5001",
    "User-Agent": POST_USER_AGENT,
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive"
}

DATA_ADMIN = {
    "Guid": str(ADMIN_GUID),
    "Name": str(ADMIN_NAME)
}

POST_ADMIN_HEADERS = {
    "Authorization": f"SS14Token {ADMIN_API}",
    "Content-Type": "application/json",
    "Actor": json.dumps(DATA_ADMIN)
}