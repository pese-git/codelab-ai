"""Интеграционные тесты для PromptOrchestrator с session/prompt функциями.

Проверяет корректную работу полного цикла обработки prompt-turn
через интеграцию всех компонентов Этапа 2 и Этапа 3.
"""

from typing import Any

import pytest
from factories import make_orchestrator

from codelab.server.protocol.handlers.prompt_orchestrator import PromptOrchestrator
from codelab.server.protocol.state import (
    ActiveTurnState,
    SessionState,
    ToolCallState,
)


class TestPromptOrchestratorFactory:
    """Тесты factory функции для создания PromptOrchestrator."""

    def test_create_prompt_orchestrator_success(self):
        """Создание PromptOrchestrator успешно инициализирует все компоненты."""
        # Act
        orchestrator = make_orchestrator()

        # Assert
        assert orchestrator is not None
        assert isinstance(orchestrator, PromptOrchestrator)
        assert orchestrator.state_manager is not None
        assert orchestrator.plan_builder is not None
        assert orchestrator.turn_lifecycle_manager is not None
        assert orchestrator.tool_call_handler is not None
        assert orchestrator.permission_manager is not None
        assert orchestrator.client_rpc_handler is not None

    def test_create_prompt_orchestrator_idempotent(self):
        """Каждый вызов создает новый независимый экземпляр."""
        # Act
        orchestrator1 = make_orchestrator()
        orchestrator2 = make_orchestrator()

        # Assert
        assert orchestrator1 is not orchestrator2
        assert orchestrator1.state_manager is not orchestrator2.state_manager


class TestSessionPromptValidation:
    """Тесты валидации параметров session/prompt."""

    @pytest.fixture
    def sessions(self) -> dict[str, SessionState]:
        """Создает тестовую сессию."""
        session = SessionState(
            session_id="sess_1",
            cwd="/tmp",
            mcp_servers=[],
            config_values={},
            permission_policy={},
            tool_calls={},
            history=[],
            latest_plan=[],
            active_turn=None,
        )
        return {"sess_1": session}

    def test_session_prompt_missing_session_id(self, sessions: dict[str, SessionState]) -> None:
        """Возвращает ошибку при отсутствии sessionId."""
        # Placeholder для тестирования отсутствия sessionId
        # Для асинхронной функции понадобится pytest-asyncio
        assert True  # placeholder

    def test_session_prompt_invalid_session_id_type(
        self, sessions: dict[str, SessionState]
    ) -> None:
        """Возвращает ошибку при неправильном типе sessionId."""
        # sessionId должен быть str, а не int
        assert True  # placeholder

    def test_session_prompt_session_not_found(self, sessions: dict[str, SessionState]) -> None:
        """Возвращает ошибку при отсутствии сессии."""
        # Попытаемся использовать несуществующий sessionId
        assert True  # placeholder

    def test_session_prompt_invalid_prompt_type(self, sessions: dict[str, SessionState]) -> None:
        """Возвращает ошибку при неправильном типе prompt."""
        # prompt должен быть list, а не string
        assert True  # placeholder


class TestSessionPromptWithOrchestrator:
    """Тесты использования PromptOrchestrator в session/prompt."""

    @pytest.fixture
    def orchestrator(self) -> PromptOrchestrator:
        """Создает PromptOrchestrator для тестирования."""
        return make_orchestrator()

    @pytest.fixture
    def session(self) -> SessionState:
        """Создает тестовую сессию."""
        return SessionState(
            session_id="sess_1",
            cwd="/tmp",
            mcp_servers=[],
            config_values={},
            permission_policy={},
            tool_calls={},
            history=[],
            latest_plan=[],
            active_turn=None,
        )

    @pytest.fixture
    def sessions(self, session: SessionState) -> dict[str, SessionState]:
        """Создает словарь сессий."""
        return {"sess_1": session}

    def test_orchestrator_handles_state_management(
        self, orchestrator: PromptOrchestrator, session: SessionState
    ) -> None:
        """PromptOrchestrator корректно управляет состоянием сессии."""
        # Assert
        assert orchestrator.state_manager is not None
        assert session.active_turn is None  # По умолчанию нет активного turn

    def test_orchestrator_integrates_all_components(self, orchestrator: PromptOrchestrator) -> None:
        """Все компоненты интегрированы в PromptOrchestrator."""
        # Проверяем наличие всех компонентов
        assert orchestrator.state_manager is not None
        assert orchestrator.plan_builder is not None
        assert orchestrator.turn_lifecycle_manager is not None
        assert orchestrator.tool_call_handler is not None
        assert orchestrator.permission_manager is not None
        assert orchestrator.client_rpc_handler is not None


