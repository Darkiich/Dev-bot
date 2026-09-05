"""
Класс для работы в бд кадровых действий.

Это отдельный Postgres на VPS, не тот, где живут базы SS14.
Соединение открывается на каждый запрос и сразу закрывается.

Две таблицы:
    team_events  - журнал действий, только вставка, ничего не меняем
    team_members - текущий состав, перезаписывается и чистится
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

# После них есть смысл переоткрыть соединение и повторить запрос
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

ACTIONS = ("hire", "fire", "promote", "demote")

logger = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc)


class DatabaseManagerTeam:
    """
    Класс для работы в бд кадровых действий.
    Ошибки наружу не пробрасываются, команды бота не должны падать из-за БД.
    """

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
        """Новое соединение, при первом обращении проверяет схему."""
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

    async def _prepare(self, conn):
        """Заводит таблицы и индексы, если их ещё нет."""
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS team_events (
                    id            bigserial PRIMARY KEY,
                    happened_at   timestamptz NOT NULL DEFAULT now(),
                    action        text        NOT NULL,
                    ds_id         bigint      NOT NULL,
                    ds_name       text,
                    department    text        NOT NULL,
                    position_from text,
                    position_to   text,
                    role_id_from  bigint,
                    role_id_to    bigint,
                    grade_from    smallint,
                    grade_to      smallint,
                    actor_id      bigint      NOT NULL,
                    actor_name    text,
                    reason        text,
                    source        text        NOT NULL DEFAULT 'command',
                    CONSTRAINT team_events_action_check
                        CHECK (action IN ('hire','fire','promote','demote'))
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS team_members (
                    ds_id          bigint      NOT NULL,
                    role_id        bigint      NOT NULL,
                    department     text        NOT NULL,
                    position       text        NOT NULL,
                    grade          smallint,
                    ds_name        text,
                    hired_at       timestamptz,
                    position_since timestamptz NOT NULL DEFAULT now(),
                    updated_at     timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (ds_id, role_id)
                )
            """)

            for statement in (
                "CREATE INDEX IF NOT EXISTS team_events_person_idx ON team_events (ds_id, happened_at DESC)",
                "CREATE INDEX IF NOT EXISTS team_events_dept_idx   ON team_events (department, happened_at DESC)",
                "CREATE INDEX IF NOT EXISTS team_events_action_idx ON team_events (action, happened_at DESC)",
                "CREATE INDEX IF NOT EXISTS team_events_actor_idx  ON team_events (actor_id, happened_at DESC)",
                "CREATE INDEX IF NOT EXISTS team_members_dept_idx  ON team_members (department)",
            ):
                await conn.execute(statement)

            logger.info("Схема БД кадров проверена")
        except _CONNECTION_ERRORS:
            raise
        except Exception as e:
            # Прав на DDL может не быть, это не повод падать при старте
            logger.exception("Не удалось проверить схему БД кадров: %s", e)

    # ------------------------------------------------------------------ #
    #  Запись действий
    # ------------------------------------------------------------------ #

    @staticmethod
    async def _insert_event(conn, **e):
        await conn.execute("""
            INSERT INTO team_events (
                happened_at, action, ds_id, ds_name, department,
                position_from, position_to, role_id_from, role_id_to,
                grade_from, grade_to, actor_id, actor_name, reason, source
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
        """,
            e["happened_at"], e["action"], e["ds_id"], e["ds_name"], e["department"],
            e["position_from"], e["position_to"], e["role_id_from"], e["role_id_to"],
            e["grade_from"], e["grade_to"], e["actor_id"], e["actor_name"],
            e["reason"], e["source"],
        )

    async def record_hire(self, ds_id, ds_name, position, actor_id, actor_name,
                          reason=None, source="command", hired_at=None):
        """
        Найм: событие плюс строка в составе, одной транзакцией.
        position это объект из team_departments.
        """
        async def operation(conn):
            moment = _now()
            async with conn.transaction():
                await self._insert_event(
                    conn, happened_at=moment, action="hire",
                    ds_id=ds_id, ds_name=ds_name, department=position.department,
                    position_from=None, position_to=position.name,
                    role_id_from=None, role_id_to=position.role_id,
                    grade_from=None, grade_to=position.grade,
                    actor_id=actor_id, actor_name=actor_name,
                    reason=reason, source=source,
                )
                await conn.execute("""
                    INSERT INTO team_members
                        (ds_id, role_id, department, position, grade, ds_name,
                         hired_at, position_since, updated_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$8)
                    ON CONFLICT (ds_id, role_id) DO UPDATE SET
                        department = EXCLUDED.department,
                        position   = EXCLUDED.position,
                        grade      = EXCLUDED.grade,
                        ds_name    = EXCLUDED.ds_name,
                        updated_at = EXCLUDED.updated_at
                """,
                    ds_id, position.role_id, position.department, position.name,
                    position.grade, ds_name,
                    moment if hired_at is None else hired_at, moment,
                )
            return "ok"

        try:
            return True, await self._run("record_hire", operation)
        except Exception as e:
            logger.exception("Ошибка record_hire: %s: %s", type(e).__name__, e)
            return False, f"{type(e).__name__}: {e}"

    async def record_fire(self, ds_id, ds_name, position, actor_id, actor_name,
                          reason=None, source="command"):
        """Увольнение с должности: событие плюс удаление строки из состава."""
        async def operation(conn):
            moment = _now()
            async with conn.transaction():
                await self._insert_event(
                    conn, happened_at=moment, action="fire",
                    ds_id=ds_id, ds_name=ds_name, department=position.department,
                    position_from=position.name, position_to=None,
                    role_id_from=position.role_id, role_id_to=None,
                    grade_from=position.grade, grade_to=None,
                    actor_id=actor_id, actor_name=actor_name,
                    reason=reason, source=source,
                )
                await conn.execute(
                    "DELETE FROM team_members WHERE ds_id = $1 AND role_id = $2",
                    ds_id, position.role_id,
                )
            return "ok"

        try:
            return True, await self._run("record_fire", operation)
        except Exception as e:
            logger.exception("Ошибка record_fire: %s: %s", type(e).__name__, e)
            return False, f"{type(e).__name__}: {e}"

    async def record_move(self, ds_id, ds_name, old_position, new_position,
                          actor_id, actor_name, action="promote",
                          reason=None, source="command"):
        """
        Повышение или понижение: одно событие, старая строка состава заменяется новой.
        Дата прихода в отдел переносится, дата вступления в должность новая.
        """
        if action not in ("promote", "demote"):
            return False, f"Неизвестное действие: {action}"

        async def operation(conn):
            moment = _now()
            async with conn.transaction():
                hired_at = await conn.fetchval(
                    "SELECT hired_at FROM team_members WHERE ds_id = $1 AND role_id = $2",
                    ds_id, old_position.role_id,
                )

                await self._insert_event(
                    conn, happened_at=moment, action=action,
                    ds_id=ds_id, ds_name=ds_name, department=new_position.department,
                    position_from=old_position.name, position_to=new_position.name,
                    role_id_from=old_position.role_id, role_id_to=new_position.role_id,
                    grade_from=old_position.grade, grade_to=new_position.grade,
                    actor_id=actor_id, actor_name=actor_name,
                    reason=reason, source=source,
                )

                await conn.execute(
                    "DELETE FROM team_members WHERE ds_id = $1 AND role_id = $2",
                    ds_id, old_position.role_id,
                )
                await conn.execute("""
                    INSERT INTO team_members
                        (ds_id, role_id, department, position, grade, ds_name,
                         hired_at, position_since, updated_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$8)
                    ON CONFLICT (ds_id, role_id) DO UPDATE SET
                        department     = EXCLUDED.department,
                        position       = EXCLUDED.position,
                        grade          = EXCLUDED.grade,
                        ds_name        = EXCLUDED.ds_name,
                        hired_at       = EXCLUDED.hired_at,
                        position_since = EXCLUDED.position_since,
                        updated_at     = EXCLUDED.updated_at
                """,
                    ds_id, new_position.role_id, new_position.department,
                    new_position.name, new_position.grade, ds_name,
                    hired_at, moment,
                )
            return "ok"

        try:
            return True, await self._run("record_move", operation)
        except Exception as e:
            logger.exception("Ошибка record_move: %s: %s", type(e).__name__, e)
            return False, f"{type(e).__name__}: {e}"

    async def import_members(self, rows):
        """
        Разовый импорт текущего состава. Событие с source='import' и hired_at=NULL,
        чтобы такие люди считались в численности, но не попадали в наймы за период.
        rows: список (ds_id, ds_name, position).
        """
        async def operation(conn):
            moment = _now()
            added = 0
            async with conn.transaction():
                for ds_id, ds_name, position in rows:
                    exists = await conn.fetchval(
                        "SELECT 1 FROM team_members WHERE ds_id = $1 AND role_id = $2",
                        ds_id, position.role_id,
                    )
                    if exists:
                        continue

                    await self._insert_event(
                        conn, happened_at=moment, action="hire",
                        ds_id=ds_id, ds_name=ds_name, department=position.department,
                        position_from=None, position_to=position.name,
                        role_id_from=None, role_id_to=position.role_id,
                        grade_from=None, grade_to=position.grade,
                        actor_id=0, actor_name=None,
                        reason="Импорт текущего состава", source="import",
                    )
                    await conn.execute("""
                        INSERT INTO team_members
                            (ds_id, role_id, department, position, grade, ds_name,
                             hired_at, position_since, updated_at)
                        VALUES ($1,$2,$3,$4,$5,$6,NULL,$7,$7)
                    """,
                        ds_id, position.role_id, position.department,
                        position.name, position.grade, ds_name, moment,
                    )
                    added += 1
            return added

        try:
            return True, await self._run("import_members", operation)
        except Exception as e:
            logger.exception("Ошибка import_members: %s: %s", type(e).__name__, e)
            return False, f"{type(e).__name__}: {e}"

    async def sync_members(self, rows):
        """
        Приводит состав в базе к тому, что сейчас в ролях Discord.
        Кого нет в базе - заводит, чья роль пропала - убирает.

        События пишутся с source='sync', поэтому в наймы и текучку за период
        они не попадают: это не решение главы, а следствие правки ролей руками.
        История при этом не теряется, team_events только дописывается.

        Возвращает (добавлено, убрано).
        """
        async def operation(conn):
            moment = _now()
            wanted = {
                (ds_id, position.role_id): (ds_name, position)
                for ds_id, ds_name, position in rows
            }

            added = removed = 0

            async with conn.transaction():
                existing = await conn.fetch(
                    "SELECT ds_id, role_id, department, position, grade FROM team_members"
                )
                have = {(r["ds_id"], r["role_id"]): r for r in existing}

                for (ds_id, role_id), (ds_name, position) in wanted.items():
                    if (ds_id, role_id) in have:
                        continue

                    await self._insert_event(
                        conn, happened_at=moment, action="hire",
                        ds_id=ds_id, ds_name=ds_name, department=position.department,
                        position_from=None, position_to=position.name,
                        role_id_from=None, role_id_to=position.role_id,
                        grade_from=None, grade_to=position.grade,
                        actor_id=0, actor_name=None,
                        reason="Роль выдана вне бота", source="sync",
                    )
                    await conn.execute("""
                        INSERT INTO team_members
                            (ds_id, role_id, department, position, grade, ds_name,
                             hired_at, position_since, updated_at)
                        VALUES ($1,$2,$3,$4,$5,$6,NULL,$7,$7)
                        ON CONFLICT (ds_id, role_id) DO NOTHING
                    """,
                        ds_id, position.role_id, position.department,
                        position.name, position.grade, ds_name, moment,
                    )
                    added += 1

                for (ds_id, role_id), row in have.items():
                    if (ds_id, role_id) in wanted:
                        continue

                    await self._insert_event(
                        conn, happened_at=moment, action="fire",
                        ds_id=ds_id, ds_name=None, department=row["department"],
                        position_from=row["position"], position_to=None,
                        role_id_from=role_id, role_id_to=None,
                        grade_from=row["grade"], grade_to=None,
                        actor_id=0, actor_name=None,
                        reason="Роль снята вне бота", source="sync",
                    )
                    await conn.execute(
                        "DELETE FROM team_members WHERE ds_id = $1 AND role_id = $2",
                        ds_id, role_id,
                    )
                    removed += 1

            return added, removed

        try:
            return True, await self._run("sync_members", operation)
        except Exception as e:
            logger.exception("Ошибка sync_members: %s: %s", type(e).__name__, e)
            return False, f"{type(e).__name__}: {e}"

    # ------------------------------------------------------------------ #
    #  Чтение
    # ------------------------------------------------------------------ #

    async def get_member_positions(self, ds_id):
        """
        Все должности участника. Пустой список это "должностей нет",
        None это "БД недоступна". Путать нельзя: по этим данным снимаются роли.
        """
        async def operation(conn):
            return await conn.fetch(
                "SELECT * FROM team_members WHERE ds_id = $1 ORDER BY department, grade",
                ds_id,
            )

        try:
            return [dict(r) for r in await self._run("get_member_positions", operation)]
        except Exception as e:
            logger.exception("Ошибка get_member_positions: %s: %s", type(e).__name__, e)
            return None

    async def get_department_members(self, department):
        """Состав отдела, сверху вниз по лестнице. None при ошибке."""
        async def operation(conn):
            return await conn.fetch(
                "SELECT * FROM team_members WHERE department = $1 "
                "ORDER BY grade DESC NULLS LAST, position",
                department,
            )

        try:
            return [dict(r) for r in await self._run("get_department_members", operation)]
        except Exception as e:
            logger.exception("Ошибка get_department_members: %s: %s", type(e).__name__, e)
            return None

    async def get_all_members(self):
        """Весь состав. None при ошибке."""
        async def operation(conn):
            return await conn.fetch("SELECT * FROM team_members")

        try:
            return [dict(r) for r in await self._run("get_all_members", operation)]
        except Exception as e:
            logger.exception("Ошибка get_all_members: %s: %s", type(e).__name__, e)
            return None

    async def get_events(self, ds_id=None, department=None, limit=20):
        """История действий. Без фильтров отдаёт последние по всем. None при ошибке."""
        async def operation(conn):
            if ds_id is not None:
                return await conn.fetch(
                    "SELECT * FROM team_events WHERE ds_id = $1 "
                    "ORDER BY happened_at DESC LIMIT $2", ds_id, limit,
                )
            if department is not None:
                return await conn.fetch(
                    "SELECT * FROM team_events WHERE department = $1 "
                    "ORDER BY happened_at DESC LIMIT $2", department, limit,
                )
            return await conn.fetch(
                "SELECT * FROM team_events ORDER BY happened_at DESC LIMIT $1", limit,
            )

        try:
            return [dict(r) for r in await self._run("get_events", operation)]
        except Exception as e:
            logger.exception("Ошибка get_events: %s: %s", type(e).__name__, e)
            return None

    async def get_report_data(self, movement_days=30, turnover_days=90):
        """
        Всё для отчёта одним соединением, отдельными запросами ходить дорого.
        Импортированные строки в движении не учитываются: у них source='import'.
        None при ошибке, отчёт в этом случае не перерисовывается.
        """
        async def operation(conn):
            data = {}

            data["members"] = await conn.fetch("SELECT * FROM team_members")

            data["movement"] = await conn.fetch("""
                SELECT department, action, count(*) AS n
                FROM team_events
                WHERE source = 'command'
                  AND happened_at >= now() - make_interval(days => $1)
                GROUP BY department, action
            """, movement_days)

            data["actors"] = await conn.fetch("""
                SELECT actor_id, max(actor_name) AS actor_name, count(*) AS n
                FROM team_events
                WHERE source = 'command' AND actor_id <> 0
                  AND happened_at >= now() - make_interval(days => $1)
                GROUP BY actor_id
                ORDER BY n DESC
                LIMIT 10
            """, movement_days)

            data["turnover"] = await conn.fetch("""
                SELECT department,
                       count(*) FILTER (WHERE action = 'hire') AS hires,
                       count(*) FILTER (WHERE action = 'fire') AS fires
                FROM team_events
                WHERE source = 'command'
                  AND happened_at >= now() - make_interval(days => $1)
                GROUP BY department
            """, turnover_days)

            # Когорты по дате прихода. Тех, кто попал импортом, тут нет:
            # у них нет события найма командой, а значит и даты прихода.
            data["cohorts"] = await conn.fetch("""
                WITH first_hire AS (
                    SELECT ds_id, min(happened_at) AS joined
                    FROM team_events
                    WHERE action = 'hire' AND source = 'command'
                    GROUP BY ds_id
                )
                SELECT
                    CASE
                        WHEN joined >= now() - interval '90 days'  THEN 90
                        WHEN joined >= now() - interval '180 days' THEN 180
                        ELSE 999
                    END AS bucket,
                    count(*) AS total,
                    count(*) FILTER (
                        WHERE EXISTS (
                            SELECT 1 FROM team_members m WHERE m.ds_id = first_hire.ds_id
                        )
                    ) AS alive
                FROM first_hire
                WHERE joined < now() - interval '30 days'
                GROUP BY bucket
                ORDER BY bucket
            """)

            return data

        try:
            data = await self._run("get_report_data", operation)
            return {key: [dict(r) for r in rows] for key, rows in data.items()}
        except Exception as e:
            logger.exception("Ошибка get_report_data: %s: %s", type(e).__name__, e)
            return None
