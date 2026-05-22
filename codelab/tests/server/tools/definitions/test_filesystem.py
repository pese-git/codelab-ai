"""Тесты для нормализации путей в файловых инструментах."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from codelab.server.protocol.state import SessionState
from codelab.server.tools.base import ToolDefinition, ToolExecutionResult
from codelab.server.tools.definitions.filesystem import (
    FileSystemToolDefinitions,
    _normalize_path,
)


class TestNormalizePath:
    """Тесты функции нормализации путей."""

    def test_relative_path(self) -> None:
        """Относительный путь должен быть присоединён к cwd."""
        result = _normalize_path("/workspace", "README.md")
        assert result == "/workspace/README.md"

    def test_absolute_path_unchanged(self) -> None:
        """Абсолютный путь должен остаться без изменений."""
        result = _normalize_path("/workspace", "/tmp/file.txt")
        assert result == "/tmp/file.txt"

    def test_dot_relative_path(self) -> None:
        """Путь с ./ должен быть нормализован относительно cwd."""
        result = _normalize_path("/workspace", "./src/main.py")
        assert result == "/workspace/src/main.py"

    def test_parent_relative_path(self) -> None:
        """Путь с ../ должен быть нормализован относительно cwd."""
        result = _normalize_path("/workspace", "../other/file.txt")
        assert result == "/workspace/../other/file.txt"

    def test_nested_relative_path(self) -> None:
        """Вложенный относительный путь должен быть нормализован."""
        result = _normalize_path("/workspace", "src/utils/helpers.py")
        assert result == "/workspace/src/utils/helpers.py"

    def test_empty_cwd_with_absolute_path(self) -> None:
        """Абсолютный путь должен работать даже с пустым cwd."""
        result = _normalize_path("", "/tmp/file.txt")
        assert result == "/tmp/file.txt"


class TestReadHandlerNormalizesPath:
    """Тесты что read_handler нормализует путь."""

    @pytest.mark.asyncio
    async def test_read_handler_normalizes_relative_path(self) -> None:
        """Read handler должен нормализовать относительный путь."""
        mock_executor = MagicMock()
        mock_execute = AsyncMock(return_value=ToolExecutionResult(success=True, output="content"))
        mock_executor.execute = mock_execute

        FileSystemToolDefinitions.register_all(
            tool_registry=FakeRegistry(),
            executor=mock_executor,
        )

        session = SessionState(session_id="sess_1", cwd="/workspace")
        handler = FakeRegistry.read_handler

        await handler(session=session, path="README.md")

        mock_execute.assert_called_once()
        call_args = mock_execute.call_args
        # execute вызывается как executor.execute(session, arguments)
        arguments = call_args[0][1]
        assert arguments["path"] == "/workspace/README.md"
        assert arguments["operation"] == "read"

    @pytest.mark.asyncio
    async def test_read_handler_keeps_absolute_path(self) -> None:
        """Read handler должен сохранить абсолютный путь без изменений."""
        mock_executor = MagicMock()
        mock_execute = AsyncMock(return_value=ToolExecutionResult(success=True, output="content"))
        mock_executor.execute = mock_execute

        FileSystemToolDefinitions.register_all(
            tool_registry=FakeRegistry(),
            executor=mock_executor,
        )

        session = SessionState(session_id="sess_1", cwd="/workspace")
        handler = FakeRegistry.read_handler

        await handler(session=session, path="/tmp/file.txt")

        mock_execute.assert_called_once()
        call_args = mock_execute.call_args
        arguments = call_args[0][1]
        assert arguments["path"] == "/tmp/file.txt"


class TestWriteHandlerNormalizesPath:
    """Тесты что write_handler нормализует путь."""

    @pytest.mark.asyncio
    async def test_write_handler_normalizes_relative_path(self) -> None:
        """Write handler должен нормализовать относительный путь."""
        mock_executor = MagicMock()
        mock_execute = AsyncMock(return_value=ToolExecutionResult(success=True, output="written"))
        mock_executor.execute = mock_execute

        FileSystemToolDefinitions.register_all(
            tool_registry=FakeRegistry(),
            executor=mock_executor,
        )

        session = SessionState(session_id="sess_1", cwd="/workspace")
        handler = FakeRegistry.write_handler

        await handler(session=session, path="output.txt", content="hello")

        mock_execute.assert_called_once()
        call_args = mock_execute.call_args
        arguments = call_args[0][1]
        assert arguments["path"] == "/workspace/output.txt"
        assert arguments["operation"] == "write"

    @pytest.mark.asyncio
    async def test_write_handler_keeps_absolute_path(self) -> None:
        """Write handler должен сохранить абсолютный путь без изменений."""
        mock_executor = MagicMock()
        mock_execute = AsyncMock(return_value=ToolExecutionResult(success=True, output="written"))
        mock_executor.execute = mock_execute

        FileSystemToolDefinitions.register_all(
            tool_registry=FakeRegistry(),
            executor=mock_executor,
        )

        session = SessionState(session_id="sess_1", cwd="/workspace")
        handler = FakeRegistry.write_handler

        await handler(session=session, path="/tmp/output.txt", content="hello")

        mock_execute.assert_called_once()
        call_args = mock_execute.call_args
        arguments = call_args[0][1]
        assert arguments["path"] == "/tmp/output.txt"


class FakeRegistry:
    """Фейковый реестр для захвата handlers."""

    read_handler = None
    write_handler = None

    def register(self, tool: ToolDefinition, handler) -> None:
        if tool.name == "fs/read_text_file":
            FakeRegistry.read_handler = handler
        elif tool.name == "fs/write_text_file":
            FakeRegistry.write_handler = handler
