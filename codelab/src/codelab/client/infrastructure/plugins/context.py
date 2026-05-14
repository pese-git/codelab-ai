"""Plugin Context - контекст выполнения для плагинов.

PluginContext предоставляет плагинам доступ к основным компонентам системы:
DI контейнеру (dishka), EventBus, HandlerRegistry и логгеру.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dishka import Container

    from codelab.client.infrastructure.events.bus import EventBus
    from codelab.client.infrastructure.handler_registry import HandlerRegistry


@dataclass(frozen=True)
class PluginContext:
    """Контекст выполнения плагина.

    Предоставляет плагину доступ к ключевым компонентам приложения,
    необходимым для инициализации и работы плагина.

    Attributes:
        container: dishka Container для разрешения зависимостей
        event_bus: EventBus для подписки на события
        handler_registry: HandlerRegistry для регистрации handlers
        logger: structlog Logger для логирования

    Пример:
        async def initialize(self, context: PluginContext) -> None:
            # Получить сервис из DI контейнера
            service = context.container.get(MyService)

            # Подписаться на событие
            context.event_bus.subscribe(SessionCreatedEvent, self._on_session_created)

            # Зарегистрировать handler
            context.handler_registry.register("my_handler", MyHandler())
    """

    # Контейнер зависимостей для разрешения сервисов и других компонентов
    container: Container

    # Шина событий для подписки и публикации доменных событий
    event_bus: EventBus

    # Реестр обработчиков для регистрации новых handlers
    handler_registry: HandlerRegistry

    # Структурированный логгер для плагина
    logger: Any
