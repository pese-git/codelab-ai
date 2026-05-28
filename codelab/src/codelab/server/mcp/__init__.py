"""MCP (Model Context Protocol) интеграция для ACP сервера.

Этот модуль реализует клиентскую часть MCP протокола для подключения
к внешним MCP серверам и использования их инструментов.

Основные компоненты:
- MCPClient: Клиент для взаимодействия с MCP сервером
- Транспорты: StdioTransport, HttpTransport, SseTransport
- Модели данных для MCP протокола

Example:
    >>> from codelab.server.mcp import MCPClient, MCPServerConfig
    >>> 
    >>> config = MCPServerConfig(
    ...     name="filesystem",
    ...     command="mcp-server-filesystem",
    ...     args=["--stdio"]
    ... )
    >>> 
    >>> async with MCPClient(config) as client:
    ...     tools = await client.list_tools()
    ...     result = await client.call_tool("read_file", {"path": "/tmp/test.txt"})
"""

from .client import (
    MCPClient,
    MCPClientError,
    MCPClientState,
    MCPInitializeError,
    MCPToolCallError,
)
from .manager import (
    MCPManager,
    MCPManagerError,
    MCPServerAlreadyExistsError,
    MCPServerNotFoundError,
)
from .models import (
    MCPCallToolParams,
    MCPCallToolResult,
    MCPCapabilities,
    MCPClientInfo,
    MCPContent,
    MCPEmbeddedResource,
    MCPError,
    MCPImageContent,
    MCPInitializeParams,
    MCPInitializeResult,
    MCPListToolsResult,
    MCPNotification,
    MCPRequest,
    MCPResponse,
    MCPServerConfig,
    MCPServerInfo,
    MCPTextContent,
    MCPTool,
    MCPToolInputSchema,
)
from .tool_adapter import MCPToolAdapter
from .transport import (
    HttpConnectionError,
    HttpTimeoutError,
    HttpTransport,
    HttpTransportError,
    ProcessExitedError,
    ProcessNotStartedError,
    SseTransport,
    SseTransportError,
    StdioTransport,
    StdioTransportError,
)

__all__ = [
    # Client
    "MCPClient",
    "MCPClientError",
    "MCPClientState",
    "MCPInitializeError",
    "MCPToolCallError",
    # Manager
    "MCPManager",
    "MCPManagerError",
    "MCPServerAlreadyExistsError",
    "MCPServerNotFoundError",
    # Tool Adapter
    "MCPToolAdapter",
    # Transport
    "StdioTransport",
    "StdioTransportError",
    "ProcessNotStartedError",
    "ProcessExitedError",
    "HttpTransport",
    "HttpTransportError",
    "HttpConnectionError",
    "HttpTimeoutError",
    "SseTransport",
    "SseTransportError",
    # Models - core JSON-RPC
    "MCPRequest",
    "MCPResponse",
    "MCPNotification",
    "MCPError",
    # Models - Server Info
    "MCPServerConfig",
    "MCPServerInfo",
    "MCPClientInfo",
    "MCPCapabilities",
    "MCPInitializeParams",
    "MCPInitializeResult",
    # Models - Tools
    "MCPTool",
    "MCPToolInputSchema",
    "MCPListToolsResult",
    "MCPCallToolParams",
    "MCPCallToolResult",
    # Models - Content
    "MCPContent",
    "MCPTextContent",
    "MCPImageContent",
    "MCPEmbeddedResource",
]
