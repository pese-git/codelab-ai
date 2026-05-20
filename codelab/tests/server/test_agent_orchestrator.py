"""Unit-тесты для AgentOrchestrator."""

import pytest

from codelab.server.agent.orchestrator import AgentOrchestrator
from codelab.server.agent.state import OrchestratorConfig
from codelab.server.llm.base import LLMMessage, LLMToolCall
from codelab.server.llm.mock_provider import MockLLMProvider
from codelab.server.protocol.state import ClientRuntimeCapabilities, SessionState, ToolResult
from codelab.server.tools.base import ToolDefinition
from codelab.server.tools.registry import SimpleToolRegistry

# ============================================================================
# Вспомогательные инструменты и фикстуры
# ============================================================================


def simple_tool(text: str) -> str:
    return f"Processed: {text}"


def another_tool(number: int) -> str:
    return f"Result: {number * 2}"


@pytest.fixture
def tool_registry() -> SimpleToolRegistry:
    registry = SimpleToolRegistry()
    registry.register(
        ToolDefinition(
            name="simple_tool",
            description="Обрабатывает текст",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}},
            kind="text",
        ),
        simple_tool,
    )
    registry.register(
        ToolDefinition(
            name="another_tool",
            description="Обрабатывает числа",
            parameters={"type": "object", "properties": {"number": {"type": "integer"}}},
            kind="math",
        ),
        another_tool,
    )
    return registry


@pytest.fixture
def config() -> OrchestratorConfig:
    return OrchestratorConfig(
        enabled=True,
        agent_class="naive",
        llm_provider_class="mock",
        model="gpt-4",
        temperature=0.7,
        max_tokens=8192,
    )


@pytest.fixture
def llm_provider() -> MockLLMProvider:
    return MockLLMProvider(response="Test response")


@pytest.fixture
def orchestrator(
    config: OrchestratorConfig,
    llm_provider: MockLLMProvider,
    tool_registry: SimpleToolRegistry,
) -> AgentOrchestrator:
    return AgentOrchestrator(
        config=config,
        llm_provider=llm_provider,
        tool_registry=tool_registry,
    )


@pytest.fixture
def session_state() -> SessionState:
    return SessionState(
        session_id="test-session-1",
        cwd="/tmp",
        mcp_servers=[],
        title="Test Session",
        history=[],
        config_values={},
    )


# ============================================================================
# Тесты создания оркестратора
# ============================================================================


def test_orchestrator_creation(
    config: OrchestratorConfig,
    llm_provider: MockLLMProvider,
    tool_registry: SimpleToolRegistry,
) -> None:
    """Тест создания оркестратора с конфигурацией."""
    orc = AgentOrchestrator(
        config=config,
        llm_provider=llm_provider,
        tool_registry=tool_registry,
    )
    assert orc.config == config
    assert orc.agent is not None
    assert orc.llm_provider is not None
    assert orc.tool_registry is not None


def test_orchestrator_agent_type(orchestrator: AgentOrchestrator) -> None:
    """Тест типа агента в оркестраторе."""
    from codelab.server.agent.naive import NaiveAgent

    assert isinstance(orchestrator.agent, NaiveAgent)


# ============================================================================
# Тесты _build_history (конвертация SessionState.history → list[LLMMessage])
# ============================================================================


def test_build_history_empty(
    orchestrator: AgentOrchestrator,
    session_state: SessionState,
) -> None:
    """_build_history на пустой истории возвращает []."""
    messages = orchestrator._build_history(session_state)
    assert messages == []


def test_build_history_user_and_assistant(
    orchestrator: AgentOrchestrator,
    session_state: SessionState,
) -> None:
    """_build_history корректно конвертирует user + assistant сообщения."""
    session_state.history = [
        {"role": "user", "text": "Привет"},
        {"role": "assistant", "text": "Привет! Чем могу помочь?"},
    ]
    messages = orchestrator._build_history(session_state)

    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "Привет"
    assert messages[1].role == "assistant"
    assert messages[1].content == "Привет! Чем могу помочь?"


