"""Тесты для TOML Configuration Loader.

Проверяют:
- Парсинг TOML файлов
- Merge logic (multi-level)
- Per-model configuration
- Environment variable expansion
- Missing files handling
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from codelab.server.toml_config import (
    FallbackConfig,
    ModelConfig,
    ProviderConfig,
    TOMLConfig,
    expand_env_vars,
    load_config,
    load_toml_file,
    _deep_merge,
    _parse_toml_config,
)


class TestExpandEnvVars:
    """Тесты для expand_env_vars."""

    def test_no_env_vars(self) -> None:
        """Строка без переменных возвращается как есть."""
        assert expand_env_vars("hello world") == "hello world"

    def test_dollar_brace_format(self) -> None:
        """Формат ${VAR} раскрывается."""
        os.environ["TEST_VAR"] = "test_value"
        try:
            assert expand_env_vars("${TEST_VAR}") == "test_value"
        finally:
            del os.environ["TEST_VAR"]

    def test_dollar_format(self) -> None:
        """Формат $VAR раскрывается."""
        os.environ["TEST_VAR"] = "test_value"
        try:
            assert expand_env_vars("$TEST_VAR") == "test_value"
        finally:
            del os.environ["TEST_VAR"]

    def test_missing_env_var(self) -> None:
        """Отсутствующая переменная заменяется на пустую строку."""
        assert expand_env_vars("${NONEXISTENT_VAR_12345}") == ""

    def test_multiple_env_vars(self) -> None:
        """Несколько переменных в одной строке."""
        os.environ["VAR_A"] = "hello"
        os.environ["VAR_B"] = "world"
        try:
            assert expand_env_vars("${VAR_A} ${VAR_B}") == "hello world"
        finally:
            del os.environ["VAR_A"]
            del os.environ["VAR_B"]

    def test_partial_replacement(self) -> None:
        """Частичная замена с текстом вокруг переменных."""
        os.environ["API_KEY"] = "secret123"
        try:
            assert expand_env_vars("Bearer ${API_KEY}") == "Bearer secret123"
        finally:
            del os.environ["API_KEY"]

    def test_empty_string(self) -> None:
        """Пустая строка возвращается как есть."""
        assert expand_env_vars("") == ""

    def test_none_value(self) -> None:
        """None возвращается как есть."""
        assert expand_env_vars(None) is None  # type: ignore


class TestDeepMerge:
    """Тесты для _deep_merge."""

    def test_simple_merge(self) -> None:
        """Простой merge двух dict."""
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self) -> None:
        """Вложенный merge."""
        base = {"llm": {"provider": "openai", "model": "gpt-4o"}}
        override = {"llm": {"model": "gpt-4-turbo"}}
        result = _deep_merge(base, override)
        assert result == {"llm": {"provider": "openai", "model": "gpt-4-turbo"}}

    def test_deep_nested_merge(self) -> None:
        """Глубокий вложенный merge."""
        base = {"llm": {"providers": {"openai": {"api_key": "key1"}}}}
        override = {"llm": {"providers": {"openai": {"base_url": "http://test"}}}}
        result = _deep_merge(base, override)
        assert result["llm"]["providers"]["openai"]["api_key"] == "key1"
        assert result["llm"]["providers"]["openai"]["base_url"] == "http://test"

    def test_override_with_non_dict(self) -> None:
        """Override dict значением не-dict."""
        base = {"a": {"b": 1}}
        override = {"a": "string"}
        result = _deep_merge(base, override)
        assert result == {"a": "string"}

    def test_empty_override(self) -> None:
        """Empty override возвращает base."""
        base = {"a": 1, "b": 2}
        result = _deep_merge(base, {})
        assert result == base

    def test_empty_base(self) -> None:
        """Empty base возвращает override."""
        override = {"a": 1, "b": 2}
        result = _deep_merge({}, override)
        assert result == override


class TestLoadTomlFile:
    """Тесты для load_toml_file."""

    def test_load_valid_toml(self) -> None:
        """Загрузка валидного TOML."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("""
[llm]
provider = "openai"
model = "gpt-4o"
""")
            f.flush()
            result = load_toml_file(Path(f.name))
            assert result["llm"]["provider"] == "openai"
            assert result["llm"]["model"] == "gpt-4o"

    def test_load_missing_file(self) -> None:
        """Загрузка отсутствующего файла возвращает empty dict."""
        result = load_toml_file(Path("/nonexistent/path/file.toml"))
        assert result == {}

    def test_load_empty_file(self) -> None:
        """Загрузка пустого TOML."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("")
            f.flush()
            result = load_toml_file(Path(f.name))
            assert result == {}


