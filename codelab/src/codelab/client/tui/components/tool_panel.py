"""Панель отображения вызовов инструментов с MVVM интеграцией.

Отвечает за:
- Отображение статуса выполнения tool calls
- Показ результатов выполнения инструментов
- Интеграция с ChatViewModel для синхронизации tool calls
- Отображение прогресса выполнения tool calls через ProgressBar
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from codelab.client.messages import ToolCallUpdate

from .progress import ProgressBar, ProgressVariant
from .terminal_output import TerminalOutputPanel
from .tool_call_list import ToolCallList

if TYPE_CHECKING:
    from codelab.client.presentation.chat_view_model import ChatViewModel
    from codelab.client.presentation.terminal_view_model import TerminalViewModel


class ToolPanel(Vertical):
    """Панель tool calls с MVVM интеграцией и прогресс-баром.
    
    Обязательно требует ChatViewModel для работы. Подписывается на Observable свойства:
    - tool_calls: список активных tool calls
    
    Включает ProgressBar для визуализации прогресса выполнения tool calls.
    
    Примеры использования:
        >>> from codelab.client.presentation.chat_view_model import ChatViewModel
        >>> chat_vm = ChatViewModel(coordinator, event_bus)
        >>> tool_panel = ToolPanel(chat_vm)
        >>> 
        >>> # Когда ChatViewModel обновляется, панель обновляется автоматически
        >>> chat_vm.tool_calls.value = [tool_call1, tool_call2]
    """

    DEFAULT_CSS = """
    ToolPanel {
        height: 1fr;
        background: $background;
    }
    
    ToolPanel #tool-call-list {
        height: auto;
        max-height: 12;
    }
    
    ToolPanel #tool-list {
        height: auto;
        display: none;  /* Скрываем текстовый список, используем ToolCallList */
        background: $background;
    }
    
    ToolPanel #tool-progress {
        height: 3;
    }
    """

    def __init__(
        self,
        chat_vm: ChatViewModel,
        terminal_vm: TerminalViewModel,
    ) -> None:
        """Инициализирует ToolPanel с обязательными ViewModels.
        
        Args:
            chat_vm: ChatViewModel для управления tool calls
            terminal_vm: TerminalViewModel для управления output панелями
        """
        super().__init__(id="tool-panel")
        self.chat_vm = chat_vm
        self._terminal_vm = terminal_vm
        self._tool_calls: dict[str, dict[str, Any]] = {}
        
        # Подписываемся на изменения в ChatViewModel
        self.chat_vm.tool_calls.subscribe(self._on_tool_calls_changed)

    def compose(self) -> ComposeResult:
        """Создаёт содержимое панели: ToolCallList, список tool calls и прогресс-бар."""
        # ToolCallList для отображения карточек tool calls
        # Автоматически подписывается на chat_vm.tool_calls
        yield ToolCallList(
            chat_vm=self.chat_vm,
            show_summary=True,
            group_by_status=False,
            id="tool-call-list",
        )
        # Текстовый список для совместимости со старым API
        yield Static("Инструменты: нет активных вызовов", id="tool-list")
        yield ProgressBar(
            variant=ProgressVariant.PRIMARY,
            show_label=True,
            label_format="{current}/{total}",
            id="tool-progress",
        )

    def on_mount(self) -> None:
        """При монтировании скрываем прогресс-бар по умолчанию."""
        self._update_progress_visibility(show=False)

    def render(self) -> Text:
        """Рендерит текстовое содержимое панели для совместимости с тестами.
        
        Returns:
            Text объект с содержимым tool-list виджета
        """
        return Text(self._render_text())

    @property
    def _tool_list(self) -> Static:
        """Возвращает виджет списка tool calls."""
        return self.query_one("#tool-list", Static)

    @property
    def _progress_bar(self) -> ProgressBar:
        """Возвращает виджет прогресс-бара."""
        return self.query_one("#tool-progress", ProgressBar)

    @property
    def _tool_call_list(self) -> ToolCallList:
        """Возвращает виджет ToolCallList."""
        return self.query_one("#tool-call-list", ToolCallList)

    def _on_tool_calls_changed(self, tool_calls: list) -> None:
        """Обновить панель при изменении tool calls.
        
        Args:
            tool_calls: Новый список tool calls
        """
        # Маппинг статусов протокола на внутренние статусы ToolCallCard
        status_map = {
            "in_progress": "running",
            "completed": "success",
            "failed": "error",
        }
        
        # Синхронизируем с ToolCallList
        try:
            tool_call_list = self._tool_call_list
            for tc in tool_calls:
                # Поддержка как словарей (из ChatViewModel), так и объектов
                if isinstance(tc, dict):
                    tc_id = tc.get("toolCallId") or str(tc)[:20]
                    tc_name = tc.get("title") or tc.get("name") or "unknown"
                    raw_status = tc.get("status") or "pending"
                else:
                    tc_id = getattr(tc, "id", None) or str(tc)[:20]
                    tc_name = getattr(tc, "name", "unknown")
                    raw_status = getattr(tc, "status", "pending")
                mapped_status = status_map.get(raw_status, raw_status)
                
                if tc_id not in tool_call_list._tool_calls:  # noqa: SLF001
                    tool_call_list.add_tool_call(tc_id, tc_name, {}, mapped_status)
                else:
                    tool_call_list.update_status(tc_id, mapped_status)
        except Exception:
            pass  # ToolCallList ещё не смонтирован
        
        # Обновляем отображение на основе новых tool calls
        if not tool_calls:
            try:
                self._tool_list.update("Инструменты: нет активных вызовов")
                self._update_progress_visibility(show=False)
            except Exception:
                pass  # Виджеты ещё не смонтированы
        else:
            # Формируем текст отображения из tool calls
            lines: list[str] = ["Инструменты:"]
            for tool_call in tool_calls[-8:]:  # Показываем последние 8
                # tool_call может быть словарем или объектом
                if isinstance(tool_call, dict):
                    tool_id = tool_call.get("toolCallId") or str(tool_call)[:20]
                    status = tool_call.get("status") or "pending"
                else:
                    tool_id = getattr(tool_call, "id", str(tool_call)[:20])
                    status = getattr(tool_call, "status", "pending")
                lines.append(f"- {tool_id} [{status}]")
            try:
                self._tool_list.update("\n".join(lines))
                self._update_progress_from_calls(tool_calls)
            except Exception:
                pass  # Виджеты ещё не смонтированы

    def _get_tc_status(self, tc: dict | Any) -> str:
        """Извлекает статус из tool call (dict или объект).
        
        Args:
            tc: Tool call (словарь или объект)
            
        Returns:
            Статус tool call
        """
        if isinstance(tc, dict):
            return tc.get("status") or ""
        return getattr(tc, "status", "")

    def _update_progress_from_calls(self, tool_calls: list) -> None:
        """Обновляет прогресс-бар на основе статусов tool calls.
        
        Args:
            tool_calls: Список tool calls
        """
        if not tool_calls:
            self._update_progress_visibility(show=False)
            return

        total = len(tool_calls)
        completed = sum(
            1 for tc in tool_calls
            if self._get_tc_status(tc) in ("completed", "success", "error", "failed")
        )
        
        # Показываем прогресс если есть активные tool calls
        self._update_progress_visibility(show=completed < total)
        
        try:
            progress_bar = self._progress_bar
            progress_bar.set_steps(completed, total)
            
            # Меняем цвет в зависимости от состояния
            has_errors = any(
                self._get_tc_status(tc) in ("error", "failed")
                for tc in tool_calls
            )
            if has_errors:
                progress_bar.set_variant(ProgressVariant.WARNING)
            elif completed == total:
                progress_bar.set_variant(ProgressVariant.SUCCESS)
            else:
                progress_bar.set_variant(ProgressVariant.PRIMARY)
        except Exception:
            pass  # Виджет ещё не смонтирован

    def _update_progress_visibility(self, *, show: bool) -> None:
        """Показывает или скрывает прогресс-бар.
        
        Args:
            show: True чтобы показать, False чтобы скрыть
        """
        try:
            progress_bar = self._progress_bar
            progress_bar.display = show
        except Exception:
            pass  # Виджет ещё не смонтирован

    def reset(self) -> None:
        """Сбрасывает локальный список вызовов инструментов и ToolCallList."""
        self._tool_calls = {}
        try:
            self._tool_list.update("Инструменты: нет активных вызовов")
            self._tool_call_list.clear()  # Очищаем ToolCallList
            self._update_progress_visibility(show=False)
            self._progress_bar.reset()
        except Exception:
            pass  # Виджеты ещё не смонтированы

    def apply_update(self, update: ToolCallUpdate) -> None:
        """Применяет одно событие tool_call/tool_call_update к панели."""

        payload = update.model_dump()
        tool_call_id = payload.get("toolCallId")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            return

        title = payload.get("title")
        if not isinstance(title, str) or not title:
            title = self._tool_calls.get(tool_call_id, {}).get("title", tool_call_id)

        status = payload.get("status")
        if not isinstance(status, str) or not status:
            status = self._tool_calls.get(tool_call_id, {}).get("status", "pending")

        previous = self._tool_calls.get(tool_call_id, {})
        terminal_id = self._extract_terminal_id(payload)
        if terminal_id is None:
            terminal_id = previous.get("terminal_id")

        output_payload = payload.get("rawOutput")
        output_text, exit_code = self._extract_terminal_output(output_payload)
        terminal_view = previous.get("terminal_view")
        if terminal_view is None:
            # Создаём новую панель вывода терминала с ViewModel
            # show_toolbar=False, так как здесь используется только для render_text()
            terminal_view = TerminalOutputPanel(self._terminal_vm, show_toolbar=False)
        if output_text:
            terminal_view.append_output(output_text)
        if exit_code is not None:
            terminal_view.set_exit_code(exit_code)

        self._tool_calls[tool_call_id] = {
            "title": title,
            "status": status,
            "terminal_id": terminal_id,
            "terminal_view": terminal_view,
        }
        
        # Синхронизируем с ToolCallList
        # Маппинг статусов протокола на внутренние статусы ToolCallCard
        status_map = {
            "in_progress": "running",
            "completed": "success",
            "failed": "error",
        }
        mapped_status = status_map.get(status, status)
        
        try:
            tool_call_list = self._tool_call_list
            if tool_call_id not in tool_call_list._tool_calls:  # noqa: SLF001
                # Новый tool call
                tool_call_list.add_tool_call(tool_call_id, title, {}, mapped_status)
            else:
                # Обновляем статус существующего
                tool_call_list.update_status(tool_call_id, mapped_status)
        except Exception:
            pass  # ToolCallList ещё не смонтирован
        
        try:
            self._tool_list.update(self._render_text())
            self._update_progress_from_tool_calls_dict()
        except Exception:
            pass  # Виджеты ещё не смонтированы

    def _update_progress_from_tool_calls_dict(self) -> None:
        """Обновляет прогресс-бар на основе локального словаря _tool_calls."""
        if not self._tool_calls:
            self._update_progress_visibility(show=False)
            return

        total = len(self._tool_calls)
        completed = sum(
            1 for payload in self._tool_calls.values()
            if payload.get("status") in ("completed", "success", "error", "failed")
        )
        
        # Показываем прогресс если есть незавершённые tool calls
        self._update_progress_visibility(show=completed < total)
        
        try:
            progress_bar = self._progress_bar
            progress_bar.set_steps(completed, total)
            
            # Меняем цвет в зависимости от состояния
            has_errors = any(
                payload.get("status") in ("error", "failed")
                for payload in self._tool_calls.values()
            )
            if has_errors:
                progress_bar.set_variant(ProgressVariant.WARNING)
            elif completed == total:
                progress_bar.set_variant(ProgressVariant.SUCCESS)
            else:
                progress_bar.set_variant(ProgressVariant.PRIMARY)
        except Exception:
            pass  # Виджет ещё не смонтирован

    def _render_text(self) -> str:
        """Формирует компактный список вызовов для отображения в панели."""

        if not self._tool_calls:
            return "Инструменты: нет активных вызовов"

        lines: list[str] = ["Инструменты:"]
        for tool_call_id, payload in list(self._tool_calls.items())[-8:]:
            title = payload["title"]
            status = payload["status"]
            terminal_id = payload.get("terminal_id")
            lines.append(f"- {title} [{status}] ({tool_call_id})")
            if isinstance(terminal_id, str) and terminal_id:
                lines.append(f"  terminal: {terminal_id}")

            terminal_view = payload.get("terminal_view")
            if isinstance(terminal_view, TerminalOutputPanel):
                rendered_output = terminal_view.render_text().plain.strip()
                if rendered_output and rendered_output != "Нет вывода терминала":
                    lines.append(f"  output: {self._shorten_output(rendered_output)}")
        return "\n".join(lines)

    def latest_terminal_snapshot(self) -> tuple[str, str, Text] | None:
        """Возвращает полный вывод последнего tool call с terminal-контентом."""

        for payload in reversed(list(self._tool_calls.values())):
            terminal_id = payload.get("terminal_id")
            terminal_view = payload.get("terminal_view")
            title = payload.get("title")
            if not isinstance(terminal_id, str) or not terminal_id:
                continue
            if not isinstance(terminal_view, TerminalOutputPanel):
                continue
            if not isinstance(title, str) or not title:
                title = "Tool call"
            return title, terminal_id, terminal_view.render_text()
        return None

    @staticmethod
    def _extract_terminal_id(payload: dict[str, Any]) -> str | None:
        """Извлекает terminalId из payload content для tool-call события."""

        content_list = payload.get("content")
        if not isinstance(content_list, list):
            return None
        for content_item in content_list:
            if not isinstance(content_item, dict):
                continue
            if content_item.get("type") != "terminal":
                continue
            terminal_id = content_item.get("terminalId")
            if isinstance(terminal_id, str) and terminal_id:
                return terminal_id
        return None

    @staticmethod
    def _extract_terminal_output(raw_output: Any) -> tuple[str | None, int | None]:
        """Извлекает output и exit code из rawOutput tool-call payload."""

        if not isinstance(raw_output, dict):
            return None, None

        output_text = raw_output.get("output")
        if not isinstance(output_text, str):
            output_text = None
        exit_code = raw_output.get("exitCode")
        if not isinstance(exit_code, int):
            exit_code = None
        return output_text, exit_code

    @staticmethod
    def _shorten_output(output: str) -> str:
        """Обрезает многострочный terminal output для компактного отображения."""

        normalized_output = " ".join(line.strip() for line in output.splitlines() if line.strip())
        if len(normalized_output) <= 140:
            return normalized_output
        return f"{normalized_output[:137]}..."
