"""Тесты SessionRuntimeRegistry."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from codelab.server.protocol.session_runtime import (
    SessionRuntimeRegistry,
    SessionRuntimeState,
)


class TestSessionRuntimeRegistry:
    """Тесты lifecycle registry."""

    @pytest.mark.asyncio
    async def test_get_or_create(self):
        """Тест получения или создания состояния."""
        registry = SessionRuntimeRegistry()
        state = await registry.get_or_create("sess_1")
        assert state is not None
        assert state.mcp_manager is None

    @pytest.mark.asyncio
    async def test_get_nonexistent(self):
        """Тест получения несуществующего состояния."""
        registry = SessionRuntimeRegistry()
        state = await registry.get("sess_nonexistent")
        assert state is None

    @pytest.mark.asyncio
    async def test_set_mcp_manager(self):
        """Тест установки MCP manager."""
        registry = SessionRuntimeRegistry()
        mock_manager = MagicMock()
        await registry.set_mcp_manager("sess_1", mock_manager)
        state = await registry.get("sess_1")
        assert state.mcp_manager is mock_manager

    @pytest.mark.asyncio
    async def test_remove_calls_shutdown(self):
        """Тест удаления с вызовом shutdown."""
        registry = SessionRuntimeRegistry()
        mock_manager = MagicMock()
        mock_manager.shutdown = AsyncMock()
        await registry.set_mcp_manager("sess_1", mock_manager)
        await registry.remove("sess_1")
        mock_manager.shutdown.assert_called_once()
        state = await registry.get("sess_1")
        assert state is None

    @pytest.mark.asyncio
    async def test_cleanup_all(self):
        """Тест очистки всех состояний."""
        registry = SessionRuntimeRegistry()
        mock_manager1 = MagicMock()
        mock_manager1.shutdown = AsyncMock()
        mock_manager2 = MagicMock()
        mock_manager2.shutdown = AsyncMock()
        await registry.set_mcp_manager("sess_1", mock_manager1)
        await registry.set_mcp_manager("sess_2", mock_manager2)
        await registry.cleanup()
        mock_manager1.shutdown.assert_called_once()
        mock_manager2.shutdown.assert_called_once()
        state = await registry.get("sess_1")
        assert state is None

    @pytest.mark.asyncio
    async def test_concurrent_access(self):
        """Тест concurrent get_or_create."""
        registry = SessionRuntimeRegistry()
        tasks = [registry.get_or_create("sess_1") for _ in range(10)]
        results = await asyncio.gather(*tasks)
        # Все должны вернуть один и тот же объект
        assert all(r is results[0] for r in results)

    @pytest.mark.asyncio
    async def test_remove_without_mcp_manager(self):
        """Тест удаления без MCP manager (не должно вызывать ошибок)."""
        registry = SessionRuntimeRegistry()
        await registry.get_or_create("sess_1")
        await registry.remove("sess_1")
        state = await registry.get("sess_1")
        assert state is None

    @pytest.mark.asyncio
    async def test_cleanup_without_mcp_managers(self):
        """Тест очистки без MCP managers (не должно вызывать ошибок)."""
        registry = SessionRuntimeRegistry()
        await registry.get_or_create("sess_1")
        await registry.get_or_create("sess_2")
        await registry.cleanup()
        state = await registry.get("sess_1")
        assert state is None

    @pytest.mark.asyncio
    async def test_set_mcp_manager_creates_state(self):
        """Тест что set_mcp_manager создает состояние если его нет."""
        registry = SessionRuntimeRegistry()
        mock_manager = MagicMock()
        await registry.set_mcp_manager("sess_new", mock_manager)
        state = await registry.get("sess_new")
        assert state is not None
        assert state.mcp_manager is mock_manager
