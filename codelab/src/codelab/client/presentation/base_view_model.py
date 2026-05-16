"""Базовый класс для всех ViewModels.

BaseViewModel предоставляет механизмы для интеграции с EventBus,
логирования и управления lifecycle.
"""

import asyncio
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from codelab.client.domain.events import DomainEvent

# Типы для событий (из Phase 3)
try:
    from codelab.client.domain.events import DomainEvent
except ImportError:
    # Fallback если domain модуль еще не доступен
    DomainEvent: Any = Any

import structlog


class BaseViewModel:
    """Базовый класс для всех ViewModels.

    Предоставляет:
    - Интеграцию с EventBus для реактивных обновлений
    - Структурированное логирование
    - Управление subscriptions на события

    Все ViewModels должны наследоваться от этого класса.

    Пример:
        >>> class MyViewModel(BaseViewModel):
        ...     def __init__(self, event_bus=None):
        ...         super().__init__(event_bus)
        ...         self.data = Observable("initial")
        ...         self.on_event(SomeEvent, self._handle_event)
        ...
        ...     def _handle_event(self, event):
        ...         self.data.value = event.data
    """

    def __init__(self, event_bus: Any | None = None, logger: Any | None = None) -> None:
        """Инициализировать ViewModel.

        Args:
            event_bus: Шина событий (EventBus) для публикации/подписки на события
            logger: Logger для структурированного логирования
        """
        self.event_bus = event_bus
        self.logger = logger or structlog.get_logger()
        # Храним unsubscribe функции для очистки при уничтожении
        self._subscriptions: dict[str, Callable[[], None]] = {}
        self.logger.debug("ViewModel initialized", vm_class=self.__class__.__name__)

    def on_event(
        self,
        event_type: type[DomainEvent],
        handler: Callable[[DomainEvent], None],
    ) -> None:
        """Подписаться на доменное событие.

        Когда событие опубликуется в EventBus, handler будет вызван.

        Args:
            event_type: Тип события для подписки
            handler: Функция-обработчик события

        Raises:
            RuntimeError: Если EventBus не инициализирован

        Пример:
            >>> self.on_event(SessionCreatedEvent, self._on_session_created)
        """
        if not self.event_bus:
            msg = (
                f"Cannot subscribe to events in {self.__class__.__name__}: "
                "EventBus is not initialized. "
                "Make sure EventBus is passed to the ViewModel during initialization."
            )
            self.logger.error("event_bus_not_initialized", vm_class=self.__class__.__name__)
            raise RuntimeError(msg)

        try:
            # EventBus.subscribe регистрирует обработчик события
            self.event_bus.subscribe(event_type, handler)
            self.logger.debug(
                "subscribed_to_event",
                event_type=event_type.__name__,
                handler=getattr(handler, "__name__", str(handler)),
            )
        except Exception as e:
            self.logger.exception(
                "error_subscribing_to_event",
                event_type=event_type.__name__,
                error=str(e),
            )
            raise

    def publish_event(self, event: DomainEvent) -> None:
        """Опубликовать доменное событие.

        Событие будет отправлено всем подписанным observers.

        Args:
            event: Событие для публикации

        Raises:
            RuntimeError: Если EventBus не инициализирован

        Пример:
            >>> event = SessionCreatedEvent(...)
            >>> self.publish_event(event)
        """
        if not self.event_bus:
            msg = (
                f"Cannot publish events from {self.__class__.__name__}: "
                "EventBus is not initialized. "
                "Make sure EventBus is passed to the ViewModel during initialization."
            )
            self.logger.error("event_bus_not_initialized", vm_class=self.__class__.__name__)
            raise RuntimeError(msg)

        try:
            publish_result = self.event_bus.publish(event)
            if asyncio.iscoroutine(publish_result):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(publish_result)
                except RuntimeError:
                    asyncio.run(publish_result)
            self.logger.debug(
                "event_published",
                event_type=event.__class__.__name__,
                aggregate_id=getattr(event, "aggregate_id", "unknown"),
            )
        except Exception as e:
            self.logger.exception(
                "error_publishing_event",
                event_type=event.__class__.__name__,
                error=str(e),
            )
            raise

    def cleanup(self) -> None:
        """Очистить ресурсы при уничтожении ViewModel.

        Должен быть вызван перед удалением ViewModel чтобы
        избежать утечек памяти от невычищенных subscriptions.

        Пример:
            >>> vm = MyViewModel(event_bus)
            >>> # ... использовать vm ...
            >>> vm.cleanup()  # Очистить перед удалением
        """
        for unsubscribe_fn in self._subscriptions.values():
            try:
                unsubscribe_fn()
            except Exception as e:
                self.logger.exception(
                    "Error unsubscribing",
                    error=str(e),
                )
        self._subscriptions.clear()
        self.logger.debug("ViewModel cleaned up", vm_class=self.__class__.__name__)

    def __del__(self) -> None:
        """Автоматически очистить при удалении объекта."""
        with suppress(Exception):
            # Не логируем ошибки в __del__ так как logger может быть уже удален
            self.cleanup()
