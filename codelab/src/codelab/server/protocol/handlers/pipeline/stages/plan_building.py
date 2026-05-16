"""Стадия построения плана выполнения задачи."""

from __future__ import annotations

from codelab.server.protocol.handlers.plan_builder import PlanBuilder

from ..base import PromptStage
from ..context import PromptContext


class PlanBuildingStage(PromptStage):
    """Построение плана выполнения задачи."""

    def __init__(self, plan_builder: PlanBuilder) -> None:
        self._plan_builder = plan_builder

    async def process(self, context: PromptContext) -> PromptContext:
        # Инициализация плана происходит позже — в LLMLoopStage из ответа агента.
        # Стадия зарезервирована для будущей pre-plan логики (например, из директив).
        return context
