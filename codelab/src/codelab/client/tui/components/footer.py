"""Нижняя строка статуса приложения с MVVM интеграцией.

Референс: OpenCode packages/web/src/ui/footer.tsx

Отвечает за:
- Hotkey hints (подсказки по горячим клавишам)
- Статус агента (thinking, idle)
- Токены/стоимость
- Отображение ошибок и уведомлений
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from textual.widgets import Static

if TYPE_CHECKING:
    from codelab.client.presentation.ui_view_model import ConnectionStatus, UIViewModel


class AgentStatus(Enum):
    """Статус агента."""

    IDLE = "idle"
    THINKING = "thinking"
    EXECUTING = "executing"
    WAITING = "waiting"


class FooterBar(Static):
    """Нижняя строка статуса с MVVM интеграцией.

    Структура по образцу OpenCode:
    - Left: hotkey hints (F1 help, ? hotkeys, etc.)
    - Center: статус агента (idle/thinking/executing)
    - Right: токены и стоимость запроса

    Обязательно требует UIViewModel для работы. Подписывается на Observable свойства:
    - connection_status: статус соединения
    - error_message: последняя ошибка
    - info_message: информационное сообщение
    - warning_message: предупреждение
    - is_loading: индикатор загрузки

    Примеры использования:
        >>> from codelab.client.presentation.ui_view_model import UIViewModel
        >>> ui_vm = UIViewModel(event_bus)
        >>> footer = FooterBar(ui_vm)
        >>>
        >>> # Когда UIViewModel обновляется, footer обновляется автоматически
        >>> ui_vm.error_message.value = "Connection failed"
    """

    # Конфигурация hotkeys для отображения
    DEFAULT_HOTKEYS = [
        ("F1", "help"),
        ("?", "hotkeys"),
        ("Ctrl+B", "sidebar"),
        ("Ctrl+N", "new"),
        ("Ctrl+Q", "quit"),
    ]

    def __init__(
        self,
        ui_vm: UIViewModel,
        *,
        show_tokens: bool = True,
        show_hotkeys: bool = True,
        theme_manager: object | None = None,
    ) -> None:
        """Инициализирует FooterBar с обязательным UIViewModel.

        Args:
            ui_vm: UIViewModel для управления состояниями
            show_tokens: Показывать ли токены/стоимость
            show_hotkeys: Показывать ли подсказки по горячим клавишам
            theme_manager: ThemeManager для отображения текущей темы
        """
        super().__init__("", id="footer")
        self.ui_vm = ui_vm
        self._show_tokens = show_tokens
        self._show_hotkeys = show_hotkeys
        self._theme_manager = theme_manager
        self._agent_status = AgentStatus.IDLE
        self._tokens_used: int = 0
        self._cost: float = 0.0

        # Подписываемся на изменения в UIViewModel
        self.ui_vm.connection_status.subscribe(self._on_connection_status_changed)
        self.ui_vm.is_loading.subscribe(self._on_loading_changed)
        self.ui_vm.loading_message.subscribe(self._on_loading_message_changed)
        self.ui_vm.error_message.subscribe(self._on_error_message_changed)
        self.ui_vm.info_message.subscribe(self._on_info_message_changed)
        self.ui_vm.warning_message.subscribe(self._on_warning_message_changed)

        # Инициализируем UI с текущим состоянием
        self._update_display()

    def _on_connection_status_changed(self, status: object) -> None:
        """Обновить footer при изменении статуса соединения.

        Args:
            status: Новый статус соединения
        """
        self._update_display()

    def _on_loading_changed(self, is_loading: bool) -> None:
        """Обновить footer при изменении глобальной загрузки.

        Args:
            is_loading: True если идет загрузка
        """
        # Обновляем статус агента на основе загрузки
        if is_loading:
            self._agent_status = AgentStatus.THINKING
        else:
            self._agent_status = AgentStatus.IDLE
        self._update_display()

    def _on_loading_message_changed(self, message: str | None) -> None:
        """Обновить footer при изменении сообщения загрузки.

        Args:
            message: Сообщение о загрузке
        """
        self._update_display()

    def _on_error_message_changed(self, message: str | None) -> None:
        """Обновить footer при появлении ошибки.

        Args:
            message: Текст ошибки или None
        """
        self._update_display()

    def _on_info_message_changed(self, message: str | None) -> None:
        """Обновить footer при появлении информационного сообщения.

        Args:
            message: Информационное сообщение или None
        """
        self._update_display()

    def _on_warning_message_changed(self, message: str | None) -> None:
        """Обновить footer при появлении предупреждения.

        Args:
            message: Текст предупреждения или None
        """
        self._update_display()

    def _update_display(self) -> None:
        """Обновить отображение footer'а на основе текущего состояния UIViewModel."""
        if self.ui_vm is None:
            return

        # Приоритет: ошибка > предупреждение > информация > статус
        if self.ui_vm.error_message.value:
            display_text = f"❌ Error: {self.ui_vm.error_message.value}"
        elif self.ui_vm.warning_message.value:
            display_text = f"⚠️  Warning: {self.ui_vm.warning_message.value}"
        elif self.ui_vm.info_message.value:
            display_text = f"ℹ️  {self.ui_vm.info_message.value}"
        else:
            display_text = self._build_status_line()

        self.update(display_text)

    def _build_status_line(self) -> str:
        """Собрать основную статусную строку."""
        parts = []

        # Левая часть: hotkeys
        if self._show_hotkeys:
            hotkeys_text = self._build_hotkeys_text()
            parts.append(hotkeys_text)

        # Центр: статус агента с индикатором соединения
        status_text = self._build_agent_status_text()
        parts.append(status_text)

        # Правая часть: токены/стоимость
        if self._show_tokens and (self._tokens_used > 0 or self._cost > 0):
            tokens_text = self._build_tokens_text()
            parts.append(tokens_text)

        # Тема (справа)
        theme_text = self._build_theme_text()
        if theme_text:
            parts.append(theme_text)

        return " │ ".join(parts)

    def _build_hotkeys_text(self) -> str:
        """Собрать текст с подсказками по горячим клавишам."""
        hotkey_parts = []
        for key, label in self.DEFAULT_HOTKEYS[:4]:  # Показываем максимум 4
            hotkey_parts.append(f"{key} {label}")
        return " | ".join(hotkey_parts)

    def _build_agent_status_text(self) -> str:
        """Собрать текст статуса агента."""
        connection_status = self.ui_vm.connection_status.value
        status_prefix = self._status_prefix(connection_status)

        # Статус агента с иконкой
        agent_icons = {
            AgentStatus.IDLE: "○",
            AgentStatus.THINKING: "◐",
            AgentStatus.EXECUTING: "●",
            AgentStatus.WAITING: "◑",
        }
        agent_icon = agent_icons.get(self._agent_status, "○")

        # Если есть сообщение загрузки - показываем его
        if self.ui_vm.is_loading.value:
            loading_msg = self.ui_vm.loading_message.value or "processing..."
            return f"{status_prefix} {agent_icon} {loading_msg}"

        return f"{status_prefix} {connection_status.value}"

    def _build_tokens_text(self) -> str:
        """Собрать текст с информацией о токенах и стоимости."""
        parts = []
        if self._tokens_used > 0:
            parts.append(f"🎯 {self._tokens_used:,} tokens")
        if self._cost > 0:
            parts.append(f"💰 ${self._cost:.4f}")
        return " ".join(parts)

    @staticmethod
    def _status_prefix(status: ConnectionStatus) -> str:
        """Вернуть короткий индикатор для статуса подключения.

        Args:
            status: Статус соединения

        Returns:
            Символ индикатора
        """
        if status.value == "connected":
            return "✓"
        if status.value in {"connecting", "reconnecting"}:
            return "⟳"
        if status.value == "error":
            return "✗"
        return "○"

    def _build_theme_text(self) -> str:
        """Собрать текст с текущей темой.

        Returns:
            Текст с иконкой темы или пустую строку.
        """
        if self._theme_manager is None:
            return ""

        try:
            theme_name = self._theme_manager.current_theme_name
            if theme_name == "dark":
                return "🌙 Dark"
            else:
                return "☀️ Light"
        except AttributeError:
            return ""

    def set_agent_status(self, status: AgentStatus) -> None:
        """Установить статус агента.

        Args:
            status: Новый статус агента
        """
        self._agent_status = status
        self._update_display()

    def update_tokens(self, tokens: int, cost: float = 0.0) -> None:
        """Обновить информацию о токенах и стоимости.

        Args:
            tokens: Количество использованных токенов
            cost: Стоимость запроса в долларах
        """
        self._tokens_used = tokens
        self._cost = cost
        self._update_display()
