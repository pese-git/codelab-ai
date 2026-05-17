"""Тесты для Permission Flow интеграции с tool calls.

Проверяет полный цикл:
1. Запрос на выполнение tool в режиме "ask"
2. Отправка notification о необходимости разрешения
3. Ответ пользователя на permission request
4. Выполнение tool или отмену на основе решения
"""

from __future__ import annotations

import pytest

from codelab.server.messages import JsonRpcId
from codelab.server.protocol.handlers.client_rpc_handler import ClientRPCHandler
from codelab.server.protocol.handlers.permission_manager import PermissionManager
from codelab.server.protocol.handlers.pipeline.stages import LLMLoopStage
from codelab.server.protocol.handlers.plan_builder import PlanBuilder
from codelab.server.protocol.handlers.prompt_orchestrator import PromptOrchestrator
from codelab.server.protocol.handlers.state_manager import StateManager
from codelab.server.protocol.handlers.tool_call_handler import ToolCallHandler
from codelab.server.protocol.handlers.turn_lifecycle_manager import TurnLifecycleManager
from codelab.server.protocol.state import ActiveTurnState, SessionState, ToolCallState
from codelab.server.tools.registry import SimpleToolRegistry


class TestPermissionFlowBasics:
    """Базовые тесты для permission flow."""

    @pytest.fixture
    def permission_manager(self) -> PermissionManager:
        """Создает PermissionManager для тестов."""
        return PermissionManager()

    @pytest.fixture
    def session(self) -> SessionState:
        """Создает тестовую сессию."""
        return SessionState(
            session_id="test_session",
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "ask"},
        )

    def test_request_tool_permission_creates_notification(
        self,
        permission_manager: PermissionManager,
        session: SessionState,
    ) -> None:
        """Проверяет, что request_tool_permission создает correct notification."""
        # Создаём tool call state
        tool_call = ToolCallState(
            tool_call_id="call_001",
            title="Read File",
            kind="read",
            status="pending",
        )

        # Добавляем в сессию
        session.tool_calls["call_001"] = tool_call

        # Инициализируем active turn
        session.active_turn = ActiveTurnState(
            prompt_request_id="req_1",
            session_id="test_session",
        )

        # Запрашиваем разрешение
        permission_request_id = permission_manager.request_tool_permission(
            session,
            tool_call,
            "read",
            "test_session",
        )

        # Проверяем, что ID был создан
        assert permission_request_id is not None
        assert isinstance(permission_request_id, str)

        # Проверяем, что он сохранён в active_turn
        assert session.active_turn.permission_request_id == permission_request_id
        assert session.active_turn.permission_tool_call_id == "call_001"

    def test_should_request_permission_checks_policy(
        self,
        permission_manager: PermissionManager,
        session: SessionState,
    ) -> None:
        """Проверяет, что should_request_permission корректно проверяет policy."""
        # По умолчанию нет policy, должно вернуть True
        assert permission_manager.should_request_permission(session, "read") is True

        # Добавляем allow_always policy
        session.permission_policy["read"] = "allow_always"
        assert permission_manager.should_request_permission(session, "read") is False

        # Добавляем reject_always policy
        session.permission_policy["read"] = "reject_always"
        assert permission_manager.should_request_permission(session, "read") is False

        # Неизвестная policy - должно вернуть True
        session.permission_policy["read"] = "unknown"
        assert permission_manager.should_request_permission(session, "read") is True

    def test_get_remembered_permission_returns_decision(
        self,
        permission_manager: PermissionManager,
        session: SessionState,
    ) -> None:
        """Проверяет, что get_remembered_permission возвращает correct decision."""
        # По умолчанию вернуть 'ask'
        assert permission_manager.get_remembered_permission(session, "read") == "ask"

        # После allow_always вернуть 'allow'
        session.permission_policy["read"] = "allow_always"
        assert permission_manager.get_remembered_permission(session, "read") == "allow"

        # После reject_always вернуть 'reject'
        session.permission_policy["read"] = "reject_always"
        assert permission_manager.get_remembered_permission(session, "read") == "reject"

    def test_build_permission_request_creates_valid_message(
        self,
        permission_manager: PermissionManager,
        session: SessionState,
    ) -> None:
        """Проверяет, что build_permission_request создает valid ACP message."""
        msg = permission_manager.build_permission_request(
            session,
            "test_session",
            "call_001",
            "Read File",
            "read",
        )

        # Проверяем базовую структуру
        assert msg.method == "session/request_permission"
        assert msg.params is not None
        assert msg.params.get("sessionId") == "test_session"
        assert isinstance(msg.params.get("toolCall"), dict)
        assert msg.params["toolCall"].get("toolCallId") == "call_001"
        assert msg.params["toolCall"].get("title") == "Read File"
        assert msg.params["toolCall"].get("kind") == "read"

        # Проверяем наличие опций
        options = msg.params.get("options", [])
        assert len(options) == 4
        option_ids = {opt.get("optionId") for opt in options}
        assert option_ids == {"allow_once", "allow_always", "reject_once", "reject_always"}

    def test_extract_permission_option_id(
        self,
        permission_manager: PermissionManager,
    ) -> None:
        """Проверяет извлечение optionId из response."""
        # ACP format
        result = {"outcome": {"optionId": "allow_once"}}
        assert permission_manager.extract_permission_option_id(result) == "allow_once"

        # Legacy format
        result = {"optionId": "reject_always"}
        assert permission_manager.extract_permission_option_id(result) == "reject_always"

        # Invalid format
        assert permission_manager.extract_permission_option_id(None) is None
        assert permission_manager.extract_permission_option_id({}) is None

    def test_find_session_by_permission_request_id(
        self,
        permission_manager: PermissionManager,
        session: SessionState,
    ) -> None:
        """Проверяет поиск сессии по permission_request_id."""
        # Инициализируем active turn с permission request
        permission_id: JsonRpcId = "perm_001"
        session.active_turn = ActiveTurnState(
            prompt_request_id="req_1",
            session_id="test_session",
            permission_request_id=permission_id,
        )

        sessions = {"test_session": session}

        # Поиск существующего permission request
        found = permission_manager.find_session_by_permission_request_id(
            permission_id,
            sessions,
        )
        assert found is not None
        assert found.session_id == "test_session"

        # Поиск несуществующего permission request
        found = permission_manager.find_session_by_permission_request_id(
            "perm_999",
            sessions,
        )
        assert found is None


