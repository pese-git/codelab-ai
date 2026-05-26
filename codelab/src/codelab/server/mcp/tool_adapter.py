"""Адаптер MCP инструментов для интеграции с ToolRegistry.

Преобразует MCP инструменты в формат ToolDefinition для использования
в ACP сервере через ToolRegistry.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..tools.base import ToolDefinition, ToolExecutionResult
from .client import MCPClient, MCPToolCallError
from .models import MCPTool

logger = logging.getLogger(__name__)

# Маппинг префиксов имён инструментов на ACP ToolKind
_NAME_PREFIX_TO_KIND: list[tuple[str, str]] = [
    ("read", "read"),
    ("get", "read"),
    ("list", "read"),
    ("cat", "read"),
    ("show", "read"),
    ("fetch", "fetch"),
    ("download", "fetch"),
    ("http", "fetch"),
    ("web", "fetch"),
    ("url", "fetch"),
    ("search", "search"),
    ("find", "search"),
    ("grep", "search"),
    ("query", "search"),
    ("write", "edit"),
    ("create", "edit"),
    ("update", "edit"),
    ("edit", "edit"),
    ("modify", "edit"),
    ("append", "edit"),
    ("delete", "delete"),
    ("remove", "delete"),
    ("rm", "delete"),
    ("move", "move"),
    ("rename", "move"),
    ("mv", "move"),
    ("exec", "execute"),
    ("run", "execute"),
    ("shell", "execute"),
    ("command", "execute"),
    ("terminal", "execute"),
]


class MCPToolAdapter:
    """Адаптер для преобразования MCP инструментов в формат ToolRegistry.
    
    Создаёт ToolDefinition объекты из MCPTool с namespace-префиксом
    и генерирует executor-функции для вызова инструментов через MCP клиент.
    
    Attributes:
        server_id: Идентификатор MCP сервера (используется в namespace).
        client: MCP клиент для вызова инструментов.
    
    Example:
        >>> adapter = MCPToolAdapter("filesystem", mcp_client)
        >>> tools = adapter.adapt_tools(mcp_tools)
        >>> # tools[0].name == "mcp:filesystem:read_file"
    """
    
    # Namespace-префикс для MCP инструментов
    NAMESPACE_PREFIX = "mcp"
    
    def __init__(self, server_id: str, client: MCPClient) -> None:
        """Инициализация адаптера.
        
        Args:
            server_id: Уникальный идентификатор MCP сервера.
            client: MCP клиент для вызова инструментов.
        """
        self.server_id = server_id
        self.client = client
    
    def get_namespaced_name(self, tool_name: str) -> str:
        """Получить полное имя инструмента с namespace.
        
        Формат: mcp:{server_id}:{tool_name}
        
        Args:
            tool_name: Оригинальное имя инструмента.
        
        Returns:
            Имя с namespace-префиксом.
        """
        return f"{self.NAMESPACE_PREFIX}:{self.server_id}:{tool_name}"
    
    @staticmethod
    def parse_namespaced_name(namespaced_name: str) -> tuple[str, str, str] | None:
        """Разобрать namespaced имя на компоненты.
        
        Args:
            namespaced_name: Полное имя вида mcp:server_id:tool_name.
        
        Returns:
            Кортеж (prefix, server_id, tool_name) или None если формат неверный.
        """
        parts = namespaced_name.split(":", 2)
        if len(parts) != 3:
            return None
        return parts[0], parts[1], parts[2]
    
    @staticmethod
    def is_mcp_tool(tool_name: str) -> bool:
        """Проверить, является ли инструмент MCP инструментом.
        
        Args:
            tool_name: Имя инструмента.
        
        Returns:
            True если инструмент имеет MCP namespace.
        """
        return tool_name.startswith(f"{MCPToolAdapter.NAMESPACE_PREFIX}:")
    
    @staticmethod
    def _infer_kind(mcp_tool: MCPTool) -> str:
        """Вывести ACP ToolKind из MCP инструмента.

        Приоритет 1: MCP ToolAnnotations (readOnlyHint, destructiveHint).
        Приоритет 2: Эвристика по имени инструмента.
        Приоритет 3: Фоллбэк на "other".

        Args:
            mcp_tool: Определение MCP инструмента.

        Returns:
            Валидный ACP ToolKind.
        """
        # Приоритет 1: Аннотации MCP
        annotations = mcp_tool.annotations
        if annotations is not None:
            if annotations.read_only_hint is True:
                return "read"
            if annotations.destructive_hint is True:
                # destructive + delete/remover в имени -> delete, иначе edit
                name_lower = mcp_tool.name.lower()
                if any(prefix in name_lower for prefix in ("delete", "remove", "rm")):
                    return "delete"
                return "edit"

        # Приоритет 2: Эвристика по имени
        name_lower = mcp_tool.name.lower()
        for prefix, kind in _NAME_PREFIX_TO_KIND:
            if name_lower.startswith(prefix):
                return kind

        # Приоритет 3: Фоллбэк
        return "other"

    def mcp_tool_to_definition(self, mcp_tool: MCPTool) -> ToolDefinition:
        """Преобразовать MCPTool в ToolDefinition.

        Args:
            mcp_tool: Определение инструмента от MCP сервера.

        Returns:
            ToolDefinition для использования в ToolRegistry.
        """
        namespaced_name = self.get_namespaced_name(mcp_tool.name)

        # Преобразуем input_schema в параметры
        parameters = {
            "type": mcp_tool.input_schema.type,
            "properties": mcp_tool.input_schema.properties,
            "required": mcp_tool.input_schema.required,
        }

        # Добавляем дополнительные поля из input_schema если есть
        schema_dict = mcp_tool.input_schema.model_dump(exclude={"type", "properties", "required"})
        parameters.update(schema_dict)

        # Выводим kind из аннотаций или эвристики по имени
        inferred_kind = self._infer_kind(mcp_tool)

        # Добавляем тег MCP сервера в описание для идентификации LLM
        base_description = mcp_tool.description or mcp_tool.name
        description = f"[MCP:{self.server_id}] {base_description}"

        return ToolDefinition(
            name=namespaced_name,
            description=description,
            parameters=parameters,
            kind=inferred_kind,
            requires_permission=True,
        )
    
    def adapt_tools(self, mcp_tools: list[MCPTool]) -> list[ToolDefinition]:
        """Преобразовать список MCP инструментов в ToolDefinition.
        
        Args:
            mcp_tools: Список инструментов от MCP сервера.
        
        Returns:
            Список ToolDefinition для регистрации в ToolRegistry.
        """
        definitions: list[ToolDefinition] = []
        
        for mcp_tool in mcp_tools:
            definition = self.mcp_tool_to_definition(mcp_tool)
            definitions.append(definition)
            
            logger.debug(
                "Adapted MCP tool: %s -> %s",
                mcp_tool.name,
                definition.name
            )
        
        return definitions
    
    async def create_executor(self, original_tool_name: str) -> Any:
        """Создать executor-функцию для вызова MCP инструмента.
        
        Args:
            original_tool_name: Оригинальное имя инструмента (без namespace).
        
        Returns:
            Async callable для выполнения инструмента.
        """
        async def mcp_tool_executor(**kwargs: Any) -> ToolExecutionResult:
            """Executor для вызова MCP инструмента.
            
            Перенаправляет вызов к MCP серверу через клиент.
            """
            try:
                logger.debug(
                    "Calling MCP tool: %s on server %s with args: %s",
                    original_tool_name,
                    self.server_id,
                    kwargs
                )
                
                result = await self.client.call_tool(original_tool_name, kwargs)
                
                # Преобразуем MCP результат в ToolExecutionResult
                if result.is_error:
                    return ToolExecutionResult(
                        success=False,
                        error=result.get_text_content() or "MCP tool returned error",
                    )
                
                # Извлекаем текстовый контент
                text_output = result.get_text_content()
                
                return ToolExecutionResult(
                    success=True,
                    output=text_output,
                    content=result.content,  # Сохраняем оригинальный content
                )
                
            except MCPToolCallError as e:
                logger.error(
                    "MCP tool call failed: %s - %s",
                    original_tool_name,
                    str(e)
                )
                return ToolExecutionResult(
                    success=False,
                    error=f"MCP tool call failed: {e}",
                )
            except Exception as e:
                logger.exception(
                    "Unexpected error calling MCP tool: %s",
                    original_tool_name
                )
                return ToolExecutionResult(
                    success=False,
                    error=f"Unexpected error: {e}",
                )
        
        return mcp_tool_executor
    
    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolExecutionResult:
        """Вызвать MCP инструмент напрямую.
        
        Удобный метод для вызова инструмента без создания executor.
        
        Args:
            tool_name: Оригинальное имя инструмента (без namespace).
            arguments: Аргументы для вызова.
        
        Returns:
            Результат выполнения инструмента.
        """
        executor = await self.create_executor(tool_name)
        return await executor(**arguments)
