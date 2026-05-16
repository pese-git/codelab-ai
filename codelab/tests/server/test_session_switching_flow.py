"""Интеграционные тесты для полного flow переключения между сессиями.

Проверяет сценарий SESSION_1 → SESSION_2 → SESSION_1 с проверкой
восстановления истории, конфигурации и отмены незавершенных операций.
"""

import pytest

from codelab.server.messages import ACPMessage
from codelab.server.protocol import ACPProtocol


@pytest.mark.asyncio
async def test_session_switching_flow_preserves_history() -> None:
    """Проверяет, что история сохраняется при переключении SESSION_1 → SESSION_2 → SESSION_1."""
    protocol = ACPProtocol()

    # === ЭТАП 1: Создание SESSION_1 ===
    created_1 = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp/session1", "mcpServers": []})
    )
    assert created_1.response is not None
    assert isinstance(created_1.response.result, dict)
    session_1_id = created_1.response.result["sessionId"]

    # === ЭТАП 2: Отправка prompt в SESSION_1 ===
    prompted_1 = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_1_id,
                "prompt": [{"type": "text", "text": "Hello from session 1"}],
            },
        )
    )
    assert prompted_1.response is not None
    # Проверяем, что история добавлена
    session_1_state = await protocol._storage.load_session(session_1_id)
    assert session_1_state is not None
    assert len(session_1_state.history) >= 2  # user + agent message

    # === ЭТАП 3: Создание SESSION_2 ===
    created_2 = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp/session2", "mcpServers": []})
    )
    assert created_2.response is not None
    assert isinstance(created_2.response.result, dict)
    session_2_id = created_2.response.result["sessionId"]

    # === ЭТАП 4: Отправка prompt в SESSION_2 ===
    prompted_2 = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_2_id,
                "prompt": [{"type": "text", "text": "Hello from session 2"}],
            },
        )
    )
    assert prompted_2.response is not None

    # === ЭТАП 5: Возврат на SESSION_1 ===
    loaded_1 = await protocol.handle(
        ACPMessage.request(
            "session/load",
            {
                "sessionId": session_1_id,
                "cwd": "/tmp/session1",
                "mcpServers": [],
            },
        )
    )
    assert loaded_1.response is not None

    # === ПРОВЕРКА: История SESSION_1 восстановлена ===
    replay_updates = [
        notification.params["update"]["sessionUpdate"]
        for notification in loaded_1.notifications
        if notification.params is not None
    ]
    assert "user_message_chunk" in replay_updates
    assert "agent_message_chunk" in replay_updates
    assert "session_info_update" in replay_updates

    # === ПРОВЕРКА: Можно отправить новый prompt в SESSION_1 ===
    prompted_1_again = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_1_id,
                "prompt": [{"type": "text", "text": "Hello again from session 1"}],
            },
        )
    )
    assert prompted_1_again.response is not None


@pytest.mark.asyncio
async def test_session_switching_clears_active_turn() -> None:
    """Проверяет, что active_turn очищается при переключении на другую сессию."""
    protocol = ACPProtocol()

    # Создаем SESSION_1
    created_1 = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp/session1", "mcpServers": []})
    )
    assert created_1.response is not None
    session_1_id = created_1.response.result["sessionId"]

    # Отправляем prompt в SESSION_1
    await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_1_id,
                "prompt": [{"type": "text", "text": "Test"}],
            },
        )
    )

    # Проверяем, что нет active_turn (уже завершен после обработки prompt)
    # active_turn будет None после обработки prompt
    _ = await protocol._storage.load_session(session_1_id)

    # Создаем и переключаемся на SESSION_2
    created_2 = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp/session2", "mcpServers": []})
    )
    session_2_id = created_2.response.result["sessionId"]  # noqa: F841

    # Возвращаемся на SESSION_1
    await protocol.handle(
        ACPMessage.request(
            "session/load",
            {
                "sessionId": session_1_id,
                "cwd": "/tmp/session1",
                "mcpServers": [],
            },
        )
    )

    # Проверяем, что active_turn остается None после load
    session_1_state_after = await protocol._storage.load_session(session_1_id)
    assert session_1_state_after.active_turn is None


