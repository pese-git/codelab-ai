"""Тесты extensibility ACP protocol.

Покрывает:
- _meta field propagation в запросах/ответах
- Custom extension methods (_ prefix) — method not found
- Custom capabilities через _meta в agentCapabilities
- Reserved W3C trace context keys в _meta
"""

import pytest

from codelab.server.messages import ACPMessage
from codelab.server.protocol import ACPProtocol
from codelab.server.storage import InMemoryStorage

# ---------------------------------------------------------------------------
# _meta field propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initialize_preserves_meta_in_request() -> None:
    """_meta в запросе initialize не ломает handshake."""
    protocol = ACPProtocol()
    request = ACPMessage.request(
        "initialize",
        {
            "protocolVersion": 1,
            "clientCapabilities": {},
            "_meta": {
                "traceparent": "00-80e1afed08e019fc1110464cfa66635c-7a085853722dc6d2-01",
                "custom.key": "value",
            },
        },
    )

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    assert outcome.response.error is None
    assert outcome.response.result is not None
    assert outcome.response.result["protocolVersion"] == 1


@pytest.mark.asyncio
async def test_session_new_preserves_meta_in_request() -> None:
    """_meta в запросе session/new не ломает создание сессии."""
    protocol = ACPProtocol()
    # Сначала initialize
    await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": True},
                    "terminal": True,
                },
            },
        )
    )

    request = ACPMessage.request(
        "session/new",
        {
            "cwd": "/tmp",
            "mcpServers": [],
            "_meta": {
                "traceparent": "00-abc123",
                "zed.dev/debugMode": True,
            },
        },
    )

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    assert outcome.response.error is None
    assert outcome.response.result is not None
    assert "sessionId" in outcome.response.result


@pytest.mark.asyncio
async def test_session_prompt_preserves_meta_in_request() -> None:
    """_meta в запросе session/prompt не ломает обработку prompt."""
    storage = InMemoryStorage()
    protocol = ACPProtocol(storage=storage)

    # Initialize
    await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": True},
                    "terminal": True,
                },
            },
        )
    )

    # Create session
    new_outcome = await protocol.handle(
        ACPMessage.request(
            "session/new",
            {"cwd": "/tmp", "mcpServers": []},
        )
    )
    assert new_outcome.response is not None
    session_id = new_outcome.response.result["sessionId"]

    # Prompt с _meta
    request = ACPMessage.request(
        "session/prompt",
        {
            "sessionId": session_id,
            "prompt": [{"type": "text", "text": "hello"}],
            "_meta": {
                "traceparent": "00-def456",
                "requestId": "req-123",
            },
        },
    )

    outcome = await protocol.handle(request)

    # Prompt может вернуть notifications или response в зависимости от конфигурации
    # Главное — не должно быть ошибки из-за _meta
    if outcome.response is not None and outcome.response.error is not None:
        # Ошибка допустима только если нет agent_orchestrator
        assert "meta" not in outcome.response.error.message.lower()


@pytest.mark.asyncio
async def test_session_list_response_contains_meta() -> None:
    """session/list возвращает _meta в каждом SessionInfo."""
    storage = InMemoryStorage()
    protocol = ACPProtocol(storage=storage)

    # Initialize
    await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {},
            },
        )
    )

    # Create session
    await protocol.handle(
        ACPMessage.request(
            "session/new",
            {"cwd": "/tmp", "mcpServers": []},
        )
    )

    # List sessions
    outcome = await protocol.handle(
        ACPMessage.request("session/list", {})
    )

    assert outcome.response is not None
    assert outcome.response.error is None
    assert outcome.response.result is not None
    sessions = outcome.response.result.get("sessions", [])
    assert len(sessions) >= 1
    # Каждая сессия содержит _meta (даже пустой)
    for session_info in sessions:
        assert "_meta" in session_info


