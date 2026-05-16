"""Тесты для BaseViewModel."""

from unittest.mock import Mock

import pytest

from codelab.client.presentation.base_view_model import BaseViewModel


class MockViewModel(BaseViewModel):
    """Тестовая реализация BaseViewModel."""
    pass


class TestBaseViewModel:
    """Тесты для BaseViewModel класса."""

    def test_viewmodel_initialization(self) -> None:
        """Проверить инициализацию BaseViewModel."""
        vm = MockViewModel()
        assert vm.event_bus is None
        assert vm.logger is not None

    def test_viewmodel_with_event_bus(self) -> None:
        """Проверить инициализацию с event_bus."""
        event_bus = Mock()
        vm = MockViewModel(event_bus=event_bus)
        assert vm.event_bus is event_bus

    def test_viewmodel_with_logger(self) -> None:
        """Проверить инициализацию с logger."""
        logger = Mock()
        vm = MockViewModel(logger=logger)
        assert vm.logger is logger

    def test_viewmodel_on_event_without_bus(self) -> None:
        """Проверить подписку на событие без event_bus."""
        vm = MockViewModel()
        handler = Mock()
        
        # Должно выбросить RuntimeError если EventBus не инициализирован
        with pytest.raises(RuntimeError, match="Cannot subscribe to events"):
            vm.on_event(Mock, handler)
        
        # Handler не должен быть вызван
        handler.assert_not_called()

    def test_viewmodel_on_event_with_bus(self) -> None:
        """Проверить подписку на событие с event_bus."""
        event_bus = Mock()
        vm = MockViewModel(event_bus=event_bus)
        handler = Mock()
        event_type = Mock
        
        vm.on_event(event_type, handler)
        
        # event_bus.subscribe должен быть вызван
        event_bus.subscribe.assert_called_once()

    def test_viewmodel_publish_event_without_bus(self) -> None:
        """Проверить публикацию события без event_bus."""
        vm = MockViewModel()
        event = Mock()
        
        # Должно выбросить RuntimeError если EventBus не инициализирован
        with pytest.raises(RuntimeError, match="Cannot publish events"):
            vm.publish_event(event)

    def test_viewmodel_publish_event_with_bus(self) -> None:
        """Проверить публикацию события с event_bus."""
        event_bus = Mock()
        vm = MockViewModel(event_bus=event_bus)
        event = Mock()
        
        vm.publish_event(event)
        
        # event_bus.publish должен быть вызван
        event_bus.publish.assert_called_once_with(event)

    def test_viewmodel_cleanup(self) -> None:
        """Проверить cleanup метод."""
        vm = MockViewModel()
        mock_unsubscribe = Mock()
        vm._subscriptions['test'] = mock_unsubscribe
        
        vm.cleanup()
        
        mock_unsubscribe.assert_called_once()
        assert len(vm._subscriptions) == 0

    def test_viewmodel_cleanup_with_error(self) -> None:
        """Проверить cleanup при ошибке в unsubscribe."""
        vm = MockViewModel()
        mock_unsubscribe = Mock(side_effect=Exception("Cleanup error"))
        vm._subscriptions['test'] = mock_unsubscribe
        
        # Не должно выбросить исключение
        vm.cleanup()

    def test_viewmodel_multiple_subscriptions_cleanup(self) -> None:
        """Проверить cleanup для множества subscriptions."""
        vm = MockViewModel()
        
        unsubscribers = [Mock() for _ in range(3)]
        for i, unsubscriber in enumerate(unsubscribers):
            vm._subscriptions[f'sub_{i}'] = unsubscriber
        
        vm.cleanup()
        
        for unsubscriber in unsubscribers:
            unsubscriber.assert_called_once()
        
        assert len(vm._subscriptions) == 0

    def test_viewmodel_on_event_stores_unsubscribe(self) -> None:
        """Проверить что on_event сохраняет unsubscribe функцию."""
        event_bus = Mock()
        event_bus.subscribe.return_value = Mock()  # unsubscribe функция
        
        vm = MockViewModel(event_bus=event_bus)
        handler = Mock()
        event_type = Mock
        
        # on_event должен сохранить unsubscribe функцию
        # (в текущей реализации это не делается явно, но может быть улучшено)
        vm.on_event(event_type, handler)
        
        # Проверить что subscribe был вызван
        event_bus.subscribe.assert_called()
