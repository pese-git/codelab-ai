"""Stdio транспорт ACP-клиента.

Модуль содержит реализацию Transport поверх subprocess. Клиент запускает
агент как subprocess и коммуницирует через stdin/stdout pipes.

Пример использования:
    transport = StdioClientTransport(
        command="codelab",
        args=["serve", "--stdio"],
        cwd="/project",
    )
    async with transport:
        await transport.send_str('{"jsonrpc": "2.0", "id": 1, ...}')
        response = await transport.receive_text()
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog


class StdioClientTransport:
    """Клиентский stdio транспорт — запускает агент как subprocess.

    Управляет жизненным циклом subprocess: запуск, коммуникация через
    stdin/stdout, graceful shutdown.

    Атрибуты:
        _process: asyncio.subprocess.Process
        _stdout_queue: asyncio.Queue для буферизации входящих сообщений
        _stdout_task: фоновая задача чтения stdout
        _stderr_task: фоновая задача чтения stderr (логирование)
    """

    def __init__(
        self,
        command: str,
        args: list[str],
        cwd: str | None = None,
        receive_timeout: float = 60.0,
    ) -> None:
        """Инициализирует stdio транспорт.

        Args:
            command: Команда для запуска агента (напр. "codelab").
            args: Аргументы командной строки (напр. ["serve", "--stdio"]).
            cwd: Рабочая директория для subprocess.
            receive_timeout: Таймаут ожидания сообщения от сервера в секундах.
                Default 60.0 — покрывает LLM запросы к удалённым API.
        """
        self._command = command
        self._args = args
        self._cwd = cwd
        self._receive_timeout = receive_timeout
        self._process: asyncio.subprocess.Process | None = None
        self._stdout_queue: asyncio.Queue[str] = asyncio.Queue()
        self._stdout_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._closed = False
        self._logger = structlog.get_logger("acp_client.transport.stdio")

    async def __aenter__(self) -> StdioClientTransport:
        """Запускает subprocess и фоновые задачи чтения.

        Returns:
            Текущий экземпляр транспорта (self).

        Raises:
            RuntimeError: Если не удалось запустить subprocess.
        """
        cmd_str = f"{self._command} {' '.join(self._args)}"
        self._logger.info("starting subprocess", command=cmd_str, cwd=self._cwd)

        try:
            self._process = await asyncio.create_subprocess_exec(
                self._command,
                *self._args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._cwd,
            )
        except FileNotFoundError as e:
            msg = f"Command not found: {self._command}"
            self._logger.error("command not found", command=self._command)
            raise RuntimeError(msg) from e
        except OSError as e:
            msg = f"Failed to start subprocess: {e}"
            self._logger.error("subprocess start failed", error=str(e))
            raise RuntimeError(msg) from e

        self._logger.info(
            "subprocess started",
            pid=self._process.pid,
            command=cmd_str,
        )

        # Запускаем фоновые задачи чтения
        self._stdout_task = asyncio.create_task(
            self._stdout_reader(),
            name="stdio_stdout_reader",
        )
        self._stderr_task = asyncio.create_task(
            self._stderr_reader(),
            name="stdio_stderr_reader",
        )

        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Graceful shutdown subprocess.

        1. Закрывает stdin (сигнал агенту о завершении)
        2. Ждёт завершения процесса (timeout 5s)
        3. Принудительно завершает если не завершился
        4. Очищает фоновые задачи
        """
        self._closed = True

        # Отменяем фоновые задачи
        if self._stdout_task is not None:
            self._stdout_task.cancel()
        if self._stderr_task is not None:
            self._stderr_task.cancel()

        if self._process is not None:
            # Закрываем stdin — сигнал агенту о завершении
            if self._process.stdin is not None:
                self._process.stdin.close()
                try:
                    await self._process.stdin.wait_closed()
                except Exception:
                    pass

            # Ждём завершения процесса
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
                self._logger.info(
                    "subprocess exited",
                    pid=self._process.pid,
                    returncode=self._process.returncode,
                )
            except TimeoutError:
                self._logger.warning(
                    "subprocess did not exit, terminating",
                    pid=self._process.pid,
                )
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=2.0)
                except TimeoutError:
                    self._logger.warning(
                        "subprocess did not terminate, killing",
                        pid=self._process.pid,
                    )
                    self._process.kill()
                    await self._process.wait()

        self._process = None
        self._logger.debug("stdio transport disconnected")

    async def send_str(self, data: str) -> None:
        """Отправляет строку (JSON-RPC) в stdin subprocess.

        Args:
            data: JSON-строка для отправки.

        Raises:
            RuntimeError: Если subprocess не запущен или stdin закрыт.
        """
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("Subprocess is not running")

        if self._closed:
            raise RuntimeError("Transport is closed")

        try:
            message = data + "\n"
            self._process.stdin.write(message.encode("utf-8"))
            await self._process.stdin.drain()
            self._logger.debug("message sent", length=len(data))
        except BrokenPipeError as e:
            msg = "Subprocess stdin pipe broken"
            self._logger.error("send failed", error=str(e))
            raise RuntimeError(msg) from e
        except Exception as e:
            msg = f"Failed to send message: {e}"
            self._logger.error("send failed", error=str(e))
            raise RuntimeError(msg) from e

    async def receive_text(self) -> str:
        """Получает строку (JSON-RPC) из stdout subprocess.

        Блокирует до получения сообщения из очереди.

        Returns:
            JSON-строка от сервера.

        Raises:
            RuntimeError: Если subprocess завершился или транспорт закрыт.
        """
        if self._closed:
            raise RuntimeError("Transport is closed")

        if self._process is not None and self._process.returncode is not None:
            msg = f"Subprocess exited with code {self._process.returncode}"
            self._logger.error("subprocess exited", returncode=self._process.returncode)
            raise RuntimeError(msg)

        try:
            message = await asyncio.wait_for(
                self._stdout_queue.get(),
                timeout=self._receive_timeout,
            )
            self._logger.debug("message received", length=len(message))
            return message
        except TimeoutError:
            msg = f"Timeout ({self._receive_timeout}s) waiting for message from subprocess"
            self._logger.error("receive timeout")
            raise RuntimeError(msg) from None
        except asyncio.CancelledError:
            raise
        except Exception as e:
            msg = f"Failed to receive message: {e}"
            self._logger.error("receive failed", error=str(e))
            raise RuntimeError(msg) from e

    def is_connected(self) -> bool:
        """Проверяет, активен ли subprocess.

        Returns:
            True если subprocess запущен и не закрыт.
        """
        if self._process is None:
            return False
        if self._closed:
            return False
        return self._process.returncode is None

    # =========================================================================
    # Internal helpers
    # =========================================================================

    async def _stdout_reader(self) -> None:
        """Фоновая задача чтения stdout subprocess.

        Читает строки построчно и кладёт в очередь для receive_text().
        """
        if self._process is None or self._process.stdout is None:
            return

        try:
            while not self._closed:
                line = await self._process.stdout.readline()
                if not line:
                    # EOF — subprocess закрыл stdout
                    self._logger.debug("stdout EOF")
                    break

                text = line.decode("utf-8").strip()
                if text:
                    await self._stdout_queue.put(text)
                    self._logger.debug("stdout line received", length=len(text))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._logger.error("stdout reader error", error=str(e))

    async def _stderr_reader(self) -> None:
        """Фоновая задача чтения stderr subprocess (логирование).

        stderr НЕ парсится как JSON-RPC — только логируется.
        """
        if self._process is None or self._process.stderr is None:
            return

        try:
            while not self._closed:
                line = await self._process.stderr.readline()
                if not line:
                    break

                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    self._logger.debug("agent stderr", text=text)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._logger.warning("stderr reader error", error=str(e))
