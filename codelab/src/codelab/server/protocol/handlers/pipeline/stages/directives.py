"""Стадия обработки prompt директив (/tool, /tool-pending и т.д.)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from codelab.server.messages import ACPMessage
from codelab.server.protocol.handlers.directives import (
    extract_prompt_directives,
    resolve_tool_title,
)
from codelab.server.protocol.state import SessionState

from ..base import PromptStage
from ..context import PromptContext

if TYPE_CHECKING:
    from codelab.server.protocol.handlers.permission_manager import PermissionManager
    from codelab.server.tools.base import ToolRegistry

logger = structlog.get_logger()


def _can_run_tool_runtime(session: SessionState) -> bool:
    """Проверяет, можно ли запускать tool-runtime в текущей сессии."""
    caps = session.runtime_capabilities
    if caps is None:
        return False
    return caps.terminal or caps.fs_read or caps.fs_write


class DirectivesStage(PromptStage):
    """Обрабатывает prompt директивы для принудительного вызова инструментов."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        permission_manager: PermissionManager,
    ) -> None:
        self._tool_registry = tool_registry
        self._permission_manager = permission_manager

    async def process(self, context: PromptContext) -> PromptContext:
        if context.should_stop:
            return context

        directives = extract_prompt_directives(
            context.raw_text,
            {"read", "edit", "delete", "move", "search", "execute", "think", "fetch", "switch_mode", "other"},
        )
        context.meta["directives"] = directives

        if not directives.request_tool:
            return context

        if not _can_run_tool_runtime(context.session):
            return context

        tool_title = resolve_tool_title(directives.tool_kind)
        tool_call_id = self._create_tool_call(context.session, tool_title, directives.tool_kind)

        context.notifications.append(
            ACPMessage.notification(
                "session/update",
                {
                    "sessionId": context.session_id,
                    "update": {
                        "sessionUpdate": "tool_call",
                        "toolCallId": tool_call_id,
                        "title": tool_title,
                        "kind": directives.tool_kind,
                        "status": "pending",
                    },
                },
            )
        )

        mode = context.session.config_values.get("mode", "ask")
        if mode == "ask":
            permission_request = ACPMessage.request(
                "session/request_permission",
                {
                    "sessionId": context.session_id,
                    "toolCall": {
                        "toolCallId": tool_call_id,
                        "title": tool_title,
                        "kind": directives.tool_kind,
                        "status": "pending",
                    },
                    "options": self._build_permission_options(),
                },
            )
            if context.session.active_turn is not None:
                context.session.active_turn.permission_request_id = permission_request.id
                context.session.active_turn.permission_tool_call_id = tool_call_id
                context.session.active_turn.phase = "waiting_permission"
            context.notifications.append(permission_request)
            context.pending_permission = True
            context.should_stop = True

            if directives.keep_tool_pending and context.session.active_turn is not None:
                context.session.active_turn.phase = "waiting_tool_completion"

        return context

    def _create_tool_call(
        self,
        session: SessionState,
        title: str,
        kind: str,
    ) -> str:
        """Создаёт tool_call в сессии и возвращает его ID."""
        import secrets

        tool_call_id = f"tool_{secrets.token_hex(8)}"
        session.events_history.append({
            "type": "tool_call",
            "toolCallId": tool_call_id,
            "title": title,
            "kind": kind,
            "status": "pending",
        })
        return tool_call_id

    def _build_permission_options(self) -> dict:
        """Строит options для permission request."""
        return {
            "allowOnce": "Allow once",
            "allowSession": "Allow for session",
            "allowAlways": "Allow always",
            "rejectOnce": "Reject",
        }
