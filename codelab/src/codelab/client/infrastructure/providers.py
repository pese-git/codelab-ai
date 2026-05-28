"""ClientProvider — декларативный DI-провайдер для сервисов клиента.

Заменяет DIBootstrapper и di_container. Использует dishka для
автоматического разрешения зависимостей и управления жизненным циклом.

Циклическая зависимость Coordinator ↔ PermissionHandler решается
через factory-метод, создающий оба объекта и связывающий их.

Пример использования:
    >>> from dishka import make_container, Scope
    >>> config = ClientConfig(host="localhost", port=8000, cwd=Path("/project"))
    >>> container = make_container(ClientProvider(), context={ClientConfig: config})
    >>> coordinator = container.get(SessionCoordinator)
"""

from dataclasses import dataclass
from typing import cast

import structlog
import structlog.stdlib
from dishka import Provider, Scope, provide

from codelab.client.application.permission_handler import PermissionHandler
from codelab.client.application.session_coordinator import SessionCoordinator
from codelab.client.domain.repositories import SessionRepository
from codelab.client.domain.services import TransportService
from codelab.client.infrastructure.client_config import ClientConfig
from codelab.client.infrastructure.events.bus import EventBus
from codelab.client.infrastructure.handlers.file_system_handler import FileSystemHandler
from codelab.client.infrastructure.handlers.terminal_handler import TerminalHandler
from codelab.client.infrastructure.repositories import InMemorySessionRepository
from codelab.client.infrastructure.services.acp_transport_service import (
    ACPTransportService,
    create_websocket_transport_service,
)
from codelab.client.infrastructure.services.file_system_executor import FileSystemExecutor
from codelab.client.infrastructure.services.terminal_executor import TerminalExecutor
from codelab.client.infrastructure.stdio_transport import StdioClientTransport


@dataclass
class CoreServices:
    """Контейнер для Coordinator и PermissionHandler.

    Используется для разрыва циклической зависимости между
    SessionCoordinator и PermissionHandler при создании в dishka.
    """

    coordinator: SessionCoordinator
    permission_handler: PermissionHandler


class ClientProvider(Provider):
    """Провайдер сервисов клиентского приложения.

    Регистрирует все зависимости в порядке разрешения графа:
    1. EventBus — шина событий
    2. ACPTransportService — WebSocket транспорт
    3. InMemorySessionRepository — хранилище сессий
    4. FileSystemExecutor + FileSystemHandler — файловые операции
    5. TerminalExecutor + TerminalHandler — терминальные операции
    6. CoreServices (Coordinator + PermissionHandler) — оркестрация
    """

    scope = Scope.APP

    # =========================================================================
    # Базовые сервисы
    # =========================================================================

    @provide(scope=Scope.APP)
    def get_client_logger(self, config: ClientConfig) -> structlog.stdlib.BoundLogger:
        """Создаёт logger для всего клиентского приложения."""
        return config.logger or structlog.get_logger("client")  # type: ignore[return-value]

    @provide(scope=Scope.APP)
    def get_event_bus(self) -> EventBus:
        """Создаёт EventBus для слабой связанности компонентов."""
        return EventBus()

    @provide(scope=Scope.APP)
    def get_transport(self, config: ClientConfig) -> TransportService:
        """Создаёт ACPTransportService с правильным транспортом.

        Если config.transport_mode == "stdio" — использует StdioClientTransport.
        Иначе — WebSocketTransport.
        """
        if config.transport_mode == "stdio":
            transport = StdioClientTransport(
                command=config.stdio_command or "codelab",
                args=config.stdio_args or ["serve", "--stdio"],
                cwd=str(config.cwd),
                receive_timeout=config.receive_timeout,
            )
            return ACPTransportService(transport=transport)
        else:
            return create_websocket_transport_service(
                host=config.host,
                port=config.port,
            )

    @provide(scope=Scope.APP)
    def get_session_repo(self) -> SessionRepository:
        """Создаёт InMemorySessionRepository для хранения сессий."""
        return InMemorySessionRepository()

    # =========================================================================
    # Файловые операции
    # =========================================================================

    @provide(scope=Scope.APP)
    def get_fs_executor(self, config: ClientConfig) -> FileSystemExecutor:
        """Создаёт FileSystemExecutor с sandbox в cwd."""
        return FileSystemExecutor(base_path=config.cwd)

    @provide(scope=Scope.APP)
    def get_fs_handler(
        self, fs_executor: FileSystemExecutor
    ) -> FileSystemHandler:
        """Создаёт FileSystemHandler поверх FileSystemExecutor."""
        return FileSystemHandler(fs_executor)

    # =========================================================================
    # Терминальные операции
    # =========================================================================

    @provide(scope=Scope.APP)
    def get_terminal_executor(self) -> TerminalExecutor:
        """Создаёт TerminalExecutor для выполнения команд."""
        return TerminalExecutor()

    @provide(scope=Scope.APP)
    def get_terminal_handler(
        self, terminal_executor: TerminalExecutor
    ) -> TerminalHandler:
        """Создаёт TerminalHandler поверх TerminalExecutor."""
        return TerminalHandler(terminal_executor)

    # =========================================================================
    # Разрешение циклической зависимости Coordinator ↔ PermissionHandler
    # =========================================================================

    @provide(scope=Scope.APP)
    def create_core_services(
        self,
        transport: TransportService,
        session_repo: SessionRepository,
        logger: structlog.stdlib.BoundLogger,
    ) -> CoreServices:
        """Создаёт Coordinator и PermissionHandler, связывая их.

        Зависимость односторонняя: SessionCoordinator использует
        PermissionHandler для доступа к request_manager.
        ACPTransportService также получает ссылку через post-init.

        Двухфазная инициализация для post-init связывания:
        1. Создаём Coordinator с permission_handler=None
        2. Создаём PermissionHandler
        3. Устанавливаем _permission_handler в coordinator и transport
        """

        # Фаза 1: Coordinator без PermissionHandler
        coordinator = SessionCoordinator(
            transport=transport,
            session_repo=session_repo,
            permission_handler=None,
        )

        # Фаза 2: PermissionHandler (не зависит от coordinator)
        permission_handler = PermissionHandler(
            transport=transport,
            logger=logger,
        )

        # Связываем coordinator с permission_handler (одностороннее)
        # cast безопасен: единственная реализация TransportService — ACPTransportService
        acp_transport = cast(ACPTransportService, transport)
        coordinator._permission_handler = permission_handler
        acp_transport._permission_handler = permission_handler

        return CoreServices(
            coordinator=coordinator,
            permission_handler=permission_handler,
        )

    @provide(scope=Scope.APP)
    def get_coordinator(self, core: CoreServices) -> SessionCoordinator:
        """Извлекает SessionCoordinator из CoreServices."""
        return core.coordinator

    @provide(scope=Scope.APP)
    def get_permission_handler(
        self, core: CoreServices
    ) -> PermissionHandler:
        """Извлекает PermissionHandler из CoreServices."""
        return core.permission_handler
