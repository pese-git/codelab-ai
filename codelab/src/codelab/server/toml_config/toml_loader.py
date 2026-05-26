"""TOML Configuration Loader для CodeLab.

Загружает конфигурацию из TOML-файлов с поддержкой многоуровневого merge:
1. `~/.codelab/auth.toml` — глобальные API keys
2. `codelab.toml` — проект (коммитится в git)
3. `codelab.local.toml` — project-local overrides (в .gitignore)
4. `.env` — environment variables
5. CLI arguments — highest priority

Пример codelab.toml:
    [llm]
    provider = "openai"
    model = "gpt-4o"
    temperature = 0.7

    [llm.providers.openai]
    api_key = "${OPENAI_API_KEY}"  # env var expansion

    [llm.providers.openai.models.gpt-4o]
    context_window = 128000
    max_output_tokens = 16384

    [llm.fallback]
    enabled = false
    strategy = "sequential"
    order = ["openai", "openrouter", "ollama"]
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class ModelConfig:
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


@dataclass
class ProviderConfig:
    """Конфигурация провайдера.

    Атрибуты:
        api_key: API ключ
        base_url: Base URL
        default_model: Модель по умолчанию
        models: Per-model конфигурация
    """

    api_key: str | None = None
    base_url: str | None = None
    default_model: str | None = None
    models: dict[str, ModelConfig] = field(default_factory=dict)


@dataclass
class FallbackConfig:
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
    order: list[str] = field(default_factory=list)
    max_attempts: int = 3
    retry_on: list[str] = field(default_factory=lambda: ["rate_limit", "timeout"])


@dataclass
class TOMLConfig:
    """Полная конфигурация из TOML.

    Атрибуты:
        llm_provider: Активный провайдер
        llm_model: Активная модель
        temperature: Температура генерации
        max_tokens: Максимальное количество токенов
        providers: Конфигурация провайдеров
        fallback: Конфигурация fallback
    """

    llm_provider: str = "mock"
    llm_model: str = "mock-model"
    temperature: float = 0.7
    max_tokens: int = 8192
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    fallback: FallbackConfig = field(default_factory=FallbackConfig)


def expand_env_vars(value: str) -> str:
    """Раскрыть переменные окружения в строке.

    Поддерживает формат `${VAR_NAME}` и `$VAR_NAME`.

    Args:
        value: Строка с переменными окружения

    Returns:
        Строка с раскрытыми переменными
    """
    if not value or ("$" not in value):
        return value

    # Простой replacement для ${VAR} и $VAR
    result = value
    import re

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


def _parse_model_config(data: dict[str, Any]) -> ModelConfig:
    """Распарсить конфигурацию модели из TOML data.

    Args:
        data: Dict из TOML

    Returns:
        ModelConfig
    """
    return ModelConfig(
        context_window=data.get("context_window"),
        max_output_tokens=data.get("max_output_tokens"),
        cost_per_input_token=data.get("cost_per_input_token"),
        cost_per_output_token=data.get("cost_per_output_token"),
    )


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

    # Ключи которые являются настоящими полями конфигурации
    config_keys = {
        "context_window", "max_output_tokens",
        "cost_per_input_token", "cost_per_output_token",
    }

    logger.debug(
        "_flatten_dotted_keys input",
        input_keys=list(data.keys()),
        input_data=data,
    )

    result: dict[str, Any] = {}

    for key, value in data.items():
        if not isinstance(value, dict):
            result[key] = value
            continue

        # Проверяем, это вложенность от точки или реальная структура
        # Если все ключи в value не являются config_keys — это вложенность
        value_keys = set(value.keys())
        is_nested = not value_keys.intersection(config_keys)

        logger.debug(
            "_flatten_dotted_keys processing key",
            key=key,
            value_keys=list(value_keys),
            is_nested=is_nested,
        )

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
                    logger.debug(
                        "_flatten_dotted_keys flattened key",
                        original=f"{key}.{nested_key}",
                        flattened=full_key,
                    )
            else:
                result[f"{key}.{nested_key}"] = nested_value
        else:
            # Это реальная конфигурация модели
            result[key] = _flatten_dotted_keys(value)

    logger.debug(
        "_flatten_dotted_keys output",
        output_keys=list(result.keys()),
    )

    return result


def _parse_provider_config(data: dict[str, Any]) -> ProviderConfig:
    """Распарсить конфигурацию провайдера из TOML data.

    Args:
        data: Dict из TOML

    Returns:
        ProviderConfig
    """
    # Раскрыть env vars в api_key
    api_key = data.get("api_key")
    if api_key and isinstance(api_key, str):
        api_key = expand_env_vars(api_key)

    # Распарсить модели
    models: dict[str, ModelConfig] = {}
    models_data = data.get("models", {})
    if isinstance(models_data, dict):
        logger.debug(
            "_parse_provider_config models_data before flatten",
            models_keys=list(models_data.keys()),
        )
        # Распутать вложенные структуры от точек в TOML ключах
        models_data = _flatten_dotted_keys(models_data)
        logger.debug(
            "_parse_provider_config models_data after flatten",
            models_keys=list(models_data.keys()),
        )
        for model_id, model_data in models_data.items():
            if isinstance(model_data, dict):
                models[model_id] = _parse_model_config(model_data)

    logger.debug(
        "_parse_provider_config final models",
        model_ids=list(models.keys()),
    )

    return ProviderConfig(
        api_key=api_key,
        base_url=data.get("base_url"),
        default_model=data.get("default_model"),
        models=models,
    )


def _parse_fallback_config(data: dict[str, Any]) -> FallbackConfig:
    """Распарсить конфигурацию fallback из TOML data.

    Args:
        data: Dict из TOML

    Returns:
        FallbackConfig
    """
    order = data.get("order", [])
    if isinstance(order, str):
        order = [x.strip() for x in order.split(",") if x.strip()]

    retry_on = data.get("retry_on", ["rate_limit", "timeout"])
    if isinstance(retry_on, str):
        retry_on = [x.strip() for x in retry_on.split(",") if x.strip()]

    return FallbackConfig(
        enabled=data.get("enabled", False),
        strategy=data.get("strategy", "sequential"),
        order=order,
        max_attempts=data.get("max_attempts", 3),
        retry_on=retry_on,
    )


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Глубокий merge двух dict.

    Args:
        base: Базовый dict
        override: Dict для override

    Returns:
       _merged dict
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_toml_file(path: Path) -> dict[str, Any]:
    """Загрузить TOML файл.

    Args:
        path: Путь к файлу

    Returns:
        Dict с данными из TOML

    Raises:
        FileNotFoundError: Если файл не найден
        tomllib.TOMLDecodeError: Если невалидный TOML
    """
    if not path.exists():
        return {}

    with open(path, "rb") as f:
        return tomllib.load(f)


def load_config(
    project_root: Path | None = None,
    custom_config_path: Path | None = None,
) -> TOMLConfig:
    """Загрузить полную конфигурацию с merge logic.

    Priority (от lowest к highest):
    1. `~/.codelab/auth.toml` — глобальные API keys
    2. `codelab.toml` — проект
    3. `codelab.local.toml` — project-local overrides
    4. `custom_config_path` — custom TOML file (если указан)

    Args:
        project_root: Корень проекта (где искать codelab.toml)
        custom_config_path: Путь к custom TOML файлу

    Returns:
        TOMLConfig с merged конфигурацией
    """
    if project_root is None:
        project_root = Path.cwd()

    # Собрать пути к TOML файлам
    auth_toml = Path.home() / ".codelab" / "auth.toml"
    project_toml = project_root / "codelab.toml"
    local_toml = project_root / "codelab.local.toml"

    # Загрузить все файлы в порядке priority
    configs: list[dict[str, Any]] = []

    # 1. Global auth.toml (lowest priority)
    auth_data = load_toml_file(auth_toml)
    if auth_data:
        configs.append(auth_data)
        logger.debug("loaded auth.toml", path=str(auth_toml))

    # 2. Project codelab.toml
    project_data = load_toml_file(project_toml)
    if project_data:
        configs.append(project_data)
        logger.debug("loaded codelab.toml", path=str(project_toml))

    # 3. Local overrides
    local_data = load_toml_file(local_toml)
    if local_data:
        configs.append(local_data)
        logger.debug("loaded codelab.local.toml", path=str(local_toml))

    # 4. Custom config (highest priority)
    if custom_config_path and custom_config_path.exists():
        custom_data = load_toml_file(custom_config_path)
        if custom_data:
            configs.append(custom_data)
            logger.debug("loaded custom config", path=str(custom_config_path))

    # Merge все configs
    merged: dict[str, Any] = {}
    for config in configs:
        merged = _deep_merge(merged, config)

    # Распарсить в TOMLConfig
    return _parse_toml_config(merged)


def _parse_toml_config(data: dict[str, Any]) -> TOMLConfig:
    """Распарсить merged TOML data в TOMLConfig.

    Args:
        data: Merged dict из TOML файлов

    Returns:
        TOMLConfig
    """
    llm_data = data.get("llm", {})

    # Распарсить провайдеров
    providers: dict[str, ProviderConfig] = {}
    providers_data = llm_data.get("providers", {})
    if isinstance(providers_data, dict):
        for provider_id, provider_data in providers_data.items():
            if isinstance(provider_data, dict):
                providers[provider_id] = _parse_provider_config(provider_data)

    # Распарсить fallback
    fallback_data = llm_data.get("fallback", {})
    fallback = _parse_fallback_config(fallback_data) if fallback_data else FallbackConfig()

    return TOMLConfig(
        llm_provider=llm_data.get("provider", "mock"),
        llm_model=llm_data.get("model", "mock-model"),
        temperature=llm_data.get("temperature", 0.7),
        max_tokens=llm_data.get("max_tokens", 8192),
        providers=providers,
        fallback=fallback,
    )
