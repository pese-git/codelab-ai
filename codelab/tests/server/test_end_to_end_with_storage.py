"""End-to-end тест с проверкой сохранения в storage.

Проверяет что новые сессии сохраняют события в правильном формате.
"""

import json
from typing import Any

import pytest

from codelab.server.protocol.handlers.prompt import create_prompt_orchestrator
from codelab.server.protocol.handlers.session import session_load
from codelab.server.protocol.session_factory import SessionFactory


class TestEndToEndWithStorage:
    """End-to-end тесты с проверкой формата в storage."""

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

    def test_new_session_saves_correct_event_format(
        self,
        config_specs: dict[str, dict[str, Any]],
    ) -> None:
        """Новая сессия сохраняет события в правильном формате."""
        # Arrange
        session = SessionFactory.create_session(
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "auto"},
            available_commands=[],
            runtime_capabilities=None,
        )

        orchestrator = create_prompt_orchestrator()

        # Act - Добавляем сообщение и проверяем формат события
        user_prompt = [{"type": "text", "text": "Hello!"}]
        orchestrator.state_manager.add_user_message(session, user_prompt)

        for block in user_prompt:
            orchestrator.state_manager.add_event(
                session,
                {
                    "type": "session_update",
                    "update": {"sessionUpdate": "user_message_chunk", "content": block},
                },
            )

        # Assert - Проверяем формат события в memory
        assert len(session.events_history) == 1
        event = session.events_history[0]

        # Проверяем что используется новый формат "update" вместо "event"
        assert "update" in event, "Event должен иметь поле 'update'"
        assert "event" not in event, "Event НЕ должен иметь поле 'event'"

        update = event["update"]
        assert update["sessionUpdate"] == "user_message_chunk"
        assert update["content"]["text"] == "Hello!"

    def test_agent_message_event_format(
        self,
        config_specs: dict[str, dict[str, Any]],
    ) -> None:
        """Agent message событие имеет правильный ContentBlock формат."""
        # Arrange
        session = SessionFactory.create_session(
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "auto"},
            available_commands=[],
            runtime_capabilities=None,
        )

        orchestrator = create_prompt_orchestrator()

        # Act
        agent_text = "I can help you!"
        orchestrator.state_manager.add_event(
            session,
            {
                "type": "session_update",
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": agent_text},
                },
            },
        )

        # Assert - Проверяем структуру
        event = session.events_history[0]

        assert "update" in event
        update = event["update"]
        assert update["sessionUpdate"] == "agent_message_chunk"

        # Проверяем ContentBlock структуру
        content = update["content"]
        assert content["type"] == "text"
        assert content["text"] == agent_text

    def test_serialized_events_preserve_format(
        self,
        config_specs: dict[str, dict[str, Any]],
    ) -> None:
        """События сохраняют правильный формат при JSON сериализации."""
        # Arrange
        session = SessionFactory.create_session(
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "auto"},
            available_commands=[],
            runtime_capabilities=None,
        )

        orchestrator = create_prompt_orchestrator()

        # Act - Добавляем события
        user_prompt = [{"type": "text", "text": "Test message"}]
        orchestrator.state_manager.add_user_message(session, user_prompt)

        for block in user_prompt:
            orchestrator.state_manager.add_event(
                session,
                {
                    "type": "session_update",
                    "update": {"sessionUpdate": "user_message_chunk", "content": block},
                },
            )

        # Сериализуем как JSON (как делает JsonFileStorage)
        json_str = json.dumps({"events_history": session.events_history})

        # Десериализуем обратно
        deserialized = json.loads(json_str)

        # Assert - Проверяем что формат сохранен
        event = deserialized["events_history"][0]
        assert "update" in event
        assert event["update"]["sessionUpdate"] == "user_message_chunk"
        assert event["update"]["content"]["text"] == "Test message"

    @pytest.mark.asyncio
    async def test_session_load_works_with_new_format_events(
        self,
        config_specs: dict[str, dict[str, Any]],
    ) -> None:
        """session/load корректно воспроизводит события в новом формате."""
        # Arrange
        session = SessionFactory.create_session(
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "auto"},
            available_commands=[],
            runtime_capabilities=None,
        )

        from codelab.server.storage import InMemoryStorage
        storage = InMemoryStorage()
        await storage.save_session(session)

        orchestrator = create_prompt_orchestrator()

        # Act - Заполняем session с правильным форматом
        user_prompt = [{"type": "text", "text": "Question"}]
        orchestrator.state_manager.add_user_message(session, user_prompt)

        for block in user_prompt:
            orchestrator.state_manager.add_event(
                session,
                {
                    "type": "session_update",
                    "update": {"sessionUpdate": "user_message_chunk", "content": block},
                },
            )

        # Сохраняем обновлённую сессию
        await storage.save_session(session)

        # Act - Загружаем сессию
        outcome = await session_load(
            request_id="req_load",
            params={"sessionId": session.session_id, "cwd": "/tmp", "mcpServers": []},
            require_auth=False,
            authenticated=True,
            config_specs=config_specs,
            auth_methods=[],
            storage=storage,
        )

        # Assert - Проверяем что события воспроизведены правильно
        user_notifications = [
            n
            for n in outcome.notifications
            if (
                n.method == "session/update"
                and n.params.get("update", {}).get("sessionUpdate") == "user_message_chunk"
            )
        ]

        assert len(user_notifications) == 1
        assert user_notifications[0].params["update"]["content"]["text"] == "Question"
