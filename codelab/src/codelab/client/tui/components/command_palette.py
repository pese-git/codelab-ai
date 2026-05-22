"""Command Palette - модальное окно с поиском команд.

Референс: OpenCode packages/web/src/ui/command-palette.tsx

Функциональность:
- Быстрый поиск команд через fuzzy search
- Категории команд с иконками
- Отображение горячих клавиш
- История последних команд
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, ClassVar

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
    pass


class CommandCategory(Enum):
    """Категории команд в палитре."""

    SESSION = "session"
    NAVIGATION = "navigation"
    VIEW = "view"
    TOOLS = "tools"
    SYSTEM = "system"


@dataclass
class Command:
    """Описание команды для палитры.

    Атрибуты:
        id: Уникальный идентификатор команды
        name: Отображаемое название
        description: Описание команды
        category: Категория команды
        action: Имя действия для выполнения
        hotkey: Горячая клавиша (опционально)
        icon: Иконка команды
        enabled: Доступна ли команда
    """

    id: str
    name: str
    description: str = ""
    category: CommandCategory = CommandCategory.SYSTEM
    action: str = ""
    hotkey: str = ""
    icon: str = "▸"
    enabled: bool = True


# Иконки для категорий команд
CATEGORY_ICONS: dict[CommandCategory, str] = {
    CommandCategory.SESSION: "💬",
    CommandCategory.NAVIGATION: "🧭",
    CommandCategory.VIEW: "👁",
    CommandCategory.TOOLS: "🔧",
    CommandCategory.SYSTEM: "⚙",
}

# Стандартный набор команд
DEFAULT_COMMANDS: list[Command] = [
    # Сессии
    Command(
        id="new_session",
        name="Новая сессия",
        description="Создать новую сессию чата",
        category=CommandCategory.SESSION,
        action="new_session",
        hotkey="Ctrl+N",
        icon="➕",
    ),
    Command(
        id="retry_prompt",
        name="Повторить запрос",
        description="Повторить последний запрос",
        category=CommandCategory.SESSION,
        action="retry_prompt",
        hotkey="Ctrl+R",
        icon="🔄",
    ),
    Command(
        id="cancel_prompt",
        name="Отменить запрос",
        description="Отменить текущий запрос",
        category=CommandCategory.SESSION,
        action="cancel_prompt",
        hotkey="Ctrl+C",
        icon="✖",
    ),
    Command(
        id="clear_chat",
        name="Очистить чат",
        description="Очистить текущую сессию",
        category=CommandCategory.SESSION,
        action="clear_chat",
        hotkey="Ctrl+L",
        icon="🗑",
    ),
    # Навигация
    Command(
        id="toggle_sidebar",
        name="Боковая панель",
        description="Показать/скрыть боковую панель",
        category=CommandCategory.NAVIGATION,
        action="toggle_sidebar",
        hotkey="Ctrl+B",
        icon="◧",
    ),
    Command(
        id="focus_sidebar",
        name="Фокус на sidebar",
        description="Переключить фокус на боковую панель",
        category=CommandCategory.NAVIGATION,
        action="focus_sidebar",
        hotkey="Ctrl+S",
        icon="◀",
    ),
    Command(
        id="next_session",
        name="Следующая сессия",
        description="Перейти к следующей сессии",
        category=CommandCategory.NAVIGATION,
        action="next_session",
        hotkey="Ctrl+J",
        icon="↓",
    ),
    Command(
        id="previous_session",
        name="Предыдущая сессия",
        description="Перейти к предыдущей сессии",
        category=CommandCategory.NAVIGATION,
        action="previous_session",
        hotkey="Ctrl+K",
        icon="↑",
    ),
    # Отображение
    Command(
        id="toggle_theme",
        name="Переключить тему",
        description="Переключить между светлой и тёмной темой",
        category=CommandCategory.VIEW,
        action="toggle_theme",
        hotkey="Ctrl+T",
        icon="🌓",
    ),
    Command(
        id="open_terminal",
        name="Терминал",
        description="Открыть вывод терминала",
        category=CommandCategory.VIEW,
        action="open_terminal_output",
        hotkey="Ctrl+`",
        icon="🖥",
    ),
    Command(
        id="toggle_plan",
        name="Панель плана",
        description="Показать/скрыть панель плана агента",
        category=CommandCategory.VIEW,
        action="toggle_plan_panel",
        hotkey="Ctrl+P",
        icon="📋",
    ),
    # Инструменты
    Command(
        id="open_file_tree",
        name="Файловое дерево",
        description="Открыть дерево файлов",
        category=CommandCategory.TOOLS,
        action="focus_file_tree",
        icon="📁",
    ),
    # Системные
    Command(
        id="open_help",
        name="Справка",
        description="Открыть справку",
        category=CommandCategory.SYSTEM,
        action="open_help",
        hotkey="Ctrl+H",
        icon="❓",
    ),
    Command(
        id="show_hotkeys",
        name="Горячие клавиши",
        description="Показать все горячие клавиши",
        category=CommandCategory.SYSTEM,
        action="show_hotkeys",
        hotkey="?",
        icon="⌨",
    ),
    Command(
        id="quit",
        name="Выход",
        description="Выйти из приложения",
        category=CommandCategory.SYSTEM,
        action="quit",
        hotkey="Ctrl+Q",
        icon="🚪",
    ),
]


class CommandItem(Static):
    """Элемент списка команд.

    Отображает одну команду с иконкой, названием и горячей клавишей.
    """

    DEFAULT_CSS = """
    CommandItem {
        width: 100%;
        height: 3;
        padding: 0 2;
        background: transparent;
    }

    CommandItem:hover {
        background: $surface-lighten-1;
    }

    CommandItem.-selected {
        background: $primary 30%;
    }

    CommandItem.-disabled {
        opacity: 0.5;
    }

    CommandItem .command-icon {
        width: 3;
        margin-right: 1;
    }

    CommandItem .command-name {
        width: 1fr;
    }

    CommandItem .command-hotkey {
        width: auto;
        color: $text-muted;
        text-style: italic;
    }

    CommandItem .command-description {
        width: 100%;
        color: $text-muted;
        text-style: italic;
    }
    """

    class Selected(Message):
        """Сообщение о выборе команды."""

        def __init__(self, command: Command) -> None:
            self.command = command
            super().__init__()

    def __init__(
        self,
        command: Command,
        *,
        selected: bool = False,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Инициализирует элемент команды.

        Args:
            command: Данные команды
            selected: Выбрана ли команда
            name: Имя виджета
            id: ID виджета
            classes: CSS классы
        """
        super().__init__(name=name, id=id, classes=classes)
        self._command = command
        self._selected = selected

    @property
    def command(self) -> Command:
        """Возвращает данные команды."""
        return self._command

    def compose(self) -> ComposeResult:
        """Создаёт содержимое элемента."""
        if self._selected:
            self.add_class("-selected")
        if not self._command.enabled:
            self.add_class("-disabled")

        # Форматируем строку команды
        icon = self._command.icon
        name = self._command.name
        hotkey = self._command.hotkey or ""

        # Основная строка: иконка + название + горячая клавиша
        line = f"{icon}  {name}"
        if hotkey:
            line += f"  [{hotkey}]"

        yield Label(line)

    def on_click(self) -> None:
        """Обрабатывает клик по команде."""
        if self._command.enabled:
            self.post_message(self.Selected(self._command))


