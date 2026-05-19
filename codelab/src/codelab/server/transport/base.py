"""Базовый протокол транспорта ACP-сервера.

Модуль определяет абстрактный интерфейс для всех реализаций транспорта
сервера. Транспорт отвечает за приём JSON-RPC сообщений от клиента,
передачу их в обработчик и отправку ответов обратно.

Пример использования:
    class MyTransport(AcpServerTransport):
        async def run(self, on_message):
            # цикл чтения сообщений
            ...

        async def send(self, message):
            # отправка сообщения клиенту
            ...

        async def close(self):
            # graceful shutdown
            ...
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from codelab.server.messages import ACPMessage
from codelab.server.protocol.state import ProtocolOutcome


@runtime_checkable
class AcpServerTransport(Protocol):
    """Протокол транспорта ACP-сервера.

    Любая реализация транспорта должна поддерживать три метода:
    - run(on_message): основной цикл чтения и обработки сообщений
    - send(message): отправка response/notification клиенту
    - close(): graceful shutdown транспорта

    Транспорт не знает о бизнес-логике — только о сообщениях.
    Callback on_message принимает ACPMessage и возвращает ProtocolOutcome
    (response + notifications + followups).

    Пример реализации:
        class WebSocketTransport(AcpServerTransport):
            async def run(self, on_message):
                async for message in self.ws:
                    acp_request = ACPMessage.from_json(message.data)
                    outcome = await on_message(acp_request)
                    await self._send_outcome(outcome)

            async def send(self, message):
                await self.ws.send_str(message.to_json())

            async def close(self):
                await self.ws.close()
    """

    async def run(
        self,
        on_message: Callable[[ACPMessage], Awaitable[ProtocolOutcome]],
    ) -> None:
        """Основной цикл транспорта.

        Читает входящие сообщения от клиента, передаёт их в callback
        on_message и отправляет результаты обратно.

        Args:
            on_message: Callback, принимающий ACPMessage и возвращающий
                       ProtocolOutcome (response + notifications).

        Цикл завершается при:
        - Закрытии соединения клиентом
        - EOF (для stdio транспорта)
        - Вызове close() из другого task
        - Ошибке соединения
        """
        ...

    async def send(self, message: ACPMessage) -> None:
        """Отправить сообщение клиенту.

        Используется для отправки:
        - Response на запрос клиента
        - Notification (session/update и др.)
        - Agent→Client RPC запросов

        Реализация должна гарантировать:
        - Сериализацию в JSON
        - Атомарность записи (без interleaving)
        - Корректную обработку закрытого соединения

        Args:
            message: ACPMessage для отправки (response, notification или RPC request).

        Raises:
            ConnectionError: Если соединение закрыто.
        """
        ...

    async def close(self) -> None:
        """Graceful shutdown транспорта.

        Выполняет:
        - Остановку цикла чтения
        - Закрытие соединения
        - Очистку ресурсов
        - Отмену pending operations

        Метод должен быть идемпотентным — повторный вызов безопасен.
        """
        ...
