"""Интеграционные тесты MCP с реальным stdio сервером.

Тестирует полный цикл:
1. Запуск реального MCP сервера (test-sqlite-mcp)
2. Подключение через MCPClient
3. Initialize handshake
4. Получение списка инструментов (tools/list)
5. Проверка _infer_kind() на реальных аннотациях
6. Вызов инструментов (tools/call)
7. Проверка адаптера MCPToolAdapter
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from codelab.server.mcp.client import MCPClient, MCPClientState
from codelab.server.mcp.models import MCPServerConfig
from codelab.server.mcp.tool_adapter import MCPToolAdapter
from codelab.server.tools.base import ToolDefinition

# Путь к тестовому MCP серверу
_TEST_SERVER_PATH = Path(__file__).parent / "mcp_test_server.py"


def _get_python_executable() -> str:
    """Получить путь к Python интерпретатору."""
    return sys.executable


@pytest.fixture
def mcp_server_config() -> MCPServerConfig:
    """Конфигурация для тестового MCP сервера."""
    return MCPServerConfig(
        name="test-sqlite",
        command=_get_python_executable(),
        args=[str(_TEST_SERVER_PATH)],
        env=[{"PYTHONUNBUFFERED": "1"}],
    )


class TestMCPClientIntegration:
    """Интеграционные тесты MCPClient с реальным сервером."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, mcp_server_config: MCPServerConfig) -> None:
        """Полный цикл: connect → initialize → list_tools → call_tool → disconnect."""
        client = MCPClient(mcp_server_config)

        try:
            # 1. Подключение
            await client.connect()
            assert client.state == MCPClientState.CONNECTING

            # 2. Инициализация
            capabilities = await client.initialize()
            assert client.state == MCPClientState.READY
            assert client.is_ready is True
            assert capabilities.tools is not None

            # 3. Получение списка инструментов
            tools = await client.list_tools()
            assert len(tools) == 3

            tool_names = {t.name for t in tools}
            assert "query" in tool_names
            assert "exec" in tool_names
            assert "unknown_tool" in tool_names

            # 4. Проверка аннотаций
            query_tool = next(t for t in tools if t.name == "query")
            assert query_tool.annotations is not None
            assert query_tool.annotations.read_only_hint is True
            assert query_tool.annotations.destructive_hint is False

            exec_tool = next(t for t in tools if t.name == "exec")
            assert exec_tool.annotations is not None
            assert exec_tool.annotations.read_only_hint is False
            assert exec_tool.annotations.destructive_hint is True

            # 5. Вызов инструмента query
            result = await client.call_tool("query", {"sql": "SELECT * FROM users"})
            assert result.is_error is False
            text = result.get_text_content()
            assert "SELECT * FROM users" in text

            # 6. Вызов инструмента exec
            result = await client.call_tool("exec", {"sql": "INSERT INTO users VALUES (1, 'test')"})
            assert result.is_error is False
            text = result.get_text_content()
            assert "INSERT INTO users" in text

        finally:
            await client.disconnect()
            assert client.state == MCPClientState.CLOSED

    @pytest.mark.asyncio
    async def test_context_manager(self, mcp_server_config: MCPServerConfig) -> None:
        """Тест асинхронного контекстного менеджера."""
        async with MCPClient(mcp_server_config) as client:
            assert client.is_ready is True
            tools = await client.list_tools()
            assert len(tools) == 3

        assert client.state == MCPClientState.CLOSED


