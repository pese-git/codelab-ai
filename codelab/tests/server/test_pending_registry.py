"""Тесты для PendingRequestRegistry.

Проверяют жизненный цикл asyncio.Future в реестре:
создание, разрешение, отмену и обработку неизвестных запросов.
"""

import pytest

from codelab.server.protocol.pending_registry import PendingRequestRegistry


@pytest.mark.asyncio
async def test_create_and_resolve():
    """Future создаётся и разрешается с ожидаемым результатом."""
    registry = PendingRequestRegistry()
    future = registry.create("req-1")
    assert registry.has("req-1")

    registry.resolve("req-1", {"outcome": "allow"})
    result = await future
    assert result == {"outcome": "allow"}
    assert not registry.has("req-1")


@pytest.mark.asyncio
async def test_cancel():
    """Future отменяется и удаляется из реестра."""
    registry = PendingRequestRegistry()
    future = registry.create("req-1")

    registry.cancel("req-1")
    assert future.cancelled()
    assert not registry.has("req-1")


@pytest.mark.asyncio
async def test_cancel_all():
    """Все futures отменяются, возвращается количество."""
    registry = PendingRequestRegistry()
    f1 = registry.create("req-1")
    f2 = registry.create("req-2")

    count = registry.cancel_all()
    assert count == 2
    assert f1.cancelled()
    assert f2.cancelled()


def test_resolve_unknown_returns_false():
    """Разрешение неизвестного запроса возвращает False."""
    registry = PendingRequestRegistry()
    result = registry.resolve("unknown-id", {})
    assert result is False


def test_cancel_unknown_returns_false():
    """Отмена неизвестного запроса возвращает False."""
    registry = PendingRequestRegistry()
    result = registry.cancel("unknown-id")
    assert result is False


def test_has_unknown_returns_false():
    """Проверка наличия неизвестного запроса возвращает False."""
    registry = PendingRequestRegistry()
    assert not registry.has("unknown-id")


def test_len_empty():
    """Пустой реестр имеет длину 0."""
    registry = PendingRequestRegistry()
    assert len(registry) == 0


@pytest.mark.asyncio
async def test_len_after_creates():
    """Длина реестра соответствует количеству созданных futures."""
    registry = PendingRequestRegistry()
    registry.create("req-1")
    registry.create("req-2")
    registry.create("req-3")
    assert len(registry) == 3


@pytest.mark.asyncio
async def test_len_decreases_after_resolve():
    """Длина уменьшается после разрешения."""
    registry = PendingRequestRegistry()
    registry.create("req-1")
    registry.create("req-2")
    assert len(registry) == 2

    registry.resolve("req-1", "ok")
    assert len(registry) == 1


@pytest.mark.asyncio
async def test_resolve_already_done_future():
    """Повторное разрешение уже завершённого Future не вызывает ошибку."""
    registry = PendingRequestRegistry()
    future = registry.create("req-1")
    registry.resolve("req-1", "first")

    # Future уже удалён из реестра и завершён
    # Повторный resolve должен вернуть False
    assert registry.resolve("req-1", "second") is False

    # Future должен содержать первый результат
    assert await future == "first"


@pytest.mark.asyncio
async def test_cancel_already_cancelled():
    """Повторная отмена уже отменённого Future возвращает False."""
    registry = PendingRequestRegistry()
    registry.create("req-1")
    registry.cancel("req-1")

    # Future уже удалён из реестра
    assert registry.cancel("req-1") is False


@pytest.mark.asyncio
async def test_cancel_all_empty():
    """Отмена всех futures в пустом реестре возвращает 0."""
    registry = PendingRequestRegistry()
    count = registry.cancel_all()
    assert count == 0


@pytest.mark.asyncio
async def test_multiple_resolve_independent():
    """Несколько futures разрешаются независимо друг от друга."""
    registry = PendingRequestRegistry()
    f1 = registry.create("req-1")
    f2 = registry.create("req-2")

    registry.resolve("req-1", "result-1")
    assert await f1 == "result-1"
    assert registry.has("req-2")

    registry.resolve("req-2", "result-2")
    assert await f2 == "result-2"
    assert len(registry) == 0
