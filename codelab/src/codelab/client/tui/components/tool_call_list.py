"""Список всех tool calls в рамках turn.

Группировка по статусу и summary.
Референс OpenCode: используется внутри turn компонента.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from .tool_call_card import ToolCallCard, ToolCallStatus

if TYPE_CHECKING:
    from codelab.client.presentation.chat_view_model import ChatViewModel


class ToolCallList(VerticalScroll):
    """Список tool calls с группировкой и summary.
    
    Отображает все вызовы инструментов в рамках turn,
    с возможностью фильтрации и группировки по статусу.
    
    Интегрируется с ChatViewModel для получения обновлений.
    
    Пример использования:
        >>> tool_list = ToolCallList(chat_vm=chat_view_model)
        >>> tool_list.add_tool_call("call_1", "read_file", {"path": "/file.txt"})
        >>> tool_list.update_status("call_1", "success")
    """

    DEFAULT_CSS = """
    ToolCallList {
        width: 100%;
        height: auto;
        max-height: 20;
        background: $surface;
        border: round $primary 30%;
        padding: 1;
    }
    
    #tool-list-header {
        width: 100%;
        height: 1;
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }
    
    #tool-list-summary {
        width: 100%;
        height: 1;
        color: $text-muted;
        margin-bottom: 1;
    }
    
    #tool-list-content {
        width: 100%;
        height: auto;
        background: $background;
    }
    
    .tool-group-header {
        width: 100%;
        height: 1;
        text-style: italic;
        color: $text-muted;
        margin-top: 1;
    }
    """

    def __init__(
        self,
        *,
        chat_vm: ChatViewModel | None = None,
        show_summary: bool = True,
        group_by_status: bool = False,
        name: str | None = None,
        id: str | None = None,  # noqa: A002
        classes: str | None = None,
    ) -> None:
        """Создаёт список tool calls.
        
        Args:
            chat_vm: ChatViewModel для синхронизации
            show_summary: Показывать summary (X completed, Y pending)
            group_by_status: Группировать по статусу
            name: Имя виджета
            id: ID виджета
            classes: Дополнительные CSS классы
        """
        super().__init__(name=name, id=id, classes=classes)
        
        self._chat_vm = chat_vm
        self._show_summary = show_summary
        self._group_by_status = group_by_status
        
        # Хранилище tool calls
        self._tool_calls: dict[str, dict[str, Any]] = {}
        self._cards: dict[str, ToolCallCard] = {}
        
        # Подписываемся на изменения ChatViewModel
        if chat_vm:
            chat_vm.tool_calls.subscribe(self._on_tool_calls_changed)
    
    def compose(self) -> ComposeResult:
        """Создаёт структуру списка."""
        yield Static("🔧 Tool Calls", id="tool-list-header")
        
        if self._show_summary:
            yield Static(self._format_summary(), id="tool-list-summary")
        
        with Vertical(id="tool-list-content"):
            # Изначально пустой контейнер
            pass
    
    def _format_summary(self) -> str:
        """Форматировать summary статистику.
        
        Returns:
            Строка вида "3 completed, 1 running, 2 pending"
        """
        if not self._tool_calls:
            return "Нет активных вызовов"
        
        # Подсчитываем по статусам
        counts: dict[str, int] = {}
        for tc in self._tool_calls.values():
            status = tc.get("status", "pending")
            counts[status] = counts.get(status, 0) + 1
        
        # Форматируем
        parts: list[str] = []
        if counts.get("success", 0):
            parts.append(f"✅ {counts['success']} completed")
        if counts.get("running", 0):
            parts.append(f"▶️ {counts['running']} running")
        if counts.get("pending", 0):
            parts.append(f"⏳ {counts['pending']} pending")
        if counts.get("error", 0):
            parts.append(f"❌ {counts['error']} failed")
        
        return ", ".join(parts) if parts else "Нет активных вызовов"
    
    def _on_tool_calls_changed(self, tool_calls: list) -> None:
        """Обработчик изменения списка tool calls в ViewModel.
        
        Args:
            tool_calls: Новый список tool calls
        """
        # Обновляем каждый tool call
        for tc in tool_calls:
            # Поддержка как словарей (из ChatViewModel), так и объектов
            if isinstance(tc, dict):
                tc_id = tc.get("toolCallId") or str(tc)[:20]
                tc_name = tc.get("title") or tc.get("name") or "unknown"
                raw_status = tc.get("status") or "pending"
                tc_params = tc.get("parameters") or tc.get("rawInput") or {}
            else:
                tc_id = getattr(tc, "id", None) or str(tc)[:20]
                tc_name = getattr(tc, "name", "unknown")
                raw_status = getattr(tc, "status", "pending")
                tc_params = getattr(tc, "parameters", {})
            
            # Маппинг статусов протокола на внутренние статусы
            # Протокол: pending, in_progress, completed, failed
            # Внутренние: pending, running, success, error, cancelled
            status_map = {
                "in_progress": "running",
                "completed": "success",
                "failed": "error",
            }
            tc_status = status_map.get(raw_status, raw_status)
            
            if tc_id not in self._tool_calls:
                # Новый tool call
                self.add_tool_call(tc_id, tc_name, tc_params, tc_status)
            else:
                # Обновляем статус существующего
                self.update_status(tc_id, tc_status)
        
        # Обновляем summary
        self._update_summary()
    
    def add_tool_call(
        self,
        tool_call_id: str,
        tool_name: str,
        parameters: dict[str, Any] | None = None,
        status: ToolCallStatus = "pending",
    ) -> ToolCallCard:
        """Добавить новый tool call в список.
        
        Args:
            tool_call_id: Уникальный ID вызова
            tool_name: Название инструмента
            parameters: Параметры вызова
            status: Начальный статус
            
        Returns:
            Созданная карточка ToolCallCard
        """
        # Сохраняем данные
        self._tool_calls[tool_call_id] = {
            "name": tool_name,
            "parameters": parameters or {},
            "status": status,
        }
        
        # Создаём карточку
        card = ToolCallCard(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            parameters=parameters,
            status=status,
            chat_vm=self._chat_vm,
        )
        
        self._cards[tool_call_id] = card
        
        # Монтируем в контейнер
        try:
            content = self.query_one("#tool-list-content", Vertical)
            content.mount(card)
        except Exception:
            pass
        
        # Обновляем summary
        self._update_summary()
        
        return card
    
    def update_status(
        self,
        tool_call_id: str,
        status: ToolCallStatus,
        *,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """Обновить статус tool call.
        
        Args:
            tool_call_id: ID вызова
            status: Новый статус
            result: Результат выполнения (опционально)
            error: Сообщение об ошибке (опционально)
        """
        if tool_call_id not in self._tool_calls:
            return
        
        # Обновляем данные
        self._tool_calls[tool_call_id]["status"] = status
        
        # Обновляем карточку
        card = self._cards.get(tool_call_id)
        if card:
            card.status = status
            if result is not None:
                card.result = result
            if error is not None:
                card.error = error
        
        # Обновляем summary
        self._update_summary()
    
    def remove_tool_call(self, tool_call_id: str) -> None:
        """Удалить tool call из списка.
        
        Args:
            tool_call_id: ID вызова для удаления
        """
        self._tool_calls.pop(tool_call_id, None)
        card = self._cards.pop(tool_call_id, None)
        if card:
            card.remove()
        
        self._update_summary()
    
    def clear(self) -> None:
        """Очистить список tool calls."""
        self._tool_calls.clear()
        
        for card in self._cards.values():
            card.remove()
        self._cards.clear()
        
        self._update_summary()
    
    def _update_summary(self) -> None:
        """Обновить текст summary."""
        if not self._show_summary:
            return
        
        try:
            summary = self.query_one("#tool-list-summary", Static)
            summary.update(self._format_summary())
        except Exception:
            pass
    
    def get_tool_call(self, tool_call_id: str) -> dict[str, Any] | None:
        """Получить данные tool call по ID.
        
        Args:
            tool_call_id: ID вызова
            
        Returns:
            Словарь с данными или None
        """
        return self._tool_calls.get(tool_call_id)
    
    @property
    def count(self) -> int:
        """Количество tool calls в списке."""
        return len(self._tool_calls)
    
    @property
    def pending_count(self) -> int:
        """Количество ожидающих tool calls."""
        return sum(
            1 for tc in self._tool_calls.values()
            if tc.get("status") in ("pending", "running")
        )
    
    @property
    def completed_count(self) -> int:
        """Количество завершённых tool calls."""
        return sum(
            1 for tc in self._tool_calls.values()
            if tc.get("status") == "success"
        )
    
    @property
    def failed_count(self) -> int:
        """Количество неудачных tool calls."""
        return sum(
            1 for tc in self._tool_calls.values()
            if tc.get("status") == "error"
        )
