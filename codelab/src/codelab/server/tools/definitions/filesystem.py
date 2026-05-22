"""Определения для файловых инструментов (fs/*)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from codelab.server.tools.base import ToolDefinition

if TYPE_CHECKING:
    from codelab.server.protocol.state import SessionState
    from codelab.server.tools.base import ToolRegistry
    from codelab.server.tools.executors.filesystem_executor import FileSystemToolExecutor


def _normalize_path(cwd: str, path: str) -> str:
    """Нормализует путь относительно cwd.
    
    Если путь уже абсолютный — возвращает как есть.
    Если относительный — присоединяет к cwd.
    
    Args:
        cwd: Текущая рабочая директория сессии.
        path: Путь к файлу (абсолютный или относительный).
        
    Returns:
        Нормализованный абсолютный путь.
    """
    p = Path(path)
    if p.is_absolute():
        return path
    return str(Path(cwd) / p)


class FileSystemToolDefinitions:
    """Фабрика для создания определений файловых инструментов.
    
    Поддерживает:
    - fs/read_text_file: Чтение текстовых файлов
    - fs/write_text_file: Запись текстовых файлов с diff tracking
    """

    @staticmethod
    def read_text_file() -> ToolDefinition:
        """Создать определение для инструмента fs/read_text_file.
        
        Позволяет LLM читать содержимое текстовых файлов в окружении клиента
        с поддержкой partial reads (line и limit).
        
        Returns:
            ToolDefinition для регистрации в реестре.
        """
        return ToolDefinition(
            name="fs/read_text_file",
            description=(
                "Read text file content from client filesystem. "
                "Supports line numbers (1-based) and limits for partial reads."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative file path",
                    },
                    "line": {
                        "type": "integer",
                        "description": "Starting line number (1-based, optional)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of lines to read (optional)",
                    },
                    "operation": {
                        "type": "string",
                        "description": "Internal: operation type (read)",
                    },
                },
                "required": ["path"],
            },
            kind="read",
            requires_permission=True,
        )

    @staticmethod
    def write_text_file() -> ToolDefinition:
        """Создать определение для инструмента fs/write_text_file.
        
        Позволяет LLM создавать и обновлять текстовые файлы в окружении клиента
        с автоматическим отслеживанием изменений (diff).
        
        Returns:
            ToolDefinition для регистрации в реестре.
        """
        return ToolDefinition(
            name="fs/write_text_file",
            description=(
                "Write or update text file in client filesystem. "
                "Supports diff generation for tracking changes."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative file path",
                    },
                    "content": {
                        "type": "string",
                        "description": "File content to write",
                    },
                    "operation": {
                        "type": "string",
                        "description": "Internal: operation type (write)",
                    },
                },
                "required": ["path", "content"],
            },
            kind="edit",
            requires_permission=True,
        )

    @staticmethod
    def register_all(
        tool_registry: ToolRegistry,
        executor: FileSystemToolExecutor,
    ) -> None:
        """Зарегистрировать все файловые инструменты в реестре.
        
        Регистрирует:
        - fs/read_text_file с executor для чтения
        - fs/write_text_file с executor для записи
        
        Args:
            tool_registry: Реестр инструментов для регистрации
            executor: Executor для выполнения операций с файлами
        """
        # Создать обработчик для чтения файлов
        async def read_handler(session: SessionState, **arguments: Any) -> Any:
            """Обработчик для fs/read_text_file."""
            # Добавить тип операции в аргументы
            arguments["operation"] = "read"
            # Нормализовать путь относительно session.cwd
            if "path" in arguments and session.cwd:
                arguments["path"] = _normalize_path(session.cwd, arguments["path"])
            return await executor.execute(session, arguments)

        # Создать обработчик для записи файлов
        async def write_handler(session: SessionState, **arguments: Any) -> Any:
            """Обработчик для fs/write_text_file."""
            # Добавить тип операции в аргументы
            arguments["operation"] = "write"
            # Нормализовать путь относительно session.cwd
            if "path" in arguments and session.cwd:
                arguments["path"] = _normalize_path(session.cwd, arguments["path"])
            return await executor.execute(session, arguments)

        # Зарегистрировать инструменты в реестре
        tool_registry.register(
            FileSystemToolDefinitions.read_text_file(),
            read_handler,
        )
        tool_registry.register(
            FileSystemToolDefinitions.write_text_file(),
            write_handler,
        )