class TestPermissionFlowIntegration:
    """Интеграционные тесты для полного permission flow."""

    @pytest.fixture
    def orchestrator(self) -> PromptOrchestrator:
        """Создает PromptOrchestrator для интеграционных тестов."""
        state_manager = StateManager()
        plan_builder = PlanBuilder()
        turn_lifecycle_manager = TurnLifecycleManager()
        tool_call_handler = ToolCallHandler()
        permission_manager = PermissionManager()
        client_rpc_handler = ClientRPCHandler()
        tool_registry = SimpleToolRegistry()

        llm_loop_stage = LLMLoopStage(
            tool_registry=tool_registry,
            tool_call_handler=tool_call_handler,
            permission_manager=permission_manager,
            state_manager=state_manager,
            plan_builder=plan_builder,
        )

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
        )

    @pytest.fixture
    def session(self) -> SessionState:
        """Создает тестовую сессию в режиме ask."""
        return SessionState(
            session_id="test_session",
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "ask"},
        )

    def test_permission_remembered_allow_always(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
    ) -> None:
        """Проверяет, что сохраненное allow_always разрешение применяется."""
        # Устанавливаем policy
        session.permission_policy["read"] = "allow_always"

        # Проверяем, что разрешение применяется
        remembered = orchestrator.permission_manager.get_remembered_permission(session, "read")
        assert remembered == "allow"

    def test_permission_remembered_reject_always(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
    ) -> None:
        """Проверяет, что сохраненное reject_always разрешение применяется."""
        # Устанавливаем policy
        session.permission_policy["execute"] = "reject_always"

        # Проверяем, что отклонение применяется
        remembered = orchestrator.permission_manager.get_remembered_permission(session, "execute")
        assert remembered == "reject"

    def test_build_permission_acceptance_updates(
        self,
        orchestrator: PromptOrchestrator,
        session: SessionState,
    ) -> None:
        """Проверяет, что build_permission_acceptance_updates сохраняет policy."""
        # Добавляем tool call
        tool_call = ToolCallState(
            tool_call_id="call_001",
            title="Execute",
            kind="execute",
            status="pending",
        )
        session.tool_calls["call_001"] = tool_call

        # Обновляем с allow_always
        orchestrator.permission_manager.build_permission_acceptance_updates(
            session,
            "test_session",
            "call_001",
            "allow_always",
        )

        # Проверяем, что policy сохранена
        assert session.permission_policy.get("execute") == "allow_always"

        # Обновляем с reject_always
        orchestrator.permission_manager.build_permission_acceptance_updates(
            session,
            "test_session",
            "call_001",
            "reject_always",
        )

        # Проверяем, что policy обновлена
        assert session.permission_policy.get("execute") == "reject_always"

    def test_extract_permission_outcome(
        self,
        orchestrator: PromptOrchestrator,
    ) -> None:
        """Проверяет извлечение outcome из response."""
        # ACP format
        result = {"outcome": {"outcome": "selected"}}
        assert orchestrator.permission_manager.extract_permission_outcome(result) == "selected"

        # Legacy format
        result = {"outcome": "selected"}
        assert orchestrator.permission_manager.extract_permission_outcome(result) == "selected"

        # Invalid
        assert orchestrator.permission_manager.extract_permission_outcome(None) is None


