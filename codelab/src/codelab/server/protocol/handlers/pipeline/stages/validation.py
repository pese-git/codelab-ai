"""Стадия валидации входных параметров и проверки состояния сессии."""

from __future__ import annotations

from codelab.server.messages import ACPMessage
from codelab.server.protocol.handlers.state_manager import StateManager

from ..base import PromptStage
from ..context import PromptContext


class ValidationStage(PromptStage):
    """Валидация входных параметров и проверки состояния сессии."""

    def __init__(self, state_manager: StateManager) -> None:
        self._state_manager = state_manager

    async def process(self, context: PromptContext) -> PromptContext:
        # Проверить что сессия не занята
        if context.session.active_turn is not None:
            context.error_response = ACPMessage.error_response(
                context.request_id, code=-32003, message="Session busy"
            )
            context.should_stop = True
            return context

        # Проверить текст промпта
        if not context.raw_text.strip():
            context.error_response = ACPMessage.error_response(
                context.request_id, code=-32602, message="Empty prompt"
            )
            context.should_stop = True
            return context

        return context
