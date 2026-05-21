"""Тесты для TerminalHandler.

Проверяют:
- Обработку create запросов
- Обработку output запросов
- Обработку wait_for_exit запросов
- Обработку kill запросов
- Обработку release запросов
- Валидацию параметров
- Обработку ошибок от executor
"""

from unittest.mock import AsyncMock

import pytest

from codelab.client.infrastructure.handlers.terminal_handler import TerminalHandler
from codelab.client.infrastructure.services.terminal_executor import TerminalExecutor

# Маркируем все async тесты в модуле
pytestmark = pytest.mark.asyncio


@pytest.fixture
def executor_mock() -> AsyncMock:
    """Mock TerminalExecutor."""
    return AsyncMock(spec=TerminalExecutor)


@pytest.fixture
def handler(executor_mock: AsyncMock) -> TerminalHandler:
    """TerminalHandler с mock executor."""
    return TerminalHandler(executor_mock)


class TestTerminalHandlerCreate:
    """Тесты для обработки create."""

    async def test_handle_create_success(
        self, handler: TerminalHandler, executor_mock: AsyncMock
    ) -> None:
        """Тест успешного создания терминала."""
        executor_mock.create_terminal.return_value = "term_abc123"
        params = {
            "sessionId": "sess_123",
            "command": "python",
            "args": ["-m", "pytest"],
            "cwd": "/project",
            "output_byte_limit": 10000,
        }

        result = await handler.handle_create(params)

        assert result == {"terminalId": "term_abc123"}
        executor_mock.create_terminal.assert_called_once_with(
            command="python",
            args=["-m", "pytest"],
            env=None,
            cwd="/project",
            output_byte_limit=10000,
        )

    async def test_handle_create_minimal_params(
        self, handler: TerminalHandler, executor_mock: AsyncMock
    ) -> None:
        """Тест создания с минимальными параметрами."""
        executor_mock.create_terminal.return_value = "term_123"
        params = {"sessionId": "sess_123", "command": "bash"}

        result = await handler.handle_create(params)

        assert result == {"terminalId": "term_123"}
        executor_mock.create_terminal.assert_called_once_with(
            command="bash",
            args=None,
            env=None,
            cwd=None,
            output_byte_limit=None,
        )

    async def test_handle_create_missing_command(
        self, handler: TerminalHandler
    ) -> None:
        """Тест ошибки при отсутствии command."""
        params = {"sessionId": "sess_123"}

        with pytest.raises(ValueError, match="Missing required parameter: command"):
            await handler.handle_create(params)

    async def test_handle_create_executor_error(
        self, handler: TerminalHandler, executor_mock: AsyncMock
    ) -> None:
        """Тест ошибки от executor."""
        executor_mock.create_terminal.side_effect = RuntimeError(
            "Failed to start process"
        )
        params = {"sessionId": "sess_123", "command": "invalid_cmd"}

        with pytest.raises(RuntimeError):
            await handler.handle_create(params)


class TestTerminalHandlerOutput:
    """Тесты для обработки output."""

    async def test_handle_output_success(
        self, handler: TerminalHandler, executor_mock: AsyncMock
    ) -> None:
        """Тест успешного получения output."""
        executor_mock.get_output.return_value = ("Hello, World!\n", True, 0)
        params = {"sessionId": "sess_123", "terminalId": "term_abc"}

        result = await handler.handle_output(params)

        assert result == {
            "output": "Hello, World!\n",
            "isComplete": True,
            "exitCode": 0,
        }
        executor_mock.get_output.assert_called_once_with("term_abc")

    async def test_handle_output_running(
        self, handler: TerminalHandler, executor_mock: AsyncMock
    ) -> None:
        """Тест output из работающего процесса."""
        executor_mock.get_output.return_value = ("Some output", False, None)
        params = {"sessionId": "sess_123", "terminalId": "term_abc"}

        result = await handler.handle_output(params)

        assert result == {
            "output": "Some output",
            "isComplete": False,
            "exitCode": None,
        }

    async def test_handle_output_missing_id(
        self, handler: TerminalHandler
    ) -> None:
        """Тест ошибки при отсутствии terminalId."""
        params = {"sessionId": "sess_123"}

        with pytest.raises(
            ValueError, match="Missing required parameter: terminalId"
        ):
            await handler.handle_output(params)

    async def test_handle_output_not_found(
        self, handler: TerminalHandler, executor_mock: AsyncMock
    ) -> None:
        """Тест ошибки когда терминал не найден."""
        executor_mock.get_output.side_effect = ValueError("Terminal not found")
        params = {"sessionId": "sess_123", "terminalId": "nonexistent"}

        with pytest.raises(ValueError):
            await handler.handle_output(params)