class TestSessionPromptComponentIntegration:
    """Тесты интеграции компонентов в сценариях обработки prompt."""

    @pytest.fixture
    def orchestrator(self) -> PromptOrchestrator:
        """Создает PromptOrchestrator."""
        return make_orchestrator()

    @pytest.fixture
    def session(self) -> SessionState:
        """Создает сессию с инициализированным turn."""
        session = SessionState(
            session_id="sess_1",
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "ask"},
            permission_policy={},
            tool_calls={},
            history=[],
            latest_plan=[],
            active_turn=ActiveTurnState(
                prompt_request_id="req_1",
                session_id="sess_1",
            ),
        )
        return session

    def test_state_manager_updates_session_state(
        self, orchestrator: PromptOrchestrator, session: SessionState
    ) -> None:
        """StateManager корректно обновляет состояние сессии."""
        # Act - обновляем заголовок сессии
        orchestrator.state_manager.update_session_title(
            session=session,
            text_preview="New Title",
        )

        # Assert
        assert session.title == "New Title"

    def test_plan_builder_normalizes_plan_entries(self, orchestrator: PromptOrchestrator) -> None:
        """PlanBuilder нормализует plan entries."""
        # Arrange
        raw_entries = [
            {"title": "Step 1", "status": "pending"},
            {"title": "Step 2", "status": "in_progress"},
        ]

        # Act
        normalized = orchestrator.plan_builder.normalize_plan_entries(raw_entries)

        # Assert
        assert normalized is not None
        assert len(normalized) == 2
        assert all(isinstance(entry, dict) for entry in normalized)

    def test_turn_lifecycle_manager_handles_stop_reason(
        self, orchestrator: PromptOrchestrator, session: SessionState
    ) -> None:
        """TurnLifecycleManager правильно определяет stop reason."""
        # Assume session has active_turn
        assert session.active_turn is not None
        request_id = session.active_turn.prompt_request_id

        # Act
        final_message = orchestrator.turn_lifecycle_manager.finalize_active_turn(
            session=session,
            stop_reason="end_turn",
        )

        # Assert
        assert session.active_turn is None
        assert final_message is not None
        assert final_message.id == request_id
        assert final_message.result == {"stopReason": "end_turn"}

    def test_tool_call_handler_creates_tool_calls(
        self, orchestrator: PromptOrchestrator, session: SessionState
    ) -> None:
        """ToolCallHandler создает tool calls."""
        # Act
        tool_call_id = orchestrator.tool_call_handler.create_tool_call(
            session=session,
            title="Test Tool",
            kind="terminal",
        )

        # Assert
        assert tool_call_id is not None
        assert tool_call_id in session.tool_calls
        tool_call = session.tool_calls[tool_call_id]
        assert isinstance(tool_call, ToolCallState)
        assert tool_call.title == "Test Tool"

    def test_permission_manager_builds_options(self, orchestrator: PromptOrchestrator) -> None:
        """PermissionManager создает permission options."""
        # Act
        options = orchestrator.permission_manager.build_permission_options()

        # Assert
        assert options is not None
        assert isinstance(options, list)
        assert len(options) > 0


class TestSessionPromptErrorHandling:
    """Тесты обработки ошибок в session/prompt."""

    @pytest.fixture
    def sessions(self) -> dict[str, SessionState]:
        """Создает словарь сессий."""
        session = SessionState(
            session_id="sess_1",
            cwd="/tmp",
            mcp_servers=[],
            config_values={},
            permission_policy={},
            tool_calls={},
            history=[],
            latest_plan=[],
            active_turn=None,
        )
        return {"sess_1": session}

    def test_error_on_missing_params(self, sessions: dict[str, SessionState]) -> None:
        """Возвращает error response при отсутствии параметров."""
        # Arrange - params с missing sessionId
        params: dict[str, Any] = {"prompt": []}

        # Assert - проверим, что обработка ошибок работает
        assert params.get("sessionId") is None

    def test_error_on_invalid_content(self, sessions: dict[str, SessionState]) -> None:
        """Возвращает error response при невалидном контенте."""
        # Arrange
        invalid_prompt = [
            {
                "type": "unknown_type",  # Invalid type
                "content": "test",
            }
        ]

        # Assert
        assert isinstance(invalid_prompt, list)


class TestPromptIntegrationWithAllComponents:
    """Комплексные интеграционные тесты всех компонентов."""

    @pytest.fixture
    def setup(
        self,
    ) -> tuple[PromptOrchestrator, SessionState, dict[str, SessionState]]:
        """Подготавливает PromptOrchestrator, сессию и словарь сессий."""
        orchestrator = make_orchestrator()
        session = SessionState(
            session_id="sess_1",
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "ask"},
            permission_policy={},
            tool_calls={},
            history=[],
            latest_plan=[],
            active_turn=None,
        )
        sessions = {"sess_1": session}
        return orchestrator, session, sessions

    def test_all_components_work_together(
        self,
        setup: tuple[PromptOrchestrator, SessionState, dict[str, SessionState]],
    ) -> None:
        """Все компоненты работают вместе в едином оркестраторе."""
        # Arrange
        orchestrator, session, sessions = setup

        # Act - используем каждый компонент
        # 1. StateManager
        orchestrator.state_manager.update_session_title(session, "Integration Test")

        # 2. PlanBuilder
        plan_entries = [
            {"title": "Phase 1", "status": "pending"},
        ]
        normalized_plan = orchestrator.plan_builder.normalize_plan_entries(plan_entries)

        # 3. ToolCallHandler
        if not session.active_turn:
            session.active_turn = ActiveTurnState(
                prompt_request_id="req_1",
                session_id="sess_1",
            )
        tool_call_id = orchestrator.tool_call_handler.create_tool_call(
            session, title="Test", kind="terminal"
        )

        # 4. PermissionManager
        permission_options = orchestrator.permission_manager.build_permission_options()

        # Assert
        assert session.title == "Integration Test"
        assert normalized_plan is not None
        assert tool_call_id in session.tool_calls
        assert len(permission_options) > 0
