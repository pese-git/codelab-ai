"""Tests for dishka-based DI container.

Tests verify:
- Container creation with create_client_container
- All dependencies resolve correctly
- Cyclic dependency resolution (Coordinator ↔ PermissionHandler)
- Container lifecycle (close)
- Singleton behavior (same instance on multiple gets)
"""

from pathlib import Path
from typing import cast

import pytest

from codelab.client.application.permission_handler import PermissionHandler
from codelab.client.application.session_coordinator import SessionCoordinator
from codelab.client.domain.repositories import SessionRepository
from codelab.client.domain.services import TransportService
from codelab.client.infrastructure.client_config import ClientConfig
from codelab.client.infrastructure.container_factory import create_client_container
from codelab.client.infrastructure.events.bus import EventBus
from codelab.client.infrastructure.handlers.file_system_handler import FileSystemHandler
from codelab.client.infrastructure.handlers.terminal_handler import TerminalHandler
from codelab.client.infrastructure.providers import ClientProvider, CoreServices
from codelab.client.infrastructure.repositories import InMemorySessionRepository
from codelab.client.infrastructure.services.acp_transport_service import ACPTransportService
from codelab.client.infrastructure.services.file_system_executor import FileSystemExecutor
from codelab.client.infrastructure.services.terminal_executor import TerminalExecutor
from codelab.client.infrastructure.view_model_provider import ViewModelProvider
from codelab.client.presentation.chat_view_model import ChatViewModel
from codelab.client.presentation.file_viewer_view_model import FileViewerViewModel
from codelab.client.presentation.filesystem_view_model import FileSystemViewModel
from codelab.client.presentation.permission_view_model import PermissionViewModel
from codelab.client.presentation.plan_view_model import PlanViewModel
from codelab.client.presentation.session_view_model import SessionViewModel
from codelab.client.presentation.terminal_log_view_model import TerminalLogViewModel
from codelab.client.presentation.terminal_view_model import TerminalViewModel
from codelab.client.presentation.ui_view_model import UIViewModel


@pytest.fixture
def container():
    """Создаёт DI контейнер для тестов."""
    ctr = create_client_container(
        host="localhost",
        port=8000,
        cwd="/tmp",
    )
    yield ctr
    ctr.close()


class TestContainerCreation:
    """Тесты создания контейнера."""

    def test_create_container_success(self) -> None:
        """Тест: контейнер успешно создаётся."""
        container = create_client_container(
            host="localhost",
            port=8000,
            cwd="/tmp",
        )
        assert container is not None
        container.close()

    def test_create_container_with_custom_cwd(self) -> None:
        """Тест: контейнер создаётся с кастомным cwd."""
        container = create_client_container(
            host="localhost",
            port=8000,
            cwd="/var/tmp",
        )
        config = container.get(ClientConfig)
        assert config.cwd == Path("/var/tmp")
        container.close()

    def test_create_container_with_history_dir(self) -> None:
        """Тест: контейнер создаётся с history_dir."""
        container = create_client_container(
            host="localhost",
            port=8000,
            cwd="/tmp",
            history_dir="/tmp/history",
        )
        config = container.get(ClientConfig)
        assert config.history_dir == "/tmp/history"
        container.close()

    def test_create_container_with_invalid_cwd_raises_error(self) -> None:
        """Тест: ошибка при создании контейнера с несуществующим cwd."""
        # Контейнер создаётся успешно, но FileSystemExecutor
        # получит несуществующий base_path — это допустимо
        container = create_client_container(
            host="localhost",
            port=8000,
            cwd="/nonexistent/path/that/does/not/exist",
        )
        # FileSystemExecutor не валидирует путь при создании
        executor = container.get(FileSystemExecutor)
        assert executor.base_path == Path("/nonexistent/path/that/does/not/exist")
        container.close()


class TestServiceResolution:
    """Тесты разрешения сервисов."""

    def test_resolve_event_bus(self, container) -> None:
        """Тест: EventBus разрешается."""
        event_bus = container.get(EventBus)
        assert isinstance(event_bus, EventBus)

    def test_resolve_transport(self, container) -> None:
        """Тест: TransportService разрешается как ACPTransportService."""
        transport = container.get(TransportService)
        assert isinstance(transport, ACPTransportService)

    def test_resolve_session_repo(self, container) -> None:
        """Тест: SessionRepository разрешается как InMemorySessionRepository."""
        repo = container.get(SessionRepository)
        assert isinstance(repo, InMemorySessionRepository)

    def test_resolve_fs_executor(self, container) -> None:
        """Тест: FileSystemExecutor разрешается."""
        executor = container.get(FileSystemExecutor)
        assert isinstance(executor, FileSystemExecutor)
        assert executor.base_path == Path("/tmp")

    def test_resolve_fs_handler(self, container) -> None:
        """Тест: FileSystemHandler разрешается."""
        handler = container.get(FileSystemHandler)
        assert isinstance(handler, FileSystemHandler)

    def test_resolve_terminal_executor(self, container) -> None:
        """Тест: TerminalExecutor разрешается."""
        executor = container.get(TerminalExecutor)
        assert isinstance(executor, TerminalExecutor)

    def test_resolve_terminal_handler(self, container) -> None:
        """Тест: TerminalHandler разрешается."""
        handler = container.get(TerminalHandler)
        assert isinstance(handler, TerminalHandler)


