"""Реестр ожидающих asyncio.Future для permission requests.

Хранит runtime-объекты, которые не могут быть сериализованы
и не должны присутствовать в персистируемом SessionState.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from ..messages import JsonRpcId

logger = structlog.get_logger()


class PendingRequestRegistry:
    """Хранилище asyncio.Future для ожидающих permission requests.

    Жизненный цикл: создаётся в ACPProtocol, не персистируется.
    При перезапуске сервера — пересоздаётся пустым.
    """

    def __init__(self) -> None:
        self._futures: dict[JsonRpcId, asyncio.Future[Any]] = {}

    def create(self, request_id: JsonRpcId) -> asyncio.Future[Any]:
        """Создать и зарегистрировать Future для request_id."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._futures[request_id] = future
        logger.debug("pending_request_created", request_id=request_id)
        return future

    def resolve(self, request_id: JsonRpcId, result: Any) -> bool:
        """Завершить Future с результатом. Возвращает True если Future найден."""
        future = self._futures.pop(request_id, None)
        if future is None:
            return False
        if not future.done():
            future.set_result(result)
            logger.debug("pending_request_resolved", request_id=request_id)
        return True

    def cancel(self, request_id: JsonRpcId) -> bool:
        """Отменить Future. Возвращает True если Future найден."""
        future = self._futures.pop(request_id, None)
        if future is None:
            return False
        if not future.done():
            future.cancel()
            logger.debug("pending_request_cancelled", request_id=request_id)
        return True

    def has(self, request_id: JsonRpcId) -> bool:
        """Проверить наличие ожидающего Future."""
        return request_id in self._futures

    def cancel_all(self) -> int:
        """Отменить все ожидающие futures. Возвращает количество отменённых."""
        count = 0
        for request_id in list(self._futures.keys()):
            if self.cancel(request_id):
                count += 1
        return count

    def __len__(self) -> int:
        return len(self._futures)
