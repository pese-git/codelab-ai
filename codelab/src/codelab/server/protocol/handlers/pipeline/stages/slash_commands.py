"""Стадия обработки slash-команд."""

from __future__ import annotations

from codelab.server.protocol.handlers.slash_commands.router import SlashCommandRouter

from ..base import PromptStage
from ..context import PromptContext


class SlashCommandStage(PromptStage):
    """Обработка slash-команд (/help, /mode, /status и т.д.)."""

    def __init__(self, router: SlashCommandRouter) -> None:
        self._router = router

    async def process(self, context: PromptContext) -> PromptContext:
        if not context.raw_text.startswith("/"):
            return context

        # Парсим команду и аргументы
        prompt_stripped = context.raw_text.strip()
        parts = prompt_stripped[1:].split(maxsplit=1)
        if not parts:
            return context

        command_name = parts[0].lower()
        args = parts[1].split() if len(parts) > 1 else []

        # Пробуем обработать через router
        outcome = self._router.route(command_name, args, context.session)
        if outcome is not None:
            context.notifications.extend(outcome.notifications)
            context.should_stop = True  # slash-команда обработана, LLM не нужен

        return context
