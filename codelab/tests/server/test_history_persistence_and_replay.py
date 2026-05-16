"""Тесты для проверки персистентности истории и replay функциональности.

Проверяет:
1. Сохранение user_message_chunk в events_history
2. Сохранение agent_message_chunk в правильном формате
3. Replay из events_history в session/load
"""

from typing import Any

import pytest

from codelab.server.protocol.handlers.prompt import create_prompt_orchestrator
from codelab.server.protocol.handlers.session import session_load
from codelab.server.protocol.state import SessionState


class TestUserMessageChunkPersistence:
    """Тесты сохранения user_message_chunk в events_history."""

    @pytest.fixture
    def orchestrator(self):
        """Создает PromptOrchestrator для тестирования."""
        return create_prompt_orchestrator()

    @pytest.fixture
    def session(self) -> SessionState:
        """Создает пустую сессию."""
        return SessionState(
            session_id="sess_1",
            cwd="/tmp",
            mcp_servers=[],
            config_values={},
            permission_policy={},
            tool_calls={},
            history=[],
            events_history=[],
            active_turn=None,
        )

    def test_user_message_chunk_saved_in_events_history(
        self,
        orchestrator,
        session: SessionState,
    ) -> None:
        """Каждый блок user_message_chunk сохраняется в events_history."""
        # Arrange
        prompt = [
            {"type": "text", "text": "Hello, assistant!"},
            {"type": "text", "text": "How are you?"},
        ]

        # Act - добавляем user message
        orchestrator.state_manager.add_user_message(session, prompt)

        # Добавляем events как делает handle_prompt
        for block in prompt:
            orchestrator.state_manager.add_event(
                session,
                {
                    "type": "session_update",
                    "update": {"sessionUpdate": "user_message_chunk", "content": block},
                },
            )

        # Assert
        assert len(session.events_history) >= 2

        # Проверяем, что события сохранены в правильном формате
        user_message_events = [
            e
            for e in session.events_history
            if e.get("type") == "session_update"
            and e.get("update", {}).get("sessionUpdate") == "user_message_chunk"
        ]
        assert len(user_message_events) == 2

        # Проверяем содержимое
        assert user_message_events[0]["update"]["content"]["text"] == "Hello, assistant!"
        assert user_message_events[1]["update"]["content"]["text"] == "How are you?"


class TestAgentMessageChunkFormat:
    """Тесты формата agent_message_chunk в events_history."""

    @pytest.fixture
    def orchestrator(self):
        """Создает PromptOrchestrator для тестирования."""
        return create_prompt_orchestrator()

    @pytest.fixture
    def session(self) -> SessionState:
        """Создает пустую сессию."""
        return SessionState(
            session_id="sess_1",
            cwd="/tmp",
            mcp_servers=[],
            config_values={},
            permission_policy={},
            tool_calls={},
            history=[],
            events_history=[],
            active_turn=None,
        )

    def test_agent_message_chunk_correct_format(
        self,
        orchestrator,
        session: SessionState,
    ) -> None:
        """agent_message_chunk сохраняется в правильном формате с ContentBlock."""
        # Arrange
        agent_response = "I am doing great, thank you for asking!"

        # Act - добавляем agent message и event как делает handle_prompt
        orchestrator.state_manager.add_assistant_message(session, agent_response)
        orchestrator.state_manager.add_event(
            session,
            {
                "type": "session_update",
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": agent_response},
                },
            },
        )

        # Assert
        # Проверяем, что событие содержит правильную структуру
        assert len(session.events_history) > 0

        agent_event = session.events_history[-1]
        assert agent_event["type"] == "session_update"

        update = agent_event["update"]
        assert update["sessionUpdate"] == "agent_message_chunk"

        # Проверяем ContentBlock структуру
        content = update["content"]
        assert content["type"] == "text"
        assert content["text"] == agent_response

    def test_agent_message_chunk_has_timestamp(
        self,
        orchestrator,
        session: SessionState,
    ) -> None:
        """agent_message_chunk событие содержит временную метку."""
        # Arrange
        agent_response = "Test response"

        # Act
        orchestrator.state_manager.add_assistant_message(session, agent_response)
        orchestrator.state_manager.add_event(
            session,
            {
                "type": "session_update",
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": agent_response},
                },
            },
        )

        # Assert
        event = session.events_history[-1]
        assert "timestamp" in event
        assert isinstance(event["timestamp"], str)


