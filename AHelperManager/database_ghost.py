"""
Журнал гост-смен: агост у модерации и игост у ивентологии
"""

import asyncio
import logging

from datetime import datetime, timezone

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
COMMAND_TIMEOUT = 30
ATTEMPTS = 2

KINDS = ("aghost", "eghost")

REVIEW_STATES = ("pending", "approved", "rejected", "none")

logger = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc)


class DatabaseManagerGhost:
    """Хранит гост-смены и действия внутри них."""

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
        """То же самое, но молча возвращает default вместо исключения."""
        try:
            return await self._run(label, operation)
        except Exception as e:
            logger.exception("Ошибка %s: %s: %s", label, type(e).__name__, e)
            return default

    async def _prepare(self, conn):
        """Заводит таблицы и индексы, если их ещё нет."""
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ghost_shifts (
                    id           bigserial PRIMARY KEY,
                    kind         text        NOT NULL,
                    guild_id     bigint      NOT NULL,
                    user_id      bigint      NOT NULL,
                    user_name    text,
                    department   text,
                    position     text,
                    round_id     integer,
                    players      integer,
                    preset       text,
                    preset_note  text,
                    event_text   text,
                    started_at   timestamptz NOT NULL,
                    ended_at     timestamptz,
                    channel_id   bigint,
                    message_id   bigint,
                    thread_id    bigint,
                    message_url  text,
                    review_state text        NOT NULL DEFAULT 'pending',
                    review_by    bigint,
                    review_name  text,
                    review_note  text,
                    reviewed_at  timestamptz,
                    actions      integer     NOT NULL DEFAULT 0,
                    created_at   timestamptz NOT NULL DEFAULT now()
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ghost_actions (
                    id         bigserial PRIMARY KEY,
                    shift_id   bigint      NOT NULL
                               REFERENCES ghost_shifts (id) ON DELETE CASCADE,
                    actor_id   bigint      NOT NULL,
                    actor_name text,
                    body       text        NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now()
                )
            """)

            # Если таблица осталась от прошлой версии схемы, дотягиваем её
            # на месте: CREATE TABLE IF NOT EXISTS новых колонок не добавит
            for statement in (
                "ALTER TABLE ghost_shifts ADD COLUMN IF NOT EXISTS preset_note text",
                "ALTER TABLE ghost_shifts ADD COLUMN IF NOT EXISTS event_text text",
            ):
                try:
                    await conn.execute(statement)
                except Exception as e:
                    logger.debug("Пропускаю миграцию «%s»: %s", statement, e)

            for statement in (
                "CREATE INDEX IF NOT EXISTS ghost_shifts_kind_idx   ON ghost_shifts (kind, started_at DESC)",
                "CREATE INDEX IF NOT EXISTS ghost_shifts_user_idx   ON ghost_shifts (user_id, started_at DESC)",
                "CREATE INDEX IF NOT EXISTS ghost_shifts_round_idx  ON ghost_shifts (round_id)",
                "CREATE INDEX IF NOT EXISTS ghost_shifts_review_idx ON ghost_shifts (review_state, started_at DESC)",
                # Открытых смен всегда единицы, полный индекс тут лишний
                "CREATE INDEX IF NOT EXISTS ghost_shifts_open_idx   ON ghost_shifts (kind, user_id) WHERE ended_at IS NULL",
                "CREATE INDEX IF NOT EXISTS ghost_actions_shift_idx ON ghost_actions (shift_id, created_at)",
            ):
                await conn.execute(statement)

            logger.info("Схема БД гост-отчётов проверена")
        except _CONNECTION_ERRORS:
            raise
        except Exception as e:
            # Прав на DDL может не быть, это не повод падать при старте
            logger.exception("Не удалось проверить схему БД гост-отчётов: %s", e)

    # ------------------------------------------------------------------ #
    #  Смены
    # ------------------------------------------------------------------ #

    async def open_shift(self, kind, guild_id, user_id, user_name, started_at,
                         department=None, position=None, round_id=None, players=None,
                         preset=None, preset_note=None, event_text=None,
                         review_state="pending"):
        """Заводит смену и возвращает её строку. None, если база недоступна."""
        async def operation(conn):
            return await conn.fetchrow("""
                INSERT INTO ghost_shifts (
                    kind, guild_id, user_id, user_name, department, position,
                    round_id, players, preset, preset_note, event_text,
                    started_at, review_state
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                RETURNING *
            """,
                kind, guild_id, user_id, user_name, department, position,
                round_id, players, preset, preset_note, event_text,
                started_at, review_state,
            )

        return await self._safe("open_shift", operation)

    async def get_shift(self, shift_id):
        async def operation(conn):
            return await conn.fetchrow("SELECT * FROM ghost_shifts WHERE id = $1", shift_id)

        return await self._safe("get_shift", operation)

    async def get_shift_by_message(self, message_id):
        """Смена по сообщению-карточке: нужно, если номер потерялся."""
        async def operation(conn):
            return await conn.fetchrow(
                "SELECT * FROM ghost_shifts WHERE message_id = $1", message_id
            )

        return await self._safe("get_shift_by_message", operation)

    async def open_shift_of(self, user_id, kind):
        """Незакрытая смена участника. Вторую открывать не даём."""
        async def operation(conn):
            return await conn.fetchrow("""
                SELECT * FROM ghost_shifts
                 WHERE user_id = $1 AND kind = $2 AND ended_at IS NULL
              ORDER BY started_at DESC
                 LIMIT 1
            """, user_id, kind)

        return await self._safe("open_shift_of", operation)

    async def set_message(self, shift_id, channel_id, message_id,
                          thread_id=None, message_url=None):
        """Запоминает карточку и ветку, чтобы потом их обновлять."""
        async def operation(conn):
            return await conn.fetchrow("""
                UPDATE ghost_shifts
                   SET channel_id = $2, message_id = $3,
                       thread_id = COALESCE($4, thread_id),
                       message_url = COALESCE($5, message_url)
                 WHERE id = $1
             RETURNING *
            """, shift_id, channel_id, message_id, thread_id, message_url)

        return await self._safe("set_message", operation)

    async def close_shift(self, shift_id, ended_at=None, review_state=None):
        """
        Закрывает смену. Возвращает строку или None, если смена уже закрыта:
        так две нажатые подряд кнопки не превращаются в две записи.
        """
        async def operation(conn):
            return await conn.fetchrow("""
                UPDATE ghost_shifts
                   SET ended_at = $2,
                       review_state = COALESCE($3, review_state)
                 WHERE id = $1 AND ended_at IS NULL
             RETURNING *
            """, shift_id, ended_at or _now(), review_state)

        return await self._safe("close_shift", operation)

    async def review_shift(self, shift_id, state, actor_id, actor_name, note=None):
        """
        Проверка отчёта наблюдателем. Пустая заметка это тоже результат:
        подтвердили без комментария.
        """
        async def operation(conn):
            return await conn.fetchrow("""
                UPDATE ghost_shifts
                   SET review_state = $2, review_by = $3, review_name = $4,
                       review_note = $5, reviewed_at = $6
                 WHERE id = $1
             RETURNING *
            """, shift_id, state, actor_id, actor_name, note, _now())

        return await self._safe("review_shift", operation)

    async def list_shifts(self, kind=None, user_id=None, limit=10, offset=0):
        """Страница истории смен, свежие сверху."""
        async def operation(conn):
            return await conn.fetch("""
                SELECT * FROM ghost_shifts
                 WHERE ($1::text IS NULL OR kind = $1)
                   AND ($2::bigint IS NULL OR user_id = $2)
              ORDER BY started_at DESC
                 LIMIT $3 OFFSET $4
            """, kind, user_id, limit, offset)

        return await self._safe("list_shifts", operation, default=[]) or []

    async def stale_shifts(self, hours=12):
        """Смены, которые забыли закрыть. Для уборки и для аналитики."""
        async def operation(conn):
            return await conn.fetch("""
                SELECT * FROM ghost_shifts
                 WHERE ended_at IS NULL
                   AND started_at < now() - ($1 || ' hours')::interval
              ORDER BY started_at
                 LIMIT 100
            """, str(hours))

        return await self._safe("stale_shifts", operation, default=[]) or []

    # ------------------------------------------------------------------ #
    #  Действия внутри смены
    # ------------------------------------------------------------------ #

    async def add_action(self, shift_id, actor_id, actor_name, body):
        """Пишет действие и сразу возвращает новый счётчик по смене."""
        async def operation(conn):
            async with conn.transaction():
                row = await conn.fetchrow("""
                    INSERT INTO ghost_actions (shift_id, actor_id, actor_name, body)
                    VALUES ($1,$2,$3,$4)
                    RETURNING *
                """, shift_id, actor_id, actor_name, body)

                total = await conn.fetchval("""
                    UPDATE ghost_shifts SET actions = actions + 1
                     WHERE id = $1
                 RETURNING actions
                """, shift_id)

            return row, total or 0

        return await self._safe("add_action", operation, default=(None, 0))

    async def list_actions(self, shift_id, limit=50):
        async def operation(conn):
            return await conn.fetch("""
                SELECT * FROM ghost_actions
                 WHERE shift_id = $1
              ORDER BY created_at
                 LIMIT $2
            """, shift_id, limit)

        return await self._safe("list_actions", operation, default=[]) or []

    # ------------------------------------------------------------------ #
    #  Аналитика
    # ------------------------------------------------------------------ #

    async def get_report_data(self, kind, guild_id=None, short_days=7,
                              long_days=30, max_hours=12, silent_days=30):
        """
        Всё для аналитики одним походом в базу.

        Считаем только закрытые смены: у открытой длительности ещё нет, а
        подставлять «сейчас минус начало» значит записать человеку часы,
        которых он не отработал.

        Смены длиннее max_hours в часы и в среднюю длительность не идут:
        это забытая кнопка «завершить», а не сутки за компьютером. Само
        число таких смен возвращается отдельно - это тоже показатель.

        None означает, что база не ответила: отчёт тогда лучше не трогать,
        чем перерисовать нулями.
        """
        # Закрытая смена вменяемой длины, вся арифметика опирается на это
        sane = """
            ended_at IS NOT NULL
            AND ended_at > started_at
            AND ended_at - started_at <= ($3 || ' hours')::interval
        """

        async def operation(conn):
            data = {}

            # 1. Часы на человека за короткий и длинный период
            for label, days in (("short", short_days), ("long", long_days)):
                data[f"hours_{label}"] = await conn.fetch(f"""
                    SELECT user_id,
                           max(user_name) AS user_name,
                           count(*)       AS shifts,
                           sum(extract(epoch FROM ended_at - started_at)) / 3600.0 AS hours
                      FROM ghost_shifts
                     WHERE kind = $1
                       AND started_at > now() - ($2 || ' days')::interval
                       AND ($4::bigint IS NULL OR guild_id = $4)
                       AND {sane}
                  GROUP BY user_id
                  ORDER BY hours DESC
                     LIMIT 25
                """, kind, str(days), str(max_hours), guild_id)

            # 2. Проверка отчётов: сколько подтвердили, сколько завернули
            data["review"] = await conn.fetch("""
                SELECT review_state, count(*) AS n
                  FROM ghost_shifts
                 WHERE kind = $1
                   AND started_at > now() - ($2 || ' days')::interval
                   AND ended_at IS NOT NULL
                   AND review_state <> 'none'
                   AND ($3::bigint IS NULL OR guild_id = $3)
              GROUP BY review_state
            """, kind, str(long_days), guild_id)

            # 3. Средняя длительность смены и сколько смен забыли закрыть
            data["duration"] = await conn.fetchrow(f"""
                SELECT count(*) AS shifts,
                       avg(extract(epoch FROM ended_at - started_at)) / 3600.0 AS avg_hours,
                       max(extract(epoch FROM ended_at - started_at)) / 3600.0 AS max_hours
                  FROM ghost_shifts
                 WHERE kind = $1
                   AND started_at > now() - ($2 || ' days')::interval
                   AND ($4::bigint IS NULL OR guild_id = $4)
                   AND {sane}
            """, kind, str(long_days), str(max_hours), guild_id)

            data["forgotten"] = await conn.fetchval("""
                SELECT count(*) FROM ghost_shifts
                 WHERE kind = $1
                   AND started_at > now() - ($2 || ' days')::interval
                   AND ($4::bigint IS NULL OR guild_id = $4)
                   AND (ended_at IS NULL
                        OR ended_at - started_at > ($3 || ' hours')::interval)
            """, kind, str(long_days), str(max_hours), guild_id)

            # 4. Молчуны: когда человек в последний раз выходил на смену
            data["last_seen"] = await conn.fetch("""
                SELECT user_id, max(started_at) AS last_at, count(*) AS shifts
                  FROM ghost_shifts
                 WHERE kind = $1
                   AND ($2::bigint IS NULL OR guild_id = $2)
              GROUP BY user_id
            """, kind, guild_id)

            data["silent_days"] = silent_days

            # 5. Ивенты. Типов у ивента нет: поле заполнено - ивент был,
            # пусто - не планировался. Ссылку от описания отличаем по http,
            # это единственное деление, которое не выдумано за ивентёров
            data["events"] = await conn.fetchrow("""
                SELECT count(*) FILTER (WHERE planned)              AS planned,
                       count(*) FILTER (WHERE planned AND linked)   AS linked,
                       count(*)                                     AS shifts
                  FROM (
                        SELECT btrim(coalesce(event_text, '')) <> ''       AS planned,
                               coalesce(event_text, '') ~* 'https?://'     AS linked
                          FROM ghost_shifts
                         WHERE kind = $1
                           AND started_at > now() - ($2 || ' days')::interval
                           AND ($3::bigint IS NULL OR guild_id = $3)
                       ) AS s
            """, kind, str(long_days), guild_id)

            data["rounds"] = await conn.fetchrow("""
                SELECT count(DISTINCT round_id) AS total,
                       count(DISTINCT round_id) FILTER (
                           WHERE btrim(coalesce(event_text, '')) <> ''
                       ) AS with_event
                  FROM ghost_shifts
                 WHERE kind = $1
                   AND started_at > now() - ($2 || ' days')::interval
                   AND round_id IS NOT NULL
                   AND ($3::bigint IS NULL OR guild_id = $3)
            """, kind, str(long_days), guild_id)

            return data

        return await self._safe("get_report_data", operation)

    async def user_summary(self, user_id, kind=None, days=30, max_hours=12):
        """Короткая сводка по человеку: смены, часы, проверка."""
        async def operation(conn):
            return await conn.fetchrow("""
                SELECT count(*) AS shifts,
                       count(*) FILTER (WHERE review_state = 'approved') AS approved,
                       count(*) FILTER (WHERE review_state = 'rejected') AS rejected,
                       count(*) FILTER (WHERE review_state = 'pending'
                                          AND ended_at IS NOT NULL)      AS pending,
                       coalesce(sum(extract(epoch FROM ended_at - started_at))
                                FILTER (WHERE ended_at IS NOT NULL
                                          AND ended_at > started_at
                                          AND ended_at - started_at
                                              <= ($4 || ' hours')::interval), 0) / 3600.0 AS hours,
                       max(started_at) AS last_at
                  FROM ghost_shifts
                 WHERE user_id = $1
                   AND ($2::text IS NULL OR kind = $2)
                   AND started_at > now() - ($3 || ' days')::interval
            """, user_id, kind, str(days), str(max_hours))

        return await self._safe("user_summary", operation)
