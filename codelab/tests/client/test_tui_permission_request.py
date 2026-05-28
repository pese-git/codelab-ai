"""Тесты для компонента PermissionRequest и интеграции с ChatViewPermissionManager."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from codelab.client.infrastructure.events.bus import EventBus
from codelab.client.messages import PermissionOption, PermissionToolCall
from codelab.client.presentation.permission_view_model import PermissionViewModel
from codelab.client.tui.components.chat_view_permission_manager import (
    _TOOL_KIND_TO_PERMISSION_TYPE,
    ChatViewPermissionManager,
    PermissionWidgetType,
)
from codelab.client.tui.components.permission_request import (
    PERMISSION_DESCRIPTIONS,
    PERMISSION_ICONS,
    PermissionRequest,
)

# --- Фикстуры ---


@pytest.fixture
def event_bus() -> EventBus:
    """Создать EventBus для тестов."""
    return EventBus()


@pytest.fixture
def permission_view_model(event_bus: EventBus) -> PermissionViewModel:
    """Создать PermissionViewModel для тестов."""
    return PermissionViewModel(event_bus=event_bus, logger=None)


@pytest.fixture
def sample_options() -> list[PermissionOption]:
    """Создать примеры опций разрешения для тестов."""
    return [
        PermissionOption(
            optionId="allow_once_123",
            name="Allow Once",
            kind="allow_once",
        ),
        PermissionOption(
            optionId="reject_once_123",
            name="Reject Once",
            kind="reject_once",
        ),
        PermissionOption(
            optionId="allow_always_123",
            name="Allow Always",
            kind="allow_always",
        ),
    ]


@pytest.fixture
def sample_tool_call() -> PermissionToolCall:
    """Создать пример tool call для тестов."""
    return PermissionToolCall(
        toolCallId="tc_123",
        kind="edit",
        title="/home/user/test.txt",
    )


# --- Тесты PermissionRequest ---


def test_permission_request_requires_permission_vm(
    permission_view_model: PermissionViewModel,
    sample_options: list[PermissionOption],
) -> None:
    """Проверить что PermissionRequest требует обязательный параметр permission_vm."""
    request = PermissionRequest(
        permission_vm=permission_view_model,
        request_id="req_123",
        permission_type="file_write",
        resource="/home/user/test.txt",
        options=sample_options,
    )

    assert request.permission_vm is permission_view_model
    assert request.request_id == "req_123"
    assert request.permission_type == "file_write"
    assert request.resource == "/home/user/test.txt"


def test_permission_request_has_correct_default_id(
    permission_view_model: PermissionViewModel,
) -> None:
    """Проверить что ID виджета формируется правильно."""
    request = PermissionRequest(
        permission_vm=permission_view_model,
        request_id="req_456",
    )

    assert request.id == "perm-req-req_456"


def test_permission_request_custom_id(
    permission_view_model: PermissionViewModel,
) -> None:
    """Проверить что можно задать custom ID."""
    request = PermissionRequest(
        permission_vm=permission_view_model,
        request_id="req_789",
        id="custom-id",
    )

    assert request.id == "custom-id"


def test_permission_request_is_not_resolved_initially(
    permission_view_model: PermissionViewModel,
) -> None:
    """Проверить что виджет изначально не resolved."""
    request = PermissionRequest(
        permission_vm=permission_view_model,
        request_id="req_123",
    )

    assert request.is_resolved is False


def test_permission_request_icons_exist_for_all_types() -> None:
    """Проверить что иконки определены для всех типов разрешений."""
    expected_types = [
        "file_read", "file_write", "file_delete",
        "execute_command", "mcp_access", "unknown",
    ]
    for perm_type in expected_types:
        assert perm_type in PERMISSION_ICONS
        assert PERMISSION_ICONS[perm_type] != ""


def test_permission_request_descriptions_exist_for_all_types() -> None:
    """Проверить что описания определены для всех типов разрешений."""
    expected_types = [
        "file_read", "file_write", "file_delete",
        "execute_command", "mcp_access", "unknown",
    ]
    for perm_type in expected_types:
        assert perm_type in PERMISSION_DESCRIPTIONS
        assert PERMISSION_DESCRIPTIONS[perm_type] != ""


def test_permission_request_find_option_id(
    permission_view_model: PermissionViewModel,
    sample_options: list[PermissionOption],
) -> None:
    """Проверить поиск опции по типу и имени."""
    request = PermissionRequest(
        permission_vm=permission_view_model,
        request_id="req_123",
        options=sample_options,
    )

    # Поиск allow once
    option_id = request._find_option_id("allow_once")  # noqa: SLF001
    assert option_id == "allow_once_123"

    # Поиск reject once
    option_id = request._find_option_id("reject_once")  # noqa: SLF001
    assert option_id == "reject_once_123"

    # Поиск always
    option_id = request._find_option_id("allow_always")  # noqa: SLF001
    assert option_id == "allow_always_123"


def test_permission_request_find_option_id_not_found(
    permission_view_model: PermissionViewModel,
    sample_options: list[PermissionOption],
) -> None:
    """Проверить что возвращается None если опция не найдена."""
    request = PermissionRequest(
        permission_vm=permission_view_model,
        request_id="req_123",
        options=sample_options,
    )

    # Поиск несуществующего kind
    option_id = request._find_option_id("nonexistent_kind")  # noqa: SLF001
    assert option_id is None


def test_permission_request_select_option_calls_callback(
    permission_view_model: PermissionViewModel,
    sample_options: list[PermissionOption],
) -> None:
    """Проверить что выбор опции вызывает callback."""
    callback = MagicMock()
    request = PermissionRequest(
        permission_vm=permission_view_model,
        request_id="req_123",
        options=sample_options,
        on_choice=callback,
    )

    request._select_option("allow_once_123")  # noqa: SLF001

    callback.assert_called_once_with("req_123", "allow_once_123")
    assert request.is_resolved is True


def test_permission_request_select_option_hides_via_view_model(
    permission_view_model: PermissionViewModel,
) -> None:
    """Проверить что выбор опции вызывает hide на ViewModel."""
    permission_view_model.show_request("file_write", "/test", "test message")
    assert permission_view_model.is_visible.value is True

    request = PermissionRequest(
        permission_vm=permission_view_model,
        request_id="req_123",
    )

    request._select_option("allow")  # noqa: SLF001

    assert permission_view_model.is_visible.value is False


def test_permission_request_cannot_select_twice(
    permission_view_model: PermissionViewModel,
    sample_options: list[PermissionOption],
) -> None:
    """Проверить что нельзя выбрать опцию дважды."""
    callback = MagicMock()
    request = PermissionRequest(
        permission_vm=permission_view_model,
        request_id="req_123",
        options=sample_options,
        on_choice=callback,
    )

    request._select_option("allow_once_123")  # noqa: SLF001
    request._select_option("deny_once_123")  # noqa: SLF001

    # Callback должен быть вызван только один раз
    callback.assert_called_once()


def test_permission_request_allow_method(
    permission_view_model: PermissionViewModel,
    sample_options: list[PermissionOption],
) -> None:
    """Проверить метод allow()."""
    callback = MagicMock()
    request = PermissionRequest(
        permission_vm=permission_view_model,
        request_id="req_123",
        options=sample_options,
        on_choice=callback,
    )

    request.allow()

    # allow() вызывает _find_option_id("allow_once") и находит опцию с optionId="allow_once_123"
    callback.assert_called_once_with("req_123", "allow_once_123")


def test_permission_request_deny_method(
    permission_view_model: PermissionViewModel,
    sample_options: list[PermissionOption],
) -> None:
    """Проверить метод deny()."""
    callback = MagicMock()
    request = PermissionRequest(
        permission_vm=permission_view_model,
        request_id="req_123",
        options=sample_options,
        on_choice=callback,
    )

    request.deny()

    # deny() вызывает _find_option_id("reject_once") и находит опцию с optionId="reject_once_123"
    callback.assert_called_once_with("req_123", "reject_once_123")


def test_permission_request_always_allow_method(
    permission_view_model: PermissionViewModel,
    sample_options: list[PermissionOption],
) -> None:
    """Проверить метод always_allow()."""
    callback = MagicMock()
    request = PermissionRequest(
        permission_vm=permission_view_model,
        request_id="req_123",
        options=sample_options,
        on_choice=callback,
    )

    request.always_allow()

    # always_allow() вызывает _find_option_id("allow_always")
    # и находит опцию с optionId="allow_always_123"
    callback.assert_called_once_with("req_123", "allow_always_123")


# --- Тесты ChatViewPermissionManager с PermissionWidgetType ---


def test_permission_widget_type_enum() -> None:
    """Проверить что enum PermissionWidgetType имеет правильные значения."""
    assert PermissionWidgetType.INLINE.value == "inline"
    assert PermissionWidgetType.REQUEST.value == "request"


def test_tool_kind_to_permission_type_mapping() -> None:
    """Проверить маппинг tool_call.kind -> PermissionType."""
    # Чтение файла
    assert _TOOL_KIND_TO_PERMISSION_TYPE["read_file"] == "file_read"
    assert _TOOL_KIND_TO_PERMISSION_TYPE["file_read"] == "file_read"

    # Запись файла
    assert _TOOL_KIND_TO_PERMISSION_TYPE["write_file"] == "file_write"
    assert _TOOL_KIND_TO_PERMISSION_TYPE["file_write"] == "file_write"

    # Удаление файла
    assert _TOOL_KIND_TO_PERMISSION_TYPE["delete_file"] == "file_delete"
    assert _TOOL_KIND_TO_PERMISSION_TYPE["file_delete"] == "file_delete"

    # Выполнение команды
    assert _TOOL_KIND_TO_PERMISSION_TYPE["execute"] == "execute_command"
    assert _TOOL_KIND_TO_PERMISSION_TYPE["execute_command"] == "execute_command"
    assert _TOOL_KIND_TO_PERMISSION_TYPE["terminal"] == "execute_command"

    # MCP инструменты теперь имеют inferred kind (read, edit, execute и т.д.)
    # и маппятся на соответствующие permission-типы
    assert _TOOL_KIND_TO_PERMISSION_TYPE["read"] == "file_read"
    assert _TOOL_KIND_TO_PERMISSION_TYPE["edit"] == "file_write"
    assert _TOOL_KIND_TO_PERMISSION_TYPE["delete"] == "file_delete"
    assert _TOOL_KIND_TO_PERMISSION_TYPE["execute"] == "execute_command"
    assert _TOOL_KIND_TO_PERMISSION_TYPE["search"] == "file_read"
    assert _TOOL_KIND_TO_PERMISSION_TYPE["fetch"] == "execute_command"
    assert _TOOL_KIND_TO_PERMISSION_TYPE["move"] == "file_write"
    assert _TOOL_KIND_TO_PERMISSION_TYPE["other"] == "unknown"


def test_chat_view_permission_manager_default_widget_type(
    permission_view_model: PermissionViewModel,
) -> None:
    """Проверить что по умолчанию используется REQUEST тип виджета."""
    mock_chat_view = MagicMock()

    manager = ChatViewPermissionManager(
        chat_view=mock_chat_view,
        permission_vm=permission_view_model,
    )

    assert manager.widget_type == PermissionWidgetType.REQUEST


def test_chat_view_permission_manager_inline_widget_type(
    permission_view_model: PermissionViewModel,
) -> None:
    """Проверить что можно установить INLINE тип виджета."""
    mock_chat_view = MagicMock()

    manager = ChatViewPermissionManager(
        chat_view=mock_chat_view,
        permission_vm=permission_view_model,
        widget_type=PermissionWidgetType.INLINE,
    )

    assert manager.widget_type == PermissionWidgetType.INLINE


def test_chat_view_permission_manager_get_permission_type(
    permission_view_model: PermissionViewModel,
) -> None:
    """Проверить метод _get_permission_type."""
    mock_chat_view = MagicMock()

    manager = ChatViewPermissionManager(
        chat_view=mock_chat_view,
        permission_vm=permission_view_model,
    )

    assert manager._get_permission_type("file_write") == "file_write"  # noqa: SLF001
    assert manager._get_permission_type("execute") == "execute_command"  # noqa: SLF001
    assert manager._get_permission_type("unknown_kind") == "unknown"  # noqa: SLF001


def test_chat_view_permission_manager_creates_permission_request_widget(
    permission_view_model: PermissionViewModel,
    sample_options: list[PermissionOption],
    sample_tool_call: PermissionToolCall,
) -> None:
    """Проверить что при REQUEST типе создается PermissionRequest виджет."""
    mock_chat_view = MagicMock()
    mock_chat_view._content_container = MagicMock()

    manager = ChatViewPermissionManager(
        chat_view=mock_chat_view,
        permission_vm=permission_view_model,
        widget_type=PermissionWidgetType.REQUEST,
    )

    callback = MagicMock()
    manager.show_permission_request(
        request_id="req_123",
        tool_call=sample_tool_call,
        options=sample_options,
        on_choice=callback,
    )

    # Проверяем что виджет создан
    assert manager._current_widget is not None
    assert isinstance(manager._current_widget, PermissionRequest)

    # Проверяем что виджет смонтирован
    mock_chat_view._content_container.mount.assert_called_once()


def test_chat_view_permission_manager_creates_inline_widget(
    permission_view_model: PermissionViewModel,
    sample_options: list[PermissionOption],
    sample_tool_call: PermissionToolCall,
) -> None:
    """Проверить что при INLINE типе создается InlinePermissionWidget."""
    from codelab.client.tui.components.inline_permission_widget import (
        InlinePermissionWidget,
    )

    mock_chat_view = MagicMock()
    mock_chat_view._content_container = MagicMock()

    manager = ChatViewPermissionManager(
        chat_view=mock_chat_view,
        permission_vm=permission_view_model,
        widget_type=PermissionWidgetType.INLINE,
    )

    callback = MagicMock()
    manager.show_permission_request(
        request_id="req_123",
        tool_call=sample_tool_call,
        options=sample_options,
        on_choice=callback,
    )

    # Проверяем что виджет создан
    assert manager._current_widget is not None
    assert isinstance(manager._current_widget, InlinePermissionWidget)


def test_chat_view_permission_manager_auto_deny_parameter(
    permission_view_model: PermissionViewModel,
    sample_options: list[PermissionOption],
    sample_tool_call: PermissionToolCall,
) -> None:
    """Проверить что auto_deny_seconds передается в PermissionRequest."""
    mock_chat_view = MagicMock()
    mock_chat_view._content_container = MagicMock()

    manager = ChatViewPermissionManager(
        chat_view=mock_chat_view,
        permission_vm=permission_view_model,
        widget_type=PermissionWidgetType.REQUEST,
    )

    callback = MagicMock()
    manager.show_permission_request(
        request_id="req_123",
        tool_call=sample_tool_call,
        options=sample_options,
        on_choice=callback,
        auto_deny_seconds=30,
    )

    # Проверяем что виджет создан с auto_deny_seconds
    assert manager._current_widget is not None
    assert isinstance(manager._current_widget, PermissionRequest)
    assert manager._current_widget._auto_deny_seconds == 30  # noqa: SLF001


def test_chat_view_permission_manager_hide_clears_widget(
    permission_view_model: PermissionViewModel,
    sample_options: list[PermissionOption],
    sample_tool_call: PermissionToolCall,
) -> None:
    """Проверить что hide_permission_request очищает виджет."""
    mock_chat_view = MagicMock()
    mock_chat_view._content_container = MagicMock()

    manager = ChatViewPermissionManager(
        chat_view=mock_chat_view,
        permission_vm=permission_view_model,
    )

    callback = MagicMock()
    manager.show_permission_request(
        request_id="req_123",
        tool_call=sample_tool_call,
        options=sample_options,
        on_choice=callback,
    )

    assert manager.is_widget_visible() is True

    # Патчим remove чтобы избежать ошибки
    with patch.object(manager._current_widget, "remove"):
        manager.hide_permission_request()

    assert manager._current_widget is None
    assert manager.is_widget_visible() is False


def test_chat_view_permission_manager_visibility_observer(
    permission_view_model: PermissionViewModel,
    sample_options: list[PermissionOption],
    sample_tool_call: PermissionToolCall,
) -> None:
    """Проверить что при изменении is_visible в ViewModel виджет скрывается."""
    mock_chat_view = MagicMock()
    mock_chat_view._content_container = MagicMock()

    manager = ChatViewPermissionManager(
        chat_view=mock_chat_view,
        permission_vm=permission_view_model,
    )

    # Сначала показываем запрос через ViewModel (устанавливаем is_visible=True)
    permission_view_model.show_request("file_write", "/test/path", "Test message")

    callback = MagicMock()
    manager.show_permission_request(
        request_id="req_123",
        tool_call=sample_tool_call,
        options=sample_options,
        on_choice=callback,
    )

    assert manager.is_widget_visible() is True

    # Патчим remove чтобы избежать ошибки
    with patch.object(manager._current_widget, "remove"):
        # Изменяем видимость через ViewModel (is_visible становится False)
        permission_view_model.hide()
        # Теперь проверяем внутри with блока
        assert manager._current_widget is None
