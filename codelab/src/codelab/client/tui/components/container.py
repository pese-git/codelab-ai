"""Универсальный контейнер с различными вариантами оформления.

Референс: OpenCode packages/ui/src/components/container.tsx

Предоставляет:
- Варианты стиля: default, bordered, rounded
- Поддержка заголовка
- Настраиваемые padding и border
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container as TextualContainer
from textual.reactive import reactive
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.widget import Widget


class ContainerVariant(Enum):
    """Варианты оформления контейнера."""
    
    DEFAULT = "default"
    BORDERED = "bordered"
    ROUNDED = "rounded"
    PANEL = "panel"


class StyledContainer(TextualContainer):
    """Универсальный стилизованный контейнер.
    
    Поддерживает несколько вариантов оформления:
    - default: базовый контейнер без рамки
    - bordered: контейнер с прямоугольной рамкой
    - rounded: контейнер со скругленной рамкой
    - panel: контейнер с фоном и рамкой для панелей
    
    Может включать заголовок в верхней части.
    
    Примеры использования:
        >>> container = StyledContainer(variant=ContainerVariant.BORDERED)
        >>> container.mount(Static("Контент"))
        
        >>> container_with_title = StyledContainer(
        ...     title="Мой контейнер",
        ...     variant=ContainerVariant.ROUNDED
        ... )
    """

    # Reactive свойство для заголовка
    title: reactive[str] = reactive("")
    
    DEFAULT_CSS = """
    StyledContainer {
        width: 100%;
        height: auto;
        padding: 0;
    }
    
    StyledContainer.bordered {
        padding: 1;
    }
    
    StyledContainer.rounded {
        padding: 1;
    }
    
    StyledContainer.panel {
        padding: 1;
    }
    
    StyledContainer > .container-header {
        height: 1;
        width: 100%;
        margin-bottom: 1;
        text-style: bold;
    }
    
    StyledContainer > .container-content {
        width: 100%;
        height: auto;
    }
    """

    def __init__(
        self,
        *children: Widget,
        title: str = "",
        variant: ContainerVariant = ContainerVariant.DEFAULT,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Инициализирует StyledContainer.

        Args:
            *children: Дочерние виджеты для контейнера
            title: Заголовок контейнера (опционально)
            variant: Вариант оформления
            name: Имя виджета
            id: ID виджета
            classes: Дополнительные CSS классы
        """
        # Добавляем класс варианта к классам
        variant_class = variant.value
        all_classes = f"{variant_class} {classes}" if classes else variant_class
        
        super().__init__(*children, name=name, id=id, classes=all_classes)
        self._title = title
        self._variant = variant
        self._header_widget: Static | None = None
        
        # Устанавливаем начальное значение reactive свойства
        self.title = title

    def compose(self) -> ComposeResult:
        """Создает структуру контейнера с опциональным заголовком."""
        if self._title:
            self._header_widget = Static(self._title, classes="container-header")
            yield self._header_widget

    def watch_title(self, new_title: str) -> None:
        """Реагирует на изменение заголовка.
        
        Args:
            new_title: Новый заголовок
        """
        if self._header_widget is not None:
            self._header_widget.update(new_title)

    def set_variant(self, variant: ContainerVariant) -> None:
        """Изменяет вариант оформления контейнера.
        
        Args:
            variant: Новый вариант оформления
        """
        # Удаляем старый класс варианта
        self.remove_class(self._variant.value)
        # Добавляем новый
        self._variant = variant
        self.add_class(variant.value)

    @property
    def variant(self) -> ContainerVariant:
        """Возвращает текущий вариант оформления."""
        return self._variant


class Card(StyledContainer):
    """Контейнер-карточка с предустановленным стилем.
    
    Карточка - это bordered контейнер с padding.
    Используется для группировки связанного контента.
    """
    
    DEFAULT_CSS = """
    Card {
        padding: 1;
        margin: 0 0 1 0;
    }
    """

    def __init__(
        self,
        *children: Widget,
        title: str = "",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Инициализирует Card.

        Args:
            *children: Дочерние виджеты
            title: Заголовок карточки
            name: Имя виджета
            id: ID виджета
            classes: Дополнительные CSS классы
        """
        super().__init__(
            *children,
            title=title,
            variant=ContainerVariant.DEFAULT,  # Card имеет свои стили
            name=name,
            id=id,
            classes=classes,
        )
