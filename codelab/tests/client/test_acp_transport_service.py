"""Тесты для ACPTransportService request_with_callbacks."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from codelab.client.infrastructure.services.acp_transport_service import ACPTransportService
from codelab.client.infrastructure.services.routing_queues import RoutingQueues
from codelab.client.infrastructure.transport import WebSocketTransport


class TestACPTransportServiceRequestWithCallbacks:
    """Тесты обработки server->client RPC внутри request_with_callbacks."""

    @pytest.mark.asyncio
    async def test_permission_request_routing_via_handler(self) -> None:
        """Permission requests маршрутизируются через PermissionHandler."""
        # Этот тест проверяет что параметр on_permission был удален
        # и permission requests обрабатываются только через PermissionHandler
        service = ACPTransportService(host="127.0.0.1", port=8765)
        
        # Проверяем что request_with_callbacks не принимает on_permission параметр
        # Если попытаться передать on_permission, будет TypeError
        try:
            # Это должно вызвать TypeError так как параметра на_permission больше нет
            await service.request_with_callbacks(
                method="test",
                on_permission=lambda x: None,  # type: ignore[call-arg]
            )
            pytest.fail("Expected TypeError for on_permission parameter")
        except TypeError as e:
            # Ожидаемая ошибка - параметр удален
            assert "on_permission" in str(e) or "unexpected keyword argument" in str(e)

    @pytest.mark.asyncio
    async def test_fs_read_request_with_id_is_handled(self) -> None:
        """Клиент отвечает на fs/read_text_file и завершает исходный запрос."""
        service = ACPTransportService(host="127.0.0.1", port=8765)
        queues = RoutingQueues()
        service._queues = queues  # noqa: SLF001 - test setup

        transport = AsyncMock(spec=WebSocketTransport)
        transport.is_connected.return_value = True
        sent_messages: list[dict[str, object]] = []

        async def send_str_side_effect(raw_payload: str) -> None:
            payload = json.loads(raw_payload)
            sent_messages.append(payload)

            if payload.get("method") != "session/prompt":
                return

            if not isinstance(payload.get("id"), str | int):
                return
            request_id: str | int = payload["id"]

            async def produce_server_messages() -> None:
                await queues.notification_queue.put(
                    {
                        "jsonrpc": "2.0",
                        "id": "rpc-1",
                        "method": "fs/read_text_file",
                        "params": {"sessionId": "sess-1", "path": "/tmp/demo.txt"},
                    }
                )
                response_queue = await queues.get_or_create_response_queue(request_id)
                await response_queue.put(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"status": "ok"},
                    }
                )

            asyncio.create_task(produce_server_messages())

        transport.send_str = AsyncMock(side_effect=send_str_side_effect)
        service._transport = transport  # noqa: SLF001 - test setup

        response = await service.request_with_callbacks(
            method="session/prompt",
            params={"sessionId": "sess-1", "prompt": [{"type": "text", "text": "read"}]},
            on_fs_read=lambda path: f"content from {path}",
        )

        assert response["result"]["status"] == "ok"

        fs_reply = next(
            message
            for message in sent_messages
            if message.get("id") == "rpc-1" and "result" in message
        )
        assert fs_reply["result"] == {"content": "content from /tmp/demo.txt"}

    @pytest.mark.asyncio
    async def test_unknown_server_rpc_with_id_gets_fallback_response(self) -> None:
        """На неизвестный server->client RPC отправляется пустой response."""
        service = ACPTransportService(host="127.0.0.1", port=8765)
        queues = RoutingQueues()
        service._queues = queues  # noqa: SLF001 - test setup

        transport = AsyncMock(spec=WebSocketTransport)
        transport.is_connected.return_value = True
        sent_messages: list[dict[str, object]] = []

        async def send_str_side_effect(raw_payload: str) -> None:
            payload = json.loads(raw_payload)
            sent_messages.append(payload)

            if payload.get("method") != "session/prompt":
                return

            if not isinstance(payload.get("id"), str | int):
                return
            request_id: str | int = payload["id"]

            async def produce_server_messages() -> None:
                await queues.notification_queue.put(
                    {
                        "jsonrpc": "2.0",
                        "id": "rpc-unknown-1",
                        "method": "custom/unknown_rpc",
                        "params": {"sessionId": "sess-1"},
                    }
                )
                response_queue = await queues.get_or_create_response_queue(request_id)
                await response_queue.put(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"status": "ok"},
                    }
                )

            asyncio.create_task(produce_server_messages())

        transport.send_str = AsyncMock(side_effect=send_str_side_effect)
        service._transport = transport  # noqa: SLF001 - test setup

        response = await service.request_with_callbacks(
            method="session/prompt",
            params={"sessionId": "sess-1", "prompt": [{"type": "text", "text": "hi"}]},
        )

        assert response["result"]["status"] == "ok"

        fallback_reply = next(
            message
            for message in sent_messages
            if message.get("id") == "rpc-unknown-1" and "result" in message
        )
        assert fallback_reply["result"] == {}

    @pytest.mark.asyncio
    async def test_handle_client_rpc_logs_tool_lifecycle_trace(self) -> None:
        """Логируется полный trace lifecycle для fs/read_text_file."""
        service = ACPTransportService(host="127.0.0.1", port=8765)
        service._logger = MagicMock()  # noqa: SLF001 - test setup
        transport = AsyncMock(spec=WebSocketTransport)
        transport.is_connected.return_value = True
        service._transport = transport  # noqa: SLF001 - test setup

        await service._handle_notification_or_client_rpc(  # noqa: SLF001 - test target
            method="session/prompt",
            request_id="req-1",
            notification_data={
                "jsonrpc": "2.0",
                "id": "rpc-1",
                "method": "fs/read_text_file",
                "params": {"path": "/tmp/demo.txt"},
            },
            on_update=None,
            on_fs_read=lambda _: "demo-content",
            on_fs_write=None,
            on_terminal_create=None,
            on_terminal_output=None,
            on_terminal_wait=None,
            on_terminal_release=None,
            on_terminal_kill=None,
        )

        transport.send_str.assert_awaited_once()
        # Debug events: rpc_received остается debug, остальные перешли в info
        debug_events = [call.args[0] for call in service._logger.debug.call_args_list if call.args]
        assert "tool_lifecycle_rpc_received" in debug_events
        # Info events: логи fs_read_rpc_* теперь info уровня для лучшей диагностики
        info_events = [call.args[0] for call in service._logger.info.call_args_list if call.args]
        assert "fs_read_rpc_start" in info_events
        assert "fs_read_rpc_callback_done" in info_events
        assert "fs_read_rpc_sending_response" in info_events
        assert "fs_read_rpc_response_sent" in info_events

    @pytest.mark.asyncio
    async def test_request_with_callbacks_logs_notification_failure(self) -> None:
        """Ошибка client-rpc callback логируется, а запрос завершается ответом."""
        service = ACPTransportService(host="127.0.0.1", port=8765)
        service._logger = MagicMock()  # noqa: SLF001 - test setup
        queues = RoutingQueues()
        service._queues = queues  # noqa: SLF001 - test setup

        transport = AsyncMock(spec=WebSocketTransport)
        transport.is_connected.return_value = True

        async def send_str_side_effect(raw_payload: str) -> None:
            payload = json.loads(raw_payload)

            if payload.get("method") != "session/prompt":
                return

            if not isinstance(payload.get("id"), str | int):
                return
            request_id: str | int = payload["id"]

            async def produce_server_messages() -> None:
                await queues.notification_queue.put(
                    {
                        "jsonrpc": "2.0",
                        "id": "rpc-1",
                        "method": "fs/read_text_file",
                        "params": {"sessionId": "sess-1", "path": "/tmp/demo.txt"},
                    }
                )
                response_queue = await queues.get_or_create_response_queue(request_id)
                await response_queue.put(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"status": "ok"},
                    }
                )

            asyncio.create_task(produce_server_messages())

        transport.send_str = AsyncMock(side_effect=send_str_side_effect)
        service._transport = transport  # noqa: SLF001 - test setup

        response = await service.request_with_callbacks(
            method="session/prompt",
            params={"sessionId": "sess-1", "prompt": [{"type": "text", "text": "read"}]},
            on_fs_read=lambda _: (_ for _ in ()).throw(ValueError("boom")),
        )

        assert response["result"]["status"] == "ok"
        # Ошибки в fs/read callback теперь логируются как error с именем fs_read_rpc_error
        error_events = [
            call.args[0] for call in service._logger.error.call_args_list if call.args
        ]
        assert "fs_read_rpc_error" in error_events


class TestFsWriteTextFile:
    """Тесты для обработки fs/write_text_file RPC."""

    @pytest.mark.asyncio
    async def test_fs_write_request_returns_success_true(self) -> None:
        """Клиент возвращает {success: true} при успешной записи."""
        service = ACPTransportService(host="127.0.0.1", port=8765)
        service._logger = MagicMock()  # noqa: SLF001 - test setup
        transport = AsyncMock(spec=WebSocketTransport)
        transport.is_connected.return_value = True
        service._transport = transport  # noqa: SLF001 - test setup

        written_files: list[tuple[str, str]] = []

        def mock_write(path: str, content: str) -> bool:
            written_files.append((path, content))
            return True

        await service._handle_notification_or_client_rpc(  # noqa: SLF001 - test target
            method="session/prompt",
            request_id="req-1",
            notification_data={
                "jsonrpc": "2.0",
                "id": "rpc-write-1",
                "method": "fs/write_text_file",
                "params": {"path": "/tmp/test.md", "content": "# Hello"},
            },
            on_update=None,
            on_fs_read=None,
            on_fs_write=mock_write,
            on_terminal_create=None,
            on_terminal_output=None,
            on_terminal_wait=None,
            on_terminal_release=None,
            on_terminal_kill=None,
        )

        transport.send_str.assert_awaited_once()
        sent_payload = json.loads(transport.send_str.call_args[0][0])
        assert sent_payload["id"] == "rpc-write-1"
        assert sent_payload["result"] == {"success": True}
        assert written_files == [("/tmp/test.md", "# Hello")]

    @pytest.mark.asyncio
    async def test_fs_write_request_returns_success_false_on_callback_failure(self) -> None:
        """Клиент возвращает {success: false} если callback вернул False."""
        service = ACPTransportService(host="127.0.0.1", port=8765)
        service._logger = MagicMock()  # noqa: SLF001 - test setup
        transport = AsyncMock(spec=WebSocketTransport)
        transport.is_connected.return_value = True
        service._transport = transport  # noqa: SLF001 - test setup

        def mock_write_failing(path: str, content: str) -> bool:
            return False

        await service._handle_notification_or_client_rpc(  # noqa: SLF001 - test target
            method="session/prompt",
            request_id="req-1",
            notification_data={
                "jsonrpc": "2.0",
                "id": "rpc-write-2",
                "method": "fs/write_text_file",
                "params": {"path": "/tmp/test.md", "content": "# Fail"},
            },
            on_update=None,
            on_fs_read=None,
            on_fs_write=mock_write_failing,
            on_terminal_create=None,
            on_terminal_output=None,
            on_terminal_wait=None,
            on_terminal_release=None,
            on_terminal_kill=None,
        )

        transport.send_str.assert_awaited_once()
        sent_payload = json.loads(transport.send_str.call_args[0][0])
        assert sent_payload["id"] == "rpc-write-2"
        assert sent_payload["result"] == {"success": False}

    @pytest.mark.asyncio
    async def test_fs_write_request_error_sends_error_response(self) -> None:
        """При исключении в callback клиент отправляет error response."""
        service = ACPTransportService(host="127.0.0.1", port=8765)
        service._logger = MagicMock()  # noqa: SLF001 - test setup
        transport = AsyncMock(spec=WebSocketTransport)
        transport.is_connected.return_value = True
        service._transport = transport  # noqa: SLF001 - test setup

        def mock_write_error(path: str, content: str) -> bool:
            raise OSError("Disk full")

        await service._handle_notification_or_client_rpc(  # noqa: SLF001 - test target
            method="session/prompt",
            request_id="req-1",
            notification_data={
                "jsonrpc": "2.0",
                "id": "rpc-write-3",
                "method": "fs/write_text_file",
                "params": {"path": "/tmp/test.md", "content": "# Error"},
            },
            on_update=None,
            on_fs_read=None,
            on_fs_write=mock_write_error,
            on_terminal_create=None,
            on_terminal_output=None,
            on_terminal_wait=None,
            on_terminal_release=None,
            on_terminal_kill=None,
        )

        transport.send_str.assert_awaited_once()
        sent_payload = json.loads(transport.send_str.call_args[0][0])
        assert sent_payload["id"] == "rpc-write-3"
        assert "error" in sent_payload
        assert sent_payload["error"]["code"] == -32603
        assert "Disk full" in sent_payload["error"]["message"]


class TestPermissionCallback:
    """Тесты для установки и использования permission callback."""

    def test_set_permission_callback_stores_callback(self) -> None:
        """Метод set_permission_callback должен сохранять callback."""
        service = ACPTransportService(host="127.0.0.1", port=8765)

        # Создаем mock callback
        callback = MagicMock()

        # Устанавливаем callback
        service.set_permission_callback(callback)

        # Проверяем, что callback сохранен
        assert service._permission_callback is callback  # noqa: SLF001

    def test_set_permission_callback_logs_info_message(self) -> None:
        """Установка callback должна логировать INFO сообщение."""
        service = ACPTransportService(host="127.0.0.1", port=8765)
        service._logger = MagicMock()  # noqa: SLF001

        # Создаем mock callback с именем
        def my_permission_callback(
            request_id: str | int, tool_call: object, options: list[object]
        ) -> None:
            pass

        # Устанавливаем callback
        service.set_permission_callback(my_permission_callback)

        # Проверяем логирование
        service._logger.info.assert_called_once()  # noqa: SLF001
        call_args = service._logger.info.call_args  # noqa: SLF001
        assert "permission_callback_set" in call_args[0]
        assert call_args[1]["callback_name"] == "my_permission_callback"

    @pytest.mark.asyncio
    async def test_handle_permission_request_with_callback_is_passed_to_handler(
        self,
    ) -> None:
        """Установленный callback должен быть передан в handler.handle_request."""
        # Создаем mock для PermissionHandler
        permission_handler = AsyncMock()
        service = ACPTransportService(
            host="127.0.0.1",
            port=8765,
            permission_handler=permission_handler,
        )

        # Устанавливаем mock callback
        callback = MagicMock()
        service.set_permission_callback(callback)

        # Подготавливаем mock для handle_request
        from codelab.client.application.permission_handler import CancelledPermissionOutcome

        permission_handler.handle_request.return_value = CancelledPermissionOutcome(
            outcome="cancelled"
        )

        # Мокируем send, чтобы избежать реальной отправки
        service.send = AsyncMock()

        # Вызываем _handle_permission_request_with_handler с корректной структурой
        await service._handle_permission_request_with_handler(
            {
                "jsonrpc": "2.0",
                "id": "perm-1",
                "method": "session/request_permission",
                "params": {
                    "sessionId": "sess-1",
                    "toolCall": {
                        "toolCallId": "tc-1",
                        "kind": "read",
                        "title": "Read file",
                    },
                    "options": [
                        {
                            "optionId": "allow_once",
                            "kind": "allow_once",
                            "name": "Allow once",
                        }
                    ],
                },
            }
        )

        # Проверяем, что handle_request был вызван с нашим callback
        permission_handler.handle_request.assert_called_once()
        call_kwargs = permission_handler.handle_request.call_args[1]
        assert call_kwargs["callback"] is callback

    @pytest.mark.asyncio
    async def test_handle_permission_request_without_callback_passes_none(
        self,
    ) -> None:
        """Если callback не установлен, handler должен получить None."""
        # Создаем mock для PermissionHandler
        permission_handler = AsyncMock()
        service = ACPTransportService(
            host="127.0.0.1",
            port=8765,
            permission_handler=permission_handler,
        )

        # НЕ устанавливаем callback - оставляем None

        # Подготавливаем mock для handle_request
        from codelab.client.application.permission_handler import CancelledPermissionOutcome

        permission_handler.handle_request.return_value = CancelledPermissionOutcome(
            outcome="cancelled"
        )

        # Мокируем send, чтобы избежать реальной отправки
        service.send = AsyncMock()

        # Вызываем _handle_permission_request_with_handler с корректной структурой
        await service._handle_permission_request_with_handler(
            {
                "jsonrpc": "2.0",
                "id": "perm-1",
                "method": "session/request_permission",
                "params": {
                    "sessionId": "sess-1",
                    "toolCall": {
                        "toolCallId": "tc-1",
                        "kind": "read",
                        "title": "Read file",
                    },
                    "options": [
                        {
                            "optionId": "allow_once",
                            "kind": "allow_once",
                            "name": "Allow once",
                        }
                    ],
                },
            }
        )

        # Проверяем, что handle_request был вызван с None callback
        permission_handler.handle_request.assert_called_once()
        call_kwargs = permission_handler.handle_request.call_args[1]
        assert call_kwargs["callback"] is None
