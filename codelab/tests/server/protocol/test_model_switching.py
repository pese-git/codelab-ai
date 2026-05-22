"""Тесты для model switching через session/set_config_option."""

import pytest

from codelab.server.messages import ACPMessage
from codelab.server.protocol.handlers.config import session_set_config_option
from codelab.server.protocol.handlers.session import build_config_options
from codelab.server.protocol.state import SessionState
from codelab.server.storage.memory import InMemoryStorage


@pytest.fixture
async def storage() -> InMemoryStorage:
    """Создать хранилище с тестовой сессией."""
    storage = InMemoryStorage()
    session = SessionState(
        session_id="test-session",
        cwd="/tmp/test",
        config_values={"mode": "ask", "model": "openai/gpt-4o"},
    )
    await storage.save_session(session)
    return storage


@pytest.fixture
def config_specs() -> dict[str, dict[str, dict]]:
    """Создать config specs."""
    return {
        "mode": {
            "name": "Session Mode",
            "category": "mode",
            "default": "ask",
            "options": [
                {"value": "ask", "name": "Ask"},
                {"value": "code", "name": "Code"},
            ],
        },
        "model": {
            "name": "Model",
            "category": "model",
            "default": "openai/gpt-4o",
            "options": [
                {"value": "openai/gpt-4o", "name": "GPT-4o"},
                {"value": "anthropic/claude-sonnet-4", "name": "Claude Sonnet 4"},
                {"value": "openrouter/mistral-large", "name": "Mistral Large"},
            ],
        },
    }


@pytest.mark.asyncio
async def test_set_model_config_option(
    storage: InMemoryStorage,
    config_specs: dict[str, dict],
) -> None:
    """Проверить установку model config option."""
    outcome = await session_set_config_option(
        request_id="req-1",
        params={
            "sessionId": "test-session",
            "configId": "model",
            "value": "anthropic/claude-sonnet-4",
        },
        storage=storage,
        config_specs=config_specs,
    )

    assert outcome.response is not None
    assert outcome.response.result is not None

    # Проверить что configOptions содержит новое значение
    result = outcome.response.result
    assert "configOptions" in result
    config_options = result["configOptions"]

    # Найти model option
    model_option = next(
        (opt for opt in config_options if opt["id"] == "model"),
        None,
    )
    assert model_option is not None
    assert model_option["currentValue"] == "anthropic/claude-sonnet-4"


@pytest.mark.asyncio
async def test_set_invalid_model_value(
    storage: InMemoryStorage,
    config_specs: dict[str, dict],
) -> None:
    """Проверить ошибку при установке недопустимого значения модели."""
    outcome = await session_set_config_option(
        request_id="req-1",
        params={
            "sessionId": "test-session",
            "configId": "model",
            "value": "unknown/invalid-model",
        },
        storage=storage,
        config_specs=config_specs,
    )

    assert outcome.response is not None
    assert outcome.response.error is not None
    assert "unsupported value" in outcome.response.error.message


@pytest.mark.asyncio
async def test_set_unknown_config_option(
    storage: InMemoryStorage,
    config_specs: dict[str, dict],
) -> None:
    """Проверить ошибку при установке неизвестной config option."""
    outcome = await session_set_config_option(
        request_id="req-1",
        params={
            "sessionId": "test-session",
            "configId": "unknown_option",
            "value": "some_value",
        },
        storage=storage,
        config_specs=config_specs,
    )

    assert outcome.response is not None
    assert outcome.response.error is not None
    assert "unknown config option" in outcome.response.error.message


@pytest.mark.asyncio
async def test_session_not_found(
    storage: InMemoryStorage,
    config_specs: dict[str, dict],
) -> None:
    """Проверить ошибку при отсутствии сессии."""
    outcome = await session_set_config_option(
        request_id="req-1",
        params={
            "sessionId": "non-existent-session",
            "configId": "model",
            "value": "openai/gpt-4o",
        },
        storage=storage,
        config_specs=config_specs,
    )

    assert outcome.response is not None
    assert outcome.response.error is not None
    assert "Session not found" in outcome.response.error.message


@pytest.mark.asyncio
async def test_config_option_notification(
    storage: InMemoryStorage,
    config_specs: dict[str, dict],
) -> None:
    """Проверить что отправляется notification при изменении config."""
    outcome = await session_set_config_option(
        request_id="req-1",
        params={
            "sessionId": "test-session",
            "configId": "model",
            "value": "anthropic/claude-sonnet-4",
        },
        storage=storage,
        config_specs=config_specs,
    )

    # Проверить что есть notifications
    assert len(outcome.notifications) > 0

    # Найти config_option_update notification
    config_update = next(
        (n for n in outcome.notifications if n.method == "session/update"),
        None,
    )
    assert config_update is not None


@pytest.mark.asyncio
async def test_build_config_options_with_model(
    config_specs: dict[str, dict],
) -> None:
    """Проверить построение config options с model."""
    values = {
        "mode": "ask",
        "model": "openai/gpt-4o",
    }

    options = build_config_options(values, config_specs)

    assert len(options) == 2

    model_option = next(
        (opt for opt in options if opt["id"] == "model"),
        None,
    )
    assert model_option is not None
    assert model_option["currentValue"] == "openai/gpt-4o"
    assert model_option["category"] == "model"
