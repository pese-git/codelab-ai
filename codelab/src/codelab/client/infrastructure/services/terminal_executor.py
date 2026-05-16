"""TerminalExecutor - исполнитель терминальных команд в локальной среде клиента.

Модуль предоставляет:
- Создание и управление терминальными сессиями (асинхронно)
- Запуск команд в фоновом режиме
- Чтение output с буферизацией
- Ожидание завершения процесса
- Убийство процесса
- Освобождение ресурсов
- Синхронное выполнение команд для callbacks

Пример использования:
    executor = TerminalExecutor()
    # Асинхронно
    terminal_id = await executor.create_terminal("python", ["-m", "pytest"], cwd="/project")
    output, is_complete, exit_code = await executor.get_output(terminal_id)
    exit_code = await executor.wait_for_exit(terminal_id)
    await executor.release_terminal(terminal_id)
    # Синхронно
    result = executor.execute("ls -la", cwd="/project")
"""

from __future__ import annotations

import asyncio
import shlex
import subprocess
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger("terminal_executor")


class TerminalState(Enum):
    """Состояние терминала."""

    CREATED = "created"
    RUNNING = "running"
    EXITED = "exited"
    RELEASED = "released"


@dataclass
class TerminalSession:
    """Сессия терминала с управлением процессом.

    Attributes:
        terminal_id: Уникальный ID сессии
        command: Команда для выполнения
        args: Аргументы команды
        process: asyncio.subprocess.Process
        state: Текущее состояние
        output_buffer: Буфер вывода процесса
        exit_code: Код выхода (если завершился)
        output_byte_limit: Лимит байт output (опционально)
    """

    terminal_id: str
    command: str
    args: list[str]
    process: asyncio.subprocess.Process
    state: TerminalState
    output_buffer: list[str] = field(default_factory=list)
    exit_code: int | None = None
    output_byte_limit: int | None = None


