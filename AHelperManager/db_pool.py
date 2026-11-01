"""
Пулы соединений с базами
"""

import asyncio
import logging
import time

import asyncpg

logger = logging.getLogger(__name__)

ACQUIRE_TIMEOUT = 20
RELEASE_TIMEOUT = 5
IDLE_LIFETIME = 1800
MAX_QUERIES = 50_000


class _NoResetConnection(asyncpg.Connection):
    """Без RESET ALL при возврате в пул."""

    def get_reset_query(self):
        return ""


def _lock_for(locks: dict, key, loop) -> asyncio.Lock:
    entry = locks.get(key)
    if entry is None or entry[1] is not loop:
        entry = locks[key] = (asyncio.Lock(), loop)
    return entry[0]


#  PostgreSQL
class PooledConnection:
    """close() возвращает соединение в пул."""

    __slots__ = ("_proxy", "_pool", "_done")

    def __init__(self, proxy, pool):
        self._proxy = proxy
        self._pool = pool
        self._done = False

    def __getattr__(self, name):
        return getattr(self._proxy, name)

    async def close(self, *, timeout=None):
        if self._done:
            return
        self._done = True
        try:
            await self._pool.release(self._proxy, timeout=timeout or RELEASE_TIMEOUT)
        except Exception as e:
            logger.warning("Соединение не вернулось в пул: %s: %s", type(e).__name__, e)

    def terminate(self):
        if not self._done:
            self._done = True
            self._proxy.terminate()

    def __del__(self):
        if self._done:
            return
        self._done = True
        try:
            loop = self._pool._loop
            if loop is not None and not loop.is_closed():
                loop.call_soon_threadsafe(
                    lambda: loop.create_task(self._pool.release(self._proxy, timeout=RELEASE_TIMEOUT))
                )
                logger.warning("Соединение с базой не закрыли явно, вернул его в пул сам")
        except Exception:
            pass


class _PgPools:
    def __init__(self):
        self._pools = {}
        self._locks = {}

    async def get(self, key: tuple, connect_kwargs: dict, min_size: int, max_size: int) -> asyncpg.Pool:
        loop = asyncio.get_running_loop()
        entry = self._pools.get(key)
        if entry is not None and entry[1] is loop and not entry[0].is_closing():
            return entry[0]

        lock = _lock_for(self._locks, key, loop)
        async with lock:
            entry = self._pools.get(key)
            if entry is not None and entry[1] is loop and not entry[0].is_closing():
                return entry[0]

            started = time.perf_counter()
            pool = await asyncpg.create_pool(
                **connect_kwargs,
                min_size=min_size,
                max_size=max_size,
                max_queries=MAX_QUERIES,
                max_inactive_connection_lifetime=IDLE_LIFETIME,
                connection_class=_NoResetConnection,
            )
            self._pools[key] = (pool, loop)
            logger.info(
                "Пул соединений открыт: %s:%s/%s, до %d соединений (%.0f мс)",
                key[0], key[1], key[3], max_size, (time.perf_counter() - started) * 1000,
            )
            return pool

    async def close_all(self):
        for pool, _ in list(self._pools.values()):
            try:
                await asyncio.wait_for(pool.close(), timeout=10)
            except Exception:
                pool.terminate()
        self._pools.clear()


_pg = _PgPools()


async def pg_connection(connect_kwargs: dict, *, min_size: int = 1, max_size: int = 10) -> PooledConnection:
    key = (
        str(connect_kwargs.get("host")),
        str(connect_kwargs.get("port")),
        str(connect_kwargs.get("user")),
        str(connect_kwargs.get("database")),
        str(connect_kwargs.get("command_timeout")),
    )
    pool = await _pg.get(key, connect_kwargs, min_size, max_size)
    proxy = await pool.acquire(timeout=ACQUIRE_TIMEOUT)
    return PooledConnection(proxy, pool)


#  MySQL
class PooledMyConnection:
    """close() возвращает соединение в пул."""

    __slots__ = ("_conn", "_pool", "_done")

    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool
        self._done = False

    def __getattr__(self, name):
        return getattr(self._conn, name)

    @property
    def raw(self):
        return self._conn

    def close(self):
        if self._done:
            return
        self._done = True
        try:
            self._pool.release(self._conn)
        except Exception as e:
            logger.warning("Соединение MySQL не вернулось в пул: %s: %s", type(e).__name__, e)

    async def ensure_closed(self):
        self.close()


class _MyPools:
    def __init__(self):
        self._pools = {}
        self._locks = {}

    async def get(self, key: tuple, connect_kwargs: dict, max_size: int):
        import aiomysql

        loop = asyncio.get_running_loop()
        entry = self._pools.get(key)
        if entry is not None and entry[1] is loop and not entry[0].closed:
            return entry[0]

        lock = _lock_for(self._locks, key, loop)
        async with lock:
            entry = self._pools.get(key)
            if entry is not None and entry[1] is loop and not entry[0].closed:
                return entry[0]

            pool = await aiomysql.create_pool(
                minsize=1,
                maxsize=max_size,
                pool_recycle=IDLE_LIFETIME,
                **connect_kwargs,
            )
            self._pools[key] = (pool, loop)
            logger.info("Пул соединений MySQL открыт: %s:%s/%s, до %d соединений", *key[:2], key[3], max_size)
            return pool


_my = _MyPools()


async def mysql_connection(connect_kwargs: dict, *, max_size: int = 5) -> PooledMyConnection:
    key = (
        str(connect_kwargs.get("host")),
        str(connect_kwargs.get("port")),
        str(connect_kwargs.get("user")),
        str(connect_kwargs.get("db")),
    )
    pool = await _my.get(key, connect_kwargs, max_size)
    conn = await asyncio.wait_for(pool.acquire(), timeout=ACQUIRE_TIMEOUT)
    return PooledMyConnection(conn, pool)


async def close_all():
    await _pg.close_all()
    for pool, _ in list(_my._pools.values()):
        pool.close()
        await pool.wait_closed()
    _my._pools.clear()
