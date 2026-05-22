"""Тесты pagination edge cases для session/list.

Покрывает edge cases, упомянутые в ACP_IMPLEMENTATION_VERIFICATION.md:
- Invalid cursor (разные типы невалидности)
- Empty results boundary
- Pagination boundaries
- Cursor encode/decode unit tests
- Storage level edge cases

Согласовано с ACP Spec: doc/Agent Client Protocol/protocol/04-Session List.md
"""

import base64
import json

import pytest

from codelab.server.messages import ACPMessage
from codelab.server.protocol import ACPProtocol
from codelab.server.protocol.handlers.session import (
    decode_session_cursor,
    encode_session_cursor,
)
from codelab.server.protocol.state import SessionState
from codelab.server.storage import InMemoryStorage

# ============================================================================
# Invalid cursor edge cases (через ACPProtocol)
# ============================================================================


@pytest.mark.asyncio
async def test_session_list_rejects_cursor_with_valid_base64_but_invalid_json() -> None:
    """Cursor декодируется из base64, но не является валидным JSON."""
    protocol = ACPProtocol()
    await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )

    invalid_cursor = base64.urlsafe_b64encode(b"not-json").decode("ascii")
    response = await protocol.handle(
        ACPMessage.request("session/list", {"cursor": invalid_cursor})
    )

    assert response.response is not None
    assert response.response.error is not None
    assert response.response.error.code == -32602


@pytest.mark.asyncio
async def test_session_list_rejects_cursor_with_valid_json_but_missing_index() -> None:
    """Cursor — валидный JSON, но без поля index."""
    protocol = ACPProtocol()
    await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )

    payload = json.dumps({"page": 1}).encode("utf-8")
    invalid_cursor = base64.urlsafe_b64encode(payload).decode("ascii")
    response = await protocol.handle(
        ACPMessage.request("session/list", {"cursor": invalid_cursor})
    )

    assert response.response is not None
    assert response.response.error is not None
    assert response.response.error.code == -32602


@pytest.mark.asyncio
async def test_session_list_rejects_cursor_with_non_int_index() -> None:
    """Cursor имеет index, но он не int (строка)."""
    protocol = ACPProtocol()
    await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )

    payload = json.dumps({"index": "not-an-int"}).encode("utf-8")
    invalid_cursor = base64.urlsafe_b64encode(payload).decode("ascii")
    response = await protocol.handle(
        ACPMessage.request("session/list", {"cursor": invalid_cursor})
    )

    assert response.response is not None
    assert response.response.error is not None
    assert response.response.error.code == -32602


@pytest.mark.asyncio
async def test_session_list_rejects_cursor_with_negative_index() -> None:
    """Cursor имеет index < 0."""
    protocol = ACPProtocol()
    await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )

    payload = json.dumps({"index": -1}).encode("utf-8")
    invalid_cursor = base64.urlsafe_b64encode(payload).decode("ascii")
    response = await protocol.handle(
        ACPMessage.request("session/list", {"cursor": invalid_cursor})
    )

    assert response.response is not None
    assert response.response.error is not None
    assert response.response.error.code == -32602


@pytest.mark.asyncio
async def test_session_list_returns_empty_page_when_cursor_beyond_total() -> None:
    """Cursor указывает за пределы общего числа сессий — пустая страница, не ошибка."""
    protocol = ACPProtocol()
    await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )

    payload = json.dumps({"index": 9999}).encode("utf-8")
    beyond_cursor = base64.urlsafe_b64encode(payload).decode("ascii")
    response = await protocol.handle(
        ACPMessage.request("session/list", {"cursor": beyond_cursor})
    )

    assert response.response is not None
    assert response.response.error is None
    assert response.response.result is not None
    assert response.response.result["sessions"] == []
    assert response.response.result["nextCursor"] is None


# ============================================================================
# Empty results edge cases
# ============================================================================


@pytest.mark.asyncio
async def test_session_list_returns_empty_when_no_sessions() -> None:
    """Пустой storage — должен вернуть пустой массив sessions."""
    protocol = ACPProtocol()
    response = await protocol.handle(ACPMessage.request("session/list", {}))

    assert response.response is not None
    assert response.response.error is None
    assert response.response.result is not None
    assert response.response.result["sessions"] == []
    assert response.response.result["nextCursor"] is None


