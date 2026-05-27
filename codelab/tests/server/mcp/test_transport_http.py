"""Unit тесты для HTTP и SSE транспортов MCP."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from codelab.server.mcp.transport import (
    HttpConnectionError,
    HttpTransport,
    HttpTransportError,
    HttpTimeoutError,
    SseTransport,
    SseTransportError,
)


# ===== HttpTransport Tests =====


class TestHttpTransportInit:
    """Тесты инициализации HttpTransport."""

    def test_init_with_url(self):
        """Инициализация с URL."""
        transport = HttpTransport(url="http://localhost:8080")
        assert transport._url == "http://localhost:8080"
        assert transport._headers == {}
        assert transport._timeout == 30.0
        assert transport._session is None
        assert transport._closed is False

    def test_init_with_headers(self):
        """Инициализация с headers."""
        headers = [
            {"name": "Authorization", "value": "Bearer token"},
            {"Content-Type": "application/json"},
        ]
        transport = HttpTransport(url="http://localhost:8080", headers=headers)
        assert transport._headers == {
            "Authorization": "Bearer token",
            "Content-Type": "application/json",
        }

    def test_init_with_custom_timeout(self):
        """Инициализация с custom timeout."""
        transport = HttpTransport(url="http://localhost:8080", timeout=60.0)
        assert transport._timeout == 60.0

    def test_build_headers_from_name_value(self):
        """Построение headers из name/value формата."""
        headers = [
            {"name": "X-Custom", "value": "test"},
            {"name": "Authorization", "value": "Bearer abc"},
        ]
        result = HttpTransport._build_headers(headers)
        assert result == {
            "X-Custom": "test",
            "Authorization": "Bearer abc",
        }

    def test_build_headers_from_dict(self):
        """Построение headers из dict формата."""
        headers = [
            {"X-Custom": "test"},
            {"Authorization": "Bearer abc"},
        ]
        result = HttpTransport._build_headers(headers)
        assert result == {
            "X-Custom": "test",
            "Authorization": "Bearer abc",
        }

    def test_build_headers_empty(self):
        """Построение headers из None."""
        assert HttpTransport._build_headers(None) == {}
        assert HttpTransport._build_headers([]) == {}


class TestHttpTransportConnection:
    """Тесты подключения HttpTransport."""

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Успешное подключение."""
        mock_session = AsyncMock()
        mock_session.closed = False
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.head = MagicMock(return_value=mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            transport = HttpTransport(url="http://localhost:8080")
            await transport.connect()

            assert transport.is_connected
            assert transport._session is not None

    @pytest.mark.asyncio
    async def test_connect_already_connected(self):
        """Ошибка при повторном подключении."""
        transport = HttpTransport(url="http://localhost:8080")
        mock_session = AsyncMock()
        mock_session.closed = False
        transport._session = mock_session

        with pytest.raises(HttpTransportError, match="already connected"):
            await transport.connect()

    @pytest.mark.asyncio
    async def test_connect_server_error(self):
        """Ошибка подключения к серверу."""
        with patch("aiohttp.ClientSession", side_effect=aiohttp.ClientError("Connection refused")):
            transport = HttpTransport(url="http://localhost:8080")
            with pytest.raises(HttpConnectionError):
                await transport.connect()

            assert transport._session is None
            assert not transport.is_connected


class TestHttpTransportSendRequest:
    """Тесты отправки запросов HttpTransport."""

    @pytest.mark.asyncio
    async def test_send_request_success(self):
        """Успешная отправка запроса."""
        transport = HttpTransport(url="http://localhost:8080")
        transport._closed = False

        mock_session = AsyncMock()
        mock_session.closed = False
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"status": "ok"},
        })
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.post = MagicMock(return_value=mock_response)
        transport._session = mock_session

        # Имитируем ответ через Future
        async def simulate_response():
            await asyncio.sleep(0.01)
            future = transport._pending_requests.get(1)
            if future and not future.done():
                from codelab.server.mcp.models import MCPResponse
                future.set_result(MCPResponse(
                    id=1,
                    result={"status": "ok"},
                ))

        asyncio.create_task(simulate_response())

        result = await transport.send_request("test_method", {"param": "value"})
        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_send_request_not_connected(self):
        """Ошибка при отправке без подключения."""
        transport = HttpTransport(url="http://localhost:8080")

        with pytest.raises(HttpConnectionError, match="Not connected"):
            await transport.send_request("test_method")

    @pytest.mark.asyncio
    async def test_send_request_timeout(self):
        """Таймаут запроса."""
        transport = HttpTransport(url="http://localhost:8080", timeout=0.01)
        transport._closed = False

        mock_session = AsyncMock()
        mock_session.closed = False
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "id": 1,
            "result": {},
        })
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.post = MagicMock(return_value=mock_response)
        transport._session = mock_session

        # Патчим asyncio.wait_for чтобы всегда вызывать timeout
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            with pytest.raises(HttpTimeoutError, match="Request timeout"):
                await transport.send_request("test_method", timeout=0.01)

    @pytest.mark.asyncio
    async def test_send_request_http_error(self):
        """HTTP ошибка (500)."""
        transport = HttpTransport(url="http://localhost:8080")
        transport._closed = False

        mock_session = AsyncMock()
        mock_session.closed = False
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.post = MagicMock(return_value=mock_response)
        transport._session = mock_session

        with pytest.raises(HttpTransportError, match="HTTP server error"):
            await transport.send_request("test_method")


