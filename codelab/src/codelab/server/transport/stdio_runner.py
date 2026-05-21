"""Функция запуска ACP-сервера в stdio режиме.

Модуль содержит run_stdio_server() — аналог ACPHttpServer.run() для
stdio транспорта. Создаёт DI контейнер, ClientRPCService и запускает
цикл обработки сообщений через StdioServerTransport.

Пример использования:
    from codelab.server.transport.stdio_runner import run_stdio_server
    from codelab.server.storage import InMemoryStorage

    storage = InMemoryStorage()
    await run_stdio_server(storage=storage, config=AppConfig())
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

from codelab.server.config import AppConfig
from codelab.server.di import make_container
from codelab.server.messages import ACPMessage
from codelab.server.protocol.core import ACPProtocol
from codelab.server.rpc_holder import ClientRPCServiceHolder
from codelab.server.storage import SessionStorage
from codelab.server.transport.stdio import StdioServerTransport

if TYPE_CHECKING:
    pass

logger = structlog.get_logger()


async def run_stdio_server(
    storage: SessionStorage,
    config: AppConfig,
    *,
    require_auth: bool = False,
    auth_api_key: str | None = None,
) -> None:
    """Запускает ACP-сервер в stdio режиме.

    Создаёт DI контейнер, ClientRPCService и запускает цикл обработки
    сообщений через StdioServerTransport.

    В stdio режиме:
    - Все JSON-RPC сообщения читаются из stdin
    - Все ответы записываются в stdout
    - Логи направляются в stderr
    - Web UI не запускается

    Args:
        storage: Хранилище сессий.
        config: Глобальная конфигурация приложения.
        require_auth: Требовать аутентификацию.
        auth_api_key: API ключ для аутентификации.
    """
    logger.info(
        "starting stdio server",
        llm_provider=config.llm.provider,
        storage_type=type(storage).__name__,
        require_auth=require_auth,
    )

    # Создаём DI контейнер
    container = make_container(
        config=config,
        storage=storage,
        require_auth=require_auth,
        auth_api_key=auth_api_key,
    )

    # Создаём stdio транспорт
    transport = StdioServerTransport()

    # Создаём ClientRPCService для Agent→Client RPC
    # В stdio режиме RPC тоже идёт через stdout (тот же канал)
    async def send_rpc_request(request_dict: dict) -> None:
        """Отправляет JSON-RPC request клиенту через stdout."""
        message = ACPMessage.from_dict(request_dict)
        await transport.send(message)

    from codelab.server.client_rpc.service import ClientRPCService

    client_rpc_service = ClientRPCService(
        send_request_callback=send_rpc_request,
        client_capabilities={
            "fs": {
                "readTextFile": True,
                "writeTextFile": True,
            },
            "terminal": True,
        },
    )

    try:
        # Устанавливаем ClientRPCService в holder
        holder = await container.get(ClientRPCServiceHolder)
        holder.service = client_rpc_service

        # Создаём REQUEST scope и получаем ACPProtocol
        async with container() as request_scope:
            protocol = await request_scope.get(ACPProtocol)

            # Настраиваем send_callback для отправки сообщений из фоновых задач
            protocol._send_callback = transport.send

            # Запускаем цикл обработки через handle_and_process
            # чтобы фоновые задачи (pending_tool_execution) работали корректно
            async def on_message(acp_request: ACPMessage) -> Any:
                return await protocol.handle_and_process(acp_request)

            await transport.run(on_message=on_message)

    except asyncio.CancelledError:
        logger.info("stdio server cancelled")
    except Exception as exc:
        logger.error(
            "stdio server error",
            error=str(exc),
            exc_info=True,
        )
    finally:
        # Cleanup: отменяем pending RPC requests
        if client_rpc_service is not None:
            cancelled = client_rpc_service.cancel_all_pending_requests(
                reason="stdio server shutting down",
            )
            if cancelled > 0:
                logger.info(
                    "pending client rpc cancelled",
                    cancelled_rpc_count=cancelled,
                )

        # Закрываем DI контейнер
        await container.close()

        logger.info("stdio server stopped")
