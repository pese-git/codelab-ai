"""Простая реализация реестра инструментов для системы tools."""

import inspect
from collections.abc import Callable
from typing import Any

import structlog

from codelab.server.tools.base import ToolDefinition, ToolExecutionResult, ToolRegistry
from codelab.server.tools.mapping import acp_name_to_llm_name, llm_name_to_acp_name

# Используем structlog для структурированного логирования
logger = structlog.get_logger()


class SimpleToolRegistry(ToolRegistry):
    """Простой реестр инструментов с хранением в памяти.

    Хранит определения инструментов и их обработчики (handlers).
    Позволяет регистрировать, получать и выполнять инструменты.
    """

    def __init__(self) -> None:
        """Инициализация реестра."""
        # Словарь для хранения определений инструментов
        self._tools: dict[str, ToolDefinition] = {}
        # Словарь для хранения обработчиков инструментов
        self._handlers: dict[str, Callable] = {}

    def register(
        self,
        tool: ToolDefinition,
        handler: Callable,
    ) -> None:
        """Регистрация инструмента и его обработчика.

        Args:
            tool: Определение инструмента (ToolDefinition)
            handler: Callable обработчик инструмента

        Raises:
            ValueError: Если имя инструмента пустое
        """
        # Проверка, что имя инструмента не пустое
        if not tool.name or not tool.name.strip():
            raise ValueError("Имя инструмента не может быть пустым")

        # Регистрация инструмента и его обработчика
        self._tools[tool.name] = tool
        self._handlers[tool.name] = handler

    def get(self, name: str) -> ToolDefinition | None:
        """Получение определения инструмента по имени.

        Args:
            name: Имя инструмента

        Returns:
            Определение инструмента или None, если не найден
        """
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        """Получение списка всех зарегистрированных инструментов.

        Returns:
            Список определений инструментов
        """
        return list(self._tools.values())

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> ToolExecutionResult:
        """Выполнение инструмента по имени с переданными аргументами.

        Args:
            name: Имя инструмента
            arguments: Словарь аргументов для обработчика

        Returns:
            Результат выполнения (ToolExecutionResult)

        Raises:
            ValueError: Если инструмент не найден
        """
        # Проверка существования инструмента
        if name not in self._tools:
            return ToolExecutionResult(
                success=False,
                error=f"Инструмент '{name}' не найден в реестре",
            )

        # Получение обработчика
        handler = self._handlers[name]

        try:
            # Выполнение обработчика с аргументами
            output = handler(**arguments)

            # Преобразование вывода в строку если необходимо
            output_str = str(output) if output is not None else None

            return ToolExecutionResult(
                success=True,
                output=output_str,
            )
        except Exception as exc:
            # Обработка исключений при выполнении
            error_msg = f"Ошибка при выполнении инструмента '{name}': {str(exc)}"
            return ToolExecutionResult(
                success=False,
                error=error_msg,
            )

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        kind: str,
        executor: Callable,
        requires_permission: bool = True,
    ) -> None:
        """Регистрация инструмента через интерфейс ToolRegistry."""
        tool = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            kind=kind,
            requires_permission=requires_permission,
        )
        self.register(tool, executor)

    def get_available_tools(
        self,
        session_id: str,
        include_permission_required: bool = True,
    ) -> list[ToolDefinition]:
        """Получить доступные инструменты для сессии.

        В упрощенной реализации возвращает все инструменты.
        """
        # Для простого реестра - возвращаем все инструменты
        tools = list(self._tools.values())
        if not include_permission_required:
            tools = [t for t in tools if not t.requires_permission]
        return tools

    def to_llm_tools(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        """Преобразовать определения инструментов для LLM.

        Применяет маппинг имён: ACP имена (с `/`) конвертируются
        в LLM-совместимые имена (с `_`).
        """
        return [
            {
                "name": acp_name_to_llm_name(tool.name),
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in tools
        ]

    async def execute_tool(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        session: Any = None,
    ) -> ToolExecutionResult:
        """Выполнить инструмент асинхронно с поддержкой async executors.

        Поддерживает как синхронные, так и асинхронные executors.
        Metadata из ToolExecutionResult сохраняется в результате.

        Args:
            session_id: ID сессии для контекста выполнения
            tool_name: Имя инструмента (может быть в LLM формате с `_`)
            arguments: Аргументы для выполнения
            session: Опциональный объект SessionState для executors (опционально)

        Returns:
            ToolExecutionResult с успехом/ошибкой и metadata если доступен
        """
        # Конвертируем LLM имя обратно в ACP формат для lookup в registry
        acp_tool_name = llm_name_to_acp_name(tool_name)

        logger.debug(
            "tool registry execute_tool called",
            session_id=session_id,
            tool_name=tool_name,
            acp_tool_name=acp_tool_name,
            arguments=arguments,
            has_session=session is not None,
        )
        
        # Проверка существования инструмента (по ACP имени)
        if acp_tool_name not in self._tools:
            logger.error(
                "tool not found in registry",
                tool_name=tool_name,
                acp_tool_name=acp_tool_name,
                registered_tools=list(self._tools.keys()),
            )
            return ToolExecutionResult(
                success=False,
                error=f"Инструмент '{acp_tool_name}' не найден в реестре",
            )

        # Получение обработчика
        handler = self._handlers[acp_tool_name]
        is_async = inspect.iscoroutinefunction(handler)
        
        logger.debug(
            "tool handler found",
            tool_name=tool_name,
            acp_tool_name=acp_tool_name,
            is_async=is_async,
            handler_type=type(handler).__name__,
        )

        try:
            # Проверяем является ли обработчик асинхронным
            if is_async:
                logger.debug(
                    "executing async tool handler",
                    tool_name=tool_name,
                    acp_tool_name=acp_tool_name,
                )
                # Для async executors вызываем await
                # Если session доступен, передаём его в handler
                if session is not None and "session" in inspect.signature(handler).parameters:
                    result = await handler(session=session, **arguments)
                else:
                    result = await handler(**arguments)
            else:
                logger.debug(
                    "executing sync tool handler",
                    tool_name=tool_name,
                    acp_tool_name=acp_tool_name,
                )
                # Для синхронных функций вызываем напрямую
                output = handler(**arguments)
                result = ToolExecutionResult(
                    success=True,
                    output=str(output) if output is not None else None,
                )

            logger.info(
                "tool handler execution completed",
                tool_name=tool_name,
                acp_tool_name=acp_tool_name,
                success=result.success,
                has_output=bool(result.output),
                has_error=bool(result.error),
                has_metadata=bool(result.metadata),
            )
            
            # Возвращаем результат с сохранением metadata
            return result

        except Exception as exc:
            # Обработка исключений при выполнении
            logger.error(
                "tool handler execution failed with exception",
                tool_name=tool_name,
                acp_tool_name=acp_tool_name,
                error=str(exc),
                exc_info=True,
            )
            error_msg = f"Ошибка при выполнении инструмента '{acp_tool_name}': {str(exc)}"
            return ToolExecutionResult(
                success=False,
                error=error_msg,
            )
