"""MCP клиент для взаимодействия с MCP серверами.

Реализует высокоуровневый API для работы с MCP серверами:
инициализацию, получение списка инструментов и вызов инструментов.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from .models import (
    MCPCallToolParams,
    MCPCallToolResult,
    MCPCapabilities,
    MCPClientInfo,
    MCPInitializeParams,
    MCPInitializeResult,
    MCPListToolsResult,
    MCPServerConfig,
    MCPTool,
)
from .transport import StdioTransport, StdioTransportError

logger = logging.getLogger(__name__)


# Версия MCP протокола
MCP_PROTOCOL_VERSION = "2024-11-05"

# Информация о нашем клиенте
ACP_CLIENT_INFO = MCPClientInfo(
    name="codelab",
    version="1.0.0"
)


class MCPClientState(Enum):
    """Состояние MCP клиента."""
    
    CREATED = "created"
    """Клиент создан, но не подключен."""
    
    CONNECTING = "connecting"
    """Выполняется подключение к серверу."""
    
    INITIALIZING = "initializing"
    """Выполняется MCP initialize handshake."""
    
    READY = "ready"
    """Клиент готов к работе."""
    
    FAILED = "failed"
    """Произошла ошибка при подключении."""
    
    CLOSED = "closed"
    """Соединение закрыто."""


class MCPClientError(Exception):
    """Базовое исключение для ошибок MCP клиента."""
    pass


class MCPInitializeError(MCPClientError):
    """Ошибка при инициализации MCP соединения."""
    pass


class MCPToolCallError(MCPClientError):
    """Ошибка при вызове инструмента MCP."""
    pass


class MCPClient:
    """Клиент для взаимодействия с одним MCP сервером.
    
    Управляет жизненным циклом подключения к MCP серверу:
    запуск процесса, инициализация, получение инструментов, вызов.
    
    Attributes:
        config: Конфигурация MCP сервера.
        state: Текущее состояние клиента.
        capabilities: Capabilities сервера после инициализации.
        tools: Список доступных инструментов.
        server_name: Имя сервера (из config или от сервера).
    
    Example:
        >>> config = MCPServerConfig(
        ...     name="filesystem",
        ...     command="mcp-server-filesystem",
        ...     args=["--stdio"]
        ... )
        >>> client = MCPClient(config)
        >>> await client.connect()
        >>> tools = await client.list_tools()
        >>> result = await client.call_tool("read_file", {"path": "/tmp/test.txt"})
        >>> await client.disconnect()
    """
    
    def __init__(self, config: MCPServerConfig) -> None:
        """Инициализация MCP клиента.
        
        Args:
            config: Конфигурация MCP сервера для подключения.
        """
        self.config = config
        self._transport: StdioTransport | None = None
        self._state: MCPClientState = MCPClientState.CREATED
        self._capabilities: MCPCapabilities | None = None
        self._server_info: dict[str, str] | None = None
        self._tools: list[MCPTool] = []
    
    @property
    def state(self) -> MCPClientState:
        """Текущее состояние клиента."""
        return self._state
    
    @property
    def capabilities(self) -> MCPCapabilities | None:
        """Capabilities MCP сервера (доступны после initialize)."""
        return self._capabilities
    
    @property
    def tools(self) -> list[MCPTool]:
        """Список доступных инструментов (после list_tools)."""
        return self._tools
    
    @property
    def server_name(self) -> str:
        """Имя сервера из конфигурации."""
        return self.config.name
    
    @property
    def is_ready(self) -> bool:
        """Проверить, готов ли клиент к работе."""
        return self._state == MCPClientState.READY
    
    async def connect(self) -> None:
        """Запустить MCP сервер и установить соединение.
        
        Запускает процесс MCP сервера, но не выполняет initialize.
        
        Raises:
            MCPClientError: Если клиент уже подключен.
            MCPClientError: Если не удалось запустить процесс.
        """
        if self._state not in (MCPClientState.CREATED, MCPClientState.CLOSED):
            raise MCPClientError(f"Cannot connect in state {self._state}")
        
        self._state = MCPClientState.CONNECTING
        
        logger.info(
            "Connecting to MCP server: %s (command=%s)",
            self.config.name,
            self.config.command
        )
        
        try:
            self._transport = StdioTransport()
            await self._transport.start(
                command=self.config.command,
                args=self.config.args,
                env=self.config.get_env_dict(),
            )
            
            logger.debug("MCP server process started: %s", self.config.name)
            
        except StdioTransportError as e:
            self._state = MCPClientState.FAILED
            raise MCPClientError(f"Failed to start MCP server: {e}") from e
    
    async def initialize(self) -> MCPCapabilities:
        """Выполнить MCP initialize handshake.
        
        Отправляет initialize запрос и получает capabilities сервера.
        После успешной инициализации отправляет notifications/initialized.
        
        Returns:
            Capabilities MCP сервера.
        
        Raises:
            MCPInitializeError: Если инициализация не удалась.
            MCPClientError: Если клиент не в состоянии CONNECTING.
        """
        if self._state != MCPClientState.CONNECTING:
            raise MCPClientError(f"Cannot initialize in state {self._state}")
        
        if not self._transport:
            raise MCPClientError("Transport not initialized")
        
        self._state = MCPClientState.INITIALIZING
        
        logger.debug("Sending initialize to MCP server: %s", self.config.name)
        
        try:
            # Формируем параметры инициализации
            params = MCPInitializeParams(
                protocolVersion=MCP_PROTOCOL_VERSION,
                capabilities={},
                clientInfo=ACP_CLIENT_INFO,
            )
            
            # Отправляем initialize
            result_data = await self._transport.send_request(
                method="initialize",
                params=params.model_dump(by_alias=True),
                timeout=30.0,
            )
            
            # Парсим результат
            result = MCPInitializeResult.model_validate(result_data)
            
            self._capabilities = result.capabilities
            self._server_info = {
                "name": result.server_info.name,
                "version": result.server_info.version,
            }
            
            logger.info(
                "MCP server initialized: %s (server=%s v%s)",
                self.config.name,
                result.server_info.name,
                result.server_info.version,
            )
            
            # Отправляем notifications/initialized
            await self._transport.send_notification(
                method="notifications/initialized"
            )
            
            self._state = MCPClientState.READY
            
            return self._capabilities
            
        except StdioTransportError as e:
            self._state = MCPClientState.FAILED
            raise MCPInitializeError(
                f"Initialize failed for {self.config.name}: {e}"
            ) from e
        except Exception as e:
            self._state = MCPClientState.FAILED
            raise MCPInitializeError(
                f"Initialize error for {self.config.name}: {e}"
            ) from e
    
    async def list_tools(self) -> list[MCPTool]:
        """Получить список доступных инструментов от MCP сервера.
        
        Вызывает tools/list и кэширует результат.
        
        Returns:
            Список определений инструментов.
        
        Raises:
            MCPClientError: Если клиент не готов или запрос не удался.
        """
        if self._state != MCPClientState.READY:
            raise MCPClientError(f"Cannot list tools in state {self._state}")
        
        if not self._transport:
            raise MCPClientError("Transport not available")
        
        # Проверяем, поддерживает ли сервер tools
        if self._capabilities and not self._capabilities.tools:
            logger.debug(
                "MCP server %s does not support tools",
                self.config.name
            )
            return []
        
        logger.debug("Requesting tools list from: %s", self.config.name)
        
        try:
            result_data = await self._transport.send_request(
                method="tools/list",
                timeout=30.0,
            )
            
            result = MCPListToolsResult.model_validate(result_data)
            self._tools = result.tools
            
            logger.info(
                "MCP server %s provides %d tools",
                self.config.name,
                len(self._tools)
            )
            
            for tool in self._tools:
                logger.debug("  - %s: %s", tool.name, tool.description)
            
            return self._tools
            
        except StdioTransportError as e:
            raise MCPClientError(f"Failed to list tools: {e}") from e
    
    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> MCPCallToolResult:
        """Вызвать инструмент MCP сервера.
        
        Args:
            name: Имя инструмента для вызова.
            arguments: Аргументы для инструмента.
            timeout: Таймаут выполнения в секундах.
        
        Returns:
            Результат вызова инструмента.
        
        Raises:
            MCPToolCallError: Если вызов не удался.
            MCPClientError: Если клиент не готов.
        """
        if self._state != MCPClientState.READY:
            raise MCPClientError(f"Cannot call tool in state {self._state}")
        
        if not self._transport:
            raise MCPClientError("Transport not available")
        
        logger.debug(
            "Calling MCP tool: %s.%s with args=%s",
            self.config.name,
            name,
            arguments
        )
        
        try:
            params = MCPCallToolParams(
                name=name,
                arguments=arguments or {},
            )
            
            result_data = await self._transport.send_request(
                method="tools/call",
                params=params.model_dump(by_alias=True),
                timeout=timeout,
            )
            
            result = MCPCallToolResult.model_validate(result_data)
            
            if result.is_error:
                logger.warning(
                    "MCP tool %s.%s returned error: %s",
                    self.config.name,
                    name,
                    result.get_text_content()
                )
            else:
                logger.debug(
                    "MCP tool %s.%s completed successfully",
                    self.config.name,
                    name
                )
            
            return result
            
        except StdioTransportError as e:
            raise MCPToolCallError(
                f"Tool call {name} failed: {e}"
            ) from e
    
    async def disconnect(self) -> None:
        """Закрыть соединение с MCP сервером.
        
        Выполняет graceful shutdown транспорта.
        """
        if self._state == MCPClientState.CLOSED:
            return
        
        logger.info("Disconnecting from MCP server: %s", self.config.name)
        
        if self._transport:
            await self._transport.close()
            self._transport = None
        
        self._state = MCPClientState.CLOSED
        self._capabilities = None
        self._tools = []
    
    async def __aenter__(self) -> MCPClient:
        """Асинхронный контекстный менеджер - вход.
        
        Выполняет подключение и инициализацию.
        """
        await self.connect()
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Асинхронный контекстный менеджер - выход.
        
        Выполняет отключение.
        """
        await self.disconnect()
