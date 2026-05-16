"""LRU-обёртка над SessionStorage с ограниченным кэшем.

Создаёт единый кэш на уровне хранилища, устраняя дублирование
кэширования между ACPProtocol._sessions и JsonFileStorage._cache.
"""

from __future__ import annotations

from collections import OrderedDict

import structlog

from ..protocol.state import SessionState
from .base import SessionStorage

logger = structlog.get_logger()

DEFAULT_CACHE_SIZE = 200  # максимум сессий в памяти


class CachedSessionStorage(SessionStorage):
    """SessionStorage с LRU-кэшем фиксированного размера.

    Оборачивает любой SessionStorage backend и добавляет кэш
    для снижения нагрузки на I/O при частых обращениях к активным сессиям.

    При переполнении кэша самая старая (least recently used) запись
    удаётся, но остаётся доступна через backend.

    Пример использования:
        backend = JsonFileStorage(path)
        storage = CachedSessionStorage(backend=backend, max_size=200)
    """

    def __init__(
        self,
        backend: SessionStorage,
        max_size: int = DEFAULT_CACHE_SIZE,
    ) -> None:
        """Инициализирует кэширующее хранилище.

        Args:
            backend: Базовое хранилище для персистентности.
            max_size: Максимальное количество сессий в LRU-кэше.
        """
        self._backend = backend
        self._max_size = max_size
        # OrderedDict работает как LRU: move_to_end при каждом обращении
        self._cache: OrderedDict[str, SessionState] = OrderedDict()

    def _put(self, session: SessionState) -> None:
        """Добавить в кэш, вытолкнув самую старую запись при переполнении."""
        session_id = session.session_id
        if session_id in self._cache:
            self._cache.move_to_end(session_id)
            self._cache[session_id] = session
        else:
            if len(self._cache) >= self._max_size:
                evicted_id, _ = self._cache.popitem(last=False)
                logger.debug("session_cache_evicted", session_id=evicted_id)
            self._cache[session_id] = session

    def _invalidate(self, session_id: str) -> None:
        """Удалить сессию из кэша."""
        self._cache.pop(session_id, None)

    async def save_session(self, session: SessionState) -> None:
        """Сохраняет сессию в backend и обновляет кэш."""
        await self._backend.save_session(session)
        self._put(session)

    async def load_session(self, session_id: str) -> SessionState | None:
        """Загружает сессию из кэша или backend."""
        if session_id in self._cache:
            self._cache.move_to_end(session_id)
            return self._cache[session_id]
        session = await self._backend.load_session(session_id)
        if session is not None:
            self._put(session)
        return session

    async def delete_session(self, session_id: str) -> bool:
        """Удаляет сессию из кэша и backend."""
        self._invalidate(session_id)
        return await self._backend.delete_session(session_id)

    async def list_sessions(
        self,
        cwd: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[list[SessionState], str | None]:
        """Возвращает список сессий через backend (без прогрева кэша)."""
        return await self._backend.list_sessions(cwd=cwd, cursor=cursor, limit=limit)

    async def session_exists(self, session_id: str) -> bool:
        """Проверяет существование сессии в кэше или backend."""
        if session_id in self._cache:
            return True
        return await self._backend.session_exists(session_id)

    @property
    def cache_size(self) -> int:
        """Текущий размер кэша."""
        return len(self._cache)
