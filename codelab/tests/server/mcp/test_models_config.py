"""Тесты для MCPServerConfig модели с поддержкой HTTP/SSE транспортов."""

import pytest

from codelab.server.mcp.models import MCPServerConfig


class TestMCPServerConfigValidation:
    """Тесты валидации MCPServerConfig."""

    def test_stdio_config_requires_command(self):
        """Stdio тип требует command."""
        with pytest.raises(ValueError, match="requires 'command'"):
            MCPServerConfig(name="test", type="stdio")

    def test_stdio_config_valid(self):
        """Валидная stdio конфигурация."""
        config = MCPServerConfig(
            name="test",
            type="stdio",
            command="mcp-server",
            args=["--stdio"],
        )
        assert config.type == "stdio"
        assert config.command == "mcp-server"
        assert config.args == ["--stdio"]

    def test_http_config_requires_url(self):
        """HTTP тип требует url."""
        with pytest.raises(ValueError, match="requires 'url'"):
            MCPServerConfig(name="test", type="http")

    def test_http_config_valid(self):
        """Валидная HTTP конфигурация."""
        config = MCPServerConfig(
            name="test",
            type="http",
            url="http://localhost:8080",
        )
        assert config.type == "http"
        assert config.url == "http://localhost:8080"

    def test_sse_config_requires_url(self):
        """SSE тип требует url."""
        with pytest.raises(ValueError, match="requires 'url'"):
            MCPServerConfig(name="test", type="sse")

    def test_sse_config_valid(self):
        """Валидная SSE конфигурация."""
        config = MCPServerConfig(
            name="test",
            type="sse",
            url="http://localhost:8080/sse",
        )
        assert config.type == "sse"
        assert config.url == "http://localhost:8080/sse"

    def test_default_type_is_stdio(self):
        """По умолчанию type = stdio."""
        config = MCPServerConfig(name="test", command="mcp-server")
        assert config.type == "stdio"


class TestMCPServerConfigConnectionParams:
    """Тесты get_connection_params метода."""

    def test_stdio_connection_params(self):
        """Параметры подключения для stdio."""
        config = MCPServerConfig(
            name="test",
            type="stdio",
            command="mcp-server",
            args=["--stdio"],
            env=[{"name": "API_KEY", "value": "secret"}],
        )
        params = config.get_connection_params()
        assert params["command"] == "mcp-server"
        assert params["args"] == ["--stdio"]
        assert params["env"] == {"API_KEY": "secret"}

    def test_http_connection_params(self):
        """Параметры подключения для http."""
        config = MCPServerConfig(
            name="test",
            type="http",
            url="http://localhost:8080",
            headers=[{"name": "Authorization", "value": "Bearer token"}],
        )
        params = config.get_connection_params()
        assert params["url"] == "http://localhost:8080"
        assert params["headers"] == [
            {"name": "Authorization", "value": "Bearer token"}
        ]

    def test_sse_connection_params(self):
        """Параметры подключения для sse."""
        config = MCPServerConfig(
            name="test",
            type="sse",
            url="http://localhost:8080/sse",
        )
        params = config.get_connection_params()
        assert params["url"] == "http://localhost:8080/sse"
        assert params["headers"] == []

    def test_unknown_type_raises_error(self):
        """Неизвестный тип вызывает ошибку."""
        config = MCPServerConfig(
            name="test",
            type="unknown",
            url="http://localhost:8080",
        )
        with pytest.raises(ValueError, match="Unsupported transport type"):
            config.get_connection_params()


class TestMCPServerConfigRetryConfig:
    """Тесты retry configuration."""

    def test_default_retry_config(self):
        """Retry configuration по умолчанию."""
        config = MCPServerConfig(
            name="test",
            type="stdio",
            command="mcp-server",
        )
        retry = config.get_retry_config()
        assert retry["max_retries"] == 5
        assert retry["initial_delay"] == 1.0
        assert retry["max_delay"] == 30.0
        assert retry["backoff_multiplier"] == 2.0

    def test_custom_retry_config(self):
        """Custom retry configuration."""
        config = MCPServerConfig(
            name="test",
            type="http",
            url="http://localhost:8080",
            max_retries=10,
            initial_delay=2.0,
            max_delay=60.0,
            backoff_multiplier=1.5,
        )
        retry = config.get_retry_config()
        assert retry["max_retries"] == 10
        assert retry["initial_delay"] == 2.0
        assert retry["max_delay"] == 60.0
        assert retry["backoff_multiplier"] == 1.5


class TestMCPServerConfigEnvDict:
    """Тесты get_env_dict метода."""

    def test_env_dict_name_value_format(self):
        """Преобразование env из name/value формата."""
        config = MCPServerConfig(
            name="test",
            type="stdio",
            command="mcp-server",
            env=[
                {"name": "API_KEY", "value": "secret"},
                {"name": "DEBUG", "value": "true"},
            ],
        )
        env_dict = config.get_env_dict()
        assert env_dict == {"API_KEY": "secret", "DEBUG": "true"}

    def test_env_dict_direct_format(self):
        """Преобразование env из direct формата."""
        config = MCPServerConfig(
            name="test",
            type="stdio",
            command="mcp-server",
            env=[
                {"API_KEY": "secret"},
                {"DEBUG": "true"},
            ],
        )
        env_dict = config.get_env_dict()
        assert env_dict == {"API_KEY": "secret", "DEBUG": "true"}

    def test_env_dict_empty(self):
        """Пустой env список."""
        config = MCPServerConfig(
            name="test",
            type="stdio",
            command="mcp-server",
        )
        env_dict = config.get_env_dict()
        assert env_dict == {}
