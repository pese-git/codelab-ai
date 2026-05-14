"""Tests for Plugin System - PluginManager and Plugin classes.

Comprehensive tests for plugin loading, initialization, and lifecycle management.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest
from dishka import Provider, Scope, make_container

from codelab.client.domain.events import SessionCreatedEvent
from codelab.client.infrastructure.events.bus import EventBus
from codelab.client.infrastructure.handler_registry import HandlerRegistry
from codelab.client.infrastructure.plugins.base import (
    EventPlugin,
    HandlerPlugin,
    Plugin,
    PluginInitializationError,
    PluginLoadError,
    PluginNotFoundError,
)
from codelab.client.infrastructure.plugins.context import PluginContext
from codelab.client.infrastructure.plugins.manager import PluginManager


def _make_test_container() -> Any:
    """Создаёт минимальный dishka контейнер для тестов."""

    class TestProvider(Provider):
        scope = Scope.APP

    return make_container(TestProvider())

# ============================================================================
# Mock Plugin Classes for Testing
# ============================================================================


class SimplePlugin(Plugin):
    """Простой тестовый плагин без функционала."""

    def __init__(self) -> None:
        self.initialized = False
        self.shutdown_called = False

    @property
    def name(self) -> str:
        return "simple_plugin"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Simple test plugin"

    async def initialize(self, context: PluginContext) -> None:
        self.initialized = True

    async def shutdown(self) -> None:
        self.shutdown_called = True


class FailingPlugin(Plugin):
    """Плагин, который выбрасывает ошибку при инициализации."""

    @property
    def name(self) -> str:
        return "failing_plugin"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Plugin that fails on init"

    async def initialize(self, context: PluginContext) -> None:
        raise RuntimeError("Initialization failed")

    async def shutdown(self) -> None:
        pass


class MockHandler:
    """Mock handler для тестирования."""

    @property
    def name(self) -> str:
        return "mock_handler"

    async def handle(self, request: dict[str, Any]) -> str | None:
        return "mock_response"


class MockHandlerPlugin(HandlerPlugin):
    """Тестовый плагин, который регистрирует handlers."""

    def __init__(self) -> None:
        self.initialized = False

    @property
    def name(self) -> str:
        return "test_handler_plugin"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Test handler plugin"

    def get_handlers(self) -> dict[str, Any]:
        return {
            "test_handler": MockHandler(),
        }

    async def initialize(self, context: PluginContext) -> None:
        self.initialized = True

    async def shutdown(self) -> None:
        pass


class MockEventPlugin(EventPlugin):
    """Тестовый плагин, который подписывается на события."""

    def __init__(self) -> None:
        self.events_received: list[str] = []
        self.initialized = False

    @property
    def name(self) -> str:
        return "test_event_plugin"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Test event plugin"

    def get_event_handlers(self) -> dict[type[Any], Any]:
        return {
            SessionCreatedEvent: self._on_session_created,
        }

    async def _on_session_created(
        self, event: SessionCreatedEvent
    ) -> None:
        self.events_received.append(f"session_created:{event.session_id}")

    async def initialize(self, context: PluginContext) -> None:
        self.initialized = True

    async def shutdown(self) -> None:
        pass


# ============================================================================
# Tests
# ============================================================================


class TestPluginBasics:
    """Базовые тесты для плагинов."""

    def test_simple_plugin_properties(self) -> None:
        """Тест: простой плагин имеет правильные свойства."""
        plugin = SimplePlugin()

        assert plugin.name == "simple_plugin"
        assert plugin.version == "1.0.0"
        assert plugin.description == "Simple test plugin"

    @pytest.mark.asyncio
    async def test_simple_plugin_lifecycle(self) -> None:
        """Тест: простой плагин может быть инициализирован и завершён."""
        plugin = SimplePlugin()

        assert not plugin.initialized
        assert not plugin.shutdown_called

        # Создать минимальный контекст
        context = PluginContext(
            container=_make_test_container(),
            event_bus=EventBus(),
            handler_registry=HandlerRegistry(),
            logger=None,
        )

        await plugin.initialize(context)
        assert plugin.initialized

        await plugin.shutdown()
        assert plugin.shutdown_called


class TestPluginManagerBasics:
    """Базовые тесты для PluginManager."""

    def test_plugin_manager_creation(self) -> None:
        """Тест: PluginManager успешно создаётся."""
        context = PluginContext(
            container=_make_test_container(),
            event_bus=EventBus(),
            handler_registry=HandlerRegistry(),
            logger=None,
        )
        manager = PluginManager(context)

        assert manager is not None

    def test_register_plugin(self) -> None:
        """Тест: можно зарегистрировать плагин."""
        context = PluginContext(
            container=_make_test_container(),
            event_bus=EventBus(),
            handler_registry=HandlerRegistry(),
            logger=None,
        )
        manager = PluginManager(context)
        plugin = SimplePlugin()

        manager.register_plugin(plugin)

        assert manager.get_plugin("simple_plugin") is plugin

    def test_register_duplicate_plugin_raises_error(self) -> None:
        """Тест: попытка зарегистрировать плагин с таким же именем вызывает ошибку."""
        context = PluginContext(
            container=_make_test_container(),
            event_bus=EventBus(),
            handler_registry=HandlerRegistry(),
            logger=None,
        )
        manager = PluginManager(context)
        plugin1 = SimplePlugin()
        plugin2 = SimplePlugin()

        manager.register_plugin(plugin1)

        with pytest.raises(ValueError, match="already registered"):
            manager.register_plugin(plugin2)

    def test_list_plugins(self) -> None:
        """Тест: можно получить список всех плагинов."""
        context = PluginContext(
            container=_make_test_container(),
            event_bus=EventBus(),
            handler_registry=HandlerRegistry(),
            logger=None,
        )
        manager = PluginManager(context)

        plugin1 = SimplePlugin()
        plugin2 = MockHandlerPlugin()

        manager.register_plugin(plugin1)
        manager.register_plugin(plugin2)

        plugins = manager.list_plugins()

        assert len(plugins) == 2
        assert ("simple_plugin", "1.0.0", "Simple test plugin") in plugins
        assert ("test_handler_plugin", "1.0.0", "Test handler plugin") in plugins


class TestPluginInitialization:
    """Тесты инициализации плагинов."""

    @pytest.mark.asyncio
    async def test_initialize_single_plugin(self) -> None:
        """Тест: можно инициализировать один плагин."""
        context = PluginContext(
            container=_make_test_container(),
            event_bus=EventBus(),
            handler_registry=HandlerRegistry(),
            logger=None,
        )
        manager = PluginManager(context)
        plugin = SimplePlugin()

        manager.register_plugin(plugin)
        await manager.initialize_plugin("simple_plugin")

        assert plugin.initialized
        assert manager.is_plugin_initialized("simple_plugin")

    @pytest.mark.asyncio
    async def test_initialize_all_plugins(self) -> None:
        """Тест: можно инициализировать все плагины сразу."""
        context = PluginContext(
            container=_make_test_container(),
            event_bus=EventBus(),
            handler_registry=HandlerRegistry(),
            logger=None,
        )
        manager = PluginManager(context)

        plugin1 = SimplePlugin()
        plugin2 = MockHandlerPlugin()

        manager.register_plugin(plugin1)
        manager.register_plugin(plugin2)

        await manager.initialize_all()

        assert plugin1.initialized
        assert plugin2.initialized
        assert manager.is_plugin_initialized("simple_plugin")
        assert manager.is_plugin_initialized("test_handler_plugin")

    @pytest.mark.asyncio
    async def test_initialize_nonexistent_plugin_raises_error(self) -> None:
        """Тест: попытка инициализировать несуществующий плагин вызывает ошибку."""
        context = PluginContext(
            container=_make_test_container(),
            event_bus=EventBus(),
            handler_registry=HandlerRegistry(),
            logger=None,
        )
        manager = PluginManager(context)

        with pytest.raises(PluginNotFoundError):
            await manager.initialize_plugin("nonexistent")

    @pytest.mark.asyncio
    async def test_failing_plugin_raises_initialization_error(self) -> None:
        """Тест: ошибка в инициализации плагина вызывает PluginInitializationError."""
        context = PluginContext(
            container=_make_test_container(),
            event_bus=EventBus(),
            handler_registry=HandlerRegistry(),
            logger=None,
        )
        manager = PluginManager(context)
        plugin = FailingPlugin()

        manager.register_plugin(plugin)

        with pytest.raises(PluginInitializationError):
            await manager.initialize_plugin("failing_plugin")


class TestHandlerPluginIntegration:
    """Тесты интеграции HandlerPlugin с HandlerRegistry."""

    @pytest.mark.asyncio
    async def test_handler_plugin_registers_handlers(self) -> None:
        """Тест: HandlerPlugin регистрирует handlers в HandlerRegistry."""
        handler_registry = HandlerRegistry()
        context = PluginContext(
            container=_make_test_container(),
            event_bus=EventBus(),
            handler_registry=handler_registry,
            logger=None,
        )
        manager = PluginManager(context)
        plugin = MockHandlerPlugin()

        manager.register_plugin(plugin)
        await manager.initialize_plugin("test_handler_plugin")

        # Проверить, что handler зарегистрирован
        handler = handler_registry.get("test_handler")
        assert handler is not None
        assert handler.name == "mock_handler"


class TestEventPluginIntegration:
    """Тесты интеграции EventPlugin с EventBus."""

    @pytest.mark.asyncio
    async def test_event_plugin_subscribes_to_events(self) -> None:
        """Тест: EventPlugin подписывается на события при инициализации."""
        event_bus = EventBus()
        context = PluginContext(
            container=_make_test_container(),
            event_bus=event_bus,
            handler_registry=HandlerRegistry(),
            logger=None,
        )
        manager = PluginManager(context)
        plugin = MockEventPlugin()

        manager.register_plugin(plugin)
        await manager.initialize_plugin("test_event_plugin")

        # Проверить, что EventBus имеет подписчика
        assert event_bus.has_subscribers(SessionCreatedEvent)

        # Опубликовать событие и проверить, что плагин его получил
        event = SessionCreatedEvent(
            aggregate_id="session1",
            occurred_at=datetime.now(UTC),
            session_id="session1",
            server_host="localhost",
            server_port=8000,
        )
        await event_bus.publish(event)

        assert "session_created:session1" in plugin.events_received


class TestPluginShutdown:
    """Тесты завершения работы плагинов."""

    @pytest.mark.asyncio
    async def test_shutdown_single_plugin(self) -> None:
        """Тест: можно завершить один плагин."""
        context = PluginContext(
            container=_make_test_container(),
            event_bus=EventBus(),
            handler_registry=HandlerRegistry(),
            logger=None,
        )
        manager = PluginManager(context)
        plugin = SimplePlugin()

        manager.register_plugin(plugin)
        await manager.initialize_plugin("simple_plugin")

        assert manager.is_plugin_initialized("simple_plugin")

        await manager.shutdown_plugin("simple_plugin")

        assert not manager.is_plugin_initialized("simple_plugin")
        assert plugin.shutdown_called

    @pytest.mark.asyncio
    async def test_shutdown_all_plugins(self) -> None:
        """Тест: можно завершить все плагины сразу."""
        context = PluginContext(
            container=_make_test_container(),
            event_bus=EventBus(),
            handler_registry=HandlerRegistry(),
            logger=None,
        )
        manager = PluginManager(context)

        plugin1 = SimplePlugin()
        plugin2 = MockHandlerPlugin()

        manager.register_plugin(plugin1)
        manager.register_plugin(plugin2)

        await manager.initialize_all()

        assert manager.is_plugin_initialized("simple_plugin")
        assert manager.is_plugin_initialized("test_handler_plugin")

        await manager.shutdown_all()

        assert not manager.is_plugin_initialized("simple_plugin")
        assert not manager.is_plugin_initialized("test_handler_plugin")
        assert plugin1.shutdown_called

    @pytest.mark.asyncio
    async def test_shutdown_nonexistent_plugin_raises_error(self) -> None:
        """Тест: попытка завершить несуществующий плагин вызывает ошибку."""
        context = PluginContext(
            container=_make_test_container(),
            event_bus=EventBus(),
            handler_registry=HandlerRegistry(),
            logger=None,
        )
        manager = PluginManager(context)

        with pytest.raises(PluginNotFoundError):
            await manager.shutdown_plugin("nonexistent")


class TestPluginLoading:
    """Тесты загрузки плагинов из файлов."""

    def test_load_plugin_from_file(self) -> None:
        """Тест: можно загрузить плагин из файла."""
        with TemporaryDirectory() as tmpdir:
            # Создать файл плагина
            plugin_file = Path(tmpdir) / "test_plugin.py"
            plugin_file.write_text(
                """
