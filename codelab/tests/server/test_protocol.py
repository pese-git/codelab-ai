import asyncio

import pytest

from codelab.server.client_rpc import ClientRPCService
from codelab.server.messages import ACPMessage
from codelab.server.protocol import ACPProtocol
from codelab.server.storage import JsonFileStorage


async def _initialize_with_tool_runtime(protocol: ACPProtocol) -> None:
    """Инициализирует протокол с включенным tool-runtime capability profile."""

    init = await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": True,
                },
            },
        )
    )
    assert init.response is not None
    assert init.response.error is None


@pytest.mark.asyncio
async def test_initialize_request() -> None:
    protocol = ACPProtocol()
    request = ACPMessage.request(
        "initialize",
        {
            "protocolVersion": 1,
            "clientCapabilities": {},
        },
    )

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    assert outcome.response.error is None
    assert outcome.response.result is not None
    assert outcome.response.result["protocolVersion"] == 1


@pytest.mark.asyncio
async def test_handle_client_response_routes_pending_client_rpc_service_response() -> None:
    """Проверяет routing ответа в ClientRPCService для async tool-вызова."""

    sent_requests: list[dict[str, object]] = []

    async def send_request(request: dict[str, object]) -> None:
        sent_requests.append(request)

    client_rpc_service = ClientRPCService(
        send_request_callback=send_request,
        client_capabilities={
            "fs": {"readTextFile": True, "writeTextFile": True},
            "terminal": True,
        },
        timeout=1.0,
    )
    protocol = ACPProtocol(client_rpc_service=client_rpc_service)

    read_task = asyncio.create_task(client_rpc_service.read_text_file("sess_1", "README.md"))
    await asyncio.sleep(0.01)

    assert len(sent_requests) == 1
    request_id = sent_requests[0]["id"]
    assert isinstance(request_id, str)

    outcome = await protocol.handle_client_response(
        ACPMessage.response(request_id, {"content": "ok"})
    )

    assert outcome.response is None
    assert outcome.notifications == []
    assert outcome.followup_responses == []
    assert await read_task == "ok"


@pytest.mark.asyncio
async def test_initialize_returns_auth_methods_when_auth_is_required() -> None:
    protocol = ACPProtocol(require_auth=True)
    request = ACPMessage.request(
        "initialize",
        {
            "protocolVersion": 1,
            "clientCapabilities": {},
        },
    )

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    assert outcome.response.error is None
    assert isinstance(outcome.response.result, dict)
    assert isinstance(outcome.response.result.get("authMethods"), list)
    assert len(outcome.response.result["authMethods"]) == 1


@pytest.mark.asyncio
async def test_session_new_requires_authentication_when_enabled() -> None:
    protocol = ACPProtocol(require_auth=True)

    outcome = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )

    assert outcome.response is not None
    assert outcome.response.error is not None
    assert outcome.response.error.message == "auth_required"


@pytest.mark.asyncio
async def test_authenticate_allows_session_creation_when_auth_enabled() -> None:
    protocol = ACPProtocol(require_auth=True)
    init = await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {},
            },
        )
    )
    assert init.response is not None
    assert isinstance(init.response.result, dict)
    auth_methods = init.response.result["authMethods"]
    assert isinstance(auth_methods, list)
    method_id = auth_methods[0]["id"]

    authenticated = await protocol.handle(
        ACPMessage.request("authenticate", {"methodId": method_id})
    )
    assert authenticated.response is not None
    assert authenticated.response.error is None

    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert created.response.error is None


@pytest.mark.asyncio
async def test_authenticate_requires_api_key_when_server_has_auth_backend() -> None:
    protocol = ACPProtocol(require_auth=True, auth_api_key="top-secret")
    init = await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {},
            },
        )
    )
    assert init.response is not None
    assert isinstance(init.response.result, dict)
    method_id = init.response.result["authMethods"][0]["id"]

    missing_key = await protocol.handle(ACPMessage.request("authenticate", {"methodId": method_id}))
    assert missing_key.response is not None
    assert missing_key.response.error is not None
    assert missing_key.response.error.message == "Invalid params: apiKey is required"

    wrong_key = await protocol.handle(
        ACPMessage.request(
            "authenticate",
            {
                "methodId": method_id,
                "apiKey": "bad-key",
            },
        )
    )
    assert wrong_key.response is not None
    assert wrong_key.response.error is not None
    assert wrong_key.response.error.message == "auth_failed"

    authenticated = await protocol.handle(
        ACPMessage.request(
            "authenticate",
            {
                "methodId": method_id,
                "apiKey": "top-secret",
            },
        )
    )
    assert authenticated.response is not None
    assert authenticated.response.error is None


@pytest.mark.asyncio
async def test_initialize_negotiates_to_supported_version() -> None:
    protocol = ACPProtocol()
    request = ACPMessage.request(
        "initialize",
        {
            "protocolVersion": 999,
            "clientCapabilities": {},
        },
    )

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    assert outcome.response.error is None
    assert outcome.response.result is not None
    assert outcome.response.result["protocolVersion"] == 1


@pytest.mark.asyncio
async def test_initialize_rejects_non_integer_protocol_version() -> None:
    protocol = ACPProtocol()
    request = ACPMessage.request(
        "initialize",
        {
            "protocolVersion": "1",
            "clientCapabilities": {},
        },
    )

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    assert outcome.response.error is not None
    assert outcome.response.error.code == -32602


@pytest.mark.asyncio
async def test_initialize_requires_client_capabilities_object() -> None:
    protocol = ACPProtocol()
    request = ACPMessage.request("initialize", {"protocolVersion": 1})

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    assert outcome.response.error is not None
    assert outcome.response.error.code == -32602


@pytest.mark.asyncio
async def test_initialize_requires_protocol_version_field() -> None:
    protocol = ACPProtocol()
    request = ACPMessage.request("initialize", {"clientCapabilities": {}})

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    assert outcome.response.error is not None
    assert outcome.response.error.code == -32602


@pytest.mark.asyncio
async def test_unknown_method() -> None:
    protocol = ACPProtocol()
    request = ACPMessage.request("missing", {})

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    assert outcome.response.error is not None
    assert outcome.response.error.code == -32601


@pytest.mark.asyncio
async def test_session_prompt_sends_update() -> None:
    protocol = ACPProtocol()

    new_session = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert new_session.response is not None
    assert isinstance(new_session.response.result, dict)
    session_id = new_session.response.result["sessionId"]

    outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "hello"}],
            },
        )
    )

    assert outcome.response is not None
    assert outcome.response.result == {"stopReason": "end_turn"}
    update_types = [
        notification.params["update"]["sessionUpdate"]
        for notification in outcome.notifications
        if notification.params is not None
    ]
    assert "agent_message_chunk" in update_types
    assert "session_info_update" in update_types
    assert "available_commands_update" in update_types


@pytest.mark.asyncio
async def test_prompt_with_plan_slash_command_emits_plan_update() -> None:
    protocol = ACPProtocol()

    new_session = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert new_session.response is not None
    assert isinstance(new_session.response.result, dict)
    session_id = new_session.response.result["sessionId"]

    outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "/plan build steps"}],
            },
        )
    )

    assert outcome.response is not None
    plan_updates = [
        notification
        for notification in outcome.notifications
        if notification.params is not None
        and notification.params["update"].get("sessionUpdate") == "plan"
    ]
    assert len(plan_updates) == 1
    assert plan_updates[0].params is not None
    assert isinstance(plan_updates[0].params["update"].get("entries"), list)


@pytest.mark.asyncio
async def test_prompt_with_meta_directive_emits_plan_update_without_slash() -> None:
    protocol = ACPProtocol()

    new_session = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert new_session.response is not None
    assert isinstance(new_session.response.result, dict)
    session_id = new_session.response.result["sessionId"]

    outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "build execution plan"}],
                "_meta": {
                    "promptDirectives": {
                        "publishPlan": True,
                    }
                },
            },
        )
    )

    assert outcome.response is not None
    plan_updates = [
        notification
        for notification in outcome.notifications
        if notification.method == "session/update"
        and isinstance(notification.params, dict)
        and isinstance(notification.params.get("update"), dict)
        and notification.params["update"].get("sessionUpdate") == "plan"
    ]
    assert len(plan_updates) == 1


