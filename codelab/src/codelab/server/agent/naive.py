"""Наивный агент с базовым циклом tool-calling."""

import asyncio
from typing import Any

import structlog

from codelab.server.agent.base import AgentContext, AgentResponse, LLMAgent
from codelab.server.agent.plan_extractor import PlanExtractor
from codelab.server.llm.base import LLMMessage, LLMProvider
from codelab.server.tools.base import ToolRegistry

# Используем structlog для структурированного логирования
logger = structlog.get_logger()


class NaiveAgent(LLMAgent):
    """Простой агент с базовым циклом tool-calling.

    Алгоритм:
    1. Отправляет промпт в LLM
    2. Если LLM возвращает tool_calls:
       - Выполняет каждый tool через ToolRegistry
       - Добавляет результаты в историю
       - Повторяет запрос к LLM (максимум max_iterations)
    3. Возвращает финальный текстовый ответ
    """

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry,
        max_iterations: int = 5,
    ) -> None:
        """Инициализация агента.

        Args:
            llm: LLM провайдер для обработки промптов
            tools: Реестр инструментов для выполнения
            max_iterations: Максимальное количество итераций цикла tool-calling
        """
        self.llm = llm
        self.tools = tools
        self.max_iterations = max_iterations
        # Словарь для хранения истории сессий
        self._session_histories: dict[str, list[LLMMessage]] = {}
        # Активные asyncio.Task для каждой сессии — для отмены
        self._active_tasks: dict[str, asyncio.Task] = {}

    async def initialize(
        self,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry,
        config: dict[str, Any],
    ) -> None:
        """Инициализация агента (переопределение из базового класса)."""
        self.llm = llm_provider
        self.tools = tool_registry

    async def process_prompt(self, context: AgentContext) -> AgentResponse:
        """Обработать prompt и вернуть ответ.

        Args:
            context: Контекст с промптом, историей и инструментами

        Returns:
            AgentResponse с финальным ответом и обновленной историей
        """
        session_id = context.session_id
        
        # Зарегистрировать текущую задачу для возможности отмены
        task = asyncio.current_task()
        if task is not None:
            self._active_tasks[session_id] = task
        
        try:
            return await self._process_prompt_impl(context)
        except asyncio.CancelledError:
            logger.info(
                "prompt processing cancelled",
                session_id=session_id,
            )
            raise
        finally:
            # Удалить задачу из активных после завершения или отмены
            self._active_tasks.pop(session_id, None)

    async def _process_prompt_impl(self, context: AgentContext) -> AgentResponse:
        """Внутренняя реализация обработки prompt.
        
        Вынесена отдельно для корректной работы отмены через asyncio.Task.
        """
        # Подготовить messages для LLM
        messages = list(context.conversation_history)

        # Добавить user message с промптом
        # Промпт может содержать list[dict] - преобразуем в текст
        prompt_text = self._format_prompt(context.prompt)
        messages.append(LLMMessage(role="user", content=prompt_text))

        # Получить список инструментов для этой сессии
        available_tools = self.tools.get_available_tools(context.session_id)

        # Преобразовать определения инструментов в формат OpenAI function calling
        tools_dict = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
            }
            for tool in available_tools
        ]

        # Цикл tool-calling
        iteration = 0
        while iteration < self.max_iterations:
            iteration += 1

            # Вызвать LLM
            response = await self.llm.create_completion(
                messages=messages,
                tools=tools_dict if tools_dict else None,
            )

            # Логирование полученного от LLM ответа
            logger.info(
                "llm response received from agent",
                iteration=iteration,
                response_length=len(response.text),
                has_tool_calls=bool(response.tool_calls),
                tool_calls_count=len(response.tool_calls),
            )
            logger.debug(
                "llm response text content",
                content=response.text[:200],
            )

            # Если нет tool calls - вернуть ответ
            if not response.tool_calls:
                # Обновить историю в контексте
                if context.session_id not in self._session_histories:
                    self._session_histories[context.session_id] = []

                # Добавить assistant message и user message в историю
                self._session_histories[context.session_id].extend(messages)
                self._session_histories[context.session_id].append(
                    LLMMessage(role="assistant", content=response.text)
                )

                # Извлечь план из текстового ответа LLM
                plan_extractor = PlanExtractor()
                extracted_plan = plan_extractor.extract_from_text(response.text)

                return AgentResponse(
                    text=response.text,
                    tool_calls=[],
                    stop_reason=response.stop_reason,
                    metadata={"iterations": iteration},
                    plan=extracted_plan,
                )

            # АРХИТЕКТУРНОЕ ИЗМЕНЕНИЕ (Вариант A - Clean Architecture):
            # Agent ДЕЛЕГИРУЕТ управление tool calls в PromptOrchestrator.
            # Согласно SERVER_PERMISSION_INTEGRATION_ARCHITECTURE.md:
            # - Agent: генерирует tool calls и возвращает их
            # - PromptOrchestrator: управляет decision flow (allow/reject/ask)
            # Это позволяет применить permission flow перед выполнением tool.
            
            # Обновить историю в контексте
            if context.session_id not in self._session_histories:
                self._session_histories[context.session_id] = []

            # Добавить user message и assistant message в историю
            self._session_histories[context.session_id].extend(messages)
            self._session_histories[context.session_id].append(
                LLMMessage(
                    role="assistant",
                    content=response.text,
                    tool_calls=response.tool_calls,
                )
            )

            # Логирование для отладки
            logger.info(
                "llm returned tool calls - delegating execution to PromptOrchestrator",
                iteration=iteration,
                num_tool_calls=len(response.tool_calls),
                tool_names=[tc.name for tc in response.tool_calls],
            )

            # Вернуть tool_calls для обработки в PromptOrchestrator
            # PromptOrchestrator применит _process_tool_calls() которая:
            # 1. Проверит разрешения (session policy -> global policy -> ask user)
            # 2. Выполнит tool или отклонит его
            # 3. Отправит notifications клиенту
            
            # Извлечь план из текста или tool call update_plan
            plan_extractor = PlanExtractor()
            extracted_plan = plan_extractor.extract_from_text(response.text)
            if extracted_plan is None:
                # Попытка извлечь из tool call update_plan
                extracted_plan = plan_extractor.extract_from_tool_call(response.tool_calls)
            
            return AgentResponse(
                text=response.text,
                tool_calls=response.tool_calls,
                stop_reason=response.stop_reason,
                metadata={"iterations": iteration},
                plan=extracted_plan,
            )

        # Достигнут лимит итераций
        if context.session_id not in self._session_histories:
            self._session_histories[context.session_id] = []

        self._session_histories[context.session_id].extend(messages)

        return AgentResponse(
            text="Достигнут максимум итераций tool-calling",
            tool_calls=[],
            stop_reason="max_iterations",
            metadata={"iterations": iteration},
            plan=None,
        )

    async def cancel_prompt(self, session_id: str) -> None:
        """Отменить текущую обработку prompt.

        Отменяет активный asyncio.Task для данной сессии, что приводит
        к прерыванию текущего LLM-запроса (OpenAI async client поддерживает
        asyncio cancellation).

        Args:
            session_id: ID сессии
        """
        active_task = self._active_tasks.get(session_id)
        if active_task is not None and not active_task.done():
            logger.info(
                "cancelling active prompt task",
                session_id=session_id,
                task_id=id(active_task),
            )
            active_task.cancel()
        else:
            logger.debug(
                "no active prompt to cancel",
                session_id=session_id,
            )

    def add_to_history(
        self,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        """Добавить сообщение в историю сессии.

        Args:
            session_id: ID сессии
            role: Роль сообщения (user, assistant, tool, system)
            content: Содержимое сообщения
        """
        if session_id not in self._session_histories:
            self._session_histories[session_id] = []

        self._session_histories[session_id].append(LLMMessage(role=role, content=content))

    def get_session_history(self, session_id: str) -> list[LLMMessage]:
        """Получить историю сообщений для сессии.

        Args:
            session_id: ID сессии

        Returns:
            Список сообщений LLM для этой сессии
        """
        return self._session_histories.get(session_id, [])

    async def end_session(self, session_id: str) -> None:
        """Завершить сессию и освободить ресурсы.

        Args:
            session_id: ID сессии
        """
        # Отменить активную задачу если есть
        await self.cancel_prompt(session_id)
        # Очистить историю для этой сессии
        if session_id in self._session_histories:
            del self._session_histories[session_id]

    def _format_prompt(self, prompt: list[dict[str, Any]]) -> str:
        """Преобразовать список блоков промпта в текст.

        Args:
            prompt: Список блоков вида [{"type": "text", "text": "..."}]

        Returns:
            Объединенный текст промпта
        """
        result_parts = []
        for block in prompt:
            if block.get("type") == "text":
                result_parts.append(block.get("text", ""))

        return "".join(result_parts)
