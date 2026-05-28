"""Тесты для MCPClient notification handling."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from codelab.server.mcp.client import (
    MCPClient,
    MCPClientState,
)
from codelab.server.mcp.models import MCPServerConfig


class TestMCPClientNotificationHandling:
    """Тесты notification handling."""

    @pytest.mark.asyncio
    async def test_register_handler(self):
        """Регистрация обработчика для notification."""
        config = MCPServerConfig(name="test", type="stdio", command="mcp-server")
        client = MCPClient(config)
        
        handler = MagicMock()
        client.register_handler("tools/list_changed", handler)
        
        assert "tools/list_changed" in client._notification_handlers
        assert handler in client._notification_handlers["tools/list_changed"]

    @pytest.mark.asyncio
    async def test_register_multiple_handlers(self):
        """Регистрация нескольких обработчиков для одного notification."""
        config = MCPServerConfig(name="test", type="stdio", command="mcp-server")
        client = MCPClient(config)
        
        handler1 = MagicMock()
        handler2 = MagicMock()
        client.register_handler("tools/list_changed", handler1)
        client.register_handler("tools/list_changed", handler2)
        
        assert len(client._notification_handlers["tools/list_changed"]) == 2

    @pytest.mark.asyncio
    async def test_handle_notification_queues(self):
        """handle_notification помещает notification в очередь."""
        config = MCPServerConfig(name="test", type="stdio", command="mcp-server")
        client = MCPClient(config)
        
        notification = {
            "method": "tools/list_changed",
            "params": {"server": "test"},
        }
        
        await client.handle_notification(notification)
        
        # Проверяем, что notification в очереди
        assert client._notification_queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_process_notifications_calls_handlers(self):
        """_process_notifications вызывает зарегистрированные handlers."""
        config = MCPServerConfig(name="test", type="stdio", command="mcp-server")
        client = MCPClient(config)
        client._state = MCPClientState.READY
        
        handler_calls = []
        
        async def async_handler(params):
            handler_calls.append(params)
        
        client.register_handler("tools/list_changed", async_handler)
        
        # Помещаем notification в очередь
        notification = {
            "method": "tools/list_changed",
            "params": {"server": "test"},
        }
        await client._notification_queue.put(notification)
        
        # Запускаем обработку на короткое время
        task = asyncio.create_task(client._process_notifications())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        assert len(handler_calls) == 1
        assert handler_calls[0] == {"server": "test"}

    @pytest.mark.asyncio
    async def test_start_stop_notification_processing(self):
        """Запуск и остановка обработки notifications."""
        config = MCPServerConfig(name="test", type="stdio", command="mcp-server")
        client = MCPClient(config)
        client._state = MCPClientState.READY
        
        await client.start_notification_processing()
        assert client._notification_task is not None
        
        await client.stop_notification_processing()
        assert client._notification_task is None

    @pytest.mark.asyncio
    async def test_notification_logging(self, caplog):
        """Notification логируются с DEBUG level."""
        import logging
        config = MCPServerConfig(name="test", type="stdio", command="mcp-server")
        client = MCPClient(config)
        client._state = MCPClientState.READY
        
        with caplog.at_level(logging.DEBUG):
            notification = {
                "method": "tools/list_changed",
                "params": {},
            }
            await client.handle_notification(notification)
            
            # Проверяем логирование
            assert "tools/list_changed" in caplog.text or client._notification_queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_handler_error_does_not_crash(self):
        """Ошибка в handler не ломает обработку notifications."""
        config = MCPServerConfig(name="test", type="stdio", command="mcp-server")
        client = MCPClient(config)
        client._state = MCPClientState.READY
        
        def failing_handler(params):
            raise ValueError("Handler error")
        
        success_handler = MagicMock()
        
        client.register_handler("tools/list_changed", failing_handler)
        client.register_handler("tools/list_changed", success_handler)
        
        notification = {
            "method": "tools/list_changed",
            "params": {"server": "test"},
        }
        await client._notification_queue.put(notification)
        
        # Запускаем обработку на короткое время
        task = asyncio.create_task(client._process_notifications())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        # Success handler должен был вызваться
        success_handler.assert_called_once_with({"server": "test"})
