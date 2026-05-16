"""Plugin System - базовые классы и интерфейсы для плагинов.

Позволяет расширять функционал ACP-клиента через плагины без изменения ядра.
Плагины могут добавлять handlers, обработчики событий и другой функционал.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from codelab.client.domain.events import DomainEvent
    from codelab.client.infrastructure.handler_registry import Handler
    from codelab.client.infrastructure.plugins.context import PluginContext


class Plugin(ABC):
    """Базовый класс для всех плагинов.

    Плагин - это модуль, который расширяет функционал ACP-клиента.
    Плагины инициализируются при запуске и могут подписываться на события,
    регистрировать handlers и выполнять другие действия.

    Пример:
        class MyPlugin(Plugin):
            @property
            def name(self) -> str:
                return "my_plugin"

            @property
            def version(self) -> str:
                return "1.0.0"

            @property
            def description(self) -> str:
                return "My awesome plugin"

            async def initialize(self, context: PluginContext) -> None:
                # Инициализировать плагин
                pass

            async def shutdown(self) -> None:
                # Очистить ресурсы
                pass
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Имя плагина (уникальный идентификатор).

        Returns:
            Название плагина (e.g., "auth_plugin", "logging_plugin")
        """
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        """Версия плагина в формате семантического версионирования.

        Returns:
            Версия (e.g., "1.0.0", "1.2.3-beta")
        """
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Описание того, что делает плагин.

        Returns:
            Описание функционала плагина
        """
        pass

    @abstractmethod
    async def initialize(self, context: PluginContext) -> None:
        """Инициализировать плагин.

        Вызывается при загрузке плагина. Здесь плагин может:
        - Подписаться на события через event_bus
        - Зарегистрировать handlers
        - Инициализировать ресурсы
        - Установить конфигурацию

        Args:
            context: PluginContext с доступом к DI контейнеру,
                    EventBus, HandlerRegistry и логгеру

        Raises:
            Exception: Если инициализация не удалась
        """
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Корректно завершить работу плагина.

        Вызывается при выключении приложения или выгрузке плагина.
        Здесь плагин должен:
        - Освободить ресурсы
        - Отписаться от событий (опционально)
        - Сохранить состояние

        Raises:
            Exception: Если завершение не удалось
        """
        pass


class HandlerPlugin(Plugin):
    """Плагин, который регистрирует handlers (permission, filesystem, terminal).

    HandlerPlugin позволяет добавлять обработчики для различных операций,
    таких как работа с файловой системой, терминалом или разрешениями.

    Пример:
        class MyHandlerPlugin(HandlerPlugin):
            def get_handlers(self) -> dict[str, Handler]:
                return {
                    "filesystem": MyFileSystemHandler(),
                    "terminal": MyTerminalHandler(),
                }
    """

    @abstractmethod
    def get_handlers(self) -> dict[str, Handler]:
        """Вернуть словарь handlers для регистрации.

        Returns:
            Словарь {handler_name: handler_instance}
            Например: {"permission": PermissionHandler(), ...}
        """
        pass


class EventPlugin(Plugin):
    """Плагин, который добавляет обработчики доменных событий.

    EventPlugin позволяет реагировать на события в системе,
    такие как создание сессии, начало prompt turn и т.д.

    Пример:
        class LoggingEventPlugin(EventPlugin):
            def get_event_handlers(self) -> dict[type[DomainEvent], Callable]:
                return {
                    SessionCreatedEvent: self._on_session_created,
                    PromptCompletedEvent: self._on_prompt_completed,
                }

            async def _on_session_created(
                self, event: SessionCreatedEvent
            ) -> None:
                logger.info("session_created", session_id=event.session_id)
    """

    @abstractmethod
    def get_event_handlers(
        self,
    ) -> dict[type[DomainEvent], Any]:
        """Вернуть словарь обработчиков событий.

        Returns:
            Словарь {EventClass: handler_function}
            Например: {SessionCreatedEvent: on_session_created, ...}
        """
        pass


class ConfigurablePlugin(Plugin):
    """Плагин, который имеет конфигурацию.

    ConfigurablePlugin позволяет плагинам иметь параметры конфигурации,
    которые могут быть установлены при инициализации.

    Пример:
        class ConfiguredPlugin(ConfigurablePlugin):
            def get_default_config(self) -> dict[str, Any]:
                return {
                    "debug": False,
                    "timeout": 30,
                }

            def set_config(self, config: dict[str, Any]) -> None:
                self.debug = config.get("debug", False)
                self.timeout = config.get("timeout", 30)
    """

    @abstractmethod
    def get_default_config(self) -> dict[str, Any]:
        """Вернуть конфигурацию по умолчанию.

        Returns:
            Словарь с параметрами конфигурации
        """
        pass

    @abstractmethod
    def set_config(self, config: dict[str, Any]) -> None:
        """Установить конфигурацию плагина.

        Args:
            config: Словарь с параметрами конфигурации
        """
        pass


class PluginError(Exception):
    """Базовый класс для ошибок плагинов."""

    pass


class PluginLoadError(PluginError):
    """Ошибка при загрузке плагина."""

    pass


class PluginInitializationError(PluginError):
    """Ошибка при инициализации плагина."""

    pass


class PluginNotFoundError(PluginError):
    """Плагин не найден."""

    pass
