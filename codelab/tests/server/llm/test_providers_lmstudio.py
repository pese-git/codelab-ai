"""Тесты для LMStudio провайдера."""

import pytest

from codelab.server.llm.base import LLMConfig
from codelab.server.llm.providers.lmstudio import LMStudioProvider


@pytest.fixture
def provider():
    """Создать экземпляр LMStudioProvider."""
    return LMStudioProvider()


class TestLMStudioProviderInit:
    """Тесты инициализации LMStudioProvider."""

    @pytest.mark.asyncio
    async def test_init_without_api_key(self, provider):
        """Инициализация без API key должна использовать placeholder."""
        config = LLMConfig(model="qwen3-coder")
        await provider.initialize(config)

        # Проверяем что клиент создан и base_url корректный
        assert provider._client is not None
        assert provider._base_url == "http://localhost:1234/v1"

    @pytest.mark.asyncio
    async def test_init_with_empty_api_key(self, provider):
        """Инициализация с пустым API key должна использовать placeholder."""
        config = LLMConfig(api_key="", model="qwen3-coder")
        await provider.initialize(config)

        assert provider._client is not None

    @pytest.mark.asyncio
    async def test_init_with_custom_api_key(self, provider):
        """Инициализация с custom API key должна использовать его."""
        custom_key = "my-secret-key"
        config = LLMConfig(api_key=custom_key, model="qwen3-coder")
        await provider.initialize(config)

        assert provider._client is not None
        # Проверяем что ключ был передан в клиент
        assert provider._client.api_key == custom_key

    @pytest.mark.asyncio
    async def test_init_preserves_config_values(self, provider):
        """Инициализация должна сохранять все значения config."""
        config = LLMConfig(
            api_key=None,
            model="qwen3-coder-30b",
            temperature=0.5,
            max_tokens=4096,
        )
        await provider.initialize(config)

        assert provider._config is not None
        assert provider._config.model == "qwen3-coder-30b"
        assert provider._config.temperature == 0.5
        assert provider._config.max_tokens == 4096
        # Placeholder key должен быть установлен
        assert provider._config.api_key == LMStudioProvider._PLACEHOLDER_KEY

    @pytest.mark.asyncio
    async def test_name_property(self, provider):
        """Имя провайдера должно быть 'lmstudio'."""
        assert provider.name == "lmstudio"

    @pytest.mark.asyncio
    async def test_base_url_default(self, provider):
        """Base URL по умолчанию должен указывать на локальный LMStudio."""
        assert provider._base_url == "http://localhost:1234/v1"

    @pytest.mark.asyncio
    async def test_default_model(self, provider):
        """Модель по умолчанию должна быть 'local-model'."""
        assert provider._default_model == "local-model"
