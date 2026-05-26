"""Компонент для отображения истории сообщений с MVVM интеграцией.

Отвечает за:
- Отображение истории сообщений из ChatViewModel
- Отображение streaming текста в реальном времени
- Отображение tool calls
- Реактивные обновления при изменении состояния
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import structlog
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Static

from codelab.client.messages import PermissionOption, PermissionToolCall
from codelab.client.tui.components.message_bubble import MessageBubble, MessageRole
from codelab.client.tui.components.spinner import LoadingIndicator

if TYPE_CHECKING:
    from codelab.client.presentation.chat_view_model import ChatViewModel
    from codelab.client.presentation.permission_view_model import PermissionViewModel
    from codelab.client.tui.components.chat_view_permission_manager import (
        ChatViewPermissionManager,
    )


class ChatView(VerticalScroll):
    """Компонент чата с MVVM интеграцией.

    Обязательно требует ChatViewModel для работы. Подписывается на Observable свойства:
    - messages: история сообщений
    - tool_calls: список tool calls
    - is_streaming: флаг активного streaming
    - streaming_text: текущий streaming текст

    Примеры использования:
        >>> from codelab.client.presentation.chat_view_model import ChatViewModel
        >>> chat_vm = ChatViewModel(coordinator, event_bus)
        >>> chat_view = ChatView(chat_vm)
        >>>
        >>> # Когда ChatViewModel обновляется, chat_view обновляется автоматически
        >>> chat_vm.messages.value = [message1, message2]
    """

    DEFAULT_CSS = """
    ChatView {
        background: $background;
    }
    """

    def __init__(
        self,
        chat_vm: ChatViewModel,
        permission_vm: PermissionViewModel | None = None,
    ) -> None:
        """Инициализирует ChatView с обязательным ChatViewModel.

        Args:
            chat_vm: ChatViewModel для управления состоянием чата
            permission_vm: Опциональный PermissionViewModel для встроенного виджета разрешения
        """
        super().__init__(id="chat_view")
        self.chat_vm = chat_vm
        self._permission_vm = permission_vm
        self._mounted = False
        self._content_container: Container | None = None
        self._loading_indicator: LoadingIndicator | None = None
        self._logger = structlog.get_logger("chat_view")

        # Инициализировать менеджер разрешений если ViewModel доступен
        self._permission_manager: ChatViewPermissionManager | None = None
        if permission_vm is not None:
            from codelab.client.tui.components.chat_view_permission_manager import (
                ChatViewPermissionManager,
            )

            self._permission_manager = ChatViewPermissionManager(self, permission_vm)

        self.chat_vm.messages.subscribe(self._on_messages_changed)
        self.chat_vm.tool_calls.subscribe(self._on_tool_calls_changed)
        self.chat_vm.is_streaming.subscribe(self._on_streaming_changed)
        self.chat_vm.streaming_text.subscribe(self._on_streaming_text_changed)

    def compose(self) -> ComposeResult:
        """Создает внутренний контейнер для контента чата."""
        # Создаем контейнер для динамического добавления виджетов
        self._content_container = Container(id="chat_content")
        yield self._content_container
        # Индикатор загрузки показывается когда агент обрабатывает запрос
        self._loading_indicator = LoadingIndicator(
            text="Агент думает...",
            visible=False,
            id="chat_loading_indicator",
        )
        yield self._loading_indicator

    def on_mount(self) -> None:
        """Вызывается когда компонент смонтирован в приложение."""
        self._mounted = True
        self._update_display()

    def _on_messages_changed(self, messages: list) -> None:
        """Обновить чат при изменении сообщений.

        Args:
            messages: Новый список сообщений
        """
        self._update_display()

    def _on_tool_calls_changed(self, tool_calls: list) -> None:
        """Обновить чат при изменении tool calls.

        Args:
            tool_calls: Новый список tool calls
        """
        self._update_display()

    def _on_streaming_changed(self, is_streaming: bool) -> None:
        """Обновить чат при изменении статуса streaming.

        Args:
            is_streaming: True если идет streaming, False иначе
        """
        # Обновляем видимость индикатора загрузки
        if self._loading_indicator is not None:
            self._loading_indicator.visible = is_streaming
        self._update_display()

    def _on_streaming_text_changed(self, text: str) -> None:
        """Обновить чат при получении нового streaming текста.

        Args:
            text: Новый streaming текст
        """
        self._logger.debug(
            "on_streaming_text_changed",
            text=text[:50] if text else "",
            text_length=len(text),
        )
        self._update_display()

    def _update_display(self) -> None:
        """Обновить отображение чата на основе текущего состояния."""
        if self.chat_vm is None or not self._mounted or self._content_container is None:
            return

        # Очищаем старый контент (счетчик не сбрасываем, чтобы ID оставались уникальными)
        self._content_container.query("*").remove()

        # Отображаем сообщения
        messages = self.chat_vm.messages.value
        for message in messages:
            self._render_message(message)

        # Отображаем streaming текст если идет streaming
        if self.chat_vm.is_streaming.value and self.chat_vm.streaming_text.value:
            self._render_streaming_text(self.chat_vm.streaming_text.value)

        # Отображаем tool calls
        tool_calls = self.chat_vm.tool_calls.value
        for tool_call in tool_calls:
            self._render_tool_call(tool_call)

        # Скроллируем вниз
        self.scroll_end()

    def _render_message(self, message: Any) -> None:
        """Отобразить одно сообщение через MessageBubble.

        Использует MessageBubble для улучшенного рендеринга сообщений с аватарами
        и стилизацией в зависимости от роли.

        Args:
            message: Объект сообщения (dict с ключами role и content)
        """
        if self._content_container is None:
            return

        # Извлекаем роль и содержимое из сообщения
        if isinstance(message, dict):
            msg_role_value = message.get("role")
            if msg_role_value is None:
                msg_role_value = message.get("type", "unknown")
            msg_role_str: str = str(msg_role_value)
            content: str = str(message.get("content", ""))

            # Конвертируем строковую роль в MessageRole enum
            role_map = {
                "user": MessageRole.USER,
                "assistant": MessageRole.ASSISTANT,
                "system": MessageRole.SYSTEM,
                "error": MessageRole.ERROR,
            }
            msg_role = role_map.get(msg_role_str, MessageRole.SYSTEM)

            # Создаем MessageBubble с улучшенным отображением
            message_widget = MessageBubble(
                role=msg_role,
                content=content,
                show_avatar=True,
                show_header=True,
                id=f"msg_{time.time_ns()}",
            )
        else:
            # Fallback для неизвестных типов - используем Static
            message_widget = Static(str(message), id=f"msg_{time.time_ns()}", classes="message")

        self._content_container.mount(message_widget)

    def _render_streaming_text(self, text: str) -> None:
        """Отобразить streaming текст.

        Args:
            text: Streaming текст
        """
        if self._content_container is None:
            return

        # Используем Content API для безопасного комбинирования styled prefix
        # с literal user text (избегаем crash на markup-like символах в тексте LLM)
        from textual.content import Content
        prefix = Content.from_markup("[bold green]⟳ [/]")
        safe_text = Content.from_text(text)
        streaming_widget = Static(
            prefix + safe_text,
            id=f"stream_{time.time_ns()}",
            classes="message",
        )
        self._content_container.mount(streaming_widget)

    def _render_tool_call(self, tool_call: object) -> None:
        """Отобразить tool call.

        Args:
            tool_call: Объект tool call
        """
        if self._content_container is None:
            return

        # Используем Content API для безопасного комбинирования styled prefix
        # с literal user text (избегаем crash на markup-like символах)
        from textual.content import Content
        prefix = Content.from_markup("[italic]Tool: [/]")
        safe_text = Content.from_text(str(tool_call))
        tool_widget = Static(
            prefix + safe_text,
            id=f"tool_{time.time_ns()}",
            classes="message",
        )
        self._content_container.mount(tool_widget)

    def clear_messages(self) -> None:
        """Очистить все сообщения из чата.

        Удаляет все сообщения из ChatViewModel.
        """
        if self.chat_vm is not None:
            self.chat_vm.messages.value = []

    def add_user_message(self, message: str) -> None:
        """Добавить пользовательское сообщение в чат.

        Args:
            message: Текст пользовательского сообщения
        """
        if self.chat_vm is not None:
            messages = self.chat_vm.messages.value.copy()
            # Используем "role" для унификации со структурой ChatViewModel.add_message()
            messages.append({"role": "user", "content": message})
            self.chat_vm.messages.value = messages

    def add_system_message(self, message: str) -> None:
        """Добавить системное сообщение в чат.

        Args:
            message: Текст системного сообщения
        """
        if self.chat_vm is not None:
            messages = self.chat_vm.messages.value.copy()
            # Используем "role" для унификации со структурой ChatViewModel.add_message()
            messages.append({"role": "system", "content": message})
            self.chat_vm.messages.value = messages

    def append_agent_chunk(self, text: str) -> None:
        """Добавить chunk текста агента в streaming режиме.

        Используется для обновления streaming текста при получении данных от агента.

        Args:
            text: Текст chunk'а от агента
        """
        self._logger.debug("append_agent_chunk", text=text, text_length=len(text))
        if self.chat_vm is not None:
            # Активируем streaming режим и конкатенируем текст
            self.chat_vm.is_streaming.value = True
            # Конкатенируем новый текст со старым (не перезаписываем!)
            old_text = self.chat_vm.streaming_text.value
            self.chat_vm.streaming_text.value += text
            self._logger.debug(
                "streaming_text_updated",
                old_length=len(old_text),
                new_length=len(self.chat_vm.streaming_text.value),
            )

    def finish_agent_message(self) -> None:
        """Обозначить окончание агентского сообщения.

        Используется для маркировки конца streaming сообщения от агента и добавления
        его в историю сообщений.
        """
        if self.chat_vm is not None:
            # Сохраняем streaming текст в messages перед сбросом
            streaming_text = self.chat_vm.streaming_text.value
            self._logger.debug("finish_agent_message", streaming_text_length=len(streaming_text))

            if streaming_text:
                # Добавляем накопленный streaming текст в историю сообщений
                # Используем "role" для унификации со структурой ChatViewModel.add_message()
                messages = self.chat_vm.messages.value.copy()
                messages.append({"role": "assistant", "content": streaming_text})
                self.chat_vm.messages.value = messages
                self._logger.debug(
                    "streaming_text_saved_to_messages", text_length=len(streaming_text)
                )

            # Отключаем streaming режим и очищаем буфер
            self.chat_vm.is_streaming.value = False
            self.chat_vm.streaming_text.value = ""

    def show_permission_request(
        self,
        request_id: str | int,
        tool_call: PermissionToolCall,
        options: list[PermissionOption],
        on_choice: Callable[[str | int, str], None],
    ) -> None:
        """Показать встроенный виджет запроса разрешения в чате.

        Интегрирует встроенный виджет разрешения в ChatView.
        Виджет отображается как часть истории сообщений.

        Args:
            request_id: ID permission request
            tool_call: Информация о tool call
            options: Доступные опции для выбора
            on_choice: Callback при выборе (request_id, option_id)
        """
        if self._permission_manager is not None:
            self._permission_manager.show_permission_request(
                request_id, tool_call, options, on_choice
            )
        else:
            self._logger.warning(
                "permission_manager_not_available",
                request_id=request_id,
            )

    def hide_permission_request(self) -> None:
        """Скрыть и удалить встроенный виджет разрешения.

        Удаляет текущий виджет разрешения из ChatView.
        """
        if self._permission_manager is not None:
            self._permission_manager.hide_permission_request()