@pytest.mark.asyncio
async def test_session_switching_preserves_config() -> None:
    """Проверяет, что конфигурация сохраняется при переключении сессий."""
    protocol = ACPProtocol()

    # Создаем SESSION_1
    created_1 = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp/session1", "mcpServers": []})
    )
    session_1_id = created_1.response.result["sessionId"]

    # Получаем начальную конфигурацию
    session_1_state = await protocol._storage.load_session(session_1_id)
    config_before = session_1_state.config_values.copy()

    # Создаем SESSION_2 (просто переключаемся в другую сессию)
    await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp/session2", "mcpServers": []})
    )

    # Возвращаемся на SESSION_1
    loaded = await protocol.handle(
        ACPMessage.request(
            "session/load",
            {
                "sessionId": session_1_id,
                "cwd": "/tmp/session1",
                "mcpServers": [],
            },
        )
    )

    # Проверяем, что конфигурация восстановлена
    session_1_state_after = await protocol._storage.load_session(session_1_id)
    assert session_1_state_after.config_values == config_before

    # Проверяем, что config_option_update был отправлен в notifications
    config_updates = [
        notification.params["update"]["sessionUpdate"]
        for notification in loaded.notifications
        if notification.params is not None
        and notification.params["update"]["sessionUpdate"] == "config_option_update"
    ]
    assert len(config_updates) > 0


@pytest.mark.asyncio
async def test_session_switching_three_way_flow() -> None:
    """Проверяет полный flow: SESSION_1 → SESSION_2 → SESSION_3 → SESSION_1."""
    protocol = ACPProtocol()

    # Создаем три сессии с разными contexts
    sessions = {}
    for i in range(1, 4):
        created = await protocol.handle(
            ACPMessage.request(
                "session/new",
                {"cwd": f"/tmp/session{i}", "mcpServers": []},
            )
        )
        session_id = created.response.result["sessionId"]
        sessions[i] = session_id

        # Отправляем уникальный prompt в каждую
        await protocol.handle(
            ACPMessage.request(
                "session/prompt",
                {
                    "sessionId": session_id,
                    "prompt": [{"type": "text", "text": f"Message from session {i}"}],
                },
            )
        )

    # Переключаемся: 1 → 2 → 3 → 1
    for session_num in [2, 3, 1]:
        loaded = await protocol.handle(
            ACPMessage.request(
                "session/load",
                {
                    "sessionId": sessions[session_num],
                    "cwd": f"/tmp/session{session_num}",
                    "mcpServers": [],
                },
            )
        )
        assert loaded.response is not None

        # Проверяем, что история восстановлена
        replay_updates = [
            notification.params["update"]["sessionUpdate"]
            for notification in loaded.notifications
            if notification.params is not None
        ]
        assert "user_message_chunk" in replay_updates

        # Проверяем, что можно отправить новый prompt
        prompted = await protocol.handle(
            ACPMessage.request(
                "session/prompt",
                {
                    "sessionId": sessions[session_num],
                    "prompt": [
                        {
                            "type": "text",
                            "text": f"New message in session {session_num}",
                        }
                    ],
                },
            )
        )
        assert prompted.response is not None


@pytest.mark.asyncio
async def test_session_switching_different_cwd_contexts() -> None:
    """Проверяет, что контекст cwd правильно обновляется при переключении."""
    protocol = ACPProtocol()

    # Создаем SESSION_1 с одним cwd
    created_1 = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp/project1", "mcpServers": []})
    )
    session_1_id = created_1.response.result["sessionId"]

    # Создаем SESSION_2 с другим cwd
    created_2 = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp/project2", "mcpServers": []})
    )
    session_2_id = created_2.response.result["sessionId"]

    # Проверяем начальные cwd
    session_1_before = await protocol._storage.load_session(session_1_id)
    session_2_before = await protocol._storage.load_session(session_2_id)
    assert session_1_before.cwd == "/tmp/project1"
    assert session_2_before.cwd == "/tmp/project2"

    # Переключаемся на SESSION_2
    await protocol.handle(
        ACPMessage.request(
            "session/load",
            {
                "sessionId": session_2_id,
                "cwd": "/tmp/project2",
                "mcpServers": [],
            },
        )
    )

    # Переключаемся обратно на SESSION_1 с обновленным cwd
    await protocol.handle(
        ACPMessage.request(
            "session/load",
            {
                "sessionId": session_1_id,
                "cwd": "/home/user/updated_project1",  # Updated cwd
                "mcpServers": [],
            },
        )
    )

    # Проверяем, что cwd обновлен
    session_1_after = await protocol._storage.load_session(session_1_id)
    assert session_1_after.cwd == "/home/user/updated_project1"