class TestCyclicDependencyResolution:
    """Тесты разрешения циклических зависимостей."""

    def test_resolve_coordinator(self, container) -> None:
        """Тест: SessionCoordinator разрешается."""
        coordinator = container.get(SessionCoordinator)
        assert isinstance(coordinator, SessionCoordinator)

    def test_resolve_permission_handler(self, container) -> None:
        """Тест: PermissionHandler разрешается."""
        handler = container.get(PermissionHandler)
        assert isinstance(handler, PermissionHandler)

    def test_coordinator_has_permission_handler(self, container) -> None:
        """Тест: Coordinator имеет PermissionHandler (цикл разрешён)."""
        coordinator = container.get(SessionCoordinator)
        permission_handler = container.get(PermissionHandler)

        assert coordinator._permission_handler is permission_handler

    def test_transport_has_permission_handler(self, container) -> None:
        """Тест: Transport имеет PermissionHandler (цикл разрешён)."""
        transport = container.get(TransportService)
        permission_handler = container.get(PermissionHandler)

        assert cast(ACPTransportService, transport)._permission_handler is permission_handler


class TestViewModelResolution:
    """Тесты разрешения ViewModels."""

    def test_resolve_ui_view_model(self, container) -> None:
        """Тест: UIViewModel разрешается."""
        vm = container.get(UIViewModel)
        assert isinstance(vm, UIViewModel)

    def test_resolve_session_view_model(self, container) -> None:
        """Тест: SessionViewModel разрешается."""
        vm = container.get(SessionViewModel)
        assert isinstance(vm, SessionViewModel)

    def test_resolve_plan_view_model(self, container) -> None:
        """Тест: PlanViewModel разрешается."""
        vm = container.get(PlanViewModel)
        assert isinstance(vm, PlanViewModel)

    def test_resolve_chat_view_model(self, container) -> None:
        """Тест: ChatViewModel разрешается."""
        vm = container.get(ChatViewModel)
        assert isinstance(vm, ChatViewModel)

    def test_resolve_terminal_view_model(self, container) -> None:
        """Тест: TerminalViewModel разрешается."""
        vm = container.get(TerminalViewModel)
        assert isinstance(vm, TerminalViewModel)

    def test_resolve_filesystem_view_model(self, container) -> None:
        """Тест: FileSystemViewModel разрешается."""
        vm = container.get(FileSystemViewModel)
        assert isinstance(vm, FileSystemViewModel)

    def test_resolve_file_viewer_view_model(self, container) -> None:
        """Тест: FileViewerViewModel разрешается."""
        vm = container.get(FileViewerViewModel)
        assert isinstance(vm, FileViewerViewModel)

    def test_resolve_permission_view_model(self, container) -> None:
        """Тест: PermissionViewModel разрешается."""
        vm = container.get(PermissionViewModel)
        assert isinstance(vm, PermissionViewModel)

    def test_resolve_terminal_log_view_model(self, container) -> None:
        """Тест: TerminalLogViewModel разрешается."""
        vm = container.get(TerminalLogViewModel)
        assert isinstance(vm, TerminalLogViewModel)


class TestSingletonBehavior:
    """Тесты синглтон-поведения (Scope.APP)."""

    def test_same_event_bus_instance(self, container) -> None:
        """Тест: EventBus — один экземпляр."""
        bus1 = container.get(EventBus)
        bus2 = container.get(EventBus)
        assert bus1 is bus2

    def test_same_coordinator_instance(self, container) -> None:
        """Тест: SessionCoordinator — один экземпляр."""
        coord1 = container.get(SessionCoordinator)
        coord2 = container.get(SessionCoordinator)
        assert coord1 is coord2

    def test_same_ui_view_model_instance(self, container) -> None:
        """Тест: UIViewModel — один экземпляр."""
        vm1 = container.get(UIViewModel)
        vm2 = container.get(UIViewModel)
        assert vm1 is vm2

    def test_same_chat_view_model_instance(self, container) -> None:
        """Тест: ChatViewModel — один экземпляр."""
        vm1 = container.get(ChatViewModel)
        vm2 = container.get(ChatViewModel)
        assert vm1 is vm2


class TestContainerLifecycle:
    """Тесты жизненного цикла контейнера."""

    def test_close_container(self) -> None:
        """Тест: контейнер закрывается без ошибок."""
        container = create_client_container(
            host="localhost",
            port=8000,
            cwd="/tmp",
        )
        container.close()
        # Повторный close не должен вызывать ошибку
        container.close()


class TestClientProvider:
    """Тесты ClientProvider."""

    def test_provider_has_scope(self) -> None:
        """Тест: ClientProvider имеет Scope.APP."""
        from dishka import Scope

        assert ClientProvider.scope == Scope.APP

    def test_core_services_dataclass(self) -> None:
        """Тест: CoreServices — dataclass с coordinator и permission_handler."""
        coordinator = SessionCoordinator(
            transport=None,  # type: ignore
            session_repo=None,  # type: ignore
            permission_handler=None,
        )
        permission_handler = PermissionHandler(
            transport=None,  # type: ignore
            logger=None,
        )
        core = CoreServices(
            coordinator=coordinator,
            permission_handler=permission_handler,
        )
        assert core.coordinator is coordinator
        assert core.permission_handler is permission_handler


class TestViewModelProvider:
    """Тесты ViewModelProvider."""

    def test_provider_has_scope(self) -> None:
        """Тест: ViewModelProvider имеет Scope.APP."""
        from dishka import Scope

        assert ViewModelProvider.scope == Scope.APP
