"""Обработчики методов работы с prompt-turn.

Содержит логику обработки session/prompt, session/cancel и related.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from ...messages import ACPMessage, JsonRpcId
from ...storage import SessionStorage
from ..state import (
    PendingClientRequestState,
    PendingToolExecution,
    PreparedFsClientRequest,
    PromptDirectives,
    ProtocolOutcome,
    SessionState,
    ToolCallState,
)
from .permissions import (
    build_permission_options,
)
from .session import (
    session_info_notification,
)

# Используем structlog для структурированного логирования
logger = structlog.get_logger()

# Максимальная длина текста одного промпт-блока (символов)
MAX_PROMPT_TEXT_LENGTH = 100_000


def complete_active_turn(
    session: SessionState,
    *,
    stop_reason: str = "end_turn",
) -> ACPMessage | None:
    """Завершает активный prompt-turn и возвращает финальный response.

    Используется транспортом WS для отложенного ответа на `session/prompt`.

    Пример использования:
        response = complete_active_turn(session, stop_reason="end_turn")
    """
    return finalize_active_turn(
        session=session,
        stop_reason=normalize_stop_reason(stop_reason),
    )


def should_auto_complete_active_turn(
    session: SessionState,
) -> bool:
    """Возвращает `True`, если active turn можно безопасно автозавершить.

    Если turn ожидает permission-response, автозавершение запрещено.

    Пример использования:
        if should_auto_complete_active_turn(session):
            ...
    """
    if session.active_turn is None:
        return False
    return session.active_turn.phase == "waiting_tool_completion"


def validate_prompt_content(
    request_id: JsonRpcId | None,
    prompt: list[Any],
) -> ACPMessage | None:
    """Проверяет корректность ContentBlock-массива для `session/prompt`.

    Поддерживаются типы `text` и `resource_link`.
    При ошибке возвращается `ACPMessage.error_response`, иначе `None`.

    Пример использования:
        error = validate_prompt_content("req_1", [{"type": "text", "text": "hi"}])
    """

    for block in prompt:
        if not isinstance(block, dict):
            return ACPMessage.error_response(
                request_id,
                code=-32602,
                message="Invalid params: each prompt item must be an object",
            )
        block_type = block.get("type")
        if block_type == "text":
            if not isinstance(block.get("text"), str):
                return ACPMessage.error_response(
                    request_id,
                    code=-32602,
                    message="Invalid params: text content requires text string",
                )
            text_length = len(block["text"])
            if text_length > MAX_PROMPT_TEXT_LENGTH:
                return ACPMessage.error_response(
                    request_id,
                    code=-32602,
                    message=(
                        f"Invalid params: prompt text too long: {text_length} chars "
                        f"(max {MAX_PROMPT_TEXT_LENGTH})"
                    ),
                )
            continue
        if block_type == "resource_link":
            has_uri = isinstance(block.get("uri"), str)
            has_name = isinstance(block.get("name"), str)
            if not has_uri or not has_name:
                return ACPMessage.error_response(
                    request_id,
                    code=-32602,
                    message="Invalid params: resource_link requires uri and name",
                )
            continue
        return ACPMessage.error_response(
            request_id,
            code=-32602,
            message=f"Invalid params: unsupported content type {block_type}",
        )
    return None


def extract_prompt_directives(
    text_preview: str,
    supported_tool_kinds: set[str],
) -> PromptDirectives:
    """Извлекает служебные флаги turn из текстового preview prompt.

    Поддерживаются только slash-команды (`/plan`, `/tool`, `/tool-pending`
    и RPC-команды `/fs-read`, `/fs-write`, `/term-run`).

    Пример использования:
        directives = extract_prompt_directives("/tool /plan", {"other"})
    """

    normalized_tokens = {
        token.strip().lower()
        for token in text_preview.replace("\n", " ").split(" ")
        if token.strip()
    }

    has_plan_directive = "/plan" in normalized_tokens
    has_tool_directive = "/tool" in normalized_tokens
    has_pending_directive = "/tool-pending" in normalized_tokens
    tool_kind = "other"
    fs_read_path: str | None = None
    fs_write_path: str | None = None
    fs_write_content: str | None = None
    terminal_command: str | None = None
    forced_stop_reason: str | None = None

    stripped_preview = text_preview.strip()
    if stripped_preview.startswith("/fs-read "):
        maybe_path = stripped_preview[len("/fs-read ") :].strip()
        if maybe_path:
            fs_read_path = maybe_path
    if stripped_preview.startswith("/fs-write "):
        raw_write_payload = stripped_preview[len("/fs-write ") :].strip()
        path_and_content = raw_write_payload.split(" ", 1)
        if len(path_and_content) == 2:
            candidate_path = path_and_content[0].strip()
            candidate_content = path_and_content[1]
            if candidate_path:
                fs_write_path = candidate_path
                fs_write_content = candidate_content
    if stripped_preview.startswith("/term-run "):
        raw_command = stripped_preview[len("/term-run ") :].strip()
        if raw_command:
            terminal_command = raw_command
    if stripped_preview.startswith("/stop-max-tokens"):
        forced_stop_reason = "max_tokens"
    if stripped_preview.startswith("/stop-max-turn-requests"):
        forced_stop_reason = "max_turn_requests"
    if stripped_preview.startswith("/refuse"):
        forced_stop_reason = "refusal"

    # Поддерживаем опциональный kind в `/tool <kind> ...` и
    # `/tool-pending <kind> ...` для policy-scope beyond `other`.
    if stripped_preview.startswith("/tool "):
        candidate = stripped_preview[len("/tool ") :].split(" ", 1)[0].strip().lower()
        normalized_candidate = normalize_tool_kind(candidate, supported_tool_kinds)
        if normalized_candidate is not None:
            tool_kind = normalized_candidate
    if stripped_preview.startswith("/tool-pending "):
        candidate = stripped_preview[len("/tool-pending ") :].split(" ", 1)[0].strip().lower()
        normalized_candidate = normalize_tool_kind(candidate, supported_tool_kinds)
        if normalized_candidate is not None:
            tool_kind = normalized_candidate

    return PromptDirectives(
        request_tool=has_tool_directive or has_pending_directive,
        keep_tool_pending=has_pending_directive,
        publish_plan=has_plan_directive,
        plan_entries=None,
        tool_kind=tool_kind,
        fs_read_path=fs_read_path,
        fs_write_path=fs_write_path,
        fs_write_content=fs_write_content,
        terminal_command=terminal_command,
        forced_stop_reason=forced_stop_reason,
    )


def resolve_prompt_directives(
    *,
    params: dict[str, Any],
    text_preview: str,
    supported_tool_kinds: set[str] | None = None,
) -> PromptDirectives:
    """Формирует итоговые prompt-directives из текста и structured `_meta`.

    Structured overrides позволяют управлять prompt-оркестрацией без
    специальных slash-триггеров внутри пользовательского текста.

    Пример использования:
        directives = resolve_prompt_directives(params=params, text_preview="hello")
    """

    if supported_tool_kinds is None:
        supported_tool_kinds = {
            "read",
            "edit",
            "delete",
            "move",
            "search",
            "execute",
            "think",
            "fetch",
            "switch_mode",
            "other",
        }

    directives = extract_prompt_directives(text_preview, supported_tool_kinds)
    raw_meta = params.get("_meta")
    if not isinstance(raw_meta, dict):
        return directives
    raw_overrides = raw_meta.get("promptDirectives")
    if not isinstance(raw_overrides, dict):
        return directives

    request_tool = raw_overrides.get("requestTool")
    if isinstance(request_tool, bool):
        directives.request_tool = request_tool

    keep_tool_pending = raw_overrides.get("keepToolPending")
    if isinstance(keep_tool_pending, bool):
        directives.keep_tool_pending = keep_tool_pending

    publish_plan = raw_overrides.get("publishPlan")
    if isinstance(publish_plan, bool):
        directives.publish_plan = publish_plan

    raw_plan_entries = raw_overrides.get("planEntries")
    normalized_plan_entries = normalize_plan_entries(raw_plan_entries)
    if normalized_plan_entries is not None:
        directives.plan_entries = normalized_plan_entries
        directives.publish_plan = True

    raw_tool_kind = raw_overrides.get("toolKind")
    if isinstance(raw_tool_kind, str):
        normalized_kind = normalize_tool_kind(raw_tool_kind.strip().lower(), supported_tool_kinds)
        if normalized_kind is not None:
            directives.tool_kind = normalized_kind

    fs_read_path = raw_overrides.get("fsReadPath")
    if isinstance(fs_read_path, str) and fs_read_path.strip():
        directives.fs_read_path = fs_read_path.strip()

    fs_write_path = raw_overrides.get("fsWritePath")
    if isinstance(fs_write_path, str) and fs_write_path.strip():
        directives.fs_write_path = fs_write_path.strip()

    fs_write_content = raw_overrides.get("fsWriteContent")
    if isinstance(fs_write_content, str):
        directives.fs_write_content = fs_write_content

    terminal_command = raw_overrides.get("terminalCommand")
    if isinstance(terminal_command, str) and terminal_command.strip():
        directives.terminal_command = terminal_command.strip()

    forced_stop_reason = raw_overrides.get("forcedStopReason")
    if isinstance(forced_stop_reason, str):
        normalized_reason = normalize_stop_reason(forced_stop_reason)
        directives.forced_stop_reason = normalized_reason

    if directives.keep_tool_pending:
        # Pending-tool сценарий не имеет смысла без явного tool-flow.
        directives.request_tool = True

    return directives


def resolve_prompt_stop_reason(directives: PromptDirectives) -> str:
    """Возвращает stopReason для текущего prompt-turn.

    Пример использования:
        reason = resolve_prompt_stop_reason(directives)
    """

    if directives.forced_stop_reason is not None:
        return normalize_stop_reason(directives.forced_stop_reason)
    return "end_turn"


def normalize_stop_reason(stop_reason: str, supported_stop_reasons: set[str] | None = None) -> str:
    """Нормализует stopReason к поддерживаемому значению ACP.

    Пример использования:
        reason = normalize_stop_reason("max_tokens")
    """

    if supported_stop_reasons is None:
        supported_stop_reasons = {
            "end_turn",
            "max_tokens",
            "max_turn_requests",
            "refusal",
            "cancelled",
        }

    if stop_reason in supported_stop_reasons:
        return stop_reason
    return "end_turn"


def resolve_tool_title(kind: str) -> str:
    """Возвращает человекочитаемый title для tool-call по kind.

    Пример использования:
        title = resolve_tool_title("execute")
    """

    titles = {
        "read": "Tool read operation",
        "edit": "Tool edit operation",
        "delete": "Tool delete operation",
        "move": "Tool move operation",
        "execute": "Tool execution",
        "search": "Tool search operation",
        "think": "Tool reasoning step",
        "fetch": "Tool fetch operation",
        "switch_mode": "Tool mode switch",
        "other": "Tool operation",
    }
    return titles.get(kind, "Tool operation")


def normalize_tool_kind(candidate: str, supported_tool_kinds: set[str] | None = None) -> str | None:
    """Нормализует tool kind к поддерживаемому множеству ACP.

    Пример использования:
        kind = normalize_tool_kind("write")
    """

    if supported_tool_kinds is None:
        supported_tool_kinds = {
            "read",
            "edit",
            "delete",
            "move",
            "search",
            "execute",
            "think",
            "fetch",
            "switch_mode",
            "other",
        }

    normalized = "edit" if candidate == "write" else candidate
    if normalized in supported_tool_kinds:
        return normalized
    return None


def normalize_plan_entries(raw_entries: Any) -> list[dict[str, str]] | None:
    """Нормализует structured `planEntries` из `_meta.promptDirectives`.

    Пример использования:
        entries = normalize_plan_entries(raw_entries)
    """

    if not isinstance(raw_entries, list) or not raw_entries:
        return None

    normalized_entries: list[dict[str, str]] = []
    allowed_priorities = {"low", "medium", "high"}
    allowed_statuses = {"pending", "in_progress", "completed", "cancelled"}
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        content = entry.get("content")
        if not isinstance(content, str) or not content.strip():
            continue

        raw_priority = entry.get("priority")
        priority = raw_priority if isinstance(raw_priority, str) else "medium"
        if priority not in allowed_priorities:
            priority = "medium"

        raw_status = entry.get("status")
        status = raw_status if isinstance(raw_status, str) else "pending"
        if status not in allowed_statuses:
            status = "pending"

        normalized_entries.append(
            {
                "content": content.strip(),
                "priority": priority,
                "status": status,
            }
        )

    return normalized_entries or None


def build_executor_tool_execution_updates(
    *,
    session: SessionState,
    session_id: str,
    tool_call_id: str,
    leave_running: bool,
) -> list[ACPMessage]:
    """Генерирует базовый executor-lifecycle для существующего tool-call.

    Пример использования:
        updates = build_executor_tool_execution_updates(
            session=state,
            session_id="sess_1",
            tool_call_id="call_001",
            leave_running=False,
        )
    """

    in_progress = ACPMessage.notification(
        "session/update",
        {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": tool_call_id,
                "status": "in_progress",
            },
        },
    )
    update_tool_call_status(session, tool_call_id, "in_progress")

    if leave_running:
        return [in_progress]

    completed_content = [
        {
            "type": "content",
            "content": {
                "type": "text",
                "text": "Tool completed successfully.",
            },
        }
    ]
    update_tool_call_status(
        session,
        tool_call_id,
        "completed",
        content=completed_content,
    )
    completed = ACPMessage.notification(
        "session/update",
        {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": tool_call_id,
                "status": "completed",
                "content": completed_content,
            },
        },
    )
    return [in_progress, completed]


def build_policy_tool_execution_updates(
    *,
    session: SessionState,
    session_id: str,
    tool_call_id: str,
    allowed: bool,
) -> list[ACPMessage]:
    """Строит lifecycle updates для tool execution после policy-решения.

    При allowed=True отправляет только "in_progress" статус.
    Реальное выполнение и "completed" статус обрабатываются асинхронно
    через pending_tool_execution в ProtocolOutcome.

    Пример использования:
        updates = build_policy_tool_execution_updates(
            session=state,
            session_id="sess_1",
            tool_call_id="call_1",
            allowed=True,
        )
    """

    if not allowed:
        update_tool_call_status(session, tool_call_id, "cancelled")
        return [
            ACPMessage.notification(
                "session/update",
                {
                    "sessionId": session_id,
                    "update": {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": tool_call_id,
                        "status": "cancelled",
                    },
                },
            )
        ]

    # При allowed=True только отмечаем "in_progress".
    # Реальное выполнение будет запущено асинхронно через pending_tool_execution.
    update_tool_call_status(session, tool_call_id, "in_progress")
    return [
        ACPMessage.notification(
            "session/update",
            {
                "sessionId": session_id,
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": tool_call_id,
                    "status": "in_progress",
                },
            },
        )
    ]


def build_plan_entries(
    *,
    directives: PromptDirectives,
    text_preview: str,
) -> list[dict[str, str]]:
    """Строит plan entries для `session/update: plan`.

    Пример использования:
        entries = build_plan_entries(
            directives=directives,
            text_preview="ship release",
        )
    """

    if directives.plan_entries:
        return directives.plan_entries

    normalized_preview = text_preview.strip() or "выполнение запроса"
    short_preview = normalized_preview[:80]
    return [
        {
            "content": f"Уточнить задачу: {short_preview}",
            "priority": "high",
            "status": "completed",
        },
        {
            "content": f"Выполнить основной шаг для: {short_preview}",
            "priority": "high",
            "status": "in_progress",
        },
        {
            "content": "Проверить результат и завершить ответ",
            "priority": "medium",
            "status": "pending",
        },
    ]


def build_fs_client_request(
    *,
    session: SessionState,
    session_id: str,
    directives: PromptDirectives,
) -> PreparedFsClientRequest | None:
    """Готовит исходящий fs/* request и связанный tool_call lifecycle.

    Пример использования:
        prepared = build_fs_client_request(
            session=state,
            session_id="sess_1",
            directives=directives,
        )
    """

    if directives.fs_read_path is not None:
        target_path = normalize_session_path(session.cwd, directives.fs_read_path)
        if target_path is None:
            return None
        tool_call_id = create_tool_call(
            session=session,
            title="Read text file",
            kind="read",
        )
        created = ACPMessage.notification(
            "session/update",
            {
                "sessionId": session_id,
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": tool_call_id,
                    "title": "Read text file",
                    "kind": "read",
                    "status": "pending",
                    "locations": [{"path": target_path}],
                },
            },
        )
        fs_request = ACPMessage.request(
            "fs/read_text_file",
            {
                "sessionId": session_id,
                "path": target_path,
            },
        )
        if fs_request.id is None:
            return None
        pending = PendingClientRequestState(
            request_id=fs_request.id,
            kind="fs_read",
            tool_call_id=tool_call_id,
            path=target_path,
        )
        return PreparedFsClientRequest(
            kind="fs_read",
            messages=[created, fs_request],
            pending_request=pending,
        )

    if directives.fs_write_path is not None and directives.fs_write_content is not None:
        target_path = normalize_session_path(session.cwd, directives.fs_write_path)
        if target_path is None:
            return None
        tool_call_id = create_tool_call(
            session=session,
            title="Write text file",
            kind="edit",
        )
        created = ACPMessage.notification(
            "session/update",
            {
                "sessionId": session_id,
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": tool_call_id,
                    "title": "Write text file",
                    "kind": "edit",
                    "status": "pending",
                    "locations": [{"path": target_path}],
                },
            },
        )
        fs_request = ACPMessage.request(
            "fs/write_text_file",
            {
                "sessionId": session_id,
                "path": target_path,
                "content": directives.fs_write_content,
            },
        )
        if fs_request.id is None:
            return None
        pending = PendingClientRequestState(
            request_id=fs_request.id,
            kind="fs_write",
            tool_call_id=tool_call_id,
            path=target_path,
            expected_new_text=directives.fs_write_content,
        )
        return PreparedFsClientRequest(
            kind="fs_write",
            messages=[created, fs_request],
            pending_request=pending,
        )

    return None


def build_terminal_client_request(
    *,
    session: SessionState,
    session_id: str,
    directives: PromptDirectives,
) -> PreparedFsClientRequest | None:
    """Готовит исходящий terminal/create request и tool_call lifecycle.

    Возвращает структуру того же формата, что и fs-подготовка, чтобы
    использовать общий пайплайн pending client RPC.

    Пример использования:
        prepared = build_terminal_client_request(
            session=state,
            session_id="sess_1",
            directives=directives,
        )
    """

    if directives.terminal_command is None:
        return None

    tool_call_id = create_tool_call(
        session=session,
        title="Run terminal command",
        kind="execute",
    )
    created = ACPMessage.notification(
        "session/update",
        {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": tool_call_id,
                "title": "Run terminal command",
                "kind": "execute",
                "status": "pending",
                "rawInput": {
                    "command": directives.terminal_command,
                },
            },
        },
    )
    terminal_create_request = ACPMessage.request(
        "terminal/create",
        {
            "sessionId": session_id,
            "command": directives.terminal_command,
        },
    )
    if terminal_create_request.id is None:
        return None

    pending = PendingClientRequestState(
        request_id=terminal_create_request.id,
        kind="terminal_create",
        tool_call_id=tool_call_id,
        path=directives.terminal_command,
    )
    return PreparedFsClientRequest(
        kind="terminal_create",
        messages=[created, terminal_create_request],
        pending_request=pending,
    )


def normalize_session_path(cwd: str, candidate: str) -> str | None:
    """Преобразует путь из slash-команды в абсолютный путь в рамках cwd.

    Пример использования:
        path = normalize_session_path("/tmp", "README.md")
    """

    if not isinstance(candidate, str) or not candidate.strip():
        return None
    candidate_path = Path(candidate)
    if candidate_path.is_absolute():
        return str(candidate_path)
    return str(Path(cwd) / candidate_path)


def can_run_tool_runtime(session: SessionState) -> bool:
    """Проверяет, можно ли запускать tool-runtime ветки в текущем соединении.

    Пример использования:
        if can_run_tool_runtime(session):
            ...
    """

    caps = session.runtime_capabilities
    if caps is None:
        # До успешного initialize runtime-возможности не согласованы,
        # поэтому tool-runtime ветки должны оставаться выключенными.
        return False
    return caps.terminal or caps.fs_read or caps.fs_write


def can_use_fs_client_rpc(session: SessionState, kind: str) -> bool:
    """Проверяет доступность fs/* client RPC для указанной операции.

    Пример использования:
        enabled = can_use_fs_client_rpc(session, "fs_read")
    """

    caps = session.runtime_capabilities
    if caps is None:
        return False
    if kind == "fs_read":
        return caps.fs_read
    if kind == "fs_write":
        return caps.fs_write
    return False


def can_use_terminal_client_rpc(session: SessionState) -> bool:
    """Проверяет доступность terminal/* client RPC в текущем runtime.

    Пример использования:
        enabled = can_use_terminal_client_rpc(session)
    """

    caps = session.runtime_capabilities
    if caps is None:
        return False
    return caps.terminal


def create_tool_call(session: SessionState, *, title: str, kind: str) -> str:
    """Создает запись нового tool call в состоянии сессии.

    Пример использования:
        tool_call_id = create_tool_call(state, title="Demo", kind="other")
    """

    # Локально монотонный ID делает тесты предсказуемыми и читабельными.
    session.tool_call_counter += 1
    tool_call_id = f"call_{session.tool_call_counter:03d}"
    session.tool_calls[tool_call_id] = ToolCallState(
        tool_call_id=tool_call_id,
        title=title,
        kind=kind,
        status="pending",
    )
    return tool_call_id


def update_tool_call_status(
    session: SessionState,
    tool_call_id: str,
    status: str,
    *,
    content: list[dict[str, Any]] | None = None,
) -> None:
    """Обновляет статус tool call с проверкой допустимых переходов.

    Пример использования:
        update_tool_call_status(state, "call_001", "in_progress")
    """

    state = session.tool_calls.get(tool_call_id)
    if state is None:
        return

    # Явная матрица переходов защищает от нелегальных смен статуса.
    allowed_transitions: dict[str, set[str]] = {
        "pending": {"in_progress", "cancelled", "failed"},
        "in_progress": {"completed", "cancelled", "failed"},
        "completed": set(),
        "cancelled": set(),
        "failed": set(),
    }
    next_states = allowed_transitions.get(state.status, set())
    if status not in next_states and status != state.status:
        return

    state.status = status
    if content is not None:
        state.content = content


def cancel_active_tool_calls(session: SessionState, session_id: str) -> list[ACPMessage]:
    """Отменяет все незавершенные tool calls и формирует update-события.

    Пример использования:
        updates = cancel_active_tool_calls(state, "sess_1")
    """

    # Финальные статусы не трогаем, отменяем только активные вызовы.
    notifications: list[ACPMessage] = []
    for tool_call in session.tool_calls.values():
        if tool_call.status not in {"pending", "in_progress"}:
            continue
        update_tool_call_status(session, tool_call.tool_call_id, "cancelled")
        notifications.append(
            ACPMessage.notification(
                "session/update",
                {
                    "sessionId": session_id,
                    "update": {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": tool_call.tool_call_id,
                        "status": "cancelled",
                    },
                },
            )
        )
    return notifications


def finalize_active_turn(session: SessionState, *, stop_reason: str) -> ACPMessage | None:
    """Финализирует текущий active turn и очищает его состояние.

    Пример использования:
        response = finalize_active_turn(state, stop_reason="cancelled")
    """

    active_turn = session.active_turn
    if active_turn is None or active_turn.prompt_request_id is None:
        return None

    session.active_turn = None
    return ACPMessage.response(
        active_turn.prompt_request_id,
        {"stopReason": normalize_stop_reason(stop_reason)},
    )


async def find_session_by_pending_client_request_id(
    request_id: JsonRpcId,
    storage: SessionStorage,
) -> SessionState | None:
    """Ищет сессию по id ожидаемого agent->client запроса.

    Пример использования:
        session = await find_session_by_pending_client_request_id("req_1", storage)
    """
    sessions, _ = await storage.list_sessions(limit=500)
    for session in sessions:
        active_turn = session.active_turn
        if active_turn is None or active_turn.pending_client_request is None:
            continue
        if active_turn.pending_client_request.request_id == request_id:
            return session
    return None


def resolve_pending_client_rpc_response_impl(
    *,
    session: SessionState,
    request_id: JsonRpcId,
    result: Any,
    error: dict[str, Any] | None,
) -> ProtocolOutcome | None:
    """Реализация обработки response на ожидаемый agent->client fs/* request.

    Пример использования:
        outcome = resolve_pending_client_rpc_response_impl(
            session=session,
            request_id="req_1",
            result={"content": "ok"},
            error=None,
        )
    """

    if session.active_turn is None:
        return None
    pending = session.active_turn.pending_client_request
    if pending is None:
        return None

    session_id = session.session_id
    notifications: list[ACPMessage] = []

    if error is not None:
        error_message = error.get("message") if isinstance(error.get("message"), str) else ""
        failure_suffix = f": {error_message}" if error_message else ""
        return finalize_failed_client_rpc_request(
            session=session,
            session_id=session_id,
            tool_call_id=pending.tool_call_id,
            failure_text=f"Client RPC request failed{failure_suffix}",
        )

    if pending.kind == "fs_read":
        if not isinstance(result, dict) or not isinstance(result.get("content"), str):
            return finalize_failed_client_rpc_request(
                session=session,
                session_id=session_id,
                tool_call_id=pending.tool_call_id,
                failure_text="Invalid fs/read_text_file response.",
            )
        content_text = ""
        content_text = result["content"]
        update_tool_call_status(
            session,
            pending.tool_call_id,
            "completed",
            content=[
                {
                    "type": "content",
                    "content": {
                        "type": "text",
                        "text": content_text,
                    },
                }
            ],
        )
        notifications.append(
            ACPMessage.notification(
                "session/update",
                {
                    "sessionId": session_id,
                    "update": {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": pending.tool_call_id,
                        "status": "completed",
                        "content": [
                            {
                                "type": "content",
                                "content": {
                                    "type": "text",
                                    "text": content_text,
                                },
                            }
                        ],
                    },
                },
            )
        )
    elif pending.kind == "fs_write":
        if not isinstance(result, dict):
            return finalize_failed_client_rpc_request(
                session=session,
                session_id=session_id,
                tool_call_id=pending.tool_call_id,
                failure_text="Invalid fs/write_text_file response.",
            )
        old_text: str | None = None
        new_text = pending.expected_new_text or ""
        if isinstance(result.get("oldText"), str):
            old_text = result["oldText"]
        if isinstance(result.get("newText"), str):
            new_text = result["newText"]

        diff_content = [
            {
                "type": "diff",
                "path": pending.path,
                "oldText": old_text,
                "newText": new_text,
            }
        ]
        update_tool_call_status(
            session,
            pending.tool_call_id,
            "completed",
            content=diff_content,
        )
        notifications.append(
            ACPMessage.notification(
                "session/update",
                {
                    "sessionId": session_id,
                    "update": {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": pending.tool_call_id,
                        "status": "completed",
                        "content": diff_content,
                    },
                },
            )
        )
    elif pending.kind == "terminal_create":
        terminal_id = None
        if isinstance(result, dict) and isinstance(result.get("terminalId"), str):
            terminal_id = result["terminalId"]
        if terminal_id is None:
            update_tool_call_status(session, pending.tool_call_id, "failed")
            notifications.append(
                ACPMessage.notification(
                    "session/update",
                    {
                        "sessionId": session_id,
                        "update": {
                            "sessionUpdate": "tool_call_update",
                            "toolCallId": pending.tool_call_id,
                            "status": "failed",
                        },
                    },
                )
            )
            done = finalize_active_turn(session=session, stop_reason="end_turn")
            return ProtocolOutcome(
                notifications=notifications,
                followup_responses=[done] if done is not None else [],
            )

        update_tool_call_status(session, pending.tool_call_id, "in_progress")
        notifications.append(
            ACPMessage.notification(
                "session/update",
                {
                    "sessionId": session_id,
                    "update": {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": pending.tool_call_id,
                        "status": "in_progress",
                        "content": [{"type": "terminal", "terminalId": terminal_id}],
                    },
                },
            )
        )

        output_request = ACPMessage.request(
            "terminal/output",
            {
                "sessionId": session_id,
                "terminalId": terminal_id,
            },
        )
        if output_request.id is None:
            return None
        session.active_turn.pending_client_request = PendingClientRequestState(
            request_id=output_request.id,
            kind="terminal_output",
            tool_call_id=pending.tool_call_id,
            path=pending.path,
            terminal_id=terminal_id,
        )
        notifications.append(output_request)
        return ProtocolOutcome(notifications=notifications)
    elif pending.kind == "terminal_output":
        terminal_id = pending.terminal_id
        if terminal_id is None:
            return None
        if not isinstance(result, dict) or not isinstance(result.get("output"), str):
            return finalize_failed_client_rpc_request(
                session=session,
                session_id=session_id,
                tool_call_id=pending.tool_call_id,
                failure_text="Invalid terminal/output response.",
            )
        output_text = ""
        output_truncated = False
        output_exit_code: int | None = None
        output_signal: str | None = None
        output_text = result["output"]
        if isinstance(result.get("truncated"), bool):
            output_truncated = result["truncated"]
        raw_exit_status = result.get("exitStatus")
        has_exit_status = isinstance(raw_exit_status, dict)
        if raw_exit_status is not None and not has_exit_status:
            return finalize_failed_client_rpc_request(
                session=session,
                session_id=session_id,
                tool_call_id=pending.tool_call_id,
                failure_text="Invalid terminal/output response.",
            )
        if has_exit_status:
            if raw_exit_status.get("exitCode") is not None and not isinstance(
                raw_exit_status.get("exitCode"), int
            ):
                return finalize_failed_client_rpc_request(
                    session=session,
                    session_id=session_id,
                    tool_call_id=pending.tool_call_id,
                    failure_text="Invalid terminal/output response.",
                )
            if raw_exit_status.get("signal") is not None and not isinstance(
                raw_exit_status.get("signal"), str
            ):
                return finalize_failed_client_rpc_request(
                    session=session,
                    session_id=session_id,
                    tool_call_id=pending.tool_call_id,
                    failure_text="Invalid terminal/output response.",
                )
            if isinstance(raw_exit_status.get("exitCode"), int):
                output_exit_code = raw_exit_status["exitCode"]
            if isinstance(raw_exit_status.get("signal"), str):
                output_signal = raw_exit_status["signal"]

        # Если terminal/output уже содержит exitStatus, можно сразу release без wait_for_exit.
        if has_exit_status:
            release_request = ACPMessage.request(
                "terminal/release",
                {
                    "sessionId": session_id,
                    "terminalId": terminal_id,
                },
            )
            if release_request.id is None:
                return None
            session.active_turn.pending_client_request = PendingClientRequestState(
                request_id=release_request.id,
                kind="terminal_release",
                tool_call_id=pending.tool_call_id,
                path=pending.path,
                terminal_id=terminal_id,
                terminal_output=output_text,
                terminal_exit_code=output_exit_code,
                terminal_signal=output_signal,
                terminal_truncated=output_truncated,
            )
            notifications.append(release_request)
            return ProtocolOutcome(notifications=notifications)

        wait_request = ACPMessage.request(
            "terminal/wait_for_exit",
            {
                "sessionId": session_id,
                "terminalId": terminal_id,
            },
        )
        if wait_request.id is None:
            return None
        session.active_turn.pending_client_request = PendingClientRequestState(
            request_id=wait_request.id,
            kind="terminal_wait_for_exit",
            tool_call_id=pending.tool_call_id,
            path=pending.path,
            terminal_id=terminal_id,
            terminal_output=output_text,
            terminal_truncated=output_truncated,
        )
        notifications.append(wait_request)
        return ProtocolOutcome(notifications=notifications)
    elif pending.kind == "terminal_wait_for_exit":
        terminal_id = pending.terminal_id
        if terminal_id is None:
            return None
        if not isinstance(result, dict):
            return finalize_failed_client_rpc_request(
                session=session,
                session_id=session_id,
                tool_call_id=pending.tool_call_id,
                failure_text="Invalid terminal/wait_for_exit response.",
            )
        exit_code = None
        signal: str | None = None
        if isinstance(result.get("exitCode"), int):
            exit_code = result["exitCode"]
        if isinstance(result.get("signal"), str):
            signal = result["signal"]

        release_request = ACPMessage.request(
            "terminal/release",
            {
                "sessionId": session_id,
                "terminalId": terminal_id,
            },
        )
        if release_request.id is None:
            return None
        session.active_turn.pending_client_request = PendingClientRequestState(
            request_id=release_request.id,
            kind="terminal_release",
            tool_call_id=pending.tool_call_id,
            path=pending.path,
            terminal_id=terminal_id,
            terminal_output=pending.terminal_output,
            terminal_exit_code=exit_code,
            terminal_signal=signal,
            terminal_truncated=pending.terminal_truncated,
        )
        notifications.append(release_request)
        return ProtocolOutcome(notifications=notifications)
    elif pending.kind == "terminal_release":
        terminal_id = pending.terminal_id
        if terminal_id is None:
            return None
        if not isinstance(result, dict):
            return finalize_failed_client_rpc_request(
                session=session,
                session_id=session_id,
                tool_call_id=pending.tool_call_id,
                failure_text="Invalid terminal/release response.",
            )
        completion_text = f"Terminal command finished with exit code {pending.terminal_exit_code}."
        if pending.terminal_exit_code is None:
            completion_text = "Terminal command finished."
        if pending.terminal_signal is not None:
            completion_text = f"{completion_text} Signal: {pending.terminal_signal}."
        if pending.terminal_truncated:
            completion_text = f"{completion_text} Output was truncated."
        if pending.terminal_output:
            completion_text = f"{completion_text} Output: {pending.terminal_output}"

        completed_content = [
            {
                "type": "terminal",
                "terminalId": terminal_id,
            },
            {
                "type": "content",
                "content": {
                    "type": "text",
                    "text": completion_text,
                },
            },
        ]
        update_tool_call_status(
            session,
            pending.tool_call_id,
            "completed",
            content=completed_content,
        )
        notifications.append(
            ACPMessage.notification(
                "session/update",
                {
                    "sessionId": session_id,
                    "update": {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": pending.tool_call_id,
                        "status": "completed",
                        "content": completed_content,
                        "rawOutput": {
                            "exitCode": pending.terminal_exit_code,
                            "signal": pending.terminal_signal,
                            "truncated": pending.terminal_truncated,
                        },
                    },
                },
            )
        )
    else:
        return None

    session.active_turn.pending_client_request = None
    session.updated_at = datetime.now(UTC).isoformat()
    notifications.append(
        session_info_notification(
            session_id=session_id,
            title=None,
            updated_at=session.updated_at,
        )
    )
    completed = finalize_active_turn(session=session, stop_reason="end_turn")
    return ProtocolOutcome(
        notifications=notifications,
        followup_responses=[completed] if completed is not None else [],
    )


def finalize_failed_client_rpc_request(
    *,
    session: SessionState,
    session_id: str,
    tool_call_id: str,
    failure_text: str,
) -> ProtocolOutcome:
    """Финализирует prompt-turn после неуспешного или невалидного client RPC.

    Пример использования:
        return finalize_failed_client_rpc_request(
            session=state,
            session_id="sess_1",
            tool_call_id="call_1",
            failure_text="Invalid terminal/output response.",
        )
    """

    update_tool_call_status(session, tool_call_id, "failed")
    failure_notification = ACPMessage.notification(
        "session/update",
        {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": tool_call_id,
                "status": "failed",
                "content": [
                    {
                        "type": "content",
                        "content": {
                            "type": "text",
                            "text": failure_text,
                        },
                    }
                ],
            },
        },
    )
    session.updated_at = datetime.now(UTC).isoformat()
    session_info = session_info_notification(
        session_id=session_id,
        title=None,
        updated_at=session.updated_at,
    )
    failed = finalize_active_turn(session=session, stop_reason="end_turn")
    return ProtocolOutcome(
        notifications=[failure_notification, session_info],
        followup_responses=[failed] if failed is not None else [],
    )


def resolve_permission_response_impl(
    *,
    session: SessionState,
    permission_request_id: JsonRpcId,
    result: Any,
) -> ProtocolOutcome | None:
    """Реализация применения решения по permission-request к активному prompt-turn.

    Пример использования:
        outcome = resolve_permission_response_impl(
            session=session,
            permission_request_id="perm_1",
            result={"outcome": {"outcome": "selected", "optionId": "allow_once"}},
        )
    """

    from .permissions import (
        extract_permission_option_id,
        extract_permission_outcome,
        resolve_permission_option_kind,
    )

    if session.active_turn is None:
        return None
    tool_call_id = session.active_turn.permission_tool_call_id
    if tool_call_id is None:
        return None

    session_id = session.session_id
    notifications: list[ACPMessage] = []
    outcome_value = extract_permission_outcome(result)
    selected_option = extract_permission_option_id(result)
    selected_option_id = selected_option if isinstance(selected_option, str) else None
    selected_option_kind = resolve_permission_option_kind(
        selected_option_id, build_permission_options()
    )

    session.active_turn.permission_request_id = None
    session.active_turn.permission_tool_call_id = None

    tool_call_state = session.tool_calls.get(tool_call_id)
    tool_kind = tool_call_state.kind if tool_call_state is not None else None

    if tool_kind is not None and selected_option_kind in {"allow_always", "reject_always"}:
        # Сохраняем policy-решение для следующих tool-call этого же kind.
        session.permission_policy[tool_kind] = selected_option_kind

    should_allow = bool(
        outcome_value == "selected" and selected_option_kind in {"allow_once", "allow_always"}
    )
    if not should_allow:
        notifications.extend(
            build_policy_tool_execution_updates(
                session=session,
                session_id=session_id,
                tool_call_id=tool_call_id,
                allowed=False,
            )
        )
        session.updated_at = datetime.now(UTC).isoformat()
        notifications.append(
            session_info_notification(
                session_id=session_id,
                title=None,
                updated_at=session.updated_at,
            )
        )
        cancelled = finalize_active_turn(session=session, stop_reason="cancelled")
        return ProtocolOutcome(
            notifications=notifications,
            followup_responses=[cancelled] if cancelled is not None else [],
        )

    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Когда permission allowed, отправить notifications
    # и завершить turn с end_turn. Tool execution будет выполнен внутри session_prompt().
    notifications.extend(
        build_policy_tool_execution_updates(
            session=session,
            session_id=session_id,
            tool_call_id=tool_call_id,
            allowed=True,
        )
    )

    session.updated_at = datetime.now(UTC).isoformat()
    notifications.append(
        session_info_notification(
            session_id=session_id,
            title=None,
            updated_at=session.updated_at,
        )
    )
    
    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Не завершаем turn, а сигнализируем о pending tool execution
    # http_server.py выполнит tool асинхронно и затем завершит turn
    logger.debug(
        "permission allowed, scheduling tool execution",
        session_id=session_id,
        tool_call_id=tool_call_id,
    )
    
    return ProtocolOutcome(
        notifications=notifications,
        followup_responses=[],
        pending_tool_execution=PendingToolExecution(
            session_id=session_id,
            tool_call_id=tool_call_id,
        ),
    )
