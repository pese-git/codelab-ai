"""Stdio транспорт ACP-сервера.

Модуль содержит реализацию AcpServerTransport поверх stdin/stdout.
Сервер читает JSON-RPC сообщения из stdin, обрабатывает через callback
и записывает ответы в stdout. Каждое сообщение отделено символом новой строки.

Логирование направляется ТОЛЬКО в stderr — stdout содержит исключительно
JSON-RPC сообщения.

Пример использования:
    transport = StdioServerTransport()
    await transport.run(on_message=protocol.handle)
"""

from __future__ import annotations

import asyncio
import signal
import sys
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from codelab.server.messages import ACPMessage
from codelab.server.protocol.state import ProtocolOutcome
from codelab.server.transport.base import AcpServerTransport

logger = structlog.get_logger()


class StdioServerTransport(AcpServerTransport):
    """Stdio реализация AcpServerTransport.

    Читает JSON-RPC сообщения из stdin (newline-delimited), передаёт
    их в callback on_message и записывает responses/notifications в stdout.

    Все логи направляются в stderr — stdout содержит ТОЛЬКО JSON-RPC.

    Атрибуты:
        _stdin_reader: asyncio.StreamReader для чтения из stdin
        _send_lock: asyncio.Lock для защиты записи в stdout
        _closed: Флаг завершения работы
    """

    def __init__(self) -> None:
        """Инициализирует stdio транспорт."""
        self._stdin_reader: asyncio.StreamReader | None = None
        self._send_lock = asyncio.Lock()
        self._closed = False
        self._on_message: Callable[[ACPMessage], Awaitable[ProtocolOutcome]] | None = None

    async def run(
        self,
        on_message: Callable[[ACPMessage], Awaitable[ProtocolOutcome]],
    ) -> None:
        """Основной цикл чтения сообщений из stdin.

        Читает строки из stdin, парсит JSON-RPC, вызывает on_message
        и отправляет результаты в stdout.

        Завершается при:
        - EOF (stdin закрыт)
        - Вызове close()
        - Ошибке парсинга (продолжает работу, логирует ошибку)

        Args:
            on_message: Callback для обработки входящих сообщений.
        """
        self._on_message = on_message

        # Настраиваем line buffering для stdout
        sys.stdout.reconfigure(line_buffering=True)

        # Создаём StreamReader для stdin
        self._stdin_reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(self._stdin_reader)
        await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin.buffer)

        # Register signal handlers для graceful shutdown
        self._setup_signal_handlers()

        logger.info("stdio transport started")

        try:
            while not self._closed:
                line = await self._stdin_reader.readline()

                if not line:
                    # EOF — stdin закрыт
                    logger.info("stdin EOF, shutting down")
                    break

                # Декодируем и парсим JSON-RPC сообщение
                try:
                    text = line.decode("utf-8").strip()
                    if not text:
                        # Пустая строка — пропускаем
                        continue

                    acp_request = ACPMessage.from_json(text)
                except Exception as exc:
                    # Parse error — отправляем error response
                    logger.warning("parse error", error=str(exc))
                    error_response = ACPMessage.error_response(
                        None,
                        code=-32700,
                        message="Parse error",
                        data=str(exc),
                    )
                    await self.send(error_response)
                    continue

                # Обрабатываем сообщение через callback
                try:
                    outcome = await on_message(acp_request)
                    await self._send_outcome(outcome)
                except Exception as exc:
                    logger.error(
                        "message handling error",
                        method=acp_request.method,
                        error=str(exc),
                        exc_info=True,
                    )
                    error_response = ACPMessage.error_response(
                        acp_request.id,
                        code=-32603,
                        message="Internal error",
                        data=str(exc),
                    )
                    await self.send(error_response)

        except asyncio.CancelledError:
            logger.info("stdio transport cancelled")
        finally:
            self._restore_signal_handlers()
            logger.info("stdio transport stopped")

    async def send(self, message: ACPMessage) -> None:
        """Отправить сообщение в stdout.

        Записывает JSON-RPC сообщение в stdout, завершённое newline.
        Защищено asyncio.Lock для предотвращения interleaving.

        Args:
            message: ACPMessage для отправки.
        """
        async with self._send_lock:
            if self._closed:
                return

            try:
                data = message.to_json().encode("utf-8") + b"\n"
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            except BrokenPipeError:
                logger.warning("stdout pipe broken, closing transport")
                self._closed = True
            except Exception as exc:
                logger.error("send error", error=str(exc))

    async def close(self) -> None:
        """Graceful shutdown транспорта.

        Устанавливает флаг _closed, отменяет pending operations.
        Метод идемпотентен.
        """
        self._closed = True
        logger.info("stdio transport closing")

    # =========================================================================
    # Internal helpers
    # =========================================================================

    async def _send_outcome(self, outcome: ProtocolOutcome) -> None:
        """Отправляет notifications, response и followups из outcome."""
        # Сначала notifications
        for notification in outcome.notifications:
            await self.send(notification)

        # Затем response
        if outcome.response is not None:
            await self.send(outcome.response)

        # Затем followup responses
        for followup in outcome.followup_responses:
            await self.send(followup)

    def _setup_signal_handlers(self) -> None:
        """Register signal handlers для graceful shutdown."""
        loop = asyncio.get_running_loop()

        def _signal_handler(signum: int, frame: Any) -> None:
            logger.info("signal received", signal=signum)
            self._closed = True

        try:
            signal.signal(signal.SIGTERM, _signal_handler)
            signal.signal(signal.SIGINT, _signal_handler)
        except (ValueError, OSError):
            # Signal handlers can only be set from main thread
            logger.debug("signal handlers not set (not main thread)")

    def _restore_signal_handlers(self) -> None:
        """Restore default signal handlers."""
        try:
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            signal.signal(signal.SIGINT, signal.SIG_DFL)
        except (ValueError, OSError):
            pass
