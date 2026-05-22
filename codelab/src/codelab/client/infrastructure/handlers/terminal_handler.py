"""TerminalHandler - обработчик terminal/* методов от агента.

Модуль предоставляет:
- Обработку terminal/create запросов
- Обработку terminal/output запросов
- Обработку terminal/wait_for_exit запросов
- Обработку terminal/kill запросов
- Обработку terminal/release запросов

Пример использования:
    executor = TerminalExecutor()
    handler = TerminalHandler(executor)
    result = await handler.handle_create({
        "sessionId": "sess_123",
        "command": "python",
        "args": ["-m", "pytest"],
        "cwd": "/project"
    })
"""

from __future__ import annotations

from typing import Any

import structlog

from codelab.client.infrastructure.services.terminal_executor import TerminalExecutor

logger = structlog.get_logger("terminal_handler")


class TerminalHandler:
    """Обработчик terminal/* методов от агента.

    Класс обрабатывает входящие RPC запросы от агента для операций терминала.

    Attributes:
        executor: TerminalExecutor для выполнения операций
    """

    def __init__(self, executor: TerminalExecutor) -> None:
        """Инициализирует handler с executor.

        Args:
            executor: TerminalExecutor для выполнения операций

        Пример:
            executor = TerminalExecutor()
            handler = TerminalHandler(executor)
        """
        self.executor = executor
        logger.debug("terminal_handler_initialized")

    async def handle_create(self, params: dict[str, Any]) -> dict[str, Any]:
        """Обработать terminal/create request от агента.

        Создает новый терминал с указанной командой.

        Args:
            params: Request параметры
                - sessionId (str): ID сессии запроса
                - command (str): Команда для выполнения (e.g., "python", "bash")
                - args (list, optional): Аргументы команды
                - env (dict, optional): Переменные окружения
                - cwd (str, optional): Рабочая директория
                - output_byte_limit (int, optional): Лимит output в байтах

        Returns:
            dict с ключом "terminalId"

        Raises:
            ValueError: Отсутствуют необходимые параметры
            RuntimeError: Ошибка создания терминала
        """
        session_id = params.get("sessionId", "unknown")
        command = params.get("command")
        args = params.get("args")
        env = params.get("env")
        cwd = params.get("cwd")
        output_byte_limit = params.get("output_byte_limit")

        if not command:
            logger.warning("terminal_create_missing_command", session_id=session_id)
            raise ValueError("Missing required parameter: command")

        logger.info(
            "agent_terminal_create_request",
            session_id=session_id,
            command=command,
            args=args,
            cwd=cwd,
        )

        try:
            terminal_id = await self.executor.create_terminal(
                command=command,
                args=args,
                env=env,
                cwd=cwd,
                output_byte_limit=output_byte_limit,
            )

            logger.info(
                "agent_terminal_create_success",
                session_id=session_id,
                terminal_id=terminal_id,
            )
            return {"terminalId": terminal_id}
        except (ValueError, RuntimeError) as e:
            logger.error(
                "agent_terminal_create_error",
                session_id=session_id,
                command=command,
                error=str(e),
            )
            raise

    async def handle_output(self, params: dict[str, Any]) -> dict[str, Any]:
        """Обработать terminal/output request от агента.

        Получает текущий output терминала.

        Args:
            params: Request параметры
                - sessionId (str): ID сессии запроса
                - terminalId (str): ID терминала

        Returns:
            dict с ключами:
                - output (str): Текущий output
                - isComplete (bool): Завершился ли процесс
                - exitCode (int | None): Код выхода (если завершился)

        Raises:
            ValueError: Терминал не найден
        """
        session_id = params.get("sessionId", "unknown")
        terminal_id = params.get("terminalId")

        if not terminal_id:
            logger.warning("terminal_output_missing_id", session_id=session_id)
            raise ValueError("Missing required parameter: terminalId")

        logger.debug(
            "agent_terminal_output_request",
            session_id=session_id,
            terminal_id=terminal_id,
        )

        try:
            output, is_complete, exit_code = await self.executor.get_output(terminal_id)

            logger.debug(
                "agent_terminal_output_success",
                session_id=session_id,
                terminal_id=terminal_id,
                output_size=len(output),
                is_complete=is_complete,
            )
            return {
                "output": output,
                "isComplete": is_complete,
                "exitCode": exit_code,
            }
        except ValueError as e:
            logger.error(
                "agent_terminal_output_error",
                session_id=session_id,
                terminal_id=terminal_id,
                error=str(e),
            )
            raise

    async def handle_wait_for_exit(self, params: dict[str, Any]) -> dict[str, Any]:
        """Обработать terminal/wait_for_exit request от агента.

        Блокирует до завершения процесса и возвращает exit code.

        Args:
            params: Request параметры
                - sessionId (str): ID сессии запроса
                - terminalId (str): ID терминала

        Returns:
            dict с ключом "exitCode"

        Raises:
            ValueError: Терминал не найден
        """
        session_id = params.get("sessionId", "unknown")
        terminal_id = params.get("terminalId")

        if not terminal_id:
            logger.warning("terminal_wait_missing_id", session_id=session_id)
            raise ValueError("Missing required parameter: terminalId")

        logger.info(
            "agent_terminal_wait_request",
            session_id=session_id,
            terminal_id=terminal_id,
        )

        try:
            exit_code = await self.executor.wait_for_exit(terminal_id)
            
            # Получаем output терминала
            output, _, _ = await self.executor.get_output(terminal_id)

            logger.info(
                "agent_terminal_wait_success",
                session_id=session_id,
                terminal_id=terminal_id,
                exit_code=exit_code,
            )
            return {"exitCode": exit_code, "output": output}
        except ValueError as e:
            logger.error(
                "agent_terminal_wait_error",
                session_id=session_id,
                terminal_id=terminal_id,
                error=str(e),
            )
            raise

    async def handle_kill(self, params: dict[str, Any]) -> dict[str, Any]:
        """Обработать terminal/kill request от агента.

        Убивает процесс терминала.

        Args:
            params: Request параметры
                - sessionId (str): ID сессии запроса
                - terminalId (str): ID терминала

        Returns:
            dict с ключом "success" = true

        Raises:
            ValueError: Терминал не найден
            RuntimeError: Ошибка убийства процесса
        """
        session_id = params.get("sessionId", "unknown")
        terminal_id = params.get("terminalId")

        if not terminal_id:
            logger.warning("terminal_kill_missing_id", session_id=session_id)
            raise ValueError("Missing required parameter: terminalId")

        logger.info(
            "agent_terminal_kill_request",
            session_id=session_id,
            terminal_id=terminal_id,
        )

        try:
            await self.executor.kill_terminal(terminal_id)

            logger.info(
                "agent_terminal_kill_success",
                session_id=session_id,
                terminal_id=terminal_id,
            )
            # ACP spec: empty response means success
            return {}
        except (ValueError, RuntimeError) as e:
            logger.error(
                "agent_terminal_kill_error",
                session_id=session_id,
                terminal_id=terminal_id,
                error=str(e),
            )
            raise

    async def handle_release(self, params: dict[str, Any]) -> dict[str, Any]:
        """Обработать terminal/release request от агента.

        Освобождает ресурсы терминала.

        Args:
            params: Request параметры
                - sessionId (str): ID сессии запроса
                - terminalId (str): ID терминала

        Returns:
            dict с ключом "success" = true

        Raises:
            ValueError: Терминал не найден
        """
        session_id = params.get("sessionId", "unknown")
        terminal_id = params.get("terminalId")

        if not terminal_id:
            logger.warning("terminal_release_missing_id", session_id=session_id)
            raise ValueError("Missing required parameter: terminalId")

        logger.info(
            "agent_terminal_release_request",
            session_id=session_id,
            terminal_id=terminal_id,
        )

        try:
            await self.executor.release_terminal(terminal_id)

            logger.info(
                "agent_terminal_release_success",
                session_id=session_id,
                terminal_id=terminal_id,
            )
            # ACP spec: empty response means success
            return {}
        except ValueError as e:
            logger.error(
                "agent_terminal_release_error",
                session_id=session_id,
                terminal_id=terminal_id,
                error=str(e),
            )
            raise