@pytest.mark.asyncio
async def test_prompt_with_plan_entries_override_emits_custom_plan() -> None:
    protocol = ACPProtocol()
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "custom plan"}],
                "_meta": {
                    "promptDirectives": {
                        "planEntries": [
                            {
                                "content": "Собрать данные",
                                "priority": "high",
                                "status": "completed",
                            },
                            {
                                "content": "Сформировать результат",
                                "priority": "medium",
                                "status": "in_progress",
                            },
                        ]
                    }
                },
            },
        )
    )

    assert outcome.response is not None
    plan_update = next(
        notification
        for notification in outcome.notifications
        if notification.method == "session/update"
        and isinstance(notification.params, dict)
        and isinstance(notification.params.get("update"), dict)
        and notification.params["update"].get("sessionUpdate") == "plan"
    )
    assert plan_update.params is not None
    entries = plan_update.params["update"].get("entries")
    assert isinstance(entries, list)
    assert entries[0]["content"] == "Собрать данные"
    assert entries[1]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_prompt_with_legacy_marker_does_not_emit_plan_update() -> None:
    protocol = ACPProtocol()

    new_session = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert new_session.response is not None
    assert isinstance(new_session.response.result, dict)
    session_id = new_session.response.result["sessionId"]

    outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "[plan] собрать шаги"}],
            },
        )
    )

    assert outcome.response is not None
    assert not any(
        notification.params is not None
        and notification.params["update"].get("sessionUpdate") == "plan"
        for notification in outcome.notifications
    )


@pytest.mark.asyncio
async def test_prompt_with_meta_directive_requests_tool_without_slash() -> None:
    protocol = ACPProtocol()
    await _initialize_with_tool_runtime(protocol)
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run a network action"}],
                "_meta": {
                    "promptDirectives": {
                        "requestTool": True,
                        "toolKind": "fetch",
                    }
                },
            },
        )
    )

    assert outcome.response is None
    assert any(
        notification.method == "session/request_permission"
        and isinstance(notification.params, dict)
        and isinstance(notification.params.get("toolCall"), dict)
        and notification.params["toolCall"].get("kind") == "fetch"
        for notification in outcome.notifications
    )


@pytest.mark.asyncio
async def test_prompt_with_meta_pending_tool_keeps_turn_open() -> None:
    protocol = ACPProtocol()
    await _initialize_with_tool_runtime(protocol)
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "do something"}],
                "_meta": {
                    "promptDirectives": {
                        "keepToolPending": True,
                    }
                },
            },
        )
    )

    assert outcome.response is None
    updates = [
        notification.params["update"]
        for notification in outcome.notifications
        if notification.method == "session/update"
        and isinstance(notification.params, dict)
        and isinstance(notification.params.get("update"), dict)
    ]
    assert any(update.get("sessionUpdate") == "tool_call" for update in updates)
    assert any(
        notification.method == "session/request_permission"
        for notification in outcome.notifications
    )

    completed_response = await protocol.complete_active_turn(session_id)
    assert completed_response is not None
    assert completed_response.result == {"stopReason": "end_turn"}


@pytest.mark.asyncio
async def test_session_new_returns_modes_state() -> None:
    protocol = ACPProtocol()
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    assert isinstance(created.response.result.get("modes"), dict)
    assert created.response.result["modes"]["currentModeId"] == "ask"


@pytest.mark.asyncio
async def test_prompt_tool_flow_respects_negotiated_client_capabilities() -> None:
    protocol = ACPProtocol()
    init = await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
            },
        )
    )
    assert init.response is not None
    assert init.response.error is None

    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "/tool run"}],
            },
        )
    )

    assert outcome.response is not None
    assert outcome.response.result == {"stopReason": "end_turn"}
    update_types = [
        notification.params["update"]["sessionUpdate"]
        for notification in outcome.notifications
        if notification.params is not None
    ]
    assert "tool_call" not in update_types


@pytest.mark.asyncio
async def test_runtime_capabilities_are_session_scoped_after_reinitialize() -> None:
    protocol = ACPProtocol()

    first_init = await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": True,
                },
            },
        )
    )
    assert first_init.response is not None
    assert first_init.response.error is None

    first_session = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert first_session.response is not None
    assert isinstance(first_session.response.result, dict)
    first_session_id = first_session.response.result["sessionId"]

    second_init = await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
            },
        )
    )
    assert second_init.response is not None
    assert second_init.response.error is None

    second_session = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert second_session.response is not None
    assert isinstance(second_session.response.result, dict)
    second_session_id = second_session.response.result["sessionId"]

    first_prompt = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": first_session_id,
                "prompt": [{"type": "text", "text": "/tool run"}],
            },
        )
    )
    first_updates = [
        notification.params["update"]["sessionUpdate"]
        for notification in first_prompt.notifications
        if notification.method == "session/update"
        and isinstance(notification.params, dict)
        and isinstance(notification.params.get("update"), dict)
    ]
    assert "tool_call" in first_updates
    if first_prompt.response is None:
        permission_requests = [
            notification
            for notification in first_prompt.notifications
            if notification.method == "session/request_permission" and notification.id is not None
        ]
        assert len(permission_requests) == 1
        permission_result = await protocol.handle_client_response(
            ACPMessage.response(
                permission_requests[0].id,
                {
                    "outcome": {
                        "outcome": "selected",
                        "optionId": "allow_once",
                    }
                },
            )
        )
        # После permission approval возвращается pending_tool_execution
        # (tool execution и LLM loop выполняются асинхронно в http_server.py)
        assert permission_result.pending_tool_execution is not None
        assert permission_result.pending_tool_execution.tool_call_id == "call_001"
    else:
        assert first_prompt.response.result == {"stopReason": "end_turn"}

    second_prompt = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": second_session_id,
                "prompt": [{"type": "text", "text": "/tool run"}],
            },
        )
    )
    assert second_prompt.response is not None
    second_updates = [
        notification.params["update"]["sessionUpdate"]
        for notification in second_prompt.notifications
        if notification.method == "session/update"
        and isinstance(notification.params, dict)
        and isinstance(notification.params.get("update"), dict)
    ]
    assert "tool_call" not in second_updates


@pytest.mark.asyncio
async def test_prompt_tool_flow_requires_initialize_capability_negotiation() -> None:
    protocol = ACPProtocol()
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "/tool run"}],
            },
        )
    )

    assert outcome.response is not None
    assert outcome.response.result == {"stopReason": "end_turn"}
    update_types = [
        notification.params["update"]["sessionUpdate"]
        for notification in outcome.notifications
        if notification.params is not None
    ]
    assert "tool_call" not in update_types
    unavailable_messages = [
        notification.params["update"]["content"]["text"]
        for notification in outcome.notifications
        if notification.params is not None
        and notification.params["update"].get("sessionUpdate") == "agent_message_chunk"
        and isinstance(notification.params["update"].get("content"), dict)
        and isinstance(notification.params["update"]["content"].get("text"), str)
    ]
    assert any("Tool runtime unavailable" in text for text in unavailable_messages)


@pytest.mark.asyncio
async def test_prompt_can_finish_with_max_tokens_stop_reason() -> None:
    protocol = ACPProtocol()
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "/stop-max-tokens"}],
            },
        )
    )

    assert outcome.response is not None
    assert outcome.response.result == {"stopReason": "max_tokens"}


@pytest.mark.asyncio
async def test_prompt_can_finish_with_max_turn_requests_stop_reason() -> None:
    protocol = ACPProtocol()
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "/stop-max-turn-requests"}],
            },
        )
    )

    assert outcome.response is not None
    assert outcome.response.result == {"stopReason": "max_turn_requests"}


@pytest.mark.asyncio
async def test_prompt_can_finish_with_refusal_stop_reason() -> None:
    protocol = ACPProtocol()
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "/refuse"}],
            },
        )
    )

    assert outcome.response is not None
    assert outcome.response.result == {"stopReason": "refusal"}


@pytest.mark.asyncio
async def test_prompt_can_finish_with_meta_forced_stop_reason() -> None:
    protocol = ACPProtocol()
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "plain prompt"}],
                "_meta": {
                    "promptDirectives": {
                        "forcedStopReason": "max_tokens",
                    }
                },
            },
        )
    )

    assert outcome.response is not None
    assert outcome.response.result == {"stopReason": "max_tokens"}


