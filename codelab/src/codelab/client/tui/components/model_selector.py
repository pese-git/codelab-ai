"""ModelSelectorModal - модальное окно для выбора LLM модели.

Референс: CommandPalette с упрощённым интерфейсом выбора из списка.

Функциональность:
- Отображение списка доступных моделей
- Поиск модели по названию
- Отображение текущей выбранной модели
- Информация о контекстном окне и стоимости
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

from .keyboard_manager import (
    KeyboardManager,
    get_keyboard_manager,
)

if TYPE_CHECKING:
    from codelab.client.presentation.model_selector_view_model import (
        ModelOption,
        ModelSelectorViewModel,
    )


class ModelItem(Static):
    """Элемент списка моделей.

    Отображает одну модель с названием, описанием и стоимостью.
    """

    DEFAULT_CSS = """
    ModelItem {
        width: 100%;
        height: 3;
        padding: 0 2;
        background: transparent;
    }

    ModelItem:hover {
        background: $surface-lighten-1;
    }

    ModelItem.-selected {
        background: $primary 30%;
    }

    ModelItem.-current {
        border-left: solid $success;
    }

    ModelItem .model-name {
        width: 1fr;
        text-style: bold;
    }

    ModelItem .model-provider {
        width: auto;
        color: $text-muted;
        text-style: italic;
    }

    ModelItem .model-details {
        width: 100%;
        color: $text-muted;
        text-style: italic;
    }
    """

    class Selected(Message):
        """Сообщение о выборе модели."""

        def __init__(self, model: ModelOption) -> None:
            self.model = model
            super().__init__()

    def __init__(
        self,
        model: ModelOption,
        *,
        selected: bool = False,
        is_current: bool = False,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Инициализирует элемент модели.

        Args:
            model: Данные модели
            selected: Выбрана ли модель в списке
            is_current: Является ли текущей моделью
            name: Имя виджета
            id: ID виджета
            classes: CSS классы
        """
        super().__init__(name=name, id=id, classes=classes)
        self._model = model
        self._selected = selected
        self._is_current = is_current

    @property
    def model(self) -> ModelOption:
        """Возвращает данные модели."""
        return self._model

    def compose(self) -> ComposeResult:
        """Создаёт содержимое элемента."""
        if self._selected:
            self.add_class("-selected")
        if self._is_current:
            self.add_class("-current")

        # Форматируем строку модели
        provider = self._model.provider_id
        label = self._model.label

        # Основная строка: название + провайдер
        line = f"{label}"
        if provider:
            line += f"  [{provider}]"

        yield Label(line, classes="model-name")

        # Детали: описание + стоимость
        details = []
        if self._model.description:
            details.append(self._model.description)
        if self._model.pricing:
            details.append(self._model.pricing)

        if details:
            yield Label(" | ".join(details), classes="model-details")

    def on_click(self) -> None:
        """Обрабатывает клик по модели."""
        self.post_message(self.Selected(self._model))


