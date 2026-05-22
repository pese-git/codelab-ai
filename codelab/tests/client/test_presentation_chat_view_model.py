"""Тесты session-aware поведения ChatViewModel."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from codelab.client.infrastructure.events.bus import EventBus
from codelab.client.presentation.chat_view_model import ChatViewModel


@pytest.fixture
def mock_fs_executor():
    """Создает mock FileSystemExecutor для тестов."""
    executor = Mock()
    executor.read_text_file_sync = Mock(return_value="test content")
    executor.write_text_file_sync = Mock(return_value=True)
    return executor


@pytest.fixture
def mock_terminal_executor():
    """Создает mock TerminalExecutor для тестов."""
    executor = Mock()
    executor.execute = Mock(return_value={"exit_code": 0, "output": "test output", "success": True})
    return executor


@pytest.fixture
def chat_view_model(tmp_path, mock_fs_executor, mock_terminal_executor) -> ChatViewModel:
    """Создает ChatViewModel для тестов."""

    return ChatViewModel(
        coordinator=None,
        event_bus=EventBus(),
        logger=None,
        history_dir=tmp_path / "history",
        fs_executor=mock_fs_executor,
        terminal_executor=mock_terminal_executor,
    )


def test_chat_state_isolated_between_sessions(chat_view_model: ChatViewModel) -> None:
    """История сообщений хранится отдельно для каждой сессии."""

    chat_view_model.set_active_session("sess_1")
    chat_view_model.add_message("user", "hello from s1")

    chat_view_model.set_active_session("sess_2")
    assert chat_view_model.messages.value == []
    chat_view_model.add_message("user", "hello from s2")

    chat_view_model.set_active_session("sess_1")
    assert len(chat_view_model.messages.value) == 1
    assert chat_view_model.messages.value[0]["content"] == "hello from s1"

    chat_view_model.set_active_session("sess_2")
    assert len(chat_view_model.messages.value) == 1
    assert chat_view_model.messages.value[0]["content"] == "hello from s2"


def test_chat_resets_when_no_active_session(chat_view_model: ChatViewModel) -> None:
    """При отсутствии активной сессии отображается пустой чат."""

    chat_view_model.set_active_session("sess_1")
    chat_view_model.add_message("assistant", "saved message")

    chat_view_model.set_active_session(None)
    assert chat_view_model.messages.value == []

    chat_view_model.set_active_session("sess_1")
    assert len(chat_view_model.messages.value) == 1
    assert chat_view_model.messages.value[0]["content"] == "saved message"


def test_session_update_chunk_written_to_original_session(chat_view_model: ChatViewModel) -> None:
    """Chunk ответа сохраняется в сессию из params.sessionId, а не в активную."""

    chat_view_model.set_active_session("sess_1")
    chat_view_model.add_message("user", "question s1", session_id="sess_1")

    chat_view_model.set_active_session("sess_2")
    chat_view_model._handle_session_update(
        {
            "params": {
                "sessionId": "sess_1",
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"text": "answer s1"},
                },
            }
        }
    )

    # В активной сессии chunk не должен появиться.
    assert chat_view_model.streaming_text.value == ""

    # После возврата в исходную сессию chunk доступен.
    chat_view_model.set_active_session("sess_1")
    assert chat_view_model.streaming_text.value == "answer s1"


def test_system_ack_chunk_separated_from_assistant_text(chat_view_model: ChatViewModel) -> None:
    """Служебный ACK отображается как system, а не смешивается с ответом."""

    chat_view_model.set_active_session("sess_ack")
    chat_view_model._handle_session_update(
        {
            "params": {
                "sessionId": "sess_ack",
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"text": "Processing with agent: hello"},
                },
            }
        }
    )

    assert len(chat_view_model.messages.value) == 1
    assert chat_view_model.messages.value[0]["role"] == "system"
    assert chat_view_model.streaming_text.value == ""

    chat_view_model._handle_session_update(
        {
            "params": {
                "sessionId": "sess_ack",
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"text": "Hello from LLM"},
                },
            }
        }
    )

    assert chat_view_model.streaming_text.value == "Hello from LLM"


def test_restore_session_from_replay_rebuilds_messages(chat_view_model: ChatViewModel) -> None:
    """Replay updates из `session/load` восстанавливают историю сообщений."""

    chat_view_model.set_active_session("sess_replay")
    chat_view_model.restore_session_from_replay(
        "sess_replay",
        [
            {
                "params": {
                    "sessionId": "sess_replay",
                    "update": {
                        "sessionUpdate": "user_message_chunk",
                        "content": {"type": "text", "text": "hello"},
                    },
                }
            },
            {
                "params": {
                    "sessionId": "sess_replay",
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "world"},
                    },
                }
            },
        ],
    )

    assert chat_view_model.messages.value == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]


def test_user_message_chunk_added_to_history(chat_view_model: ChatViewModel) -> None:
    """user_message_chunk обрабатывается и добавляется в историю сообщений."""

    chat_view_model.set_active_session("sess_user_chunk")

    # Обработаем user_message_chunk
    chat_view_model._handle_session_update(
        {
            "params": {
                "sessionId": "sess_user_chunk",
                "update": {
                    "sessionUpdate": "user_message_chunk",
                    "content": {"text": "user question"},
                },
            }
        }
    )

    # Сообщение должно быть добавлено в историю
    assert len(chat_view_model.messages.value) == 1
    assert chat_view_model.messages.value[0]["role"] == "user"
    assert chat_view_model.messages.value[0]["content"] == "user question"


def test_user_message_chunk_persisted_to_storage(tmp_path) -> None:
    """user_message_chunk сохраняется в локальное хранилище."""

    history_dir = tmp_path / "history"
    chat_view_model = ChatViewModel(
        coordinator=None,
        event_bus=EventBus(),
        logger=None,
        history_dir=history_dir,
    )

    chat_view_model.set_active_session("sess_user_persist")
    chat_view_model._handle_session_update(
        {
            "params": {
                "sessionId": "sess_user_persist",
                "update": {
                    "sessionUpdate": "user_message_chunk",
                    "content": {"text": "save me"},
                },
            }
        }
    )

    # Создаем новый ViewModel и проверяем что сообщение загружено из storage
    second_vm = ChatViewModel(
        coordinator=None,
        event_bus=EventBus(),
        logger=None,
        history_dir=history_dir,
    )
    second_vm.set_active_session("sess_user_persist")

    assert len(second_vm.messages.value) == 1
    assert second_vm.messages.value[0]["role"] == "user"
    assert second_vm.messages.value[0]["content"] == "save me"


def test_chat_history_is_persisted_to_local_storage(tmp_path) -> None:
    """История сообщений сохраняется и восстанавливается из локального storage."""

    history_dir = tmp_path / "history"

    first_vm = ChatViewModel(
        coordinator=None,
        event_bus=EventBus(),
        logger=None,
        history_dir=history_dir,
    )
    first_vm.set_active_session("sess_local")
    first_vm.add_message("user", "persist me")

    second_vm = ChatViewModel(
        coordinator=None,
        event_bus=EventBus(),
        logger=None,
        history_dir=history_dir,
    )
    second_vm.set_active_session("sess_local")

    assert second_vm.messages.value == [{"role": "user", "content": "persist me"}]


def test_chat_history_uses_env_dir_when_history_dir_not_passed(tmp_path, monkeypatch) -> None:
    """При отсутствии history_dir используется путь из ACP_CLIENT_HISTORY_DIR."""

    env_history_dir = tmp_path / "history_from_env"
    monkeypatch.setenv("CODELAB_CLIENT_HISTORY_DIR", str(env_history_dir))

    vm = ChatViewModel(
        coordinator=None,
        event_bus=EventBus(),
        logger=None,
    )
    vm.add_message("user", "saved via env", session_id="sess_env")

    assert (env_history_dir / "sess_env.json").exists()


def test_chat_history_explicit_dir_has_priority_over_env(tmp_path, monkeypatch) -> None:
    """Явный history_dir имеет приоритет над ACP_CLIENT_HISTORY_DIR."""

    env_history_dir = tmp_path / "history_from_env"
    explicit_history_dir = tmp_path / "history_explicit"
    monkeypatch.setenv("CODELAB_CLIENT_HISTORY_DIR", str(env_history_dir))

    vm = ChatViewModel(
        coordinator=None,
        event_bus=EventBus(),
        logger=None,
        history_dir=explicit_history_dir,
    )
    vm.add_message("user", "saved via explicit", session_id="sess_explicit_priority")

    assert (explicit_history_dir / "sess_explicit_priority.json").exists()
    assert not (env_history_dir / "sess_explicit_priority.json").exists()


def test_chat_history_falls_back_to_default_dir_when_env_missing(tmp_path, monkeypatch) -> None:
    """Без history_dir и CODELAB_CLIENT_HISTORY_DIR используется ~/.codelab/data/history."""

    monkeypatch.delenv("CODELAB_CLIENT_HISTORY_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    vm = ChatViewModel(
        coordinator=None,
        event_bus=EventBus(),
        logger=None,
    )
    vm.add_message("user", "saved via default", session_id="sess_default")

    default_history_dir = tmp_path / ".codelab" / "data" / "history"
    assert (default_history_dir / "sess_default.json").exists()


def test_message_with_explicit_session_id_is_persisted(tmp_path) -> None:
    """Сообщение с explicit session_id сразу сохраняется в локальный storage."""

    history_dir = tmp_path / "history"

    first_vm = ChatViewModel(
        coordinator=None,
        event_bus=EventBus(),
        logger=None,
        history_dir=history_dir,
    )
    first_vm.set_active_session("sess_explicit")
    first_vm.add_message("user", "save immediately", session_id="sess_explicit")

    second_vm = ChatViewModel(
        coordinator=None,
        event_bus=EventBus(),
        logger=None,
        history_dir=history_dir,
    )
    second_vm.set_active_session("sess_explicit")

    assert second_vm.messages.value == [{"role": "user", "content": "save immediately"}]


def test_restore_session_persists_all_replay_updates(tmp_path) -> None:
    """В локальном кэше сохраняются все replay-события, а не только сообщения."""

    history_dir = tmp_path / "history"
    vm = ChatViewModel(
        coordinator=None,
        event_bus=EventBus(),
        logger=None,
        history_dir=history_dir,
    )
    vm.set_active_session("sess_events")

    replay_updates = [
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess_events",
                "update": {
                    "sessionUpdate": "user_message_chunk",
                    "content": {"type": "text", "text": "hello"},
                },
            },
        },
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess_events",
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolUseId": "tool_1",
                    "title": "Read file",
                },
            },
        },
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess_events",
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "world"},
                },
            },
        },
    ]

    vm.restore_session_from_replay("sess_events", replay_updates)

    cache_payload = json.loads((history_dir / "sess_events.json").read_text(encoding="utf-8"))
    cached_replay_updates = cache_payload.get("replay_updates")

    assert isinstance(cached_replay_updates, list)
    assert len(cached_replay_updates) == 3
    assert cached_replay_updates[1]["params"]["update"]["sessionUpdate"] == "tool_call"


def test_streaming_flag_resets_after_background_session_completion(
    chat_view_model: ChatViewModel,
) -> None:
    """Глобальный is_streaming сбрасывается после завершения неактивной сессии."""

    # Имитируем ситуацию, когда prompt-input уже отключен в UI.
    chat_view_model.is_streaming.value = True

    # Завершаем поток в неактивной для UI сессии.
    chat_view_model.set_active_session("sess_active")
    chat_view_model._set_streaming_state("sess_background", is_streaming=True, clear_text=False)
    chat_view_model._set_streaming_state("sess_background", is_streaming=False, clear_text=True)

    assert chat_view_model.is_streaming.value is False


# Тесты для callbacks файловой системы и терминала
@pytest.mark.asyncio
async def test_handle_fs_read_success(chat_view_model: ChatViewModel, mock_fs_executor) -> None:
    """Тест успешного чтения файла через callback."""
    chat_view_model.set_active_session("test-session")

    content = await chat_view_model._handle_fs_read("test.txt")

    assert content == "test content"
    mock_fs_executor.read_text_file_sync.assert_called_once_with("test.txt")


@pytest.mark.asyncio
async def test_handle_fs_read_no_active_session(
    chat_view_model: ChatViewModel,
    mock_fs_executor,
) -> None:
    """Тест чтения файла без активной сессии."""
    chat_view_model.set_active_session(None)

    content = await chat_view_model._handle_fs_read("test.txt")

    assert content == ""
    mock_fs_executor.read_text_file_sync.assert_not_called()


@pytest.mark.asyncio
async def test_handle_fs_read_error(chat_view_model: ChatViewModel, mock_fs_executor) -> None:
    """Тест обработки ошибки при чтении файла."""
    chat_view_model.set_active_session("test-session")
    mock_fs_executor.read_text_file_sync.side_effect = Exception("Read error")

    content = await chat_view_model._handle_fs_read("test.txt")

    assert content == ""


@pytest.mark.asyncio
async def test_handle_fs_write_success(chat_view_model: ChatViewModel, mock_fs_executor) -> None:
    """Тест успешной записи файла через callback."""
    chat_view_model.set_active_session("test-session")

    success = await chat_view_model._handle_fs_write("test.txt", "content")

    assert success is True
    mock_fs_executor.write_text_file_sync.assert_called_once_with("test.txt", "content")


@pytest.mark.asyncio
async def test_handle_fs_write_no_active_session(
    chat_view_model: ChatViewModel, mock_fs_executor
) -> None:
    """Тест записи файла без активной сессии."""
    chat_view_model.set_active_session(None)

    success = await chat_view_model._handle_fs_write("test.txt", "content")

    assert success is False
    mock_fs_executor.write_text_file_sync.assert_not_called()


@pytest.mark.asyncio
async def test_handle_fs_write_error(chat_view_model: ChatViewModel, mock_fs_executor) -> None:
    """Тест обработки ошибки при записи файла."""
    chat_view_model.set_active_session("test-session")
    mock_fs_executor.write_text_file_sync.side_effect = Exception("Write error")

    success = await chat_view_model._handle_fs_write("test.txt", "content")

    assert success is False


def test_handle_terminal_execute_success(
    chat_view_model: ChatViewModel, mock_terminal_executor
) -> None:
    """Тест успешного выполнения команды в терминале."""
    chat_view_model.set_active_session("test-session")

    result = chat_view_model._handle_terminal_execute("ls -la")

    assert result["success"] is True
    assert result["output"] == "test output"
    mock_terminal_executor.execute.assert_called_once_with("ls -la", cwd=None)


def test_handle_terminal_execute_with_cwd(
    chat_view_model: ChatViewModel, mock_terminal_executor
) -> None:
    """Тест выполнения команды с рабочей директорией."""
    chat_view_model.set_active_session("test-session")

    result = chat_view_model._handle_terminal_execute("pwd", cwd="/tmp")

    assert result["success"] is True
    mock_terminal_executor.execute.assert_called_once_with("pwd", cwd="/tmp")


def test_handle_terminal_execute_no_active_session(
    chat_view_model: ChatViewModel, mock_terminal_executor
) -> None:
    """Тест выполнения команды без активной сессии."""
    chat_view_model.set_active_session(None)

    result = chat_view_model._handle_terminal_execute("ls -la")

    assert result["success"] is False
    assert "No active session" in result.get("error", "")
    mock_terminal_executor.execute.assert_not_called()


def test_handle_terminal_execute_error(
    chat_view_model: ChatViewModel, mock_terminal_executor
) -> None:
    """Тест обработки ошибки при выполнении команды."""
    chat_view_model.set_active_session("test-session")
    mock_terminal_executor.execute.side_effect = Exception("Execution error")

    result = chat_view_model._handle_terminal_execute("ls -la")

    assert result["success"] is False
    assert "Execution error" in result.get("error", "")