def test_build_history_with_tool_calls(
    orchestrator: AgentOrchestrator,
    session_state: SessionState,
) -> None:
    """_build_history сохраняет assistant+tool_calls и tool result."""
    session_state.history = [
        {"role": "user", "text": "Посчитай"},
        {
            "role": "assistant",
            "text": "",
            "tool_calls": [{"id": "tc1", "name": "calc", "arguments": {"a": 1}}],
        },
        {"role": "tool", "tool_call_id": "tc1", "content": "Result: 1"},
    ]
    messages = orchestrator._build_history(session_state)

    assert len(messages) == 3
    assert messages[1].role == "assistant"
    assert messages[1].tool_calls is not None
    assert messages[2].role == "tool"
    assert messages[2].tool_call_id == "tc1"


def test_build_history_user_content_as_blocks(
    orchestrator: AgentOrchestrator,
    session_state: SessionState,
) -> None:
    """_build_history корректно обрабатывает content в виде list[block] (user msg)."""
    session_state.history = [
        {
            "role": "user",
            "content": [{"type": "text", "text": "Блочный контент"}],
        }
    ]
    messages = orchestrator._build_history(session_state)

    assert len(messages) == 1
    assert messages[0].content == "Блочный контент"


# ============================================================================
# Тесты _filter_tools / _filter_tools_by_capabilities
# ============================================================================


def test_filter_tools_no_capabilities(
    orchestrator: AgentOrchestrator,
    session_state: SessionState,
) -> None:
    """Без capabilities — доступны только серверные инструменты (kind=think/plan)."""
    session_state.runtime_capabilities = None

    # В реестре нет think/plan инструментов → фильтр вернёт []
    filtered = orchestrator._filter_tools(session_state)
    assert all(t.kind in {"think", "plan"} for t in filtered)


def test_filter_tools_with_full_capabilities(
    orchestrator: AgentOrchestrator,
    session_state: SessionState,
) -> None:
    """С fs_read=True tools из реестра не проходят (kind не fs/terminal/think)."""
    session_state.runtime_capabilities = ClientRuntimeCapabilities(
        fs_read=True, fs_write=True, terminal=True
    )
    # simple_tool (kind=text) и another_tool (kind=math) не попадают в фильтр
    # потому что их name не начинается с fs/ или terminal/
    filtered = orchestrator._filter_tools(session_state)
    tool_names = [t.name for t in filtered]
    assert "simple_tool" not in tool_names
    assert "another_tool" not in tool_names


def test_filter_tools_server_side_always_included(
    orchestrator: AgentOrchestrator,
    session_state: SessionState,
) -> None:
    """Инструменты kind=think всегда включаются независимо от capabilities."""
    # Регистрируем think-инструмент в реестре orchestrator
    think_tool = ToolDefinition(
        name="update_plan",
        description="План",
        parameters={"type": "object", "properties": {}},
        kind="think",
        requires_permission=False,
    )
    orchestrator.tool_registry.register(think_tool, lambda: None)

    # Без capabilities
    session_state.runtime_capabilities = None
    filtered = orchestrator._filter_tools(session_state)
    assert any(t.name == "update_plan" for t in filtered)

    # С capabilities=False для всего
    session_state.runtime_capabilities = ClientRuntimeCapabilities(
        fs_read=False, fs_write=False, terminal=False
    )
    filtered2 = orchestrator._filter_tools(session_state)
    assert any(t.name == "update_plan" for t in filtered2)


def test_filter_tools_fs_read_only(
    orchestrator: AgentOrchestrator,
    session_state: SessionState,
    tool_registry: SimpleToolRegistry,
) -> None:
    """С fs_read=True доступен только fs/read_text_file."""
    # Регистрируем fs-инструменты
    tool_registry.register(
        ToolDefinition(
            name="fs/read_text_file",
            description="Читает файл",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
            kind="filesystem",
        ),
        lambda path: "content",
    )
    tool_registry.register(
        ToolDefinition(
            name="fs/write_text_file",
            description="Пишет файл",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
            kind="filesystem",
        ),
        lambda path, content: True,
    )

    session_state.runtime_capabilities = ClientRuntimeCapabilities(
        fs_read=True, fs_write=False, terminal=False
    )
    filtered = orchestrator._filter_tools(session_state)
    tool_names = [t.name for t in filtered]

    assert "fs/read_text_file" in tool_names
    assert "fs/write_text_file" not in tool_names


