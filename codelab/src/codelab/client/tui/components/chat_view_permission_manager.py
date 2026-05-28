"""Менеджер встроенного виджета разрешения в ChatView.

Управляет жизненным циклом виджетов разрешения:
- InlinePermissionWidget: базовый виджет с кнопками
- PermissionRequest: расширенный виджет с иконками, типами и автоотклонением

Поддерживает:
- Создание и монтирование в ChatView
- Скрытие и удаление
- Синхронизация с PermissionViewModel
- Выбор типа виджета (inline/request)
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import TYPE_CHECKING

import structlog

from codelab.client.messages import PermissionOption, PermissionToolCall
from codelab.client.tui.components.inline_permission_widget import InlinePermissionWidget
from codelab.client.tui.components.permission_request import (
    PermissionRequest,
    PermissionType,
)

if TYPE_CHECKING:
    from codelab.client.presentation.permission_view_model import PermissionViewModel
    from codelab.client.tui.components.chat_view import ChatView


class PermissionWidgetType(Enum):
    """Тип виджета разрешения.
    
    - INLINE: базовый виджет с кнопками (InlinePermissionWidget)
    - REQUEST: расширенный виджет с иконками и автоотклонением (PermissionRequest)
    """
    
    INLINE = "inline"
    REQUEST = "request"


# Маппинг tool_call.kind -> PermissionType
# MCP инструменты теперь имеют inferred kind (read, edit, execute и т.д.)
# и маппятся на соответствующие permission-типы вместе с нативными инструментами.
_TOOL_KIND_TO_PERMISSION_TYPE: dict[str, PermissionType] = {
    "read_file": "file_read",
    "file_read": "file_read",
    "read": "file_read",
    "write_file": "file_write",
    "file_write": "file_write",
    "edit": "file_write",
    "delete_file": "file_delete",
    "file_delete": "file_delete",
    "delete": "file_delete",
    "execute": "execute_command",
    "execute_command": "execute_command",
    "terminal": "execute_command",
    "search": "file_read",
    "fetch": "execute_command",
    "move": "file_write",
    "think": "unknown",
    "switch_mode": "unknown",
    "other": "unknown",
}


class ChatViewPermissionManager:
    """Менеджер встроенного виджета разрешения в ChatView.

    Ответственность:
    - Управление жизненным циклом виджетов разрешения
    - Поддержка InlinePermissionWidget и PermissionRequest
    - Интеграция с ChatView._content_container
    - Синхронизация с PermissionViewModel через Observable паттерн
    - Показ/скрытие виджета разрешения
    """

    def __init__(
        self,
        chat_view: ChatView,
        permission_vm: PermissionViewModel,
        widget_type: PermissionWidgetType = PermissionWidgetType.REQUEST,
    ) -> None:
        """Инициализирует менеджер разрешений.

        Args:
            chat_view: ChatView компонент для монтирования виджета
            permission_vm: PermissionViewModel для управления состоянием
            widget_type: Тип виджета разрешения (по умолчанию REQUEST)
        """
        self.chat_view = chat_view
        self.permission_vm = permission_vm
        self.widget_type = widget_type
        self._current_widget: InlinePermissionWidget | PermissionRequest | None = None
        self._logger = structlog.get_logger("chat_view_permission_manager")

        # Подписаться на изменения видимости в ViewModel
        permission_vm.is_visible.subscribe(self._on_visibility_changed)

    def show_permission_request(
        self,
        request_id: str | int,
        tool_call: PermissionToolCall,
        options: list[PermissionOption],
        on_choice: Callable[[str | int, str], None],
        *,
        auto_deny_seconds: int | None = None,
    ) -> None:
        """Показать виджет разрешения в ChatView.

        В зависимости от widget_type создаёт:
        - INLINE: InlinePermissionWidget (базовый)
        - REQUEST: PermissionRequest (расширенный с иконками и автоотклонением)

        Args:
            request_id: ID permission request
            tool_call: Информация о tool call
            options: Доступные опции для выбора
            on_choice: Callback при выборе (request_id, option_id)
            auto_deny_seconds: Время до автоотклонения (только для REQUEST)
        """
        # Если виджет уже показан, скрыть его перед созданием нового
        if self._current_widget is not None:
            self.hide_permission_request()

        # Создать виджет в зависимости от типа
        if self.widget_type == PermissionWidgetType.REQUEST:
            # Определяем тип разрешения из tool_call.kind
            kind = tool_call.kind or "unknown"
            permission_type = self._get_permission_type(kind)
            
            self._current_widget = PermissionRequest(
                permission_vm=self.permission_vm,
                request_id=request_id,
                permission_type=permission_type,
                resource=tool_call.title or "",
                message=self.permission_vm.message.value,
                options=options,
                on_choice=on_choice,
                auto_deny_seconds=auto_deny_seconds,
            )
        else:
            # Создать InlinePermissionWidget (INLINE по умолчанию для обратной совместимости)
            self._current_widget = InlinePermissionWidget(
                permission_vm=self.permission_vm,
                request_id=request_id,
                tool_call=tool_call,
                options=options,
                on_choice=on_choice,
            )

        # Монтировать в контейнер ChatView если он доступен
        if self.chat_view._content_container is not None:
            self.chat_view._content_container.mount(self._current_widget)
            # Автоскролл к виджету для видимости
            self.chat_view.scroll_end()
            self._logger.info(
                "permission_widget_mounted",
                request_id=request_id,
                tool_call_kind=tool_call.kind,
                widget_type=self.widget_type.value,
            )
        else:
            self._logger.error(
                "chat_view_content_container_not_available",
                request_id=request_id,
            )
    
    def _get_permission_type(self, kind: str) -> PermissionType:
        """Преобразовать tool_call.kind в PermissionType.
        
        Args:
            kind: Тип tool call
            
        Returns:
            Соответствующий PermissionType
        """
        return _TOOL_KIND_TO_PERMISSION_TYPE.get(kind, "unknown")

    def hide_permission_request(self) -> None:
        """Скрыть и удалить встроенный виджет разрешения.

        Удаляет текущий виджет из DOM и очищает ссылку.
        """
        if self._current_widget is not None:
            try:
                self._current_widget.remove()
            except Exception as e:
                # Виджет уже удален или произошла ошибка
                self._logger.warning(
                    "failed_to_remove_permission_widget",
                    error=str(e),
                )
            finally:
                self._current_widget = None
            self._logger.info("permission_widget_hidden")

    def is_widget_visible(self) -> bool:
        """Проверить видимость встроенного виджета.

        Returns:
            True если виджет смонтирован, False иначе
        """
        return self._current_widget is not None

    def _on_visibility_changed(self, is_visible: bool) -> None:
        """Обработчик изменения видимости в PermissionViewModel.

        Скрывает виджет когда ViewModel.is_visible становится False.

        Args:
            is_visible: Новое значение видимости
        """
        if not is_visible:
            self.hide_permission_request()
