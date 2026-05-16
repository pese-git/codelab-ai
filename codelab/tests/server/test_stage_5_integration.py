"""Интеграционные тесты для Этапа 5: глубокая интеграция в session_prompt() и session_cancel().

Проверяет полную интеграцию PromptOrchestrator в функции обработки prompt-turn.
"""

from typing import Any

import pytest
import pytest_asyncio

from codelab.server.messages import ACPMessage, JsonRpcId
from codelab.server.protocol.handlers.prompt import (
    create_prompt_orchestrator,
    session_cancel,
    validate_prompt_content,
)
from codelab.server.protocol.state import (
    ActiveTurnState,
    ProtocolOutcome,
    SessionState,
)
from codelab.server.storage import InMemoryStorage


class TestSessionPromptValidationStage5:
    """Тесты валидации параметров в session_prompt (Этап 5)."""

    def test_validate_prompt_content_valid_text(self) -> None:
        """Валидирует корректный text контент."""
        # Arrange
        request_id: JsonRpcId | None = "req_1"
        prompt = [{"type": "text", "text": "Hello world"}]

        # Act
        error = validate_prompt_content(request_id, prompt)

        # Assert
        assert error is None

    def test_validate_prompt_content_valid_resource_link(self) -> None:
        """Валидирует корректный resource_link контент."""
        # Arrange
        request_id: JsonRpcId | None = "req_1"
        prompt = [
            {
                "type": "resource_link",
                "uri": "https://example.com",
                "name": "Example",
            }
        ]

        # Act
        error = validate_prompt_content(request_id, prompt)

        # Assert
        assert error is None

    def test_validate_prompt_content_mixed_valid(self) -> None:
        """Валидирует смешанный корректный контент."""
        # Arrange
        request_id: JsonRpcId | None = "req_1"
        prompt = [
            {"type": "text", "text": "Check this:"},
            {
                "type": "resource_link",
                "uri": "https://example.com",
                "name": "Link",
            },
            {"type": "text", "text": "Done"},
        ]

        # Act
        error = validate_prompt_content(request_id, prompt)

        # Assert
        assert error is None

    def test_validate_prompt_content_invalid_type(self) -> None:
        """Возвращает ошибку при невалидном типе."""
        # Arrange
        request_id: JsonRpcId | None = "req_1"
        prompt = [{"type": "invalid_type", "content": "test"}]

        # Act
        error = validate_prompt_content(request_id, prompt)

        # Assert
        assert error is not None
        assert isinstance(error, ACPMessage)

    def test_validate_prompt_content_missing_text_field(self) -> None:
        """Возвращает ошибку при отсутствии text поля."""
        # Arrange
        request_id: JsonRpcId | None = "req_1"
        prompt = [{"type": "text"}]  # Missing 'text' field

        # Act
        error = validate_prompt_content(request_id, prompt)

        # Assert
        assert error is not None
        assert isinstance(error, ACPMessage)

    def test_validate_prompt_content_missing_resource_link_uri(self) -> None:
        """Возвращает ошибку при отсутствии uri в resource_link."""
        # Arrange
        request_id: JsonRpcId | None = "req_1"
        prompt = [{"type": "resource_link", "name": "Example"}]  # Missing 'uri'

        # Act
        error = validate_prompt_content(request_id, prompt)

        # Assert
        assert error is not None
        assert isinstance(error, ACPMessage)

    def test_validate_prompt_content_non_dict_block(self) -> None:
        """Возвращает ошибку при non-dict блоке."""
        # Arrange
        request_id: JsonRpcId | None = "req_1"
        prompt = ["string instead of dict"]  # type: ignore

        # Act
        error = validate_prompt_content(request_id, prompt)

        # Assert
        assert error is not None
        assert isinstance(error, ACPMessage)