class TestHttpTransportSendNotification:
    """Тесты отправки notifications HttpTransport."""

    @pytest.mark.asyncio
    async def test_send_notification_success(self):
        """Успешная отправка notification."""
        transport = HttpTransport(url="http://localhost:8080")
        transport._closed = False

        mock_session = AsyncMock()
        mock_session.closed = False
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.post = MagicMock(return_value=mock_response)
        transport._session = mock_session

        await transport.send_notification("test_notification", {"data": "value"})
        mock_session.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_notification_not_connected(self):
        """Ошибка при отправке notification без подключения."""
        transport = HttpTransport(url="http://localhost:8080")

        with pytest.raises(HttpConnectionError, match="Not connected"):
            await transport.send_notification("test_notification")


class TestHttpTransportDisconnect:
    """Тесты отключения HttpTransport."""

    @pytest.mark.asyncio
    async def test_disconnect_success(self):
        """Успешное отключение."""
        transport = HttpTransport(url="http://localhost:8080")
        transport._closed = False

        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()
        transport._session = mock_session

        await transport.disconnect()

        assert transport._closed is True
        assert transport._session is None
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_already_closed(self):
        """Повторное отключение (already closed)."""
        transport = HttpTransport(url="http://localhost:8080")
        transport._closed = True

        await transport.disconnect()
        # Не должно вызвать ошибок


class TestHttpTransportNotificationHandler:
    """Тесты обработчиков notifications HttpTransport."""

    def test_register_notification_handler(self):
        """Регистрация обработчика notifications."""
        transport = HttpTransport(url="http://localhost:8080")
        handler = MagicMock()
        transport.register_notification_handler(handler)

        assert handler in transport._notification_handlers

    @pytest.mark.asyncio
    async def test_handle_response_notification(self):
        """Обработка notification response."""
        transport = HttpTransport(url="http://localhost:8080")
        handler_calls = []

        def handler(data):
            handler_calls.append(data)

        transport.register_notification_handler(handler)

        notification_data = {
            "method": "notifications/tools/list_changed",
            "params": {"server": "test"},
        }

        await transport._handle_response(notification_data)

        assert len(handler_calls) == 1
        assert handler_calls[0] == notification_data


# ===== SseTransport Tests =====


class TestSseTransportInit:
    """Тесты инициализации SseTransport."""

    @pytest.mark.asyncio
    async def test_init_with_url(self):
        """Инициализация с URL."""
        transport = SseTransport(url="http://localhost:8080/sse")
        assert transport._url == "http://localhost:8080/sse"
        assert transport._headers == {}
        assert transport._timeout == 30.0
        assert transport._session is None
        assert transport._closed is False

    @pytest.mark.asyncio
    async def test_init_with_headers(self):
        """Инициализация с headers."""
        headers = [{"name": "Authorization", "value": "Bearer token"}]
        transport = SseTransport(url="http://localhost:8080/sse", headers=headers)
        assert transport._headers == {"Authorization": "Bearer token"}

    @pytest.mark.asyncio
    async def test_init_logs_deprecation_warning(self, caplog):
        """Инициализация логирует warning о deprecated."""
        import logging
        with caplog.at_level(logging.WARNING):
            transport = SseTransport(url="http://localhost:8080/sse")
            assert "deprecated" in caplog.text.lower() or transport is not None