@pytest.mark.asyncio
async def test_session_list_returns_created_session() -> None:
    protocol = ACPProtocol()
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    created_id = created.response.result["sessionId"]

    listed = await protocol.handle(ACPMessage.request("session/list", {}))
    assert listed.response is not None
    assert isinstance(listed.response.result, dict)
    sessions = listed.response.result["sessions"]
    assert isinstance(sessions, list)
    assert any(session["sessionId"] == created_id for session in sessions)


@pytest.mark.asyncio
async def test_session_list_supports_cursor_pagination() -> None:
    protocol = ACPProtocol()
    for _ in range(51):
        created = await protocol.handle(
            ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
        )
        assert created.response is not None

    first_page = await protocol.handle(ACPMessage.request("session/list", {}))
    assert first_page.response is not None
    assert isinstance(first_page.response.result, dict)
    first_sessions = first_page.response.result["sessions"]
    next_cursor = first_page.response.result["nextCursor"]
    assert len(first_sessions) == 50
    assert isinstance(next_cursor, str)

    second_page = await protocol.handle(ACPMessage.request("session/list", {"cursor": next_cursor}))
    assert second_page.response is not None
    assert isinstance(second_page.response.result, dict)
    second_sessions = second_page.response.result["sessions"]
    assert len(second_sessions) == 1
    assert second_page.response.result["nextCursor"] is None


@pytest.mark.asyncio
async def test_session_list_rejects_invalid_cursor() -> None:
    protocol = ACPProtocol()
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None

    listed = await protocol.handle(
        ACPMessage.request("session/list", {"cursor": "not-a-valid-cursor"})
    )
    assert listed.response is not None
    assert listed.response.error is not None
    assert listed.response.error.code == -32602


@pytest.mark.asyncio
async def test_set_config_option_updates_value() -> None:
    protocol = ACPProtocol()
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    created_id = created.response.result["sessionId"]

    updated = await protocol.handle(
        ACPMessage.request(
            "session/set_config_option",
            {
                "sessionId": created_id,
                "configId": "mode",
                "value": "code",
            },
        )
    )

    assert updated.response is not None
    assert isinstance(updated.response.result, dict)
    config_options = updated.response.result["configOptions"]
    assert isinstance(updated.response.result.get("modes"), dict)
    assert updated.response.result["modes"]["currentModeId"] == "code"
    mode = next(option for option in config_options if option["id"] == "mode")
    assert mode["currentValue"] == "code"
    assert len(updated.notifications) == 3
    assert updated.notifications[0].params is not None
    assert updated.notifications[0].params["update"]["sessionUpdate"] == "config_option_update"
    assert updated.notifications[1].params is not None
    assert updated.notifications[1].params["update"]["sessionUpdate"] == "current_mode_update"
    assert updated.notifications[2].params is not None
    assert updated.notifications[2].params["update"]["sessionUpdate"] == "session_info_update"


@pytest.mark.asyncio
async def test_prompt_rejects_unsupported_content_type() -> None:
    protocol = ACPProtocol()
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    created_id = created.response.result["sessionId"]

    outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": created_id,
                "prompt": [{"type": "audio", "data": "abc"}],
            },
        )
    )

    assert outcome.response is not None
    assert outcome.response.error is not None
    assert outcome.response.error.code == -32602


@pytest.mark.asyncio
async def test_prompt_can_emit_tool_call_updates() -> None:
    protocol = ACPProtocol()
    await _initialize_with_tool_runtime(protocol)
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    created_id = created.response.result["sessionId"]

    updated = await protocol.handle(
        ACPMessage.request(
            "session/set_config_option",
            {
                "sessionId": created_id,
                "configId": "mode",
                "value": "code",
            },
        )
    )
    assert updated.response is not None

    outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": created_id,
                "prompt": [{"type": "text", "text": "run tool for me"}],
                "_meta": {"promptDirectives": {"requestTool": True}},
            },
        )
    )

    assert outcome.response is not None
    assert outcome.response.result == {"stopReason": "end_turn"}
    update_types = [
        notification.params["update"]["sessionUpdate"]
        for notification in outcome.notifications
        if notification.params is not None
    ]
    assert "tool_call" in update_types
    assert "tool_call_update" in update_types


@pytest.mark.asyncio
async def test_prompt_fs_read_emits_client_rpc_request_when_capability_enabled() -> None:
    protocol = ACPProtocol()
    initialized = await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": False},
                    "terminal": False,
                },
            },
        )
    )
    assert initialized.response is not None

    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "read file"}],
                "_meta": {"promptDirectives": {"fsReadPath": "README.md"}},
            },
        )
    )

    assert outcome.response is None
    assert any(notification.method == "fs/read_text_file" for notification in outcome.notifications)


@pytest.mark.asyncio
async def test_fs_read_response_completes_turn_with_completed_tool_update() -> None:
    protocol = ACPProtocol()
    await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": False},
                    "terminal": False,
                },
            },
        )
    )
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "read file"}],
                "_meta": {"promptDirectives": {"fsReadPath": "README.md"}},
            },
        )
    )
    assert prompt_outcome.response is None

    fs_request = next(
        notification
        for notification in prompt_outcome.notifications
        if notification.method == "fs/read_text_file"
    )
    assert fs_request.id is not None

    resolved = await protocol.handle_client_response(
        ACPMessage.response(fs_request.id, {"content": "file-body"})
    )
    assert len(resolved.followup_responses) == 1
    assert resolved.followup_responses[0].result == {"stopReason": "end_turn"}
    assert any(
        notification.params is not None
        and notification.params["update"].get("sessionUpdate") == "tool_call_update"
        and notification.params["update"].get("status") == "completed"
        for notification in resolved.notifications
    )


@pytest.mark.asyncio
async def test_fs_write_response_contains_diff_tool_content() -> None:
    protocol = ACPProtocol()
    await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": True},
                    "terminal": False,
                },
            },
        )
    )
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "write file"}],
                "_meta": {
                    "promptDirectives": {
                        "fsWritePath": "notes.txt",
                        "fsWriteContent": "updated",
                    }
                },
            },
        )
    )
    assert prompt_outcome.response is None

    fs_request = next(
        notification
        for notification in prompt_outcome.notifications
        if notification.method == "fs/write_text_file"
    )
    assert fs_request.id is not None

    resolved = await protocol.handle_client_response(
        ACPMessage.response(
            fs_request.id,
            {
                "ok": True,
                "oldText": "before",
                "newText": "updated",
            },
        )
    )
    diff_updates = [
        notification
        for notification in resolved.notifications
        if notification.params is not None
        and notification.params["update"].get("sessionUpdate") == "tool_call_update"
    ]
    assert len(diff_updates) >= 1
    assert diff_updates[0].params is not None
    content = diff_updates[0].params["update"].get("content")
    assert isinstance(content, list)
    assert content[0].get("type") == "diff"


@pytest.mark.asyncio
async def test_prompt_fs_read_without_capability_does_not_emit_fs_rpc() -> None:
    protocol = ACPProtocol()
    await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
            },
        )
    )
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "read file"}],
                "_meta": {"promptDirectives": {"fsReadPath": "README.md"}},
            },
        )
    )

    assert outcome.response is not None
    assert outcome.response.result == {"stopReason": "end_turn"}
    assert all(notification.method != "fs/read_text_file" for notification in outcome.notifications)


@pytest.mark.asyncio
async def test_fs_read_client_error_marks_tool_as_failed() -> None:
    protocol = ACPProtocol()
    await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": False},
                    "terminal": False,
                },
            },
        )
    )
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "read file"}],
                "_meta": {"promptDirectives": {"fsReadPath": "README.md"}},
            },
        )
    )
    assert prompt_outcome.response is None

    fs_request = next(
        notification
        for notification in prompt_outcome.notifications
        if notification.method == "fs/read_text_file"
    )
    assert fs_request.id is not None

    resolved = await protocol.handle_client_response(
        ACPMessage.error_response(
            fs_request.id,
            code=-32000,
            message="read failed",
        )
    )
    assert len(resolved.followup_responses) == 1
    assert resolved.followup_responses[0].result == {"stopReason": "end_turn"}
    assert any(
        notification.params is not None and notification.params["update"].get("status") == "failed"
        for notification in resolved.notifications
    )


