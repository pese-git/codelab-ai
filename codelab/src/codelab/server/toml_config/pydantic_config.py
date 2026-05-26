"""Pydantic models для TOML конфигурации.

Содержит типы для Registry metadata (providers, models, fallback).
Runtime конфигурация (provider, model, temperature) определена в config.py.

Поддерживает:
- Валидацию типов через Pydantic
- Environment variable expansion через field_validator
- Генерацию ProviderInfo/ModelInfo для LLMProviderRegistry
"""

from __future__ import annotations

import os
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

from codelab.server.llm.models import ModelInfo, ProviderInfo


def _humanize_name(model_id: str) -> str:
    """Преобразует model_id в читаемое имя.

    Заменяет дефисы и подчёркивания на пробелы, применяет title case.
    Примеры:
        gpt-4o → Gpt 4o
        llama3_1_70b → Llama3 1 70b
        claude-sonnet-4 → Claude Sonnet 4
    """
    return re.sub(r"[-_]", " ", model_id).title()


def _flatten_dotted_keys(data: dict[str, Any]) -> dict[str, Any]:
    """Распутывает вложенные структуры от точек в TOML ключах.

    TOML интерпретирует точки в именах ключей как вложенность:
    [models.qwen3.6-plus] → {"qwen3": {"6-plus": {...}}}

    Эта функция рекурсивно flattens такие структуры обратно.

    Args:
        data: Dict из TOML

    Returns:
        Dict с распутанными ключами
    """
    if not isinstance(data, dict):
        return data

    # Ключи которые являются настоящими полями конфигурации модели
    config_keys = {
        "context_window", "max_output_tokens",
        "cost_per_input_token", "cost_per_output_token",
    }

    result: dict[str, Any] = {}

    for key, value in data.items():
        if not isinstance(value, dict):
            result[key] = value
            continue

        # Проверяем, это вложенность от точки или реальная структура
        # Если ключи в value НЕ являются config_keys — это вложенность от точки
        value_keys = set(value.keys())
        is_nested = not value_keys.intersection(config_keys)

        if is_nested and len(value_keys) == 1:
            # Одиночная вложенность от точки — рекурсивно flattens
            nested_key = next(iter(value_keys))
            nested_value = value[nested_key]
            if isinstance(nested_value, dict):
                # Продолжаем распутывание
                flattened = _flatten_dotted_keys({nested_key: nested_value})
                # Объединяем с результатом
                for fk, fv in flattened.items():
                    full_key = f"{key}.{fk}"
                    result[full_key] = fv
            else:
                result[f"{key}.{nested_key}"] = nested_value
        else:
            # Это реальная конфигурация модели
            result[key] = _flatten_dotted_keys(value)

    return result


def _expand_env_vars(value: str) -> str:
    """Раскрывает переменные окружения в строке.

    Поддерживает формат ${VAR_NAME} и $VAR_NAME.
    """
    if not value or "$" not in value:
        return value

    result = value
    # ${VAR} format
    for match in re.finditer(r"\$\{([^}]+)\}", value):
        var_name = match.group(1)
        env_value = os.environ.get(var_name, "")
        result = result.replace(match.group(0), env_value)

    # $VAR format (без скобок)
    for match in re.finditer(r"\$([A-Za-z_][A-Za-z0-9_]*)", result):
        var_name = match.group(1)
        env_value = os.environ.get(var_name, "")
        result = result.replace(match.group(0), env_value)

    return result


class ModelConfig(BaseModel):
    """Конфигурация конкретной модели.

    Атрибуты:
        context_window: Размер контекстного окна
        max_output_tokens: Максимальное количество выходных токенов
        cost_per_input_token: Стоимость входного токена (USD)
        cost_per_output_token: Стоимость выходного токена (USD)
    """

    context_window: int | None = None
    max_output_tokens: int | None = None
    cost_per_input_token: float | None = None
    cost_per_output_token: float | None = None

    def to_model_info(self, model_id: str, provider_id: str) -> ModelInfo:
        """Создаёт ModelInfo из конфигурации модели.

        Args:
            model_id: Идентификатор модели (например, "gpt-4o")
            provider_id: Идентификатор провайдера (например, "openai")

        Returns:
            ModelInfo с метаданными модели
        """
        return ModelInfo(
            id=model_id,
            provider_id=provider_id,
            name=_humanize_name(model_id),
            context_window=self.context_window,
            max_output_tokens=self.max_output_tokens,
            cost_per_input_token=self.cost_per_input_token,
            cost_per_output_token=self.cost_per_output_token,
        )


class ProviderConfig(BaseModel):
    """Конфигурация провайдера.

    Атрибуты:
        api_key: API ключ (поддерживает ${ENV_VAR} expansion)
        base_url: Base URL API
        default_model: Модель по умолчанию
        models: Per-model конфигурация
    """

    api_key: str | None = None
    base_url: str | None = None
    default_model: str | None = None
    models: dict[str, ModelConfig] = Field(default_factory=dict)

    @field_validator("api_key", mode="before")
    @classmethod
    def expand_env_in_api_key(cls, v: str | None) -> str | None:
        """Раскрывает переменные окружения в api_key."""
        if v and isinstance(v, str):
            return _expand_env_vars(v)
        return v

    @field_validator("models", mode="before")
    @classmethod
    def flatten_dotted_model_keys(cls, v: Any) -> Any:
        """Распутывает вложенные структуры от точек в TOML ключах моделей.

        TOML интерпретирует [models.qwen3.6-plus] как {"qwen3": {"6-plus": {...}}}.
        Эта функция преобразует обратно в {"qwen3.6-plus": {...}}.
        """
        if isinstance(v, dict):
            return _flatten_dotted_keys(v)
        return v

    def to_provider_info(self, provider_id: str) -> ProviderInfo:
        """Создаёт ProviderInfo из конфигурации провайдера.

        Args:
            provider_id: Идентификатор провайдера (например, "openai")

        Returns:
            ProviderInfo со списком моделей
        """
        models = [
            model_cfg.to_model_info(model_id, provider_id)
            for model_id, model_cfg in self.models.items()
        ]
        return ProviderInfo(
            id=provider_id,
            name=provider_id.title(),
            base_url=self.base_url,
            models=models,
        )


class FallbackConfig(BaseModel):
    """Конфигурация fallback системы.

    Атрибуты:
        enabled: Включён ли fallback
        strategy: Стратегия (sequential, cost, latency, smart)
        order: Порядок провайдеров
        max_attempts: Максимальное количество попыток
        retry_on: Типы ошибок для retry
    """

    enabled: bool = False
    strategy: str = "sequential"
    order: list[str] = Field(default_factory=list)
    max_attempts: int = 3
    retry_on: list[str] = Field(default_factory=lambda: ["rate_limit", "timeout"])
