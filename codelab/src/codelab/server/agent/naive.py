"""NaiveAgent — реализация LLMAgent с одним вызовом LLM на обращение.

Архитектурный принцип: агент делает ОДИН вызов LLM и возвращает ответ.
Цикл tool-calling живёт в LLMLoopStage, а не здесь.

Два явных метода:
  - start_turn: добавляет user message, вызывает LLM
  - continue_turn: НЕ добавляет user message (история содержит tool_results), вызывает LLM
"""

import asyncio
from typing import Any

import structlog

from codelab.server.agent.base import (
    AgentContext,
    AgentResponse,
    ContinuationContext,
    LLMAgent,
)
from codelab.server.agent.plan_extractor import PlanExtractor
from codelab.server.llm.base import LLMMessage, LLMProvider, LLMResponse
from codelab.server.tools.base import ToolDefinition, ToolRegistry
from codelab.server.tools.mapping import acp_name_to_llm_name

logger = structlog.get_logger()


class NaiveAgent(LLMAgent):
    """Агент с одним вызовом LLM.

    Отвечает за:
      - Формирование списка messages из контекста.
      - Один HTTP вызов к LLM провайдеру.
      - Поддержку отмены через asyncio.Task.

    НЕ отвечает за:
      - Цикл tool-calling (LLMLoopStage).
      - Хранение истории сессии (SessionState).
      - Выполнение инструментов (ToolRegistry).
    """

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry | None = None,
    ) -> None:
        """Инициализация агента.

        Args:
            llm: LLM провайдер для выполнения запросов.
            tools: Реестр инструментов (не используется для поиска tools —
                   инструменты приходят через context.available_tools;
                   параметр оставлен для совместимости с initialize()).
        """
        self.llm = llm
        # Хранит tools только для initialize() — поиск tools через context
        self._tools = tools
        # Активные asyncio.Task по session_id — для отмены
        self._active_tasks: dict[str, asyncio.Task] = {}

    # ── Публичный интерфейс LLMAgent ────────────────────────────────────────

    async def start_turn(self, context: AgentContext) -> AgentResponse:
        """Начало нового turn: добавляет user message и вызывает LLM.

        Формирует messages:
            [история, user(prompt_text)]

        Args:
            context: Контекст с историей и промптом пользователя.

        Returns:
            AgentResponse с текстом и/или tool_calls.
        """
        messages = list(context.conversation_history)

        # Формируем user message из prompt blocks
        prompt_text = _format_prompt(context.prompt)
        if prompt_text:
            messages.append(LLMMessage(role="user", content=prompt_text))

        return await self._call_llm(
            messages=messages,
            tools=context.available_tools,
            session_id=context.session_id,
        )

    async def continue_turn(self, context: ContinuationContext) -> AgentResponse:
        """Продолжение turn после tool_results: НЕ добавляет user message.

        История уже содержит tool_results, добавленные AgentOrchestrator:
            [..., assistant(tool_calls), tool(result_1), ...]
        LLM получает эту историю как есть и генерирует следующий ответ.

        Args:
            context: Контекст с полной историей, включая tool_results.

        Returns:
            AgentResponse с текстом или новыми tool_calls.
        """
        return await self._call_llm(
            messages=context.history,
            tools=context.available_tools,
            session_id=context.session_id,
        )

    async def cancel_prompt(self, session_id: str) -> None:
        """Отменить активный LLM запрос для сессии.

        Args:
            session_id: ID сессии.
        """
        task = self._active_tasks.get(session_id)
        if task is not None and not task.done():
            logger.info(
                "cancelling active llm task",
                session_id=session_id,
                task_id=id(task),
            )
            task.cancel()
        else:
            logger.debug("no active llm task to cancel", session_id=session_id)

    async def initialize(
        self,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry,
        config: dict[str, Any],
    ) -> None:
        """Обновить LLM провайдер после инициализации DI контейнера.

        Args:
            llm_provider: Новый провайдер.
            tool_registry: Реестр инструментов (зарезервировано).
            config: Конфигурация (зарезервировано).
        """
        self.llm = llm_provider
        self._tools = tool_registry

    async def end_session(self, session_id: str) -> None:
        """Отменить активный запрос и очистить ресурсы сессии.

        Args:
            session_id: ID сессии.
        """
        await self.cancel_prompt(session_id)
        # _active_tasks очищается в finally блоке _call_llm, но на всякий случай:
        self._active_tasks.pop(session_id, None)

    # ── Внутренняя реализация ────────────────────────────────────────────────

    async def _call_llm(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition],
        session_id: str,
    ) -> AgentResponse:
        """Одиночный вызов LLM. Общая реализация для start_turn и continue_turn.

        Регистрирует текущую asyncio.Task для возможности отмены через cancel_prompt().

        Args:
            messages: Полный список сообщений для LLM.
            tools: Доступные инструменты (уже отфильтрованы по capabilities).
            session_id: ID сессии для управления отменой.

        Returns:
            AgentResponse с текстом ответа и/или tool_calls.

        Raises:
            asyncio.CancelledError: При отмене задачи через cancel_prompt().
        """
        task = asyncio.current_task()
        if task is not None:
            self._active_tasks[session_id] = task

        try:
            return await self._execute_llm_call(messages, tools, session_id)
        except asyncio.CancelledError:
            logger.info("llm_call_cancelled", session_id=session_id)
            raise
        finally:
            self._active_tasks.pop(session_id, None)

    async def _execute_llm_call(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition],
        session_id: str,
    ) -> AgentResponse:
        """Непосредственный вызов LLM провайдера и парсинг ответа.

        Args:
            messages: Список сообщений для LLM.
            tools: Доступные инструменты.
            session_id: ID сессии для логирования.

        Returns:
            AgentResponse с разобранным ответом LLM.
        """
        tools_dict = _to_openai_tools_format(tools)

        response: LLMResponse = await self.llm.create_completion(
            messages=messages,
            tools=tools_dict if tools_dict else None,
        )

        logger.info(
            "llm_response_received",
            session_id=session_id,
            response_length=len(response.text),
            has_tool_calls=bool(response.tool_calls),
            tool_calls_count=len(response.tool_calls),
        )
        logger.debug(
            "llm_response_content",
            session_id=session_id,
            content=response.text[:200],
        )

        # Извлекаем plan из текста или из tool call update_plan
        extractor = PlanExtractor()
        plan = extractor.extract_from_text(response.text)
        if plan is None and response.tool_calls:
            plan = extractor.extract_from_tool_call(response.tool_calls)

        return AgentResponse(
            text=response.text,
            tool_calls=response.tool_calls if response.tool_calls else [],
            stop_reason=response.stop_reason,
            metadata={},
            plan=plan,
        )


# ── Вспомогательные функции модульного уровня ────────────────────────────────


def _format_prompt(prompt: list[dict[str, Any]]) -> str:
    """Объединить текстовые блоки промпта в строку.

    Args:
        prompt: Список блоков вида [{"type": "text", "text": "..."}].

    Returns:
        Объединённый текст, пустая строка если блоков нет.
    """
    return "".join(
        block.get("text", "")
        for block in prompt
        if block.get("type") == "text"
    )


def _to_openai_tools_format(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    """Преобразовать ToolDefinition в формат OpenAI function calling.

    Применяет маппинг имён: ACP имена (с `/`) конвертируются
    в LLM-совместимые имена (с `_`).

    Args:
        tools: Список определений инструментов.

    Returns:
        Список словарей в формате OpenAI API.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": acp_name_to_llm_name(tool.name),
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in tools
    ]