class ModelSelectorModal(ModalScreen[str | None]):
    """Модальное окно выбора LLM модели.

    Открывается по hotkey, позволяет выбрать модель из списка.
    """

    DEFAULT_CSS = """
    ModelSelectorModal {
        align: center middle;
    }

    ModelSelectorModal > Container {
        width: 70;
        max-width: 85%;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: solid $border;
        padding: 1;
    }

    ModelSelectorModal .modal-title {
        width: 100%;
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    ModelSelectorModal .current-model {
        width: 100%;
        text-align: center;
        color: $success;
        text-style: italic;
        margin-bottom: 1;
    }

    ModelSelectorModal .search-container {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }

    ModelSelectorModal Input {
        width: 100%;
    }

    ModelSelectorModal .models-scroll {
        width: 100%;
        height: auto;
        max-height: 20;
    }

    ModelSelectorModal .no-results {
        width: 100%;
        text-align: center;
        color: $text-muted;
        padding: 2;
    }

    ModelSelectorModal .no-models {
        width: 100%;
        text-align: center;
        color: $text-muted;
        padding: 2;
    }

    ModelSelectorModal .hint {
        width: 100%;
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }
    """

    BINDINGS = [
        ("escape", "close", "Закрыть"),
        ("up", "previous", "Предыдущая"),
        ("down", "next", "Следующая"),
        ("enter", "select", "Выбрать"),
    ]

    def __init__(
        self,
        view_model: ModelSelectorViewModel,
        session_id: str,
        keyboard_manager: KeyboardManager | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Инициализирует модальное окно выбора модели.

        Args:
            view_model: ModelSelectorViewModel для управления состоянием
            session_id: ID текущей сессии
            keyboard_manager: KeyboardManager для hotkeys
            name: Имя виджета
            id: ID виджета
            classes: CSS классы
        """
        super().__init__(name=name, id=id, classes=classes)
        self._view_model = view_model
        self._session_id = session_id
        self._keyboard_manager = keyboard_manager or get_keyboard_manager()
        self._filtered_models: list[ModelOption] = []
        self._selected_index: int = 0

    def compose(self) -> ComposeResult:
        """Создаёт содержимое модального окна."""
        with Container():
            yield Label("🤖 Выбор модели", classes="modal-title")

            # Показываем текущую модель
            current_label = self._view_model.get_current_model_label()
            yield Label(f"Текущая: {current_label}", classes="current-model")

            with Container(classes="search-container"):
                yield Input(placeholder="Поиск модели...", id="model-search")

            with VerticalScroll(classes="models-scroll"):
                yield from self._render_models()

            yield Label("↑↓ навигация • Enter выбор • Esc закрыть", classes="hint")

    def _render_models(self) -> ComposeResult:
        """Рендерит список моделей."""
        all_models = self._view_model.available_models.value
        models = self._filtered_models if self._filtered_models else all_models

        if not models:
            if self._view_model.available_models.value:
                yield Label("Модели не найдены", classes="no-results")
            else:
                yield Label(
                    "Список моделей недоступен.\nСоздайте или загрузите сессию.",
                    classes="no-models",
                )
            return

        current_model = self._view_model.current_model.value

        for i, model in enumerate(models):
            is_selected = i == self._selected_index
            is_current = model.value == current_model
            yield ModelItem(
                model,
                selected=is_selected,
                is_current=is_current,
                id=f"model-{model.value.replace('/', '_')}",
            )

    def on_mount(self) -> None:
        """Фокусируемся на поле поиска при открытии."""
        search_input = self.query_one("#model-search", Input)
        search_input.focus()

    async def on_input_changed(self, event: Input.Changed) -> None:
        """Обрабатывает изменение поискового запроса."""
        query = event.value.strip().lower()
        self._filter_models(query)
        await self._refresh_models()

    def _filter_models(self, query: str) -> None:
        """Фильтрует модели по запросу (fuzzy search).

        Args:
            query: Поисковый запрос
        """
        all_models = self._view_model.available_models.value

        if not query:
            self._filtered_models = all_models.copy()
        else:
            self._filtered_models = []
            for model in all_models:
                # Fuzzy match по названию, провайдеру и описанию
                if (
                    self._fuzzy_match(query, model.label.lower())
                    or self._fuzzy_match(query, model.provider_id.lower())
                    or self._fuzzy_match(query, model.description.lower())
                ):
                    self._filtered_models.append(model)

        # Сбрасываем выбор
        self._selected_index = 0

    def _fuzzy_match(self, query: str, text: str) -> bool:
        """Проверяет fuzzy соответствие запроса тексту.

        Args:
            query: Поисковый запрос
            text: Текст для проверки

        Returns:
            True если текст соответствует запросу
        """
        # Простой fuzzy match: все символы query должны быть в text в том же порядке
        query_index = 0
        for char in text:
            if query_index < len(query) and char == query[query_index]:
                query_index += 1
        return query_index == len(query)

    def _update_selection(self) -> None:
        """Обновляет класс -selected без пересоздания виджетов."""
        all_models = self._view_model.available_models.value
        models = self._filtered_models if self._filtered_models else all_models
        for i, model in enumerate(models):
            try:
                widget_id = f"model-{model.value.replace('/', '_')}"
                item = self.query_one(widget_id, ModelItem)
                item.set_class(i == self._selected_index, "-selected")
            except Exception:
                pass

    async def _refresh_models(self) -> None:
        """Пересоздаёт список моделей (используется после фильтрации)."""
        scroll = self.query_one(".models-scroll", VerticalScroll)
        await scroll.remove_children()
        await scroll.mount(*list(self._render_models()))

    def action_close(self) -> None:
        """Закрывает модальное окно без выбора."""
        self.dismiss(None)

    def action_previous(self) -> None:
        """Выбирает предыдущую модель."""
        all_models = self._view_model.available_models.value
        models = self._filtered_models if self._filtered_models else all_models
        if models and self._selected_index > 0:
            self._selected_index -= 1
            self._update_selection()

    def action_next(self) -> None:
        """Выбирает следующую модель."""
        all_models = self._view_model.available_models.value
        models = self._filtered_models if self._filtered_models else all_models
        if models and self._selected_index < len(models) - 1:
            self._selected_index += 1
            self._update_selection()

    def action_select(self) -> None:
        """Выбирает модель и закрывает модальное окно."""
        all_models = self._view_model.available_models.value
        models = self._filtered_models if self._filtered_models else all_models
        if models and 0 <= self._selected_index < len(models):
            selected_model = models[self._selected_index]
            self.dismiss(selected_model.value)

    def on_model_item_selected(self, event: ModelItem.Selected) -> None:
        """Обрабатывает выбор модели кликом."""
        self.dismiss(event.model.value)
