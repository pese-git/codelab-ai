"""Конфигурация клиента для DI-контейнера.

Содержит все параметры, необходимые для создания
DI-контейнера клиентского приложения.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ClientConfig:
    """Конфигурация клиентского приложения.

    Attributes:
        host: Адрес сервера ACP
        port: Порт сервера ACP
        cwd: Рабочая директория проекта
        history_dir: Директория локальной истории чата
        logger: Logger для структурированного логирования
    """

    host: str
    port: int
    cwd: Path
    history_dir: str | None = None
    logger: Any = None
