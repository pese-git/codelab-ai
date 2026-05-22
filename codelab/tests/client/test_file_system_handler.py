"""Тесты для FileSystemHandler.

Проверяют:
- Обработку read_text_file запросов
- Обработку write_text_file запросов
- Валидацию параметров
- Обработку ошибок от executor
"""

from unittest.mock import AsyncMock

import pytest

from codelab.client.infrastructure.handlers.file_system_handler import (
    FileSystemHandler,
)
from codelab.client.infrastructure.services.file_system_executor import (
    FileSystemExecutor,
)

# Маркируем все async тесты в модуле
pytestmark = pytest.mark.asyncio


@pytest.fixture
def executor_mock() -> AsyncMock:
    """Mock FileSystemExecutor."""
    return AsyncMock(spec=FileSystemExecutor)


@pytest.fixture
def handler(executor_mock: AsyncMock) -> FileSystemHandler:
    """FileSystemHandler с mock executor."""
    return FileSystemHandler(executor_mock)


class TestFileSystemHandlerReadFile:
    """Тесты для обработки read_text_file."""

    async def test_handle_read_text_file_success(
        self, handler: FileSystemHandler, executor_mock: AsyncMock
    ) -> None:
        """Тест успешного чтения файла."""
        # Подготовка
        test_content = "Hello, World!"
        executor_mock.read_text_file.return_value = test_content
        params = {
            "sessionId": "sess_123",
            "path": "test.txt",
            "line": 1,
            "limit": 10,
        }

        # Действие
        result = await handler.handle_read_text_file(params)

        # Проверка
        assert result == {"content": test_content}
        executor_mock.read_text_file.assert_called_once_with(
            "test.txt", line=1, limit=10
        )

    async def test_handle_read_text_file_no_range(
        self, handler: FileSystemHandler, executor_mock: AsyncMock
    ) -> None:
        """Тест чтения без диапазона строк."""
        executor_mock.read_text_file.return_value = "Full content"
        params = {"sessionId": "sess_123", "path": "file.txt"}

        result = await handler.handle_read_text_file(params)

        assert result == {"content": "Full content"}
        executor_mock.read_text_file.assert_called_once_with(
            "file.txt", line=None, limit=None
        )

    async def test_handle_read_text_file_missing_path(
        self, handler: FileSystemHandler
    ) -> None:
        """Тест ошибки при отсутствии параметра path."""
        params = {"sessionId": "sess_123"}

        with pytest.raises(ValueError, match="Missing required parameter: path"):
            await handler.handle_read_text_file(params)

    async def test_handle_read_text_file_not_found(
        self, handler: FileSystemHandler, executor_mock: AsyncMock
    ) -> None:
        """Тест ошибки когда файл не найден."""
        executor_mock.read_text_file.side_effect = FileNotFoundError(
            "File not found"
        )
        params = {"sessionId": "sess_123", "path": "nonexistent.txt"}

        with pytest.raises(FileNotFoundError):
            await handler.handle_read_text_file(params)

    async def test_handle_read_text_file_io_error(
        self, handler: FileSystemHandler, executor_mock: AsyncMock
    ) -> None:
        """Тест ошибки IO."""
        executor_mock.read_text_file.side_effect = OSError("Permission denied")
        params = {"sessionId": "sess_123", "path": "test.txt"}

        with pytest.raises(IOError):
            await handler.handle_read_text_file(params)


class TestFileSystemHandlerWriteFile:
    """Тесты для обработки write_text_file."""

    async def test_handle_write_text_file_success(
        self, handler: FileSystemHandler, executor_mock: AsyncMock
    ) -> None:
        """Тест успешной записи файла."""
        executor_mock.write_text_file.return_value = True
        params = {
            "sessionId": "sess_123",
            "path": "output.txt",
            "content": "New content",
        }

        result = await handler.handle_write_text_file(params)

        assert result == {}
        executor_mock.write_text_file.assert_called_once_with(
            "output.txt", "New content"
        )

    async def test_handle_write_text_file_missing_path(
        self, handler: FileSystemHandler
    ) -> None:
        """Тест ошибки при отсутствии параметра path."""
        params = {"sessionId": "sess_123", "content": "data"}

        with pytest.raises(ValueError, match="Missing required parameter: path"):
            await handler.handle_write_text_file(params)

    async def test_handle_write_text_file_missing_content(
        self, handler: FileSystemHandler
    ) -> None:
        """Тест ошибки при отсутствии параметра content."""
        params = {"sessionId": "sess_123", "path": "file.txt"}

        with pytest.raises(
            ValueError, match="Missing required parameter: content"
        ):
            await handler.handle_write_text_file(params)

    async def test_handle_write_text_file_io_error(
        self, handler: FileSystemHandler, executor_mock: AsyncMock
    ) -> None:
        """Тест ошибки IO при записи."""
        executor_mock.write_text_file.side_effect = OSError(
            "Permission denied"
        )
        params = {
            "sessionId": "sess_123",
            "path": "test.txt",
            "content": "data",
        }

        with pytest.raises(IOError):
            await handler.handle_write_text_file(params)

    async def test_handle_write_text_file_empty_content(
        self, handler: FileSystemHandler, executor_mock: AsyncMock
    ) -> None:
        """Тест записи пустого содержимого."""
        executor_mock.write_text_file.return_value = True
        params = {
            "sessionId": "sess_123",
            "path": "empty.txt",
            "content": "",
        }

        result = await handler.handle_write_text_file(params)

        assert result == {}
        executor_mock.write_text_file.assert_called_once_with("empty.txt", "")