@pytest.mark.asyncio
async def test_session_list_returns_empty_when_cwd_filter_no_match() -> None:
    """Фильтр cwd не находит matching сессий — пустой массив."""
    protocol = ACPProtocol()
    await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )

    response = await protocol.handle(
        ACPMessage.request("session/list", {"cwd": "/nonexistent/path"})
    )

    assert response.response is not None
    assert response.response.error is None
    assert response.response.result is not None
    assert response.response.result["sessions"] == []
    assert response.response.result["nextCursor"] is None


@pytest.mark.asyncio
async def test_session_list_returns_empty_page_after_last_session() -> None:
    """Cursor указывает точно после последней сессии — пустая страница."""
    protocol = ACPProtocol()
    await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )

    first_page = await protocol.handle(ACPMessage.request("session/list", {}))
    assert first_page.response is not None
    assert first_page.response.result is not None
    next_cursor = first_page.response.result.get("nextCursor")

    if next_cursor:
        second_page = await protocol.handle(
            ACPMessage.request("session/list", {"cursor": next_cursor})
        )
        assert second_page.response is not None
        assert second_page.response.result is not None
        assert second_page.response.result["sessions"] == []
        assert second_page.response.result["nextCursor"] is None


# ============================================================================
# Pagination boundary cases
# ============================================================================


@pytest.mark.asyncio
async def test_session_list_exactly_page_size_returns_no_next_cursor() -> None:
    """Ровно 50 сессий (page size) — одна страница без nextCursor."""
    protocol = ACPProtocol()
    for _ in range(50):
        await protocol.handle(
            ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
        )

    response = await protocol.handle(ACPMessage.request("session/list", {}))
    assert response.response is not None
    assert response.response.result is not None
    assert len(response.response.result["sessions"]) == 50
    assert response.response.result["nextCursor"] is None


@pytest.mark.asyncio
async def test_session_list_one_less_than_page_size_returns_no_next_cursor() -> None:
    """49 сессий — одна страница без nextCursor."""
    protocol = ACPProtocol()
    for _ in range(49):
        await protocol.handle(
            ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
        )

    response = await protocol.handle(ACPMessage.request("session/list", {}))
    assert response.response is not None
    assert response.response.result is not None
    assert len(response.response.result["sessions"]) == 49
    assert response.response.result["nextCursor"] is None


@pytest.mark.asyncio
async def test_session_list_one_more_than_page_size_returns_next_cursor() -> None:
    """51 сессия — первая страница 50, есть nextCursor."""
    protocol = ACPProtocol()
    for _ in range(51):
        await protocol.handle(
            ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
        )

    response = await protocol.handle(ACPMessage.request("session/list", {}))
    assert response.response is not None
    assert response.response.result is not None
    assert len(response.response.result["sessions"]) == 50
    assert response.response.result["nextCursor"] is not None

    second_page = await protocol.handle(
        ACPMessage.request("session/list", {"cursor": response.response.result["nextCursor"]})
    )
    assert second_page.response is not None
    assert second_page.response.result is not None
    assert len(second_page.response.result["sessions"]) == 1
    assert second_page.response.result["nextCursor"] is None


@pytest.mark.asyncio
async def test_session_list_cursor_at_exact_page_boundary() -> None:
    """Cursor=50 на 100 сессиях — вторая страница с 50 сессиями."""
    protocol = ACPProtocol()
    for _ in range(100):
        await protocol.handle(
            ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
        )

    first_page = await protocol.handle(ACPMessage.request("session/list", {}))
    assert first_page.response is not None
    assert first_page.response.result is not None
    assert len(first_page.response.result["sessions"]) == 50
    next_cursor = first_page.response.result["nextCursor"]
    assert next_cursor is not None

    second_page = await protocol.handle(
        ACPMessage.request("session/list", {"cursor": next_cursor})
    )
    assert second_page.response is not None
    assert second_page.response.result is not None
    assert len(second_page.response.result["sessions"]) == 50
    assert second_page.response.result["nextCursor"] is None


# ============================================================================
# Cursor encode/decode unit tests
# ============================================================================


