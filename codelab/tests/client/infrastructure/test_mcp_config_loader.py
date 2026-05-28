"""Тесты для MCPConfigLoader — загрузка MCP серверов из TOML файлов."""

import os
from pathlib import Path
from unittest.mock import patch

from codelab.client.infrastructure.mcp_config_loader import (
    MCPConfigLoader,
    _expand_server_env_vars,
    _find_toml_chain,
    _load_mcp_servers_from_toml,
    _merge_servers,
    _validate_server,
    expand_env_vars,
)

# ===========================================================================
# expand_env_vars
# ===========================================================================


class TestExpandEnvVars:
    """Tests for expand_env_vars function."""

    def test_plain_text_unchanged(self) -> None:
        assert expand_env_vars("plain-text") == "plain-text"

    def test_dollar_brace_format(self) -> None:
        with patch.dict(os.environ, {"TEST_KEY": "secret123"}):
            assert expand_env_vars("${TEST_KEY}") == "secret123"

    def test_missing_var_replaced_with_empty(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            # Убедимся что переменная не установлена
            os.environ.pop("UNDEFINED_VAR_XYZ", None)
            assert expand_env_vars("${UNDEFINED_VAR_XYZ}") == ""

    def test_prefix_suffix(self) -> None:
        with patch.dict(os.environ, {"API_KEY": "mykey"}):
            result = expand_env_vars("prefix-${API_KEY}-suffix")
            assert result == "prefix-mykey-suffix"

    def test_empty_string(self) -> None:
        assert expand_env_vars("") == ""

    def test_no_dollar_sign(self) -> None:
        assert expand_env_vars("hello world") == "hello world"

    def test_multiple_vars(self) -> None:
        with patch.dict(os.environ, {"HOST": "localhost", "PORT": "8080"}):
            result = expand_env_vars("${HOST}:${PORT}")
            assert result == "localhost:8080"


# ===========================================================================
# _expand_server_env_vars
# ===========================================================================


class TestExpandServerEnvVars:
    """Tests for _expand_server_env_vars function."""

    def test_expand_command(self) -> None:
        with patch.dict(os.environ, {"NPM": "npx"}):
            server = {"name": "test", "command": "${NPM}"}
            result = _expand_server_env_vars(server)
            assert result["command"] == "npx"

    def test_expand_args(self) -> None:
        with patch.dict(os.environ, {"PKG": "my-server"}):
            server = {"name": "test", "command": "npx", "args": ["-y", "${PKG}"]}
            result = _expand_server_env_vars(server)
            assert result["args"] == ["-y", "my-server"]

    def test_expand_headers(self) -> None:
        with patch.dict(os.environ, {"TOKEN": "abc123"}):
            server = {
                "name": "test",
                "type": "http",
                "url": "https://api.example.com",
                "headers": [{"name": "Authorization", "value": "Bearer ${TOKEN}"}],
            }
            result = _expand_server_env_vars(server)
            assert result["headers"][0]["value"] == "Bearer abc123"

    def test_expand_env(self) -> None:
        with patch.dict(os.environ, {"DB_URL": "postgres://localhost"}):
            server = {
                "name": "test",
                "command": "python",
                "env": [{"name": "DATABASE_URL", "value": "${DB_URL}"}],
            }
            result = _expand_server_env_vars(server)
            assert result["env"][0]["value"] == "postgres://localhost"

    def test_expand_url(self) -> None:
        with patch.dict(os.environ, {"BASE_URL": "https://api.example.com"}):
            server = {"name": "test", "type": "http", "url": "${BASE_URL}/mcp"}
            result = _expand_server_env_vars(server)
            assert result["url"] == "https://api.example.com/mcp"


# ===========================================================================
# _validate_server
# ===========================================================================


class TestValidateServer:
    """Tests for _validate_server function."""

    def test_valid_stdio_server(self) -> None:
        server = {"name": "filesystem", "type": "stdio", "command": "npx"}
        assert _validate_server(server) is True

    def test_valid_http_server(self) -> None:
        server = {"name": "github", "type": "http", "url": "https://api.github.com/mcp"}
        assert _validate_server(server) is True

    def test_stdio_defaults_when_type_missing(self) -> None:
        server = {"name": "test", "command": "python"}
        assert _validate_server(server) is True

    def test_skip_server_without_name(self) -> None:
        server = {"command": "npx"}
        assert _validate_server(server) is False

    def test_skip_stdio_without_command(self) -> None:
        server = {"name": "test", "type": "stdio"}
        assert _validate_server(server) is False

    def test_skip_http_without_url(self) -> None:
        server = {"name": "test", "type": "http"}
        assert _validate_server(server) is False

    def test_skip_unknown_type(self) -> None:
        server = {"name": "test", "type": "unknown"}
        assert _validate_server(server) is False


# ===========================================================================
# _merge_servers
# ===========================================================================


class TestMergeServers:
    """Tests for _merge_servers function."""

    def test_merge_no_overlap(self) -> None:
        existing = [{"name": "a", "command": "cmd_a"}]
        new = [{"name": "b", "command": "cmd_b"}]
        result = _merge_servers(existing, new)
        assert len(result) == 2
        names = {s["name"] for s in result}
        assert names == {"a", "b"}

    def test_override_by_name(self) -> None:
        existing = [{"name": "fs", "command": "old_cmd"}]
        new = [{"name": "fs", "command": "new_cmd"}]
        result = _merge_servers(existing, new)
        assert len(result) == 1
        assert result[0]["command"] == "new_cmd"

    def test_new_adds_additional(self) -> None:
        existing = [{"name": "a", "command": "cmd_a"}]
        new = [
            {"name": "a", "command": "new_a"},
            {"name": "b", "command": "cmd_b"},
        ]
        result = _merge_servers(existing, new)
        assert len(result) == 2
        by_name = {s["name"]: s for s in result}
        assert by_name["a"]["command"] == "new_a"
        assert by_name["b"]["command"] == "cmd_b"

    def test_empty_existing(self) -> None:
        result = _merge_servers([], [{"name": "a", "command": "cmd"}])
        assert len(result) == 1
        assert result[0]["name"] == "a"

    def test_empty_new(self) -> None:
        result = _merge_servers([{"name": "a", "command": "cmd"}], [])
        assert len(result) == 1
        assert result[0]["name"] == "a"


# ===========================================================================
# _load_mcp_servers_from_toml
# ===========================================================================


class TestLoadMcpServersFromToml:
    """Tests for _load_mcp_servers_from_toml function."""

    def test_load_single_stdio_server(self, tmp_path: Path) -> None:
        toml = tmp_path / "codelab.toml"
        toml.write_text(
            """
[[mcp.servers]]
name = "filesystem"
type = "stdio"
command = "npx"
args = ["-y", "@mcp/server-filesystem", "/project"]
"""
        )
        servers = _load_mcp_servers_from_toml(toml)
        assert len(servers) == 1
        assert servers[0]["name"] == "filesystem"
        assert servers[0]["command"] == "npx"

    def test_load_http_server(self, tmp_path: Path) -> None:
        toml = tmp_path / "codelab.toml"
        toml.write_text(
            """
[[mcp.servers]]
name = "github"
type = "http"
url = "https://api.github.com/mcp"
"""
        )
        servers = _load_mcp_servers_from_toml(toml)
        assert len(servers) == 1
        assert servers[0]["type"] == "http"
        assert servers[0]["url"] == "https://api.github.com/mcp"

    def test_load_multiple_servers(self, tmp_path: Path) -> None:
        toml = tmp_path / "codelab.toml"
        toml.write_text(
            """
[[mcp.servers]]
name = "fs"
command = "npx"

[[mcp.servers]]
name = "db"
command = "python"
"""
        )
        servers = _load_mcp_servers_from_toml(toml)
        assert len(servers) == 2
        names = {s["name"] for s in servers}
        assert names == {"fs", "db"}

    def test_empty_mcp_section(self, tmp_path: Path) -> None:
        toml = tmp_path / "codelab.toml"
        toml.write_text("[mcp]\n# no servers\n")
        servers = _load_mcp_servers_from_toml(toml)
        assert servers == []

    def test_no_mcp_section(self, tmp_path: Path) -> None:
        toml = tmp_path / "codelab.toml"
        toml.write_text("[llm]\nprovider = 'openai'\n")
        servers = _load_mcp_servers_from_toml(toml)
        assert servers == []

    def test_invalid_toml_file(self, tmp_path: Path) -> None:
        toml = tmp_path / "codelab.toml"
        toml.write_text("invalid toml {{{")
        servers = _load_mcp_servers_from_toml(toml)
        assert servers == []

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        servers = _load_mcp_servers_from_toml(tmp_path / "nonexistent.toml")
        assert servers == []


# ===========================================================================
# _find_toml_chain
# ===========================================================================


class TestFindTomlChain:
    """Tests for _find_toml_chain function."""

    def test_no_toml_files(self, tmp_path: Path) -> None:
        files = _find_toml_chain(tmp_path)
        # Могут быть глобальные файлы, но в tmp_path точно нет
        project_files = [f for f in files if str(tmp_path) in str(f)]
        assert len(project_files) == 0

    def test_finds_project_toml(self, tmp_path: Path) -> None:
        (tmp_path / "codelab.toml").write_text("")
        files = _find_toml_chain(tmp_path)
        project_files = [f for f in files if str(tmp_path) in str(f)]
        assert len(project_files) == 1
        assert project_files[0].name == "codelab.toml"

    def test_finds_local_override(self, tmp_path: Path) -> None:
        (tmp_path / "codelab.toml").write_text("")
        (tmp_path / "codelab.local.toml").write_text("")
        files = _find_toml_chain(tmp_path)
        project_files = [f for f in files if str(tmp_path) in str(f)]
        assert len(project_files) == 2
        assert project_files[0].name == "codelab.toml"
        assert project_files[1].name == "codelab.local.toml"

    def test_order_codelab_before_local(self, tmp_path: Path) -> None:
        (tmp_path / "codelab.local.toml").write_text("")
        (tmp_path / "codelab.toml").write_text("")
        files = _find_toml_chain(tmp_path)
        project_files = [f for f in files if str(tmp_path) in str(f)]
        # codelab.toml должен идти перед codelab.local.toml
        assert project_files[0].name == "codelab.toml"
        assert project_files[1].name == "codelab.local.toml"


# ===========================================================================
# MCPConfigLoader integration
# ===========================================================================


class TestMCPConfigLoader:
    """Integration tests for MCPConfigLoader class."""

    def test_load_servers_from_single_toml(self, tmp_path: Path) -> None:
        toml = tmp_path / "codelab.toml"
        toml.write_text(
            """
[[mcp.servers]]
name = "filesystem"
type = "stdio"
command = "npx"
args = ["-y", "server"]
"""
        )
        loader = MCPConfigLoader(cwd=tmp_path)
        servers = loader.load_mcp_servers()
        assert len(servers) == 1
        assert servers[0]["name"] == "filesystem"

    def test_env_var_expansion_in_loader(self, tmp_path: Path) -> None:
        toml = tmp_path / "codelab.toml"
        toml.write_text(
            """
[[mcp.servers]]
name = "test"
type = "stdio"
command = "${MY_COMMAND}"
"""
        )
        with patch.dict(os.environ, {"MY_COMMAND": "python3"}):
            loader = MCPConfigLoader(cwd=tmp_path)
            servers = loader.load_mcp_servers()
            assert len(servers) == 1
            assert servers[0]["command"] == "python3"

    def test_invalid_server_skipped(self, tmp_path: Path) -> None:
        toml = tmp_path / "codelab.toml"
        toml.write_text(
            """
[[mcp.servers]]
name = "valid"
command = "npx"

[[mcp.servers]]
command = "npx"
"""
        )
        loader = MCPConfigLoader(cwd=tmp_path)
        servers = loader.load_mcp_servers()
        assert len(servers) == 1
        assert servers[0]["name"] == "valid"

    def test_empty_result_when_no_toml(self, tmp_path: Path) -> None:
        loader = MCPConfigLoader(cwd=tmp_path)
        servers = loader.load_mcp_servers()
        assert servers == []

    def test_toml_chain_merge(self, tmp_path: Path) -> None:
        # Основной конфиг
        (tmp_path / "codelab.toml").write_text(
            """
[[mcp.servers]]
name = "fs"
command = "old_cmd"

[[mcp.servers]]
name = "db"
command = "db_cmd"
"""
        )
        # Local override
        (tmp_path / "codelab.local.toml").write_text(
            """
[[mcp.servers]]
name = "fs"
command = "new_cmd"
"""
        )
        loader = MCPConfigLoader(cwd=tmp_path)
        servers = loader.load_mcp_servers()
        by_name = {s["name"]: s for s in servers}
        assert by_name["fs"]["command"] == "new_cmd"
        assert by_name["db"]["command"] == "db_cmd"

    def test_missing_env_var_replaced_with_empty(self, tmp_path: Path) -> None:
        toml = tmp_path / "codelab.toml"
        toml.write_text(
            """
[[mcp.servers]]
name = "test"
type = "http"
url = "https://${UNDEFINED_VAR_XYZ_123}/mcp"
"""
        )
        # Убедимся что переменная не установлена
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("UNDEFINED_VAR_XYZ_123", None)
            loader = MCPConfigLoader(cwd=tmp_path)
            servers = loader.load_mcp_servers()
            assert len(servers) == 1
            # URL должен содержать пустую строку вместо переменной
            assert servers[0]["url"] == "https:///mcp"
