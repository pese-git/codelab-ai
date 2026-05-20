"""Unit-тесты для NaiveAgent."""

from typing import Any

import pytest

from codelab.server.agent.base import AgentContext
from codelab.server.agent.naive import NaiveAgent
from codelab.server.llm.base import LLMMessage, LLMResponse, LLMToolCall
from codelab.server.llm.mock_provider import MockLLMProvider
from codelab.server.protocol.state import SessionState
from codelab.server.tools.base import ToolDefinition
from codelab.server.tools.registry import SimpleToolRegistry

# ============================================================================
# Фикстуры с тестовыми инструментами
# ============================================================================


def simple_calculator(operation: str, a: float, b: float) -> float:
    """Простой калькулятор для тестирования."""
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
    """Echo инструмент для тестирования."""
    return f"Echo: {text}"


def error_tool() -> None:
    """Инструмент, который всегда выбрасывает ошибку."""
    raise RuntimeError("Это тестовая ошибка")


@pytest.fixture
def tool_registry() -> SimpleToolRegistry:
    """Создать реестр с тестовыми инструментами."""
    registry = SimpleToolRegistry()

    # Регистрация калькулятора
    calc_tool = ToolDefinition(
        name="calculator",
        description="Выполняет базовые математические операции",
        parameters={
            "type": "object",
            "properties": {
                "operation": {"type": "string"},
                "a": {"type": "number"},
                "b": {"type": "number"},
            },
        },
        kind="math",
    )
    registry.register(calc_tool, simple_calculator)

    # Регистрация echo инструмента
    echo_def = ToolDefinition(
        name="echo",
        description="Возвращает переданный текст",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
        },
        kind="other",
    )
    registry.register(echo_def, echo_tool)

    # Регистрация error инструмента
    error_def = ToolDefinition(
        name="error_tool",
        description="Инструмент, который выбрасывает ошибку",
        parameters={"type": "object", "properties": {}},
        kind="other",
    )
    registry.register(error_def, error_tool)

    return registry


@pytest.fixture
def naive_agent(tool_registry: SimpleToolRegistry) -> NaiveAgent:
    """Создать NaiveAgent с mock LLM провайдером."""
    llm = MockLLMProvider(response="Test response")
    return NaiveAgent(llm=llm, tools=tool_registry, max_iterations=5)


@pytest.fixture
def session_state() -> SessionState:
    """Создать SessionState для тестов."""
    return SessionState(
        session_id="test-session",
        cwd="/tmp",
        mcp_servers=[],
    )


# ============================================================================
# Базовые тесты
# ============================================================================