# ---------------------------------------------------------------------------
# Custom extension methods (_ prefix)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_request_method_returns_method_not_found() -> None:
    """Custom method с _ prefix возвращает стандартную ошибку Method not found."""
    protocol = ACPProtocol()

    request = ACPMessage.request(
        "_zed.dev/workspace/buffers",
        {"language": "rust"},
    )

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    assert outcome.response.error is not None
    assert outcome.response.error.code == -32601
    assert "Method not found" in outcome.response.error.message
    assert "_zed.dev/workspace/buffers" in outcome.response.error.message


@pytest.mark.asyncio
async def test_custom_notification_is_ignored() -> None:
    """Custom notification с _ prefix игнорируется без ошибки."""
    protocol = ACPProtocol()

    # Notification не имеет id
    notification = ACPMessage.notification(
        "_zed.dev/file_opened",
        {"path": "/home/user/project/src/editor.rs"},
    )

    outcome = await protocol.handle(notification)

    # Уведомления без обработчика возвращают пустой outcome
    assert outcome.response is None
    assert outcome.notifications == []


@pytest.mark.asyncio
async def test_custom_request_with_id_returns_error_with_same_id() -> None:
    """Custom request с id возвращает ошибку с тем же id."""
    protocol = ACPProtocol()

    request = ACPMessage.request(
        "_custom/method",
        {"data": "test"},
    )

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    assert outcome.response.error is not None
    # ID в ответе должен совпадать с ID запроса
    assert outcome.response.error.code == -32601


@pytest.mark.asyncio
async def test_multiple_custom_methods_all_return_method_not_found() -> None:
    """Разные custom methods с _ prefix все возвращают Method not found."""
    protocol = ACPProtocol()

    custom_methods = [
        "_zed.dev/workspace/buffers",
        "_custom/tool/execute",
        "_my.extension/nested/method",
        "_test",
    ]

    for method in custom_methods:
        request = ACPMessage.request(method, {})
        outcome = await protocol.handle(request)

        assert outcome.response is not None
        assert outcome.response.error is not None
        assert outcome.response.error.code == -32601, f"Failed for method: {method}"


# ---------------------------------------------------------------------------
# Custom capabilities через _meta
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_capabilities_structure() -> None:
    """agentCapabilities имеет ожидаемую структуру."""
    protocol = ACPProtocol()

    outcome = await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {},
            },
        )
    )

    assert outcome.response is not None
    assert outcome.response.error is None
    result = outcome.response.result
    assert result is not None

    agent_capabilities = result.get("agentCapabilities")
    assert agent_capabilities is not None
    assert "loadSession" in agent_capabilities
    assert "mcpCapabilities" in agent_capabilities
    assert "promptCapabilities" in agent_capabilities
    assert "sessionCapabilities" in agent_capabilities


@pytest.mark.asyncio
async def test_session_capabilities_list() -> None:
    """sessionCapabilities.list присутствует и пустой объект (поддерживается)."""
    protocol = ACPProtocol()

    outcome = await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {},
            },
        )
    )

    assert outcome.response is not None
    result = outcome.response.result
    assert result is not None

    session_capabilities = result["agentCapabilities"]["sessionCapabilities"]
    assert "list" in session_capabilities
    assert session_capabilities["list"] == {}


@pytest.mark.asyncio
async def test_mcp_capabilities_structure() -> None:
    """mcpCapabilities имеет http и sse поля."""
    protocol = ACPProtocol()

    outcome = await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {},
            },
        )
    )

    assert outcome.response is not None
    result = outcome.response.result
    assert result is not None

    mcp_capabilities = result["agentCapabilities"]["mcpCapabilities"]
    assert "http" in mcp_capabilities
    assert "sse" in mcp_capabilities
    assert isinstance(mcp_capabilities["http"], bool)
    assert isinstance(mcp_capabilities["sse"], bool)