@pytest.mark.asyncio
async def test_fs_read_invalid_success_payload_marks_tool_as_failed() -> None:
    protocol = ACPProtocol()
    await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": False},
                    "terminal": False,
                },
            },
        )
    )
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "read file"}],
                "_meta": {"promptDirectives": {"fsReadPath": "README.md"}},
            },
        )
    )
    assert prompt_outcome.response is None
    fs_request = next(
        notification
        for notification in prompt_outcome.notifications
        if notification.method == "fs/read_text_file"
    )
    assert fs_request.id is not None

    resolved = await protocol.handle_client_response(ACPMessage.response(fs_request.id, {}))
    assert len(resolved.followup_responses) == 1
    assert resolved.followup_responses[0].result == {"stopReason": "end_turn"}
    assert any(
        notification.params is not None
        and notification.params["update"].get("status") == "failed"
        and "Invalid fs/read_text_file response"
        in notification.params["update"]["content"][0]["content"]["text"]
        for notification in resolved.notifications
    )


@pytest.mark.asyncio
async def test_fs_write_non_object_payload_marks_tool_as_failed() -> None:
    protocol = ACPProtocol()
    await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": True},
                    "terminal": False,
                },
            },
        )
    )
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "write file"}],
                "_meta": {
                    "promptDirectives": {
                        "fsWritePath": "notes.txt",
                        "fsWriteContent": "updated",
                    }
                },
            },
        )
    )
    assert prompt_outcome.response is None
    fs_request = next(
        notification
        for notification in prompt_outcome.notifications
        if notification.method == "fs/write_text_file"
    )
    assert fs_request.id is not None

    resolved = await protocol.handle_client_response(ACPMessage.response(fs_request.id, "ok"))
    assert len(resolved.followup_responses) == 1
    assert resolved.followup_responses[0].result == {"stopReason": "end_turn"}
    assert any(
        notification.params is not None
        and notification.params["update"].get("status") == "failed"
        and "Invalid fs/write_text_file response"
        in notification.params["update"]["content"][0]["content"]["text"]
        for notification in resolved.notifications
    )


@pytest.mark.asyncio
async def test_prompt_terminal_run_emits_terminal_create_request() -> None:
    protocol = ACPProtocol()
    await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": True,
                },
            },
        )
    )
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run command"}],
                "_meta": {"promptDirectives": {"terminalCommand": "ls -la"}},
            },
        )
    )
    assert outcome.response is None
    assert any(notification.method == "terminal/create" for notification in outcome.notifications)


@pytest.mark.asyncio
async def test_terminal_rpc_chain_completes_prompt_turn() -> None:
    protocol = ACPProtocol()
    await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": True,
                },
            },
        )
    )
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run command"}],
                "_meta": {"promptDirectives": {"terminalCommand": "ls"}},
            },
        )
    )
    assert prompt_outcome.response is None

    create_request = next(
        notification
        for notification in prompt_outcome.notifications
        if notification.method == "terminal/create"
    )
    assert create_request.id is not None

    output_step = await protocol.handle_client_response(
        ACPMessage.response(create_request.id, {"terminalId": "term_1"})
    )
    output_request = next(
        notification
        for notification in output_step.notifications
        if notification.method == "terminal/output"
    )
    assert output_request.id is not None

    wait_step = await protocol.handle_client_response(
        ACPMessage.response(output_request.id, {"output": "hello"})
    )
    wait_request = next(
        notification
        for notification in wait_step.notifications
        if notification.method == "terminal/wait_for_exit"
    )
    assert wait_request.id is not None

    release_step = await protocol.handle_client_response(
        ACPMessage.response(wait_request.id, {"exitCode": 0})
    )
    release_request = next(
        notification
        for notification in release_step.notifications
        if notification.method == "terminal/release"
    )
    assert release_request.id is not None

    done = await protocol.handle_client_response(
        ACPMessage.response(release_request.id, {"ok": True})
    )
    assert len(done.followup_responses) == 1
    assert done.followup_responses[0].result == {"stopReason": "end_turn"}
    assert any(
        notification.params is not None
        and notification.params["update"].get("sessionUpdate") == "tool_call_update"
        and notification.params["update"].get("status") == "completed"
        for notification in done.notifications
    )


@pytest.mark.asyncio
async def test_terminal_output_exit_status_skips_wait_for_exit() -> None:
    protocol = ACPProtocol()
    await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": True,
                },
            },
        )
    )
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run command"}],
                "_meta": {"promptDirectives": {"terminalCommand": "sleep 1"}},
            },
        )
    )
    assert prompt_outcome.response is None

    create_request = next(
        notification
        for notification in prompt_outcome.notifications
        if notification.method == "terminal/create"
    )
    assert create_request.id is not None

    output_step = await protocol.handle_client_response(
        ACPMessage.response(create_request.id, {"terminalId": "term_1"})
    )
    output_request = next(
        notification
        for notification in output_step.notifications
        if notification.method == "terminal/output"
    )
    assert output_request.id is not None

    release_step = await protocol.handle_client_response(
        ACPMessage.response(
            output_request.id,
            {
                "output": "done",
                "truncated": True,
                "exitStatus": {"exitCode": None, "signal": "SIGTERM"},
            },
        )
    )
    assert any(
        notification.method == "terminal/release" for notification in release_step.notifications
    )
    assert not any(
        notification.method == "terminal/wait_for_exit"
        for notification in release_step.notifications
    )

    release_request = next(
        notification
        for notification in release_step.notifications
        if notification.method == "terminal/release"
    )
    assert release_request.id is not None
    done = await protocol.handle_client_response(ACPMessage.response(release_request.id, {}))
    assert len(done.followup_responses) == 1
    assert done.followup_responses[0].result == {"stopReason": "end_turn"}
    assert any(
        notification.params is not None
        and notification.params["update"].get("sessionUpdate") == "tool_call_update"
        and notification.params["update"].get("rawOutput", {}).get("signal") == "SIGTERM"
        for notification in done.notifications
    )


@pytest.mark.asyncio
async def test_terminal_output_invalid_payload_marks_tool_as_failed() -> None:
    protocol = ACPProtocol()
    await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": True,
                },
            },
        )
    )
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run command"}],
                "_meta": {"promptDirectives": {"terminalCommand": "ls"}},
            },
        )
    )
    assert prompt_outcome.response is None
    create_request = next(
        notification
        for notification in prompt_outcome.notifications
        if notification.method == "terminal/create"
    )
    assert create_request.id is not None

    output_step = await protocol.handle_client_response(
        ACPMessage.response(create_request.id, {"terminalId": "term_1"})
    )
    output_request = next(
        notification
        for notification in output_step.notifications
        if notification.method == "terminal/output"
    )
    assert output_request.id is not None

    resolved = await protocol.handle_client_response(ACPMessage.response(output_request.id, {}))
    assert len(resolved.followup_responses) == 1
    assert resolved.followup_responses[0].result == {"stopReason": "end_turn"}
    assert any(
        notification.params is not None
        and notification.params["update"].get("status") == "failed"
        and "Invalid terminal/output response"
        in notification.params["update"]["content"][0]["content"]["text"]
        for notification in resolved.notifications
    )


@pytest.mark.asyncio
async def test_terminal_output_with_non_object_exit_status_marks_tool_as_failed() -> None:
    protocol = ACPProtocol()
    await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": True,
                },
            },
        )
    )
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run command"}],
                "_meta": {"promptDirectives": {"terminalCommand": "ls"}},
            },
        )
    )
    assert prompt_outcome.response is None
    create_request = next(
        notification
        for notification in prompt_outcome.notifications
        if notification.method == "terminal/create"
    )
    assert create_request.id is not None

    output_step = await protocol.handle_client_response(
        ACPMessage.response(create_request.id, {"terminalId": "term_1"})
    )
    output_request = next(
        notification
        for notification in output_step.notifications
        if notification.method == "terminal/output"
    )
    assert output_request.id is not None

    resolved = await protocol.handle_client_response(
        ACPMessage.response(
            output_request.id,
            {
                "output": "partial",
                "exitStatus": "done",
            },
        )
    )
    assert len(resolved.followup_responses) == 1
    assert resolved.followup_responses[0].result == {"stopReason": "end_turn"}
    assert any(
        notification.params is not None
        and notification.params["update"].get("status") == "failed"
        and "Invalid terminal/output response"
        in notification.params["update"]["content"][0]["content"]["text"]
        for notification in resolved.notifications
    )


