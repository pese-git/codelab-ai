"""Unit-тесты для NaiveAgent.

Тестируем два явных контракта:
  - start_turn: добавляет user message, возвращает AgentResponse
  - continue_turn: НЕ добавляет user message, использует историю как есть
"""

import asyncio
from typing import Any

import pytest

from codelab.server.agent.base import AgentContext, ContinuationContext
from codelab.server.agent.naive import NaiveAgent, _format_prompt, _to_openai_tools_format
from codelab.server.llm.base import LLMMessage, LLMResponse, LLMToolCall
from codelab.server.llm.mock_provider import MockLLMProvider
from codelab.server.protocol.state import SessionState
from codelab.server.tools.base import ToolDefinition
from codelab.server.tools.registry import SimpleToolRegistry

# ============================================================================
# Вспомогательные инструменты
# ============================================================================


def simple_calculator(operation: str, a: float, b: float) -> float:
    """Простой калькулятор для тестов."""
    if operation == "add":
        return a + b
    elif operation == "subtract":
        return a - b
    elif operation == "multiply":
        return a * b
    elif operation == "divide":
        if b == 0:
            raise ValueError("Деление на ноль")
        return a / b
    else:
        raise ValueError(f"Неизвестная операция: {operation}")


def echo_tool(text: str) -> str:
    """Echo инструмент для тестов."""
    return f"Echo: {text}"


# ============================================================================
# Фикстуры
# ============================================================================


@pytest.fixture
def tool_registry() -> SimpleToolRegistry:
    """Реестр с тестовыми инструментами."""
    registry = SimpleToolRegistry()

    registry.register(
        ToolDefinition(
            name="calculator",
            description="Выполняет математические операции",
            parameters={
                "type": "object",
                "properties": {
                    "operation": {"type": "string"},
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
            },
            kind="math",
        ),
        simple_calculator,
    )
    registry.register(
        ToolDefinition(
            name="echo",
            description="Возвращает переданный текст",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
            },
            kind="other",
        ),
        echo_tool,
    )
    return registry


@pytest.fixture
def naive_agent(tool_registry: SimpleToolRegistry) -> NaiveAgent:
    """NaiveAgent с MockLLMProvider."""
    return NaiveAgent(llm=MockLLMProvider(response="Test response"), tools=tool_registry)


@pytest.fixture
def session_state() -> SessionState:
    """Базовый SessionState для тестов."""
    return SessionState(session_id="test-session", cwd="/tmp", mcp_servers=[])


def _make_context(
    session_state: SessionState,
    tool_registry: SimpleToolRegistry,
    prompt_text: str = "Hello",
    history: list[LLMMessage] | None = None,
) -> AgentContext:
    """Вспомогательная фабрика AgentContext."""
    return AgentContext(
        session_id=session_state.session_id,
        session=session_state,
        prompt=[{"type": "text", "text": prompt_text}],
        conversation_history=history or [],
        available_tools=tool_registry.list_tools(),
        config={},
    )


def _make_continuation(
    session_state: SessionState,
    tool_registry: SimpleToolRegistry,
    history: list[LLMMessage],
) -> ContinuationContext:
    """Вспомогательная фабрика ContinuationContext."""
    return ContinuationContext(
        session_id=session_state.session_id,
        session=session_state,
        history=history,
        available_tools=tool_registry.list_tools(),
        config={},
    )


# ============================================================================
# Тесты start_turn
# ============================================================================


