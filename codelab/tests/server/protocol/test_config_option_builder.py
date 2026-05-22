"""Тесты для ConfigOptionBuilder и model switching."""

import pytest

from codelab.server.llm.models import ModelInfo, ProviderInfo
from codelab.server.llm.registry import LLMProviderRegistry
from codelab.server.protocol.handlers.config_option_builder import ConfigOptionBuilder


@pytest.fixture
def registry() -> LLMProviderRegistry:
    """Создать registry с тестовыми провайдерами."""
    reg = LLMProviderRegistry()

    reg.register(
        "openai",
        lambda: None,  # type: ignore
        ProviderInfo(
            id="openai",
            name="OpenAI",
            models=[
                ModelInfo(
                    id="gpt-4o",
                    provider_id="openai",
                    name="GPT-4o",
                    context_window=128000,
                    cost_per_input_token=0.000005,
                    cost_per_output_token=0.000015,
                ),
                ModelInfo(
                    id="o3",
                    provider_id="openai",
                    name="o3",
                    context_window=200000,
                ),
            ],
        ),
    )
    reg.register(
        "anthropic",
        lambda: None,  # type: ignore
        ProviderInfo(
            id="anthropic",
            name="Anthropic",
            models=[
                ModelInfo(
                    id="claude-sonnet-4",
                    provider_id="anthropic",
                    name="Claude Sonnet 4",
                    context_window=200000,
                    cost_per_input_token=0.000003,
                    cost_per_output_token=0.000015,
                ),
            ],
        ),
    )

    return reg


class TestConfigOptionBuilder:
    """Тесты для ConfigOptionBuilder."""

    def test_build_model_config_option(self, registry: LLMProviderRegistry) -> None:
        """Проверить создание model config option."""
        builder = ConfigOptionBuilder(registry)
        spec = builder.build_model_config_option()

        assert spec["id"] == "model"
        assert spec["name"] == "Model"
        assert spec["category"] == "model"
        assert spec["type"] == "select"
        assert spec["default"] == "openai/gpt-4o"
        assert len(spec["options"]) == 3

    def test_model_options_format(self, registry: LLMProviderRegistry) -> None:
        """Проверить формат model options."""
        builder = ConfigOptionBuilder(registry)
        spec = builder.build_model_config_option()

        # Проверить что все options имеют value и label
        for option in spec["options"]:
            assert "value" in option
            assert "label" in option
            assert "/" in option["value"]  # Формат "provider/model"

    def test_model_options_with_pricing(self, registry: LLMProviderRegistry) -> None:
        """Проверить pricing в model options."""
        builder = ConfigOptionBuilder(registry)
        spec = builder.build_model_config_option()

        # Найти option с pricing
        gpt4o_option = next(
            (opt for opt in spec["options"] if opt["value"] == "openai/gpt-4o"),
            None,
        )
        assert gpt4o_option is not None
        assert "pricing" in gpt4o_option
        assert "$" in gpt4o_option["pricing"]

    def test_model_options_without_pricing(self, registry: LLMProviderRegistry) -> None:
        """Проверить options без pricing."""
        builder = ConfigOptionBuilder(registry)
        spec = builder.build_model_config_option()

        # Найти option без pricing
        o3_option = next(
            (opt for opt in spec["options"] if opt["value"] == "openai/o3"),
            None,
        )
        assert o3_option is not None
        assert "pricing" not in o3_option

    def test_build_config_specs(self, registry: LLMProviderRegistry) -> None:
        """Проверить создание полной спецификации."""
        builder = ConfigOptionBuilder(registry)
        specs = builder.build_config_specs()

        assert "model" in specs
        assert specs["model"]["id"] == "model"

    def test_build_config_specs_with_additional(self, registry: LLMProviderRegistry) -> None:
        """Проверить создание спецификации с дополнительными опциями."""
        builder = ConfigOptionBuilder(registry)
        additional = {
            "mode": {
                "id": "mode",
                "name": "Mode",
                "category": "mode",
                "default": "ask",
                "options": [{"value": "ask", "name": "Ask"}],
            },
        }
        specs = builder.build_config_specs(additional_specs=additional)

        assert "model" in specs
        assert "mode" in specs

    def test_get_model_list(self, registry: LLMProviderRegistry) -> None:
        """Проверить получение списка моделей."""
        builder = ConfigOptionBuilder(registry)
        models = builder.get_model_list()

        assert len(models) == 3
        model_ids = {m.id for m in models}
        assert "gpt-4o" in model_ids
        assert "o3" in model_ids
        assert "claude-sonnet-4" in model_ids

    def test_empty_registry(self) -> None:
        """Проверить работу с пустым registry."""
        reg = LLMProviderRegistry()
        builder = ConfigOptionBuilder(reg)
        spec = builder.build_model_config_option()

        assert spec["options"] == []

    def test_model_options_description(self, registry: LLMProviderRegistry) -> None:
        """Проверить description в model options."""
        builder = ConfigOptionBuilder(registry)
        spec = builder.build_model_config_option()

        gpt4o_option = next(
            (opt for opt in spec["options"] if opt["value"] == "openai/gpt-4o"),
            None,
        )
        assert gpt4o_option is not None
        assert "description" in gpt4o_option
        assert "128,000" in gpt4o_option["description"]
