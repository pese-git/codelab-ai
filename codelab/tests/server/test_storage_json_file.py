"""Unit-тесты для JsonFileStorage."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from codelab.server.protocol.state import (
    ActiveTurnState,
    ClientRuntimeCapabilities,
    SessionState,
    ToolCallState,
)
from codelab.server.storage import JsonFileStorage, StorageError


@pytest.fixture
def temp_storage_dir() -> Iterator[Path]:
    """Создает временную директорию для тестов."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.mark.asyncio
async def test_save_and_load_session(temp_storage_dir: Path) -> None:
    """Тест сохранения и загрузки сессии из JSON файла."""
    storage = JsonFileStorage(temp_storage_dir)
    session = SessionState(session_id="sess_1", cwd="/tmp", mcp_servers=[])

    await storage.save_session(session)
    loaded = await storage.load_session("sess_1")

    assert loaded is not None
    assert loaded.session_id == "sess_1"
    assert loaded.cwd == "/tmp"
    # Проверяем, что файл был создан
    assert (temp_storage_dir / "sess_1.json").exists()


@pytest.mark.asyncio
async def test_load_nonexistent_session(temp_storage_dir: Path) -> None:
    """Тест загрузки несуществующей сессии."""
    storage = JsonFileStorage(temp_storage_dir)
    loaded = await storage.load_session("nonexistent")
    assert loaded is None


@pytest.mark.asyncio
async def test_delete_session(temp_storage_dir: Path) -> None:
    """Тест удаления сессии из JSON файла."""
    storage = JsonFileStorage(temp_storage_dir)
    session = SessionState(session_id="sess_1", cwd="/tmp", mcp_servers=[])

    await storage.save_session(session)
    assert (temp_storage_dir / "sess_1.json").exists()

    deleted = await storage.delete_session("sess_1")
    assert deleted is True
    assert not (temp_storage_dir / "sess_1.json").exists()

    loaded = await storage.load_session("sess_1")
    assert loaded is None


@pytest.mark.asyncio
async def test_delete_nonexistent_session(temp_storage_dir: Path) -> None:
    """Тест удаления несуществующей сессии."""
    storage = JsonFileStorage(temp_storage_dir)
    deleted = await storage.delete_session("nonexistent")
    assert deleted is False


@pytest.mark.asyncio
async def test_session_exists(temp_storage_dir: Path) -> None:
    """Тест проверки существования сессии."""
    storage = JsonFileStorage(temp_storage_dir)
    session = SessionState(session_id="sess_1", cwd="/tmp", mcp_servers=[])

    assert not await storage.session_exists("sess_1")
    await storage.save_session(session)
    assert await storage.session_exists("sess_1")


@pytest.mark.asyncio
async def test_persistence(temp_storage_dir: Path) -> None:
    """Тест persistence - данные сохраняются между инстансами."""
    # Сохраняем сессию через первый инстанс
    storage1 = JsonFileStorage(temp_storage_dir)
    session = SessionState(session_id="sess_1", cwd="/tmp", mcp_servers=[])
    await storage1.save_session(session)

    # Загружаем через второй инстанс
    storage2 = JsonFileStorage(temp_storage_dir)
    loaded = await storage2.load_session("sess_1")

    assert loaded is not None
    assert loaded.session_id == "sess_1"
    assert loaded.cwd == "/tmp"


@pytest.mark.asyncio
async def test_list_sessions_empty(temp_storage_dir: Path) -> None:
    """Тест получения пустого списка сессий."""
    storage = JsonFileStorage(temp_storage_dir)
    sessions, cursor = await storage.list_sessions()

    assert sessions == []
    assert cursor is None


@pytest.mark.asyncio
async def test_list_sessions(temp_storage_dir: Path) -> None:
    """Тест получения списка сессий."""
    storage = JsonFileStorage(temp_storage_dir)
    session1 = SessionState(session_id="sess_1", cwd="/tmp", mcp_servers=[])
    session2 = SessionState(session_id="sess_2", cwd="/home", mcp_servers=[])

    await storage.save_session(session1)
    await storage.save_session(session2)

    sessions, cursor = await storage.list_sessions()
    assert len(sessions) == 2
    assert cursor is None