from codelab.client.infrastructure.plugins.base import Plugin
from codelab.client.infrastructure.plugins.context import PluginContext

class MyPlugin(Plugin):
    @property
    def name(self):
        return "my_plugin"
    
    @property
    def version(self):
        return "1.0.0"
    
    @property
    def description(self):
        return "My test plugin"
    
    async def initialize(self, context: PluginContext):
        pass
    
    async def shutdown(self):
        pass
"""
            )

            context = PluginContext(
                container=_make_test_container(),
                event_bus=EventBus(),
                handler_registry=HandlerRegistry(),
                logger=None,
            )
            manager = PluginManager(context)

            plugin = manager.load_plugin(plugin_file)

            assert plugin.name == "my_plugin"
            assert plugin.version == "1.0.0"

    def test_load_plugin_nonexistent_file_raises_error(self) -> None:
        """Тест: попытка загрузить несуществующий файл вызывает ошибку."""
        context = PluginContext(
            container=_make_test_container(),
            event_bus=EventBus(),
            handler_registry=HandlerRegistry(),
            logger=None,
        )
        manager = PluginManager(context)

        with pytest.raises(FileNotFoundError):
            manager.load_plugin(Path("/nonexistent/plugin.py"))

    def test_load_plugin_no_plugin_class_raises_error(self) -> None:
        """Тест: загрузка файла без Plugin класса вызывает ошибку."""
        with TemporaryDirectory() as tmpdir:
            plugin_file = Path(tmpdir) / "bad_plugin.py"
            plugin_file.write_text("# No Plugin class here\n")

            context = PluginContext(
                container=_make_test_container(),
                event_bus=EventBus(),
                handler_registry=HandlerRegistry(),
                logger=None,
            )
            manager = PluginManager(context)

            with pytest.raises(PluginLoadError, match="No Plugin class found"):
                manager.load_plugin(plugin_file)

    def test_load_plugin_with_multiple_plugin_classes_raises_error(
        self,
    ) -> None:
        """Тест: загрузка файла с несколькими Plugin классами вызывает ошибку."""
        with TemporaryDirectory() as tmpdir:
            plugin_file = Path(tmpdir) / "multi_plugin.py"
            plugin_file.write_text(
                """
from codelab.client.infrastructure.plugins.base import Plugin
from codelab.client.infrastructure.plugins.context import PluginContext

class FirstPlugin(Plugin):
    @property
    def name(self):
        return "first"
    
    @property
    def version(self):
        return "1.0.0"
    
    @property
    def description(self):
        return "First"
    
    async def initialize(self, context: PluginContext):
        pass
    
    async def shutdown(self):
        pass

class SecondPlugin(Plugin):
    @property
    def name(self):
        return "second"
    
    @property
    def version(self):
        return "1.0.0"
    
    @property
    def description(self):
        return "Second"
    
    async def initialize(self, context: PluginContext):
        pass
    
    async def shutdown(self):
        pass
"""
            )

            context = PluginContext(
                container=_make_test_container(),
                event_bus=EventBus(),
                handler_registry=HandlerRegistry(),
                logger=None,
            )
            manager = PluginManager(context)

            with pytest.raises(
                PluginLoadError, match="Multiple Plugin classes found"
            ):
                manager.load_plugin(plugin_file)