@pytest.mark.asyncio
async def test_start_turn_simple_text_response(
    naive_agent: NaiveAgent,
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """start_turn возвращает текстовый ответ без tool_calls."""
    context = _make_context(session_state, tool_registry, "Hello, agent!")
    response = await naive_agent.start_turn(context)

    assert response.text == "Test response"
    assert response.tool_calls == []
    assert response.stop_reason == "end_turn"


@pytest.mark.asyncio
async def test_start_turn_adds_user_message(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """start_turn добавляет user message к истории перед вызовом LLM.

    Проверяем что LLM получает: [history..., user(промпт)].
    """
    captured_messages: list[list[LLMMessage]] = []

    class CapturingProvider(MockLLMProvider):
        async def create_completion(
            self,
            messages: list[LLMMessage],
            tools: list[dict[str, Any]] | None = None,
            **kwargs: Any,
        ) -> LLMResponse:
            captured_messages.append(list(messages))
            return await super().create_completion(messages, tools, **kwargs)

    prior_history = [
        LLMMessage(role="user", content="Предыдущее сообщение"),
        LLMMessage(role="assistant", content="Предыдущий ответ"),
    ]

    agent = NaiveAgent(llm=CapturingProvider(response="ok"), tools=tool_registry)
    context = AgentContext(
        session_id="test",
        session=session_state,
        prompt=[{"type": "text", "text": "Новый промпт"}],
        conversation_history=prior_history,
        available_tools=tool_registry.list_tools(),
        config={},
    )
    await agent.start_turn(context)

    assert len(captured_messages) == 1
    sent = captured_messages[0]
    # Последнее сообщение должно быть user с текстом промпта
    assert sent[-1].role == "user"
    assert sent[-1].content == "Новый промпт"
    # До него должна быть история
    assert len(sent) == 3


@pytest.mark.asyncio
async def test_start_turn_empty_prompt_no_user_message(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """start_turn с пустым prompt НЕ добавляет пустой user message."""
    captured_messages: list[list[LLMMessage]] = []

    class CapturingProvider(MockLLMProvider):
        async def create_completion(
            self,
            messages: list[LLMMessage],
            tools: list[dict[str, Any]] | None = None,
            **kwargs: Any,
        ) -> LLMResponse:
            captured_messages.append(list(messages))
            return await super().create_completion(messages, tools, **kwargs)

    agent = NaiveAgent(llm=CapturingProvider(response="ok"), tools=tool_registry)
    context = AgentContext(
        session_id="test",
        session=session_state,
        prompt=[],  # Пустой промпт
        conversation_history=[LLMMessage(role="user", content="history")],
        available_tools=tool_registry.list_tools(),
        config={},
    )
    await agent.start_turn(context)

    sent = captured_messages[0]
    # Не должен быть добавлен пустой user message
    assert len(sent) == 1
    assert sent[0].content == "history"


@pytest.mark.asyncio
async def test_start_turn_returns_tool_calls(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """start_turn возвращает tool_calls от LLM не выполняя их."""
    tool_call = LLMToolCall(
        id="call_1",
        name="calculator",
        arguments={"operation": "add", "a": 2, "b": 3},
    )
    agent = NaiveAgent(
        llm=MockLLMProvider(response="Считаю 2+3", tool_calls=[tool_call]),
        tools=tool_registry,
    )

    context = _make_context(session_state, tool_registry, "Сколько 2+3?")
    response = await agent.start_turn(context)

    # Агент делегирует tool calls в LLMLoopStage, не выполняет сам
    assert response.stop_reason == "tool_use"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "calculator"


@pytest.mark.asyncio
async def test_start_turn_multiple_tool_calls(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """start_turn возвращает несколько tool_calls."""
    tool_calls = [
        LLMToolCall(id="c1", name="echo", arguments={"text": "Hello"}),
        LLMToolCall(id="c2", name="echo", arguments={"text": "World"}),
    ]
    agent = NaiveAgent(
        llm=MockLLMProvider(response="", tool_calls=tool_calls),
        tools=tool_registry,
    )

    context = _make_context(session_state, tool_registry, "Echo twice")
    response = await agent.start_turn(context)

    assert len(response.tool_calls) == 2


@pytest.mark.asyncio
async def test_start_turn_uses_available_tools_from_context(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """start_turn использует context.available_tools (не self._tools напрямую).

    Это гарантирует что capability filtering из AgentOrchestrator применяется.
    """
    captured_tool_names: list[list[str]] = []

    class CapturingProvider(MockLLMProvider):
        async def create_completion(
            self,
            messages: list[LLMMessage],
            tools: list[dict[str, Any]] | None = None,
            **kwargs: Any,
        ) -> LLMResponse:
            if tools:
                captured_tool_names.append([t["function"]["name"] for t in tools])
            return await super().create_completion(messages, tools, **kwargs)

    # В context.available_tools — только calculator, не echo
    only_calculator = [t for t in tool_registry.list_tools() if t.name == "calculator"]

    agent = NaiveAgent(llm=CapturingProvider(response="ok"), tools=tool_registry)
    context = AgentContext(
        session_id="test",
        session=session_state,
        prompt=[{"type": "text", "text": "test"}],
        conversation_history=[],
        available_tools=only_calculator,  # Фильтрованный список
        config={},
    )
    await agent.start_turn(context)

    assert captured_tool_names == [["calculator"]]


# ============================================================================
# Тесты continue_turn — ключевой контракт
# ============================================================================


@pytest.mark.asyncio
async def test_continue_turn_does_not_add_user_message(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """continue_turn НЕ добавляет user message — история идёт в LLM как есть.

    Это главное отличие от start_turn.
    Последовательность messages: [..., assistant(tool_calls), tool(result)]
    LLM получает ИМЕННО эту последовательность без добавлений.
    """
    captured_messages: list[list[LLMMessage]] = []

    class CapturingProvider(MockLLMProvider):
        async def create_completion(
            self,
            messages: list[LLMMessage],
            tools: list[dict[str, Any]] | None = None,
            **kwargs: Any,
        ) -> LLMResponse:
            captured_messages.append(list(messages))
            return await super().create_completion(messages, tools, **kwargs)

    # История: user → assistant(tool_calls) → tool(result)
    history = [
        LLMMessage(role="user", content="Прочти файл"),
        LLMMessage(
            role="assistant",
            content="",
            tool_calls=[LLMToolCall(id="tc1", name="fs/read", arguments={"path": "a.txt"})],
        ),
        LLMMessage(role="tool", content="Содержимое файла", tool_call_id="tc1"),
    ]

    agent = NaiveAgent(llm=CapturingProvider(response="Вот файл"), tools=tool_registry)
    context = _make_continuation(session_state, tool_registry, history)
    await agent.continue_turn(context)

    assert len(captured_messages) == 1
    sent = captured_messages[0]
    # LLM должен получить ровно ту историю которую мы передали — без добавлений
    assert len(sent) == 3
    assert sent[0].role == "user"
    assert sent[1].role == "assistant"
    assert sent[2].role == "tool"
    # Нет лишнего user("") в конце!
    assert not any(m.role == "user" and m.content == "" for m in sent)


@pytest.mark.asyncio
async def test_continue_turn_simple_text_response(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """continue_turn возвращает текстовый ответ после tool_results."""
    history = [
        LLMMessage(role="user", content="Анализируй"),
        LLMMessage(
            role="assistant",
            content="",
            tool_calls=[LLMToolCall(id="t1", name="echo", arguments={"text": "x"})],
        ),
        LLMMessage(role="tool", content="Echo: x", tool_call_id="t1"),
    ]

    agent = NaiveAgent(
        llm=MockLLMProvider(response="Анализ завершён"),
        tools=tool_registry,
    )
    context = _make_continuation(session_state, tool_registry, history)
    response = await agent.continue_turn(context)

    assert response.text == "Анализ завершён"
    assert response.tool_calls == []
    assert response.stop_reason == "end_turn"


@pytest.mark.asyncio
async def test_continue_turn_can_return_more_tool_calls(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """continue_turn может вернуть новые tool_calls (LLMLoopStage продолжит цикл)."""
    next_tool_call = LLMToolCall(id="t2", name="echo", arguments={"text": "next"})
    history = [
        LLMMessage(role="user", content="Сделай"),
        LLMMessage(
            role="assistant",
            content="",
            tool_calls=[LLMToolCall(id="t1", name="echo", arguments={"text": "first"})],
        ),
        LLMMessage(role="tool", content="Echo: first", tool_call_id="t1"),
    ]

    agent = NaiveAgent(
        llm=MockLLMProvider(response="", tool_calls=[next_tool_call]),
        tools=tool_registry,
    )
    context = _make_continuation(session_state, tool_registry, history)
    response = await agent.continue_turn(context)

    assert response.stop_reason == "tool_use"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "t2"


# ============================================================================
# Тесты отмены (cancel_prompt)
# ============================================================================


class _SlowLLMProvider(MockLLMProvider):
    """Провайдер с задержкой — для тестирования отмены."""

    async def create_completion(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        await asyncio.sleep(10)
        return await super().create_completion(messages, tools, **kwargs)


@pytest.mark.asyncio
async def test_cancel_prompt_no_active_task_is_silent(
    tool_registry: SimpleToolRegistry,
) -> None:
    """Отмена без активной задачи не вызывает ошибок."""
    agent = NaiveAgent(llm=MockLLMProvider(response="ok"), tools=tool_registry)
    await agent.cancel_prompt("non-existent")


@pytest.mark.asyncio
async def test_cancel_prompt_cancels_active_start_turn(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """cancel_prompt прерывает активный start_turn."""
    agent = NaiveAgent(llm=_SlowLLMProvider(response="ok"), tools=tool_registry)
    context = _make_context(session_state, tool_registry, "Test")

    task = asyncio.create_task(agent.start_turn(context))
    await asyncio.sleep(0.1)

    assert "test-session" in agent._active_tasks

    await agent.cancel_prompt("test-session")

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_cancel_prompt_cancels_active_continue_turn(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """cancel_prompt прерывает активный continue_turn."""
    agent = NaiveAgent(llm=_SlowLLMProvider(response="ok"), tools=tool_registry)
    history = [LLMMessage(role="tool", content="result", tool_call_id="t1")]
    context = _make_continuation(session_state, tool_registry, history)

    task = asyncio.create_task(agent.continue_turn(context))
    await asyncio.sleep(0.1)

    await agent.cancel_prompt("test-session")

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_active_task_cleared_after_completion(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """После завершения start_turn активная задача очищается."""
    agent = NaiveAgent(llm=MockLLMProvider(response="ok"), tools=tool_registry)
    context = _make_context(session_state, tool_registry, "Test")

    await agent.start_turn(context)

    assert "test-session" not in agent._active_tasks


@pytest.mark.asyncio
async def test_active_task_cleared_after_cancellation(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """После отмены активная задача очищается из _active_tasks."""
    agent = NaiveAgent(llm=_SlowLLMProvider(response="ok"), tools=tool_registry)
    context = _make_context(session_state, tool_registry, "Test")

    task = asyncio.create_task(agent.start_turn(context))
    await asyncio.sleep(0.1)
    await agent.cancel_prompt("test-session")

    with pytest.raises(asyncio.CancelledError):
        await task

    assert "test-session" not in agent._active_tasks


# ============================================================================
# Тесты end_session
# ============================================================================


@pytest.mark.asyncio
async def test_end_session_cancels_active_task(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """end_session отменяет активную задачу."""
    agent = NaiveAgent(llm=_SlowLLMProvider(response="ok"), tools=tool_registry)
    context = _make_context(session_state, tool_registry, "Test")

    task = asyncio.create_task(agent.start_turn(context))
    await asyncio.sleep(0.1)

    assert "test-session" in agent._active_tasks

    await agent.end_session("test-session")

    with pytest.raises(asyncio.CancelledError):
        await task


# ============================================================================
# Тесты initialize
# ============================================================================


@pytest.mark.asyncio
async def test_initialize_updates_llm_provider(
    tool_registry: SimpleToolRegistry,
) -> None:
    """initialize обновляет LLM провайдер."""
    old_llm = MockLLMProvider(response="old")
    agent = NaiveAgent(llm=old_llm, tools=tool_registry)

    new_llm = MockLLMProvider(response="new")
    new_tools = SimpleToolRegistry()
    await agent.initialize(new_llm, new_tools, {})

    assert agent.llm is new_llm


# ============================================================================
# Тесты _format_prompt (вспомогательная функция)
# ============================================================================


def test_format_prompt_single_block() -> None:
    """_format_prompt объединяет один текстовый блок."""
    assert _format_prompt([{"type": "text", "text": "Hello"}]) == "Hello"


def test_format_prompt_multiple_blocks() -> None:
    """_format_prompt объединяет несколько блоков без разделителей."""
    assert _format_prompt([
        {"type": "text", "text": "Hello "},
        {"type": "text", "text": "World"},
    ]) == "Hello World"


def test_format_prompt_skips_non_text_blocks() -> None:
    """_format_prompt пропускает не-текстовые блоки."""
    assert _format_prompt([
        {"type": "text", "text": "Text"},
        {"type": "image", "url": "http://example.com/img.png"},
    ]) == "Text"


def test_format_prompt_empty_list() -> None:
    """_format_prompt на пустом списке возвращает пустую строку."""
    assert _format_prompt([]) == ""


# ============================================================================
# Тесты _to_openai_tools_format (маппинг имён инструментов)
# ============================================================================


def test_to_openai_tools_format_maps_slash_to_underscore() -> None:
    """_to_openai_tools_format конвертирует ACP имена (с `/`) в LLM имена (с `_`)."""
    tools = [
        ToolDefinition(
            name="fs/read_text_file",
            description="Read a text file",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
            kind="fs",
        ),
        ToolDefinition(
            name="terminal/run_command",
            description="Run a terminal command",
            parameters={"type": "object", "properties": {"command": {"type": "string"}}},
            kind="terminal",
        ),
    ]

    result = _to_openai_tools_format(tools)

    assert len(result) == 2
    assert result[0]["function"]["name"] == "fs_read_text_file"
    assert result[1]["function"]["name"] == "terminal_run_command"


def test_to_openai_tools_format_preserves_description_and_parameters() -> None:
    """_to_openai_tools_format сохраняет description и parameters без изменений."""
    params = {"type": "object", "properties": {"path": {"type": "string"}}}
    tools = [
        ToolDefinition(
            name="fs/read",
            description="Read file content",
            parameters=params,
            kind="fs",
        ),
    ]

    result = _to_openai_tools_format(tools)

    assert result[0]["function"]["description"] == "Read file content"
    assert result[0]["function"]["parameters"] == params


def test_to_openai_tools_format_handles_names_without_slash() -> None:
    """_to_openai_tools_format корректно обрабатывает имена без `/`."""
    tools = [
        ToolDefinition(
            name="calculator",
            description="Math operations",
            parameters={"type": "object", "properties": {}},
            kind="math",
        ),
    ]

    result = _to_openai_tools_format(tools)

    # Имя без `/` остаётся без изменений
    assert result[0]["function"]["name"] == "calculator"


def test_to_openai_tools_format_empty_list() -> None:
    """_to_openai_tools_format на пустом списке возвращает пустой список."""
    assert _to_openai_tools_format([]) == []
