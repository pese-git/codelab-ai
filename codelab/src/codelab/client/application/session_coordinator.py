"""SessionCoordinator - оркестрация операций с сессиями.

Координирует взаимодействие между Application и Infrastructure слоями
для управления жизненным циклом сессии и выполнения операций.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from codelab.client.domain import SessionRepository, TransportService
from codelab.client.infrastructure.logging_config import get_logger
from codelab.client.messages import (
    CancelledPermissionOutcome,
    PermissionOption,
    PermissionOutcome,
    PermissionToolCall,
    RequestPermissionRequest,
)

from .dto import CreateSessionRequest, LoadSessionRequest, PromptCallbacks, SendPromptRequest
from .permission_handler import PermissionHandler
from .use_cases import (
    CreateSessionUseCase,
    InitializeUseCase,
    ListSessionsUseCase,
    LoadSessionUseCase,
    SendPromptUseCase,
)


class SessionCoordinator:
    """Оркестратор для операций с сессиями.

    Предоставляет удобный интерфейс для работы с сессиями,
    инкапсулируя использование use cases и управление зависимостями.
    """

    def __init__(
        self,
        transport: TransportService,
        session_repo: SessionRepository,
        permission_handler: PermissionHandler | None = None,
    ) -> None:
        """Инициализирует координатор.

        Аргументы:
            transport: TransportService для коммуникации
            session_repo: SessionRepository для хранения
            permission_handler: PermissionHandler для обработки permission requests (опционально)
        """
        self.transport = transport
        self.session_repo = session_repo
        self._permission_handler = permission_handler
        self._logger = get_logger("session_coordinator")

        # Инициализируем use cases
        self.initialize_use_case = InitializeUseCase(transport)
        self.create_session_use_case = CreateSessionUseCase(transport, session_repo)
        self.load_session_use_case = LoadSessionUseCase(transport, session_repo)
        self.send_prompt_use_case = SendPromptUseCase(transport, session_repo)
        self.list_sessions_use_case = ListSessionsUseCase(transport, session_repo)

    async def initialize(self) -> dict[str, Any]:
        """Инициализирует соединение с сервером.

        Возвращает:
            Информацию о сервере и его capabilities
        """
        self._logger.info("initializing_connection")
        response = await self.initialize_use_case.execute()
        return {
            "server_capabilities": response.server_capabilities,
            "available_auth_methods": response.available_auth_methods,
            "protocol_version": response.protocol_version,
        }

    async def create_session(
        self,
        server_host: str,
        server_port: int,
        cwd: str | None = None,
        client_capabilities: dict[str, Any] | None = None,
        mcp_servers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Создает новую сессию на сервере.

        Аргументы:
            server_host: Адрес сервера
            server_port: Порт сервера
            cwd: Абсолютный путь рабочей директории (если None, используется текущая директория)
            client_capabilities: Возможности клиента (опционально)
            mcp_servers: Список MCP-серверов из TOML конфигурации

        Возвращает:
            Объект созданной сессии с ID и capabilities
        """
        session_cwd = cwd or str(Path.cwd())

        request = CreateSessionRequest(
            server_host=server_host,
            server_port=server_port,
            cwd=session_cwd,
            client_capabilities=client_capabilities,
            mcp_servers=mcp_servers,
        )

        self._logger.info("creating_session")
        response = await self.create_session_use_case.execute(request)

        return {
            "session_id": response.session_id,
            "server_capabilities": response.server_capabilities,
            "is_authenticated": response.is_authenticated,
        }

    async def list_sessions(self) -> list[dict[str, Any]]:
        """Получает список всех доступных сессий.

        Возвращает:
            Список сессий с метаданными
        """
        self._logger.info("listing_sessions")
        response = await self.list_sessions_use_case.execute()
        return response.sessions

    async def load_session(
        self,
        session_id: str,
        server_host: str,
        server_port: int,
        cwd: str | None = None,
        mcp_servers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Загружает существующую сессию через `session/load`.

        Аргументы:
            session_id: ID сессии
            server_host: Адрес сервера (для совместимости DTO)
            server_port: Порт сервера (для совместимости DTO)
            cwd: Абсолютный путь рабочей директории
            mcp_servers: Список MCP-серверов

        Возвращает:
            Словарь с данными загруженной сессии и replay updates
        """

        request = LoadSessionRequest(
            session_id=session_id,
            server_host=server_host,
            server_port=server_port,
            cwd=cwd,
            mcp_servers=mcp_servers,
        )

        self._logger.info("loading_session")
        response = await self.load_session_use_case.execute(request)
        return {
            "session_id": response.session_id,
            "server_capabilities": response.server_capabilities,
            "is_authenticated": response.is_authenticated,
            "replay_updates": response.replay_updates,
        }

    async def delete_session(self, session_id: str) -> None:
        """Удаляет сессию из локального репозитория."""

        self._logger.info("deleting_session")
        await self.session_repo.delete(session_id)

    async def cancel_prompt(self, session_id: str) -> None:
        """Отменяет текущий prompt на сервере для указанной сессии."""

        self._logger.info("cancelling_prompt", session_id=session_id)
        await self.transport.cancel_prompt(session_id)
        self._logger.info("cancelling_prompt_done", session_id=session_id)

    async def request_permission(
        self,
        request: RequestPermissionRequest,
        callback: Callable[[str | int, PermissionToolCall, list[PermissionOption]], None],
    ) -> PermissionOutcome:
        """Запрашивает разрешение у пользователя через UI.

        Координирует полный цикл обработки permission request:
        1. Создание PermissionRequest с timeout
        2. Вызов callback для показа UI modal (request_id, tool_call, options)
        3. Ожидание выбора пользователя или timeout
        4. Возврат результата выбора

        Args:
            request: Permission request от сервера (RequestPermissionRequest)
            callback: Функция для показа UI modal
                Сигнатура: Callable[[str | int, PermissionToolCall, list[PermissionOption]], None]
                Вызывается как: callback(request_id, tool_call, options)
                Должна показать модальное окно и вернуться сразу (без ожидания)

        Returns:
            PermissionOutcome с выбором пользователя (selected или cancelled)

        Raises:
            asyncio.TimeoutError: Если пользователь не ответил в течение timeout (обработано внутри)
        """
        # Проверить наличие permission_handler
        if self._permission_handler is None:
            self._logger.warning(
                "permission_handler_not_available",
                request_id=request.id,
            )
            return CancelledPermissionOutcome(outcome="cancelled")

        try:
            # Получить request manager из permission handler
            request_manager = self._permission_handler.get_request_manager()

            # Создать PermissionRequest через manager с timeout 5 минут
            perm_request = request_manager.create_request(
                request_id=request.id,
                session_id=request.params.sessionId,
                tool_call=request.params.toolCall,
                options=request.params.options,
                timeout=300.0,  # 5 минут
            )

            self._logger.info(
                "permission_request_created",
                request_id=request.id,
                session_id=request.params.sessionId,
                tool_call_id=request.params.toolCall.toolCallId,
            )

            # Вызвать callback для показа UI modal
            # Callback должен показать PermissionModal в TUI
            self._logger.info(
                "showing_permission_modal_to_user",
                request_id=request.id,
                session_id=request.params.sessionId,
                tool_call_id=request.params.toolCall.toolCallId,
                tool_name=request.params.toolCall.title,
            )
            callback(request.id, request.params.toolCall, request.params.options)

            # Дождаться результата выбора пользователя или timeout
            self._logger.debug(
                "waiting_for_user_permission_choice",
                request_id=request.id,
                session_id=request.params.sessionId,
            )
            outcome = await perm_request.wait_for_outcome()

            self._logger.info(
                "permission_outcome_received_from_user",
                request_id=request.id,
                session_id=request.params.sessionId,
                tool_call_id=request.params.toolCall.toolCallId,
                outcome=outcome.outcome,
                option_id=getattr(outcome, 'optionId', None),
            )

            return outcome

        except TimeoutError:
            self._logger.warning(
                "permission_request_timeout",
                request_id=request.id,
            )
            return CancelledPermissionOutcome(outcome="cancelled")

        except Exception as e:
            self._logger.error(
                "permission_request_error",
                request_id=request.id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return CancelledPermissionOutcome(outcome="cancelled")

        finally:
            # Cleanup - удалить request из manager после завершения
            if self._permission_handler is not None:
                try:
                    self._permission_handler.get_request_manager().remove_request(
                        request.id
                    )
                    self._logger.debug(
                        "permission_request_removed",
                        request_id=request.id,
                    )
                except Exception as e:
                    self._logger.debug(
                        "permission_request_cleanup_error",
                        request_id=request.id,
                        error=str(e),
                    )

    def resolve_permission(
        self,
        request_id: str | int,
        option_id: str,
    ) -> None:
        """Разрешает pending permission request с выбранной опцией.

        Вызывается из UI когда пользователь делает выбор.

        Args:
            request_id: ID запроса
            option_id: ID выбранной опции (allow_once, reject_once, etc.)
        """
        self._logger.debug(
            "user_made_permission_choice",
            request_id=request_id,
            option_id=option_id,
        )
        
        if self._permission_handler is None:
            self._logger.warning(
                "permission_handler_not_available_for_resolve",
                request_id=request_id,
            )
            return

        try:
            request_manager = self._permission_handler.get_request_manager()
            perm_request = request_manager.get_request(request_id)

            if perm_request is None:
                self._logger.warning(
                    "permission_request_not_found_for_resolve",
                    request_id=request_id,
                )
                return

            perm_request.resolve_with_option(option_id)

        except Exception as e:
            self._logger.error(
                "permission_resolve_error",
                request_id=request_id,
                error=str(e),
            )

    def cancel_permission(
        self,
        request_id: str | int,
    ) -> None:
        """Отменяет pending permission request.

        Вызывается при получении session/cancel от сервера.

        Args:
            request_id: ID запроса для отмены
        """
        if self._permission_handler is None:
            self._logger.warning(
                "permission_handler_not_available_cancel",
                request_id=request_id,
            )
            return

        try:
            request_manager = self._permission_handler.get_request_manager()
            request_manager.cancel_request(request_id)

            self._logger.info(
                "permission_cancelled",
                request_id=request_id,
            )

        except Exception as e:
            self._logger.error(
                "permission_cancel_error",
                request_id=request_id,
                error=str(e),
            )

    async def set_config_option(
        self,
        session_id: str,
        config_id: str,
        value: str,
    ) -> dict[str, Any] | None:
        """Установить конфигурационную опцию сессии.

        Args:
            session_id: ID сессии
            config_id: ID конфигурационной опции (например, "model")
            value: Новое значение (например, "openai/gpt-4o")

        Returns:
            Результат с обновлёнными configOptions или None при ошибке
        """
        self._logger.info(
            "setting_config_option",
            session_id=session_id,
            config_id=config_id,
            value=value,
        )

        try:
            result = await self.transport.set_config_option(
                session_id=session_id,
                config_id=config_id,
                value=value,
            )
            self._logger.info(
                "config_option_set_successfully",
                session_id=session_id,
                config_id=config_id,
            )
            return result
        except Exception as e:
            self._logger.error(
                "config_option_set_failed",
                session_id=session_id,
                config_id=config_id,
                error=str(e),
            )
            return None

    async def handle_permission(
        self,
        session_id: str,
        permission_id: str,
        *,
        approved: bool,
        **_: Any,
    ) -> None:
        """Локально фиксирует решение по permission-запросу.

        В текущем клиенте решение по permission отправляется в рамках
        request/response-цикла транспорта. Этот метод оставлен как
        совместимый контракт для существующих ViewModel-команд.

        Deprecated: Используйте resolve_permission() вместо этого метода.
        """

        self._logger.info(
            "permission_decision_recorded",
            session_id=session_id,
            permission_id=permission_id,
            approved=approved,
        )

    async def send_prompt(
        self,
        session_id: str,
        prompt_text: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Отправить prompt в активную сессию.

        Аргументы:
            session_id: ID сессии
            prompt_text: Текст промпта
            **kwargs: Дополнительные параметры (callbacks и т.д.)

        Возвращает:
            Результат выполнения промпта
        """
        # Извлекаем callbacks если переданы
        callbacks = kwargs.get("callbacks")
        if callbacks is None and any(k.startswith("on_") for k in kwargs):
            # Создаем PromptCallbacks из kwargs
            callbacks = PromptCallbacks(
                on_update=kwargs.get("on_update"),
                on_fs_read=kwargs.get("on_fs_read"),
                on_fs_write=kwargs.get("on_fs_write"),
                on_terminal_create=kwargs.get("on_terminal_create"),
                on_terminal_output=kwargs.get("on_terminal_output"),
                on_terminal_wait_for_exit=kwargs.get("on_terminal_wait_for_exit"),
                on_terminal_release=kwargs.get("on_terminal_release"),
                on_terminal_kill=kwargs.get("on_terminal_kill"),
            )

        request = SendPromptRequest(
            session_id=session_id,
            prompt_text=prompt_text,
            callbacks=callbacks,
        )

        self._logger.info("sending_prompt")
        response = await self.send_prompt_use_case.execute(request)

        return {
            "session_id": response.session_id,
            "prompt_result": response.prompt_result,
            "updates": response.updates,
        }
