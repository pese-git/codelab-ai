"""Executor для MCP инструментов.

Адаптирует MCPManager.call_tool() под интерфейс ToolExecutor.
Конвертирует MCP content → ACP content format.
Обрабатывает timeout и errors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from codelab.server.protocol.state import SessionState
from codelab.server.tools.base import ToolExecutionResult
from codelab.server.tools.executors.base import ToolExecutor

if TYPE_CHECKING:
    from codelab.server.mcp.manager import MCPManager

logger = structlog.get_logger()

# MCP namespace prefix
_MCP_PREFIX = "mcp:"


class MCPToolExecutor(ToolExecutor):
    """Executor для MCP инструментов через MCPManager.

    Делегирует выполнение инструментов MCP серверам через MCPManager.
    Конвертирует результаты MCP в формат ToolExecutionResult.

    Attributes:
        mcp_manager: Менеджер MCP серверов сессии.
        default_timeout: Таймаут выполнения инструмента в секундах.
    """

    def __init__(
        self,
        mcp_manager: MCPManager,
        default_timeout: float = 30.0,
    ) -> None:
        """Инициализировать executor.

        Args:
            mcp_manager: Менеджер MCP серверов сессии.
            default_timeout: Таймаут выполнения в секундах.
        """
        self._mcp_manager = mcp_manager
        self._default_timeout = default_timeout

    @staticmethod
    def is_mcp_tool(tool_name: str) -> bool:
        """Проверить, является ли инструмент MCP инструментом.

        Args:
            tool_name: Имя инструмента (в ACP формате).

        Returns:
            True если инструмент имеет MCP namespace.
        """
        return tool_name.startswith(_MCP_PREFIX)

    async def execute(
        self,
        session: SessionState,
        arguments: dict[str, Any],
    ) -> ToolExecutionResult:
        """Выполнить MCP инструмент.

        Args:
            session: Состояние сессии (используется для получения mcp_manager).
            arguments: Аргументы инструмента, включая 'tool_name'.

        Returns:
            ToolExecutionResult с результатом выполнения.
        """
        tool_name = arguments.get("tool_name", "")

        if not self.is_mcp_tool(tool_name):
            return ToolExecutionResult(
                success=False,
                error=f"Not an MCP tool: {tool_name}",
            )

        if self._mcp_manager is None:
            session_id = session.session_id if session else "unknown"
            return ToolExecutionResult(
                success=False,
                error=f"MCP manager not available for session {session_id}",
            )

        logger.info(
            "executing MCP tool",
            session_id=session.session_id,
            tool_name=tool_name,
        )

        # Убираем tool_name из arguments перед передачей в MCP
        mcp_arguments = {k: v for k, v in arguments.items() if k != "tool_name"}

        try:
            result = await self._mcp_manager.call_tool(tool_name, mcp_arguments)
            return result
        except Exception as exc:
            logger.error(
                "MCP tool execution failed",
                session_id=session.session_id,
                tool_name=tool_name,
                error=str(exc),
                exc_info=True,
            )
            return ToolExecutionResult(
                success=False,
                error=f"MCP tool execution error: {exc}",
            )

    async def execute_tool(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        session: SessionState | None = None,
    ) -> ToolExecutionResult:
        """Выполнить MCP инструмент напрямую (без SessionState).

        Args:
            session_id: ID сессии (для логирования).
            tool_name: И MCP инструмента (mcp:server:tool).
            arguments: Аргументы инструмента.
            session: Сессия с mcp_manager.

        Returns:
            ToolExecutionResult с результатом выполнения.
        """
        if session is None:
            return ToolExecutionResult(
                success=False,
                error="Session required for MCP tool execution",
            )

        return await self.execute(session, {"tool_name": tool_name, **arguments})
