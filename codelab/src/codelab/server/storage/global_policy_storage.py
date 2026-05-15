"""Управление глобальными permission policies."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiofiles
import structlog

from ..exceptions import StorageError

logger = structlog.get_logger()


class GlobalPolicyStorage:
    """Управление глобальными permission policies.

    Хранилище: ~/.codelab/data/policies/global_permissions.json
    Thread-safe операции с atomic file writes.

    Пример использования:
        storage = GlobalPolicyStorage()
        policies = await storage.load()
        await storage.set_policy('execute', 'allow_always')
        saved = await storage.save(policies)
    """

    # JSON Schema version
    SCHEMA_VERSION = 1

    # Допустимые решения
    VALID_DECISIONS = ("allow_always", "reject_always")

    # Путь по умолчанию: ~/.codelab/data/policies/global_permissions.json
    _DEFAULT_PATH = Path.home() / ".codelab" / "data" / "policies"
    DEFAULT_STORAGE_PATH = _DEFAULT_PATH / "global_permissions.json"

    def __init__(self, storage_path: Path | None = None) -> None:
        """Инициализирует хранилище.

        Args:
            storage_path: Путь к JSON файлу (default: ~/.codelab/data/policies/)
        """
        self._storage_path = storage_path or self.DEFAULT_STORAGE_PATH
        self._lock = asyncio.Lock()
        self._cache: dict[str, str] | None = None

    async def _ensure_directory(self) -> None:
        """Создаёт директорию если не существует."""
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)

    async def _read_file(self) -> dict[str, Any]:
        """Читает JSON файл с error handling.

        Returns:
            dict с версией и policies

        Raises:
            StorageError: Если файл повреждён или недоступен
        """
        try:
            if not self._storage_path.exists():
                logger.debug("policy_file_not_found", path=str(self._storage_path))
                return {"version": self.SCHEMA_VERSION, "policies": {}, "metadata": {}}

            async with aiofiles.open(self._storage_path) as f:
                content = await f.read()
                if not content.strip():
                    logger.debug("policy_file_empty", path=str(self._storage_path))
                    return {"version": self.SCHEMA_VERSION, "policies": {}, "metadata": {}}

                data = json.loads(content)
                return data
        except json.JSONDecodeError as e:
            error_msg = f"Corrupted JSON in {self._storage_path}: {e}"
            logger.error(error_msg)
            raise StorageError(error_msg) from e
        except OSError as e:
            error_msg = f"Cannot read policy file {self._storage_path}: {e}"
            logger.error(error_msg)
            raise StorageError(error_msg) from e

    async def _write_file(self, policies: dict[str, str]) -> None:
        """Пишет JSON файл atomically (temp file + rename).

        Args:
            policies: dict[str, str] с policies для сохранения

        Raises:
            StorageError: Если не удалось записать файл
        """
        try:
            await self._ensure_directory()

            # Atomic write: write to temp file, then rename
            temp_path = self._storage_path.with_suffix(".json.tmp")

            # Подготовить данные с metadata
            output_data = {
                "version": self.SCHEMA_VERSION,
                "policies": policies,
                "metadata": {
                    "updated_at": datetime.now(UTC).isoformat(),
                    "updated_by": "system",
                },
            }

            # Записать в временный файл
            async with aiofiles.open(temp_path, "w") as f:
                content = json.dumps(output_data, indent=2)
                await f.write(content)

            # Atomically rename
            temp_path.replace(self._storage_path)
            logger.debug("policies_written", path=str(self._storage_path))

        except OSError as e:
            error_msg = f"Cannot write policy file {self._storage_path}: {e}"
            logger.error(error_msg)
            raise StorageError(error_msg) from e
        except Exception as e:
            error_msg = f"Unexpected error writing policy file: {e}"
            logger.error(error_msg)
            raise StorageError(error_msg) from e

    async def load(self) -> dict[str, str]:
        """Загрузить policies из файла.

        Returns:
            dict[str, str]: {tool_kind: decision}

        Raises:
            StorageError: Если файл повреждён или недоступен
        """
        async with self._lock:
            try:
                data = await self._read_file()

                # Валидация версии
                version = data.get("version", 1)
                if version != self.SCHEMA_VERSION:
                    logger.warning(
                        "policy_version_mismatch",
                        file_version=version,
                        expected_version=self.SCHEMA_VERSION,
                    )

                policies = data.get("policies", {})
                self._cache = policies
                logger.debug("policies_loaded", count=len(policies))
                return policies

            except StorageError:
                raise
            except Exception as e:
                error_msg = f"Unexpected error loading policies: {e}"
                logger.error(error_msg)
                raise StorageError(error_msg) from e

    async def save(self, policies: dict[str, str]) -> None:
        """Сохранить policies в файл (atomic write).

        Args:
            policies: dict[str, str] с policies

        Raises:
            StorageError: Если не удалось записать файл
        """
        async with self._lock:
            try:
                # Передаём сами policies (не dict с ключом 'policies')
                await self._write_file(policies)
                self._cache = dict(policies)
            except StorageError:
                raise
            except Exception as e:
                error_msg = f"Unexpected error saving policies: {e}"
                logger.error(error_msg)
                raise StorageError(error_msg) from e

    async def get_policy(self, tool_kind: str) -> str | None:
        """Получить policy для tool_kind.

        Args:
            tool_kind: Тип инструмента (например, 'execute')

        Returns:
            'allow_always', 'reject_always' или None
        """
        async with self._lock:
            # Использовать кэш если загружен
            if self._cache is not None:
                return self._cache.get(tool_kind)

            # Иначе загрузить из файла
            data = await self._read_file()
            policies = data.get("policies", {})
            self._cache = policies
            return policies.get(tool_kind)

    async def set_policy(self, tool_kind: str, decision: str) -> None:
        """Установить policy для tool_kind.

        Args:
            tool_kind: Тип инструмента
            decision: 'allow_always' или 'reject_always'

        Raises:
            ValueError: Если decision некорректен
            StorageError: Если не удалось сохранить
        """
        if decision not in self.VALID_DECISIONS:
            raise ValueError(
                f"Invalid decision '{decision}'. Must be one of {self.VALID_DECISIONS}"
            )

        async with self._lock:
            # Загрузить текущие policies
            data = await self._read_file()
            policies = data.get("policies", {})

            # Обновить
            policies[tool_kind] = decision

            # Сохранить
            await self._write_file(policies)
            self._cache = dict(policies)
            logger.debug("policy_set", tool_kind=tool_kind, decision=decision)

    async def delete_policy(self, tool_kind: str) -> bool:
        """Удалить policy.

        Args:
            tool_kind: Тип инструмента

        Returns:
            True если удалена, False если не существовала

        Raises:
            StorageError: Если не удалось сохранить
        """
        async with self._lock:
            # Загрузить текущие policies
            data = await self._read_file()
            policies = data.get("policies", {})

            # Проверить существование
            if tool_kind not in policies:
                return False

            # Удалить
            del policies[tool_kind]

            # Сохранить
            await self._write_file(policies)
            self._cache = dict(policies)
            logger.debug("policy_deleted", tool_kind=tool_kind)
            return True

    async def list_policies(self) -> dict[str, str]:
        """Получить все policies.

        Returns:
            Копия всех текущих policies
        """
        async with self._lock:
            # Использовать кэш если загружен
            if self._cache is not None:
                return dict(self._cache)

            # Иначе загрузить из файла
            data = await self._read_file()
            policies = data.get("policies", {})
            self._cache = policies
            return dict(policies)

    async def clear_all(self) -> None:
        """Удалить все policies.

        Raises:
            StorageError: Если не удалось сохранить
        """
        async with self._lock:
            # Сохранить пустой dict
            await self._write_file({})
            self._cache = {}
            logger.debug("Cleared all policies")
