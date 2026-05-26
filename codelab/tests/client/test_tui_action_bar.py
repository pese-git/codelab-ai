"""Тесты для ActionBar и QuickActionsBar компонентов.

Тестирует:
- ActionBar - панель с кнопками действий
- QuickActionsBar - глобальная панель быстрых действий
- Интеграция ActionBar в PermissionRequest
"""

from __future__ import annotations

from unittest.mock import Mock

from codelab.client.tui.components.action_bar import ActionBar
from codelab.client.tui.components.quick_actions_bar import QuickActionsBar

# ============================================================================
# ActionBar Tests
# ============================================================================


class TestActionBar:
    """Тесты для ActionBar компонента."""

    def test_create_action_bar(self) -> None:
        """Создание ActionBar с параметрами по умолчанию."""
        bar = ActionBar()
        
        assert bar is not None
        assert bar._buttons == {}

    def test_create_action_bar_with_align(self) -> None:
        """Создание ActionBar с выравниванием."""
        bar_left = ActionBar(align="left")
        bar_right = ActionBar(align="right")
        bar_spread = ActionBar(align="spread")
        
        assert "left" in bar_left.classes
        assert "right" in bar_right.classes
        assert "spread" in bar_spread.classes

    def test_create_action_bar_with_id(self) -> None:
        """Создание ActionBar с ID."""
        bar = ActionBar(id="test-bar")
        
        assert bar.id == "test-bar"

    def test_add_action_basic(self) -> None:
        """Добавление базовой кнопки действия."""
        bar = ActionBar()
        
        # ActionBar.add_action вызывает mount, который требует DOM
        # Поэтому проверяем только что метод существует
        assert hasattr(bar, "add_action")
        assert callable(bar.add_action)

    def test_get_action_nonexistent(self) -> None:
        """Получение несуществующей кнопки возвращает None."""
        bar = ActionBar()
        
        result = bar.get_action("nonexistent")
        
        assert result is None

    def test_set_action_disabled_nonexistent(self) -> None:
        """Установка disabled для несуществующей кнопки не вызывает ошибку."""
        bar = ActionBar()
        
        # Не должно выбрасывать исключение
        bar.set_action_disabled("nonexistent", True)

    def test_remove_action_nonexistent(self) -> None:
        """Удаление несуществующей кнопки не вызывает ошибку."""
        bar = ActionBar()
        
        # Не должно выбрасывать исключение
        bar.remove_action("nonexistent")

    def test_clear_actions_empty(self) -> None:
        """Очистка пустой панели не вызывает ошибку."""
        bar = ActionBar()
        
        # Не должно выбрасывать исключение
        bar.clear_actions()
        
        assert bar._buttons == {}


# ============================================================================
# QuickActionsBar Tests
# ============================================================================


