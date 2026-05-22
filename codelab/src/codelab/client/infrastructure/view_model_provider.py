"""ViewModelProvider — декларативный DI-провайдер для ViewModels.

Заменяет ViewModelFactory. Регистрирует все 9 ViewModels как
синглтоны (Scope.APP), автоматически разрешая зависимости.

Пример использования:
    >>> from dishka import make_container, Scope
    >>> container = make_container(ViewModelProvider())
    >>> ui_vm = container.get(UIViewModel)
"""

import structlog.stdlib
from dishka import Provider, Scope, provide

from codelab.client.application.session_coordinator import SessionCoordinator
from codelab.client.infrastructure.client_config import ClientConfig
from codelab.client.infrastructure.events.bus import EventBus
from codelab.client.infrastructure.services.file_system_executor import (
    FileSystemExecutor,
)
from codelab.client.infrastructure.services.terminal_executor import (
    TerminalExecutor,
)
from codelab.client.presentation.chat_view_model import ChatViewModel
from codelab.client.presentation.file_viewer_view_model import FileViewerViewModel
from codelab.client.presentation.filesystem_view_model import FileSystemViewModel
from codelab.client.presentation.permission_view_model import PermissionViewModel
from codelab.client.presentation.plan_view_model import PlanViewModel
from codelab.client.presentation.session_view_model import SessionViewModel
from codelab.client.presentation.terminal_log_view_model import TerminalLogViewModel
from codelab.client.presentation.terminal_view_model import TerminalViewModel
from codelab.client.presentation.ui_view_model import UIViewModel


class ViewModelProvider(Provider):
    """Провайдер ViewModels клиентского приложения.

    Регистрирует 9 ViewModels как синглтоны (Scope.APP):
    1. UIViewModel — глобальное UI состояние
    2. SessionViewModel — управление сессиями
    3. PlanViewModel — управление планом (создаётся до ChatViewModel)
    4. ChatViewModel — управление чатом (зависит от PlanViewModel)
    5. TerminalViewModel — управление терминалом
    6. FileSystemViewModel — управление файловой системой
    7. FileViewerViewModel — просмотр файлов
    8. PermissionViewModel — управление разрешениями
    9. TerminalLogViewModel — просмотр логов терминала
    """

    scope = Scope.APP

    # =========================================================================
    # ViewModels без зависимостей от координатора
    # =========================================================================

    @provide(scope=Scope.APP)
    def get_ui_vm(
        self,
        event_bus: EventBus,
        logger: structlog.stdlib.BoundLogger,
    ) -> UIViewModel:
        """Создаёт UIViewModel для глобального UI состояния."""
        return UIViewModel(event_bus=event_bus, logger=logger)

    @provide(scope=Scope.APP)
    def get_plan_vm(
        self,
        event_bus: EventBus,
        logger: structlog.stdlib.BoundLogger,
    ) -> PlanViewModel:
        """Создаёт PlanViewModel для управления планом."""
        return PlanViewModel(event_bus=event_bus, logger=logger)

    @provide(scope=Scope.APP)
    def get_terminal_vm(
        self,
        event_bus: EventBus,
        logger: structlog.stdlib.BoundLogger,
    ) -> TerminalViewModel:
        """Создаёт TerminalViewModel для управления терминалом."""
        return TerminalViewModel(event_bus=event_bus, logger=logger)

    @provide(scope=Scope.APP)
    def get_filesystem_vm(
        self,
        event_bus: EventBus,
        logger: structlog.stdlib.BoundLogger,
    ) -> FileSystemViewModel:
        """Создаёт FileSystemViewModel для управления файловой системой."""
        return FileSystemViewModel(event_bus=event_bus, logger=logger)

    @provide(scope=Scope.APP)
    def get_file_viewer_vm(
        self,
        event_bus: EventBus,
        logger: structlog.stdlib.BoundLogger,
    ) -> FileViewerViewModel:
        """Создаёт FileViewerViewModel для просмотра файлов."""
        return FileViewerViewModel(event_bus=event_bus, logger=logger)

    @provide(scope=Scope.APP)
    def get_permission_vm(
        self,
        event_bus: EventBus,
        logger: structlog.stdlib.BoundLogger,
    ) -> PermissionViewModel:
        """Создаёт PermissionViewModel для управления разрешениями."""
        return PermissionViewModel(event_bus=event_bus, logger=logger)

    @provide(scope=Scope.APP)
    def get_terminal_log_vm(
        self,
        event_bus: EventBus,
        logger: structlog.stdlib.BoundLogger,
    ) -> TerminalLogViewModel:
        """Создаёт TerminalLogViewModel для просмотра логов терминала."""
        return TerminalLogViewModel(event_bus=event_bus, logger=logger)

    # =========================================================================
    # ViewModels с зависимостью от SessionCoordinator
    # =========================================================================

    @provide(scope=Scope.APP)
    def get_session_vm(
        self,
        coordinator: SessionCoordinator,
        event_bus: EventBus,
        logger: structlog.stdlib.BoundLogger,
    ) -> SessionViewModel:
        """Создаёт SessionViewModel для управления сессиями."""
        return SessionViewModel(
            coordinator=coordinator,
            event_bus=event_bus,
            logger=logger,
        )

    @provide(scope=Scope.APP)
    def get_chat_vm(
        self,
        coordinator: SessionCoordinator,
        event_bus: EventBus,
        config: ClientConfig,
        logger: structlog.stdlib.BoundLogger,
        plan_vm: PlanViewModel,
        fs_executor: FileSystemExecutor,
        terminal_executor: TerminalExecutor,
    ) -> ChatViewModel:
        """Создаёт ChatViewModel для управления чатом.

        Зависит от PlanViewModel для обработки plan updates.
        Executors всегда регистрируются в ClientProvider.
        """
        return ChatViewModel(
            coordinator=coordinator,
            event_bus=event_bus,
            logger=logger,
            history_dir=config.history_dir,
            fs_executor=fs_executor,
            terminal_executor=terminal_executor,
            plan_vm=plan_vm,
        )