class TerminalExecutor:
    """Исполнитель терминальных команд в локальной среде клиента.

    Управляет жизненным циклом процессов, читает output, контролирует
    завершение процесса.

    Attributes:
        _terminals: Словарь активных терминальных сессий
    """

    def __init__(self) -> None:
        """Инициализирует executor."""
        self._terminals: dict[str, TerminalSession] = {}
        logger.debug("terminal_executor_initialized")

    async def create_terminal(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        output_byte_limit: int | None = None,
    ) -> str:
        """Создать терминал и запустить команду.

        Запускает процесс и сразу же запускает фоновую задачу для чтения output.

        Args:
            command: Команда для выполнения (e.g., "python", "bash")
            args: Аргументы команды (e.g., ["-m", "pytest"])
            env: Переменные окружения (опционально)
            cwd: Рабочая директория (опционально)
            output_byte_limit: Лимит байт output (опционально)

        Returns:
            Terminal ID для последующих операций

        Raises:
            RuntimeError: Ошибка запуска процесса
        """
        terminal_id = f"term_{uuid.uuid4().hex[:12]}"
        args = args or []

        try:
            # Запустить процесс с объединением stderr в stdout
            process = await asyncio.create_subprocess_exec(
                command,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
                env=env,
            )

            # Создать сессию
            session = TerminalSession(
                terminal_id=terminal_id,
                command=command,
                args=args,
                process=process,
                state=TerminalState.RUNNING,
                output_buffer=[],
                output_byte_limit=output_byte_limit,
            )

            self._terminals[terminal_id] = session

            # Запустить фоновую задачу для чтения output
            asyncio.create_task(self._read_output(session))

            logger.info(
                "terminal_created",
                terminal_id=terminal_id,
                command=command,
                args=args,
                cwd=cwd,
            )

            return terminal_id
        except Exception as e:
            logger.error("terminal_create_error", command=command, error=str(e))
            raise RuntimeError(f"Failed to create terminal: {e}") from e

    async def _read_output(self, session: TerminalSession) -> None:
        """Читать output процесса в фоне.

        Эта функция работает в отдельной задаче и читает output процесса
        построчно, добавляя в буфер и контролируя размер.

        Args:
            session: Сессия терминала
        """
        try:
            if not session.process.stdout:
                logger.warning("stdout_is_none", terminal_id=session.terminal_id)
                return

            while True:
                line = await session.process.stdout.readline()
                if not line:
                    break

                decoded = line.decode("utf-8", errors="replace")
                session.output_buffer.append(decoded)

                # Проверить лимит байт
                if session.output_byte_limit:
                    total_bytes = sum(len(line.encode()) for line in session.output_buffer)
                    if total_bytes > session.output_byte_limit:
                        # Обрезать старые строки
                        while (
                            total_bytes > session.output_byte_limit
                            and session.output_buffer
                        ):
                            removed = session.output_buffer.pop(0)
                            total_bytes -= len(removed.encode())

            # Процесс завершился
            await session.process.wait()
            session.exit_code = session.process.returncode
            session.state = TerminalState.EXITED

            logger.info(
                "terminal_exited",
                terminal_id=session.terminal_id,
                exit_code=session.exit_code,
            )
        except asyncio.CancelledError:
            logger.debug("terminal_read_output_cancelled", terminal_id=session.terminal_id)
        except Exception as e:
            logger.error(
                "terminal_read_output_error",
                terminal_id=session.terminal_id,
                error=str(e),
            )

    async def get_output(self, terminal_id: str) -> tuple[str, bool, int | None]:
        """Получить output терминала.

        Возвращает текущий output буфер и информацию о завершении.

        Args:
            terminal_id: ID терминала

        Returns:
            Tuple (output_text, is_complete, exit_code)
                - output_text: Полный output с начала или после обрезки
                - is_complete: Завершился ли процесс
                - exit_code: Код выхода (или None если еще работает)

        Raises:
            ValueError: Терминал не найден
        """
        session = self._terminals.get(terminal_id)
        if not session:
            logger.warning("terminal_not_found", terminal_id=terminal_id)
            raise ValueError(f"Terminal not found: {terminal_id}")

        output = "".join(session.output_buffer)
        is_complete = session.state == TerminalState.EXITED

        logger.debug(
            "terminal_output_retrieved",
            terminal_id=terminal_id,
            output_size=len(output),
            is_complete=is_complete,
        )

        return output, is_complete, session.exit_code

    async def wait_for_exit(self, terminal_id: str) -> int:
        """Дождаться завершения терминала.

        Блокирует до завершения процесса.

        Args:
            terminal_id: ID терминала

        Returns:
            Exit code процесса

        Raises:
            ValueError: Терминал не найден
        """
        session = self._terminals.get(terminal_id)
        if not session:
            logger.warning("terminal_not_found_wait", terminal_id=terminal_id)
            raise ValueError(f"Terminal not found: {terminal_id}")

        if session.state == TerminalState.EXITED:
            logger.debug(
                "terminal_already_exited",
                terminal_id=terminal_id,
                exit_code=session.exit_code,
            )
            return session.exit_code or 0

        # Ждать завершения процесса
        await session.process.wait()
        exit_code = session.process.returncode or 0

        logger.info(
            "terminal_wait_complete",
            terminal_id=terminal_id,
            exit_code=exit_code,
        )

        return exit_code

    async def kill_terminal(self, terminal_id: str) -> bool:
        """Убить процесс терминала.

        Сигнал SIGKILL для принудительного завершения.

        Args:
            terminal_id: ID терминала

        Returns:
            True при успехе

        Raises:
            ValueError: Терминал не найден
        """
        session = self._terminals.get(terminal_id)
        if not session:
            logger.warning("terminal_not_found_kill", terminal_id=terminal_id)
            raise ValueError(f"Terminal not found: {terminal_id}")

        if session.state != TerminalState.EXITED:
            try:
                session.process.kill()
                await session.process.wait()
                session.state = TerminalState.EXITED
                session.exit_code = session.process.returncode
            except Exception as e:
                logger.error("terminal_kill_error", terminal_id=terminal_id, error=str(e))
                raise RuntimeError(f"Failed to kill terminal: {e}") from e

        logger.info("terminal_killed", terminal_id=terminal_id)
        return True

    async def release_terminal(self, terminal_id: str) -> bool:
        """Освободить ресурсы терминала.

        Удаляет сессию из реестра и очищает ресурсы.

        Args:
            terminal_id: ID терминала

        Returns:
            True при успехе

        Raises:
            ValueError: Терминал не найден
        """
        session = self._terminals.pop(terminal_id, None)
        if not session:
            logger.warning("terminal_not_found_release", terminal_id=terminal_id)
            raise ValueError(f"Terminal not found: {terminal_id}")

        # Убедиться что процесс завершен
        if session.state != TerminalState.EXITED:
            try:
                session.process.kill()
                await session.process.wait()
            except Exception as e:
                logger.warning("error_killing_process_on_release", error=str(e))

        session.state = TerminalState.RELEASED
        session.output_buffer.clear()

        logger.info("terminal_released", terminal_id=terminal_id)
        return True

    async def cleanup_all(self) -> None:
        """Освободить все терминалы.

        Вызвать при завершении приложения.
        """
        terminal_ids = list(self._terminals.keys())
        for terminal_id in terminal_ids:
            try:
                await self.release_terminal(terminal_id)
            except Exception as e:
                logger.warning("error_releasing_terminal_on_cleanup", error=str(e))

        logger.info("all_terminals_cleaned_up", count=len(terminal_ids))

    def execute(self, command: str, cwd: str | None = None) -> dict[str, Any]:
        """Выполнить команду синхронно и дождаться результата.

        Используется для синхронных callbacks (не требует asyncio event loop).

        Команда разбивается на аргументы через shlex.split.
        Shell-операторы (; && || | > >>) НЕ поддерживаются намеренно
        для предотвращения shell injection.

        Args:
            command: Команда для выполнения. Разбивается на аргументы через shlex.split.
            cwd: Рабочая директория (опционально)

        Returns:
            Словарь с ключами:
            - exit_code (int): Код выхода процесса
            - output (str): Вывод процесса (stdout + stderr)
            - success (bool): True если exit_code == 0

        Example:
            result = executor.execute("ls -la", cwd="/tmp")
            print(result["output"])
        """
        try:
            logger.debug("execute_command_sync", command=command, cwd=cwd)

            # Безопасно разбиваем строку команды на список аргументов
            # без интерпретации shell-операторов
            try:
                args = shlex.split(command)
            except ValueError as e:
                logger.error("invalid_command_syntax", command=command, error=str(e))
                return {
                    "exit_code": -1,
                    "output": f"Invalid command syntax: {e}",
                    "success": False,
                }

            if not args:
                return {
                    "exit_code": -1,
                    "output": "Empty command",
                    "success": False,
                }

            # Выполняем команду без оболочки (shell=False)
            process = subprocess.run(
                args,
                shell=False,
                cwd=cwd,
                capture_output=True,
                text=True,
            )

            output = process.stdout
            if process.stderr:
                output = output + process.stderr if output else process.stderr

            logger.info(
                "execute_command_sync_complete",
                command=command,
                exit_code=process.returncode,
                output_size=len(output),
            )

            return {
                "exit_code": process.returncode,
                "output": output,
                "success": process.returncode == 0,
            }
        except FileNotFoundError:
            executable = shlex.split(command)[0] if command.strip() else command
            logger.error("command_not_found", executable=executable)
            return {
                "exit_code": 127,
                "output": f"Command not found: {executable}",
                "success": False,
            }
        except Exception as e:
            logger.error("execute_command_sync_error", command=command, error=str(e))
            return {
                "exit_code": -1,
                "output": f"Error executing command: {e}",
                "success": False,
            }
