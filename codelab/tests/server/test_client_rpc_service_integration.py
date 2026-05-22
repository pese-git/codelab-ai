"""Тест для проверки что ClientRPCService передается через цепочку инициализации.

Тест проверяет:
1. ACPProtocol инициализируется с client_rpc_service
2. PromptOrchestrator принимает client_rpc_service
"""

from unittest.mock import AsyncMock

from factories import make_orchestrator

from codelab.server.client_rpc.service import ClientRPCService
from codelab.server.protocol import ACPProtocol
from codelab.server.storage import InMemoryStorage


class TestClientRPCServiceIntegration:
    """Тесты для проверки передачи ClientRPCService через цепочку инициализации."""

    def test_acpprotocol_accepts_client_rpc_service(self) -> None:
        """Проверяет что ACPProtocol.__init__ принимает client_rpc_service."""
        send_callback = AsyncMock()
        client_rpc_service = ClientRPCService(
            send_request_callback=send_callback,
            client_capabilities={"fs": {"readTextFile": True}},
        )

        protocol = ACPProtocol(
            storage=InMemoryStorage(),
            client_rpc_service=client_rpc_service,
        )

        assert protocol._client_rpc_service is client_rpc_service

    def test_make_orchestrator_with_client_rpc_service(self) -> None:
        """Проверяет что make_orchestrator() принимает client_rpc_service."""
        send_callback = AsyncMock()
        client_rpc_service = ClientRPCService(
            send_request_callback=send_callback,
            client_capabilities={},
        )

        orchestrator = make_orchestrator(client_rpc_service=client_rpc_service)

        assert orchestrator.client_rpc_service is client_rpc_service

    def test_client_rpc_service_without_agent_orchestrator(self) -> None:
        """Проверяет что ClientRPCService работает без agent_orchestrator."""
        send_callback = AsyncMock()
        client_rpc_service = ClientRPCService(
            send_request_callback=send_callback,
            client_capabilities={"fs": {"readTextFile": True}},
        )

        protocol = ACPProtocol(
            storage=InMemoryStorage(),
            client_rpc_service=client_rpc_service,
            agent_orchestrator=None,
        )

        assert protocol._client_rpc_service is client_rpc_service
        assert protocol._agent_orchestrator is None

    def test_make_orchestrator_without_client_rpc_service(self) -> None:
        """Проверяет что make_orchestrator() работает без client_rpc_service."""
        orchestrator = make_orchestrator(client_rpc_service=None)

        assert orchestrator.client_rpc_service is None
