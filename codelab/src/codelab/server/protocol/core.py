"""Основной класс протокола ACP.

Содержит реализацию класса ACPProtocol с основной логикой обработки
запросов клиента и управления сессиями.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol

import structlog

from ..mcp import MCPManager, MCPManagerError
from ..mcp.models import MCPServerConfig
from ..messages import ACPMessage, JsonRpcId
from ..storage import SessionStorage
from .handlers import (
    auth,
    config,
    legacy,
    permissions,
    prompt,
    session,
)
from .pending_registry import PendingRequestRegistry
from .session_factory import SessionFactory
from .state import (
    ClientRuntimeCapabilities,
    LLMLoopResult,
    ProtocolOutcome,
    SessionState,
)

if TYPE_CHECKING:
    from ..agent.orchestrator import AgentOrchestrator
    from ..client_rpc.service import ClientRPCService
    from ..tools.base import ToolRegistry
    from .handlers.global_policy_manager import GlobalPolicyManager
    from .handlers.prompt_orchestrator import PromptOrchestrator


# Тип обработчика метода: async-функция, принимающая сообщение и возвращающая outcome
MethodHandler = Callable[[ACPMessage], Awaitable[ProtocolOutcome]]


class MiddlewareFn(Protocol):
    """Протокол middleware для сквозной логики (логирование, метрики, auth-check).

    Middleware применяется в порядке onion pattern: первое в списке — внешнее,
    последнее — ближе к обработчику.
    """

    async def __call__(
        self,
        message: ACPMessage,
        next_handler: MethodHandler,
    ) -> ProtocolOutcome: ...


logger = structlog.get_logger()


class ACPProtocol:
    """Диспетчер ACP-методов и in-memory реализация сессионного протокола.

    Класс принимает валидированные JSON-RPC сообщения и возвращает
    `ProtocolOutcome` для транспортного слоя.

    Пример использования:
        protocol = ACPProtocol()
        outcome = protocol.handle(ACPMessage.request("initialize", {}))
    """

    def __init__(
        self,
        *,
        require_auth: bool = False,
        auth_api_key: str | None = None,
        storage: SessionStorage | None = None,
        agent_orchestrator: AgentOrchestrator | None = None,
        client_rpc_service: ClientRPCService | None = None,
        tool_registry: ToolRegistry | None = None,
        prompt_orchestrator: PromptOrchestrator | None = None,
        middleware: list[MiddlewareFn] | None = None,
    ) -> None:
        """Инициализирует протокол и хранилище сессий.

        Args:
            require_auth: Требовать аутентификацию перед session setup.
            auth_api_key: API ключ для аутентификации.
            storage: Хранилище сессий (по умолчанию InMemoryStorage).
            agent_orchestrator: Оркестратор LLM-агента для обработки prompts (опционально).
            client_rpc_service: Сервис ClientRPC для выполнения инструментов (опционально).
            tool_registry: Реестр инструментов для регистрации и выполнения tools (опционально).
            prompt_orchestrator: Оркестратор prompt-turn (опционально, создаётся лениво).
            middleware: Список middleware функций для сквозной логики (опционально).

        Пример использования:
            protocol = ACPProtocol()
            # или с кастомным хранилищем и агентом:
            from codelab.server.storage import InMemoryStorage
            from codelab.server.agent.orchestrator import AgentOrchestrator
            storage = InMemoryStorage()
            agent = AgentOrchestrator(...)
            protocol = ACPProtocol(storage=storage, agent_orchestrator=agent)
        """

        # Инициализировать хранилище (по умолчанию InMemoryStorage)
        if storage is None:
            from ..storage import InMemoryStorage

            storage = InMemoryStorage()
        self._storage = storage

        # Оркестратор LLM-агента для обработки prompt-turns через агента
        self._agent_orchestrator = agent_orchestrator

        # Сервис ClientRPC для выполнения встроенных инструментов
        self._client_rpc_service = client_rpc_service

        # Реестр инструментов для регистрации и выполнения tools
        self._tool_registry = tool_registry

        # PromptOrchestrator создаётся один раз, если не передан извне
        self._prompt_orchestrator: PromptOrchestrator | None = prompt_orchestrator

        # GlobalPolicyManager для fallback chain в permission checks
        self._global_policy_manager: GlobalPolicyManager | None = None

        # Последние capabilities, согласованные через initialize.
        # Для in-memory demo-сервера это достаточно; по мере роста можно
        # расширить до connection-scoped хранилища.
        self._runtime_capabilities: ClientRuntimeCapabilities | None = None
        # Флаг для сценариев, где агент требует authenticate до session setup.
        self._require_auth = require_auth
        # Локальный API key для production-профиля authenticate (если задан).
        self._auth_api_key = auth_api_key
        # Состояние аутентификации текущего протокольного инстанса.
        self._authenticated = False
        self._auth_methods: list[dict[str, Any]] = [
            {
                "id": "local",
                "name": "Local authentication",
                "description": "Local authentication flow",
                "type": "api_key",
            }
        ]

        # Runtime-реестр futures для permission requests — не персистируется,
        # не входит в SessionState, пересоздаётся при каждом запуске
        self._pending_registry = PendingRequestRegistry()

        # Реестр обработчиков методов — заменяет цепочку if method == "..."
        self._handlers: dict[str, MethodHandler] = {
            "initialize": self._handle_initialize,
            "authenticate": self._handle_authenticate,
            "session/new": self._handle_session_new,
            "session/load": self._handle_session_load,
            "session/list": self._handle_session_list,
            "session/prompt": self._handle_session_prompt,
            "session/cancel": self._handle_session_cancel,
            "session/request_permission_response": self._handle_permission_response_method,
            "session/set_config_option": self._handle_set_config_option,
            "session/set_mode": self._handle_set_mode,
            "ping": self._handle_ping,
            "echo": self._handle_echo,
            "shutdown": self._handle_shutdown,
        }

        # Middleware для сквозной логики (логирование, метрики, auth-check)
        self._middleware: list[MiddlewareFn] = middleware or []

    _config_specs: dict[str, dict[str, Any]] = {
        "mode": {
            "name": "Session Mode",
            "category": "mode",
            "default": "ask",
            "options": [
                {
                    "value": "ask",
                    "name": "Ask",
                    "description": "Request permission before sensitive actions",
                },
                {
                    "value": "code",
                    "name": "Code",
                    "description": "Execute actions without per-step approval",
                },
            ],
        },
        "model": {
            "name": "Model",
            "category": "model",
            "default": "baseline",
            "options": [
                {
                    "value": "baseline",
                    "name": "Baseline",
                    "description": "Balanced speed and quality",
                }
            ],
        },
    }
    _supported_protocol_versions = (1,)
    _supported_stop_reasons = {
        "end_turn",
        "max_tokens",
        "max_turn_requests",
        "refusal",
        "cancelled",
    }
    _supported_tool_kinds = {
        "read",
        "edit",
        "delete",
        "move",
        "search",
        "execute",
        "think",
        "fetch",
        "switch_mode",
        "other",
    }
    # Размер страницы для `session/list`; cursor указывает смещение в этом срезе.
    _session_list_page_size = 50

    async def handle(self, message: ACPMessage) -> ProtocolOutcome:
        """Маршрутизирует входящее сообщение по методу через реестр обработчиков.

        Метод является основной точкой входа для HTTP/WS транспорта.

        Пример использования:
            outcome = protocol.handle(ACPMessage.request("session/list", {}))
        """
        # Если method=None, это response (JSON-RPC 2.0)
        # Маршрутизируем на handle_client_response() вместо отклонения.
        if message.method is None:
            logger.debug(
                "response received, routing to handle_client_response",
                request_id=message.id,
            )
            return await self.handle_client_response(message)

        method = message.method
        handler = self._handlers.get(method)

        if handler is None:
            # Уведомления — игнорируем без ошибки
            if message.is_notification:
                return ProtocolOutcome()
            return ProtocolOutcome(
                response=ACPMessage.error_response(
                    message.id, code=-32601, message=f"Method not found: {method}"
                )
            )

        # Применить middleware в обратном порядке (onion pattern)
        wrapped: MethodHandler = handler
        for mw in reversed(self._middleware):
            # Создаём замыкание для корректного захвата переменных
            next_handler = wrapped

            async def wrapped_with_middleware(
                msg: ACPMessage,
                _mw=mw,
                _next=next_handler,
            ) -> ProtocolOutcome:
                return await _mw(msg, _next)

            wrapped = wrapped_with_middleware

        return await wrapped(message)

    async def complete_active_turn(
        self, session_id: str, *, stop_reason: str = "end_turn"
    ) -> ACPMessage | None:
        """Завершает активный prompt-turn и возвращает финальный response.

        Используется транспортом WS для отложенного ответа на `session/prompt`.

        Пример использования:
            response = await protocol.complete_active_turn("sess_1", stop_reason="end_turn")
        """
        session = await self._storage.load_session(session_id)
        if session is None:
            return None
        return prompt.complete_active_turn(
            session,
            stop_reason=stop_reason,
        )

    async def should_auto_complete_active_turn(self, session_id: str) -> bool:
        """Возвращает `True`, если active turn можно безопасно автозавершить.

        Если turn ожидает permission-response, автозавершение запрещено.

        Пример использования:
            if await protocol.should_auto_complete_active_turn("sess_1"):
                ...
        """
        session = await self._storage.load_session(session_id)
        if session is None or session.active_turn is None:
            return False
        return prompt.should_auto_complete_active_turn(session)

    async def handle_client_response(self, message: ACPMessage) -> ProtocolOutcome:
        """Обрабатывает входящий response от клиента для server-originated requests.

        Сейчас используется для `session/request_permission`, отправленного ранее
        в рамках active prompt-turn.

        Пример использования:
            outcome = await protocol.handle_client_response(client_response)
        """

        if message.id is None:
            return ProtocolOutcome()

        resolved_client_rpc = await self._resolve_pending_client_rpc_response(
            request_id=message.id,
            result=message.result,
            error=message.error.model_dump(exclude_none=True)
            if message.error is not None
            else None,
        )
        if resolved_client_rpc is not None:
            return resolved_client_rpc

        if self._client_rpc_service is not None and self._client_rpc_service.has_pending_request(
            message.id
        ):
            # Пробрасываем response в ClientRPCService для async-ожиданий,
            # используемых tool executors (filesystem/terminal).
            logger.debug(
                "forwarding client response to client_rpc_service",
                request_id=message.id,
                has_error=message.error is not None,
            )
            self._client_rpc_service.handle_response(message.to_dict())
            return ProtocolOutcome()

        if await permissions.consume_cancelled_client_rpc_response(message.id, self._storage):
            # Late response на отмененный agent->client RPC считаем no-op.
            return ProtocolOutcome()

        if await permissions.consume_cancelled_permission_response(message.id, self._storage):
            # Late response на уже отмененный permission-request считаем
            # корректно обработанным no-op, чтобы избежать race-эффектов.
            return ProtocolOutcome()

        resolved = await self._resolve_permission_response(message.id, message.result)
        if resolved is None:
            return ProtocolOutcome()
        return resolved

    async def _resolve_pending_client_rpc_response(
        self,
        *,
        request_id: JsonRpcId,
        result: Any,
        error: dict[str, Any] | None,
    ) -> ProtocolOutcome | None:
        """Обрабатывает response на ожидаемый agent->client fs/* request.

        Пример использования:
            outcome = await protocol._resolve_pending_client_rpc_response(
                request_id="req_1",
                result={"content": "ok"},
                error=None,
            )
        """

        session = await prompt.find_session_by_pending_client_request_id(request_id, self._storage)
        if session is None:
            return None

        return prompt.resolve_pending_client_rpc_response_impl(
            session=session,
            request_id=request_id,
            result=result,
            error=error,
        )

    async def _resolve_permission_response(
        self,
        permission_request_id: JsonRpcId,
        result: Any,
    ) -> ProtocolOutcome | None:
        """Применяет решение по permission-request к активному prompt-turn.

        Пример использования:
            outcome = await protocol._resolve_permission_response(
                "perm_1",
                {"outcome": {"outcome": "selected", "optionId": "allow_once"}},
            )
        """

        session = await permissions.find_session_by_permission_request_id(
            permission_request_id, self._storage
        )
        if session is None:
            return None

        return prompt.resolve_permission_response_impl(
            session=session,
            permission_request_id=permission_request_id,
            result=result,
        )

    async def _get_session_for_runtime(self, session_id: str) -> SessionState | None:
        """Возвращает сессию из storage по id.

        Пример использования:
            session = await protocol._get_session_for_runtime("sess_1")
        """
        return await self._storage.load_session(session_id)

    async def cancel_active_turns_on_disconnect(self) -> int:
        """Отменяет все активные turn в рамках текущего протокольного инстанса.

        Используется транспортом при разрыве соединения клиента. Метод
        обеспечивает ACP-инвариант остановки in-flight turn и освобождение
        внутренних ожиданий без отправки сетевых сообщений.

        Returns:
            Количество сессий, в которых активный turn был отменен.
        """
        cancelled_count = 0
        cursor = None
        while True:
            sessions, cursor = await self._storage.list_sessions(cursor=cursor, limit=100)
            for session_state in sessions:
                if session_state.active_turn is None:
                    continue

                await prompt.session_cancel(
                    request_id=None,
                    params={"sessionId": session_state.session_id},
                    storage=self._storage,
                )
                cancelled_count += 1

                try:
                    await self._storage.save_session(session_state)
                except Exception:
                    # Ошибка персистентности не должна блокировать cleanup при disconnect.
                    continue

            if cursor is None:
                break

        return cancelled_count

    async def _get_prompt_orchestrator(self) -> PromptOrchestrator | None:
        """Получить или создать PromptOrchestrator.

        Если передан явно в конструктор — использует его.
        Если нет — создаёт лениво при первом обращении.

        Returns:
            PromptOrchestrator или None, если tool_registry не настроен.
        """
        if self._prompt_orchestrator is not None:
            return self._prompt_orchestrator

        if self._tool_registry is None:
            return None

        self._prompt_orchestrator = prompt.create_prompt_orchestrator(
            tool_registry=self._tool_registry,
            client_rpc_service=self._client_rpc_service,
            global_policy_manager=self._global_policy_manager,
        )
        return self._prompt_orchestrator

    async def initialize_global_policy_manager(self) -> None:
        """Инициализировать GlobalPolicyManager для fallback на global policies.

        Graceful degradation: если инициализация не удалась, продолжаем без global policies.

        Пример использования:
            await protocol.initialize_global_policy_manager()
        """
        try:
            from .handlers.global_policy_manager import GlobalPolicyManager

            self._global_policy_manager = await GlobalPolicyManager.get_instance()
            await self._global_policy_manager.initialize()

            # Сбросить кэш, чтобы оркестратор пересоздался с новым policy manager
            self._prompt_orchestrator = None

            logger.info("GlobalPolicyManager initialized successfully")
        except Exception as e:
            logger.warning(
                "Failed to initialize GlobalPolicyManager, continuing without global policies",
                error=str(e),
                exc_info=True,
            )
            self._global_policy_manager = None

    # -----------------------------------------------------------------------
    # Обработчики методов протокола (реестр _handlers)
    # -----------------------------------------------------------------------

    async def _handle_initialize(self, message: ACPMessage) -> ProtocolOutcome:
        """Обрабатывает метод initialize."""
        params = message.params or {}
        response = auth.initialize(
            message.id,
            params,
            self._supported_protocol_versions,
            self._require_auth,
            self._auth_methods,
        )
        # Сохраняем согласованные runtime-возможности клиента для feature-gate.
        client_capabilities = params.get("clientCapabilities")
        if isinstance(client_capabilities, dict):
            self._runtime_capabilities = auth.parse_client_runtime_capabilities(
                client_capabilities
            )

        # Инициализируем GlobalPolicyManager для fallback chain
        if self._global_policy_manager is None:
            logger.debug("GlobalPolicyManager will be initialized on demand")

        return ProtocolOutcome(response=response)

    async def _handle_authenticate(self, message: ACPMessage) -> ProtocolOutcome:
        """Обрабатывает метод authenticate."""
        params = message.params or {}
        response, authenticated = auth.authenticate(
            message.id,
            params,
            self._require_auth,
            self._auth_api_key,
            self._auth_methods,
        )
        self._authenticated = authenticated
        return ProtocolOutcome(response=response)

    async def _handle_session_new(self, message: ACPMessage) -> ProtocolOutcome:
        """Обрабатывает метод session/new."""
        params = message.params or {}
        response_msg = session.session_new(
            message.id,
            params,
            self._require_auth,
            self._authenticated,
            self._config_specs,
            self._auth_methods,
            self._runtime_capabilities,
        )

        # Если создание прошло успешно, сохраняем в storage и кэш
        if response_msg.result is not None:
            session_id = response_msg.result.get("sessionId")
            if isinstance(session_id, str):
                config_values = {
                    config_id: str(spec["default"])
                    for config_id, spec in self._config_specs.items()
                }
                session_state = SessionFactory.create_session(
                    cwd=params.get("cwd", ""),
                    mcp_servers=params.get("mcpServers", []),
                    config_values=config_values,
                    available_commands=session.build_default_commands(),
                    runtime_capabilities=self._runtime_capabilities,
                    session_id=session_id,
                )

                # Единая точка инициализации MCP серверов
                await self._setup_mcp_if_needed(session_state, params)

                await self._storage.save_session(session_state)

        return ProtocolOutcome(response=response_msg)

    async def _handle_session_load(self, message: ACPMessage) -> ProtocolOutcome:
        """Обрабатывает метод session/load."""
        params = message.params or {}
        session_id = params.get("sessionId")
        if isinstance(session_id, str):
            session_obj = await self._get_session_for_runtime(session_id)
            if session_obj is not None:
                session_obj.runtime_capabilities = self._runtime_capabilities

                # Единая точка инициализации MCP серверов
                await self._setup_mcp_if_needed(session_obj, params)

                # Обработка orphaned permission requests после перезапуска сервера.
                if session_obj.active_turn and session_obj.active_turn.permission_request_id:
                    perm_req_id = session_obj.active_turn.permission_request_id
                    if not self._pending_registry.has(perm_req_id):
                        logger.warning(
                            "session_loaded_with_orphaned_permission_request",
                            session_id=session_id,
                            permission_request_id=perm_req_id,
                        )
                        session_obj.active_turn = None
                        await self._storage.save_session(session_obj)

        return await session.session_load(
            message.id,
            params,
            self._require_auth,
            self._authenticated,
            self._config_specs,
            self._auth_methods,
            self._storage,
        )

    async def _handle_session_list(self, message: ACPMessage) -> ProtocolOutcome:
        """Обрабатывает метод session/list."""
        params = message.params or {}
        response = await session.session_list(
            message.id,
            params,
            self._storage,
            self._session_list_page_size,
        )
        return ProtocolOutcome(response=response)

    async def _handle_session_prompt(self, message: ACPMessage) -> ProtocolOutcome:
        """Обрабатывает метод session/prompt."""
        params = message.params or {}
        return await prompt.session_prompt(
            message.id,
            params,
            self._storage,
            self._config_specs,
            agent_orchestrator=self._agent_orchestrator,
            tool_registry=self._tool_registry,
            client_rpc_service=self._client_rpc_service,
            global_manager=self._global_policy_manager,
        )

    async def _handle_session_cancel(self, message: ACPMessage) -> ProtocolOutcome:
        """Обрабатывает метод session/cancel."""
        params = message.params or {}
        return await prompt.session_cancel(
            message.id,
            params,
            self._storage,
        )

    async def _handle_permission_response_method(self, message: ACPMessage) -> ProtocolOutcome:
        """Обрабатывает метод session/request_permission_response."""
        if message.id is None:
            return ProtocolOutcome(response=ACPMessage.error_response(
                None, code=-32600, message="Invalid Request: id is required"
            ))
        params = message.params or {}
        return await self._handle_permission_response(
            message.id,
            params,
        )

    async def _handle_set_config_option(self, message: ACPMessage) -> ProtocolOutcome:
        """Обрабатывает метод session/set_config_option."""
        params = message.params or {}
        return await config.session_set_config_option(
            message.id,
            params,
            self._storage,
            self._config_specs,
        )

    async def _handle_set_mode(self, message: ACPMessage) -> ProtocolOutcome:
        """Обрабатывает метод session/set_mode."""
        params = message.params or {}
        return await config.session_set_mode(
            message.id,
            params,
            self._storage,
            self._config_specs,
        )

    async def _handle_ping(self, message: ACPMessage) -> ProtocolOutcome:
        """Обрабатывает метод ping."""
        return ProtocolOutcome(response=legacy.ping(message.id))

    async def _handle_echo(self, message: ACPMessage) -> ProtocolOutcome:
        """Обрабатывает метод echo."""
        params = message.params or {}
        return ProtocolOutcome(response=legacy.echo(message.id, params))

    async def _handle_shutdown(self, message: ACPMessage) -> ProtocolOutcome:
        """Обрабатывает метод shutdown."""
        return ProtocolOutcome(response=legacy.shutdown(message.id))

    # -----------------------------------------------------------------------
    # Вспомогательные методы
    # -----------------------------------------------------------------------

    async def _setup_mcp_if_needed(
        self,
        session_state: SessionState,
        params: dict[str, Any],
    ) -> None:
        """Единая точка инициализации MCP серверов — не дублируется.

        Вызывается из session/new и session/load.
        """
        mcp_servers = params.get("mcpServers", [])
        if mcp_servers and isinstance(mcp_servers, list):
            await self._initialize_mcp_servers(session_state, mcp_servers)

    async def _handle_permission_response(
        self,
        request_id: JsonRpcId,
        params: dict[str, Any],
    ) -> ProtocolOutcome:
        """Обрабатывает response на session/request_permission от клиента.
        
        Логика:
        1. Найти сессию с активным permission request
        2. Проверить, не был ли request отменен (late response handling)
        3. Извлечь решение из response
        4. Обновить policy если нужно (для allow_always/reject_always)
        5. Обновить tool call status и отправить notifications
        
        Args:
            request_id: ID permission request
            params: Параметры (sessionId, result с outcome и optionId)
        
        Returns:
            ProtocolOutcome с response и notifications
        """
        session_id = params.get("sessionId", "")
        
        # Найти сессию по permission request ID через storage
        session = await permissions.find_session_by_permission_request_id(
            request_id, self._storage
        )

        if session is None:
            # Проверить, был ли request отменен (late response handling)
            cancelled_session = await permissions.find_session_with_cancelled_permission(
                request_id, self._storage
            )
            if cancelled_session is not None:
                logger.debug(
                    "ignoring late response on cancelled permission request",
                    request_id=request_id,
                    session_id=cancelled_session.session_id,
                )
                # Удалить из tombstone
                cancelled_session.cancelled_permission_requests.discard(request_id)
                await self._storage.save_session(cancelled_session)
                return ProtocolOutcome(response=ACPMessage.response(request_id, {}))

            # Неизвестный request
            logger.warning(
                "permission response for unknown request",
                request_id=request_id,
            )
            return ProtocolOutcome(
                response=ACPMessage.error_response(
                    request_id,
                    code=-32603,
                    message="Unknown permission request",
                )
            )

        # Получить PermissionManager из handlers (инициализируется в prompt.py)
        from .handlers.permission_manager import PermissionManager

        # Создать временный PermissionManager для извлечения данных
        permission_manager = PermissionManager()

        result = params.get("result", {})
        
        # Извлечь решение из response
        outcome = permission_manager.extract_permission_outcome(result)
        option_id = permission_manager.extract_permission_option_id(result)

        if outcome != "selected" or option_id is None:
            logger.warning(
                "invalid permission response format",
                request_id=request_id,
                session_id=session_id,
                outcome=outcome,
            )
            return ProtocolOutcome(
                response=ACPMessage.error_response(
                    request_id,
                    code=-32603,
                    message="Invalid permission response",
                )
            )

        # Получить tool_call_id из active_turn
        if session.active_turn is None or session.active_turn.permission_tool_call_id is None:
            logger.warning(
                "no permission tool call in active turn",
                request_id=request_id,
                session_id=session_id,
            )
            return ProtocolOutcome(
                response=ACPMessage.error_response(
                    request_id,
                    code=-32603,
                    message="No pending tool call",
                )
            )

        tool_call_id = session.active_turn.permission_tool_call_id

        # Сохранить policy если нужно (для allow_always/reject_always)
        acceptance_updates = permission_manager.build_permission_acceptance_updates(
            session,
            session_id,
            tool_call_id,
            option_id,
        )

        logger.debug(
            "permission response handled",
            request_id=request_id,
            session_id=session_id,
            option_id=option_id,
            tool_call_id=tool_call_id,
        )

        return ProtocolOutcome(
            response=ACPMessage.response(request_id, {}),
            notifications=acceptance_updates,
        )

    async def execute_pending_tool(
        self,
        session_id: str,
        tool_call_id: str,
    ) -> LLMLoopResult:
        """Выполняет pending tool после permission approval и продолжает LLM loop.
        
        Вызывается из http_server.py после того как permission был одобрен.
        Создаёт PromptOrchestrator и делегирует ему выполнение.
        Согласно ACP протоколу (05-Prompt Turn.md, Step 6), после выполнения
        инструмента результат передаётся LLM для продолжения диалога.
        
        Args:
            session_id: ID сессии
            tool_call_id: ID tool call для выполнения
            
        Returns:
            LLMLoopResult с notifications, stop_reason и pending_permission флагом
        """
        session = await self._storage.load_session(session_id)
        if session is None:
            logger.error(
                "session not found for pending tool execution",
                session_id=session_id,
                tool_call_id=tool_call_id,
            )
            return LLMLoopResult(notifications=[], stop_reason="end_turn")
        
        # Проверить наличие agent_orchestrator для LLM loop
        if self._agent_orchestrator is None:
            logger.error(
                "agent_orchestrator not configured for LLM loop",
                session_id=session_id,
                tool_call_id=tool_call_id,
            )
            return LLMLoopResult(notifications=[], stop_reason="end_turn")

        # Получить или создать PromptOrchestrator (переиспользуется)
        orchestrator = await self._get_prompt_orchestrator()
        if orchestrator is None:
            logger.error(
                "orchestrator not configured for pending tool execution",
                session_id=session_id,
                tool_call_id=tool_call_id,
            )
            return LLMLoopResult(notifications=[], stop_reason="end_turn")

        return await orchestrator.execute_pending_tool(
            session=session,
            session_id=session_id,
            tool_call_id=tool_call_id,
            agent_orchestrator=self._agent_orchestrator,
        )

    async def _initialize_mcp_servers(
        self,
        session_state: SessionState,
        mcp_servers: list[dict[str, Any]],
    ) -> None:
        """Инициализирует MCP серверы для сессии.
        
        Создаёт MCPManager, подключается к каждому MCP серверу,
        получает инструменты и регистрирует их в ToolRegistry.
        
        Args:
            session_state: Состояние сессии для сохранения MCPManager.
            mcp_servers: Список конфигураций MCP серверов из параметров session/new.
        
        Примечание:
            При ошибке подключения к серверу, ошибка логируется,
            но не прерывает инициализацию других серверов (graceful degradation).
        """
        if not mcp_servers:
            return
        
        # Создаём MCPManager для этой сессии
        mcp_manager = MCPManager(session_state.session_id)
        session_state.mcp_manager = mcp_manager
        
        for server_config_dict in mcp_servers:
            # Пропускаем невалидные конфигурации
            if not isinstance(server_config_dict, dict):
                logger.warning(
                    "invalid mcp server config, skipping",
                    session_id=session_state.session_id,
                    config=server_config_dict,
                )
                continue
            
            # Проверяем обязательные поля
            name = server_config_dict.get("name")
            command = server_config_dict.get("command")
            if not name or not command:
                logger.warning(
                    "mcp server config missing name or command",
                    session_id=session_state.session_id,
                    config=server_config_dict,
                )
                continue
            
            try:
                # Преобразуем dict в MCPServerConfig
                config = MCPServerConfig(
                    name=name,
                    command=command,
                    args=server_config_dict.get("args", []),
                    env=server_config_dict.get("env", []),
                )
                
                # Добавляем сервер и получаем список инструментов
                # MCP инструменты НЕ регистрируются в глобальном ToolRegistry,
                # т.к. они привязаны к сессии. Доступ к ним через session_state.mcp_manager.
                tool_definitions = await mcp_manager.add_server(config)
                
                logger.info(
                    "mcp server initialized",
                    session_id=session_state.session_id,
                    server=name,
                    tools_count=len(tool_definitions),
                    tool_names=[td.name for td in tool_definitions],
                )
                
            except MCPManagerError as e:
                # Graceful degradation: логируем ошибку, но продолжаем
                logger.error(
                    "failed to initialize mcp server",
                    session_id=session_state.session_id,
                    server=name,
                    error=str(e),
                )
            except Exception as e:
                # Непредвиденные ошибки также логируем без прерывания
                logger.exception(
                    "unexpected error initializing mcp server",
                    session_id=session_state.session_id,
                    server=name,
                    error=str(e),
                )
