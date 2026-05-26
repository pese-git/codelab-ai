"""Модуль протокола ACP.

Инкапсулирует в-memory реализацию ACP-протокола для demo/интеграционных сценариев.
"""

from .core import ACPProtocol
from .session_factory import SessionFactory
from .session_runtime import SessionRuntimeRegistry, SessionRuntimeState
from .state import (
    ActiveTurnState,
    ClientRuntimeCapabilities,
    LLMLoopResult,
    PendingClientRequestState,
    PreparedFsClientRequest,
    PromptDirectives,
    ProtocolOutcome,
    SessionState,
    ToolCallState,
    ToolResult,
)

__all__ = [
    "ACPProtocol",
    "SessionFactory",
    "ProtocolOutcome",
    "SessionState",
    "SessionRuntimeRegistry",
    "SessionRuntimeState",
    "ToolCallState",
    "ActiveTurnState",
    "PromptDirectives",
    "PendingClientRequestState",
    "PreparedFsClientRequest",
    "ClientRuntimeCapabilities",
    "ToolResult",
    "LLMLoopResult",
]
