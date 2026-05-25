"""LM Studio провайдер.

OpenAI-compatible провайдер для локального LM Studio API.
"""

from __future__ import annotations

from codelab.server.llm.base import LLMConfig
from codelab.server.llm.providers.openai_compatible import OpenAICompatibleProvider


class LMStudioProvider(OpenAICompatibleProvider):
    """Провайдер для LM Studio API.

    LM Studio — десктопное приложение для запуска LLM моделей локально.
    По умолчанию не требует API ключа, но поддерживает его для безопасности.
    """

    # Placeholder API key для локального LMStudio без аутентификации
    _PLACEHOLDER_KEY = "lmstudio"

    def __init__(self) -> None:
        """Инициализация."""
        super().__init__(
            base_url="http://localhost:1234/v1",
            default_model="local-model",
        )

    @property
    def name(self) -> str:
        """Имя провайдера."""
        return "lmstudio"

    async def initialize(self, config: LLMConfig) -> None:
        """Инициализировать провайдер.

        Если API ключ не предоставлен — используется placeholder,
        так как LMStudio локальный сервер не требует аутентификации.

        Args:
            config: Конфигурация провайдера
        """
        if not config.api_key:
            config = LLMConfig(
                api_key=self._PLACEHOLDER_KEY,
                model=config.model,
                base_url=config.base_url,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                extra=config.extra,
            )
        await super().initialize(config)
