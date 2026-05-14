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
) -> Container:
    """Создаёт и конфигурирует DI-контейнер для клиента.

    Регистрирует все сервисы и ViewModels через декларативные
    Provider'ы (ClientProvider + ViewModelProvider).

    Args:
        host: Адрес сервера ACP
        port: Порт сервера ACP
        cwd: Абсолютный путь к рабочей директории проекта
        history_dir: Путь к директории локальной истории чата
        logger: Logger для структурированного логирования

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
    )

    try:
        # Создаём конфигурацию для передачи в контекст
        config = ClientConfig(
            host=host,
            port=port,
            cwd=Path(cwd),
            history_dir=history_dir,
            logger=logger,
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