@pytest.mark.asyncio
async def test_list_sessions_with_cwd_filter(temp_storage_dir: Path) -> None:
    """Тест фильтрации сессий по рабочей директории."""
    storage = JsonFileStorage(temp_storage_dir)
    session1 = SessionState(session_id="sess_1", cwd="/tmp", mcp_servers=[])
    session2 = SessionState(session_id="sess_2", cwd="/home", mcp_servers=[])

    await storage.save_session(session1)
    await storage.save_session(session2)

    sessions, cursor = await storage.list_sessions(cwd="/tmp")
    assert len(sessions) == 1
    assert sessions[0].session_id == "sess_1"


@pytest.mark.asyncio
async def test_list_sessions_pagination(temp_storage_dir: Path) -> None:
    """Тест пагинации при получении списка сессий."""
    storage = JsonFileStorage(temp_storage_dir)

    # Создаем 5 сессий
    for i in range(5):
        session = SessionState(session_id=f"sess_{i}", cwd="/tmp", mcp_servers=[])
        await storage.save_session(session)

    # Получаем первую страницу с лимитом 2
    page1, cursor1 = await storage.list_sessions(limit=2)
    assert len(page1) == 2
    assert cursor1 is not None

    # Получаем вторую страницу
    page2, cursor2 = await storage.list_sessions(cursor=cursor1, limit=2)
    assert len(page2) == 2
    assert cursor2 is not None

    # Проверяем, что идентификаторы не повторяются
    ids1 = {s.session_id for s in page1}
    ids2 = {s.session_id for s in page2}
    assert len(ids1 & ids2) == 0


@pytest.mark.asyncio
async def test_list_sessions_sorted_by_updated_at(temp_storage_dir: Path) -> None:
    """Тест сортировки сессий по updated_at (новые первыми)."""
    storage = JsonFileStorage(temp_storage_dir)
    session1 = SessionState(session_id="sess_1", cwd="/tmp", mcp_servers=[])

    await storage.save_session(session1)
    # Сохраняем первую сессию, затем вторую - вторая должна быть "новее"
    session2 = SessionState(session_id="sess_2", cwd="/tmp", mcp_servers=[])
    await storage.save_session(session2)

    sessions, _ = await storage.list_sessions()
    # Новая сессия должна быть первой
    assert sessions[0].session_id == "sess_2"
    assert sessions[1].session_id == "sess_1"


@pytest.mark.asyncio
async def test_serialize_complex_session(temp_storage_dir: Path) -> None:
    """Тест сериализации сложной сессии со вложенными структурами."""
    storage = JsonFileStorage(temp_storage_dir)

    # Создаем сессию со всеми типами данных
    session = SessionState(
        session_id="complex_sess",
        cwd="/work",
        mcp_servers=[{"name": "test", "args": ["arg1"]}],
        title="Test Session",
        config_values={"key1": "value1", "key2": "value2"},
        history=[{"role": "user", "content": "test"}],
        tool_call_counter=5,
        available_commands=[{"name": "cmd1", "description": "Test command"}],
        latest_plan=[{"step": "1", "action": "test"}],
        permission_policy={"kind_test": "allow_always"},
        cancelled_permission_requests={"req_1", "req_2"},
        cancelled_client_rpc_requests={"rpc_1", "rpc_2"},
        runtime_capabilities=ClientRuntimeCapabilities(fs_read=True, fs_write=True, terminal=False),
    )

    # Добавляем tool call
    tool_call = ToolCallState(
        tool_call_id="call_001",
        title="Test Call",
        kind="execute",
        status="completed",
        content=[{"type": "text", "text": "result"}],
    )
    session.tool_calls["call_001"] = tool_call

    # Добавляем active turn
    active_turn = ActiveTurnState(
        prompt_request_id="req_001",
        session_id="complex_sess",
        cancel_requested=False,
        phase="completed",
    )
    session.active_turn = active_turn

    # Сохраняем и загружаем
    await storage.save_session(session)
    loaded = await storage.load_session("complex_sess")

    assert loaded is not None
    assert loaded.session_id == "complex_sess"
    assert loaded.cwd == "/work"
    assert loaded.title == "Test Session"
    assert len(loaded.mcp_servers) == 1
    assert loaded.config_values["key1"] == "value1"
    assert len(loaded.history) == 1
    assert loaded.tool_call_counter == 5
    assert "call_001" in loaded.tool_calls
    assert loaded.tool_calls["call_001"].title == "Test Call"
    # active_turn сериализуется для корректного сопоставления permission/client_rpc ответов
    assert loaded.active_turn is not None
    assert loaded.active_turn.prompt_request_id == "req_001"
    assert loaded.runtime_capabilities is not None
    assert loaded.runtime_capabilities.fs_read is True
    assert loaded.runtime_capabilities.fs_write is True
    assert loaded.runtime_capabilities.terminal is False