class TestTerminalHandlerWaitForExit:
    """Тесты для обработки wait_for_exit."""

    async def test_handle_wait_for_exit_success(
        self, handler: TerminalHandler, executor_mock: AsyncMock
    ) -> None:
        """Тест успешного ожидания завершения."""
        executor_mock.wait_for_exit.return_value = 0
        executor_mock.get_output.return_value = ("output text", True, 0)
        params = {"sessionId": "sess_123", "terminalId": "term_abc"}

        result = await handler.handle_wait_for_exit(params)

        assert result["exitCode"] == 0
        executor_mock.wait_for_exit.assert_called_once_with("term_abc")

    async def test_handle_wait_for_exit_error_code(
        self, handler: TerminalHandler, executor_mock: AsyncMock
    ) -> None:
        """Тест ожидания с non-zero exit code."""
        executor_mock.wait_for_exit.return_value = 1
        executor_mock.get_output.return_value = ("error output", True, 1)
        params = {"sessionId": "sess_123", "terminalId": "term_abc"}

        result = await handler.handle_wait_for_exit(params)

        assert result["exitCode"] == 1

    async def test_handle_wait_for_exit_missing_id(
        self, handler: TerminalHandler
    ) -> None:
        """Тест ошибки при отсутствии terminalId."""
        params = {"sessionId": "sess_123"}

        with pytest.raises(
            ValueError, match="Missing required parameter: terminalId"
        ):
            await handler.handle_wait_for_exit(params)

    async def test_handle_wait_for_exit_not_found(
        self, handler: TerminalHandler, executor_mock: AsyncMock
    ) -> None:
        """Тест ошибки когда терминал не найден."""
        executor_mock.wait_for_exit.side_effect = ValueError(
            "Terminal not found"
        )
        params = {"sessionId": "sess_123", "terminalId": "nonexistent"}

        with pytest.raises(ValueError):
            await handler.handle_wait_for_exit(params)


class TestTerminalHandlerKill:
    """Тесты для обработки kill."""

    async def test_handle_kill_success(
        self, handler: TerminalHandler, executor_mock: AsyncMock
    ) -> None:
        """Тест успешного убийства процесса."""
        executor_mock.kill_terminal.return_value = True
        params = {"sessionId": "sess_123", "terminalId": "term_abc"}

        result = await handler.handle_kill(params)

        assert result == {"success": True}
        executor_mock.kill_terminal.assert_called_once_with("term_abc")

    async def test_handle_kill_missing_id(
        self, handler: TerminalHandler
    ) -> None:
        """Тест ошибки при отсутствии terminalId."""
        params = {"sessionId": "sess_123"}

        with pytest.raises(
            ValueError, match="Missing required parameter: terminalId"
        ):
            await handler.handle_kill(params)

    async def test_handle_kill_not_found(
        self, handler: TerminalHandler, executor_mock: AsyncMock
    ) -> None:
        """Тест ошибки когда терминал не найден."""
        executor_mock.kill_terminal.side_effect = ValueError(
            "Terminal not found"
        )
        params = {"sessionId": "sess_123", "terminalId": "nonexistent"}

        with pytest.raises(ValueError):
            await handler.handle_kill(params)

    async def test_handle_kill_executor_error(
        self, handler: TerminalHandler, executor_mock: AsyncMock
    ) -> None:
        """Тест ошибки от executor."""
        executor_mock.kill_terminal.side_effect = RuntimeError("Failed to kill")
        params = {"sessionId": "sess_123", "terminalId": "term_abc"}

        with pytest.raises(RuntimeError):
            await handler.handle_kill(params)


class TestTerminalHandlerRelease:
    """Тесты для обработки release."""

    async def test_handle_release_success(
        self, handler: TerminalHandler, executor_mock: AsyncMock
    ) -> None:
        """Тест успешного освобождения ресурсов."""
        executor_mock.release_terminal.return_value = True
        params = {"sessionId": "sess_123", "terminalId": "term_abc"}

        result = await handler.handle_release(params)

        assert result == {"success": True}
        executor_mock.release_terminal.assert_called_once_with("term_abc")

    async def test_handle_release_missing_id(
        self, handler: TerminalHandler
    ) -> None:
        """Тест ошибки при отсутствии terminalId."""
        params = {"sessionId": "sess_123"}

        with pytest.raises(
            ValueError, match="Missing required parameter: terminalId"
        ):
            await handler.handle_release(params)

    async def test_handle_release_not_found(
        self, handler: TerminalHandler, executor_mock: AsyncMock
    ) -> None:
        """Тест ошибки когда терминал не найден."""
        executor_mock.release_terminal.side_effect = ValueError(
            "Terminal not found"
        )
        params = {"sessionId": "sess_123", "terminalId": "nonexistent"}

        with pytest.raises(ValueError):
            await handler.handle_release(params)