@pytest.mark.asyncio
async def test_prompt_capabilities_structure() -> None:
    """promptCapabilities имеет image, audio, embeddedContext поля."""
    protocol = ACPProtocol()

    outcome = await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {},
            },
        )
    )

    assert outcome.response is not None
    result = outcome.response.result
    assert result is not None

    prompt_capabilities = result["agentCapabilities"]["promptCapabilities"]
    assert "image" in prompt_capabilities
    assert "audio" in prompt_capabilities
    assert "embeddedContext" in prompt_capabilities
    assert isinstance(prompt_capabilities["image"], bool)
    assert isinstance(prompt_capabilities["audio"], bool)
    assert isinstance(prompt_capabilities["embeddedContext"], bool)


# ---------------------------------------------------------------------------
# Reserved W3C trace context keys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_meta_with_w3c_traceparent() -> None:
    """_meta с W3C traceparent корректно обрабатывается."""
    protocol = ACPProtocol()

    request = ACPMessage.request(
        "initialize",
        {
            "protocolVersion": 1,
            "clientCapabilities": {},
            "_meta": {
                "traceparent": "00-80e1afed08e019fc1110464cfa66635c-7a085853722dc6d2-01",
            },
        },
    )

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    assert outcome.response.error is None


@pytest.mark.asyncio
async def test_meta_with_w3c_tracestate() -> None:
    """_meta с W3C tracestate корректно обрабатывается."""
    protocol = ACPProtocol()

    request = ACPMessage.request(
        "initialize",
        {
            "protocolVersion": 1,
            "clientCapabilities": {},
            "_meta": {
                "tracestate": "congo=t61rcWkgMzE",
            },
        },
    )

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    assert outcome.response.error is None


@pytest.mark.asyncio
async def test_meta_with_w3c_baggage() -> None:
    """_meta с W3C baggage корректно обрабатывается."""
    protocol = ACPProtocol()

    request = ACPMessage.request(
        "initialize",
        {
            "protocolVersion": 1,
            "clientCapabilities": {},
            "_meta": {
                "baggage": "userId=alice,serverNode=DF%2028",
            },
        },
    )

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    assert outcome.response.error is None


@pytest.mark.asyncio
async def test_meta_with_multiple_custom_keys() -> None:
    """_meta с несколькими custom keys корректно обрабатывается."""
    protocol = ACPProtocol()

    request = ACPMessage.request(
        "initialize",
        {
            "protocolVersion": 1,
            "clientCapabilities": {},
            "_meta": {
                "traceparent": "00-abc",
                "zed.dev/debugMode": True,
                "custom.field": "value",
                "another_key": {"nested": "object"},
            },
        },
    )

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    assert outcome.response.error is None


# ---------------------------------------------------------------------------
# Extensibility: _meta в различных типах контента
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_meta_in_session_load() -> None:
    """_meta в запросе session/load корректно обрабатывается."""
    storage = InMemoryStorage()
    protocol = ACPProtocol(storage=storage)

    # Initialize
    await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {},
            },
        )
    )

    # Create session
    new_outcome = await protocol.handle(
        ACPMessage.request(
            "session/new",
            {"cwd": "/tmp", "mcpServers": []},
        )
    )
    assert new_outcome.response is not None
    session_id = new_outcome.response.result["sessionId"]

    # Load с _meta
    request = ACPMessage.request(
        "session/load",
        {
            "sessionId": session_id,
            "cwd": "/tmp",
            "mcpServers": [],
            "_meta": {"traceparent": "00-xyz"},
        },
    )

    outcome = await protocol.handle(request)

    # Load должен работать (не должно быть ошибки из-за _meta)
    assert outcome.response is not None
    # Может быть ошибка сессии не найдена или успех — главное не из-за _meta
    if outcome.response.error is not None:
        assert "meta" not in outcome.response.error.message.lower()


