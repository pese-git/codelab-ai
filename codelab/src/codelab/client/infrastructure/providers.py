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

import structlog
from dishka import Provider, Scope, provide

from codelab.client.application.permission_handler import PermissionHandler
from codelab.client.application.session_coordinator import SessionCoordinator
from codelab.client.infrastructure.client_config import ClientConfig
from codelab.client.infrastructure.events.bus import EventBus
from codelab.client.infrastructure.handlers.file_system_handler import FileSystemHandler
from codelab.client.infrastructure.handlers.terminal_handler import TerminalHandler
from codelab.client.infrastructure.repositories import InMemorySessionRepository
from codelab.client.infrastructure.services.acp_transport_service import ACPTransportService
from codelab.client.infrastructure.services.file_system_executor import FileSystemExecutor
from codelab.client.infrastructure.services.terminal_executor import TerminalExecutor


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
    def get_event_bus(self) -> EventBus:
        """Создаёт EventBus для слабой связанности компонентов."""
        return EventBus()

    @provide(scope=Scope.APP)
    def get_transport(self, config: ClientConfig) -> ACPTransportService:
        """Создаёт ACPTransportService для WebSocket коммуникации.

        PermissionHandler будет установлен позже через CoreServices.
        """
        return ACPTransportService(host=config.host, port=config.port)

    @provide(scope=Scope.APP)
    def get_session_repo(self) -> InMemorySessionRepository:
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
        transport: ACPTransportService,
        session_repo: InMemorySessionRepository,
        config: ClientConfig,
    ) -> CoreServices:
        """Создаёт Coordinator и PermissionHandler, разрывая цикл.

        Циклическая зависимость:
        - SessionCoordinator зависит от PermissionHandler
        - PermissionHandler зависит от SessionCoordinator
        - ACPTransportService зависит от PermissionHandler

        Решение: двухфазная инициализация
        1. Создаём Coordinator с permission_handler=None
        2. Создаём PermissionHandler с координатором
        3. Связываем обратно через _permission_handler
        """
        logger = config.logger or structlog.get_logger("client")

        # Фаза 1: Coordinator без PermissionHandler
        coordinator = SessionCoordinator(
            transport=transport,
            session_repo=session_repo,
            permission_handler=None,
        )

        # Фаза 2: PermissionHandler с координатором
        permission_handler = PermissionHandler(
            coordinator=coordinator,
            transport=transport,
            logger=logger,
        )

        # Фаза 3: Разрыв цикла — обратная связь
        coordinator._permission_handler = permission_handler
        transport._permission_handler = permission_handler

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
