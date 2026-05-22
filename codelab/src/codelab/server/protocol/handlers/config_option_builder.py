"""Билдер config options для ACP протокола.

Создаёт config options из Registry провайдеров для переключения моделей.
Поддерживает:
- build_model_config_option() — генерация model config option из Registry
- build_config_specs() — полная спецификация config options
"""

from __future__ import annotations

from typing import Any

import structlog

from codelab.server.llm.models import ModelInfo
from codelab.server.llm.registry import LLMProviderRegistry

logger = structlog.get_logger()


class ConfigOptionBuilder:
    """Билдер config options для ACP протокола.

    Генерирует config options из Registry провайдеров.
    """

    def __init__(self, registry: LLMProviderRegistry) -> None:
        """Инициализация.

        Args:
            registry: Реестр провайдеров
        """
        self._registry = registry

    def build_model_config_option(
        self,
        default_model: str = "openai/gpt-4o",
    ) -> dict[str, Any]:
        """Создать config option для модели.

        Формат value: "provider/model" (например, "openai/gpt-4o").

        Args:
            default_model: Модель по умолчанию

        Returns:
            Spec для model config option
        """
        models = self._registry.list_all_models()
        options = self._build_model_options(models)

        return {
            "id": "model",
            "name": "Model",
            "category": "model",
            "type": "select",
            "default": default_model,
            "options": options,
        }

    def build_config_specs(
        self,
        default_model: str = "openai/gpt-4o",
        additional_specs: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Создать полную спецификацию config options.

        Args:
            default_model: Модель по умолчанию
            additional_specs: Дополнительные config specs (mode, etc.)

        Returns:
            Dict config_id -> spec
        """
        specs: dict[str, dict[str, Any]] = {}

        # Добавить model config option
        model_spec = self.build_model_config_option(default_model)
        specs[model_spec["id"]] = model_spec

        # Добавить дополнительные specs
        if additional_specs:
            specs.update(additional_specs)

        return specs

    def get_model_list(self) -> list[ModelInfo]:
        """Получить список всех доступных моделей.

        Returns:
            Список моделей из всех провайдеров
        """
        return self._registry.list_all_models()

    @staticmethod
    def _build_model_options(models: list[ModelInfo]) -> list[dict[str, Any]]:
        """Создать список options для model config option.

        Args:
            models: Список моделей

        Returns:
            Список options в формате ACP
        """
        options: list[dict[str, Any]] = []

        for model in models:
            description = model.description or ""
            if model.context_window:
                description += f" ({model.context_window:,} context)"

            option: dict[str, Any] = {
                "value": model.full_id,
                "label": f"{model.name or model.id}",
            }

            if description:
                option["description"] = description

            # Добавить pricing если доступен
            pricing_parts = []
            if model.cost_per_input_token is not None:
                pricing_parts.append(f"${model.cost_per_input_token:.6f}/input")
            if model.cost_per_output_token is not None:
                pricing_parts.append(f"${model.cost_per_output_token:.6f}/output")
            if pricing_parts:
                option["pricing"] = ", ".join(pricing_parts)

            options.append(option)

        return options
