"""Обработчики методов управления сессиями.

Содержит логику обработки session/new, session/load, session/list.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import structlog

from ...messages import ACPMessage, JsonRpcId
from ...storage import SessionStorage
from ..session_factory import SessionFactory
from ..state import ClientRuntimeCapabilities, ProtocolOutcome, SessionState
from .replay_manager import ReplayManager

# Используем structlog для структурированного логирования
logger = structlog.get_logger()


def _serialize_available_commands(
    commands: list,
) -> list[dict[str, Any]]:
    """Сериализует список available_commands для JSON.

    Преобразует Pydantic модели в dict для JSON сериализации.
    """
    result: list[dict[str, Any]] = []
    for cmd in commands:
        if isinstance(cmd, dict):
            result.append(cmd)
        elif hasattr(cmd, "model_dump"):
            result.append(cmd.model_dump(exclude_none=False))
        else:
            result.append(cmd)
    return result


def _cleanup_session_state(session: SessionState) -> None:
    """Очищает незавершенные операции при переключении сессии.

    Выполняет следующие действия для безопасного переключения:
    1. Отменяет active turn, если он активен
    2. Отмечает все pending tool calls как cancelled
    3. Добавляет permission request IDs в cancelled_permission_requests
    4. Добавляет RPC request IDs в cancelled_client_rpc_requests

    Аргументы:
        session: SessionState для очистки.

    Пример использования:
        _cleanup_session_state(session)
    """
    # Завершить active turn
    if session.active_turn is not None:
        session.active_turn.cancel_requested = True
        session.active_turn.phase = "cancelled"

        # Если был permission request, отменить его
        if session.active_turn.permission_request_id is not None:
            session.cancelled_permission_requests.add(session.active_turn.permission_request_id)

        # Если был pending client request, отменить его
        if session.active_turn.pending_client_request is not None:
            session.cancelled_client_rpc_requests.add(
                session.active_turn.pending_client_request.request_id
            )

        session.active_turn = None

    # Отметить все pending tool calls как cancelled
    for _tool_call_id, tool_call in session.tool_calls.items():
        if tool_call.status == "pending":
            tool_call.status = "cancelled"


def session_new(
    request_id: JsonRpcId | None,
    params: dict[str, Any],
    require_auth: bool,
    authenticated: bool,
    config_specs: dict[str, dict[str, Any]],
    auth_methods: list[dict[str, Any]],
    runtime_capabilities: ClientRuntimeCapabilities | None,
) -> ACPMessage:
    """Создает новую in-memory сессию и возвращает ее идентификатор.

    Метод валидирует `cwd`, инициализирует config options и дефолтные
    slash-команды.

    Пример использования:
        response = session_new(
            "req_1", {"cwd": "/tmp", "mcpServers": []}, False, True, {}, [], None
        )
    """

    if require_auth and not authenticated:
        return ACPMessage.error_response(
            request_id,
            code=-32010,
            message="auth_required",
            data={"authMethods": auth_methods},
        )

    # По спецификации cwd должен быть абсолютным путем.
    cwd = params.get("cwd")
    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
        return ACPMessage.error_response(
            request_id,
            code=-32602,
            message="Invalid params: cwd must be an absolute path",
        )

    mcp_servers = params.get("mcpServers", [])
    if not isinstance(mcp_servers, list):
        return ACPMessage.error_response(
            request_id,
            code=-32602,
            message="Invalid params: mcpServers must be an array",
        )

    # Создаем сессию через фабрику
    config_values = {config_id: str(spec["default"]) for config_id, spec in config_specs.items()}

    session_state = SessionFactory.create_session(
        cwd=cwd,
        mcp_servers=mcp_servers,
        config_values=config_values,
        available_commands=build_default_commands(),
        runtime_capabilities=runtime_capabilities,
    )

    return ACPMessage.response(
        request_id,
        {
            "sessionId": session_state.session_id,
            "configOptions": build_config_options(config_values, config_specs),
            "modes": build_modes_state(config_values, config_specs),
        },
    )


async def session_load(
    request_id: JsonRpcId | None,
    params: dict[str, Any],
    require_auth: bool,
    authenticated: bool,
    config_specs: dict[str, dict[str, Any]],
    auth_methods: list[dict[str, Any]],
    storage: SessionStorage,
) -> ProtocolOutcome:
    """Загружает существующую сессию и реплеит состояние через updates.

    Возвращает `result: null` и набор `session/update` уведомлений:
    история сообщений, config options, команды и session info.

    Пример использования:
        outcome = await session_load(
            "req_1",
            {"sessionId": "sess_1", "cwd": "/tmp", "mcpServers": []},
            False,
            True,
            {},
            [],
            storage,
        )
    """

    if require_auth and not authenticated:
        return ProtocolOutcome(
            response=ACPMessage.error_response(
                request_id,
                code=-32010,
                message="auth_required",
                data={"authMethods": auth_methods},
            )
        )

    # Загрузка поддерживает in-memory сессии и реплей накопленной истории в `session/update`.
    session_id = params.get("sessionId")
    cwd = params.get("cwd")
    mcp_servers = params.get("mcpServers")

    if not isinstance(session_id, str):
        return ProtocolOutcome(
            response=ACPMessage.error_response(
                request_id,
                code=-32602,
                message="Invalid params: sessionId is required",
            )
        )
    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
        return ProtocolOutcome(
            response=ACPMessage.error_response(
                request_id,
                code=-32602,
                message="Invalid params: cwd must be an absolute path",
            )
        )
    if not isinstance(mcp_servers, list):
        return ProtocolOutcome(
            response=ACPMessage.error_response(
                request_id,
                code=-32602,
                message="Invalid params: mcpServers must be an array",
            )
        )

    session = await storage.load_session(session_id)
    if session is None:
        return ProtocolOutcome(
            response=ACPMessage.error_response(
                request_id,
                code=-32001,
                message=f"Session not found: {session_id}",
            )
        )

    # Очистить незавершенные операции перед переключением контекста.
    # Это предотвращает race conditions и утечки памяти при переключении сессий.
    _cleanup_session_state(session)

    # При загрузке фиксируем актуальный контекст клиента.
    session.cwd = cwd
    session.mcp_servers = [server for server in mcp_servers if isinstance(server, dict)]

    notifications: list[ACPMessage] = []

    # Используем ReplayManager для воспроизведения истории session/update уведомлений
    # согласно спецификации ACP (protocol/03-Session Setup.md, раздел 132):
    # "The Agent MUST replay the entire conversation to the Client
    # in the form of session/update notifications"
    replay_manager = ReplayManager()
    history_notifications = replay_manager.replay_history(session)
    notifications.extend(history_notifications)

    # Реплеим latest_plan если он есть и не был в events_history
    plan_notification = replay_manager.replay_latest_plan(session)
    if plan_notification:
        notifications.append(plan_notification)

    # Fallback: реплеим tool calls из session.tool_calls если они не были в events_history
    # Это обеспечивает обратную совместимость с сессиями, созданными до внедрения
    # сохранения tool_call событий в events_history
    has_tool_call_events = any(
        event.get("type") == "session_update"
        and event.get("update", {}).get("sessionUpdate") == "tool_call"
        for event in session.events_history
    )
    if not has_tool_call_events and session.tool_calls:
        for tool_call in session.tool_calls.values():
            notifications.append(
                ACPMessage.notification(
                    "session/update",
                    {
                        "sessionId": session_id,
                        "update": {
                            "sessionUpdate": "tool_call",
                            "toolCallId": tool_call.tool_call_id,
                            "title": tool_call.title,
                            "kind": tool_call.kind,
                            "status": "pending",
                        },
                    },
                )
            )
            if tool_call.status != "pending":
                update_payload: dict[str, Any] = {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": tool_call.tool_call_id,
                    "status": tool_call.status,
                }
                if tool_call.content:
                    update_payload["content"] = tool_call.content
                notifications.append(
                    ACPMessage.notification(
                        "session/update",
                        {
                            "sessionId": session_id,
                            "update": update_payload,
                        },
                    )
                )

    notifications.append(
        ACPMessage.notification(
            "session/update",
            {
                "sessionId": session_id,
                "update": {
                    "sessionUpdate": "config_option_update",
                    "configOptions": build_config_options(session.config_values, config_specs),
                },
            },
        )
    )
    notifications.append(
        ACPMessage.notification(
            "session/update",
            {
                "sessionId": session_id,
                "update": {
                    "sessionUpdate": "available_commands_update",
                    "availableCommands": _serialize_available_commands(session.available_commands),
                },
            },
        )
    )
    notifications.append(
        session_info_notification(
            session_id=session_id,
            title=session.title,
            updated_at=session.updated_at,
        )
    )

    return ProtocolOutcome(
        response=ACPMessage.response(
            request_id,
            {
                "configOptions": build_config_options(session.config_values, config_specs),
                "modes": build_modes_state(session.config_values, config_specs),
            },
        ),
        notifications=notifications,
    )


async def session_list(
    request_id: JsonRpcId | None,
    params: dict[str, Any],
    storage: SessionStorage,
    session_list_page_size: int = 50,
) -> ACPMessage:
    """Возвращает список сессий с опциональной фильтрацией по `cwd`.

    Пример использования:
        response = await session_list("req_1", {"cwd": "/tmp"}, storage)
    """

    # Поддерживаем фильтрацию сессий по cwd для клиентских списков.
    cwd_filter = params.get("cwd")
    cursor = params.get("cursor")
    if cwd_filter is not None and (
        not isinstance(cwd_filter, str) or not Path(cwd_filter).is_absolute()
    ):
        return ACPMessage.error_response(
            request_id,
            code=-32602,
            message="Invalid params: cwd must be an absolute path",
        )
    if cursor is not None and not isinstance(cursor, str):
        return ACPMessage.error_response(
            request_id,
            code=-32602,
            message="Invalid params: cursor must be a string",
        )

    start_index = 0
    if isinstance(cursor, str):
        decoded = decode_session_cursor(cursor)
        if decoded is None:
            return ACPMessage.error_response(
                request_id,
                code=-32602,
                message="Invalid params: cursor is invalid",
            )
        start_index = decoded

    # Загружаем сессии через storage с пагинацией
    sessions_list: list[dict[str, Any]] = []
    storage_cursor = None
    while True:
        page, next_cursor = await storage.list_sessions(
            cwd=cwd_filter if isinstance(cwd_filter, str) else None,
            cursor=storage_cursor,
            limit=100,
        )
        for session in page:
            sessions_list.append(
                {
                    "sessionId": session.session_id,
                    "cwd": session.cwd,
                    "title": session.title,
                    "updatedAt": session.updated_at,
                }
            )
        if next_cursor is None:
            break
        storage_cursor = next_cursor

    sorted_sessions = sorted(
        sessions_list, key=lambda item: str(item.get("updatedAt") or ""), reverse=True
    )
    page_end = start_index + session_list_page_size
    page = sorted_sessions[start_index:page_end]
    next_cursor: str | None = None
    if page_end < len(sorted_sessions):
        next_cursor = encode_session_cursor(page_end)

    return ACPMessage.response(request_id, {"sessions": page, "nextCursor": next_cursor})


def encode_session_cursor(index: int) -> str:
    """Кодирует индекс страницы в opaque cursor для `session/list`.

    Пример использования:
        cursor = encode_session_cursor(50)
    """

    payload = json.dumps({"index": index}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def decode_session_cursor(cursor: str) -> int | None:
    """Декодирует opaque cursor `session/list` в индекс начала страницы.

    Возвращает `None`, если cursor поврежден или невалиден.

    Пример использования:
        index = decode_session_cursor(cursor)
    """

    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    index = payload.get("index")
    if not isinstance(index, int) or index < 0:
        return None
    return index


def build_modes_state(
    values: dict[str, str],
    config_specs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Строит legacy-состояние modes для совместимых клиентов ACP.

    Пример использования:
        modes = build_modes_state({"mode": "ask", "model": "baseline"}, specs)
    """

    mode_option = config_specs.get("mode", {})
    available_modes = []
    for option in mode_option.get("options", []):
        if isinstance(option, dict) and isinstance(option.get("value"), str):
            available_modes.append(
                {
                    "id": option["value"],
                    "name": option.get("name", option["value"]),
                    "description": option.get("description"),
                }
            )

    return {
        "availableModes": available_modes,
        "currentModeId": values.get("mode", str(mode_option.get("default", "ask"))),
    }


