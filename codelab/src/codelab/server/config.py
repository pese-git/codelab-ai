"""Глобальные настройки CodeLab сервера с использованием Pydantic Settings.

Модуль определяет конфигурацию для LLM провайдера, модели, системного промпта
и других параметров сервера через Pydantic BaseSettings.

Источники конфигурации (приоритет от высшего к низшему):
    1. CLI kwargs (init args при создании AppConfig)
    2. Environment variables (CODELAB_*)
    3. .env файлы
    4. TOML файлы (цепочка с deep merge):
       a. codelab.toml.example — шаблон (lowest)
       b. ~/.codelab/codelab.toml — глобальный конфиг
       c. ~/.codelab/auth.toml — глобальные API keys
       d. codelab.toml — проект
       e. codelab.local.toml — project-local overrides
       f. Custom path через --config (highest)
    5. Default values

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
    # Загрузка из всех источников (TOML chain + env + .env)
    config = AppConfig.load()
    print(config.llm.model)

    # С переменными окружения (имеют приоритет над TOML):
    export CODELAB_LLM_PROVIDER=openai
    config = AppConfig.load()
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Импортируем типы для Registry metadata из TOML config
from codelab.server.toml_config.pydantic_config import (
    FallbackConfig,
    ProviderConfig,
    _expand_env_vars,
)


def _get_env(name: str, default: str | None = None) -> str | None:
    """Получить переменную окружения."""
    return os.getenv(name, default)


def _get_env_typed(name: str, default: str, type_: type) -> Any:
    """Получить переменную окружения с приведением типа."""
    value = os.getenv(name)
    if value is None:
        return default
    return type_(value)


class LLMConfig(BaseModel):
    """Конфигурация LLM провайдера.

    Атрибуты:
        provider: Тип провайдера LLM (openai, mock, anthropic,
            openrouter, zen, go, ollama, lmstudio)
        api_key: API ключ для провайдера
        base_url: Base URL для провайдера (опционально)
        model: Модель LLM для использования
        temperature: Temperature для генерации (0.0-1.0)
        max_tokens: Максимальное количество токенов в ответе
        providers: Конфигурация провайдеров из TOML (для Registry)
        fallback: Конфигурация fallback системы из TOML
    """

    # Runtime params (могут быть установлены через env/TOML/CLI)
    provider: str = "mock"
    api_key: str | None = None
    base_url: str | None = None
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 8192

    # Registry metadata (загружаются только из TOML)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    fallback: FallbackConfig = Field(default_factory=FallbackConfig)

    @classmethod
    def from_values(cls, **overrides: Any) -> LLMConfig:
        """Создать LLMConfig с явными значениями (для CLI overrides)."""
        return cls(**overrides)


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


class AppConfig(BaseSettings):
    """Глобальная конфигурация ACP сервера.

    Объединяет конфигурацию LLM, агента и других компонентов.
    Загружается из нескольких источников с приоритетом:
    CLI kwargs > Environment variables > .env файлы > TOML файл > Default values.

    Пример:
        # Загрузка из всех источников
        config = AppConfig.load()
        print(config.llm.model)
        print(config.llm.providers)  # из TOML

        # С переменными окружения (приоритет над TOML):
        export CODELAB_LLM_PROVIDER=openai
        config = AppConfig.load()
    """

    llm: LLMConfig = Field(default_factory=LLMConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    websocket: WebSocketConfig = Field(default_factory=WebSocketConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)

    model_config = SettingsConfigDict(
        env_prefix="CODELAB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def _find_toml_files(cls, custom_path: str | None = None) -> list[Path]:
        """Найти все TOML файлы конфигурации в порядке приоритета (от низшего к высшему).

        Цепочка файлов:
        1. ~/.codelab/codelab.toml — глобальный конфиг пользователя
        2. ~/.codelab/auth.toml — глобальные API keys
        3. codelab.toml — локальный проект
        4. codelab.local.toml — project-local overrides
        5. custom_path — custom TOML file (highest, если указан через --config)

        Примечание: codelab.toml.example НЕ загружается — это только шаблон.

        Args:
            custom_path: Путь к custom TOML файлу.

        Returns:
            Список Path к найденным TOML файлам в порядке приоритета.
        """
        files: list[Path] = []

        # 1. Global codelab.toml (user-level config)
        global_toml = Path.home() / ".codelab" / "codelab.toml"
        if global_toml.exists():
            files.append(global_toml)

        # 2. Global auth.toml (API keys — overrides template env vars)
        auth_toml = Path.home() / ".codelab" / "auth.toml"
        if auth_toml.exists():
            files.append(auth_toml)

        # 3. Project codelab.toml (overrides global config)
        project_toml = Path.cwd() / "codelab.toml"
        if project_toml.exists():
            files.append(project_toml)

        # 4. Local overrides
        local_toml = Path.cwd() / "codelab.local.toml"
        if local_toml.exists():
            files.append(local_toml)

        # 5. Custom config (highest priority)
        if custom_path:
            custom_toml = Path(custom_path)
            if custom_toml.exists():
                files.append(custom_toml)

        return files

    @classmethod
    def _find_toml_file(cls, custom_path: str | None = None) -> Path | None:
        """Найти основной TOML файл конфигурации (обратная совместимость).

        Args:
            custom_path: Путь к custom TOML файлу.

        Returns:
            Path к найденному TOML файлу или None.
        """
        files = cls._find_toml_files(custom_path)
        return files[-1] if files else None

    @staticmethod
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """Глубокий merge двух dict.

        Args:
            base: Базовый dict.
            override: Dict для override.

        Returns:
            Merged dict.
        """
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = AppConfig._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    @classmethod
    def _load_merged_toml_data(cls, toml_files: list[Path]) -> dict[str, Any]:
        """Загрузить и объединить данные из нескольких TOML файлов.

        Args:
            toml_files: Список путей к TOML файлам в порядке приоритета
                (от низшего к высшему).

        Returns:
            Merged dict с данными из всех TOML файлов.
        """
        merged: dict[str, Any] = {}
        for toml_path in toml_files:
            try:
                with open(toml_path, "rb") as f:
                    data = tomllib.load(f)
                merged = cls._deep_merge(merged, data)
            except Exception:
                pass
        return merged

    @classmethod
    def _merge_llm_config(cls, toml_data: dict[str, Any]) -> dict[str, Any]:
        """Собрать конфигурацию LLM из всех источников с правильным приоритетом.

        Приоритет (от высшего к низшему):
        1. Environment variables (CODELAB_LLM_*)
        2. TOML файл
        3. Default values

        Args:
            toml_data: Данные из TOML файла.

        Returns:
            Dict с merged конфигурацией для LLMConfig.
        """
        # Начинаем с defaults
        llm_data: dict[str, Any] = {
            "provider": "mock",
            "model": "gpt-4o",
            "temperature": 0.7,
            "max_tokens": 8192,
            "api_key": None,
            "base_url": None,
        }

        # Применяем TOML (нижний приоритет)
        toml_llm = toml_data.get("llm", {})
        if isinstance(toml_llm, dict):
            for key in ("provider", "model", "temperature", "max_tokens", "api_key", "base_url"):
                if key in toml_llm:
                    llm_data[key] = toml_llm[key]

            # Providers и fallback — только из TOML
            if "providers" in toml_llm:
                llm_data["providers"] = toml_llm["providers"]
            if "fallback" in toml_llm:
                llm_data["fallback"] = toml_llm["fallback"]

        # Применяем env vars (высший приоритет над TOML)
        env_provider = os.getenv("CODELAB_LLM_PROVIDER")
        if env_provider is not None:
            llm_data["provider"] = env_provider

        env_model = os.getenv("CODELAB_LLM_MODEL")
        if env_model is not None:
            llm_data["model"] = env_model

        env_temperature = os.getenv("CODELAB_LLM_TEMPERATURE")
        if env_temperature is not None:
            llm_data["temperature"] = float(env_temperature)

        env_max_tokens = os.getenv("CODELAB_LLM_MAX_TOKENS")
        if env_max_tokens is not None:
            llm_data["max_tokens"] = int(env_max_tokens)

        env_api_key = os.getenv("CODELAB_LLM_API_KEY")
        if env_api_key is not None:
            llm_data["api_key"] = env_api_key

        env_base_url = os.getenv("CODELAB_LLM_BASE_URL")
        if env_base_url is not None:
            llm_data["base_url"] = env_base_url

        # Если api_key/base_url не заданы напрямую, берём из конфига
        # активного провайдера ([llm.providers.<provider>])
        if llm_data["api_key"] is None or llm_data["base_url"] is None:
            active_provider = llm_data["provider"]
            providers_data = toml_data.get("llm", {}).get("providers", {})
            if isinstance(providers_data, dict) and active_provider in providers_data:
                provider_cfg = providers_data[active_provider]
                if isinstance(provider_cfg, dict):
                    if llm_data["api_key"] is None and "api_key" in provider_cfg:
                        raw_key = provider_cfg["api_key"]
                        expanded_key = (
                            _expand_env_vars(raw_key) if isinstance(raw_key, str) else raw_key
                        )
                        # Если env var не задан, _expand_env_vars вернёт "" —
                        # считаем это как None (ключ не предоставлен)
                        if expanded_key:
                            llm_data["api_key"] = expanded_key
                    if llm_data["base_url"] is None and "base_url" in provider_cfg:
                        llm_data["base_url"] = provider_cfg["base_url"]

        return llm_data

    @classmethod
    def load(cls, *, toml_path: str | None = None) -> AppConfig:
        """Загрузить конфигурацию из всех источников.

        Приоритет (от высшего к низшему):
        1. CLI kwargs (применяются вручную после load())
        2. Environment variables (CODELAB_*)
        3. .env файлы
        4. TOML файлы (auth.toml < codelab.toml < codelab.local.toml < custom)
        5. Default values

        Args:
            toml_path: Путь к custom TOML файлу (опционально).

        Returns:
            Объект AppConfig с загруженной конфигурацией.
        """
        toml_files = cls._find_toml_files(toml_path)

        if toml_files:
            toml_data = cls._load_merged_toml_data(toml_files)
            llm_data = cls._merge_llm_config(toml_data)

            # Создаём LLMConfig из merged данных
            # Нужно сконвертировать providers и fallback из dict в объекты
            providers_data = llm_data.pop("providers", {})
            fallback_data = llm_data.pop("fallback", {})

            # Конвертируем providers
            providers: dict[str, ProviderConfig] = {}
            if isinstance(providers_data, dict):
                for pid, pdata in providers_data.items():
                    if isinstance(pdata, dict):
                        providers[pid] = ProviderConfig(**pdata)

            # Конвертируем fallback
            if isinstance(fallback_data, dict):
                fallback = FallbackConfig(**fallback_data)
            else:
                fallback = FallbackConfig()

            llm_config = LLMConfig(
                **llm_data,
                providers=providers,
                fallback=fallback,
            )
        else:
            # Без TOML — только env vars + defaults
            llm_data = cls._merge_llm_config({})
            providers_data = llm_data.pop("providers", {})
            fallback_data = llm_data.pop("fallback", {})

            providers: dict[str, ProviderConfig] = {}
            if isinstance(providers_data, dict):
                for pid, pdata in providers_data.items():
                    if isinstance(pdata, dict):
                        providers[pid] = ProviderConfig(**pdata)

            if isinstance(fallback_data, dict):
                fallback = FallbackConfig(**fallback_data)
            else:
                fallback = FallbackConfig()

            llm_config = LLMConfig(
                **llm_data,
                providers=providers,
                fallback=fallback,
            )

        return cls(
            llm=llm_config,
        )

    @classmethod
    def from_env(cls) -> AppConfig:
        """Создать конфигурацию из переменных окружения.

        Обратная совместимость — alias для load().
        Загружает из env vars, .env файлов и TOML (если найден).

        Returns:
            Объект AppConfig со значениями из переменных окружения.
        """
        return cls.load()