class CommandPalette(ModalScreen[Command | None]):
    """Модальное окно палитры команд.

    Открывается по Ctrl+K, позволяет искать и выполнять команды.
    """

    DEFAULT_CSS = """
    CommandPalette {
        align: center middle;
    }

    CommandPalette > Container {
        width: 60;
        max-width: 80%;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: solid $border;
        padding: 1;
    }

    CommandPalette .palette-title {
        width: 100%;
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    CommandPalette .search-container {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }

    CommandPalette Input {
        width: 100%;
    }

    CommandPalette .commands-scroll {
        width: 100%;
        height: auto;
        max-height: 20;
    }

    CommandPalette .category-header {
        width: 100%;
        padding: 0 1;
        color: $text-muted;
        text-style: bold italic;
        margin-top: 1;
    }

    CommandPalette .no-results {
        width: 100%;
        text-align: center;
        color: $text-muted;
        padding: 2;
    }

    CommandPalette .hint {
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

    # Максимальное количество элементов в истории
    MAX_HISTORY: ClassVar[int] = 5

    def __init__(
        self,
        commands: list[Command] | None = None,
        keyboard_manager: KeyboardManager | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Инициализирует палитру команд.

        Args:
            commands: Список доступных команд (по умолчанию DEFAULT_COMMANDS)
            keyboard_manager: KeyboardManager для получения hotkeys
            name: Имя виджета
            id: ID виджета
            classes: CSS классы
        """
        super().__init__(name=name, id=id, classes=classes)
        self._commands = commands or DEFAULT_COMMANDS.copy()
        self._keyboard_manager = keyboard_manager or get_keyboard_manager()
        self._filtered_commands: list[Command] = self._commands.copy()
        self._selected_index: int = 0
        self._history: list[str] = []  # История последних команд (ID)

    def compose(self) -> ComposeResult:
        """Создаёт содержимое палитры."""
        with Container():
            yield Label("🔍 Палитра команд", classes="palette-title")

            with Container(classes="search-container"):
                yield Input(placeholder="Введите команду...", id="command-search")

            with VerticalScroll(classes="commands-scroll"):
                yield from self._render_commands()

            yield Label("↑↓ навигация • Enter выбор • Esc закрыть", classes="hint")

    def _render_commands(self) -> ComposeResult:
        """Рендерит список команд с категориями."""
        if not self._filtered_commands:
            yield Label("Команды не найдены", classes="no-results")
            return

        # Группируем по категориям
        by_category: dict[CommandCategory, list[Command]] = {}
        for cmd in self._filtered_commands:
            if cmd.category not in by_category:
                by_category[cmd.category] = []
            by_category[cmd.category].append(cmd)

        # Порядок категорий
        category_order = [
            CommandCategory.SESSION,
            CommandCategory.NAVIGATION,
            CommandCategory.VIEW,
            CommandCategory.TOOLS,
            CommandCategory.SYSTEM,
        ]

        current_index = 0
        for category in category_order:
            if category not in by_category:
                continue

            # Заголовок категории
            icon = CATEGORY_ICONS.get(category, "")
            name = {
                CommandCategory.SESSION: "Сессии",
                CommandCategory.NAVIGATION: "Навигация",
                CommandCategory.VIEW: "Отображение",
                CommandCategory.TOOLS: "Инструменты",
                CommandCategory.SYSTEM: "Системные",
            }.get(category, category.value)

            yield Label(f"{icon} {name}", classes="category-header")

            # Команды категории
            for cmd in by_category[category]:
                is_selected = current_index == self._selected_index
                yield CommandItem(cmd, selected=is_selected, id=f"cmd-{cmd.id}")
                current_index += 1

    def on_mount(self) -> None:
        """Фокусируемся на поле поиска при открытии."""
        search_input = self.query_one("#command-search", Input)
        search_input.focus()

    async def on_input_changed(self, event: Input.Changed) -> None:
        """Обрабатывает изменение поискового запроса."""
        query = event.value.strip().lower()
        self._filter_commands(query)
        await self._refresh_commands()

    def _filter_commands(self, query: str) -> None:
        """Фильтрует команды по запросу (fuzzy search).

        Args:
            query: Поисковый запрос
        """
        if not query:
            self._filtered_commands = self._commands.copy()
        else:
            self._filtered_commands = []
            for cmd in self._commands:
                # Fuzzy match по названию и описанию
                if self._fuzzy_match(query, cmd.name.lower()) or self._fuzzy_match(
                    query, cmd.description.lower()
                ):
                    self._filtered_commands.append(cmd)

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
        for i, cmd in enumerate(self._filtered_commands):
            try:
                item = self.query_one(f"#cmd-{cmd.id}", CommandItem)
                item.set_class(i == self._selected_index, "-selected")
            except Exception:
                pass

    async def _refresh_commands(self) -> None:
        """Пересоздаёт список команд (используется после фильтрации)."""
        scroll = self.query_one(".commands-scroll", VerticalScroll)
        await scroll.remove_children()
        await scroll.mount(*list(self._render_commands()))

    def action_close(self) -> None:
        """Закрывает палитру без выбора."""
        self.dismiss(None)

    def action_previous(self) -> None:
        """Выбирает предыдущую команду."""
        if self._filtered_commands and self._selected_index > 0:
            self._selected_index -= 1
            self._update_selection()

    def action_next(self) -> None:
        """Выбирает следующую команду."""
        if self._filtered_commands and self._selected_index < len(self._filtered_commands) - 1:
            self._selected_index += 1
            self._update_selection()

    def action_select(self) -> None:
        """Выполняет выбранную команду."""
        if self._filtered_commands and 0 <= self._selected_index < len(self._filtered_commands):
            command = self._filtered_commands[self._selected_index]
            self._add_to_history(command.id)
            self.dismiss(command)

    def on_command_item_selected(self, event: CommandItem.Selected) -> None:
        """Обрабатывает выбор команды кликом."""
        self._add_to_history(event.command.id)
        self.dismiss(event.command)

    def _add_to_history(self, command_id: str) -> None:
        """Добавляет команду в историю.

        Args:
            command_id: ID команды
        """
        # Удаляем если уже есть
        if command_id in self._history:
            self._history.remove(command_id)
        # Добавляем в начало
        self._history.insert(0, command_id)
        # Ограничиваем размер
        self._history = self._history[: self.MAX_HISTORY]

    def add_command(self, command: Command) -> None:
        """Добавляет команду в палитру.

        Args:
            command: Команда для добавления
        """
        self._commands.append(command)
        self._filtered_commands = self._commands.copy()

    def remove_command(self, command_id: str) -> bool:
        """Удаляет команду из палитры.

        Args:
            command_id: ID команды для удаления

        Returns:
            True если команда удалена, False если не найдена
        """
        for i, cmd in enumerate(self._commands):
            if cmd.id == command_id:
                self._commands.pop(i)
                self._filtered_commands = self._commands.copy()
                return True
        return False
