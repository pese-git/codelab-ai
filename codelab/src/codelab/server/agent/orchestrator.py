"""AgentOrchestrator — сборка контекстов для агента и управление историей.

Ответственности:
  - Конвертировать SessionState.history в список LLMMessage.
  - Фильтровать инструменты по capabilities клиента.
  - Добавлять tool_results в историю сессии.
  - Вызывать agent.start_turn() или agent.continue_turn() в зависимости от ситуации.
"""

from typing import Any

import structlog

from codelab.server.agent.base import (
    AgentContext,
    AgentResponse,
    ContinuationContext,
    LLMAgent,
)
from codelab.server.agent.naive import NaiveAgent
from codelab.server.agent.state import OrchestratorConfig
from codelab.server.llm.base import LLMMessage, LLMProvider
from codelab.server.protocol.state import ClientRuntimeCapabilities, SessionState, ToolResult
from codelab.server.tools.base import ToolDefinition, ToolRegistry

logger = structlog.get_logger()

# Инструменты с этими kind — серверные, не требуют client capabilities.
# Всегда доступны вне зависимости от runtime_capabilities клиента.
_SERVER_SIDE_TOOL_KINDS: frozenset[str] = frozenset({"think", "plan"})


class AgentOrchestrator:
    """Оркестратор для управления LLM-агентом в контексте ACP протокола.

    Собирает контекст из SessionState и вызывает агента через явные методы:
      - process_prompt       → agent.start_turn()   (новый turn пользователя)
      - continue_with_tool_results → agent.continue_turn() (после tool_results)

    Также отвечает за _filter_tools_by_capabilities — фильтрацию инструментов
    согласно ACP-спецификации (capabilities omitted in initialize = UNSUPPORTED).
    """

    def __init__(
        self,
        config: OrchestratorConfig,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry,
    ) -> None:
        """Инициализация оркестратора.

        Args:
            config: Конфигурация (класс агента, параметры LLM).
            llm_provider: Провайдер LLM для запросов.
            tool_registry: Реестр всех зарегистрированных инструментов.
        """
        self.config = config
        self.llm_provider = llm_provider
        self.tool_registry = tool_registry

        # NaiveAgent — единственная реализация; tools передаём для initialize()
        self.agent: LLMAgent = NaiveAgent(llm=llm_provider, tools=tool_registry)

    async def process_prompt(
        self,
        session_state: SessionState,
        prompt: str,
    ) -> AgentResponse:
        """Начало нового turn: вызывает agent.start_turn().

        Формирует AgentContext из истории сессии и текста промпта.
        Агент добавит user message и выполнит один вызов LLM.

        Args:
            session_state: Текущее состояние сессии.
            prompt: Текст промпта пользователя.

        Returns:
            AgentResponse с ответом LLM (текст и/или tool_calls).
        """
        context = AgentContext(
            session_id=session_state.session_id,
            session=session_state,
            prompt=[{"type": "text", "text": prompt}],
            conversation_history=self._build_history(session_state),
            available_tools=self._filter_tools(session_state),
            config=session_state.config_values,
        )

        agent_response = await self.agent.start_turn(context)

        logger.info(
            "agent_start_turn_completed",
            session_id=session_state.session_id,
            response_length=len(agent_response.text),
            has_tool_calls=bool(agent_response.tool_calls),
        )
        return agent_response

    async def continue_with_tool_results(
        self,
        session_state: SessionState,
        tool_results: list[ToolResult],
    ) -> AgentResponse:
        """Продолжение turn после получения tool_results: вызывает agent.continue_turn().

        1. Добавляет tool_results в session_state.history.
        2. Формирует ContinuationContext — история уже содержит tool_results.
        3. Агент НЕ добавляет user message — история идёт в LLM как есть.

        Args:
            session_state: Состояние сессии (история обновляется на месте).
            tool_results: Результаты выполнения tool_calls.

        Returns:
            AgentResponse с ответом LLM (текст или новые tool_calls).
        """
        # Сначала записываем tool_results в историю сессии
        for result in tool_results:
            self._add_tool_result_to_history(session_state, result)

        context = ContinuationContext(
            session_id=session_state.session_id,
            session=session_state,
            # История уже содержит: [..., assistant(tool_calls), tool(result), ...]
            history=self._build_history(session_state),
            available_tools=self._filter_tools(session_state),
            config=session_state.config_values,
        )

        agent_response = await self.agent.continue_turn(context)

        logger.info(
            "agent_continue_turn_completed",
            session_id=session_state.session_id,
            tool_results_count=len(tool_results),
            response_length=len(agent_response.text),
            has_tool_calls=bool(agent_response.tool_calls),
        )
        return agent_response

    async def cancel_prompt(self, session_id: str) -> None:
        """Отменить текущий LLM запрос для сессии.

        Args:
            session_id: ID сессии.
        """
        await self.agent.cancel_prompt(session_id)

    # ── Вспомогательные методы ───────────────────────────────────────────────

    def _build_history(self, session_state: SessionState) -> list[LLMMessage]:
        """Конвертировать session_state.history в список LLMMessage для LLM.

        Args:
            session_state: Состояние сессии.

        Returns:
            Список LLMMessage, готовый к передаче в LLM провайдер.
        """
        return self._sanitize_orphaned_tool_calls(
            self._convert_to_llm_messages(session_state.history)
        )

    def _filter_tools(self, session_state: SessionState) -> list[ToolDefinition]:
        """Получить инструменты, доступные для данной сессии.

        Args:
            session_state: Состояние сессии с runtime_capabilities.

        Returns:
            Список ToolDefinition, отфильтрованный по capabilities клиента.
        """
        all_tools = self.tool_registry.get_available_tools(session_state.session_id)
        return self._filter_tools_by_capabilities(
            all_tools, session_state.runtime_capabilities
        )

    def _add_tool_result_to_history(
        self,
        session_state: SessionState,
        tool_result: ToolResult,
    ) -> None:
        """Добавить результат выполнения tool в историю сессии.

        Формат соответствует OpenAI API для tool response messages:
          {"role": "tool", "tool_call_id": "...", "content": "..."}

        Args:
            session_state: Состояние сессии (мутируется).
            tool_result: Результат выполнения инструмента.
        """
        content = (
            tool_result.output
            if tool_result.success
            else (tool_result.error or "Tool execution failed")
        )

        session_state.history.append({
            "role": "tool",
            "tool_call_id": tool_result.tool_call_id,
            "content": content or "",
        })

        logger.debug(
            "tool_result_added_to_history",
            session_id=session_state.session_id,
            tool_call_id=tool_result.tool_call_id,
            tool_name=tool_result.tool_name,
            success=tool_result.success,
        )

    def _filter_tools_by_capabilities(
        self,
        tools: list[ToolDefinition],
        runtime_capabilities: ClientRuntimeCapabilities | None,
    ) -> list[ToolDefinition]:
        """Отфильтровать инструменты по capabilities клиента.

        Согласно ACP-спецификации: capabilities omitted in initialize = UNSUPPORTED.
        Серверные инструменты (kind in _SERVER_SIDE_TOOL_KINDS) всегда доступны —
        они не требуют поддержки со стороны клиента.

        Args:
            tools: Все зарегистрированные инструменты.
            runtime_capabilities: Capabilities клиента из initialize request.

        Returns:
            Отфильтрованный список инструментов.
        """
        filtered: list[ToolDefinition] = []

        for tool in tools:
            # Серверные инструменты (update_plan, think-tools) не зависят
            # от capabilities клиента — всегда включаем
            if tool.kind in _SERVER_SIDE_TOOL_KINDS:
                filtered.append(tool)
                continue

            # Без capabilities — только серверные инструменты доступны
            if runtime_capabilities is None:
                continue

            # Инструменты файловой системы
            if (
                (tool.name == "fs/read_text_file" and runtime_capabilities.fs_read)
                or (tool.name == "fs/write_text_file" and runtime_capabilities.fs_write)
            ) or tool.name.startswith("terminal/") and runtime_capabilities.terminal:
                filtered.append(tool)
            # Прочие инструменты — не включаются без явного объявления

        logger.debug(
            "tools_filtered_by_capabilities",
            total=len(tools),
            filtered=len(filtered),
            has_capabilities=runtime_capabilities is not None,
            fs_read=runtime_capabilities.fs_read if runtime_capabilities else None,
            fs_write=runtime_capabilities.fs_write if runtime_capabilities else None,
            terminal=runtime_capabilities.terminal if runtime_capabilities else None,
        )
        return filtered

    def _convert_to_llm_messages(
        self,
        history: list[dict[str, Any]] | list,
    ) -> list[LLMMessage]:
        """Конвертировать session.history в список LLMMessage.

        Поддерживает форматы записей истории:
          - {"role": "user",      "content": list[block] | str}
          - {"role": "user",      "text": str}
          - {"role": "assistant", "text": str, "tool_calls"?: [...]}
          - {"role": "tool",      "tool_call_id": str, "content": str}

        Args:
            history: Записи из SessionState.history.

        Returns:
            Список LLMMessage для передачи в LLM провайдер.
        """
        from codelab.server.llm.base import LLMToolCall

        messages: list[LLMMessage] = []

        for entry in history:
            entry_dict: dict[str, Any]
            if isinstance(entry, dict):
                entry_dict = entry
            elif hasattr(entry, "model_dump"):
                entry_dict = entry.model_dump()
            else:
                continue

            role = entry_dict.get("role", "user")
            if role not in ("system", "user", "assistant", "tool"):
                role = "user"

            # tool результаты
            if role == "tool":
                messages.append(LLMMessage(
                    role="tool",
                    content=str(entry_dict.get("content", "")),
                    tool_call_id=entry_dict.get("tool_call_id"),
                    name=entry_dict.get("name"),
                ))
                continue

            # assistant с tool_calls
            tool_calls_data = entry_dict.get("tool_calls")
            if role == "assistant" and tool_calls_data:
                llm_tool_calls: list[LLMToolCall] = []
                for tc in tool_calls_data:
                    if isinstance(tc, dict):
                        llm_tool_calls.append(LLMToolCall(
                            id=tc.get("id", ""),
                            name=tc.get("name", ""),
                            arguments=tc.get("arguments", {}),
                        ))
                    elif hasattr(tc, "id"):
                        llm_tool_calls.append(tc)
                messages.append(LLMMessage(
                    role="assistant",
                    content=str(entry_dict.get("text", "") or entry_dict.get("content", "") or ""),
                    tool_calls=llm_tool_calls if llm_tool_calls else None,
                ))
                continue

            # Обычные сообщения (user / assistant без tool_calls)
            content = entry_dict.get("text", "") or entry_dict.get("content", "")
            # content может быть list[dict] (prompt blocks от StateManager) — конвертируем в str
            if isinstance(content, list):
                content = " ".join(
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            if content:
                messages.append(LLMMessage(role=role, content=str(content)))

        return messages

    def _sanitize_orphaned_tool_calls(
        self, messages: list[LLMMessage]
    ) -> list[LLMMessage]:
        """Добавить синтетические error-результаты для потерянных tool_calls.

        Восстанавливает корректность истории если assistant message имеет tool_calls,
        но соответствующих tool responses нет (например, после краша или ошибки RPC).

        Args:
            messages: Список messages из истории.

        Returns:
            Список messages с добавленными заглушками для осиротевших tool_calls.
        """
        result: list[LLMMessage] = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            if msg.role == "assistant" and msg.tool_calls:
                expected_ids = {tc.id for tc in msg.tool_calls}
                j = i + 1
                tool_msgs: list[LLMMessage] = []
                while j < len(messages) and messages[j].role == "tool":
                    tool_msgs.append(messages[j])
                    j += 1
                satisfied_ids = {m.tool_call_id for m in tool_msgs if m.tool_call_id}
                orphaned_ids = expected_ids - satisfied_ids
                result.append(msg)
                result.extend(tool_msgs)
                for oid in orphaned_ids:
                    logger.warning("orphaned_tool_call_in_history", tool_call_id=oid)
                    result.append(LLMMessage(
                        role="tool",
                        content="Error: Tool execution did not complete",
                        tool_call_id=oid,
                    ))
                i = j
            else:
                result.append(msg)
                i += 1
        return result
