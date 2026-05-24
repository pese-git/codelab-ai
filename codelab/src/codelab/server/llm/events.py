"""Система событий для LLM провайдеров.

Определяет ProviderEventBus — простой event bus для публикации и подписки
на события провайдеров. В MVP события только логируются, в будущем можно
добавить WebSocket notifications клиенту.

События:
- ProviderInitialized: провайдер успешно инициализирован
- ProviderFailed: провайдер упал при инициализации или запросе
- ModelsUpdated: список доступных моделей обновлён
- FallbackTriggered: активирован fallback на другой провайдер
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Protocol

import structlog

logger = structlog.get_logger()


@dataclass
class ProviderEvent:
    """Базовое событие провайдера."""

    provider_id: str
    timestamp: float = field(default_factory=time.monotonic)


@dataclass
class ProviderInitialized(ProviderEvent):
    """Провайдер успешно инициализирован."""

    model: str | None = None
    base_url: str | None = None


@dataclass
class ProviderFailed(ProviderEvent):
    """Провайдер упал при инициализации или запросе."""

    error: str = ""
    error_type: str | None = None


@dataclass
class ModelsUpdated(ProviderEvent):
    """Список доступных моделей обновлён."""

    models: list[str] = field(default_factory=list)


@dataclass
class FallbackTriggered(ProviderEvent):
    """Активирован fallback на другой провайдер."""

    from_provider: str = ""
    to_provider: str = ""
    reason: str = ""


class EventListener(Protocol):
    """Протокол слушателя событий."""

    async def __call__(self, event: ProviderEvent) -> None:
        """Обработать событие."""
        ...


class ProviderEventBus:
    """Шина событий для LLM провайдеров.

    Позволяет подписываться на события провайдеров и публиковать их.
    В MVP все события логируются. Подписчики получают события асинхронно.
    """

    def __init__(self) -> None:
        self._listeners: dict[type[ProviderEvent], list[EventListener]] = {}
        self._global_listeners: list[EventListener] = []

    def subscribe(
        self,
        event_type: type[ProviderEvent],
        listener: EventListener,
    ) -> None:
        """Подписаться на определённый тип событий.

        Args:
            event_type: Тип события для подписки
            listener: Функция-обработчик
        """
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        self._listeners[event_type].append(listener)

    def subscribe_all(self, listener: EventListener) -> None:
        """Подписаться на все события.

        Args:
            listener: Функция-обработчик
        """
        self._global_listeners.append(listener)

    async def publish(self, event: ProviderEvent) -> None:
        """Опубликовать событие.

        Логирует событие и уведомляет всех подписчиков.

        Args:
            event: Событие для публикации
        """
        self._log_event(event)

        # Уведомить глобальных подписчиков
        for listener in self._global_listeners:
            try:
                await listener(event)
            except Exception as e:
                logger.error(
                    "event listener error",
                    event_type=type(event).__name__,
                    error=str(e),
                )

        # Уведомить специфичных подписчиков
        event_type = type(event)
        if event_type in self._listeners:
            for listener in self._listeners[event_type]:
                try:
                    await listener(event)
                except Exception as e:
                    logger.error(
                        "event listener error",
                        event_type=event_type.__name__,
                        error=str(e),
                    )

    def _log_event(self, event: ProviderEvent) -> None:
        """Логировать событие."""
        event_type = type(event).__name__

        if isinstance(event, ProviderInitialized):
            logger.info(
                "provider initialized",
                provider_id=event.provider_id,
                model=event.model,
            )
        elif isinstance(event, ProviderFailed):
            logger.error(
                "provider failed",
                provider_id=event.provider_id,
                error=event.error,
                error_type=event.error_type,
            )
        elif isinstance(event, ModelsUpdated):
            logger.info(
                "models updated",
                provider_id=event.provider_id,
                models_count=len(event.models),
            )
        elif isinstance(event, FallbackTriggered):
            logger.warning(
                "fallback triggered",
                from_provider=event.from_provider,
                to_provider=event.to_provider,
                reason=event.reason,
            )
        else:
            logger.debug(
                "provider event",
                event_type=event_type,
                provider_id=event.provider_id,
            )


# Глобальный экземпляр event bus
event_bus = ProviderEventBus()
