"""Карточка отдельного tool call.

Референс OpenCode: packages/web/src/ui/session/tool-call.tsx

Отображает:
- Название инструмента и иконку
- Статус выполнения (pending, running, success, error)
- Параметры вызова
- Expand/collapse для деталей
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Collapsible, Static

from .permission_badge import PermissionBadge

if TYPE_CHECKING:
    from codelab.client.presentation.chat_view_model import ChatViewModel


# Типы статусов tool call
ToolCallStatus = Literal["pending", "running", "success", "error", "cancelled"]


# Иконки для разных типов инструментов
TOOL_ICONS: dict[str, str] = {
    "read_file": "📄",
    "write_file": "✏️",
    "list_files": "📁",
    "create_directory": "📂",
    "delete_file": "🗑️",
    "execute_command": "⚡",
    "terminal": "💻",
    "search": "🔍",
    "default": "🔧",
}

# Иконка для MCP инструментов (определяется по namespace-префиксу)
MCP_TOOL_ICON = "🔌"

# Иконки для статусов
STATUS_ICONS: dict[ToolCallStatus, str] = {
    "pending": "⏳",
    "running": "▶️",
    "success": "✅",
    "error": "❌",
    "cancelled": "⛔",
}


class ToolCallCard(Static):
    """Карточка для отображения отдельного tool call.
    
    Показывает информацию о вызове инструмента с возможностью
    раскрытия деталей (параметры, результат).
    
    Интегрируется с ChatViewModel для получения обновлений статуса.
    
    Пример использования:
        >>> card = ToolCallCard(
        ...     tool_call_id="call_123",
        ...     tool_name="read_file",
        ...     parameters={"path": "/home/user/file.txt"},
        ...     status="running",
        ... )
    """

    # Сообщение о клике на карточку
    class Selected(Message):
        """Событие выбора карточки."""
        
        def __init__(self, card: ToolCallCard) -> None:
            """Создать событие выбора.
            
            Args:
                card: Выбранная карточка
            """
            self.card = card
            self.tool_call_id = card.tool_call_id
            super().__init__()

    DEFAULT_CSS = """
    ToolCallCard {
        width: 100%;
        height: auto;
        background: $surface;
        border: round $primary 50%;
        padding: 1;
        margin: 0 0 1 0;
    }
    
    ToolCallCard.pending {
        border: round $warning 50%;
    }
    
    ToolCallCard.running {
        border: round $primary;
    }
    
    ToolCallCard.success {
        border: round $success 50%;
    }
    
    ToolCallCard.error {
        border: round $error 50%;
    }
    
    ToolCallCard.cancelled {
        border: round $surface-lighten-2;
    }
    
    #tool-header {
        width: 100%;
        height: 1;
        layout: horizontal;
    }
    
    #tool-icon {
        width: 3;
    }
    
    #tool-name {
        width: 1fr;
        text-style: bold;
    }
    
    #tool-status {
        width: auto;
    }
    
    #tool-params {
        margin-top: 1;
        color: $text-muted;
    }
    
    #tool-result {
        margin-top: 1;
        padding: 1;
        background: $background;
    }
    
    #tool-error {
        margin-top: 1;
        padding: 1;
        background: $error 20%;
        color: $error;
    }
    
    #tool-actions {
        margin-top: 1;
    }
    """

    def __init__(
        self,
        tool_call_id: str,
        tool_name: str,
        *,
        parameters: dict[str, Any] | None = None,
        status: ToolCallStatus = "pending",
        result: str | None = None,
        error: str | None = None,
        chat_vm: ChatViewModel | None = None,
        name: str | None = None,
        id: str | None = None,  # noqa: A002
        classes: str | None = None,
    ) -> None:
        """Создаёт карточку tool call.
        
        Args:
            tool_call_id: Уникальный ID вызова инструмента
            tool_name: Название инструмента
            parameters: Параметры вызова
            status: Текущий статус выполнения
            result: Результат выполнения (если завершён успешно)
            error: Сообщение об ошибке (если завершился с ошибкой)
            chat_vm: ChatViewModel для получения обновлений
            name: Имя виджета
            id: ID виджета
            classes: Дополнительные CSS классы
        """
        # Формируем CSS классы с учётом статуса
        css_classes = status
        if classes:
            css_classes = f"{status} {classes}"
        
        super().__init__(name=name, id=id or f"tool-{tool_call_id}", classes=css_classes)
        
        self._tool_call_id = tool_call_id
        self._tool_name = tool_name
        self._parameters = parameters or {}
        self._status = status
        self._result = result
        self._error = error
        self._chat_vm = chat_vm
        self._expanded = False
    
    @property
    def tool_call_id(self) -> str:
        """ID вызова инструмента."""
        return self._tool_call_id
    
    @property
    def tool_name(self) -> str:
        """Название инструмента."""
        return self._tool_name
    
    @property
    def status(self) -> ToolCallStatus:
        """Текущий статус выполнения."""
        return self._status
    
    @status.setter
    def status(self, value: ToolCallStatus) -> None:
        """Установить новый статус.
        
        Args:
            value: Новый статус
        """
        # Удаляем старый класс статуса
        self.remove_class(self._status)
        
        # Устанавливаем новый
        self._status = value
        self.add_class(value)
        
        # Обновляем отображение статуса
        try:
            status_widget = self.query_one("#tool-status", PermissionBadge)
            # Мапим статус tool call на статус permission badge
            badge_status = "granted" if value == "success" else \
                          "denied" if value == "error" else \
                          "pending"
            status_widget.status = badge_status
        except Exception:
            pass  # Виджет ещё не смонтирован
    
    @property
    def result(self) -> str | None:
        """Результат выполнения."""
        return self._result
    
    @result.setter
    def result(self, value: str | None) -> None:
        """Установить результат выполнения.
        
        Args:
            value: Результат или None
        """
        self._result = value
        try:
            result_widget = self.query_one("#tool-result", Static)
            if value:
                result_widget.update(self._truncate(value, 200))
                result_widget.display = True
            else:
                result_widget.display = False
        except Exception:
            pass
    
    @property
    def error(self) -> str | None:
        """Сообщение об ошибке."""
        return self._error
    
    @error.setter
    def error(self, value: str | None) -> None:
        """Установить сообщение об ошибке.
        
        Args:
            value: Текст ошибки или None
        """
        self._error = value
        try:
            error_widget = self.query_one("#tool-error", Static)
            if value:
                error_widget.update(f"Ошибка: {value}")
                error_widget.display = True
            else:
                error_widget.display = False
        except Exception:
            pass
    
    def compose(self) -> ComposeResult:
        """Создаёт структуру карточки."""
        # Определяем иконку инструмента
        # MCP инструменты детектируются по namespace-префиксу "mcp:"
        if self._tool_name.startswith("mcp:"):
            icon = MCP_TOOL_ICON
        else:
            icon = TOOL_ICONS.get(self._tool_name, TOOL_ICONS["default"])
        
        # Заголовок с иконкой, названием и статусом
        with Vertical(id="tool-header"):
            yield Static(icon, id="tool-icon")
            yield Static(self._tool_name, id="tool-name")
            
            # Badge статуса (маппим на permission status)
            badge_status = "granted" if self._status == "success" else \
                          "denied" if self._status == "error" else \
                          "pending"
            yield PermissionBadge(badge_status, show_label=True, id="tool-status")
        
        # Параметры в сворачиваемом блоке
        if self._parameters:
            with Collapsible(title="Параметры", collapsed=not self._expanded):
                params_text = self._format_parameters()
                yield Static(params_text, id="tool-params")
        
        # Результат (изначально скрыт)
        result_widget = Static(
            self._truncate(self._result, 200) if self._result else "",
            id="tool-result",
        )
        result_widget.display = bool(self._result)
        yield result_widget
        
        # Ошибка (изначально скрыта)
        error_widget = Static(
            f"Ошибка: {self._error}" if self._error else "",
            id="tool-error",
        )
        error_widget.display = bool(self._error)
        yield error_widget
    
    def _format_parameters(self) -> str:
        """Форматировать параметры для отображения.
        
        Returns:
            Строка с форматированными параметрами
        """
        lines: list[str] = []
        for key, value in self._parameters.items():
            # Укорачиваем длинные значения
            str_value = str(value)
            if len(str_value) > 50:
                str_value = str_value[:47] + "..."
            lines.append(f"  {key}: {str_value}")
        return "\n".join(lines)
    
    def _truncate(self, text: str | None, max_length: int) -> str:
        """Укоротить текст до максимальной длины.
        
        Args:
            text: Исходный текст
            max_length: Максимальная длина
            
        Returns:
            Укороченный текст с многоточием если нужно
        """
        if not text:
            return ""
        if len(text) <= max_length:
            return text
        return text[:max_length - 3] + "..."
    
    def on_click(self) -> None:
        """Обработчик клика - отправляет событие Selected."""
        self.post_message(self.Selected(self))
    
    def toggle_expanded(self) -> None:
        """Переключить раскрытое/свёрнутое состояние."""
        self._expanded = not self._expanded
        try:
            collapsible = self.query_one(Collapsible)
            collapsible.collapsed = not self._expanded
        except Exception:
            pass
