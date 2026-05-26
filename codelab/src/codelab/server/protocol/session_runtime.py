"""Реестр runtime-состояний сессий.

Хранит in-memory объекты (MCP manager, кэши) отдельно от
сериализуемого SessionState. REQUEST-scoped, живет в рамках
одного WebSocket соединения. Dishka cleanup при disconnect.
"""

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..mcp.manager import MCPManager


@dataclass
class SessionRuntimeState:
    """Runtime-состояние одной сессии (не сериализуется)."""

    mcp_manager: "MCPManager | None" = None


class SessionRuntimeRegistry:
    """Реестр runtime-состояний сессий.

    Thread-safe через asyncio.Lock. REQUEST-scoped.
    Cleanup через dishka generator при exit из REQUEST scope.
    """

    def __init__(self) -> None:
        """Инициализация пустого реестра."""
        self._states: dict[str, SessionRuntimeState] = {}
        self._lock = asyncio.Lock()

    async def get(self, session_id: str) -> SessionRuntimeState | None:
        """Получить runtime state сессии или None.

        Args:
            session_id: Идентификатор сессии.

        Returns:
            SessionRuntimeState если найден, иначе None.
        """
        async with self._lock:
            return self._states.get(session_id)

    async def get_or_create(self, session_id: str) -> SessionRuntimeState:
        """Получить или создать runtime state сессии.

        Args:
            session_id: Идентификатор сессии.

        Returns:
            SessionRuntimeState для указанной сессии.
        """
        async with self._lock:
            if session_id not in self._states:
                self._states[session_id] = SessionRuntimeState()
            return self._states[session_id]

    async def set_mcp_manager(
        self, session_id: str, mcp_manager: "MCPManager"
    ) -> None:
        """Установить MCP manager для сессии.

        Args:
            session_id: Идентификатор сессии.
            mcp_manager: Экземпляр MCPManager.
        """
        async with self._lock:
            if session_id not in self._states:
                self._states[session_id] = SessionRuntimeState()
            self._states[session_id].mcp_manager = mcp_manager

    async def remove(self, session_id: str) -> None:
        """Удалить runtime state с cleanup MCP subprocesses.

        Args:
            session_id: Идентификатор сессии для удаления.
        """
        async with self._lock:
            state = self._states.pop(session_id, None)
        if state and state.mcp_manager:
            await state.mcp_manager.shutdown()

    async def cleanup(self) -> None:
        """Shutdown всех MCP managers при выходе из REQUEST scope.

        Вызывается автоматически dishka через generator cleanup.
        """
        async with self._lock:
            states = list(self._states.values())
            self._states.clear()
        for state in states:
            if state.mcp_manager:
                await state.mcp_manager.shutdown()
