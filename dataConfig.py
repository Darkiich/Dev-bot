import os
import json

from dotenv import load_dotenv

load_dotenv()

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
        print("Ключ секрета не найден")

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

VACATION_ROLE_ID = 1437106179389128764

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

DB_SIZE_LIMIT_GB = 18
DB_SIZE_CHECK_INTERVAL_MIN = 60
DB_SIZE_ALERT_CHANNEL_ID = LOG_CHANNEL_ID
DB_SIZE_REALERT_HOURS = 6

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