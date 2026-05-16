"""Глобальные настройки CodeLab сервера с использованием Pydantic.

Модуль определяет конфигурацию для LLM провайдера, модели, системного промпта
и других параметров сервера через Pydantic BaseSettings.

Переменные окружения:
    CODELAB_LLM_PROVIDER: Тип провайдера LLM (openai, mock). По умолчанию mock.
    CODELAB_LLM_BASE_URL: Base URL для LLM провайдера (опционально)
    CODELAB_LLM_API_KEY: API ключ для LLM провайдера (опционально)
    CODELAB_LLM_MODEL: Модель LLM (по умолчанию gpt-4o)
    CODELAB_LLM_TEMPERATURE: Temperature для LLM (по умолчанию 0.7)
    CODELAB_LLM_MAX_TOKENS: Максимальное количество токенов (по умолчанию 8192)
    CODELAB_SYSTEM_PROMPT: Системный промпт для агента
    CODELAB_SESSION_CACHE_SIZE: Размер LRU-кэша сессий (по умолчанию 200)

Пример использования:
    config = AppConfig()
    print(config.llm.model)

    # С переменными окружения:
    export CODELAB_LLM_PROVIDER=openai
    export CODELAB_LLM_MODEL=gpt-4-turbo
    config = AppConfig()
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    """Конфигурация LLM провайдера.

    Атрибуты:
        provider: Тип провайдера LLM (openai, mock)
        api_key: API ключ для провайдера
        base_url: Base URL для провайдера (опционально)
        model: Модель LLM для использования
        temperature: Temperature для генерации (0.0-1.0)
        max_tokens: Максимальное количество токенов в ответе
    """

    provider: str = Field(default_factory=lambda: os.getenv("CODELAB_LLM_PROVIDER", "mock"))
    api_key: str | None = Field(default_factory=lambda: os.getenv("CODELAB_LLM_API_KEY"))
    base_url: str | None = Field(default_factory=lambda: os.getenv("CODELAB_LLM_BASE_URL"))
    model: str = Field(default_factory=lambda: os.getenv("CODELAB_LLM_MODEL", "gpt-4o"))
    temperature: float = Field(
        default_factory=lambda: float(os.getenv("CODELAB_LLM_TEMPERATURE", "0.7"))
    )
    max_tokens: int = Field(
        default_factory=lambda: int(os.getenv("CODELAB_LLM_MAX_TOKENS", "8192"))
    )


class AgentConfig(BaseModel):
    """Конфигурация агента.

    Атрибуты:
        system_prompt: Системный промпт для агента
    """

    system_prompt: str = Field(
        default_factory=lambda: os.getenv(
            "CODELAB_SYSTEM_PROMPT",
            (
                "Ты помощник, который помогает пользователю выполнять различные задачи. "
                "Используй доступные инструменты для решения задач.\n\n"
                "При решении сложных задач создавай план выполнения "
                "с помощью инструмента update_plan:\n"
                "- Разбивай задачу на логические шаги\n"
                "- Указывай priority: high (критично), medium (стандартно), low (отложить)\n"
                "- Начальный status: pending, затем in_progress, completed по завершении\n"
                "- Обновляй план по мере выполнения, отправляя полный список entries\n"
                "- Вызывай update_plan в начале сложной задачи и при изменении статуса"
            ),
        )
    )


class StorageConfig(BaseModel):
    """Конфигурация хранилища сессий.

    Атрибуты:
        session_cache_size: Максимальное количество сессий в LRU-кэше
    """

    session_cache_size: int = Field(
        default_factory=lambda: int(os.getenv("CODELAB_SESSION_CACHE_SIZE", "200"))
    )


class WebSocketConfig(BaseModel):
    """Конфигурация WebSocket-соединения.

    Атрибуты:
        max_msg_size: Максимальный размер одного сообщения в байтах (по умолчанию 4 МБ)
        heartbeat_interval: Интервал heartbeat-пинга в секундах (по умолчанию 30.0)
    """

    max_msg_size: int = Field(
        default_factory=lambda: int(os.getenv("CODELAB_WS_MAX_MSG_SIZE", str(4 * 1024 * 1024))),
    )
    heartbeat_interval: float = Field(
        default_factory=lambda: float(os.getenv("CODELAB_WS_HEARTBEAT_INTERVAL", "30.0")),
    )


class AppConfig(BaseModel):
    """Глобальная конфигурация ACP сервера.

    Объединяет конфигурацию LLM, агента и других компонентов.
    Все параметры могут быть установлены через переменные окружения с префиксом CODELAB_.

    Пример:
        config = AppConfig()
        print(config.llm.model)
        print(config.agent.system_prompt)

        # С переменными окружения:
        export CODELAB_LLM_PROVIDER=openai
        config = AppConfig()
    """

    llm: LLMConfig = Field(default_factory=LLMConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    websocket: WebSocketConfig = Field(default_factory=WebSocketConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)

    @classmethod
    def from_env(cls) -> AppConfig:
        """Создать конфигурацию из переменных окружения.

        Returns:
            Объект AppConfig со значениями из переменных окружения
        """
        return cls()