class TestMCPToolAdapterIntegration:
    """Интеграционные тесты MCPToolAdapter с реальным сервером."""

    @pytest.mark.asyncio
    async def test_adapt_tools_with_real_annotations(
        self, mcp_server_config: MCPServerConfig
    ) -> None:
        """Проверяет адаптацию инструментов с реальными аннотациями от сервера."""
        async with MCPClient(mcp_server_config) as client:
            mcp_tools = await client.list_tools()
            adapter = MCPToolAdapter("test-sqlite", client)
            tool_defs = adapter.adapt_tools(mcp_tools)

            assert len(tool_defs) == 3

            # Проверяем namespaced имена
            names = {td.name for td in tool_defs}
            assert "mcp:test-sqlite:query" in names
            assert "mcp:test-sqlite:exec" in names
            assert "mcp:test-sqlite:unknown_tool" in names

            # Проверяем inferred kind из аннотаций
            query_def = next(td for td in tool_defs if td.name.endswith(":query"))
            assert query_def.kind == "read"  # readOnlyHint=True

            exec_def = next(td for td in tool_defs if td.name.endswith(":exec"))
            assert exec_def.kind == "edit"  # destructiveHint=True + не-delete имя

            unknown_def = next(td for td in tool_defs if td.name.endswith(":unknown_tool"))
            assert unknown_def.kind == "other"  # Нет аннотаций, имя не маппится

    @pytest.mark.asyncio
    async def test_all_kinds_are_valid_acp_kinds(
        self, mcp_server_config: MCPServerConfig
    ) -> None:
        """Проверяет что все inferred kind — валидные ACP ToolKind."""
        valid_kinds = {
            "read", "edit", "delete", "move", "search",
            "execute", "think", "fetch", "switch_mode", "other",
        }

        async with MCPClient(mcp_server_config) as client:
            mcp_tools = await client.list_tools()
            adapter = MCPToolAdapter("test-sqlite", client)
            tool_defs = adapter.adapt_tools(mcp_tools)

            for td in tool_defs:
                assert td.kind in valid_kinds, f"Invalid kind '{td.kind}' for tool {td.name}"

    @pytest.mark.asyncio
    async def test_tool_definition_structure(
        self, mcp_server_config: MCPServerConfig
    ) -> None:
        """Проверяет структуру ToolDefinition после адаптации."""
        async with MCPClient(mcp_server_config) as client:
            mcp_tools = await client.list_tools()
            adapter = MCPToolAdapter("test-sqlite", client)
            tool_defs = adapter.adapt_tools(mcp_tools)

            query_def = next(td for td in tool_defs if td.name.endswith(":query"))

            assert isinstance(query_def, ToolDefinition)
            assert query_def.name == "mcp:test-sqlite:query"
            assert query_def.description == "[MCP:test-sqlite] Execute a SQL SELECT query (read-only)"
            assert query_def.parameters["type"] == "object"
            assert "sql" in query_def.parameters["properties"]
            assert query_def.requires_permission is True


class TestMCPKindInferenceRealWorld:
    """Тесты инференса kind на реальных MCP инструментах."""

    @pytest.mark.asyncio
    async def test_query_tool_kind_from_annotations(
        self, mcp_server_config: MCPServerConfig
    ) -> None:
        """Проверяет что query получает kind='read' из readOnlyHint."""
        async with MCPClient(mcp_server_config) as client:
            tools = await client.list_tools()
            adapter = MCPToolAdapter("test-sqlite", client)

            query_tool = next(t for t in tools if t.name == "query")
            kind = adapter._infer_kind(query_tool)

            assert kind == "read"

    @pytest.mark.asyncio
    async def test_exec_tool_kind_from_annotations(
        self, mcp_server_config: MCPServerConfig
    ) -> None:
        """Проверяет что exec получает kind='edit' из destructiveHint."""
        async with MCPClient(mcp_server_config) as client:
            tools = await client.list_tools()
            adapter = MCPToolAdapter("test-sqlite", client)

            exec_tool = next(t for t in tools if t.name == "exec")
            kind = adapter._infer_kind(exec_tool)

            assert kind == "edit"

    @pytest.mark.asyncio
    async def test_unknown_tool_kind_fallback(
        self, mcp_server_config: MCPServerConfig
    ) -> None:
        """Проверяет fallback на 'other' для неизвестного инструмента."""
        async with MCPClient(mcp_server_config) as client:
            tools = await client.list_tools()
            adapter = MCPToolAdapter("test-sqlite", client)

            unknown_tool = next(t for t in tools if t.name == "unknown_tool")
            kind = adapter._infer_kind(unknown_tool)

            assert kind == "other"
