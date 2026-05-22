"""Базовый интерфейс для LLM-агентов.

Архитектурный контракт:
  - LLMAgent отвечает за ОДИН вызов LLM. Цикл tool-calling — в LLMLoopStage.
  - start_turn: начало нового turn — добавляет user message и вызывает LLM.
  - continue_turn: продолжение после tool_results — НЕ добавляет user message.
  - Управление историей (session.history) — ответственность AgentOrchestrator.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from codelab.server.llm.base import LLMMessage, LLMProvider, LLMToolCall
from codelab.server.tools.base import ToolDefinition, ToolRegistry

if TYPE_CHECKING:
    from codelab.server.protocol.state import SessionState


@dataclass
class AgentContext:
    """Контекст для start_turn — начало нового turn пользователя.

    Отличие от ContinuationContext: здесь есть prompt пользователя, который
    агент должен добавить как user message перед вызовом LLM.
    """

    session_id: str
    session: "SessionState"
    # Prompt пользователя в виде блоков контента
    prompt: list[dict[str, Any]]
    # История сообщений до текущего промпта (user message ещё не добавлен)
    conversation_history: list[LLMMessage]
    # Инструменты, уже отфильтрованные по capabilities клиента
    available_tools: list[ToolDefinition]
    config: dict[str, Any]


@dataclass
class ContinuationContext:
    """Контекст для continue_turn — продолжение после получения tool_results.

    История уже содержит:
      [..., assistant(tool_calls), tool(result_1), tool(result_2), ...]
    Агент НЕ должен добавлять user message — LLM получает историю как есть
    и генерирует следующий ответ (assistant text или новые tool_calls).
    """

    session_id: str
    session: "SessionState"
    # Полная история включая только что добавленные tool_results
    history: list[LLMMessage]
    # Инструменты, уже отфильтрованные по capabilities клиента
    available_tools: list[ToolDefinition]
    config: dict[str, Any]


@dataclass
class AgentResponse:
    """Ответ агента после одного вызова LLM.

    Attributes:
        text: Текстовый ответ агента (может быть пустым при наличии tool_calls).
        tool_calls: Список вызовов инструментов, запрошенных LLM.
        stop_reason: Причина завершения ("end_turn", "tool_use", "max_tokens").
        metadata: Дополнительные метаданные (зарезервировано).
        plan: Список шагов плана, если LLM использовал update_plan.
            Каждый элемент: {content, priority, status, description?}
    """

    text: str
    tool_calls: list[LLMToolCall]
    stop_reason: str
    metadata: dict[str, Any] = field(default_factory=dict)
    plan: list[dict[str, str]] | None = None


class LLMAgent(ABC):
    """Абстрактный агент — выполняет один вызов LLM.

    Ответственности:
      - Сформировать список messages из контекста.
      - Вызвать LLM провайдер ровно один раз.
      - Вернуть AgentResponse с текстом и/или tool_calls.
      - Поддерживать отмену активного запроса через cancel_prompt().

    НЕ является ответственностью агента:
      - Управление циклом tool-calling (это LLMLoopStage).
      - Хранение истории сессии (это SessionState в AgentOrchestrator).
      - Выполнение инструментов (это LLMLoopStage + ToolRegistry).
    """

    @abstractmethod
    async def start_turn(self, context: AgentContext) -> AgentResponse:
        """Начало нового turn пользователя.

        Добавляет user message из context.prompt к conversation_history
        и выполняет один вызов LLM.

        Args:
            context: Контекст с промптом и историей до него.

        Returns:
            AgentResponse с текстом и/или tool_calls от LLM.
        """

    @abstractmethod
    async def continue_turn(self, context: ContinuationContext) -> AgentResponse:
        """Продолжение turn после получения результатов tool_calls.

        НЕ добавляет user message — history уже содержит tool_results.
        Выполняет один вызов LLM для получения следующего ответа.

        Args:
            context: Контекст с полной историей включая tool_results.

        Returns:
            AgentResponse с текстом (или новыми tool_calls) от LLM.
        """

    @abstractmethod
    async def cancel_prompt(self, session_id: str) -> None:
        """Отменить текущий in-flight LLM запрос для сессии.

        Прерывает HTTP запрос к LLM API через asyncio cancellation.

        Args:
            session_id: ID сессии для поиска активного запроса.
        """

    @abstractmethod
    async def initialize(
        self,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry,
        config: dict[str, Any],
    ) -> None:
        """Обновить зависимости агента после инициализации DI контейнера.

        Args:
            llm_provider: Новый LLM провайдер.
            tool_registry: Реестр инструментов (зарезервировано).
            config: Дополнительная конфигурация.
        """

    @abstractmethod
    async def end_session(self, session_id: str) -> None:
        """Завершить сессию и освободить ресурсы.

        Отменяет активный запрос если он есть.

        Args:
            session_id: ID сессии.
        """
