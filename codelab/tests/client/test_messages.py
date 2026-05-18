import pytest
from pydantic import ValidationError

from codelab.client.messages import (
    ACPMessage,
    AudioContentBlock,
    AvailableCommandInput,
    AvailableCommandsUpdate,
    ConfigOptionUpdate,
    CurrentModeUpdate,
    ImageContentBlock,
    InitializeResult,
    JsonRpcError,
    MessageChunkUpdate,
    PlanUpdate,
    RequestPermissionRequest,
    ResourceLinkContentBlock,
    SessionInfoUpdate,
    SessionListResult,
    SessionSetupResult,
    TextContentBlock,
    ThoughtChunkUpdate,
    ToolCallContentBlock,
    ToolCallCreatedUpdate,
    ToolCallDiffContent,
    ToolCallLocation,
    ToolCallStateUpdate,
    ToolCallTerminalContent,
    parse_authenticate_result,
    parse_initialize_result,
    parse_json_params,
    parse_plan_update,
    parse_prompt_result,
    parse_request_permission_request,
    parse_session_list_result,
    parse_session_setup_result,
    parse_session_update_notification,
    parse_structured_session_update,
    parse_tool_call_update,
)


def test_parse_json_params_object() -> None:
    params = parse_json_params('{"x":1,"y":"ok"}')
    assert params == {"x": 1, "y": "ok"}


def test_parse_json_params_requires_object() -> None:
    with pytest.raises(ValueError):
        parse_json_params("[1, 2]")


def test_message_to_from_dict() -> None:
    request = ACPMessage.request(method="initialize", params={"protocolVersion": 1, "clientCapabilities": {}})
    restored = ACPMessage.from_dict(request.to_dict())
    assert restored.method == "initialize"


def test_parse_session_update_notification() -> None:
    payload = {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": "sess_1",
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "hello"},
            },
        },
    }
    parsed = parse_session_update_notification(payload)
    assert parsed is not None
    assert parsed.params.sessionId == "sess_1"
    assert parsed.params.update.sessionUpdate == "agent_message_chunk"


def test_parse_session_update_notification_ignores_other_methods() -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": "req_1",
        "result": {},
    }
    parsed = parse_session_update_notification(payload)
    assert parsed is None


def test_parse_tool_call_created_update() -> None:
    notification = parse_session_update_notification(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess_1",
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "call_001",
                    "title": "Demo tool",
                    "kind": "other",
                    "status": "pending",
                },
            },
        }
    )
    assert notification is not None

    parsed = parse_tool_call_update(notification)
    assert isinstance(parsed, ToolCallCreatedUpdate)
    assert parsed.toolCallId == "call_001"


def test_parse_tool_call_state_update() -> None:
    notification = parse_session_update_notification(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess_1",
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "call_001",
                    "status": "completed",
                    "content": [
                        {
                            "type": "content",
                            "content": {"type": "text", "text": "ok"},
                        }
                    ],
                },
            },
        }
    )
    assert notification is not None

    parsed = parse_tool_call_update(notification)
    assert isinstance(parsed, ToolCallStateUpdate)
    assert parsed.status == "completed"


def test_parse_tool_call_state_update_with_typed_content_and_locations() -> None:
    notification = parse_session_update_notification(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess_1",
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "call_002",
                    "status": "in_progress",
                    "locations": [{"path": "src/main.py", "line": 7}],
                    "content": [
                        {
                            "type": "content",
                            "content": {"type": "text", "text": "step 1"},
                        },
                        {
                            "type": "diff",
                            "path": "README.md",
                            "oldText": "old",
                            "newText": "new",
                        },
                        {
                            "type": "terminal",
                            "terminalId": "term_1",
                        },
                    ],
                },
            },
        }
    )
    assert notification is not None

    parsed = parse_tool_call_update(notification)
    assert isinstance(parsed, ToolCallStateUpdate)
    assert parsed.locations is not None
    assert isinstance(parsed.locations[0], ToolCallLocation)
    assert parsed.content is not None
    assert isinstance(parsed.content[0], ToolCallContentBlock)
    assert isinstance(parsed.content[1], ToolCallDiffContent)
    assert isinstance(parsed.content[2], ToolCallTerminalContent)


def test_parse_request_permission_request() -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": "perm_1",
        "method": "session/request_permission",
        "params": {
            "sessionId": "sess_1",
            "toolCall": {"toolCallId": "call_001"},
            "options": [
                {
                    "optionId": "allow_once",
                    "name": "Allow once",
                    "kind": "allow_once",
                }
            ],
        },
    }
    parsed = parse_request_permission_request(payload)
    assert isinstance(parsed, RequestPermissionRequest)
    assert parsed.id == "perm_1"
    assert parsed.params.options[0].optionId == "allow_once"


