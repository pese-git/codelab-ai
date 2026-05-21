"""Определения для терминальных инструментов (terminal/*)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from codelab.server.tools.base import ToolDefinition

if TYPE_CHECKING:
    from codelab.server.protocol.state import SessionState
    from codelab.server.tools.base import ToolRegistry
    from codelab.server.tools.executors.terminal_executor import TerminalToolExecutor


class TerminalToolDefinitions:
    """Фабрика для создания определений терминальных инструментов.
    
    Поддерживает:
    - terminal/create: Создание терминала и запуск команды
    - terminal/wait_for_exit: Ожидание завершения процесса
    - terminal/release: Освобождение терминала
    """

    @staticmethod
    def create() -> ToolDefinition:
        """Создать определение для инструмента terminal/create.
        
        Позволяет LLM создавать терминалы и запускать команды
        в окружении клиента с поддержкой параметров запуска.
        
        Returns:
            ToolDefinition для регистрации в реестре.
        """
        return ToolDefinition(
            name="terminal/create",
            description=(
                "Create a new terminal and execute a command. "
                "Returns terminal ID for subsequent operations like wait_for_exit and release."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Command to execute (e.g., 'npm', 'python')",
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Command arguments (optional)",
                    },
                    "env": {
                        "type": "object",
                        "description": "Environment variables to set (optional)",
                        "additionalProperties": {"type": "string"},
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Working directory for the command (optional)",
                    },
                    "output_byte_limit": {
                        "type": "integer",
                        "description": "Maximum output bytes to retain (optional)",
                    },
                    "operation": {
                        "type": "string",
                        "description": "Internal: operation type (create)",
                    },
                },
                "required": ["command"],
            },
            kind="execute",
            requires_permission=True,
        )

    @staticmethod
    def wait_for_exit() -> ToolDefinition:
        """Создать определение для инструмента terminal/wait_for_exit.
        
        Позволяет LLM ожидать завершения выполнения команды в терминале
        и получить exit code вместе с output.
        
        Returns:
            ToolDefinition для регистрации в реестре.
        """
        return ToolDefinition(
            name="terminal/wait_for_exit",
            description=(
                "Wait for a terminal to complete execution and retrieve the exit code. "
                "The terminal output is retrieved automatically. "
                "Use after terminal/create to get the result of a long-running command."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "terminal_id": {
                        "type": "string",
                        "description": "Terminal ID returned by execute_command",
                    },
                    "operation": {
                        "type": "string",
                        "description": "Internal: operation type (wait_for_exit)",
                    },
                },
                "required": ["terminal_id"],
            },
            kind="read",
            requires_permission=False,
        )

    @staticmethod
    def release() -> ToolDefinition:
        """Создать определение для инструмента terminal/release.
        
        Позволяет LLM освобождать ресурсы терминала после завершения работы.
        
        Returns:
            ToolDefinition для регистрации в реестре.
        """
        return ToolDefinition(
            name="terminal/release",
            description=(
                "Release terminal resources and clean up. "
                "Should be called after wait_for_exit to free up resources."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "terminal_id": {
                        "type": "string",
                        "description": "Terminal ID returned by execute_command",
                    },
                    "operation": {
                        "type": "string",
                        "description": "Internal: operation type (release)",
                    },
                },
                "required": ["terminal_id"],
            },
            kind="delete",
            requires_permission=False,
        )

    @staticmethod
    def register_all(
        tool_registry: ToolRegistry,
        executor: TerminalToolExecutor,
    ) -> None:
        """Зарегистрировать все терминальные инструменты в реестре.
        
        Регистрирует:
        - terminal/execute_command (create) для запуска команды
        - terminal/wait_for_exit для ожидания завершения
        - terminal/release_terminal (release) для освобождения ресурсов
        
        Args:
            tool_registry: Реестр инструментов для регистрации
            executor: Executor для выполнения терминальных операций
        """
        # Создать обработчик для создания терминала и запуска команды
        async def create_handler(session: SessionState, **arguments: Any) -> Any:
            """Обработчик для terminal/execute_command (create)."""
            # Добавить тип операции в аргументы
            arguments["operation"] = "create"
            return await executor.execute(session, arguments)

        # Создать обработчик для ожидания завершения
        async def wait_for_exit_handler(session: SessionState, **arguments: Any) -> Any:
            """Обработчик для terminal/wait_for_exit."""
            # Добавить тип операции в аргументы
            arguments["operation"] = "wait_for_exit"
            return await executor.execute(session, arguments)

        # Создать обработчик для освобождения терминала
        async def release_handler(session: SessionState, **arguments: Any) -> Any:
            """Обработчик для terminal/release_terminal (release)."""
            # Добавить тип операции в аргументы
            arguments["operation"] = "release"
            return await executor.execute(session, arguments)

        # Зарегистрировать инструменты в реестре
        tool_registry.register(
            TerminalToolDefinitions.create(),
            create_handler,
        )
        tool_registry.register(
            TerminalToolDefinitions.wait_for_exit(),
            wait_for_exit_handler,
        )
        tool_registry.register(
            TerminalToolDefinitions.release(),
            release_handler,
        )
