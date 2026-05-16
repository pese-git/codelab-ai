"""Тесты для MCP (Model Context Protocol) модуля.

Тестирует:
- MCPClient — клиент для взаимодействия с MCP серверами (mock транспорт)
- MCPToolAdapter — преобразование MCP инструментов в ToolDefinition
- MCPManager — управление несколькими MCP серверами

Примечание: Методы session/mcp/* НЕ входят в официальную спецификацию ACP протокола.
MCP серверы подключаются через параметр mcpServers при session/new и session/load.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from codelab.server.mcp.client import MCPClient, MCPClientError, MCPClientState
from codelab.server.mcp.manager import (
    MCPManager,
    MCPServerAlreadyExistsError,
    MCPServerNotFoundError,
)
from codelab.server.mcp.models import (
    MCPCapabilities,
    MCPServerConfig,
    MCPTool,
    MCPToolInputSchema,
)
from codelab.server.mcp.tool_adapter import MCPToolAdapter
from codelab.server.tools.base import ToolDefinition

# ===== Фикстуры =====


@pytest.fixture
def mcp_server_config() -> MCPServerConfig:
    """Создаёт тестовую конфигурацию MCP сервера."""
    return MCPServerConfig(
        name="test-server",
        command="test-mcp-server",
        args=["--stdio"],
        env=[{"name": "TEST_VAR", "value": "test_value"}],
    )


@pytest.fixture
def sample_mcp_tools() -> list[MCPTool]:
    """Создаёт список тестовых MCP инструментов."""
    return [
        MCPTool(
            name="read_file",
            description="Читает содержимое файла",
            input_schema=MCPToolInputSchema(
                type="object",
                properties={
                    "path": {
                        "type": "string",
                        "description": "Путь к файлу",
                    }
                },
                required=["path"],
            ),
        ),
        MCPTool(
            name="write_file",
            description="Записывает содержимое в файл",
            input_schema=MCPToolInputSchema(
                type="object",
                properties={
                    "path": {
                        "type": "string",
                        "description": "Путь к файлу",
                    },
                    "content": {
                        "type": "string",
                        "description": "Содержимое для записи",
                    },
                },
                required=["path", "content"],
            ),
        ),
    ]


@pytest.fixture
def mock_transport() -> MagicMock:
    """Создаёт mock транспорта для MCP клиента."""
    transport = MagicMock()
    transport.is_running = True
    transport.start = AsyncMock()
    transport.close = AsyncMock()
    transport.send_request = AsyncMock()
    transport.send_notification = AsyncMock()
    return transport


# ===== Тесты MCPToolAdapter =====


class TestMCPToolAdapter:
    """Тесты для MCPToolAdapter — преобразование инструментов."""

    def test_get_namespaced_name(self, mcp_server_config: MCPServerConfig) -> None:
        """Проверяет формирование namespaced имени инструмента."""
        # Создаём mock клиент для адаптера
        mock_client = MagicMock()
        adapter = MCPToolAdapter("test-server", mock_client)

        # Проверяем формат namespace
        namespaced = adapter.get_namespaced_name("read_file")
        assert namespaced == "mcp:test-server:read_file"

    def test_parse_namespaced_name_valid(self) -> None:
        """Проверяет парсинг корректного namespaced имени."""
        result = MCPToolAdapter.parse_namespaced_name("mcp:fs-server:read_file")
        
        assert result is not None
        assert result == ("mcp", "fs-server", "read_file")

    def test_parse_namespaced_name_invalid(self) -> None:
        """Проверяет парсинг некорректного namespaced имени."""
        # Неверный формат — слишком мало частей
        assert MCPToolAdapter.parse_namespaced_name("mcp:read_file") is None
        # Неверный формат — без разделителей
        assert MCPToolAdapter.parse_namespaced_name("read_file") is None

    def test_is_mcp_tool(self) -> None:
        """Проверяет определение MCP инструмента по имени."""
        assert MCPToolAdapter.is_mcp_tool("mcp:server:tool") is True
        assert MCPToolAdapter.is_mcp_tool("mcp:") is True
        assert MCPToolAdapter.is_mcp_tool("fs_read_file") is False
        assert MCPToolAdapter.is_mcp_tool("terminal_execute") is False

    def test_mcp_tool_to_definition(self, sample_mcp_tools: list[MCPTool]) -> None:
        """Проверяет преобразование MCPTool в ToolDefinition."""
        mock_client = MagicMock()
        adapter = MCPToolAdapter("fs-server", mock_client)

        tool_def = adapter.mcp_tool_to_definition(sample_mcp_tools[0])

        # Проверяем преобразованное определение
        assert isinstance(tool_def, ToolDefinition)
        assert tool_def.name == "mcp:fs-server:read_file"
        assert tool_def.description == "Читает содержимое файла"
        assert tool_def.kind == "mcp"  # MCP инструменты имеют kind="mcp"
        assert tool_def.requires_permission is True

    def test_adapt_tools(self, sample_mcp_tools: list[MCPTool]) -> None:
        """Проверяет преобразование списка MCPTool в ToolDefinition."""
        mock_client = MagicMock()
        adapter = MCPToolAdapter("fs-server", mock_client)

        tool_defs = adapter.adapt_tools(sample_mcp_tools)

        # Проверяем количество инструментов
        assert len(tool_defs) == 2
        
        # Проверяем namespaced имена
        names = [td.name for td in tool_defs]
        assert "mcp:fs-server:read_file" in names
        assert "mcp:fs-server:write_file" in names


# ===== Тесты MCPClient =====


class TestMCPClient:
    """Тесты для MCPClient — клиент MCP серверов с mock транспортом."""

    def test_initial_state(self, mcp_server_config: MCPServerConfig) -> None:
        """Проверяет начальное состояние клиента."""
        client = MCPClient(mcp_server_config)

        assert client.state == MCPClientState.CREATED
        assert client.server_name == "test-server"
        assert client.is_ready is False
        assert client.capabilities is None
        assert client.tools == []

    @pytest.mark.asyncio
    async def test_connect_starts_transport(
        self,
        mcp_server_config: MCPServerConfig,
        mock_transport: MagicMock,
    ) -> None:
        """Проверяет, что connect запускает транспорт."""
        client = MCPClient(mcp_server_config)

        # Подменяем создание транспорта
        with patch(
            "codelab.server.mcp.client.StdioTransport",
            return_value=mock_transport,
        ):
            await client.connect()

        # Проверяем, что транспорт запущен
        mock_transport.start.assert_called_once()
        assert client.state == MCPClientState.CONNECTING

    @pytest.mark.asyncio
    async def test_connect_in_wrong_state_raises_error(
        self,
        mcp_server_config: MCPServerConfig,
        mock_transport: MagicMock,
    ) -> None:
        """Проверяет ошибку при повторном connect."""
        client = MCPClient(mcp_server_config)
        
        # Первый connect
        with patch(
            "codelab.server.mcp.client.StdioTransport",
            return_value=mock_transport,
        ):
            await client.connect()
        
        # Повторный connect должен вызвать ошибку
        with pytest.raises(MCPClientError, match="Cannot connect"):
            await client.connect()

    @pytest.mark.asyncio
    async def test_initialize_success(
        self,
        mcp_server_config: MCPServerConfig,
        mock_transport: MagicMock,
    ) -> None:
        """Проверяет успешную инициализацию."""
        client = MCPClient(mcp_server_config)

        # Mock ответ initialize от сервера
        mock_transport.send_request.return_value = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "test-mcp", "version": "1.0.0"},
        }

        with patch(
            "codelab.server.mcp.client.StdioTransport",
            return_value=mock_transport,
        ):
            await client.connect()
            capabilities = await client.initialize()

        # Проверяем результат
        assert client.state == MCPClientState.READY
        assert client.is_ready is True
        assert capabilities is not None
        
        # Проверяем, что отправлен notifications/initialized
        mock_transport.send_notification.assert_called_once_with(
            method="notifications/initialized"
        )

    @pytest.mark.asyncio
    async def test_disconnect_closes_transport(
        self,
        mcp_server_config: MCPServerConfig,
        mock_transport: MagicMock,
    ) -> None:
        """Проверяет, что disconnect закрывает транспорт."""
        client = MCPClient(mcp_server_config)

        # Mock initialize
        mock_transport.send_request.return_value = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {"name": "test-mcp", "version": "1.0.0"},
        }

        with patch(
            "codelab.server.mcp.client.StdioTransport",
            return_value=mock_transport,
        ):
            await client.connect()
            await client.initialize()
            await client.disconnect()

        # Проверяем закрытие транспорта
        mock_transport.close.assert_called_once()
        assert client.state == MCPClientState.CLOSED


# ===== Тесты MCPManager =====


class TestMCPManager:
    """Тесты для MCPManager — управление MCP серверами."""

    def test_initial_state(self) -> None:
        """Проверяет начальное состояние менеджера."""
        manager = MCPManager("session_123")

        assert manager.session_id == "session_123"
        assert manager.server_count == 0
        assert manager.server_ids == []

    def test_has_server(self) -> None:
        """Проверяет проверку наличия сервера."""
        manager = MCPManager("session_123")
        
        assert manager.has_server("non-existent") is False

    @pytest.mark.asyncio
    async def test_add_server_success(
        self,
        mcp_server_config: MCPServerConfig,
        sample_mcp_tools: list[MCPTool],
    ) -> None:
        """Проверяет успешное добавление MCP сервера."""
        manager = MCPManager("session_123")

        # Создаём mock клиент
        mock_client = AsyncMock()
        mock_client.state = MCPClientState.READY
        mock_client.list_tools = AsyncMock(return_value=sample_mcp_tools)

        with patch(
            "codelab.server.mcp.manager.MCPClient",
            return_value=mock_client,
        ):
            tools = await manager.add_server(mcp_server_config)

        # Проверяем результат
        assert manager.server_count == 1
        assert manager.has_server("test-server") is True
        assert len(tools) == 2

    @pytest.mark.asyncio
    async def test_add_server_already_exists(
        self,
        mcp_server_config: MCPServerConfig,
        sample_mcp_tools: list[MCPTool],
    ) -> None:
        """Проверяет ошибку при добавлении существующего сервера."""
        manager = MCPManager("session_123")

        mock_client = AsyncMock()
        mock_client.state = MCPClientState.READY
        mock_client.list_tools = AsyncMock(return_value=sample_mcp_tools)

        with patch(
            "codelab.server.mcp.manager.MCPClient",
            return_value=mock_client,
        ):
            await manager.add_server(mcp_server_config)

            # Повторное добавление должно вызвать ошибку
            with pytest.raises(MCPServerAlreadyExistsError):
                await manager.add_server(mcp_server_config)

    @pytest.mark.asyncio
    async def test_remove_server_success(
        self,
        mcp_server_config: MCPServerConfig,
        sample_mcp_tools: list[MCPTool],
    ) -> None:
        """Проверяет успешное удаление MCP сервера."""
        manager = MCPManager("session_123")

        mock_client = AsyncMock()
        mock_client.state = MCPClientState.READY
        mock_client.list_tools = AsyncMock(return_value=sample_mcp_tools)

        with patch(
            "codelab.server.mcp.manager.MCPClient",
            return_value=mock_client,
        ):
            await manager.add_server(mcp_server_config)
            
            # Удаляем сервер
            await manager.remove_server("test-server")

        # Проверяем результат
        assert manager.server_count == 0
        assert manager.has_server("test-server") is False

    @pytest.mark.asyncio
    async def test_remove_server_not_found(self) -> None:
        """Проверяет ошибку при удалении несуществующего сервера."""
        manager = MCPManager("session_123")

        with pytest.raises(MCPServerNotFoundError):
            await manager.remove_server("non-existent")

    @pytest.mark.asyncio
    async def test_get_all_tools(
        self,
        mcp_server_config: MCPServerConfig,
        sample_mcp_tools: list[MCPTool],
    ) -> None:
        """Проверяет получение всех инструментов."""
        manager = MCPManager("session_123")

        mock_client = AsyncMock()
        mock_client.state = MCPClientState.READY
        mock_client.list_tools = AsyncMock(return_value=sample_mcp_tools)

        with patch(
            "codelab.server.mcp.manager.MCPClient",
            return_value=mock_client,
        ):
            await manager.add_server(mcp_server_config)

        # Получаем все инструменты
        all_tools = manager.get_all_tools()

        assert len(all_tools) == 2
        assert all(isinstance(t, ToolDefinition) for t in all_tools)

    @pytest.mark.asyncio
    async def test_shutdown_closes_all_servers(
        self,
        mcp_server_config: MCPServerConfig,
        sample_mcp_tools: list[MCPTool],
    ) -> None:
        """Проверяет, что shutdown закрывает все серверы."""
        manager = MCPManager("session_123")

        mock_client = AsyncMock()
        mock_client.state = MCPClientState.READY
        mock_client.list_tools = AsyncMock(return_value=sample_mcp_tools)

        with patch(
            "codelab.server.mcp.manager.MCPClient",
            return_value=mock_client,
        ):
            await manager.add_server(mcp_server_config)
            await manager.shutdown()

        # Проверяем закрытие
        mock_client.disconnect.assert_called_once()
        assert manager.server_count == 0


# ===== Тесты обработчиков протокола =====

# ===== Тесты моделей =====


class TestMCPModels:
    """Тесты для моделей данных MCP."""

    def test_mcp_server_config_basic(self) -> None:
        """Проверяет создание базовой конфигурации сервера."""
        config = MCPServerConfig(
            name="test",
            command="test-cmd",
        )

        assert config.name == "test"
        assert config.command == "test-cmd"
        assert config.args == []
        assert config.env == []

    def test_mcp_server_config_with_env(self) -> None:
        """Проверяет конфигурацию с переменными окружения."""
        config = MCPServerConfig(
            name="test",
            command="test-cmd",
            env=[
                {"name": "VAR1", "value": "val1"},
                {"name": "VAR2", "value": "val2"},
            ],
        )

        env_dict = config.get_env_dict()
        assert env_dict == {"VAR1": "val1", "VAR2": "val2"}

    def test_mcp_tool_with_schema(self) -> None:
        """Проверяет создание инструмента со схемой."""
        tool = MCPTool(
            name="read_file",
            description="Reads a file",
            input_schema=MCPToolInputSchema(
                type="object",
                properties={"path": {"type": "string"}},
                required=["path"],
            ),
        )

        assert tool.name == "read_file"
        assert tool.description == "Reads a file"
        assert tool.input_schema.properties == {"path": {"type": "string"}}
        assert tool.input_schema.required == ["path"]

    def test_mcp_capabilities(self) -> None:
        """Проверяет создание capabilities."""
        caps = MCPCapabilities(
            tools={"listChanged": True},
            resources=None,
        )

        assert caps.tools == {"listChanged": True}
        assert caps.resources is None


# ===== Тесты интеграции с session/new =====


class TestSessionMCPIntegration:
    """Тесты интеграции MCP с методами session/new и session/load."""

    @pytest.mark.asyncio
    async def test_session_new_with_mcp_servers_initializes_mcp_manager(
        self,
    ) -> None:
        """Проверяет, что session/new с mcpServers инициализирует MCPManager.
        
        При передаче mcpServers в session/new, протокол должен:
        1. Создать MCPManager для сессии
        2. Попытаться подключиться к каждому серверу (graceful degradation при ошибках)
        3. Сохранить MCPManager в session_state.mcp_manager
        """
        from codelab.server.messages import ACPMessage
        from codelab.server.protocol.core import ACPProtocol
        
        # Создаём протокол
        protocol = ACPProtocol(require_auth=False)
        
        # Инициализируем протокол
        init_msg = ACPMessage.request(
            request_id=0,
            method="initialize",
            params={
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fsRead": True,
                    "fsWrite": True,
                    "terminal": True,
                },
            },
        )
        await protocol.handle(init_msg)
        
        # Создаём сессию с MCP серверами (намеренно используем несуществующий сервер
        # для проверки graceful degradation)
        session_new_msg = ACPMessage.request(
            request_id=1,
            method="session/new",
            params={
                "cwd": "/tmp",
                "mcpServers": [
                    {
                        "name": "test-server",
                        "command": "nonexistent-mcp-server",
                        "args": ["--stdio"],
                        "env": [],
                    }
                ],
            },
        )
        
        # Выполняем session/new - ожидаем успех даже при ошибке подключения к MCP
        # (graceful degradation: ошибка логируется, но не прерывает создание сессии)
        outcome = await protocol.handle(session_new_msg)
        
        # Проверяем успешный ответ session/new
        assert outcome.response is not None
        assert outcome.response.result is not None
        assert "sessionId" in outcome.response.result
        
        session_id = outcome.response.result["sessionId"]
        
        # Проверяем, что сессия создана и MCPManager инициализирован
        session_state = await protocol._storage.load_session(session_id)
        assert session_state is not None
        assert session_state.mcp_manager is not None
        assert isinstance(session_state.mcp_manager, MCPManager)
        
        # Проверяем, что MCPManager привязан к правильной сессии
        assert session_state.mcp_manager.session_id == session_id

    @pytest.mark.asyncio
    async def test_session_new_without_mcp_servers_no_manager(
        self,
    ) -> None:
        """Проверяет, что session/new без mcpServers не создаёт MCPManager."""
        from codelab.server.messages import ACPMessage
        from codelab.server.protocol.core import ACPProtocol
        
        # Создаём протокол
        protocol = ACPProtocol(require_auth=False)
        
        # Инициализируем протокол
        init_msg = ACPMessage.request(
            request_id=0,
            method="initialize",
            params={"protocolVersion": 1},
        )
        await protocol.handle(init_msg)
        
        # Создаём сессию БЕЗ MCP серверов
        session_new_msg = ACPMessage.request(
            request_id=1,
            method="session/new",
            params={
                "cwd": "/tmp",
            },
        )
        
        outcome = await protocol.handle(session_new_msg)
        
        # Проверяем успешный ответ
        assert outcome.response is not None
        assert outcome.response.result is not None
        session_id = outcome.response.result["sessionId"]
        
        # Проверяем, что MCPManager НЕ создан (нет mcpServers)
        session_state = await protocol._storage.load_session(session_id)
        assert session_state is not None
        assert session_state.mcp_manager is None

    @pytest.mark.asyncio
    async def test_session_new_with_empty_mcp_servers_no_manager(
        self,
    ) -> None:
        """Проверяет, что пустой список mcpServers не создаёт MCPManager."""
        from codelab.server.messages import ACPMessage
        from codelab.server.protocol.core import ACPProtocol
        
        protocol = ACPProtocol(require_auth=False)
        
        init_msg = ACPMessage.request(
            request_id=0,
            method="initialize",
            params={"protocolVersion": 1},
        )
        await protocol.handle(init_msg)
        
        # Создаём сессию с пустым списком MCP серверов
        session_new_msg = ACPMessage.request(
            request_id=1,
            method="session/new",
            params={
                "cwd": "/tmp",
                "mcpServers": [],
            },
        )
        
        outcome = await protocol.handle(session_new_msg)
        
        assert outcome.response is not None
        session_id = outcome.response.result["sessionId"]
        
        # Пустой список - MCPManager не создаётся
        session_state = await protocol._storage.load_session(session_id)
        assert session_state is not None
        assert session_state.mcp_manager is None

    @pytest.mark.asyncio
    async def test_session_new_with_invalid_mcp_config_graceful(
        self,
    ) -> None:
        """Проверяет graceful degradation при невалидной конфигурации MCP."""
        from codelab.server.messages import ACPMessage
        from codelab.server.protocol.core import ACPProtocol
        
        protocol = ACPProtocol(require_auth=False)
        
        init_msg = ACPMessage.request(
            request_id=0,
            method="initialize",
            params={"protocolVersion": 1},
        )
        await protocol.handle(init_msg)
        
        # Создаём сессию с невалидной конфигурацией (отсутствует name)
        session_new_msg = ACPMessage.request(
            request_id=1,
            method="session/new",
            params={
                "cwd": "/tmp",
                "mcpServers": [
                    {
                        # name отсутствует - невалидная конфигурация
                        "command": "some-command",
                    },
                    {
                        # command отсутствует - невалидная конфигурация
                        "name": "incomplete",
                    },
                ],
            },
        )
        
        # Сессия должна создаться успешно (graceful degradation)
        outcome = await protocol.handle(session_new_msg)
        
        assert outcome.response is not None
        assert outcome.response.result is not None
        session_id = outcome.response.result["sessionId"]
        
        # MCPManager создан, но без серверов (все были невалидные)
        session_state = await protocol._storage.load_session(session_id)
        assert session_state is not None
        # MCPManager создаётся, но без успешных подключений
        assert session_state.mcp_manager is not None
        assert session_state.mcp_manager.server_count == 0