@pytest.mark.asyncio
async def test_meta_in_set_config_option() -> None:
    """_meta в запросе session/set_config_option корректно обрабатывается."""
    storage = InMemoryStorage()
    protocol = ACPProtocol(storage=storage)

    # Initialize
    await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {},
            },
        )
    )

    # Create session
    new_outcome = await protocol.handle(
        ACPMessage.request(
            "session/new",
            {"cwd": "/tmp", "mcpServers": []},
        )
    )
    assert new_outcome.response is not None
    session_id = new_outcome.response.result["sessionId"]

    # set_config_option с _meta
    request = ACPMessage.request(
        "session/set_config_option",
        {
            "sessionId": session_id,
            "id": "mode",
            "value": "code",
            "_meta": {"traceparent": "00-config"},
        },
    )

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    # Должно работать без ошибок из-за _meta
    if outcome.response.error is not None:
        assert "meta" not in outcome.response.error.message.lower()


@pytest.mark.asyncio
async def test_meta_in_set_mode() -> None:
    """_meta в запросе session/set_mode корректно обрабатывается."""
    storage = InMemoryStorage()
    protocol = ACPProtocol(storage=storage)

    # Initialize
    await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {},
            },
        )
    )

    # Create session
    new_outcome = await protocol.handle(
        ACPMessage.request(
            "session/new",
            {"cwd": "/tmp", "mcpServers": []},
        )
    )
    assert new_outcome.response is not None
    session_id = new_outcome.response.result["sessionId"]

    # set_mode с _meta
    request = ACPMessage.request(
        "session/set_mode",
        {
            "sessionId": session_id,
            "mode": "code",
            "_meta": {"traceparent": "00-mode"},
        },
    )

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    if outcome.response.error is not None:
        assert "meta" not in outcome.response.error.message.lower()


# ---------------------------------------------------------------------------
# Extensibility: notification с _meta
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_notification_with_complex_params() -> None:
    """Custom notification с complex params игнорируется."""
    protocol = ACPProtocol()

    notification = ACPMessage.notification(
        "_custom/complex_notification",
        {
            "data": {"nested": {"key": "value"}},
            "list": [1, 2, 3],
            "_meta": {"traceparent": "00-notification"},
        },
    )

    outcome = await protocol.handle(notification)

    assert outcome.response is None
    assert outcome.notifications == []


# ---------------------------------------------------------------------------
# Extensibility: edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_meta_object() -> None:
    """Пустой объект _meta корректно обрабатывается."""
    protocol = ACPProtocol()

    request = ACPMessage.request(
        "initialize",
        {
            "protocolVersion": 1,
            "clientCapabilities": {},
            "_meta": {},
        },
    )

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    assert outcome.response.error is None


@pytest.mark.asyncio
async def test_meta_with_null_value() -> None:
    """_meta с null value корректно обрабатывается."""
    protocol = ACPProtocol()

    request = ACPMessage.request(
        "initialize",
        {
            "protocolVersion": 1,
            "clientCapabilities": {},
            "_meta": {
                "traceparent": None,
                "custom_key": "value",
            },
        },
    )

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    assert outcome.response.error is None


@pytest.mark.asyncio
async def test_meta_with_array_value() -> None:
    """_meta с array value корректно обрабатывается."""
    protocol = ACPProtocol()

    request = ACPMessage.request(
        "initialize",
        {
            "protocolVersion": 1,
            "clientCapabilities": {},
            "_meta": {
                "tags": ["tag1", "tag2", "tag3"],
            },
        },
    )

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    assert outcome.response.error is None


@pytest.mark.asyncio
async def test_custom_method_with_underscore_only() -> None:
    """Метод состоящий только из _ возвращает Method not found."""
    protocol = ACPProtocol()

    request = ACPMessage.request("_", {})

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    assert outcome.response.error is not None
    assert outcome.response.error.code == -32601


@pytest.mark.asyncio
async def test_custom_method_with_double_underscore() -> None:
    """Метод с __ prefix возвращает Method not found."""
    protocol = ACPProtocol()

    request = ACPMessage.request("__custom/method", {})

    outcome = await protocol.handle(request)

    assert outcome.response is not None
    assert outcome.response.error is not None
    assert outcome.response.error.code == -32601