@pytest.mark.asyncio
async def test_cancel_during_terminal_flow_emits_kill_and_release_requests() -> None:
    protocol = ACPProtocol()
    await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": True,
                },
            },
        )
    )
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run command"}],
                "_meta": {"promptDirectives": {"terminalCommand": "sleep 10"}},
            },
        )
    )
    assert prompt_outcome.response is None
    create_request = next(
        notification
        for notification in prompt_outcome.notifications
        if notification.method == "terminal/create"
    )
    assert create_request.id is not None

    _ = await protocol.handle_client_response(
        ACPMessage.response(create_request.id, {"terminalId": "term_1"})
    )

    cancel_outcome = await protocol.handle(
        ACPMessage.request(
            "session/cancel",
            {
                "sessionId": session_id,
            },
        )
    )
    # После архитектурного изменения, cancel отправляет session/update с cancelled статусом.
    # Управление терминалами (kill/release) теперь - ответственность оркестратора.
    methods = [notification.method for notification in cancel_outcome.notifications]
    assert "session/update" in methods
    # Проверяем, что есть update со статусом cancelled
    cancelled_updates = [
        n for n in cancel_outcome.notifications
        if n.method == "session/update"
        and n.params is not None
        and n.params.get("update", {}).get("status") == "cancelled"
    ]
    assert len(cancelled_updates) >= 1


@pytest.mark.asyncio
async def test_cancel_marks_active_tool_call_as_cancelled() -> None:
    protocol = ACPProtocol()
    await _initialize_with_tool_runtime(protocol)
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    created_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": created_id,
                "prompt": [{"type": "text", "text": "run tool"}],
                "_meta": {"promptDirectives": {"keepToolPending": True}},
            },
        )
    )
    assert prompt_outcome.response is None

    tool_call_created = next(
        notification
        for notification in prompt_outcome.notifications
        if notification.params is not None
        and notification.params["update"]["sessionUpdate"] == "tool_call"
    )
    assert tool_call_created.params is not None
    tool_call_id = tool_call_created.params["update"]["toolCallId"]

    cancel_outcome = await protocol.handle(
        ACPMessage.notification("session/cancel", {"sessionId": created_id})
    )

    assert len(cancel_outcome.followup_responses) == 1
    assert cancel_outcome.followup_responses[0].result == {"stopReason": "cancelled"}

    cancelled_updates = [
        notification
        for notification in cancel_outcome.notifications
        if notification.params is not None
        and notification.params["update"]["sessionUpdate"] == "tool_call_update"
        and notification.params["update"]["status"] == "cancelled"
    ]
    assert any(
        notification.params is not None
        and notification.params["update"]["toolCallId"] == tool_call_id
        for notification in cancelled_updates
    )


@pytest.mark.asyncio
async def test_deferred_prompt_can_be_completed_without_cancel() -> None:
    protocol = ACPProtocol()
    await _initialize_with_tool_runtime(protocol)
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run tool"}],
                "_meta": {"promptDirectives": {"keepToolPending": True}},
            },
        )
    )
    assert prompt_outcome.response is None

    completed_response = await protocol.complete_active_turn(session_id, stop_reason="end_turn")
    assert completed_response is not None
    assert completed_response.result == {"stopReason": "end_turn"}


@pytest.mark.asyncio
async def test_prompt_with_tool_pending_slash_command_defers_turn() -> None:
    protocol = ACPProtocol()
    await _initialize_with_tool_runtime(protocol)
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    # Переключаемся в mode=code, чтобы не уходить в permission-flow и проверить defer tool-call.
    updated = await protocol.handle(
        ACPMessage.request(
            "session/set_config_option",
            {
                "sessionId": session_id,
                "configId": "mode",
                "value": "code",
            },
        )
    )
    assert updated.response is not None

    outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "/tool-pending выполнить"}],
            },
        )
    )

    assert outcome.response is None
    assert any(
        notification.params is not None
        and notification.params["update"].get("sessionUpdate") == "tool_call"
        for notification in outcome.notifications
    )


@pytest.mark.asyncio
async def test_permission_selected_completes_prompt_turn() -> None:
    protocol = ACPProtocol()
    await _initialize_with_tool_runtime(protocol)
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run tool"}],
                "_meta": {"promptDirectives": {"requestTool": True}},
            },
        )
    )
    assert prompt_outcome.response is None

    permission_request = next(
        notification
        for notification in prompt_outcome.notifications
        if notification.method == "session/request_permission"
    )
    assert permission_request.id is not None
    assert permission_request.params is not None
    options = permission_request.params["options"]
    assert isinstance(options, list)
    assert any(
        isinstance(option, dict) and option.get("kind") == "reject_once" for option in options
    )
    assert any(
        isinstance(option, dict) and option.get("kind") == "allow_always" for option in options
    )

    resolved = await protocol.handle_client_response(
        ACPMessage.response(
            permission_request.id,
            {
                "outcome": {
                    "outcome": "selected",
                    "optionId": "allow_once",
                },
            },
        )
    )
    # После permission approval возвращается pending_tool_execution для async выполнения
    assert resolved.pending_tool_execution is not None
    assert resolved.pending_tool_execution.session_id == session_id

    # Выполняем pending tool
    await protocol.execute_pending_tool(
        session_id=resolved.pending_tool_execution.session_id,
        tool_call_id=resolved.pending_tool_execution.tool_call_id,
    )

    # Завершаем turn
    turn_completion = await protocol.complete_active_turn(session_id, stop_reason="end_turn")
    assert turn_completion is not None
    assert turn_completion.result == {"stopReason": "end_turn"}


@pytest.mark.asyncio
async def test_permission_cancelled_finishes_turn_with_cancelled() -> None:
    protocol = ACPProtocol()
    await _initialize_with_tool_runtime(protocol)
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run tool"}],
                "_meta": {"promptDirectives": {"requestTool": True}},
            },
        )
    )
    assert prompt_outcome.response is None

    permission_request = next(
        notification
        for notification in prompt_outcome.notifications
        if notification.method == "session/request_permission"
    )
    assert permission_request.id is not None

    resolved = await protocol.handle_client_response(
        ACPMessage.response(
            permission_request.id,
            {"outcome": {"outcome": "cancelled"}},
        )
    )
    assert len(resolved.followup_responses) == 1
    assert resolved.followup_responses[0].result == {"stopReason": "cancelled"}


@pytest.mark.asyncio
async def test_permission_reject_option_finishes_turn_with_cancelled() -> None:
    protocol = ACPProtocol()
    await _initialize_with_tool_runtime(protocol)
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run tool"}],
                "_meta": {"promptDirectives": {"requestTool": True}},
            },
        )
    )
    assert prompt_outcome.response is None

    permission_request = next(
        notification
        for notification in prompt_outcome.notifications
        if notification.method == "session/request_permission"
    )
    assert permission_request.id is not None

    resolved = await protocol.handle_client_response(
        ACPMessage.response(
            permission_request.id,
            {"outcome": {"outcome": "selected", "optionId": "reject_once"}},
        )
    )
    assert len(resolved.followup_responses) == 1
    assert resolved.followup_responses[0].result == {"stopReason": "cancelled"}


@pytest.mark.asyncio
async def test_permission_selected_with_unknown_option_is_rejected() -> None:
    protocol = ACPProtocol()
    await _initialize_with_tool_runtime(protocol)
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run tool"}],
                "_meta": {"promptDirectives": {"requestTool": True}},
            },
        )
    )
    assert prompt_outcome.response is None

    permission_request = next(
        notification
        for notification in prompt_outcome.notifications
        if notification.method == "session/request_permission"
    )
    assert permission_request.id is not None

    resolved = await protocol.handle_client_response(
        ACPMessage.response(
            permission_request.id,
            {
                "outcome": {
                    "outcome": "selected",
                    "optionId": "allow_unknown",
                },
            },
        )
    )
    assert len(resolved.followup_responses) == 1
    assert resolved.followup_responses[0].result == {"stopReason": "cancelled"}

    next_prompt = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run tool again"}],
                "_meta": {"promptDirectives": {"requestTool": True}},
            },
        )
    )
    assert next_prompt.response is None
    assert any(
        notification.method == "session/request_permission"
        for notification in next_prompt.notifications
    )


