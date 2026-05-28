"""Тесты передачи MCP конфигурации через Application Layer клиента."""

from unittest.mock import AsyncMock

import pytest

from codelab.client.application.dto import CreateSessionRequest, LoadSessionRequest
from codelab.client.application.use_cases import CreateSessionUseCase

# ===========================================================================
# CreateSessionRequest
# ===========================================================================


class TestCreateSessionRequest:
    """Tests for CreateSessionRequest DTO."""

    def test_mcp_servers_field_optional(self) -> None:
        request = CreateSessionRequest(
            server_host="localhost",
            server_port=8000,
            cwd="/project",
        )
        assert request.mcp_servers is None

    def test_mcp_servers_field_set(self) -> None:
        mcp_servers = [
            {"name": "fs", "type": "stdio", "command": "npx"},
        ]
        request = CreateSessionRequest(
            server_host="localhost",
            server_port=8000,
            cwd="/project",
            mcp_servers=mcp_servers,
        )
        assert request.mcp_servers == mcp_servers


# ===========================================================================
# LoadSessionRequest
# ===========================================================================


class TestLoadSessionRequest:
    """Tests for LoadSessionRequest DTO."""

    def test_mcp_servers_field_optional(self) -> None:
        request = LoadSessionRequest(
            session_id="session-1",
            server_host="localhost",
            server_port=8000,
        )
        assert request.mcp_servers is None

    def test_mcp_servers_field_set(self) -> None:
        mcp_servers = [
            {"name": "fs", "type": "stdio", "command": "npx"},
        ]
        request = LoadSessionRequest(
            session_id="session-1",
            server_host="localhost",
            server_port=8000,
            mcp_servers=mcp_servers,
        )
        assert request.mcp_servers == mcp_servers


# ===========================================================================
# CreateSessionUseCase
# ===========================================================================


class TestCreateSessionUseCaseMcpServers:
    """Tests for CreateSessionUseCase with mcp_servers."""

    @pytest.fixture
    def transport(self) -> AsyncMock:
        mock = AsyncMock()
        mock.is_initialized.return_value = True
        mock.is_connected.return_value = True
        mock.get_server_capabilities.return_value = {}
        mock.receive.return_value = {
            "id": 1,
            "result": {"sessionId": "test-session-123"},
        }
        return mock

    @pytest.fixture
    def session_repo(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def use_case(self, transport: AsyncMock, session_repo: AsyncMock) -> CreateSessionUseCase:
        return CreateSessionUseCase(transport, session_repo)

    @pytest.mark.asyncio
    async def test_mcp_servers_passed_to_session_new(
        self, use_case: CreateSessionUseCase, transport: AsyncMock, session_repo: AsyncMock
    ) -> None:
        """MCP серверы должны быть переданы в session/new."""
        mcp_servers = [
            {"name": "fs", "type": "stdio", "command": "npx"},
        ]
        request = CreateSessionRequest(
            server_host="localhost",
            server_port=8000,
            cwd="/project",
            mcp_servers=mcp_servers,
        )

        await use_case.execute(request)

        # Проверяем что send был вызван с mcpServers в params
        send_calls = transport.send.call_args_list
        assert len(send_calls) >= 1

        # Находим вызов session/new
        session_new_call = None
        for call in send_calls:
            msg = call[0][0]
            if isinstance(msg, dict) and msg.get("method") == "session/new":
                session_new_call = msg
                break

        assert session_new_call is not None
        params = session_new_call.get("params", {})
        assert "mcpServers" in params
        assert params["mcpServers"] == mcp_servers

    @pytest.mark.asyncio
    async def test_empty_mcp_servers_when_none(
        self, use_case: CreateSessionUseCase, transport: AsyncMock
    ) -> None:
        """Если mcp_servers=None, должен быть передан пустой список."""
        request = CreateSessionRequest(
            server_host="localhost",
            server_port=8000,
            cwd="/project",
        )

        await use_case.execute(request)

        send_calls = transport.send.call_args_list
        session_new_call = None
        for call in send_calls:
            msg = call[0][0]
            if isinstance(msg, dict) and msg.get("method") == "session/new":
                session_new_call = msg
                break

        assert session_new_call is not None
        params = session_new_call.get("params", {})
        assert params["mcpServers"] == []


# ===========================================================================
# SessionCoordinator
# ===========================================================================


class TestSessionCoordinatorMcpServers:
    """Tests for SessionCoordinator with mcp_servers."""

    @pytest.mark.asyncio
    async def test_create_session_passes_mcp_servers(self) -> None:
        """SessionCoordinator должен передавать mcp_servers в CreateSessionRequest."""
        from codelab.client.application.session_coordinator import SessionCoordinator

        transport = AsyncMock()
        transport.is_initialized.return_value = True
        transport.is_connected.return_value = True
        transport.get_server_capabilities.return_value = {}
        transport.receive.return_value = {
            "id": 1,
            "result": {"sessionId": "test-session-123"},
        }

        session_repo = AsyncMock()

        coordinator = SessionCoordinator(transport, session_repo)

        mcp_servers = [
            {"name": "fs", "type": "stdio", "command": "npx"},
        ]

        await coordinator.create_session(
            server_host="localhost",
            server_port=8000,
            cwd="/project",
            mcp_servers=mcp_servers,
        )

        # Проверяем что send был вызван с mcpServers
        send_calls = transport.send.call_args_list
        session_new_call = None
        for call in send_calls:
            msg = call[0][0]
            if isinstance(msg, dict) and msg.get("method") == "session/new":
                session_new_call = msg
                break

        assert session_new_call is not None
        params = session_new_call.get("params", {})
        assert params["mcpServers"] == mcp_servers

    @pytest.mark.asyncio
    async def test_create_session_without_mcp_servers(self) -> None:
        """SessionCoordinator должен работать без mcp_servers."""
        from codelab.client.application.session_coordinator import SessionCoordinator

        transport = AsyncMock()
        transport.is_initialized.return_value = True
        transport.is_connected.return_value = True
        transport.get_server_capabilities.return_value = {}
        transport.receive.return_value = {
            "id": 1,
            "result": {"sessionId": "test-session-123"},
        }

        session_repo = AsyncMock()

        coordinator = SessionCoordinator(transport, session_repo)

        await coordinator.create_session(
            server_host="localhost",
            server_port=8000,
            cwd="/project",
        )

        # Должно работать без ошибок
        send_calls = transport.send.call_args_list
        session_new_call = None
        for call in send_calls:
            msg = call[0][0]
            if isinstance(msg, dict) and msg.get("method") == "session/new":
                session_new_call = msg
                break

        assert session_new_call is not None
        params = session_new_call.get("params", {})
        assert params["mcpServers"] == []
