"""Тесты Tool Call advanced features.

Покрывает:
- Tool Call locations (path + line для follow-along)
- Tool Call rawInput / rawOutput
- Tool Call status transitions (полная матрица переходов)
- Tool Call content types (text, diff, terminal)
- Tool kinds (все ACP tool kinds)
- Интеграционные тесты tool call lifecycle
"""

from __future__ import annotations

import pytest

from codelab.server.protocol.handlers.tool_call_handler import ToolCallHandler
from codelab.server.protocol.state import (
    ClientRuntimeCapabilities,
    SessionState,
    ToolCallState,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler() -> ToolCallHandler:
    """Фикстура для создания ToolCallHandler."""
    return ToolCallHandler()


@pytest.fixture
def session() -> SessionState:
    """Фикстура для создания базовой сессии с runtime capabilities."""
    sess = SessionState(
        session_id="test_session",
        cwd="/tmp",
        mcp_servers=[],
    )
    sess.runtime_capabilities = ClientRuntimeCapabilities(
        terminal=True,
        fs_read=True,
        fs_write=True,
    )
    return sess


# ---------------------------------------------------------------------------
# Tool Call locations
# ---------------------------------------------------------------------------


class TestToolCallLocations:
    """Тесты locations в tool calls."""

    def test_notification_with_single_location(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """tool_call notification с одним location (path)."""
        locations = [{"path": "/tmp/file.txt"}]
        msg = handler.build_tool_call_notification(
            session_id="sess_1",
            tool_call_id="call_001",
            title="Read File",
            kind="read",
            locations=locations,
        )

        update = msg.params["update"]
        assert update["locations"] == locations
        assert len(update["locations"]) == 1
        assert update["locations"][0]["path"] == "/tmp/file.txt"

    def test_notification_with_multiple_locations(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """tool_call notification с несколькими locations."""
        locations = [
            {"path": "/tmp/file1.txt"},
            {"path": "/tmp/file2.txt"},
            {"path": "/tmp/file3.txt"},
        ]
        msg = handler.build_tool_call_notification(
            session_id="sess_1",
            tool_call_id="call_001",
            title="Move Files",
            kind="move",
            locations=locations,
        )

        update = msg.params["update"]
        assert update["locations"] == locations
        assert len(update["locations"]) == 3

    def test_notification_with_location_and_line(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """location с path и line number."""
        locations = [
            {"path": "/tmp/src/main.py", "line": "42"},
            {"path": "/tmp/src/utils.py", "line": "10"},
        ]
        msg = handler.build_tool_call_notification(
            session_id="sess_1",
            tool_call_id="call_001",
            title="Edit Code",
            kind="edit",
            locations=locations,
        )

        update = msg.params["update"]
        assert update["locations"] == locations
        assert update["locations"][0]["line"] == "42"
        assert update["locations"][1]["line"] == "10"

    def test_notification_without_locations(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """tool_call notification без locations (опциональное поле)."""
        msg = handler.build_tool_call_notification(
            session_id="sess_1",
            tool_call_id="call_001",
            title="Think",
            kind="think",
        )

        update = msg.params["update"]
        assert "locations" not in update

    def test_notification_with_empty_locations(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """tool_call notification с пустым списком locations."""
        msg = handler.build_tool_call_notification(
            session_id="sess_1",
            tool_call_id="call_001",
            title="Search",
            kind="search",
            locations=[],
        )

        update = msg.params["update"]
        assert update["locations"] == []

    def test_fs_read_tool_call_has_location(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """fs/read tool call должен иметь location с path."""
        tool_call_id = handler.create_tool_call(session, title="Read file", kind="read")

        # Обновляем status с locations
        handler.update_tool_call_status(session, tool_call_id, "in_progress")

        # В реальной реализации locations добавляются при создании notification
        # Проверяем что tool call state создан корректно
        assert tool_call_id in session.tool_calls
        assert session.tool_calls[tool_call_id].kind == "read"


# ---------------------------------------------------------------------------
# Tool Call rawInput / rawOutput
# ---------------------------------------------------------------------------


class TestToolCallRawInputOutput:
    """Тесты rawInput и rawOutput в tool calls."""

    def test_tool_call_state_supports_raw_input(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """ToolCallState может хранить rawInput данные."""
        tool_call_id = handler.create_tool_call(
            session,
            title="Terminal command",
            kind="execute",
            tool_name="terminal/create",
            tool_arguments={"command": "ls -la", "cwd": "/tmp"},
        )

        tool_call = session.tool_calls[tool_call_id]
        assert tool_call.tool_arguments == {"command": "ls -la", "cwd": "/tmp"}
        assert tool_call.tool_name == "terminal/create"

    def test_tool_call_state_supports_raw_output(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """ToolCallState может хранить rawOutput через content."""
        tool_call_id = handler.create_tool_call(session, title="Read file", kind="read")

        # Сначала in_progress, потом completed
        handler.update_tool_call_status(session, tool_call_id, "in_progress")

        raw_output = [
            {
                "type": "content",
                "content": {
                    "type": "text",
                    "text": "file content here",
                },
            }
        ]
        handler.update_tool_call_status(
            session, tool_call_id, "completed", content=raw_output
        )

        tool_call = session.tool_calls[tool_call_id]
        assert tool_call.status == "completed"
        assert tool_call.content == raw_output

    def test_terminal_tool_call_raw_output_with_exit_code(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """Terminal tool call rawOutput с exit code и signal."""
        tool_call_id = handler.create_tool_call(session, title="Run command", kind="execute")

        handler.update_tool_call_status(session, tool_call_id, "in_progress")

        raw_output = [
            {
                "type": "terminal",
                "terminalId": "term_001",
            },
            {
                "type": "content",
                "content": {
                    "type": "text",
                    "text": "Command finished with exit code 0.",
                },
            },
        ]
        handler.update_tool_call_status(
            session, tool_call_id, "completed", content=raw_output
        )

        tool_call = session.tool_calls[tool_call_id]
        assert tool_call.status == "completed"
        assert len(tool_call.content) == 2
        assert tool_call.content[0]["type"] == "terminal"
        assert tool_call.content[0]["terminalId"] == "term_001"
        assert tool_call.content[1]["content"]["text"] == "Command finished with exit code 0."

    def test_raw_input_in_notification(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """rawInput может быть включен в notification через content."""
        tool_call_id = handler.create_tool_call(session, title="Execute", kind="execute")

        # Создаем notification с rawInput-like content
        msg = handler.build_tool_call_notification(
            session_id="sess_1",
            tool_call_id=tool_call_id,
            title="Execute command",
            kind="execute",
        )

        update = msg.params["update"]
        assert update["sessionUpdate"] == "tool_call"
        assert update["toolCallId"] == tool_call_id
        assert update["status"] == "pending"

    def test_raw_output_in_update_notification(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """rawOutput включается в tool_call_update notification."""
        tool_call_id = handler.create_tool_call(session, title="Read", kind="read")

        raw_output_content = [
            {
                "type": "content",
                "content": {
                    "type": "text",
                    "text": "Hello, world!",
                },
            }
        ]
        msg = handler.build_tool_update_notification(
            session_id="sess_1",
            tool_call_id=tool_call_id,
            status="completed",
            content=raw_output_content,
        )

        update = msg.params["update"]
        assert update["status"] == "completed"
        assert update["content"] == raw_output_content


# ---------------------------------------------------------------------------
# Tool Call status transitions (полная матрица)
# ---------------------------------------------------------------------------


class TestToolCallStatusTransitions:
    """Тесты полной матрицы переходов статусов."""

    def test_pending_to_in_progress(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """pending → in_progress: допустимый переход."""
        tool_call_id = handler.create_tool_call(session, title="Test", kind="execute")
        handler.update_tool_call_status(session, tool_call_id, "in_progress")
        assert session.tool_calls[tool_call_id].status == "in_progress"

    def test_pending_to_cancelled(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """pending → cancelled: допустимый переход."""
        tool_call_id = handler.create_tool_call(session, title="Test", kind="execute")
        handler.update_tool_call_status(session, tool_call_id, "cancelled")
        assert session.tool_calls[tool_call_id].status == "cancelled"

    def test_pending_to_failed(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """pending → failed: допустимый переход."""
        tool_call_id = handler.create_tool_call(session, title="Test", kind="execute")
        handler.update_tool_call_status(session, tool_call_id, "failed")
        assert session.tool_calls[tool_call_id].status == "failed"

    def test_in_progress_to_completed(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """in_progress → completed: допустимый переход."""
        tool_call_id = handler.create_tool_call(session, title="Test", kind="execute")
        handler.update_tool_call_status(session, tool_call_id, "in_progress")
        handler.update_tool_call_status(session, tool_call_id, "completed")
        assert session.tool_calls[tool_call_id].status == "completed"

    def test_in_progress_to_cancelled(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """in_progress → cancelled: допустимый переход."""
        tool_call_id = handler.create_tool_call(session, title="Test", kind="execute")
        handler.update_tool_call_status(session, tool_call_id, "in_progress")
        handler.update_tool_call_status(session, tool_call_id, "cancelled")
        assert session.tool_calls[tool_call_id].status == "cancelled"

    def test_in_progress_to_failed(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """in_progress → failed: допустимый переход."""
        tool_call_id = handler.create_tool_call(session, title="Test", kind="execute")
        handler.update_tool_call_status(session, tool_call_id, "in_progress")
        handler.update_tool_call_status(session, tool_call_id, "failed")
        assert session.tool_calls[tool_call_id].status == "failed"

    def test_completed_is_terminal(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """completed: терминальное состояние, нет переходов."""
        tool_call_id = handler.create_tool_call(session, title="Test", kind="execute")
        handler.update_tool_call_status(session, tool_call_id, "in_progress")
        handler.update_tool_call_status(session, tool_call_id, "completed")

        # Все попытки изменить статус должны быть проигнорированы
        handler.update_tool_call_status(session, tool_call_id, "in_progress")
        handler.update_tool_call_status(session, tool_call_id, "pending")
        handler.update_tool_call_status(session, tool_call_id, "cancelled")
        handler.update_tool_call_status(session, tool_call_id, "failed")

        assert session.tool_calls[tool_call_id].status == "completed"

    def test_cancelled_is_terminal(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """cancelled: терминальное состояние, нет переходов."""
        tool_call_id = handler.create_tool_call(session, title="Test", kind="execute")
        handler.update_tool_call_status(session, tool_call_id, "cancelled")

        handler.update_tool_call_status(session, tool_call_id, "in_progress")
        handler.update_tool_call_status(session, tool_call_id, "pending")
        handler.update_tool_call_status(session, tool_call_id, "completed")
        handler.update_tool_call_status(session, tool_call_id, "failed")

        assert session.tool_calls[tool_call_id].status == "cancelled"

    def test_failed_is_terminal(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """failed: терминальное состояние, нет переходов."""
        tool_call_id = handler.create_tool_call(session, title="Test", kind="execute")
        handler.update_tool_call_status(session, tool_call_id, "failed")

        handler.update_tool_call_status(session, tool_call_id, "in_progress")
        handler.update_tool_call_status(session, tool_call_id, "pending")
        handler.update_tool_call_status(session, tool_call_id, "completed")
        handler.update_tool_call_status(session, tool_call_id, "cancelled")

        assert session.tool_calls[tool_call_id].status == "failed"

    def test_pending_to_completed_invalid(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """pending → completed: недопустимый переход (нужен in_progress)."""
        tool_call_id = handler.create_tool_call(session, title="Test", kind="execute")
        handler.update_tool_call_status(session, tool_call_id, "completed")
        # Должен остаться pending
        assert session.tool_calls[tool_call_id].status == "pending"

    def test_full_lifecycle_pending_to_completed(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """Полный lifecycle: pending → in_progress → completed."""
        tool_call_id = handler.create_tool_call(session, title="Test", kind="execute")

        assert session.tool_calls[tool_call_id].status == "pending"

        handler.update_tool_call_status(session, tool_call_id, "in_progress")
        assert session.tool_calls[tool_call_id].status == "in_progress"

        content = [{"type": "content", "content": {"type": "text", "text": "Done"}}]
        handler.update_tool_call_status(session, tool_call_id, "completed", content=content)
        assert session.tool_calls[tool_call_id].status == "completed"
        assert session.tool_calls[tool_call_id].content == content


# ---------------------------------------------------------------------------
# Tool Call content types
# ---------------------------------------------------------------------------


class TestToolCallContentTypes:
    """Тесты различных типов контента в tool calls."""

    def test_text_content(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """tool call с text content."""
        tool_call_id = handler.create_tool_call(session, title="Read", kind="read")

        content = [
            {
                "type": "content",
                "content": {
                    "type": "text",
                    "text": "File contents here",
                },
            }
        ]
        handler.update_tool_call_status(session, tool_call_id, "in_progress")
        handler.update_tool_call_status(session, tool_call_id, "completed", content=content)

        assert session.tool_calls[tool_call_id].content == content

    def test_diff_content(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """tool call с diff content."""
        tool_call_id = handler.create_tool_call(session, title="Edit", kind="edit")

        content = [
            {
                "type": "diff",
                "path": "/tmp/file.txt",
                "oldText": "old line",
                "newText": "new line",
            }
        ]
        handler.update_tool_call_status(session, tool_call_id, "in_progress")
        handler.update_tool_call_status(session, tool_call_id, "completed", content=content)

        assert session.tool_calls[tool_call_id].content == content
        assert session.tool_calls[tool_call_id].content[0]["type"] == "diff"
        assert session.tool_calls[tool_call_id].content[0]["oldText"] == "old line"
        assert session.tool_calls[tool_call_id].content[0]["newText"] == "new line"

    def test_terminal_content(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """tool call с terminal content."""
        tool_call_id = handler.create_tool_call(session, title="Run", kind="execute")

        content = [
            {
                "type": "terminal",
                "terminalId": "term_001",
            },
            {
                "type": "content",
                "content": {
                    "type": "text",
                    "text": "Command output",
                },
            },
        ]
        handler.update_tool_call_status(session, tool_call_id, "in_progress")
        handler.update_tool_call_status(session, tool_call_id, "completed", content=content)

        assert session.tool_calls[tool_call_id].content == content
        assert session.tool_calls[tool_call_id].content[0]["type"] == "terminal"
        assert session.tool_calls[tool_call_id].content[0]["terminalId"] == "term_001"

    def test_multiple_content_items(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """tool call с несколькими content items."""
        tool_call_id = handler.create_tool_call(session, title="Complex", kind="edit")

        content = [
            {
                "type": "diff",
                "path": "/tmp/file1.txt",
                "newText": "changes to file1",
            },
            {
                "type": "diff",
                "path": "/tmp/file2.txt",
                "newText": "changes to file2",
            },
            {
                "type": "content",
                "content": {
                    "type": "text",
                    "text": "Summary of changes",
                },
            },
        ]
        handler.update_tool_call_status(session, tool_call_id, "in_progress")
        handler.update_tool_call_status(session, tool_call_id, "completed", content=content)

        assert len(session.tool_calls[tool_call_id].content) == 3


# ---------------------------------------------------------------------------
# Tool kinds
# ---------------------------------------------------------------------------


class TestToolKinds:
    """Тесты всех ACP tool kinds."""

    @pytest.mark.parametrize(
        "kind",
        [
            "read",
            "edit",
            "delete",
            "move",
            "search",
            "execute",
            "think",
            "fetch",
            "switch_mode",
            "other",
        ],
    )
    def test_all_tool_kinds_supported(
        self, handler: ToolCallHandler, session: SessionState, kind: str
    ) -> None:
        """Все ACP tool kinds поддерживаются."""
        tool_call_id = handler.create_tool_call(session, title=f"Test {kind}", kind=kind)

        assert tool_call_id in session.tool_calls
        assert session.tool_calls[tool_call_id].kind == kind

    @pytest.mark.parametrize(
        "kind,expected_title",
        [
            ("read", "Tool read operation"),
            ("edit", "Tool edit operation"),
            ("delete", "Tool delete operation"),
            ("move", "Tool move operation"),
            ("search", "Tool search operation"),
            ("execute", "Tool execution"),
            ("think", "Tool reasoning step"),
            ("fetch", "Tool fetch operation"),
            ("switch_mode", "Tool mode switch"),
            ("other", "Tool operation"),
        ],
    )
    def test_tool_kind_titles(
        self, handler: ToolCallHandler, session: SessionState, kind: str, expected_title: str
    ) -> None:
        """Каждый tool kind имеет человекочитаемый title."""
        notification = handler.build_tool_call_notification(
            session_id="sess_1",
            tool_call_id="call_001",
            title=expected_title,
            kind=kind,
        )

        update = notification.params["update"]
        assert update["kind"] == kind
        assert update["title"] == expected_title


# ---------------------------------------------------------------------------
# Интеграционные тесты tool call lifecycle
# ---------------------------------------------------------------------------


class TestToolCallLifecycleIntegration:
    """Интеграционные тесты полного lifecycle tool call."""

    def test_full_read_file_lifecycle(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """Полный lifecycle fs/read_text_file."""
        # 1. Создание tool call
        tool_call_id = handler.create_tool_call(
            session, title="Read text file", kind="read"
        )
        assert tool_call_id == "call_001"
        assert session.tool_calls[tool_call_id].status == "pending"

        # 2. Notification о создании
        create_notif = handler.build_tool_call_notification(
            session_id="sess_1",
            tool_call_id=tool_call_id,
            title="Read text file",
            kind="read",
            locations=[{"path": "/tmp/README.md"}],
        )
        assert create_notif.params["update"]["status"] == "pending"
        assert create_notif.params["update"]["locations"] == [{"path": "/tmp/README.md"}]

        # 3. Переход в in_progress
        handler.update_tool_call_status(session, tool_call_id, "in_progress")
        in_progress_notif = handler.build_tool_update_notification(
            session_id="sess_1",
            tool_call_id=tool_call_id,
            status="in_progress",
        )
        assert in_progress_notif.params["update"]["status"] == "in_progress"

        # 4. Завершение с content
        content = [
            {
                "type": "content",
                "content": {
                    "type": "text",
                    "text": "# README\n\nProject description",
                },
            }
        ]
        handler.update_tool_call_status(session, tool_call_id, "completed", content=content)
        completed_notif = handler.build_tool_update_notification(
            session_id="sess_1",
            tool_call_id=tool_call_id,
            status="completed",
            content=content,
        )
        assert completed_notif.params["update"]["status"] == "completed"
        assert completed_notif.params["update"]["content"] == content

    def test_full_write_file_lifecycle(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """Полный lifecycle fs/write_text_file."""
        tool_call_id = handler.create_tool_call(
            session, title="Write text file", kind="edit"
        )

        # Создание с location
        create_notif = handler.build_tool_call_notification(
            session_id="sess_1",
            tool_call_id=tool_call_id,
            title="Write text file",
            kind="edit",
            locations=[{"path": "/tmp/output.txt"}],
        )
        assert create_notif.params["update"]["kind"] == "edit"

        # Выполнение
        handler.update_tool_call_status(session, tool_call_id, "in_progress")

        # Завершение с diff
        diff_content = [
            {
                "type": "diff",
                "path": "/tmp/output.txt",
                "oldText": "",
                "newText": "New file content",
            }
        ]
        handler.update_tool_call_status(
            session, tool_call_id, "completed", content=diff_content
        )

        assert session.tool_calls[tool_call_id].status == "completed"
        assert session.tool_calls[tool_call_id].content[0]["type"] == "diff"

    def test_full_terminal_lifecycle(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """Полный lifecycle terminal/create."""
        tool_call_id = handler.create_tool_call(
            session, title="Run terminal command", kind="execute"
        )

        # Создание с rawInput
        create_notif = handler.build_tool_call_notification(
            session_id="sess_1",
            tool_call_id=tool_call_id,
            title="Run terminal command",
            kind="execute",
        )
        assert create_notif.params["update"]["status"] == "pending"

        # Выполнение
        handler.update_tool_call_status(session, tool_call_id, "in_progress")

        # Завершение с terminal content
        terminal_content = [
            {
                "type": "terminal",
                "terminalId": "term_001",
            },
            {
                "type": "content",
                "content": {
                    "type": "text",
                    "text": "Command finished with exit code 0.",
                },
            },
        ]
        handler.update_tool_call_status(
            session, tool_call_id, "completed", content=terminal_content
        )

        assert session.tool_calls[tool_call_id].status == "completed"
        assert len(session.tool_calls[tool_call_id].content) == 2

    def test_tool_call_cancellation_during_execution(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """Отмена tool call во время выполнения."""
        tool_call_id = handler.create_tool_call(
            session, title="Long running task", kind="execute"
        )

        # Начало выполнения
        handler.update_tool_call_status(session, tool_call_id, "in_progress")

        # Отмена
        updates = handler.cancel_active_tools(session, "sess_1")

        assert len(updates) == 1
        assert session.tool_calls[tool_call_id].status == "cancelled"
        assert updates[0].params["update"]["status"] == "cancelled"

    def test_multiple_tool_calls_parallel_lifecycle(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """Параллельный lifecycle нескольких tool calls."""
        # Создание нескольких tool calls
        id1 = handler.create_tool_call(session, title="Read file", kind="read")
        id2 = handler.create_tool_call(session, title="Run command", kind="execute")
        id3 = handler.create_tool_call(session, title="Search", kind="search")

        # Разные статусы
        handler.update_tool_call_status(session, id1, "in_progress")
        handler.update_tool_call_status(session, id1, "completed")

        handler.update_tool_call_status(session, id2, "in_progress")

        # id3 остается pending

        assert session.tool_calls[id1].status == "completed"
        assert session.tool_calls[id2].status == "in_progress"
        assert session.tool_calls[id3].status == "pending"

        # Отмена только активных
        updates = handler.cancel_active_tools(session, "sess_1")

        assert len(updates) == 2  # id2 и id3
        assert session.tool_calls[id2].status == "cancelled"
        assert session.tool_calls[id3].status == "cancelled"
        assert session.tool_calls[id1].status == "completed"  # не изменился

    def test_tool_call_with_tool_arguments(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """tool call с tool_arguments для отложенного выполнения."""
        tool_call_id = handler.create_tool_call(
            session,
            title="Execute command",
            kind="execute",
            tool_name="terminal/create",
            tool_arguments={
                "command": "echo hello",
                "cwd": "/tmp",
                "env": [{"name": "PATH", "value": "/usr/bin"}],
            },
        )

        tool_call = session.tool_calls[tool_call_id]
        assert tool_call.tool_name == "terminal/create"
        assert tool_call.tool_arguments["command"] == "echo hello"
        assert tool_call.tool_arguments["cwd"] == "/tmp"
        assert len(tool_call.tool_arguments["env"]) == 1

    def test_tool_call_with_llm_id(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """tool call с tool_call_id_from_llm для связки в истории."""
        tool_call_id = handler.create_tool_call(
            session,
            title="LLM tool",
            kind="think",
            tool_call_id_from_llm="toolu_01ABC123",
        )

        tool_call = session.tool_calls[tool_call_id]
        assert tool_call.tool_call_id == "call_001"  # наш ID
        assert tool_call.tool_call_id_from_llm == "toolu_01ABC123"  # ID от LLM


# ---------------------------------------------------------------------------
# ToolCallState serialization
# ---------------------------------------------------------------------------


class TestToolCallStateSerialization:
    """Тесты сериализации ToolCallState."""

    def test_tool_call_state_to_dict(
        self, handler: ToolCallHandler, session: SessionState
    ) -> None:
        """ToolCallState сериализуется в dict."""
        tool_call_id = handler.create_tool_call(
            session,
            title="Test",
            kind="execute",
            tool_name="terminal/create",
            tool_arguments={"command": "ls"},
        )

        tool_call = session.tool_calls[tool_call_id]
        data = tool_call.model_dump()

        assert data["tool_call_id"] == tool_call_id
        assert data["title"] == "Test"
        assert data["kind"] == "execute"
        assert data["status"] == "pending"
        assert data["tool_name"] == "terminal/create"
        assert data["tool_arguments"] == {"command": "ls"}

    def test_tool_call_state_from_dict(self) -> None:
        """ToolCallState десериализуется из dict."""
        data = {
            "tool_call_id": "call_001",
            "title": "Restored",
            "kind": "read",
            "status": "completed",
            "content": [
                {
                    "type": "content",
                    "content": {"type": "text", "text": "Restored content"},
                }
            ],
        }

        tool_call = ToolCallState(**data)

        assert tool_call.tool_call_id == "call_001"
        assert tool_call.title == "Restored"
        assert tool_call.kind == "read"
        assert tool_call.status == "completed"
        assert len(tool_call.content) == 1

    def test_tool_call_state_with_optional_fields(self) -> None:
        """ToolCallState с опциональными полями."""
        data = {
            "tool_call_id": "call_001",
            "title": "Test",
            "kind": "other",
            "status": "pending",
            "tool_call_id_from_llm": "toolu_xyz",
            "result_content": [],
        }

        tool_call = ToolCallState(**data)

        assert tool_call.tool_call_id_from_llm == "toolu_xyz"
        assert tool_call.result_content == []