def test_parse_request_permission_request_rejects_unknown_option_kind() -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": "perm_1",
        "method": "session/request_permission",
        "params": {
            "sessionId": "sess_1",
            "toolCall": {"toolCallId": "call_001"},
            "options": [
                {
                    "optionId": "reject",
                    "name": "Reject",
                    "kind": "reject",
                }
            ],
        },
    }
    with pytest.raises(ValidationError):
        parse_request_permission_request(payload)


def test_parse_plan_update() -> None:
    notification = parse_session_update_notification(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess_1",
                "update": {
                    "sessionUpdate": "plan",
                    "entries": [
                        {
                            "content": "Подготовить изменения",
                            "priority": "high",
                            "status": "in_progress",
                        }
                    ],
                },
            },
        }
    )
    assert notification is not None

    parsed = parse_plan_update(notification)
    assert isinstance(parsed, PlanUpdate)
    assert parsed.entries[0].priority == "high"


def test_parse_initialize_result_success() -> None:
    response = ACPMessage.response(
        "init_1",
        {
            "protocolVersion": 1,
            "agentCapabilities": {
                "loadSession": True,
                "promptCapabilities": {"image": False},
                "mcpCapabilities": {"http": False, "sse": False},
                "sessionCapabilities": {"list": {}},
            },
            "agentInfo": {"name": "codelab-server", "version": "0.1.0"},
            "authMethods": [],
        },
    )

    parsed = parse_initialize_result(response)
    assert isinstance(parsed, InitializeResult)
    assert parsed.protocolVersion == 1
    assert parsed.agentCapabilities.loadSession is True


def test_parse_initialize_result_parses_auth_methods() -> None:
    response = ACPMessage.response(
        "init_2",
        {
            "protocolVersion": 1,
            "agentCapabilities": {
                "loadSession": True,
                "promptCapabilities": {"image": False},
                "mcpCapabilities": {"http": False, "sse": False},
                "sessionCapabilities": {"list": {}},
            },
            "authMethods": [
                {
                    "id": "local",
                    "name": "Local authentication",
                    "type": "api_key",
                }
            ],
        },
    )

    parsed = parse_initialize_result(response)
    assert len(parsed.authMethods) == 1
    assert parsed.authMethods[0].id == "local"


def test_parse_initialize_result_error_response_raises() -> None:
    response = ACPMessage(
        id="init_1",
        error=JsonRpcError(code=-32602, message="Invalid params"),
    )

    with pytest.raises(ValueError):
        parse_initialize_result(response)


def test_parse_authenticate_result_success() -> None:
    response = ACPMessage.response("auth_1", {})

    parsed = parse_authenticate_result(response)
    assert parsed.model_dump() == {}


def test_parse_session_list_result_success() -> None:
    response = ACPMessage.response(
        "list_1",
        {
            "sessions": [
                {
                    "sessionId": "sess_1",
                    "cwd": "/tmp",
                    "title": "Demo",
                    "updatedAt": "2026-04-07T00:00:00Z",
                }
            ],
            "nextCursor": "cursor_2",
        },
    )

    parsed = parse_session_list_result(response)
    assert isinstance(parsed, SessionListResult)
    assert len(parsed.sessions) == 1
    assert parsed.sessions[0].sessionId == "sess_1"
    assert parsed.nextCursor == "cursor_2"


def test_parse_session_list_result_error_response_raises() -> None:
    response = ACPMessage(
        id="list_1",
        error=JsonRpcError(code=-32602, message="Invalid params"),
    )

    with pytest.raises(ValueError):
        parse_session_list_result(response)


def test_parse_session_setup_result_success() -> None:
    response = ACPMessage.response(
        "new_1",
        {
            "sessionId": "sess_1",
            "configOptions": [
                {
                    "id": "mode",
                    "name": "Mode",
                    "category": "mode",
                    "type": "select",
                    "currentValue": "ask",
                    "options": [{"value": "ask", "name": "Ask"}],
                }
            ],
            "modes": {
                "availableModes": [{"id": "ask", "name": "Ask"}],
                "currentModeId": "ask",
            },
        },
    )

    parsed = parse_session_setup_result(response, method_name="session/new")
    assert isinstance(parsed, SessionSetupResult)
    assert parsed.sessionId == "sess_1"
    assert parsed.configOptions[0].id == "mode"
    assert parsed.modes is not None
    assert parsed.modes.currentModeId == "ask"