@pytest.mark.asyncio
async def test_permission_selected_without_option_id_is_rejected() -> None:
    protocol = ACPProtocol()
    await _initialize_with_tool_runtime(protocol)
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run tool"}],
                "_meta": {"promptDirectives": {"requestTool": True}},
            },
        )
    )
    assert prompt_outcome.response is None

    permission_request = next(
        notification
        for notification in prompt_outcome.notifications
        if notification.method == "session/request_permission"
    )
    assert permission_request.id is not None

    resolved = await protocol.handle_client_response(
        ACPMessage.response(
            permission_request.id,
            {
                "outcome": {
                    "outcome": "selected",
                },
            },
        )
    )
    assert len(resolved.followup_responses) == 1
    assert resolved.followup_responses[0].result == {"stopReason": "cancelled"}


@pytest.mark.asyncio
async def test_late_permission_response_after_cancel_is_ignored() -> None:
    protocol = ACPProtocol()
    await _initialize_with_tool_runtime(protocol)
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run tool"}],
                "_meta": {"promptDirectives": {"requestTool": True}},
            },
        )
    )
    assert prompt_outcome.response is None

    permission_request = next(
        notification
        for notification in prompt_outcome.notifications
        if notification.method == "session/request_permission"
    )
    assert permission_request.id is not None

    cancel_outcome = await protocol.handle(
        ACPMessage.notification("session/cancel", {"sessionId": session_id})
    )
    assert len(cancel_outcome.followup_responses) == 1
    assert cancel_outcome.followup_responses[0].result == {"stopReason": "cancelled"}

    late_permission = await protocol.handle_client_response(
        ACPMessage.response(
            permission_request.id,
            {
                "outcome": {
                    "outcome": "selected",
                    "optionId": "allow_once",
                },
            },
        )
    )
    assert late_permission.notifications == []
    assert late_permission.followup_responses == []

    next_prompt = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "normal prompt"}],
            },
        )
    )
    assert next_prompt.response is not None
    assert next_prompt.response.result == {"stopReason": "end_turn"}


@pytest.mark.asyncio
async def test_late_fs_response_after_cancel_is_ignored() -> None:
    protocol = ACPProtocol()
    await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": False},
                    "terminal": False,
                },
            },
        )
    )
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "read file"}],
                "_meta": {"promptDirectives": {"fsReadPath": "README.md"}},
            },
        )
    )
    assert prompt_outcome.response is None

    fs_request = next(
        notification
        for notification in prompt_outcome.notifications
        if notification.method == "fs/read_text_file"
    )
    assert fs_request.id is not None

    cancel_outcome = await protocol.handle(
        ACPMessage.notification("session/cancel", {"sessionId": session_id})
    )
    assert len(cancel_outcome.followup_responses) == 1
    assert cancel_outcome.followup_responses[0].result == {"stopReason": "cancelled"}

    late_fs_response = await protocol.handle_client_response(
        ACPMessage.response(fs_request.id, {"content": "late payload"})
    )
    assert late_fs_response.notifications == []
    assert late_fs_response.followup_responses == []

    next_prompt = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "normal prompt"}],
            },
        )
    )
    assert next_prompt.response is not None
    assert next_prompt.response.result == {"stopReason": "end_turn"}


@pytest.mark.asyncio
async def test_late_terminal_create_response_after_cancel_is_ignored() -> None:
    protocol = ACPProtocol()
    await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": True,
                },
            },
        )
    )
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run command"}],
                "_meta": {"promptDirectives": {"terminalCommand": "sleep 10"}},
            },
        )
    )
    assert prompt_outcome.response is None

    create_request = next(
        notification
        for notification in prompt_outcome.notifications
        if notification.method == "terminal/create"
    )
    assert create_request.id is not None

    cancel_outcome = await protocol.handle(
        ACPMessage.notification("session/cancel", {"sessionId": session_id})
    )
    assert len(cancel_outcome.followup_responses) == 1
    assert cancel_outcome.followup_responses[0].result == {"stopReason": "cancelled"}

    late_create_response = await protocol.handle_client_response(
        ACPMessage.response(create_request.id, {"terminalId": "term_late"})
    )
    assert late_create_response.notifications == []
    assert late_create_response.followup_responses == []

    next_prompt = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "normal prompt"}],
            },
        )
    )
    assert next_prompt.response is not None
    assert next_prompt.response.result == {"stopReason": "end_turn"}


@pytest.mark.asyncio
async def test_disconnect_auto_cancel_turn_with_pending_permission() -> None:
    """Проверяет auto-cancel активного turn при разрыве соединения."""

    protocol = ACPProtocol()
    await _initialize_with_tool_runtime(protocol)
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run tool"}],
                "_meta": {"promptDirectives": {"requestTool": True}},
            },
        )
    )
    assert prompt_outcome.response is None

    permission_request = next(
        notification
        for notification in prompt_outcome.notifications
        if notification.method == "session/request_permission"
    )
    assert permission_request.id is not None

    cancelled_count = await protocol.cancel_active_turns_on_disconnect()
    assert cancelled_count == 1

    late_permission = await protocol.handle_client_response(
        ACPMessage.response(
            permission_request.id,
            {
                "outcome": {
                    "outcome": "selected",
                    "optionId": "allow_once",
                },
            },
        )
    )
    assert late_permission.notifications == []
    assert late_permission.followup_responses == []

    next_prompt = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "normal prompt"}],
            },
        )
    )
    assert next_prompt.response is not None
    assert next_prompt.response.result == {"stopReason": "end_turn"}


@pytest.mark.asyncio
async def test_permission_allow_always_applies_to_next_tool_call() -> None:
    protocol = ACPProtocol()
    await _initialize_with_tool_runtime(protocol)
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    first_prompt = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run tool"}],
                "_meta": {"promptDirectives": {"requestTool": True}},
            },
        )
    )
    assert first_prompt.response is None
    permission_request = next(
        notification
        for notification in first_prompt.notifications
        if notification.method == "session/request_permission"
    )
    assert permission_request.id is not None

    first_resolution = await protocol.handle_client_response(
        ACPMessage.response(
            permission_request.id,
            {
                "outcome": {
                    "outcome": "selected",
                    "optionId": "allow_always",
                },
            },
        )
    )
    # После permission approval возвращается pending_tool_execution для async выполнения
    assert first_resolution.pending_tool_execution is not None
    assert first_resolution.pending_tool_execution.session_id == session_id

    # Выполняем pending tool
    await protocol.execute_pending_tool(
        session_id=first_resolution.pending_tool_execution.session_id,
        tool_call_id=first_resolution.pending_tool_execution.tool_call_id,
    )

    # Завершаем turn
    turn_completion = await protocol.complete_active_turn(session_id, stop_reason="end_turn")
    assert turn_completion is not None
    assert turn_completion.result == {"stopReason": "end_turn"}

    second_prompt = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run tool again"}],
                "_meta": {"promptDirectives": {"requestTool": True}},
            },
        )
    )
    assert second_prompt.response is not None
    assert second_prompt.response.result == {"stopReason": "end_turn"}
    assert not any(
        notification.method == "session/request_permission"
        for notification in second_prompt.notifications
    )


@pytest.mark.asyncio
async def test_permission_reject_always_applies_to_next_tool_call() -> None:
    protocol = ACPProtocol()
    await _initialize_with_tool_runtime(protocol)
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    first_prompt = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run tool"}],
                "_meta": {"promptDirectives": {"requestTool": True}},
            },
        )
    )
    assert first_prompt.response is None
    permission_request = next(
        notification
        for notification in first_prompt.notifications
        if notification.method == "session/request_permission"
    )
    assert permission_request.id is not None

    first_resolution = await protocol.handle_client_response(
        ACPMessage.response(
            permission_request.id,
            {
                "outcome": {
                    "outcome": "selected",
                    "optionId": "reject_always",
                },
            },
        )
    )
    assert len(first_resolution.followup_responses) == 1
    assert first_resolution.followup_responses[0].result == {"stopReason": "cancelled"}

    second_prompt = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run tool again"}],
                "_meta": {"promptDirectives": {"requestTool": True}},
            },
        )
    )
    assert second_prompt.response is not None
    assert second_prompt.response.result == {"stopReason": "cancelled"}
    assert not any(
        notification.method == "session/request_permission"
        for notification in second_prompt.notifications
    )