class TestParseTomlConfig:
    """Тесты для _parse_toml_config."""

    def test_parse_basic_config(self) -> None:
        """Парсинг базовой конфигурации."""
        data = {
            "llm": {
                "provider": "openai",
                "model": "gpt-4o",
                "temperature": 0.8,
                "max_tokens": 4096,
            }
        }
        config = _parse_toml_config(data)
        assert config.llm_provider == "openai"
        assert config.llm_model == "gpt-4o"
        assert config.temperature == 0.8
        assert config.max_tokens == 4096

    def test_parse_with_providers(self) -> None:
        """Парсинг с конфигурацией провайдеров."""
        data = {
            "llm": {
                "providers": {
                    "openai": {
                        "api_key": "sk-test",
                        "base_url": "https://api.openai.com/v1",
                        "default_model": "gpt-4o",
                        "models": {
                            "gpt-4o": {
                                "context_window": 128000,
                                "max_output_tokens": 16384,
                            }
                        },
                    }
                }
            }
        }
        config = _parse_toml_config(data)
        assert "openai" in config.providers
        openai_config = config.providers["openai"]
        assert openai_config.api_key == "sk-test"
        assert openai_config.base_url == "https://api.openai.com/v1"
        assert "gpt-4o" in openai_config.models
        assert openai_config.models["gpt-4o"].context_window == 128000

    def test_parse_with_fallback(self) -> None:
        """Парсинг с fallback конфигурацией."""
        data = {
            "llm": {
                "fallback": {
                    "enabled": True,
                    "strategy": "sequential",
                    "order": ["openai", "openrouter", "ollama"],
                    "max_attempts": 5,
                    "retry_on": ["rate_limit", "timeout", "internal_error"],
                }
            }
        }
        config = _parse_toml_config(data)
        assert config.fallback.enabled is True
        assert config.fallback.strategy == "sequential"
        assert config.fallback.order == ["openai", "openrouter", "ollama"]
        assert config.fallback.max_attempts == 5
        assert config.fallback.retry_on == ["rate_limit", "timeout", "internal_error"]

    def test_parse_defaults(self) -> None:
        """Парсинг с defaults при пустых данных."""
        config = _parse_toml_config({})
        assert config.llm_provider == "mock"
        assert config.llm_model == "mock-model"
        assert config.temperature == 0.7
        assert config.max_tokens == 8192
        assert config.providers == {}
        assert config.fallback.enabled is False


class TestModelConfig:
    """Тесты для ModelConfig."""

    def test_model_config_defaults(self) -> None:
        """ModelConfig имеет правильные defaults."""
        config = ModelConfig()
        assert config.context_window is None
        assert config.max_output_tokens is None
        assert config.cost_per_input_token is None
        assert config.cost_per_output_token is None

    def test_model_config_with_values(self) -> None:
        """ModelConfig принимает значения."""
        config = ModelConfig(
            context_window=128000,
            max_output_tokens=16384,
            cost_per_input_token=0.00001,
            cost_per_output_token=0.00002,
        )
        assert config.context_window == 128000
        assert config.max_output_tokens == 16384
        assert config.cost_per_input_token == 0.00001
        assert config.cost_per_output_token == 0.00002


class TestProviderConfig:
    """Тесты для ProviderConfig."""

    def test_provider_config_defaults(self) -> None:
        """ProviderConfig имеет правильные defaults."""
        config = ProviderConfig()
        assert config.api_key is None
        assert config.base_url is None
        assert config.default_model is None
        assert config.models == {}

    def test_provider_config_with_models(self) -> None:
        """ProviderConfig с моделями."""
        config = ProviderConfig(
            api_key="sk-test",
            base_url="https://api.test.com",
            default_model="test-model",
            models={"test-model": ModelConfig(context_window=4096)},
        )
        assert config.api_key == "sk-test"
        assert config.default_model == "test-model"
        assert "test-model" in config.models


