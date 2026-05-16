import pytest

from codelab.server.messages import ACPMessage
from codelab.server.protocol import ACPProtocol


async def _initialize_with_tool_runtime(protocol: ACPProtocol) -> None:
    """Инициализирует capability profile, разрешающий tool-runtime сценарии."""

    initialized = await protocol.handle(
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
    assert initialized.response is not None
    assert initialized.response.error is None


async def _initialize_with_fs_runtime(protocol: ACPProtocol) -> None:
    """Инициализирует capability profile для fs client-rpc сценариев."""

    initialized = await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": True},
                    "terminal": False,
                },
            },
        )
    )
    assert initialized.response is not None
    assert initialized.response.error is None


@pytest.mark.asyncio
async def test_conformance_prompt_returns_end_turn_with_agent_update() -> None:
    """Проверяет базовый ACP prompt-cycle: update-поток + финальный end_turn."""

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
                "prompt": [{"type": "text", "text": "hello"}],
            },
        )
    )

    assert prompted.response is not None
    assert prompted.response.result == {"stopReason": "end_turn"}
    update_types = [
        notification.params["update"]["sessionUpdate"]
        for notification in prompted.notifications
        if notification.params is not None
    ]
    assert "agent_message_chunk" in update_types


@pytest.mark.asyncio
async def test_conformance_cancel_while_waiting_permission_returns_cancelled() -> None:
    """Проверяет обязательный ACP-инвариант: cancel завершает turn как cancelled."""

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
                "prompt": [{"type": "text", "text": "/tool run"}],
            },
        )
    )
    assert prompt_outcome.response is None

    cancel_outcome = await protocol.handle(
        ACPMessage.notification("session/cancel", {"sessionId": session_id})
    )
    assert len(cancel_outcome.followup_responses) == 1
    assert cancel_outcome.followup_responses[0].result == {"stopReason": "cancelled"}


@pytest.mark.asyncio
async def test_conformance_permission_selected_completes_turn() -> None:
    """Проверяет ACP permission-flow: selected/allow завершает turn как end_turn."""

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
                "prompt": [{"type": "text", "text": "/tool run"}],
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

    permission_resolved = await protocol.handle_client_response(
        ACPMessage.response(
            permission_request.id,
            {
                "outcome": {
                    "outcome": "selected",
                    "optionId": "allow_once",
                }
            },
        )
    )
    # Новый async flow: permission approval возвращает pending_tool_execution
    # Turn completion происходит в http_server после async выполнения tool
    assert permission_resolved.pending_tool_execution is not None
    assert permission_resolved.pending_tool_execution.session_id == session_id


@pytest.mark.asyncio
async def test_conformance_load_replays_history_and_stateful_updates() -> None:
    """Проверяет load replay для истории, plan и tool call состояния."""

    protocol = ACPProtocol()
    await _initialize_with_tool_runtime(protocol)
    created = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    _ = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "/plan release checklist"}],
            },
        )
    )
    _ = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "/tool-pending run"}],
            },
        )
    )

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

    replay_types = [
        notification.params["update"]["sessionUpdate"]
        for notification in loaded.notifications
        if notification.params is not None
    ]
    assert "user_message_chunk" in replay_types
    assert "agent_message_chunk" in replay_types
    assert "plan" in replay_types
    assert "tool_call" in replay_types


@pytest.mark.asyncio
async def test_conformance_fs_client_rpc_error_marks_tool_failed() -> None:
    """Проверяет fs edge-case: client-rpc error переводит tool_call в failed."""

    protocol = ACPProtocol()
    await _initialize_with_fs_runtime(protocol)
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
                "prompt": [{"type": "text", "text": "/fs-read README.md"}],
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
            code=-32050,
            message="Read failed",
        )
    )
    assert len(resolved.followup_responses) == 1
    assert resolved.followup_responses[0].result == {"stopReason": "end_turn"}
    assert any(
        notification.params is not None
        and notification.params["update"].get("sessionUpdate") == "tool_call_update"
        and notification.params["update"].get("status") == "failed"
        for notification in resolved.notifications
    )


@pytest.mark.asyncio
async def test_conformance_terminal_client_rpc_lifecycle_completes() -> None:
    """Проверяет terminal edge-case: create/output/wait/release завершают turn."""

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
                "prompt": [{"type": "text", "text": "/term-run echo ok"}],
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

    create_resolved = await protocol.handle_client_response(
        ACPMessage.response(create_request.id, {"terminalId": "term_1"})
    )
    output_request = next(
        notification
        for notification in create_resolved.notifications
        if notification.method == "terminal/output"
    )
    assert output_request.id is not None

    output_resolved = await protocol.handle_client_response(
        ACPMessage.response(output_request.id, {"output": "ok"})
    )
    wait_request = next(
        notification
        for notification in output_resolved.notifications
        if notification.method == "terminal/wait_for_exit"
    )
    assert wait_request.id is not None

    wait_resolved = await protocol.handle_client_response(
        ACPMessage.response(wait_request.id, {"exitCode": 0})
    )
    release_request = next(
        notification
        for notification in wait_resolved.notifications
        if notification.method == "terminal/release"
    )
    assert release_request.id is not None

    released = await protocol.handle_client_response(ACPMessage.response(release_request.id, {}))
    assert len(released.followup_responses) == 1
    assert released.followup_responses[0].result == {"stopReason": "end_turn"}
    assert any(
        notification.params is not None
        and notification.params["update"].get("sessionUpdate") == "tool_call_update"
        and notification.params["update"].get("status") == "completed"
        for notification in released.notifications
    )