@pytest.mark.asyncio
async def test_permission_policy_is_scoped_by_tool_kind() -> None:
    protocol = ACPProtocol()
    await _initialize_with_tool_runtime(protocol)
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    first_prompt = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "execute tool"}],
                "_meta": {"promptDirectives": {"requestTool": True, "toolKind": "execute"}},
            },
        )
    )
    assert first_prompt.response is None
    permission_request = next(
        notification
        for notification in first_prompt.notifications
        if notification.method == "session/request_permission"
    )
    assert permission_request.id is not None
    assert permission_request.params is not None
    assert permission_request.params["toolCall"]["kind"] == "execute"

    resolved = await protocol.handle_client_response(
        ACPMessage.response(
            permission_request.id,
            {
                "outcome": {
                    "outcome": "selected",
                    "optionId": "allow_always",
                },
            },
        )
    )
    # После permission approval возвращается pending_tool_execution для async выполнения
    assert resolved.pending_tool_execution is not None

    # Выполняем pending tool и завершаем turn
    await protocol.execute_pending_tool(
        session_id=resolved.pending_tool_execution.session_id,
        tool_call_id=resolved.pending_tool_execution.tool_call_id,
    )
    turn_completion = await protocol.complete_active_turn(session_id, stop_reason="end_turn")
    assert turn_completion is not None
    assert turn_completion.result == {"stopReason": "end_turn"}

    same_kind_prompt = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "execute tool again"}],
                "_meta": {"promptDirectives": {"requestTool": True, "toolKind": "execute"}},
            },
        )
    )
    assert same_kind_prompt.response is not None
    assert not any(
        notification.method == "session/request_permission"
        for notification in same_kind_prompt.notifications
    )

    different_kind_prompt = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "edit file"}],
                "_meta": {"promptDirectives": {"requestTool": True, "toolKind": "edit"}},
            },
        )
    )
    assert different_kind_prompt.response is None
    assert any(
        notification.method == "session/request_permission"
        for notification in different_kind_prompt.notifications
    )


@pytest.mark.asyncio
async def test_prompt_tool_flow_supports_fetch_kind() -> None:
    protocol = ACPProtocol()
    await _initialize_with_tool_runtime(protocol)
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "fetch latest"}],
                "_meta": {"promptDirectives": {"requestTool": True, "toolKind": "fetch"}},
            },
        )
    )

    assert outcome.response is None
    tool_call_updates = [
        notification
        for notification in outcome.notifications
        if notification.method == "session/update"
        and isinstance(notification.params, dict)
        and isinstance(notification.params.get("update"), dict)
        and notification.params["update"].get("sessionUpdate") == "tool_call"
    ]
    assert len(tool_call_updates) == 1
    assert tool_call_updates[0].params is not None
    assert tool_call_updates[0].params["update"].get("kind") == "fetch"


@pytest.mark.asyncio
async def test_cancel_without_active_turn_does_not_affect_next_prompt() -> None:
    protocol = ACPProtocol()
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    cancel_outcome = await protocol.handle(
        ACPMessage.notification("session/cancel", {"sessionId": session_id})
    )
    assert cancel_outcome.response is None

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "normal prompt"}],
            },
        )
    )
    assert prompt_outcome.response is not None
    assert prompt_outcome.response.result == {"stopReason": "end_turn"}


@pytest.mark.asyncio
async def test_session_load_replays_history_and_config() -> None:
    protocol = ACPProtocol()
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompted = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "hello replay"}],
            },
        )
    )
    assert prompted.response is not None

    loaded = await protocol.handle(
        ACPMessage.request(
            "session/load",
            {
                "sessionId": session_id,
                "cwd": "/tmp",
                "mcpServers": [],
            },
        )
    )

    assert loaded.response is not None
    assert isinstance(loaded.response.result, dict)
    assert "configOptions" in loaded.response.result
    assert isinstance(loaded.response.result.get("modes"), dict)

    replay_updates = [
        notification.params["update"]["sessionUpdate"]
        for notification in loaded.notifications
        if notification.params is not None
    ]
    assert "user_message_chunk" in replay_updates
    assert "agent_message_chunk" in replay_updates
    assert "config_option_update" in replay_updates
    assert "session_info_update" in replay_updates
    assert "available_commands_update" in replay_updates


@pytest.mark.asyncio
async def test_session_load_replays_last_plan_update() -> None:
    protocol = ACPProtocol()
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompted = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "compose plan"}],
                "_meta": {"promptDirectives": {"publishPlan": True}},
            },
        )
    )
    assert prompted.response is not None

    loaded = await protocol.handle(
        ACPMessage.request(
            "session/load",
            {
                "sessionId": session_id,
                "cwd": "/tmp",
                "mcpServers": [],
            },
        )
    )

    assert loaded.response is not None
    replay_updates = [
        notification.params["update"]["sessionUpdate"]
        for notification in loaded.notifications
        if notification.params is not None
    ]
    assert "plan" in replay_updates


@pytest.mark.asyncio
async def test_session_set_mode_updates_current_mode() -> None:
    protocol = ACPProtocol()
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    outcome = await protocol.handle(
        ACPMessage.request(
            "session/set_mode",
            {
                "sessionId": session_id,
                "modeId": "code",
            },
        )
    )

    assert outcome.response is not None
    assert outcome.response.result == {}
    update_types = [
        notification.params["update"]["sessionUpdate"]
        for notification in outcome.notifications
        if notification.params is not None
    ]
    assert "current_mode_update" in update_types


@pytest.mark.asyncio
async def test_session_load_replays_tool_call_state() -> None:
    protocol = ACPProtocol()
    await _initialize_with_tool_runtime(protocol)
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "run tool"}],
                "_meta": {"promptDirectives": {"keepToolPending": True}},
            },
        )
    )
    assert prompt_outcome.response is None

    loaded = await protocol.handle(
        ACPMessage.request(
            "session/load",
            {
                "sessionId": session_id,
                "cwd": "/tmp",
                "mcpServers": [],
            },
        )
    )
    assert loaded.response is not None

    replay_updates = [
        notification.params["update"]["sessionUpdate"]
        for notification in loaded.notifications
        if notification.params is not None
    ]
    assert "tool_call" in replay_updates


@pytest.mark.asyncio
async def test_session_list_reads_persisted_sessions_after_restart(tmp_path) -> None:
    """Проверяет, что `session/list` видит JSON-сессии после рестарта процесса."""

    storage = JsonFileStorage(tmp_path / "sessions")
    protocol = ACPProtocol(storage=storage)
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    created_session_id = created.response.result["sessionId"]

    # Имитация рестарта сервера: новый инстанс протокола с тем же storage.
    restarted_protocol = ACPProtocol(storage=storage)
    listed = await restarted_protocol.handle(ACPMessage.request("session/list", {}))

    assert listed.response is not None
    assert isinstance(listed.response.result, dict)
    sessions = listed.response.result.get("sessions")
    assert isinstance(sessions, list)
    assert any(
        isinstance(item, dict) and item.get("sessionId") == created_session_id for item in sessions
    )


@pytest.mark.asyncio
async def test_session_load_reads_persisted_session_after_restart(tmp_path) -> None:
    """Проверяет, что `session/load` поднимает сессию из JSON storage после рестарта."""

    storage = JsonFileStorage(tmp_path / "sessions")
    protocol = ACPProtocol(storage=storage)
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    created_session_id = created.response.result["sessionId"]

    restarted_protocol = ACPProtocol(storage=storage)
    loaded = await restarted_protocol.handle(
        ACPMessage.request(
            "session/load",
            {
                "sessionId": created_session_id,
                "cwd": "/tmp",
                "mcpServers": [],
            },
        )
    )

    assert loaded.response is not None
    assert loaded.response.error is None
    assert isinstance(loaded.response.result, dict)
    assert "configOptions" in loaded.response.result


