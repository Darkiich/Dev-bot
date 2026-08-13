"""
Слой работы с базой отпусков команды проекта.
"""

import asyncio
import re

from datetime import datetime

import aiomysql

from dataConfig import (
    VACATION_DB_HOST,
    VACATION_DB_NAME,
    VACATION_DB_PASS,
    VACATION_DB_PORT,
    VACATION_DB_TABLE,
    VACATION_DB_USER,
)
from vacation_time import as_local, as_local_end, now_local, to_naive_local

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_INT_TYPES = ("bigint", "int", "integer", "mediumint", "smallint", "tinyint", "decimal")
_TEXT_TYPES = ("varchar", "char", "text", "tinytext", "mediumtext", "longtext")

# Ошибки, при которых имеет смысл переоткрыть соединение и повторить запрос
_CONNECTION_ERRORS = (
    aiomysql.OperationalError,
    aiomysql.InterfaceError,
    aiomysql.InternalError,
    ConnectionError,
    OSError,
    asyncio.TimeoutError,
)

CONNECT_TIMEOUT = 15
ATTEMPTS = 2

DEFAULT_REASON_LIMIT = 255


def _session_timezone() -> str:
    """Смещение пояса проекта в формате MySQL, например '+03:00'."""
    offset = now_local().strftime("%z") or "+0300"
    return f"{offset[:3]}:{offset[3:]}"