@pytest.mark.asyncio
async def test_simple_response_without_tool_calls(
    naive_agent: NaiveAgent,
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """Тест простого ответа без tool calls."""
    context = AgentContext(
        session_id="test-session",
        session=session_state,
        prompt=[{"type": "text", "text": "Hello, agent!"}],
        conversation_history=[],
        available_tools=tool_registry.list_tools(),
        config={},
    )

    response = await naive_agent.process_prompt(context)

    assert response.text == "Test response"
    assert response.tool_calls == []
    assert response.stop_reason == "end_turn"


@pytest.mark.asyncio
async def test_single_tool_call_success(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """Тест делегирования tool call в PromptOrchestrator.
    
    После архитектурного изменения, агент НЕ выполняет tool calls сам.
    Он возвращает stop_reason="tool_use" с tool_calls для обработки в PromptOrchestrator.
    """
    tool_call = LLMToolCall(
        id="call_1",
        name="calculator",
        arguments={"operation": "add", "a": 2, "b": 3},
    )

    llm = MockLLMProvider(
        response="I need to calculate 2 + 3",
        tool_calls=[tool_call],
    )
    agent = NaiveAgent(llm=llm, tools=tool_registry)

    context = AgentContext(
        session_id="test-session",
        session=session_state,
        prompt=[{"type": "text", "text": "Calculate 2 + 3"}],
        conversation_history=[],
        available_tools=tool_registry.list_tools(),
        config={},
    )

    response = await agent.process_prompt(context)

    # Агент делегирует tool calls в PromptOrchestrator
    assert response.stop_reason == "tool_use"
    assert response.text == "I need to calculate 2 + 3"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "calculator"
    assert response.metadata["iterations"] == 1


@pytest.mark.asyncio
async def test_multiple_tool_calls_in_single_response(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """Тест нескольких tool calls в одном ответе."""
    tool_calls = [
        LLMToolCall(
            id="call_1",
            name="echo",
            arguments={"text": "Hello"},
        ),
        LLMToolCall(
            id="call_2",
            name="echo",
            arguments={"text": "World"},
        ),
    ]

    llm = MockLLMProvider(
        response="I'll echo both texts",
        tool_calls=tool_calls,
    )

    agent = NaiveAgent(llm=llm, tools=tool_registry)

    context = AgentContext(
        session_id="test-session",
        session=session_state,
        prompt=[{"type": "text", "text": "Echo hello and world"}],
        conversation_history=[],
        available_tools=tool_registry.list_tools(),
        config={},
    )

    response = await agent.process_prompt(context)

    # Агент должен обработать оба tool calls
    assert response is not None
    assert response.metadata["iterations"] >= 1


# ============================================================================
# Тесты с цепочками tool calls
# ============================================================================


@pytest.mark.asyncio
async def test_tool_call_chain(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """Тест делегирования tool calls в PromptOrchestrator.
    
    После архитектурного изменения, агент НЕ выполняет tool calls сам,
    поэтому не формирует цепочки. Он возвращает tool_calls для PromptOrchestrator.
    """
    tool_call = LLMToolCall(
        id="call_1",
        name="calculator",
        arguments={"operation": "add", "a": 5, "b": 3},
    )

    llm = MockLLMProvider(
        response="I'll calculate 5 + 3",
        tool_calls=[tool_call],
    )
    agent = NaiveAgent(llm=llm, tools=tool_registry)

    context = AgentContext(
        session_id="test-session",
        session=session_state,
        prompt=[{"type": "text", "text": "Calculate 5 + 3 and tell me the result"}],
        conversation_history=[],
        available_tools=tool_registry.list_tools(),
        config={},
    )

    response = await agent.process_prompt(context)

    # Агент делегирует tool calls в PromptOrchestrator
    assert response.stop_reason == "tool_use"
    assert response.text == "I'll calculate 5 + 3"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "calculator"
    assert response.metadata["iterations"] == 1


# ============================================================================
# Тесты обработки ошибок
# ============================================================================


@pytest.mark.asyncio
async def test_max_iterations_exceeded(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """Тест делегирования tool calls в PromptOrchestrator.
    
    После архитектурного изменения, агент возвращает tool calls на первой итерации.
    Контроль max_iterations теперь - ответственность PromptOrchestrator.
    """
    tool_call = LLMToolCall(
        id="call_1",
        name="echo",
        arguments={"text": "loop"},
    )

    llm = MockLLMProvider(
        response="Continuing...",
        tool_calls=[tool_call],
    )
    agent = NaiveAgent(llm=llm, tools=tool_registry, max_iterations=3)

    context = AgentContext(
        session_id="test-session",
        session=session_state,
        prompt=[{"type": "text", "text": "Loop forever"}],
        conversation_history=[],
        available_tools=tool_registry.list_tools(),
        config={},
    )

    response = await agent.process_prompt(context)

    # Агент делегирует tool calls в PromptOrchestrator на первой итерации
    assert response.stop_reason == "tool_use"
    assert len(response.tool_calls) == 1
    assert response.metadata["iterations"] == 1


@pytest.mark.asyncio
async def test_tool_not_found(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """Тест вызова несуществующего инструмента."""
    tool_call = LLMToolCall(
        id="call_1",
        name="nonexistent_tool",
        arguments={},
    )

    llm = MockLLMProvider(
        response="Using nonexistent tool",
        tool_calls=[tool_call],
    )

    agent = NaiveAgent(llm=llm, tools=tool_registry)

    context = AgentContext(
        session_id="test-session",
        session=session_state,
        prompt=[{"type": "text", "text": "Use nonexistent tool"}],
        conversation_history=[],
        available_tools=tool_registry.list_tools(),
        config={},
    )

    response = await agent.process_prompt(context)

    # Агент должен обработать ошибку и вернуть ответ
    assert response is not None


@pytest.mark.asyncio
async def test_tool_execution_error(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """Тест делегирования error_tool в PromptOrchestrator.
    
    После архитектурного изменения, агент не выполняет tool calls сам,
    поэтому не обрабатывает ошибки выполнения. Это ответственность PromptOrchestrator.
    """
    tool_call = LLMToolCall(
        id="call_1",
        name="error_tool",
        arguments={},
    )

    llm = MockLLMProvider(
        response="Calling error tool",
        tool_calls=[tool_call],
    )
    agent = NaiveAgent(llm=llm, tools=tool_registry)

    context = AgentContext(
        session_id="test-session",
        session=session_state,
        prompt=[{"type": "text", "text": "Call error tool"}],
        conversation_history=[],
        available_tools=tool_registry.list_tools(),
        config={},
    )

    response = await agent.process_prompt(context)

    # Агент делегирует tool calls в PromptOrchestrator
    assert response is not None
    assert response.stop_reason == "tool_use"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "error_tool"
    assert response.metadata["iterations"] == 1


# ============================================================================
# Тесты с историей и контекстом
# ============================================================================


@pytest.mark.asyncio
async def test_empty_prompt(
    naive_agent: NaiveAgent,
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """Тест с пустым промптом."""
    context = AgentContext(
        session_id="test-session",
        session=session_state,
        prompt=[],  # Пустой промпт
        conversation_history=[],
        available_tools=tool_registry.list_tools(),
        config={},
    )

    response = await naive_agent.process_prompt(context)

    assert response is not None
    assert response.text == "Test response"


@pytest.mark.asyncio
async def test_with_conversation_history(
    naive_agent: NaiveAgent,
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """Тест с историей предыдущих сообщений."""
    history = [
        LLMMessage(role="user", content="First message"),
        LLMMessage(role="assistant", content="First response"),
    ]

    context = AgentContext(
        session_id="test-session",
        session=session_state,
        prompt=[{"type": "text", "text": "Second message"}],
        conversation_history=history,
        available_tools=tool_registry.list_tools(),
        config={},
    )

    response = await naive_agent.process_prompt(context)

    assert response is not None
    assert response.text == "Test response"


# ============================================================================
# Тесты управления историей сессии
# ============================================================================


@pytest.mark.asyncio
async def test_add_to_history(
    naive_agent: NaiveAgent,
) -> None:
    """Тест добавления сообщений в историю."""
    session_id = "test-session"

    naive_agent.add_to_history(session_id, "user", "Hello")
    naive_agent.add_to_history(session_id, "assistant", "Hi there")

    history = naive_agent.get_session_history(session_id)

    assert len(history) == 2
    assert history[0].role == "user"
    assert history[0].content == "Hello"
    assert history[1].role == "assistant"
    assert history[1].content == "Hi there"


@pytest.mark.asyncio
async def test_end_session(
    naive_agent: NaiveAgent,
) -> None:
    """Тест завершения сессии и очистки истории."""
    session_id = "test-session"

    # Добавить сообщения
    naive_agent.add_to_history(session_id, "user", "Hello")
    assert len(naive_agent.get_session_history(session_id)) == 1

    # Завершить сессию
    await naive_agent.end_session(session_id)

    # История должна быть пустой
    assert len(naive_agent.get_session_history(session_id)) == 0


# ============================================================================
# Тесты инициализации
# ============================================================================


@pytest.mark.asyncio
async def test_initialize_agent(
    tool_registry: SimpleToolRegistry,
) -> None:
    """Тест инициализации агента."""
    llm = MockLLMProvider()
    agent = NaiveAgent(llm=llm, tools=tool_registry)

    new_llm = MockLLMProvider(response="New response")
    new_tools = SimpleToolRegistry()

    await agent.initialize(new_llm, new_tools, {})

    # Убедиться, что зависимости обновлены
    assert agent.llm is new_llm
    assert agent.tools is new_tools


# ============================================================================
# Тесты форматирования промпта
# ============================================================================


@pytest.mark.asyncio
async def test_format_prompt_with_multiple_blocks(
    naive_agent: NaiveAgent,
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """Тест форматирования промпта с несколькими блоками."""
    context = AgentContext(
        session_id="test-session",
        session=session_state,
        prompt=[
            {"type": "text", "text": "Hello "},
            {"type": "text", "text": "World"},
        ],
        conversation_history=[],
        available_tools=tool_registry.list_tools(),
        config={},
    )

    response = await naive_agent.process_prompt(context)

    assert response is not None
    # Проверить, что промпт был правильно объединен
    assert response.text == "Test response"


# ============================================================================
# Интеграционные тесты
# ============================================================================


@pytest.mark.asyncio
async def test_integration_with_mock_provider(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """Интеграционный тест с MockLLMProvider.
    
    После архитектурного изменения, агент делегирует tool calls в PromptOrchestrator.
    """
    tool_call = LLMToolCall(
        id="call_1",
        name="calculator",
        arguments={"operation": "multiply", "a": 7, "b": 6},
    )

    llm = MockLLMProvider(
        response="I need to calculate 7 * 6",
        tool_calls=[tool_call],
    )
    agent = NaiveAgent(llm=llm, tools=tool_registry)

    context = AgentContext(
        session_id="test-session",
        session=session_state,
        prompt=[{"type": "text", "text": "What is 7 * 6?"}],
        conversation_history=[],
        available_tools=tool_registry.list_tools(),
        config={},
    )

    response = await agent.process_prompt(context)

    # Агент делегирует tool calls в PromptOrchestrator
    assert response.text == "I need to calculate 7 * 6"
    assert response.stop_reason == "tool_use"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "calculator"
    assert response.metadata["iterations"] == 1


# ============================================================================
# Тесты отмены prompt (cancel_prompt)
# ============================================================================


class _SlowMockLLMProvider(MockLLMProvider):
    """Mock провайдер с задержкой для тестирования отмены."""

    async def create_completion(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        import asyncio
        await asyncio.sleep(10)  # Длинная задержка для возможности отмены
        return await super().create_completion(messages, tools, **kwargs)


@pytest.mark.asyncio
async def test_cancel_prompt_no_active_task(
    tool_registry: SimpleToolRegistry,
) -> None:
    """Отмена без активной задачи — не вызывает ошибок."""
    llm = MockLLMProvider(response="Hello")
    agent = NaiveAgent(llm=llm, tools=tool_registry)

    # Нет активной задачи — отмена должна пройти тихо
    await agent.cancel_prompt("non-existent-session")


@pytest.mark.asyncio
async def test_cancel_prompt_cancels_active_task(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """Отмена прерывает активную задачу process_prompt."""
    import asyncio

    llm = _SlowMockLLMProvider(response="Hello")
    agent = NaiveAgent(llm=llm, tools=tool_registry)

    context = AgentContext(
        session_id="test-session",
        session=session_state,
        prompt=[{"type": "text", "text": "Test"}],
        conversation_history=[],
        available_tools=tool_registry.list_tools(),
        config={},
    )

    # Запускаем process_prompt как задачу
    task = asyncio.create_task(agent.process_prompt(context))

    # Даём задаче начать выполнение и войти в LLM call
    await asyncio.sleep(0.1)

    # Убеждаемся что задача активна
    assert "test-session" in agent._active_tasks

    # Отменяем
    await agent.cancel_prompt("test-session")

    # Задача должна завершиться с CancelledError
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_cancel_prompt_clears_active_task_on_completion(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """После завершения process_prompt активная задача очищается."""
    llm = MockLLMProvider(response="Hello")
    agent = NaiveAgent(llm=llm, tools=tool_registry)

    context = AgentContext(
        session_id="test-session",
        session=session_state,
        prompt=[{"type": "text", "text": "Test"}],
        conversation_history=[],
        available_tools=tool_registry.list_tools(),
        config={},
    )

    response = await agent.process_prompt(context)
    assert response.text == "Hello"

    # После завершения нет активной задачи
    assert "test-session" not in agent._active_tasks


@pytest.mark.asyncio
async def test_end_session_cancels_active_task(
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """end_session отменяет активную задачу перед очисткой."""
    import asyncio

    llm = _SlowMockLLMProvider(response="Hello")
    agent = NaiveAgent(llm=llm, tools=tool_registry)

    context = AgentContext(
        session_id="test-session",
        session=session_state,
        prompt=[{"type": "text", "text": "Test"}],
        conversation_history=[],
        available_tools=tool_registry.list_tools(),
        config={},
    )

    task = asyncio.create_task(agent.process_prompt(context))
    await asyncio.sleep(0.1)

    # Убеждаемся что задача активна
    assert "test-session" in agent._active_tasks

    # end_session должен отменить задачу
    await agent.end_session("test-session")

    with pytest.raises(asyncio.CancelledError):
        await task

    # История очищена
    assert "test-session" not in agent._session_histories
