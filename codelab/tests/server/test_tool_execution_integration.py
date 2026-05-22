"""Интеграционные тесты: NaiveAgent + SessionState через start_turn/continue_turn."""

import pytest

from codelab.server.agent.base import AgentContext, ContinuationContext
from codelab.server.agent.naive import NaiveAgent
from codelab.server.llm.base import LLMMessage, LLMToolCall
from codelab.server.llm.mock_provider import MockLLMProvider
from codelab.server.protocol.state import SessionState
from codelab.server.tools.base import ToolDefinition
from codelab.server.tools.registry import SimpleToolRegistry


def echo_tool(text: str) -> str:
    return f"Echo: {text}"


@pytest.fixture
def tool_registry() -> SimpleToolRegistry:
    registry = SimpleToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo",
            description="Возвращает переданный текст",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}},
            kind="other",
        ),
        echo_tool,
    )
    return registry


@pytest.fixture
def session_state() -> SessionState:
    return SessionState(
        session_id="integration-test-session",
        cwd="/tmp",
        mcp_servers=[],
        title="Integration Test Session",
    )


@pytest.mark.asyncio
async def test_start_turn_with_session_state(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """start_turn корректно передаёт SessionState в контекст и возвращает tool_calls."""
    tool_call = LLMToolCall(id="call_1", name="echo", arguments={"text": "Hello"})
    agent = NaiveAgent(
        llm=MockLLMProvider(response="Буду echo", tool_calls=[tool_call]),
        tools=tool_registry,
    )

    context = AgentContext(
        session_id="integration-test-session",
        session=session_state,
        prompt=[{"type": "text", "text": "Echo something"}],
        conversation_history=[],
        available_tools=tool_registry.list_tools(),
        config={},
    )

    # session передаётся в контекст
    assert context.session is session_state

    response = await agent.start_turn(context)

    assert response.text == "Буду echo"
    assert response.stop_reason == "tool_use"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "echo"


@pytest.mark.asyncio
async def test_continue_turn_with_tool_result(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """continue_turn получает историю с tool_result и возвращает финальный текст."""
    # История после первого turn + выполнения tool
    history = [
        LLMMessage(role="user", content="Echo hello"),
        LLMMessage(
            role="assistant",
            content="",
            tool_calls=[LLMToolCall(id="c1", name="echo", arguments={"text": "hello"})],
        ),
        LLMMessage(role="tool", content="Echo: hello", tool_call_id="c1"),
    ]

    agent = NaiveAgent(
        llm=MockLLMProvider(response="Готово, вот эхо"),
        tools=tool_registry,
    )

    context = ContinuationContext(
        session_id="integration-test-session",
        session=session_state,
        history=history,
        available_tools=tool_registry.list_tools(),
        config={},
    )

    response = await agent.continue_turn(context)

    assert response.text == "Готово, вот эхо"
    assert response.tool_calls == []
    assert response.stop_reason == "end_turn"


@pytest.mark.asyncio
async def test_multiple_tool_calls_in_start_turn(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """start_turn возвращает несколько tool_calls — LLMLoopStage обработает их по очереди."""
    tool_calls = [
        LLMToolCall(id="c1", name="echo", arguments={"text": "First"}),
        LLMToolCall(id="c2", name="echo", arguments={"text": "Second"}),
    ]
    agent = NaiveAgent(
        llm=MockLLMProvider(response="", tool_calls=tool_calls),
        tools=tool_registry,
    )

    context = AgentContext(
        session_id="integration-test-session",
        session=session_state,
        prompt=[{"type": "text", "text": "Execute multiple tools"}],
        conversation_history=[],
        available_tools=tool_registry.list_tools(),
        config={},
    )

    response = await agent.start_turn(context)

    assert len(response.tool_calls) == 2


@pytest.mark.asyncio
async def test_session_state_not_mutated_by_agent(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """NaiveAgent не мутирует SessionState — это ответственность AgentOrchestrator."""
    original_session_id = session_state.session_id
    original_cwd = session_state.cwd
    original_history_len = len(session_state.history)

    agent = NaiveAgent(
        llm=MockLLMProvider(response="ok"),
        tools=tool_registry,
    )

    context = AgentContext(
        session_id="integration-test-session",
        session=session_state,
        prompt=[{"type": "text", "text": "Test"}],
        conversation_history=[],
        available_tools=tool_registry.list_tools(),
        config={},
    )

    await agent.start_turn(context)

    # SessionState не должен быть изменён агентом
    assert session_state.session_id == original_session_id
    assert session_state.cwd == original_cwd
    assert len(session_state.history) == original_history_len