class DatabaseManagerVacation:
    """
    Класс для работы с БД отпусков.

    Все публичные методы возвращают либо данные, либо кортеж (ok: bool, info: str),
    ошибки наружу не пробрасываются.
    """

    def __init__(self):
        table = (VACATION_DB_TABLE).strip()
        if not _IDENT_RE.match(table):
            raise ValueError(f"Недопустимое имя таблицы отпусков: {table!r}")

        self.table = table
        self.qtable = f"`{table}`"
        self.database = VACATION_DB_NAME

        self.db_params = {
            "user": VACATION_DB_USER,
            "password": VACATION_DB_PASS,
            "host": VACATION_DB_HOST,
            "port": int(VACATION_DB_PORT or 3306),
            "db": VACATION_DB_NAME,
            "charset": "utf8mb4",
            "autocommit": True,
            "connect_timeout": CONNECT_TIMEOUT,
        }

        self._lock = asyncio.Lock()
        self._schema_checked = False
        self._col_types = {}
        self._reason_limit = DEFAULT_REASON_LIMIT


    #  Соединение и подготовка схемы
    async def get_connection(self):
        """Открывает соединение и при первом обращении сверяет схему таблицы."""
        conn = await aiomysql.connect(**self.db_params)

        try:
            async with conn.cursor() as cur:
                await cur.execute("SET time_zone = %s", (_session_timezone(),))
        except Exception as e:
            print(f"[vacation_db] Не удалось задать часовой пояс сессии: {e}")

        if not self._schema_checked:
            async with self._lock:
                if not self._schema_checked:
                    await self._prepare(conn)
                    self._schema_checked = True

        return conn

    async def _run(self, label: str, operation):
        last_error = None

        for attempt in range(1, ATTEMPTS + 1):
            conn = None
            try:
                conn = await self.get_connection()
                return await operation(conn)
            except _CONNECTION_ERRORS as e:
                last_error = e
                print(
                    f"[vacation_db] {label}: соединение оборвалось "
                    f"(попытка {attempt}/{ATTEMPTS}): {type(e).__name__}: {e}"
                )
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass

        raise last_error

    async def _prepare(self, conn):
        """Создаёт таблицу, если её нет, и запоминает реальные типы колонок."""
        await self._load_columns(conn)

        # Отдельная проверка вместо CREATE IF NOT EXISTS, чтобы MySQL не сыпал
        # предупреждением при каждом запуске
        if not self._col_types:
            await self._create_table(conn)
            await self._load_columns(conn)

        if not self._col_types:
            print(
                f"[vacation_db] Таблица {self.table} не найдена в базе {self.database}. "
                f"Проверь VACATION_DB_NAME / VACATION_DB_TABLE."
            )
            return

        missing = [c for c in ("reason", "start_vacation", "end_vacation")
                   if c not in self._col_types]
        if missing:
            await self._add_missing_columns(conn, missing)

        await self._upgrade_date_columns(conn)

    async def _upgrade_date_columns(self, conn):
        stale = [c for c in ("start_vacation", "end_vacation")
                 if self._col_types.get(c) == "date"]
        if not stale:
            return

        async with conn.cursor() as cur:
            for column in stale:
                try:
                    await cur.execute(
                        f"ALTER TABLE {self.qtable} "
                        f"MODIFY COLUMN `{column}` datetime DEFAULT NULL"
                    )
                    self._col_types[column] = "datetime"
                    print(f"[vacation_db] Колонка {column}: date -> datetime")
                except Exception as e:
                    print(f"[vacation_db] Не перевести {column} в datetime: {e}")

    async def _load_columns(self, conn):
        """Читает реальные типы колонок таблицы из information_schema."""
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            """, (self.database, self.table))
            rows = await cur.fetchall()

        self._col_types = {r[0]: str(r[1]).lower() for r in rows}

        for row in rows:
            if row[0] == "reason" and row[2]:
                self._reason_limit = int(row[2])

    async def _create_table(self, conn):
        """Заводит таблицу отпусков с нуля."""
        try:
            async with conn.cursor() as cur:
                await cur.execute(f"""
                    CREATE TABLE {self.qtable} (
                        ds_id          varchar(32) NOT NULL,
                        reason         varchar(255) DEFAULT NULL,
                        start_vacation datetime DEFAULT NULL,
                        end_vacation   datetime DEFAULT NULL,
                        PRIMARY KEY (ds_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
            print(f"[vacation_db] Создана таблица {self.table}")
        except _CONNECTION_ERRORS:
            raise
        except Exception as e:
            print(f"[vacation_db] Не удалось создать таблицу {self.table}: {e}")

    async def _add_missing_columns(self, conn, missing: list):
        """Дописывает недостающие колонки в уже существующую таблицу."""
        types = {
            "reason": "varchar(255) DEFAULT NULL",
            "start_vacation": "datetime DEFAULT NULL",
            "end_vacation": "datetime DEFAULT NULL",
        }
        async with conn.cursor() as cur:
            for column in missing:
                if column not in types:
                    continue
                try:
                    await cur.execute(
                        f"ALTER TABLE {self.qtable} ADD COLUMN `{column}` {types[column]}"
                    )
                    self._col_types[column] = types[column].split("(")[0].split()[0]
                    print(f"[vacation_db] Добавлена колонка {column}")
                except Exception as e:
                    print(f"[vacation_db] Не удалось добавить колонку {column}: {e}")


    #  Подгонка значений под реальные типы колонок


    def _adapt_id(self, ds_id):
        """Discord ID приводится к типу колонки ds_id (строка или число)."""
        coltype = self._col_types.get("ds_id", "varchar")
        if coltype in _INT_TYPES:
            return int(ds_id)
        return str(ds_id)

    def _adapt_dt(self, value: datetime | None, column: str):
        """Дату приводим к типу колонки. MySQL не понимает tz-aware datetime."""
        if value is None:
            return None

        coltype = self._col_types.get(column, "datetime")
        local = to_naive_local(value)

        if coltype == "date":
            return local.date()
        if coltype in _TEXT_TYPES:
            return local.strftime("%Y-%m-%d %H:%M:%S")
        return local.replace(microsecond=0)

    def _adapt_reason(self, reason: str | None) -> str:
        """Обрезает причину до длины колонки, чтобы вставка не сорвалась."""
        text = (reason or "").strip() or "Причина не указана"
        if len(text) > self._reason_limit:
            text = text[: self._reason_limit - 1].rstrip() + "…"
        return text

    @staticmethod
    def _row_to_dict(row) -> dict:
        """Дата окончания без времени считается концом суток, а не полуночью."""
        return {
            "ds_id": str(row["ds_id"]),
            "reason": row["reason"] or "Причина не указана",
            "start_vacation": as_local(row["start_vacation"]),
            "end_vacation": as_local_end(row["end_vacation"]),
        }


    #  Публичные операции


    async def get_vacation(self, ds_id) -> dict | None:
        """Возвращает запись об отпуске участника или None."""
        async def operation(conn):
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    f"SELECT ds_id, reason, start_vacation, end_vacation "
                    f"FROM {self.qtable} WHERE ds_id = %s",
                    (self._adapt_id(ds_id),),
                )
                return await cur.fetchone()

        try:
            row = await self._run("get_vacation", operation)
            return self._row_to_dict(row) if row else None
        except Exception as e:
            print(f"[vacation_db] Ошибка get_vacation: {type(e).__name__}: {e}")
            return None

    async def get_all_vacations(self) -> list[dict] | None:
        """
        Все записи об отпусках, отсортированные по дате окончания.
        Пустой список это "отпусков нет", None это "БД недоступна". Путать нельзя:
        по этим данным снимается роль, ошибка чтения снесла бы её всем.
        """
        async def operation(conn):
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # NULLS LAST в MySQL нет, сортируем сначала по пустоте даты
                await cur.execute(
                    f"SELECT ds_id, reason, start_vacation, end_vacation "
                    f"FROM {self.qtable} "
                    f"ORDER BY end_vacation IS NULL, end_vacation ASC"
                )
                return await cur.fetchall()

        try:
            rows = await self._run("get_all_vacations", operation)
            return [self._row_to_dict(r) for r in rows]
        except Exception as e:
            print(f"[vacation_db] Ошибка get_all_vacations: {type(e).__name__}: {e}")
            return None

    async def set_vacation(self, ds_id, start: datetime, end: datetime, reason: str) -> tuple[bool, str]:
        """
        Записывает отпуск участника (одна активная запись на человека).
        Возвращает (True, 'created') / (True, 'updated') или (False, текст ошибки).
        """
        async def operation(conn):
            key = self._adapt_id(ds_id)
            values = (
                self._adapt_reason(reason),
                self._adapt_dt(start, "start_vacation"),
                self._adapt_dt(end, "end_vacation"),
            )

            await conn.begin()
            try:
                async with conn.cursor() as cur:
                    await cur.execute(
                        f"SELECT 1 FROM {self.qtable} WHERE ds_id = %s", (key,)
                    )
                    existed = await cur.fetchone() is not None

                    if existed:
                        await cur.execute(
                            f"UPDATE {self.qtable} "
                            f"SET reason = %s, start_vacation = %s, end_vacation = %s "
                            f"WHERE ds_id = %s",
                            (*values, key),
                        )
                    else:
                        await cur.execute(
                            f"INSERT INTO {self.qtable} "
                            f"(ds_id, reason, start_vacation, end_vacation) "
                            f"VALUES (%s, %s, %s, %s)",
                            (key, *values),
                        )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

            return "updated" if existed else "created"

        try:
            return True, await self._run("set_vacation", operation)
        except Exception as e:
            print(f"[vacation_db] Ошибка set_vacation: {type(e).__name__}: {e}")
            return False, f"{type(e).__name__}: {e}"

    async def delete_vacation(self, ds_id) -> tuple[bool, str]:
        """
        Удаляет запись об отпуске.
        Возвращает (True, 'ok') / (False, 'not_found') / (False, текст ошибки).
        """
        async def operation(conn):
            async with conn.cursor() as cur:
                await cur.execute(
                    f"DELETE FROM {self.qtable} WHERE ds_id = %s",
                    (self._adapt_id(ds_id),),
                )
                return cur.rowcount

        try:
            deleted = await self._run("delete_vacation", operation)
            return (True, "ok") if deleted else (False, "not_found")
        except Exception as e:
            print(f"[vacation_db] Ошибка delete_vacation: {type(e).__name__}: {e}")
            return False, f"{type(e).__name__}: {e}"
