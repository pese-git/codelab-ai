"""Тесты для ProviderEventBus интеграции."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from codelab.server.llm.base import LLMConfig
from codelab.server.llm.events import (
    ProviderEvent,
    ProviderEventBus,
    ProviderFailed,
    ProviderInitialized,
)
from codelab.server.llm.registry import LLMProviderRegistry


class TestProviderEventBus:
    """Тесты для ProviderEventBus."""

    @pytest.mark.asyncio
    async def test_event_emission(self) -> None:
        """Проверить что события эмитятся."""
        bus = ProviderEventBus()
        received_events: list[ProviderEvent] = []

        async def collector(event: ProviderEvent) -> None:
            received_events.append(event)

        bus.subscribe_all(collector)

        event = ProviderInitialized(provider_id="openai", model="gpt-4o")
        await bus.publish(event)

        assert len(received_events) == 1
        assert received_events[0].provider_id == "openai"

    @pytest.mark.asyncio
    async def test_specific_event_subscription(self) -> None:
        """Проверить подписку на конкретный тип события."""
        bus = ProviderEventBus()
        received: list[ProviderInitialized] = []

        async def handler(event: ProviderInitialized) -> None:
            received.append(event)

        bus.subscribe(ProviderInitialized, handler)

        await bus.publish(ProviderInitialized(provider_id="openai", model="gpt-4o"))
        await bus.publish(ProviderFailed(provider_id="openai", error="test"))

        assert len(received) == 1
        assert received[0].model == "gpt-4o"

    @pytest.mark.asyncio
    async def test_provider_initialized_event(self) -> None:
        """Проверить ProviderInitialized event."""
        bus = ProviderEventBus()
        received: list[ProviderInitialized] = []

        async def handler(event: ProviderInitialized) -> None:
            received.append(event)

        bus.subscribe(ProviderInitialized, handler)

        await bus.publish(
            ProviderInitialized(
                provider_id="anthropic",
                model="claude-sonnet-4",
                base_url="https://api.anthropic.com",
            )
        )

        assert len(received) == 1
        assert received[0].provider_id == "anthropic"
        assert received[0].model == "claude-sonnet-4"
        assert received[0].base_url == "https://api.anthropic.com"

    @pytest.mark.asyncio
    async def test_provider_failed_event(self) -> None:
        """Проверить ProviderFailed event."""
        bus = ProviderEventBus()
        received: list[ProviderFailed] = []

        async def handler(event: ProviderFailed) -> None:
            received.append(event)

        bus.subscribe(ProviderFailed, handler)

        await bus.publish(
            ProviderFailed(
                provider_id="openai",
                error="Rate limited",
                error_type="RateLimitError",
            )
        )

        assert len(received) == 1
        assert received[0].provider_id == "openai"
        assert received[0].error == "Rate limited"
        assert received[0].error_type == "RateLimitError"


class TestRegistryEventIntegration:
    """Тесты для интеграции Registry с Event Bus."""

    @pytest.mark.asyncio
    async def test_create_provider_emits_initialized_event(self) -> None:
        """Проверить что create_provider эмитит ProviderInitialized."""
        registry = LLMProviderRegistry()
        bus = ProviderEventBus()

        # Заменить глобальный event_bus на тестовый
        import codelab.server.llm.registry as reg_module

        original_bus = reg_module.event_bus
        reg_module.event_bus = bus

        try:
            received: list[ProviderInitialized] = []

            async def handler(event: ProviderInitialized) -> None:
                received.append(event)

            bus.subscribe(ProviderInitialized, handler)

            mock_provider = MagicMock()
            mock_provider.initialize = AsyncMock()
            mock_provider.name = "test"

            registry.register("test", lambda: mock_provider)

            config = LLMConfig(api_key="test", model="test-model")
            await registry.create_provider("test", config)

            assert len(received) == 1
            assert received[0].provider_id == "test"
            assert received[0].model == "test-model"
        finally:
            reg_module.event_bus = original_bus

    @pytest.mark.asyncio
    async def test_create_provider_emits_failed_event_on_error(self) -> None:
        """Проверить что create_provider эмитит ProviderFailed при ошибке."""
        registry = LLMProviderRegistry()
        bus = ProviderEventBus()

        import codelab.server.llm.registry as reg_module

        original_bus = reg_module.event_bus
        reg_module.event_bus = bus

        try:
            received: list[ProviderFailed] = []

            async def handler(event: ProviderFailed) -> None:
                received.append(event)

            bus.subscribe(ProviderFailed, handler)

            mock_provider = MagicMock()
            mock_provider.initialize = AsyncMock(side_effect=RuntimeError("Connection failed"))

            registry.register("test", lambda: mock_provider)

            config = LLMConfig(api_key="test", model="test-model")

            with pytest.raises(RuntimeError, match="Connection failed"):
                await registry.create_provider("test", config)

            assert len(received) == 1
            assert received[0].provider_id == "test"
            assert "Connection failed" in received[0].error
        finally:
            reg_module.event_bus = original_bus
