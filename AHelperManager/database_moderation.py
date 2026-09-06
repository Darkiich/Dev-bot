"""
Журнал модерации Discord.

Живёт в том же Postgres, что и кадровая база, в своей таблице mod_cases:
все действия модераторов, каждое со своим номером кейса.

Соединение открывается на запрос и сразу закрывается - как в остальных
менеджерах проекта. Ошибки наружу не пробрасываются: если база прилегла,
модерация обязана продолжать работать, просто без истории.
"""

import asyncio
import logging

from datetime import datetime, timedelta, timezone

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

ACTIONS = (
    # Выдаёт сам бот
    "warn", "mute", "kick", "ban", "softban", "note", "unmute", "unban", "unwarn",
    "lock", "unlock",
    # Сделано руками через интерфейс Discord
    "timeout", "untimeout", "nick", "purge", "prune",
    "voice_kick", "voice_move", "voice_mute", "voice_unmute",
    "voice_deaf", "voice_undeaf",
)

# Почему кейс закрыт: срок вышел, сняли руками, заменили новым наказанием
CLOSE_KINDS = ("expired", "revoked", "replaced")

logger = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc)


class DatabaseManagerModeration:
    """Хранит кейсы модерации."""

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
                CREATE TABLE IF NOT EXISTS mod_cases (
                    id             bigserial PRIMARY KEY,
                    guild_id       bigint      NOT NULL,
                    action         text        NOT NULL,
                    target_id      bigint      NOT NULL,
                    target_name    text,
                    actor_id       bigint      NOT NULL,
                    actor_name     text,
                    reason         text,
                    created_at     timestamptz NOT NULL DEFAULT now(),
                    expires_at     timestamptz,
                    active         boolean     NOT NULL DEFAULT true,
                    closed_at      timestamptz,
                    closed_by      bigint,
                    closed_name    text,
                    close_reason   text,
                    close_kind     text,
                    channel_id     bigint,
                    message_url    text,
                    log_message_id bigint,
                    parent_id      bigint,
                    source         text        NOT NULL DEFAULT 'command'
                )
            """)
            for statement in (
                "CREATE INDEX IF NOT EXISTS mod_cases_target_idx ON mod_cases (target_id, created_at DESC)",
                "CREATE INDEX IF NOT EXISTS mod_cases_actor_idx  ON mod_cases (actor_id, created_at DESC)",
                "CREATE INDEX IF NOT EXISTS mod_cases_due_idx    ON mod_cases (active, expires_at)",
                "CREATE INDEX IF NOT EXISTS mod_cases_action_idx ON mod_cases (action, created_at DESC)",
            ):
                await conn.execute(statement)

            logger.info("Схема БД модерации проверена")
        except _CONNECTION_ERRORS:
            raise
        except Exception as e:
            # Прав на DDL может не быть, это не повод падать при старте
            logger.exception("Не удалось проверить схему БД модерации: %s", e)

    # ------------------------------------------------------------------ #
    #  Кейсы
    # ------------------------------------------------------------------ #

    async def add_case(self, guild_id, action, target_id, target_name,
                       actor_id, actor_name, reason=None, expires_at=None,
                       channel_id=None, message_url=None, parent_id=None,
                       source="command", active=True):
        """
        Заводит кейс и возвращает его строку. None, если база недоступна:
        наказание при этом всё равно выдаётся, просто без номера.
        """
        async def operation(conn):
            return await conn.fetchrow("""
                INSERT INTO mod_cases (
                    guild_id, action, target_id, target_name, actor_id, actor_name,
                    reason, created_at, expires_at, active, channel_id, message_url,
                    parent_id, source
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                RETURNING *
            """,
                guild_id, action, target_id, target_name, actor_id, actor_name,
                reason, _now(), expires_at, active, channel_id, message_url,
                parent_id, source,
            )

        return await self._safe("add_case", operation)

    async def get_case(self, case_id):
        async def operation(conn):
            return await conn.fetchrow("SELECT * FROM mod_cases WHERE id = $1", case_id)

        return await self._safe("get_case", operation)

    async def set_log_message(self, case_id, message_id):
        """Запоминает сообщение-карточку, чтобы потом её обновлять."""
        async def operation(conn):
            await conn.execute(
                "UPDATE mod_cases SET log_message_id = $2 WHERE id = $1",
                case_id, message_id,
            )
            return True

        return await self._safe("set_log_message", operation, default=False)

    async def update_reason(self, case_id, reason):
        async def operation(conn):
            return await conn.fetchrow(
                "UPDATE mod_cases SET reason = $2 WHERE id = $1 RETURNING *",
                case_id, reason,
            )

        return await self._safe("update_reason", operation)

    async def close_case(self, case_id, kind="revoked", actor_id=None,
                         actor_name=None, reason=None):
        """
        Закрывает кейс: снят руками, истёк сам или заменён новым наказанием.
        Возвращает закрытую строку или None, если кейс уже был закрыт.
        """
        async def operation(conn):
            return await conn.fetchrow("""
                UPDATE mod_cases
                   SET active = false, closed_at = $2, closed_by = $3,
                       closed_name = $4, close_reason = $5, close_kind = $6
                 WHERE id = $1 AND active
             RETURNING *
            """, case_id, _now(), actor_id, actor_name, reason, kind)

        return await self._safe("close_case", operation)

    async def active_case(self, target_id, action, guild_id=None):
        """Текущее незакрытое наказание участника: мут или бан."""
        async def operation(conn):
            return await conn.fetchrow("""
                SELECT * FROM mod_cases
                 WHERE target_id = $1 AND action = $2 AND active
                   AND ($3::bigint IS NULL OR guild_id = $3)
              ORDER BY created_at DESC
                 LIMIT 1
            """, target_id, action, guild_id)

        return await self._safe("active_case", operation)

    async def active_warns(self, target_id, guild_id=None):
        """Варны, которые ещё не сняты и не сгорели по сроку давности."""
        async def operation(conn):
            return await conn.fetch("""
                SELECT * FROM mod_cases
                 WHERE target_id = $1 AND action = 'warn' AND active
                   AND (expires_at IS NULL OR expires_at > now())
                   AND ($2::bigint IS NULL OR guild_id = $2)
              ORDER BY created_at DESC
            """, target_id, guild_id)

        return await self._safe("active_warns", operation, default=[]) or []

    async def active_locks(self, guild_id=None, source=None):
        """Каналы, которые сейчас закрыты ботом."""
        async def operation(conn):
            return await conn.fetch("""
                SELECT * FROM mod_cases
                 WHERE action = 'lock' AND active
                   AND ($1::bigint IS NULL OR guild_id = $1)
                   AND ($2::text IS NULL OR source = $2)
              ORDER BY created_at
            """, guild_id, source)

        return await self._safe("active_locks", operation, default=[]) or []

    async def list_cases(self, target_id, limit=10, offset=0, actions=None):
        """Страница истории участника, свежие сверху."""
        async def operation(conn):
            return await conn.fetch("""
                SELECT * FROM mod_cases
                 WHERE target_id = $1
                   AND ($4::text[] IS NULL OR action = ANY($4))
              ORDER BY created_at DESC
                 LIMIT $2 OFFSET $3
            """, target_id, limit, offset, list(actions) if actions else None)

        return await self._safe("list_cases", operation, default=[]) or []

    async def count_cases(self, target_id):
        """Сколько чего было у участника: {'warn': 3, 'mute': 1, ...}."""
        async def operation(conn):
            rows = await conn.fetch("""
                SELECT action, count(*) AS total
                  FROM mod_cases
                 WHERE target_id = $1
              GROUP BY action
            """, target_id)
            return {row["action"]: row["total"] for row in rows}

        return await self._safe("count_cases", operation, default={}) or {}

    async def due_cases(self, actions=("mute", "ban")):
        """Активные наказания, у которых вышел срок. Их снимает фоновая задача."""
        async def operation(conn):
            return await conn.fetch("""
                SELECT * FROM mod_cases
                 WHERE active AND action = ANY($1)
                   AND expires_at IS NOT NULL AND expires_at <= now()
              ORDER BY expires_at
                 LIMIT 200
            """, list(actions))

        return await self._safe("due_cases", operation, default=[]) or []

    async def expire_warns(self):
        """
        Гасит варны, у которых вышел срок давности. Строки остаются в истории,
        просто перестают считаться активными и учитываться в мерах наказания.
        """
        async def operation(conn):
            rows = await conn.fetch("""
                UPDATE mod_cases
                   SET active = false, closed_at = now(), close_kind = 'expired',
                       close_reason = 'Срок давности'
                 WHERE active AND action = 'warn'
                   AND expires_at IS NOT NULL AND expires_at <= now()
             RETURNING id
            """)
            return len(rows)

        return await self._safe("expire_warns", operation, default=0) or 0

    # ------------------------------------------------------------------ #
    #  Статистика
    # ------------------------------------------------------------------ #

    async def actor_stats(self, days=30, guild_id=None):
        """Кто сколько наказаний выдал за период."""
        async def operation(conn):
            return await conn.fetch("""
                SELECT actor_id, max(actor_name) AS actor_name,
                       count(*) AS total,
                       count(*) FILTER (WHERE action = 'warn') AS warns,
                       count(*) FILTER (WHERE action = 'mute') AS mutes,
                       count(*) FILTER (WHERE action = 'kick') AS kicks,
                       count(*) FILTER (WHERE action IN ('ban','softban')) AS bans
                  FROM mod_cases
                 WHERE created_at > now() - ($1 || ' days')::interval
                   AND action IN ('warn','mute','kick','ban','softban')
                   AND actor_id <> 0
                   AND ($2::bigint IS NULL OR guild_id = $2)
              GROUP BY actor_id
              ORDER BY total DESC
                 LIMIT 20
            """, str(days), guild_id)

        return await self._safe("actor_stats", operation, default=[]) or []

    async def period_totals(self, days=30, guild_id=None):
        """Сводка по действиям за период: {'warn': 12, 'mute': 4, ...}."""
        async def operation(conn):
            rows = await conn.fetch("""
                SELECT action, count(*) AS total
                  FROM mod_cases
                 WHERE created_at > now() - ($1 || ' days')::interval
                   AND ($2::bigint IS NULL OR guild_id = $2)
              GROUP BY action
            """, str(days), guild_id)
            return {row["action"]: row["total"] for row in rows}

        return await self._safe("period_totals", operation, default={}) or {}

    async def top_targets(self, days=30, limit=5, guild_id=None):
        """Кто чаще всех попадал под раздачу за период."""
        async def operation(conn):
            return await conn.fetch("""
                SELECT target_id, max(target_name) AS target_name, count(*) AS total
                  FROM mod_cases
                 WHERE created_at > now() - ($1 || ' days')::interval
                   AND action IN ('warn','mute','kick','ban','softban')
                   AND ($3::bigint IS NULL OR guild_id = $3)
              GROUP BY target_id
              ORDER BY total DESC
                 LIMIT $2
            """, str(days), limit, guild_id)

        return await self._safe("top_targets", operation, default=[]) or []

    # ------------------------------------------------------------------ #
    #  Данные для отчёта
    # ------------------------------------------------------------------ #

    async def get_report_data(self, guild_id=None, short_days=7, long_days=30,
                              chart_days=14, tz="Europe/Moscow"):
        """
        Всё для аналитического отчёта одним походом в базу.

        Отдельными методами это было бы девять соединений подряд, а отчёт
        рисуется по расписанию и торопиться ему некуда, но и трепать базу
        девять раз ради одной картинки незачем.

        None означает, что база не ответила: отчёт тогда лучше не трогать,
        чем перерисовать нулями.
        """
        punish = "('warn','mute','kick','ban','softban')"

        async def operation(conn):
            data = {}

            data["short"] = await conn.fetch(f"""
                SELECT action, count(*) AS n
                  FROM mod_cases
                 WHERE created_at > now() - ($1 || ' days')::interval
                   AND ($2::bigint IS NULL OR guild_id = $2)
              GROUP BY action
            """, str(short_days), guild_id)

            data["long"] = await conn.fetch(f"""
                SELECT action, count(*) AS n
                  FROM mod_cases
                 WHERE created_at > now() - ($1 || ' days')::interval
                   AND ($2::bigint IS NULL OR guild_id = $2)
              GROUP BY action
            """, str(long_days), guild_id)

            # Предыдущий такой же отрезок: нужен, чтобы показать динамику
            data["previous"] = await conn.fetchval(f"""
                SELECT count(*)
                  FROM mod_cases
                 WHERE created_at >  now() - ($1 || ' days')::interval * 2
                   AND created_at <= now() - ($1 || ' days')::interval
                   AND action IN {punish}
                   AND ($2::bigint IS NULL OR guild_id = $2)
            """, str(short_days), guild_id)

            data["daily"] = await conn.fetch(f"""
                SELECT (created_at AT TIME ZONE $3)::date AS day, count(*) AS n
                  FROM mod_cases
                 WHERE created_at > now() - ($1 || ' days')::interval
                   AND action IN {punish}
                   AND ($2::bigint IS NULL OR guild_id = $2)
              GROUP BY day
              ORDER BY day
            """, str(chart_days), guild_id, tz)

            data["hourly"] = await conn.fetch(f"""
                SELECT extract(hour FROM created_at AT TIME ZONE $3)::int AS hour,
                       count(*) AS n
                  FROM mod_cases
                 WHERE created_at > now() - ($1 || ' days')::interval
                   AND action IN {punish}
                   AND ($2::bigint IS NULL OR guild_id = $2)
              GROUP BY hour
            """, str(long_days), guild_id, tz)

            data["actors"] = await conn.fetch(f"""
                SELECT actor_id, max(actor_name) AS actor_name,
                       count(*) AS total,
                       count(*) FILTER (WHERE action = 'warn') AS warns,
                       count(*) FILTER (WHERE action = 'mute') AS mutes,
                       count(*) FILTER (WHERE action = 'kick') AS kicks,
                       count(*) FILTER (WHERE action IN ('ban','softban')) AS bans
                  FROM mod_cases
                 WHERE created_at > now() - ($1 || ' days')::interval
                   AND action IN {punish}
                   AND actor_id <> 0
                   AND ($2::bigint IS NULL OR guild_id = $2)
              GROUP BY actor_id
              ORDER BY total DESC
                 LIMIT 15
            """, str(long_days), guild_id)

            data["revokers"] = await conn.fetch("""
                SELECT closed_by AS actor_id, count(*) AS n
                  FROM mod_cases
                 WHERE closed_at > now() - ($1 || ' days')::interval
                   AND close_kind = 'revoked' AND closed_by IS NOT NULL
                   AND ($2::bigint IS NULL OR guild_id = $2)
              GROUP BY closed_by
              ORDER BY n DESC
                 LIMIT 5
            """, str(long_days), guild_id)

            data["targets"] = await conn.fetch(f"""
                SELECT target_id, max(target_name) AS target_name, count(*) AS n
                  FROM mod_cases
                 WHERE created_at > now() - ($1 || ' days')::interval
                   AND action IN {punish}
                   AND ($2::bigint IS NULL OR guild_id = $2)
              GROUP BY target_id
              ORDER BY n DESC
                 LIMIT 5
            """, str(long_days), guild_id)

            data["repeat"] = await conn.fetchval(f"""
                SELECT count(*) FROM (
                    SELECT target_id
                      FROM mod_cases
                     WHERE created_at > now() - ($1 || ' days')::interval
                       AND action IN {punish}
                       AND ($2::bigint IS NULL OR guild_id = $2)
                  GROUP BY target_id
                    HAVING count(*) > 1
                ) AS t
            """, str(long_days), guild_id)

            data["active"] = await conn.fetchrow("""
                SELECT
                    count(*) FILTER (WHERE action = 'mute' AND active) AS mutes,
                    count(*) FILTER (WHERE action = 'ban'  AND active) AS bans,
                    count(DISTINCT target_id) FILTER (
                        WHERE action = 'warn' AND active
                          AND (expires_at IS NULL OR expires_at > now())
                    ) AS warned
                  FROM mod_cases
                 WHERE ($1::bigint IS NULL OR guild_id = $1)
            """, guild_id)

            return data

        return await self._safe("get_report_data", operation)
