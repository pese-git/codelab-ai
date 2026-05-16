"""Стадия основного цикла LLM и выполнения tool calls."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, cast

import structlog

from codelab.server.messages import ACPMessage
from codelab.server.protocol.content.extractor import ContentExtractor
from codelab.server.protocol.content.formatter import ContentFormatter
from codelab.server.protocol.content.validator import ContentValidator
from codelab.server.protocol.handlers.permission_manager import PermissionManager
from codelab.server.protocol.handlers.plan_builder import PlanBuilder
from codelab.server.protocol.handlers.replay_manager import ReplayManager
from codelab.server.protocol.handlers.state_manager import StateManager
from codelab.server.protocol.handlers.tool_call_handler import ToolCallHandler
from codelab.server.protocol.state import LLMLoopResult, SessionState, ToolResult
from codelab.server.tools.base import ToolRegistry

from ..base import PromptStage
from ..context import PromptContext

if TYPE_CHECKING:
    from codelab.server.agent.orchestrator import AgentOrchestrator
    from codelab.server.protocol.handlers.global_policy_manager import GlobalPolicyManager

logger = structlog.get_logger()


class LLMLoopStage(PromptStage):
    """Основной цикл взаимодействия с LLM и выполнения tool calls."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        tool_call_handler: ToolCallHandler,
        permission_manager: PermissionManager,
        state_manager: StateManager,
        plan_builder: PlanBuilder,
        global_policy_manager: GlobalPolicyManager | None = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._tool_call_handler = tool_call_handler
        self._permission_manager = permission_manager
        self._state_manager = state_manager
        self._plan_builder = plan_builder
        self._global_policy_manager = global_policy_manager

        self._content_extractor = ContentExtractor()
        self._content_validator = ContentValidator()
        self._content_formatter = ContentFormatter()
        self._replay_manager = ReplayManager()

    async def process(self, context: PromptContext) -> PromptContext:
        agent_orchestrator: AgentOrchestrator | None = context.meta.get("agent_orchestrator")
        if agent_orchestrator is None:
            context.error_response = ACPMessage.error_response(
                context.request_id,
                code=-32603,
                message="Agent orchestrator not configured",
            )
            context.should_stop = True
            return context

        result = await self.run_loop(
            session=context.session,
            session_id=context.session_id,
            agent_orchestrator=agent_orchestrator,
            initial_prompt_text=context.raw_text,
        )

        context.notifications.extend(result.notifications)
        context.stop_reason = result.stop_reason or "end_turn"
        context.pending_permission = result.pending_permission

        if result.pending_permission:
            context.should_stop = True  # pipeline приостанавливается, turn остаётся открытым

        return context

    async def run_loop(
        self,
        session: SessionState,
        session_id: str,
        agent_orchestrator: AgentOrchestrator,
        initial_prompt_text: str | None = None,
        tool_results: list[ToolResult] | None = None,
    ) -> LLMLoopResult:
        """Запустить LLM loop. Используется как из process(), так и из execute_pending_tool."""
        return await self._run_llm_loop(
            session=session,
            session_id=session_id,
            agent_orchestrator=agent_orchestrator,
            initial_prompt_text=initial_prompt_text,
            tool_results=tool_results,
        )

    async def execute_pending_tool(
        self,
        session: SessionState,
        session_id: str,
        tool_call_id: str,
        agent_orchestrator: AgentOrchestrator,
    ) -> LLMLoopResult:
        """Выполняет pending tool после permission approval и продолжает LLM loop."""
        notifications: list[ACPMessage] = []
        tool_result: ToolResult | None = None

        tool_call_state = session.tool_calls.get(tool_call_id)
        if tool_call_state is None:
            logger.error(
                "tool_call_state not found for pending execution",
                session_id=session_id,
                tool_call_id=tool_call_id,
            )
            return LLMLoopResult(notifications=notifications, stop_reason="end_turn")

        tool_name = tool_call_state.tool_name
        tool_arguments = tool_call_state.tool_arguments
        tool_call_id_from_llm = tool_call_state.tool_call_id_from_llm

        if tool_name is None:
            logger.error(
                "tool_name not found in tool_call_state",
                session_id=session_id,
                tool_call_id=tool_call_id,
            )
            return LLMLoopResult(notifications=notifications, stop_reason="end_turn")

        logger.info(
            "executing pending tool after permission approval",
            session_id=session_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        )

        try:
            result = await self._tool_registry.execute_tool(
                session_id, tool_name, tool_arguments, session=session
            )

            extracted_content = await self._content_extractor.extract_from_result(
                tool_call_id, result
            )
            tool_call_state.result_content = extracted_content.content_items

            provider_raw = session.config_values.get("llm_provider", "openai")
            provider = cast(Literal["openai", "anthropic"], provider_raw)
            self._content_formatter.format_for_llm(extracted_content, provider=provider)

            if result.success:
                completed_content = [
                    {"type": "content", "content": {"type": "text", "text": result.output or "Tool executed successfully"}}
                ]
                self._tool_call_handler.update_tool_call_status(
                    session, tool_call_id, "completed", content=completed_content
                )
                notifications.append(
                    self._tool_call_handler.build_tool_update_notification(
                        session_id=session_id,
                        tool_call_id=tool_call_id,
                        status="completed",
                        content=completed_content,
                    )
                )
                self._replay_manager.save_tool_call_update(
                    session=session, tool_call_id=tool_call_id, status="completed", content=completed_content
                )
                tool_result = ToolResult(
                    tool_call_id=tool_call_id_from_llm or tool_call_id,
                    tool_name=tool_name,
                    success=True,
                    output=result.output,
                )
            else:
                error_content = [
                    {"type": "content", "content": {"type": "text", "text": result.error or "Tool execution failed"}}
                ]
                self._tool_call_handler.update_tool_call_status(
                    session, tool_call_id, "failed", content=error_content
                )
                notifications.append(
                    self._tool_call_handler.build_tool_update_notification(
                        session_id=session_id,
                        tool_call_id=tool_call_id,
                        status="failed",
                        content=error_content,
                    )
                )
                self._replay_manager.save_tool_call_update(
                    session=session, tool_call_id=tool_call_id, status="failed", content=error_content
                )
                tool_result = ToolResult(
                    tool_call_id=tool_call_id_from_llm or tool_call_id,
                    tool_name=tool_name,
                    success=False,
                    error=result.error,
                )

        except Exception as exc:
            logger.error(
                "tool execution failed with exception",
                session_id=session_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                error=str(exc),
                exc_info=True,
            )
            error_content = [
                {"type": "content", "content": {"type": "text", "text": f"Tool execution error: {exc}"}}
            ]
            self._tool_call_handler.update_tool_call_status(
                session, tool_call_id, "failed", content=error_content
            )
            notifications.append(
                self._tool_call_handler.build_tool_update_notification(
                    session_id=session_id, tool_call_id=tool_call_id, status="failed", content=error_content
                )
            )
            self._replay_manager.save_tool_call_update(
                session=session, tool_call_id=tool_call_id, status="failed", content=error_content
            )
            tool_result = ToolResult(
                tool_call_id=tool_call_id_from_llm or tool_call_id,
                tool_name=tool_name,
                success=False,
                error=str(exc),
            )

        if tool_result is not None:
            llm_loop_result = await self._run_llm_loop(
                session=session,
                session_id=session_id,
                agent_orchestrator=agent_orchestrator,
                initial_prompt_text="",
                tool_results=[tool_result],
            )
            return LLMLoopResult(
                notifications=notifications + llm_loop_result.notifications,
                stop_reason=llm_loop_result.stop_reason,
                final_text=llm_loop_result.final_text,
                pending_permission=llm_loop_result.pending_permission,
                pending_tool_calls=llm_loop_result.pending_tool_calls,
                tool_results=llm_loop_result.tool_results,
            )

        return LLMLoopResult(notifications=notifications, stop_reason="end_turn")

    # ── internal methods ──────────────────────────────────────────────────

    async def _run_llm_loop(
        self,
        session: SessionState,
        session_id: str,
        agent_orchestrator: AgentOrchestrator,
        initial_prompt_text: str | None = None,
        tool_results: list[ToolResult] | None = None,
    ) -> LLMLoopResult:
        notifications: list[ACPMessage] = []
        max_iterations = 10
        iteration = 0
        final_text: str | None = None

        while iteration < max_iterations:
            iteration += 1

            if self._is_cancel_requested(session):
                logger.debug("llm_loop cancelled before LLM call", session_id=session_id, iteration=iteration)
                return LLMLoopResult(notifications=notifications, stop_reason="cancelled")

            try:
                if iteration == 1 and initial_prompt_text:
                    agent_response = await agent_orchestrator.process_prompt(session, initial_prompt_text)
                else:
                    agent_response = await agent_orchestrator.continue_with_tool_results(
                        session, tool_results or []
                    )
            except Exception as e:
                error_message = f"Agent error: {str(e)}"
                notifications.append(_build_error_notification(session_id, error_message))
                logger.error("llm_loop agent processing failed", session_id=session_id, iteration=iteration, error=str(e))
                return LLMLoopResult(notifications=notifications, stop_reason="end_turn")

            if self._is_cancel_requested(session):
                logger.debug("llm_loop cancelled after LLM call", session_id=session_id, iteration=iteration)
                return LLMLoopResult(notifications=notifications, stop_reason="cancelled")

            agent_response_text = agent_response.text if agent_response else ""
            has_tool_calls = agent_response and agent_response.tool_calls

            if agent_response_text:
                final_text = agent_response_text

                if not has_tool_calls:
                    self._state_manager.add_assistant_message(session, agent_response_text)

                self._state_manager.add_event(
                    session,
                    {
                        "type": "session_update",
                        "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": agent_response_text}},
                    },
                )
                notifications.append(_build_agent_response_notification(session_id, agent_response_text))

            agent_plan = getattr(agent_response, "plan", None) if agent_response else None
            if agent_plan:
                validated_plan = self._plan_builder.validate_plan_entries(agent_plan)
                if validated_plan:
                    session.latest_plan = list(validated_plan)
                    notifications.append(self._plan_builder.build_plan_notification(session_id, validated_plan))
                    self._replay_manager.save_plan(session, validated_plan)
                    logger.debug("plan processed and published", session_id=session_id, num_entries=len(validated_plan))

            if not has_tool_calls:
                logger.debug("llm_loop completed - no tool calls", session_id=session_id, iteration=iteration)
                return LLMLoopResult(notifications=notifications, stop_reason="end_turn", final_text=final_text)

            logger.info(
                "llm_loop processing tool calls",
                session_id=session_id,
                iteration=iteration,
                num_tool_calls=len(agent_response.tool_calls),
            )

            tool_calls_for_history = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in agent_response.tool_calls
            ]
            session.history.append({
                "role": "assistant",
                "text": agent_response_text or "",
                "tool_calls": tool_calls_for_history,
            })

            loop_result = await self._process_tool_calls_for_llm_loop(
                session, session_id, agent_response.tool_calls, notifications
            )

            if loop_result.pending_permission:
                logger.debug("llm_loop deferred for permission", session_id=session_id, iteration=iteration)
                return LLMLoopResult(
                    notifications=notifications,
                    stop_reason=None,
                    pending_permission=True,
                    tool_results=loop_result.tool_results,
                )

            if self._is_cancel_requested(session):
                logger.debug("llm_loop cancelled during tool processing", session_id=session_id, iteration=iteration)
                return LLMLoopResult(notifications=notifications, stop_reason="cancelled")

            tool_results = loop_result.tool_results

        logger.warning("llm_loop max iterations reached", session_id=session_id, max_iterations=max_iterations)
        return LLMLoopResult(notifications=notifications, stop_reason="max_iterations", final_text=final_text)

    async def _process_tool_calls_for_llm_loop(
        self,
        session: SessionState,
        session_id: str,
        tool_calls: list[Any],
        notifications: list[ACPMessage],
    ) -> LLMLoopResult:
        tool_results: list[ToolResult] = []

        for tool_call in tool_calls:
            if self._is_cancel_requested(session):
                logger.debug("tool processing cancelled", session_id=session_id)
                return LLMLoopResult(tool_results=tool_results, stop_reason="cancelled")

            tool_name = getattr(tool_call, "name", None)
            tool_arguments = getattr(tool_call, "arguments", {})
            tool_call_id_from_llm = getattr(tool_call, "id", None)

            if not tool_name:
                logger.warning("tool_call has no name", session_id=session_id)
                continue

            tool_kind = "other"
            tool_definition = self._tool_registry.get(tool_name)
            if tool_definition is not None:
                tool_kind = tool_definition.kind

            tool_call_id = self._tool_call_handler.create_tool_call(
                session=session,
                title=tool_name,
                kind=tool_kind,
                tool_name=tool_name,
                tool_arguments=tool_arguments,
                tool_call_id_from_llm=tool_call_id_from_llm,
            )

            notifications.append(
                self._tool_call_handler.build_tool_call_notification(
                    session_id=session_id, tool_call_id=tool_call_id, title=tool_name, kind=tool_kind
                )
            )

            self._replay_manager.save_tool_call(
                session=session, tool_call_id=tool_call_id, title=tool_name, kind=tool_kind, status="pending"
            )

            if tool_definition is not None and not tool_definition.requires_permission:
                decision = "allow"
            else:
                decision = await self._decide_tool_execution(session, tool_kind)

            if decision == "ask":
                tool_call_state = session.tool_calls.get(tool_call_id)
                if tool_call_state is not None:
                    permission_msg = self._permission_manager.build_permission_request(
                        session, session_id, tool_call_state.tool_call_id, tool_call_state.title, tool_kind
                    )
                    notifications.append(permission_msg)

                    if session.active_turn:
                        session.active_turn.phase = "awaiting_permission"
                        session.active_turn.permission_tool_call_id = tool_call_id

                logger.debug("permission request sent, pausing llm loop", session_id=session_id, tool_call_id=tool_call_id)
                return LLMLoopResult(tool_results=tool_results, pending_permission=True)

            if decision == "reject":
                self._tool_call_handler.update_tool_call_status(session, tool_call_id, "failed")
                rejection_msg = f"Tool execution rejected by policy for {tool_kind}"
                rejection_content = [{"type": "content", "content": {"type": "text", "text": rejection_msg}}]
                notifications.append(
                    self._tool_call_handler.build_tool_update_notification(
                        session_id=session_id, tool_call_id=tool_call_id, status="failed", content=rejection_content
                    )
                )
                self._replay_manager.save_tool_call_update(
                    session=session, tool_call_id=tool_call_id, status="failed", content=rejection_content
                )
                tool_results.append(ToolResult(
                    tool_call_id=tool_call_id_from_llm or tool_call_id,
                    tool_name=tool_name,
                    success=False,
                    error=rejection_msg,
                ))
                continue

            # decision == "allow"
            try:
                self._tool_call_handler.update_tool_call_status(session, tool_call_id, "in_progress")
                notifications.append(
                    self._tool_call_handler.build_tool_update_notification(
                        session_id=session_id, tool_call_id=tool_call_id, status="in_progress"
                    )
                )
                self._replay_manager.save_tool_call_update(
                    session=session, tool_call_id=tool_call_id, status="in_progress"
                )

                result = await self._tool_registry.execute_tool(
                    session_id, tool_name, tool_arguments, session=session
                )

                extracted_content = await self._content_extractor.extract_from_result(tool_call_id, result)

                is_valid, errors = self._content_validator.validate_content_list(extracted_content.content_items)
                if not is_valid:
                    logger.warning("tool_result_content_validation_failed", tool_call_id=tool_call_id, errors=errors)

                tool_call_state = session.tool_calls.get(tool_call_id)
                if tool_call_state:
                    tool_call_state.result_content = extracted_content.content_items

                provider_raw = session.config_values.get("llm_provider", "openai")
                provider = cast(Literal["openai", "anthropic"], provider_raw)
                self._content_formatter.format_for_llm(extracted_content, provider=provider)

                if result.success:
                    success_text = result.output or "Success"
                    success_content = [{"type": "content", "content": {"type": "text", "text": success_text}}]
                    self._tool_call_handler.update_tool_call_status(
                        session, tool_call_id, "completed", content=success_content
                    )
                    status = "completed"
                else:
                    success_content = None
                    self._tool_call_handler.update_tool_call_status(session, tool_call_id, "failed")
                    status = "failed"

                notification_content = None
                if result.success and result.output:
                    notification_content = [{"type": "content", "content": {"type": "text", "text": result.output}}]

                notifications.append(
                    self._tool_call_handler.build_tool_update_notification(
                        session_id=session_id, tool_call_id=tool_call_id, status=status, content=notification_content
                    )
                )
                self._replay_manager.save_tool_call_update(
                    session=session, tool_call_id=tool_call_id, status=status, content=notification_content
                )

                tool_results.append(ToolResult(
                    tool_call_id=tool_call_id_from_llm or tool_call_id,
                    tool_name=tool_name,
                    success=result.success,
                    output=result.output if result.success else None,
                    error=result.error if not result.success else None,
                ))

            except Exception as e:
                logger.error("tool execution failed", session_id=session_id, tool_name=tool_name, error=str(e))
                self._tool_call_handler.update_tool_call_status(session, tool_call_id, "failed")
                notifications.append(
                    self._tool_call_handler.build_tool_update_notification(
                        session_id=session_id, tool_call_id=tool_call_id, status="failed"
                    )
                )
                self._replay_manager.save_tool_call_update(
                    session=session, tool_call_id=tool_call_id, status="failed"
                )
                tool_results.append(ToolResult(
                    tool_call_id=tool_call_id_from_llm or tool_call_id,
                    tool_name=tool_name,
                    success=False,
                    error=str(e),
                ))

        return LLMLoopResult(tool_results=tool_results)

    async def _decide_tool_execution(self, session: SessionState, tool_kind: str) -> str:
        session_policy = session.permission_policy.get(tool_kind)
        if session_policy == "allow_always":
            return "allow"
        if session_policy == "reject_always":
            return "reject"

        if self._global_policy_manager is not None:
            global_policy = await self._global_policy_manager.get_global_policy(tool_kind)
            if global_policy == "allow_always":
                return "allow"
            if global_policy == "reject_always":
                return "reject"

        return "ask"

    def _is_cancel_requested(self, session: SessionState) -> bool:
        return session.active_turn is not None and session.active_turn.cancel_requested


def _build_error_notification(session_id: str, error_message: str) -> ACPMessage:
    return ACPMessage.notification(
        "session/update",
        {
            "sessionId": session_id,
            "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": error_message}},
        },
    )


def _build_agent_response_notification(session_id: str, text: str) -> ACPMessage:
    return ACPMessage.notification(
        "session/update",
        {
            "sessionId": session_id,
            "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}},
        },
    )
