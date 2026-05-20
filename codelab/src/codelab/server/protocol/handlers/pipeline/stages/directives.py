"""Стадия обработки prompt директив (/tool, /tool-pending, _meta.promptDirectives и т.д.)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from codelab.server.messages import ACPMessage
from codelab.server.protocol.handlers.prompt import (
    build_executor_tool_execution_updates,
    build_fs_client_request,
    build_plan_entries,
    build_policy_tool_execution_updates,
    build_terminal_client_request,
    can_use_fs_client_rpc,
    can_use_terminal_client_rpc,
    create_tool_call,
    resolve_prompt_directives,
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


def _decide_tool_policy(session: SessionState, tool_kind: str) -> str:
    """Определяет политику выполнения tool (allow/reject/ask)."""
    session_policy = session.permission_policy.get(tool_kind)
    if session_policy == "allow_always":
        return "allow"
    if session_policy == "reject_always":
        return "reject"
    return "ask"


class DirectivesStage(PromptStage):
    """Обрабатывает prompt директивы для принудительного вызова инструментов.

    Читает как text-based директивы (/tool, /tool-pending, /plan, /fs-read и пр.),
    так и structured overrides из _meta.promptDirectives.

    Порядок обработки:
    1. forced_stop_reason — устанавливает stop_reason, не прерывает pipeline
    2. publish_plan — эмитирует plan notification, не прерывает pipeline
    3. terminal_command — строит terminal/create RPC request, прерывает pipeline
    4. fs_read_path / fs_write_path — строит fs/* RPC request, прерывает pipeline
    5. requestTool — в зависимости от policy:
       - "ask": запрашивает permission, прерывает pipeline
       - "allow": выполняет tool, продолжает pipeline
       - "reject": отменяет tool, продолжает pipeline
    """

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

        directives = resolve_prompt_directives(
            params=context.params,
            text_preview=context.raw_text,
        )
        context.meta["directives"] = directives

        # 1. Forced stop reason — изменяем stop_reason, но не останавливаем pipeline
        if directives.forced_stop_reason is not None:
            context.stop_reason = directives.forced_stop_reason

        # 2. Publish plan — эмитируем plan notification, не останавливаем pipeline
        if directives.publish_plan:
            plan_entries = build_plan_entries(
                directives=directives,
                text_preview=context.raw_text,
            )
            if plan_entries:
                plan_notification = ACPMessage.notification(
                    "session/update",
                    {
                        "sessionId": context.session_id,
                        "update": {
                            "sessionUpdate": "plan",
                            "entries": plan_entries,
                        },
                    },
                )
                context.notifications.append(plan_notification)
                # Сохраняем план в сессии для replay
                context.session.latest_plan = [
                    {
                        "title": entry.get("content", ""),
                        "description": entry.get("description", ""),
                    }
                    for entry in plan_entries
                ]

        # 3. Terminal RPC — если есть terminal_command, строим client RPC request
        if directives.terminal_command is not None and can_use_terminal_client_rpc(context.session):
            prepared = build_terminal_client_request(
                session=context.session,
                session_id=context.session_id,
                directives=directives,
            )
            if prepared is not None:
                context.notifications.extend(prepared.messages)
                if context.session.active_turn is not None:
                    context.session.active_turn.pending_client_request = prepared.pending_request
                    context.session.active_turn.phase = "waiting_client_rpc"
                context.pending_permission = True  # turn deferred — не отправлять response
                context.should_stop = True
                return context

        # 4. FS RPC — если есть fsReadPath или fsWritePath, строим fs/* client RPC request
        if directives.fs_read_path is not None or directives.fs_write_path is not None:
            fs_kind = "fs_read" if directives.fs_read_path is not None else "fs_write"
            if can_use_fs_client_rpc(context.session, fs_kind):
                prepared = build_fs_client_request(
                    session=context.session,
                    session_id=context.session_id,
                    directives=directives,
                )
                if prepared is not None:
                    context.notifications.extend(prepared.messages)
                    if context.session.active_turn is not None:
                        context.session.active_turn.pending_client_request = prepared.pending_request
                        context.session.active_turn.phase = "waiting_client_rpc"
                    context.pending_permission = True  # turn deferred — не отправлять response
                    context.should_stop = True
                    return context

        # 5. Request tool — permission flow
        if not directives.request_tool:
            return context

        if not _can_run_tool_runtime(context.session):
            # Сообщаем о недоступности tool runtime
            context.notifications.append(
                ACPMessage.notification(
                    "session/update",
                    {
                        "sessionId": context.session_id,
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {
                                "type": "text",
                                "text": "Tool runtime unavailable: capability not negotiated via initialize",
                            },
                        },
                    },
                )
            )
            return context

        tool_title = resolve_tool_title(directives.tool_kind)
        tool_call_id = create_tool_call(
            context.session,
            title=tool_title,
            kind=directives.tool_kind,
        )

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

        # Проверяем политику разрешений
        policy = _decide_tool_policy(context.session, directives.tool_kind)

        if policy == "allow":
            # Политика разрешает — выполняем tool без запроса permission.
            # Продолжаем pipeline (LLMLoopStage → close), turn завершится нормально.
            execution_updates = build_executor_tool_execution_updates(
                session=context.session,
                session_id=context.session_id,
                tool_call_id=tool_call_id,
                leave_running=False,
            )
            context.notifications.extend(execution_updates)
            return context

        if policy == "reject":
            # Политика отклоняет — отменяем tool call, завершаем turn с cancelled.
            execution_updates = build_policy_tool_execution_updates(
                session=context.session,
                session_id=context.session_id,
                tool_call_id=tool_call_id,
                allowed=False,
            )
            context.notifications.extend(execution_updates)
            context.stop_reason = "cancelled"
            return context

        # policy == "ask" — запрашиваем permission у пользователя (только в режиме "ask")
        mode = context.session.config_values.get("mode", "ask")
        if mode != "ask":
            # В не-ask режиме (code, architect и т.д.) выполняем tool без permission request
            execution_updates = build_executor_tool_execution_updates(
                session=context.session,
                session_id=context.session_id,
                tool_call_id=tool_call_id,
                leave_running=directives.keep_tool_pending,
            )
            context.notifications.extend(execution_updates)
            if directives.keep_tool_pending:
                if context.session.active_turn is not None:
                    context.session.active_turn.phase = "waiting_tool_completion"
                context.pending_permission = True  # turn deferred
                context.should_stop = True
            return context

        if mode == "ask":
            options = self._permission_manager.build_permission_options()
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
                    "options": options,
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
        elif directives.keep_tool_pending:
            # Не режим ask, но /tool-pending — defer turn without permission request.
            # Turn остаётся открытым в фазе "waiting_tool_completion".
            if context.session.active_turn is not None:
                context.session.active_turn.phase = "waiting_tool_completion"
            context.pending_permission = True  # сигнализирует handle_prompt об отложенном turn
            context.should_stop = True

        return context