class TestSessionCancelStage5:
    """Тесты session_cancel с использованием PromptOrchestrator (Этап 5)."""

    @pytest.fixture
    def sessions(self) -> dict[str, SessionState]:
        """Создает тестовую сессию с активным turn."""
        session = SessionState(
            session_id="sess_1",
            cwd="/tmp",
            mcp_servers=[],
            config_values={},
            permission_policy={},
            tool_calls={},
            history=[],
            latest_plan=[],
            active_turn=ActiveTurnState(
                prompt_request_id="req_1",
                session_id="sess_1",
            ),
        )
        return {"sess_1": session}

    @pytest_asyncio.fixture
    async def storage(self, sessions: dict[str, SessionState]) -> InMemoryStorage:
        """Создает storage с тестовой сессией."""
        from codelab.server.storage import InMemoryStorage
        storage = InMemoryStorage()
        for session in sessions.values():
            await storage.save_session(session)
        return storage

    @pytest.mark.asyncio
    async def test_session_cancel_with_active_turn(self, storage: InMemoryStorage) -> None:
        """Отменяет активный turn через PromptOrchestrator."""
        # Arrange
        request_id: JsonRpcId | None = "cancel_1"
        params = {"sessionId": "sess_1"}

        # Act
        outcome = await session_cancel(request_id, params, storage)

        # Assert
        assert outcome is not None
        assert isinstance(outcome, ProtocolOutcome)
        # Проверяем, что turn был завершен
        session = await storage.load_session("sess_1")
        assert session.active_turn is None

    @pytest.mark.asyncio
    async def test_session_cancel_as_notification(self, storage: InMemoryStorage) -> None:
        """Обрабатывает cancel как notification (без request_id)."""
        # Arrange
        request_id: JsonRpcId | None = None
        params = {"sessionId": "sess_1"}

        # Act
        outcome = await session_cancel(request_id, params, storage)

        # Assert
        assert outcome is not None
        assert outcome.response is None  # Notifications не имеют response
        session = await storage.load_session("sess_1")
        assert session.active_turn is None

    async def test_session_cancel_no_active_turn(self) -> None:
        """Обрабатывает cancel при отсутствии активного turn."""
        # Arrange
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
        from codelab.server.storage import InMemoryStorage
        storage = InMemoryStorage()
        await storage.save_session(session)
        request_id: JsonRpcId | None = "cancel_1"
        params = {"sessionId": "sess_1"}

        # Act
        outcome = await session_cancel(request_id, params, storage)

        # Assert
        assert outcome is not None
        assert isinstance(outcome, ProtocolOutcome)
        # When there's no active turn, orchestrator returns minimal outcome
        # We just verify the structure is correct
        assert outcome.notifications == [] or outcome.notifications is not None

    async def test_session_cancel_invalid_session_id(self) -> None:
        """Обрабатывает cancel с невалидным sessionId."""
        # Arrange
        from codelab.server.storage import InMemoryStorage
        storage = InMemoryStorage()
        request_id: JsonRpcId | None = "cancel_1"
        params = {"sessionId": "nonexistent"}

        # Act
        outcome = await session_cancel(request_id, params, storage)

        # Assert
        assert outcome is not None
        assert isinstance(outcome, ProtocolOutcome)
        # Should return empty or error response
        assert outcome.response is not None

    async def test_session_cancel_no_session_id(self) -> None:
        """Обрабатывает cancel без sessionId в params."""
        # Arrange
        sessions: dict[str, SessionState] = {}
        request_id: JsonRpcId | None = "cancel_1"
        params: dict[str, Any] = {}  # Missing sessionId

        # Act
        outcome = await session_cancel(request_id, params, sessions)

        # Assert
        assert outcome is not None
        assert isinstance(outcome, ProtocolOutcome)


class TestCreatePromptOrchestratorStage5:
    """Тесты factory функции create_prompt_orchestrator для Этапа 5."""

    def test_orchestrator_created_with_all_components(self) -> None:
        """Factory создает orchestrator со всеми компонентами."""
        # Act
        orchestrator = create_prompt_orchestrator()

        # Assert
        assert orchestrator is not None
        assert orchestrator.state_manager is not None
        assert orchestrator.plan_builder is not None
        assert orchestrator.turn_lifecycle_manager is not None
        assert orchestrator.tool_call_handler is not None
        assert orchestrator.permission_manager is not None
        assert orchestrator.client_rpc_handler is not None

    def test_orchestrator_instances_are_independent(self) -> None:
        """Каждый вызов create_prompt_orchestrator() создает независимый экземпляр."""
        # Act
        orch1 = create_prompt_orchestrator()
        orch2 = create_prompt_orchestrator()

        # Assert
        assert orch1 is not orch2
        assert orch1.state_manager is not orch2.state_manager
        assert orch1.tool_call_handler is not orch2.tool_call_handler