class TestFallbackConfig:
    """Тесты для FallbackConfig."""

    def test_fallback_config_defaults(self) -> None:
        """FallbackConfig имеет правильные defaults."""
        config = FallbackConfig()
        assert config.enabled is False
        assert config.strategy == "sequential"
        assert config.order == []
        assert config.max_attempts == 3
        assert config.retry_on == ["rate_limit", "timeout"]

    def test_fallback_config_with_values(self) -> None:
        """FallbackConfig с значениями."""
        config = FallbackConfig(
            enabled=True,
            strategy="cost",
            order=["openai", "ollama"],
            max_attempts=5,
            retry_on=["rate_limit"],
        )
        assert config.enabled is True
        assert config.strategy == "cost"
        assert config.order == ["openai", "ollama"]


class TestLoadConfig:
    """Тесты для load_config."""

    def test_load_config_no_files(self) -> None:
        """load_config с отсутствующими файлами возвращает defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(project_root=Path(tmpdir))
            assert config.llm_provider == "mock"
            assert config.llm_model == "mock-model"

    def test_load_config_with_project_toml(self) -> None:
        """load_config загружает codelab.toml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            toml_path = Path(tmpdir) / "codelab.toml"
            toml_path.write_text("""
[llm]
provider = "openai"
model = "gpt-4o"
temperature = 0.8
""")
            config = load_config(project_root=Path(tmpdir))
            assert config.llm_provider == "openai"
            assert config.llm_model == "gpt-4o"
            assert config.temperature == 0.8

    def test_load_config_with_local_override(self) -> None:
        """load_config применяет local overrides."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Project config
            (Path(tmpdir) / "codelab.toml").write_text("""
[llm]
provider = "openai"
model = "gpt-4o"
temperature = 0.7
""")
            # Local override
            (Path(tmpdir) / "codelab.local.toml").write_text("""
[llm]
model = "gpt-4-turbo"
""")
            config = load_config(project_root=Path(tmpdir))
            assert config.llm_provider == "openai"  # из project
            assert config.llm_model == "gpt-4-turbo"  # из local
            assert config.temperature == 0.7  # из project

    def test_load_config_with_custom_path(self) -> None:
        """load_config с custom config path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = Path(tmpdir) / "custom.toml"
            custom_path.write_text("""
[llm]
provider = "anthropic"
model = "claude-sonnet-4"
""")
            config = load_config(
                project_root=Path(tmpdir),
                custom_config_path=custom_path,
            )
            assert config.llm_provider == "anthropic"
            assert config.llm_model == "claude-sonnet-4"

    def test_load_config_with_providers(self) -> None:
        """load_config загружает конфигурацию провайдеров."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "codelab.toml").write_text("""
[llm]
provider = "openai"
model = "gpt-4o"

[llm.providers.openai]
api_key = "${OPENAI_API_KEY}"
base_url = "https://api.openai.com/v1"

[llm.providers.openai.models.gpt-4o]
context_window = 128000
max_output_tokens = 16384

[llm.providers.anthropic]
api_key = "${ANTHROPIC_API_KEY}"

[llm.providers.anthropic.models.claude-sonnet-4]
context_window = 200000
""")
            os.environ["OPENAI_API_KEY"] = "sk-openai-test"
            os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
            try:
                config = load_config(project_root=Path(tmpdir))
                assert "openai" in config.providers
                assert "anthropic" in config.providers
                assert config.providers["openai"].api_key == "sk-openai-test"
                assert config.providers["anthropic"].api_key == "sk-ant-test"
                assert config.providers["openai"].models["gpt-4o"].context_window == 128000
            finally:
                del os.environ["OPENAI_API_KEY"]
                del os.environ["ANTHROPIC_API_KEY"]

    def test_load_config_with_fallback(self) -> None:
        """load_config загружает fallback конфигурацию."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "codelab.toml").write_text("""
[llm]
provider = "openai"
model = "gpt-4o"

[llm.fallback]
enabled = true
strategy = "sequential"
order = ["openai", "openrouter", "ollama"]
max_attempts = 5
""")
            config = load_config(project_root=Path(tmpdir))
            assert config.fallback.enabled is True
            assert config.fallback.strategy == "sequential"
            assert config.fallback.order == ["openai", "openrouter", "ollama"]
            assert config.fallback.max_attempts == 5

    def test_load_config_missing_env_vars(self) -> None:
        """load_config с отсутствующими env vars раскрывает в пустую строку."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "codelab.toml").write_text("""
[llm.providers.openai]
api_key = "${NONEXISTENT_API_KEY}"
""")
            config = load_config(project_root=Path(tmpdir))
            assert config.providers["openai"].api_key == ""
