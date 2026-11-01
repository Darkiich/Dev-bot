"""
Общий кэш тяжёлых запросов
"""

import asyncio
import logging
import time
from collections import OrderedDict

logger = logging.getLogger(__name__)


class SharedResult:
    __slots__ = ("loader", "ttl", "max_age", "name", "value", "loaded_at", "_task")

    def __init__(self, loader, ttl: float, max_age: float, name: str):
        self.loader = loader
        self.ttl = ttl
        self.max_age = max_age
        self.name = name
        self.value = None
        self.loaded_at = 0.0
        self._task = None

    def _age(self) -> float:
        return time.monotonic() - self.loaded_at

    def peek(self):
        if self.value is None or self._age() >= self.max_age:
            return None
        if self._age() >= self.ttl:
            self._start()
        return self.value

    async def get(self):
        value = self.peek()
        if value is not None:
            return value
        return await asyncio.shield(self._start())

    def warm(self):
        if self.peek() is None:
            self._start()

    def _start(self) -> asyncio.Task:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._load())
            self._task.add_done_callback(self._report)
        return self._task

    async def _load(self):
        started = time.perf_counter()
        value = await self.loader()
        self.value = value
        self.loaded_at = time.monotonic()
        logger.info("Пересчитано %s за %.0f мс", self.name, (time.perf_counter() - started) * 1000)
        return value

    def _report(self, task: asyncio.Task):
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.warning("Не удалось пересчитать %s: %s: %s", self.name, type(error).__name__, error)


class SharedCache:
    def __init__(self, ttl: float, max_age: float, limit: int = 64):
        self.ttl = ttl
        self.max_age = max_age
        self.limit = limit
        self._items = OrderedDict()

    def entry(self, key, loader, name: str) -> SharedResult:
        item = self._items.get(key)
        if item is None:
            item = SharedResult(loader, self.ttl, self.max_age, name)
            self._items[key] = item
            while len(self._items) > self.limit:
                self._items.popitem(last=False)
        else:
            self._items.move_to_end(key)
        return item

    async def get(self, key, loader, name: str):
        return await self.entry(key, loader, name).get()
