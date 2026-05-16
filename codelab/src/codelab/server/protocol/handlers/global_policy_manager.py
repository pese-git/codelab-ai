"""Управление глобальными permission policies.

Singleton для управления глобальными разрешениями инструментов.
Предоставляет высокоуровневый API для работы с GlobalPolicyStorage
и кэширование policies в памяти для улучшения производительности.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

from ...storage.global_policy_storage import GlobalPolicyStorage

logger = structlog.get_logger()


class GlobalPolicyManager:
    """Singleton для управления глобальными permission policies.

    Предоставляет высокоуровневый API для работы с GlobalPolicyStorage.
    Кэширует policies в памяти для performance.

    Thread-safe операции через asyncio.Lock на уровне класса.

    Спецификация допустимых decisions:
    - allow_always: автоматически разрешить все инструменты этого типа
    - reject_always: автоматически отклонить все инструменты этого типа
    """

    _instance: GlobalPolicyManager | None = None
    _lock: asyncio.Lock | None = None  # создаётся лениво в текущем event loop

    # Допустимые решения (синхронизировано с GlobalPolicyStorage)
    VALID_DECISIONS = ("allow_always", "reject_always")

    @classmethod
    def _get_lock(cls) -> asyncio.Lock:
        """Получить или создать Lock в текущем event loop.

        Ленивая инициализация гарантирует что Lock привязан
        к активному event loop, а не к loop на момент импорта модуля.
        """
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        return cls._lock

    @classmethod
    async def get_instance(
        cls, storage_path: Path | None = None
    ) -> GlobalPolicyManager:
        """Получить singleton instance. Thread-safe.

        При первом вызове создаёт экземпляр с GlobalPolicyStorage.
        При последующих вызовах возвращает существующий экземпляр.

        Args:
            storage_path: Путь к JSON файлу с policies.
                         Default: ~/.acp/global_permissions.json
                         Игнорируется если экземпляр уже создан.

        Returns:
            GlobalPolicyManager: Singleton instance.
        """
        if cls._instance is not None:
            return cls._instance

        async with cls._get_lock():
            # Double-check pattern для thread-safety
            if cls._instance is not None:
                return cls._instance

            storage = GlobalPolicyStorage(storage_path=storage_path)
            cls._instance = cls(storage)
            await cls._instance.initialize()
            logger.debug("GlobalPolicyManager singleton created and initialized")
            return cls._instance

    def __init__(self, storage: GlobalPolicyStorage) -> None:
        """Private constructor. Use get_instance().

        Args:
            storage: GlobalPolicyStorage instance для персистентного хранилища.
        """
        self._storage = storage
        self._cache: dict[str, str] | None = None

    async def initialize(self) -> None:
        """Инициализировать manager (загрузить policies в кэш).

        Загружает все policies из хранилища в кэш для последующих операций.

        Raises:
            StorageError: Если не удалось загрузить policies из хранилища.
        """
        try:
            self._cache = await self._storage.load()
            logger.debug("global_policy_manager_initialized", policy_count=len(self._cache))
        except Exception as e:
            logger.error("global_policy_manager_init_failed", error=str(e))
            raise

    async def get_global_policy(self, tool_kind: str) -> str | None:
        """Получить global policy для tool_kind.

        Args:
            tool_kind: Тип инструмента (например, 'execute', 'write_file').

        Returns:
            decision: 'allow_always', 'reject_always' или None если не установлена.
        """
        if self._cache is None:
            logger.warning("Cache is None, loading from storage")
            self._cache = await self._storage.load()

        return self._cache.get(tool_kind)

    async def set_global_policy(self, tool_kind: str, decision: str) -> None:
        """Установить global policy. Валидация decision.

        Args:
            tool_kind: Тип инструмента (например, 'execute').
            decision: 'allow_always' или 'reject_always'.

        Raises:
            ValueError: Если decision некорректен.
            StorageError: Если не удалось сохранить в хранилище.
        """
        if decision not in self.VALID_DECISIONS:
            raise ValueError(
                f"Invalid decision '{decision}'. "
                f"Must be one of {self.VALID_DECISIONS}"
            )

        if self._cache is None:
            self._cache = await self._storage.load()

        await self._storage.set_policy(tool_kind, decision)
        self._cache[tool_kind] = decision
        logger.debug("global_policy_set", tool_kind=tool_kind, decision=decision)

    async def delete_global_policy(self, tool_kind: str) -> bool:
        """Удалить global policy.

        Args:
            tool_kind: Тип инструмента.

        Returns:
            True если политика была удалена, False если не существовала.

        Raises:
            StorageError: Если не удалось сохранить в хранилище.
        """
        if self._cache is None:
            self._cache = await self._storage.load()

        deleted = await self._storage.delete_policy(tool_kind)

        if deleted and tool_kind in self._cache:
            del self._cache[tool_kind]
            logger.debug("global_policy_deleted", tool_kind=tool_kind)

        return deleted

    async def list_global_policies(self) -> dict[str, str]:
        """Получить все глобальные policies.

        Returns:
            dict[str, str]: {tool_kind: decision}. Копия кэша.
        """
        if self._cache is None:
            self._cache = await self._storage.load()

        return dict(self._cache)

    async def clear_all_policies(self) -> None:
        """Удалить все глобальные policies.

        Raises:
            StorageError: Если не удалось сохранить в хранилище.
        """
        await self._storage.clear_all()
        self._cache = {}
        logger.debug("Cleared all global policies")

    async def _invalidate_cache(self) -> None:
        """Инвалидировать кэш (reload from storage).

        Вызывается когда нужно синхронизировать кэш с хранилищем.
        Используется внутренне для обеспечения консистентности.

        Raises:
            StorageError: Если не удалось загрузить из хранилища.
        """
        self._cache = await self._storage.load()
        logger.debug("Cache invalidated, reloaded from storage")

    @classmethod
    def reset_for_testing(cls) -> None:
        """Сбросить singleton состояние. Использовать ТОЛЬКО в тестах.

        Сбрасывает и instance и lock, чтобы в новом тесте
        lock создался в новом event loop.
        """
        cls._instance = None
        cls._lock = None
        logger.debug("GlobalPolicyManager reset for testing")