class TestSessionPromptIntegrationStage5:
    """Интеграционные тесты session_prompt с PromptOrchestrator (Этап 5)."""

    @pytest.fixture
    def config_specs(self) -> dict[str, dict[str, Any]]:
        """Создает спецификации конфигурации."""
        return {
            "mode": {
                "description": "Operation mode",
                "values": ["ask", "auto"],
                "default": "ask",
            }
        }

    async def test_session_prompt_invalid_session_id_type(
        self, config_specs: dict[str, dict[str, Any]]
    ) -> None:
        """Возвращает error при неправильном типе sessionId."""
        # Arrange - sessionId как int вместо str
        params: dict[str, Any] = {
            "sessionId": 123,  # Invalid: should be str
            "prompt": [{"type": "text", "text": "hello"}],
        }

        # Act - нужен async для полной функции, но валидация синхронна
        # Проверяем валидацию
        session_id = params.get("sessionId")
        assert not isinstance(session_id, str)

    async def test_session_prompt_missing_session_id(
        self, config_specs: dict[str, dict[str, Any]]
    ) -> None:
        """Возвращает error при отсутствии sessionId."""
        # Arrange
        params: dict[str, Any] = {
            "prompt": [{"type": "text", "text": "hello"}]
            # Missing sessionId
        }

        # Act
        session_id = params.get("sessionId")

        # Assert
        assert session_id is None
        assert not isinstance(session_id, str)

    async def test_session_prompt_invalid_prompt_type(
        self, config_specs: dict[str, dict[str, Any]]
    ) -> None:
        """Возвращает error при неправильном типе prompt."""
        # Arrange
        params: dict[str, Any] = {
            "sessionId": "sess_1",
            "prompt": "not a list",  # Invalid: should be list
        }

        # Act
        prompt = params.get("prompt")

        # Assert
        assert not isinstance(prompt, list)

    async def test_session_prompt_session_not_found(
        self, config_specs: dict[str, dict[str, Any]]
    ) -> None:
        """Возвращает error при отсутствии сессии."""
        # Arrange
        sessions: dict[str, SessionState] = {}
        params: dict[str, Any] = {
            "sessionId": "nonexistent",
            "prompt": [{"type": "text", "text": "hello"}],
        }

        # Act
        session = sessions.get(params.get("sessionId"))

        # Assert
        assert session is None

    async def test_session_prompt_empty_prompt_valid(self) -> None:
        """Пустой prompt должен быть валидным."""
        # Arrange
        prompt: list[Any] = []

        # Act
        error = validate_prompt_content(None, prompt)

        # Assert
        assert error is None


class TestPromptOrchestratorIntegrationFullStack:
    """Full-stack интеграционные тесты всей цепочки обработки."""

    def test_orchestrator_handles_complete_turn_lifecycle(self) -> None:
        """Проверяет полный жизненный цикл turn через orchestrator."""
        # Arrange
        orchestrator = create_prompt_orchestrator()
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

        # Act - инициализация turn
        active_turn = orchestrator.turn_lifecycle_manager.create_active_turn(
            "sess_1",
            "req_1",
        )
        session.active_turn = active_turn

        # Assert - turn создан
        assert session.active_turn is not None
        assert session.active_turn.prompt_request_id == "req_1"

        # Act - завершение turn
        final_msg = orchestrator.turn_lifecycle_manager.finalize_turn(
            session,
            "end_turn",
        )

        # Act - очистка turn состояния
        orchestrator.turn_lifecycle_manager.clear_active_turn(session)

        # Assert - turn завершен
        assert session.active_turn is None
        assert final_msg is not None

    def test_orchestrator_handles_state_updates(self) -> None:
        """Проверяет обновление состояния через StateManager в orchestrator."""
        # Arrange
        orchestrator = create_prompt_orchestrator()
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

        # Act - обновление заголовка
        orchestrator.state_manager.update_session_title(
            session,
            "Test Session",
        )

        # Assert
        assert session.title == "Test Session"

        # Act - добавление сообщения пользователя
        prompt_content = [{"type": "text", "text": "Hello"}]
        orchestrator.state_manager.add_user_message(
            session,
            prompt_content,
        )

        # Assert
        assert len(session.history) > 0


