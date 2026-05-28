"""Фабрика создания DI-контейнера клиента.

Заменяет DIBootstrapper.build(). Создаёт dishka-контейнер
с ClientProvider и ViewModelProvider.

Пример использования:
    >>> container = create_client_container(
    ...     host="localhost", port=8000, cwd="/project"
    ... )
    >>> coordinator = container.get(SessionCoordinator)
    >>> await container.get(ACPTransportService).disconnect()
    >>> container.close()
"""

import os
from pathlib import Path
from typing import Any

import structlog
from dishka import Container, make_container

from codelab.client.infrastructure.client_config import ClientConfig
from codelab.client.infrastructure.providers import ClientProvider
from codelab.client.infrastructure.view_model_provider import ViewModelProvider


def create_client_container(
    host: str,
    port: int,
    cwd: str | None = None,
    history_dir: str | None = None,
    logger: Any | None = None,
    transport_mode: str = "websocket",
    stdio_command: str | None = None,
    stdio_args: list[str] | None = None,
    mcp_servers: list[dict[str, Any]] | None = None,
    receive_timeout: float = 60.0,
) -> Container:
    """Создаёт и конфигурирует DI-контейнер для клиента.

    Регистрирует все зависимости через декларативные
    Provider'ы (ClientProvider + ViewModelProvider).

    Args:
        host: Адрес сервера ACP
        port: Порт сервера ACP
        cwd: Абсолютный путь к рабочей директории проекта
        history_dir: Путь к директории локальной истории чата
        logger: Logger для структурированного логирования
        transport_mode: Режим транспорта ("websocket" или "stdio")
        stdio_command: Команда для запуска агента (для stdio режима)
        stdio_args: Аргументы команды (для stdio режима)
        mcp_servers: Конфигурация MCP серверов из TOML файлов
        receive_timeout: Таймаут ожидания сообщения от сервера (секунды)

    Returns:
        Готовый dishka Container

    Raises:
        RuntimeError: Если произойдёт ошибка при создании контейнера
    """
    if logger is None:
        logger = structlog.get_logger("client_container")

    # Если cwd не передан, используем текущую рабочую директорию
    if cwd is None:
        cwd = os.getcwd()

    logger.info(
        "creating_client_container",
        host=host,
        port=port,
        cwd=cwd,
        transport_mode=transport_mode,
    )

    try:
        # Создаём конфигурацию для передачи в контекст
        config = ClientConfig(
            host=host,
            port=port,
            cwd=Path(cwd),
            history_dir=history_dir,
            logger=logger,
            transport_mode=transport_mode,
            stdio_command=stdio_command,
            stdio_args=stdio_args or [],
            mcp_servers=mcp_servers or [],
            receive_timeout=receive_timeout,
        )

        container = make_container(
            ClientProvider(),
            ViewModelProvider(),
            context={ClientConfig: config},
        )

        logger.info("client_container_created_successfully")
        return container

    except Exception as e:
        logger.error(
            "failed_to_create_client_container",
            error=str(e),
        )
        raise RuntimeError(
            f"Failed to create DI container: {e}. Check logs for details."
        ) from e
