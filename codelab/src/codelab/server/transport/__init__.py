"""Транспортный слой ACP-сервера.

Пакет предоставляет абстракцию транспорта и реализации для различных
механизмов коммуникации (WebSocket, stdio).

Архитектура:
- AcpServerTransport — протокол (интерфейс) транспорта
- WebSocketTransport — реализация поверх aiohttp WebSocket
- StdioServerTransport — реализация поверх stdin/stdout
- stdio_runner — функция запуска сервера в stdio режиме

Пример использования:
    # WebSocket транспорт
    transport = WebSocketTransport(ws_connection)
    await transport.run(on_message=protocol.handle)

    # Stdio транспорт
    transport = StdioServerTransport()
    await transport.run(on_message=protocol.handle)
"""

from .base import AcpServerTransport
from .stdio import StdioServerTransport
from .websocket import WebSocketTransport

__all__ = ["AcpServerTransport", "WebSocketTransport", "StdioServerTransport"]
