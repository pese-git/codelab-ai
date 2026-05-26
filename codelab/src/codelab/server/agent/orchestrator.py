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
from codelab.server.llm.base import LLMProvider
from codelab.server.llm.models import LLMMessage
from codelab.server.llm.registry import LLMProviderRegistry
from codelab.server.llm.resolver import ModelResolver
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
        llm_registry: LLMProviderRegistry | None = None,
        model_resolver: ModelResolver | None = None,
    ) -> None:
        """Инициализация оркестратора.

        Args:
            config: Конфигурация (класс агента, параметры LLM).
            llm_provider: Провайдер LLM для запросов (legacy).
            tool_registry: Реестр всех зарегистрированных инструментов.
            llm_registry: Реестр LLM провайдеров для multi-provider (опционально).
            model_resolver: Резолвер моделей для выбора провайдера (опционально).
        """
        self.config = config
        self.llm_provider = llm_provider
        self.tool_registry = tool_registry
        self.llm_registry = llm_registry
        self.model_resolver = model_resolver

        # NaiveAgent — единственная реализация; tools передаём для initialize()
        self.agent: LLMAgent = NaiveAgent(llm=llm_provider, tools=tool_registry)

    async def resolve_provider_for_session(
        self,
        session_state: SessionState,
    ) -> LLMProvider:
        """Резолвить провайдер для сессии на основе config values.

        Если model_resolver доступен — использует его для выбора провайдера
        из session config values. Иначе возвращает дефолтный llm_provider.

        Args:
            session_state: Состояние сессии

        Returns:
            LLMProvider для данной сессии
        """
        if self.model_resolver:
            model_value = session_state.config_values.get("model", "")
            if model_value:
                try:
                    provider, _ = await self.model_resolver.resolve(model_value)
                    return provider
                except Exception:
                    logger.warning(
                        "failed to resolve model, using default provider",
                        model=model_value,
                    )

        return self.llm_provider

    @property
    def _default_model_ref(self) -> str:
        """Сформировать default model reference из config.

        Returns:
            Строка в формате "provider/model" (например, "openai/gpt-4o").
        """
        return f"{self.config.llm_provider_class}/{self.config.model}"

    async def _resolve_provider_for_turn(
        self,
        session_id: str,
        model_ref: str,
    ) -> tuple[LLMProvider, str]:
        """Резолвить провайдер для turn с кэшированием.

        Если model_resolver доступен — использует его с кэшированием.
        Иначе возвращает legacy llm_provider.

        Args:
            session_id: ID сессии для кэширования
            model_ref: Ссылка на модель в формате "provider/model"

        Returns:
            Кортеж (LLMProvider, model_id)
        """
        if self.model_resolver:
            try:
                return await self.model_resolver.resolve_for_session(
                    session_id, model_ref
                )
            except Exception:
                logger.warning(
                    "failed to resolve model, using default provider",
                    session_id=session_id,
                    model=model_ref,
                )
        # Fallback на legacy provider
        return self.llm_provider, self.config.model

    async def process_prompt(
        self,
        session_state: SessionState,
        prompt: str,
        mcp_manager: Any | None = None,
    ) -> AgentResponse:
        """Начало нового turn: вызывает agent.start_turn().

        Формирует AgentContext из истории сессии и текста промпта.
        Агент добавит user message и выполнит один вызов LLM.

        Args:
            session_state: Текущее состояние сессии.
            prompt: Текст промпта пользователя.
            mcp_manager: MCP manager для сессии (из runtime registry).

        Returns:
            AgentResponse с ответом LLM (текст и/или tool_calls).
        """
        # Определить модель из config_values с fallback на default
        model_ref = session_state.config_values.get("model", "")
        if not model_ref:
            # Fallback: собрать из config.llm.provider и config.llm.model
            model_ref = self._default_model_ref

        # Резолвить провайдер для данной сессии (с кэшированием)
        provider, model_id = await self._resolve_provider_for_turn(
            session_state.session_id, model_ref
        )

        # Установить провайдер на агенте для этого turn
        self.agent.set_llm(provider)

        context = AgentContext(
            session_id=session_state.session_id,
            session=session_state,
            prompt=[{"type": "text", "text": prompt}],
            conversation_history=self._build_history(session_state, mcp_manager),
            available_tools=self._filter_tools(session_state, mcp_manager),
            config=session_state.config_values,
            model=model_ref,
        )

        logger.info(
            "agent context built",
            session_id=session_state.session_id,
            history_messages=len(context.conversation_history),
            available_tools_count=len(context.available_tools),
            mcp_tools_count=sum(
                1 for t in context.available_tools
                if t.name.startswith("mcp:")
            ),
        )

        agent_response = await self.agent.start_turn(context)

        logger.info(
            "agent_start_turn_completed",
            session_id=session_state.session_id,
            response_length=len(agent_response.text),
            has_tool_calls=bool(agent_response.tool_calls),
            model=model_ref,
        )
        return agent_response

    async def continue_with_tool_results(
        self,
        session_state: SessionState,
        tool_results: list[ToolResult],
        mcp_manager: Any | None = None,
    ) -> AgentResponse:
        """Продолжение turn после получения tool_results: вызывает agent.continue_turn().

        1. Добавляет tool_results в session_state.history.
        2. Формирует ContinuationContext — история уже содержит tool_results.
        3. Агент НЕ добавляет user message — история идёт в LLM как есть.

        Args:
            session_state: Состояние сессии (история обновляется на месте).
            tool_results: Результаты выполнения tool_calls.
            mcp_manager: MCP manager для сессии (из runtime registry).

        Returns:
            AgentResponse с ответом LLM (текст или новые tool_calls).
        """
        # Сначала записываем tool_results в историю сессии
        for result in tool_results:
            self._add_tool_result_to_history(session_state, result)

        # Определить модель из config_values с fallback на default
        model_ref = session_state.config_values.get("model", "")
        if not model_ref:
            model_ref = self._default_model_ref

        # Резолвить провайдер для данной сессии (с кэшированием)
        provider, model_id = await self._resolve_provider_for_turn(
            session_state.session_id, model_ref
        )

        # Установить провайдер на агенте для этого turn
        self.agent.set_llm(provider)

        context = ContinuationContext(
            session_id=session_state.session_id,
            session=session_state,
            # История уже содержит: [..., assistant(tool_calls), tool(result), ...]
            history=self._build_history(session_state, mcp_manager),
            available_tools=self._filter_tools(session_state, mcp_manager),
            config=session_state.config_values,
            model=model_ref,
        )

        agent_response = await self.agent.continue_turn(context)

        logger.info(
            "agent_continue_turn_completed",
            session_id=session_state.session_id,
            tool_results_count=len(tool_results),
            response_length=len(agent_response.text),
            has_tool_calls=bool(agent_response.tool_calls),
            model=model_ref,
        )
        return agent_response

    async def cancel_prompt(self, session_id: str) -> None:
        """Отменить текущий LLM запрос для сессии.

        Args:
            session_id: ID сессии.
        """
        await self.agent.cancel_prompt(session_id)

    # ── Вспомогательные методы ───────────────────────────────────────────────

    def _build_system_message(
        self, session_state: SessionState, mcp_manager: Any | None = None
    ) -> str:
        """Собрать system message с информацией о MCP серверах.

        Args:
            session_state: Состояние сессии.
            mcp_manager: MCP manager для сессии (из runtime registry).

        Returns:
            Текст system message или пустая строка.
        """
        parts: list[str] = []

        # Кастомный системный промпт из конфигурации
        if self.config.system_prompt:
            parts.append(self.config.system_prompt)

        # Информация о подключённых MCP серверах
        has_mcp = mcp_manager is not None
        mcp_count = mcp_manager.server_count if has_mcp else 0

        logger.info(
            "building system message",
            session_id=session_state.session_id,
            has_system_prompt=bool(self.config.system_prompt),
            has_mcp_manager=has_mcp,
            mcp_server_count=mcp_count,
        )

        if has_mcp:
            mcp_info = self._format_mcp_info(mcp_manager)
            if mcp_info:
                parts.append(mcp_info)

        return "\n\n".join(parts)

    def _format_mcp_info(self, mcp_manager: Any) -> str:
        """Сформировать текст о MCP серверах для LLM.

        Args:
            mcp_manager: MCPManager с подключёнными серверами.

        Returns:
            Форматированный текст или пустая строка.
        """
        if mcp_manager.server_count == 0:
            return ""

        lines = [
            "You have access to the following MCP (Model Context Protocol) servers:",
        ]

        for server_id in mcp_manager.server_ids:
            tools = mcp_manager.get_tools_for_server(server_id)
            tool_names = [t.name.split(":")[-1] for t in tools]
            names_str = ", ".join(tool_names)
            lines.append(
                f"- **{server_id}** ({len(tools)} tools): {names_str}"
            )

        lines.append(
            "\nWhen the user asks about MCP capabilities, "
            "reference these servers and their tools."
        )

        return "\n".join(lines)

    def _build_history(
        self, session_state: SessionState, mcp_manager: Any | None = None
    ) -> list[LLMMessage]:
        """Конвертировать session_state.history в список LLMMessage для LLM.

        Args:
            session_state: Состояние сессии.
            mcp_manager: MCP manager для сессии (из runtime registry).

        Returns:
            Список LLMMessage, готовый к передаче в LLM провайдер.
        """
        messages: list[LLMMessage] = []

        # System message (кастомный промпт + MCP информация)
        system_msg = self._build_system_message(session_state, mcp_manager)
        if system_msg:
            messages.append(LLMMessage(role="system", content=system_msg))
            logger.info(
                "system message added to LLM",
                session_id=session_state.session_id,
                system_message_length=len(system_msg),
                system_message_preview=system_msg[:200],
            )

        # История сессии
        messages.extend(
            self._sanitize_orphaned_tool_calls(
                self._convert_to_llm_messages(session_state.history)
            )
        )

        return messages

    def _filter_tools(
        self, session_state: SessionState, mcp_manager: Any | None = None
    ) -> list[ToolDefinition]:
        """Получить инструменты, доступные для данной сессии.

        Args:
            session_state: Состояние сессии с runtime_capabilities.
            mcp_manager: MCP manager для сессии (из runtime registry).

        Returns:
            Список ToolDefinition, отфильтрованный по capabilities клиента,
            включая MCP инструменты из mcp_manager.
        """
        all_tools = self.tool_registry.get_available_tools(session_state.session_id)
        filtered = self._filter_tools_by_capabilities(
            all_tools, session_state.runtime_capabilities
        )

        # Добавляем MCP инструменты из MCPManager
        if mcp_manager is not None:
            mcp_tools = mcp_manager.get_all_tools()
            filtered.extend(mcp_tools)

        return filtered

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
        from codelab.server.llm.models import LLMToolCall

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
