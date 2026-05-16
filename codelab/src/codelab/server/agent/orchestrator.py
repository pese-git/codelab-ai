"""Оркестратор для управления LLM-агентом в контексте ACP протокола."""

from typing import Any

import structlog

from codelab.server.agent.base import AgentContext, AgentResponse, LLMAgent
from codelab.server.agent.naive import NaiveAgent
from codelab.server.agent.state import OrchestratorConfig
from codelab.server.llm.base import LLMMessage, LLMProvider
from codelab.server.protocol.state import ClientRuntimeCapabilities, SessionState, ToolResult
from codelab.server.tools.base import ToolDefinition, ToolRegistry

# Используем structlog для структурированного логирования
logger = structlog.get_logger()


class AgentOrchestrator:
    """Оркестратор для управления LLM-агентом в контексте ACP протокола.

    Отвечает за:
    - Создание и управление экземплярами NaiveAgent
    - Преобразование между ACP SessionState и AgentContext
    - Управление историей сообщений сессии
    - Координацию выполнения tool calls
    """

    def __init__(
        self,
        config: OrchestratorConfig,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry,
    ) -> None:
        """Инициализация оркестратора.

        Args:
            config: Конфигурация с LLM provider и tool registry
            llm_provider: Провайдер LLM для запросов
            tool_registry: Реестр инструментов для выполнения
            
        Примечание:
            Встроенные инструменты (fs/*, terminal/*) регистрируются
            в PromptOrchestrator, где доступен контекст сессии.
        """
        self.config = config
        self.llm_provider = llm_provider
        self.tool_registry = tool_registry

        # Создать агента в зависимости от конфигурации
        if config.agent_class == "naive":
            self.agent: LLMAgent = NaiveAgent(
                llm=llm_provider,
                tools=tool_registry,
                max_iterations=5,
            )
        else:
            # По умолчанию используем NaiveAgent
            self.agent = NaiveAgent(
                llm=llm_provider,
                tools=tool_registry,
                max_iterations=5,
            )

    async def process_prompt(
        self,
        session_state: SessionState,
        prompt: str,
    ) -> AgentResponse:
        """Обработать промпт и вернуть ответ агента.

        Согласно архитектуре двухуровневой истории, этот метод:
        - НЕ добавляет assistant message в историю сессии
        - НЕ модифицирует session_state
        - ТОЛЬКО возвращает текст ответа агента

        История сообщений обновляется в PromptOrchestrator,
        что обеспечивает централизованное управление сохранением.

        Args:
            session_state: Текущее состояние сессии
            prompt: Текст промпта от пользователя

        Returns:
            AgentResponse с текстом ответа и информацией о tool calls
        """
        # Создать контекст агента из состояния сессии
        agent_context = self._create_agent_context(session_state, prompt)

        # Вызвать агента для обработки промпта
        agent_response = await self.agent.process_prompt(agent_context)

        # Логируем результат обработки
        logger.info(
            "agent processed prompt successfully",
            session_id=session_state.session_id,
            response_length=len(agent_response.text),
        )
        logger.debug(
            "agent response content",
            content=agent_response.text[:200],
        )

        # Возвращаем ответ агента без модификации session_state
        return agent_response

    def _create_agent_context(
        self,
        session_state: SessionState,
        prompt: str,
    ) -> AgentContext:
        """Преобразовать SessionState в AgentContext.

        Args:
            session_state: Состояние сессии из протокола
            prompt: Текст промпта от пользователя

        Returns:
            Контекст для агента
        """
        # Получить историю сообщений из SessionState
        conversation_history = self._convert_to_llm_messages(session_state.history)

        # Преобразовать промпт в формат list[dict]
        prompt_blocks = [{"type": "text", "text": prompt}]

        # Получить доступные инструменты для этой сессии
        all_tools = self.tool_registry.get_available_tools(session_state.session_id)

        # Отфильтровать tools согласно ACP спецификации:
        # Согласно спецификации, capabilities omitted in the initialize request
        # считаются UNSUPPORTED
        available_tools = self._filter_tools_by_capabilities(
            all_tools,
            session_state.runtime_capabilities,
        )

        # Создать и вернуть AgentContext
        return AgentContext(
            session_id=session_state.session_id,
            session=session_state,  # Передаём session_state для использования в tool handlers
            prompt=prompt_blocks,
            conversation_history=conversation_history,
            available_tools=available_tools,
            config=session_state.config_values,
        )

    def _convert_to_llm_messages(
        self,
        history: list[dict[str, Any]] | list,
    ) -> list[LLMMessage]:
        """Преобразовать историю из SessionState в формат LLMMessage.
        
        Поддерживает форматы:
        - {"role": "user", "text": "..."} или {"role": "user", "content": "..."}
        - {"role": "assistant", "text": "...", "tool_calls": [...]}
        - {"role": "tool", "tool_call_id": "...", "content": "..."}

        Args:
            history: История сообщений из SessionState

        Returns:
            Список LLMMessage для отправки в LLM
        """
        from codelab.server.llm.base import LLMToolCall
        
        messages: list[LLMMessage] = []

        for entry in history:
            if isinstance(entry, dict):
                entry_dict = entry
            elif hasattr(entry, "model_dump"):
                entry_dict = entry.model_dump()
            else:
                continue

            # Определить роль сообщения
            role = entry_dict.get("role", "user")
            if role not in ("system", "user", "assistant", "tool"):
                role = "user"

            # Получить содержимое сообщения
            content = entry_dict.get("text", "")
            if not content:
                content = entry_dict.get("content", "")
            
            # Обработка tool messages (результаты выполнения tool)
            if role == "tool":
                tool_call_id = entry_dict.get("tool_call_id")
                tool_name = entry_dict.get("name")
                messages.append(LLMMessage(
                    role="tool",
                    content=str(content) if content else "",
                    tool_call_id=tool_call_id,
                    name=tool_name,
                ))
                continue
            
            # Обработка assistant messages с tool_calls
            tool_calls_data = entry_dict.get("tool_calls")
            if role == "assistant" and tool_calls_data:
                # Конвертировать tool_calls в LLMToolCall объекты
                llm_tool_calls: list[LLMToolCall] = []
                for tc in tool_calls_data:
                    if isinstance(tc, dict):
                        llm_tool_calls.append(LLMToolCall(
                            id=tc.get("id", ""),
                            name=tc.get("name", ""),
                            arguments=tc.get("arguments", {}),
                        ))
                    elif hasattr(tc, "id"):
                        # Уже LLMToolCall объект
                        llm_tool_calls.append(tc)
                
                messages.append(LLMMessage(
                    role="assistant",
                    content=str(content) if content else None,
                    tool_calls=llm_tool_calls if llm_tool_calls else None,
                ))
                continue

            # Создать обычный LLMMessage
            if content:
                messages.append(LLMMessage(role=role, content=str(content)))

        return self._sanitize_orphaned_tool_calls(messages)

    def _sanitize_orphaned_tool_calls(self, messages: list[LLMMessage]) -> list[LLMMessage]:
        """Add synthetic error results for orphaned tool_calls in history.

        Handles corrupted session histories where an assistant message has tool_calls
        but the corresponding tool result messages are missing (e.g. due to a crash
        or failed RPC during the previous session).
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

    def _convert_from_llm_messages(
        self,
        messages: list[LLMMessage],
    ) -> list[dict[str, Any]]:
        """Преобразовать LLMMessage обратно в формат для SessionState.

        Args:
            messages: Список LLMMessage от LLM

        Returns:
            История в формате SessionState
        """
        history: list[dict[str, Any]] = []

        for msg in messages:
            history.append(
                {
                    "type": "text",
                    "role": msg.role,
                    "text": msg.content,
                }
            )

        return history

    def _filter_tools_by_capabilities(
        self,
        tools: list[ToolDefinition],
        runtime_capabilities: ClientRuntimeCapabilities | None,
    ) -> list[ToolDefinition]:
        """Отфильтровать tools согласно ACP спецификации.

        Согласно спецификации, capabilities omitted in the initialize request
        считаются UNSUPPORTED и не должны быть доступны для использования.

        Args:
            tools: Все доступные tools
            runtime_capabilities: Parsed capabilities от клиента

        Returns:
            Отфильтрованный список tools
        """
        if runtime_capabilities is None:
            # Если capabilities не указаны, возвращаем пустой список tools
            logger.debug(
                "runtime_capabilities is None, filtering out all tools",
            )
            return []

        # Отфильтровать tools на основе capabilities
        filtered_tools: list[ToolDefinition] = []

        for tool in tools:
            # File System tools
            if (
                (
                    tool.name == "fs/read_text_file"
                    and runtime_capabilities.fs_read
                )
                or (
                    tool.name == "fs/write_text_file"
                    and runtime_capabilities.fs_write
                )
            ):
                filtered_tools.append(tool)
            # Terminal tools
            elif tool.name.startswith("terminal/"):
                if runtime_capabilities.terminal:
                    filtered_tools.append(tool)
            # Другие tools пропускаем
            else:
                # Пока не зарегистрировано других tools
                pass

        logger.debug(
            "tools filtered by capabilities",
            total_tools=len(tools),
            filtered_tools=len(filtered_tools),
            fs_read=runtime_capabilities.fs_read,
            fs_write=runtime_capabilities.fs_write,
            terminal=runtime_capabilities.terminal,
        )

        return filtered_tools

    async def continue_with_tool_results(
        self,
        session_state: SessionState,
        tool_results: list[ToolResult],
    ) -> AgentResponse:
        """Продолжить обработку после получения tool results.
        
        Добавляет tool results в историю сессии и вызывает LLM повторно
        для получения следующего ответа в LLM loop.
        
        Согласно ACP протоколу (05-Prompt Turn.md):
        "The Agent sends the tool results back to the language model as another request.
        The cycle returns to step 2, continuing until the language model completes
        its response without requesting additional tool calls."
        
        Args:
            session_state: Состояние сессии с обновленной историей
            tool_results: Результаты выполнения tool calls
            
        Returns:
            AgentResponse с текстом ответа и информацией о tool calls
        """
        # Добавить tool results в историю сессии для передачи в LLM
        for result in tool_results:
            self._add_tool_result_to_history(session_state, result)
        
        # Создать контекст агента без нового промпта (продолжение)
        agent_context = self._create_agent_context(session_state, prompt="")
        
        # Вызвать агента для продолжения обработки
        agent_response = await self.agent.process_prompt(agent_context)
        
        logger.info(
            "agent continued with tool results",
            session_id=session_state.session_id,
            tool_results_count=len(tool_results),
            response_length=len(agent_response.text),
        )
        
        return agent_response
    
    def _add_tool_result_to_history(
        self,
        session_state: SessionState,
        tool_result: ToolResult,
    ) -> None:
        """Добавить tool result в историю сессии.
        
        Формат соответствует OpenAI API для tool responses:
        {"role": "tool", "tool_call_id": "...", "content": "..."}
        
        Args:
            session_state: Состояние сессии
            tool_result: Результат выполнения tool
        """
        # Формируем content: либо output, либо error
        content = tool_result.output if tool_result.success else (
            tool_result.error or "Tool execution failed"
        )
        
        # Добавляем tool result в историю в формате OpenAI API
        tool_message = {
            "role": "tool",
            "tool_call_id": tool_result.tool_call_id,
            "content": content or "",
        }
        session_state.history.append(tool_message)
        
        logger.debug(
            "tool result added to history",
            session_id=session_state.session_id,
            tool_call_id=tool_result.tool_call_id,
            success=tool_result.success,
        )