@pytest.mark.asyncio
async def test_json_file_format(temp_storage_dir: Path) -> None:
    """Тест что JSON файл имеет ожидаемый формат."""
    storage = JsonFileStorage(temp_storage_dir)
    session = SessionState(
        session_id="test_json",
        cwd="/tmp",
        mcp_servers=[{"name": "test"}],
        title="Test",
    )

    await storage.save_session(session)

    # Читаем файл и проверяем JSON
    file_path = temp_storage_dir / "test_json.json"
    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)

    assert data["session_id"] == "test_json"
    assert data["cwd"] == "/tmp"
    assert data["title"] == "Test"
    assert isinstance(data["mcp_servers"], list)
    assert "updated_at" in data



@pytest.mark.asyncio
async def test_invalid_json_file_error(temp_storage_dir: Path) -> None:
    """Тест обработки битого JSON файла."""
    storage = JsonFileStorage(temp_storage_dir)

    # Создаем битый JSON файл
    file_path = temp_storage_dir / "broken.json"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("{ invalid json }")

    # Должна быть ошибка при загрузке
    with pytest.raises(StorageError):
        await storage.load_session("broken")


@pytest.mark.asyncio
async def test_update_session_updates_timestamp(temp_storage_dir: Path) -> None:
    """Тест обновления временной метки при сохранении."""
    storage = JsonFileStorage(temp_storage_dir)
    session = SessionState(session_id="sess_time", cwd="/tmp", mcp_servers=[])
    original_time = session.updated_at

    await storage.save_session(session)
    loaded = await storage.load_session("sess_time")

    assert loaded is not None
    # Временная метка должна быть обновлена
    assert loaded.updated_at != original_time
    # И она должна быть более свежей
    assert loaded.updated_at > original_time


@pytest.mark.asyncio
async def test_active_turn_serialized_for_permission_matching(temp_storage_dir: Path) -> None:
    """Тест что active_turn сериализуется (нужен для find_session_by_permission_request_id)."""
    storage = JsonFileStorage(temp_storage_dir)

    session = SessionState(
        session_id="sess_active",
        cwd="/tmp",
        mcp_servers=[],
    )
    session.active_turn = ActiveTurnState(
        prompt_request_id="req_1",
        session_id="sess_active",
    )
    session.active_turn.permission_request_id = "perm_1"

    await storage.save_session(session)

    # active_turn должен быть в JSON
    file_path = temp_storage_dir / "sess_active.json"
    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)

    assert "active_turn" in data, "active_turn должен сериализоваться в JSON"
    assert data["active_turn"]["permission_request_id"] == "perm_1"

    # При загрузке active_turn восстанавливается (для сопоставления ответов)
    loaded = await storage.load_session("sess_active")
    assert loaded is not None
    assert loaded.active_turn is not None
    assert loaded.active_turn.permission_request_id == "perm_1"
