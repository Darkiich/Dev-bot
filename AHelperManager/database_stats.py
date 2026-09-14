"""
Статистика игроков из базы SS14: часы по ролям, раунды, заходы, персонажи.

Имена колонок у форков различаются, поэтому при первом запросе они читаются
из information_schema и запоминаются. Итог пишется в лог.
"""

import asyncio
import logging
import time

from datetime import timedelta

from AHelperManager.database_ss14 import DatabaseManagerSS14
from dataConfig import PLAYER_TOP_MAX_YEARS, PLAYER_TOP_SKIP_GRANTED
from player_jobs import OVERALL

logger = logging.getLogger(__name__)

TRACKERS_TTL = 3600 # список ролей меняется только с обновлением игры


class SchemaError(RuntimeError):
    """Структура игровой базы не та, которую ждёт бот."""


def to_timedelta(value) -> timedelta:
    """Время из play_time. Обычно interval, но бывает и число секунд."""
    if isinstance(value, timedelta):
        return value
    if isinstance(value, (int, float)):
        return timedelta(seconds=float(value))
    return timedelta()


class DatabaseManagerStats(DatabaseManagerSS14):
    """Читает игровую базу. Ничего в неё не пишет."""

    def __init__(self):
        super().__init__()
        self._schema = {}
        self._trackers = {}
        self._lock = asyncio.Lock()

    #  Разбор схемы
    async def _table_columns(self, conn, table: str) -> dict:
        rows = await conn.fetch("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = $1
        """, table)
        return {row["column_name"]: row["data_type"] for row in rows}

    @staticmethod
    def _pick(columns: dict, table: str, *names: str) -> str:
        for name in names:
            if name in columns:
                return name
        raise SchemaError(f"в таблице {table} нет ни одной из колонок: {', '.join(names)}")

    async def schema(self, conn, db_name: str = "mrp") -> dict:
        """Имена колонок в этой базе. Считается один раз и запоминается."""
        cached = self._schema.get(db_name)
        if cached is not None:
            return cached

        async with self._lock:
            cached = self._schema.get(db_name)
            if cached is not None:
                return cached

            play = await self._table_columns(conn, "play_time")
            if not play:
                raise SchemaError("в базе нет таблицы play_time")

            rounds = await self._table_columns(conn, "round")
            if not rounds:
                raise SchemaError("в базе нет таблицы round")

            player_round = await self._table_columns(conn, "player_round")
            connection_log = await self._table_columns(conn, "connection_log")
            profile = await self._table_columns(conn, "profile")
            preference = await self._table_columns(conn, "preference")
            ban = await self._table_columns(conn, "ban")
            job = await self._table_columns(conn, "job")
            trait = await self._table_columns(conn, "trait")
            role_unban = await self._table_columns(conn, "role_unban")

            pt_player = self._pick(play, "play_time", "player_id", "user_id", "player_user_id")
            pr_player = (
                self._pick(player_round, "player_round", "players_id", "player_id", "players_player_id")
                if player_round else None
            )
            pr_round = (
                self._pick(player_round, "player_round", "rounds_id", "round_id", "rounds_round_id")
                if player_round else None
            )
            cl_time = self._pick(connection_log, "connection_log", "time", "connection_time") if connection_log else None

            info = {
                "pt_player": pt_player,
                "pt_player_uuid": play[pt_player] == "uuid",
                "pt_tracker": self._pick(play, "play_time", "tracker", "tracker_id"),
                "pt_time": self._pick(play, "play_time", "time_spent", "timespent", "time"),

                "round_id": self._pick(rounds, "round", "round_id", "id"),
                "round_start": self._pick(rounds, "round", "start_date", "start_time", "started_at"),

                "pr_player": pr_player,
                "pr_round": pr_round,
                "pr_player_uuid": bool(player_round) and player_round[pr_player] == "uuid",

                "cl_user": self._pick(connection_log, "connection_log", "user_id") if connection_log else None,
                "cl_time": cl_time,
                "cl_tz": bool(cl_time) and connection_log[cl_time] == "timestamp with time zone",
                "cl_denied": "denied" in connection_log,

                "pt_time_type": play[self._pick(play, "play_time", "time_spent", "timespent", "time")],

                "profile": profile,
                "preference": preference,
                "job": "profile_id" in job and "job_name" in job,
                "job_priority": "priority" in job,
                "trait": "profile_id" in trait and "trait_name" in trait,
                "ban_type": "type" in ban,
                "ban_role": next((c for c in ("role_id", "role") if c in ban), None),
                "role_unban": "ban_id" in role_unban and "unban_time" in role_unban,
            }

            self._schema[db_name] = info
            logger.info("Схема статистики (%s): %s", db_name, {
                k: v for k, v in info.items() if k not in ("profile", "preference")
            })
            return info

    @staticmethod
    def _player_key(info: dict, player, uuid_field: str):
        """Каким ключом эта таблица ссылается на игрока: UUID или player_id."""
        return player["user_id"] if info[uuid_field] else player["player_id"]

    async def _names(self, conn, keys: list, uuid_key: bool) -> dict:
        """Ники по ключам игроков одним запросом."""
        if not keys:
            return {}

        if uuid_key:
            rows = await conn.fetch("""
                SELECT user_id AS k, last_seen_user_name AS n FROM player WHERE user_id = ANY($1::uuid[])
            """, keys)
        else:
            rows = await conn.fetch("""
                SELECT player_id AS k, last_seen_user_name AS n FROM player WHERE player_id = ANY($1::int[])
            """, keys)

        return {row["k"]: row["n"] for row in rows}

    #  Игрок
    async def player_row(self, guid, db_name: str = "mrp"):
        """Строка игрока по GUID: player_id, даты, ник."""
        conn = await self.get_connection(db_name)
        try:
            return await conn.fetchrow("""
                SELECT player_id, user_id, first_seen_time, last_seen_time, last_seen_user_name
                FROM player WHERE user_id = $1
            """, guid)
        finally:
            await conn.close()

    async def summary(self, guid, db_name: str = "mrp") -> dict:
        """Карточка игрока: общее время, раунды и время по ролям."""
        conn = await self.get_connection(db_name)
        try:
            info = await self.schema(conn, db_name)

            player = await conn.fetchrow("""
                SELECT player_id, user_id, first_seen_time, last_seen_time, last_seen_user_name
                FROM player WHERE user_id = $1
            """, guid)
            if player is None:
                return {}

            rows = await conn.fetch(f"""
                SELECT {info['pt_tracker']} AS tracker, {info['pt_time']} AS time_spent
                FROM play_time WHERE {info['pt_player']} = $1
            """, self._player_key(info, player, "pt_player_uuid"))

            rounds = None
            if info["pr_player"]:
                rounds = await conn.fetchval(f"""
                    SELECT COUNT(*) FROM player_round WHERE {info['pr_player']} = $1
                """, self._player_key(info, player, "pr_player_uuid"))

            times = {row["tracker"]: to_timedelta(row["time_spent"]) for row in rows}

            return {
                "player": player,
                "overall": times.get(OVERALL, timedelta()),
                "rounds": int(rounds or 0),
                "times": times,
            }
        finally:
            await conn.close()

    async def trackers(self, db_name: str = "mrp") -> list:
        """Все трекеры, которые встречаются на сервере. Кэш на час."""
        cached = self._trackers.get(db_name)
        if cached and cached[0] > time.monotonic():
            return cached[1]

        conn = await self.get_connection(db_name)
        try:
            info = await self.schema(conn, db_name)
            rows = await conn.fetch(f"SELECT DISTINCT {info['pt_tracker']} AS tracker FROM play_time")
            trackers = sorted(row["tracker"] for row in rows if row["tracker"])
        finally:
            await conn.close()

        self._trackers[db_name] = (time.monotonic() + TRACKERS_TTL, trackers)
        return trackers

    #  Заходы и стрик
    async def connection_days(self, guid, timezone_name: str, db_name: str = "mrp") -> list:
        """Даты, когда игрок заходил на сервер, от новых к старым."""
        conn = await self.get_connection(db_name)
        try:
            info = await self.schema(conn, db_name)
            if not info["cl_user"] or not info["cl_time"]:
                raise SchemaError("в базе нет таблицы connection_log")

            column = info["cl_time"]
            local = (
                f"({column} AT TIME ZONE $2::text)"
                if info["cl_tz"]
                else f"(({column} AT TIME ZONE 'UTC') AT TIME ZONE $2::text)"
            )
            denied = "AND denied IS NULL" if info["cl_denied"] else ""

            rows = await conn.fetch(f"""
                SELECT DISTINCT {local}::date AS day
                FROM connection_log
                WHERE {info['cl_user']} = $1 {denied}
                  AND {column} > now() - interval '3 years'
                ORDER BY day DESC
            """, guid, timezone_name)

            return [row["day"] for row in rows]
        finally:
            await conn.close()

    #  Баны
    async def bans(self, guid, db_name: str = "mrp") -> list:
        """Все баны игрока, включая джоббаны, от новых к старым."""
        conn = await self.get_connection(db_name)
        try:
            info = await self.schema(conn, db_name)

            type_column = "b.type AS ban_type," if info["ban_type"] else "NULL::int AS ban_type,"
            role_column = f"b.{info['ban_role']} AS role," if info["ban_role"] else "NULL::text AS role,"

            if info["role_unban"]:
                unban_join = """
                    LEFT JOIN unban u ON b.ban_id = u.ban_id
                    LEFT JOIN role_unban ru ON b.ban_id = ru.ban_id
                """
                unban_time = "COALESCE(u.unban_time, ru.unban_time) AS unban_time"
            else:
                unban_join = "LEFT JOIN unban u ON b.ban_id = u.ban_id"
                unban_time = "u.unban_time AS unban_time"

            rows = await conn.fetch(f"""
                SELECT
                    b.ban_id,
                    b.ban_time,
                    b.expiration_time,
                    b.reason,
                    {type_column}
                    {role_column}
                    COALESCE(p.last_seen_user_name, 'Неизвестно') AS admin_nickname,
                    {unban_time}
                FROM ban b
                INNER JOIN ban_player bp ON b.ban_id = bp.ban_id
                LEFT JOIN player p ON b.banning_admin = p.user_id
                {unban_join}
                WHERE bp.user_id = $1
                ORDER BY b.ban_id DESC
                LIMIT 50
            """, guid)

            return list(rows)
        finally:
            await conn.close()

    #  Рейтинги
    async def top_by_tracker(self, tracker: str, limit: int = 10, db_name: str = "mrp") -> list:
        """Топ игроков по времени в конкретном трекере."""
        conn = await self.get_connection(db_name)
        try:
            info = await self.schema(conn, db_name)

            key = "user_id" if info["pt_player_uuid"] else "player_id"

            args = [tracker, limit]
            cap = ""
            if PLAYER_TOP_MAX_YEARS:
                args.append(int(PLAYER_TOP_MAX_YEARS))
                cap = f"AND pt.{info['pt_time']} <= ${len(args)}::int * interval '1 year'"

            granted = ""
            if PLAYER_TOP_SKIP_GRANTED:
                column = f"pt.{info['pt_time']}"
                granted = f"AND date_trunc('minute', {column}) <> {column}"

            rows = await conn.fetch(f"""
                SELECT COALESCE(pl.last_seen_user_name, 'Неизвестно') AS ckey,
                       pt.{info['pt_time']} AS time_spent
                FROM play_time pt
                JOIN player pl ON pl.{key} = pt.{info['pt_player']}
                WHERE pt.{info['pt_tracker']} = $1
                  {cap}
                  {granted}
                ORDER BY pt.{info['pt_time']} DESC
                LIMIT $2
            """, *args)

            return [
                {"ckey": row["ckey"], "time": to_timedelta(row["time_spent"])}
                for row in rows
            ]
        finally:
            await conn.close()

    async def top_by_rounds(self, days: int = None, limit: int = 10, db_name: str = "mrp") -> list:
        """Топ по числу раундов. days=None - за всё время."""
        conn = await self.get_connection(db_name)
        try:
            info = await self.schema(conn, db_name)
            if not info["pr_player"]:
                raise SchemaError("в базе нет таблицы player_round")

            if days is None:
                rows = await conn.fetch(f"""
                    SELECT pr.{info['pr_player']} AS k, COUNT(*) AS n
                    FROM player_round pr
                    GROUP BY 1 ORDER BY n DESC LIMIT $1
                """, limit)
            else:
                rows = await conn.fetch(f"""
                    SELECT pr.{info['pr_player']} AS k, COUNT(*) AS n
                    FROM player_round pr
                    JOIN round r ON r.{info['round_id']} = pr.{info['pr_round']}
                    WHERE r.{info['round_start']} >= now() - $1::interval
                    GROUP BY 1 ORDER BY n DESC LIMIT $2
                """, timedelta(days=days), limit)

            names = await self._names(conn, [row["k"] for row in rows], info["pr_player_uuid"])

            return [
                {"ckey": names.get(row["k"]) or "Неизвестно", "rounds": int(row["n"])}
                for row in rows
            ]
        finally:
            await conn.close()

    async def rank_by_tracker(self, guid, trackers: list, db_name: str = "mrp") -> dict:
        """Места игрока в рейтингах по времени: {трекер: (место, всего, время)}."""
        conn = await self.get_connection(db_name)
        try:
            info = await self.schema(conn, db_name)

            player = await conn.fetchrow("SELECT player_id, user_id FROM player WHERE user_id = $1", guid)
            if player is None:
                return {}

            key = self._player_key(info, player, "pt_player_uuid")
            places = {}

            for tracker in trackers:
                mine = await conn.fetchval(f"""
                    SELECT {info['pt_time']} FROM play_time
                    WHERE {info['pt_player']} = $1 AND {info['pt_tracker']} = $2
                """, key, tracker)
                if mine is None:
                    continue

                better = await conn.fetchval(f"""
                    SELECT COUNT(*) FROM play_time
                    WHERE {info['pt_tracker']} = $1 AND {info['pt_time']} > $2
                """, tracker, mine)

                total = await conn.fetchval(f"""
                    SELECT COUNT(*) FROM play_time WHERE {info['pt_tracker']} = $1
                """, tracker)

                places[tracker] = (int(better) + 1, int(total), to_timedelta(mine))

            return places
        finally:
            await conn.close()

    async def rank_by_rounds(self, guid, days: int = None, db_name: str = "mrp"):
        """Место по раундам: (место, всего, раундов) или None. days=None - за всё время."""
        conn = await self.get_connection(db_name)
        try:
            info = await self.schema(conn, db_name)
            if not info["pr_player"]:
                return None

            player = await conn.fetchrow("SELECT player_id, user_id FROM player WHERE user_id = $1", guid)
            if player is None:
                return None

            key = self._player_key(info, player, "pr_player_uuid")

            if days is None:
                row = await conn.fetchrow(f"""
                    WITH counted AS (
                        SELECT pr.{info['pr_player']} AS k, COUNT(*) AS n
                        FROM player_round pr
                        GROUP BY 1
                    )
                    SELECT
                        (SELECT n FROM counted WHERE k = $1) AS mine,
                        (SELECT COUNT(*) FROM counted WHERE n > COALESCE((SELECT n FROM counted WHERE k = $1), 0)) AS better,
                        (SELECT COUNT(*) FROM counted) AS total
                """, key)
            else:
                row = await conn.fetchrow(f"""
                    WITH counted AS (
                        SELECT pr.{info['pr_player']} AS k, COUNT(*) AS n
                        FROM player_round pr
                        JOIN round r ON r.{info['round_id']} = pr.{info['pr_round']}
                        WHERE r.{info['round_start']} >= now() - $1::interval
                        GROUP BY 1
                    )
                    SELECT
                        (SELECT n FROM counted WHERE k = $2) AS mine,
                        (SELECT COUNT(*) FROM counted WHERE n > COALESCE((SELECT n FROM counted WHERE k = $2), 0)) AS better,
                        (SELECT COUNT(*) FROM counted) AS total
                """, timedelta(days=days), key)

            if row is None or row["mine"] is None:
                return None

            return int(row["better"]) + 1, int(row["total"]), int(row["mine"])
        finally:
            await conn.close()

    async def common_rounds(self, guid_a, guid_b, db_name: str = "mrp") -> int:
        """Сколько раундов двое провели в одном раунде."""
        conn = await self.get_connection(db_name)
        try:
            info = await self.schema(conn, db_name)
            if not info["pr_player"]:
                return 0

            rows = await conn.fetch("""
                SELECT player_id, user_id FROM player WHERE user_id = ANY($1::uuid[])
            """, [guid_a, guid_b])
            if len(rows) < 2:
                return 0

            by_guid = {str(row["user_id"]): row for row in rows}
            first = by_guid.get(str(guid_a))
            second = by_guid.get(str(guid_b))
            if first is None or second is None:
                return 0

            total = await conn.fetchval(f"""
                SELECT COUNT(*) FROM player_round a
                JOIN player_round b ON a.{info['pr_round']} = b.{info['pr_round']}
                WHERE a.{info['pr_player']} = $1 AND b.{info['pr_player']} = $2
            """, self._player_key(info, first, "pr_player_uuid"),
                 self._player_key(info, second, "pr_player_uuid"))

            return int(total or 0)
        finally:
            await conn.close()

    #  Персонажи
    def _profile_columns(self, info: dict) -> list:
        """Колонки персонажа, которые есть в этой базе."""
        wanted = (
            "profile_id", "char_name", "species", "age", "sex", "gender", "flavor_text", "slot",
            "hair_name", "hair_color", "facial_hair_name", "facial_hair_color",
            "eye_color", "skin_color", "height", "width",
        )
        return [c for c in wanted if c in info["profile"]]

    async def characters_of(self, guid, db_name: str = "mrp") -> list:
        """Персонажи игрока по его GUID."""
        conn = await self.get_connection(db_name)
        try:
            info = await self.schema(conn, db_name)
            if "char_name" not in info["profile"] or "user_id" not in info["preference"]:
                raise SchemaError("в базе нет таблиц profile и preference")

            columns = ", ".join(f"p.{c}" for c in self._profile_columns(info))
            order = "p.slot" if "slot" in info["profile"] else "p.char_name"

            rows = await conn.fetch(f"""
                SELECT {columns}
                FROM profile p
                JOIN preference pr ON pr.preference_id = p.preference_id
                WHERE pr.user_id = $1
                ORDER BY {order}
            """, guid)

            return list(rows)
        finally:
            await conn.close()

    async def characters_by_name(self, name: str, db_name: str = "mrp") -> list:
        """Поиск персонажа по имени. Владелец не возвращается: это метагейм."""
        conn = await self.get_connection(db_name)
        try:
            info = await self.schema(conn, db_name)
            if "char_name" not in info["profile"]:
                raise SchemaError("в базе нет таблицы profile")

            columns = ", ".join(f"p.{c}" for c in self._profile_columns(info))

            rows = await conn.fetch(f"""
                SELECT {columns}, pr.user_id AS owner_user_id
                FROM profile p
                JOIN preference pr ON pr.preference_id = p.preference_id
                WHERE p.char_name ILIKE $1
                ORDER BY p.char_name
                LIMIT 25
            """, f"%{name}%")

            return list(rows)
        finally:
            await conn.close()

    async def character_extras(self, profile_id, db_name: str = "mrp") -> dict:
        """Приоритеты ролей и черты персонажа. Чего нет в базе - того нет в карточке."""
        if profile_id is None:
            return {}

        conn = await self.get_connection(db_name)
        try:
            info = await self.schema(conn, db_name)
            extras = {}

            if info["job"]:
                priority = "priority" if info["job_priority"] else "NULL::int"
                rows = await conn.fetch(f"""
                    SELECT job_name, {priority} AS priority
                    FROM job WHERE profile_id = $1
                    ORDER BY {priority} DESC NULLS LAST, job_name
                """, profile_id)
                extras["jobs"] = [(row["job_name"], row["priority"]) for row in rows]

            if info["trait"]:
                rows = await conn.fetch("""
                    SELECT trait_name FROM trait WHERE profile_id = $1 ORDER BY trait_name
                """, profile_id)
                extras["traits"] = [row["trait_name"] for row in rows]

            return extras
        finally:
            await conn.close()

    #  Снимки часов для динамики
    async def overall_minutes(self, active_days: int = 60, db_name: str = "mrp") -> list:
        """Общее время всех, кто заходил за active_days: [(user_id, минуты)]."""
        conn = await self.get_connection(db_name)
        try:
            info = await self.schema(conn, db_name)
            key = "user_id" if info["pt_player_uuid"] else "player_id"

            rows = await conn.fetch(f"""
                SELECT pl.user_id AS user_id, pt.{info['pt_time']} AS time_spent
                FROM play_time pt
                JOIN player pl ON pl.{key} = pt.{info['pt_player']}
                WHERE pt.{info['pt_tracker']} = $1
                  AND pl.last_seen_time > now() - $2::interval
            """, OVERALL, timedelta(days=active_days))

            return [
                (row["user_id"], int(to_timedelta(row["time_spent"]).total_seconds() // 60))
                for row in rows
            ]
        finally:
            await conn.close()