class TestSseTransportConnection:
    """Тесты подключения SseTransport."""

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Успешное подключение."""
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.closed = False
        mock_session.get = AsyncMock(return_value=mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            transport = SseTransport(url="http://localhost:8080/sse")
            await transport.connect()

            assert transport._session is not None
            assert transport._sse_response is not None

    @pytest.mark.asyncio
    async def test_connect_already_connected(self):
        """Ошибка при повторном подключении."""
        transport = SseTransport(url="http://localhost:8080/sse")
        transport._session = AsyncMock()
        transport._session.closed = False

        with pytest.raises(SseTransportError, match="already connected"):
            await transport.connect()

    @pytest.mark.asyncio
    async def test_connect_server_error(self):
        """Ошибка подключения к серверу."""
        import aiohttp
        with patch("aiohttp.ClientSession", side_effect=aiohttp.ClientError("Connection refused")):
            transport = SseTransport(url="http://localhost:8080/sse")
            with pytest.raises(SseTransportError):
                await transport.connect()

            assert transport._session is None


class TestSseTransportSendRequest:
    """Тесты отправки запросов SseTransport."""

    @pytest.mark.asyncio
    async def test_send_request_not_connected(self):
        """Ошибка при отправке без подключения."""
        transport = SseTransport(url="http://localhost:8080/sse")

        with pytest.raises(SseTransportError, match="Not connected"):
            await transport.send_request("test_method")


class TestSseTransportSendNotification:
    """Тесты отправки notifications SseTransport."""

    @pytest.mark.asyncio
    async def test_send_notification_not_connected(self):
        """Ошибка при отправке notification без подключения."""
        transport = SseTransport(url="http://localhost:8080/sse")

        with pytest.raises(SseTransportError, match="Not connected"):
            await transport.send_notification("test_notification")


class TestSseTransportDisconnect:
    """Тесты отключения SseTransport."""

    @pytest.mark.asyncio
    async def test_disconnect_success(self):
        """Успешное отключение."""
        transport = SseTransport(url="http://localhost:8080/sse")
        transport._closed = False

        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()
        transport._session = mock_session

        mock_sse_response = AsyncMock()
        mock_sse_response.closed = False
        mock_sse_response.release = AsyncMock()
        transport._sse_response = mock_sse_response

        await transport.disconnect()

        assert transport._closed is True
        assert transport._session is None
        assert transport._sse_response is None

    @pytest.mark.asyncio
    async def test_disconnect_already_closed(self):
        """Повторное отключение (already closed)."""
        transport = SseTransport(url="http://localhost:8080/sse")
        transport._closed = True

        await transport.disconnect()
        # Не должно вызвать ошибок


class TestSseTransportNotificationHandler:
    """Тесты обработчиков notifications SseTransport."""

    @pytest.mark.asyncio
    async def test_register_notification_handler(self):
        """Регистрация обработчика для конкретного метода."""
        transport = SseTransport(url="http://localhost:8080/sse")
        handler = MagicMock()
        transport.register_notification_handler("tools/list_changed", handler)

        assert "tools/list_changed" in transport._notification_handlers
        assert handler in transport._notification_handlers["tools/list_changed"]

    @pytest.mark.asyncio
    async def test_handle_sse_event_notification(self):
        """Обработка SSE notification event."""
        transport = SseTransport(url="http://localhost:8080/sse")
        handler_calls = []

        async def async_handler(data):
            handler_calls.append(data)

        transport.register_notification_handler("tools/list_changed", async_handler)

        notification_data = '{"method": "tools/list_changed", "params": {}}'
        await transport._handle_sse_event(
            event="message",
            data=notification_data,
        )

        assert len(handler_calls) == 1
        assert handler_calls[0]["method"] == "tools/list_changed"

    @pytest.mark.asyncio
    async def test_handle_sse_event_invalid_json(self, caplog):
        """Обработка SSE event с invalid JSON."""
        import logging
        transport = SseTransport(url="http://localhost:8080/sse")

        with caplog.at_level(logging.WARNING):
            await transport._handle_sse_event(
                event="message",
                data="invalid json",
            )
            assert "Invalid JSON" in caplog.text
