"""Главный оркестратор обработки prompt-turn через Pipeline Pattern."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from ...client_rpc.service import ClientRPCService
from ...messages import ACPMessage, JsonRpcId
from ...rpc_holder import ClientRPCServiceHolder
from ...storage import SessionStorage
from ...tools.base import ToolRegistry
from ..state import LLMLoopResult, ProtocolOutcome, SessionState
from .client_rpc_handler import ClientRPCHandler
from .permission_manager import PermissionManager
from .pipeline import (
    LLMLoopStage,
    PromptContext,
    PromptPipeline,
)
from .plan_builder import PlanBuilder
from .slash_commands import CommandRegistry
from .state_manager import StateManager
from .tool_call_handler import ToolCallHandler
from .turn_lifecycle_manager import TurnLifecycleManager

if TYPE_CHECKING:
    from ...agent.orchestrator import AgentOrchestrator
    from .global_policy_manager import GlobalPolicyManager

logger = structlog.get_logger()


class PromptOrchestrator:
    """Фабрика и точка входа для обработки prompt-turn через Pipeline.

    Собирает все стадии в PromptPipeline и предоставляет методы:
    - handle_prompt: основная обработка prompt-turn
    - handle_cancel: отмена активного turn
    - handle_permission_response: обработка ответа на permission request
    - handle_pending_client_rpc_response: обработка ответа на client RPC
    - execute_pending_tool: выполнение tool после permission approval
    """

    def __init__(
        self,
        state_manager: StateManager,
        plan_builder: PlanBuilder,
        turn_lifecycle_manager: TurnLifecycleManager,
        tool_call_handler: ToolCallHandler,
        permission_manager: PermissionManager,
        client_rpc_handler: ClientRPCHandler,
        tool_registry: ToolRegistry,
        llm_loop_stage: LLMLoopStage,
        command_registry: CommandRegistry,
        pipeline: PromptPipeline,
        client_rpc_service_holder: ClientRPCServiceHolder | None = None,
        client_rpc_service: ClientRPCService | None = None,  # backward compatibility
        global_policy_manager: GlobalPolicyManager | None = None,
    ):
        self.state_manager = state_manager
        self.plan_builder = plan_builder
        self.turn_lifecycle_manager = turn_lifecycle_manager
        self.tool_call_handler = tool_call_handler
        self.permission_manager = permission_manager
        self.client_rpc_handler = client_rpc_handler
        self.tool_registry = tool_registry
        self.global_policy_manager = global_policy_manager
        self._tools_registered = False

        # Поддерживаем оба способа передачи сервиса
        if client_rpc_service_holder is not None:
            self.client_rpc_service_holder = client_rpc_service_holder
        elif client_rpc_service is not None:
            # backward compatibility: создаём holder с уже установленным сервисом
            self.client_rpc_service_holder = ClientRPCServiceHolder()
            self.client_rpc_service_holder.service = client_rpc_service
        else:
            self.client_rpc_service_holder = None

        # Регистрация plan tool сразу
        from ...tools.definitions import PlanToolDefinitions
        from ...tools.executors.plan_executor import PlanToolExecutor

        PlanToolDefinitions.register_all(tool_registry, PlanToolExecutor())

        self._llm_loop_stage = llm_loop_stage
        self._command_registry = command_registry
        self._pipeline = pipeline

    @property
    def client_rpc_service(self) -> ClientRPCService | None:
        """Возвращает ClientRPCService из holder."""
        if self.client_rpc_service_holder is not None:
            return self.client_rpc_service_holder.service
        return None

    def _ensure_tools_registered(self) -> None:
        """Лениво регистрирует tool executors при первом использовании."""
        if self._tools_registered:
            return

        if self.client_rpc_service is not None:
            from ...tools.definitions import (
                FileSystemToolDefinitions,
                TerminalToolDefinitions,
            )
            from ...tools.executors.filesystem_executor import FileSystemToolExecutor
            from ...tools.executors.terminal_executor import TerminalToolExecutor
            from ...tools.integrations.client_rpc_bridge import ClientRPCBridge
            from ...tools.integrations.permission_checker import PermissionChecker

            bridge = ClientRPCBridge(self.client_rpc_service)
            checker = PermissionChecker(self.permission_manager)
            FileSystemToolDefinitions.register_all(self.tool_registry, FileSystemToolExecutor(bridge, checker))
            TerminalToolDefinitions.register_all(self.tool_registry, TerminalToolExecutor(bridge, checker))
            logger.debug("PromptOrchestrator registered tool executors", tools_registered=len(self.tool_registry.get_available_tools("")))

        self._tools_registered = True

    @property
    def command_registry(self) -> CommandRegistry:
        return self._command_registry

    async def handle_prompt(
        self,
        request_id: JsonRpcId | None,
        params: dict[str, Any],
        session: SessionState,
        storage: SessionStorage,
        agent_orchestrator: AgentOrchestrator,
    ) -> ProtocolOutcome:
        """Обрабатывает session/prompt request.

        Оркестрирует весь цикл обработки промпта:
        1. Инициализация active turn
        2. Извлечение текста из prompt blocks
        3. Обработка через LLM-агента
        4. Построение и отправка notifications
        5. Управление tool calls, permissions, client RPC
        6. Финализация turn

        Args:
            request_id: ID входящего request
            params: Параметры (должны содержать prompt array)
            session: Состояние сессии
            storage: Хранилище сессий
            agent_orchestrator: LLM-агент для обработки

        Returns:
            ProtocolOutcome с notifications и response
        """
        # Лениво регистрируем tool executors если service стал доступен
        self._ensure_tools_registered()

        session_id = session.session_id
        prompt = params.get("prompt", [])

        # Подготовка состояния сессии до запуска pipeline
        text_preview = _extract_text_preview(prompt)
        prompt_text = _extract_full_text(prompt)
        self.state_manager.update_session_title(session, text_preview)
        self.state_manager.add_user_message(session, prompt)
        for block in prompt:
            self.state_manager.add_event(
                session,
                {"type": "session_update", "update": {"sessionUpdate": "user_message_chunk", "content": block}},
            )
        self.state_manager.update_session_timestamp(session)

        context = PromptContext(
            session_id=session_id,
            session=session,
            request_id=request_id,
            params=params,
            raw_text=prompt_text,
        )
        context.meta["agent_orchestrator"] = agent_orchestrator
        context.notifications.append(_build_ack_notification(session_id, text_preview))

        result = await self._pipeline.run(context)

        # Pipeline-ошибка: закрыть turn если он был открыт
        if result.error_response is not None:
            if session.active_turn is not None:
                self.turn_lifecycle_manager.finalize_turn(session, "end_turn")
                self.turn_lifecycle_manager.clear_active_turn(session)
            # Не отправляем notifications при ошибке валидации
            return ProtocolOutcome(response=result.error_response, notifications=[])

        # Добавить session info независимо от того, завершён turn или отложен
        summary = self.state_manager.get_session_summary(session)
        result.notifications.append(_build_session_info_notification(session_id, summary))
        self.state_manager.add_event(
            session,
            {
                "type": "session_update",
                "update": {"sessionUpdate": "session_info", "title": summary.get("title"), "updated_at": summary.get("updated_at")},
            },
        )

        # Turn отложен — ожидает разрешения пользователя
        if result.pending_permission:
            logger.debug(
                "turn deferred, awaiting permission response",
                session_id=session_id,
                permission_request_id=(session.active_turn.permission_request_id if session.active_turn else None),
            )
            return ProtocolOutcome(notifications=result.notifications)

        logger.debug(
            "prompt handling completed via pipeline",
            session_id=session_id,
            stop_reason=result.stop_reason,
            notifications_count=len(result.notifications),
        )

        response = (
            ACPMessage.response(request_id, {"stopReason": result.stop_reason})
            if request_id is not None
            else None
        )
        return ProtocolOutcome(response=response, notifications=result.notifications)

    def handle_cancel(
        self,
        request_id: JsonRpcId | None,
        params: dict[str, Any],
        session: SessionState,
        sessions: dict[str, SessionState] | None = None,
    ) -> ProtocolOutcome:
        """Обрабатывает session/cancel request.

        Логика:
        1. Найти сессию если нужна по ID
        2. Если есть active turn, установить cancel_requested флаг
        3. Отменить все активные tool calls
        4. Отметить cancelled permission requests
        5. Отметить cancelled client RPC requests
        6. Завершить turn с stop_reason='cancel'

        Args:
            request_id: ID cancel request
            params: Параметры (sessionId)
            session: Состояние сессии (может быть найдена по sessionId)
            sessions: Deprecated, не используется

        Returns:
            ProtocolOutcome с notifications об отмене
        """
        session_id = params.get("sessionId", session.session_id)
        notifications: list[ACPMessage] = []

        if session.active_turn is None:
            logger.debug("cancel request with no active turn", session_id=session_id)
            return ProtocolOutcome(response=None, notifications=[])

        self.turn_lifecycle_manager.mark_cancel_requested(session)

        cancel_messages = self.tool_call_handler.cancel_active_tools(session, session_id)
        notifications.extend(cancel_messages)

        if session.active_turn.permission_request_id is not None:
            session.cancelled_permission_requests.add(session.active_turn.permission_request_id)

        if session.active_turn.pending_client_request is not None:
            session.cancelled_client_rpc_requests.add(session.active_turn.pending_client_request.request_id)

        if self.client_rpc_service is not None:
            cancelled_rpc_count = self.client_rpc_service.cancel_all_pending_requests(reason="session/cancel requested")
            if cancelled_rpc_count > 0:
                logger.debug("cancelled pending RPC requests", session_id=session_id, cancelled_count=cancelled_rpc_count)

        self.turn_lifecycle_manager.finalize_turn(session, "cancelled")

        # Сохраняем prompt response до очистки active_turn
        if session.active_turn is not None and session.active_turn.prompt_request_id is not None:
            session.pending_prompt_response = {
                "request_id": session.active_turn.prompt_request_id,
                "stop_reason": "cancelled",
            }

        self.turn_lifecycle_manager.clear_active_turn(session)

        logger.debug("cancel request handled", session_id=session_id, notifications_count=len(notifications))
        return ProtocolOutcome(response=None, notifications=notifications)

    def handle_pending_client_rpc_response(
        self,
        session: SessionState,
        session_id: str,
        kind: str,
        result: Any,
        error: dict[str, Any] | None,
    ) -> ProtocolOutcome:
        """Обрабатывает response на pending client RPC request."""
        notifications: list[ACPMessage] = []
        updates = self.client_rpc_handler.handle_pending_response(session, session_id, kind, result, error)
        notifications.extend(updates)
        logger.debug("client RPC response handled", session_id=session_id, kind=kind, has_error=error is not None)
        return ProtocolOutcome(response=None, notifications=notifications)

    def handle_permission_response(
        self,
        session: SessionState,
        session_id: str,
        permission_request_id: JsonRpcId,
        result: Any,
    ) -> ProtocolOutcome:
        """Обрабатывает response на permission request."""
        notifications: list[ACPMessage] = []

        if permission_request_id in session.cancelled_permission_requests:
            logger.debug("ignoring response to cancelled permission request", session_id=session_id, request_id=permission_request_id)
            return ProtocolOutcome(response=None, notifications=[])

        outcome = self.permission_manager.extract_permission_outcome(result)
        option_id = self.permission_manager.extract_permission_option_id(result)

        if outcome != "selected" or option_id is None:
            logger.warning("invalid permission response", session_id=session_id, outcome=outcome)
            return ProtocolOutcome(response=None, notifications=[])

        if session.active_turn is None or session.active_turn.permission_tool_call_id is None:
            logger.warning("no permission tool call in active turn", session_id=session_id)
            return ProtocolOutcome(response=None, notifications=[])

        tool_call_id = session.active_turn.permission_tool_call_id
        acceptance_updates = self.permission_manager.build_permission_acceptance_updates(
            session, session_id, tool_call_id, option_id
        )
        notifications.extend(acceptance_updates)

        logger.debug("permission response handled", session_id=session_id, option_id=option_id)
        return ProtocolOutcome(response=None, notifications=notifications)

    async def execute_pending_tool(
        self,
        session: SessionState,
        session_id: str,
        tool_call_id: str,
        agent_orchestrator: AgentOrchestrator,
    ) -> LLMLoopResult:
        """Выполняет pending tool после permission approval и продолжает LLM loop."""
        return await self._llm_loop_stage.execute_pending_tool(
            session=session,
            session_id=session_id,
            tool_call_id=tool_call_id,
            agent_orchestrator=agent_orchestrator,
        )


# ── module-level helpers ──────────────────────────────────────────────────────

def _extract_text_preview(prompt: list[dict[str, Any]]) -> str:
    if not isinstance(prompt, list):
        return "Prompt received"
    for block in prompt:
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            text = block["text"]
            return text if text else "Prompt received"
    return "Prompt received"


def _extract_full_text(prompt: list[dict[str, Any]]) -> str:
    if not isinstance(prompt, list):
        return ""
    return "\n".join(
        block["text"]
        for block in prompt
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
    )


def _build_ack_notification(session_id: str, text_preview: str) -> ACPMessage:
    return ACPMessage.notification(
        "session/update",
        {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": f"Processing prompt: {text_preview[:80]}"},
            },
        },
    )


def _build_session_info_notification(session_id: str, summary: dict[str, Any]) -> ACPMessage:
    return ACPMessage.notification(
        "session/update",
        {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "session_info",
                "title": summary.get("title"),
                "updated_at": summary.get("updated_at"),
            },
        },
    )
