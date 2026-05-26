"""Главный layout контейнер приложения.

Референс: OpenCode packages/web/src/ui/layout.tsx

Отвечает за:
- Структуру layout: Header | (Sidebar | MainContent) | Footer
- Toggle sidebar и bottom panel
- Координацию между панелями через UIViewModel
- События изменения состояния (SidebarToggled, PanelToggled)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.message import Message
from textual.reactive import reactive

if TYPE_CHECKING:
    from codelab.client.presentation.ui_view_model import UIViewModel


@dataclass
class LayoutConfig:
    """Конфигурация MainLayout (OpenCode-style).
    
    Attributes:
        sidebar_width: Ширина sidebar в символах
        sidebar_visible: Начальная видимость sidebar
        right_panel_width: Ширина правой панели в символах
        right_panel_visible: Начальная видимость правой панели
        bottom_panel_height: Высота dock region в строках (устаревшее название)
        bottom_panel_visible: Видимость dock region (PromptInput, QuickActionsBar)
        min_width_for_sidebar: Минимальная ширина экрана для показа sidebar
    """
    
    sidebar_width: int = 30
    sidebar_visible: bool = True
    right_panel_width: int = 30
    right_panel_visible: bool = True
    bottom_panel_height: int = 10  # Dock region height (OpenCode-style)
    bottom_panel_visible: bool = True  # Dock region всегда виден в OpenCode layout
    min_width_for_sidebar: int = 80


class MainLayout(Container):
    """Главный layout контейнер.
    
    Структура:
    ┌─────────────────────────────────────────┐
    │ Header                                  │
    ├────────┬────────────────────────────────┤
    │        │ ChatView                       │
    │Sidebar │────────────────────────────────│
    │        │ PromptInput                    │
    │        ├────────────────────────────────│
    │        │ ToolPanel / TerminalPanel      │
    └────────┴────────────────────────────────┘
    │ Footer                                  │
    └─────────────────────────────────────────┘
    
    Attributes:
        sidebar_visible: Видимость sidebar
        bottom_panel_visible: Видимость нижней панели
    """

    # --- События ---
    
    class SidebarToggled(Message):
        """Событие переключения sidebar.
        
        Attributes:
            visible: Новое состояние видимости sidebar
        """
        
        def __init__(self, visible: bool) -> None:
            """Инициализирует событие.
            
            Args:
                visible: Новое состояние видимости
            """
            super().__init__()
            self.visible = visible
    
    class PanelToggled(Message):
        """Событие переключения нижней панели.
        
        Attributes:
            panel_type: Тип панели ('bottom')
            visible: Новое состояние видимости
        """
        
        def __init__(self, panel_type: str, visible: bool) -> None:
            """Инициализирует событие.
            
            Args:
                panel_type: Тип панели
                visible: Новое состояние видимости
            """
            super().__init__()
            self.panel_type = panel_type
            self.visible = visible

    # --- Reactive свойства ---
    
    sidebar_visible: reactive[bool] = reactive(True)
    right_panel_visible: reactive[bool] = reactive(True)
    bottom_panel_visible: reactive[bool] = reactive(False)
    
    DEFAULT_CSS = """
    MainLayout {
        layout: horizontal;
        width: 100%;
        height: 1fr;
        background: $background;
    }
    
    MainLayout > #sidebar-column {
        width: 30;
        height: 100%;
        layout: vertical;
        background: $background;
    }
    
    MainLayout > #sidebar-column.hidden {
        display: none;
    }
    
    MainLayout > #main-column {
        width: 1fr;
        height: 100%;
        layout: vertical;
        background: $background;
    }
    
    MainLayout > #main-column > #content-area {
        height: 1fr;
        background: $background;
    }
    
    /* Dock Region - область для PromptInput и QuickActionsBar (как в OpenCode) */
    MainLayout > #main-column > #dock-region {
        height: auto;
        min-height: 6;
        max-height: 15;
        background: $background;
    }
    
    MainLayout > #main-column > #dock-region.hidden {
        display: none;
    }
    
    MainLayout > #right-panel-column {
        width: 30;
        height: 100%;
        layout: vertical;
        background: $background;
    }
    
    MainLayout > #right-panel-column.hidden {
        display: none;
    }
    """

    def __init__(
        self,
        config: LayoutConfig | None = None,
        ui_vm: UIViewModel | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Инициализирует MainLayout.

        Args:
            config: Конфигурация layout
            ui_vm: UIViewModel для управления состоянием layout
            name: Имя виджета
            id: ID виджета
            classes: CSS классы
        """
        super().__init__(name=name, id=id, classes=classes)
        self._config = config or LayoutConfig()
        self._ui_vm = ui_vm
        
        # Контейнеры для секций (инициализируем ДО reactive свойств)
        self._sidebar_container: Vertical | None = None
        self._content_container: Vertical | None = None
        self._dock_region_container: Vertical | None = None  # OpenCode-style dock region
        self._right_panel_container: Vertical | None = None
        
        # Применяем начальные значения из конфигурации
        self.sidebar_visible = self._config.sidebar_visible
        self.right_panel_visible = self._config.right_panel_visible
        self.bottom_panel_visible = self._config.bottom_panel_visible
        
        # Подписываемся на изменения в UIViewModel
        if self._ui_vm is not None:
            self._ui_vm.sidebar_collapsed.subscribe(self._on_sidebar_collapsed_changed)

    @property
    def config(self) -> LayoutConfig:
        """Возвращает конфигурацию layout."""
        return self._config

    def compose(self) -> ComposeResult:
        """Создает базовую структуру layout.
        
        MainLayout имеет layout:horizontal и содержит три колонки напрямую:
        - sidebar-column (Vertical) - левая панель
        - main-column (Vertical) - центральная панель с content-area и bottom-panel
        - right-panel-column (Vertical) - правая панель
        
        Дочерние виджеты должны быть добавлены через mount() в контейнеры.
        """
        # Sidebar колонка (левая)
        sidebar_classes = ""
        if not self.sidebar_visible:
            sidebar_classes = "hidden"
        self._sidebar_container = Vertical(
            classes=sidebar_classes if sidebar_classes else None,
            id="sidebar-column",
        )
        yield self._sidebar_container
        
        # Основная колонка (центр + низ)
        with Vertical(id="main-column"):
            # Контент
            self._content_container = Vertical(id="content-area")
            yield self._content_container
            
            # Dock Region - область для PromptInput и QuickActionsBar (как в OpenCode)
            dock_classes = ""
            if not self.bottom_panel_visible:
                dock_classes = "hidden"
            self._dock_region_container = Vertical(
                classes=dock_classes if dock_classes else None,
                id="dock-region",
            )
            yield self._dock_region_container
        
        # Правая панель (для ToolPanel)
        right_classes = ""
        if not self.right_panel_visible:
            right_classes = "hidden"
        self._right_panel_container = Vertical(
            classes=right_classes if right_classes else None,
            id="right-panel-column",
        )
        yield self._right_panel_container

    def _on_sidebar_collapsed_changed(self, collapsed: bool) -> None:
        """Обработчик изменения состояния свернутости sidebar.
        
        Args:
            collapsed: True если sidebar свернут
        """
        self.sidebar_visible = not collapsed

    def watch_sidebar_visible(self, visible: bool) -> None:
        """Реагирует на изменение видимости sidebar.
        
        Args:
            visible: Новое значение видимости
        """
        if self._sidebar_container is not None:
            if visible:
                self._sidebar_container.remove_class("hidden")
            else:
                self._sidebar_container.add_class("hidden")
        
        # Отправляем событие
        self.post_message(self.SidebarToggled(visible))

    def watch_bottom_panel_visible(self, visible: bool) -> None:
        """Реагирует на изменение видимости dock region (нижней панели).
        
        Args:
            visible: Новое значение видимости
        """
        if self._dock_region_container is not None:
            if visible:
                self._dock_region_container.remove_class("hidden")
            else:
                self._dock_region_container.add_class("hidden")
        
        # Отправляем событие
        self.post_message(self.PanelToggled("dock", visible))

    def watch_right_panel_visible(self, visible: bool) -> None:
        """Реагирует на изменение видимости правой панели.
        
        Args:
            visible: Новое значение видимости
        """
        if self._right_panel_container is not None:
            if visible:
                self._right_panel_container.remove_class("hidden")
            else:
                self._right_panel_container.add_class("hidden")
        
        # Отправляем событие
        self.post_message(self.PanelToggled("right", visible))

    def toggle_sidebar(self) -> None:
        """Переключает видимость sidebar."""
        self.sidebar_visible = not self.sidebar_visible
        # Синхронизируем с ViewModel если есть
        if self._ui_vm is not None:
            self._ui_vm.sidebar_collapsed.value = not self.sidebar_visible

    def toggle_bottom_panel(self) -> None:
        """Переключает видимость нижней панели."""
        self.bottom_panel_visible = not self.bottom_panel_visible

    def toggle_right_panel(self) -> None:
        """Переключает видимость правой панели."""
        self.right_panel_visible = not self.right_panel_visible

    def on_resize(self) -> None:
        """Обрабатывает изменение размера для responsive поведения."""
        # Автоматически скрываем sidebar при маленькой ширине
        if (
            self.size.width < self._config.min_width_for_sidebar
            and self.sidebar_visible
        ):
            self.sidebar_visible = False
        # Восстанавливаем если достаточно места и не было явно скрыто
        elif (
            self._ui_vm is not None
            and not self._ui_vm.sidebar_collapsed.value
            and not self.sidebar_visible
            and self.size.width >= self._config.min_width_for_sidebar
        ):
            self.sidebar_visible = True

    @property
    def sidebar_column(self) -> Vertical | None:
        """Возвращает контейнер sidebar колонки."""
        return self._sidebar_container
    
    @property
    def content_area(self) -> Vertical | None:
        """Возвращает контейнер области контента."""
        return self._content_container
    
    @property
    def dock_region(self) -> Vertical | None:
        """Возвращает контейнер dock region (область для PromptInput).
        
        OpenCode-style layout: Prompt и QuickActionsBar находятся в dock region
        внизу main-column, а не в отдельном контейнере снаружи.
        """
        return self._dock_region_container

    @property
    def bottom_panel(self) -> Vertical | None:
        """Alias для dock_region (обратная совместимость)."""
        return self._dock_region_container
    
    @property
    def right_panel_column(self) -> Vertical | None:
        """Возвращает контейнер правой панели."""
        return self._right_panel_container