# ============================================================================
# Тесты _add_tool_result_to_history
# ============================================================================


def test_add_tool_result_success(
    orchestrator: AgentOrchestrator,
    session_state: SessionState,
) -> None:
    """_add_tool_result_to_history добавляет успешный результат в историю."""
    result = ToolResult(
        tool_call_id="tc1",
        tool_name="echo",
        success=True,
        output="Результат выполнения",
    )
    orchestrator._add_tool_result_to_history(session_state, result)

    assert len(session_state.history) == 1
    entry = session_state.history[0]
    assert entry["role"] == "tool"
    assert entry["tool_call_id"] == "tc1"
    assert entry["content"] == "Результат выполнения"


def test_add_tool_result_failure(
    orchestrator: AgentOrchestrator,
    session_state: SessionState,
) -> None:
    """_add_tool_result_to_history добавляет ошибку в историю при неудаче."""
    result = ToolResult(
        tool_call_id="tc1",
        tool_name="echo",
        success=False,
        error="Что-то пошло не так",
    )
    orchestrator._add_tool_result_to_history(session_state, result)

    entry = session_state.history[0]
    assert entry["content"] == "Что-то пошло не так"


# ============================================================================
# Тесты _convert_to_llm_messages (приватный, тестируем напрямую)
# ============================================================================


def test_convert_to_llm_messages_empty(orchestrator: AgentOrchestrator) -> None:
    """Пустая история → пустой список."""
    assert orchestrator._convert_to_llm_messages([]) == []


def test_convert_to_llm_messages_single(orchestrator: AgentOrchestrator) -> None:
    """Одна запись → один LLMMessage."""
    messages = orchestrator._convert_to_llm_messages(
        [{"role": "user", "text": "Hello"}]
    )
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert messages[0].content == "Hello"


def test_convert_to_llm_messages_mixed_roles(orchestrator: AgentOrchestrator) -> None:
    """Записи с разными ролями конвертируются корректно."""
    history = [
        {"role": "system", "text": "Ты помощник"},
        {"role": "user", "text": "Привет"},
        {"role": "assistant", "text": "Привет!"},
        {"role": "tool", "tool_call_id": "t1", "content": "result"},
    ]
    messages = orchestrator._convert_to_llm_messages(history)

    assert len(messages) == 4
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert messages[2].role == "assistant"
    assert messages[3].role == "tool"
    assert messages[3].tool_call_id == "t1"


def test_convert_to_llm_messages_skips_empty_content(orchestrator: AgentOrchestrator) -> None:
    """Записи без content пропускаются."""
    history = [
        {"role": "user"},             # нет ни text, ни content
        {"role": "assistant", "text": ""},  # пустая строка
    ]
    messages = orchestrator._convert_to_llm_messages(history)
    assert len(messages) == 0


def test_convert_to_llm_messages_invalid_role_becomes_user(
    orchestrator: AgentOrchestrator,
) -> None:
    """Неизвестная роль нормализуется до 'user'."""
    messages = orchestrator._convert_to_llm_messages(
        [{"role": "unknown_role", "text": "Some text"}]
    )
    assert len(messages) == 1
    assert messages[0].content == "Some text"


# ============================================================================
# Тесты _sanitize_orphaned_tool_calls
# ============================================================================


def test_sanitize_no_orphans(orchestrator: AgentOrchestrator) -> None:
    """Когда все tool_calls имеют ответы — история не меняется."""
    messages = [
        LLMMessage(
            role="assistant",
            content="",
            tool_calls=[LLMToolCall(id="tc1", name="f", arguments={})],
        ),
        LLMMessage(role="tool", content="ok", tool_call_id="tc1"),
    ]
    result = orchestrator._sanitize_orphaned_tool_calls(messages)
    assert len(result) == 2


