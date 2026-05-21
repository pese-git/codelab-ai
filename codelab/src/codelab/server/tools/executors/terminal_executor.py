"""Executor для терминальных операций через ClientRPC."""

from __future__ import annotations

from typing import Any

import structlog

from codelab.server.protocol.state import SessionState
from codelab.server.tools.base import ToolExecutionResult
from codelab.server.tools.executors.base import ToolExecutor
from codelab.server.tools.integrations.client_rpc_bridge import ClientRPCBridge
from codelab.server.tools.integrations.permission_checker import PermissionChecker

logger = structlog.get_logger()


class TerminalToolExecutor(ToolExecutor):
    """Executor для терминальных операций через ClientRPC.
    
    Поддерживает:
    - terminal/create (запуск команды)
    - terminal/wait_for_exit (ожидание завершения)
    - terminal/release (освобождение терминала)
    
    Интегрирует проверку разрешений, логирование и lifecycle management.
    """

    def __init__(
        self,
        client_rpc_bridge: ClientRPCBridge,
        permission_checker: PermissionChecker,
    ) -> None:
        """Инициализировать executor с зависимостями.
        
        Args:
            client_rpc_bridge: Адаптер для ClientRPCService.
            permission_checker: Адаптер для PermissionManager.
        """
        self._bridge = client_rpc_bridge
        self._permission_checker = permission_checker

    async def execute(
        self,
        session: SessionState,
        arguments: dict[str, Any],
    ) -> ToolExecutionResult:
        """Выполнить инструмент на основе аргументов.
        
        Args:
            session: Состояние сессии.
            arguments: Словарь аргументов инструмента.
                Ожидается поле 'operation' для выбора метода.
                
        Returns:
            ToolExecutionResult с результатом выполнения.
        """
        operation = arguments.get("operation")
        
        if operation == "create":
            return await self.execute_create(
                session=session,
                command=arguments.get("command", ""),
                args=arguments.get("args"),
                env=arguments.get("env"),
                cwd=arguments.get("cwd"),
                output_byte_limit=arguments.get("output_byte_limit"),
            )
        elif operation == "wait_for_exit":
            return await self.execute_wait_for_exit(
                session=session,
                terminal_id=arguments.get("terminal_id", ""),
            )
        elif operation == "release":
            return await self.execute_release(
                session=session,
                terminal_id=arguments.get("terminal_id", ""),
            )
        else:
            return ToolExecutionResult(
                success=False,
                error=f"Неизвестная операция: {operation}",
            )

    async def execute_create(
        self,
        session: SessionState,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        output_byte_limit: int | None = None,
    ) -> ToolExecutionResult:
        """Создать терминал и запустить команду через ClientRPC.
        
        Args:
            session: Состояние сессии.
            command: Команда для выполнения.
            args: Аргументы команды (опционально).
            env: Переменные окружения (опционально).
            cwd: Рабочая директория (опционально).
            output_byte_limit: Лимит байт output (опционально).
            
        Returns:
            ToolExecutionResult с terminal_id в metadata.
        """
        try:
            logger.debug(
                "Начало выполнения terminal/create",
                extra={
                    "session_id": session.session_id,
                    "command": command,
                    "cwd": cwd,
                },
            )
            
            # Примечание: Проверка разрешений выполняется в
            # PromptOrchestrator._decide_tool_execution() перед вызовом executor.
            # Здесь мы только выполняем операцию.
            
            # Вызов ClientRPC для создания терминала
            terminal_id = await self._bridge.create_terminal(
                session=session,
                command=command,
                args=args,
                env=env,
                cwd=cwd,
                output_byte_limit=output_byte_limit,
            )
            
            if terminal_id is None:
                return ToolExecutionResult(
                    success=False,
                    error=f"Ошибка при создании терминала для команды: {command}",
                )
            
            logger.debug(
                "Терминал успешно создан",
                extra={
                    "session_id": session.session_id,
                    "terminal_id": terminal_id,
                    "command": command,
                },
            )
            
            # Сгенерировать content для отправки клиенту и LLM согласно ACP Content Types
            content_items = [
                {
                    "type": "text",
                    "text": f"Terminal {terminal_id} created for command: {command}"
                }
            ]
            
            return ToolExecutionResult(
                success=True,
                output=f"Терминал создан с ID: {terminal_id}",
                metadata={
                    "terminal_id": terminal_id,
                    "command": command,
                },
                content=content_items,
            )
            
        except Exception as e:
            logger.error(
                "Ошибка при создании терминала",
                extra={
                    "session_id": session.session_id,
                    "command": command,
                    "error": str(e),
                },
            )
            return ToolExecutionResult(
                success=False,
                error=f"Ошибка при создании терминала: {str(e)}",
            )

    async def execute_wait_for_exit(
        self,
        session: SessionState,
        terminal_id: str,
    ) -> ToolExecutionResult:
        """Ожидать завершения терминала через ClientRPC.
        
        По ACP spec terminal/wait_for_exit возвращает только exitCode/signal.
        Output получается через отдельный вызов terminal/output.
        
        Args:
            session: Состояние сессии.
            terminal_id: ID терминала.
            
        Returns:
            ToolExecutionResult с exit_code и output.
        """
        try:
            logger.debug(
                "Начало выполнения terminal/wait_for_exit",
                extra={
                    "session_id": session.session_id,
                    "terminal_id": terminal_id,
                },
            )
            
            # 1. Сначала пытаемся получить текущий output и статус
            output_data = await self._bridge.terminal_output(
                session=session,
                terminal_id=terminal_id,
            )
            
            output = ""
            exit_code: int | None = -1
            signal: str | None = None
            
            if output_data:
                output = output_data.get("output", "")
                is_complete = output_data.get("is_complete", False)
                exit_code = output_data.get("exit_code")
                signal = output_data.get("signal")
                
                # Если терминал уже завершён — не нужно ждать
                if is_complete and exit_code is not None:
                    logger.debug(
                        "Терминал уже завершён (получено из terminal/output)",
                        extra={
                            "session_id": session.session_id,
                            "terminal_id": terminal_id,
                            "exit_code": exit_code,
                        },
                    )
                    exit_message = f"Terminal {terminal_id} exited with code {exit_code}"
                    content_items = [
                        {
                            "type": "text",
                            "text": f"{exit_message}\n\nOutput:\n{output}",
                        }
                    ]
                    return ToolExecutionResult(
                        success=exit_code == 0,
                        output=output,
                        metadata={
                            "terminal_id": terminal_id,
                            "exit_code": exit_code,
                            "signal": signal,
                        },
                        content=content_items,
                    )
            
            # 2. Если ещё не завершён — ждём через wait_for_exit
            wait_result = await self._bridge.wait_terminal_exit(
                session=session,
                terminal_id=terminal_id,
            )
            
            if wait_result is None:
                return ToolExecutionResult(
                    success=False,
                    error=f"Ошибка при ожидании завершения терминала: {terminal_id}",
                )
            
            exit_code = wait_result.get("exit_code")
            signal = wait_result.get("signal")
            
            # 3. После завершения — получаем финальный output
            final_output_data = await self._bridge.terminal_output(
                session=session,
                terminal_id=terminal_id,
            )
            if final_output_data:
                output = final_output_data.get("output", "")
            
            resolved_exit_code = exit_code if exit_code is not None else -1
            
            logger.debug(
                "Терминал завершен",
                extra={
                    "session_id": session.session_id,
                    "terminal_id": terminal_id,
                    "exit_code": resolved_exit_code,
                    "signal": signal,
                },
            )
            
            # Сгенерировать content для отправки клиенту и LLM
            exit_message = f"Terminal {terminal_id} exited with code {resolved_exit_code}"
            if signal:
                exit_message = f"Terminal {terminal_id} exited with signal {signal}"
            content_items = [
                {
                    "type": "text",
                    "text": f"{exit_message}\n\nOutput:\n{output}",
                }
            ]
            
            return ToolExecutionResult(
                success=resolved_exit_code == 0,
                output=output,
                metadata={
                    "terminal_id": terminal_id,
                    "exit_code": resolved_exit_code,
                    "signal": signal,
                },
                content=content_items,
            )
            
        except Exception as e:
            logger.error(
                "Ошибка при ожидании завершения терминала",
                extra={
                    "session_id": session.session_id,
                    "terminal_id": terminal_id,
                    "error": str(e),
                },
            )
            return ToolExecutionResult(
                success=False,
                error=f"Ошибка при ожидании завершения терминала: {str(e)}",
            )

    async def execute_release(
        self,
        session: SessionState,
        terminal_id: str,
    ) -> ToolExecutionResult:
        """Освободить терминал через ClientRPC.
        
        Args:
            session: Состояние сессии.
            terminal_id: ID терминала.
            
        Returns:
            ToolExecutionResult с результатом освобождения.
        """
        try:
            logger.debug(
                "Начало выполнения terminal/release",
                extra={
                    "session_id": session.session_id,
                    "terminal_id": terminal_id,
                },
            )
            
            # Вызов ClientRPC для освобождения терминала
            success = await self._bridge.release_terminal(
                session=session,
                terminal_id=terminal_id,
            )
            
            if not success:
                return ToolExecutionResult(
                    success=False,
                    error=f"Ошибка при освобождении терминала: {terminal_id}",
                )
            
            logger.debug(
                "Терминал успешно освобожден",
                extra={
                    "session_id": session.session_id,
                    "terminal_id": terminal_id,
                },
            )
            
            return ToolExecutionResult(
                success=True,
                output=f"Терминал {terminal_id} успешно освобожден",
                metadata={
                    "terminal_id": terminal_id,
                },
            )
            
        except Exception as e:
            logger.error(
                "Ошибка при освобождении терминала",
                extra={
                    "session_id": session.session_id,
                    "terminal_id": terminal_id,
                    "error": str(e),
                },
            )
            return ToolExecutionResult(
                success=False,
                error=f"Ошибка при освобождении терминала: {str(e)}",
            )
