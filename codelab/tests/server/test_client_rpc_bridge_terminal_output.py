"""Тесты для ClientRPCBridge.terminal_output.

Покрывает:
- Успешное получение output терминала
- Обработка различных exit status (exit_code, signal)
- Обработка truncated output
- Обработка ошибок (capability missing, timeout, response error, general error)
- Логирование операций
- Интеграция с ClientRPCService
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from codelab.server.client_rpc.exceptions import (
    ClientCapabilityMissingError,
    ClientRPCError,
    ClientRPCResponseError,
    ClientRPCTimeoutError,
)
from codelab.server.client_rpc.service import ClientRPCService
from codelab.server.protocol.state import ClientRuntimeCapabilities, SessionState
from codelab.server.tools.integrations.client_rpc_bridge import ClientRPCBridge

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session() -> SessionState:
    """Фикстура для создания базовой сессии."""
    sess = SessionState(
        session_id="test_session_001",
        cwd="/tmp",
        mcp_servers=[],
    )
    sess.runtime_capabilities = ClientRuntimeCapabilities(
        terminal=True,
        fs_read=True,
        fs_write=True,
    )
    return sess


@pytest.fixture
def mock_rpc_service() -> AsyncMock:
    """Mock для ClientRPCService."""
    service = AsyncMock(spec=ClientRPCService)
    service.terminal_output = AsyncMock()
    return service


@pytest.fixture
def bridge(mock_rpc_service: AsyncMock) -> ClientRPCBridge:
    """Фикстура для создания ClientRPCBridge с mock сервисом."""
    return ClientRPCBridge(client_rpc_service=mock_rpc_service)


# ---------------------------------------------------------------------------
# Успешные сценарии
# ---------------------------------------------------------------------------


class TestTerminalOutputSuccess:
    """Тесты успешного получения output терминала."""

    @pytest.mark.asyncio
    async def test_terminal_output_running(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Получение output от работающего терминала (без exit status)."""
        mock_rpc_service.terminal_output.return_value = (
            "command output here",  # output
            False,                   # truncated
            None,                    # exit_code
            None,                    # signal
        )

        result = await bridge.terminal_output(session, terminal_id="term_001")

        assert result is not None
        assert result["output"] == "command output here"
        assert result["truncated"] is False
        assert result["is_complete"] is False
        assert result["exit_code"] is None
        assert result["signal"] is None

        mock_rpc_service.terminal_output.assert_called_once_with(
            session_id="test_session_001",
            terminal_id="term_001",
        )

    @pytest.mark.asyncio
    async def test_terminal_output_completed_with_exit_code(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Получение output от завершенного терминала с exit code."""
        mock_rpc_service.terminal_output.return_value = (
            "finished successfully",  # output
            False,                     # truncated
            0,                         # exit_code
            None,                      # signal
        )

        result = await bridge.terminal_output(session, terminal_id="term_002")

        assert result is not None
        assert result["output"] == "finished successfully"
        assert result["truncated"] is False
        assert result["is_complete"] is True
        assert result["exit_code"] == 0
        assert result["signal"] is None

    @pytest.mark.asyncio
    async def test_terminal_output_completed_with_non_zero_exit_code(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Получение output от терминала с ненулевым exit code."""
        mock_rpc_service.terminal_output.return_value = (
            "error: file not found",  # output
            False,                     # truncated
            1,                         # exit_code
            None,                      # signal
        )

        result = await bridge.terminal_output(session, terminal_id="term_003")

        assert result is not None
        assert result["is_complete"] is True
        assert result["exit_code"] == 1

    @pytest.mark.asyncio
    async def test_terminal_output_completed_with_signal(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Получение output от терминала завершенного сигналом."""
        mock_rpc_service.terminal_output.return_value = (
            "killed",                 # output
            False,                     # truncated
            None,                      # exit_code
            "SIGTERM",                 # signal
        )

        result = await bridge.terminal_output(session, terminal_id="term_004")

        assert result is not None
        assert result["is_complete"] is True
        assert result["exit_code"] is None
        assert result["signal"] == "SIGTERM"

    @pytest.mark.asyncio
    async def test_terminal_output_with_both_exit_code_and_signal(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Получение output с exit code и signal (редкий случай)."""
        mock_rpc_service.terminal_output.return_value = (
            "core dumped",            # output
            False,                     # truncated
            139,                       # exit_code (SIGSEGV)
            "SIGSEGV",                 # signal
        )

        result = await bridge.terminal_output(session, terminal_id="term_005")

        assert result is not None
        assert result["is_complete"] is True
        assert result["exit_code"] == 139
        assert result["signal"] == "SIGSEGV"

    @pytest.mark.asyncio
    async def test_terminal_output_truncated(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Получение truncated output."""
        mock_rpc_service.terminal_output.return_value = (
            "a" * 10000,              # output (большой)
            True,                      # truncated
            None,                      # exit_code
            None,                      # signal
        )

        result = await bridge.terminal_output(session, terminal_id="term_006")

        assert result is not None
        assert result["truncated"] is True
        assert len(result["output"]) == 10000
        assert result["is_complete"] is False

    @pytest.mark.asyncio
    async def test_terminal_output_empty(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Получение пустого output."""
        mock_rpc_service.terminal_output.return_value = (
            "",                        # output (пустой)
            False,                     # truncated
            None,                      # exit_code
            None,                      # signal
        )

        result = await bridge.terminal_output(session, terminal_id="term_007")

        assert result is not None
        assert result["output"] == ""
        assert result["is_complete"] is False

    @pytest.mark.asyncio
    async def test_terminal_output_passes_correct_session_id(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Проверка что передается правильный session_id."""
        mock_rpc_service.terminal_output.return_value = ("", False, None, None)

        await bridge.terminal_output(session, terminal_id="term_008")

        mock_rpc_service.terminal_output.assert_called_once_with(
            session_id="test_session_001",
            terminal_id="term_008",
        )

    @pytest.mark.asyncio
    async def test_terminal_output_passes_correct_terminal_id(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Проверка что передается правильный terminal_id."""
        mock_rpc_service.terminal_output.return_value = ("", False, None, None)

        await bridge.terminal_output(session, terminal_id="custom_term_id")

        mock_rpc_service.terminal_output.assert_called_once_with(
            session_id="test_session_001",
            terminal_id="custom_term_id",
        )


# ---------------------------------------------------------------------------
# Обработка ошибок
# ---------------------------------------------------------------------------


class TestTerminalOutputErrors:
    """Тесты обработки ошибок при получении output."""

    @pytest.mark.asyncio
    async def test_terminal_output_capability_missing(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Обработка отсутствия capability terminal."""
        mock_rpc_service.terminal_output.side_effect = ClientCapabilityMissingError(
            "terminal"
        )

        result = await bridge.terminal_output(session, terminal_id="term_001")

        assert result is None

    @pytest.mark.asyncio
    async def test_terminal_output_timeout(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Обработка timeout при получении output."""
        mock_rpc_service.terminal_output.side_effect = ClientRPCTimeoutError(
            "Request timed out after 5.0s"
        )

        result = await bridge.terminal_output(session, terminal_id="term_002")

        assert result is None

    @pytest.mark.asyncio
    async def test_terminal_output_response_error(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Обработка ошибки response от клиента."""
        mock_rpc_service.terminal_output.side_effect = ClientRPCResponseError(
            code=-32603, message="Invalid response format"
        )

        result = await bridge.terminal_output(session, terminal_id="term_003")

        assert result is None

    @pytest.mark.asyncio
    async def test_terminal_output_general_error(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Обработка общей ошибки ClientRPCError."""
        mock_rpc_service.terminal_output.side_effect = ClientRPCError(
            "Internal client error"
        )

        result = await bridge.terminal_output(session, terminal_id="term_004")

        assert result is None

    @pytest.mark.asyncio
    async def test_terminal_output_error_does_not_raise_exception(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Ошибки не должны пробрасываться наружу, только возвращать None."""
        mock_rpc_service.terminal_output.side_effect = ClientRPCTimeoutError("timeout")

        # Не должно быть исключения
        result = await bridge.terminal_output(session, terminal_id="term_005")

        assert result is None


# ---------------------------------------------------------------------------
# Интеграционные тесты с реальным ClientRPCService
# ---------------------------------------------------------------------------


class TestTerminalOutputIntegration:
    """Интеграционные тесты с реальным ClientRPCService."""

    @pytest.mark.asyncio
    async def test_terminal_output_integration_success(self, session: SessionState) -> None:
        """Интеграционный тест: успешный вызов через реальный ClientRPCService."""
        sent_requests: list[dict[str, object]] = []

        async def send_request(request: dict[str, object]) -> None:
            sent_requests.append(request)

        rpc_service = ClientRPCService(
            send_request_callback=send_request,
            client_capabilities={
                "fs": {"readTextFile": True, "writeTextFile": True},
                "terminal": True,
            },
            timeout=1.0,
        )

        bridge = ClientRPCBridge(client_rpc_service=rpc_service)

        # Запустить вызов
        task = asyncio.create_task(
            bridge.terminal_output(session, terminal_id="term_001")
        )

        # Дать время на отправку request
        await asyncio.sleep(0.01)

        # Проверить отправленный request
        assert len(sent_requests) == 1
        request = sent_requests[0]
        assert request["method"] == "terminal/output"
        assert request["params"]["sessionId"] == "test_session_001"
        assert request["params"]["terminalId"] == "term_001"

        # Симулировать ответ от клиента
        request_id = request["id"]
        rpc_service.handle_response({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "output": "hello world",
                "truncated": False,
                "exitStatus": {
                    "exitCode": 0,
                    "signal": None,
                },
            },
        })

        # Проверить результат
        result = await task

        assert result is not None
        assert result["output"] == "hello world"
        assert result["truncated"] is False
        assert result["is_complete"] is True
        assert result["exit_code"] == 0
        assert result["signal"] is None

    @pytest.mark.asyncio
    async def test_terminal_output_integration_running_terminal(
        self, session: SessionState
    ) -> None:
        """Интеграционный тест: работающий терминал без exit status."""
        sent_requests: list[dict[str, object]] = []

        async def send_request(request: dict[str, object]) -> None:
            sent_requests.append(request)

        rpc_service = ClientRPCService(
            send_request_callback=send_request,
            client_capabilities={
                "fs": {"readTextFile": True, "writeTextFile": True},
                "terminal": True,
            },
            timeout=1.0,
        )

        bridge = ClientRPCBridge(client_rpc_service=rpc_service)

        task = asyncio.create_task(
            bridge.terminal_output(session, terminal_id="term_002")
        )

        await asyncio.sleep(0.01)

        request = sent_requests[0]
        request_id = request["id"]

        # Ответ без exitStatus (терминал еще работает)
        rpc_service.handle_response({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "output": "still running...",
                "truncated": False,
            },
        })

        result = await task

        assert result is not None
        assert result["output"] == "still running..."
        assert result["is_complete"] is False
        assert result["exit_code"] is None
        assert result["signal"] is None

    @pytest.mark.asyncio
    async def test_terminal_output_integration_capability_missing(
        self, session: SessionState
    ) -> None:
        """Интеграционный тест: отсутствие capability terminal."""
        sent_requests: list[dict[str, object]] = []

        async def send_request(request: dict[str, object]) -> None:
            sent_requests.append(request)

        rpc_service = ClientRPCService(
            send_request_callback=send_request,
            client_capabilities={
                "fs": {"readTextFile": True, "writeTextFile": True},
                "terminal": False,  # terminal отключен
            },
            timeout=1.0,
        )

        bridge = ClientRPCBridge(client_rpc_service=rpc_service)

        result = await bridge.terminal_output(session, terminal_id="term_003")

        assert result is None
        # Request не должен быть отправлен
        assert len(sent_requests) == 0

    @pytest.mark.asyncio
    async def test_terminal_output_integration_timeout(self, session: SessionState) -> None:
        """Интеграционный тест: timeout при ожидании ответа."""
        sent_requests: list[dict[str, object]] = []

        async def send_request(request: dict[str, object]) -> None:
            sent_requests.append(request)

        rpc_service = ClientRPCService(
            send_request_callback=send_request,
            client_capabilities={
                "fs": {"readTextFile": True, "writeTextFile": True},
                "terminal": True,
            },
            timeout=0.01,  # очень короткий timeout
        )

        bridge = ClientRPCBridge(client_rpc_service=rpc_service)

        result = await bridge.terminal_output(session, terminal_id="term_004")

        assert result is None

    @pytest.mark.asyncio
    async def test_terminal_output_integration_with_signal(self, session: SessionState) -> None:
        """Интеграционный тест: терминал завершен сигналом."""
        sent_requests: list[dict[str, object]] = []

        async def send_request(request: dict[str, object]) -> None:
            sent_requests.append(request)

        rpc_service = ClientRPCService(
            send_request_callback=send_request,
            client_capabilities={
                "fs": {"readTextFile": True, "writeTextFile": True},
                "terminal": True,
            },
            timeout=1.0,
        )

        bridge = ClientRPCBridge(client_rpc_service=rpc_service)

        task = asyncio.create_task(
            bridge.terminal_output(session, terminal_id="term_005")
        )

        await asyncio.sleep(0.01)

        request = sent_requests[0]
        request_id = request["id"]

        # Ответ с signal
        rpc_service.handle_response({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "output": "terminated",
                "truncated": False,
                "exitStatus": {
                    "exitCode": None,
                    "signal": "SIGKILL",
                },
            },
        })

        result = await task

        assert result is not None
        assert result["output"] == "terminated"
        assert result["is_complete"] is True
        assert result["exit_code"] is None
        assert result["signal"] == "SIGKILL"


# ---------------------------------------------------------------------------
# Тесты других методов ClientRPCBridge (базовое покрытие)
# ---------------------------------------------------------------------------


class TestClientRPCBridgeOtherMethods:
    """Базовые тесты других методов ClientRPCBridge."""

    @pytest.mark.asyncio
    async def test_read_file_success(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Успешное чтение файла."""
        mock_rpc_service.read_text_file = AsyncMock(return_value="file content")

        result = await bridge.read_file(session, path="/tmp/test.txt")

        assert result == "file content"
        mock_rpc_service.read_text_file.assert_called_once_with(
            session_id="test_session_001",
            path="/tmp/test.txt",
            line=None,
            limit=None,
        )

    @pytest.mark.asyncio
    async def test_read_file_with_line_and_limit(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Чтение файла с line и limit."""
        mock_rpc_service.read_text_file = AsyncMock(return_value="lines 10-20")

        result = await bridge.read_file(
            session, path="/tmp/test.txt", line=10, limit=10
        )

        assert result == "lines 10-20"
        mock_rpc_service.read_text_file.assert_called_once_with(
            session_id="test_session_001",
            path="/tmp/test.txt",
            line=10,
            limit=10,
        )

    @pytest.mark.asyncio
    async def test_read_file_error_returns_none(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Ошибка чтения файла возвращает None."""
        mock_rpc_service.read_text_file = AsyncMock(
            side_effect=ClientRPCError("error")
        )

        result = await bridge.read_file(session, path="/tmp/test.txt")

        assert result is None

    @pytest.mark.asyncio
    async def test_write_file_success(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Успешная запись файла."""
        mock_rpc_service.write_text_file = AsyncMock(return_value=True)

        result = await bridge.write_file(session, path="/tmp/test.txt", content="data")

        assert result is True

    @pytest.mark.asyncio
    async def test_write_file_error_returns_false(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Ошибка записи файла возвращает False."""
        mock_rpc_service.write_text_file = AsyncMock(
            side_effect=ClientRPCError("error")
        )

        result = await bridge.write_file(session, path="/tmp/test.txt", content="data")

        assert result is False

    @pytest.mark.asyncio
    async def test_create_terminal_success(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Успешное создание терминала."""
        mock_rpc_service.create_terminal = AsyncMock(return_value="term_001")

        result = await bridge.create_terminal(session, command="ls -la")

        assert result == "term_001"

    @pytest.mark.asyncio
    async def test_create_terminal_error_returns_none(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Ошибка создания терминала возвращает None."""
        mock_rpc_service.create_terminal = AsyncMock(
            side_effect=ClientCapabilityMissingError("terminal")
        )

        result = await bridge.create_terminal(session, command="ls")

        assert result is None

    @pytest.mark.asyncio
    async def test_wait_terminal_exit_success(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Успешное ожидание завершения терминала."""
        mock_rpc_service.wait_for_exit = AsyncMock(return_value=(0, None))

        result = await bridge.wait_terminal_exit(session, terminal_id="term_001")

        assert result is not None
        assert result["exit_code"] == 0
        assert result["signal"] is None

    @pytest.mark.asyncio
    async def test_wait_terminal_exit_error_returns_none(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Ошибка ожидания завершения возвращает None."""
        mock_rpc_service.wait_for_exit = AsyncMock(
            side_effect=ClientRPCTimeoutError("timeout")
        )

        result = await bridge.wait_terminal_exit(session, terminal_id="term_001")

        assert result is None

    @pytest.mark.asyncio
    async def test_release_terminal_success(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Успешное освобождение терминала."""
        mock_rpc_service.release_terminal = AsyncMock(return_value=True)

        result = await bridge.release_terminal(session, terminal_id="term_001")

        assert result is True

    @pytest.mark.asyncio
    async def test_release_terminal_error_returns_false(
        self, bridge: ClientRPCBridge, mock_rpc_service: AsyncMock, session: SessionState
    ) -> None:
        """Ошибка освобождения терминала возвращает False."""
        mock_rpc_service.release_terminal = AsyncMock(
            side_effect=ClientRPCResponseError(code=-32603, message="error")
        )

        result = await bridge.release_terminal(session, terminal_id="term_001")

        assert result is False
