"""Обработчики методов управления разрешениями.

Содержит логику обработки session/request_permission и related.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...messages import JsonRpcId
from ...storage import SessionStorage
from ..state import SessionState

if TYPE_CHECKING:
    from .global_policy_manager import GlobalPolicyManager


async def find_session_by_permission_request_id(
    permission_request_id: JsonRpcId,
    storage: SessionStorage,
) -> SessionState | None:
    """Ищет сессию с активным turn, ожидающим ответ по permission-request.

    Пример использования:
        session = await find_session_by_permission_request_id("perm_1", storage)
    """
    cursor = None
    while True:
        page, cursor = await storage.list_sessions(cursor=cursor, limit=100)
        for session in page:
            active_turn = session.active_turn
            if active_turn is None:
                continue
            if active_turn.permission_request_id == permission_request_id:
                return session
        if cursor is None:
            return None


def extract_permission_outcome(result: Any) -> str | None:
    """Извлекает outcome из `session/request_permission` response.

    Поддерживает текущий ACP shape (`{"outcome": {"outcome": ...}}`) и
    legacy-вариант (`{"outcome": ...}`) для обратной совместимости.

    Пример использования:
        outcome = extract_permission_outcome(
            {"outcome": {"outcome": "selected", "optionId": "allow_once"}},
        )
    """

    if not isinstance(result, dict):
        return None

    nested_outcome = result.get("outcome")
    if isinstance(nested_outcome, dict):
        raw_value = nested_outcome.get("outcome")
        if isinstance(raw_value, str):
            return raw_value

    # Legacy fallback для старых клиентов.
    if isinstance(nested_outcome, str):
        return nested_outcome
    return None


def extract_permission_option_id(result: Any) -> str | None:
    """Извлекает `optionId` из `session/request_permission` response.

    Поддерживает ACP shape (`{"outcome": {"optionId": ...}}`) и legacy
    (`{"optionId": ...}`) формат для обратной совместимости.

    Пример использования:
        option_id = extract_permission_option_id(
            {"outcome": {"outcome": "selected", "optionId": "allow_once"}},
        )
    """

    if not isinstance(result, dict):
        return None

    nested_outcome = result.get("outcome")
    if isinstance(nested_outcome, dict):
        raw_option_id = nested_outcome.get("optionId")
        if isinstance(raw_option_id, str):
            return raw_option_id

    raw_option_id = result.get("optionId")
    if isinstance(raw_option_id, str):
        return raw_option_id
    return None


def resolve_permission_option_kind(
    option_id: str | None,
    permission_options: list[dict[str, Any]],
) -> str | None:
    """Возвращает kind permission-опции по ее `optionId`.

    Пример использования:
        kind = resolve_permission_option_kind("allow_once", options)
    """

    if option_id is None:
        return None
    for option in permission_options:
        if not isinstance(option, dict):
            continue
        if option.get("optionId") != option_id:
            continue
        kind_value = option.get("kind")
        if isinstance(kind_value, str):
            return kind_value
        return None
    return None


async def resolve_remembered_permission_decision(
    *,
    session: SessionState,
    tool_kind: str,
    global_manager: GlobalPolicyManager | None = None,
) -> str:
    """Возвращает применяемое policy-решение для tool kind с fallback chain.

    Fallback chain:
    1. Session policy (session.permission_policy)
    2. Global policy (global_manager.get_global_policy) если global_manager передан
    3. Ask user (default)

    Возвращаемые значения:
    - `allow`: выполнить tool-call без запроса permission.
    - `reject`: отклонить tool-call без запроса permission.
    - `ask`: запросить решение у клиента через `session/request_permission`.

    Args:
        session: Текущая сессия
        tool_kind: Тип инструмента (execute, read, write, etc.)
        global_manager: Optional GlobalPolicyManager для fallback на global policies

    Пример использования:
        decision = await resolve_remembered_permission_decision(
            session=state,
            tool_kind="execute",
            global_manager=manager,
        )
    """

    # 1. Check session policy
    session_decision = session.permission_policy.get(tool_kind)
    if session_decision is not None:
        if session_decision == "allow_always":
            return "allow"
        if session_decision == "reject_always":
            return "reject"

    # 2. Check global policy (if manager provided)
    if global_manager is not None:
        global_decision = await global_manager.get_global_policy(tool_kind)
        if global_decision is not None:
            if global_decision == "allow_always":
                return "allow"
            if global_decision == "reject_always":
                return "reject"

    # 3. Default: ask user
    return "ask"


def build_permission_options() -> list[dict[str, Any]]:
    """Возвращает варианты решения для `session/request_permission`.

    Пример использования:
        options = build_permission_options()
    """

    return [
        {
            "optionId": "allow_once",
            "name": "Allow once",
            "kind": "allow_once",
        },
        {
            "optionId": "allow_always",
            "name": "Always allow this tool",
            "kind": "allow_always",
        },
        {
            "optionId": "reject_once",
            "name": "Reject once",
            "kind": "reject_once",
        },
        {
            "optionId": "reject_always",
            "name": "Always reject this tool",
            "kind": "reject_always",
        },
    ]


async def consume_cancelled_permission_response(
    request_id: JsonRpcId,
    storage: SessionStorage,
) -> bool:
    """Поглощает late-response на ранее отмененный permission-request.

    Возвращает `True`, если идентификатор найден в canceled-tombstones и
    удален; иначе `False`.

    Пример использования:
        if await consume_cancelled_permission_response("perm_1", storage):
            ...
    """
    cursor = None
    while True:
        page, cursor = await storage.list_sessions(cursor=cursor, limit=100)
        for session in page:
            if request_id not in session.cancelled_permission_requests:
                continue
            session.cancelled_permission_requests.remove(request_id)
            await storage.save_session(session)
            return True
        if cursor is None:
            return False


async def find_session_with_cancelled_permission(
    request_id: JsonRpcId,
    storage: SessionStorage,
) -> SessionState | None:
    """Ищет сессию с отменённым permission request в tombstones.

    Пример использования:
        session = await find_session_with_cancelled_permission("perm_1", storage)
    """
    cursor = None
    while True:
        page, cursor = await storage.list_sessions(cursor=cursor, limit=100)
        for session in page:
            if request_id in session.cancelled_permission_requests:
                return session
        if cursor is None:
            return None


async def consume_cancelled_client_rpc_response(
    request_id: JsonRpcId,
    storage: SessionStorage,
) -> bool:
    """Поглощает late-response на ранее отмененный agent->client RPC.

    Возвращает `True`, если идентификатор найден в canceled-tombstones и
    удален; иначе `False`.

    Пример использования:
        if await consume_cancelled_client_rpc_response("rpc_1", storage):
            ...
    """
    cursor = None
    while True:
        page, cursor = await storage.list_sessions(cursor=cursor, limit=100)
        for session in page:
            if request_id not in session.cancelled_client_rpc_requests:
                continue
            session.cancelled_client_rpc_requests.remove(request_id)
            await storage.save_session(session)
            return True
        if cursor is None:
            return False