def test_sanitize_adds_synthetic_error_for_orphan(orchestrator: AgentOrchestrator) -> None:
    """Для осиротевшего tool_call добавляется синтетический error-результат."""
    messages = [
        LLMMessage(
            role="assistant",
            content="",
            tool_calls=[
                LLMToolCall(id="tc1", name="f", arguments={}),
                LLMToolCall(id="tc2", name="g", arguments={}),  # осиротевший
            ],
        ),
        LLMMessage(role="tool", content="ok", tool_call_id="tc1"),
        # tc2 не имеет ответа
    ]
    result = orchestrator._sanitize_orphaned_tool_calls(messages)

    # Должен быть добавлен синтетический результат для tc2
    assert len(result) == 3
    orphan_synthetic = next(m for m in result if m.tool_call_id == "tc2")
    assert "did not complete" in orphan_synthetic.content


# ============================================================================
# Интеграционный тест process_prompt и continue_with_tool_results
# ============================================================================


@pytest.mark.asyncio
async def test_process_prompt_calls_start_turn(
    config: OrchestratorConfig,
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """process_prompt вызывает agent.start_turn и возвращает AgentResponse."""
    orchestrator = AgentOrchestrator(
        config=config,
        llm_provider=MockLLMProvider(response="Привет!"),
        tool_registry=tool_registry,
    )
    response = await orchestrator.process_prompt(session_state, "Привет")

    assert response.text == "Привет!"
    assert response.tool_calls == []


@pytest.mark.asyncio
async def test_continue_with_tool_results_adds_to_history(
    config: OrchestratorConfig,
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """continue_with_tool_results добавляет tool_results в историю сессии."""
    # Предварительно заполним историю как будто уже было prompt + tool_call
    session_state.history = [
        {"role": "user", "text": "Прочти файл"},
        {
            "role": "assistant",
            "text": "",
            "tool_calls": [{"id": "tc1", "name": "fs/read", "arguments": {}}],
        },
    ]

    orchestrator = AgentOrchestrator(
        config=config,
        llm_provider=MockLLMProvider(response="Файл прочитан"),
        tool_registry=tool_registry,
    )
    tool_results = [
        ToolResult(
            tool_call_id="tc1",
            tool_name="fs/read",
            success=True,
            output="Содержимое файла",
        )
    ]
    response = await orchestrator.continue_with_tool_results(session_state, tool_results)

    # tool_result должен быть добавлен в историю
    assert any(
        e.get("role") == "tool" and e.get("tool_call_id") == "tc1"
        for e in session_state.history
    )
    assert response.text == "Файл прочитан"


@pytest.mark.asyncio
async def test_continue_with_tool_results_no_user_message_in_history(
    config: OrchestratorConfig,
    tool_registry: SimpleToolRegistry,
    session_state: SessionState,
) -> None:
    """continue_with_tool_results НЕ добавляет пустой user message в историю.

    Регрессионный тест для бага: пустой user("") вызывал зависание LLM.
    """
    captured_histories: list[list] = []

    from codelab.server.agent.base import ContinuationContext
    from codelab.server.agent.naive import NaiveAgent

    class CapturingAgent(NaiveAgent):
        async def continue_turn(self, context: ContinuationContext) -> "AgentResponse":
            captured_histories.append(list(context.history))
            return await super().continue_turn(context)

    session_state.history = [
        {"role": "user", "text": "Прочти"},
        {
            "role": "assistant",
            "text": "",
            "tool_calls": [{"id": "tc1", "name": "f", "arguments": {}}],
        },
    ]

    orchestrator = AgentOrchestrator(
        config=config,
        llm_provider=MockLLMProvider(response="Готово"),
        tool_registry=tool_registry,
    )
    orchestrator.agent = CapturingAgent(
        llm=MockLLMProvider(response="Готово"),
        tools=tool_registry,
    )

    await orchestrator.continue_with_tool_results(session_state, [
        ToolResult(tool_call_id="tc1", tool_name="f", success=True, output="result")
    ])

    assert len(captured_histories) == 1
    history = captured_histories[0]
    # Последнее сообщение — tool result, не пустой user
    last = history[-1]
    assert last.role == "tool"
    # Нет ни одного пустого user message
    empty_user = [m for m in history if m.role == "user" and not m.content]
    assert empty_user == []


# Вспомогательный импорт для аннотации
from codelab.server.agent.base import AgentResponse  # noqa: E402, F401
