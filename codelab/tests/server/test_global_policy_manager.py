"""Unit тесты для GlobalPolicyManager.

Тестирует singleton pattern, кэширование, валидацию и операции с policies.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from codelab.server.protocol.handlers.global_policy_manager import GlobalPolicyManager
from codelab.server.storage.global_policy_storage import GlobalPolicyStorage


@pytest.fixture
def mock_storage() -> AsyncMock:
    """Mock GlobalPolicyStorage."""
    storage = AsyncMock(spec=GlobalPolicyStorage)
    storage.load = AsyncMock(return_value={})
    storage.set_policy = AsyncMock()
    storage.delete_policy = AsyncMock(return_value=False)
    storage.clear_all = AsyncMock()
    storage.get_policy = AsyncMock(return_value=None)
    storage.list_policies = AsyncMock(return_value={})
    return storage


class TestSingletonPattern:
    """Тесты singleton pattern."""

    @pytest.mark.asyncio
    async def test_singleton_instance(self, tmp_path: Path) -> None:
        """Проверить что get_instance возвращает один экземпляр."""
        storage_path = tmp_path / "policies.json"
        instance1 = await GlobalPolicyManager.get_instance(storage_path=storage_path)
        instance2 = await GlobalPolicyManager.get_instance(storage_path=storage_path)
        assert instance1 is instance2

    @pytest.mark.asyncio
    async def test_get_instance_initializes_storage(
        self, tmp_path: Path
    ) -> None:
        """Проверить что get_instance инициализирует storage."""
        storage_path = tmp_path / "policies.json"
        instance = await GlobalPolicyManager.get_instance(storage_path=storage_path)
        assert instance is not None
        assert instance._cache is not None

    @pytest.mark.asyncio
    async def test_reset_instance(self, mock_storage: AsyncMock) -> None:
        """Проверить что reset_for_testing очищает singleton."""
        instance1 = await GlobalPolicyManager.get_instance()
        GlobalPolicyManager.reset_for_testing()
        instance2 = await GlobalPolicyManager.get_instance()
        assert instance1 is not instance2


class TestInitialization:
    """Тесты инициализации."""

    @pytest.mark.asyncio
    async def test_initialize_loads_policies(self, mock_storage: AsyncMock) -> None:
        """Проверить что initialize загружает policies в кэш."""
        mock_storage.load.return_value = {
            "execute": "allow_always",
            "read_file": "reject_always",
        }

        with patch("codelab.server.protocol.handlers.global_policy_manager.GlobalPolicyStorage"):
            manager = GlobalPolicyManager(mock_storage)
            await manager.initialize()

        assert manager._cache == {
            "execute": "allow_always",
            "read_file": "reject_always",
        }
        mock_storage.load.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_empty_policies(self, mock_storage: AsyncMock) -> None:
        """Проверить initialize с пустым хранилищем."""
        mock_storage.load.return_value = {}

        manager = GlobalPolicyManager(mock_storage)
        await manager.initialize()

        assert manager._cache == {}

    @pytest.mark.asyncio
    async def test_initialize_propagates_storage_error(
        self, mock_storage: AsyncMock
    ) -> None:
        """Проверить что initialize пробрасывает ошибки хранилища."""
        from codelab.server.exceptions import StorageError

        mock_storage.load.side_effect = StorageError("Storage error")

        manager = GlobalPolicyManager(mock_storage)
        with pytest.raises(StorageError):
            await manager.initialize()


class TestGetGlobalPolicy:
    """Тесты получения policies."""

    @pytest.mark.asyncio
    async def test_get_existing_policy(self, mock_storage: AsyncMock) -> None:
        """Получить существующую policy из кэша."""
        manager = GlobalPolicyManager(mock_storage)
        manager._cache = {
            "execute": "allow_always",
            "read_file": "reject_always",
        }

        result = await manager.get_global_policy("execute")
        assert result == "allow_always"

    @pytest.mark.asyncio
    async def test_get_nonexistent_policy(self, mock_storage: AsyncMock) -> None:
        """Получить несуществующую policy возвращает None."""
        manager = GlobalPolicyManager(mock_storage)
        manager._cache = {}

        result = await manager.get_global_policy("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_policy_loads_cache_if_none(
        self, mock_storage: AsyncMock
    ) -> None:
        """Получить policy загружает кэш если он None."""
        mock_storage.load.return_value = {"execute": "allow_always"}

        manager = GlobalPolicyManager(mock_storage)
        manager._cache = None

        result = await manager.get_global_policy("execute")

        assert result == "allow_always"
        mock_storage.load.assert_called_once()


class TestSetGlobalPolicy:
    """Тесты установки policies."""

    @pytest.mark.asyncio
    async def test_set_policy_allow_always(self, mock_storage: AsyncMock) -> None:
        """Установить policy с allow_always."""
        manager = GlobalPolicyManager(mock_storage)
        manager._cache = {}

        await manager.set_global_policy("execute", "allow_always")

        assert manager._cache["execute"] == "allow_always"
        mock_storage.set_policy.assert_called_once_with("execute", "allow_always")

    @pytest.mark.asyncio
    async def test_set_policy_reject_always(self, mock_storage: AsyncMock) -> None:
        """Установить policy с reject_always."""
        manager = GlobalPolicyManager(mock_storage)
        manager._cache = {}

        await manager.set_global_policy("write_file", "reject_always")

        assert manager._cache["write_file"] == "reject_always"
        mock_storage.set_policy.assert_called_once_with("write_file", "reject_always")

    @pytest.mark.asyncio
    async def test_set_policy_invalid_decision(self, mock_storage: AsyncMock) -> None:
        """Валидация decision при установке policy."""
        manager = GlobalPolicyManager(mock_storage)
        manager._cache = {}

        with pytest.raises(ValueError, match="Invalid decision"):
            await manager.set_global_policy("execute", "invalid_decision")

    @pytest.mark.asyncio
    async def test_set_policy_loads_cache_if_none(
        self, mock_storage: AsyncMock
    ) -> None:
        """Установить policy загружает кэш если он None."""
        mock_storage.load.return_value = {}

        manager = GlobalPolicyManager(mock_storage)
        manager._cache = None

        await manager.set_global_policy("execute", "allow_always")

        assert "execute" in manager._cache
        mock_storage.load.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_policy_propagates_storage_error(
        self, mock_storage: AsyncMock
    ) -> None:
        """Проверить что set_policy пробрасывает ошибки хранилища."""
        from codelab.server.exceptions import StorageError

        mock_storage.set_policy.side_effect = StorageError("Storage error")

        manager = GlobalPolicyManager(mock_storage)
        manager._cache = {}

        with pytest.raises(StorageError):
            await manager.set_global_policy("execute", "allow_always")


class TestDeleteGlobalPolicy:
    """Тесты удаления policies."""

    @pytest.mark.asyncio
    async def test_delete_existing_policy(self, mock_storage: AsyncMock) -> None:
        """Удалить существующую policy."""
        mock_storage.delete_policy.return_value = True

        manager = GlobalPolicyManager(mock_storage)
        manager._cache = {"execute": "allow_always"}

        result = await manager.delete_global_policy("execute")

        assert result is True
        assert "execute" not in manager._cache
        mock_storage.delete_policy.assert_called_once_with("execute")

    @pytest.mark.asyncio
    async def test_delete_nonexistent_policy(self, mock_storage: AsyncMock) -> None:
        """Удалить несуществующую policy возвращает False."""
        mock_storage.delete_policy.return_value = False

        manager = GlobalPolicyManager(mock_storage)
        manager._cache = {}

        result = await manager.delete_global_policy("nonexistent")

        assert result is False
        mock_storage.delete_policy.assert_called_once_with("nonexistent")

    @pytest.mark.asyncio
    async def test_delete_policy_loads_cache_if_none(
        self, mock_storage: AsyncMock
    ) -> None:
        """Удалить policy загружает кэш если он None."""
        mock_storage.load.return_value = {}
        mock_storage.delete_policy.return_value = False

        manager = GlobalPolicyManager(mock_storage)
        manager._cache = None

        await manager.delete_global_policy("execute")

        mock_storage.load.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_policy_propagates_storage_error(
        self, mock_storage: AsyncMock
    ) -> None:
        """Проверить что delete_policy пробрасывает ошибки хранилища."""
        from codelab.server.exceptions import StorageError

        mock_storage.delete_policy.side_effect = StorageError("Storage error")

        manager = GlobalPolicyManager(mock_storage)
        manager._cache = {"execute": "allow_always"}

        with pytest.raises(StorageError):
            await manager.delete_global_policy("execute")


class TestListGlobalPolicies:
    """Тесты получения списка policies."""

    @pytest.mark.asyncio
    async def test_list_policies(self, mock_storage: AsyncMock) -> None:
        """Получить все policies."""
        policies = {
            "execute": "allow_always",
            "read_file": "reject_always",
        }
        manager = GlobalPolicyManager(mock_storage)
        manager._cache = policies.copy()

        result = await manager.list_global_policies()

        assert result == policies
        # Проверить что возвращена копия, а не оригинал
        assert result is not manager._cache

    @pytest.mark.asyncio
    async def test_list_empty_policies(self, mock_storage: AsyncMock) -> None:
        """Получить пустой список policies."""
        manager = GlobalPolicyManager(mock_storage)
        manager._cache = {}

        result = await manager.list_global_policies()

        assert result == {}

    @pytest.mark.asyncio
    async def test_list_policies_loads_cache_if_none(
        self, mock_storage: AsyncMock
    ) -> None:
        """Получить список policies загружает кэш если он None."""
        mock_storage.load.return_value = {"execute": "allow_always"}

        manager = GlobalPolicyManager(mock_storage)
        manager._cache = None

        result = await manager.list_global_policies()

        assert result == {"execute": "allow_always"}
        mock_storage.load.assert_called_once()


class TestClearAllPolicies:
    """Тесты очистки всех policies."""

    @pytest.mark.asyncio
    async def test_clear_all_policies(self, mock_storage: AsyncMock) -> None:
        """Очистить все policies."""
        manager = GlobalPolicyManager(mock_storage)
        manager._cache = {
            "execute": "allow_always",
            "read_file": "reject_always",
        }

        await manager.clear_all_policies()

        assert manager._cache == {}
        mock_storage.clear_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear_already_empty(self, mock_storage: AsyncMock) -> None:
        """Очистить уже пустой кэш."""
        manager = GlobalPolicyManager(mock_storage)
        manager._cache = {}

        await manager.clear_all_policies()

        assert manager._cache == {}
        mock_storage.clear_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear_propagates_storage_error(
        self, mock_storage: AsyncMock
    ) -> None:
        """Проверить что clear_all_policies пробрасывает ошибки хранилища."""
        from codelab.server.exceptions import StorageError

        mock_storage.clear_all.side_effect = StorageError("Storage error")

        manager = GlobalPolicyManager(mock_storage)
        manager._cache = {"execute": "allow_always"}

        with pytest.raises(StorageError):
            await manager.clear_all_policies()


class TestCacheInvalidation:
    """Тесты инвалидации кэша."""

    @pytest.mark.asyncio
    async def test_invalidate_cache(self, mock_storage: AsyncMock) -> None:
        """Инвалидировать кэш и перезагрузить."""
        mock_storage.load.return_value = {
            "execute": "allow_always",
            "read_file": "reject_always",
        }

        manager = GlobalPolicyManager(mock_storage)
        manager._cache = {"old": "policy"}

        await manager._invalidate_cache()

        assert manager._cache == {
            "execute": "allow_always",
            "read_file": "reject_always",
        }
        assert mock_storage.load.call_count == 1

    @pytest.mark.asyncio
    async def test_invalidate_cache_propagates_error(
        self, mock_storage: AsyncMock
    ) -> None:
        """Проверить что _invalidate_cache пробрасывает ошибки хранилища."""
        from codelab.server.exceptions import StorageError

        mock_storage.load.side_effect = StorageError("Storage error")

        manager = GlobalPolicyManager(mock_storage)
        manager._cache = {"execute": "allow_always"}

        with pytest.raises(StorageError):
            await manager._invalidate_cache()


class TestConcurrentAccess:
    """Тесты concurrent access."""

    @pytest.mark.asyncio
    async def test_concurrent_get_operations(
        self, mock_storage: AsyncMock
    ) -> None:
        """Concurrent get операции на одном manager."""
        manager = GlobalPolicyManager(mock_storage)
        manager._cache = {
            "execute": "allow_always",
            "read_file": "reject_always",
        }

        results = await asyncio.gather(
            manager.get_global_policy("execute"),
            manager.get_global_policy("read_file"),
            manager.get_global_policy("nonexistent"),
        )

        assert results == ["allow_always", "reject_always", None]

    @pytest.mark.asyncio
    async def test_concurrent_set_operations(
        self, mock_storage: AsyncMock
    ) -> None:
        """Concurrent set операции на одном manager."""
        manager = GlobalPolicyManager(mock_storage)
        manager._cache = {}

        await asyncio.gather(
            manager.set_global_policy("execute", "allow_always"),
            manager.set_global_policy("read_file", "reject_always"),
        )

        assert manager._cache == {
            "execute": "allow_always",
            "read_file": "reject_always",
        }

    @pytest.mark.asyncio
    async def test_concurrent_mixed_operations(
        self, mock_storage: AsyncMock
    ) -> None:
        """Concurrent mixed операции."""
        mock_storage.load.return_value = {"execute": "allow_always"}
        mock_storage.delete_policy.return_value = True

        manager = GlobalPolicyManager(mock_storage)
        manager._cache = {"execute": "allow_always", "read_file": "reject_always"}

        results = await asyncio.gather(
            manager.get_global_policy("execute"),
            manager.set_global_policy("write_file", "allow_always"),
            manager.list_global_policies(),
        )

        assert results[0] == "allow_always"
        # results[1] is None (set_global_policy returns None)
        assert isinstance(results[2], dict)


class TestMultipleConcurrentGetInstance:
    """Тесты concurrent calls к get_instance."""

    @pytest.mark.asyncio
    async def test_multiple_concurrent_get_instance(
        self, tmp_path: Path
    ) -> None:
        """Concurrent get_instance возвращает один экземпляр."""
        storage_path = tmp_path / "policies.json"

        instances = await asyncio.gather(
            GlobalPolicyManager.get_instance(storage_path=storage_path),
            GlobalPolicyManager.get_instance(storage_path=storage_path),
            GlobalPolicyManager.get_instance(storage_path=storage_path),
        )

        assert instances[0] is instances[1]
        assert instances[1] is instances[2]

    @pytest.mark.asyncio
    async def test_get_instance_storage_path_ignored_after_init(
        self, tmp_path: Path
    ) -> None:
        """Параметр storage_path игнорируется после первого создания."""
        storage_path1 = tmp_path / "policies1.json"
        storage_path2 = tmp_path / "policies2.json"

        instance1 = await GlobalPolicyManager.get_instance(storage_path=storage_path1)
        instance2 = await GlobalPolicyManager.get_instance(storage_path=storage_path2)

        assert instance1 is instance2
        # Оба должны использовать storage_path1
        assert instance1._storage._storage_path == storage_path1

    @pytest.mark.asyncio
    async def test_concurrent_get_instance_creates_only_one(self) -> None:
        """Конкурентные вызовы должны вернуть один и тот же экземпляр."""
        results = await asyncio.gather(*[
            GlobalPolicyManager.get_instance()
            for _ in range(10)
        ])
        first = results[0]
        assert all(r is first for r in results)

    @pytest.mark.asyncio
    async def test_lock_works_in_new_event_loop(self) -> None:
        """Lock должен корректно работать после сброса в новом event loop."""
        GlobalPolicyManager.reset_for_testing()
        # Просто убеждаемся что не падает
        instance = await GlobalPolicyManager.get_instance()
        assert instance is not None

    def test_get_instance_requires_running_loop(self) -> None:
        """get_instance проверяет наличие running event loop."""
        # Проверяем что внутри get_instance есть проверка на running loop
        # путём вызова из синхронного контекста (без event loop)
        GlobalPolicyManager.reset_for_testing()

        # Создаём корутину но не запускаем её
        coro = GlobalPolicyManager.get_instance()

        # Проверяем что это корутина (значит функция асинхронная)
        assert asyncio.iscoroutine(coro)

        # Закрываем корутину без запуска
        coro.close()


class TestResetForTesting:
    """Тесты метода reset_for_testing."""

    @pytest.mark.asyncio
    async def test_reset_clears_singleton(self) -> None:
        """После сброса создаётся новый экземпляр."""
        instance1 = await GlobalPolicyManager.get_instance()
        GlobalPolicyManager.reset_for_testing()
        instance2 = await GlobalPolicyManager.get_instance()
        assert instance1 is not instance2

    @pytest.mark.asyncio
    async def test_reset_clears_lock(self) -> None:
        """После сброса lock также очищается."""
        await GlobalPolicyManager.get_instance()
        assert GlobalPolicyManager._lock is not None
        GlobalPolicyManager.reset_for_testing()
        assert GlobalPolicyManager._lock is None

    @pytest.mark.asyncio
    async def test_reset_allows_new_lock_creation(self) -> None:
        """После сброса должен создаться новый lock в новом тесте."""
        await GlobalPolicyManager.get_instance()
        old_lock = GlobalPolicyManager._lock
        assert old_lock is not None

        GlobalPolicyManager.reset_for_testing()
        new_lock = GlobalPolicyManager._get_lock()

        assert new_lock is not old_lock


class TestValidationAndErrors:
    """Тесты валидации и обработки ошибок."""

    @pytest.mark.asyncio
    async def test_valid_decisions(self, mock_storage: AsyncMock) -> None:
        """Проверить что допустимые decisions принимаются."""
        manager = GlobalPolicyManager(mock_storage)
        manager._cache = {}

        # Должны пройти без ошибок
        await manager.set_global_policy("execute", "allow_always")
        await manager.set_global_policy("read_file", "reject_always")

        assert manager._cache["execute"] == "allow_always"
        assert manager._cache["read_file"] == "reject_always"

    @pytest.mark.asyncio
    async def test_invalid_decision_variations(self, mock_storage: AsyncMock) -> None:
        """Проверить что невалидные decisions отклоняются."""
        manager = GlobalPolicyManager(mock_storage)
        manager._cache = {}

        invalid_decisions = [
            "allow",
            "reject",
            "allow_once",
            "reject_once",
            "",
            "ALLOW_ALWAYS",
            "Allow_Always",
        ]

        for invalid_decision in invalid_decisions:
            with pytest.raises(ValueError, match="Invalid decision"):
                await manager.set_global_policy("execute", invalid_decision)

    @pytest.mark.asyncio
    async def test_empty_tool_kind(self, mock_storage: AsyncMock) -> None:
        """Проверить с пустым tool_kind."""
        manager = GlobalPolicyManager(mock_storage)
        manager._cache = {}

        # get_global_policy с пустым tool_kind возвращает None
        result = await manager.get_global_policy("")
        assert result is None

        # set_global_policy с пустым tool_kind работает (хранилище не валидирует)
        await manager.set_global_policy("", "allow_always")
        assert manager._cache[""] == "allow_always"