class TestPermissionFlowModes:
    """Тесты для различных режимов работы permission flow."""

    @pytest.fixture
    def session(self) -> SessionState:
        """Создает тестовую сессию."""
        return SessionState(
            session_id="test_session",
            cwd="/tmp",
            mcp_servers=[],
            config_values={},
        )

    def test_ask_mode_requires_permission(self, session: SessionState) -> None:
        """Проверяет, что режим ask требует разрешение."""
        session.config_values["mode"] = "ask"

        permission_manager = PermissionManager()

        # Должно требовать разрешение по умолчанию
        assert permission_manager.should_request_permission(session, "read") is True

    def test_code_mode_doesnt_require_permission(self, session: SessionState) -> None:
        """Проверяет, что режим code не требует разрешение для allow_always."""
        session.config_values["mode"] = "code"

        # Устанавливаем allow_always для режима code
        session.permission_policy["read"] = "allow_always"

        permission_manager = PermissionManager()

        # Не должно требовать разрешение
        assert permission_manager.should_request_permission(session, "read") is False


class TestPermissionFlowOptionKinds:
    """Тесты для различных типов опций разрешения."""

    @pytest.fixture
    def permission_manager(self) -> PermissionManager:
        """Создает PermissionManager для тестов."""
        return PermissionManager()

    def test_resolve_permission_option_kind_allow_once(
        self,
        permission_manager: PermissionManager,
    ) -> None:
        """Проверяет resolve allow_once опции."""
        options = permission_manager.build_permission_options()

        kind = permission_manager.resolve_permission_option_kind("allow_once", options)
        assert kind == "allow_once"

    def test_resolve_permission_option_kind_reject_always(
        self,
        permission_manager: PermissionManager,
    ) -> None:
        """Проверяет resolve reject_always опции."""
        options = permission_manager.build_permission_options()

        kind = permission_manager.resolve_permission_option_kind("reject_always", options)
        assert kind == "reject_always"

    def test_resolve_permission_option_kind_invalid(
        self,
        permission_manager: PermissionManager,
    ) -> None:
        """Проверяет resolve invalid опции."""
        options = permission_manager.build_permission_options()

        kind = permission_manager.resolve_permission_option_kind("invalid_option", options)
        assert kind is None
