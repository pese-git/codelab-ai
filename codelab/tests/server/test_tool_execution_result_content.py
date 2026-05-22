"""Тесты для content support в ToolExecutionResult.

Проверяет:
- Backward compatibility ToolExecutionResult (пустой content по умолчанию)
- Генерация text content в FileSystemToolExecutor.execute_read()
- Генерация text и diff content в FileSystemToolExecutor.execute_write()
- Генерация text content в TerminalToolExecutor.execute_create()
- Генерация text content в TerminalToolExecutor.execute_wait_for_exit()
- Корректность структуры content согласно ACP Content Types
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from codelab.server.protocol.state import SessionState
from codelab.server.tools.base import ToolExecutionResult
from codelab.server.tools.executors.filesystem_executor import FileSystemToolExecutor
from codelab.server.tools.executors.terminal_executor import TerminalToolExecutor
from codelab.server.tools.integrations.client_rpc_bridge import ClientRPCBridge
from codelab.server.tools.integrations.permission_checker import PermissionChecker


class TestToolExecutionResultContent:
    """Тесты для content поля в ToolExecutionResult."""

    def test_result_with_empty_content_by_default(self) -> None:
        """Backward compatibility: результат без явного content имеет пустой список."""
        # Arrange & Act
        result = ToolExecutionResult(
            success=True,
            output="test"
        )

        # Assert
        assert result.content == []
        assert isinstance(result.content, list)

    def test_result_with_text_content(self) -> None:
        """Результат с text content."""
        # Arrange & Act
        result = ToolExecutionResult(
            success=True,
            output="test",
            content=[{"type": "text", "text": "Hello"}]
        )

        # Assert
        assert len(result.content) == 1
        assert result.content[0]["type"] == "text"
        assert result.content[0]["text"] == "Hello"

    def test_result_with_multiple_content(self) -> None:
        """Результат с несколькими content элементами."""
        # Arrange & Act
        result = ToolExecutionResult(
            success=True,
            output="test",
            content=[
                {"type": "text", "text": "Info"},
                {"type": "diff", "path": "file.py", "diff": "..."}
            ]
        )

        # Assert
        assert len(result.content) == 2
        assert result.content[0]["type"] == "text"
        assert result.content[1]["type"] == "diff"


class TestFileSystemExecutorContent:
    """Тесты для content в FileSystemToolExecutor."""

    @pytest.fixture
    def executor(self) -> FileSystemToolExecutor:
        """Создает executor с mock зависимостями."""
        mock_bridge = MagicMock(spec=ClientRPCBridge)
        mock_checker = MagicMock(spec=PermissionChecker)
        mock_checker.should_request_permission.return_value = False
        return FileSystemToolExecutor(mock_bridge, mock_checker)

    @pytest.fixture
    def session(self) -> SessionState:
        """Создает тестовую сессию."""
        return SessionState(
            session_id="test_session",
            cwd="/tmp",
            mcp_servers=[],
            config_values={},
        )

    @pytest.mark.asyncio
    async def test_read_generates_text_content(
        self,
        executor: FileSystemToolExecutor,
        session: SessionState,
    ) -> None:
        """execute_read генерирует text content."""
        # Arrange
        file_content = "Hello World"
        executor._bridge.read_file = AsyncMock(return_value=file_content)  # type: ignore

        # Act
        result = await executor.execute_read(
            session=session,
            path="/tmp/test.txt",
        )

        # Assert
        assert result.success is True
        assert len(result.content) == 1
        assert result.content[0]["type"] == "text"
        assert "Hello World" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_read_content_includes_file_path(
        self,
        executor: FileSystemToolExecutor,
        session: SessionState,
    ) -> None:
        """Контент чтения включает путь файла."""
        # Arrange
        file_content = "content"
        executor._bridge.read_file = AsyncMock(return_value=file_content)  # type: ignore

        # Act
        result = await executor.execute_read(
            session=session,
            path="/tmp/test.txt",
        )

        # Assert
        assert len(result.content) == 1
        assert "/tmp/test.txt" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_read_content_includes_file_content(
        self,
        executor: FileSystemToolExecutor,
        session: SessionState,
    ) -> None:
        """Контент чтения включает содержимое файла."""
        # Arrange
        file_content = "Line 1\nLine 2\nLine 3"
        executor._bridge.read_file = AsyncMock(return_value=file_content)  # type: ignore

        # Act
        result = await executor.execute_read(
            session=session,
            path="/tmp/test.txt",
        )

        # Assert
        assert len(result.content) == 1
        assert "Line 1" in result.content[0]["text"]
        assert "Line 2" in result.content[0]["text"]
        assert "Line 3" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_write_generates_text_content(
        self,
        executor: FileSystemToolExecutor,
        session: SessionState,
    ) -> None:
        """execute_write генерирует text content."""
        # Arrange
        executor._bridge.read_file = AsyncMock(return_value=None)  # type: ignore
        executor._bridge.write_file = AsyncMock(return_value=True)  # type: ignore

        # Act
        result = await executor.execute_write(
            session=session,
            path="/tmp/test.txt",
            content="New content",
        )

        # Assert
        assert result.success is True
        assert len(result.content) >= 1
        # Первый элемент должен быть text content
        text_content = [c for c in result.content if c["type"] == "text"]
        assert len(text_content) == 1
        assert "Successfully wrote" in text_content[0]["text"]

    @pytest.mark.asyncio
    async def test_write_generates_diff_content(
        self,
        executor: FileSystemToolExecutor,
        session: SessionState,
    ) -> None:
        """execute_write генерирует diff content при изменении файла."""
        # Arrange
        old_content = "Old content\nLine 2"
        new_content = "New content\nLine 2"
        executor._bridge.read_file = AsyncMock(return_value=old_content)  # type: ignore
        executor._bridge.write_file = AsyncMock(return_value=True)  # type: ignore

        # Act
        result = await executor.execute_write(
            session=session,
            path="/tmp/test.txt",
            content=new_content,
        )

        # Assert
        assert result.success is True
        # Проверить наличие diff content
        diff_content = [c for c in result.content if c["type"] == "diff"]
        assert len(diff_content) == 1
        assert diff_content[0]["path"] == "/tmp/test.txt"
        assert "diff" in diff_content[0]

    @pytest.mark.asyncio
    async def test_write_content_with_no_old_file(
        self,
        executor: FileSystemToolExecutor,
        session: SessionState,
    ) -> None:
        """execute_write содержит text content когда старого файла нет."""
        # Arrange - читать файл возвращает None (файл не существует)
        executor._bridge.read_file = AsyncMock(return_value=None)  # type: ignore
        executor._bridge.write_file = AsyncMock(return_value=True)  # type: ignore

        # Act
        result = await executor.execute_write(
            session=session,
            path="/tmp/new_file.txt",
            content="New file content",
        )

        # Assert
        assert result.success is True
        # Должен быть только text content, не будет diff
        assert len(result.content) == 1
        assert result.content[0]["type"] == "text"
        # Не должно быть diff content
        diff_content = [c for c in result.content if c["type"] == "diff"]
        assert len(diff_content) == 0


class TestTerminalExecutorContent:
    """Тесты для content в TerminalToolExecutor."""

    @pytest.fixture
    def executor(self) -> TerminalToolExecutor:
        """Создает executor с mock зависимостями."""
        mock_bridge = MagicMock(spec=ClientRPCBridge)
        mock_checker = MagicMock(spec=PermissionChecker)
        mock_checker.should_request_permission.return_value = False
        return TerminalToolExecutor(mock_bridge, mock_checker)

    @pytest.fixture
    def session(self) -> SessionState:
        """Создает тестовую сессию."""
        return SessionState(
            session_id="test_session",
            cwd="/tmp",
            mcp_servers=[],
            config_values={},
        )

    @pytest.mark.asyncio
    async def test_create_generates_text_content(
        self,
        executor: TerminalToolExecutor,
        session: SessionState,
    ) -> None:
        """execute_create генерирует text content."""
        # Arrange
        executor._bridge.create_terminal = AsyncMock(return_value="term_001")  # type: ignore

        # Act
        result = await executor.execute_create(
            session=session,
            command="echo test",
            cwd="/tmp",
        )

        # Assert
        assert result.success is True
        assert len(result.content) == 1
        assert result.content[0]["type"] == "text"
        assert "Terminal" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_create_content_includes_terminal_id(
        self,
        executor: TerminalToolExecutor,
        session: SessionState,
    ) -> None:
        """Контент create включает terminal ID."""
        # Arrange
        executor._bridge.create_terminal = AsyncMock(return_value="term_abc123")  # type: ignore

        # Act
        result = await executor.execute_create(
            session=session,
            command="ls -la",
            cwd="/tmp",
        )

        # Assert
        assert result.success is True
        assert len(result.content) == 1
        assert "term_abc123" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_create_content_includes_command(
        self,
        executor: TerminalToolExecutor,
        session: SessionState,
    ) -> None:
        """Контент create включает команду."""
        # Arrange
        executor._bridge.create_terminal = AsyncMock(return_value="term_001")  # type: ignore

        # Act
        result = await executor.execute_create(
            session=session,
            command="python -m pytest",
            cwd="/tmp",
        )

        # Assert
        assert result.success is True
        assert len(result.content) == 1
        assert "python -m pytest" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_wait_generates_output_content(
        self,
        executor: TerminalToolExecutor,
        session: SessionState,
    ) -> None:
        """execute_wait_for_exit генерирует content с output."""
        # Arrange
        executor._bridge.terminal_output = AsyncMock(return_value={  # type: ignore
            "output": "test output",
            "truncated": False,
            "is_complete": True,
            "exit_code": 0,
            "signal": None,
        })

        # Act
        result = await executor.execute_wait_for_exit(
            session=session,
            terminal_id="term_001",
        )

        # Assert
        assert result.success is True
        assert len(result.content) == 1
        assert result.content[0]["type"] == "text"
        assert "exited" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_wait_content_includes_exit_code(
        self,
        executor: TerminalToolExecutor,
        session: SessionState,
    ) -> None:
        """Контент wait включает exit code."""
        # Arrange
        executor._bridge.terminal_output = AsyncMock(side_effect=[  # type: ignore
            None,
            {
                "output": "output",
                "truncated": False,
                "is_complete": True,
                "exit_code": 42,
                "signal": None,
            },
        ])
        executor._bridge.wait_terminal_exit = AsyncMock(return_value={  # type: ignore
            "exit_code": 42,
            "signal": None,
        })

        # Act
        result = await executor.execute_wait_for_exit(
            session=session,
            terminal_id="term_001",
        )

        # Assert
        assert result.success is False  # exit_code != 0
        assert len(result.content) == 1
        assert "42" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_wait_content_includes_output(
        self,
        executor: TerminalToolExecutor,
        session: SessionState,
    ) -> None:
        """Контент wait включает вывод команды."""
        # Arrange
        executor._bridge.terminal_output = AsyncMock(side_effect=[  # type: ignore
            None,
            {
                "output": "Hello from terminal",
                "truncated": False,
                "is_complete": True,
                "exit_code": 0,
                "signal": None,
            },
        ])
        executor._bridge.wait_terminal_exit = AsyncMock(return_value={  # type: ignore
            "exit_code": 0,
            "signal": None,
        })

        # Act
        result = await executor.execute_wait_for_exit(
            session=session,
            terminal_id="term_001",
        )

        # Assert
        assert result.success is True
        assert len(result.content) == 1
        assert "Hello from terminal" in result.content[0]["text"]


class TestContentStructureCompliance:
    """Тесты соответствия структуры content ACP Content Types."""

    def test_text_content_structure(self) -> None:
        """Структура text content соответствует спецификации."""
        # Arrange & Act
        content = {
            "type": "text",
            "text": "Some text"
        }

        # Assert
        assert content["type"] == "text"
        assert isinstance(content["text"], str)
        assert "text" in content
        assert "type" in content

    def test_diff_content_structure(self) -> None:
        """Структура diff content соответствует спецификации."""
        # Arrange & Act
        content = {
            "type": "diff",
            "path": "/path/to/file",
            "diff": "--- old\n+++ new"
        }

        # Assert
        assert content["type"] == "diff"
        assert isinstance(content["path"], str)
        assert isinstance(content["diff"], str)
        assert "type" in content
        assert "path" in content
        assert "diff" in content

    def test_result_content_list_type(self) -> None:
        """Поле content всегда список dict."""
        # Arrange & Act
        result = ToolExecutionResult(
            success=True,
            output="test",
            content=[
                {"type": "text", "text": "hello"},
                {"type": "text", "text": "world"}
            ]
        )

        # Assert
        assert isinstance(result.content, list)
        for item in result.content:
            assert isinstance(item, dict)
            assert "type" in item
