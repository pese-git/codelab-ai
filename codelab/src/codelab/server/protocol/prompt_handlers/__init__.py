"""
Специализированные обработчики для session/prompt.

Модуль содержит компоненты для разложения монолитной функции session_prompt
на специализированные обработчики согласно принципу единственной ответственности.
"""

from codelab.server.protocol.prompt_handlers.validator import PromptValidator

__all__ = [
    "PromptValidator",
]