def test_encode_decode_cursor_round_trip() -> None:
    """encode → decode возвращает оригинальный индекс."""
    for index in [0, 1, 50, 100, 9999]:
        cursor = encode_session_cursor(index)
        decoded = decode_session_cursor(cursor)
        assert decoded == index


def test_decode_cursor_returns_none_for_invalid_base64() -> None:
    """Невалидный base64 → None."""
    assert decode_session_cursor("not-valid-base64!!!") is None


def test_decode_cursor_returns_none_for_invalid_json() -> None:
    """Base64 декодируется, но не JSON → None."""
    payload = base64.urlsafe_b64encode(b"not-json").decode("ascii")
    assert decode_session_cursor(payload) is None


def test_decode_cursor_returns_none_for_missing_index() -> None:
    """JSON без поля index → None."""
    payload = json.dumps({"page": 1}).encode("utf-8")
    cursor = base64.urlsafe_b64encode(payload).decode("ascii")
    assert decode_session_cursor(cursor) is None


def test_decode_cursor_returns_none_for_negative_index() -> None:
    """index < 0 → None."""
    payload = json.dumps({"index": -5}).encode("utf-8")
    cursor = base64.urlsafe_b64encode(payload).decode("ascii")
    assert decode_session_cursor(cursor) is None


def test_decode_cursor_returns_none_for_non_dict_json() -> None:
    """JSON не dict (например, массив) → None."""
    payload = json.dumps([1, 2, 3]).encode("utf-8")
    cursor = base64.urlsafe_b64encode(payload).decode("ascii")
    assert decode_session_cursor(cursor) is None


# ============================================================================
# Storage level edge cases (InMemoryStorage)
# ============================================================================


@pytest.mark.asyncio
async def test_storage_list_sessions_cursor_beyond_all_sessions() -> None:
    """Storage: cursor ссылается на несуществующий session_id — возвращает с начала."""
    storage = InMemoryStorage()
    for i in range(5):
        session = SessionState(session_id=f"sess_{i}", cwd="/tmp", mcp_servers=[])
        await storage.save_session(session)

    page, next_cursor = await storage.list_sessions(cursor="nonexistent_session_id")
    assert len(page) == 5
    assert next_cursor is None


@pytest.mark.asyncio
async def test_storage_list_sessions_cursor_on_last_session() -> None:
    """Storage: cursor — последняя сессия (по updated_at) — пустая страница."""
    storage = InMemoryStorage()

    session_oldest = SessionState(session_id="sess_oldest", cwd="/tmp", mcp_servers=[])
    await storage.save_session(session_oldest)

    session_newest = SessionState(session_id="sess_newest", cwd="/tmp", mcp_servers=[])
    await storage.save_session(session_newest)

    first_page, cursor1 = await storage.list_sessions(limit=1)
    assert len(first_page) == 1
    assert first_page[0].session_id == "sess_newest"
    assert cursor1 is not None

    second_page, cursor2 = await storage.list_sessions(cursor=cursor1, limit=1)
    assert len(second_page) == 1
    assert second_page[0].session_id == "sess_oldest"
    assert cursor2 is None


@pytest.mark.asyncio
async def test_storage_list_sessions_empty_page_with_cursor() -> None:
    """Storage: pagination разбивает сессии на страницы корректно."""
    storage = InMemoryStorage()
    for i in range(3):
        session = SessionState(session_id=f"sess_{i}", cwd="/tmp", mcp_servers=[])
        await storage.save_session(session)

    page1, cursor1 = await storage.list_sessions(limit=2)
    assert len(page1) == 2
    assert cursor1 is not None

    page2, cursor2 = await storage.list_sessions(cursor=cursor1, limit=2)
    assert len(page2) == 1
    assert cursor2 is None


@pytest.mark.asyncio
async def test_storage_list_sessions_cursor_for_nonexistent_session() -> None:
    """Storage: cursor ссылается на несуществующий session_id — возвращает с начала."""
    storage = InMemoryStorage()
    for i in range(3):
        session = SessionState(session_id=f"sess_{i}", cwd="/tmp", mcp_servers=[])
        await storage.save_session(session)

    page, next_cursor = await storage.list_sessions(
        cursor="nonexistent_session", limit=10
    )
    assert len(page) == 3
    assert next_cursor is None