def test_parse_session_setup_result_error_response_raises() -> None:
    response = ACPMessage(
        id="load_1",
        error=JsonRpcError(code=-32001, message="Session not found"),
    )

    with pytest.raises(ValueError):
        parse_session_setup_result(response, method_name="session/load")


@pytest.mark.parametrize(
    "stop_reason",
    ["end_turn", "max_tokens", "max_turn_requests", "refusal", "cancelled"],
)
def test_parse_prompt_result_accepts_all_supported_stop_reasons(stop_reason: str) -> None:
    response = ACPMessage.response("prompt_1", {"stopReason": stop_reason})

    parsed = parse_prompt_result(response)
    assert parsed.stopReason == stop_reason


def test_parse_structured_session_update_for_message_chunk() -> None:
    notification = parse_session_update_notification(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess_1",
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "hello"},
                },
            },
        }
    )
    assert notification is not None

    parsed = parse_structured_session_update(notification)
    assert isinstance(parsed, MessageChunkUpdate)
    assert isinstance(parsed.content, TextContentBlock)


def test_parse_structured_session_update_for_non_text_content_blocks() -> None:
    fixtures: list[tuple[dict[str, object], type[object]]] = [
        (
            {
                "sessionUpdate": "agent_message_chunk",
                "content": {
                    "type": "image",
                    "mimeType": "image/png",
                    "data": "iVBORw0KGgoAAAANSUhEUg==",
                },
            },
            ImageContentBlock,
        ),
        (
            {
                "sessionUpdate": "agent_message_chunk",
                "content": {
                    "type": "audio",
                    "mimeType": "audio/wav",
                    "data": "UklGRjQAAABXQVZFZm10",
                },
            },
            AudioContentBlock,
        ),
        (
            {
                "sessionUpdate": "agent_message_chunk",
                "content": {
                    "type": "resource_link",
                    "uri": "file:///tmp/README.md",
                    "name": "README.md",
                },
            },
            ResourceLinkContentBlock,
        ),
    ]

    for payload, expected_content_type in fixtures:
        notification = parse_session_update_notification(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": "sess_1",
                    "update": payload,
                },
            }
        )
        assert notification is not None
        parsed = parse_structured_session_update(notification)
        assert isinstance(parsed, MessageChunkUpdate)
        assert isinstance(parsed.content, expected_content_type)


def test_parse_structured_session_update_for_thought_chunk() -> None:
    notification = parse_session_update_notification(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess_1",
                "update": {
                    "sessionUpdate": "agent_thought_chunk",
                    "content": {"type": "text", "text": "thinking"},
                },
            },
        }
    )
    assert notification is not None

    parsed = parse_structured_session_update(notification)
    assert isinstance(parsed, ThoughtChunkUpdate)


def test_parse_structured_session_update_for_session_state_updates() -> None:
    fixtures: list[tuple[dict[str, object], type[object]]] = [
        (
            {
                "sessionUpdate": "session_info_update",
                "title": "Test",
                "updatedAt": "2026-04-07T00:00:00Z",
            },
            SessionInfoUpdate,
        ),
        (
            {
                "sessionUpdate": "current_mode_update",
                "currentModeId": "ask",
            },
            CurrentModeUpdate,
        ),
        (
            {
                "sessionUpdate": "available_commands_update",
                "availableCommands": [
                    {
                        "name": "status",
                        "description": "show",
                        "input": {"hint": "optional query"},
                    }
                ],
            },
            AvailableCommandsUpdate,
        ),
        (
            {
                "sessionUpdate": "config_option_update",
                "configOptions": [
                    {
                        "id": "mode",
                        "name": "Mode",
                        "category": "mode",
                        "type": "select",
                        "currentValue": "ask",
                        "options": [{"value": "ask", "name": "Ask"}],
                    }
                ],
            },
            ConfigOptionUpdate,
        ),
    ]

    for payload, expected_type in fixtures:
        notification = parse_session_update_notification(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": "sess_1",
                    "update": payload,
                },
            }
        )
        assert notification is not None
        parsed = parse_structured_session_update(notification)
        assert isinstance(parsed, expected_type)
        if isinstance(parsed, AvailableCommandsUpdate):
            assert parsed.availableCommands[0].input is not None
            assert isinstance(parsed.availableCommands[0].input, AvailableCommandInput)


def test_parse_structured_session_update_rejects_invalid_current_mode_shape() -> None:
    notification = parse_session_update_notification(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess_1",
                "update": {
                    "sessionUpdate": "current_mode_update",
                    "modeId": "ask",
                },
            },
        }
    )
    assert notification is not None

    with pytest.raises(ValidationError):
        parse_structured_session_update(notification)
