"""Состояние и конфигурация агента."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OrchestratorConfig:
    """Конфигурация оркестратора."""

    enabled: bool = False  # Включить ли использование агента
    llm_provider_class: str = "openai"  # Класс провайдера ("openai", "mock")
    agent_class: str = "naive"  # Класс агента ("naive")
    llm_config: dict[str, Any] = field(default_factory=dict)  # Конфиг для LLM

    # LLM параметры
    model: str = "gpt-4o"  # Модель
    temperature: float = 0.7  # Температура
    max_tokens: int = 8192  # Максимум токенов

    # Поведение агента
    enable_tools: bool = True  # Использовать инструменты
    tool_timeout: float = 30.0  # Timeout для выполнения инструментов
    history_limit: int = 100  # Лимит истории сообщений

    # System prompt
    system_prompt: str = ""  # Кастомный системный промпт (пустой = default)
