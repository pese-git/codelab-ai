"""Панель быстрых действий для приложения.

Горизонтальная панель с кнопками для частых операций:
- Новая сессия
- Отменить выполнение
- Справка
- Переключить тему

Интегрируется с UIViewModel для управления состоянием кнопок.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.message import Message
from textual.widgets import Static

from .action_bar import ActionBar

if TYPE_CHECKING:
    from codelab.client.presentation.ui_view_model import UIViewModel


class QuickActionsBar(Static):
    """Панель быстрых действий с интеграцией UIViewModel.
    
    Предоставляет кнопки для частых операций пользователя.
    Автоматически обновляет состояние кнопок на основе UIViewModel.
    
    Пример использования:
        >>> bar = QuickActionsBar(ui_vm)
        >>> # Кнопки автоматически реагируют на состояние loading
    """

    # Сообщения о действиях
    class NewSessionRequested(Message):
        """Запрос создания новой сессии."""
        pass

    class CancelRequested(Message):
        """Запрос отмены текущей операции."""
        pass

    class HelpRequested(Message):
        """Запрос показа справки."""
        pass

    class ThemeToggleRequested(Message):
        """Запрос переключения темы."""
        pass

    DEFAULT_CSS = """
    QuickActionsBar {
        width: 100%;
        height: 3;
        background: $surface;
        border-top: solid $primary 50%;
        padding: 0 1;
    }
    
    QuickActionsBar.hidden {
        display: none;
    }
    
    QuickActionsBar > ActionBar {
        width: 100%;
        height: 100%;
    }
    """

    def __init__(
        self,
        ui_vm: UIViewModel,
        *,
        name: str | None = None,
        id: str | None = None,  # noqa: A002
        classes: str | None = None,
        theme_manager: object | None = None,
    ) -> None:
        """Создаёт панель быстрых действий.
        
        Args:
            ui_vm: UIViewModel для управления состоянием
            name: Имя виджета
            id: ID виджета
            classes: Дополнительные CSS классы
            theme_manager: ThemeManager для отображения иконки темы
        """
        super().__init__(name=name, id=id or "quick-actions-bar", classes=classes)
        self._ui_vm = ui_vm
        self._theme_manager = theme_manager
        self._action_bar: ActionBar | None = None
        
        # Подписываемся на изменения состояния загрузки
        self._ui_vm.is_loading.subscribe(self._on_loading_changed)
    
    def compose(self):
        """Создаёт структуру виджета."""
        self._action_bar = ActionBar(align="spread", id="quick-actions")
        yield self._action_bar
    
    def on_mount(self) -> None:
        """Добавляет кнопки действий при монтировании."""
        if self._action_bar:
            # Кнопка новой сессии
            self._action_bar.add_action(
                "Новая сессия",
                variant="primary",
                icon="➕",
                action_id="quick-new-session",
            )
            
            # Разделитель
            self._action_bar.add_separator()
            
            # Кнопка отмены (отключена по умолчанию)
            self._action_bar.add_action(
                "Отменить",
                variant="danger",
                icon="⛔",
                action_id="quick-cancel",
                disabled=True,
            )
            
            # Разделитель
            self._action_bar.add_separator()
            
            # Кнопка справки
            self._action_bar.add_action(
                "Справка",
                variant="secondary",
                icon="❓",
                action_id="quick-help",
            )
            
            # Кнопка темы
            theme_icon = self._get_theme_icon()
            self._action_bar.add_action(
                "Тема",
                variant="ghost",
                icon=theme_icon,
                action_id="quick-theme",
            )
    
    def _get_theme_icon(self) -> str:
        """Получить иконку текущей темы.
        
        Returns:
            Иконка темы (☀️ для light, 🌙 для dark)
        """
        if self._theme_manager is None:
            return "🎨"
        
        try:
            theme_name = self._theme_manager.current_theme_name
            return "🌙" if theme_name == "dark" else "☀️"
        except AttributeError:
            return "🎨"
    
    def update_theme_icon(self) -> None:
        """Обновить иконку темы при переключении."""
        if self._action_bar is None:
            return
        
        new_icon = self._get_theme_icon()
        # Обновляем иконку кнопки темы через свойство icon
        try:
            theme_button = self._action_bar.get_action("quick-theme")
            if theme_button:
                theme_button.icon = new_icon
        except Exception:
            pass
    
    def _on_loading_changed(self, is_loading: bool) -> None:
        """Обновляет состояние кнопки отмены при изменении загрузки.
        
        Args:
            is_loading: True если идет загрузка/выполнение
        """
        if self._action_bar:
            # Активируем кнопку отмены только когда идет загрузка
            self._action_bar.set_action_disabled("quick-cancel", not is_loading)
    
    def on_button_pressed(self, event) -> None:
        """Обрабатывает нажатия кнопок действий.
        
        Args:
            event: Событие нажатия кнопки
        """
        button_id = event.button.id
        
        if button_id == "quick-new-session":
            self.post_message(self.NewSessionRequested())
        
        elif button_id == "quick-cancel":
            self.post_message(self.CancelRequested())
        
        elif button_id == "quick-help":
            self.post_message(self.HelpRequested())
        
        elif button_id == "quick-theme":
            self.post_message(self.ThemeToggleRequested())
    
    def show(self) -> None:
        """Показать панель."""
        self.remove_class("hidden")
    
    def hide(self) -> None:
        """Скрыть панель."""
        self.add_class("hidden")
