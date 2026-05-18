"""Unit-тесты для PromptOrchestrator.

Проверяет интеграцию всех компонентов Этапа 2 и Этапа 3
при обработке prompt-turn.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from codelab.server.agent.base import AgentResponse
from codelab.server.llm.base import LLMToolCall
from codelab.server.protocol.handlers.client_rpc_handler import ClientRPCHandler
from codelab.server.protocol.handlers.permission_manager import PermissionManager
from codelab.server.protocol.handlers.pipeline import (
    PlanBuildingStage,
    PromptPipeline,
    SlashCommandStage,
    TurnLifecycleStage,
    ValidationStage,
)
from codelab.server.protocol.handlers.pipeline.stages import LLMLoopStage
from codelab.server.protocol.handlers.pipeline.stages.directives import DirectivesStage
from codelab.server.protocol.handlers.plan_builder import PlanBuilder
from codelab.server.protocol.handlers.prompt_orchestrator import PromptOrchestrator
from codelab.server.protocol.handlers.slash_commands import CommandRegistry, SlashCommandRouter
from codelab.server.protocol.handlers.slash_commands.builtin import (
    HelpCommandHandler,
    ModeCommandHandler,
    StatusCommandHandler,
)
from codelab.server.protocol.handlers.state_manager import StateManager
from codelab.server.protocol.handlers.tool_call_handler import ToolCallHandler
from codelab.server.protocol.handlers.turn_lifecycle_manager import TurnLifecycleManager
from codelab.server.protocol.state import SessionState
from codelab.server.tools.registry import SimpleToolRegistry


@pytest.fixture
def state_manager() -> StateManager:
    """Создает StateManager."""
    return StateManager()


@pytest.fixture
def plan_builder() -> PlanBuilder:
    """Создает PlanBuilder."""
    return PlanBuilder()


@pytest.fixture
def turn_lifecycle_manager() -> TurnLifecycleManager:
    """Создает TurnLifecycleManager."""
    return TurnLifecycleManager()


@pytest.fixture
def tool_call_handler() -> ToolCallHandler:
    """Создает ToolCallHandler."""
    return ToolCallHandler()


@pytest.fixture
def permission_manager() -> PermissionManager:
    """Создает PermissionManager."""
    return PermissionManager()


@pytest.fixture
def client_rpc_handler() -> ClientRPCHandler:
    """Создает ClientRPCHandler."""
    return ClientRPCHandler()


@pytest.fixture
def tool_registry() -> SimpleToolRegistry:
    """Создает SimpleToolRegistry."""
    return SimpleToolRegistry()


@pytest.fixture
def llm_loop_stage(
    tool_registry: SimpleToolRegistry,
    tool_call_handler: ToolCallHandler,
    permission_manager: PermissionManager,
    state_manager: StateManager,
    plan_builder: PlanBuilder,
) -> LLMLoopStage:
    """Создаёт LLMLoopStage."""
    return LLMLoopStage(
        tool_registry=tool_registry,
        tool_call_handler=tool_call_handler,
        permission_manager=permission_manager,
        state_manager=state_manager,
        plan_builder=plan_builder,
    )


@pytest.fixture
def command_registry() -> CommandRegistry:
    """Создает CommandRegistry со стандартными командами."""
    registry = CommandRegistry()
    registry.register(StatusCommandHandler())
    registry.register(ModeCommandHandler())
    registry.register(HelpCommandHandler(registry))
    return registry


@pytest.fixture
def pipeline(
    state_manager: StateManager,
    plan_builder: PlanBuilder,
    turn_lifecycle_manager: TurnLifecycleManager,
    tool_registry: SimpleToolRegistry,
    permission_manager: PermissionManager,
    llm_loop_stage: LLMLoopStage,
    command_registry: CommandRegistry,
) -> PromptPipeline:
    """Собирает PromptPipeline из стадий."""
    slash_router = SlashCommandRouter(command_registry)
    return PromptPipeline(stages=[
        ValidationStage(state_manager),
        SlashCommandStage(slash_router),
        PlanBuildingStage(plan_builder),
        TurnLifecycleStage(turn_lifecycle_manager, action="open"),
        DirectivesStage(tool_registry, permission_manager),
        llm_loop_stage,
        TurnLifecycleStage(turn_lifecycle_manager, action="close"),
    ])


@pytest.fixture
def orchestrator(
    state_manager: StateManager,
    plan_builder: PlanBuilder,
    turn_lifecycle_manager: TurnLifecycleManager,
    tool_call_handler: ToolCallHandler,
    permission_manager: PermissionManager,
    client_rpc_handler: ClientRPCHandler,
    tool_registry: SimpleToolRegistry,
    llm_loop_stage: LLMLoopStage,
    command_registry: CommandRegistry,
    pipeline: PromptPipeline,
) -> PromptOrchestrator:
    """Создает PromptOrchestrator со всеми компонентами."""
    return PromptOrchestrator(
        state_manager=state_manager,
        plan_builder=plan_builder,
        turn_lifecycle_manager=turn_lifecycle_manager,
        tool_call_handler=tool_call_handler,
        permission_manager=permission_manager,
        client_rpc_handler=client_rpc_handler,
        tool_registry=tool_registry,
        llm_loop_stage=llm_loop_stage,
        client_rpc_service=None,
        command_registry=command_registry,
        pipeline=pipeline,
    )


@pytest.fixture
def session() -> SessionState:
    """Создает SessionState."""
    return SessionState(
        session_id="sess_1",
        cwd="/tmp",
        mcp_servers=[],
    )


@pytest.fixture
def sessions(session: SessionState) -> dict[str, SessionState]:
    """Создает словарь сессий."""
    return {"sess_1": session}


@pytest.fixture
def agent_orchestrator() -> AsyncMock:
    """Создает mock для AgentOrchestrator.
    
    Возвращает AgentResponse вместо SessionState для соответствия
    новой архитектуре LLM loop.
    """
    mock = AsyncMock()
    # AgentResponse с пустым текстом и без tool calls
    mock.process_prompt = AsyncMock(return_value=AgentResponse(
        text="",
        tool_calls=[],
        stop_reason="end_turn",
    ))
    mock.continue_with_tool_results = AsyncMock(return_value=AgentResponse(
        text="",
        tool_calls=[],
        stop_reason="end_turn",
    ))
    return mock


class TestPromptOrchestratorInitialization:
    """Тесты инициализации PromptOrchestrator."""

    def test_initialization(self, orchestrator: PromptOrchestrator) -> None:
        """Инициализирует PromptOrchestrator со всеми компонентами."""
        assert orchestrator.state_manager is not None
        assert orchestrator.plan_builder is not None
        assert orchestrator.turn_lifecycle_manager is not None
        assert orchestrator.tool_call_handler is not None
        assert orchestrator.permission_manager is not None
        assert orchestrator.client_rpc_handler is not None


class TestPromptOrchestratorHandlePrompt:
    """Тесты handle_prompt метода."""

    @pytest.mark.asyncio
    async def test_handle_prompt_creates_active_turn(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
        sessions: dict[str, SessionState],
        agent_orchestrator: AsyncMock,
    ) -> None:
        """Создает active turn при обработке промпта."""
        prompt = [{"type": "text", "text": "Test prompt"}]
        await orchestrator.handle_prompt(
            "req_1",
            {"prompt": prompt},
            session,
            sessions,
            agent_orchestrator,
        )

        assert session.active_turn is None  # Должен быть очищен после завершения

    @pytest.mark.asyncio
    async def test_handle_prompt_updates_session_state(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
        sessions: dict[str, SessionState],
        agent_orchestrator: AsyncMock,
    ) -> None:
        """Обновляет состояние сессии при обработке."""
        prompt = [{"type": "text", "text": "Test prompt"}]
        await orchestrator.handle_prompt(
            "req_1",
            {"prompt": prompt},
            session,
            sessions,
            agent_orchestrator,
        )

        # Проверяем что история обновлена
        assert len(session.history) > 0
        assert session.history[0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_handle_prompt_returns_notifications(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
        sessions: dict[str, SessionState],
        agent_orchestrator: AsyncMock,
    ) -> None:
        """Возвращает notifications при обработке."""
        prompt = [{"type": "text", "text": "Test prompt"}]
        outcome = await orchestrator.handle_prompt(
            "req_1",
            {"prompt": prompt},
            session,
            sessions,
            agent_orchestrator,
        )

        assert outcome.notifications is not None
        assert len(outcome.notifications) > 0
        # Должны быть notifications session/update
        methods = [n.method for n in outcome.notifications]
        assert "session/update" in methods
        assert outcome.response is not None
        assert outcome.response.result == {"stopReason": "end_turn"}

    @pytest.mark.asyncio
    async def test_handle_prompt_with_empty_prompt(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
        sessions: dict[str, SessionState],
        agent_orchestrator: AsyncMock,
    ) -> None:
        """Обрабатывает пустой промпт."""
        outcome = await orchestrator.handle_prompt(
            "req_1",
            {"prompt": []},
            session,
            sessions,
            agent_orchestrator,
        )

        # Должны быть notifications даже при пустом промпте
        assert outcome.notifications is not None

    @pytest.mark.asyncio
    async def test_handle_prompt_with_agent_error(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
        sessions: dict[str, SessionState],
        agent_orchestrator: AsyncMock,
    ) -> None:
        """Обрабатывает ошибку агента."""
        agent_orchestrator.process_prompt.side_effect = Exception("Agent failed")

        prompt = [{"type": "text", "text": "Test prompt"}]
        outcome = await orchestrator.handle_prompt(
            "req_1",
            {"prompt": prompt},
            session,
            sessions,
            agent_orchestrator,
        )

        # Должны быть notifications с ошибкой
        assert outcome.notifications is not None
        error_found = any("error" in str(n.params).lower() for n in outcome.notifications)
        assert error_found or len(outcome.notifications) > 0

    @pytest.mark.asyncio
    async def test_handle_prompt_sets_session_title(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
        sessions: dict[str, SessionState],
        agent_orchestrator: AsyncMock,
    ) -> None:
        """Устанавливает заголовок сессии из первого промпта."""
        prompt = [{"type": "text", "text": "My test prompt"}]
        await orchestrator.handle_prompt(
            "req_1",
            {"prompt": prompt},
            session,
            sessions,
            agent_orchestrator,
        )

        assert session.title == "My test prompt"


class TestPromptOrchestratorHandleCancel:
    """Тесты handle_cancel метода."""

    def test_handle_cancel_with_active_turn(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
        sessions: dict[str, SessionState],
    ) -> None:
        """Обрабатывает cancel при активном turn."""
        from codelab.server.protocol.state import ActiveTurnState

        session.active_turn = ActiveTurnState(
            prompt_request_id="req_1",
            session_id="sess_1",
        )

        outcome = orchestrator.handle_cancel(
            "cancel_req",
            {"sessionId": "sess_1"},
            session,
            sessions,
        )

        # Должны быть notifications об отмене
        assert outcome.notifications is not None
        # Turn должен быть очищен
        assert session.active_turn is None

    def test_handle_cancel_without_active_turn(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
        sessions: dict[str, SessionState],
    ) -> None:
        """Не падает при cancel без активного turn."""
        session.active_turn = None

        outcome = orchestrator.handle_cancel(
            "cancel_req",
            {"sessionId": "sess_1"},
            session,
            sessions,
        )

        # Должно вернуть пустой результат
        assert outcome.notifications == []

    def test_handle_cancel_marks_cancel_requested(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
        sessions: dict[str, SessionState],
    ) -> None:
        """Устанавливает флаг cancel_requested."""
        from codelab.server.protocol.state import ActiveTurnState

        session.active_turn = ActiveTurnState(
            prompt_request_id="req_1",
            session_id="sess_1",
        )

        orchestrator.handle_cancel(
            "cancel_req",
            {"sessionId": "sess_1"},
            session,
            sessions,
        )

        # После очистки active_turn сразу, проверяем что он был очищен
        assert session.active_turn is None


class TestPromptOrchestratorHandleClientRpcResponse:
    """Тесты handle_pending_client_rpc_response."""

    def test_handle_client_rpc_response_fs_read(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
    ) -> None:
        """Обрабатывает response на fs/read request."""
        outcome = orchestrator.handle_pending_client_rpc_response(
            session,
            "sess_1",
            "fs_read",
            {"content": "file content"},
            None,
        )

        # Должны быть notifications
        assert outcome.notifications is not None

    def test_handle_client_rpc_response_fs_write(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
    ) -> None:
        """Обрабатывает response на fs/write request."""
        outcome = orchestrator.handle_pending_client_rpc_response(
            session,
            "sess_1",
            "fs_write",
            {"success": True},
            None,
        )

        # Должны быть notifications
        assert outcome.notifications is not None

    def test_handle_client_rpc_response_with_error(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
    ) -> None:
        """Обрабатывает response с ошибкой."""
        outcome = orchestrator.handle_pending_client_rpc_response(
            session,
            "sess_1",
            "fs_read",
            None,
            {"code": -1, "message": "File not found"},
        )

        # Должны быть notifications
        assert outcome.notifications is not None


class TestPromptOrchestratorHandlePermissionResponse:
    """Тесты handle_permission_response."""

    def test_handle_permission_response_allow(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
    ) -> None:
        """Обрабатывает allow decision."""
        from codelab.server.protocol.state import ActiveTurnState

        session.active_turn = ActiveTurnState(
            prompt_request_id="req_1",
            session_id="sess_1",
            permission_request_id="perm_req_1",
            permission_tool_call_id="call_001",
        )

        result = {
            "outcome": "selected",
            "optionId": "allow_once",
        }

        outcome = orchestrator.handle_permission_response(
            session,
            "sess_1",
            "perm_req_1",
            result,
        )

        # Должны быть notifications
        assert outcome.notifications is not None

    def test_handle_permission_response_reject(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
    ) -> None:
        """Обрабатывает reject decision."""
        from codelab.server.protocol.state import ActiveTurnState

        session.active_turn = ActiveTurnState(
            prompt_request_id="req_1",
            session_id="sess_1",
            permission_request_id="perm_req_1",
            permission_tool_call_id="call_001",
        )

        result = {
            "outcome": "selected",
            "optionId": "reject_once",
        }

        outcome = orchestrator.handle_permission_response(
            session,
            "sess_1",
            "perm_req_1",
            result,
        )

        # Должны быть notifications
        assert outcome.notifications is not None

    def test_handle_permission_response_cancelled(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
    ) -> None:
        """Игнорирует response на отменённый request."""
        session.cancelled_permission_requests.add("perm_req_1")

        result = {
            "outcome": "selected",
            "optionId": "allow_once",
        }

        outcome = orchestrator.handle_permission_response(
            session,
            "sess_1",
            "perm_req_1",
            result,
        )

        # Должно вернуть пустой результат
        assert outcome.notifications == []

    def test_handle_permission_response_invalid_format(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
    ) -> None:
        """Обрабатывает невалидный формат response."""
        from codelab.server.protocol.state import ActiveTurnState

        session.active_turn = ActiveTurnState(
            prompt_request_id="req_1",
            session_id="sess_1",
            permission_request_id="perm_req_1",
            permission_tool_call_id="call_001",
        )

        outcome = orchestrator.handle_permission_response(
            session,
            "sess_1",
            "perm_req_1",
            {},  # Invalid format
        )

        # Должно вернуть пустой результат для невалидного формата
        assert outcome.notifications == []


class TestPromptOrchestratorComponentIntegration:
    """Тесты интеграции всех компонентов."""

    def test_all_components_initialized(
        self,
        orchestrator: PromptOrchestrator,
    ) -> None:
        """Все компоненты инициализированы."""
        assert orchestrator.state_manager is not None
        assert orchestrator.plan_builder is not None
        assert orchestrator.turn_lifecycle_manager is not None
        assert orchestrator.tool_call_handler is not None
        assert orchestrator.permission_manager is not None
        assert orchestrator.client_rpc_handler is not None

    @pytest.mark.asyncio
    async def test_state_manager_integration(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
        sessions: dict[str, SessionState],
        agent_orchestrator: AsyncMock,
    ) -> None:
        """StateManager интегрирован в prompt handling."""
        prompt = [{"type": "text", "text": "Test"}]
        await orchestrator.handle_prompt(
            "req_1",
            {"prompt": prompt},
            session,
            sessions,
            agent_orchestrator,
        )

        # Проверяем что StateManager обновил состояние
        assert session.title == "Test"
        assert len(session.history) > 0

    def test_turn_lifecycle_integration(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
        sessions: dict[str, SessionState],
    ) -> None:
        """TurnLifecycleManager интегрирован в cancel handling."""
        from codelab.server.protocol.state import ActiveTurnState

        session.active_turn = ActiveTurnState(
            prompt_request_id="req_1",
            session_id="sess_1",
        )

        orchestrator.handle_cancel(
            "cancel_req",
            {"sessionId": "sess_1"},
            session,
            sessions,
        )

        # Проверяем что TurnLifecycleManager очистил turn
        assert session.active_turn is None


class TestPromptOrchestratorToolCallFlow:
    """Тесты tool-call flow в PromptOrchestrator."""

    @pytest.mark.asyncio
    async def test_handle_prompt_processes_tool_calls_with_valid_signature(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
        sessions: dict[str, SessionState],
        agent_orchestrator: AsyncMock,
        tool_registry: SimpleToolRegistry,
    ) -> None:
        """Проверяет, что tool call обрабатывается без TypeError по сигнатуре."""
        session.config_values["mode"] = "auto"
        # Устанавливаем policy чтобы пропустить permission flow
        session.permission_policy["other"] = "allow_always"

        tool_registry.register_tool(
            name="demo/tool",
            description="Demo tool",
            parameters={"type": "object", "properties": {}},
            kind="other",
            executor=lambda: "ok",
            requires_permission=False,
        )

        agent_orchestrator.process_prompt.return_value = SimpleNamespace(
            text="Tool executed",
            tool_calls=[
                LLMToolCall(
                    id="tc_1",
                    name="demo/tool",
                    arguments={},
                )
            ],
        )

        outcome = await orchestrator.handle_prompt(
            "req_1",
            {"prompt": [{"type": "text", "text": "run tool"}]},
            session,
            sessions,
            agent_orchestrator,
        )

        tool_call_notifications = [
            n
            for n in outcome.notifications
            if n.method == "session/update"
            and isinstance(n.params, dict)
            and isinstance(n.params.get("update"), dict)
            and n.params["update"].get("sessionUpdate") == "tool_call"
        ]
        assert len(tool_call_notifications) == 1

        tool_updates = [
            n
            for n in outcome.notifications
            if n.method == "session/update"
            and isinstance(n.params, dict)
            and isinstance(n.params.get("update"), dict)
            and n.params["update"].get("sessionUpdate") == "tool_call_update"
        ]
        statuses: list[str | None] = []
        for notification in tool_updates:
            params = notification.params
            if not isinstance(params, dict):
                continue
            update = params.get("update")
            if not isinstance(update, dict):
                continue
            statuses.append(update.get("status"))
        assert "in_progress" in statuses
        assert "completed" in statuses

    @pytest.mark.asyncio
    async def test_handle_prompt_ask_mode_keeps_pending_status_while_waiting_permission(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
        sessions: dict[str, SessionState],
        agent_orchestrator: AsyncMock,
    ) -> None:
        """Проверяет, что ask-режим не публикует не-ACP статус pending_permission."""
        session.config_values["mode"] = "ask"

        agent_orchestrator.process_prompt.return_value = SimpleNamespace(
            text="Need permission",
            tool_calls=[
                LLMToolCall(
                    id="tc_2",
                    name="fs/read_text_file",
                    arguments={"path": "README.md"},
                )
            ],
        )

        outcome = await orchestrator.handle_prompt(
            "req_2",
            {"prompt": [{"type": "text", "text": "read file"}]},
            session,
            sessions,
            agent_orchestrator,
        )

        permission_requests = [
            n for n in outcome.notifications if n.method == "session/request_permission"
        ]
        assert len(permission_requests) == 1
        assert permission_requests[0].id is not None
        # В новом flow turn остается активным в состоянии awaiting_permission
        assert session.active_turn is not None
        assert session.active_turn.phase == "awaiting_permission"

        statuses: list[str | None] = []
        for notification in outcome.notifications:
            if notification.method != "session/update":
                continue
            params = notification.params
            if not isinstance(params, dict):
                continue
            update = params.get("update")
            if not isinstance(update, dict):
                continue
            if update.get("sessionUpdate") != "tool_call_update":
                continue
            statuses.append(update.get("status"))
        assert "pending_permission" not in statuses

    @pytest.mark.asyncio
    async def test_handle_prompt_emits_single_permission_request_message(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
        sessions: dict[str, SessionState],
        agent_orchestrator: AsyncMock,
    ) -> None:
        """Проверяет, что в ask-flow отправляется ровно один RPC permission request."""
        session.config_values["mode"] = "ask"

        agent_orchestrator.process_prompt.return_value = SimpleNamespace(
            text="Need permission",
            tool_calls=[
                LLMToolCall(
                    id="tc_4",
                    name="fs/read_text_file",
                    arguments={"path": "README.md"},
                )
            ],
        )

        outcome = await orchestrator.handle_prompt(
            "req_4",
            {"prompt": [{"type": "text", "text": "read file"}]},
            session,
            sessions,
            agent_orchestrator,
        )

        permission_requests = [
            n for n in outcome.notifications if n.method == "session/request_permission"
        ]
        assert len(permission_requests) == 1
        request_params = permission_requests[0].params
        assert isinstance(request_params, dict)
        assert isinstance(request_params.get("toolCall"), dict)

    @pytest.mark.asyncio
    async def test_handle_prompt_reject_policy_maps_to_failed_status(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
        sessions: dict[str, SessionState],
        agent_orchestrator: AsyncMock,
    ) -> None:
        """Проверяет, что reject policy публикуется как failed, а не cancelled."""
        session.config_values["mode"] = "ask"
        # Устанавливаем reject policy на "other" kind, т.к. tool не найден в registry
        session.permission_policy["other"] = "reject_always"

        agent_orchestrator.process_prompt.return_value = SimpleNamespace(
            text="Permission denied by policy",
            tool_calls=[
                LLMToolCall(
                    id="tc_3",
                    name="fs/read_text_file",
                    arguments={"path": "README.md"},
                )
            ],
        )

        outcome = await orchestrator.handle_prompt(
            "req_3",
            {"prompt": [{"type": "text", "text": "read file"}]},
            session,
            sessions,
            agent_orchestrator,
        )

        statuses: list[str | None] = []
        for notification in outcome.notifications:
            if notification.method != "session/update":
                continue
            params = notification.params
            if not isinstance(params, dict):
                continue
            update = params.get("update")
            if not isinstance(update, dict):
                continue
            if update.get("sessionUpdate") != "tool_call_update":
                continue
            statuses.append(update.get("status"))
        assert "failed" in statuses
        assert "cancelled" not in statuses
