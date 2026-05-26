"""Левая панель с краткой информацией о сессиях с MVVM интеграцией.

Отвечает за:
- Отображение списка сессий из SessionViewModel
- Навигацию по сессиям (Up/Down)
- Выбор сессии (Enter)
- Фильтрацию сессий через SearchInput
- Реактивные обновления при изменении состояния
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static

from codelab.client.tui.components.search_input import SearchInput

if TYPE_CHECKING:
    from codelab.client.presentation.session_view_model import SessionViewModel
    from codelab.client.presentation.ui_view_model import UIViewModel

from codelab.client.presentation.ui_view_model import SidebarTab


class Sidebar(Vertical):
    """Панель сессий с MVVM интеграцией и поиском.

    Обязательно требует SessionViewModel для работы. Подписывается на Observable свойства:
    - sessions: список доступных сессий
    - selected_session_id: текущая выбранная сессия
    - is_loading_sessions: флаг загрузки сессий

    Поддерживает фильтрацию сессий через встроенный SearchInput.

    Примеры использования:
        >>> from codelab.client.presentation.session_view_model import SessionViewModel
        >>> session_vm = SessionViewModel(coordinator, event_bus)
        >>> sidebar = Sidebar(session_vm)
        >>>
        >>> # Когда SessionViewModel обновляется, sidebar обновляется автоматически
        >>> session_vm.sessions.value = [session1, session2]
    """

    can_focus = True

    # Текущий фильтр поиска сессий
    search_filter: reactive[str] = reactive("", init=False)

    class SessionSelected(Message):
        """Событие выбора сессии по Enter в sidebar."""

        def __init__(self, session_id: str) -> None:
            """Сохраняет идентификатор выбранной сессии."""
            super().__init__()
            self.session_id = session_id

    def __init__(
        self,
        session_vm: SessionViewModel,
        ui_vm: UIViewModel | None = None,
    ) -> None:
        """Инициализирует Sidebar с обязательным SessionViewModel.

        Args:
            session_vm: SessionViewModel для управления состоянием сессий
            ui_vm: UIViewModel для управления UI состоянием (опционально)
        """
        super().__init__(id="sidebar")
        self.session_vm = session_vm
        self.ui_vm = ui_vm
        self._selected_index: int = 0

        # Подписываемся на изменения в SessionViewModel
        self.session_vm.sessions.subscribe(self._on_sessions_changed)
        self.session_vm.selected_session_id.subscribe(self._on_selected_session_changed)
        self.session_vm.is_loading_sessions.subscribe(self._on_loading_changed)
        if self.ui_vm is not None:
            self.ui_vm.sidebar_tab.subscribe(self._on_sidebar_tab_changed)
            self.ui_vm.sessions_expanded.subscribe(self._on_sessions_expanded_changed)

    DEFAULT_CSS = """
    Sidebar {
        background: $background;
    }
    """

    def compose(self) -> ComposeResult:
        """Создаёт содержимое Sidebar: SearchInput и список сессий."""
        yield SearchInput(
            placeholder="Поиск сессий...",
            debounce=0.2,
            id="sidebar-search",
        )
        yield Static("", id="sidebar-sessions-list")

    def _on_sessions_changed(self, sessions: list) -> None:
        """Обновить sidebar при изменении списка сессий.

        Args:
            sessions: Новый список сессий
        """
        # Синхронизировать выделение с выбранной сессией
        self._sync_selected_index()
        self._update_display()

    def _on_selected_session_changed(self, session_id: str | None) -> None:
        """Обновить sidebar при изменении выбранной сессии.

        Args:
            session_id: ID выбранной сессии или None
        """
        self._sync_selected_index()
        self._update_display()

    def _on_loading_changed(self, is_loading: bool) -> None:
        """Обновить sidebar при изменении статуса загрузки.

        Args:
            is_loading: True если идет загрузка, False иначе
        """
        self._update_display()

    def _on_sidebar_tab_changed(self, tab: SidebarTab) -> None:
        """Обновить отображение при смене вкладки sidebar."""

        self._update_display()

    def _on_sessions_expanded_changed(self, is_expanded: bool) -> None:
        """Обновить отображение при сворачивании/разворачивании секции."""

        self._update_display()

    def on_mount(self) -> None:
        """Вызывается при монтировании виджета. Инициализирует отображение."""
        self._update_display()

    def _update_display(self) -> None:
        """Обновить отображение sidebar'а на основе текущего состояния."""
        try:
            sessions_list = self.query_one("#sidebar-sessions-list", Static)
            sessions_list.update(self._render_text())
        except Exception:
            # Виджет ещё не смонтирован
            pass

    def on_search_input_search_changed(self, event: SearchInput.SearchChanged) -> None:
        """Обрабатывает изменение поискового запроса.

        Args:
            event: Событие изменения поиска с новым значением
        """
        self.search_filter = event.value
        # Сбрасываем выделение при изменении фильтра
        self._selected_index = 0
        self._update_display()

    def on_search_input_search_cleared(self, event: SearchInput.SearchCleared) -> None:
        """Обрабатывает очистку поискового запроса."""
        self.search_filter = ""
        self._selected_index = 0
        self._update_display()

    def _get_filtered_sessions(self) -> list:
        """Возвращает отфильтрованный список сессий по текущему фильтру.

        Returns:
            Список сессий, соответствующих фильтру поиска
        """
        sessions = self.session_vm.sessions.value
        if not self.search_filter:
            return sessions

        filter_lower = self.search_filter.lower()
        filtered = []
        for session in sessions:
            title = self._extract_session_title(session).lower()
            session_id = self._extract_session_id(session) or ""
            # Ищем совпадение в title или sessionId
            if filter_lower in title or filter_lower in session_id.lower():
                filtered.append(session)
        return filtered

    def select_next(self) -> None:
        """Смещает выделение к следующей сессии (учитывает фильтрацию)."""
        filtered_sessions = self._get_filtered_sessions()
        if not filtered_sessions:
            return

        self._selected_index += 1
        if self._selected_index >= len(filtered_sessions):
            self._selected_index = 0

        # Обновить выбранную сессию в ViewModel
        self._update_selected_session()

    def select_previous(self) -> None:
        """Смещает выделение к предыдущей сессии (учитывает фильтрацию)."""
        filtered_sessions = self._get_filtered_sessions()
        if not filtered_sessions:
            return

        self._selected_index -= 1
        if self._selected_index < 0:
            self._selected_index = len(filtered_sessions) - 1

        # Обновить выбранную сессию в ViewModel
        self._update_selected_session()

    def get_selected_session_id(self) -> str | None:
        """Возвращает sessionId для текущей выделенной строки (учитывает фильтрацию)."""
        filtered_sessions = self._get_filtered_sessions()
        if not filtered_sessions or self._selected_index >= len(filtered_sessions):
            return None
        return self._extract_session_id(filtered_sessions[self._selected_index])

    def _update_selected_session(self) -> None:
        """Обновить выбранную сессию в ViewModel."""
        selected_id = self.get_selected_session_id()
        if selected_id is not None:
            self.session_vm.selected_session_id.value = selected_id
            self._update_display()

    def on_key(self, event: events.Key) -> None:
        """Обрабатывает управление выбором сессии с клавиатуры."""
        if event.key == "up":
            self.select_previous()
            event.stop()
            return
        if event.key == "down":
            self.select_next()
            event.stop()
            return
        if event.key == "enter":
            selected_session_id = self.get_selected_session_id()
            if selected_session_id is not None:
                self.post_message(self.SessionSelected(selected_session_id))
                event.stop()
            return
        if event.key == "space" and self.ui_vm is not None:
            self.ui_vm.toggle_active_sidebar_section()
            event.stop()

    def _render_text(self) -> str:
        """Формирует текстовое представление списка сессий с учётом фильтра."""
        if self.ui_vm is not None:
            active_tab = self.ui_vm.sidebar_tab.value
            if active_tab == SidebarTab.FILES:
                return self._render_files_tab_placeholder()
            if active_tab == SidebarTab.SETTINGS:
                return self._render_settings_tab_placeholder()

        all_sessions = self.session_vm.sessions.value
        is_loading = self.session_vm.is_loading_sessions.value
        selected_id = self.session_vm.selected_session_id.value

        if self.ui_vm is not None and not self.ui_vm.sessions_expanded.value:
            return self._render_collapsed_sessions_view()

        if is_loading:
            return self._with_tabs_header("Сессии загружаются...")

        if not all_sessions:
            return self._with_tabs_header("Сессий пока нет")

        # Получаем отфильтрованные сессии
        filtered_sessions = self._get_filtered_sessions()

        lines: list[str] = [
            self._tabs_header(),
            "",
        ]

        # Показываем информацию о фильтрации если есть фильтр
        if self.search_filter:
            lines.append(f"Найдено: {len(filtered_sessions)} из {len(all_sessions)}")
        else:
            lines.append("Сессии (Up/Down + Enter):")

        if not filtered_sessions and self.search_filter:
            lines.append("Ничего не найдено")
        else:
            for index, session in enumerate(filtered_sessions[:10]):
                session_id = self._extract_session_id(session)
                marker = "*" if session_id == selected_id else " "
                cursor = ">" if index == self._selected_index else " "
                title = self._extract_session_title(session)
                lines.append(f"{cursor}{marker} {title}")

        if self.ui_vm is not None:
            lines.extend(["", "Space - свернуть список"])
        return "\n".join(lines)

    def _tabs_header(self) -> str:
        """Сформировать текстовое меню вкладок sidebar."""

        if self.ui_vm is None:
            return ""

        active_tab = self.ui_vm.sidebar_tab.value
        tab_specs = [
            (SidebarTab.SESSIONS, "Sessions"),
            (SidebarTab.FILES, "Files"),
            (SidebarTab.SETTINGS, "Settings"),
        ]
        items: list[str] = []
        for tab, label in tab_specs:
            marker = "*" if tab == active_tab else " "
            items.append(f"[{marker}{label}]")
        return " ".join(items)

    def _with_tabs_header(self, content: str) -> str:
        """Добавить шапку вкладок к содержимому, если доступно UI-состояние."""

        header = self._tabs_header()
        if not header:
            return content
        return "\n".join([header, "", content])

    def _render_collapsed_sessions_view(self) -> str:
        """Отрисовать свернутое состояние секции сессий."""

        return self._with_tabs_header("Sessions: свернуто (Space - развернуть)")

    def _render_files_tab_placeholder(self) -> str:
        """Отрисовать заглушку вкладки файлов в sidebar."""

        lines = [
            self._tabs_header(),
            "",
            "Файлы отображаются в нижней панели слева.",
            "Tab переключает фокус, Enter открывает файл.",
        ]
        return "\n".join(lines)

    def _render_settings_tab_placeholder(self) -> str:
        """Отрисовать временную вкладку настроек до выделенного экрана."""

        lines = [
            self._tabs_header(),
            "",
            "Settings (MVP):",
            "- F1: контекстная справка",
            "- ?: список горячих клавиш",
            "- Ctrl+Tab: следующая вкладка",
        ]
        return "\n".join(lines)

    def _sync_selected_index(self) -> None:
        """Синхронизирует выделение с выбранной сессией из ViewModel.

        Учитывает текущий фильтр поиска - индекс ищется
        в отфильтрованном списке сессий.
        """
        filtered_sessions = self._get_filtered_sessions()
        selected_id = self.session_vm.selected_session_id.value

        if not filtered_sessions:
            self._selected_index = 0
            return

        if selected_id is None:
            self._selected_index = 0
            return

        # Найти индекс выбранной сессии в отфильтрованном списке
        for index, session in enumerate(filtered_sessions):
            if self._extract_session_id(session) == selected_id:
                self._selected_index = index
                return

        # Если не нашли в отфильтрованном списке, выбрать первую
        self._selected_index = 0

    @staticmethod
    def _extract_session_id(session: Any) -> str | None:
        """Возвращает идентификатор сессии из dict/DTO/entity объектов."""

        if isinstance(session, dict):
            raw_id = session.get("sessionId") or session.get("id")
            return raw_id if isinstance(raw_id, str) else None

        for attribute_name in ("sessionId", "id"):
            if hasattr(session, attribute_name):
                raw_id = getattr(session, attribute_name)
                if isinstance(raw_id, str):
                    return raw_id
        return None

    @classmethod
    def _extract_session_title(cls, session: Any) -> str:
        """Возвращает заголовок сессии или fallback по идентификатору."""

        if isinstance(session, dict):
            raw_title = session.get("title")
            if isinstance(raw_title, str) and raw_title:
                return raw_title
            session_id = cls._extract_session_id(session)
            return session_id or "unknown-session"
        try:
            raw_title = session.title
            if isinstance(raw_title, str) and raw_title:
                return raw_title
        except AttributeError:
            pass
        session_id = cls._extract_session_id(session)
        return session_id or "unknown-session"
