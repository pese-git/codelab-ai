"""Сворачиваемая панель с заголовком и действиями.

Референс: OpenCode packages/ui/src/components/panel.tsx

Предоставляет:
- Collapsible (сворачиваемый) контент
- Header с иконкой и действиями
- Анимация сворачивания через CSS
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Button, Static

if TYPE_CHECKING:
    from textual.widget import Widget


class CollapsiblePanel(Container):
    """Сворачиваемая панель с заголовком.
    
    Панель состоит из:
    - Header: заголовок с иконкой, текстом и кнопкой toggle
    - Content: основной контент, скрываемый при сворачивании
    
    Примеры использования:
        >>> panel = CollapsiblePanel(title="Настройки", icon="⚙️")
        >>> panel.mount(Static("Содержимое панели"))
        
        >>> # С начально свернутым состоянием
        >>> panel = CollapsiblePanel(title="Логи", collapsed=True)
    """

    # Reactive свойства
    collapsed: reactive[bool] = reactive(False)
    title: reactive[str] = reactive("")
    icon: reactive[str] = reactive("")
    
    DEFAULT_CSS = """
    CollapsiblePanel {
        width: 100%;
        height: auto;
    }
    
    CollapsiblePanel > .panel-header {
        width: 100%;
        height: 3;
        layout: horizontal;
        padding: 0 1;
    }
    
    CollapsiblePanel > .panel-header > .panel-icon {
        width: 3;
        height: 1;
        content-align: center middle;
    }
    
    CollapsiblePanel > .panel-header > .panel-title {
        width: 1fr;
        height: 1;
        text-style: bold;
    }
    
    CollapsiblePanel > .panel-header > .panel-toggle {
        width: 3;
        height: 1;
        min-width: 3;
        content-align: center middle;
        border: none;
    }
    
    CollapsiblePanel > .panel-content {
        width: 100%;
        height: auto;
        padding: 1;
    }
    
    CollapsiblePanel > .panel-content.hidden {
        display: none;
    }
    
    CollapsiblePanel.collapsed > .panel-content {
        display: none;
    }
    """

    class Toggled(Message):
        """Событие переключения состояния панели."""

        def __init__(self, panel: CollapsiblePanel, collapsed: bool) -> None:
            """Сохраняет информацию о состоянии.
            
            Args:
                panel: Панель, состояние которой изменилось
                collapsed: Новое состояние (True = свернуто)
            """
            super().__init__()
            self.panel = panel
            self.collapsed = collapsed

    def __init__(
        self,
        *children: Widget,
        title: str = "",
        icon: str = "",
        collapsed: bool = False,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Инициализирует CollapsiblePanel.

        Args:
            *children: Дочерние виджеты для контента
            title: Заголовок панели
            icon: Иконка (emoji или символ)
            collapsed: Начальное состояние (True = свернуто)
            name: Имя виджета
            id: ID виджета
            classes: Дополнительные CSS классы
        """
        super().__init__(name=name, id=id, classes=classes)
        self._initial_children = children
        self._title = title
        self._icon = icon
        self._initial_collapsed = collapsed
        
        # Виджеты для обновления
        self._icon_widget: Static | None = None
        self._title_widget: Static | None = None
        self._toggle_button: Button | None = None
        self._content_container: Vertical | None = None

    def compose(self) -> ComposeResult:
        """Создает структуру панели с header и content."""
        # Header
        with Container(classes="panel-header"):
            self._icon_widget = Static(self._icon, classes="panel-icon")
            yield self._icon_widget
            
            self._title_widget = Static(self._title, classes="panel-title")
            yield self._title_widget
            
            toggle_icon = "▼" if not self._initial_collapsed else "▶"
            self._toggle_button = Button(toggle_icon, classes="panel-toggle")
            yield self._toggle_button
        
        # Content
        self._content_container = Vertical(classes="panel-content")
        if self._initial_collapsed:
            self._content_container.add_class("hidden")
        yield self._content_container

    def on_mount(self) -> None:
        """Монтирует начальных детей после инициализации."""
        # Устанавливаем начальные значения reactive свойств
        self.title = self._title
        self.icon = self._icon
        self.collapsed = self._initial_collapsed
        
        # Монтируем дочерние виджеты в контейнер контента
        if self._content_container is not None and self._initial_children:
            for child in self._initial_children:
                self._content_container.mount(child)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Обрабатывает нажатие на кнопку toggle."""
        if event.button is self._toggle_button:
            self.toggle()
            event.stop()

    def on_click(self, event: events.Click) -> None:
        """Обрабатывает клик на header для toggle."""
        # Проверяем, что клик был в области header
        header = self.query_one(".panel-header", Container)
        if header in event.widget.ancestors_with_self:
            self.toggle()
            event.stop()

    def toggle(self) -> None:
        """Переключает состояние панели."""
        self.collapsed = not self.collapsed

    def watch_collapsed(self, collapsed: bool) -> None:
        """Реагирует на изменение состояния свернутости.
        
        Args:
            collapsed: Новое состояние
        """
        if self._content_container is not None:
            if collapsed:
                self._content_container.add_class("hidden")
                self.add_class("collapsed")
            else:
                self._content_container.remove_class("hidden")
                self.remove_class("collapsed")
        
        if self._toggle_button is not None:
            self._toggle_button.label = "▶" if collapsed else "▼"
        
        # Отправляем событие
        self.post_message(self.Toggled(self, collapsed))

    def watch_title(self, new_title: str) -> None:
        """Реагирует на изменение заголовка."""
        if self._title_widget is not None:
            self._title_widget.update(new_title)

    def watch_icon(self, new_icon: str) -> None:
        """Реагирует на изменение иконки."""
        if self._icon_widget is not None:
            self._icon_widget.update(new_icon)

    def expand(self) -> None:
        """Разворачивает панель."""
        self.collapsed = False

    def collapse(self) -> None:
        """Сворачивает панель."""
        self.collapsed = True

    @property
    def content(self) -> Vertical | None:
        """Возвращает контейнер контента для добавления виджетов."""
        return self._content_container


class AccordionPanel(Container):
    """Группа панелей, где только одна может быть развернута.
    
    Работает как аккордеон - при разворачивании одной панели,
    остальные автоматически сворачиваются.
    """
    
    DEFAULT_CSS = """
    AccordionPanel {
        width: 100%;
        height: auto;
        layout: vertical;
    }
    
    AccordionPanel > CollapsiblePanel {
        margin-bottom: 1;
    }
    """

    def __init__(
        self,
        *children: CollapsiblePanel,
        allow_multiple: bool = False,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Инициализирует AccordionPanel.

        Args:
            *children: Панели для группы
            allow_multiple: Разрешить несколько открытых панелей
            name: Имя виджета
            id: ID виджета
            classes: Дополнительные CSS классы
        """
        super().__init__(*children, name=name, id=id, classes=classes)
        self._allow_multiple = allow_multiple

    def on_collapsible_panel_toggled(self, event: CollapsiblePanel.Toggled) -> None:
        """Обрабатывает событие toggle панели.
        
        При развертывании панели сворачивает остальные (если allow_multiple=False).
        """
        if self._allow_multiple:
            return
            
        if not event.collapsed:
            # Сворачиваем все остальные панели
            for panel in self.query(CollapsiblePanel):
                if panel is not event.panel and not panel.collapsed:
                    panel.collapse()