class TestSessionLoadReplay:
    """Тесты replay из events_history в session/load."""

    @pytest.fixture
    def config_specs(self) -> dict[str, dict[str, Any]]:
        """Создает спецификацию конфигурации."""
        return {
            "mode": {
                "default": "auto",
                "description": "Mode",
                "name": "Mode",
                "category": "Agent",
                "options": ["auto", "manual"],
            }
        }

    @pytest.mark.asyncio
    async def test_session_load_replays_user_messages(
        self,
        config_specs: dict[str, dict[str, Any]],
    ) -> None:
        """session/load replays user_message_chunk события из events_history."""
        # Arrange
        session = SessionState(
            session_id="sess_1",
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "auto"},
            permission_policy={},
            tool_calls={},
            history=[],
            events_history=[
                {
                    "type": "session_update",
                    "update": {
                        "sessionUpdate": "user_message_chunk",
                        "content": {"type": "text", "text": "Hello"},
                    },
                    "timestamp": "2026-04-13T07:00:00Z",
                }
            ],
            active_turn=None,
        )

        from codelab.server.storage import InMemoryStorage
        storage = InMemoryStorage()
        await storage.save_session(session)

        # Act
        outcome = await session_load(
            request_id="req_1",
            params={"sessionId": "sess_1", "cwd": "/tmp", "mcpServers": []},
            require_auth=False,
            authenticated=True,
            config_specs=config_specs,
            auth_methods=[],
            storage=storage,
        )

        # Assert
        # Проверяем, что есть notifications
        assert outcome.notifications is not None

        # Ищем user_message_chunk notifications
        user_message_notifications = [
            n
            for n in outcome.notifications
            if (
                n.method == "session/update"
                and n.params.get("update", {}).get("sessionUpdate") == "user_message_chunk"
            )
        ]

        assert len(user_message_notifications) == 1
        assert user_message_notifications[0].params["update"]["content"]["text"] == "Hello"

    @pytest.mark.asyncio
    async def test_session_load_replays_agent_messages(
        self,
        config_specs: dict[str, dict[str, Any]],
    ) -> None:
        """session/load replays agent_message_chunk события из events_history."""
        # Arrange
        session = SessionState(
            session_id="sess_1",
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "auto"},
            permission_policy={},
            tool_calls={},
            history=[],
            events_history=[
                {
                    "type": "session_update",
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "I am ready to help!"},
                    },
                    "timestamp": "2026-04-13T07:00:00Z",
                }
            ],
            active_turn=None,
        )

        from codelab.server.storage import InMemoryStorage
        storage = InMemoryStorage()
        await storage.save_session(session)

        # Act
        outcome = await session_load(
            request_id="req_1",
            params={"sessionId": "sess_1", "cwd": "/tmp", "mcpServers": []},
            require_auth=False,
            authenticated=True,
            config_specs=config_specs,
            auth_methods=[],
            storage=storage,
        )

        # Assert
        agent_message_notifications = [
            n
            for n in outcome.notifications
            if (
                n.method == "session/update"
                and n.params.get("update", {}).get("sessionUpdate") == "agent_message_chunk"
            )
        ]

        assert len(agent_message_notifications) == 1
        agent_content_text = agent_message_notifications[0].params["update"]["content"]["text"]
        assert agent_content_text == "I am ready to help!"

    @pytest.mark.asyncio
    async def test_session_load_replays_full_conversation(
        self,
        config_specs: dict[str, dict[str, Any]],
    ) -> None:
        """session/load replays полную беседу из events_history."""
        # Arrange
        session = SessionState(
            session_id="sess_1",
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "auto"},
            permission_policy={},
            tool_calls={},
            history=[],
            events_history=[
                {
                    "type": "session_update",
                    "update": {
                        "sessionUpdate": "user_message_chunk",
                        "content": {"type": "text", "text": "What is 2+2?"},
                    },
                    "timestamp": "2026-04-13T07:00:00Z",
                },
                {
                    "type": "session_update",
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "2+2 equals 4"},
                    },
                    "timestamp": "2026-04-13T07:00:01Z",
                },
            ],
            active_turn=None,
        )

        from codelab.server.storage import InMemoryStorage
        storage = InMemoryStorage()
        await storage.save_session(session)

        # Act
        outcome = await session_load(
            request_id="req_1",
            params={"sessionId": "sess_1", "cwd": "/tmp", "mcpServers": []},
            require_auth=False,
            authenticated=True,
            config_specs=config_specs,
            auth_methods=[],
            storage=storage,
        )

        # Assert
        # Ищем session/update notifications в порядке
        update_notifications = [n for n in outcome.notifications if n.method == "session/update"]

        # Должны быть notifications для user_message и agent_message, плюс config и session_info
        assert len(update_notifications) >= 2

        # Проверяем первое сообщение (пользователя)
        user_notifs = [
            n
            for n in update_notifications
            if n.params.get("update", {}).get("sessionUpdate") == "user_message_chunk"
        ]
        assert len(user_notifs) == 1
        assert user_notifs[0].params["update"]["content"]["text"] == "What is 2+2?"

        # Проверяем второе сообщение (агента)
        agent_notifs = [
            n
            for n in update_notifications
            if n.params.get("update", {}).get("sessionUpdate") == "agent_message_chunk"
        ]
        assert len(agent_notifs) == 1
        assert agent_notifs[0].params["update"]["content"]["text"] == "2+2 equals 4"

    @pytest.mark.asyncio
    async def test_session_load_skips_non_session_update_events(
        self,
        config_specs: dict[str, dict[str, Any]],
    ) -> None:
        """session/load игнорирует события без type=session_update."""
        # Arrange
        session = SessionState(
            session_id="sess_1",
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "auto"},
            permission_policy={},
            tool_calls={},
            history=[],
            events_history=[
                {"type": "non_session_event", "timestamp": "2026-04-13T07:00:00Z"},
                {
                    "type": "session_update",
                    "update": {
                        "sessionUpdate": "user_message_chunk",
                        "content": {"type": "text", "text": "Hello"},
                    },
                    "timestamp": "2026-04-13T07:00:01Z",
                },
            ],
            active_turn=None,
        )

        from codelab.server.storage import InMemoryStorage
        storage = InMemoryStorage()
        await storage.save_session(session)

        # Act
        outcome = await session_load(
            request_id="req_1",
            params={"sessionId": "sess_1", "cwd": "/tmp", "mcpServers": []},
            require_auth=False,
            authenticated=True,
            config_specs=config_specs,
            auth_methods=[],
            storage=storage,
        )

        # Assert
        # События не типа session_update должны быть пропущены
        # Проверяем что есть только session/update notifications
        for notification in outcome.notifications:
            if notification.method == "session/update":
                update = notification.params.get("update", {})
                session_update = update.get("sessionUpdate")
                assert session_update is not None