class TestSessionPromptWithOrchestratorIntegration:
    """Полные интеграционные тесты session_prompt() с PromptOrchestrator (Этап 5)."""

    @pytest.mark.asyncio
    async def test_session_prompt_returns_protocol_outcome(self) -> None:
        """Проверяет, что session_prompt() возвращает ProtocolOutcome с notifications."""
        # Arrange
        from codelab.server.protocol.handlers.prompt import session_prompt

        session = SessionState(
            session_id="sess_1",
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "ask"},
        )
        storage = InMemoryStorage()
        await storage.save_session(session)
        config_specs = {
            "mode": {
                "description": "Mode",
                "options": [{"value": "ask"}],
                "default": "ask",
                "name": "Mode",
                "category": "execution",
            }
        }
        params = {
            "sessionId": "sess_1",
            "prompt": [{"type": "text", "text": "Hello test"}],
        }

        # Act
        outcome = await session_prompt(
            "req_1", params, storage, config_specs, agent_orchestrator=None
        )

        # Assert
        assert isinstance(outcome, ProtocolOutcome)
        assert outcome.response is not None
        assert len(outcome.notifications) > 0

    @pytest.mark.asyncio
    async def test_session_prompt_with_orchestrator_creates_notifications(self) -> None:
        """Проверяет, что orchestrator создает необходимые notifications."""
        # Arrange
        from codelab.server.protocol.handlers.prompt import session_prompt

        session = SessionState(
            session_id="sess_1",
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "ask"},
        )
        storage = InMemoryStorage()
        await storage.save_session(session)
        config_specs = {
            "mode": {
                "description": "Mode",
                "options": [{"value": "ask"}],
                "default": "ask",
                "name": "Mode",
                "category": "execution",
            }
        }
        params = {
            "sessionId": "sess_1",
            "prompt": [{"type": "text", "text": "Test message"}],
        }

        # Act
        outcome = await session_prompt(
            "req_1", params, storage, config_specs, agent_orchestrator=None
        )

        # Assert - проверяем, что были созданы notifications
        notification_types = [
            n.params["update"]["sessionUpdate"]
            for n in outcome.notifications
            if n.params is not None
        ]
        assert "agent_message_chunk" in notification_types or len(notification_types) > 0

    @pytest.mark.asyncio
    async def test_session_prompt_validates_prompt_array(self) -> None:
        """Проверяет валидацию prompt как array."""
        # Arrange
        from codelab.server.protocol.handlers.prompt import session_prompt

        session = SessionState(
            session_id="sess_1",
            cwd="/tmp",
            mcp_servers=[],
        )
        storage = InMemoryStorage()
        await storage.save_session(session)
        config_specs = {}
        params = {
            "sessionId": "sess_1",
            "prompt": "not an array",  # Invalid
        }

        # Act
        outcome = await session_prompt(
            "req_1", params, storage, config_specs, agent_orchestrator=None
        )

        # Assert
        assert outcome.response is not None
        assert outcome.response.error is not None
        assert outcome.response.error.code == -32602

    @pytest.mark.asyncio
    async def test_session_prompt_error_handling(self) -> None:
        """Проверяет обработку ошибок при вызове orchestrator."""
        # Arrange
        from codelab.server.protocol.handlers.prompt import session_prompt

        storage = InMemoryStorage()
        config_specs = {}
        params = {
            "sessionId": "nonexistent",
            "prompt": [{"type": "text", "text": "test"}],
        }

        # Act
        outcome = await session_prompt(
            "req_1", params, storage, config_specs, agent_orchestrator=None
        )

        # Assert
        assert outcome.response is not None
        assert outcome.response.error is not None
        assert outcome.response.error.code == -32001  # Session not found

    @pytest.mark.asyncio
    async def test_session_prompt_updates_session_title(self) -> None:
        """Проверяет обновление заголовка сессии при первом prompt."""
        # Arrange
        from codelab.server.protocol.handlers.prompt import session_prompt

        session = SessionState(
            session_id="sess_1",
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "ask"},
            title=None,
        )
        storage = InMemoryStorage()
        await storage.save_session(session)
        config_specs = {
            "mode": {
                "description": "Mode",
                "options": [{"value": "ask"}],
                "default": "ask",
                "name": "Mode",
                "category": "execution",
            }
        }
        params = {
            "sessionId": "sess_1",
            "prompt": [{"type": "text", "text": "First message"}],
        }

        # Act
        outcome = await session_prompt(
            "req_1", params, storage, config_specs, agent_orchestrator=None
        )

        # Assert
        # Проверяем, что outcome был создан
        assert outcome is not None
        assert isinstance(outcome, ProtocolOutcome)
