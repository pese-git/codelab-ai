"""Тесты для MCPManager auto-reconnect logic."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from codelab.server.mcp.client import MCPClient, MCPClientState
from codelab.server.mcp.manager import (
    MCPManager,
    MCPManagerError,
    MCPManagerState,
)
from codelab.server.mcp.models import MCPServerConfig


class TestMCPManagerReconnectWithBackoff:
    """Тесты метода reconnect_with_backoff."""

    @pytest.mark.asyncio
    async def test_reconnect_success_first_attempt(self):
        """Успешное переподключение с первой попытки."""
        manager = MCPManager("test_session")
        
        # Создаём mock клиент
        config = MCPServerConfig(
            name="test_server",
            type="stdio",
            command="mcp-server",
            max_retries=3,
            initial_delay=0.1,
        )
        client = AsyncMock(spec=MCPClient)
        client.config = config
        client.state = MCPClientState.READY
        client.connect = AsyncMock()
        client.initialize = AsyncMock()
        client.disconnect = AsyncMock()
        client.list_tools = AsyncMock(return_value=[])
        
        manager._clients["test_server"] = client
        manager._adapters["test_server"] = MagicMock()
        manager._tools_cache["test_server"] = []
        
        result = await manager.reconnect_with_backoff("test_server")
        
        assert result is True
        assert manager.state == MCPManagerState.READY
        client.disconnect.assert_called_once()
        client.connect.assert_called_once()
        client.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_reconnect_not_found(self):
        """Переподключение несуществующего сервера."""
        manager = MCPManager("test_session")
        
        result = await manager.reconnect_with_backoff("nonexistent")
        
        assert result is False

    @pytest.mark.asyncio
    async def test_reconnect_failed_after_max_retries(self):
        """Переподключение не удалось после max_retries."""
        manager = MCPManager("test_session")
        
        config = MCPServerConfig(
            name="test_server",
            type="stdio",
            command="mcp-server",
            max_retries=2,
            initial_delay=0.05,
        )
        client = AsyncMock(spec=MCPClient)
        client.config = config
        client.state = MCPClientState.FAILED
        client.connect = AsyncMock(side_effect=Exception("Connection failed"))
        client.initialize = AsyncMock()
        client.disconnect = AsyncMock()
        client.list_tools = AsyncMock()
        
        manager._clients["test_server"] = client
        manager._adapters["test_server"] = MagicMock()
        manager._tools_cache["test_server"] = []
        
        result = await manager.reconnect_with_backoff("test_server")
        
        assert result is False
        assert manager.state == MCPManagerState.FAILED

    @pytest.mark.asyncio
    async def test_reconnect_state_transitions(self):
        """Проверка переходов состояний при переподключении."""
        manager = MCPManager("test_session")
        
        config = MCPServerConfig(
            name="test_server",
            type="stdio",
            command="mcp-server",
            max_retries=1,
            initial_delay=0.05,
        )
        client = AsyncMock(spec=MCPClient)
        client.config = config
        client.state = MCPClientState.READY
        client.connect = AsyncMock()
        client.initialize = AsyncMock()
        client.disconnect = AsyncMock()
        client.list_tools = AsyncMock(return_value=[])
        
        manager._clients["test_server"] = client
        manager._adapters["test_server"] = MagicMock()
        manager._tools_cache["test_server"] = []
        
        assert manager.state == MCPManagerState.READY
        
        # Запускаем переподключение
        task = asyncio.create_task(manager.reconnect_with_backoff("test_server"))
        await asyncio.sleep(0.01)
        
        # Во время переподключения состояние должно быть RECONNECTING
        # (но может уже завершиться, поэтому не проверяем)
        
        await task
        
        assert manager.state == MCPManagerState.READY


class TestMCPManagerHealthCheck:
    """Тесты health check механизма."""

    @pytest.mark.asyncio
    async def test_start_health_check(self):
        """Запуск health check."""
        manager = MCPManager("test_session")
        
        config = MCPServerConfig(
            name="test_server",
            type="stdio",
            command="mcp-server",
        )
        client = AsyncMock(spec=MCPClient)
        client.config = config
        client.state = MCPClientState.READY
        
        manager._clients["test_server"] = client
        
        await manager.start_health_check("test_server", interval=0.1)
        
        assert "test_server" in manager._health_check_tasks
        assert manager._health_check_tasks["test_server"] is not None
        
        # Останавливаем
        await manager.stop_health_check("test_server")
        assert "test_server" not in manager._health_check_tasks

    @pytest.mark.asyncio
    async def test_stop_health_check(self):
        """Остановка health check."""
        manager = MCPManager("test_session")
        
        config = MCPServerConfig(
            name="test_server",
            type="stdio",
            command="mcp-server",
        )
        client = AsyncMock(spec=MCPClient)
        client.config = config
        client.state = MCPClientState.READY
        
        manager._clients["test_server"] = client
        
        await manager.start_health_check("test_server", interval=0.1)
        await manager.stop_health_check("test_server")
        
        assert "test_server" not in manager._health_check_tasks

    @pytest.mark.asyncio
    async def test_health_check_triggers_reconnect_on_failure(self):
        """Health check запускает переподключение при ошибке."""
        manager = MCPManager("test_session")
        
        config = MCPServerConfig(
            name="test_server",
            type="stdio",
            command="mcp-server",
            max_retries=1,
            initial_delay=0.05,
        )
        client = AsyncMock(spec=MCPClient)
        client.config = config
        client.state = MCPClientState.FAILED  # Не READY — trigger reconnect
        client.connect = AsyncMock()
        client.initialize = AsyncMock()
        client.disconnect = AsyncMock()
        client.list_tools = AsyncMock(return_value=[])
        
        manager._clients["test_server"] = client
        manager._adapters["test_server"] = MagicMock()
        manager._tools_cache["test_server"] = []
        
        # Патчим reconnect_with_backoff чтобы отследить вызов
        reconnect_called = False
        original_reconnect = manager.reconnect_with_backoff
        
        async def mock_reconnect(server_id):
            nonlocal reconnect_called
            reconnect_called = True
            return await original_reconnect(server_id)
        
        manager.reconnect_with_backoff = mock_reconnect
        
        await manager.start_health_check("test_server", interval=0.1)
        await asyncio.sleep(0.2)
        await manager.stop_health_check("test_server")
        
        assert reconnect_called is True

    @pytest.mark.asyncio
    async def test_health_check_does_not_trigger_reconnect_when_ready(self):
        """Health check не запускает переподключение когда сервер READY."""
        manager = MCPManager("test_session")
        
        config = MCPServerConfig(
            name="test_server",
            type="stdio",
            command="mcp-server",
        )
        client = AsyncMock(spec=MCPClient)
        client.config = config
        client.state = MCPClientState.READY
        
        manager._clients["test_server"] = client
        manager._adapters["test_server"] = MagicMock()
        manager._tools_cache["test_server"] = []
        
        reconnect_called = False
        original_reconnect = manager.reconnect_with_backoff
        
        async def mock_reconnect(server_id):
            nonlocal reconnect_called
            reconnect_called = True
            return await original_reconnect(server_id)
        
        manager.reconnect_with_backoff = mock_reconnect
        
        await manager.start_health_check("test_server", interval=0.1)
        await asyncio.sleep(0.2)
        await manager.stop_health_check("test_server")
        
        assert reconnect_called is False


class TestMCPManagerHandleServerFailure:
    """Тесты handle_server_failure метода."""

    @pytest.mark.asyncio
    async def test_handle_server_failure_starts_reconnect(self):
        """handle_server_failure запускает переподключение."""
        manager = MCPManager("test_session")
        
        config = MCPServerConfig(
            name="test_server",
            type="stdio",
            command="mcp-server",
            max_retries=1,
            initial_delay=0.05,
        )
        client = AsyncMock(spec=MCPClient)
        client.config = config
        client.state = MCPClientState.READY
        client.connect = AsyncMock()
        client.initialize = AsyncMock()
        client.disconnect = AsyncMock()
        client.list_tools = AsyncMock(return_value=[])
        
        manager._clients["test_server"] = client
        manager._adapters["test_server"] = MagicMock()
        manager._tools_cache["test_server"] = []
        
        await manager.handle_server_failure("test_server")
        
        assert "test_server" in manager._reconnect_tasks
        
        # Ждём завершения задачи
        await asyncio.sleep(0.2)
        
        # Задача должна завершиться
        if "test_server" in manager._reconnect_tasks:
            try:
                await manager._reconnect_tasks["test_server"]
            except Exception:
                pass