def build_config_options(
    values: dict[str, str],
    config_specs: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Строит wire-представление списка config options для клиента.

    Пример использования:
        options = build_config_options({"mode": "ask", "model": "baseline"}, specs)
    """

    options: list[dict[str, Any]] = []
    for config_id, spec in config_specs.items():
        options.append(
            {
                "id": config_id,
                "name": spec["name"],
                "category": spec["category"],
                "type": "select",
                "currentValue": values.get(config_id, spec["default"]),
                "options": spec["options"],
            }
        )
    return options


def session_info_notification(
    *,
    session_id: str,
    title: str | None,
    updated_at: str,
) -> ACPMessage:
    """Создает notification `session_info_update` для `session/update`.

    Пример использования:
        note = session_info_notification(
            session_id="sess_1",
            title="My session",
            updated_at="2026-04-07T00:00:00Z",
        )
    """

    return ACPMessage.notification(
        "session/update",
        {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "session_info_update",
                "title": title,
                "updatedAt": updated_at,
            },
        },
    )


def build_default_commands() -> list[dict[str, Any]]:
    """Возвращает базовый набор команд для сессий.

    Возвращает список встроенных slash-команд в формате, соответствующем
    спецификации ACP Protocol 14-Slash Commands.

    Пример использования:
        commands = build_default_commands()
    """
    # Встроенные slash-команды согласно спецификации ACP Protocol.
    # Формат соответствует AvailableCommand: name, description, input? (с hint).
    return [
        {
            "name": "status",
            "description": "Показать состояние текущей сессии",
        },
        {
            "name": "mode",
            "description": "Показать или изменить режим сессии",
            "input": {"hint": "имя режима (code, architect, ask, debug)"},
        },
        {
            "name": "help",
            "description": "Показать список доступных команд",
            "input": {"hint": "имя команды для подробной справки"},
        },
    ]
