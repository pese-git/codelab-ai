"""Поле ввода пользовательского промпта с MVVM интеграцией.

Отвечает за:
- Ввод текста пользователя для отправки к модели
- Отправку prompt через ChatViewModel
- Управление историей промптов по сессиям
- Отключение/включение при streaming
- Кнопка отправки сообщения
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, TextArea

if TYPE_CHECKING:
    from codelab.client.presentation.chat_view_model import ChatViewModel

logger = structlog.get_logger("prompt_input")


class PromptTextArea(TextArea):
    """Многострочное поле ввода текста промпта."""

    def __init__(self) -> None:
        """Инициализирует поле ввода."""
        super().__init__(id="prompt-textarea")

    async def _on_key(self, event: events.Key) -> None:
        """Обработка клавиш: Ctrl+Enter отправляет, Enter - новая строка."""
        # Ctrl+Enter - отправка сообщения через родителя
        key = event.key
        if key in ("ctrl+enter", "ctrl+j", "ctrl+m"):
            # Находим родительский PromptInput и вызываем action_submit
            parent = self.parent
            while parent is not None:
                if isinstance(parent, PromptInput):
                    parent.action_submit()
                    event.prevent_default()
                    event.stop()
                    return
                parent = parent.parent
        # Вызываем родительский обработчик для стандартной обработки
        await super()._on_key(event)


class PromptInput(Horizontal):
    """Компонент ввода промпта с кнопкой отправки.
    
    Обязательно требует ChatViewModel для работы. Подписывается на Observable свойства:
    - is_streaming: флаг для disable/enable поля при streaming
    
    Примеры использования:
        >>> from codelab.client.presentation.chat_view_model import ChatViewModel
        >>> chat_vm = ChatViewModel(coordinator, event_bus)
        >>> prompt_input = PromptInput(chat_vm)
        >>> 
        >>> # При streaming, поле ввода будет отключено
        >>> chat_vm.is_streaming.value = True
    """

    BINDINGS = [
        ("ctrl+enter", "submit", "Send"),
        ("ctrl+up", "history_previous", "Prev Prompt"),
        ("ctrl+down", "history_next", "Next Prompt"),
    ]

    class Submitted(Message):
        """Событие отправки текущего текста из поля ввода."""

        def __init__(self, text: str) -> None:
            """Сохраняет текст отправленного сообщения."""
            super().__init__()
            self.text = text

    class Cancelled(Message):
        """Событие отмены текущего запроса."""

    def __init__(self, chat_vm: ChatViewModel) -> None:
        """Инициализирует PromptInput с обязательным ChatViewModel.
        
        Args:
            chat_vm: ChatViewModel для управления состоянием
        """
        super().__init__(id="prompt-input")
        self.chat_vm = chat_vm
        self._active_session_id: str | None = None
        self._history_by_session: dict[str, list[str]] = {}
        self._history_index: int | None = None
        self._draft_text: str = ""
        self._text_area: PromptTextArea | None = None
        self._submit_button: Button | None = None
        self._stop_button: Button | None = None

        # Подписываемся на изменения в ChatViewModel
        self.chat_vm.is_streaming.subscribe(self._on_streaming_changed)

    DEFAULT_CSS = """
    PromptInput {
        background: $background;
    }
    """

    def compose(self) -> ComposeResult:
        """Создаёт поле ввода и кнопки Send/Stop."""
        self._text_area = PromptTextArea()
        self._text_area.border_title = "Prompt"
        self._text_area.tooltip = "Ctrl+Enter - отправить, Ctrl+Up/Down - история"
        yield self._text_area

        self._submit_button = Button("Send", id="submit-button", variant="primary")
        yield self._submit_button

        self._stop_button = Button("Stop", id="stop-button", variant="error")
        yield self._stop_button

    def on_mount(self) -> None:
        """Скрываем Stop при монтировании — агент ещё не запущен."""
        if self._stop_button is not None:
            self._stop_button.display = False

    @property
    def text(self) -> str:
        """Возвращает текст из поля ввода."""
        if self._text_area is not None:
            return self._text_area.text
        return ""

    @text.setter
    def text(self, value: str) -> None:
        """Устанавливает текст в поле ввода."""
        if self._text_area is not None:
            self._text_area.text = value

    def set_active_session(self, session_id: str | None) -> None:
        """Переключает активный контекст истории промптов для текущей сессии."""
        self._active_session_id = session_id
        self._history_index = None
        self._draft_text = ""

    def remember_prompt(self, text: str) -> None:
        """Сохраняет отправленный prompt в историю активной сессии."""
        normalized = text.strip()
        if not normalized:
            return
        history = self._active_history()
        if history and history[-1] == normalized:
            return
        history.append(normalized)
        if len(history) > 100:
            del history[0]
        self._history_index = None
        self._draft_text = ""

    def action_submit(self) -> None:
        """Отправляет текст, если поле не пустое."""
        normalized = self.text.strip()
        if not normalized:
            return
        self.post_message(self.Submitted(normalized))

    def action_history_previous(self) -> None:
        """Подставляет предыдущий prompt из истории активной сессии."""
        history = self._active_history()
        if not history:
            return
        if self._history_index is None:
            self._draft_text = self.text
            self._history_index = len(history) - 1
        elif self._history_index > 0:
            self._history_index -= 1
        self.text = history[self._history_index]

    def action_history_next(self) -> None:
        """Переходит к более новому prompt или возвращает сохраненный черновик."""
        history = self._active_history()
        if not history or self._history_index is None:
            return
        if self._history_index < len(history) - 1:
            self._history_index += 1
            self.text = history[self._history_index]
            return
        self._history_index = None
        self.text = self._draft_text
        self._draft_text = ""

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Обработка нажатия кнопок Send и Stop."""
        logger.debug("button_pressed", button_id=event.button.id)
        if event.button.id == "submit-button":
            self.action_submit()
        elif event.button.id == "stop-button":
            # Скрываем кнопку немедленно — до обработки сообщения Textual может
            # поставить несколько Cancelled в очередь если кнопка нажата дважды.
            if self._stop_button is not None:
                self._stop_button.display = False
            if self._submit_button is not None:
                self._submit_button.display = True
            logger.info("stop_button_pressed_posting_cancelled")
            self.post_message(self.Cancelled())

    def _on_streaming_changed(self, is_streaming: bool) -> None:
        """Переключает Send↔Stop и блокирует поле ввода при streaming."""
        logger.debug(
            "streaming_changed",
            is_streaming=is_streaming,
            submit_mounted=self._submit_button is not None,
            stop_mounted=self._stop_button is not None,
        )
        if self._text_area is not None:
            self._text_area.disabled = is_streaming
        if self._submit_button is not None:
            self._submit_button.display = not is_streaming
        if self._stop_button is not None:
            self._stop_button.display = is_streaming

    def _active_history(self) -> list[str]:
        """Возвращает список истории для активной сессии."""
        history_key = self._active_session_id or "__default__"
        if history_key not in self._history_by_session:
            self._history_by_session[history_key] = []
        return self._history_by_session[history_key]
