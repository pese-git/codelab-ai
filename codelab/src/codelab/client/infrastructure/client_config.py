"""Конфигурация клиента для DI-контейнера.

Содержит все параметры, необходимые для создания
DI-контейнера клиентского приложения.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ClientConfig:
    """Конфигурация клиентского приложения.

    Attributes:
        host: Адрес сервера ACP (для WebSocket режима)
        port: Порт сервера ACP (для WebSocket режима)
        cwd: Рабочая директория проекта
        history_dir: Директория локальной истории чата
        logger: Logger для структурированного логирования
        transport_mode: Режим транспорта ("websocket" или "stdio")
        stdio_command: Команда для запуска агента (для stdio режима)
        stdio_args: Аргументы команды (для stdio режима)
    """

    host: str
    port: int
    cwd: Path
    history_dir: str | None = None
    logger: Any = None
    transport_mode: str = "websocket"
    stdio_command: str | None = None
    stdio_args: list[str] = field(default_factory=list)
