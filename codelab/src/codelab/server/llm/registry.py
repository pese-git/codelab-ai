"""Registry для LLM провайдеров.

LLMProviderRegistry — центральный реестр провайдеров с factory-паттерном.
Позволяет регистрировать провайдеры, создавать их экземпляры лениво,
получать список всех доступных моделей и информацию о провайдерах.
"""

from __future__ import annotations

from typing import Any, Callable

import structlog

from codelab.server.llm.base import LLMConfig, LLMProvider
from codelab.server.llm.errors import ModelNotFoundError, ProviderNotFoundError
from codelab.server.llm.events import ProviderFailed, ProviderInitialized, event_bus
from codelab.server.llm.models import ModelInfo, ProviderInfo

logger = structlog.get_logger()


# Factory-функция для создания провайдера
ProviderFactory = Callable[[], LLMProvider]


class LLMProviderRegistry:
    """Реестр LLM провайдеров.

    Хранит factory-функции для создания провайдеров лениво.
    Поддерживает регистрацию провайдеров, получение информации
    о моделях и провайдерах.

    Пример использования:
        registry = LLMProviderRegistry()
        registry.register("openai", lambda: OpenAIProvider())
        registry.register("anthropic", lambda: AnthropicProvider())

        provider = await registry.get_provider("openai")
        models = registry.list_all_models()
    """

    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}
        self._instances: dict[str, LLMProvider] = {}
        self._provider_info: dict[str, ProviderInfo] = {}

    def register(
        self,
        provider_id: str,
        factory: ProviderFactory,
        info: ProviderInfo | None = None,
    ) -> None:
        """Зарегистрировать провайдер.

        Args:
            provider_id: Уникальный идентификатор провайдера
            factory: Factory-функция для создания экземпляра
            info: Метаданные провайдера (опционально)
        """
        self._factories[provider_id] = factory
        if info:
            self._provider_info[provider_id] = info
        logger.info("provider registered", provider_id=provider_id)

    def is_registered(self, provider_id: str) -> bool:
        """Проверить, зарегистрирован ли провайдер.

        Args:
            provider_id: Идентификатор провайдера

        Returns:
            True если провайдер зарегистрирован
        """
        return provider_id in self._factories

    def get_registered_providers(self) -> list[str]:
        """Получить список зарегистрированных провайдеров.

        Returns:
            Список идентификаторов провайдеров
        """
        return list(self._factories.keys())

    async def get_provider(self, provider_id: str) -> LLMProvider:
        """Получить экземпляр провайдера.

        Создаёт провайдер лениво при первом обращении.
        Повторные вызовы возвращают кэшированный экземпляр.

        Args:
            provider_id: Идентификатор провайдера

        Returns:
            Экземпляр провайдера

        Raises:
            ProviderNotFoundError: Если провайдер не зарегистрирован
        """
        if provider_id not in self._factories:
            raise ProviderNotFoundError(provider_id)

        # Вернуть кэшированный экземпляр если есть
        if provider_id in self._instances:
            return self._instances[provider_id]

        # Создать новый экземпляр
        factory = self._factories[provider_id]
        instance = factory()
        self._instances[provider_id] = instance

        logger.info("provider instance created", provider_id=provider_id)
        return instance

    async def create_provider(
        self,
        provider_id: str,
        config: LLMConfig,
    ) -> LLMProvider:
        """Создать и инициализировать провайдер.

        Args:
            provider_id: Идентификатор провайдера
            config: Конфигурация для инициализации

        Returns:
            Инициализированный провайдер

        Raises:
            ProviderNotFoundError: Если провайдер не зарегистрирован
        """
        provider = await self.get_provider(provider_id)
        try:
            await provider.initialize(config)
            logger.info("provider initialized", provider_id=provider_id, model=config.model)

            # Emit event
            await event_bus.publish(
                ProviderInitialized(
                    provider_id=provider_id,
                    model=config.model,
                    base_url=config.base_url,
                )
            )

            return provider
        except Exception as e:
            # Emit failure event
            await event_bus.publish(
                ProviderFailed(
                    provider_id=provider_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
            )
            raise

    def list_all_models(self) -> list[ModelInfo]:
        """Получить список всех доступных моделей.

        Returns:
            Список всех моделей от всех зарегистрированных провайдеров
        """
        models: list[ModelInfo] = []
        for provider_id, info in self._provider_info.items():
            models.extend(info.models)
        return models

    def get_provider_info(self, provider_id: str) -> ProviderInfo:
        """Получить информацию о провайдере.

        Args:
            provider_id: Идентификатор провайдера

        Returns:
            Метаданные провайдера

        Raises:
            ProviderNotFoundError: Если провайдер не зарегистрирован
        """
        if provider_id not in self._provider_info:
            raise ProviderNotFoundError(provider_id)
        return self._provider_info[provider_id]

    def get_model_info(self, provider_id: str, model_id: str) -> ModelInfo:
        """Получить информацию о конкретной модели.

        Args:
            provider_id: Идентификатор провайдера
            model_id: Идентификатор модели

        Returns:
            Метаданные модели

        Raises:
            ProviderNotFoundError: Если провайдер не зарегистрирован
            ModelNotFoundError: Если модель не найдена
        """
        info = self.get_provider_info(provider_id)
        for model in info.models:
            if model.id == model_id:
                return model
        raise ModelNotFoundError(model_id=model_id, provider_id=provider_id)

    def update_provider_info(self, provider_id: str, info: ProviderInfo) -> None:
        """Обновить информацию о провайдере.

        Args:
            provider_id: Идентификатор провайдера
            info: Новые метаданные провайдера
        """
        self._provider_info[provider_id] = info
        logger.debug("provider info updated", provider_id=provider_id)

    def clear(self) -> None:
        """Очистить реестр."""
        self._factories.clear()
        self._instances.clear()
        self._provider_info.clear()
        logger.info("registry cleared")
