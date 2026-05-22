"""Тесты для fallback системы."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from codelab.server.llm.base import CompletionRequest, LLMMessage
from codelab.server.llm.errors import (
    AllProvidersFailed,
    ProviderError,
    ProviderErrorType,
)
from codelab.server.llm.fallback.base import FallbackContext
from codelab.server.llm.fallback.circuit_breaker import CircuitBreaker, CircuitState
from codelab.server.llm.fallback.config import FallbackConfig
from codelab.server.llm.fallback.factory import FallbackStrategyFactory
from codelab.server.llm.fallback.orchestrator import FallbackOrchestrator
from codelab.server.llm.fallback.sequential import SequentialFallback
from codelab.server.llm.models import CompletionResponse, StopReason


def _make_mock_provider(
    name: str,
    response: CompletionResponse | None = None,
    error: ProviderError | None = None,
) -> MagicMock:
    """Создать mock провайдер."""
    provider = MagicMock()
    provider.name = name
    provider.create_completion = AsyncMock()

    if error:
        provider.create_completion.side_effect = error
    elif response:
        provider.create_completion.return_value = response
    else:
        provider.create_completion.return_value = CompletionResponse(
            text=f"Response from {name}",
            stop_reason=StopReason.END_TURN,
        )

    return provider


class TestSequentialFallback:
    """Тесты для SequentialFallback."""

    @pytest.mark.asyncio
    async def test_select_provider_order(self) -> None:
        """Проверить порядок выбора провайдеров."""
        fallback = SequentialFallback(provider_order=["openai", "anthropic", "ollama"])
        candidates = [
            _make_mock_provider("openai"),
            _make_mock_provider("anthropic"),
            _make_mock_provider("ollama"),
        ]
        context = FallbackContext()

        provider = await fallback.select_provider(candidates, {}, context)
        assert provider.name == "openai"

    @pytest.mark.asyncio
    async def test_select_provider_skips_failed(self) -> None:
        """Проверить пропуск.failed провайдеров."""
        fallback = SequentialFallback(provider_order=["openai", "anthropic"])
        fallback._failed_providers.add("openai")

        candidates = [
            _make_mock_provider("openai"),
            _make_mock_provider("anthropic"),
        ]
        context = FallbackContext()

        provider = await fallback.select_provider(candidates, {}, context)
        assert provider.name == "anthropic"

    def test_on_success_resets_failed(self) -> None:
        """Проверить сброс.failed списка при успехе."""
        fallback = SequentialFallback()
        fallback._failed_providers.add("openai")
        fallback._failed_providers.add("anthropic")

        fallback.on_success("openai")
        assert len(fallback._failed_providers) == 0

    def test_on_failure_adds_to_failed(self) -> None:
        """Проверить добавление в.failed список."""
        fallback = SequentialFallback()
        error = ProviderError("Test", provider_id="openai")
        fallback.on_failure("openai", error)
        assert "openai" in fallback._failed_providers

    @pytest.mark.asyncio
    async def test_all_providers_failed(self) -> None:
        """Проверить ошибку при всех.failed провайдерах."""
        fallback = SequentialFallback(provider_order=["openai", "anthropic"])
        fallback._failed_providers.add("openai")
        fallback._failed_providers.add("anthropic")

        candidates = [
            _make_mock_provider("openai"),
            _make_mock_provider("anthropic"),
        ]
        context = FallbackContext()

        with pytest.raises(AllProvidersFailed):
            await fallback.select_provider(candidates, {}, context)


class TestCircuitBreaker:
    """Тесты для CircuitBreaker."""

    def test_initial_state_closed(self) -> None:
        """Проверить начальное состояние."""
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.is_circuit_open("test") is False
        assert cb.get_state("test") == CircuitState.CLOSED

    def test_opens_after_threshold(self) -> None:
        """Проверить открытие circuit после порога."""
        cb = CircuitBreaker(failure_threshold=3)
        error = ProviderError("Error", provider_id="test")

        for _ in range(3):
            cb.record_failure("test", error)

        assert cb.is_circuit_open("test") is True
        assert cb.get_state("test") == CircuitState.OPEN

    def test_closes_on_success(self) -> None:
        """Проверить закрытие circuit при успехе."""
        cb = CircuitBreaker(failure_threshold=2)
        error = ProviderError("Error", provider_id="test")

        cb.record_failure("test", error)
        cb.record_failure("test", error)
        assert cb.get_state("test") == CircuitState.OPEN

        cb.record_success("test")
        assert cb.get_state("test") == CircuitState.CLOSED

    def test_reset(self) -> None:
        """Проверить сброс circuit."""
        cb = CircuitBreaker(failure_threshold=2)
        error = ProviderError("Error", provider_id="test")

        cb.record_failure("test", error)
        cb.record_failure("test", error)
        assert cb.get_state("test") == CircuitState.OPEN

        cb.reset("test")
        assert cb.get_state("test") == CircuitState.CLOSED
        assert cb.is_circuit_open("test") is False

    def test_unknown_provider_closed(self) -> None:
        """Проверить что неизвестный провайдер имеет closed circuit."""
        cb = CircuitBreaker()
        assert cb.is_circuit_open("unknown") is False


class TestFallbackOrchestrator:
    """Тесты для FallbackOrchestrator."""

    @pytest.mark.asyncio
    async def test_success_first_provider(self) -> None:
        """Проверить успех с первого провайдера."""
        config = FallbackConfig(enabled=True)
        strategy = SequentialFallback()
        orchestrator = FallbackOrchestrator(strategy, config)

        provider = _make_mock_provider("openai")
        request = CompletionRequest(model="gpt-4o", messages=[LLMMessage(role="user", content="Hi")])

        response = await orchestrator.execute_completion([provider], request)
        assert response.text == "Response from openai"

    @pytest.mark.asyncio
    async def test_fallback_to_second_provider(self) -> None:
        """Проверить fallback на второго провайдера."""
        config = FallbackConfig(enabled=True, max_attempts=2)
        strategy = SequentialFallback(provider_order=["openai", "anthropic"])
        orchestrator = FallbackOrchestrator(strategy, config)

        primary = _make_mock_provider(
            "openai",
            error=ProviderError("Rate limited", error_type=ProviderErrorType.RATE_LIMIT),
        )
        secondary = _make_mock_provider("anthropic")

        request = CompletionRequest(model="gpt-4o", messages=[LLMMessage(role="user", content="Hi")])

        response = await orchestrator.execute_completion([primary, secondary], request)
        assert response.text == "Response from anthropic"

    @pytest.mark.asyncio
    async def test_non_retryable_error_propagates(self) -> None:
        """Проверить propagation non-retryable ошибки."""
        config = FallbackConfig(enabled=True)
        strategy = SequentialFallback()
        orchestrator = FallbackOrchestrator(strategy, config)

        provider = _make_mock_provider(
            "openai",
            error=ProviderError("Auth error", error_type=ProviderErrorType.AUTH_ERROR),
        )

        request = CompletionRequest(model="gpt-4o", messages=[LLMMessage(role="user", content="Hi")])

        with pytest.raises(ProviderError) as exc_info:
            await orchestrator.execute_completion([provider], request)
        assert exc_info.value.error_type == ProviderErrorType.AUTH_ERROR

    @pytest.mark.asyncio
    async def test_all_providers_failed(self) -> None:
        """Проверить ошибку при всех.failed провайдерах."""
        config = FallbackConfig(enabled=True, max_attempts=3)
        strategy = SequentialFallback(provider_order=["openai", "anthropic"])
        orchestrator = FallbackOrchestrator(strategy, config)

        primary = _make_mock_provider(
            "openai",
            error=ProviderError("Error 1", error_type=ProviderErrorType.RATE_LIMIT),
        )
        secondary = _make_mock_provider(
            "anthropic",
            error=ProviderError("Error 2", error_type=ProviderErrorType.TIMEOUT),
        )

        request = CompletionRequest(model="gpt-4o", messages=[LLMMessage(role="user", content="Hi")])

        with pytest.raises(AllProvidersFailed):
            await orchestrator.execute_completion([primary, secondary], request)

    @pytest.mark.asyncio
    async def test_fallback_disabled_uses_first(self) -> None:
        """Проверить что при выключенном fallback используется первый."""
        config = FallbackConfig(enabled=False)
        strategy = SequentialFallback()
        orchestrator = FallbackOrchestrator(strategy, config)

        provider = _make_mock_provider("openai")
        request = CompletionRequest(model="gpt-4o", messages=[LLMMessage(role="user", content="Hi")])

        response = await orchestrator.execute_completion([provider], request)
        assert response.text == "Response from openai"


class TestFallbackStrategyFactory:
    """Тесты для FallbackStrategyFactory."""

    def test_create_sequential(self) -> None:
        """Проверить создание sequential стратегии."""
        config = FallbackConfig(strategy="sequential", order=["openai", "anthropic"])
        strategy = FallbackStrategyFactory.create(config)
        assert isinstance(strategy, SequentialFallback)

    def test_create_unsupported_strategy(self) -> None:
        """Проверить ошибку при неподдерживаемой стратегии."""
        config = FallbackConfig(strategy="cost")
        with pytest.raises(ValueError, match="Unsupported fallback strategy"):
            FallbackStrategyFactory.create(config)
