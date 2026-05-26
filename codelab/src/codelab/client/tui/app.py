"""Главное Textual приложение ACP-Client TUI с Clean Architecture.

Приложение использует новую архитектуру:
- create_client_container для инициализации dishka контейнера
- ViewModels для управления состоянием UI
- Use Cases для бизнес-логики
- Event Bus для слабо связанной коммуникации между компонентами
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import structlog
from textual.app import App, ComposeResult

from codelab.client.application.session_coordinator import SessionCoordinator
from codelab.client.domain.services import TransportService
from codelab.client.infrastructure.container_factory import create_client_container
from codelab.client.infrastructure.services.acp_transport_service import ACPTransportService
from codelab.client.messages import PermissionOption, PermissionToolCall
from codelab.client.presentation.chat_view_model import ChatViewModel
from codelab.client.presentation.file_viewer_view_model import FileViewerViewModel
from codelab.client.presentation.filesystem_view_model import FileSystemViewModel
from codelab.client.presentation.model_selector_view_model import ModelSelectorViewModel
from codelab.client.presentation.permission_view_model import PermissionViewModel
from codelab.client.presentation.plan_view_model import PlanViewModel
from codelab.client.presentation.session_view_model import SessionViewModel
from codelab.client.presentation.terminal_log_view_model import TerminalLogViewModel
from codelab.client.presentation.terminal_view_model import TerminalViewModel
from codelab.client.presentation.ui_view_model import ConnectionStatus, SidebarTab, UIViewModel
from codelab.client.tui.navigation import NavigationManager

from .components import (
    ChatView,
    CommandPalette,
    FileChangePreviewModal,
    FileTree,
    FooterBar,
    HeaderBar,
    HelpModal,
    MainLayout,
    ModelSelectorModal,
    PermissionModal,
    PlanPanel,
    PromptInput,
    QuickActionsBar,
    Sidebar,
    ToastContainer,
    ToolCallCard,
    ToolPanel,
)
from .config import TUIConfigStore, TUITheme, resolve_tui_connection
from .themes import ThemeManager


class ACPClientApp(App[None]):
    """Главное TUI приложение с Clean Architecture.

    Все компоненты инициализируются через dishka контейнер.
    State management осуществляется через ViewModels.
    """

    # Отключаем стандартный выход по Ctrl+C — используем его для отмены prompt.
    # Выход назначен на Ctrl+Q.
    CTRL_C_CAN_QUIT = False

    BINDINGS = [
        ("ctrl+q", "quit", "Выход"),
        ("ctrl+n", "new_session", "Новая сессия"),
        ("ctrl+r", "retry_prompt", "Повторить"),
        ("ctrl+b", "toggle_sidebar", "Sidebar"),
        ("ctrl+s", "focus_session_list", "Список сессий"),
        ("ctrl+j", "next_session", "Следующая сессия"),
        ("ctrl+k", "previous_session", "Предыдущая сессия"),
        ("ctrl+l", "clear_chat", "Очистить чат"),
        ("ctrl+h", "open_help", "Справка"),
        ("?", "show_hotkeys", "Горячие клавиши"),
        ("ctrl+tab", "next_sidebar_tab", "Вкладка sidebar"),
        ("ctrl+shift+tab", "previous_sidebar_tab", "Предыдущая вкладка"),
        ("ctrl+`", "open_terminal_output", "Терминал"),
        ("tab", "cycle_focus", "Переключить фокус"),
        ("ctrl+c", "cancel_prompt", "Отменить"),
        # Новые горячие клавиши Фазы 5
        ("ctrl+p", "command_palette", "Палитра команд"),
        ("ctrl+t", "toggle_theme", "Переключить тему"),
        ("ctrl+m", "select_model", "Выбрать модель"),
        ("escape", "close_modal", "Закрыть"),
    ]

    CSS_PATH = str(Path(__file__).with_name("styles") / "app.tcss")

    def __init__(
        self,
        *,
        host: str,
        port: int,
        cwd: str | None = None,
        history_dir: str | None = None,
        transport_mode: str = "websocket",
        stdio_command: str | None = None,
        stdio_args: list[str] | None = None,
        theme: str | None = None,
    ) -> None:
        """Инициализирует приложение с Clean Architecture.

        Все компоненты инициализируются через DI контейнер.

        Args:
            host: Адрес сервера ACP
            port: Порт сервера ACP
            cwd: Путь к проекту (если None, используется текущая рабочая директория)
            history_dir: Путь к директории локальной истории чата (опционально)
            transport_mode: Режим транспорта ("websocket" или "stdio")
            stdio_command: Команда для запуска агента (для stdio режима)
            stdio_args: Аргументы команды (для stdio режима)
            theme: Тема интерфейса ("light" или "dark", если None — из конфига)
        """
        super().__init__()
        self._host = host
        self._port = port
        # Если cwd не передан, используем текущую директорию
        # Преобразуем в абсолютный путь и проверяем существование
        cwd = os.getcwd() if cwd is None else os.path.abspath(os.path.expanduser(cwd))

        # Проверяем что директория существует
        if not os.path.exists(cwd) or not os.path.isdir(cwd):
            raise ValueError(f"Путь {cwd} не является доступной директорией")

        self._cwd = cwd
        self._config_store = TUIConfigStore()
        self._app_logger = structlog.get_logger("acp_client.tui.app")

        # ThemeManager для переключения тем
        self._theme_manager = ThemeManager(app=self)
        # Регистрируем темы в Textual ДО применения начальной темы
        self._theme_manager.register_textual_themes()
        # Применяем тему из конфига или CLI
        self._apply_initial_theme(theme)
        
        # Флаг видимости sidebar
        self._sidebar_visible = True

        # NavigationManager будет инициализирован в on_mount
        self._navigation_manager: NavigationManager | None = None
        
        # MainLayout будет инициализирован в compose()
        self._main_layout: MainLayout | None = None

        # Блокировка предотвращает параллельные `session/load`, которые могут
        # перемешивать `session/update` между конкурентными запросами.
        self._session_history_load_lock = asyncio.Lock()

        # Инициализируем DI контейнер через dishka
        try:
            self._container = create_client_container(
                host=host,
                port=port,
                cwd=cwd,
                history_dir=history_dir,
                logger=self._app_logger,
                transport_mode=transport_mode,
                stdio_command=stdio_command,
                stdio_args=stdio_args,
            )
            self._app_logger.info("di_container_built_successfully", cwd=cwd)
        except Exception as e:
            self._app_logger.error(
                "failed_to_build_di_container",
                error=str(e),
            )
            raise RuntimeError(f"Failed to initialize DI container: {e}") from e

        # Разрешаем все ViewModels через dishka
        try:
            self._ui_vm = self._container.get(UIViewModel)
            self._session_vm = self._container.get(SessionViewModel)
            self._chat_vm = self._container.get(ChatViewModel)
            self._plan_vm = self._container.get(PlanViewModel)
            self._filesystem_vm = self._container.get(FileSystemViewModel)
            self._terminal_log_vm = self._container.get(TerminalLogViewModel)
            self._file_viewer_vm = self._container.get(FileViewerViewModel)
            self._permission_vm = self._container.get(PermissionViewModel)
            self._terminal_vm = self._container.get(TerminalViewModel)
            self._model_selector_vm = self._container.get(ModelSelectorViewModel)

            self._coordinator = self._container.get(SessionCoordinator)
            self._transport = self._container.get(TransportService)

            self._app_logger.info("all_view_models_resolved")

            # Синхронизируем ChatViewModel с выбранной сессией.
            self._session_vm.selected_session_id.subscribe(self._on_selected_session_changed)
            self._chat_vm.set_active_session(self._session_vm.selected_session_id.value)

            # Подписываемся на события обновления config options
            try:
                from codelab.client.domain.events import ConfigOptionUpdatedEvent

                self._ui_vm.on_event(ConfigOptionUpdatedEvent, self._on_config_option_updated)
            except ImportError:
                self._app_logger.debug("ConfigOptionUpdatedEvent not available")

            # Синхронизируем layout левой колонки с глобальным UI состоянием.
            self._ui_vm.sidebar_tab.subscribe(self._on_sidebar_state_changed)
            self._ui_vm.files_expanded.subscribe(self._on_sidebar_state_changed)
        except Exception as e:
            self._app_logger.error(
                "failed_to_resolve_view_models",
                error=str(e),
            )
            raise RuntimeError(f"Failed to initialize ViewModels: {e}") from e

    def compose(self) -> ComposeResult:
        """Собирает базовый layout приложения в стиле OpenCode.
        
        Структура (OpenCode-style):
        - HeaderBar (titlebar)
        - MainLayout (id="body"):
            - sidebar-column: Sidebar, FileTree (монтируются в on_ready)
            - main-column:
                - content-area: ChatView, PlanPanel (монтируются в on_ready)
                - dock-region: PromptInput, QuickActionsBar (монтируются в on_ready)
            - right-panel-column: ToolPanel (монтируется в on_ready)
        - FooterBar (статус-бар внизу)
        - ToastContainer (overlay)
        """
        yield HeaderBar(self._ui_vm, self._model_selector_vm)
        # MainLayout с dock-region внутри main-column (OpenCode-style)
        self._main_layout = MainLayout(ui_vm=self._ui_vm, id="body")
        yield self._main_layout
        # FooterBar как отдельный элемент внизу экрана
        yield FooterBar(self._ui_vm, theme_manager=self._theme_manager)
        # ToastContainer должен быть поверх других элементов (в конце compose)
        yield ToastContainer(id="toast-container")

    def _apply_initial_theme(self, cli_theme: str | None) -> None:
        """Применяет тему при старте из конфига или CLI.

        Приоритет: CLI theme > config file > default (light).

        Args:
            cli_theme: Тема из CLI флага --theme (если есть)
        """
        if cli_theme in ("light", "dark"):
            # CLI имеет высший приоритет
            self._theme_manager.set_theme(cli_theme)
            self._app_logger.info("theme_applied_from_cli", theme=cli_theme)
        else:
            # Загружаем из конфига
            config = self._config_store.load()
            self._theme_manager.set_theme(config.theme)
            self._app_logger.info("theme_applied_from_config", theme=config.theme)

    def on_ready(self) -> None:
        """Запускается когда приложение готово к работе."""
        self._app_logger.info("app_ready")

        # Монтируем компоненты в контейнеры MainLayout
        self._mount_main_layout_children()

        # Инициализируем NavigationManager
        try:
            self._navigation_manager = NavigationManager(self)
            self._app_logger.debug("navigation_manager_initialized")
        except Exception as e:
            self._app_logger.error(
                "failed_to_initialize_navigation_manager",
                error=str(e),
            )

        # Инициализируем подключение к серверу
        self._app_logger.info("starting_connection_worker")
        self.run_worker(self._initialize_connection(), exclusive=False)
        self._on_sidebar_state_changed(None)

    def _mount_main_layout_children(self) -> None:
        """Монтирует дочерние компоненты в контейнеры MainLayout (OpenCode-style).
        
        Эта функция вызывается в on_ready после того как MainLayout создан в compose().
        
        OpenCode-style layout:
        - sidebar-column: Sidebar, FileTree
        - main-column:
            - content-area: ChatView, PlanPanel
            - dock-region: PromptInput, QuickActionsBar
        - right-panel-column: ToolPanel
        """
        if self._main_layout is None:
            self._app_logger.error("main_layout_not_initialized")
            return
        
        # Монтируем компоненты в sidebar
        sidebar_column = self._main_layout.sidebar_column
        if sidebar_column is not None:
            sidebar_column.mount(Sidebar(self._session_vm, self._ui_vm))
            sidebar_column.mount(
                FileTree(
                    filesystem_vm=self._filesystem_vm,
                    root_path=self._cwd,
                )
            )
            self._app_logger.debug("sidebar_components_mounted")
        
        # Монтируем компоненты в content-area
        content_area = self._main_layout.content_area
        if content_area is not None:
            self._chat_view = ChatView(self._chat_vm, self._permission_vm)
            content_area.mount(self._chat_view)
            content_area.mount(PlanPanel(self._plan_vm))
            self._app_logger.debug("content_area_components_mounted")
        
        # Монтируем PromptInput и QuickActionsBar в dock-region (OpenCode-style)
        dock_region = self._main_layout.dock_region
        if dock_region is not None:
            dock_region.mount(PromptInput(self._chat_vm))
            dock_region.mount(QuickActionsBar(self._ui_vm, theme_manager=self._theme_manager))
            self._app_logger.debug("dock_region_components_mounted")
        
        # Монтируем ToolPanel в right-panel-column
        right_panel = self._main_layout.right_panel_column
        if right_panel is not None:
            right_panel.mount(ToolPanel(self._chat_vm, self._terminal_vm))
            self._app_logger.debug("right_panel_components_mounted")

    async def _initialize_connection(self) -> None:
        """Инициализирует подключение к серверу."""
        self._app_logger.info("connection_worker_started")
        self._ui_vm.set_connection_status(ConnectionStatus.CONNECTING)
        self._ui_vm.set_loading(True, "connecting to server")
        try:
            # Инициализируем подключение
            self._app_logger.info("initializing_server_connection")
            server_info = await self._coordinator.initialize()

            self._app_logger.info(
                "server_connection_initialized",
                protocol_version=server_info.get("protocol_version"),
                auth_methods=len(server_info.get("available_auth_methods", [])),
            )

            # Обновляем статус подключения в UI
            self._ui_vm.set_connection_status(ConnectionStatus.CONNECTED)
            self._ui_vm.set_loading(False)

            # Показываем toast о успешном подключении
            self.show_toast("Подключено к серверу", level="success")

            # Устанавливаем callback для показа permission modal в UI.
            # Это необходимо, чтобы при получении session/request_permission от сервера
            # TUI приложение показало модальное окно для выбора разрешения.
            try:
                cast(ACPTransportService, self._transport).set_permission_callback(
                    self.show_permission_modal
                )
                self._app_logger.info("permission_callback_registered_in_transport")
            except Exception as e:
                self._app_logger.warning(
                    "failed_to_set_permission_callback",
                    error=str(e),
                )

            # После успешного подключения запрашиваем список сессий с сервера,
            # чтобы sidebar отображал сохраненные сессии сразу при старте.
            await self._session_vm.load_sessions_cmd.execute()
            loaded_count = self._session_vm.session_count.value
            self._app_logger.info(
                "sessions_loaded_on_startup",
                count=loaded_count,
                host=self._host,
                port=self._port,
            )
            if loaded_count == 0:
                # Явный warning помогает сразу понять, что сервер вернул пустой session/list.
                self._app_logger.warning(
                    "session_list_is_empty_on_startup",
                    hint="Проверьте, что сервер запущен с persistent --storage json:<path>",
                )

        except Exception as e:
            self._app_logger.error(
                "failed_to_initialize_connection",
                error=str(e),
                exc_info=True,
            )
            # Обновляем статус подключения в UI
            self._ui_vm.set_connection_status(ConnectionStatus.DISCONNECTED)
            self._ui_vm.set_loading(False)

            # Показываем toast об ошибке подключения
            self.show_toast(f"Ошибка подключения: {e}", level="error")

    def show_toast(self, message: str, level: str = "info", timeout: float = 3.0) -> None:
        """Показывает toast-уведомление.

        Args:
            message: Текст уведомления
            level: Уровень уведомления (info, success, warning, error)
            timeout: Время отображения в секундах
        """
        try:
            toast_container = self.query_one("#toast-container", ToastContainer)
            # Вызываем соответствующий метод в зависимости от уровня
            if level == "success":
                toast_container.success(message, duration=timeout)
            elif level == "warning":
                toast_container.warning(message, duration=timeout)
            elif level == "error":
                toast_container.error(message, duration=timeout)
            else:
                toast_container.info(message, duration=timeout)
        except Exception as e:
            self._app_logger.warning("failed_to_show_toast", error=str(e))

    def _on_sidebar_state_changed(self, _: object) -> None:
        """Синхронизировать видимость FileTree с активной вкладкой sidebar."""

        try:
            file_tree = self.query_one(FileTree)
        except Exception:
            return

        is_files_tab = self._ui_vm.sidebar_tab.value == SidebarTab.FILES
        should_show = is_files_tab and self._ui_vm.files_expanded.value
        file_tree.display = should_show

    def action_next_sidebar_tab(self) -> None:
        """Переключить вкладку sidebar вперед по кругу."""

        self._ui_vm.cycle_sidebar_tab()

    def action_previous_sidebar_tab(self) -> None:
        """Переключить вкладку sidebar назад по кругу."""

        self._ui_vm.cycle_sidebar_tab(reverse=True)

    def action_new_session(self) -> None:
        """Создает новую сессию по горячей клавише Ctrl+N."""
        self._app_logger.info("new_session_requested", cwd=self._cwd)
        # Передаем cwd при создании новой сессии для инициализации рабочей директории
        self.run_worker(
            self._session_vm.create_session_cmd.execute(
                self._host,
                self._port,
                cwd=self._cwd,
            ),
            exclusive=False,
        )

    def action_cancel_prompt(self) -> None:
        """Отменяет текущий LLM-запрос для активной сессии (Ctrl+C / Stop)."""
        session_id = self._session_vm.selected_session_id.value
        is_streaming = self._chat_vm.is_streaming.value
        is_executing = self._chat_vm.cancel_prompt_cmd.is_executing.value
        self._app_logger.info(
            "action_cancel_prompt_called",
            session_id=session_id,
            is_streaming=is_streaming,
            is_executing=is_executing,
        )
        if not session_id:
            self._app_logger.warning("cancel_prompt_no_active_session")
            return
        if not is_streaming:
            self._app_logger.debug("cancel_prompt_skipped_not_streaming")
            return
        if is_executing:
            self._app_logger.debug("cancel_prompt_skipped_already_executing")
            return
        self._app_logger.info("cancel_prompt_dispatching", session_id=session_id)
        self.run_worker(
            self._chat_vm.cancel_prompt_cmd.execute(session_id),
            exclusive=False,
        )

    def action_toggle_sidebar(self) -> None:
        """Показывает/скрывает боковую панель."""
        try:
            sidebar_column = self.query_one("#sidebar-column")
            self._sidebar_visible = not self._sidebar_visible
            sidebar_column.display = self._sidebar_visible
            self._app_logger.debug("sidebar_toggled", visible=self._sidebar_visible)
        except Exception as e:
            self._app_logger.warning("toggle_sidebar_failed", error=str(e))

    def action_focus_sidebar(self) -> None:
        """Переводит фокус в список сессий."""

        sidebar = self.query_one(Sidebar)
        sidebar.focus()

    def action_focus_session_list(self) -> None:
        """Алиас для перевода фокуса в список сессий."""

        self.action_focus_sidebar()

    def action_open_help(self) -> None:
        """Открыть контекстную справку по текущему фокусу."""

        focused = self.focused
        context = "global"
        if isinstance(focused, Sidebar):
            context = "sidebar"
        elif isinstance(focused, FileTree):
            context = "file-tree"
        elif isinstance(focused, PromptInput):
            context = "prompt-input"
        self.push_screen(HelpModal(context=context, show_hotkeys=False))

    def action_show_hotkeys(self) -> None:
        """Показать отдельный экран со списком горячих клавиш."""

        self.push_screen(HelpModal(context="global", show_hotkeys=True))

    def action_command_palette(self) -> None:
        """Открывает палитру команд."""
        self._app_logger.debug("opening_command_palette")

        def on_command_selected(result: object) -> None:
            """Обработка выбранной команды."""
            if result is not None:
                # Выполняем action команды
                from .components import Command
                if isinstance(result, Command) and result.action:
                    self._app_logger.debug(
                        "command_selected",
                        command_id=result.id,
                        action=result.action,
                    )
                    try:
                        self.action(result.action)
                    except Exception as e:
                        self._app_logger.warning(
                            "command_action_failed",
                            action=result.action,
                            error=str(e),
                        )

        self.push_screen(CommandPalette(), callback=on_command_selected)

    def action_toggle_theme(self) -> None:
        """Переключает между светлой и тёмной темой."""
        current = self._theme_manager.current_theme_name
        if current == "dark":
            self._theme_manager.set_theme("light")
        else:
            self._theme_manager.set_theme("dark")
        
        # Сохраняем тему в конфиг
        config = self._config_store.load()
        config.theme = cast(TUITheme, self._theme_manager.current_theme_name)
        self._config_store.save(config)
        
        # Обновляем иконку в QuickActionsBar
        try:
            quick_actions = self.query_one(QuickActionsBar)
            quick_actions.update_theme_icon()
        except Exception as e:
            self._app_logger.debug("failed_to_update_theme_icon", error=str(e))
        
        self._app_logger.debug(
            "theme_toggled",
            new_theme=self._theme_manager.current_theme_name,
        )

    def action_select_model(self) -> None:
        """Открывает модальное окно выбора LLM модели."""
        session_id = self._session_vm.selected_session_id.value
        if not session_id:
            self._app_logger.warning("select_model_no_active_session")
            self.show_toast("Сначала создайте или загрузите сессию", level="warning")
            return

        self._app_logger.debug("opening_model_selector", session_id=session_id)

        def on_model_selected(model_value: str | None) -> None:
            """Обработка выбранной модели."""
            if model_value:
                self._app_logger.info(
                    "model_selected",
                    session_id=session_id,
                    model=model_value,
                )
                self.run_worker(
                    self._model_selector_vm.select_model_cmd.execute(
                        session_id=session_id,
                        model_value=model_value,
                    ),
                    exclusive=False,
                )
                self.show_toast(f"Модель изменена на {model_value.split('/')[-1]}", level="success")
            else:
                self._app_logger.debug("model_selection_cancelled")

        self.push_screen(
            ModelSelectorModal(
                view_model=self._model_selector_vm,
                session_id=session_id,
            ),
            callback=on_model_selected,
        )

    def action_close_modal(self) -> None:
        """Закрывает текущее модальное окно."""
        # Textual автоматически обрабатывает escape для модальных окон,
        # но этот action может быть вызван из других мест
        if self.screen.is_modal:
            self.pop_screen()
        else:
            # Если нет модального окна, отменяем текущий ввод
            self.action_cancel_prompt()

    def action_next_session(self) -> None:
        """Выбирает следующую сессию в sidebar и применяет выбор."""

        sidebar = self.query_one(Sidebar)
        sidebar.select_next()
        selected_session_id = sidebar.get_selected_session_id()
        if selected_session_id is None:
            return
        self.run_worker(
            self._session_vm.switch_session_cmd.execute(selected_session_id),
            exclusive=False,
        )

    def action_previous_session(self) -> None:
        """Выбирает предыдущую сессию в sidebar и применяет выбор."""

        sidebar = self.query_one(Sidebar)
        sidebar.select_previous()
        selected_session_id = sidebar.get_selected_session_id()
        if selected_session_id is None:
            return
        self.run_worker(
            self._session_vm.switch_session_cmd.execute(selected_session_id),
            exclusive=False,
        )

    def on_sidebar_session_selected(self, event: Sidebar.SessionSelected) -> None:
        """Применяет выбор сессии по Enter в sidebar."""

        self.run_worker(
            self._session_vm.switch_session_cmd.execute(event.session_id),
            exclusive=False,
        )

    # =========================================================================
    # Обработчики QuickActionsBar
    # =========================================================================

    def on_quick_actions_bar_new_session_requested(
        self, event: QuickActionsBar.NewSessionRequested
    ) -> None:
        """Обработчик запроса создания новой сессии из QuickActionsBar."""
        self._app_logger.info("quick_actions_new_session_requested")
        self.action_new_session()

    def on_quick_actions_bar_cancel_requested(
        self, event: QuickActionsBar.CancelRequested
    ) -> None:
        """Обработчик запроса отмены из QuickActionsBar."""
        self._app_logger.info("quick_actions_cancel_requested")
        self.action_cancel_prompt()

    def on_quick_actions_bar_help_requested(
        self, event: QuickActionsBar.HelpRequested
    ) -> None:
        """Обработчик запроса справки из QuickActionsBar."""
        self._app_logger.info("quick_actions_help_requested")
        self.action_open_help()

    def on_quick_actions_bar_theme_toggle_requested(
        self, event: QuickActionsBar.ThemeToggleRequested
    ) -> None:
        """Обработчик запроса переключения темы из QuickActionsBar."""
        self._app_logger.info("quick_actions_theme_toggle_requested")
        self.action_toggle_theme()

    def on_prompt_input_cancelled(self, event: PromptInput.Cancelled) -> None:
        """Обработка нажатия кнопки Stop в PromptInput."""
        self._app_logger.info("prompt_input_cancelled_received")
        self.action_cancel_prompt()

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        """Обработать отправку промпта пользователем.

        Args:
            event: Событие с текстом промпта
        """
        # Получаем ID активной сессии
        session_id = self._session_vm.selected_session_id.value

        if not session_id:
            self._app_logger.warning("prompt_submitted_without_active_session")
            # Можно показать уведомление пользователю
            return

        self._app_logger.info(
            "prompt_submitted",
            session_id=session_id,
            prompt_length=len(event.text),
        )

        # Добавляем сообщение пользователя в чат
        self._chat_vm.add_message("user", event.text, session_id=session_id)

        # Устанавливаем состояние загрузки ДО запуска async worker'а
        # чтобы LoadingIndicator показался сразу
        self._chat_vm.is_streaming.value = True

        # Запускаем отправку промпта асинхронно
        self.run_worker(
            self._chat_vm.send_prompt_cmd.execute(session_id, event.text),
            exclusive=False,
        )

        # Показываем toast о отправке запроса
        self.show_toast("Запрос отправлен", level="info")

    def _on_selected_session_changed(self, session_id: str | None) -> None:
        """Обновляет ChatView при смене активной сессии."""

        self._chat_vm.set_active_session(session_id)
        if session_id is None:
            return

        # При выборе сессии сразу запрашиваем `session/load`, чтобы UI получил
        # историю из серверного persistence даже при пустом локальном кэше.
        self.run_worker(
            self._load_selected_session_history(session_id),
            exclusive=False,
        )

    async def _load_selected_session_history(self, session_id: str) -> None:
        """Загружает историю выбранной сессии через `session/load`."""

        async with self._session_history_load_lock:
            try:
                loaded = await self._coordinator.load_session(
                    session_id,
                    self._host,
                    self._port,
                    cwd=self._cwd,
                    mcp_servers=[],
                )
                replay_updates = loaded.get("replay_updates", [])
                if isinstance(replay_updates, list):
                    self._chat_vm.restore_session_from_replay(session_id, replay_updates)

                self._app_logger.info(
                    "session_history_loaded",
                    session_id=session_id,
                    replay_updates_count=(
                        len(replay_updates) if isinstance(replay_updates, list) else 0
                    ),
                )
            except Exception as error:
                self._app_logger.warning(
                    "session_history_load_failed",
                    session_id=session_id,
                    error=str(error),
                )

    def show_permission_modal(
        self,
        request_id: str | int,
        tool_call: PermissionToolCall,
        options: list[PermissionOption],
        on_choice: Callable[[str | int, str], None],
    ) -> None:
        """Показывает встроенный виджет разрешения в ChatView.

        Заменяет модальное окно на встроенный виджет для лучшей видимости.
        Интегрирует InlinePermissionWidget с SessionCoordinator через callback pattern.

        Args:
            request_id: ID permission request от сервера
            tool_call: Информация о tool call (kind, title, toolCallId)
            options: Доступные опции для выбора (allow_once, reject_once, и т.д.)
            on_choice: Callback для обработки выбора (request_id, option_id)
        """
        self._app_logger.debug(
            "show_permission_modal_called",
            request_id=request_id,
            tool_call_kind=tool_call.kind,
            tool_call_title=tool_call.title,
            options_count=len(options),
        )

        try:
            # Показать встроенный виджет в ChatView
            if hasattr(self, "_chat_view") and self._chat_view is not None:
                self._app_logger.debug(
                    "showing_inline_permission_widget",
                    request_id=request_id,
                    tool_call_kind=tool_call.kind,
                    tool_call_title=tool_call.title,
                    options_count=len(options),
                )
                self._chat_view.show_permission_request(
                    request_id, tool_call, options, on_choice
                )
            else:
                self._app_logger.warning(
                    "chat_view_not_available_for_permission_widget",
                    request_id=request_id,
                    fallback="showing_modal_instead",
                )
                # Fallback на модальное окно если ChatView недоступна
                title = f"{tool_call.kind}: {tool_call.title}"
                modal = PermissionModal(
                    permission_vm=self._permission_vm,
                    request_id=request_id,
                    title=title,
                    options=options,
                    on_choice=on_choice,
                )
                self.push_screen(modal)

        except Exception as e:
            self._app_logger.error(
                "failed_to_show_permission_widget",
                request_id=request_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            # Fallback: вызвать on_choice с cancelled при ошибке
            try:
                on_choice(request_id, "cancelled")
            except Exception as fallback_error:
                self._app_logger.error(
                    "failed_to_call_on_choice_callback",
                    request_id=request_id,
                    error=str(fallback_error),
                )

    def on_tool_call_card_selected(self, event: ToolCallCard.Selected) -> None:
        """Обработчик выбора карточки tool call.
        
        Показывает модальное окно FileChangePreviewModal для инструментов
        типа write_file, file_edit и подобных, которые изменяют файлы.
        
        Args:
            event: Событие выбора карточки tool call
        """
        card = event.card
        tool_name = card.tool_name
        tool_call_id = card.tool_call_id
        
        self._app_logger.debug(
            "tool_call_card_selected",
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        )
        
        # Проверяем, является ли инструмент файловым
        file_tools = {"write_file", "file_edit", "create_file", "edit_file", "patch_file"}
        if tool_name not in file_tools:
            # Для не-файловых инструментов просто логируем
            self._app_logger.debug(
                "tool_call_card_selected_non_file_tool",
                tool_call_id=tool_call_id,
                tool_name=tool_name,
            )
            return
        
        # Получаем данные о tool call из ChatViewModel
        tool_calls = self._chat_vm.tool_calls.value
        tool_call_data = None
        
        for tc in tool_calls:
            if isinstance(tc, dict):
                tc_id = tc.get("toolCallId") or tc.get("id")
            else:
                tc_id = getattr(tc, "toolCallId", None) or getattr(tc, "id", None)
            
            if tc_id == tool_call_id:
                tool_call_data = tc
                break
        
        if tool_call_data is None:
            self._app_logger.warning(
                "tool_call_data_not_found",
                tool_call_id=tool_call_id,
            )
            return
        
        # Извлекаем параметры для FileChangePreview
        if isinstance(tool_call_data, dict):
            params = tool_call_data.get("parameters") or tool_call_data.get("rawInput") or {}
        else:
            params = getattr(tool_call_data, "parameters", {}) or {}
        
        file_path = (
            params.get("path") or params.get("file_path")
            or params.get("filePath") or "unknown"
        )
        old_content = params.get("old_content") or params.get("oldContent") or ""
        new_content = (
            params.get("content") or params.get("new_content")
            or params.get("newContent") or ""
        )
        
        # Показываем модальное окно предпросмотра изменений
        self._app_logger.info(
            "showing_file_change_preview_modal",
            tool_call_id=tool_call_id,
            file_path=file_path,
        )
        
        modal = FileChangePreviewModal(
            file_path=file_path,
            old_content=old_content,
            new_content=new_content,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        )
        self.push_screen(modal)

    def _on_config_option_updated(self, event: Any) -> None:
        """Обработать обновление конфигурационных опций сессии.

        Обновляет ModelSelectorViewModel новыми данными из configOptions.

        Args:
            event: ConfigOptionUpdatedEvent
        """
        session_id = getattr(event, "session_id", None)
        config_options = getattr(event, "config_options", [])

        if session_id and config_options:
            self._app_logger.debug(
                "config_option_updated",
                session_id=session_id,
                config_options_count=len(config_options),
            )
            self._model_selector_vm.update_models_from_config(
                config_options=config_options,
                session_id=session_id,
            )

    async def on_unmount(self) -> None:
        """Очистка ресурсов при завершении приложения."""
        self._app_logger.info("app_unmounting")

        # Закрываем WebSocket соединение
        try:
            await self._transport.disconnect()
            self._app_logger.info("websocket_disconnected")
        except Exception as e:
            self._app_logger.error("websocket_disconnect_failed", error=str(e))

        # Закрываем DI контейнер (dishka вызывает финализаторы)
        try:
            self._container.close()
            self._app_logger.info("di_container_closed")
        except Exception as e:
            self._app_logger.error("di_container_close_failed", error=str(e))

        self._app_logger.info("app_unmounted")


def run_tui_app(
    *,
    host: str | None = None,
    port: int | None = None,
    cwd: str | None = None,
    history_dir: str | None = None,
    transport_mode: str = "websocket",
    stdio_command: str | None = None,
    stdio_args: list[str] | None = None,
    theme: str | None = None,
) -> None:
    """Запускает TUI приложение с параметрами подключения и рабочей директории.

    Args:
        host: Адрес сервера ACP (если None, используется значение по умолчанию)
        port: Порт сервера ACP (если None, используется значение по умолчанию)
        cwd: Путь к проекту (если None, используется текущая рабочая директория)
        history_dir: Путь к директории локальной истории чата (опционально)
        transport_mode: Режим транспорта ("websocket" или "stdio")
        stdio_command: Команда для запуска агента (для stdio режима)
        stdio_args: Аргументы команды (для stdio режима)
        theme: Тема интерфейса ("light" или "dark", если None — из конфига)
    """
    resolved_host, resolved_port, resolved_theme = resolve_tui_connection(
        host=host, port=port, theme=cast(TUITheme, theme) if theme in ("light", "dark") else None
    )
    app = ACPClientApp(
        host=resolved_host,
        port=resolved_port,
        cwd=cwd,
        history_dir=history_dir,
        transport_mode=transport_mode,
        stdio_command=stdio_command,
        stdio_args=stdio_args,
        theme=resolved_theme,
    )
    app.run()