# ---------------------------------------------------------------------------
# Тесты реестра обработчиков (Handler Registry)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_method_returns_method_not_found():
    """Незарегистрированный метод возвращает -32601 Method Not Found."""
    protocol = ACPProtocol()
    outcome = await protocol.handle(ACPMessage.request("unknown/method", {}))
    assert outcome.response is not None
    assert outcome.response.error is not None
    assert outcome.response.error.code == -32601


@pytest.mark.asyncio
async def test_all_standard_methods_are_registered():
    """Все стандартные ACP методы зарегистрированы в реестре."""
    protocol = ACPProtocol()
    required_methods = [
        "initialize",
        "authenticate",
        "session/new",
        "session/load",
        "session/list",
        "session/prompt",
        "session/cancel",
        "session/request_permission_response",
        "session/set_config_option",
        "session/set_mode",
        "ping",
        "echo",
        "shutdown",
    ]
    for method in required_methods:
        assert method in protocol._handlers, f"Method not registered: {method}"


@pytest.mark.asyncio
async def test_notification_returns_empty_outcome():
    """Уведомления с неизвестным методом возвращают пустой outcome."""
    protocol = ACPProtocol()
    msg = ACPMessage.notification("unknown/notify", {})
    outcome = await protocol.handle(msg)
    assert outcome.response is None
    assert outcome.notifications == []


@pytest.mark.asyncio
async def test_middleware_is_called_for_registered_method():
    """Middleware вызывается для зарегистрированных методов."""
    call_log: list[str] = []

    async def logging_middleware(message, next_handler):
        call_log.append(f"before:{message.method}")
        result = await next_handler(message)
        call_log.append(f"after:{message.method}")
        return result

    protocol = ACPProtocol(middleware=[logging_middleware])
    outcome = await protocol.handle(ACPMessage.request("ping", {}))

    assert outcome.response is not None
    assert outcome.response.error is None
    assert call_log == ["before:ping", "after:ping"]


@pytest.mark.asyncio
async def test_middleware_is_not_called_for_unknown_method():
    """Middleware НЕ вызывается для неизвестных методов."""
    call_log: list[str] = []

    async def logging_middleware(message, next_handler):
        call_log.append(f"middleware:{message.method}")
        return await next_handler(message)

    protocol = ACPProtocol(middleware=[logging_middleware])
    await protocol.handle(ACPMessage.request("unknown/method", {}))

    assert call_log == []


@pytest.mark.asyncio
async def test_middleware_is_not_called_for_notifications():
    """Middleware НЕ вызывается для уведомлений."""
    call_log: list[str] = []

    async def logging_middleware(message, next_handler):
        call_log.append(f"middleware:{message.method}")
        return await next_handler(message)

    protocol = ACPProtocol(middleware=[logging_middleware])
    await protocol.handle(ACPMessage.notification("some/notify", {}))

    assert call_log == []


@pytest.mark.asyncio
async def test_multiple_middleware_applied_in_order():
    """Несколько middleware применяются в порядке onion pattern."""
    call_log: list[str] = []

    async def mw_outer(message, next_handler):
        call_log.append("outer:before")
        result = await next_handler(message)
        call_log.append("outer:after")
        return result

    async def mw_inner(message, next_handler):
        call_log.append("inner:before")
        result = await next_handler(message)
        call_log.append("inner:after")
        return result

    protocol = ACPProtocol(middleware=[mw_outer, mw_inner])
    await protocol.handle(ACPMessage.request("ping", {}))

    # Onion pattern: outer -> inner -> handler -> inner -> outer
    assert call_log == [
        "outer:before",
        "inner:before",
        "inner:after",
        "outer:after",
    ]


@pytest.mark.asyncio
async def test_middleware_can_modify_response():
    """Middleware может модифицировать результат."""

    async def error_middleware(message, next_handler):
        result = await next_handler(message)
        # Добавляем дополнительную notification
        from codelab.server.messages import ACPMessage

        extra = ACPMessage.notification("middleware/traced", {"method": message.method})
        result.notifications.append(extra)
        return result

    protocol = ACPProtocol(middleware=[error_middleware])
    outcome = await protocol.handle(ACPMessage.request("ping", {}))

    assert outcome.response is not None
    assert len(outcome.notifications) == 1
    assert outcome.notifications[0].method == "middleware/traced"


@pytest.mark.asyncio
async def test_handler_registry_dispatches_to_correct_handler():
    """Реестр корректно диспетчеризует к нужному обработчику."""
    protocol = ACPProtocol()

    # initialize
    init_outcome = await protocol.handle(
        ACPMessage.request("initialize", {"protocolVersion": 1, "clientCapabilities": {}})
    )
    assert init_outcome.response is not None
    assert init_outcome.response.error is None

    # ping
    ping_outcome = await protocol.handle(ACPMessage.request("ping", {}))
    assert ping_outcome.response is not None

    # echo
    echo_outcome = await protocol.handle(ACPMessage.request("echo", {"data": "test"}))
    assert echo_outcome.response is not None

    # shutdown
    shutdown_outcome = await protocol.handle(ACPMessage.request("shutdown", {}))
    assert shutdown_outcome.response is not None


@pytest.mark.asyncio
async def test_session_new_uses_shared_mcp_setup():
    """session/new использует единый метод _setup_mcp_if_needed."""
    protocol = ACPProtocol()
    outcome = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert outcome.response is not None
    assert outcome.response.error is None
    assert isinstance(outcome.response.result, dict)
    assert "sessionId" in outcome.response.result


@pytest.mark.asyncio
async def test_session_load_uses_shared_mcp_setup():
    """session/load использует единый метод _setup_mcp_if_needed."""
    protocol = ACPProtocol()

    # Создаём сессию
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    session_id = created.response.result["sessionId"]

    # Загружаем сессию
    loaded = await protocol.handle(
        ACPMessage.request(
            "session/load",
            {"sessionId": session_id, "cwd": "/tmp", "mcpServers": []},
        )
    )
    assert loaded.response is not None
    assert loaded.response.error is None


# ---------------------------------------------------------------------------
# Тесты инъекции PromptOrchestrator (2.7-inject-prompt-orchestrator)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_created_once():
    """PromptOrchestrator должен создаваться единожды."""
    from unittest.mock import MagicMock

    from codelab.server.tools.registry import ToolRegistry

    tool_registry = MagicMock(spec=ToolRegistry)
    protocol = ACPProtocol(tool_registry=tool_registry)

    orch1 = await protocol._get_prompt_orchestrator()
    orch2 = await protocol._get_prompt_orchestrator()

    assert orch1 is orch2


@pytest.mark.asyncio
async def test_orchestrator_can_be_injected():
    """Внешний PromptOrchestrator должен использоваться вместо создания нового."""
    from unittest.mock import MagicMock

    from codelab.server.protocol.handlers.prompt_orchestrator import PromptOrchestrator

    mock_orchestrator = MagicMock(spec=PromptOrchestrator)
    protocol = ACPProtocol(prompt_orchestrator=mock_orchestrator)

    result = await protocol._get_prompt_orchestrator()
    assert result is mock_orchestrator


@pytest.mark.asyncio
async def test_orchestrator_reset_after_policy_manager_init():
    """После инициализации GlobalPolicyManager оркестратор должен пересоздаться."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from codelab.server.tools.registry import ToolRegistry

    tool_registry = MagicMock(spec=ToolRegistry)
    protocol = ACPProtocol(tool_registry=tool_registry)

    orch_before = await protocol._get_prompt_orchestrator()
    assert orch_before is not None

    # Мокаем GlobalPolicyManager для теста
    mock_gpm = AsyncMock()
    mock_gpm.initialize = AsyncMock()
    with patch(
        "codelab.server.protocol.handlers.global_policy_manager.GlobalPolicyManager.get_instance",
        return_value=mock_gpm,
    ):
        await protocol.initialize_global_policy_manager()

    orch_after = await protocol._get_prompt_orchestrator()

    # Оркестратор пересоздан с новым policy manager
    assert orch_before is not orch_after


@pytest.mark.asyncio
async def test_get_prompt_orchestrator_returns_none_without_tool_registry():
    """_get_prompt_orchestrator возвращает None, если tool_registry не настроен."""
    protocol = ACPProtocol()

    result = await protocol._get_prompt_orchestrator()
    assert result is None

