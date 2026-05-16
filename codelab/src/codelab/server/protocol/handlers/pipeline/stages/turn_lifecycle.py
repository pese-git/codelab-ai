"""Стадия управления жизненным циклом turn."""

from __future__ import annotations

from codelab.server.protocol.handlers.turn_lifecycle_manager import TurnLifecycleManager

from ..base import PromptStage
from ..context import PromptContext


class TurnLifecycleStage(PromptStage):
    """Управление началом и завершением turn, обновление events_history."""

    def __init__(
        self,
        turn_manager: TurnLifecycleManager,
        action: str = "close",  # "open" или "close"
    ) -> None:
        self._turn_manager = turn_manager
        self._action = action

    async def process(self, context: PromptContext) -> PromptContext:
        if self._action == "open":
            # Открыть turn
            active_turn = self._turn_manager.create_active_turn(
                context.session_id,
                context.request_id,
            )
            context.session.active_turn = active_turn
        elif self._action == "close":
            # Закрыть turn
            self._turn_manager.finalize_turn(context.session, context.stop_reason)
            self._turn_manager.clear_active_turn(context.session)

        return context
