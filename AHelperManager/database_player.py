"""
База бота для игроцких команд: снимки наигранных часов
"""

import asyncio
import logging

import asyncpg

from dataConfig import (
    TEAM_DB_HOST,
    TEAM_DB_NAME,
    TEAM_DB_PASS,
    TEAM_DB_PORT,
    TEAM_DB_SSL,
    TEAM_DB_USER,
)

_CONNECTION_ERRORS = (
    asyncpg.exceptions.PostgresConnectionError,
    asyncpg.exceptions.InterfaceError,
    asyncpg.exceptions.InternalClientError,
    ConnectionError,
    OSError,
    asyncio.TimeoutError,
)

CONNECT_TIMEOUT = 15
COMMAND_TIMEOUT = 60
ATTEMPTS = 2

logger = logging.getLogger(__name__)


class DatabaseManagerPlayer:
    """Снимки наигранных часов."""

    def __init__(self):
        self.db_params = {
            "user": TEAM_DB_USER,
            "password": TEAM_DB_PASS,
            "host": TEAM_DB_HOST,
            "port": int(TEAM_DB_PORT or 5432),
            "database": TEAM_DB_NAME,
            "ssl": TEAM_DB_SSL,
        }

        self._lock = asyncio.Lock()
        self._schema_ready = False

    async def get_connection(self):
        conn = await asyncpg.connect(
            **self.db_params,
            timeout=CONNECT_TIMEOUT,
            command_timeout=COMMAND_TIMEOUT,
        )

        if not self._schema_ready:
            async with self._lock:
                if not self._schema_ready:
                    await self._prepare(conn)
                    self._schema_ready = True

        return conn

    async def _run(self, label: str, operation):
        """Выполняет операцию, при обрыве соединения повторяет на новом."""
        last_error = None

        for attempt in range(1, ATTEMPTS + 1):
            conn = None
            try:
                conn = await self.get_connection()
                return await operation(conn)
            except _CONNECTION_ERRORS as e:
                last_error = e
                logger.warning("%s: обрыв (%d/%d) %s: %s", label, attempt, ATTEMPTS, type(e).__name__, e)
            finally:
                if conn is not None:
                    try:
                        await conn.close(timeout=5)
                    except Exception:
                        pass

        raise last_error

    async def _safe(self, label: str, operation, default=None):
        try:
            return await self._run(label, operation)
        except Exception as e:
            logger.exception("Ошибка %s: %s: %s", label, type(e).__name__, e)
            return default

    async def _prepare(self, conn):
        """Заводит таблицы, если их ещё нет."""
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS playtime_snapshots (
                taken_on date NOT NULL,
                user_id  uuid NOT NULL,
                minutes  integer NOT NULL,
                PRIMARY KEY (taken_on, user_id)
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS playtime_snapshots_user_idx
            ON playtime_snapshots (user_id, taken_on DESC)
        """)

        logger.info("Таблицы игроцкой статистики готовы")

    #  Снимки часов
    async def save_snapshot(self, taken_on, rows: list) -> int:
        """Записывает снимок за день. Повторный запуск в тот же день перезаписывает."""
        if not rows:
            return 0

        async def operation(conn):
            await conn.executemany("""
                INSERT INTO playtime_snapshots (taken_on, user_id, minutes)
                VALUES ($1, $2, $3)
                ON CONFLICT (taken_on, user_id) DO UPDATE SET minutes = EXCLUDED.minutes
            """, [(taken_on, user_id, minutes) for user_id, minutes in rows])
            return len(rows)

        return await self._safe("save_snapshot", operation, 0) or 0

    async def prune_snapshots(self, keep_days: int) -> int:
        async def operation(conn):
            result = await conn.execute(
                "DELETE FROM playtime_snapshots WHERE taken_on < current_date - $1::int", keep_days
            )
            return int(result.split()[-1]) if result else 0

        return await self._safe("prune_snapshots", operation, 0) or 0

    async def snapshot_before(self, user_id, day):
        """Минуты на ближайшем снимке не новее указанной даты."""
        async def operation(conn):
            return await conn.fetchrow("""
                SELECT taken_on, minutes FROM playtime_snapshots
                WHERE user_id = $1 AND taken_on <= $2
                ORDER BY taken_on DESC LIMIT 1
            """, user_id, day)

        return await self._safe("snapshot_before", operation)

    async def snapshot_series(self, user_id, days: int) -> list:
        """Снимки за последние дни, от старых к новым."""
        async def operation(conn):
            return await conn.fetch("""
                SELECT taken_on, minutes FROM playtime_snapshots
                WHERE user_id = $1 AND taken_on >= current_date - $2::int
                ORDER BY taken_on
            """, user_id, days)

        return await self._safe("snapshot_series", operation, []) or []

    async def last_snapshot_day(self):
        """Дата последнего снимка."""
        async def operation(conn):
            return await conn.fetchval("SELECT MAX(taken_on) FROM playtime_snapshots")

        return await self._safe("last_snapshot_day", operation)

    async def first_snapshot_day(self, user_id):
        async def operation(conn):
            return await conn.fetchval("""
                SELECT MIN(taken_on) FROM playtime_snapshots WHERE user_id = $1
            """, user_id)

        return await self._safe("first_snapshot_day", operation)
