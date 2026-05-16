"""Тесты для устранения двойного кэша сессий (2.1-double-cache-session-state).

Проверяет:
1. Сессия доступна после пересоздания ACPProtocol
2. LRU-кэш корректно вытесняет старые записи
"""

import asyncio

import pytest

from codelab.server.messages import ACPMessage
from codelab.server.protocol.core import ACPProtocol
from codelab.server.protocol.state import SessionState
from codelab.server.storage import CachedSessionStorage, InMemoryStorage


@pytest.mark.asyncio
async def test_session_survives_protocol_restart() -> None:
    """Сессия должна быть доступна после пересоздания ACPProtocol."""
    storage = InMemoryStorage()
    protocol1 = ACPProtocol(storage=storage)

    # Инициализируем протокол
    await protocol1.handle(ACPMessage.request("initialize", {"clientCapabilities": {}}))

    # Создаем сессию
    created = await protocol1.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert created.response is not None
    assert isinstance(created.response.result, dict)
    session_id = created.response.result["sessionId"]

    # "Перезапускаем" — создаем новый экземпляр протокола с тем же storage
    protocol2 = ACPProtocol(storage=storage)
    await protocol2.handle(ACPMessage.request("initialize", {"clientCapabilities": {}}))

    # Сессия должна быть найдена через session/load
    load_result = await protocol2.handle(
        ACPMessage.request(
            "session/load",
            {"sessionId": session_id, "cwd": "/tmp", "mcpServers": []},
        )
    )
    assert load_result.response is not None
    assert load_result.response.error is None


def test_lru_cache_eviction() -> None:
    """LRU-кэш должен вытеснять самые старые записи при переполнении."""
    backend = InMemoryStorage()
    cache = CachedSessionStorage(backend=backend, max_size=2)

    # Создаем сессии
    s1 = SessionState(session_id="s1", cwd="/", mcp_servers=[])
    s2 = SessionState(session_id="s2", cwd="/", mcp_servers=[])
    s3 = SessionState(session_id="s3", cwd="/", mcp_servers=[])

    # Сохраняем первые две сессии
    asyncio.run(cache.save_session(s1))
    asyncio.run(cache.save_session(s2))

    assert cache.cache_size == 2

    # Добавляем третью — должна вытеснить первую (LRU)
    asyncio.run(cache.save_session(s3))
    assert cache.cache_size == 2
    assert "s1" not in cache._cache
    assert "s3" in cache._cache


@pytest.mark.asyncio
async def test_cached_storage_delegates_to_backend() -> None:
    """CachedSessionStorage должен делегировать операции backend."""
    backend = InMemoryStorage()
    cache = CachedSessionStorage(backend=backend, max_size=10)

    session = SessionState(session_id="test", cwd="/tmp", mcp_servers=[])
    await cache.save_session(session)

    # Загрузка из кэша
    loaded = await cache.load_session("test")
    assert loaded is not None
    assert loaded.session_id == "test"

    # Удаление
    deleted = await cache.delete_session("test")
    assert deleted is True

    # Проверка существования
    exists = await cache.session_exists("test")
    assert exists is False


@pytest.mark.asyncio
async def test_cached_storage_list_sessions_delegates_to_backend() -> None:
    """list_sessions должен делегировать backend без прогрева кэша."""
    backend = InMemoryStorage()
    cache = CachedSessionStorage(backend=backend, max_size=10)

    # Создаем несколько сессий
    for i in range(5):
        session = SessionState(session_id=f"s{i}", cwd="/tmp", mcp_servers=[])
        await cache.save_session(session)

    # list_sessions должен вернуть все сессии через backend
    sessions, next_cursor = await cache.list_sessions(limit=10)
    assert len(sessions) == 5
    assert next_cursor is None
