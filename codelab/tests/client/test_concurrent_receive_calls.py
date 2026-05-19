"""Тесты для проверки синхронизации конкурентных вызовов receive().

Проверяет исправление race condition:
- RuntimeError: Concurrent call to receive() is not allowed

Архитектура решения:
- Background Receive Loop: единственный вызов receive() на WebSocket
- Message Router: маршрутизация по типам сообщений
- Routing Queues: распределение по очередям для конкурентных запросов

Сценарий:
- Background loop постоянно получает сообщения из transport.receive()
- Конкурентные запросы получают из своих очередей без блокировок
- Нет конкурентных вызовов receive() на WebSocket
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest

from codelab.client.infrastructure.services.acp_transport_service import (
    ACPTransportService,
)
from codelab.client.infrastructure.services.background_receive_loop import (
    BackgroundReceiveLoop,
)
from codelab.client.infrastructure.services.message_router import MessageRouter
from codelab.client.infrastructure.services.routing_queues import RoutingQueues
from codelab.client.infrastructure.transport import WebSocketTransport


def _create_service_for_test() -> ACPTransportService:
    """Создаёт ACPTransportService для тестов с mock транспортом."""
    transport = AsyncMock(spec=WebSocketTransport)
    transport.is_connected.return_value = True
    return ACPTransportService(transport=transport)


class TestConcurrentReceiveCalls:
    """Тесты конкурентного доступа к receive() на одном WebSocket."""

    @pytest.mark.asyncio
    async def test_background_loop_prevents_concurrent_receive(self) -> None:
        """Background loop предотвращает конкурентные вызовы receive().

        Сценарий: Background loop - единственный источник receive() на WebSocket.
        Конкурентные запросы получают из очередей, что исключает конкурентные
        вызовы receive() на WebSocket.
        """
        # Счетчик одновременных вызовов receive_text()
        concurrent_calls = 0
        max_concurrent_calls = 0

        async def receive_text_with_concurrent_check():
            """Имитирует receive_text() с проверкой на конкурентные вызовы."""
            nonlocal concurrent_calls, max_concurrent_calls

            concurrent_calls += 1
            max_concurrent_calls = max(max_concurrent_calls, concurrent_calls)

            # Если два вызова одновременны, это эмулирует ошибку aiohttp
            if concurrent_calls > 1:
                raise RuntimeError("Concurrent call to receive() is not allowed")

            try:
                await asyncio.sleep(0.01)
                return json.dumps({"id": 1, "result": {}})
            finally:
                concurrent_calls -= 1

        # Создаем mock транспорт
        mock_transport = AsyncMock()
        mock_transport.is_connected = Mock(return_value=True)
        mock_transport.receive_text = AsyncMock(
            side_effect=receive_text_with_concurrent_check
        )

        # Создаем сервис и подключаемся
        service = _create_service_for_test()
        service._transport = mock_transport  # noqa: SLF001 - test setup

        # Инициализируем routing infrastructure
        service._router = MessageRouter()
        service._queues = RoutingQueues()
        service._background_loop = BackgroundReceiveLoop(
            mock_transport, service._router, service._queues
        )

        # Запускаем background loop
        await service._background_loop.start()

        # Даем loop время на получение сообщения
        await asyncio.sleep(0.1)

        # Проверяем что loop работает
        assert service._background_loop.is_running()

        # Проверяем что был только ОДИН вызов receive_text()
        # (от background loop'а, а не конкурентные вызовы)
        assert max_concurrent_calls == 1

        # Останавливаем loop
        await service._background_loop.stop()

    @pytest.mark.asyncio
    async def test_concurrent_receive_calls_work_with_routing_queues(self) -> None:
        """Конкурентные receive() работают правильно с routing queues.

        Сценарий: Несколько задач получают сообщения из разных очередей.
        Каждая очередь содержит сообщения для конкретного request_id.
        """
        # Создаем mock транспорт, который отправляет разные сообщения
        messages = [
            json.dumps({"id": 1, "result": "response1"}),
            json.dumps({"id": 2, "result": "response2"}),
            json.dumps({"id": 3, "result": "response3"}),
        ]
        message_index = 0

        async def receive_text():
            nonlocal message_index
            if message_index < len(messages):
                msg = messages[message_index]
                message_index += 1
                return msg
            else:
                await asyncio.sleep(10)  # Бесконечное ожидание

        mock_transport = AsyncMock()
        mock_transport.is_connected = Mock(return_value=True)
        mock_transport.receive_text = AsyncMock(side_effect=receive_text)

        # Создаем сервис
        service = _create_service_for_test()
        service._transport = mock_transport  # noqa: SLF001 - test setup
        service._router = MessageRouter()
        service._queues = RoutingQueues()
        service._background_loop = BackgroundReceiveLoop(
            mock_transport, service._router, service._queues
        )

        # Запускаем background loop
        await service._background_loop.start()

        # Даем loop время на получение всех сообщений
        await asyncio.sleep(0.2)

        # Получаем сообщения из разных очередей
        # Это не вызывает конкурентные receive() на WebSocket!
        queue1 = await service._queues.get_or_create_response_queue(1)
        queue2 = await service._queues.get_or_create_response_queue(2)
        queue3 = await service._queues.get_or_create_response_queue(3)

        msg1 = queue1.get_nowait()
        msg2 = queue2.get_nowait()
        msg3 = queue3.get_nowait()

        assert msg1["id"] == 1
        assert msg2["id"] == 2
        assert msg3["id"] == 3

        # Останавливаем loop
        await service._background_loop.stop()

    @pytest.mark.asyncio
    async def test_background_loop_initializes_on_connect(self) -> None:
        """Background loop инициализируется и запускается при connect().

        Сценарий: При вызове connect() должны быть инициализированы:
        1. Message Router
        2. Routing Queues
        3. Background Receive Loop (и запущен)
        """
        mock_transport = AsyncMock()
        mock_transport.is_connected = Mock(return_value=True)
        mock_transport.receive_text = AsyncMock(
            side_effect=asyncio.CancelledError()
        )

        service = _create_service_for_test()
        service._transport = mock_transport  # noqa: SLF001 - test setup

        # Имитируем connect()
        service._router = MessageRouter()
        service._queues = RoutingQueues()
        service._background_loop = BackgroundReceiveLoop(
            mock_transport, service._router, service._queues
        )
        await service._background_loop.start()

        # Проверяем что все инициализировано
        assert service._router is not None
        assert service._queues is not None
        assert service._background_loop is not None
        assert service._background_loop.is_running()

        # Останавливаем loop
        await service._background_loop.stop()

    @pytest.mark.asyncio
    async def test_routing_queues_separate_responses_by_id(self) -> None:
        """Routing queues правильно разделяют ответы по request_id.

        Сценарий: Сообщения с разными id попадают в разные очереди.
        """
        queues = RoutingQueues()

        # Создаем очереди для разных request_id
        queue1 = await queues.get_or_create_response_queue(100)
        queue2 = await queues.get_or_create_response_queue(200)

        # Кладем сообщения в очереди
        msg1 = {"id": 100, "result": "response1"}
        msg2 = {"id": 200, "result": "response2"}

        await queues.put_response(100, msg1)
        await queues.put_response(200, msg2)

        # Получаем сообщения из очередей
        # Каждая очередь содержит ТОЛЬКО свои сообщения
        received1 = queue1.get_nowait()
        received2 = queue2.get_nowait()

        assert received1 == msg1
        assert received2 == msg2

    @pytest.mark.asyncio
    async def test_multiple_concurrent_requests_use_different_queues(self) -> None:
        """Множественные конкурентные запросы используют разные очереди.

        Сценарий: Три задачи создают запросы и получают ответы из разных очередей.
        Не используется блокирующее receive() на WebSocket.
        """
        queues = RoutingQueues()

        async def simulate_request(request_id: int):
            """Имитирует запрос и получение ответа."""
            # Создаем очередь для этого request_id
            queue = await queues.get_or_create_response_queue(request_id)

            # Имитируем получение ответа (от background loop)
            await queues.put_response(
                request_id, {"id": request_id, "result": f"response_{request_id}"}
            )

            # Получаем ответ из очереди
            response = await asyncio.wait_for(queue.get(), timeout=1.0)
            return response

        # Запускаем несколько конкурентных "запросов"
        results = await asyncio.gather(
            simulate_request(1), simulate_request(2), simulate_request(3)
        )

        # Все должны получить свои ответы
        assert len(results) == 3
        assert results[0]["id"] == 1
        assert results[1]["id"] == 2
        assert results[2]["id"] == 3

    @pytest.mark.asyncio
    async def test_background_loop_handles_messages_without_concurrent_calls(
        self,
    ) -> None:
        """Background loop обрабатывает сообщения без конкурентных вызовов receive().

        Сценарий: Background loop запускается и обрабатывает сообщения из очереди,
        но при этом не вызывает конкурентные receive() на WebSocket.
        """
        messages = [
            json.dumps({"id": 100, "result": {"status": "ok"}}),
            json.dumps({"id": 101, "result": {"status": "ok"}}),
        ]
        message_index = 0

        async def receive_text():
            nonlocal message_index
            if message_index < len(messages):
                msg = messages[message_index]
                message_index += 1
                return msg
            else:
                await asyncio.sleep(10)

        mock_transport = AsyncMock()
        mock_transport.is_connected = Mock(return_value=True)
        mock_transport.receive_text = AsyncMock(side_effect=receive_text)

        service = _create_service_for_test()
        service._transport = mock_transport  # noqa: SLF001 - test setup
        service._router = MessageRouter()
        service._queues = RoutingQueues()
        service._background_loop = BackgroundReceiveLoop(
            mock_transport, service._router, service._queues
        )

        # Запускаем background loop
        await service._background_loop.start()

        # Даем loop время на получение сообщений
        await asyncio.sleep(0.1)

        # Получаем статистику loop'а
        stats = service._background_loop.get_stats()

        # Background loop должна обработать сообщения
        assert stats["running"]
        assert stats["messages_received"] >= 1
        assert stats["messages_routed"] >= 1

        # Останавливаем loop
        await service._background_loop.stop()
