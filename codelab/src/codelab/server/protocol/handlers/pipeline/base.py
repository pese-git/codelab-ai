"""Базовая абстракция стадии pipeline."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .context import PromptContext


class PromptStage(ABC):
    """Одна стадия обработки prompt-turn.

    Каждая стадия получает контекст, выполняет работу и:
    - возвращает context (продолжить pipeline)
    - устанавливает context.should_stop = True (прервать, успешно)
    - устанавливает context.error_response (прервать с ошибкой)
    """

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    async def process(self, context: PromptContext) -> PromptContext:
        """Выполнить стадию. Изменить context и вернуть его."""
        ...