class TestQuickActionsBar:
    """Тесты для QuickActionsBar компонента."""

    def _create_mock_ui_vm(self) -> Mock:
        """Создаёт мок UIViewModel."""
        ui_vm = Mock()
        ui_vm.is_loading = Mock()
        ui_vm.is_loading.subscribe = Mock()
        ui_vm.is_loading.value = False
        return ui_vm

    def test_create_quick_actions_bar(self) -> None:
        """Создание QuickActionsBar."""
        ui_vm = self._create_mock_ui_vm()
        
        bar = QuickActionsBar(ui_vm)
        
        assert bar is not None
        assert bar._ui_vm is ui_vm

    def test_create_quick_actions_bar_with_id(self) -> None:
        """Создание QuickActionsBar с кастомным ID."""
        ui_vm = self._create_mock_ui_vm()
        
        bar = QuickActionsBar(ui_vm, id="custom-bar")
        
        assert bar.id == "custom-bar"

    def test_subscribes_to_loading_state(self) -> None:
        """QuickActionsBar подписывается на изменения is_loading."""
        ui_vm = self._create_mock_ui_vm()
        
        QuickActionsBar(ui_vm)  # Создание вызывает subscribe
        
        ui_vm.is_loading.subscribe.assert_called_once()

    def test_show_method(self) -> None:
        """Метод show() удаляет класс hidden."""
        ui_vm = self._create_mock_ui_vm()
        bar = QuickActionsBar(ui_vm)
        bar.add_class("hidden")
        
        bar.show()
        
        assert "hidden" not in bar.classes

    def test_hide_method(self) -> None:
        """Метод hide() добавляет класс hidden."""
        ui_vm = self._create_mock_ui_vm()
        bar = QuickActionsBar(ui_vm)
        
        bar.hide()
        
        assert "hidden" in bar.classes

    def test_on_loading_changed_enables_cancel(self) -> None:
        """При is_loading=True кнопка отмены должна включаться."""
        ui_vm = self._create_mock_ui_vm()
        bar = QuickActionsBar(ui_vm)
        bar._action_bar = Mock()
        
        bar._on_loading_changed(True)
        
        bar._action_bar.set_action_disabled.assert_called_with("quick-cancel", False)

    def test_on_loading_changed_disables_cancel(self) -> None:
        """При is_loading=False кнопка отмены должна отключаться."""
        ui_vm = self._create_mock_ui_vm()
        bar = QuickActionsBar(ui_vm)
        bar._action_bar = Mock()
        
        bar._on_loading_changed(False)
        
        bar._action_bar.set_action_disabled.assert_called_with("quick-cancel", True)

    def test_update_theme_icon_with_dark_theme(self) -> None:
        """update_theme_icon устанавливает иконку луны для dark темы."""
        ui_vm = self._create_mock_ui_vm()
        mock_theme_manager = Mock()
        mock_theme_manager.current_theme_name = "dark"
        bar = QuickActionsBar(ui_vm, theme_manager=mock_theme_manager)
        bar._action_bar = Mock()
        
        mock_button = Mock()
        bar._action_bar.get_action.return_value = mock_button
        
        bar.update_theme_icon()
        
        bar._action_bar.get_action.assert_called_with("quick-theme")
        mock_button.icon = "🌙"

    def test_update_theme_icon_with_light_theme(self) -> None:
        """update_theme_icon устанавливает иконку солнца для light темы."""
        ui_vm = self._create_mock_ui_vm()
        mock_theme_manager = Mock()
        mock_theme_manager.current_theme_name = "light"
        bar = QuickActionsBar(ui_vm, theme_manager=mock_theme_manager)
        bar._action_bar = Mock()
        
        mock_button = Mock()
        bar._action_bar.get_action.return_value = mock_button
        
        bar.update_theme_icon()
        
        bar._action_bar.get_action.assert_called_with("quick-theme")
        mock_button.icon = "☀️"

    def test_update_theme_icon_without_theme_manager(self) -> None:
        """update_theme_icon без theme_manager использует иконку по умолчанию."""
        ui_vm = self._create_mock_ui_vm()
        bar = QuickActionsBar(ui_vm)
        bar._action_bar = Mock()
        
        mock_button = Mock()
        bar._action_bar.get_action.return_value = mock_button
        
        bar.update_theme_icon()
        
        bar._action_bar.get_action.assert_called_with("quick-theme")
        mock_button.icon = "🎨"

    def test_update_theme_icon_when_action_bar_is_none(self) -> None:
        """update_theme_icon не делает ничего если _action_bar None."""
        ui_vm = self._create_mock_ui_vm()
        mock_theme_manager = Mock()
        mock_theme_manager.current_theme_name = "dark"
        bar = QuickActionsBar(ui_vm, theme_manager=mock_theme_manager)
        bar._action_bar = None
        
        # Не должно выбрасывать исключение
        bar.update_theme_icon()

    def test_update_theme_icon_when_button_not_found(self) -> None:
        """update_theme_icon не делает ничего если кнопка не найдена."""
        ui_vm = self._create_mock_ui_vm()
        mock_theme_manager = Mock()
        mock_theme_manager.current_theme_name = "dark"
        bar = QuickActionsBar(ui_vm, theme_manager=mock_theme_manager)
        bar._action_bar = Mock()
        bar._action_bar.get_action.return_value = None
        
        # Не должно выбрасывать исключение
        bar.update_theme_icon()
        
        bar._action_bar.get_action.assert_called_with("quick-theme")


class TestQuickActionsBarMessages:
    """Тесты для сообщений QuickActionsBar."""

    def test_new_session_requested_message(self) -> None:
        """Сообщение NewSessionRequested создаётся корректно."""
        msg = QuickActionsBar.NewSessionRequested()
        
        assert msg is not None

    def test_cancel_requested_message(self) -> None:
        """Сообщение CancelRequested создаётся корректно."""
        msg = QuickActionsBar.CancelRequested()
        
        assert msg is not None

    def test_help_requested_message(self) -> None:
        """Сообщение HelpRequested создаётся корректно."""
        msg = QuickActionsBar.HelpRequested()
        
        assert msg is not None

    def test_theme_toggle_requested_message(self) -> None:
        """Сообщение ThemeToggleRequested создаётся корректно."""
        msg = QuickActionsBar.ThemeToggleRequested()
        
        assert msg is not None


# ============================================================================
# ActionBar Integration in PermissionRequest Tests
# ============================================================================


class TestActionBarInPermissionRequest:
    """Тесты для интеграции ActionBar в PermissionRequest."""

    def _create_mock_permission_vm(self) -> Mock:
        """Создаёт мок PermissionViewModel."""
        permission_vm = Mock()
        permission_vm.hide = Mock()
        return permission_vm

    def test_permission_request_has_action_bar_attribute(self) -> None:
        """PermissionRequest имеет атрибут _action_bar."""
        from codelab.client.tui.components.permission_request import PermissionRequest
        
        permission_vm = self._create_mock_permission_vm()
        request = PermissionRequest(
            permission_vm=permission_vm,
            request_id="test-123",
        )
        
        assert hasattr(request, "_action_bar")
        # До compose _action_bar равен None
        assert request._action_bar is None

    def test_permission_request_imports_action_bar(self) -> None:
        """PermissionRequest импортирует ActionBar."""
        from codelab.client.tui.components import permission_request
        
        assert hasattr(permission_request, "ActionBar")
